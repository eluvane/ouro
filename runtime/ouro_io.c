/* Host implementation of std/runtime.ouro prims; compiler algorithms must not live here.
   IO a is represented as a thunk: a closure applied to Unit. */
#define _POSIX_C_SOURCE 200809L
#define _XOPEN_SOURCE 700
#ifdef __APPLE__
/* Darwin keeps O_NOFOLLOW behind its extended interface feature macro. */
#define _DARWIN_C_SOURCE 1
#endif
#include "ouro_rt.h"
#include "ouro_io.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#ifdef _WIN32
#include <io.h>
#include <process.h>
#include <windows.h>
#else
#include <sys/wait.h>
#include <unistd.h>
#endif

#ifdef _WIN32
static void slash_path(char *p)
{
	ouro_slash_path(p);
}

static int file_exists(const char *path)
{
	FILE *f;

	if (path == 0 || path[0] == 0)
		return 0;
	f = fopen(path, "rb");
	if (f == 0)
		return 0;
	fclose(f);
	return 1;
}

/* PE system() is cmd.exe and cannot parse POSIX quotes. Tools and the
   runtime_io suite need a real sh (Git for Windows). OURO_POSIX_SH wins. */
static const char *find_posix_sh(void)
{
	static char found[512];
	static const char *const well_known[] = {
		"C:/Program Files/Git/bin/sh.exe",
		"C:/Program Files/Git/usr/bin/sh.exe",
		"C:/Program Files (x86)/Git/bin/sh.exe",
		"C:/Program Files (x86)/Git/usr/bin/sh.exe",
		0
	};
	const char *env;
	const char *p;
	size_t i;

	env = getenv("OURO_POSIX_SH");
	if (env != 0 && file_exists(env))
		return env;
	for (i = 0; well_known[i] != 0; i++) {
		if (file_exists(well_known[i]))
			return well_known[i];
	}
	env = getenv("PATH");
	if (env == 0)
		return 0;
	p = env;
	while (*p != 0) {
		const char *semi = strchr(p, ';');
		size_t n = semi != 0 ? (size_t)(semi - p) : strlen(p);

		if (n > 0 && n + 8 < sizeof found) {
			memcpy(found, p, n);
			found[n] = 0;
			slash_path(found);
			if (n > 0 && found[n - 1] != '/')
				snprintf(found + n, sizeof found - n, "/sh.exe");
			else
				snprintf(found + n, sizeof found - n, "sh.exe");
			if (file_exists(found))
				return found;
		}
		if (semi == 0)
			break;
		p = semi + 1;
	}
	return 0;
}

static void win_slashes(char *p)
{
	for (; p != 0 && *p != 0; p++) {
		if (*p == '/')
			*p = '\\';
	}
}

static int system_posix(const char *line, const char *script_path)
{
	const char *sh = find_posix_sh();
	FILE *f;
	char sh_win[512];
	char script_win[4096];
	char cmdline[8192];
	STARTUPINFOA si;
	PROCESS_INFORMATION pi;
	DWORD code = 127;

	if (sh == 0)
		return -1;
	f = fopen(script_path, "wb");
	if (f == 0)
		return -1;
	fputs(line, f);
	fputc('\n', f);
	fclose(f);
	snprintf(sh_win, sizeof sh_win, "%s", sh);
	snprintf(script_win, sizeof script_win, "%s", script_path);
	win_slashes(sh_win);
	win_slashes(script_win);
	if (snprintf(cmdline, sizeof cmdline, "\"%s\" \"%s\"", sh_win,
		    script_win) < 0) {
		remove(script_path);
		return -1;
	}
	ZeroMemory(&si, sizeof si);
	si.cb = sizeof si;
	ZeroMemory(&pi, sizeof pi);
	if (!CreateProcessA(sh_win, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW,
		NULL, NULL, &si, &pi)) {
		remove(script_path);
		return -1;
	}
	WaitForSingleObject(pi.hProcess, INFINITE);
	GetExitCodeProcess(pi.hProcess, &code);
	CloseHandle(pi.hProcess);
	CloseHandle(pi.hThread);
	remove(script_path);
	return (int)code;
}

#endif

static char **io_argv;
static int io_argc;
static int io_sandbox;
static int io_exit_status;

int ouro_io_exit_status(void)
{
	return io_exit_status;
}

void ouro_io_set_argv(int argc, char **argv)
{
#ifdef _WIN32
	/* LSP/JSON-RPC frames are byte-exact (`\r\n\r\n` + Content-Length).
	   Windows text-mode stdin strips CR so the header never ends and
	   the server exits 1 with an empty reply. */
	_setmode(_fileno(stdin), _O_BINARY);
	_setmode(_fileno(stdout), _O_BINARY);
	_setmode(_fileno(stderr), _O_BINARY);
#endif
	io_argc = argc;
	io_argv = argv;
}

void ouro_io_set_sandbox(int on)
{
	io_sandbox = on;
}

static ouro_v *v_unit(void)
{
	return ouro_ctor(0, 0, 0);
}

/* std/prelude.ouro: inductive Bool := True | False, so True is tag 0. */
static ouro_v *v_true(void)
{
	return ouro_ctor(0, 0, 0);
}

static ouro_v *v_false(void)
{
	return ouro_ctor(1, 0, 0);
}

static ouro_v *v_bool(int ok)
{
	return ok ? v_true() : v_false();
}

static ouro_v *v_nothing(void)
{
	return ouro_ctor(0, 0, 0);
}

static ouro_v *v_just(ouro_v *x)
{
	ouro_v *f[1];
	f[0] = x;
	return ouro_ctor(1, 1, f);
}

/* Nat is either a Peano chain of S cells or one packed cell the runtime
   folds S/Z over (ouro_rt.c ouro_nat / ouro_case). */
static unsigned long nat_u(ouro_v *v)
{
	unsigned long n = 0;
	if (v != 0 && v->tag == OURO_TAG_NAT && v->n >= 0)
		return (unsigned long)v->n;
	if (v != 0 && !ouro_nat_to_ulong(v, &n)) {
		fputs("ouro run: Nat does not fit the host operation\n", stderr);
		exit(70);
	}
	return n;
}

static char *codes_to_cstr(ouro_v *xs, unsigned long *len_out);

static char *cstr_of(ouro_v *v)
{
	if (v != 0 && v->tag == OURO_TAG_STR && v->u.s != 0)
		return strdup(v->u.s);
	if (v != 0 && v->tag == OURO_TAG_BYTES && v->u.s != 0) {
		char *p = (char *)malloc((unsigned long)v->n + 1UL);
		if (p == 0)
			return 0;
		memcpy(p, v->u.s, (unsigned long)v->n);
		p[v->n] = 0;
		return p;
	}
	/* Concat nodes and plain code lists: flatten. A String produced by
	   Ouro code can be any of these shapes. */
	if (v != 0 && (v->tag == OURO_TAG_CAT || (v->tag == 1 && v->n == 2)))
		return codes_to_cstr(v, 0);
	return strdup("");
}

static ouro_v *owned_str(const char *s)
{
	unsigned long n;
	char *p;
	if (s == 0)
		s = "";
	n = (unsigned long)strlen(s);
	p = (char *)ouro_alloc(n + 1UL);
	memcpy(p, s, n + 1UL);
	return ouro_str(p);
}

/* Temporary C adapter: length-based bytes for the producer until the C
   runtime is removed. strlen/fputs cannot emit PE (interior NULs). */
static int write_value_bytes(FILE *f, ouro_v *v)
{
	unsigned long len = 0;
	char *owned = 0;
	const char *data = 0;
	size_t wrote;

	if (v != 0 && (v->tag == OURO_TAG_STR || v->tag == OURO_TAG_BYTES) &&
	    v->u.s != 0 && v->n >= 0) {
		data = v->u.s;
		len = (unsigned long)v->n;
	} else {
		owned = codes_to_cstr(v, &len);
		data = owned;
	}
	if (data == 0) {
		free(owned);
		return -1;
	}
	wrote = fwrite(data, 1, (size_t)len, f);
	free(owned);
	return wrote == (size_t)len ? 0 : -1;
}

/* List Nat (cons cells, packed chunks, or concat nodes) into one buffer.
   String is a byte string, so a code list round-trips through this. */
static char *codes_to_cstr(ouro_v *xs, unsigned long *len_out)
{
	unsigned long cap = 128;
	unsigned long n = 0;
	char *buf = (char *)malloc(cap);
	ouro_v *stack[128];
	int sp = 0;
	if (buf == 0)
		return 0;
	for (;;) {
		if (xs == 0 || (xs->tag == 0 && xs->n == 0) ||
		    (xs->tag == OURO_TAG_NAT && xs->n == 0) ||
		    (xs->tag == OURO_TAG_BYTES && xs->n == 0) ||
		    (xs->tag == OURO_TAG_STR && (xs->u.s == 0 || xs->u.s[0] == 0))) {
			if (sp == 0)
				break;
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == OURO_TAG_CAT && xs->n == 2) {
			if (sp < 127)
				stack[sp++] = OURO_F(xs, 1);
			xs = OURO_F(xs, 0);
			continue;
		}
		if (xs->tag == OURO_TAG_BYTES || xs->tag == OURO_TAG_STR) {
			unsigned long k = xs->tag == OURO_TAG_BYTES ?
						  (unsigned long)xs->n :
						  (unsigned long)strlen(xs->u.s);
			while (n + k + 1UL > cap) {
				char *grown;
				cap *= 2;
				grown = (char *)realloc(buf, cap);
				if (grown == 0) {
					free(buf);
					return 0;
				}
				buf = grown;
			}
			memcpy(buf + n, xs->u.s, (size_t)k);
			n += k;
			if (sp == 0)
				break;
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == 1 && xs->n == 2) {
			if (n + 2UL > cap) {
				char *grown;
				cap *= 2;
				grown = (char *)realloc(buf, cap);
				if (grown == 0) {
					free(buf);
					return 0;
				}
				buf = grown;
			}
			buf[n++] = (char)(ouro_nat_low32(OURO_F(xs, 0)) & 0xFFU);
			xs = OURO_F(xs, 1);
			continue;
		}
		break;
	}
	buf[n] = 0;
	if (len_out != 0)
		*len_out = n;
	return buf;
}

static ouro_v *list_cons_str(const char *s, ouro_v *tail)
{
	ouro_v *cell[2];
	cell[0] = owned_str(s);
	cell[1] = tail;
	return ouro_ctor(1, 2, cell);
}

static void sandbox_die(const char *op)
{
	if (io_sandbox) {
		fprintf(stderr, "OURO_SANDBOX: blocked %s\n", op);
		exit(1);
	}
}

static ouro_v *thunk(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env)
{
	return ouro_clos(fn, env);
}

static ouro_v *io_pure_x(ouro_env *env, ouro_v *u)
{
	(void)u;
	return env->v;
}

static ouro_v *f_io_pure(ouro_env *env, ouro_v *x)
{
	(void)env;
	return thunk(io_pure_x, ouro_cons(x, 0));
}

static ouro_v *io_bind_run(ouro_env *env, ouro_v *u)
{
	ouro_v *ma = ouro_get(env, 1);
	ouro_v *f = ouro_get(env, 0);
	ouro_v *a;
	ouro_v *kb;
	(void)u;
	a = ouro_apply(ma, v_unit());
	kb = ouro_apply(f, a);
	return ouro_apply(kb, v_unit());
}

static ouro_v *f_io_bind_f(ouro_env *env, ouro_v *f)
{
	return thunk(io_bind_run, ouro_cons(f, env));
}

static ouro_v *f_io_bind_ma(ouro_env *env, ouro_v *ma)
{
	(void)env;
	return ouro_clos(f_io_bind_f, ouro_cons(ma, 0));
}

/* Checked word construction for the raw Runtime operations used by the
   standard library. Words use packed cells; they are not Peano naturals. */
static ouro_v *word_from_nat(ouro_v *value, uint32_t limit)
{
	unsigned long count;
	if (!ouro_nat_to_ulong(value, &count) || count > limit)
		return v_nothing();
	return v_just(ouro_nat(count));
}

static ouro_v *f_u8_from_nat(ouro_env *env, ouro_v *value)
{
	(void)env;
	return word_from_nat(value, UINT8_MAX);
}

static ouro_v *f_u32_from_nat(ouro_env *env, ouro_v *value)
{
	(void)env;
	return word_from_nat(value, UINT32_MAX);
}

static unsigned long word8_value(ouro_v *value)
{
	if (value == 0 || value->tag != OURO_TAG_NAT ||
	    value->n < 0 || value->n > UINT8_MAX) {
		fputs("ouro run: invalid U8 runtime value\n", stderr);
		exit(70);
	}
	return (unsigned long)value->n;
}

static ouro_v *f_u8_sub_right(ouro_env *env, ouro_v *right)
{
	return ouro_nat((word8_value(env->v) - word8_value(right)) & UINT8_MAX);
}

static ouro_v *f_u8_sub(ouro_env *env, ouro_v *left)
{
	(void)env;
	return ouro_clos(f_u8_sub_right, ouro_cons(left, 0));
}

static ouro_v *runtime_loop_run(ouro_env *env, ouro_v *unit)
{
	ouro_v *state = ouro_get(env, 2);
	ouro_v *condition = ouro_get(env, 1);
	ouro_v *step = ouro_get(env, 0);
	(void)unit;
	for (;;) {
		ouro_v *test = ouro_apply(ouro_apply(condition, state), v_unit());
		if (word8_value(test) == 0)
			return state;
		state = ouro_apply(ouro_apply(step, state), v_unit());
	}
}

static ouro_v *f_runtime_loop_step(ouro_env *env, ouro_v *step)
{
	return thunk(runtime_loop_run, ouro_cons(step, env));
}

static ouro_v *f_runtime_loop_condition(ouro_env *env, ouro_v *condition)
{
	return ouro_clos(f_runtime_loop_step, ouro_cons(condition, env));
}

static ouro_v *f_runtime_loop(ouro_env *env, ouro_v *initial)
{
	(void)env;
	return ouro_clos(f_runtime_loop_condition, ouro_cons(initial, 0));
}

static ouro_v *stream_write_run(FILE *out, ouro_env *env, ouro_v *u)
{
	char *s = cstr_of(env->v);
	(void)u;
	if (s) {
		fputs(s, out);
		fflush(out);
		free(s);
	}
	return v_unit();
}

static ouro_v *stdout_run(ouro_env *env, ouro_v *u)
{
	return stream_write_run(stdout, env, u);
}

static ouro_v *f_stdout(ouro_env *env, ouro_v *s)
{
	(void)env;
	return thunk(stdout_run, ouro_cons(s, 0));
}

static ouro_v *stderr_run(ouro_env *env, ouro_v *u)
{
	return stream_write_run(stderr, env, u);
}

static ouro_v *f_stderr(ouro_env *env, ouro_v *s)
{
	(void)env;
	return thunk(stderr_run, ouro_cons(s, 0));
}

static ouro_v *stdin_run(ouro_env *env, ouro_v *u)
{
	char buf[8192];
	(void)env;
	(void)u;
	if (fgets(buf, (int)sizeof buf, stdin) == 0)
		return owned_str("");
	{
		size_t n = strlen(buf);
		if (n > 0 && buf[n - 1] == '\n')
			buf[n - 1] = 0;
	}
	return owned_str(buf);
}

static ouro_v *f_stdin(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	return stdin_run(0, 0);
}

static ouro_v *exit_run(ouro_env *env, ouro_v *u)
{
	(void)u;
	exit((int)nat_u(env->v));
	return v_unit();
}

static ouro_v *f_exit(ouro_env *env, ouro_v *code)
{
	(void)env;
	io_exit_status = (int)nat_u(code);
	return thunk(exit_run, ouro_cons(code, 0));
}

static ouro_v *argv_run(ouro_env *env, ouro_v *u)
{
	ouro_v *list = ouro_ctor(0, 0, 0);
	int i;
	(void)env;
	(void)u;
	for (i = io_argc - 1; i >= 0; i--)
		list = list_cons_str(io_argv[i], list);
	return list;
}

static ouro_v *f_argv(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	return argv_run(0, 0);
}

static ouro_v *env_run(ouro_env *env, ouro_v *u)
{
	char *name = cstr_of(env->v);
	const char *v;
	(void)u;
	if (name == 0)
		return v_nothing();
	v = getenv(name);
	free(name);
	if (v == 0)
		return v_nothing();
	return v_just(owned_str(v));
}

static ouro_v *f_env(ouro_env *env, ouro_v *name)
{
	(void)env;
	return thunk(env_run, ouro_cons(name, 0));
}

static ouro_v *read_fail(FILE *f, char *buf)
{
	free(buf);
	if (f)
		fclose(f);
	return owned_str("");
}

static ouro_v *fs_read_run(ouro_env *env, ouro_v *u)
{
	char *path;
	FILE *f;
	long len;
	char *buf;
	ouro_v *r;
	(void)u;
	sandbox_die("fs_read_file");
	path = cstr_of(env->v);
	if (path == 0)
		return owned_str("");
	f = fopen(path, "rb");
	free(path);
	if (f == 0)
		return owned_str("");
	if (fseek(f, 0L, SEEK_END) != 0 || (len = ftell(f)) < 0)
		return read_fail(f, 0);
	rewind(f);
	buf = (char *)malloc((unsigned long)len + 1UL);
	if (buf == 0)
		return read_fail(f, 0);
	if (len > 0 && fread(buf, 1, (unsigned long)len, f) != (unsigned long)len)
		return read_fail(f, buf);
	buf[len] = 0;
	fclose(f);
	r = ouro_packed((const unsigned char *)buf, (unsigned long)len);
	free(buf);
	return r;
}

static ouro_v *f_fs_read(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_read_run, ouro_cons(p, 0));
}

/* Scratch files may live below an untrusted workspace.  Open the final path
   without following a link so a write cannot be redirected outside it. */
static FILE *open_write_file(const char *path)
{
#ifdef _WIN32
	HANDLE h;
	FILE_ATTRIBUTE_TAG_INFO info;
	int fd;
	FILE *f;

	h = CreateFileA(path, GENERIC_WRITE, 0, NULL, OPEN_ALWAYS,
	    FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
	if (h == INVALID_HANDLE_VALUE)
		return 0;
	if (!GetFileInformationByHandleEx(h, FileAttributeTagInfo, &info,
	        sizeof info) || (info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
		CloseHandle(h);
		return 0;
	}
	if (SetFilePointer(h, 0, NULL, FILE_BEGIN) == INVALID_SET_FILE_POINTER &&
	    GetLastError() != NO_ERROR) {
		CloseHandle(h);
		return 0;
	}
	if (!SetEndOfFile(h)) {
		CloseHandle(h);
		return 0;
	}
	fd = _open_osfhandle((intptr_t)h, _O_WRONLY | _O_BINARY);
	if (fd < 0) {
		CloseHandle(h);
		return 0;
	}
	f = _fdopen(fd, "wb");
	if (f == 0)
		_close(fd);
	return f;
#else
	int fd;
	FILE *f;

	fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0666);
	if (fd < 0)
		return 0;
	f = fdopen(fd, "wb");
	if (f == 0)
		close(fd);
	return f;
#endif
}

static ouro_v *fs_write_run(ouro_env *env, ouro_v *u)
{
	char *path;
	FILE *f;
	(void)u;
	sandbox_die("fs_write_file");
	path = cstr_of(env->next->v);
	if (path != 0) {
		f = open_write_file(path);
		if (f != 0) {
			(void)write_value_bytes(f, env->v);
			fclose(f);
		}
	}
	free(path);
	return v_unit();
}

static ouro_v *f_fs_write_c(ouro_env *env, ouro_v *content)
{
	return thunk(fs_write_run, ouro_cons(content, env));
}

static ouro_v *f_fs_write_p(ouro_env *env, ouro_v *p)
{
	(void)env;
	return ouro_clos(f_fs_write_c, ouro_cons(p, 0));
}

static int path_stat(ouro_env *env, struct stat *st)
{
	char *path = cstr_of(env->v);
	int ok = path != 0 && stat(path, st) == 0;
	free(path);
	return ok;
}

static ouro_v *fs_exists_run(ouro_env *env, ouro_v *u)
{
	struct stat st;
	(void)u;
	sandbox_die("fs_exists");
	return v_bool(path_stat(env, &st));
}

static ouro_v *f_fs_exists(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_exists_run, ouro_cons(p, 0));
}

static ouro_v *fs_is_dir_run(ouro_env *env, ouro_v *u)
{
	struct stat st;
	(void)u;
	sandbox_die("fs_is_dir");
	return v_bool(path_stat(env, &st) && S_ISDIR(st.st_mode));
}

static ouro_v *f_fs_is_dir(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_is_dir_run, ouro_cons(p, 0));
}

/* No-follow path kind used by security-sensitive tree walkers.
   0 = missing/error, 1 = regular file, 2 = directory, 3 = link/reparse/other. */
static unsigned long path_kind(const char *path)
{
#ifdef _WIN32
	DWORD attrs;
	if (path == 0 || path[0] == 0)
		return 0UL;
	attrs = GetFileAttributesA(path);
	if (attrs == INVALID_FILE_ATTRIBUTES)
		return 0UL;
	if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
		return 3UL;
	if ((attrs & FILE_ATTRIBUTE_DIRECTORY) != 0)
		return 2UL;
	return 1UL;
#else
	struct stat st;
	if (path == 0 || path[0] == 0 || lstat(path, &st) != 0)
		return 0UL;
	if (S_ISREG(st.st_mode))
		return 1UL;
	if (S_ISDIR(st.st_mode))
		return 2UL;
	return 3UL;
#endif
}

static ouro_v *fs_kind_run(ouro_env *env, ouro_v *u)
{
	char *path;
	unsigned long kind;
	(void)u;
	sandbox_die("fs_kind");
	path = cstr_of(env->v);
	kind = path_kind(path);
	free(path);
	return ouro_nat(kind);
}

static ouro_v *f_fs_kind(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_kind_run, ouro_cons(p, 0));
}

static char *canonical_path(const char *path)
{
#ifdef _WIN32
	HANDLE h;
	DWORD need;
	char *raw;
	char *out;
	const char *start;
	if (path == 0 || path[0] == 0)
		return 0;
	h = CreateFileA(path, FILE_READ_ATTRIBUTES,
		FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
		OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
	if (h == INVALID_HANDLE_VALUE)
		return 0;
	need = GetFinalPathNameByHandleA(h, NULL, 0,
		FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
	if (need == 0) {
		CloseHandle(h);
		return 0;
	}
	raw = (char *)malloc((size_t)need + 1U);
	if (raw == 0) {
		CloseHandle(h);
		return 0;
	}
	if (GetFinalPathNameByHandleA(h, raw, need + 1U,
		    FILE_NAME_NORMALIZED | VOLUME_NAME_DOS) == 0) {
		free(raw);
		CloseHandle(h);
		return 0;
	}
	CloseHandle(h);
	start = raw;
	if (strncmp(raw, "\\\\?\\UNC\\", 8) == 0) {
		size_t n = strlen(raw + 8);
		out = (char *)malloc(n + 3U);
		if (out != 0) {
			out[0] = '/';
			out[1] = '/';
			memcpy(out + 2, raw + 8, n + 1U);
		}
		free(raw);
		if (out != 0)
			slash_path(out);
		return out;
	}
	if (strncmp(raw, "\\\\?\\", 4) == 0)
		start = raw + 4;
	out = _strdup(start);
	free(raw);
	if (out != 0)
		slash_path(out);
	return out;
#else
	if (path == 0 || path[0] == 0)
		return 0;
	return realpath(path, NULL);
#endif
}

static ouro_v *fs_realpath_run(ouro_env *env, ouro_v *u)
{
	char *path;
	char *resolved;
	ouro_v *result;
	(void)u;
	sandbox_die("fs_realpath");
	path = cstr_of(env->v);
	resolved = canonical_path(path);
	result = owned_str(resolved != 0 ? resolved : "");
	free(resolved);
	free(path);
	return result;
}

static ouro_v *f_fs_realpath(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_realpath_run, ouro_cons(p, 0));
}

static ouro_v *fs_list_run(ouro_env *env, ouro_v *u)
{
	char *path;
	DIR *d;
	struct dirent *e;
	ouro_v *list;
	(void)u;
	sandbox_die("fs_list_dir");
	path = cstr_of(env->v);
	list = ouro_ctor(0, 0, 0);
	if (path == 0)
		return list;
	d = opendir(path);
	free(path);
	if (d == 0)
		return list;
	while ((e = readdir(d)) != 0) {
		if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0)
			continue;
		list = list_cons_str(e->d_name, list);
	}
	closedir(d);
	return list;
}

static ouro_v *f_fs_list(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_list_run, ouro_cons(p, 0));
}

static ouro_v *fs_listable_run(ouro_env *env, ouro_v *u)
{
	char *path;
	DIR *dir;
	int ok = 0;
	(void)u;
	sandbox_die("fs_listable");
	path = cstr_of(env->v);
	if (path != 0) {
		dir = opendir(path);
		if (dir != 0) {
			ok = 1;
			closedir(dir);
		}
	}
	free(path);
	return v_bool(ok);
}

static ouro_v *f_fs_listable(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_listable_run, ouro_cons(p, 0));
}

static ouro_v *time_run(ouro_env *env, ouro_v *u)
{
	char buf[32];
	(void)env;
	(void)u;
	snprintf(buf, sizeof buf, "%ld000", (long)time(0));
	return owned_str(buf);
}

static ouro_v *f_time(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	return time_run(0, 0);
}

static ouro_v *str_concat(ouro_env *env, ouro_v *b)
{
	unsigned long an = 0;
	unsigned long bn = 0;
	char *as = codes_to_cstr(env->v, &an);
	char *bs = codes_to_cstr(b, &bn);
	char *out;
	ouro_v *r;
	if (as == 0 || bs == 0 || an > (unsigned long)INT_MAX ||
	    bn > (unsigned long)INT_MAX - an) {
		free(as);
		free(bs);
		fputs("ouro run: string concatenation exceeds host capacity\n", stderr);
		exit(70);
	}
	out = (char *)malloc(an + bn + 1UL);
	if (out == 0) {
		free(as);
		free(bs);
		fputs("ouro run: string concatenation allocation failed\n", stderr);
		exit(70);
	}
	memcpy(out, as, an);
	memcpy(out + an, bs, bn);
	r = ouro_packed((const unsigned char *)out, an + bn);
	free(out);
	free(as);
	free(bs);
	return r;
}

static ouro_v *f_str_concat(ouro_env *env, ouro_v *a)
{
	(void)env;
	return ouro_clos(str_concat, ouro_cons(a, 0));
}

static ouro_v *f_str_length(ouro_env *env, ouro_v *s)
{
	char *p;
	(void)env;
	if (s != 0 && s->tag == OURO_TAG_STR && s->u.s != 0 && s->n >= 0)
		return ouro_nat((unsigned long)s->n);
	if (s != 0 && s->tag == OURO_TAG_BYTES && s->u.s != 0 && s->n >= 0)
		return ouro_nat((unsigned long)s->n);
	p = cstr_of(s);
	if (p == 0)
		return ouro_nat(0);
	{
		unsigned long n = (unsigned long)strlen(p);
		free(p);
		return ouro_nat(n);
	}
}

static ouro_v *str_byte_at_run(ouro_env *env, ouro_v *index_v)
{
	ouro_v *value_v = env->v;
	unsigned long index = nat_u(index_v);
	unsigned long value = 0UL;
	char *s;
	if (value_v != 0 &&
	    (value_v->tag == OURO_TAG_STR || value_v->tag == OURO_TAG_BYTES) &&
	    value_v->u.s != 0 && value_v->n >= 0) {
		if (index < (unsigned long)value_v->n)
			value = (unsigned long)(unsigned char)value_v->u.s[index];
		return ouro_nat(value);
	}
	/* Ouro concatenation/list strings are flattened only for this fallback.
	   parse_json compacts its input once, so its hot cursor stays above. */
	s = cstr_of(value_v);
	if (s != 0 && index < (unsigned long)strlen(s))
		value = (unsigned long)(unsigned char)s[index];
	free(s);
	return ouro_nat(value);
}

static ouro_v *f_str_byte_at(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_byte_at_run, ouro_cons(s, 0));
}

/* JSON strings are the one potentially huge recursive leaf in the Ouro
   parser. Decode that leaf in one bounded host loop; arrays/objects retain the
   Ouro depth and fuel checks. The returned Pair is (Maybe String, next byte). */
static ouro_v *json_string_parse_run(ouro_env *env, ouro_v *index_v)
{
	ouro_v *value_v = env->v;
	char *owned = 0;
	const unsigned char *s;
	unsigned long len;
	unsigned long i = nat_u(index_v);
	unsigned long failure = i;
	unsigned char *out = 0;
	unsigned long used = 0;
	ouro_v *fields[2];
	int ok = 0;

	if (value_v != 0 &&
	    (value_v->tag == OURO_TAG_STR || value_v->tag == OURO_TAG_BYTES) &&
	    value_v->u.s != 0 && value_v->n >= 0) {
		s = (const unsigned char *)value_v->u.s;
		len = (unsigned long)value_v->n;
	} else {
		owned = cstr_of(value_v);
		if (owned == 0) {
			fields[0] = v_nothing();
			fields[1] = ouro_nat(i);
			return ouro_ctor(0, 2, fields);
		}
		s = (const unsigned char *)owned;
		len = (unsigned long)strlen(owned);
	}
	if (i >= len || s[i] != '"')
		goto done;
	i++;
	out = (unsigned char *)malloc(len - i + 1UL);
	if (out == 0)
		goto done;
	while (i < len) {
		unsigned char c = s[i++];
		failure = i - 1UL;
		if (c == '"') {
			ok = 1;
			failure = i;
			break;
		}
		if (c < 0x20U)
			goto done;
		if (c == '\\') {
			if (i >= len)
				goto done;
			failure = i;
			c = s[i++];
			switch (c) {
			case '"': case '\\': case '/': break;
			case 'b': c = 8U; break;
			case 'f': c = 12U; break;
			case 'n': c = 10U; break;
			case 'r': c = 13U; break;
			case 't': c = 9U; break;
			default: goto done;
			}
		}
		out[used++] = c;
	}
done:
	if (ok) {
		out[used] = 0;
		fields[0] = v_just(owned_str((const char *)out));
		fields[1] = ouro_nat(failure);
	} else {
		fields[0] = v_nothing();
		fields[1] = ouro_nat(failure);
	}
	free(out);
	free(owned);
	return ouro_ctor(0, 2, fields);
}

static ouro_v *f_json_string_parse(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(json_string_parse_run, ouro_cons(s, 0));
}

static ouro_v *f_str_eq_b(ouro_env *env, ouro_v *b)
{
	ouro_v *a = env->v;
	unsigned long an = 0;
	unsigned long bn = 0;
	char *as;
	char *bs;
	int eq;
	if (a != 0 && b != 0 && a->u.s != 0 && b->u.s != 0 &&
	    (a->tag == OURO_TAG_STR || a->tag == OURO_TAG_BYTES) &&
	    (b->tag == OURO_TAG_STR || b->tag == OURO_TAG_BYTES) &&
	    a->n >= 0 && b->n >= 0)
		return v_bool(a->n == b->n && memcmp(a->u.s, b->u.s, (size_t)a->n) == 0);
	as = codes_to_cstr(a, &an);
	bs = codes_to_cstr(b, &bn);
	eq = as != 0 && bs != 0 && an == bn && memcmp(as, bs, (size_t)an) == 0;
	free(as);
	free(bs);
	return v_bool(eq);
}

static ouro_v *f_str_eq(ouro_env *env, ouro_v *a)
{
	(void)env;
	return ouro_clos(f_str_eq_b, ouro_cons(a, 0));
}

static ouro_v *str_starts_run(ouro_env *env, ouro_v *pre_v)
{
	char *s = cstr_of(env->v);
	char *pre = cstr_of(pre_v);
	size_t s_len = s != 0 ? strlen(s) : 0;
	size_t pre_len = pre != 0 ? strlen(pre) : 0;
	int ok = s != 0 && pre != 0 && s_len >= pre_len &&
		 strncmp(s, pre, pre_len) == 0;
	free(s);
	free(pre);
	return v_bool(ok);
}

static ouro_v *f_str_starts(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_starts_run, ouro_cons(s, 0));
}

static ouro_v *str_ends_run(ouro_env *env, ouro_v *suf_v)
{
	char *s = cstr_of(env->v);
	char *suf = cstr_of(suf_v);
	size_t s_len = s != 0 ? strlen(s) : 0;
	size_t suf_len = suf != 0 ? strlen(suf) : 0;
	int ok = s != 0 && suf != 0 && s_len >= suf_len &&
		 memcmp(s + s_len - suf_len, suf, suf_len) == 0;
	free(s);
	free(suf);
	return v_bool(ok);
}

static ouro_v *f_str_ends(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_ends_run, ouro_cons(s, 0));
}

static ouro_v *str_contains_run(ouro_env *env, ouro_v *pat_v)
{
	unsigned long size = 0;
	unsigned long width = 0;
	unsigned long index;
	char *s = codes_to_cstr(env->v, &size);
	char *pat = codes_to_cstr(pat_v, &width);
	int ok = 0;
	if (s == 0 || pat == 0) {
		free(s);
		free(pat);
		fputs("ouro run: string search allocation failed\n", stderr);
		exit(70);
	}
	if (width == 0)
		ok = 1;
	else if (width <= size) {
		for (index = 0; index <= size - width; index++) {
			if (memcmp(s + index, pat, width) == 0) {
				ok = 1;
				break;
			}
		}
	}
	free(s);
	free(pat);
	return v_bool(ok);
}

static ouro_v *f_str_contains(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_contains_run, ouro_cons(s, 0));
}

static ouro_v *str_index_run(ouro_env *env, ouro_v *pat_v)
{
	char *s = cstr_of(env->v);
	char *pat = cstr_of(pat_v);
	char *found = s != 0 && pat != 0 ? strstr(s, pat) : 0;
	ouro_v *result = found != 0 ? v_just(ouro_nat((unsigned long)(found - s))) :
					 v_nothing();
	free(s);
	free(pat);
	return result;
}

static ouro_v *f_str_index(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_index_run, ouro_cons(s, 0));
}

static ouro_v *string_list_cons_slice(char *s, size_t start, size_t end,
				       ouro_v *tail)
{
	char saved = s[end];
	ouro_v *result;
	s[end] = 0;
	result = list_cons_str(s + start, tail);
	s[end] = saved;
	return result;
}

static ouro_v *str_split_run(ouro_env *env, ouro_v *sep_v)
{
	char *s = cstr_of(env->v);
	unsigned long sep = nat_u(sep_v);
	ouro_v *list = ouro_ctor(0, 0, 0);
	size_t end;
	size_t i;
	if (s == 0)
		return list_cons_str("", list);
	if (sep > 255UL) {
		list = list_cons_str(s, list);
		free(s);
		return list;
	}
	end = strlen(s);
	for (i = end; i > 0; i--) {
		if ((unsigned char)s[i - 1] == (unsigned char)sep) {
			list = string_list_cons_slice(s, i, end, list);
			end = i - 1;
		}
	}
	list = string_list_cons_slice(s, 0, end, list);
	free(s);
	return list;
}

static ouro_v *f_str_split(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(str_split_run, ouro_cons(s, 0));
}

static ouro_v *str_replace_run(ouro_env *env, ouro_v *rep_v)
{
	char *s = cstr_of(ouro_get(env, 1));
	char *pat = cstr_of(ouro_get(env, 0));
	char *rep = cstr_of(rep_v);
	size_t s_len;
	size_t pat_len;
	size_t rep_len;
	size_t count = 0;
	size_t out_len;
	char *scan;
	char *found;
	char *out;
	char *dst;
	ouro_v *result;
	if (s == 0 || pat == 0 || rep == 0 || pat[0] == 0) {
		result = owned_str(s != 0 ? s : "");
		free(s);
		free(pat);
		free(rep);
		return result;
	}
	s_len = strlen(s);
	pat_len = strlen(pat);
	rep_len = strlen(rep);
	for (scan = s; (found = strstr(scan, pat)) != 0; scan = found + pat_len)
		count++;
	if (rep_len >= pat_len) {
		size_t growth = rep_len - pat_len;
		if (growth != 0 && count > (SIZE_MAX - s_len - 1U) / growth) {
			free(s);
			free(pat);
			free(rep);
			return owned_str("");
		}
		out_len = s_len + count * growth;
	} else {
		out_len = s_len - count * (pat_len - rep_len);
	}
	out = (char *)malloc(out_len + 1U);
	if (out == 0) {
		free(s);
		free(pat);
		free(rep);
		return owned_str("");
	}
	dst = out;
	scan = s;
	while ((found = strstr(scan, pat)) != 0) {
		size_t prefix_len = (size_t)(found - scan);
		memcpy(dst, scan, prefix_len);
		dst += prefix_len;
		memcpy(dst, rep, rep_len);
		dst += rep_len;
		scan = found + pat_len;
	}
	memcpy(dst, scan, strlen(scan) + 1U);
	result = owned_str(out);
	free(out);
	free(s);
	free(pat);
	free(rep);
	return result;
}

static ouro_v *f_str_replace_pat(ouro_env *env, ouro_v *pat)
{
	return ouro_clos(str_replace_run, ouro_cons(pat, env));
}

static ouro_v *f_str_replace(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(f_str_replace_pat, ouro_cons(s, 0));
}

static ouro_v *str_le_run(ouro_env *env, ouro_v *b_v)
{
	char *a = cstr_of(env->v);
	char *b = cstr_of(b_v);
	int ok = a != 0 && b != 0 && strcmp(a, b) <= 0;
	free(a);
	free(b);
	return v_bool(ok);
}

static ouro_v *f_str_le(ouro_env *env, ouro_v *a)
{
	(void)env;
	return ouro_clos(str_le_run, ouro_cons(a, 0));
}

static int string_ws(unsigned char c)
{
	return c == 32U || c == 9U || c == 10U || c == 13U;
}

static ouro_v *f_str_tokens(ouro_env *env, ouro_v *s_v)
{
	char *s = cstr_of(s_v);
	ouro_v *list = ouro_ctor(0, 0, 0);
	size_t i;
	(void)env;
	if (s == 0)
		return list;
	i = strlen(s);
	while (i > 0) {
		size_t end;
		while (i > 0 && string_ws((unsigned char)s[i - 1]))
			i--;
		end = i;
		while (i > 0 && !string_ws((unsigned char)s[i - 1]))
			i--;
		if (end > i)
			list = string_list_cons_slice(s, i, end, list);
	}
	free(s);
	return list;
}

static ouro_v *str_slice_run(ouro_env *env, ouro_v *len_v)
{
	/* env = [start, s]; an overlong slice ends at the final byte. */
	unsigned long have = 0;
	char *s = codes_to_cstr(ouro_get(env, 1), &have);
	unsigned long start = nat_u(ouro_get(env, 0));
	unsigned long want = nat_u(len_v);
	ouro_v *r;
	if (s == 0) {
		fputs("ouro run: string slice allocation failed\n", stderr);
		exit(70);
	}
	if (start >= have) {
		free(s);
		return owned_str("");
	}
	if (want > have - start)
		want = have - start;
	r = ouro_packed((const unsigned char *)s + start, want);
	free(s);
	return r;
}

static ouro_v *f_str_slice_start(ouro_env *env, ouro_v *start)
{
	return ouro_clos(str_slice_run, ouro_cons(start, env));
}

static ouro_v *f_str_slice(ouro_env *env, ouro_v *s)
{
	(void)env;
	return ouro_clos(f_str_slice_start, ouro_cons(s, 0));
}

static ouro_v *f_str_of_nat(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_nat_decimal(n);
}

static ouro_v *f_str_to_codes(ouro_env *env, ouro_v *s)
{
	ouro_v *r;
	(void)env;
	if (s != 0 && (s->tag == OURO_TAG_STR || s->tag == OURO_TAG_BYTES) &&
	    s->u.s != 0 && s->n >= 0)
		return ouro_packed((const unsigned char *)s->u.s,
				   (unsigned long)s->n);
	{
		unsigned long len = 0;
		char *p = codes_to_cstr(s, &len);
		if (p == 0)
			return ouro_ctor(0, 0, 0);
		r = ouro_packed((const unsigned char *)p, len);
		free(p);
		return r;
	}
}

static ouro_v *f_str_of_codes(ouro_env *env, ouro_v *xs)
{
	unsigned long len = 0;
	char *p = codes_to_cstr(xs, &len);
	ouro_v *r;
	(void)env;
	if (p == 0)
		return ouro_packed((const unsigned char *)"", 0);
	r = ouro_packed((const unsigned char *)p, len);
	free(p);
	return r;
}

static int mkdir_one(const char *path)
{
#ifdef _WIN32
	return mkdir(path);
#else
	return mkdir(path, 0777);
#endif
}

/* mkdir -p: existing components are not an error. */
static void mkdir_p(const char *path)
{
	char buf[4096];
	size_t n = strlen(path);
	size_t i;
	if (n == 0 || n >= sizeof buf)
		return;
	memcpy(buf, path, n + 1);
	for (i = 1; i < n; i++) {
		if (buf[i] != '/' && buf[i] != '\\')
			continue;
		buf[i] = 0;
		mkdir_one(buf);
		buf[i] = path[i];
	}
	mkdir_one(buf);
}

static ouro_v *fs_mkdir_run(ouro_env *env, ouro_v *u)
{
	char *path;
	(void)u;
	sandbox_die("fs_mkdir");
	path = cstr_of(env->v);
	if (path != 0) {
		mkdir_p(path);
		free(path);
	}
	return v_unit();
}

static ouro_v *f_fs_mkdir(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_mkdir_run, ouro_cons(p, 0));
}

static ouro_v *fs_remove_run(ouro_env *env, ouro_v *u)
{
	char *path;
	(void)u;
	sandbox_die("fs_remove");
	path = cstr_of(env->v);
	if (path != 0) {
		if (remove(path) != 0)
			rmdir(path);
		free(path);
	}
	return v_unit();
}

static ouro_v *f_fs_remove(ouro_env *env, ouro_v *p)
{
	(void)env;
	return thunk(fs_remove_run, ouro_cons(p, 0));
}

static const char *host_temp_dir(void)
{
	const char *tmp = getenv("TMPDIR");
#ifdef _WIN32
	/* Git Bash exports TMPDIR=/tmp; native PE programs cannot use it. */
	if (tmp == 0 || tmp[0] == 0 || tmp[0] == '/')
		tmp = getenv("TMP");
	if (tmp == 0 || tmp[0] == 0 || tmp[0] == '/')
		tmp = getenv("TEMP");
	if (tmp == 0 || tmp[0] == 0 || tmp[0] == '/')
		tmp = ".";
#else
	if (tmp == 0 || tmp[0] == 0)
		tmp = getenv("TMP");
	if (tmp == 0 || tmp[0] == 0)
		tmp = getenv("TEMP");
	if (tmp == 0 || tmp[0] == 0)
		tmp = "/tmp";
#endif
	return tmp;
}

/* Create a private, previously nonexistent scratch file in an existing
   directory.  Its path is passed to a child tool, so the file remains named
   until the caller removes it. */
static char *create_private_temp_file_in(const char *tmp)
{
	char path[4096];
	if (tmp == 0 || tmp[0] == 0)
		return 0;
#ifdef _WIN32
	static LONG sequence;
	unsigned long attempt;
	for (attempt = 0; attempt < 256UL; attempt++) {
		LARGE_INTEGER ticks;
		HANDLE h;
		QueryPerformanceCounter(&ticks);
		snprintf(path, sizeof path, "%s/ouro_tmp_%lu_%lx_%lx",
			 tmp, (unsigned long)GetCurrentProcessId(),
			 (unsigned long)ticks.LowPart,
			 (unsigned long)InterlockedIncrement(&sequence));
		slash_path(path);
		h = CreateFileA(path, GENERIC_READ | GENERIC_WRITE, 0, NULL,
			CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY, NULL);
		if (h != INVALID_HANDLE_VALUE) {
			CloseHandle(h);
			return _strdup(path);
		}
		if (GetLastError() != ERROR_FILE_EXISTS &&
		    GetLastError() != ERROR_ALREADY_EXISTS)
			return 0;
	}
	return 0;
#else
	int fd;
	if (snprintf(path, sizeof path, "%s/ouro_tmp_XXXXXX", tmp) < 0 ||
	    strlen(path) >= sizeof path - 1U)
		return 0;
	fd = mkstemp(path);
	if (fd < 0)
		return 0;
	(void)fchmod(fd, 0600);
	close(fd);
	return strdup(path);
#endif
}

static char *create_private_temp_file(void)
{
	return create_private_temp_file_in(host_temp_dir());
}

static ouro_v *fs_temp_file_run(ouro_env *env, ouro_v *u)
{
	char *path;
	ouro_v *result;
	(void)env;
	(void)u;
	sandbox_die("fs_temp_file");
	path = create_private_temp_file();
	result = owned_str(path != 0 ? path : "");
	free(path);
	return result;
}

static ouro_v *f_fs_temp_file(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	return fs_temp_file_run(0, 0);
}

static ouro_v *fs_temp_file_in_run(ouro_env *env, ouro_v *u)
{
	char *dir = cstr_of(env->v);
	char *path;
	ouro_v *result;
	(void)u;
	sandbox_die("fs_temp_file_in");
	path = create_private_temp_file_in(dir);
	result = owned_str(path != 0 ? path : "");
	free(path);
	free(dir);
	return result;
}

static ouro_v *f_fs_temp_file_in(ouro_env *env, ouro_v *dir)
{
	(void)env;
	return thunk(fs_temp_file_in_run, ouro_cons(dir, 0));
}

static ouro_v *fs_copy_run(ouro_env *env, ouro_v *u)
{
	/* env = [dst, src] */
	char *dst = cstr_of(env->v);
	char *src = cstr_of(env->next->v);
	FILE *in;
	FILE *out;
	(void)u;
	sandbox_die("fs_copy_file");
	if (src != 0 && dst != 0) {
		in = fopen(src, "rb");
		if (in != 0) {
			out = fopen(dst, "wb");
			if (out != 0) {
				char buf[8192];
				size_t n;
				while ((n = fread(buf, 1, sizeof buf, in)) > 0)
					fwrite(buf, 1, n, out);
				fclose(out);
			}
			fclose(in);
		}
	}
	free(src);
	free(dst);
	return v_unit();
}

static ouro_v *f_fs_copy_dst(ouro_env *env, ouro_v *dst)
{
	return thunk(fs_copy_run, ouro_cons(dst, env));
}

static ouro_v *f_fs_copy(ouro_env *env, ouro_v *src)
{
	(void)env;
	return ouro_clos(f_fs_copy_dst, ouro_cons(src, 0));
}

/* Path-only validation before the legacy flattener: none of its packed,
   concat, or list chunks may hide a NUL or be silently truncated. */
static char *rename_path_text(ouro_v *value)
{
	ouro_v *original = value;
	ouro_v *pending[128];
	size_t depth = 0;
	size_t length = 0;
	char *text;
	errno = EINVAL;
	for (;;) {
		if (value == 0)
			return 0;
		if (value->tag == OURO_TAG_CAT && value->n == 2) {
			if (depth == sizeof pending / sizeof pending[0] - 1U)
				return 0;
			pending[depth++] = OURO_F(value, 1);
			value = OURO_F(value, 0);
			continue;
		}
		if (value->tag == OURO_TAG_STR || value->tag == OURO_TAG_BYTES) {
			if (value->n < 0 || (value->n != 0 && (value->u.s == 0 ||
			    memchr(value->u.s, 0, (size_t)value->n) != 0)))
				return 0;
			if ((size_t)value->n > (size_t)INT_MAX - 1U - length)
				return 0;
			length += (size_t)value->n;
		} else if (value->tag == 1 && value->n == 2) {
			unsigned long byte = nat_u(OURO_F(value, 0));
			if (byte == 0 || byte > 255UL || length == (size_t)INT_MAX - 1U)
				return 0;
			length++;
			value = OURO_F(value, 1);
			continue;
		} else if (value->tag != 0 || value->n != 0) {
			return 0;
		}
		if (depth == 0)
			break;
		value = pending[--depth];
	}
	if (length == 0)
		return 0;
	text = codes_to_cstr(original, 0);
	if (text == 0)
		errno = ENOMEM;
	return text;
}

#ifdef _WIN32
static DWORD rename_wide_path(const char *text, wchar_t **output)
{
	int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
	if (count == 0)
		return GetLastError();
	*output = (wchar_t *)malloc((size_t)count * sizeof **output);
	if (*output == 0)
		return ERROR_NOT_ENOUGH_MEMORY;
	if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, *output, count) == 0)
		return GetLastError();
	return ERROR_SUCCESS;
}
#endif

static ouro_v *fs_rename_run(ouro_env *env, ouro_v *unit)
{
	char *source = 0;
	char *target = 0;
	unsigned long status;
#ifdef _WIN32
	wchar_t *wide_source = 0;
	wchar_t *wide_target = 0;
#endif
	(void)unit;
	sandbox_die("fs_rename");
	source = rename_path_text(env->next->v);
	if (source != 0)
		target = rename_path_text(env->v);
	if (source == 0 || target == 0) {
#ifdef _WIN32
		status = errno == ENOMEM ? ERROR_NOT_ENOUGH_MEMORY : ERROR_INVALID_PARAMETER;
#else
		status = (unsigned long)errno;
#endif
	} else {
#ifdef _WIN32
		status = rename_wide_path(source, &wide_source);
		if (status == ERROR_SUCCESS)
			status = rename_wide_path(target, &wide_target);
		if (status == ERROR_SUCCESS &&
		    !MoveFileExW(wide_source, wide_target, MOVEFILE_REPLACE_EXISTING))
			status = GetLastError();
#else
		status = rename(source, target) == 0 ? 0UL : (unsigned long)errno;
#endif
	}
#ifdef _WIN32
	free(wide_target);
	free(wide_source);
#endif
	free(target);
	free(source);
	return ouro_nat(status);
}

static ouro_v *f_fs_rename_dst(ouro_env *env, ouro_v *dst)
{
	return thunk(fs_rename_run, ouro_cons(dst, env));
}

static ouro_v *f_fs_rename(ouro_env *env, ouro_v *src)
{
	(void)env;
	return ouro_clos(f_fs_rename_dst, ouro_cons(src, 0));
}

static ouro_v *stdin_bytes_run(ouro_env *env, ouro_v *u)
{
	unsigned long want = nat_u(env->v);
	char *buf;
	size_t got;
	ouro_v *r;
	(void)u;
	if (want == 0)
		return owned_str("");
	buf = (char *)malloc(want + 1UL);
	if (buf == 0)
		return owned_str("");
	got = fread(buf, 1, (size_t)want, stdin);
	buf[got] = 0;
	r = owned_str(buf);
	free(buf);
	return r;
}

static ouro_v *f_stdin_bytes(ouro_env *env, ouro_v *n)
{
	(void)env;
	return thunk(stdin_bytes_run, ouro_cons(n, 0));
}

static ouro_v *stdout_flush_run(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	fflush(stdout);
	return v_unit();
}

static ouro_v *f_stdout_flush(ouro_env *env, ouro_v *u)
{
	(void)env;
	(void)u;
	return stdout_flush_run(0, 0);
}

static char *copy_string(const char *s)
{
	size_t n;
	char *copy;
	if (s == 0)
		return 0;
	n = strlen(s);
	copy = (char *)malloc(n + 1U);
	if (copy != 0)
		memcpy(copy, s, n + 1U);
	return copy;
}

static char **proc_argv_of(char *cmd, ouro_v *args, size_t *argc_out)
{
	ouro_env *pending = 0;
	size_t capacity = 16;
	size_t i = 1;
	size_t j;
	char **argv;
	*argc_out = 0;
	if (cmd == 0)
		return 0;
	argv = (char **)calloc(capacity, sizeof *argv);
	if (argv == 0) {
		free(cmd);
		return 0;
	}
	argv[0] = cmd;
	/* append is represented by concat nodes for every List element type.
	   Traverse its complete spine before launching, including concat tails. */
	for (;;) {
		if (args == 0)
			goto fail;
		if (args->tag == OURO_TAG_CAT && args->n == 2) {
			ouro_env *node = (ouro_env *)malloc(sizeof *node);
			if (node == 0)
				goto fail;
			node->v = OURO_F(args, 1);
			node->next = pending;
			pending = node;
			args = OURO_F(args, 0);
			continue;
		}
		if (args->tag == 0 && args->n == 0) {
			ouro_env *node = pending;
			if (node == 0)
				break;
			args = node->v;
			pending = node->next;
			free(node);
			continue;
		}
		if (args->tag != 1 || args->n != 2)
			goto fail;
		if (i == capacity - 1U) {
			char **grown;
			if (capacity > SIZE_MAX / sizeof *argv / 2U)
				goto fail;
			capacity *= 2U;
			grown = (char **)realloc(argv, capacity * sizeof *argv);
			if (grown == 0)
				goto fail;
			argv = grown;
		}
		argv[i] = cstr_of(OURO_F(args, 0));
		if (argv[i] == 0)
			goto fail;
		i++;
		args = OURO_F(args, 1);
	}
	argv[i] = 0;
	*argc_out = i;
	return argv;
fail:
	while (pending != 0) {
		ouro_env *node = pending;
		pending = node->next;
		free(node);
	}
	for (j = 0; j < i; j++)
		free(argv[j]);
	free(argv);
	return 0;
}

static void proc_argv_free(char **argv, size_t argc)
{
	size_t i;
	if (argv == 0)
		return;
	for (i = 0; i < argc; i++)
		free(argv[i]);
	free(argv);
}

#ifdef _WIN32
static char *shell_quote_alloc(const char *s)
{
	size_t cap = strlen(s) * 4U + 3U;
	size_t at = 0;
	char *out = (char *)calloc(cap, 1U);
	if (out == 0)
		return 0;
	out[at++] = '\'';
	for (; *s != 0; s++) {
		if (*s == '\'') {
			memcpy(out + at, "'\\''", 4U);
			at += 4U;
		} else {
			out[at++] = *s;
		}
	}
	out[at++] = '\'';
	out[at] = 0;
	return out;
}

static int line_append(char *line, size_t cap, size_t *used,
	const char *piece, int spaced)
{
	size_t n = strlen(piece);
	size_t extra = n + (spaced ? 1U : 0U);
	if (*used + extra + 1U > cap)
		return 0;
	if (spaced)
		line[(*used)++] = ' ';
	memcpy(line + *used, piece, n + 1U);
	*used += n;
	return 1;
}

static int create_private_capture_dir(char *dir, size_t cap)
{
	char base[2048];
	DWORD n = GetTempPathA((DWORD)sizeof base, base);
	static LONG sequence;
	unsigned long attempt;
	if (n == 0 || n >= sizeof base)
		return 0;
	for (attempt = 0; attempt < 256UL; attempt++) {
		LARGE_INTEGER ticks;
		QueryPerformanceCounter(&ticks);
		if (snprintf(dir, cap, "%souro_exec_%lu_%lx_%lx", base,
			    (unsigned long)GetCurrentProcessId(),
			    (unsigned long)ticks.LowPart,
			    (unsigned long)InterlockedIncrement(&sequence)) < 0)
			return 0;
		slash_path(dir);
		if (CreateDirectoryA(dir, NULL))
			return 1;
		if (GetLastError() != ERROR_ALREADY_EXISTS)
			return 0;
	}
	return 0;
}

static int create_empty_private_file(const char *path)
{
	HANDLE h = CreateFileA(path, GENERIC_READ | GENERIC_WRITE, 0, NULL,
		CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY, NULL);
	if (h == INVALID_HANDLE_VALUE)
		return 0;
	CloseHandle(h);
	return 1;
}

static ouro_v *read_whole_file(const char *path)
{
	FILE *f = fopen(path, "rb");
	char chunk[8192];
	char *acc = (char *)malloc(1U);
	size_t used = 0;
	size_t got;
	ouro_v *result;
	if (f == 0 || acc == 0) {
		if (f != 0)
			fclose(f);
		free(acc);
		return owned_str("");
	}
	acc[0] = 0;
	while ((got = fread(chunk, 1, sizeof chunk, f)) > 0) {
		char *grown = (char *)realloc(acc, used + got + 1U);
		if (grown == 0)
			break;
		acc = grown;
		memcpy(acc + used, chunk, got);
		used += got;
		acc[used] = 0;
	}
	fclose(f);
	result = owned_str(acc);
	free(acc);
	return result;
}

static unsigned long proc_exec_host(char **argv, size_t argc,
	ouro_v **out_v, ouro_v **err_v)
{
	char dir[4096];
	char out_path[4096];
	char err_path[4096];
	char script_path[4096];
	char line[32768];
	size_t used = 0;
	size_t i;
	int status = -1;
	int ready = 0;
	if (!create_private_capture_dir(dir, sizeof dir))
		goto done;
	if (snprintf(out_path, sizeof out_path, "%s/out", dir) < 0 ||
	    snprintf(err_path, sizeof err_path, "%s/err", dir) < 0 ||
	    snprintf(script_path, sizeof script_path, "%s/run.sh", dir) < 0)
		goto cleanup_dir;
	if (!create_empty_private_file(out_path) ||
	    !create_empty_private_file(err_path))
		goto cleanup_files;
	line[0] = 0;
	for (i = 0; i < argc; i++) {
		char *quoted = shell_quote_alloc(argv[i]);
		if (quoted == 0 || !line_append(line, sizeof line, &used, quoted, i > 0)) {
			free(quoted);
			goto cleanup_files;
		}
		free(quoted);
	}
	{
		char *quoted_out = shell_quote_alloc(out_path);
		char *quoted_err = shell_quote_alloc(err_path);
		if (quoted_out == 0 || quoted_err == 0 ||
		    !line_append(line, sizeof line, &used, ">", 1) ||
		    !line_append(line, sizeof line, &used, quoted_out, 1) ||
		    !line_append(line, sizeof line, &used, "2>", 1) ||
		    !line_append(line, sizeof line, &used, quoted_err, 1) ||
		    !line_append(line, sizeof line, &used, "< /dev/null", 1)) {
			free(quoted_out);
			free(quoted_err);
			goto cleanup_files;
		}
		free(quoted_out);
		free(quoted_err);
	}
	status = system_posix(line, script_path);
	ready = 1;
cleanup_files:
	*out_v = ready ? read_whole_file(out_path) : owned_str("");
	*err_v = ready ? read_whole_file(err_path) : owned_str("");
	remove(script_path);
	remove(out_path);
	remove(err_path);
cleanup_dir:
	RemoveDirectoryA(dir);
done:
	if (!ready) {
		*out_v = owned_str("");
		*err_v = owned_str("");
	}
	return status < 0 ? 127UL : (unsigned long)status;
}
#else
static int posix_capture_fd(void)
{
	char path[4096];
	const char *tmp = host_temp_dir();
	int written = snprintf(path, sizeof path, "%s/ouro_exec_XXXXXX", tmp);
	int fd;
	if (written < 0 || (size_t)written >= sizeof path)
		return -1;
	fd = mkstemp(path);
	if (fd < 0)
		return -1;
	(void)fchmod(fd, 0600);
	(void)unlink(path);
	return fd;
}

static ouro_v *read_capture_fd(int fd)
{
	char chunk[8192];
	char *acc = (char *)malloc(1U);
	size_t used = 0;
	ssize_t got;
	ouro_v *result;
	if (acc == 0)
		return owned_str("");
	acc[0] = 0;
	(void)lseek(fd, 0, SEEK_SET);
	while ((got = read(fd, chunk, sizeof chunk)) > 0) {
		char *grown = (char *)realloc(acc, used + (size_t)got + 1U);
		if (grown == 0)
			break;
		acc = grown;
		memcpy(acc + used, chunk, (size_t)got);
		used += (size_t)got;
		acc[used] = 0;
	}
	result = owned_str(acc);
	free(acc);
	return result;
}

static unsigned long proc_exec_host(char **argv, size_t argc,
	ouro_v **out_v, ouro_v **err_v)
{
	int out_fd = posix_capture_fd();
	int err_fd = posix_capture_fd();
	pid_t child = -1;
	int status = 0;
	unsigned long code = 127UL;
	(void)argc;
	if (out_fd < 0 || err_fd < 0)
		goto done;
	child = fork();
	if (child == 0) {
		int null_fd = open("/dev/null", O_RDONLY);
		if (null_fd >= 0)
			(void)dup2(null_fd, STDIN_FILENO);
		(void)dup2(out_fd, STDOUT_FILENO);
		(void)dup2(err_fd, STDERR_FILENO);
		if (null_fd > STDERR_FILENO)
			close(null_fd);
		if (out_fd > STDERR_FILENO)
			close(out_fd);
		if (err_fd > STDERR_FILENO)
			close(err_fd);
		execvp(argv[0], argv);
		_exit(127);
	}
	if (child > 0) {
		while (waitpid(child, &status, 0) < 0 && errno == EINTR)
			;
		if (WIFEXITED(status))
			code = (unsigned long)WEXITSTATUS(status);
		else if (WIFSIGNALED(status))
			code = 128UL + (unsigned long)WTERMSIG(status);
	}
done:
	*out_v = out_fd < 0 ? owned_str("") : read_capture_fd(out_fd);
	*err_v = err_fd < 0 ? owned_str("") : read_capture_fd(err_fd);
	if (out_fd >= 0)
		close(out_fd);
	if (err_fd >= 0)
		close(err_fd);
	return code;
}
#endif

/* POSIX executes the argv vector directly into already-open unlinked capture
   descriptors. Windows quotes argv into a script inside a newly-created
   private directory whose capture files are opened with CREATE_NEW/no sharing.
   Neither path reuses an attacker-predictable shared filename. */
static ouro_v *proc_exec_run(ouro_env *env, ouro_v *u)
{
	ouro_v *args = env->v;
	char *cmd = cstr_of(env->next->v);
	char **argv;
	size_t argc = 0;
	unsigned long code = 127UL;
	ouro_v *fields[3];
	(void)u;
	sandbox_die("proc_exec");
	if (cmd == 0)
		cmd = copy_string("");
	argv = proc_argv_of(cmd, args, &argc);
	fields[1] = owned_str("");
	fields[2] = owned_str("");
	if (argv != 0 && argc > 0 && argv[0][0] != 0)
		code = proc_exec_host(argv, argc, &fields[1], &fields[2]);
	fields[0] = ouro_nat(code);
	proc_argv_free(argv, argc);
	return ouro_ctor(0, 3, fields);
}

static ouro_v *f_proc_exec_args(ouro_env *env, ouro_v *args)
{
	return thunk(proc_exec_run, ouro_cons(args, env));
}

static ouro_v *f_proc_exec(ouro_env *env, ouro_v *cmd)
{
	(void)env;
	return ouro_clos(f_proc_exec_args, ouro_cons(cmd, 0));
}

/* The checked intrinsic uses ordinary pairs. Keep the legacy ProcResult
   adapter on the same process implementation until C hosting is retired. */
static ouro_v *proc_capture_run(ouro_env *env, ouro_v *unit)
{
	ouro_v *result = proc_exec_run(env, unit);
	ouro_v *fields[2];
	ouro_v *streams;
	fields[0] = OURO_F(result, 1);
	fields[1] = OURO_F(result, 2);
	streams = ouro_ctor(0, 2, fields);
	fields[0] = OURO_F(result, 0);
	fields[1] = streams;
	return ouro_ctor(0, 2, fields);
}

static ouro_v *f_proc_capture_args(ouro_env *env, ouro_v *args)
{
	return thunk(proc_capture_run, ouro_cons(args, env));
}

static ouro_v *f_proc_capture(ouro_env *env, ouro_v *cmd)
{
	(void)env;
	return ouro_clos(f_proc_capture_args, ouro_cons(cmd, 0));
}

/* Foreground inherited execution belongs to the native Windows owner.
   This temporary host returns ERROR_CALL_NOT_IMPLEMENTED only when run. */
static ouro_v *proc_inherit_unavailable_run(ouro_env *env, ouro_v *unit)
{
	ouro_v *fields[2];
	(void)env;
	(void)unit;
	fields[0] = ouro_nat(120);
	fields[1] = ouro_nat(0);
	return ouro_ctor(0, 2, fields);
}

static ouro_v *f_proc_inherit_args(ouro_env *env, ouro_v *args)
{
	(void)env;
	(void)args;
	return thunk(proc_inherit_unavailable_run, 0);
}

static ouro_v *f_proc_inherit(ouro_env *env, ouro_v *command)
{
	(void)env;
	(void)command;
	return ouro_clos(f_proc_inherit_args, 0);
}

/* The transitional C host has no HTTP transport. Preserve the checked
   three-argument interface and report unavailability only when IO runs. */
/* Bounded capture is unavailable in the temporary C host. No child is
   launched; construction and partial application remain pure capture. */
static ouro_v *proc_bounded_unavailable_run(ouro_env *env, ouro_v *unit)
{
    ouro_v *fields[2];
    ouro_v *result;
    (void)env;
    (void)unit;
    fields[0] = owned_str(""); fields[1] = owned_str("");
    result = ouro_ctor(0, 2, fields);
    fields[0] = ouro_nat(0); fields[1] = result;
    result = ouro_ctor(0, 2, fields);
    fields[0] = ouro_nat(120); fields[1] = result;
    result = ouro_ctor(0, 2, fields);
    fields[0] = ouro_nat(1); fields[1] = result;
    return ouro_ctor(0, 2, fields);
}
static ouro_v *f_proc_bounded_limits(ouro_env *env, ouro_v *limits)
{
    (void)env; (void)limits;
    return thunk(proc_bounded_unavailable_run, 0);
}
static ouro_v *f_proc_bounded_args(ouro_env *env, ouro_v *args)
{
    (void)env; (void)args;
    return ouro_clos(f_proc_bounded_limits, 0);
}
static ouro_v *f_proc_bounded(ouro_env *env, ouro_v *command)
{
    (void)env; (void)command;
    return ouro_clos(f_proc_bounded_args, 0);
}

static ouro_v *http_unavailable_run(ouro_env *env, ouro_v *unit)
{
	ouro_v *fields[2];
	ouro_v *response;
	(void)env;
	(void)unit;
	fields[0] = owned_str("");
	fields[1] = owned_str("HTTP transport unavailable in C host");
	response = ouro_ctor(0, 2, fields);
	fields[0] = ouro_nat(0);
	fields[1] = response;
	return ouro_ctor(0, 2, fields);
}

static ouro_v *f_http_body(ouro_env *env, ouro_v *body)
{
	(void)env;
	(void)body;
	return thunk(http_unavailable_run, 0);
}

static ouro_v *f_http_headers(ouro_env *env, ouro_v *headers)
{
	(void)env;
	(void)headers;
	return ouro_clos(f_http_body, 0);
}

static ouro_v *f_http_post(ouro_env *env, ouro_v *url)
{
	(void)env;
	(void)url;
	return ouro_clos(f_http_headers, 0);
}

static ouro_v *type_stub_apply(ouro_env *env, ouro_v *a)
{
	const char *nm = env != 0 && env->v != 0 && env->v->tag == OURO_TAG_STR &&
					 env->v->u.s != 0 ?
				 env->v->u.s :
				 "?";
	(void)a;
	fprintf(stderr,
		"ouro run: global %s has no runtime value "
		"(erased type argument or unwired axiom)\n",
		nm);
	exit(70);
}

/* Stand-in for a global that extraction kept as a value but that carries no
   runtime content: an inductive/Type axiom name used as a type argument.
   Passing it around is fine; applying or matching it fails loudly. */
ouro_v *ouro_io_type_stub(const char *name)
{
	ouro_v *v;
	/* Generated code caches this value for the whole process; it must not
	   sit at the top of the phase heap, where ouro_app reclaims temporaries. */
	ouro_static_begin();
	v = ouro_clos(type_stub_apply, ouro_cons(ouro_str(name), 0));
	ouro_static_end();
	return v;
}

ouro_v *ouro_io_prim_req(const char *name)
{
	ouro_v *v = ouro_io_prim(name);
	if (v == 0) {
		fprintf(stderr,
			"ouro run: runtime prim %s is not wired in the C host\n",
			name);
		exit(70);
	}
	return v;
}

static ouro_v *io_prim_new(const char *name);

/* Host prims are process-lifetime values that generated code caches in a
   global; they live in the static bank for the same reason as ouro_fast. */
ouro_v *ouro_io_prim(const char *name)
{
	ouro_v *v;
	ouro_static_begin();
	v = io_prim_new(name);
	ouro_static_end();
	return v;
}

static ouro_v *io_prim_new(const char *name)
{
	if (strcmp(name, "ouro.runtime.pure") == 0)
		return ouro_clos(f_io_pure, 0);
	if (strcmp(name, "ouro.runtime.bind") == 0)
		return ouro_clos(f_io_bind_ma, 0);
	if (strcmp(name, "ouro.runtime.loop") == 0)
		return ouro_clos(f_runtime_loop, 0);
	if (strcmp(name, "ouro.u8.from_nat.checked") == 0)
		return ouro_clos(f_u8_from_nat, 0);
	if (strcmp(name, "ouro.u32.from_nat.checked") == 0)
		return ouro_clos(f_u32_from_nat, 0);
	if (strcmp(name, "ouro.u8.sub.wrap") == 0)
		return ouro_clos(f_u8_sub, 0);
	if (strcmp(name, "io_pure") == 0)
		return ouro_clos(f_io_pure, 0);
	if (strcmp(name, "io_bind") == 0)
		return ouro_clos(f_io_bind_ma, 0);
	if (strcmp(name, "prim_stdout_write") == 0)
		return ouro_clos(f_stdout, 0);
	if (strcmp(name, "prim_stderr_write") == 0)
		return ouro_clos(f_stderr, 0);
	if (strcmp(name, "prim_stdin_read_line") == 0)
		return ouro_clos(f_stdin, 0);
	if (strcmp(name, "prim_exit") == 0)
		return ouro_clos(f_exit, 0);
	if (strcmp(name, "prim_argv") == 0)
		return ouro_clos(f_argv, 0);
	if (strcmp(name, "prim_env_get") == 0)
		return ouro_clos(f_env, 0);
	if (strcmp(name, "prim_fs_read_file") == 0)
		return ouro_clos(f_fs_read, 0);
	if (strcmp(name, "prim_fs_write_file") == 0)
		return ouro_clos(f_fs_write_p, 0);
	if (strcmp(name, "prim_fs_exists") == 0)
		return ouro_clos(f_fs_exists, 0);
	if (strcmp(name, "prim_fs_list_dir") == 0)
		return ouro_clos(f_fs_list, 0);
	if (strcmp(name, "prim_fs_listable") == 0)
		return ouro_clos(f_fs_listable, 0);
	if (strcmp(name, "prim_fs_kind") == 0)
		return ouro_clos(f_fs_kind, 0);
	if (strcmp(name, "prim_fs_realpath") == 0)
		return ouro_clos(f_fs_realpath, 0);
	if (strcmp(name, "prim_time_now") == 0)
		return ouro_clos(f_time, 0);
	if (strcmp(name, "prim_string_concat") == 0)
		return ouro_clos(f_str_concat, 0);
	if (strcmp(name, "prim_string_length") == 0)
		return ouro_clos(f_str_length, 0);
	if (strcmp(name, "prim_string_byte_at") == 0)
		return ouro_clos(f_str_byte_at, 0);
	if (strcmp(name, "prim_json_string_parse") == 0)
		return ouro_clos(f_json_string_parse, 0);
	if (strcmp(name, "prim_string_eq") == 0)
		return ouro_clos(f_str_eq, 0);
	if (strcmp(name, "prim_string_slice") == 0)
		return ouro_clos(f_str_slice, 0);
	if (strcmp(name, "prim_string_of_nat") == 0)
		return ouro_clos(f_str_of_nat, 0);
	if (strcmp(name, "prim_string_to_char_codes") == 0)
		return ouro_clos(f_str_to_codes, 0);
	if (strcmp(name, "prim_string_of_char_codes") == 0)
		return ouro_clos(f_str_of_codes, 0);
	if (strcmp(name, "prim_string_starts") == 0)
		return ouro_clos(f_str_starts, 0);
	if (strcmp(name, "prim_string_ends") == 0)
		return ouro_clos(f_str_ends, 0);
	if (strcmp(name, "prim_string_contains") == 0)
		return ouro_clos(f_str_contains, 0);
	if (strcmp(name, "prim_string_index") == 0)
		return ouro_clos(f_str_index, 0);
	if (strcmp(name, "prim_string_split") == 0)
		return ouro_clos(f_str_split, 0);
	if (strcmp(name, "prim_string_replace") == 0)
		return ouro_clos(f_str_replace, 0);
	if (strcmp(name, "prim_string_le") == 0)
		return ouro_clos(f_str_le, 0);
	if (strcmp(name, "prim_string_tokens") == 0)
		return ouro_clos(f_str_tokens, 0);
	if (strcmp(name, "prim_fs_is_dir") == 0)
		return ouro_clos(f_fs_is_dir, 0);
	if (strcmp(name, "prim_fs_mkdir") == 0)
		return ouro_clos(f_fs_mkdir, 0);
	if (strcmp(name, "prim_fs_remove") == 0)
		return ouro_clos(f_fs_remove, 0);
	if (strcmp(name, "prim_fs_temp_file") == 0)
		return ouro_clos(f_fs_temp_file, 0);
	if (strcmp(name, "prim_fs_temp_file_in") == 0)
		return ouro_clos(f_fs_temp_file_in, 0);
	if (strcmp(name, "prim_fs_copy_file") == 0)
		return ouro_clos(f_fs_copy, 0);
	if (strcmp(name, "prim_fs_rename") == 0)
		return ouro_clos(f_fs_rename, 0);
	if (strcmp(name, "prim_stdin_read_bytes") == 0)
		return ouro_clos(f_stdin_bytes, 0);
	if (strcmp(name, "prim_stdout_flush") == 0)
		return ouro_clos(f_stdout_flush, 0);
	if (strcmp(name, "prim_proc_exec") == 0)
		return ouro_clos(f_proc_exec, 0);
	if (strcmp(name, "ouro.process.capture_bounded") == 0)
		return ouro_clos(f_proc_bounded, 0);
	if (strcmp(name, "ouro.process.inherit") == 0)
		return ouro_clos(f_proc_inherit, 0);
	if (strcmp(name, "ouro.process.capture") == 0)
		return ouro_clos(f_proc_capture, 0);
	if (strcmp(name, "ouro.http.post") == 0)
		return ouro_clos(f_http_post, 0);
	return 0;
}
