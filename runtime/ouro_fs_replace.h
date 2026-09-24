/* Host filesystem adapter for Ouro's source publication transaction.
   The caller owns distinct source/stage/empty-backup files on one volume.
   All recovery policy remains in Ouro. No copy/delete fallback for publication. */
#ifndef OURO_FS_REPLACE_H
#define OURO_FS_REPLACE_H

#ifdef _WIN32
static DWORD source_replace_failure(void)
{
	DWORD status = GetLastError();
	return status == ERROR_SUCCESS ? ERROR_GEN_FAILURE : status;
}

static DWORD source_replace_info(const wchar_t *path, BY_HANDLE_FILE_INFORMATION *info, int flush)
{
	DWORD status = ERROR_SUCCESS;
	HANDLE file = CreateFileW(path, flush ? GENERIC_WRITE : 0,
		FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
		FILE_FLAG_OPEN_REPARSE_POINT, NULL);
	if (file == INVALID_HANDLE_VALUE)
		return source_replace_failure();
	if (!GetFileInformationByHandle(file, info) || (flush && !FlushFileBuffers(file)))
		status = source_replace_failure();
	if (!CloseHandle(file) && status == ERROR_SUCCESS)
		status = source_replace_failure();
	return status;
}

static int source_replace_same(const BY_HANDLE_FILE_INFORMATION *left, const BY_HANDLE_FILE_INFORMATION *right)
{
	return left->dwVolumeSerialNumber == right->dwVolumeSerialNumber &&
		left->nFileIndexHigh == right->nFileIndexHigh && left->nFileIndexLow == right->nFileIndexLow;
}

static DWORD source_security_owner_equal(const wchar_t *source, const wchar_t *stage)
{
	union { uint64_t align; BYTE bytes[256]; } left, right;
	DWORD needed;
	PSID a, b;
	BOOL defaulted;
	if (!GetFileSecurityW(source, OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION,
	    left.bytes, sizeof left.bytes, &needed) ||
	    !GetFileSecurityW(stage, OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION,
	    right.bytes, sizeof right.bytes, &needed))
		return source_replace_failure();
	if (!GetSecurityDescriptorOwner(left.bytes, &a, &defaulted) ||
	    !GetSecurityDescriptorOwner(right.bytes, &b, &defaulted))
		return source_replace_failure();
	if (a == NULL || b == NULL || !EqualSid(a, b))
		return ERROR_ACCESS_DENIED;
	if (!GetSecurityDescriptorGroup(left.bytes, &a, &defaulted) ||
	    !GetSecurityDescriptorGroup(right.bytes, &b, &defaulted))
		return source_replace_failure();
	return a != NULL && b != NULL && EqualSid(a, b) ? ERROR_SUCCESS : ERROR_ACCESS_DENIED;
}

static DWORD source_replace_windows(const wchar_t *source, const wchar_t *stage, const wchar_t *backup)
{
	const DWORD supported = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM |
		FILE_ATTRIBUTE_ARCHIVE | FILE_ATTRIBUTE_NORMAL | FILE_ATTRIBUTE_TEMPORARY |
		FILE_ATTRIBUTE_NOT_CONTENT_INDEXED;
	const wchar_t *paths[3] = {source, stage, backup};
	DWORD attributes[3], status;
	BY_HANDLE_FILE_INFORMATION info[3];
	size_t index;
	for (index = 0; index < 3; index++) {
		attributes[index] = GetFileAttributesW(paths[index]);
		if (attributes[index] == INVALID_FILE_ATTRIBUTES)
			return source_replace_failure();
		if (attributes[index] & ~supported)
			return ERROR_INVALID_PARAMETER;
	}
	for (index = 0; index < 3; index++) {
		status = source_replace_info(paths[index], &info[index], index == 1);
		if (status != ERROR_SUCCESS)
			return status;
		if (info[index].nNumberOfLinks != 1 || info[index].dwFileAttributes & ~supported)
			return ERROR_INVALID_PARAMETER;
	}
	if (info[2].nFileSizeHigh != 0 || info[2].nFileSizeLow != 0 ||
	    info[0].dwVolumeSerialNumber != info[1].dwVolumeSerialNumber ||
	    info[0].dwVolumeSerialNumber != info[2].dwVolumeSerialNumber ||
	    source_replace_same(&info[0], &info[1]) || source_replace_same(&info[0], &info[2]) ||
	    source_replace_same(&info[1], &info[2]))
		return ERROR_INVALID_PARAMETER;
	status = source_security_owner_equal(source, stage);
	if (status != ERROR_SUCCESS)
		return status;
	if (!SetFileAttributesW(stage, attributes[0]))
		return source_replace_failure();
	/* In particular, never set IGNORE_MERGE_ERRORS or IGNORE_ACL_ERRORS. */
	return ReplaceFileW(source, stage, backup, 0, NULL, NULL) ? ERROR_SUCCESS : source_replace_failure();
}
#else
#include <sys/types.h>
#if defined(__linux__) || defined(__APPLE__)
#include <sys/xattr.h>

static ssize_t source_xattr_list(int fd, char *names, size_t count)
{
#ifdef __APPLE__
	return flistxattr(fd, names, count, 0);
#else
	return flistxattr(fd, names, count);
#endif
}

static ssize_t source_xattr_get(int fd, const char *name, void *value, size_t count)
{
#ifdef __APPLE__
	return fgetxattr(fd, name, value, count, 0, 0);
#else
	return fgetxattr(fd, name, value, count);
#endif
}

static int source_xattr_set(int fd, const char *name, const void *value, size_t count)
{
#ifdef __APPLE__
	return fsetxattr(fd, name, value, count, 0, 0);
#else
	return fsetxattr(fd, name, value, count, 0);
#endif
}

static int source_xattr_remove(int fd, const char *name)
{
#ifdef __APPLE__
	return fremovexattr(fd, name, 0);
#else
	return fremovexattr(fd, name);
#endif
}

/* A newly created stage may inherit metadata absent from the original. Do
   not accidentally publish such additional ACLs or security attributes. */
static int source_xattrs_prune(int source, int stage)
{
	ssize_t length = source_xattr_list(stage, NULL, 0), got;
	char *names;
	size_t offset;
	int status = 0;
	if (length < 0)
		return errno == ENOTSUP ? 0 : errno;
	if (length == 0)
		return 0;
	if (length > 1024 * 1024)
		return E2BIG;
	names = (char *)malloc((size_t)length);
	if (names == NULL)
		return ENOMEM;
	got = source_xattr_list(stage, names, (size_t)length);
	if (got != length) { status = got < 0 ? errno : EAGAIN; goto done; }
	for (offset = 0; offset < (size_t)length;) {
		const char *name = names + offset;
		const char *end = (const char *)memchr(name, 0, (size_t)length - offset);
		if (end == NULL || end == name) { status = EINVAL; break; }
		offset += (size_t)(end - name) + 1;
		if (source_xattr_get(source, name, NULL, 0) >= 0)
			continue;
#ifdef __APPLE__
		if (errno != ENOATTR) { status = errno; break; }
#else
		if (errno != ENODATA) { status = errno; break; }
#endif
		if (source_xattr_remove(stage, name) != 0) { status = errno; break; }
	}
done:
	free(names);
	return status;
}

/* Bound metadata allocations independently of source size. Every xattr,
   including ACL/security metadata, must copy successfully or publication stops. */
static int source_xattrs_copy(int source, int stage)
{
	ssize_t length = source_xattr_list(source, NULL, 0), got;
	char *names = NULL;
	size_t offset;
	int status = 0;
	if (length < 0)
		return errno == ENOTSUP ? 0 : errno;
	if (length == 0)
		return 0;
	if (length > 1024 * 1024)
		return E2BIG;
	names = (char *)malloc((size_t)length);
	if (names == NULL)
		return ENOMEM;
	got = source_xattr_list(source, names, (size_t)length);
	if (got != length) {
		status = got < 0 ? errno : EAGAIN;
		goto done;
	}
	for (offset = 0; offset < (size_t)length;) {
		const char *name = names + offset;
		const char *end = (const char *)memchr(name, 0, (size_t)length - offset);
		void *value;
		ssize_t size;
		if (end == NULL || end == name) { status = EINVAL; break; }
		offset += (size_t)(end - name) + 1;
		size = source_xattr_get(source, name, NULL, 0);
		if (size < 0) { status = errno; break; }
		if (size > 1024 * 1024) { status = E2BIG; break; }
		value = malloc(size == 0 ? 1 : (size_t)size);
		if (value == NULL) { status = ENOMEM; break; }
		got = source_xattr_get(source, name, value, (size_t)size);
		if (got != size)
			status = got < 0 ? errno : EAGAIN;
		else if (source_xattr_set(stage, name, value, (size_t)size) != 0)
			status = errno;
		free(value);
		if (status != 0)
			break;
	}
done:
	free(names);
	return status;
}
#endif

static unsigned long source_replace_posix(const char *source, const char *stage, const char *backup)
{
#if (defined(__linux__) || defined(__APPLE__)) && defined(O_NOFOLLOW)
	struct stat original, candidate, saved, current;
	int source_fd = -1, stage_fd = -1, status = 0;
	if (lstat(source, &original) != 0 || lstat(stage, &candidate) != 0 || lstat(backup, &saved) != 0)
		return (unsigned long)errno;
	if (!S_ISREG(original.st_mode) || !S_ISREG(candidate.st_mode) || !S_ISREG(saved.st_mode) ||
	    original.st_nlink != 1 || candidate.st_nlink != 1 || saved.st_nlink != 1 || saved.st_size != 0 ||
	    original.st_dev != candidate.st_dev || original.st_dev != saved.st_dev ||
	    original.st_ino == candidate.st_ino || original.st_ino == saved.st_ino || candidate.st_ino == saved.st_ino)
		return EINVAL;
	source_fd = open(source, O_RDWR | O_NOFOLLOW);
	if (source_fd < 0)
		return (unsigned long)errno;
	stage_fd = open(stage, O_RDWR | O_NOFOLLOW);
	if (stage_fd < 0) { status = errno; goto done; }
	if (fstat(source_fd, &current) != 0) { status = errno; goto done; }
	if (current.st_dev != original.st_dev || current.st_ino != original.st_ino) { status = EAGAIN; goto done; }
	if (fstat(stage_fd, &current) != 0) { status = errno; goto done; }
	if (current.st_dev != candidate.st_dev || current.st_ino != candidate.st_ino) { status = EAGAIN; goto done; }
	if ((candidate.st_uid != original.st_uid || candidate.st_gid != original.st_gid) &&
	    fchown(stage_fd, original.st_uid, original.st_gid) != 0) { status = errno; goto done; }
	if (fchmod(stage_fd, original.st_mode & 07777) != 0) { status = errno; goto done; }
	status = source_xattrs_prune(source_fd, stage_fd);
	if (status != 0)
		goto done;
	status = source_xattrs_copy(source_fd, stage_fd);
	if (status != 0)
		goto done;
	if (fstat(stage_fd, &current) != 0) { status = errno; goto done; }
	if ((current.st_mode & 07777) != (original.st_mode & 07777) ||
	    current.st_uid != original.st_uid || current.st_gid != original.st_gid) { status = EAGAIN; goto done; }
#ifdef __APPLE__
	if (current.st_flags != original.st_flags) { status = ENOTSUP; goto done; }
#endif
	if (fsync(stage_fd) != 0) { status = errno; goto done; }
	/* Close errors are precommit errors. Never report an ordinary failure
	   after rename has already installed the candidate. */
	if (close(stage_fd) != 0) { stage_fd = -1; status = errno; goto done; }
	stage_fd = -1;
	if (close(source_fd) != 0) { source_fd = -1; status = errno; goto done; }
	source_fd = -1;
	if (lstat(source, &current) != 0) { status = errno; goto done; }
	if (current.st_dev != original.st_dev || current.st_ino != original.st_ino || current.st_nlink != 1) {
		status = EAGAIN;
		goto done;
	}
	/* The empty private reservation is consumed only to create a hard-link
	   recovery name. Failure leaves the original source path unchanged. */
	if (unlink(backup) != 0 || link(source, backup) != 0) { status = errno; goto done; }
	if (rename(stage, source) != 0)
		status = errno;
done:
	if (stage_fd >= 0 && close(stage_fd) != 0 && status == 0)
		status = errno;
	if (source_fd >= 0 && close(source_fd) != 0 && status == 0)
		status = errno;
	return (unsigned long)status;
#else
	(void)source;
	(void)stage;
	(void)backup;
	return ENOTSUP;
#endif
}
#endif

static ouro_v *fs_replace_run(ouro_env *env, ouro_v *unit)
{
	char *source = NULL, *stage = NULL, *backup = NULL;
	unsigned long status;
#ifdef _WIN32
	wchar_t *wide_source = NULL, *wide_stage = NULL, *wide_backup = NULL;
#endif
	(void)unit;
	sandbox_die("fs_replace_file");
	source = rename_path_text(env->next->next->v);
	if (source != NULL)
		stage = rename_path_text(env->next->v);
	if (stage != NULL)
		backup = rename_path_text(env->v);
	if (source == NULL || stage == NULL || backup == NULL) {
#ifdef _WIN32
		status = errno == ENOMEM ? ERROR_NOT_ENOUGH_MEMORY : ERROR_INVALID_PARAMETER;
#else
		status = (unsigned long)errno;
#endif
	} else {
#ifdef _WIN32
		status = ouro_host_wide_path(source, &wide_source);
		if (status == ERROR_SUCCESS)
			status = ouro_host_wide_path(stage, &wide_stage);
		if (status == ERROR_SUCCESS)
			status = ouro_host_wide_path(backup, &wide_backup);
		if (status == ERROR_SUCCESS)
			status = source_replace_windows(wide_source, wide_stage, wide_backup);
#else
		status = source_replace_posix(source, stage, backup);
#endif
	}
#ifdef _WIN32
	free(wide_backup);
	free(wide_stage);
	free(wide_source);
#endif
	free(backup);
	free(stage);
	free(source);
	return ouro_nat(status);
}

static ouro_v *f_fs_replace_backup(ouro_env *env, ouro_v *backup)
{
	return thunk(fs_replace_run, ouro_cons(backup, env));
}

static ouro_v *f_fs_replace_stage(ouro_env *env, ouro_v *stage)
{
	return ouro_clos(f_fs_replace_backup, ouro_cons(stage, env));
}

static ouro_v *f_fs_replace(ouro_env *env, ouro_v *source)
{
	(void)env;
	return ouro_clos(f_fs_replace_stage, ouro_cons(source, NULL));
}
#endif
