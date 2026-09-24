/* ouro_io_selftest.c: prove C IO prims without Node.
   Covers checked writes, unique private scratch, JSON string decoding, and
   process capture without the old predictable shared filenames. */
#include "ouro_io.h"
#include "ouro_rt.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#include <fcntl.h>
#include <io.h>
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

static unsigned int loop_tests;
static unsigned int loop_steps;

static ouro_v *loop_condition_run(ouro_env *env, ouro_v *unit)
{
	(void)unit;
	loop_tests++;
	return ouro_nat(env->v->n > 0 ? 1 : 0);
}

static ouro_v *loop_condition(ouro_env *env, ouro_v *state)
{
	(void)env;
	return ouro_clos(loop_condition_run, ouro_cons(state, 0));
}

static ouro_v *loop_step_run(ouro_env *env, ouro_v *unit)
{
	(void)unit;
	loop_steps++;
	return ouro_nat((unsigned long)env->v->n - 1UL);
}

static ouro_v *loop_step(ouro_env *env, ouro_v *state)
{
	(void)env;
	return ouro_clos(loop_step_run, ouro_cons(state, 0));
}

static ouro_v *loop_action(unsigned long initial)
{
	ouro_v *action = ouro_apply(ouro_io_prim_req("ouro.runtime.loop"), ouro_nat(initial));
	action = ouro_apply(action, ouro_clos(loop_condition, 0));
	return ouro_apply(action, ouro_clos(loop_step, 0));
}

static ouro_v *runtime_bound_next(ouro_env *env, ouro_v *value)
{
	(void)env;
	return ouro_apply(ouro_io_prim_req("ouro.runtime.pure"), ouro_nat((unsigned long)value->n + 1UL));
}

static ouro_v *invalid_loop_condition(ouro_env *env, ouro_v *state)
{
	(void)env;
	(void)state;
	return ouro_apply(ouro_io_prim_req("ouro.runtime.pure"), ouro_nat(256));
}

static int runtime_operations_check(void)
{
	ouro_v *action;
	ouro_v *result;
	ouro_v *value;
	ouro_v *successor;
	unsigned long n;
	unsigned long converted;
	for (n = 0; n <= 257; n++) {
		result = ouro_apply(ouro_io_prim_req("ouro.u8.from_nat.checked"), ouro_nat(n));
		if (result->tag != (n <= 255 ? 1 : 0) || result->n != (n <= 255 ? 1 : 0))
			return fail("checked U8 conversion boundary");
		if (n <= 255 && (OURO_F(result, 0)->tag != OURO_TAG_NAT || OURO_F(result, 0)->n != (int)n))
			return fail("checked U8 conversion value");
	}
	value = ouro_nat(INT_MAX);
	successor = ouro_ctor(1, 1, &value);
	result = ouro_apply(ouro_io_prim_req("ouro.u32.from_nat.checked"), successor);
	if (result->tag != 1 || result->n != 1 ||
	    !ouro_nat_to_ulong(OURO_F(result, 0), &converted) || converted != (unsigned long)INT_MAX + 1UL)
		return fail("checked U32 conversion across signed host boundary");
	value = ouro_nat(UINT32_MAX);
	result = ouro_apply(ouro_io_prim_req("ouro.u32.from_nat.checked"), value);
	if (result->tag != 1 || result->n != 1 ||
	    !ouro_nat_to_ulong(OURO_F(result, 0), &converted) || converted != UINT32_MAX)
		return fail("checked U32 maximum");
	successor = ouro_ctor(1, 1, &value);
	result = ouro_apply(ouro_io_prim_req("ouro.u32.from_nat.checked"), successor);
	if (result->tag != 0 || result->n != 0)
		return fail("checked U32 overflow accepted");
	result = ouro_apply(ouro_io_prim_req("prim_string_of_nat"), successor);
	if (!host_bytes_eq(result, "4294967296", 10))
		return fail("wide Nat string formatting");
	result = ouro_apply(ouro_io_prim_req("ouro.u32.from_nat.checked"), ouro_str("invalid Nat"));
	if (result->tag != 0 || result->n != 0)
		return fail("malformed checked word conversion accepted");
	result = ouro_apply(ouro_apply(ouro_io_prim_req("ouro.u8.sub.wrap"), ouro_nat(0)), ouro_nat(1));
	if (result->tag != OURO_TAG_NAT || result->n != 255)
		return fail("U8 subtraction must wrap");
	loop_tests = 0;
	loop_steps = 0;
	action = loop_action(3);
	if (loop_tests != 0 || loop_steps != 0)
		return fail("Runtime loop executed during construction");
	for (n = 1; n <= 2; n++) {
		result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (result->tag != OURO_TAG_NAT || result->n != 0 || loop_tests != 4 * n || loop_steps != 3 * n)
			return fail("Runtime loop must recheck, thread state, stop and remain reusable");
	}
	action = loop_action(0);
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (result->n != 0 || loop_tests != 9 || loop_steps != 6)
		return fail("zero Runtime loop executed its body");
	action = ouro_apply(ouro_io_prim_req("ouro.runtime.pure"), ouro_nat(7));
	action = ouro_apply(ouro_io_prim_req("ouro.runtime.bind"), action);
	action = ouro_apply(action, ouro_clos(runtime_bound_next, 0));
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (result->tag != OURO_TAG_NAT || result->n != 8)
		return fail("raw Runtime pure/bind result");
	return 0;
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

static int binary_string_concat_check(void)
{
	const unsigned char first[] = { 0, 255, 13 };
	const unsigned char second[] = { 10, 254, 0 };
	const unsigned char expected[] = { 0, 255, 13, 10, 254, 0 };
	ouro_v *left[3];
	ouro_v *right[3];
	ouro_v *chunks[2];
	ouro_v *result;
	int i;
	int j;
	left[0] = ouro_packed(first, sizeof first);
	left[1] = ouro_bytes(first, sizeof first);
	chunks[0] = ouro_packed(first, 1);
	chunks[1] = ouro_packed(first + 1, 2);
	left[2] = ouro_ctor(OURO_TAG_CAT, 2, chunks);
	right[0] = ouro_packed(second, sizeof second);
	right[1] = ouro_bytes(second, sizeof second);
	chunks[0] = ouro_packed(second, 2);
	chunks[1] = ouro_packed(second + 2, 1);
	right[2] = ouro_ctor(OURO_TAG_CAT, 2, chunks);
	for (i = 0; i < 3; i++) {
		for (j = 0; j < 3; j++) {
			result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_concat"),
				left[i]), right[j]);
			if (!host_bytes_eq(result, (const char *)expected, sizeof expected))
				return fail("binary string concatenation dropped bytes");
		}
		result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_concat"),
			ouro_str("")), left[i]);
		if (!host_bytes_eq(result, (const char *)first, sizeof first))
			return fail("empty left string concatenation dropped bytes");
		result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_concat"),
			right[i]), ouro_str(""));
		if (!host_bytes_eq(result, (const char *)second, sizeof second))
			return fail("empty right string concatenation dropped bytes");
	}
	result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_concat"),
		ouro_str("hello")), ouro_str(" world"));
	if (!host_bytes_eq(result, "hello world", 11))
		return fail("text string concatenation");
	return 0;
}

static int binary_string_operations_check(void)
{
	const unsigned char payload[] = { 77, 90, 0, 255, 66, 0 };
	const unsigned char needle[] = { 0, 255 };
	const unsigned char missing[] = { 0, 128 };
	ouro_v *text = ouro_packed(payload, sizeof payload);
	ouro_v *result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_contains"),
		ouro_str("C:\\bin\\coil.exe")), ouro_packed(payload + 2, 1));
	if (result == 0 || result->tag != 1 || result->n != 0)
		return fail("string search confused NUL with an empty pattern");
	result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_contains"), text),
		ouro_packed(needle, sizeof needle));
	if (result == 0 || result->tag != 0 || result->n != 0)
		return fail("binary string search missed bytes after NUL");
	result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_contains"), text),
		ouro_packed(missing, sizeof missing));
	if (result == 0 || result->tag != 1 || result->n != 0)
		return fail("binary string search ignored bytes after NUL");
	result = ouro_apply(ouro_apply(ouro_io_prim("prim_string_contains"), text), ouro_str(""));
	if (result == 0 || result->tag != 0 || result->n != 0)
		return fail("empty string search pattern");
	result = ouro_apply(ouro_apply(ouro_apply(ouro_io_prim("prim_string_slice"), text),
		ouro_nat(2)), ouro_nat(3));
	if (!host_bytes_eq(result, (const char *)payload + 2, 3))
		return fail("binary string slice dropped bytes");
	result = ouro_apply(ouro_apply(ouro_apply(ouro_io_prim("prim_string_slice"), text),
		ouro_nat(3)), ouro_nat(99));
	if (!host_bytes_eq(result, (const char *)payload + 3, 3))
		return fail("binary string slice did not clamp length");
	result = ouro_apply(ouro_apply(ouro_apply(ouro_io_prim("prim_string_slice"), text),
		ouro_nat(sizeof payload)), ouro_nat(1));
	if (!host_bytes_eq(result, "", 0))
		return fail("out-of-range string slice");
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

static ouro_v *replace_action(ouro_v *source, ouro_v *stage, ouro_v *backup)
{
	ouro_v *action = ouro_apply(ouro_io_prim_req("prim_fs_replace_file"), source);
	action = ouro_apply(action, stage);
	return ouro_apply(action, backup);
}

static int file_replace_check(void)
{
	char source[256], stage[256], backup[256];
	ouro_v *action;
	struct stat info;
	const char *error = NULL;
	int status;
	snprintf(source, sizeof source, "_build/c/io_replace_%d.src", ouro_test_getpid());
	snprintf(stage, sizeof stage, "_build/c/io_replace_%d.stage", ouro_test_getpid());
	snprintf(backup, sizeof backup, "_build/c/io_replace_%d.backup", ouro_test_getpid());
	if (!write_text(source, "original\n") || !write_text(stage, "candidate\n") || !write_text(backup, "")) {
		error = "replace setup";
		goto done;
	}
	status = rename_result_status(replace_action(ouro_str(source), ouro_str(source), ouro_str(backup)));
	if (status <= 0 || !file_text_eq(source, "original\n") || !file_text_eq(stage, "candidate\n")) {
		error = "replace accepted alias or modified original";
		goto done;
	}
	if (!write_text(backup, "reserved elsewhere\n")) {
		error = "replace occupied backup setup";
		goto done;
	}
	status = rename_result_status(replace_action(ouro_str(source), ouro_str(stage), ouro_str(backup)));
	if (status <= 0 || !file_text_eq(source, "original\n") || !file_text_eq(backup, "reserved elsewhere\n")) {
		error = "replace accepted occupied recovery file";
		goto done;
	}
	if (!write_text(backup, "")) {
		error = "replace reserve empty backup";
		goto done;
	}
	action = replace_action(ouro_str(source), ouro_str(stage), ouro_str(backup));
	if (!file_text_eq(source, "original\n") || !file_text_eq(stage, "candidate\n")) {
		error = "replace action was not deferred";
		goto done;
	}
	if (rename_result_status(action) != 0 || !file_text_eq(source, "candidate\n") ||
	    !file_text_eq(backup, "original\n") || stat(stage, &info) == 0) {
		error = "replace publication/recovery contents";
		goto done;
	}
	if (rename_result_status(action) <= 0 || !file_text_eq(source, "candidate\n") ||
	    !file_text_eq(backup, "original\n"))
		error = "replace reused action changed files or returned success";
done:
	if (remove(source) != 0 && errno != ENOENT && error == NULL)
		error = "replace source cleanup";
	if (remove(stage) != 0 && errno != ENOENT && error == NULL)
		error = "replace stage cleanup";
	if (remove(backup) != 0 && errno != ENOENT && error == NULL)
		error = "replace backup cleanup";
	return error == NULL ? 0 : fail(error);
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

static int process_arguments_check(void)
{
	const char *names[2] = {"prim_proc_exec", "ouro.process.capture"};
	const char *words[4] = {"%s|%s|%s", "", "arg with spaces", "$()'\";|"};
	const char *expected = "|arg with spaces|$()'\";|";
	ouro_v *arguments = ouro_ctor(0, 0, 0);
	int index;
	for (index = 3; index >= 0; index--) {
		ouro_v *parts[2] = {string_list_one(words[index]), arguments};
		arguments = ouro_ctor(OURO_TAG_CAT, 2, parts);
	}
	/* Empty chunks and nesting beyond the string flattener's fixed stack
	   must neither truncate nor reorder a process argument list. */
	for (index = 0; index < 160; index++) {
		ouro_v *parts[2] = {arguments, ouro_ctor(0, 0, 0)};
		arguments = ouro_ctor(OURO_TAG_CAT, 2, parts);
	}
	for (index = 0; index < 2; index++) {
		ouro_v *action = ouro_apply(ouro_io_prim(names[index]), ouro_str("printf"));
		ouro_v *result;
		ouro_v *out;
		ouro_v *err;
		action = ouro_apply(action, arguments);
		result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (result == 0 || result->tag != 0 || result->n != (index == 0 ? 3 : 2) ||
		    OURO_F(result, 0)->tag != OURO_TAG_NAT || OURO_F(result, 0)->n != 0)
			return fail("concatenated process argument status");
		out = index == 0 ? OURO_F(result, 1) : OURO_F(OURO_F(result, 1), 0);
		err = index == 0 ? OURO_F(result, 2) : OURO_F(OURO_F(result, 1), 1);
		if (!host_bytes_eq(out, expected, strlen(expected)) || !host_bytes_eq(err, "", 0))
			return fail("concatenated process argument streams");
		{
			ouro_v *many = ouro_ctor(0, 0, 0);
			ouro_v *parts[2];
			char repeated[65];
			int word;
			for (word = 0; word < 64; word++) {
				parts[0] = ouro_str("x");
				parts[1] = many;
				many = ouro_ctor(1, 2, parts);
				repeated[word] = 'x';
			}
			repeated[64] = 0;
			parts[0] = string_list_one("%s");
			parts[1] = many;
			action = ouro_apply(ouro_io_prim(names[index]), ouro_str("printf"));
			action = ouro_apply(action, ouro_ctor(OURO_TAG_CAT, 2, parts));
			result = ouro_apply(action, ouro_ctor(0, 0, 0));
			out = index == 0 ? OURO_F(result, 1) : OURO_F(OURO_F(result, 1), 0);
			if (OURO_F(result, 0)->tag != OURO_TAG_NAT || OURO_F(result, 0)->n != 0 ||
			    !host_bytes_eq(out, repeated, 64))
				return fail("process argument vector growth");
		}
		/* A malformed tail must reject the whole launch, even after a valid
		   printf operand that would otherwise produce output. */
		{
			ouro_v *parts[2] = {string_list_one("must-not-run"), ouro_ctor(3, 0, 0)};
			action = ouro_apply(ouro_io_prim(names[index]), ouro_str("printf"));
			action = ouro_apply(action, ouro_ctor(OURO_TAG_CAT, 2, parts));
			result = ouro_apply(action, ouro_ctor(0, 0, 0));
			if (OURO_F(result, 0)->tag != OURO_TAG_NAT || OURO_F(result, 0)->n != 127)
				return fail("malformed process arguments launched a child");
		}
	}
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

static ouro_v *bounded_pair2(ouro_v *a, ouro_v *b)
{
	ouro_v *fields[2];
	fields[0] = a;
	fields[1] = b;
	return ouro_ctor(0, 2, fields);
}

static ouro_v *bounded_request(ouro_v *stdin_v, unsigned long timeout_ms,
	unsigned long memory_mb, unsigned long cpu,
	unsigned long long out_cap, unsigned long long err_cap)
{
	return bounded_pair2(stdin_v,
		bounded_pair2(ouro_nat(timeout_ms),
		bounded_pair2(ouro_nat(memory_mb),
		bounded_pair2(ouro_nat(cpu),
		bounded_pair2(ouro_nat_u64(out_cap), ouro_nat_u64(err_cap))))));
}

static int bounded_nat_eq(ouro_v *v, unsigned long long want)
{
	unsigned long got = 0;
	if (v == 0)
		return 0;
	if (want <= (unsigned long)INT_MAX && v->tag == OURO_TAG_NAT)
		return v->n == (int)want;
	if (!ouro_nat_to_ulong(v, &got))
		return 0;
	return (unsigned long long)got == want;
}

/* Unpack kind/detail/peak/stdout/stderr; 1 on well-formed reply. */
static int bounded_unpack(ouro_v *result, ouro_v **kind, ouro_v **detail,
	ouro_v **peak, ouro_v **out, ouro_v **err)
{
	ouro_v *r1;
	ouro_v *r2;
	ouro_v *streams;
	if (result == 0 || result->tag != 0 || result->n != 2)
		return 0;
	*kind = OURO_F(result, 0);
	r1 = OURO_F(result, 1);
	if (r1 == 0 || r1->tag != 0 || r1->n != 2)
		return 0;
	*detail = OURO_F(r1, 0);
	r2 = OURO_F(r1, 1);
	if (r2 == 0 || r2->tag != 0 || r2->n != 2)
		return 0;
	*peak = OURO_F(r2, 0);
	streams = OURO_F(r2, 1);
	if (streams == 0 || streams->tag != 0 || streams->n != 2)
		return 0;
	*out = OURO_F(streams, 0);
	*err = OURO_F(streams, 1);
	return 1;
}

static ouro_v *bounded_action(const char *executable, const char *mode, ouro_v *request)
{
	ouro_v *run = ouro_io_prim("ouro.process.capture_bounded");
	ouro_v *partial;
	if (run == 0 || run->tag != OURO_TAG_CLOS)
		return 0;
	partial = ouro_apply(run, ouro_str(executable));
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return 0;
	partial = ouro_apply(partial, mode != 0 ? string_list_one(mode) : ouro_ctor(0, 0, 0));
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return 0;
	return ouro_apply(partial, request);
}

static int process_bounded_check(const char *executable)
{
	ouro_v *kind;
	ouro_v *detail;
	ouro_v *peak;
	ouro_v *out;
	ouro_v *err;
	ouro_v *action;
	ouro_v *result;
#ifdef _WIN32
	int iteration;
	static const unsigned char binary[] = {65, 0, 255, 128, 10, 13, 90};
	/* Deferred construction launches nothing, twice reusable. */
	action = bounded_action("no-child-may-be-launched", 0,
		bounded_request(ouro_str(""), 5000, 64, 1, 0, 0));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("bounded capture is not a stored Runtime action");
	/* Basic completion with exact binary streams and nonzero exit. */
	action = bounded_action(executable, "--capture-child",
		bounded_request(ouro_str(""), 10000, 64, 1, 64, 64));
	if (action == 0)
		return fail("bounded capture basic action");
	for (iteration = 0; iteration < 2; iteration++) {
		unsigned long peak_bytes = 0;
		result = ouro_apply(action, ouro_ctor(0, 0, 0));
		if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
		    !bounded_nat_eq(kind, 0) || !bounded_nat_eq(detail, 7) ||
		    !host_bytes_eq(out, "capture-out", 11) ||
		    !host_bytes_eq(err, "capture-err", 11) ||
		    !ouro_nat_to_ulong(peak, &peak_bytes) || peak_bytes == 0)
			return fail("bounded capture basic completion");
	}
	/* Binary stdin round-trips exactly, including interior NUL. */
	action = bounded_action(executable, "--bounded-echo",
		bounded_request(ouro_packed(binary, sizeof binary), 10000, 64, 1, 64, 0));
	if (action == 0)
		return fail("bounded capture stdin action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 0) || !bounded_nat_eq(detail, 0) ||
	    !host_bytes_eq(out, (const char *)binary, sizeof binary) ||
	    !host_bytes_eq(err, "", 0))
		return fail("bounded capture stdin echo");
	/* Exit 73 stays a completed child status, not host failure. */
	action = bounded_action(executable, "--bounded-child73",
		bounded_request(ouro_str(""), 10000, 64, 1, 0, 0));
	if (action == 0)
		return fail("bounded capture exit73 action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 0) || !bounded_nat_eq(detail, 73))
		return fail("bounded capture exit 73");
	/* Timeout kills the child and keeps the kind distinct from exit. */
	action = bounded_action(executable, "--bounded-sleep",
		bounded_request(ouro_str(""), 250, 64, 1, 64, 64));
	if (action == 0)
		return fail("bounded capture timeout action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 2))
		return fail("bounded capture timeout kind");
	/* Stream caps report actual lengths without truncated success. */
	action = bounded_action(executable, "--capture-child",
		bounded_request(ouro_str(""), 10000, 64, 1, 5, 64));
	if (action == 0)
		return fail("bounded capture stdout-cap action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 6) || !bounded_nat_eq(detail, 11) ||
	    !host_bytes_eq(out, "", 0) || !host_bytes_eq(err, "", 0))
		return fail("bounded capture stdout cap");
	action = bounded_action(executable, "--capture-child",
		bounded_request(ouro_str(""), 10000, 64, 1, 64, 5));
	if (action == 0)
		return fail("bounded capture stderr-cap action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 7) || !bounded_nat_eq(detail, 11))
		return fail("bounded capture stderr cap");
	/* Missing binaries are OS errors, never child exits. */
	action = bounded_action("./__ouro_absent_bounded_5f79d__.exe", 0,
		bounded_request(ouro_str(""), 5000, 64, 1, 0, 0));
	if (action == 0)
		return fail("bounded capture missing action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 1) || bounded_nat_eq(detail, 0))
		return fail("bounded capture missing binary");
#else
	(void)executable;
	(void)kind;
	(void)detail;
	(void)peak;
	(void)out;
	(void)err;
	action = bounded_action("no-child-may-be-launched", 0,
		bounded_request(ouro_str(""), 5000, 64, 1, 0, 0));
	if (action == 0 || action->tag != OURO_TAG_CLOS)
		return fail("bounded capture is not a stored Runtime action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 1) || !bounded_nat_eq(detail, 120))
		return fail("bounded capture POSIX unavailability");
	return 0;
#endif
	/* Invalid limits name their field without launching. */
	{
		struct {
			unsigned long timeout;
			unsigned long memory;
			unsigned long cpu;
			unsigned long long out_cap;
			unsigned long long err_cap;
			unsigned long long field;
			const char *name;
		} cases[] = {
			{0, 64, 1, 0, 0, 1, "zero timeout"},
			{5000, 0, 1, 0, 0, 2, "zero memory"},
			{5000, 64, 2, 0, 0, 3, "cpu count"},
			{5000, 64, 1, 0xFFFFFFFFFFFFFFFFULL, 0, 4, "stdout cap"},
			{5000, 64, 1, 0, 0xFFFFFFFFFFFFFFFFULL, 5, "stderr cap"},
		};
		size_t i;
		for (i = 0; i < sizeof cases / sizeof cases[0]; i++) {
			action = bounded_action(executable, "--capture-child",
				bounded_request(ouro_str(""), cases[i].timeout,
					cases[i].memory, cases[i].cpu,
					cases[i].out_cap, cases[i].err_cap));
			if (action == 0)
				return fail("bounded capture invalid action");
			result = ouro_apply(action, ouro_ctor(0, 0, 0));
			if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
			    !bounded_nat_eq(kind, 4) ||
			    !bounded_nat_eq(detail, cases[i].field))
				return fail(cases[i].name);
		}
	}
	/* Malformed shapes fail closed as OS parameter errors. */
	action = bounded_action(executable, "--capture-child", ouro_ctor(0, 0, 0));
	if (action == 0)
		return fail("bounded capture malformed action");
	result = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (!bounded_unpack(result, &kind, &detail, &peak, &out, &err) ||
	    !bounded_nat_eq(kind, 1) || !bounded_nat_eq(detail, 87))
		return fail("bounded capture malformed request");
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

	if (!ouro_host_utf8_argv(&argc, &argv))
		return fail("invalid Windows command line");
	if (argc >= 2 && strcmp(argv[1], "--host-arguments") == 0) {
		int i;
		ouro_io_set_argv(argc, argv);
		for (i = 2; i < argc; i++) {
			if (fwrite(argv[i], 1, strlen(argv[i]) + 1U, stdout) != strlen(argv[i]) + 1U)
				return fail("argv observer output");
		}
		return 0;
	}
	if (argc == 2 && strcmp(argv[1], "--capture-child") == 0) {
		fputs("capture-out", stdout);
		fputs("capture-err", stderr);
		return 7;
	}
	if (argc == 2 && strcmp(argv[1], "--bounded-echo") == 0) {
		char chunk[4096];
		size_t got;
#ifdef _WIN32
		_setmode(_fileno(stdin), _O_BINARY);
		_setmode(_fileno(stdout), _O_BINARY);
#endif
		while ((got = fread(chunk, 1, sizeof chunk, stdin)) > 0) {
			if (fwrite(chunk, 1, got, stdout) != got)
				return 11;
		}
		return ferror(stdin) ? 11 : 0;
	}
	if (argc == 2 && strcmp(argv[1], "--bounded-sleep") == 0) {
#ifdef _WIN32
		Sleep(10000);
#else
		sleep(10);
#endif
		return 91;
	}
	if (argc == 2 && strcmp(argv[1], "--bounded-child73") == 0)
		return 73;
	ouro_rt_warmup();
	if (argc == 3 && (strcmp(argv[1], "--read-file") == 0 || strcmp(argv[1], "--read-nul-path") == 0 ||
	    strcmp(argv[1], "--read-invalid-utf8-path") == 0)) {
		ouro_v *name = ouro_str(argv[2]);
		ouro_io_set_argv(argc, argv);
		if (strcmp(argv[1], "--read-nul-path") == 0) {
			static const unsigned char suffix[] = { 0, 'x' };
			name = ouro_apply(ouro_apply(ouro_io_prim_req("prim_string_concat"), name),
			    ouro_packed(suffix, sizeof suffix));
		}
		if (strcmp(argv[1], "--read-invalid-utf8-path") == 0)
			name = ouro_apply(ouro_apply(ouro_io_prim_req("prim_string_concat"), name), ouro_str("\xC0\xAF"));
		r = ouro_apply(ouro_apply(ouro_io_prim_req("prim_fs_read_file"), name), ouro_ctor(0, 0, 0));
		if (r == 0 || r->tag != OURO_TAG_BYTES || r->n < 0)
			return fail("read did not return packed bytes");
		if (fwrite(r->u.s, 1, (size_t)r->n, stdout) != (size_t)r->n)
			return fail("read observer output failed");
		return 0;
	}
	if (argc == 3 && (strcmp(argv[1], "--path-info") == 0 || strcmp(argv[1], "--path-info-nul") == 0 ||
	    strcmp(argv[1], "--path-info-invalid-utf8") == 0)) {
		ouro_v *name = ouro_str(argv[2]);
		ouro_v *exists;
		ouro_v *directory;
		if (strcmp(argv[1], "--path-info-nul") == 0) {
			static const unsigned char suffix[] = { 0, 'x' };
			name = ouro_apply(ouro_apply(ouro_io_prim_req("prim_string_concat"), name),
			    ouro_packed(suffix, sizeof suffix));
		}
		if (strcmp(argv[1], "--path-info-invalid-utf8") == 0)
			name = ouro_apply(ouro_apply(ouro_io_prim_req("prim_string_concat"), name), ouro_str("\xC0\xAF"));
		exists = ouro_apply(ouro_apply(ouro_io_prim_req("prim_fs_exists"), name), ouro_ctor(0, 0, 0));
		directory = ouro_apply(ouro_apply(ouro_io_prim_req("prim_fs_is_dir"), name), ouro_ctor(0, 0, 0));
		if (exists == 0 || directory == 0 || exists->n != 0 || directory->n != 0 ||
		    exists->tag < 0 || exists->tag > 1 || directory->tag < 0 || directory->tag > 1)
			return fail("path predicate result");
		printf("exists=%d directory=%d\n", exists->tag == 0, directory->tag == 0);
		return 0;
	}
	if (argc == 5 && strcmp(argv[1], "--replace-files") == 0) {
		int status = rename_result_status(replace_action(ouro_str(argv[2]), ouro_str(argv[3]), ouro_str(argv[4])));
		printf("%d\n", status);
		return status == 0 ? 0 : 1;
	}
	if (argc == 2 && strcmp(argv[1], "--arguments-only") == 0)
		return process_arguments_check();
	if (argc == 2 && strcmp(argv[1], "--runtime-only") == 0)
		return runtime_operations_check();
	if (argc == 2 && strcmp(argv[1], "--invalid-u8") == 0) {
		w = ouro_apply(ouro_io_prim_req("ouro.u8.sub.wrap"), ouro_ctor(0, 0, 0));
		(void)ouro_apply(w, ouro_nat(1));
		return fail("invalid U8 subtraction returned");
	}
	if (argc == 2 && strcmp(argv[1], "--invalid-loop") == 0) {
		w = ouro_apply(ouro_io_prim_req("ouro.runtime.loop"), ouro_nat(0));
		w = ouro_apply(w, ouro_clos(invalid_loop_condition, 0));
		w = ouro_apply(w, ouro_clos(loop_step, 0));
		(void)ouro_apply(w, ouro_ctor(0, 0, 0));
		return fail("invalid Runtime loop condition returned");
	}
	if (argc == 2 && strcmp(argv[1], "--bounded-only") == 0)
		return process_bounded_check(argv[0]);
	if (process_bounded_check(argv[0]) != 0)
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
	if (process_arguments_check() != 0)
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
	if (runtime_operations_check() != 0)
		return 1;
	if (packed_codes_reverse_check() != 0)
		return 1;
	if (binary_file_roundtrip_check() != 0)
		return 1;
	if (binary_string_equality_check() != 0)
		return 1;
	if (binary_string_concat_check() != 0)
		return 1;
	if (binary_string_operations_check() != 0)
		return 1;
	if (json_string_primitive_check() != 0)
		return 1;
	if (private_temp_check() != 0)
		return 1;
	if (file_rename_check() != 0)
		return 1;
	if (file_replace_check() != 0)
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
