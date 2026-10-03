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
	    || g_cgn_objects[0] != 65535UL
	    || g_cgn_objects[1] != 1000000UL
	    || g_cgn_objects[2] != 65536UL) {
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
	    || g_cgn_objects[0] != ULONG_MAX || g_cgn_budget_off != 104UL) {
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
	OURO_F(OURO_F(OURO_F(program, 1), 0), 0) = ouro_nat(ULONG_MAX);
	if (cgn_refresh_meta(program) == 0 || g_cgn_meta_ok) {
		fputs("FRONTEND_CODEGEN_META: overflowing data ID accepted\n", stderr);
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
	int cap = 0;
	int i;
	int equal = 0;

	if (host_list_collect(list, &items, &n, &cap) != 0 || n != count)
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

static int metadata_compare(ouro_v *program)
{
	ouro_v *result;
	unsigned long budget;

	result = ouro_apply(export_value("mir_managed_descriptors"), program);
	if (!metadata_list_equal(result, g_cgn_objects, g_cgn_nobj))
		return 1;
	result = ouro_apply(export_value("codegen_runtime_descriptors"), program);
	if (!metadata_list_equal(result, g_cgn_alldesc, g_cgn_nall))
		return 1;
	result = ouro_apply(export_value("codegen_runtime_budget_offset"), program);
	if (x64enc_dec_nat(result, &budget) != 0 || budget != g_cgn_budget_off)
		return 1;
	return 0;
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
	if (parity && metadata_parity_check() != 0) {
		fputs("FRONTEND_CODEGEN_META: pure/host parity failed\n", stderr);
		return 1;
	}
	free(g_cgn_objects);
	free(g_cgn_alldesc);
	printf("FRONTEND_CODEGEN_META: passed %s\n", argv[1]);
	return 0;
}
