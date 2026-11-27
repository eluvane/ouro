/* Exercise native-host metadata without substituting for MIR acceptance. */
#ifndef OURO_FE_FLAT_EXPORTS
#define OURO_FE_FLAT_EXPORTS
#endif
#include "frontend_link.c"

static ouro_v *preparation_probe_term(ouro_env *env, ouro_v *term)
{
	ouro_v *temporary[1];
	ouro_v *fields[1];
	int i;
	if (as_nat(ouro_get(env, 2)) != 37UL
	    || as_nat(ouro_get(env, 1)) != 45UL
	    || as_nat(ouro_get(env, 0)) != 55UL)
		return 0;
	for (i = 0; i < 20000; ++i) {
		temporary[0] = term;
		(void)ouro_ctor(71, 1, temporary);
	}
	if (as_nat(term) == 0UL) {
		fields[0] = ouro_ctor(3, 0, 0);
		return ouro_ctor(1, 1, fields);
	}
	temporary[0] = ouro_nat(as_nat(term));
	fields[0] = ouro_ctor(6, 1, temporary);
	return ouro_ctor(0, 1, fields);
}

static ouro_v *preparation_probe_types(ouro_env *env, ouro_v *types)
{
	return ouro_clos(preparation_probe_term, ouro_cons(types, env));
}

static ouro_v *preparation_probe_environment(ouro_env *env, ouro_v *environment)
{
	return ouro_clos(preparation_probe_types, ouro_cons(environment, env));
}

static ouro_v *preparation_probe_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(preparation_probe_environment, ouro_cons(fuel, env));
}

static int preparation_context_check(void)
{
	ouro_v *raw = ouro_clos(preparation_probe_fuel, 0);
	ouro_v *prepare = ouro_clos(emission_prepare_fuel, ouro_cons(raw, 0));
	ouro_v *result;
	ouro_v *results[16];
	unsigned long long before;
	int i;
	prepare = ouro_apply(ouro_apply(ouro_apply(prepare, ouro_nat(37)),
		ouro_nat(45)), ouro_nat(55));
	for (i = 0; i < 16; ++i) {
		before = ouro_heap_live_bytes();
		result = ouro_apply(prepare, ouro_nat((unsigned long)(66 + i)));
		results[i] = result;
		if (result == 0 || result->tag != 0 || result->n != 1
		    || OURO_F(result, 0)->tag != 6
		    || as_nat(OURO_F(OURO_F(result, 0), 0)) != (unsigned long)(66 + i)
		    || ouro_heap_live_bytes() - before > 65536ULL)
			return 1;
	}
	result = ouro_apply(prepare, ouro_nat(0));
	if (result == 0 || result->tag != 1 || result->n != 1
	    || OURO_F(result, 0)->tag != 3 || OURO_F(result, 0)->n != 0)
		return 1;
	for (i = 0; i < 16; ++i)
		if (as_nat(OURO_F(OURO_F(results[i], 0), 0)) != (unsigned long)(66 + i))
			return 1;
	return 0;
}

static ouro_v *meta_program(void)
{
	unsigned long ids[] = {65536UL, 65535UL, 1000000UL, 65536UL};
	ouro_v *instructions[4];
	ouro_v *objects[3];
	ouro_v *empty = ouro_ctor(0, 0, 0);
	unsigned char descriptor[40] = {1, 0, 0, 0, 6, 0, 0, 0, 40};
	ouro_v *fields[7];
	int i;

	for (i = 0; i < 4; i++) {
		ouro_v *allocation[5] = {ouro_nat(0), ouro_nat(2),
			ouro_nat(3), ouro_nat(ids[i]), empty};
		instructions[i] = ouro_ctor(11, 5, allocation);
	}
	fields[0] = ouro_nat(0);
	fields[1] = cgasm_list(instructions, 4);
	fields[2] = ouro_ctor(3, 0, 0);
	fields[6] = cgasm_list((ouro_v *[]){ouro_ctor(0, 3, fields)}, 1);
	fields[0] = ouro_nat(1);
	fields[1] = empty;
	fields[2] = empty;
	fields[3] = empty;
	fields[4] = empty;
	fields[5] = ouro_nat(0);
	fields[0] = cgasm_list((ouro_v *[]){ouro_ctor(0, 7, fields)}, 1);
	for (i = 0; i < 3; i++) {
		ouro_v *object[3] = {ouro_nat(ids[i]), ouro_ctor(0, 0, 0),
			ouro_bytes(descriptor, sizeof descriptor)};
		objects[i] = ouro_ctor(0, 3, object);
	}
	fields[1] = cgasm_list(objects, 3);
	fields[2] = empty;
	fields[3] = ouro_nat(1);
	return ouro_ctor(0, 4, fields);
}

static ouro_v *meta_function(ouro_v *program)
{
	return OURO_F(OURO_F(program, 0), 0);
}

static ouro_v *meta_allocation(ouro_v *program)
{
	ouro_v *block = OURO_F(OURO_F(meta_function(program), 6), 0);

	return OURO_F(OURO_F(block, 1), 0);
}

static int metadata_check(void)
{
	ouro_v *program = meta_program();

	if (cgn_refresh_meta(program) != 0 || g_cgn_nobj != 3
	    || g_cgn_nall != 3 || g_cgn_budget_off != 88UL
	    || g_cgn_alldesc[0] != 65535UL
	    || g_cgn_alldesc[1] != 1000000UL
	    || g_cgn_alldesc[2] != 65536UL) {
		fputs("FRONTEND_CODEGEN_META: descriptor ordering/count failed\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(meta_allocation(program), 3) = ouro_ctor(77, 0, 0);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: malformed descriptor accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(meta_allocation(program), 3) = ouro_nat(ULONG_MAX);
	if (cgn_refresh_meta(program) != 0 || g_cgn_nobj != 4
	    || g_cgn_alldesc[0] != ULONG_MAX || g_cgn_budget_off != 104UL) {
		fputs("FRONTEND_CODEGEN_META: host-width descriptor lost\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(meta_function(program), 0) = ouro_nat(ULONG_MAX);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: overflowing runtime ID accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	meta_allocation(program)->n = 4;
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: truncated allocation accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	{
		ouro_v *block = OURO_F(OURO_F(meta_function(program), 6), 0);
		ouro_v *example = meta_allocation(program);
		ouro_v *allocations[73];
		int i;

		for (i = 0; i < 72; i++) {
			allocations[i] = ouro_ctor(11, 5, ouro_fields(example));
			OURO_F(allocations[i], 3) = ouro_nat(100UL + (unsigned long)i);
		}
		allocations[72] = allocations[0];
		OURO_F(block, 1) = cgasm_list(allocations, 73);
		if (cgn_refresh_meta(program) != 0 || g_cgn_nobj != 72 || g_cgn_alldesc[71] != 100UL) {
			fputs("FRONTEND_CODEGEN_META: growing descriptor buffer lost the final occurrence\n", stderr);
			return 1;
		}
		for (i = 0; i < 71; i++)
			if (g_cgn_alldesc[i] != 101UL + (unsigned long)i) {
				fputs("FRONTEND_CODEGEN_META: growing descriptor buffer changed site order\n", stderr);
				return 1;
			}
	}
	program = meta_program();
	{
		ouro_v *function = meta_function(program);
		ouro_v *block = OURO_F(OURO_F(function, 6), 0);
		ouro_v *instructions = OURO_F(block, 1);
		ouro_v *tail = OURO_F(instructions, 1);
		ouro_v *left = cgasm_list(ouro_fields(instructions), 1);
		ouro_v *right = cgasm_list(ouro_fields(tail), 1);
		ouro_v *next = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(1), OURO_F(tail, 1), OURO_F(block, 2)});

		OURO_F(block, 1) = cgn_cat(left, right);
		OURO_F(function, 6) = cgn_cat(cgasm_list(&block, 1), cgasm_list(&next, 1));
		if (cgn_refresh_meta(program) != 0 || g_cgn_nobj != 3 || g_cgn_budget_off != 88UL
		    || g_cgn_alldesc[0] != 65535UL || g_cgn_alldesc[1] != 1000000UL
		    || g_cgn_alldesc[2] != 65536UL) {
			fputs("FRONTEND_CODEGEN_META: descriptor order across block lists changed\n", stderr);
			return 1;
		}
	}
	program = meta_program();
	{
		ouro_v *block = OURO_F(OURO_F(meta_function(program), 6), 0);

		OURO_F(block, 1) = cgn_cat(OURO_F(block, 1), ouro_ctor(77, 0, 0));
		if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
			fputs("FRONTEND_CODEGEN_META: malformed tail after allocations accepted\n", stderr);
			return 1;
		}
	}
	program = meta_program();
	{
		ouro_v *function = meta_function(program);

		OURO_F(function, 6) = cgn_cat(OURO_F(function, 6), ouro_ctor(77, 0, 0));
		if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
			fputs("FRONTEND_CODEGEN_META: malformed block-list tail after allocations accepted\n", stderr);
			return 1;
		}
	}
	program = meta_program();
	OURO_F(program, 3) = ouro_ctor(77, 0, 0);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: malformed entry accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(meta_function(program), 3) =
		cgasm_list((ouro_v *[]){ouro_ctor(77, 0, 0)}, 1);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: malformed root local accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	{
		ouro_v *function = meta_function(program);
		ouro_v *root = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(7), cgn_unit(6)});
		OURO_F(function, 2) = cgasm_list(&root, 1);
		OURO_F(function, 3) = cgn_cat(cgasm_list(&root, 1), ouro_ctor(77, 0, 0));
		if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
			fputs("FRONTEND_CODEGEN_META: malformed tail after a managed local accepted\n", stderr);
			return 1;
		}
	}
	program = meta_program();
	OURO_F(OURO_F(OURO_F(program, 1), 0), 0) = ouro_nat(ULONG_MAX);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: overflowing data ID accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(program, 1) = cgn_cat(OURO_F(program, 1), ouro_ctor(77, 0, 0));
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: malformed tail after data rows accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	OURO_F(program, 1) = cgasm_list((ouro_v *[]){ouro_nat(65536)}, 1);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: scalar data row accepted\n", stderr);
		return 1;
	}
	program = meta_program();
	{
		ouro_v *object = OURO_F(OURO_F(program, 1), 0);
		OURO_F(program, 1) = cgasm_list((ouro_v *[]){
			ouro_ctor(77, 3, ouro_fields(object))}, 1);
	}
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: wrong-constructor data row accepted\n", stderr);
		return 1;
	}
	if (cgn_refresh_meta(meta_program()) != 0 || !g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: recovery after failure failed\n", stderr);
		return 1;
	}
	return 0;
}

static ouro_v *export_value(const char *name)
{
	int i;

	for (i = 0; i < ouro_export_count(); i++) {
		if (strcmp(name, ouro_export_name(i)) == 0)
			return ouro_export_value(i);
	}
	fprintf(stderr, "FRONTEND_CODEGEN_META: missing export %s\n", name);
	exit(2);
}

static int metadata_list_equal(ouro_v *list, unsigned long *ids, int count)
{
	ouro_v **items = 0;
	int n = 0;
	int i;
	int equal = 0;

	if (host_list_collect(list, &items, &n, 0) != 0 || n != count)
		goto done;
	for (i = 0; i < n; i++) {
		unsigned long id;

		if (x64enc_dec_nat(items[i], &id) != 0 || id != ids[i])
			goto done;
	}
	equal = 1;
done:
	free(items);
	return equal;
}

static int gc_result_matches(ouro_v *result, int tag, unsigned long first,
			     unsigned long second)
{
	ouro_v *payload;
	unsigned long id;

	if (result == 0 || result->n != 1 || result->tag != (tag < 0 ? 1 : 0))
		return 0;
	payload = OURO_F(result, 0);
	if (tag < 0)
		return payload != 0 && payload->tag == 0 && payload->n == 0;
	if (payload == 0 || payload->tag != tag || payload->n != (tag == 19 ? 2 : 1)
	    || x64enc_dec_nat(OURO_F(payload, 0), &id) != 0 || id != first)
		return 0;
	return tag != 19 || (x64enc_dec_nat(OURO_F(payload, 1), &id) == 0 && id == second);
}

static int gc_check_matches(ouro_v *program, ouro_v *bodies, ouro_v *raw,
			    int tag, unsigned long first, unsigned long second)
{
	return gc_result_matches(gchk_try(program, bodies), tag, first, second)
		&& (raw == 0 || gc_result_matches(ouro_apply(ouro_apply(raw, program), bodies),
			tag, first, second));
}

static int gc_check_order(int parity)
{
	ouro_v *program = meta_program();
	ouro_v *block = OURO_F(OURO_F(meta_function(program), 6), 0);
	ouro_v *allocation = meta_allocation(program);
	ouro_v *empty = cgn_unit(0);
	ouro_v *allocator = cgasm_list((ouro_v *[]){ouro_nat(2)}, 1);
	ouro_v *both = cgasm_list((ouro_v *[]){ouro_nat(2), ouro_nat(3)}, 2);
	ouro_v *target = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(3)});
	ouro_v *call = ouro_ctor(10, 4, (ouro_v *[]){empty, empty, target, empty});
	ouro_v *allocations = cgasm_list(&allocation, 1);
	ouro_v *calls = cgasm_list(&call, 1);
	ouro_v *raw = 0;

	if (parity) {
		(void)export_value("mir_gc_check");
		raw = g_raw_gc_check;
		if (raw == 0)
			return 1;
	}
	OURO_F(block, 1) = cgn_cat(calls, allocations);
	if (!gc_check_matches(program, both, raw, 19, 1UL, 3UL))
		return 1;
	OURO_F(block, 1) = cgn_cat(allocations, calls);
	if (!gc_check_matches(program, empty, raw, 20, 2UL, 0UL)
	    || !gc_check_matches(program, allocator, raw, 20, 3UL, 0UL)
	    || !gc_check_matches(program, both, raw, 19, 1UL, 3UL))
		return 1;
	OURO_F(block, 1) = cgn_cat(calls, cgn_unit(77));
	if (gchk_try(program, empty) != 0)
		return 1;
	OURO_F(call, 0) = cgn_unit(1);
	OURO_F(block, 1) = cgn_cat(allocations, calls);
	return !gc_check_matches(program, both, raw, -1, 0UL, 0UL);
}

static int gc_annotation_matches(ouro_v *program)
{
	ouro_v *blocks;
	ouro_v *first;
	ouro_v *second;

	if (program == 0 || program->tag != 0 || program->n != 4)
		return 0;
	blocks = OURO_F(meta_function(program), 6);
	first = OURO_F(OURO_F(OURO_F(blocks, 0), 1), 0);
	second = OURO_F(OURO_F(OURO_F(OURO_F(blocks, 1), 0), 1), 0);
	return first->tag == 10 && OURO_F(first, 0)->tag == 0
		&& second->tag == 10 && OURO_F(second, 0)->tag == 1;
}

static int gc_annotation_retry(int parity)
{
	ouro_v *program = meta_program();
	ouro_v *function = meta_function(program);
	ouro_v *first = OURO_F(OURO_F(function, 6), 0);
	ouro_v *empty = cgn_unit(0);
	ouro_v *known = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(2)});
	ouro_v *unknown = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(3)});
	ouro_v *call = ouro_ctor(10, 4, (ouro_v *[]){cgn_unit(1), empty, known, empty});
	ouro_v *later = ouro_ctor(10, 4, (ouro_v *[]){empty, empty, cgn_unit(77), empty});
	ouro_v *second = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(7), cgasm_list(&later, 1),
		OURO_F(first, 2)});
	ouro_v *bodies = cgasm_list((ouro_v *[]){ouro_nat(2)}, 1);

	OURO_F(first, 1) = cgasm_list(&call, 1);
	OURO_F(function, 6) = cgasm_list((ouro_v *[]){first, second}, 2);
	if (gcan_try(program, bodies) != 0 || OURO_F(call, 0)->tag != 1)
		return 1;
	OURO_F(later, 2) = unknown;
	if (!gc_annotation_matches(gcan_try(program, bodies))
	    || OURO_F(call, 0)->tag != 1 || OURO_F(later, 0)->tag != 0)
		return 1;
	if (!parity)
		return 0;
	(void)export_value("mir_gc_annotate");
	return g_raw_gc_annotate == 0
		|| !gc_annotation_matches(ouro_apply(ouro_apply(g_raw_gc_annotate, program), bodies));
}

static int gc_infer_matches(ouro_v *raw, ouro_v *program, unsigned long fuel,
			    unsigned long *expected, int count)
{
	ouro_v *result = raw == 0 ? gcinf_try(ouro_nat(fuel), program)
		: ouro_apply(ouro_apply(raw, ouro_nat(fuel)), program);
	ouro_v *payload;

	if (result == 0 || result->n != 1)
		return 0;
	payload = OURO_F(result, 0);
	if (expected == 0)
		return result->tag == 0 && payload != 0 && payload->tag == 0 && payload->n == 0;
	return result->tag == 1 && metadata_list_equal(payload, expected, count);
}

static int gc_infer_rounds(int parity)
{
	ouro_v *program = meta_program();
	ouro_v *example = meta_function(program);
	ouro_v *empty = cgn_unit(0);
	unsigned long ids[] = {17UL, 2UL, 65535UL, 31UL, 4UL};
	unsigned long targets[] = {2UL, 99UL, 31UL, 65535UL, 100UL};
	unsigned long expected[] = {65535UL, 31UL, 4UL};
	ouro_v *functions[5];
	ouro_v *maygc = ouro_ctor(0, 4, (ouro_v *[]){cgn_unit(1), ouro_nat(99), empty, empty});
	ouro_v *nogc = ouro_ctor(0, 4, (ouro_v *[]){empty, ouro_nat(100), empty, empty});
	ouro_v *externs = cgn_cat(cgasm_list(&maygc, 1), cgasm_list(&nogc, 1));
	ouro_v *library = ouro_ctor(0, 2, (ouro_v *[]){empty, externs});
	int i;

	for (i = 0; i < 5; i++) {
		ouro_v *target = ouro_ctor(0, 1, (ouro_v *[]){ouro_nat(targets[i])});
		ouro_v *call = ouro_ctor(10, 4, (ouro_v *[]){empty, empty, target, empty});
		ouro_v *block = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(0), cgasm_list(&call, 1), cgn_unit(3)});

		functions[i] = ouro_ctor(0, 7, ouro_fields(example));
		OURO_F(functions[i], 0) = ouro_nat(ids[i]);
		OURO_F(functions[i], 6) = cgasm_list(&block, 1);
	}
	OURO_F(program, 0) = cgasm_list(functions, 5);
	OURO_F(program, 2) = cgasm_list(&library, 1);
	if (!gc_infer_matches(0, program, 2, 0, 0)
	    || !gc_infer_matches(0, program, 3, expected, 3))
		return 1;
	if (parity) {
		(void)export_value("mir_gc_infer");
		if (g_raw_gc_infer == 0 || !gc_infer_matches(g_raw_gc_infer, program, 2, 0, 0)
		    || !gc_infer_matches(g_raw_gc_infer, program, 3, expected, 3))
			return 1;
	}
	OURO_F(functions[2], 0) = ouro_nat(65536UL);
	return gcinf_try(ouro_nat(3), program) != 0;
}

static int metadata_compare(ouro_v *program)
{
	ouro_v *result;
	unsigned long budget;

	result = ouro_apply(export_value("mir_managed_descriptors"), program);
	if (!metadata_list_equal(result, g_cgn_alldesc, g_cgn_nobj))
		return 1;
	result = ouro_apply(export_value("codegen_runtime_descriptors"), program);
	if (!metadata_list_equal(result, g_cgn_alldesc, g_cgn_nall))
		return 1;
	result = ouro_apply(export_value("codegen_runtime_budget_offset"), program);
	if (x64enc_dec_nat(result, &budget) != 0 || budget != g_cgn_budget_off)
		return 1;
	return 0;
}

static int descriptor_kinds_equal(const unsigned long *expected, int expected_count)
{
	ouro_v **atoms = 0;
	int count = 0;
	int i;
	int equal = 0;

	if (g_cgn_nall != expected_count
	    || host_list_collect(cgb_runtime_init(1), &atoms, &count, 0) != 0
	    || count != 4 + 4 * expected_count)
		goto done;
	for (i = 0; i < expected_count; i++) {
		ouro_v *atom = atoms[6 + 4 * i];
		ouro_v *ins;
		unsigned long word[4];

		if (atom == 0 || atom->tag != 0 || atom->n != 1)
			goto done;
		ins = OURO_F(atom, 0);
		if (ins == 0 || ins->tag != 0 || ins->n != 2
		    || x64enc_dec_word32(OURO_F(ins, 1), word) != 0
		    || word[0] != expected[i] || word[1] != 0 || word[2] != 0 || word[3] != 0)
			goto done;
	}
	equal = 1;
done:
	free(atoms);
	return equal;
}

static int descriptor_kind_check(void)
{
	ouro_v *program = meta_program();
	ouro_v *function = meta_function(program);
	ouro_v *second;

	OURO_F(function, 3) = cgasm_list((ouro_v *[]){
		ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(0), cgn_unit(6)})}, 1);
	if (cgn_refresh_meta(program) != 0
	    || !descriptor_kinds_equal((unsigned long []){1, 1, 1, 2}, 4))
		return 1;

	OURO_F(meta_allocation(program), 3) = ouro_nat(1000004UL);
	second = ouro_ctor(0, 7, ouro_fields(function));
	OURO_F(second, 0) = ouro_nat(2);
	program = ouro_ctor(0, 4, ouro_fields(program));
	OURO_F(program, 0) = cgasm_list((ouro_v *[]){function, second}, 2);
	return cgn_refresh_meta(program) != 0
		|| !descriptor_kinds_equal((unsigned long []){1, 1, 1, 1, 2, 1}, 6);
}

static int metadata_parity_check(void)
{
	ouro_v *program = meta_program();
	ouro_v *root[2] = {ouro_nat(0), ouro_ctor(6, 0, 0)};
	ouro_v *function;
	ouro_v *functions[3];
	ouro_v *fields[7];
	int i;

	OURO_F(meta_function(program), 3) =
		cgasm_list((ouro_v *[]){ouro_ctor(0, 2, root)}, 1);
	if (cgn_refresh_meta(program) != 0 || g_cgn_nall != 4
	    || g_cgn_alldesc[3] != 1000003UL || g_cgn_budget_off != 104UL
	    || metadata_compare(program) != 0)
		return 1;
	function = meta_function(program);
	functions[0] = function;
	for (i = 0; i < 7; i++)
		fields[i] = OURO_F(function, i);
	fields[0] = ouro_nat(3);
	functions[2] = ouro_ctor(0, 7, fields);
	fields[0] = ouro_nat(2);
	fields[3] = ouro_ctor(0, 0, 0);
	functions[1] = ouro_ctor(0, 7, fields);
	/* A new program identity forces metadata refresh after changing the list. */
	for (i = 0; i < 4; i++)
		fields[i] = OURO_F(program, i);
	fields[0] = cgasm_list(functions, 3);
	program = ouro_ctor(0, 4, fields);
	if (cgn_refresh_meta(program) != 0 || g_cgn_nobj != 3 || g_cgn_nall != 5
	    || g_cgn_alldesc[3] != 1000003UL || g_cgn_alldesc[4] != 1000005UL
	    || g_cgn_budget_off != 120UL || metadata_compare(program) != 0)
		return 1;
	return 0;
}

static int function_index_check(void)
{
	ouro_v *program = meta_program();
	ouro_v *function = meta_function(program);
	ouro_v *functions[4];
	ouro_v *fields[7];
	ouro_v *pinned;
	unsigned long ids[] = {65536UL, 17UL, 65536UL, 1000001UL};
	unsigned long ordinal = 99UL;
	int position;
	int i;

	for (i = 0; i < 7; i++)
		fields[i] = OURO_F(function, i);
	for (i = 0; i < 4; i++) {
		fields[0] = ouro_nat(ids[i]);
		functions[i] = ouro_ctor(0, 7, fields);
	}
	OURO_F(program, 0) = cgasm_list(functions, 4);
	(void)ps_program(0, program);
	pinned = g_perm_cg_program;
	if (cgn_refresh_meta(pinned) != 0
	    || !cgn_find_pinned_function(pinned, 65536UL, &position) || position != 0
	    || !cgn_find_pinned_function(pinned, 1000002UL, &position) || position != -1
	    || cgb_fn_index(pinned, 1000001UL, &ordinal) != 0 || ordinal != 3UL
	    || cgn_has_function(pinned, 17UL) != 1 || cgn_has_function(pinned, 1UL) != 0)
		return 1;

	(void)ps_program(0, meta_program());
	if (cgn_find_pinned_function(pinned, 65536UL, &position)
	    || cgb_fn_index(pinned, 65536UL, &ordinal) != 0 || ordinal != 0UL)
		return 1;
	pinned = g_perm_cg_program;
	if (cgn_refresh_meta(pinned) != 0
	    || !cgn_find_pinned_function(pinned, 1UL, &position) || position != 0
	    || cgn_has_function(pinned, 65536UL) != 0)
		return 1;
	ouro_fe_reset_mir_pins();
	return cgn_find_pinned_function(pinned, 1UL, &position)
		|| cgn_has_function(pinned, 1UL) != 1;
}

static int metadata_reset_check(void)
{
	ouro_v *program = meta_program();
	ouro_v *fields[4];
	ouro_v *entry = ouro_nat(17);
	unsigned long saved_n;
	unsigned long saved_used;
	uintptr_t old_address;
	int i;
	int result = 1;

	for (i = 0; i < 4; i++)
		fields[i] = OURO_F(program, i);
	ouro_heap_mark_save(&saved_n, &saved_used);
	ouro_heap_mark();
	program = ouro_ctor(0, 4, fields);
	old_address = (uintptr_t)program;
	if (cgn_refresh_meta(program) != 0 || g_cgn_entry != 1UL)
		goto done;
	ouro_fe_reset_mir_pins();
	ouro_heap_reset();
	fields[3] = entry;
	program = ouro_ctor(0, 4, fields);
	if ((uintptr_t)program != old_address)
		goto done;
	if (cgn_refresh_meta(program) != 0 || g_cgn_entry != 17UL)
		goto done;
	result = 0;
done:
	ouro_fe_reset_mir_pins();
	ouro_heap_reset();
	ouro_heap_mark_restore(saved_n, saved_used);
	return result;
}

static ouro_v *meta_extern_library(unsigned long first, int count)
{
	ouro_v *empty = ouro_ctor(0, 0, 0);
	ouro_v *externs = empty;
	int i;
	for (i = 0; i < count; i++) {
		ouro_v *entry = ouro_ctor(0, 4, (ouro_v *[]){empty,
			ouro_nat(first + (unsigned long)i), empty, empty});
		externs = ouro_ctor(1, 2, (ouro_v *[]){entry, externs});
	}
	return ouro_ctor(0, 2, (ouro_v *[]){empty, externs});
}

static int meta_address_kind(ouro_v *program, unsigned long id)
{
	ouro_v *slot = ouro_ctor(0, 3, (ouro_v *[]){ouro_nat(9), cgn_unit(4), ouro_nat(0)});
	cgn_frame_slots slots = { .source = cgasm_list(&slot, 1) };
	ouro_v *instruction = ouro_ctor(8, 2, (ouro_v *[]){ouro_nat(9), ouro_nat(id)});
	ouro_v *result = cgi_try(program, &slots, ouro_nat(0), ouro_nat(0), instruction, 0);
	ouro_v **atoms = 0;
	int count = 0;
	int kind = -1;

	if (result != 0 && result->tag == 1 && result->n == 1 &&
	    host_list_collect(OURO_F(result, 0), &atoms, &count, 0) == 0 && count > 0 &&
	    atoms[0] != 0 && atoms[0]->tag == 6 && atoms[0]->n == 2 &&
	    OURO_F(atoms[0], 1) != 0 && as_nat(OURO_F(atoms[0], 0)) == id)
		kind = OURO_F(atoms[0], 1)->tag;
	free(atoms);
	free(slots.entries);
	return kind;
}

static int extern_index_check(void)
{
	ouro_v *program = meta_program();
	ouro_v *left = meta_extern_library(2000000UL, 64);
	ouro_v *right = meta_extern_library(2000050UL, 40);
	ouro_v *pinned;
	ouro_v *invalid;

	OURO_F(program, 2) = cgn_cat(cgasm_list(&left, 1), cgasm_list(&right, 1));
	if (meta_address_kind(program, 2000050UL) != 0 || meta_address_kind(program, 65535UL) != 1)
		return 1;
	(void)ps_program(0, program);
	pinned = g_perm_cg_program;
	if (cgn_refresh_meta(pinned) != 0 || g_cgn_runtime_id != 2000091UL ||
	    !g_cgn_externs.available || g_cgn_externs.count != 104 ||
	    cgn_has_extern(pinned, 2000000UL) != 1 || cgn_has_extern(pinned, 2000089UL) != 1 ||
	    meta_address_kind(pinned, 2000050UL) != 0 || meta_address_kind(pinned, 65535UL) != 1)
		return 1;

	invalid = meta_program();
	right = meta_extern_library(3000000UL, 1);
	OURO_F(right, 1) = cgn_cat(OURO_F(right, 1), ouro_ctor(77, 0, 0));
	OURO_F(invalid, 2) = cgasm_list((ouro_v *[]){left, right}, 2);
	(void)ps_program(0, invalid);
	if (g_cgn_externs.available || cgn_has_extern(pinned, 2000089UL) != 1 ||
	    cgn_refresh_meta(g_perm_cg_program) == 0 || g_cgn_meta_ok || g_cgn_externs.available ||
	    g_cgn_function_index_ready || g_cgn_function_positions != 0 ||
	    cgn_has_extern(g_perm_cg_program, 2000000UL) != 1 ||
	    cgn_has_extern(g_perm_cg_program, 3000000UL) != -1)
		return 1;

	(void)ps_program(0, program);
	pinned = g_perm_cg_program;
	if (cgn_refresh_meta(pinned) != 0 || !g_cgn_externs.available)
		return 1;
	ouro_fe_reset_mir_pins();
	return g_cgn_externs.available || g_cgn_externs.ids != 0 ||
		cgn_has_extern(pinned, 2000089UL) != 1;
}

int main(int argc, char **argv)
{
	int parity = argc == 2 && strcmp(argv[1], "metadata-parity") == 0;

	if (argc != 2 || (!parity && strcmp(argv[1], "metadata") != 0))
		return 2;
	if (preparation_context_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: preparation context failed\n", stderr);
		return 1;
	}
	if (metadata_check() != 0)
		return 1;
	if (descriptor_kind_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: emitted descriptor kinds failed\n", stderr);
		return 1;
	}
	if (metadata_reset_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: reused program address kept stale metadata\n", stderr);
		return 1;
	}
	if (gc_check_order(parity) != 0) {
		fputs("FRONTEND_CODEGEN_META: GC check diagnostic order failed\n", stderr);
		return 1;
	}
	if (gc_annotation_retry(parity) != 0) {
		fputs("FRONTEND_CODEGEN_META: GC annotation retry failed\n", stderr);
		return 1;
	}
	if (gc_infer_rounds(parity) != 0) {
		fputs("FRONTEND_CODEGEN_META: GC inference rounds failed\n", stderr);
		return 1;
	}
	if (function_index_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: function index failed\n", stderr);
		return 1;
	}
	if (extern_index_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: extern index failed\n", stderr);
		return 1;
	}
	if (parity && metadata_parity_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: pure/host parity failed\n", stderr);
		return 1;
	}
	free(g_cgn_alldesc);
	printf("FRONTEND_CODEGEN_META: passed %s\n", argv[1]);
	return 0;
}
