/* Compare the C-host codegen seam with its generated canonical callbacks.
   Including the adapter keeps raw callbacks out of the production API. */
#ifndef OURO_FE_FLAT_EXPORTS
#define OURO_FE_FLAT_EXPORTS
#endif
#include "frontend_link.c"
#include "ouro_host_selftest.h"
#include "ouro_io.h"

static ouro_v *test_nil(void)
{
	return ouro_ctor(0, 0, 0);
}

static ouro_v *test_cons(ouro_v *head, ouro_v *tail)
{
	return ouro_ctor(1, 2, (ouro_v *[]){head, tail});
}

static ouro_v *test_use(unsigned long id)
{
	return ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(id)});
}

static ouro_v *test_local(unsigned long id, int type)
{
	return ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(id), ouro_ctor(type, 0, 0)});
}

static ouro_v *test_slot(unsigned long id, int type, unsigned long offset)
{
	return ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(id),
		ouro_ctor(type, 0, 0), ouro_nat(offset)});
}

static ouro_v *test_call(int may_gc, ouro_v *dest, ouro_v *args)
{
	return ouro_ctor(10, 4, (ouro_v *[]){ouro_ctor(may_gc, 0, 0), dest,
		ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(7)}), args});
}

static int test_fail(const char *message)
{
	fprintf(stderr, "FRONTEND_CODEGEN_SELFTEST: FAIL %s\n", message);
	return 1;
}

static ouro_v *test_apply6(ouro_v *callback, ouro_v **args)
{
	int i;
	for (i = 0; i < 6; i++)
		callback = ouro_apply(callback, args[i]);
	return callback;
}

static ouro_v *test_capture(ouro_env *env, ouro_v *value)
{
	ouro_v *args[6];
	ouro_env *item;
	int count = 0;
	int i;
	for (item = env; item != 0; item = item->next)
		count++;
	if (count < 5)
		return ouro_clos(test_capture, ouro_cons(value, env));
	for (i = 4; i >= 0; i--, env = env->next)
		args[i] = env->v;
	args[5] = value;
	if (value->tag == 4 && value->n == 1)
		return ouro_ctor(0, 1, &value); /* Left NativeMissingLabel */
	return ouro_ctor(0, 6, args);
}

static int test_diagnostic_source_decoder(void)
{
	static const char source[] = "source\ntext";
	char *decoded;
	size_t n = 99;
	int ok;
	decoded = src_from_codes(0, &n);
	ok = decoded == 0 && n == 0;
	free(decoded);
	if (!ok)
		return test_fail("absent diagnostic source was decoded as text");
	n = 99;
	decoded = src_from_codes(test_nil(), &n);
	ok = decoded != 0 && n == 0 && decoded[0] == 0;
	free(decoded);
	if (!ok)
		return test_fail("empty diagnostic source did not remain empty text");
	n = 99;
	decoded = src_from_codes(ouro_string_codes(source), &n);
	ok = decoded != 0 && n == sizeof source - 1 && strcmp(decoded, source) == 0;
	free(decoded);
	if (!ok)
		return test_fail("diagnostic source text or byte length changed");
	return 0;
}

static int test_forwarded_arguments(void)
{
	ouro_v *args[6];
	ouro_v *wrapped = ouro_wrap_codegen_block(ouro_clos(test_capture, 0));
	ouro_v *out;
	int i;
	if (test_diagnostic_source_decoder() != 0)
		return 1;
	for (i = 0; i < 6; i++)
		args[i] = ouro_ctor(40 + i, 0, 0);
	/* The unsupported block forces the wrapper's ordinary raw fallback. */
	out = test_apply6(wrapped, args);
	if (out == 0 || out->tag != 0 || out->n != 6)
		return test_fail("fallback returned a partial closure");
	for (i = 0; i < 6; i++)
		if (OURO_F(out, i) != args[i])
			return test_fail("fallback argument identity or order");
	args[5] = ouro_ctor(4, 1, (ouro_v *[]){ouro_nat(99)});
	out = test_apply6(wrapped, args);
	if (out == 0 || out->tag != 0 || out->n != 1 || OURO_F(out, 0) != args[5])
		return test_fail("fallback did not preserve a typed raw failure");
	return g_cgb_fallback == 2UL ? 0 : test_fail("fallback was not exercised");
}

static int test_nat_lists_equal(ouro_v *left, ouro_v *right)
{
	if (left != 0 && right != 0 && left->tag == OURO_TAG_BYTES
	    && right->tag == OURO_TAG_BYTES)
		return left->n >= 0 && left->n == right->n
			&& (left->n == 0 || (left->u.s != 0 && right->u.s != 0
				&& memcmp(left->u.s, right->u.s, (size_t)left->n) == 0));
	ouro_v **lhs = 0;
	ouro_v **rhs = 0;
	int nl = 0, nr = 0;
	int same = 1;
	int i;
	if (host_list_collect(left, &lhs, &nl, 0) != 0
	    || host_list_collect(right, &rhs, &nr, 0) != 0 || nl != nr)
		same = 0;
	for (i = 0; same && i < nl; i++)
		if (as_nat(lhs[i]) != as_nat(rhs[i]))
			same = 0;
	free(lhs);
	free(rhs);
	return same;
}

static int test_bytes_equal(ouro_v *fast, ouro_v *pure)
{
	ouro_v *assemble = FIND(lo, "codegen_assemble");
	ouro_v *left;
	ouro_v *right;
	if (fast == 0 || pure == 0 || fast->tag != 1 || pure->tag != 1
	    || fast->n != 1 || pure->n != 1)
		return 0;
	left = ouro_apply(ouro_apply(ouro_apply(assemble, OURO_F(fast, 0)),
		ouro_nat(4096)), ouro_nat(0));
	right = ouro_apply(ouro_apply(ouro_apply(assemble, OURO_F(pure, 0)),
		ouro_nat(4096)), ouro_nat(0));
	if (left == 0 || right == 0 || left->tag != 1 || right->tag != 1
	    || left->n != 1 || right->n != 1)
		return 0;
	return test_nat_lists_equal(OURO_F(OURO_F(left, 0), 0),
		OURO_F(OURO_F(right, 0), 0));
}

/* Count only the zeroing stores before the first call's argument load. */
static int test_clear_prefix(ouro_v *result, unsigned long live_offset,
	unsigned long dead_offset, int expect_clear)
{
	ouro_v **atoms = 0;
	int n = 0, i;
	int live = 0, dead = 0;
	if (result == 0 || result->tag != 1 || result->n != 1
	    || host_list_collect(OURO_F(result, 0), &atoms, &n, 0) != 0) {
		free(atoms);
		return 0;
	}
	for (i = 0; i < n; i++) {
		ouro_v *ins;
		ouro_v *addr;
		if (atoms[i] == 0 || atoms[i]->tag != 0 || atoms[i]->n != 1)
			continue;
		ins = OURO_F(atoms[i], 0);
		if (ins->tag == 3) /* first X64Load: argument loading starts */
			break;
		if (ins->tag != 4 || ins->n != 3)
			continue;
		addr = OURO_F(ins, 1);
		if (addr->tag == 0 && addr->n == 2) {
			unsigned long offset;
			unsigned long bytes[4];
			int backward;
			if (x64enc_dec_disp(OURO_F(addr, 1), bytes, &backward) != 0 || backward)
				continue;
			offset = bytes[0] | (bytes[1] << 8) | (bytes[2] << 16) | (bytes[3] << 24);
			live += offset == live_offset;
			dead += offset == dead_offset;
		}
	}
	free(atoms);
	return live == 0 && dead == expect_clear;
}

static ouro_v *test_replace_field(ouro_v *value, int index, ouro_v *replacement)
{
	ouro_v *fields[7];
	int i;
	if (value == 0 || value->tag < 0 || value->n > 7 || index < 0 || index >= value->n)
		return 0;
	for (i = 0; i < value->n; i++)
		fields[i] = i == index ? replacement : OURO_F(value, i);
	return ouro_ctor(value->tag, value->n, fields);
}

static int test_root_clear_context(void)
{
	ouro_v *slots = test_nil();
	ouro_v *live = test_cons(ouro_nat(0), test_cons(ouro_nat(127), test_nil()));
	ouro_v *wrapped = FIND(lo, "codegen_clear_dead_roots");
	ouro_v *reference;
	ouro_v *first = 0, *last = 0;
	ouro_heap_context *context;
	unsigned long long before, retained, start;
	int i;
	if (g_raw_clear_roots == 0)
		return test_fail("root-clear lifetime hook missing");
	for (i = 127; i >= 0; i--)
		slots = test_cons(test_slot((unsigned long)i, 6,
			4096UL + 8UL * (unsigned long)i), slots);
	before = ouro_heap_live_bytes();
	context = ouro_heap_context_enter();
	reference = ouro_apply(ouro_apply(g_raw_clear_roots, slots), live);
	reference = ouro_heap_context_leave(context, reference);
	retained = ouro_heap_live_bytes() - before;
	start = ouro_heap_live_bytes();
	for (i = 0; i < 64; i++) {
		last = ouro_apply(ouro_apply(wrapped, slots), live);
		if (i == 0)
			first = last;
		if (ouro_heap_live_bytes() - start >
		    (unsigned long long)(i + 1) * (retained + 4096ULL) + 1048576ULL)
			return test_fail("root-clear temporary work retained");
	}
	if (!test_bytes_equal(cgn_right(first), cgn_right(reference))
	    || !test_bytes_equal(cgn_right(last), cgn_right(reference)))
		return test_fail("root-clear retained bytes changed");
	return 0;
}

static ouro_v *test_apply(ouro_v *function, ouro_v **arguments, int count)
{
	int i;
	for (i = 0; i < count; i++)
		function = ouro_apply(function, arguments[i]);
	return function;
}

static int test_pe_byte_lists_equal(ouro_v *left, ouro_v *right)
{
	char lhs[32768], rhs[32768];
	int nl = codes_to_buf(left, lhs, sizeof(lhs));
	int nr = codes_to_buf(right, rhs, sizeof(rhs));
	return nl >= 0 && nl == nr && memcmp(lhs, rhs, (size_t)nl) == 0;
}

static int test_pe_value_equal(ouro_v *left, ouro_v *right)
{
	unsigned long a, b;
	int i;
	if (left == right)
		return 1;
	if (left == 0 || right == 0)
		return 0;
	if (left->tag == OURO_TAG_BIG_NAT || right->tag == OURO_TAG_BIG_NAT) {
		ouro_v *equal;
		if ((left->tag != OURO_TAG_NAT && left->tag != OURO_TAG_BIG_NAT)
		    || (right->tag != OURO_TAG_NAT && right->tag != OURO_TAG_BIG_NAT))
			return 0;
		equal = ouro_apply(ouro_apply(ouro_fast("eqNat"), left), right);
		return equal != 0 && equal->tag == 0 && equal->n == 0;
	}
	if (left->tag == OURO_TAG_NAT || right->tag == OURO_TAG_NAT)
		return ouro_nat_to_ulong(left, &a) && ouro_nat_to_ulong(right, &b) && a == b;
	if (left->tag == OURO_TAG_BYTES || right->tag == OURO_TAG_BYTES
	    || left->tag == OURO_TAG_CAT || right->tag == OURO_TAG_CAT)
		return test_pe_byte_lists_equal(left, right);
	if (left->tag < 0 || left->tag != right->tag || left->n != right->n)
		return 0;
	for (i = 0; i < left->n; i++)
		if (!test_pe_value_equal(OURO_F(left, i), OURO_F(right, i)))
			return 0;
	return 1;
}

static ouro_v *test_contract_scoped(ouro_v *function, ouro_v **arguments, int count)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = test_apply(function, arguments, count);
	return ouro_heap_context_leave(context, result);
}

static unsigned long long test_preflight_scope_start, test_preflight_scratch_bytes;
static int test_preflight_scope_count, test_preflight_scratch_retained;

static ouro_v *test_preflight_scratch(ouro_env *env, ouro_v *name)
{
	unsigned long long before = ouro_heap_live_bytes();
	int i;
	for (i = 0; i < 8192; i++)
		(void)ouro_ctor(0, 1, &name);
	test_preflight_scratch_bytes = ouro_heap_live_bytes() - before;
	return ouro_apply(ouro_get(env, 0), name);
}

static ouro_v *test_preflight_scope(ouro_env *env, ouro_v *item)
{
	unsigned long long live = ouro_heap_live_bytes();
	/* The next callback sees the caller bank after the previous item leaves. */
	if (test_preflight_scope_count++ == 0)
		test_preflight_scope_start = live;
	else if (live > test_preflight_scope_start
		 && live - test_preflight_scope_start >= test_preflight_scratch_bytes)
		test_preflight_scratch_retained = 1;
	return bounded_compile_program_item_scope(env,
		ouro_clos(test_preflight_scratch, ouro_cons(item, 0)));
}

static ouro_v *test_preflight_decl(unsigned long name, int surface_tag, unsigned long value)
{
	ouro_v *surface = ouro_ctor(surface_tag, 1, (ouro_v *[]){ouro_nat(value)});
	return ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(name), surface});
}

static int test_preflight_context(void)
{
	ouro_v *raw = FIND(co, "compile_program_with_location");
	ouro_v *legacy = FIND(co, "compile_program_with_location_with");
	ouro_v *indexed = FIND(co, "compile_program_with_location_indexed_with");
	ouro_v *legacy_item = bounded_compile_program_item_scope(0, FIND(co, "compile_program_item_pure"));
	ouro_v *sort = test_preflight_decl(7, 1, 0);
	ouro_v *success = test_cons(sort, test_cons(test_preflight_decl(8, 0, 7), test_nil()));
	ouro_v *duplicate = test_cons(sort, test_cons(test_preflight_decl(7, 6, 9), test_nil()));
	ouro_v *future = test_cons(test_preflight_decl(7, 6, 9),
		test_cons(test_preflight_decl(9, 1, 0), test_nil()));
	ouro_v *inputs[] = {test_nil(), success, duplicate, future};
	ouro_v *expected, *probed;
	int i;
	for (i = 0; i < 4; i++) {
		expected = test_contract_scoped(raw, &inputs[i], 1);
		if (expected == 0 || expected->tag != (i < 2 ? 1 : 0)
		    || !test_pe_value_equal(expected, bounded_compile_program(0, inputs[i]))
		    || !test_pe_value_equal(expected,
			test_contract_scoped(legacy, (ouro_v *[]){legacy_item, inputs[i]}, 2)))
			return test_fail("indexed and legacy preflight outcomes differ");
	}
	test_preflight_scope_count = 0;
	test_preflight_scratch_retained = 0;
	probed = test_contract_scoped(indexed,
		(ouro_v *[]){ouro_clos(test_preflight_scope, 0), success}, 2);
	expected = test_contract_scoped(raw, &success, 1);
	if (test_preflight_scope_count != 2 || test_preflight_scratch_bytes < 8192
	    || test_preflight_scratch_retained || !test_pe_value_equal(probed, expected))
		return test_fail("indexed preflight did not reclaim item scratch or retain its result");
	return 0;
}

static ouro_v *test_bounds_limits(unsigned long nodes, unsigned long bytes,
	unsigned long flow)
{
	return ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(nodes), ouro_nat(bytes), ouro_nat(flow)});
}

static ouro_v *test_bounds_program(void)
{
	unsigned char bytes[256];
	ouro_v *objects = test_nil(), *payload, *function, *library, *signature;
	ouro_v *block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0), test_nil(), ouro_ctor(3, 0, 0)});
	int i;
	for (i = 0; i < 256; i++)
		bytes[i] = (unsigned char)i;
	payload = ouro_packed(bytes, sizeof(bytes));
	for (i = 63; i >= 0; i--)
		objects = test_cons(ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(100UL + (unsigned long)i),
			ouro_ctor(1, 0, 0), payload}), objects);
	function = ouro_ctor(0, 7, (ouro_v *[]){ouro_nat(1), ouro_string_codes("bounds"),
		test_nil(), test_nil(), test_nil(), ouro_nat(0), test_cons(block, test_nil())});
	signature = ouro_ctor(0, 2, (ouro_v *[]){test_cons(ouro_ctor(1, 0, 0), test_nil()), test_nil()});
	library = ouro_ctor(0, 2, (ouro_v *[]){ouro_string_codes("probe.dll"),
		test_cons(ouro_ctor(0, 4, (ouro_v *[]){ouro_ctor(0, 0, 0), ouro_nat(7),
			ouro_string_codes("external"), signature}), test_nil())});
	return ouro_ctor(0, 4, (ouro_v *[]){test_cons(function, test_nil()), objects,
		test_cons(library, test_nil()), ouro_nat(1)});
}

static int test_mir_bounds_context(int check_memory)
{
	ouro_v *wrapped = FIND(lo, "mir_check_bounds"), *program = test_bounds_program();
	ouro_v *empty = ouro_ctor(0, 4, (ouro_v *[]){test_nil(), test_nil(), test_nil(), ouro_nat(0)});
	ouro_v *limits[10], *expected[10], *args[2], *snapshots[4];
	ouro_v *right = ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	ouro_v *left = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	ouro_v *good, *bad, *first = 0, *last = 0, *caller, *caller_snapshot;
	ouro_v *nested_good, *nested_bad, *nested_result, *retained;
	ouro_env *good_captures, *bad_captures;
	ouro_heap_context *nested;
	unsigned long mark_n, mark_used, after_n, after_used;
	unsigned long long start, live, budget;
	int i, rounds = check_memory ? 32 : 4;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS)
		return test_fail("MIR bounds export missing");
	/* The fixture spends 8 function nodes, 20 library nodes and 64 data nodes. */
	limits[0] = test_bounds_limits(0, 0, 0);
	limits[1] = test_bounds_limits(92, 16384, 64);
	limits[2] = test_bounds_limits(0, 16384, 64);
	limits[3] = test_bounds_limits(8, 16384, 64);
	limits[4] = test_bounds_limits(91, 16384, 64);
	limits[5] = test_bounds_limits(92, 16383, 64);
	limits[6] = test_bounds_limits(16777217UL, 16384, 64);
	limits[7] = test_bounds_limits(92, 16777217UL, 64);
	limits[8] = test_bounds_limits(92, 16384, 16777217UL);
	limits[9] = test_bounds_limits(92, 16384, 0);
	for (i = 0; i < 10; i++) {
		expected[i] = i == 0 || i == 1 || i == 9 ? right : left;
		args[0] = limits[i]; args[1] = i == 0 ? empty : program;
		if (!test_pe_value_equal(test_contract_scoped(wrapped, args, 2), expected[i]))
			return test_fail("MIR bounds exact scoped outcome");
	}
	snapshots[0] = ouro_clone_perm_deep(program);
	snapshots[1] = ouro_clone_perm_deep(limits[1]);
	snapshots[2] = ouro_clone_perm_deep(limits[5]);
	snapshots[3] = ouro_clone_perm_deep(empty);
	ouro_heap_mark();
	ouro_heap_mark_save(&mark_n, &mark_used);
	caller = ouro_string_codes("unrelated bounds caller survives");
	caller_snapshot = ouro_clone_perm_deep(caller);
	good = ouro_apply(wrapped, limits[1]);
	bad = ouro_apply(wrapped, limits[5]);
	if (good == 0 || bad == 0 || good->tag != OURO_TAG_CLOS || bad->tag != OURO_TAG_CLOS)
		return test_fail("MIR bounds reusable partial missing");
	good_captures = good->u.c.env;
	bad_captures = bad->u.c.env;
	for (i = 0; i < 10; i++) {
		args[0] = limits[i]; args[1] = i == 0 ? empty : program;
		if (!test_pe_value_equal(test_apply(wrapped, args, 2), expected[i]))
			return test_fail("MIR bounds exact direct outcome");
	}
	start = ouro_heap_live_bytes();
	for (i = 0; i < rounds; i++) {
		last = ouro_apply((i & 1) == 0 ? good : bad, program);
		if (i == 0)
			first = last;
		if (!test_pe_value_equal(last, (i & 1) == 0 ? right : left)
		    || !test_pe_value_equal(first, right)
		    || good->u.c.env != good_captures || bad->u.c.env != bad_captures)
			return test_fail("MIR bounds complete result or reusable capture changed");
		ouro_heap_mark_save(&after_n, &after_used);
		if (after_n != mark_n || after_used != mark_used
		    || !test_pe_value_equal(caller, caller_snapshot))
			return test_fail("MIR bounds changed outer mark or unrelated caller");
		live = ouro_heap_live_bytes();
		/* Complete Unit/resource results are small. Work cannot grow with retained results. */
		budget = 131072ULL + (unsigned long long)(i + 1) * 4096ULL;
		if (check_memory && (live < start || live - start > budget)) {
			fprintf(stderr, "MIR_BOUNDS_CONTEXT: calls=%d live_delta=%llu budget=%llu\n",
				i + 1, live < start ? 0ULL : live - start, budget);
			return test_fail("MIR bounds temporary work retained");
		}
	}
	if (!test_pe_value_equal(program, snapshots[0])
	    || !test_pe_value_equal(limits[1], snapshots[1])
	    || !test_pe_value_equal(limits[5], snapshots[2])
	    || !test_pe_value_equal(empty, snapshots[3]))
		return test_fail("MIR bounds changed complete caller inputs");
	nested = ouro_heap_context_enter();
	nested_good = ouro_apply(wrapped, limits[1]);
	nested_bad = ouro_apply(wrapped, limits[5]);
	nested_result = ouro_heap_context_leave(nested, ouro_ctor(0, 4, (ouro_v *[]){
		ouro_apply(nested_good, program), ouro_apply(nested_bad, program), nested_good, nested_bad}));
	if (!test_pe_value_equal(OURO_F(nested_result, 0), right)
	    || !test_pe_value_equal(OURO_F(nested_result, 1), left)
	    || !test_pe_value_equal(ouro_apply(OURO_F(nested_result, 2), program), right)
	    || !test_pe_value_equal(ouro_apply(OURO_F(nested_result, 3), empty), right)
	    || !test_pe_value_equal(ouro_apply(good, program), right)
	    || !test_pe_value_equal(ouro_apply(bad, program), left)
	    || !test_pe_value_equal(caller, caller_snapshot))
		return test_fail("MIR bounds nested result or earlier partial changed");
	ouro_heap_mark_save(&after_n, &after_used);
	if (after_n != mark_n || after_used != mark_used)
		return test_fail("MIR bounds nested call changed outer mark");
	retained = ouro_clone_perm_deep(ouro_ctor(0, 5, (ouro_v *[]){first, last,
		OURO_F(nested_result, 2), OURO_F(nested_result, 3), caller}));
	ouro_heap_reset();
	memset(ouro_alloc(262144UL), 0xA5, 262144UL);
	ouro_heap_reset();
	if (!test_pe_value_equal(OURO_F(retained, 0), right)
	    || !test_pe_value_equal(OURO_F(retained, 1), left)
	    || !test_pe_value_equal(ouro_apply(OURO_F(retained, 2), program), right)
	    || !test_pe_value_equal(ouro_apply(OURO_F(retained, 3), program), left)
	    || !test_pe_value_equal(OURO_F(retained, 4), caller_snapshot))
		return test_fail("MIR bounds survivor or partial changed after caller reset");
	return 0;
}

/* The unused data payload stays in the caller phase. Partial application
   must retain its identity without copying its complete bytes. */
static ouro_v *test_mir_function_program(void)
{
	const unsigned long size = 2UL * 1024UL * 1024UL;
	unsigned char *bytes = (unsigned char *)ouro_alloc(size);
	ouro_v *program = test_bounds_program();
	ouro_v *object;
	memset(bytes, 0x5A, (size_t)size);
	object = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(10000),
		ouro_ctor(1, 0, 0), ouro_packed(bytes, size)});
	return test_replace_field(program, 1, test_cons(object, test_nil()));
}

/* The small-value oracle has a 32 KiB byte buffer. Use the full-length
   comparator for this fixture's complete packed payload. */
static int test_mir_function_program_same(ouro_v *actual, ouro_v *expected)
{
	ouro_v *actual_objects, *expected_objects, *actual_data, *expected_data;
	if (actual == 0 || expected == 0 || actual->tag != 0 || expected->tag != 0
	    || actual->n != 4 || expected->n != 4)
		return 0;
	actual_objects = OURO_F(actual, 1); expected_objects = OURO_F(expected, 1);
	if (actual_objects == 0 || expected_objects == 0 || actual_objects->tag != 1
	    || expected_objects->tag != 1 || actual_objects->n != 2 || expected_objects->n != 2)
		return 0;
	actual_data = OURO_F(actual_objects, 0); expected_data = OURO_F(expected_objects, 0);
	if (actual_data == 0 || expected_data == 0 || actual_data->tag != 0
	    || expected_data->tag != 0 || actual_data->n != 3 || expected_data->n != 3)
		return 0;
	return test_pe_value_equal(OURO_F(actual, 0), OURO_F(expected, 0))
		&& test_pe_value_equal(OURO_F(actual, 2), OURO_F(expected, 2))
		&& test_pe_value_equal(OURO_F(actual, 3), OURO_F(expected, 3))
		&& test_pe_value_equal(OURO_F(actual_objects, 1), OURO_F(expected_objects, 1))
		&& test_pe_value_equal(OURO_F(actual_data, 0), OURO_F(expected_data, 0))
		&& test_pe_value_equal(OURO_F(actual_data, 1), OURO_F(expected_data, 1))
		&& test_nat_lists_equal(OURO_F(actual_data, 2), OURO_F(expected_data, 2));
}

static int test_mir_function_partial(void)
{
	ouro_v *wrapped = FIND(lo, "mir_check_function"), *program = test_mir_function_program();
	ouro_v *snapshot = ouro_clone_perm_deep(program), *partial;
	unsigned long long before_live = ouro_heap_live_bytes();
	unsigned long long before_total = ouro_heap_total_alloc_bytes();
	unsigned long long live, total;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS)
		return test_fail("MIR function export missing");
	partial = ouro_apply(wrapped, program);
	live = ouro_heap_live_bytes() - before_live;
	total = ouro_heap_total_alloc_bytes() - before_total;
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return test_fail("MIR function program partial missing");
	if (live > 4096ULL || total > 4096ULL) {
		fprintf(stderr, "MIR_FUNCTION_PARTIAL: payload_bytes=2097152 live_delta=%llu total_delta=%llu budget=4096\n",
			live, total);
		return test_fail("MIR function partial application copied caller MIR");
	}
	if (ouro_get(partial->u.c.env, 0) != program || !test_mir_function_program_same(program, snapshot))
		return test_fail("MIR function program partial changed borrowed input");
	return 0;
}

static int test_mir_function_context(void)
{
	ouro_v *wrapped = FIND(lo, "mir_check_function");
	ouro_v *identity = ouro_apply(ouro_apply(FIND(lo, "mir_check_function_with"),
		ouro_clos(ouro_host_test_run_unit, 0)), FIND(lo, "mir_check_declared_flow"));
	ouro_v *right = ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	ouro_v *left = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	ouro_v *flow = ouro_nat(16), *empty = ouro_nat(0), *program, *function, *snapshot;
	ouro_v *partial, *good, *bad, *caller, *caller_snapshot, *first = 0, *last = 0;
	ouro_v *nested_program, *nested_function, *nested_good, *nested_bad, *nested_result, *bundle, *retained;
	ouro_env *partial_env, *good_env, *bad_env;
	ouro_heap_context *nested;
	unsigned long mark_n, mark_used, after_n, after_used;
	unsigned long long start, live, budget;
	int i;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS)
		return test_fail("MIR function export missing");
	ouro_heap_mark();
	ouro_heap_mark_save(&mark_n, &mark_used);
	program = test_mir_function_program();
	function = OURO_F(OURO_F(program, 0), 0);
	snapshot = ouro_clone_perm_deep(program);
	caller = ouro_string_codes("unrelated function caller survives");
	caller_snapshot = ouro_clone_perm_deep(caller);
	if (!test_pe_value_equal(test_contract_scoped(identity, (ouro_v *[]){program, flow, function}, 3), right)
	    || !test_pe_value_equal(test_contract_scoped(identity, (ouro_v *[]){program, empty, function}, 3), left))
		return test_fail("MIR function canonical scoped outcomes");
	partial = ouro_apply(wrapped, program);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return test_fail("MIR function reusable program partial missing");
	good = ouro_apply(partial, flow); bad = ouro_apply(partial, empty);
	if (good == 0 || bad == 0 || good->tag != OURO_TAG_CLOS || bad->tag != OURO_TAG_CLOS)
		return test_fail("MIR function reusable partial missing");
	partial_env = partial->u.c.env; good_env = good->u.c.env; bad_env = bad->u.c.env;
	if (ouro_get(partial_env, 0) != program || ouro_get(good_env, 1) != program
	    || ouro_get(bad_env, 1) != program || ouro_get(good_env, 0) != flow || ouro_get(bad_env, 0) != empty)
		return test_fail("MIR function partial captures changed");
	start = ouro_heap_live_bytes();
	for (i = 0; i < 32; i++) {
		last = ouro_apply((i % 2) == 0 ? good : bad, function);
		if (i == 0) first = last;
		if (!test_pe_value_equal(last, (i % 2) == 0 ? right : left)
		    || !test_pe_value_equal(first, right))
			return test_fail("MIR function complete retained outcome changed");
		ouro_heap_mark_save(&after_n, &after_used);
		if (after_n != mark_n || after_used != mark_used
		    || !test_pe_value_equal(caller, caller_snapshot))
			return test_fail("MIR function caller mark or unrelated data changed");
		if (partial->u.c.env != partial_env || good->u.c.env != good_env || bad->u.c.env != bad_env
		    || ouro_get(partial_env, 0) != program || ouro_get(good_env, 1) != program
		    || ouro_get(bad_env, 1) != program || ouro_get(good_env, 0) != flow
		    || ouro_get(bad_env, 0) != empty || !test_mir_function_program_same(program, snapshot))
			return test_fail("MIR function borrowed input or partial changed");
		live = ouro_heap_live_bytes() - start;
		budget = 131072ULL + (unsigned long long)(i + 1) * 4096ULL;
		if (live > budget) {
			fprintf(stderr, "MIR_FUNCTION_CONTEXT: calls=%d live_delta=%llu budget=%llu\n", i + 1, live, budget);
			return test_fail("MIR function temporary work retained");
		}
	}
	nested = ouro_heap_context_enter();
	nested_program = test_mir_function_program();
	nested_function = OURO_F(OURO_F(nested_program, 0), 0);
	partial = ouro_apply(wrapped, nested_program);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return test_fail("MIR function nested program partial missing");
	nested_good = ouro_apply(partial, flow); nested_bad = ouro_apply(partial, empty);
	if (nested_good == 0 || nested_bad == 0 || nested_good->tag != OURO_TAG_CLOS || nested_bad->tag != OURO_TAG_CLOS)
		return test_fail("MIR function nested reusable partial missing");
	nested_result = ouro_apply(nested_good, nested_function);
	bundle = ouro_heap_context_leave(nested, ouro_ctor(0, 4,
		(ouro_v *[]){nested_program, nested_good, nested_bad, nested_result}));
	nested_program = OURO_F(bundle, 0); nested_good = OURO_F(bundle, 1); nested_bad = OURO_F(bundle, 2);
	nested_function = OURO_F(OURO_F(nested_program, 0), 0);
	if (ouro_get(nested_good->u.c.env, 1) != nested_program || ouro_get(nested_bad->u.c.env, 1) != nested_program
	    || !test_mir_function_program_same(nested_program, snapshot) || !test_pe_value_equal(OURO_F(bundle, 3), right)
	    || !test_pe_value_equal(ouro_apply(nested_good, nested_function), right)
	    || !test_pe_value_equal(ouro_apply(nested_bad, nested_function), left))
		return test_fail("MIR function complete nested partial survivor changed");
	ouro_heap_mark_save(&after_n, &after_used);
	if (after_n != mark_n || after_used != mark_used || !test_pe_value_equal(caller, caller_snapshot))
		return test_fail("MIR function nested call changed caller mark or data");
	retained = ouro_clone_perm_deep(ouro_ctor(0, 6,
		(ouro_v *[]){good, bad, first, last, caller, bundle}));
	ouro_fe_reset_mir_pins();
	ouro_heap_mark_restore(mark_n, mark_used);
	ouro_heap_reset();
	memset(ouro_alloc(262144UL), 0xA5, 262144UL);
	good = OURO_F(retained, 0); bad = OURO_F(retained, 1);
	program = ouro_get(good->u.c.env, 1); function = OURO_F(OURO_F(program, 0), 0);
	bundle = OURO_F(retained, 5); nested_program = OURO_F(bundle, 0);
	nested_function = OURO_F(OURO_F(nested_program, 0), 0);
	if (ouro_get(bad->u.c.env, 1) != program || !test_mir_function_program_same(program, snapshot)
	    || !test_pe_value_equal(OURO_F(retained, 2), right) || !test_pe_value_equal(OURO_F(retained, 3), left)
	    || !test_pe_value_equal(OURO_F(retained, 4), caller_snapshot)
	    || !test_pe_value_equal(ouro_apply(good, function), right) || !test_pe_value_equal(ouro_apply(bad, function), left)
	    || !test_mir_function_program_same(nested_program, snapshot)
	    || !test_pe_value_equal(ouro_apply(OURO_F(bundle, 1), nested_function), right)
	    || !test_pe_value_equal(ouro_apply(OURO_F(bundle, 2), nested_function), left))
		return test_fail("MIR function full survivor or partial changed after caller reset");
	return 0;
}

static int test_contract_case(ouro_v *raw, ouro_v *wrapped,
	ouro_v **arguments, ouro_v *expected)
{
	return test_pe_value_equal(test_contract_scoped(raw, arguments, 5), expected)
		&& test_pe_value_equal(test_apply(wrapped, arguments, 5), expected);
}

static ouro_v *test_contract_branch(ouro_env *env, ouro_v *unused)
{
	(void)unused;
	return ouro_apply(ouro_get(env, 1), ouro_get(env, 0));
}

/* Inputs are captured from the complete compiler-owned source pipeline. */
static ouro_v *test_check_inputs[3], *test_check_actual_result;
static int test_check_capture_count;

static ouro_v *test_check_capture_items(ouro_env *env, ouro_v *items)
{
	ouro_v *arguments[] = {ouro_get(env, 1), ouro_get(env, 0), items};
	ouro_v *result = test_apply(ouro_get(env, 2), arguments, 3);
	/* Retain the inputs and result before the compiler releases their phase. */
	ouro_v *snapshot = ouro_clone_perm_deep(ouro_ctor(0, 4,
		(ouro_v *[]){arguments[0], arguments[1], arguments[2], result}));
	int i;
	for (i = 0; i < 3; i++)
		test_check_inputs[i] = OURO_F(snapshot, i);
	test_check_capture_count++;
	test_check_actual_result = OURO_F(snapshot, 3);
	return result;
}

static ouro_v *test_check_capture_names(ouro_env *env, ouro_v *names)
{
	return ouro_clos(test_check_capture_items, ouro_cons(names, env));
}

static ouro_v *test_check_capture_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(test_check_capture_names, ouro_cons(fuel, env));
}

static ouro_v *test_check_source(ouro_v *checker, ouro_v *fuel, ouro_v *source)
{
	static const char *callbacks[] = {
		"lex_go_import", "driver_parse_file_visibility", "desugar_file",
		"rewrite_declarations", "lower_expr_env2", "compile_program",
		"driver_elaborate_surfaces", "elaborate", 0,
		"preprocess_imports_reg", "preprocess_records_reg"
	};
	ouro_v *compiler = FIND(pl, "pipeline_compile_checked_source");
	int i;
	for (i = 0; i < 11; i++)
		compiler = ouro_apply(compiler, i == 8 ? checker : FIND(pl, callbacks[i]));
	return test_apply(compiler, (ouro_v *[]){fuel, source}, 2);
}

static int test_check_case(ouro_v *raw, ouro_v *wrapped, ouro_v **args, ouro_v *expected)
{
	return test_pe_value_equal(test_contract_scoped(raw, args, 3), expected)
		&& test_pe_value_equal(test_apply(wrapped, args, 3), expected);
}

static ouro_v *test_check_error(ouro_v *name, int phase, ouro_v *failure)
{
	return ouro_ctor(1, 3, (ouro_v *[]){name, ouro_ctor(phase, 0, 0), failure});
}

static int test_check_module_context(void)
{
	static const char source[] =
		"intrinsic Word : Type := \"ouro.u32\"; def Alias : Type := Word; "
		"def identity (x : Alias) : Alias := x; axiom a : Alias;";
	static const char bad_source[] = "axiom A : Type; def wrong : A := Type;";
	ouro_v *wrapped = FIND(fc, "check_module"), *raw, *capture, *partial, *branch;
	ouro_v *args[3], *borrowed[5], *snapshots[5], *items[4], *cursor, *reference;
	ouro_v *source_codes = ouro_string_codes(source), *compiled, *replayed, *actual;
	ouro_v *first, *last, *first_name, *last_name, *duplicate, *missing_items, *expected;
	ouro_v *bad_compiled, *bad_expected, *bad_name, *bad_args[3], *resource;
	ouro_env *partial_env, *branch_env;
	unsigned long long before, retained, start;
	int i, j;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS
	    || wrapped->u.c.fn != import_token_fuel)
		return test_fail("source module lifetime hook missing");
	raw = ouro_apply(FIND(fc, "check_indexed_module_with"), FIND(fc, "check_indexed_declaration"));
	capture = ouro_clos(test_check_capture_fuel, ouro_cons(raw, 0));
	test_check_capture_count = 0;
	compiled = test_check_source(capture, ouro_nat(16000), source_codes);
	if (compiled == 0 || compiled->tag != 1 || compiled->n != 1 || test_check_capture_count != 1)
		return test_fail("module source acceptance and actual plan capture");
	for (i = 0; i < 3; i++) args[i] = test_check_inputs[i];
	reference = test_check_actual_result;
	if (reference == 0 || reference->tag != 0 || reference->n != 1
	    || !test_check_case(raw, wrapped, args, reference))
		return test_fail("complete raw and bounded source module result");
	actual = test_contract_scoped(FIND(pl, "compile_checked_source"),
		(ouro_v *[]){args[0], source_codes}, 2);
	if (!test_pe_value_equal(actual, compiled))
		return test_fail("complete public source compilation envelope changed");
	replayed = test_contract_scoped(FIND(lo, "lower_recheck_program"),
		(ouro_v *[]){args[0], OURO_F(compiled, 0)}, 2);
	if (replayed == 0 || replayed->tag != 1 || replayed->n != 1
	    || !test_pe_value_equal(OURO_F(replayed, 0), OURO_F(compiled, 0)))
		return test_fail("source module complete strict replay");
	cursor = args[2];
	for (i = 0; i < 4; i++) {
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2)
			return test_fail("actual ordered module plan length");
		items[i] = OURO_F(cursor, 0);
		cursor = OURO_F(cursor, 1);
	}
	if (cursor == 0 || cursor->tag != 0 || cursor->n != 0)
		return test_fail("actual ordered module plan tail");
	first_name = ouro_apply(FIND(fc, "file_item_name"), items[0]);
	last_name = ouro_apply(FIND(fc, "file_item_name"), items[3]);
	for (i = 0; i < 3; i++) borrowed[i] = args[i];
	borrowed[3] = compiled; borrowed[4] = source_codes;
	for (i = 0; i < 5; i++) snapshots[i] = ouro_clone_perm_deep(borrowed[i]);
	partial = test_apply(wrapped, args, 2);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS || partial->u.c.fn != import_token_state)
		return test_fail("actual source module partial application");
	partial_env = partial->u.c.env;
	branch = ouro_thunk(test_contract_branch, ouro_cons(args[2], ouro_cons(partial, 0)));
	branch_env = branch->u.c.env;
	before = ouro_heap_live_bytes();
	first = ouro_apply(partial, args[2]);
	retained = ouro_heap_live_bytes() - before;
	start = ouro_heap_live_bytes();
	for (i = 0; i < 16; i++) {
		ouro_heap_context *outer = ouro_heap_context_enter();
		ouro_heap_context *inner = ouro_heap_context_enter();
		for (j = 0; j < 1024; j++)
			(void)ouro_ctor(0, 2, (ouro_v *[]){ouro_nat((unsigned long)j), first});
		(void)ouro_heap_context_leave(inner, test_nil());
		last = ouro_case(test_nil(), 1, &branch);
		last = ouro_heap_context_leave(outer, last);
		if (!test_pe_value_equal(first, reference) || !test_pe_value_equal(last, reference))
			return test_fail("complete module survivors changed after nested contexts");
		if (ouro_heap_live_bytes() - start >
		    (unsigned long long)(i + 1) * (retained + 4096ULL) + 1048576ULL)
			return test_fail("source module temporary work retained");
		if (partial->u.c.env != partial_env || ouro_get(partial_env, 0) != args[1]
		    || ouro_get(partial_env, 1) != args[0]
		    || ouro_get(partial_env, 2) != ouro_get(wrapped->u.c.env, 0)
		    || branch->tag != OURO_TAG_THUNK || branch->u.c.fn != test_contract_branch
		    || branch->u.c.env != branch_env || ouro_get(branch_env, 0) != args[2]
		    || ouro_get(branch_env, 1) != partial || FIND(fc, "check_module") != wrapped)
			return test_fail("source module borrowed captures or lazy caller changed");
		for (j = 0; j < 5; j++)
			if (!test_pe_value_equal(borrowed[j], snapshots[j]))
				return test_fail("complete source module caller inputs changed");
	}
	duplicate = test_cons(items[0], test_cons(items[0], test_nil()));
	args[2] = duplicate;
	expected = test_check_error(first_name, 0, ouro_ctor(1, 1,
		(ouro_v *[]){ouro_ctor(8, 1, &first_name)}));
	if (!test_check_case(raw, wrapped, args, expected))
		return test_fail("full duplicate module declaration failure");
	resource = test_check_error(first_name, 0, ouro_ctor(3, 0, 0));
	args[0] = ouro_nat(0);
	if (!test_check_case(raw, wrapped, args, resource))
		return test_fail("zero module fuel precedes duplicate declaration");
	args[2] = borrowed[2];
	if (!test_check_case(raw, wrapped, args, resource))
		return test_fail("full zero-fuel module failure");
	args[1] = test_nil(); args[2] = test_nil();
	expected = test_check_error(ouro_nat(0), 0, ouro_ctor(3, 0, 0));
	if (!test_check_case(raw, wrapped, args, expected))
		return test_fail("empty module is checked after fuel");
	args[0] = ouro_nat(1);
	if (!test_check_case(raw, wrapped, args, ouro_ctor(0, 1, (ouro_v *[]){test_nil()})))
		return test_fail("complete empty source module result");
	args[0] = borrowed[0]; args[1] = borrowed[1];
	missing_items = test_cons(items[0], test_cons(items[1], test_cons(items[2], test_nil())));
	args[2] = missing_items;
	expected = test_check_error(last_name, 0, ouro_ctor(1, 1,
		(ouro_v *[]){ouro_ctor(1, 1, &last_name)}));
	if (!test_check_case(raw, wrapped, args, expected))
		return test_fail("full missing required source declaration failure");
	test_check_capture_count = 0;
	bad_compiled = test_check_source(capture, borrowed[0], ouro_string_codes(bad_source));
	if (bad_compiled == 0 || bad_compiled->tag != 0 || bad_compiled->n != 1
	    || test_check_capture_count != 1)
		return test_fail("actual invalid source plan capture");
	for (i = 0; i < 3; i++) bad_args[i] = test_check_inputs[i];
	cursor = bad_args[2];
	if (cursor == 0 || cursor->tag != 1 || cursor->n != 2)
		return test_fail("invalid source first declaration");
	cursor = OURO_F(cursor, 1);
	if (cursor == 0 || cursor->tag != 1 || cursor->n != 2)
		return test_fail("invalid source body declaration");
	bad_name = ouro_apply(FIND(fc, "file_item_name"), OURO_F(cursor, 0));
	bad_expected = test_check_error(bad_name, 2, ouro_ctor(0, 1,
		(ouro_v *[]){ouro_ctor(0, 0, 0)}));
	if (!test_pe_value_equal(test_check_actual_result, bad_expected)
	    || !test_check_case(raw, wrapped, bad_args, bad_expected))
		return test_fail("complete source body type failure");
	actual = test_contract_scoped(FIND(pl, "compile_checked_source"),
		(ouro_v *[]){borrowed[0], ouro_string_codes(bad_source)}, 2);
	if (!test_pe_value_equal(actual, bad_compiled)
	    || !test_pe_value_equal(first, reference))
		return test_fail("source failure envelope or earlier accepted result changed");
	for (i = 0; i < 5; i++)
		if (!test_pe_value_equal(borrowed[i], snapshots[i]))
			return test_fail("source failure changed earlier complete caller inputs");
	return 0;
}

static int test_lower_contract_context(void)
{
	static const char source[] =
		"intrinsic Effect : Type -> Type := \"ouro.runtime\"; "
		"intrinsic Pointer : Type -> Type := \"ouro.raw_ptr\"; "
		"intrinsic Word : Type := \"ouro.u32\"; intrinsic Size : Type := \"ouro.usize\"; "
		"def AliasWord : Type := Word; def AliasPointer (A : Type) : Type := Pointer A; "
		"def Deferred (A : Type) : Type := Effect A; "
		"extern contract_probe : AliasPointer Size -> AliasPointer AliasWord -> Deferred AliasWord := "
		"\"windows-x86_64\" \"win64\" \"kernel32.dll\" \"GetLastError\" \"nogc\";";
	ouro_v *args[5], *captures[7], *snapshots[7], *program, *rechecked, *entries, *sig, *source_codes;
	ouro_v *selected, *entry, *id, *typ, *binding, *normal, *codomain, *expected, *none_expected;
	ouro_v *wrapped = FIND(lo, "lower_make_contract_indexed"), *raw, *partial, *branch;
	ouro_v *first = 0, *last = 0, *saved, *malformed, *resource, *malformed_error, *unsupported;
	ouro_env *partial_env, *branch_env;
	unsigned long mark_n, mark_used, after_n, after_used;
	int i;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS
	    || wrapped->u.c.fn != lower_make_contract_fuel)
		return test_fail("indexed contract lifetime hook missing");
	raw = ouro_get(wrapped->u.c.env, 0);
	if (raw == 0 || raw->tag != OURO_TAG_CLOS || raw->u.c.fn == lower_make_contract_fuel)
		return test_fail("indexed contract raw callback missing");
	source_codes = ouro_string_codes(source);
	args[0] = ouro_nat(16000); args[1] = source_codes;
	selected = test_contract_scoped(FIND(pl, "compile_checked_source"), args, 2);
	if (selected == 0 || selected->tag != 1 || selected->n != 1)
		return test_fail("contract source acceptance");
	program = OURO_F(selected, 0);
	args[1] = program;
	selected = test_contract_scoped(FIND(lo, "lower_recheck_program"), args, 2);
	if (selected == 0 || selected->tag != 1 || selected->n != 1
	    || !test_pe_value_equal(program, OURO_F(selected, 0)))
		return test_fail("contract complete exact-Core replay");
	program = OURO_F(selected, 0);
	entries = ouro_apply(FIND(pl, "checked_program_entries"), program);
	sig = ouro_apply(FIND(el, "check_environment_from_entries"), entries);
	selected = test_apply(FIND(lo, "managed_source_symbol"),
		(ouro_v *[]){program, ouro_string_codes("contract_probe")}, 2);
	if (selected == 0 || selected->tag != 1 || selected->n != 1)
		return test_fail("checked extern contract symbol");
	id = OURO_F(selected, 0);
	selected = test_apply(FIND(lo, "lower_find_entry"), (ouro_v *[]){id, entries}, 2);
	if (selected == 0 || selected->tag != 1 || selected->n != 1)
		return test_fail("checked extern contract entry");
	entry = OURO_F(selected, 0);
	if (entry == 0 || entry->tag != 2 || entry->n != 3
	    || !test_pe_value_equal(OURO_F(entry, 0), id))
		return test_fail("checked extern binding shape");
	typ = OURO_F(entry, 1);
	binding = ouro_ctor(1, 1, (ouro_v *[]){OURO_F(entry, 2)});
	args[0] = FIND(lo, "native_build_fuel"); args[1] = sig;
	selected = test_contract_scoped(FIND(lo, "lower_normalize"),
		(ouro_v *[]){args[0], sig, typ}, 3);
	if (selected == 0 || selected->tag != 1 || selected->n != 1)
		return test_fail("checked alias signature normalization");
	normal = OURO_F(selected, 0);
	if (normal == 0 || normal->tag != 2 || normal->n != 2)
		return test_fail("first checked pointer parameter");
	codomain = OURO_F(normal, 1);
	if (codomain == 0 || codomain->tag != 2 || codomain->n != 2)
		return test_fail("second checked pointer parameter");
	expected = ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(0, 5, (ouro_v *[]){id, normal,
		test_cons(ouro_ctor(0, 3, (ouro_v *[]){OURO_F(normal, 0),
			ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(5, 0, 0)}), ouro_ctor(1, 0, 0)}),
			test_cons(ouro_ctor(0, 3, (ouro_v *[]){OURO_F(codomain, 0),
				ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(5, 0, 0)}), ouro_ctor(1, 0, 0)}), test_nil())),
		ouro_ctor(0, 3, (ouro_v *[]){OURO_F(codomain, 1),
			ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(1, 0, 0)}), ouro_ctor(0, 0, 0)}), binding})});
	args[2] = id; args[3] = typ; args[4] = binding;
	if (!test_contract_case(raw, wrapped, args, expected))
		return test_fail("complete checked extern contract result");
	entry = OURO_F(expected, 0);
	none_expected = ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(0, 5, (ouro_v *[]){
		OURO_F(entry, 0), OURO_F(entry, 1), OURO_F(entry, 2), OURO_F(entry, 3), test_nil()})});
	args[4] = test_nil();
	if (!test_contract_case(raw, wrapped, args, none_expected))
		return test_fail("complete contract with absent binding");
	args[4] = binding;
	for (i = 0; i < 5; i++) captures[i] = args[i];
	captures[5] = program; captures[6] = source_codes;
	for (i = 0; i < 7; i++) snapshots[i] = ouro_clone_perm_deep(captures[i]);
	partial = test_apply(wrapped, args, 4);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS
	    || partial->u.c.fn != lower_make_contract_binding)
		return test_fail("actual contract partial application");
	partial_env = partial->u.c.env;
	ouro_perm_begin();
	branch = ouro_thunk(test_contract_branch, ouro_cons(binding, ouro_cons(partial, 0)));
	ouro_perm_end();
	branch_env = branch->u.c.env;
	malformed = ouro_ctor(11, 2, (ouro_v *[]){ouro_nat(7), ouro_nat(0)});
	resource = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	malformed_error = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(1, 3, (ouro_v *[]){
		ouro_ctor(0, 0, 0), ouro_ctor(2, 0, 0), ouro_ctor(2, 1, (ouro_v *[]){ouro_ctor(12, 0, 0)})})});
	unsupported = ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(0)});
	ouro_heap_mark();
	ouro_heap_mark_save(&mark_n, &mark_used);
	for (i = 0; i < 16; i++) {
		last = ouro_apply(partial, binding);
		if (i == 0) first = last;
		if (!test_pe_value_equal(first, expected) || !test_pe_value_equal(last, expected)
		    || OURO_F(OURO_F(last, 0), 0) != id || OURO_F(OURO_F(last, 0), 4) != binding)
			return test_fail("retained contract or borrowed payload identity changed");
		if (i % 4 == 0) {
			ouro_heap_context *context = ouro_heap_context_enter();
			ouro_v *lazy = ouro_case(test_nil(), 1, &branch);
			lazy = ouro_heap_context_leave(context, lazy);
			if (!test_pe_value_equal(lazy, expected))
				return test_fail("borrowed contract branch survivor changed");
		}
		ouro_heap_mark_save(&after_n, &after_used);
		if (after_n != mark_n || after_used != mark_used || partial->u.c.env != partial_env
		    || ouro_get(partial_env, 0) != typ || ouro_get(partial_env, 1) != id
		    || ouro_get(partial_env, 2) != sig || ouro_get(partial_env, 3) != captures[0]
		    || ouro_get(partial_env, 4) != raw || branch->tag != OURO_TAG_THUNK
		    || branch->u.c.fn != test_contract_branch || branch->u.c.env != branch_env
		    || ouro_get(branch_env, 0) != binding || ouro_get(branch_env, 1) != partial
		    || FIND(lo, "lower_make_contract_indexed") != wrapped)
			return test_fail("contract caller captures, marks or thunk changed");
	}
	saved = ouro_clone_perm_deep(first);
	ouro_heap_reset();
	if (!test_pe_value_equal(saved, expected) || !test_pe_value_equal(ouro_apply(partial, binding), expected)
	    || !test_pe_value_equal(ouro_case(test_nil(), 1, &branch), expected))
		return test_fail("saved contract and caller captures unusable after reset");
	for (i = 0; i < 7; i++)
		if (!test_pe_value_equal(captures[i], snapshots[i]))
			return test_fail("full checked contract captures changed");
	args[0] = ouro_nat(0);
	if (!test_contract_case(raw, wrapped, args, resource))
		return test_fail("exact zero-fuel contract failure");
	args[3] = malformed;
	if (!test_contract_case(raw, wrapped, args, resource))
		return test_fail("zero fuel precedes malformed contract failure");
	args[0] = captures[0];
	if (!test_contract_case(raw, wrapped, args, malformed_error))
		return test_fail("full malformed contract failure");
	args[3] = unsupported;
	if (!test_contract_case(raw, wrapped, args, ouro_ctor(0, 1,
	    (ouro_v *[]){ouro_ctor(4, 1, (ouro_v *[]){unsupported})})))
		return test_fail("full unsupported contract failure");
	rechecked = test_contract_scoped(FIND(lo, "lower_recheck_program"),
		(ouro_v *[]){ouro_nat(16000), program}, 2);
	if (rechecked == 0 || rechecked->tag != 1 || rechecked->n != 1
	    || !test_pe_value_equal(OURO_F(rechecked, 0), program))
		return test_fail("original contract program no longer rechecks");
	return 0;
}

static int test_pe_operation(ouro_v *wrapped, ouro_v **arguments, int count)
{
	ouro_v *raw, *reference, *first = 0, *last = 0;
	ouro_heap_context *context;
	unsigned long long before, retained, start;
	int i;
	if (wrapped == 0 || wrapped->tag != OURO_TAG_CLOS
	    || wrapped->u.c.fn != pe_scoped_argument)
		return test_fail("PE operation lifetime hook missing");
	raw = ouro_get(wrapped->u.c.env, 1);
	before = ouro_heap_live_bytes();
	context = ouro_heap_context_enter();
	reference = test_apply(raw, arguments, count);
	reference = ouro_heap_context_leave(context, reference);
	retained = ouro_heap_live_bytes() - before;
	start = ouro_heap_live_bytes();
	for (i = 0; i < 64; i++) {
		last = test_apply(wrapped, arguments, count);
		if (i == 0)
			first = last;
		if (ouro_heap_live_bytes() - start >
		    (unsigned long long)(i + 1) * (retained + 4096ULL) + 1048576ULL)
			return test_fail("PE operation temporary work retained");
	}
	if (!test_pe_value_equal(first, reference) || !test_pe_value_equal(last, reference))
		return test_fail("PE operation complete result changed");
	return 0;
}

static int test_pe_patch_bytes(ouro_v *actual, const unsigned char *expected, unsigned long size)
{
	ouro_v **stack = 0;
	unsigned long offset = 0;
	unsigned char *copy;
	int capacity = 0;
	int equal;
	copy = (unsigned char *)malloc(size == 0 ? 1UL : size);
	if (copy == 0)
		return 0;
	equal = cgp_walk_bytes(actual, copy, &offset, size, &stack, &capacity) == 0 && offset == size
		&& (size == 0 || memcmp(copy, expected, size) == 0);
	free(stack);
	free(copy);
	return equal;
}

static ouro_v *test_pe_patch(int kind, unsigned long offset, const unsigned char *bytes, unsigned long size)
{
	return ouro_ctor(0, 4, (ouro_v *[]){ouro_ctor(kind, 0, 0), ouro_nat(offset),
		ouro_packed(bytes, size), ouro_ctor(1, 0, 0)});
}

static ouro_v *test_pe_patch_result(ouro_v *bytes, ouro_v *patches)
{
	ouro_v *section = ouro_ctor(0, 5, (ouro_v *[]){test_nil(), ouro_nat(4096),
		ouro_nat(1024), ouro_nat(512), bytes});
	ouro_v *layout = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(8192), ouro_nat(1536),
		test_cons(section, test_nil())});
	ouro_v *result = test_apply(FIND(lo, "pe_apply_patches"), (ouro_v *[]){layout, patches}, 2);
	ouro_v *sections, *placed;
	int i;
	if (result == 0 || result->tag != 0 || result->n != 3
	    || OURO_F(result, 0) != OURO_F(layout, 0) || OURO_F(result, 1) != OURO_F(layout, 1)) {
		test_fail("PE patch layout metadata changed");
		return 0;
	}
	sections = OURO_F(result, 2);
	if (sections == 0 || sections->tag != 1 || sections->n != 2 || !list_done(OURO_F(sections, 1))) {
		test_fail("PE patch section inventory changed");
		return 0;
	}
	placed = OURO_F(sections, 0);
	if (placed == 0 || placed->tag != 0 || placed->n != 5) {
		test_fail("PE patch section shape changed");
		return 0;
	}
	for (i = 0; i < 4; i++)
		if (OURO_F(placed, i) != OURO_F(section, i)) {
			test_fail("PE patch section metadata changed");
			return 0;
		}
	return OURO_F(placed, 4);
}

static int test_pe_patch_apply(ouro_v *bytes, ouro_v *patches,
	const unsigned char *expected, unsigned long size)
{
	ouro_v *result = test_pe_patch_result(bytes, patches);
	if (result == 0)
		return 1;
	if (!test_pe_patch_bytes(result, expected, size))
		return test_fail("PE patch complete byte oracle changed");
	return 0;
}

static int test_pe_patch_prefixes(void)
{
	static const unsigned char bytes[] = {0,1,2,3,4,5,6,7};
	static const unsigned char replacement[] = {9,8,7,6};
	static const unsigned char truncated[] = {0,1,2,3,4,5,9,8,7,6};
	static const unsigned char outside[] = {0,1,2,3,4,5,6,7,9};
	static const unsigned char backward[] = {0,1,2,3,9,8,7,7};
	static const unsigned char duplicate[] = {0,1,2,3,9,8,6,7};
	const unsigned long counts[] = {0,1024,1025,1070};
	const unsigned long prefixes[] = {0,1024,1025,1040};
	unsigned char chunk[1040];
	ouro_v *step = FIND(lo, "pe_patch_prefix_step"), *source, *pair, *suffix;
	ouro_v *first, *wide, *wide_source, *tail;
	unsigned long i;
	if (step == 0 || step->tag != OURO_TAG_CLOS || step->u.c.fn != pe_scoped_argument
	    || as_nat(ouro_get(step->u.c.env, 0)) != 1UL)
		return test_fail("PE prefix step context hook missing");
	for (i = 0; i < sizeof(chunk); i++)
		chunk[i] = (unsigned char)(i % 251UL);
	source = ouro_packed(chunk, sizeof(chunk));
	if (test_pe_operation(step, &source, 1))
		return 1;
	for (i = 0; i < sizeof(counts) / sizeof(counts[0]); i++) {
		pair = test_contract_scoped(FIND(lo, "pe_patch_prefix"),
			(ouro_v *[]){ouro_nat(counts[i]), source}, 2);
		if (pair == 0 || pair->tag != 0 || pair->n != 2
		    || !test_pe_patch_bytes(OURO_F(pair, 0), chunk, prefixes[i])
		    || !test_pe_patch_bytes(OURO_F(pair, 1), chunk + prefixes[i], sizeof(chunk) - prefixes[i]))
			return test_fail("PE zero/chunk/tail/truncated prefix changed");
	}
	pair = test_contract_scoped(FIND(lo, "pe_patch_prefix"),
		(ouro_v *[]){ouro_nat(1025), test_nil()}, 2);
	if (pair == 0 || pair->tag != 0 || pair->n != 2
	    || !list_done(OURO_F(pair, 0)) || !list_done(OURO_F(pair, 1)))
		return test_fail("PE empty prefix changed");
	first = ouro_nat(257);
	wide = ouro_nat_u64(UINT64_C(4294967313));
	tail = test_cons(wide, test_nil());
	wide_source = test_cons(first, tail);
	pair = test_contract_scoped(FIND(lo, "pe_patch_prefix"),
		(ouro_v *[]){ouro_nat(1), wide_source}, 2);
	if (pair == 0 || pair->tag != 0 || pair->n != 2
	    || OURO_F(pair, 0) == 0 || OURO_F(pair, 0)->tag != 1 || OURO_F(pair, 0)->n != 2
	    || OURO_F(OURO_F(pair, 0), 0) != first || !list_done(OURO_F(OURO_F(pair, 0), 1))
	    || OURO_F(pair, 1) != tail || OURO_F(tail, 0) != wide)
		return test_fail("PE prefix truncated arbitrary Nat or recopied caller tail");
	{
		ouro_v **items = 0;
		int n = 0, failed;
		ouro_v *actual = test_pe_patch_result(wide_source,
			test_cons(ouro_ctor(0, 4, (ouro_v *[]){test_nil(), ouro_nat(1),
				test_cons(wide, test_nil()), ouro_ctor(1, 0, 0)}), test_nil()));
		failed = actual == 0 || host_list_collect(actual, &items, &n, 0) != 0
			|| n != 2 || items[0] != first || items[1] != wide;
		free(items);
		if (failed)
			return test_fail("PE direct patch truncated arbitrary Nat payloads");
	}
	if (test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)), test_nil(), bytes, sizeof(bytes))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(0, 3, replacement, 0), test_nil()), bytes, sizeof(bytes))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(1, 2000, replacement, 4), test_nil()), bytes, sizeof(bytes))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(0, 6, replacement, 4), test_nil()), truncated, sizeof(truncated))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(0, 12, replacement, 1), test_nil()), outside, sizeof(outside))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(0, 4, replacement, 2),
		  test_cons(test_pe_patch(0, 2, replacement + 2, 1), test_nil())), backward, sizeof(backward))
	    || test_pe_patch_apply(ouro_packed(bytes, sizeof(bytes)),
		test_cons(test_pe_patch(0, 4, replacement, 1),
		  test_cons(test_pe_patch(0, 4, replacement + 1, 1), test_nil())), duplicate, sizeof(duplicate))
	    || test_pe_patch_apply(test_nil(), test_cons(test_pe_patch(0, 1025, replacement, 1), test_nil()), replacement, 1))
		return 1;
	{
		const unsigned long size = 1048576UL;
		unsigned char *expected = (unsigned char *)malloc(size);
		unsigned long long start;
		ouro_v *retained_pair = 0, *retained_output = 0;
		int failed = 0;
		if (expected == 0)
			return test_fail("PE large prefix input allocation failed");
		for (i = 0; i < size; i++)
			expected[i] = (unsigned char)((i * 17UL + 3UL) % 251UL);
		source = ouro_packed(expected, size);
		start = ouro_heap_live_bytes();
		for (i = 0; i < 64; i++) {
			pair = ouro_apply(step, source);
			if (pair == 0 || pair->tag != 0 || pair->n != 2) {
				failed = test_fail("PE large prefix step shape changed");
				break;
			}
			suffix = OURO_F(pair, 1);
			if (!test_pe_patch_bytes(OURO_F(pair, 0), expected, 1024)
			    || suffix == 0 || suffix->tag != OURO_TAG_BYTES || suffix->n != (int)(size - 1024UL)
			    || suffix->u.s != source->u.s + 1024UL
			    || ouro_heap_live_bytes() - start > (unsigned long long)(i + 1UL) * 65536ULL + 1048576ULL) {
				failed = test_fail("PE prefix step retained scratch or copied the packed tail");
				break;
			}
			if (i == 0)
				retained_pair = pair;
		}
		memcpy(expected + size - 4UL, replacement, 4);
		for (i = 0; i < 2 && !failed; i++) {
			ouro_v *output = test_pe_patch_result(source,
				test_cons(test_pe_patch(0, size - 4UL, replacement, 4), test_nil()));
			if (i == 0)
				retained_output = output;
			if (output == 0 || !test_pe_patch_bytes(output, expected, size))
				failed = test_fail("PE complete large patched output changed");
			if (!failed && ouro_heap_live_bytes() - start > 268435456ULL)
				failed = test_fail("PE complete large patched outputs exceeded the 256 MiB survivor budget");
		}
		if (!failed && !test_pe_patch_bytes(retained_output, expected, size))
			failed = test_fail("PE first large patched output changed after repeated contexts");
		for (i = 0; i < size; i++)
			expected[i] = (unsigned char)((i * 17UL + 3UL) % 251UL);
		if (!test_pe_patch_bytes(source, expected, size))
			failed = test_fail("PE patching changed original packed input");
		if (!failed) {
			suffix = OURO_F(retained_pair, 1);
			if (!test_pe_patch_bytes(OURO_F(retained_pair, 0), expected, 1024)
			    || suffix == 0 || suffix->tag != OURO_TAG_BYTES || suffix->n != (int)(size - 1024UL)
			    || suffix->u.s != source->u.s + 1024UL
			    || !test_pe_patch_bytes(suffix, expected + 1024UL, size - 1024UL))
				failed = test_fail("PE first prefix and shared suffix changed after repeated contexts");
		}
		free(expected);
		return failed;
	}
}

static ouro_v *test_pe_fixup_capture;
static int test_pe_fixup_work_failed;

static ouro_v *test_pe_fixup_work(ouro_env *env, ouro_v *unit)
{
	static const unsigned char bytes[] = {0,16,0,0};
	ouro_v *capture = ouro_get(env, 0);
	ouro_v *source = OURO_F(capture, 1);
	ouro_v *result;
	if (capture != test_pe_fixup_capture || unit == 0 || unit->tag != 0 || unit->n != 0)
		test_pe_fixup_work_failed = 1;
	memset(ouro_alloc(1024UL * 1024UL), 0xA5, 1024UL * 1024UL);
	if (as_nat(OURO_F(capture, 2)) == 1UL) {
		result = ouro_ctor(3, 2, (ouro_v *[]){ouro_ctor(1, 0, 0), ouro_nat(511)});
		result = ouro_ctor(21, 1, &result);
		return ouro_ctor(0, 1, &result);
	}
	result = (ouro_v *)ouro_alloc(sizeof(ouro_v));
	result->tag = OURO_TAG_BYTES;
	result->n = source->n - 4;
	result->u.s = source->u.s + 4;
	result = ouro_ctor(0, 4, (ouro_v *[]){
		ouro_ctor(0, 4, (ouro_v *[]){test_nil(), ouro_nat(8192),
			ouro_packed(bytes, sizeof(bytes)), ouro_ctor(1, 0, 0)}),
		ouro_nat(0), ouro_nat(8196), result});
	return ouro_ctor(1, 1, &result);
}

static int test_pe_fixup_steps(void)
{
	unsigned char bytes[257] = {0};
	ouro_v *source = ouro_packed(bytes, sizeof(bytes));
	ouro_v *runner = FIND(lo, "pe_run_fixup_step");
	ouro_v *index = ouro_ctor(77, 2, (ouro_v *[]){ouro_nat(4097), source});
	ouro_v *capture;
	ouro_v *work;
	ouro_v *result;
	ouro_heap_context *context;
	int branch;
	for (branch = 0; branch < 2; branch++) {
		capture = ouro_ctor(0, 3, (ouro_v *[]){index, source, ouro_nat((unsigned long)branch)});
		test_pe_fixup_capture = capture;
		work = ouro_clos(test_pe_fixup_work, ouro_cons(capture, 0));
		if (test_pe_operation(runner, &work, 1))
			return 1;
		context = ouro_heap_context_enter();
		result = ouro_apply(runner, work);
		result = ouro_heap_context_leave(context, result);
		if (result == 0 || result->tag != (branch == 0 ? 1 : 0) || result->n != 1)
			return test_fail("PE fixup step result branch changed");
		if (branch == 0) {
			ouro_v *step = OURO_F(result, 0);
			ouro_v *suffix;
			if (step == 0 || step->tag != 0 || step->n != 4)
				return test_fail("PE fixup step state layout changed");
			suffix = OURO_F(step, 3);
			if (as_nat(OURO_F(step, 1)) != 0UL || as_nat(OURO_F(step, 2)) != 8196UL
			    || suffix == 0 || suffix->tag != OURO_TAG_BYTES || suffix->n != 253
			    || suffix->u.s != source->u.s + 4 || OURO_F(capture, 0) != index)
				return test_fail("PE fixup step recopied caller input or changed cursor");
		}
	}
	return test_pe_fixup_work_failed ? test_fail("PE fixup step thunk capture or Unit changed") : 0;
}

static int test_pe_operations(void)
{
	unsigned char bytes[16384] = {0};
	ouro_v *section = ouro_ctor(0, 5, (ouro_v *[]){test_nil(), ouro_nat(4096),
		ouro_nat(1024), ouro_nat(sizeof(bytes)), ouro_packed(bytes, sizeof(bytes))});
	ouro_v *sections = test_cons(section, test_nil());
	ouro_v *symbols = test_cons(ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(7),
		test_nil(), ouro_nat(4096)}), test_nil());
	ouro_v *measured = ouro_ctor(0, 2, (ouro_v *[]){section, ouro_nat(sizeof(bytes))});
	ouro_v *arguments[5];
	ouro_v *fixup = FIND(lo, "pe_resolve_fixup_indexed_with");
	arguments[0] = ouro_nat(2147483647UL);
	if (test_pe_operation(FIND(lo, "pe_word32"), arguments, 1))
		return 1;
	arguments[0] = ouro_apply(FIND(lo, "pe_cached_section_lookup"),
		test_cons(measured, test_nil()));
	arguments[1] = ouro_apply(FIND(lo, "pe_symbol_index_from_symbols"), symbols);
	arguments[2] = test_nil();
	arguments[3] = ouro_ctor(0, 4, (ouro_v *[]){test_nil(), ouro_nat(8192),
		ouro_nat(8196), ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(7)})});
	arguments[4] = measured;
	if (test_pe_operation(fixup, arguments, 5))
		return 1;
	arguments[3] = ouro_ctor(0, 4, (ouro_v *[]){test_nil(), ouro_nat(8192),
		ouro_nat(8195), ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(7)})});
	if (test_pe_operation(fixup, arguments, 5))
		return 1;
	arguments[0] = sections;
	arguments[1] = symbols;
	arguments[2] = ouro_ctor(0, 4, (ouro_v *[]){ouro_nat(7), ouro_nat(1),
		test_nil(), test_nil()});
	arguments[3] = test_nil();
	if (test_pe_operation(FIND(lo, "pe_function_scan"), arguments, 4))
		return 1;
	arguments[2] = ouro_ctor(0, 4, (ouro_v *[]){ouro_nat(8), ouro_nat(1),
		test_nil(), test_nil()});
	if (test_pe_operation(FIND(lo, "pe_function_scan"), arguments, 4))
		return 1;
	arguments[0] = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(24576), ouro_nat(20480), sections});
	arguments[1] = test_cons(ouro_ctor(0, 4, (ouro_v *[]){test_nil(),
		ouro_nat(8192), test_cons(ouro_nat(1), test_cons(ouro_nat(2),
			test_cons(ouro_nat(3), test_cons(ouro_nat(4), test_nil())))), test_nil()}), test_nil());
	if (test_pe_operation(FIND(lo, "pe_apply_patches"), arguments, 2))
		return 1;
	if (test_pe_fixup_steps())
		return 1;
	return test_pe_patch_prefixes();
}

static int test_assembly_rows_equal(ouro_v *fast, ouro_v *pure)
{
	ouro_v **left = 0;
	ouro_v **right = 0;
	int nl = 0, nr = 0;
	int same = 0;
	int i;

	if (host_list_collect(fast, &left, &nl, 0) != 0
	    || host_list_collect(pure, &right, &nr, 0) != 0 || nl != nr)
		goto done;
	for (i = 0; i < nl; i++)
		if (!test_pe_value_equal(left[i], right[i]))
			goto done;
	same = 1;
done:
	free(left);
	free(right);
	return same;
}

static int test_assembly_output_equal(ouro_v *fast, ouro_v *pure)
{
	if (fast == 0 || pure == 0 || fast->tag != 1 || pure->tag != 1
	    || fast->n != 1 || pure->n != 1)
		return 0;
	fast = OURO_F(fast, 0);
	pure = OURO_F(pure, 0);
	return fast != 0 && pure != 0 && fast->tag == 0 && pure->tag == 0
		&& fast->n == 3 && pure->n == 3
		&& test_pe_byte_lists_equal(OURO_F(fast, 0), OURO_F(pure, 0))
		&& test_assembly_rows_equal(OURO_F(fast, 1), OURO_F(pure, 1))
		&& test_assembly_rows_equal(OURO_F(fast, 2), OURO_F(pure, 2));
}

static int test_assembly_labels(void)
{
	ouro_v *site = cgn_site_label(7, 3, 1);
	ouro_v *next = cgn_site_label(7, 3, 2);
	ouro_v *mark = ouro_ctor(1, 1, &next);
	ouro_v *atoms[] = {
		cgn_mark_block(7),
		ouro_ctor(1, 1, &site),
		cgn_direct(11),
		cgn_bound(7, 3),
		ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(4), next }),
		cgn_mark_block(7),
		cgn_jump_block(7),
		mark,
		mark,
		ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(4), site }),
		cgn_atom(ouro_ctor(24, 0, 0))
	};
	ouro_v *args[] = {
		cgasm_list(atoms, (int)(sizeof atoms / sizeof atoms[0])),
		ouro_nat(700),
		ouro_nat(300)
	};
	ouro_v *missing = cgn_jump_block(99);
	ouro_v *bad_shift = cgn_atom(ouro_ctor(15, 4, (ouro_v *[]){
		cgn_unit(0), cgn_unit(0), cgn_unit(0), ouro_nat(32) }));
	ouro_v *fast;

	(void)FIND(lo, "codegen_assemble");
	if (g_raw_codegen_assemble == 0)
		return test_fail("assembly hook missing");
	fast = cgasm_try(args[0], args[1], args[2]);
	if (!test_assembly_output_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("indexed labels changed bytes, fixups or call sites");

	args[0] = test_cons(missing, test_nil());
	fast = cgasm_try(args[0], args[1], args[2]);
	if (fast == 0 || fast->tag != 0 || OURO_F(fast, 0)->tag != 4
	    || !test_pe_value_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("indexed assembly lost the missing label error");

	args[0] = test_cons(missing, test_cons(bad_shift, test_nil()));
	fast = cgasm_try(args[0], args[1], args[2]);
	if (fast == 0 || fast->tag != 0 || OURO_F(fast, 0)->tag != 1
	    || !test_pe_value_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("indexed assembly changed encoding error precedence");
	return 0;
}

static int test_assembly_buffer_growth(void)
{
	ouro_v *body[144];
	ouro_v *ret = cgn_atom(ouro_ctor(24, 0, 0));
	ouro_v *imported = ouro_ctor(5, 1, (ouro_v *[]){ouro_nat(21)});
	ouro_v *start[] = {cgn_mark_block(4), cgn_jump_block(9)};
	ouro_v *end[] = {cgn_mark_block(9), cgn_jump_block(4), cgn_sym(20), imported};
	ouro_v *args[] = {0, ouro_nat(700), ouro_nat(300)};
	ouro_v *fast;
	int i;

	for (i = 0; i < 72; i++) {
		body[2 * i] = i % 2 == 0 ? ret : cgn_direct((unsigned long)i);
		body[2 * i + 1] = cgn_bound(4, (unsigned long)i);
	}
	args[0] = cgn_cat(cgn_cat(cgasm_list(start, 2), cgasm_list(body, 144)), cgasm_list(end, 4));
	fast = cgasm_try(args[0], args[1], args[2]);
	if (!test_assembly_output_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("assembly buffer growth changed branches, fixups or call sites");

	args[0] = test_cons(cgn_jump_block(99), test_cons(ret, test_nil()));
	args[2] = ouro_nat(PE_MAX_RVA - 5UL);
	fast = cgasm_try(args[0], args[1], args[2]);
	if (fast == 0 || fast->tag != 0 || OURO_F(fast, 0)->tag != 5
	    || !test_pe_value_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("assembly size limit lost precedence over unresolved labels");

	args[0] = test_cons(cgn_mark_block(4), test_cons(cgn_bound(4, 1), test_nil()));
	args[2] = ouro_nat(PE_MAX_RVA + 1UL);
	fast = cgasm_try(args[0], args[1], args[2]);
	if (!test_assembly_output_equal(fast, test_apply(g_raw_codegen_assemble, args, 3)))
		return test_fail("assembly without instruction bytes changed boundary offsets");
	return 0;
}

static int test_prepared_code_concat(void)
{
	static const unsigned char expected[] = {0x48, 0, 0x89, 0x90, 0xc3};
	ouro_v *first = cgp_cat(ouro_packed(expected, 2), ouro_packed(expected + 2, 1));
	ouro_v *second = cgp_cat(ouro_packed(expected + 3, 1),
		test_cons(ouro_nat(expected[4]), test_nil()));
	ouro_v *parts[3];
	ouro_v *payloads[] = {first, test_nil(), second};
	ouro_v *combined;
	int i;
	int field;

	for (i = 0; i < 3; i++) {
		ouro_v *fields[5];

		fields[0] = payloads[i];
		for (field = 1; field < 5; field++)
			fields[field] = test_cons(ouro_nat((unsigned long)(10 * field + i)), test_nil());
		parts[i] = ouro_ctor(0, 5, fields);
	}
	combined = cgp_concat_functions(test_cons(parts[2], test_cons(parts[1],
		test_cons(parts[0], test_nil()))));
	if (combined == 0 || combined->n != 5
	    || !test_pe_patch_bytes(OURO_F(combined, 0), expected, sizeof expected))
		return test_fail("prepared code concatenation changed bytes");
	for (field = 1; field < 5; field++) {
		ouro_v *rows = test_nil();

		for (i = 2; i >= 0; i--)
			rows = test_cons(ouro_nat((unsigned long)(10 * field + i)), rows);
		if (!test_nat_lists_equal(OURO_F(combined, field), rows))
			return test_fail("prepared code metadata changed function order");
	}
	{
		unsigned char deep_expected[70];
		ouro_v *deep = test_nil();
		ouro_v *bad = ouro_packed(expected, 1);
		ouro_v *many = test_cons(parts[0], test_nil());

		for (i = 0; i < (int)sizeof deep_expected; i++) {
			deep_expected[i] = (unsigned char)i;
			deep = cgp_cat(deep, ouro_packed(deep_expected + i, 1));
		}
		OURO_F(parts[0], 0) = cgp_cat(deep, bad);
		bad->u.s = 0;
		if (cgp_concat_functions(many) != 0)
			return test_fail("prepared code accepted a missing nonempty byte buffer");
		bad->u.s = (const char *)expected;
		bad->n = INT_MAX;
		if (cgp_concat_functions(many) != 0)
			return test_fail("prepared code accepted a total outside packed byte range");
		OURO_F(parts[0], 0) = deep;
		combined = cgp_concat_functions(many);
		if (combined == 0 || !test_pe_patch_bytes(OURO_F(combined, 0), deep_expected, sizeof deep_expected))
			return test_fail("prepared code stack did not recover after rejecting malformed bytes");
	}
	return 0;
}

static int test_frame_slots(void)
{
	ouro_v *source = cgn_cat(
		test_cons(test_slot(70000, 1, 32), test_nil()),
		test_cons(test_slot(3, 1, 40),
			test_cons(test_slot(70000, 0, 48), test_nil())));
	cgn_frame_slots slots = { .source = source };
	ouro_v *move = ouro_ctor(0, 2, (ouro_v *[]){ ouro_nat(3), test_use(70000) });
	ouro_v *args[] = { test_nil(), source, ouro_nat(7), ouro_nat(0), move };
	ouro_v *wrapped = FIND(lo, "codegen_instruction");
	ouro_v *fast;
	unsigned long offset;
	unsigned long fast_count = g_cgi_count;
	unsigned long fallback_count = g_cgi_fallback;
	int type;
	int found;

	found = cgn_slot(&slots, 70000, &offset, &type) == 0
		&& offset == 32 && type == 1
		&& cgn_slot(&slots, 3, &offset, &type) == 0
		&& offset == 40 && type == 1
		&& cgn_slot(&slots, 99, &offset, &type) != 0;
	free(slots.entries);
	if (!found)
		return test_fail("slot index lost source order, sparse ID or missing-slot handling");
	if (g_raw_cgi == 0)
		return test_fail("instruction hook missing");
	fast = test_apply(wrapped, args, 5);
	if (g_cgi_count != fast_count + 1
	    || !test_bytes_equal(fast, test_apply(g_raw_cgi, args, 5)))
		return test_fail("indexed sparse slots changed instruction bytes");

	args[4] = test_replace_field(move, 1, test_use(99));
	fast = test_apply(wrapped, args, 5);
	if (g_cgi_fallback != fallback_count + 1
	    || fast == 0 || fast->tag != 0 || OURO_F(fast, 0)->tag != 3
	    || !test_pe_value_equal(fast, test_apply(g_raw_cgi, args, 5)))
		return test_fail("indexed instruction lost the typed slot error");

	slots = (cgn_frame_slots){ .source = test_cons(
		test_replace_field(test_slot(70000, 1, 0), 2, ouro_ctor(2, 0, 0)),
		source) };
	found = cgn_slot(&slots, 70000, &offset, &type);
	free(slots.entries);
	if (found == 0)
		return test_fail("slot lookup skipped the invalid first match");
	slots = (cgn_frame_slots){ .source = test_cons(
		test_slot(70000, 1, 0), ouro_ctor(2, 0, 0)) };
	found = cgn_slot(&slots, 70000, &offset, &type);
	free(slots.entries);
	if (found == 0)
		return test_fail("slot lookup accepted a malformed list tail");
	return 0;
}

static int test_tail_successors(void)
{
	ouro_v *jump = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(7)});
	ouro_v *ret = ouro_ctor(2, 1, (ouro_v *[]){
		ouro_ctor(1, 1, (ouro_v *[]){test_use(3)})});
	ouro_v *first = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(2), test_use(1)});
	ouro_v *second = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(3), test_use(2)});
	ouro_v *moves = ouro_ctor(OURO_TAG_CAT, 2, (ouro_v *[]){
		test_cons(first, test_nil()), test_cons(second, test_nil())});
	ouro_v *target = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(7), moves, ret});
	ouro_v *entries[] = {target};
	cgb_block_context blocks = { .entries = entries, .count = 1 };

	if (!cgb_tail_return(&blocks, 2, 1, jump)
	    || cgb_tail_return(&blocks, 1, 1, jump)
	    || cgb_tail_return(&blocks, 2, 2, jump))
		return test_fail("tail continuation changed move order or fuel");
	OURO_F(target, 1) = test_cons(second, ouro_ctor(2, 0, 0));
	if (cgb_tail_return(&blocks, 2, 2, jump))
		return test_fail("tail continuation accepted a malformed move list");
	OURO_F(target, 1) = test_nil();
	OURO_F(target, 2) = jump;
	if (cgb_tail_return(&blocks, 2, 1, jump))
		return test_fail("tail continuation followed a cycle past fuel");
	return 0;
}

static int test_block_positions(void)
{
	ouro_v *entries[20];
	ouro_v *primary = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(900000)});
	ouro_v *following = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(900000), test_nil(), test_nil()});
	int i;
	int unpacked;

	for (i = 0; i < 20; i++)
		entries[i] = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(100000UL + 7UL * (unsigned long)i)});
	entries[1] = primary;
	entries[13] = following;
	for (unpacked = 0; unpacked < 2; unpacked++) {
		cgb_block_context blocks = { .entries = entries, .count = 20 };
		int matched;
		if (unpacked)
			entries[15] = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(1, 1, (ouro_v *[]){test_nil()})});
		matched = cgb_find_block(&blocks, 999999) == 0 && blocks.positions == 0
			&& cgb_find_block(&blocks, 900000) == primary
			&& (blocks.positions == 0) == unpacked
			&& cgb_find_block(&blocks, 999999) == 0
			&& cgb_find_block(&blocks, 1) == (unpacked ? entries[15] : 0);
		free(blocks.positions);
		if (!matched)
			return test_fail("tail block lookup changed first match, missing ID or unpacked fallback");
	}
	return 0;
}

static int test_slot_root_state(void)
{
	ouro_v *root = test_cons(test_slot(3, 6, 32), test_nil());
	ouro_v *scalar = test_cons(test_slot(4, 2, 40), test_nil());
	ouro_v *empty_forms[] = {0, ouro_nat(0), ouro_packed(0, 0),
		ouro_ctor(OURO_TAG_CAT, 2, (ouro_v *[]){test_nil(), test_nil()})};
	cgn_frame_slots slots = { .source = cgn_cat(scalar, root) };
	size_t i;

	if (cgb_zero_roots(&slots) == 0 || slots.roots != CGN_ROOTS_PRESENT
	    || cgb_slot_roots(&slots) != 1)
		return test_fail("prologue did not retain frame root presence");
	slots = (cgn_frame_slots){ .source = scalar };
	if (cgb_zero_roots(&slots) == 0 || slots.roots != CGN_ROOTS_SCALAR_FRAME
	    || cgb_slot_roots(&slots) != 0)
		return test_fail("scalar frame inherited root presence");
	for (i = 0; i < sizeof empty_forms / sizeof empty_forms[0]; i++) {
		slots = (cgn_frame_slots){ .source = test_cons(OURO_F(scalar, 0), empty_forms[i]) };
		if (cgb_zero_roots(&slots) == 0 || slots.roots != CGN_ROOTS_ABSENT)
			return test_fail("noncanonical scalar slot list enabled annotation bypass");
	}
	slots = (cgn_frame_slots){ .source = cgn_cat(root, ouro_ctor(2, 0, 0)) };
	if (cgb_slot_roots(&slots) != -1 || cgb_zero_roots(&slots) != 0
	    || slots.roots != CGN_ROOTS_UNKNOWN)
		return test_fail("root presence skipped a malformed slot-list tail");
	return 0;
}

static int test_scalar_body(void)
{
	ouro_v *slots = test_cons(test_slot(4, 2, 32), test_nil());
	ouro_v *frame = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(56), slots});
	ouro_v *move = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(4), test_use(4)});
	ouro_v *call = test_call(1, ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(4)}),
		test_cons(test_use(4), test_nil()));
	ouro_v *term = ouro_ctor(2, 1, (ouro_v *[]){test_nil()});
	ouro_v *block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0), test_nil(), term});
	ouro_v *function = ouro_ctor(0, 7, (ouro_v *[]){ouro_nat(1), ouro_string_codes("scalar"),
		test_cons(test_local(4, 2), test_nil()), test_nil(), test_nil(), ouro_nat(0),
		test_cons(block, test_nil())});
	ouro_v *program = ouro_ctor(0, 4, (ouro_v *[]){test_cons(function, test_nil()),
		test_nil(), test_nil(), ouro_nat(1)});
	ouro_v *forms[2];
	ouro_v *moves[32];
	int i;

	forms[0] = test_cons(call, test_nil());
	for (i = 0; i < (int)(sizeof moves / sizeof moves[0]); i++) {
		moves[i] = move;
		forms[0] = test_cons(move, forms[0]);
	}
	forms[1] = cgn_cat(cgasm_list(moves, i), test_cons(call, test_nil()));
	(void)FIND(lo, "codegen_body");
	for (i = 0; i < 2; i++) {
		cgn_frame_slots context = { .source = slots };
		cgb_block_context blocks = { 0 };
		ouro_v *fast;
		ouro_v *pure;
		int used_annotations;

		OURO_F(block, 1) = forms[i];
		fast = cgb_emit_body(program, function, frame, &context, &blocks);
		used_annotations = blocks.annotate != 0;
		cgb_release_blocks(&blocks);
		free(context.entries);
		pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
		if (used_annotations != i || !test_bytes_equal(fast, pure))
			return test_fail("scalar body annotation selection or byte parity changed");
	}
	return 0;
}

enum { TAIL_CHAIN_BLOCKS = 64 };

static unsigned long tail_chain_block_id(int index)
{
	return (unsigned long)(index * 17 % TAIL_CHAIN_BLOCKS) * 100000UL + 7UL;
}

static int test_tail_chain_body(void)
{
	ouro_v *slots = test_cons(test_slot(4, 2, 32), test_nil());
	ouro_v *frame = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(56), slots});
	ouro_v *blocks = test_nil();
	ouro_v *call = test_call(0, ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(4)}),
		test_cons(test_use(4), test_nil()));
	ouro_v *function;
	ouro_v *program;
	ouro_v *fast;
	ouro_v *pure;
	ouro_v *args[6];
	int i;

	OURO_F(call, 2) = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(1)});
	for (i = TAIL_CHAIN_BLOCKS - 1; i >= 0; i--) {
		ouro_v *term = i == TAIL_CHAIN_BLOCKS - 1 ? ouro_ctor(2, 1, (ouro_v *[]){
			ouro_ctor(1, 1, (ouro_v *[]){test_use(4)})})
			: ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(tail_chain_block_id(i + 1))});
		ouro_v *instructions = i == 0 ? test_cons(call, test_nil()) : test_nil();
		ouro_v *block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(tail_chain_block_id(i)),
			instructions, term});
		blocks = test_cons(block, blocks);
	}
	function = ouro_ctor(0, 7, (ouro_v *[]){ouro_nat(1), ouro_string_codes("tail-chain"),
		test_cons(test_local(4, 2), test_nil()), test_nil(),
		ouro_ctor(1, 1, (ouro_v *[]){cgn_unit(2)}), ouro_nat(tail_chain_block_id(0)), blocks});
	program = ouro_ctor(0, 4, (ouro_v *[]){test_cons(function, test_nil()),
		test_nil(), test_nil(), ouro_nat(1)});
	(void)FIND(lo, "codegen_body");
	fast = cgb_body_try(program, function, frame);
	pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
	if (!test_bytes_equal(fast, pure))
		return test_fail("tail chain changed body bytes");
	args[0] = program;
	args[1] = slots;
	args[2] = OURO_F(frame, 0);
	args[3] = test_nil();
	args[4] = blocks;
	args[5] = OURO_F(blocks, 0);
	fast = cgb_try(program, slots, args[2], args[3], blocks, args[5]);
	pure = test_apply6(g_raw_cgb, args);
	if (!test_bytes_equal(fast, pure))
		return test_fail("indexed tail continuation changed bytes from the raw block callback");
	return 0;
}

static int test_roots(void)
{
	ouro_v *slots = test_cons(test_slot(0, 6, 32),
		test_cons(test_slot(1, 6, 40), test_cons(test_slot(2, 6, 48), test_nil())));
	ouro_v *call = test_call(1, ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(0)}),
		test_cons(test_use(0), test_nil()));
	ouro_v *term = ouro_ctor(2, 1, (ouro_v *[]){
		ouro_ctor(1, 1, (ouro_v *[]){test_use(0)})});
	ouro_v *after_call = test_call(0, test_nil(), test_nil());
	ouro_v *block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0),
		test_cons(call, test_cons(after_call, test_nil())), term});
	ouro_v *blocks = test_cons(block, test_nil());
	ouro_v *function = ouro_ctor(0, 7, (ouro_v *[]){ouro_nat(1), ouro_string_codes("roots"),
		test_cons(test_local(0, 6), test_cons(test_local(1, 6), test_nil())),
		test_cons(test_local(2, 6), test_nil()), ouro_ctor(1, 1, (ouro_v *[]){ouro_ctor(6, 0, 0)}),
		ouro_nat(0), blocks});
	ouro_v *program = ouro_ctor(0, 4, (ouro_v *[]){test_cons(function, test_nil()),
		test_nil(), test_nil(), ouro_nat(1)});
	ouro_v *frame = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(88), slots});
	ouro_v *roots = ouro_apply(FIND(lo, "mir_live_roots"), function);
	ouro_v *analysis = live_exact(ouro_nat(2), roots, blocks);
	ouro_v *args[6] = {program, slots, ouro_nat(88), 0, blocks, block};
	ouro_v *fast;
	ouro_v *pure;
	ouro_v *wrapped = FIND(lo, "codegen_block");
	(void)FIND(lo, "codegen_body");
	if (analysis == 0 || analysis->tag != 1 || analysis->n != 1)
		return test_fail("root analysis");
	args[3] = OURO_F(analysis, 0);
	fast = cgb_try(program, slots, args[2], args[3], blocks, block);
	pure = test_apply6(g_raw_cgb, args);
	if (!test_bytes_equal(fast, pure) || !test_clear_prefix(fast, 32, 40, 1))
		return test_fail("MayGc old destination/live operand and dead root byte parity");
	if (!test_bytes_equal(test_apply6(wrapped, args), pure))
		return test_fail("wrapped block byte parity");
	fast = cgb_body_try(program, function, frame);
	pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
	if (!test_bytes_equal(fast, pure))
		return test_fail("body did not preserve exact root facts");
	/* NoGc must not insert dead-root clearing. The old destination is still
	   an argument, and an effectful following call prevents tail conversion. */
	OURO_F(call, 0) = ouro_ctor(0, 0, 0);
	fast = cgb_try(program, slots, args[2], args[3], blocks, block);
	pure = test_apply6(g_raw_cgb, args);
	if (!test_bytes_equal(fast, pure) || !test_clear_prefix(fast, 32, 40, 0))
		return test_fail("NoGc inserted dead-root clearing");
	/* Allocation clearing has to precede its budget branch, and the root
	   used only by a later indexed load must remain live across collection. */
	{
		ouro_v *bytes = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(2, 0, 0),
			ouro_ctor(0, 2, (ouro_v *[]){cgn_word32(64), cgn_word32(0)})});
		ouro_v *allocation = ouro_ctor(11, 5, (ouro_v *[]){ouro_nat(2),
			ouro_nat(7), ouro_nat(8), ouro_nat(9), bytes});
		ouro_v *indexed = ouro_ctor(6, 3, (ouro_v *[]){ouro_nat(2), test_use(0),
			ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(4, 0, 0),
				ouro_ctor(0, 2, (ouro_v *[]){cgn_word32(0), cgn_word32(0)})})});
		OURO_F(block, 1) = test_cons(allocation, test_cons(indexed, test_nil()));
		/* New immutable program identity invalidates cached managed metadata. */
		program = ouro_ctor(0, 4, (ouro_v *[]){test_cons(function, test_nil()),
			test_nil(), test_nil(), ouro_nat(1)});
		args[0] = program;
		analysis = live_exact(ouro_nat(2), roots, blocks);
		if (analysis == 0 || analysis->tag != 1 || analysis->n != 1)
			return test_fail("allocation root analysis");
		args[3] = OURO_F(analysis, 0);
		fast = cgb_try(program, slots, args[2], args[3], blocks, block);
		pure = test_apply6(g_raw_cgb, args);
		if (!test_bytes_equal(fast, pure) || !test_clear_prefix(fast, 32, 40, 1))
			return test_fail("allocation budget/dead root/indexed owner byte parity");
		fast = cgb_body_try(program, function, frame);
		pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
		if (!test_bytes_equal(fast, pure))
			return test_fail("allocation body byte parity");
	}
	/* A tail call unlinks the frame instead of clearing its live roots. */
	OURO_F(call, 0) = ouro_ctor(1, 0, 0);
	OURO_F(block, 1) = test_cons(call, test_nil());
	{
		static const int counts[] = { 0, 1, 4, 5 };
		ouro_v *saved_args = OURO_F(call, 3);
		ouro_v *operands[] = { test_use(0), test_use(1), test_use(2), test_use(0), test_use(1) };
		size_t i;

		for (i = 0; i < sizeof counts / sizeof counts[0]; i++) {
			int count = counts[i];

			OURO_F(call, 3) = count < 4 ? cgasm_list(operands, count)
				: cgn_cat(cgasm_list(operands, 2), cgasm_list(operands + 2, count - 2));
			analysis = live_exact(ouro_nat(2), roots, blocks);
			if (analysis == 0 || analysis->tag != 1 || analysis->n != 1)
				return test_fail("tail-argument root analysis");
			args[3] = OURO_F(analysis, 0);
			fast = cgb_try(program, slots, args[2], args[3], blocks, block);
			pure = test_apply6(g_raw_cgb, args);
			if (!test_bytes_equal(fast, pure))
				return test_fail("tail-call register and stack arguments changed bytes");
		}
		OURO_F(call, 3) = saved_args;
	}
	/* Successor facts keep an owner alive even when this block never reads
	   it itself. The next block uses it in indexed memory after the call. */
	{
		ouro_v *next = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(1),
			test_cons(ouro_ctor(6, 3, (ouro_v *[]){ouro_nat(2), test_use(0),
				ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(4, 0, 0),
					ouro_ctor(0, 2, (ouro_v *[]){cgn_word32(0), cgn_word32(0)})})}),
				test_nil()), term});
		block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0),
			test_cons(test_call(1, test_nil(), test_nil()), test_nil()),
			ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(1)})});
		blocks = test_cons(block, test_cons(next, test_nil()));
		function = test_replace_field(function, 6, blocks);
		/* Metadata is cached by immutable program identity. */
		program = test_replace_field(program, 0, test_cons(function, test_nil()));
		args[0] = program;
		analysis = live_exact(ouro_nat(3), roots, blocks);
		if (analysis == 0 || analysis->tag != 1 || analysis->n != 1)
			return test_fail("successor root analysis");
		args[3] = OURO_F(analysis, 0);
		args[4] = blocks;
		args[5] = block;
		fast = cgb_try(program, slots, args[2], args[3], blocks, block);
		if (!test_clear_prefix(fast, 32, 40, 1))
			return test_fail("successor owner cleared before MayGc call");
		fast = cgb_body_try(program, function, frame);
		pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
		if (!test_bytes_equal(fast, pure))
			return test_fail("successor owner body byte parity");
	}
	/* Unknown CFG edges remain typed failures, even with a managed slot. */
	block = test_replace_field(block, 2, ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(99)}));
	args[5] = block;
	fast = cgb_try(program, slots, args[2], args[3], blocks, block);
	pure = test_apply6(g_raw_cgb, args);
	if (fast == 0 || pure == 0 || fast->tag != 0 || pure->tag != 0
	    || fast->n != 1 || pure->n != 1
	    || OURO_F(fast, 0)->tag != 0 || OURO_F(pure, 0)->tag != 0
	    || OURO_F(fast, 0)->n != 1 || OURO_F(pure, 0)->n != 1
	    || OURO_F(OURO_F(fast, 0), 0)->tag != 6
	    || OURO_F(OURO_F(pure, 0), 0)->tag != 6
	    || as_nat(OURO_F(OURO_F(OURO_F(fast, 0), 0), 0)) != 99
	    || as_nat(OURO_F(OURO_F(OURO_F(pure, 0), 0), 0)) != 99)
		return test_fail("unknown edge lost its typed liveness failure");
	{
		ouro_v *join = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(7),
			test_cons(ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(0), test_use(1)}),
				test_nil()), term});
		block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0),
			test_cons(call, test_nil()), ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(7)})});
		blocks = test_cons(block, test_cons(join, test_nil()));
		function = test_replace_field(function, 6, blocks);
		program = test_replace_field(program, 0, test_cons(function, test_nil()));
		fast = cgb_body_try(program, function, frame);
		pure = ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, program), function), frame);
		if (!test_bytes_equal(fast, pure))
			return test_fail("tail call through a successor changed body bytes");
		if (cgb_try(program, slots, args[2], args[3],
			    test_cons(block, ouro_ctor(2, 0, 0)), block) != 0)
			return test_fail("standalone block accepted a malformed block list");
	}
	return 0;
}

static ouro_v *test_remap_instructions(ouro_v *list, unsigned long old_id,
	ouro_v *new_id, int *references)
{
	ouro_v **items = 0;
	ouro_v *result = 0;
	int n = 0, i;
	if (host_list_collect(list, &items, &n, 0) != 0)
		goto done;
	for (i = 0; i < n; i++) {
		ouro_v *instruction = items[i];
		unsigned long id;
		int field;
		if (instruction == 0 || instruction->tag < 0)
			goto done;
		if (instruction->tag != 11 && instruction->tag != 8)
			continue;
		field = instruction->tag == 11 ? 3 : 1;
		if (instruction->n <= field
		    || x64enc_dec_nat(OURO_F(instruction, field), &id) != 0)
			goto done;
		if (id == old_id) {
			items[i] = test_replace_field(instruction, field, new_id);
			if (items[i] == 0)
				goto done;
			if (instruction->tag == 11)
				(*references)++;
		}
	}
	result = cgasm_list(items, n);
done:
	free(items);
	return result;
}

static ouro_v *test_remap_blocks(ouro_v *list, unsigned long old_id,
	ouro_v *new_id, int *references)
{
	ouro_v **blocks = 0;
	ouro_v *result = 0;
	int n = 0, i;
	if (host_list_collect(list, &blocks, &n, 0) != 0)
		goto done;
	for (i = 0; i < n; i++) {
		ouro_v *instructions;
		if (blocks[i] == 0 || blocks[i]->tag != 0 || blocks[i]->n != 3)
			goto done;
		instructions = test_remap_instructions(OURO_F(blocks[i], 1), old_id, new_id, references);
		if (instructions == 0)
			goto done;
		blocks[i] = test_replace_field(blocks[i], 1, instructions);
	}
	result = cgasm_list(blocks, n);
done:
	free(blocks);
	return result;
}

static ouro_v *test_high_descriptor(ouro_v *program)
{
	ouro_v **descriptors = 0, **globals = 0, **functions = 0, **objects = 0;
	ouro_v *result = 0;
	ouro_v *new_id;
	unsigned long old_id, maximum = 65535UL;
	int nd = 0, ng = 0, nf = 0, no = 0;
	int definitions = 0, references = 0, i;
	if (program == 0 || program->tag != 0 || program->n != 4
	    || host_list_collect(ouro_apply(FIND(lo, "mir_managed_descriptors"), program),
		&descriptors, &nd, 0) != 0 || nd == 0
	    || x64enc_dec_nat(descriptors[0], &old_id) != 0
	    || host_list_collect(ouro_apply(FIND(lo, "mir_global_ids"), program),
		&globals, &ng, 0) != 0)
		goto done;
	for (i = 0; i < ng; i++) {
		unsigned long id;
		if (x64enc_dec_nat(globals[i], &id) != 0)
			goto done;
		if (id > maximum)
			maximum = id;
	}
	if (maximum == ULONG_MAX)
		goto done;
	new_id = ouro_nat(maximum + 1UL);
	if (host_list_collect(OURO_F(program, 0), &functions, &nf, 0) != 0
	    || host_list_collect(OURO_F(program, 1), &objects, &no, 0) != 0)
		goto done;
	for (i = 0; i < nf; i++) {
		ouro_v *blocks;
		if (functions[i] == 0 || functions[i]->tag != 0 || functions[i]->n != 7)
			goto done;
		blocks = test_remap_blocks(OURO_F(functions[i], 6), old_id, new_id, &references);
		if (blocks == 0)
			goto done;
		functions[i] = test_replace_field(functions[i], 6, blocks);
	}
	for (i = 0; i < no; i++) {
		unsigned long id;
		if (objects[i] == 0 || objects[i]->tag != 0 || objects[i]->n != 3
		    || x64enc_dec_nat(OURO_F(objects[i], 0), &id) != 0)
			goto done;
		if (id == old_id) {
			objects[i] = test_replace_field(objects[i], 0, new_id);
			definitions++;
		}
	}
	if (definitions != 1 || references == 0)
		goto done;
	result = ouro_ctor(0, 4, (ouro_v *[]){cgasm_list(functions, nf),
		cgasm_list(objects, no), OURO_F(program, 2), OURO_F(program, 3)});
done:
	free(descriptors);
	free(globals);
	free(functions);
	free(objects);
	return result;
}

static int test_live_image(const char *mode, const char *output)
{
	ouro_v *unit = test_nil();
	ouro_v *loaded = ouro_apply(ouro_apply(FIND(lo, "native_build_load_source"),
		ouro_str("tests/native_managed/runtime.ouro")), unit);
	ouro_v *limits = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(8192),
		ouro_nat(1048576), ouro_nat(4096)});
	ouro_v *input;
	ouro_v *root;
	ouro_v *runtime;
	ouro_v *program;
	ouro_v *image;
	ouro_v *published;
	if (loaded == 0 || loaded->tag != 1 || loaded->n != 1)
		return test_fail("could not load checked raw runtime source closure");
	input = OURO_F(loaded, 0);
	if (input == 0 || input->tag != 0 || input->n != 2)
		return test_fail("raw runtime source closure shape");
	root = ouro_apply(FIND(lo, "native_build_normalize"), OURO_F(input, 0));
	root = ouro_apply(ouro_io_prim_req("prim_string_to_char_codes"), root);
	runtime = ouro_apply(ouro_apply(ouro_apply(FIND(lo, "managed_fixture_runtime_with_limits"),
		limits), root), OURO_F(input, 1));
	if (runtime == 0 || runtime->tag != 1 || runtime->n != 1)
		return test_fail("checked raw runtime lowering");
	if (strcmp(mode, "escaping_collect") == 0)
		program = ouro_apply(FIND(lo, "managed_value_escape_collect"), OURO_F(runtime, 0));
	else if (strcmp(mode, "pap_reuse_collect") == 0)
		program = ouro_apply(FIND(lo, "managed_value_pap_collect"), OURO_F(runtime, 0));
	else if (strcmp(mode, "pap_plateau") == 0)
		program = ouro_apply(FIND(lo, "live_runtime_pap_plateau"), OURO_F(runtime, 0));
	else
		program = ouro_apply(FIND(lo, strcmp(mode, "live-calls") == 0
			? "live_runtime_calls" : "live_runtime_reclaim"), OURO_F(runtime, 0));
	if (strcmp(mode, "live-high-descriptor") == 0) {
		program = test_high_descriptor(program);
		if (program == 0)
			return test_fail("high descriptor fixture reconstruction");
	}
	image = ouro_apply(ouro_apply(FIND(lo, "codegen_program"), limits), program);
	if (image == 0 || image->tag != 1 || image->n != 1)
		return test_fail("validated liveness fixture image emission");
	published = ouro_apply(ouro_apply(ouro_apply(FIND(lo, "native_build_publish_image"),
		ouro_str(output)), OURO_F(image, 0)), unit);
	if (published == 0 || published->tag != 1 || published->n != 1)
		return test_fail("liveness fixture image publication");
	return 0;
}

static int test_file_read_status_mode(const char *text, unsigned long *mode)
{
	static const char *const names[] = {"0", "8", "9", "10", "11", "12",
		"13", "14", "15", "16", "17", "18"};
	static const unsigned long values[] = {0, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18};
	size_t i;
	for (i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
		if (strcmp(text, names[i]) == 0) {
			*mode = values[i];
			return 0;
		}
	}
	return 2;
}

static int test_file_read_status_image(unsigned long mode, const char *output)
{
	ouro_v *unit = test_nil();
	ouro_v *loaded = ouro_apply(ouro_apply(FIND(lo, "native_build_load_source"),
		ouro_str("tests/native_managed/source_file_read_status_fault.ouro")), unit);
	ouro_v *limits = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(8192),
		ouro_nat(1048576), ouro_nat(4096)});
	ouro_v *input;
	ouro_v *root;
	ouro_v *parts;
	ouro_v *transformed;
	ouro_v *validated;
	ouro_v *lowered;
	ouro_v *image;
	ouro_v *published;
	if (loaded == 0 || loaded->tag != 1 || loaded->n != 1)
		return test_fail("could not load checked file status source closure");
	input = OURO_F(loaded, 0);
	if (input == 0 || input->tag != 0 || input->n != 2)
		return test_fail("file status source closure shape");
	root = ouro_apply(FIND(lo, "native_build_normalize"), OURO_F(input, 0));
	root = ouro_apply(ouro_io_prim_req("prim_string_to_char_codes"), root);
	parts = ouro_apply(ouro_apply(ouro_apply(ouro_apply(FIND(lo, "frontend_host_file_status_parts"),
		ouro_nat(16000)), limits), root), OURO_F(input, 1));
	if (parts == 0 || parts->tag != 1 || parts->n != 1)
		return test_fail("checked file status source lowering");
	parts = OURO_F(parts, 0);
	if (parts == 0 || parts->tag != 0 || parts->n != 3)
		return test_fail("checked file status parts shape");
	transformed = ouro_apply(ouro_apply(FIND(lo, "native_file_read_status_fixture"), ouro_nat(mode)), parts);
	if (transformed == 0 || transformed->tag != 1 || transformed->n != 1)
		return test_fail("file status fault reconstruction");
	parts = ouro_ctor(0, 3, (ouro_v *[]){OURO_F(parts, 0), OURO_F(parts, 1), OURO_F(transformed, 0)});
	validated = ouro_apply(ouro_apply(FIND(lo, "managed_validate_parts"), limits), parts);
	if (validated == 0 || validated->tag != 1 || validated->n != 1)
		return test_fail("transformed file status MIR/GC validation");
	lowered = OURO_F(validated, 0);
	if (lowered == 0 || lowered->tag != 0 || lowered->n != 3)
		return test_fail("validated file status parts shape");
	image = ouro_apply(ouro_apply(FIND(lo, "codegen_program"), limits), OURO_F(lowered, 2));
	if (image == 0 || image->tag != 1 || image->n != 1)
		return test_fail("validated file status image emission");
	published = ouro_apply(ouro_apply(ouro_apply(FIND(lo, "native_build_publish_image"),
		ouro_str(output)), OURO_F(image, 0)), unit);
	if (published == 0 || published->tag != 1 || published->n != 1)
		return test_fail("file status image publication");
	return 0;
}

static ouro_v *test_replay_rows(ouro_v *rows, int key_field, ouro_v *key,
	int value_field, ouro_v *replacement)
{
	ouro_v *row, *tail;
	if (rows != 0 && rows->tag == 0 && rows->n == 0)
		return rows;
	if (rows == 0 || rows->tag != 1 || rows->n != 2)
		return 0;
	row = OURO_F(rows, 0);
	if (row == 0 || row->tag < 0 || row->n <= key_field)
		return 0;
	if (test_pe_value_equal(OURO_F(row, key_field), key))
		row = test_replace_field(row, value_field, replacement);
	tail = test_replay_rows(OURO_F(rows, 1), key_field, key, value_field, replacement);
	return row == 0 || tail == 0 ? 0 : test_cons(row, tail);
}

static int test_replay_identity(ouro_v *result, ouro_v *program, ouro_v *wide,
	ouro_v *annotation, ouro_v *body)
{
	ouro_v *checked, *rows, *entry, *value;
	int found = 0;
	if (result == 0 || result->tag != 1 || result->n != 1)
		return 0;
	checked = OURO_F(result, 0);
	if (checked == 0 || checked->tag != 0 || checked->n != 3
	    || OURO_F(checked, 0) != OURO_F(program, 0)
	    || OURO_F(checked, 2) != OURO_F(program, 2)
	    || !test_pe_value_equal(checked, program))
		return 0;
	for (rows = OURO_F(checked, 1); rows != 0 && rows->tag == 1 && rows->n == 2;
	     rows = OURO_F(rows, 1)) {
		entry = OURO_F(rows, 0);
		if (entry != 0 && entry->tag == 0 && entry->n == 3 && OURO_F(entry, 0) == wide) {
			value = OURO_F(entry, 2);
			if (OURO_F(entry, 1) != annotation || value == 0 || value->tag != 1
			    || value->n != 1 || OURO_F(value, 0) != body)
				return 0;
			found++;
		}
	}
	return found == 1 && rows != 0 && rows->tag == 0 && rows->n == 0;
}

static int test_replay_type_identity(ouro_v *result, ouro_v *wide)
{
	ouro_v *rows;
	int found = 0;
	if (result == 0 || result->tag != 1 || result->n != 1)
		return 0;
	for (rows = OURO_F(result, 0); rows != 0 && rows->tag == 1 && rows->n == 2;
	     rows = OURO_F(rows, 1))
		if (OURO_F(rows, 0) == wide)
			found++;
	return found == 1 && rows != 0 && rows->tag == 0 && rows->n == 0;
}

static int test_native_prepare_lookup_context(ouro_v *program, ouro_v *wide)
{
	static const char *spellings[] = {"Alias", "_ouro_m_0_Alias", "_ouro_m_42_Alias",
		"_ouro_m_01_Alias", "_ouro_m_42_Aliases", "missing"};
	ouro_v *environment = FIND(fc, "check_environment_from_entries");
	ouro_v *symbol = FIND(lo, "managed_source_symbol_using");
	ouro_v *spelling = FIND(lo, "managed_source_spelling");
	ouro_v *callbacks[3] = {environment, symbol, spelling}, *raw[3], *scope;
	ouro_v *(*functions[3])(ouro_env *, ouro_v *) =
		{check_environment_entries, managed_symbol_program, managed_spelling_requested};
	unsigned long arities[3] = {1, 3, 2};
	ouro_v *entries = OURO_F(program, 1), *name = ouro_string_codes("Alias"), *names;
	ouro_v *expected, *first, *last, *first_symbol, *last_symbol, *partial, *bundle, *bad;
	ouro_v *args[3], *pair, *error;
	ouro_heap_context *outer;
	ouro_env *captures;
	int i;
	for (i = 0; i < 3; i++) {
		if (callbacks[i] == 0 || callbacks[i]->tag != OURO_TAG_CLOS || callbacks[i]->u.c.fn != functions[i])
			return test_fail("native prepare lookup lifetime hook missing");
		scope = ouro_get(callbacks[i]->u.c.env, 0);
		if (scope == 0 || scope->tag != OURO_TAG_CLOS || scope->u.c.fn != module_pure_scope_argument
		    || as_nat(ouro_get(scope->u.c.env, 0)) != arities[i])
			return test_fail("native prepare lookup pure scope arity");
		raw[i] = ouro_get(scope->u.c.env, 1);
	}
	expected = test_contract_scoped(raw[0], &entries, 1);
	outer = ouro_heap_context_enter();
	first = ouro_apply(environment, entries);
	if (first == 0 || first->tag != 0 || first->n != 2 || OURO_F(first, 0) != entries
	    || !test_pe_value_equal(first, expected))
		return test_fail("native prepare complete environment and borrowed entries");
	args[0] = program; args[1] = first; args[2] = name;
	partial = test_apply(symbol, args, 2);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS)
		return test_fail("native prepare reusable symbol lookup");
	first_symbol = ouro_apply(partial, name);
	last = first; last_symbol = first_symbol;
	for (i = 0; i < 8; i++) {
		last = ouro_apply(environment, entries);
		last_symbol = ouro_apply(partial, name);
		if (OURO_F(last, 0) != entries || !test_pe_value_equal(last, expected)
		    || !test_pe_value_equal(first, expected) || !test_pe_value_equal(first_symbol, last_symbol)
		    || last_symbol == 0 || last_symbol->tag != 1 || last_symbol->n != 1 || OURO_F(last_symbol, 0) != wide)
			return test_fail("native prepare complete environment or full symbol survivor");
	}
	bundle = ouro_heap_context_leave(outer, ouro_ctor(0, 5,
		(ouro_v *[]){first, last, first_symbol, last_symbol, partial}));
	first = OURO_F(bundle, 0); last = OURO_F(bundle, 1);
	first_symbol = OURO_F(bundle, 2); last_symbol = OURO_F(bundle, 3); partial = OURO_F(bundle, 4);
	args[1] = first;
	if (OURO_F(first, 0) != entries || OURO_F(last, 0) != entries
	    || !test_pe_value_equal(first, expected) || !test_pe_value_equal(last, expected)
	    || OURO_F(first_symbol, 0) != wide || OURO_F(last_symbol, 0) != wide
	    || !test_pe_value_equal(ouro_apply(partial, name), test_contract_scoped(raw[1], args, 3)))
		return test_fail("native prepare caller captures or full ID after outer leave");
	args[2] = ouro_string_codes("missing");
	error = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(7, 1, (ouro_v *[]){ouro_nat(0)})});
	if (!test_pe_value_equal(test_contract_scoped(raw[1], args, 3), error)
	    || !test_pe_value_equal(test_apply(symbol, args, 3), error))
		return test_fail("native prepare exact missing symbol rejection");
	names = OURO_F(OURO_F(program, 0), 0);
	for (pair = 0; names != 0 && names->tag == 1 && names->n == 2; names = OURO_F(names, 1))
		if (OURO_F(OURO_F(names, 0), 1) == wide)
			pair = OURO_F(names, 0);
	if (pair == 0)
		return test_fail("native prepare wide symbol row");
	bad = test_replace_field(program, 0, test_replace_field(OURO_F(program, 0), 0,
		test_cons(pair, OURO_F(OURO_F(program, 0), 0))));
	args[0] = bad; args[2] = name;
	error = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(2, 1, (ouro_v *[]){ouro_nat(0)})});
	if (!test_pe_value_equal(test_contract_scoped(raw[1], args, 3), error)
	    || !test_pe_value_equal(test_apply(symbol, args, 3), error))
		return test_fail("native prepare exact duplicate spelling rejection");
	args[0] = name;
	partial = ouro_apply(spelling, name);
	captures = partial->u.c.env;
	for (i = 0; i < 6; i++) {
		args[1] = ouro_string_codes(spellings[i]);
		expected = ouro_ctor(i < 3 ? 0 : 1, 0, 0);
		if (!test_pe_value_equal(test_contract_scoped(raw[2], args, 2), expected)
		    || !test_pe_value_equal(ouro_apply(partial, args[1]), expected) || partial->u.c.env != captures)
			return test_fail("native prepare source spelling parity or reusable capture");
	}
	return 0;
}

static int test_native_replay_context(int probe)
{
	static const char source[] =
		"axiom A : Type; axiom a : A; def identity (x : A) : A := x; "
		"def Alias (T : Type) : Type := T;";
	const uint32_t limbs[3] = {17, 0, 1};
	ouro_v *wrapped = FIND(lo, "lower_recheck_program"), *types = FIND(pl, "checked_program_type_globals_indexed");
	ouro_v *raw, *raw_types, *normalize = FIND(el, "normalize_checked_indexed");
	ouro_v *fuel = ouro_nat(16000), *result, *program, *id, *entry, *annotation, *body;
	ouro_v *half, *wide, *snapshot, *intern, *rows, *args[2], *type_args[3], *reference, *type_reference;
	ouro_v *first, *last, *first_types, *last_types, *bundle, *bad, *expected, *empty;
	ouro_v *partial, *type_partial;
	ouro_v *callable, *type_callable;
	ouro_env *partial_env, *type_env;
	ouro_heap_context *outer;
	unsigned long long before, retained, start, allocated, live_delta, total_delta;
	int i, raw_probe = probe == 1;
	int replay_hook = wrapped != 0 && wrapped->tag == OURO_TAG_CLOS
		&& wrapped->u.c.fn == module_pure_scope_argument
		&& as_nat(ouro_get(wrapped->u.c.env, 0)) == 2UL;
	int type_hook = types != 0 && types->tag == OURO_TAG_CLOS
		&& types->u.c.fn == import_token_fuel;
	if (!raw_probe && (!replay_hook || !type_hook))
		return test_fail("complete native replay or indexed type-global lifetime hook missing");
	raw = replay_hook ? ouro_get(wrapped->u.c.env, 1) : wrapped;
	raw_types = type_hook ? ouro_get(types->u.c.env, 0) : types;
	if (raw == 0 || raw->tag != OURO_TAG_CLOS || raw_types == 0 || raw_types->tag != OURO_TAG_CLOS)
		return test_fail("native replay canonical raw callbacks missing");
	callable = raw_probe ? raw : wrapped;
	type_callable = raw_probe ? raw_types : types;
	result = test_contract_scoped(FIND(pl, "compile_checked_source"),
		(ouro_v *[]){fuel, ouro_string_codes(source)}, 2);
	if (result == 0 || result->tag != 1 || result->n != 1)
		return test_fail("native replay source acceptance");
	program = OURO_F(result, 0);
	result = test_apply(FIND(lo, "managed_source_symbol"),
		(ouro_v *[]){program, ouro_string_codes("Alias")}, 2);
	if (result == 0 || result->tag != 1 || result->n != 1)
		return test_fail("native replay checked type-former name");
	id = OURO_F(result, 0);
	result = test_apply(FIND(lo, "lower_find_entry"), (ouro_v *[]){id, OURO_F(program, 1)}, 2);
	if (result == 0 || result->tag != 1 || result->n != 1)
		return test_fail("native replay checked ordinary entry");
	entry = OURO_F(result, 0);
	if (entry == 0 || entry->tag != 0 || entry->n != 3
	    || OURO_F(entry, 2) == 0 || OURO_F(entry, 2)->tag != 1 || OURO_F(entry, 2)->n != 1)
		return test_fail("native replay checked body shape");
	annotation = OURO_F(entry, 1); body = OURO_F(OURO_F(entry, 2), 0);
	half = ouro_nat_u64(UINT64_C(0x8000000000000000));
	wide = ouro_apply(ouro_apply(ouro_fast("add"), half), half);
	wide = ouro_apply(ouro_apply(ouro_fast("add"), wide), ouro_nat(17));
	if (wide == 0 || wide->tag != OURO_TAG_BIG_NAT || wide->n != 3
	    || memcmp(wide + 1, limbs, sizeof limbs) != 0)
		return test_fail("native replay full ID construction");
	snapshot = ouro_clone_perm_deep(wide);
	if (snapshot == wide || !test_pe_value_equal(snapshot, wide)
	    || test_pe_value_equal(snapshot, ouro_nat(17)))
		return test_fail("native replay full Nat equality");
	/* Alias is a leaf. Relabel all three public tables before strict replay. */
	intern = OURO_F(program, 0);
	intern = test_replace_field(intern, 0, test_replay_rows(OURO_F(intern, 0), 1, id, 1, wide));
	intern = test_replace_field(intern, 1, ouro_apply(ouro_apply(ouro_fast("add"), wide), ouro_nat(1)));
	program = ouro_ctor(0, 3, (ouro_v *[]){intern,
		test_replay_rows(OURO_F(program, 1), 0, id, 0, wide),
		test_replay_rows(OURO_F(program, 2), 0, id, 0, wide)});
	if (probe == 0 && test_native_prepare_lookup_context(program, wide) != 0)
		return 1;
	args[0] = fuel; args[1] = program;
	reference = test_contract_scoped(raw, args, 2);
	if (!test_replay_identity(reference, program, wide, annotation, body))
		return test_fail("wide native replay retains complete checked metadata and bodies");
	type_args[0] = normalize; type_args[1] = fuel; type_args[2] = OURO_F(reference, 0);
	type_reference = test_contract_scoped(raw_types, type_args, 3);
	if (!test_replay_type_identity(type_reference, wide))
		return test_fail("indexed type-global reference preserves full checked ID");
	partial = ouro_apply(callable, fuel);
	type_partial = test_apply(type_callable, type_args, 2);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS
	    || type_partial == 0 || type_partial->tag != OURO_TAG_CLOS)
		return test_fail("native replay reusable partial shape");
	partial_env = partial->u.c.env; type_env = type_partial->u.c.env;
	outer = ouro_heap_context_enter();
	before = ouro_heap_live_bytes();
	allocated = ouro_heap_total_alloc_bytes();
	first = ouro_apply(partial, program);
	if (!test_replay_identity(first, program, wide, annotation, body))
		return test_fail("native replay first complete retained result");
	first_types = ouro_apply(type_partial, OURO_F(first, 0));
	retained = ouro_heap_live_bytes() - before;
	start = ouro_heap_live_bytes();
	last = first; last_types = first_types;
	for (i = 0; i < 8; i++) {
		last = ouro_apply(partial, program);
		if (!test_replay_identity(last, program, wide, annotation, body))
			return test_fail("native replay next complete retained result");
		last_types = ouro_apply(type_partial, OURO_F(last, 0));
		if (!test_replay_identity(first, program, wide, annotation, body)
		    || !test_replay_identity(last, program, wide, annotation, body)
		    || !test_pe_value_equal(first, reference) || !test_pe_value_equal(last, reference)
		    || !test_replay_type_identity(first_types, wide) || !test_replay_type_identity(last_types, wide)
		    || !test_pe_value_equal(first_types, type_reference) || !test_pe_value_equal(last_types, type_reference)
		    || (!raw_probe && ouro_heap_live_bytes() - start >
		        (unsigned long long)(i + 1) * (retained + 4096ULL) + 1048576ULL))
			return test_fail("complete native replay survivors or scratch lifetime");
	}
	live_delta = ouro_heap_live_bytes() - before;
	total_delta = ouro_heap_total_alloc_bytes() - allocated;
	bundle = ouro_heap_context_leave(outer, ouro_ctor(0, 4,
		(ouro_v *[]){first, first_types, last, last_types}));
	first = OURO_F(bundle, 0); first_types = OURO_F(bundle, 1);
	last = OURO_F(bundle, 2); last_types = OURO_F(bundle, 3);
	result = ouro_apply(type_partial, OURO_F(first, 0));
	if (!test_replay_identity(first, program, wide, annotation, body)
	    || !test_replay_identity(last, program, wide, annotation, body)
	    || !test_replay_type_identity(first_types, wide) || !test_replay_type_identity(last_types, wide)
	    || !test_replay_identity(ouro_apply(partial, program), program, wide, annotation, body)
	    || !test_replay_type_identity(result, wide) || !test_pe_value_equal(result, type_reference)
	    || partial->u.c.env != partial_env || type_partial->u.c.env != type_env
	    || (!raw_probe && (ouro_get(partial_env, 1) != fuel || ouro_get(partial_env, 2) != raw
	        || ouro_get(type_env, 0) != fuel || ouro_get(type_env, 1) != normalize || ouro_get(type_env, 2) != raw_types))
	    || FIND(lo, "lower_recheck_program") != wrapped || FIND(pl, "checked_program_type_globals_indexed") != types
	    || memcmp(wide + 1, limbs, sizeof limbs) != 0)
		return test_fail("native replay caller, full ID, body or reusable closure changed after outer leave");
	rows = test_replay_rows(OURO_F(program, 2), 0, wide, 1, ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(0)}));
	bad = test_replace_field(program, 2, rows);
	args[1] = bad;
	expected = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(3, 1, &wide)});
	if (!test_pe_value_equal(test_contract_scoped(raw, args, 2), expected)
	    || !test_pe_value_equal(test_apply(callable, args, 2), expected))
		return test_fail("native replay complete wide-ID body mismatch rejection");
	args[1] = test_replace_field(program, 1,
		test_cons(OURO_F(OURO_F(program, 1), 0), OURO_F(program, 1)));
	expected = test_contract_scoped(raw, args, 2);
	if (expected == 0 || expected->tag != 0 || expected->n != 1
	    || OURO_F(expected, 0) == 0 || OURO_F(expected, 0)->tag != 1 || OURO_F(expected, 0)->n != 3
	    || OURO_F(OURO_F(expected, 0), 0) != wide
	    || OURO_F(OURO_F(expected, 0), 1) == 0 || OURO_F(OURO_F(expected, 0), 1)->tag != 0
	    || OURO_F(OURO_F(expected, 0), 1)->n != 0
	    || !test_pe_value_equal(test_apply(callable, args, 2), expected))
		return test_fail("native replay complete duplicate declaration rejection");
	args[0] = ouro_nat(0); args[1] = program;
	expected = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 0, 0)});
	if (!test_pe_value_equal(test_contract_scoped(raw, args, 2), expected)
	    || !test_pe_value_equal(test_apply(callable, args, 2), expected))
		return test_fail("native replay complete zero-fuel rejection");
	type_args[1] = args[0]; type_args[2] = OURO_F(first, 0);
	expected = cerr(44, 0);
	if (!test_pe_value_equal(test_contract_scoped(raw_types, type_args, 3), expected)
	    || !test_pe_value_equal(test_apply(type_callable, type_args, 3), expected))
		return test_fail("indexed type-global complete zero-fuel rejection");
	empty = ouro_ctor(0, 3, (ouro_v *[]){intern, test_nil(), test_nil()});
	args[0] = ouro_nat(1); args[1] = empty;
	expected = ouro_ctor(1, 1, &empty);
	if (!test_pe_value_equal(test_contract_scoped(raw, args, 2), expected)
	    || !test_pe_value_equal(test_apply(callable, args, 2), expected))
		return test_fail("complete empty native replay result");
	type_args[2] = empty;
	expected = ouro_ctor(1, 1, (ouro_v *[]){test_nil()});
	if (!test_pe_value_equal(test_contract_scoped(raw_types, type_args, 3), expected)
	    || !test_pe_value_equal(test_apply(type_callable, type_args, 3), expected)
	    || !test_replay_identity(first, program, wide, annotation, body)
	    || !test_pe_value_equal(first_types, type_reference))
		return test_fail("empty type-global result or earlier complete replay survivor changed");
	if (probe != 0)
		printf("NATIVE_REPLAY_HEAP: mode=%s replays=9 classifications=9 live_delta=%llu total_delta=%llu\n",
			raw_probe ? "raw" : "wrapped", live_delta, total_delta);
	return 0;
}

int main(int argc, char **argv)
{
	int result;
	ouro_rt_warmup();
	ouro_io_set_argv(argc, argv);
	if (argc == 4 && strcmp(argv[1], "file-read-status") == 0) {
		unsigned long mode;
		if (test_file_read_status_mode(argv[2], &mode) != 0)
			return 2;
		result = test_file_read_status_image(mode, argv[3]);
		if (result == 0)
			printf("FRONTEND_CODEGEN_SELFTEST: passed file-read-status %s\n", argv[2]);
		return result;
	}
	if (argc == 3 && (strcmp(argv[1], "live-reclaim") == 0
	    || strcmp(argv[1], "live-calls") == 0 || strcmp(argv[1], "live-high-descriptor") == 0
	    || strcmp(argv[1], "escaping_collect") == 0 || strcmp(argv[1], "pap_reuse_collect") == 0
	    || strcmp(argv[1], "pap_plateau") == 0))
		result = test_live_image(argv[1], argv[2]);
	else if (argc != 2)
		return 2;
	else if (strcmp(argv[1], "fallback-forward") == 0)
		result = test_forwarded_arguments();
	else if (strcmp(argv[1], "root-parity") == 0) {
		result = test_tail_successors();
		if (result == 0)
			result = test_block_positions();
		if (result == 0)
			result = test_slot_root_state();
		if (result == 0)
			result = test_scalar_body();
		if (result == 0)
			result = test_tail_chain_body();
		if (result == 0)
			result = test_roots();
		if (result == 0)
			result = test_assembly_labels();
		if (result == 0)
			result = test_assembly_buffer_growth();
		if (result == 0)
			result = test_prepared_code_concat();
		if (result == 0)
			result = test_frame_slots();
	}
	else if (strcmp(argv[1], "root-clear-context") == 0)
		result = test_root_clear_context();
	else if (strcmp(argv[1], "lower-contract-context") == 0)
		result = test_lower_contract_context();
	else if (strcmp(argv[1], "check-module-context") == 0) {
		result = test_preflight_context();
		if (result == 0)
			result = test_check_module_context();
		if (result == 0)
			result = test_native_replay_context(0);
	}
	else if (strcmp(argv[1], "native-replay-heap-raw") == 0)
		result = test_native_replay_context(1);
	else if (strcmp(argv[1], "native-replay-heap-wrapped") == 0)
		result = test_native_replay_context(2);
	else if (strcmp(argv[1], "mir-bounds-outcomes") == 0)
		result = test_mir_bounds_context(0);
	else if (strcmp(argv[1], "mir-bounds-context") == 0)
		result = test_mir_bounds_context(1);
	else if (strcmp(argv[1], "mir-function-partial") == 0)
		result = test_mir_function_partial();
	else if (strcmp(argv[1], "mir-function-context") == 0)
		result = test_mir_function_context();
	else if (strcmp(argv[1], "pe-operation-context") == 0)
		result = test_pe_operations();
	else
		return 2;
	if (result == 0)
		printf("FRONTEND_CODEGEN_SELFTEST: passed %s\n", argv[1]);
	return result;
}
