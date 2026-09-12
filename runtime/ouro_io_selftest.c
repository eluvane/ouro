/* ouro_io_selftest.c: prove C IO prims without Node.
   Covers checked writes, unique private scratch, JSON string decoding, and
   process capture without the old predictable shared filenames. */
#include "ouro_io.h"
#include "ouro_rt.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#include <process.h>
#include <wchar.h>
#include <windows.h>
#define ouro_test_getpid _getpid
#else
#include <unistd.h>
#define ouro_test_getpid getpid
#endif

static int fail(const char *m)
{
	fprintf(stderr, "OURO_IO_SELFTEST: FAIL %s\n", m);
	return 1;
}

static int host_bytes_eq(ouro_v *v, const char *s, size_t n)
{
	if (v == 0 || v->u.s == 0 || v->n != (int)n)
		return 0;
	if (v->tag != OURO_TAG_STR && v->tag != OURO_TAG_BYTES)
		return 0;
	return memcmp(v->u.s, s, n) == 0;
}

static int write_text(const char *path, const char *text)
{
	FILE *f = fopen(path, "wb");
	if (f == 0)
		return 0;
	if (fputs(text, f) < 0) {
		fclose(f);
		return 0;
	}
	return fclose(f) == 0;
}

static int file_text_eq(const char *path, const char *want)
{
	char buf[128];
	FILE *f = fopen(path, "rb");
	if (f == 0)
		return 0;
	if (fgets(buf, (int)sizeof buf, f) == 0) {
		fclose(f);
		return 0;
	}
	fclose(f);
	return strcmp(buf, want) == 0;
}

/* ouro-structural: {"rule":"STRUCT_DUPLICATE_IMPLEMENTATION","category":"independent-oracle","related":["runtime/ouro_io.c#host_temp_dir"],"reason":"Compute the expected host scratch directory independently when validating runtime temporary-file behavior."} */
static const char *test_temp_dir(void)
{
	const char *tmp = getenv("TMPDIR");
#ifdef _WIN32
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

static ouro_v *string_list_one(const char *text)
{
	ouro_v *fields[2];
	fields[0] = ouro_str(text);
	fields[1] = ouro_ctor(0, 0, 0);
	return ouro_ctor(1, 2, fields);
}

static int json_string_primitive_check(void)
{
	const size_t body_len = 600000U;
	char *json = (char *)malloc(body_len + 3U);
	ouro_v *parsed;
	ouro_v *maybe;
	ouro_v *decoded;
	ouro_v *invalid;
	if (json == 0)
		return fail("large JSON allocation");
	json[0] = '"';
	memset(json + 1, 'a', body_len);
	json[body_len + 1U] = '"';
	json[body_len + 2U] = 0;
	parsed = ouro_io_prim("prim_json_string_parse");
	parsed = ouro_apply(parsed, ouro_str(json));
	parsed = ouro_apply(parsed, ouro_nat(0));
	free(json);
	if (parsed == 0 || parsed->tag != 0 || parsed->n != 2)
		return fail("JSON primitive pair");
	maybe = OURO_F(parsed, 0);
	if (maybe == 0 || maybe->tag != 1 || maybe->n != 1)
		return fail("large JSON string rejected");
	decoded = OURO_F(maybe, 0);
	if (decoded == 0 || decoded->tag != OURO_TAG_STR || decoded->u.s == 0 ||
	    decoded->n != (int)body_len)
		return fail("large JSON string decode");
	invalid = ouro_io_prim("prim_json_string_parse");
	invalid = ouro_apply(invalid, ouro_str("\"\\u0041\""));
	invalid = ouro_apply(invalid, ouro_nat(0));
	if (invalid == 0 || invalid->tag != 0 || invalid->n != 2 ||
	    OURO_F(invalid, 0) == 0 || OURO_F(invalid, 0)->tag != 0)
		return fail("unsupported JSON escape accepted");
	return 0;
}

/* The list prim_string_to_char_codes returns is a packed chunk, and an
   append of two of them is a concat node. The host-fast `reverse` bound to
   compiled programs must read both the way ouro_case does; it used to return
   Nil for a packed chunk. */
static int packed_codes_reverse_check(void)
{
	ouro_v *codes = ouro_apply(ouro_io_prim("prim_string_to_char_codes"),
				 ouro_str("abc"));
	ouro_v *more = ouro_apply(ouro_io_prim("prim_string_to_char_codes"),
				ouro_str("de"));
	ouro_v *reversed;
	ouro_v *text;
	if (codes == 0 || codes->tag != OURO_TAG_BYTES || codes->n != 3)
		return fail("char codes are not a packed chunk");
	reversed = ouro_apply(ouro_fast("reverse"), codes);
	text = ouro_apply(ouro_io_prim("prim_string_of_char_codes"), reversed);
	if (!host_bytes_eq(text, "cba", 3))
		return fail("reverse of packed char codes");
	reversed = ouro_apply(ouro_apply(ouro_fast("append"), codes), more);
	reversed = ouro_apply(ouro_fast("reverse"), reversed);
	text = ouro_apply(ouro_io_prim("prim_string_of_char_codes"), reversed);
	if (!host_bytes_eq(text, "edcba", 5))
		return fail("reverse of appended packed char codes");
	reversed = ouro_apply(ouro_fast("reverse"), reversed);
	text = ouro_apply(ouro_io_prim("prim_string_of_char_codes"), reversed);
	if (!host_bytes_eq(text, "abcde", 5))
		return fail("reverse of a cons list");
	return 0;
}

static int binary_file_roundtrip_check(void)
{
	char path[256];
	unsigned char payload[] = { 0, 255, 128, 65, 13, 10, 0 };
	unsigned char got[sizeof payload];
	ouro_v *codes;
	ouro_v *text;
	ouro_v *read;
	ouro_v *write;
	FILE *f;
	size_t n;

	if (snprintf(path, sizeof path, "_build/c/io_selftest_bin_%d.bin",
		     ouro_test_getpid()) < 0)
		return fail("binary path");
	codes = ouro_bytes(payload, (unsigned long)sizeof payload);
	text = ouro_apply(ouro_io_prim("prim_string_of_char_codes"), codes);
	if (!host_bytes_eq(text, (const char *)payload, sizeof payload))
		return fail("of_char_codes keeps NULs");
	write = ouro_io_prim("prim_fs_write_file");
	write = ouro_apply(write, ouro_str(path));
	write = ouro_apply(write, text);
	(void)ouro_apply(write, ouro_ctor(0, 0, 0));
	f = fopen(path, "rb");
	if (f == 0)
		return fail("binary write did not create file");
	n = fread(got, 1, sizeof got, f);
	fclose(f);
	if (n != sizeof payload || memcmp(got, payload, sizeof payload) != 0)
		return fail("binary write dropped bytes");
	read = ouro_io_prim("prim_fs_read_file");
	read = ouro_apply(read, ouro_str(path));
	read = ouro_apply(read, ouro_ctor(0, 0, 0));
	if (!host_bytes_eq(read, (const char *)payload, sizeof payload))
		return fail("binary read dropped bytes");
	remove(path);
	return 0;
}

static int binary_string_equality_check(void)
{
	const unsigned char first[] = { 77, 90, 0, 1 };
	const unsigned char second[] = { 77, 90, 0, 2 };
	ouro_v *left = ouro_packed(first, sizeof first);
	ouro_v *different = ouro_packed(second, sizeof second);
	ouro_v *shorter = ouro_packed(first, sizeof first - 1U);
	ouro_v *equal = ouro_apply(ouro_io_prim("prim_string_of_char_codes"),
		ouro_bytes(first, sizeof first));
	ouro_v *compare = ouro_apply(ouro_io_prim("prim_string_eq"), left);
	ouro_v *result = ouro_apply(compare, different);
	ouro_v *chunks[2];
	if (result == 0 || result->tag != 1 || result->n != 0)
		return fail("binary string equality ignored bytes after NUL");
	result = ouro_apply(compare, shorter);
	if (result == 0 || result->tag != 1 || result->n != 0)
		return fail("binary string equality ignored length after NUL");
	result = ouro_apply(compare, equal);
	if (result == 0 || result->tag != 0 || result->n != 0)
		return fail("binary string equality rejected equal bytes");
	result = ouro_apply(compare, ouro_bytes(first, sizeof first));
	if (result == 0 || result->tag != 0 || result->n != 0)
		return fail("binary string equality rejected byte-list representation");
	chunks[0] = ouro_packed(first, 2);
	chunks[1] = ouro_packed(first + 2, 2);
	result = ouro_apply(compare, ouro_ctor(OURO_TAG_CAT, 2, chunks));
	if (result == 0 || result->tag != 0 || result->n != 0)
		return fail("binary string equality rejected concat representation");
	return 0;
}

static int private_temp_check(void)
{
	ouro_v *unit = ouro_ctor(0, 0, 0);
	ouro_v *a = ouro_io_prim("prim_fs_temp_file_in");
	ouro_v *b = ouro_io_prim("prim_fs_temp_file_in");
	struct stat st;
	a = ouro_apply(a, ouro_str("_build/c"));
	a = ouro_apply(a, unit);
	b = ouro_apply(b, ouro_str("_build/c"));
	b = ouro_apply(b, unit);
	if (a == 0 || b == 0 || a->tag != OURO_TAG_STR || b->tag != OURO_TAG_STR ||
	    a->u.s == 0 || b->u.s == 0 || a->u.s[0] == 0 || b->u.s[0] == 0)
		return fail("private temp creation");
	if (strcmp(a->u.s, b->u.s) == 0)
		return fail("private temp collision");
	if (stat(a->u.s, &st) != 0 || stat(b->u.s, &st) != 0)
		return fail("private temp missing");
#ifndef _WIN32
	if ((st.st_mode & 077) != 0)
		return fail("private temp permissions");
#endif
	remove(a->u.s);
	remove(b->u.s);
	return 0;
}

static int rename_result_status(ouro_v *action)
{
	ouro_v *result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (result == 0 || result->tag != OURO_TAG_NAT || result->n < 0)
		return -1;
	return result->n;
}

static ouro_v *rename_action(ouro_v *source, ouro_v *target)
{
	ouro_v *action = ouro_apply(ouro_io_prim_req("prim_fs_rename"), source);
	return ouro_apply(action, target);
}

static int file_rename_check(void)
{
	char source[256];
	char target[256];
	char directory[256];
	char malformed[260];
	ouro_v *action;
	ouro_v *chunks[2];
	struct stat info;
	const char *error = 0;
	int status;
	int missing_status;
#ifdef _WIN32
	HANDLE lock;
	char unicode_path[256];
	wchar_t wide_path[256];
	missing_status = ERROR_FILE_NOT_FOUND;
#else
	missing_status = ENOENT;
#endif
	snprintf(source, sizeof source, "_build/c/io_rename_%d.src", ouro_test_getpid());
	snprintf(target, sizeof target, "_build/c/io_rename_%d.dst", ouro_test_getpid());
	snprintf(directory, sizeof directory, "_build/c/io_rename_%d.dir", ouro_test_getpid());
#ifdef _WIN32
	snprintf(unicode_path, sizeof unicode_path, "_build/c/io_rename_%d_\xD0\x96.dst", ouro_test_getpid());
	swprintf(wide_path, sizeof wide_path / sizeof wide_path[0], L"_build/c/io_rename_%d_\x0416.dst", ouro_test_getpid());
	if (_mkdir(directory) != 0)
#else
	if (mkdir(directory, 0700) != 0)
#endif
		return fail("rename directory setup");
	if (!write_text(source, "new\n") || !write_text(target, "old\n")) {
		error = "rename file setup";
		goto done;
	}
	action = rename_action(ouro_str(source), ouro_str(target));
	if (!file_text_eq(source, "new\n") || !file_text_eq(target, "old\n")) {
		error = "rename ran before action execution";
		goto done;
	}
	if (rename_result_status(action) != 0 || stat(source, &info) == 0 ||
	    !file_text_eq(target, "new\n")) {
		error = "rename existing replacement";
		goto done;
	}
	if (rename_result_status(action) != missing_status || !file_text_eq(target, "new\n")) {
		error = "reused rename did not report missing source or changed destination";
		goto done;
	}
	if (!write_text(source, "staging\n")) {
		error = "rename staging setup";
		goto done;
	}
	status = rename_result_status(rename_action(ouro_str(source), ouro_str(directory)));
	if (status <= 0 || !file_text_eq(source, "staging\n") ||
	    stat(directory, &info) != 0 || !S_ISDIR(info.st_mode)) {
		error = "rename directory refusal did not preserve staging and directory";
		goto done;
	}
#ifdef _WIN32
	lock = CreateFileA(target, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
		FILE_ATTRIBUTE_NORMAL, NULL);
	if (lock == INVALID_HANDLE_VALUE) {
		error = "rename locked output setup";
		goto done;
	}
	status = rename_result_status(action);
	if (!CloseHandle(lock)) {
		error = "rename locked output cleanup";
		goto done;
	}
	if (status <= 0 || !file_text_eq(source, "staging\n") || !file_text_eq(target, "new\n")) {
		error = "rename locked output did not preserve both files";
		goto done;
	}
#endif
	memcpy(malformed, source, strlen(source) + 1U);
	memcpy(malformed + strlen(source) + 1U, "bad", 3);
	status = rename_result_status(rename_action(
		ouro_packed((const unsigned char *)malformed, (unsigned long)strlen(source) + 4UL),
		ouro_str(target)));
	if (status <= 0 || !file_text_eq(source, "staging\n") || !file_text_eq(target, "new\n")) {
		error = "rename accepted embedded source NUL";
		goto done;
	}
	chunks[0] = ouro_str(target);
	chunks[1] = ouro_packed((const unsigned char *)"\0bad", 4);
	status = rename_result_status(rename_action(ouro_str(source), ouro_ctor(OURO_TAG_CAT, 2, chunks)));
	if (status <= 0 || !file_text_eq(source, "staging\n") || !file_text_eq(target, "new\n")) {
		error = "rename accepted embedded target NUL in concat";
		goto done;
	}
	if (rename_result_status(rename_action(ouro_str(""), ouro_str(target))) <= 0 ||
	    rename_result_status(rename_action(ouro_str(source), ouro_str(""))) <= 0 ||
	    !file_text_eq(source, "staging\n") || !file_text_eq(target, "new\n")) {
		error = "rename accepted empty path";
		goto done;
	}
#ifdef _WIN32
	status = rename_result_status(rename_action(ouro_str(source), ouro_str("\xC0\xAF")));
	if (status != ERROR_NO_UNICODE_TRANSLATION || !file_text_eq(source, "staging\n")) {
		error = "rename accepted malformed UTF-8";
		goto done;
	}
	status = rename_result_status(rename_action(ouro_str(source), ouro_str(unicode_path)));
	if (status != 0 || GetFileAttributesW(wide_path) == INVALID_FILE_ATTRIBUTES ||
	    rename_result_status(rename_action(ouro_str(unicode_path), ouro_str(source))) != 0 ||
	    !file_text_eq(source, "staging\n")) {
		error = "rename Unicode path roundtrip";
		goto done;
	}
#endif
	status = rename_result_status(rename_action(
		ouro_bytes((const unsigned char *)source, (unsigned long)strlen(source)), ouro_str(target)));
	if (status != 0 || !file_text_eq(target, "staging\n") || stat(source, &info) == 0)
		error = "rename plain byte-list path";
done:
#ifdef _WIN32
	if (!DeleteFileW(wide_path) && GetLastError() != ERROR_FILE_NOT_FOUND && error == 0)
		error = "rename Unicode path cleanup";
#endif
	if (remove(source) != 0 && errno != ENOENT && error == 0)
		error = "rename source cleanup";
	if (remove(target) != 0 && errno != ENOENT && error == 0)
		error = "rename target cleanup";
#ifdef _WIN32
	if (_rmdir(directory) != 0 && error == 0)
#else
	if (rmdir(directory) != 0 && error == 0)
#endif
		error = "rename directory cleanup";
	return error == 0 ? 0 : fail(error);
}

static int private_process_capture_check(void)
{
	char old_out[4096];
	char old_err[4096];
	const char *tmp = test_temp_dir();
	ouro_v *run;
	ouro_v *result;
	int written_out = snprintf(old_out, sizeof old_out,
		"%s/ouro_exec_%ld_0.out", tmp, (long)ouro_test_getpid());
	int written_err = snprintf(old_err, sizeof old_err,
		"%s/ouro_exec_%ld_0.err", tmp, (long)ouro_test_getpid());
	if (written_out < 0 || written_err < 0 ||
	    (size_t)written_out >= sizeof old_out ||
	    (size_t)written_err >= sizeof old_err)
		return fail("predictable capture path setup");
	if (!write_text(old_out, "out-sentinel\n") ||
	    !write_text(old_err, "err-sentinel\n"))
		return fail("predictable capture sentinel setup");
	run = ouro_io_prim("prim_proc_exec");
	run = ouro_apply(run, ouro_str("printf"));
	run = ouro_apply(run, string_list_one("proc-secure"));
	result = ouro_apply(run, ouro_ctor(0, 0, 0));
	if (result == 0 || result->tag != 0 || result->n != 3 ||
	    OURO_F(result, 1) == 0 || OURO_F(result, 1)->tag != OURO_TAG_STR ||
	    OURO_F(result, 1)->u.s == 0 || strcmp(OURO_F(result, 1)->u.s, "proc-secure") != 0) {
		remove(old_out);
		remove(old_err);
		return fail("private process capture result");
	}
	if (!file_text_eq(old_out, "out-sentinel\n") ||
	    !file_text_eq(old_err, "err-sentinel\n")) {
		remove(old_out);
		remove(old_err);
		return fail("predictable process capture path touched");
	}
	remove(old_out);
	remove(old_err);
	return 0;
}

static int process_capture_pair_check(const char *executable)
{
	ouro_v *capture = ouro_io_prim("ouro.process.capture");
	ouro_v *action;
	ouro_v *result;
	ouro_v *streams;
	int iteration;
	if (capture == 0)
		return fail("missing checked process capture primitive");
	action = ouro_apply(capture, ouro_str(executable));
	action = ouro_apply(action, string_list_one("--capture-child"));
	for (iteration = 0; iteration < 2; iteration++) {
		result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (result == 0 || result->tag != 0 || result->n != 2 ||
		    OURO_F(result, 0) == 0 || OURO_F(result, 0)->tag != OURO_TAG_NAT ||
		    OURO_F(result, 0)->n != 7) {
			if (result != 0 && result->n == 2 && OURO_F(result, 0) != 0)
				fprintf(stderr, "capture status: tag=%d n=%d\n",
					OURO_F(result, 0)->tag, OURO_F(result, 0)->n);
			if (result != 0 && result->n == 2 && OURO_F(result, 1) != 0) {
				streams = OURO_F(result, 1);
				if (streams->n == 2 && OURO_F(streams, 1) != 0 &&
				    OURO_F(streams, 1)->tag == OURO_TAG_STR)
					fprintf(stderr, "capture stderr: %s\n", OURO_F(streams, 1)->u.s);
			}
			return fail("checked process capture status pair");
		}
		streams = OURO_F(result, 1);
		if (streams == 0 || streams->tag != 0 || streams->n != 2 ||
		    !host_bytes_eq(OURO_F(streams, 0), "capture-out", 11) ||
		    !host_bytes_eq(OURO_F(streams, 1), "capture-err", 11))
			return fail("checked process capture stream pair");
	}
	action = ouro_apply(capture, ouro_str(""));
	action = ouro_apply(action, ouro_ctor(0, 0, 0));
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (result == 0 || result->tag != 0 || result->n != 2 ||
	    OURO_F(result, 0) == 0 || OURO_F(result, 0)->tag != OURO_TAG_NAT ||
	    OURO_F(result, 0)->n != 127)
		return fail("checked process capture launch failure");
	streams = OURO_F(result, 1);
	if (streams == 0 || streams->tag != 0 || streams->n != 2 ||
	    !host_bytes_eq(OURO_F(streams, 0), "", 0) ||
	    !host_bytes_eq(OURO_F(streams, 1), "", 0))
		return fail("checked process capture failed-launch streams");
	return 0;
}

static int process_inherit_unavailable_check(void)
{
	ouro_v *run = ouro_io_prim("ouro.process.inherit");
	ouro_v *partial;
	ouro_v *action;
	int iteration;
	if (run == 0 || run->tag != OURO_TAG_CLOS)
		return fail("missing checked inherited process primitive");
	partial = ouro_apply(run, ouro_str("no-child-may-be-launched"));
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return fail("inherited process partial application is not deferred");
	action = ouro_apply(partial, ouro_ctor(0, 0, 0));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("inherited process is not a stored Runtime action");
	for (iteration = 0; iteration < 2; iteration++) {
		ouro_v *result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (result == 0 || result->tag != 0 || result->n != 2 ||
		    OURO_F(result, 0) == 0 || OURO_F(result, 0)->tag != OURO_TAG_NAT ||
		    OURO_F(result, 0)->n != 120 || OURO_F(result, 1) == 0 ||
		    OURO_F(result, 1)->tag != OURO_TAG_NAT || OURO_F(result, 1)->n != 0)
			return fail("inherited process host unavailability must be OS error 120");
	}
	return 0;
}

static int process_bounded_unavailable_check(void)
{
    ouro_v *run = ouro_io_prim("ouro.process.capture_bounded");
    ouro_v *partial;
    ouro_v *action;
    int iteration;
    if (run == 0 || run->tag != OURO_TAG_CLOS)
        return fail("missing bounded capture primitive");
    partial = ouro_apply(run, ouro_str("no-child-may-be-launched"));
    if (partial == 0 || partial->tag != OURO_TAG_CLOS)
        return fail("bounded capture command application is not deferred");
    partial = ouro_apply(partial, ouro_ctor(0, 0, 0));
    if (partial == 0 || partial->tag != OURO_TAG_CLOS)
        return fail("bounded capture argv application is not deferred");
    action = ouro_apply(partial, ouro_ctor(0, 0, 0));
    if (action == 0 || action->tag != OURO_TAG_CLOS)
        return fail("bounded capture is not a stored Runtime action");
    for (iteration = 0; iteration < 2; iteration++) {
        const int expected[3] = {1, 120, 0};
        ouro_v *result = ouro_apply(action, ouro_ctor(0, 0, 0));
        int field;
        for (field = 0; field < 3; field++) {
            if (result == 0 || result->tag != 0 || result->n != 2 ||
                OURO_F(result, 0) == 0 || OURO_F(result, 0)->tag != OURO_TAG_NAT ||
                OURO_F(result, 0)->n != expected[field])
                return fail("bounded capture host unavailability outcome");
            result = OURO_F(result, 1);
        }
        if (result == 0 || result->tag != 0 || result->n != 2 ||
            OURO_F(result, 0) == 0 || OURO_F(result, 1) == 0 ||
            !host_bytes_eq(OURO_F(result, 0), "", 0) ||
            !host_bytes_eq(OURO_F(result, 1), "", 0))
            return fail("unavailable bounded capture streams must be empty");
    }
    return 0;
}

static int http_unavailable_check(void)
{
	const char *reason = "HTTP transport unavailable in C host";
	ouro_v *request = ouro_io_prim("ouro.http.post");
	ouro_v *header_fields[2] = {ouro_str("X-Test"), ouro_str("deferred")};
	ouro_v *headers[2] = {ouro_ctor(0, 2, header_fields), ouro_ctor(0, 0, 0)};
	ouro_v *action;
	ouro_v *result;
	ouro_v *response;
	int iteration;
	if (request == 0 || request->tag != OURO_TAG_CLOS)
		return fail("missing checked HTTP primitive");
	action = ouro_apply(request, ouro_str(""));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("HTTP URL partial application is not deferred");
	action = ouro_apply(action, ouro_ctor(1, 2, headers));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("HTTP headers partial application is not deferred");
	action = ouro_apply(action, ouro_str("request body"));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("HTTP request did not return a stored Runtime action");
	for (iteration = 0; iteration < 2; iteration++) {
		result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (result == 0 || result->tag != 0 || result->n != 2 ||
		    OURO_F(result, 0) == 0 || OURO_F(result, 0)->tag != OURO_TAG_NAT ||
		    OURO_F(result, 0)->n != 0)
			return fail("unavailable HTTP transport did not return status zero");
		response = OURO_F(result, 1);
		if (response == 0 || response->tag != 0 || response->n != 2 ||
		    !host_bytes_eq(OURO_F(response, 0), "", 0) ||
		    !host_bytes_eq(OURO_F(response, 1), reason, strlen(reason)))
			return fail("unavailable HTTP transport body/reason pair");
	}
	return 0;
}

int main(int argc, char **argv)
{
	const char *path = "_build/c/io_selftest.txt";
#ifndef _WIN32
	const char *target = "_build/c/io_selftest_target.txt";
	const char *link = "_build/c/io_selftest_link.txt";
#endif
	ouro_v *w;
	ouro_v *r;
	ouro_v *unit;
	FILE *f;
	char buf[64];

	if (argc == 2 && strcmp(argv[1], "--capture-child") == 0) {
		fputs("capture-out", stdout);
		fputs("capture-err", stderr);
		return 7;
	}
	ouro_rt_warmup();
	if (argc == 2 && strcmp(argv[1], "--bounded-only") == 0)
		return process_bounded_unavailable_check();
	if (process_bounded_unavailable_check() != 0)
		return 1;
	if (argc == 2 && strcmp(argv[1], "--inherit-only") == 0)
		return process_inherit_unavailable_check();
	if (process_inherit_unavailable_check() != 0)
		return 1;
	if (argc == 2 && strcmp(argv[1], "--http-only") == 0)
		return http_unavailable_check();
	if (http_unavailable_check() != 0)
		return 1;
	if (process_capture_pair_check(argv[0]) != 0)
		return 1;
	if (ouro_io_prim("prim_stdout_write") == 0)
		return fail("missing prim_stdout_write");
	if (ouro_io_prim("prim_fs_write_file") == 0)
		return fail("missing prim_fs_write_file");
	if (ouro_io_prim("io_bind") == 0)
		return fail("missing io_bind");

	{
		char *dir = "_build/c";
#ifdef _WIN32
		_mkdir("_build");
		_mkdir(dir);
#else
		mkdir("_build", 0777);
		mkdir(dir, 0777);
#endif
	}
	if (packed_codes_reverse_check() != 0)
		return 1;
	if (binary_file_roundtrip_check() != 0)
		return 1;
	if (binary_string_equality_check() != 0)
		return 1;
	if (json_string_primitive_check() != 0)
		return 1;
	if (private_temp_check() != 0)
		return 1;
	if (file_rename_check() != 0)
		return 1;
	if (private_process_capture_check() != 0)
		return 1;

	w = ouro_io_prim("prim_fs_write_file");
	w = ouro_apply(w, ouro_str(path));
	w = ouro_apply(w, ouro_str("hello-c-io\n"));
	unit = ouro_apply(w, ouro_ctor(0, 0, 0));
	(void)unit;

	f = fopen(path, "rb");
	if (f == 0)
		return fail("write did not create file");
	if (fgets(buf, (int)sizeof buf, f) == 0) {
		fclose(f);
		return fail("empty file");
	}
	fclose(f);
	if (strcmp(buf, "hello-c-io\n") != 0)
		return fail("file contents");

#ifndef _WIN32
	f = fopen(target, "wb");
	if (f == 0 || fputs("keep\n", f) < 0 || fclose(f) != 0)
		return fail("symlink target setup");
	unlink(link);
	if (symlink("io_selftest_target.txt", link) != 0)
		return fail("symlink setup");
	w = ouro_io_prim("prim_fs_write_file");
	w = ouro_apply(w, ouro_str(link));
	w = ouro_apply(w, ouro_str("overwrite\n"));
	(void)ouro_apply(w, ouro_ctor(0, 0, 0));
	f = fopen(target, "rb");
	if (f == 0 || fgets(buf, (int)sizeof buf, f) == 0) {
		if (f != 0)
			fclose(f);
		return fail("symlink target read");
	}
	fclose(f);
	if (strcmp(buf, "keep\n") != 0)
		return fail("write followed symlink");
	unlink(link);
#endif

	r = ouro_io_prim("prim_fs_read_file");
	r = ouro_apply(r, ouro_str(path));
	r = ouro_apply(r, ouro_ctor(0, 0, 0));
	if (!host_bytes_eq(r, "hello-c-io\n", 11))
		return fail("read mismatch");

	w = ouro_io_prim("prim_stdout_write");
	w = ouro_apply(w, ouro_str("hello-c-io\n"));
	(void)ouro_apply(w, ouro_ctor(0, 0, 0));

	fputs("OURO_IO_SELFTEST: PASS prims=io_bind,stdout,fs_read,fs_write,rename,temp,json,proc,codes_reverse,binary\n",
	      stdout);
	return 0;
}
