/* Exercise the generated compile_checked_units hook from an ordinary caller.
   Link with frontend_link.c and the generated Ouro compiler exports. */
#include "ouro_host_values.h"
#include "ouro_io.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

static int fail(const char *message)
{
	fprintf(stderr, "FRONTEND_LINK_SELFTEST: FAIL %s\n", message);
	return 1;
}

static ouro_v *export_value(const char *name)
{
	int i;
	for (i = 0; i < ouro_export_count(); i++)
		if (strcmp(ouro_export_name(i), name) == 0)
			return ouro_export_value(i);
	fprintf(stderr, "FRONTEND_LINK_SELFTEST: missing export %s\n", name);
	exit(2);
}


static ouro_v *compile_one(const char *source)
{
	ouro_v *file[2] = {ouro_string_codes("probe.ouro"), ouro_string_codes(source)};
	ouro_v *files[2] = {ouro_ctor(0, 2, file), ouro_ctor(0, 0, 0)};
	ouro_v *check = export_value("compile_checked_units");
	return ouro_apply(ouro_apply(ouro_apply(check, ouro_nat(5000)), ouro_string_codes("probe.ouro")),
		ouro_ctor(1, 2, files));
}

static ouro_v *source_unit(const char *path, const char *source, ouro_v *rest)
{
	ouro_v *pair_fields[2] = {ouro_string_codes(path), ouro_string_codes(source)};
	ouro_v *list_fields[2] = {ouro_ctor(0, 2, pair_fields), rest};
	return ouro_ctor(1, 2, list_fields);
}

static ouro_v *compile_qualified_collision(void)
{
	ouro_v *files = ouro_ctor(0, 0, 0);
	ouro_v *check = export_value("compile_checked_units");
	files = source_unit("probe.ouro",
		"import \"a.ouro\" as A; import \"b.ouro\" as B; "
		"def left : Type := A.Shared; def right : Type := B.Shared;", files);
	files = source_unit("b.ouro", "axiom Shared : Type;", files);
	files = source_unit("a.ouro", "axiom Shared : Type;", files);
	return ouro_apply(ouro_apply(ouro_apply(check, ouro_nat(5000)),
		ouro_string_codes("probe.ouro")), files);
}

static int intern_has_name(ouro_v *intern, const char *name)
{
	ouro_v *found;
	if (intern == 0 || intern->tag != 0 || intern->n != 4)
		return 0;
	found = ouro_apply(ouro_apply(export_value("source_lookup_id"), OURO_F(intern, 0)), ouro_string_codes(name));
	return found != 0 && found->tag == 1 && found->n == 1;
}

static int has_name(ouro_v *result, const char *name)
{
	if (result == 0 || result->tag != 1 || result->n != 1)
		return 0;
	return intern_has_name(ouro_apply(export_value("checked_program_intern"),
		OURO_F(result, 0)), name);
}

static ouro_v *compile_and_return_output(ouro_env *env, ouro_v *unit)
{
	ouro_v *result;
	(void)unit;
	result = compile_one("axiom Checked : Type;");
	if (!has_name(result, "Checked"))
		return 0;
	return ouro_get(env, 0);
}

static int caller_output_check(int argc, char **argv)
{
	ouro_v *arguments;
	ouro_v *output;
	ouro_v *continuation;
	ouro_v *actual;
	int i;
	ouro_io_set_argv(argc, argv);
	arguments = ouro_apply(ouro_io_prim("prim_argv"), ouro_ctor(0, 0, 0));
	for (i = 0; i < 2; i++)
		arguments = OURO_F(arguments, 1);
	output = OURO_F(arguments, 0);
	continuation = ouro_clos(compile_and_return_output, ouro_cons(output, 0));
	actual = ouro_apply(continuation, ouro_ctor(0, 0, 0));
	if (actual == 0 || actual->tag != OURO_TAG_STR || actual->u.s == 0 ||
	    actual->n != (int)strlen(argv[2]) || memcmp(actual->u.s, argv[2], strlen(argv[2])) != 0)
		return fail("caller argv/output did not survive compilation");
	return 0;
}

static int retained_result_check(void)
{
	ouro_v *first = compile_one("axiom First : Type;");
	ouro_v *second;
	ouro_v *qualified;
	if (!has_name(first, "First"))
		return fail("initial checked result");
	second = compile_one("axiom Second : Type;");
	if (!has_name(second, "Second"))
		return fail("second checked result");
	if (!has_name(first, "First") || has_name(first, "Second"))
		return fail("first checked result did not survive second compilation");
	qualified = compile_qualified_collision();
	if (!has_name(qualified, "_ouro_m_0_Shared") ||
	    !has_name(qualified, "_ouro_m_1_Shared") ||
	    !has_name(qualified, "left") || !has_name(qualified, "right") ||
	    !has_name(first, "First"))
		return fail("split frontend lost qualified module identity or retained result");
	return 0;
}

static int typed_failure_check(void)
{
	ouro_v *failed = compile_one("axiom A : Type; def wrong : A := Type;");
	ouro_v *intern = ouro_fe_last_intern();
	ouro_v *next;
	ouro_v *error;
	if (failed == 0 || failed->tag != 0 || failed->n != 1 || !intern_has_name(intern, "wrong"))
		return fail("initial typed failure and intern table");
	next = compile_one("axiom Second : Type;");
	if (!has_name(next, "Second") || failed->tag != 0 || failed->n != 1)
		return fail("typed failure did not survive later success");
	error = OURO_F(failed, 0);
	if (error == 0 || error->tag != 0 || error->n != 2 || as_nat(OURO_F(error, 0)) != 41 ||
	    !intern_has_name(intern, "wrong") || intern_has_name(intern, "Second"))
		return fail("typed failure code or original diagnostic names changed");
	return 0;
}

static int packed_eq(ouro_v *value, const unsigned char *bytes, unsigned long size)
{
	return value != 0 && value->tag == OURO_TAG_BYTES && value->n == (int)size &&
		value->u.s != 0 && memcmp(value->u.s, bytes, size) == 0;
}

static int nested_context_check(void)
{
	const unsigned char binary[] = {'a', 0, 'b', 255};
	ouro_v *caller = ouro_string_codes("caller");
	ouro_heap_context *outer;
	ouro_heap_context *inner;
	ouro_v *work;
	ouro_v *result;
	ouro_v *fields[2];
	unsigned long long before;
	ouro_heap_mark();
	before = ouro_heap_live_bytes();
	outer = ouro_heap_context_enter();
	if (ouro_heap_live_bytes() != before)
		return fail("suspended caller banks missing from live byte count");
	ouro_perm_select(1);
	ouro_perm_begin();
	work = ouro_packed(binary, sizeof binary);
	ouro_perm_end();
	inner = ouro_heap_context_enter();
	fields[0] = work;
	fields[1] = ouro_string_codes("inner");
	result = ouro_heap_context_leave(inner, ouro_ctor(0, 2, fields));
	if (!packed_eq(work, binary, sizeof binary))
		return fail("nested context released its caller's permanent value");
	result = ouro_heap_context_leave(outer, result);
	if (result == 0 || result->tag != 0 || result->n != 2 ||
	    !packed_eq(OURO_F(result, 0), binary, sizeof binary) ||
	    !packed_eq(OURO_F(result, 1), (const unsigned char *)"inner", 5))
		return fail("nested survivor borrowed released byte storage");
	ouro_heap_reset();
	if (ouro_heap_live_bytes() != before || !packed_eq(caller, (const unsigned char *)"caller", 6))
		return fail("caller mark or phase values not restored");
	return 0;
}

static int allocation_context_check(void)
{
	ouro_heap_context *context;
	ouro_v *cached;
	ouro_v *permanent;
	ouro_v *result;
	unsigned long long before = ouro_heap_live_bytes();
	/* A lazy generated getter evaluates its body under static_begin. Its
	   result must remain static even though compiler work uses private banks. */
	ouro_static_begin();
	context = ouro_heap_context_enter();
	(void)ouro_alloc(2UL * 1024UL * 1024UL);
	cached = ouro_heap_context_leave(context, ouro_string_codes("cached"));
	ouro_static_end();
	if (ouro_heap_live_bytes() > before + 1024ULL)
		return fail("compiler work leaked into the static getter heap");
	ouro_heap_discard_phase();
	ouro_perm_reset_bank(0);
	ouro_perm_reset_bank(1);
	if (!packed_eq(cached, (const unsigned char *)"cached", 6))
		return fail("static getter survivor copied into temporary storage");
	ouro_perm_select(1);
	ouro_perm_begin();
	permanent = ouro_string_codes("permanent");
	context = ouro_heap_context_enter();
	result = ouro_heap_context_leave(context, ouro_string_codes("result"));
	ouro_perm_end();
	ouro_heap_discard_phase();
	ouro_perm_reset_bank(0);
	if (!packed_eq(permanent, (const unsigned char *)"permanent", 9) ||
	    !packed_eq(result, (const unsigned char *)"result", 6))
		return fail("caller permanent bank or allocation depth not restored");
	ouro_perm_reset_bank(1);
	ouro_perm_select(0);
	return 0;
}

/* cm_parse threads one intern table through every imported module. Leave must
   share that caller-owned spine; recopying it on each file is the 4 GiB OOM. */
static int shared_parent_spine_check(void)
{
	const unsigned long size = 1024UL * 1024UL;
	unsigned char *bytes;
	ouro_v *parent;
	ouro_v *result;
	ouro_v *inner;
	unsigned long long after_parent;
	unsigned long long after_wraps;
	int i;
	bytes = (unsigned char *)malloc(size);
	if (bytes == 0)
		return fail("could not allocate parent spine payload");
	memset(bytes, 0x5A, size);
	parent = ouro_packed(bytes, size);
	if (!packed_eq(parent, bytes, size)) {
		free(bytes);
		return fail("parent spine payload was not retained");
	}
	after_parent = ouro_heap_live_bytes();
	result = parent;
	for (i = 0; i < 32; i++) {
		ouro_v *fields[2];
		ouro_heap_context *context = ouro_heap_context_enter();
		fields[0] = result;
		fields[1] = ouro_string_codes("nested-wrap");
		result = ouro_heap_context_leave(context, ouro_ctor(0, 2, fields));
	}
	inner = result;
	for (i = 0; i < 32; i++) {
		if (inner == 0 || inner->tag != 0 || inner->n != 2) {
			free(bytes);
			return fail("shared-parent wrapper chain was damaged");
		}
		inner = OURO_F(inner, 0);
	}
	if (inner != parent) {
		free(bytes);
		return fail("leave recopied a caller-owned intern/AST spine");
	}
	if (!packed_eq(inner, bytes, size)) {
		free(bytes);
		return fail("shared parent payload was not readable after leave");
	}
	free(bytes);
	after_wraps = ouro_heap_live_bytes();
	/* Quadratic recopy of the 1 MiB parent would add tens of MiB. */
	if (after_wraps > after_parent + 4ULL * 1024ULL * 1024ULL)
		return fail("leave recopied the caller-owned spine into the parent heap");
	return 0;
}

static ouro_v *recheck_node1(int tag, ouro_v *value)
{
	ouro_v *fields[1] = {value};
	return ouro_ctor(tag, 1, fields);
}

static ouro_v *recheck_node2(int tag, ouro_v *first, ouro_v *second)
{
	ouro_v *fields[2] = {first, second};
	return ouro_ctor(tag, 2, fields);
}

/* Constructor tags follow core.ouro, file_check_model.ouro and
   checked_program.ouro. Public CheckedProgram data must be replayed even
   when it was assembled by a caller, including late invalid declarations. */
static ouro_v *recheck_program(unsigned long count, unsigned long depth, int error)
{
	ouro_v *nil = ouro_ctor(0, 0, 0);
	ouro_v *natural = recheck_node1(6, ouro_nat(1)); /* CConst 1 */
	ouro_v *constant = recheck_node1(6, ouro_nat(2));
	ouro_v *sort = recheck_node1(1, ouro_nat(0)); /* CSort 0 */
	ouro_v *fields[4] = {ouro_nat(1), sort, nil, nil};
	ouro_v *entries = recheck_node2(1, ouro_ctor(0, 3, fields), nil);
	ouro_v *bodies = nil;
	ouro_v *cursor;
	unsigned long index;
	fields[0] = ouro_nat(2); fields[1] = natural;
	entries = recheck_node2(1, ouro_ctor(0, 3, fields), entries);
	for (index = 0; index < count + (error == 1 ? 1UL : 0UL); index++) {
		ouro_v *typ = natural;
		ouro_v *body = constant;
		unsigned long level;
		for (level = 0; level < depth; level++) {
			typ = recheck_node2(2, natural, typ); /* CPi */
			body = recheck_node2(3, natural, body); /* CLam */
		}
		fields[0] = ouro_nat(index + 3);
		fields[1] = index == count ? natural : typ;
		fields[2] = recheck_node1(1, index == count ? sort : body); /* Just */
		entries = recheck_node2(1, ouro_ctor(0, 3, fields), entries);
	}
	if (error != 3)
		for (cursor = entries; cursor->tag == 1; cursor = OURO_F(cursor, 1)) {
			ouro_v *entry = OURO_F(cursor, 0);
			ouro_v *body = OURO_F(entry, 2);
			if (body->tag == 1)
				bodies = recheck_node2(1, recheck_node2(0, OURO_F(entry, 0), OURO_F(body, 0)), bodies);
		}
	fields[0] = nil; fields[1] = ouro_nat(count + 4);
	fields[2] = nil; fields[3] = ouro_nat(0);
	fields[0] = ouro_ctor(0, 4, fields); /* MkIntern */
	fields[1] = entries; fields[2] = bodies;
	return ouro_ctor(0, 3, fields);
}

static int recheck_length(ouro_v *items, unsigned long expected)
{
	unsigned long actual = 0;
	while (items != 0 && items->tag == 1 && items->n == 2) {
		actual++;
		items = OURO_F(items, 1);
	}
	return items != 0 && items->tag == 0 && items->n == 0 && actual == expected;
}

static int recheck_result(ouro_v *result, int error, unsigned long count)
{
	ouro_v *value;
	if (result == 0 || result->n != 1)
		return 0;
	value = OURO_F(result, 0);
	if (error >= 0)
		return result->tag == 0 && value != 0 && value->tag == error &&
			(error != 1 || (value->n == 3 && as_nat(OURO_F(value, 0)) == count + 3));
	return result->tag == 1 && value != 0 && value->tag == 0 && value->n == 3 &&
		recheck_length(OURO_F(value, 1), count + 2) && recheck_length(OURO_F(value, 2), count);
}

static int recheck_check(const char *mode)
{
	unsigned long count = strcmp(mode, "recheck-scale") == 0 ? 8192 : 4096;
	unsigned long depth = strcmp(mode, "recheck-scale") == 0 ? 64 : 24;
	int expected = -1;
	ouro_v *program;
	ouro_v *sentinel;
	ouro_v *recheck;
	ouro_v *fuel;
	ouro_v *result;
	if (strcmp(mode, "recheck-late-invalid") == 0)
		expected = 1;
	else if (strcmp(mode, "recheck-missing-bodies") == 0)
		expected = 3;
	else if (strcmp(mode, "recheck-zero-fuel") == 0) {
		expected = 0;
		count = 32;
	}
	program = ouro_keep(recheck_program(count, depth, expected));
	sentinel = ouro_string_codes("caller survives exact replay");
	recheck = export_value("lower_recheck_program");
	fuel = ouro_nat(expected == 0 ? 0 : 200000);
	result = ouro_apply(ouro_apply(recheck, fuel), program);
	if (!recheck_result(result, expected, count))
		return fail("recheck changed declaration, metadata or body result");
	if (strcmp(mode, "recheck-retained") == 0) {
		ouro_v *first = result;
		ouro_v *partial = ouro_apply(recheck, fuel);
		result = ouro_apply(ouro_apply(recheck, ouro_nat(0)), program);
		if (!recheck_result(result, 0, count) || !recheck_result(first, -1, count))
			return fail("recheck failure released a prior result");
		result = ouro_apply(partial, program);
		if (!recheck_result(result, -1, count) || !recheck_result(first, -1, count))
			return fail("recheck released a partial application or prior result");
	}
	if (!packed_eq(sentinel, (const unsigned char *)"caller survives exact replay", 28) ||
	    !recheck_length(OURO_F(program, 1), count + (expected == 1 ? 3UL : 2UL)))
		return fail("recheck released the caller graph");
	return 0;
}

int main(int argc, char **argv)
{
	int result;
	ouro_rt_warmup();
	if (argc == 3 && strcmp(argv[1], "caller-output") == 0)
		result = caller_output_check(argc, argv);
	else if (argc == 2 && strcmp(argv[1], "retained-result") == 0)
		result = retained_result_check();
	else if (argc == 2 && strcmp(argv[1], "typed-failure") == 0)
		result = typed_failure_check();
	else if (argc == 2 && strcmp(argv[1], "nested-context") == 0)
		result = nested_context_check();
	else if (argc == 2 && strcmp(argv[1], "allocation-context") == 0)
		result = allocation_context_check();
	else if (argc == 2 && strcmp(argv[1], "shared-parent-spine") == 0)
		result = shared_parent_spine_check();
	else if (argc == 2 && (strcmp(argv[1], "recheck-scale") == 0 ||
		strcmp(argv[1], "recheck-retained") == 0 || strcmp(argv[1], "recheck-late-invalid") == 0 ||
		strcmp(argv[1], "recheck-missing-bodies") == 0 || strcmp(argv[1], "recheck-zero-fuel") == 0))
		result = recheck_check(argv[1]);
	else
		return 2;
	if (result == 0)
		printf("FRONTEND_LINK_SELFTEST: passed %s\n", argv[1]);
	return result;
}
