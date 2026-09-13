/* Exercise the N1 producer's actual emission boundary with typed MIR faults.
   Link with the same generated Ouro backend and runtime as n1_host_main.c. */
#define main n1_producer_main
#include "n1_host_main.c"
#undef main
#include <stdint.h>

static ouro_v *codes(const char *s)
{
	return ouro_string_codes(s);
}

static ouro_v *probe_mir(int uninitialized, int bad_return)
{
	ouro_v *word = ouro_ctor(1, 0, 0); /* MirU32 */
	ouro_v *local_fields[2];
	ouro_v *locals;
	ouro_v *use;
	ouro_v *instructions;
	ouro_v *block_fields[3];
	ouro_v *function_fields[7];
	ouro_v *program_fields[4];
	ouro_v *id = ouro_nat(21);
	local_fields[0] = id;
	local_fields[1] = word;
	locals = cons(ouro_ctor(0, 2, local_fields), nil());
	local_fields[0] = ouro_nat(20);
	locals = cons(ouro_ctor(0, 2, local_fields), locals);
	use = ouro_ctor(0, 1, &id); /* MirUse 21 */
	local_fields[1] = use;
	instructions = uninitialized ? cons(ouro_ctor(0, 2, local_fields), nil()) : nil();
	block_fields[0] = ouro_nat(0);
	block_fields[1] = instructions;
	use = nil();
	block_fields[2] = bad_return ? ouro_ctor(2, 1, &use) : ouro_ctor(3, 0, 0);
	function_fields[0] = ouro_nat(1);
	function_fields[1] = codes("probe");
	function_fields[2] = nil();
	function_fields[3] = locals;
	function_fields[4] = bad_return ? ouro_ctor(1, 1, &word) : nil();
	function_fields[5] = ouro_nat(0);
	function_fields[6] = cons(ouro_ctor(0, 3, block_fields), nil());
	program_fields[0] = cons(ouro_ctor(0, 7, function_fields), nil());
	program_fields[1] = nil();
	program_fields[2] = nil();
	program_fields[3] = ouro_nat(1);
	return ouro_ctor(0, 4, program_fields);
}

static int expect_check(ouro_v *result, int error_tag, const char *label)
{
	int ok = result != 0 && result->n == 1;
	if (error_tag < 0)
		ok = ok && result->tag == 1;
	else
		ok = ok && result->tag == 0 && OURO_F(result, 0) != 0 &&
			OURO_F(result, 0)->tag == error_tag;
	if (!ok)
		fprintf(stderr, "N1_HOST_CONTEXT: %s expected %s (error %d)\n",
			label, error_tag < 0 ? "acceptance" : "rejection", error_tag);
	return ok;
}

static ouro_v *external_program(ouro_v *function, int return_type)
{
	ouro_v *word = ouro_ctor(return_type, 0, 0);
	ouro_v *result = ouro_ctor(1, 1, &word);
	ouro_v *signature = pair(nil(), result); /* MirSignatureOf */
	ouro_v *fields[4] = {nil(), ouro_nat(7), codes("external"), signature};
	ouro_v *library = pair(codes("probe.dll"), cons(ouro_ctor(0, 4, fields), nil()));
	fields[0] = cons(function, nil());
	fields[1] = nil();
	fields[2] = cons(library, nil());
	fields[3] = ouro_nat(1);
	return ouro_ctor(0, 4, fields);
}

static int check_program_context(void)
{
	ouro_v *base = probe_mir(0, 0);
	ouro_v *function = OURO_F(OURO_F(base, 0), 0);
	ouro_v *block = OURO_F(OURO_F(function, 6), 0);
	ouro_v *local = ouro_nat(20);
	ouro_v *symbol = ouro_nat(7);
	ouro_v *call_fields[4] = {nil(), ouro_ctor(1, 1, &local),
		ouro_ctor(0, 1, &symbol), nil()};
	ouro_v *valid;
	ouro_v *invalid;
	ouro_v *original;
	ouro_v *check = find_export("mir_check_function");
	ouro_v *flow = ouro_nat(16);
	OURO_F(block, 1) = cons(ouro_ctor(10, 4, call_fields), nil());
	valid = external_program(function, 1); /* external returns MirU32 */
	invalid = external_program(function, 2); /* MirU64 cannot fill local 20 */
	original = ouro_apply(ouro_apply(check, valid), flow);
	if (!expect_check(ouro_apply(original, function),
		-1, "initial external signature"))
		return 1;
	if (!expect_check(ouro_apply(ouro_apply(ouro_apply(check, invalid), flow), function),
		8, "changed external signature"))
		return 1;
	if (!expect_check(ouro_apply(original, function), -1, "retained external signature"))
		return 1;
	return !expect_check(ouro_apply(ouro_apply(ouro_apply(check, valid), flow), function),
		-1, "restored external signature");
}

static int check_flow_context(void)
{
	ouro_v *program = probe_mir(0, 0);
	ouro_v *function = OURO_F(OURO_F(program, 0), 0);
	ouro_v *check = ouro_apply(find_export("mir_check_function"), program);
	ouro_v *enough = ouro_nat(16);
	ouro_v *empty = ouro_nat(0);
	ouro_v *original = ouro_apply(check, enough);
	if (!expect_check(ouro_apply(original, function),
		-1, "initial flow budget"))
		return 1;
	if (!expect_check(ouro_apply(ouro_apply(check, empty), function),
		0, "exhausted flow budget"))
		return 1;
	if (!expect_check(ouro_apply(original, function), -1, "retained flow budget"))
		return 1;
	return !expect_check(ouro_apply(ouro_apply(check, enough), function),
		-1, "restored flow budget");
}

static ouro_v *phase_error_program(int phase)
{
	ouro_v *program = probe_mir(phase == 2, 0);
	ouro_v *function = OURO_F(OURO_F(program, 0), 0);
	ouro_v *block = OURO_F(OURO_F(function, 6), 0);
	ouro_v *fields[3];
	if (phase == 0) {
		fields[0] = ouro_nat(99);
		fields[1] = ouro_ctor(0, 1, fields); /* MirUse 99 */
		fields[0] = ouro_nat(20);
		OURO_F(block, 1) = cons(ouro_ctor(0, 2, fields), nil());
	} else if (phase == 1) {
		fields[0] = ouro_nat(31);
		fields[1] = nil();
		fields[2] = ouro_ctor(3, 0, 0); /* unreachable MirTrap */
		OURO_F(function, 6) = cons(block, cons(ouro_ctor(0, 3, fields), nil()));
	}
	return program;
}

static int check_phase_results(ouro_v *results)
{
	const int tags[3] = {4, 18, 7};
	const unsigned long first[3] = {99, 31, 0};
	int i;
	if (results == 0 || results->tag != 0 || results->n != 3)
		return 1;
	for (i = 0; i < 3; i++) {
		ouro_v *result = OURO_F(results, i);
		ouro_v *error;
		if (result == 0 || result->tag != 0 || result->n != 1)
			return 1;
		error = OURO_F(result, 0);
		if (error == 0 || error->tag != tags[i] || error->n != (i == 2 ? 2 : 1) ||
		    as_nat(OURO_F(error, 0)) != first[i] ||
		    (i == 2 && as_nat(OURO_F(error, 1)) != 21))
			return 1;
	}
	return 0;
}

static int check_mir_phase_errors(int nested)
{
	ouro_v *caller = codes("MIR phase caller survives");
	ouro_heap_context *context = nested ? ouro_heap_context_enter() : 0;
	ouro_v *check = find_export("mir_check_function");
	ouro_v *retained[3];
	ouro_v *results;
	ouro_v *program;
	ouro_v *function;
	char text[64];
	int i;
	for (i = 0; i < 3; i++) {
		program = phase_error_program(i);
		function = OURO_F(OURO_F(program, 0), 0);
		retained[i] = ouro_apply(ouro_apply(ouro_apply(check, program), ouro_nat(64)), function);
	}
	results = ouro_clone_perm(ouro_ctor(0, 3, retained));
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0xA5, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	if (context != 0) {
		ouro_fe_reset_mir_pins();
		results = ouro_heap_context_leave(context, results);
	}
	if (check_phase_results(results) || codes_to_buf(caller, text, sizeof(text)) != 25 ||
	    memcmp(text, "MIR phase caller survives", 25) != 0)
		return 1;
	program = probe_mir(0, 0);
	function = OURO_F(OURO_F(program, 0), 0);
	return !expect_check(ouro_apply(ouro_apply(ouro_apply(check, program), ouro_nat(64)), function),
		-1, "valid function after retained phase errors");
}

static ouro_v *reach_probe_block(unsigned long id, unsigned long next, int trap)
{
	ouro_v *target = ouro_nat(next);
	ouro_v *fields[3] = {ouro_nat(id), nil(),
		trap ? ouro_ctor(3, 0, 0) : ouro_ctor(0, 1, &target)};
	return ouro_ctor(0, 3, fields);
}

static ouro_v *reach_probe_chain(unsigned long count, int reversed, ouro_v *tail)
{
	unsigned long offset;
	for (offset = 0; offset < count; offset++) {
		unsigned long id = reversed ? offset : count - offset - 1;
		tail = cons(reach_probe_block(id, id + 1, id + 1 == count), tail);
	}
	return tail;
}

static ouro_v *reach_probe_identity(ouro_env *env, ouro_v *work)
{
	(void)env;
	return ouro_apply(work, ouro_ctor(0, 0, 0));
}

static ouro_v *reach_probe_apply(ouro_v *check, unsigned long fuel, ouro_v *blocks)
{
	return ouro_apply(ouro_apply(ouro_apply(check, ouro_nat(fuel)), ouro_nat(0)), blocks);
}

static int reach_probe_result(ouro_v *result, int tag, unsigned long id)
{
	ouro_v *payload;
	if (result == 0 || result->n != 1 || result->tag != (tag < 0 ? 1 : 0))
		return 0;
	payload = OURO_F(result, 0);
	if (payload == 0 || payload->tag != (tag < 0 ? 0 : tag) ||
	    payload->n != (tag == 18 ? 1 : 0))
		return 0;
	return tag != 18 || as_nat(OURO_F(payload, 0)) == id;
}

static int check_mir_reachability_rounds(void)
{
	ouro_v *caller = codes("reachability caller survives");
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *check = find_export("mir_reachable");
	ouro_v *identity = ouro_apply(find_export("mir_reachable_with"),
		ouro_clos(reach_probe_identity, 0));
	ouro_v *blocks;
	ouro_v *retained[3];
	ouro_v *results;
	char text[64];
	unsigned long fuel;
	int reversed;
	int ok = 1;
	for (reversed = 0; reversed < 2; reversed++) {
		blocks = reach_probe_chain(8, reversed, nil());
		for (fuel = 0; fuel <= 9; fuel++) {
			int expected = fuel < 8 ? 0 : -1;
			ok = reach_probe_result(reach_probe_apply(check, fuel, blocks), expected, 0) && ok;
			ok = reach_probe_result(reach_probe_apply(identity, fuel, blocks), expected, 0) && ok;
		}
	}
	/* The public helper still permits a successor absent from the block list. */
	blocks = cons(reach_probe_block(0, 99, 0), nil());
	ok = reach_probe_result(reach_probe_apply(check, 1, blocks), 0, 0) && ok;
	ok = reach_probe_result(reach_probe_apply(check, 2, blocks), -1, 0) && ok;
	/* These error IDs exceed the static Nat cache. They must survive round
	   cleanup and be copied with the errors across the enclosing context. */
	blocks = reach_probe_chain(8, 0, cons(reach_probe_block(5009, 0, 1),
		cons(reach_probe_block(5010, 0, 1), nil())));
	ok = reach_probe_result(reach_probe_apply(check, 7, blocks), 0, 0) && ok;
	retained[0] = reach_probe_apply(check, 8, blocks);
	blocks = reach_probe_chain(8, 1, cons(reach_probe_block(5010, 0, 1),
		cons(reach_probe_block(5009, 0, 1), nil())));
	retained[1] = reach_probe_apply(check, 8, blocks);
	/* A long path requires 256 growth/convergence rounds. This retains the
	   exact frontier construction instead of testing a different graph walk. */
	blocks = reach_probe_chain(256, 0, nil());
	retained[2] = reach_probe_apply(check, 256, blocks);
	results = ouro_heap_context_leave(context, ouro_ctor(0, 3, retained));
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0xA5, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	ok = reach_probe_result(OURO_F(results, 0), 18, 5009) && ok;
	ok = reach_probe_result(OURO_F(results, 1), 18, 5010) && ok;
	ok = reach_probe_result(OURO_F(results, 2), -1, 0) && ok;
	ok = codes_to_buf(caller, text, sizeof(text)) == 28 &&
		memcmp(text, "reachability caller survives", 28) == 0 && ok;
	if (!ok)
		fputs("N1_HOST_CONTEXT: reachability fuel, payload or capture changed\n", stderr);
	return !ok;
}

static ouro_v *flow_probe_program(int reversed, int initialized)
{
	ouro_v *program = probe_mir(0, 0);
	ouro_v *function = OURO_F(OURO_F(program, 0), 0);
	ouro_v *blocks = nil();
	unsigned long offset;
	if (initialized) {
		ouro_v *locals = OURO_F(function, 3);
		OURO_F(function, 2) = OURO_F(locals, 1); /* argument 21 */
		OURO_F(function, 3) = cons(OURO_F(locals, 0), nil());
	}
	for (offset = 0; offset < 8; offset++) {
		unsigned long index = reversed ? offset : 7 - offset;
		ouro_v *block = reach_probe_block(5000 + index, 5001 + index, index == 7);
		if (index == 7) {
			ouro_v *id = ouro_nat(21);
			ouro_v *fields[2] = {ouro_nat(20), ouro_ctor(0, 1, &id)};
			OURO_F(block, 1) = cons(ouro_ctor(0, 2, fields), nil());
		}
		blocks = cons(block, blocks);
	}
	OURO_F(function, 5) = ouro_nat(5000);
	OURO_F(function, 6) = blocks;
	return program;
}

static int flow_probe_same(ouro_v *actual, ouro_v *expected)
{
	ouro_v *left;
	ouro_v *right;
	int i;
	if (actual == 0 || expected == 0 || actual->tag != expected->tag ||
	    actual->n != 1 || expected->n != 1)
		return 0;
	left = OURO_F(actual, 0);
	right = OURO_F(expected, 0);
	if (left == 0 || right == 0 || left->tag != right->tag || left->n != right->n)
		return 0;
	for (i = 0; i < left->n; i++)
		if (as_nat(OURO_F(left, i)) != as_nat(OURO_F(right, i)))
			return 0;
	return 1;
}

static int check_mir_flow_rounds(void)
{
	const unsigned long fuels[4] = {0, 7, 8, 9};
	ouro_v *caller = codes("flow caller survives");
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *check = find_export("mir_check_function");
	ouro_v *identity = ouro_apply(ouro_apply(find_export("mir_check_function_with"),
		ouro_clos(reach_probe_identity, 0)), find_export("mir_check_declared_flow"));
	ouro_v *retained[3] = {0, 0, 0};
	ouro_v *results;
	char text[32];
	int reversed, initialized, budget;
	int ok = 1;
	for (reversed = 0; reversed < 2; reversed++) {
		for (initialized = 0; initialized < 2; initialized++) {
			ouro_v *program = flow_probe_program(reversed, initialized);
			ouro_v *function = OURO_F(OURO_F(program, 0), 0);
			for (budget = 0; budget < 4; budget++) {
				ouro_v *fuel = ouro_nat(fuels[budget]);
				ouro_v *expected = ouro_apply(ouro_apply(ouro_apply(identity, program), fuel), function);
				ouro_v *actual = ouro_apply(ouro_apply(ouro_apply(check, program), fuel), function);
				ok = flow_probe_same(actual, expected) && ok;
				if (budget == 3) {
					ok = expect_check(actual, initialized ? -1 : 7, "flow round convergence") && ok;
					retained[initialized ? 2 : reversed] = actual;
				}
			}
		}
	}
	ouro_fe_reset_mir_pins();
	results = ouro_heap_context_leave(context, ouro_ctor(0, 3, retained));
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0xA5, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	for (reversed = 0; reversed < 2; reversed++) {
		ouro_v *result = OURO_F(results, reversed);
		ok = expect_check(result, 7, "retained flow error") && ok;
		if (result != 0 && result->tag == 0 && result->n == 1) {
			ouro_v *error = OURO_F(result, 0);
			ok = error != 0 && error->n == 2 && as_nat(OURO_F(error, 0)) == 5007 &&
				as_nat(OURO_F(error, 1)) == 21 && ok;
		}
	}
	ok = expect_check(OURO_F(results, 2), -1, "retained flow success") && ok;
	ok = codes_to_buf(caller, text, sizeof(text)) == 20 && memcmp(text, "flow caller survives", 20) == 0 && ok;
	return !ok;
}

static ouro_v *data_program(unsigned long entry, const char *bytes)
{
	ouro_v *fields[4] = {ouro_nat(30), ouro_ctor(1, 0, 0), codes(bytes), 0};
	ouro_v *data = ouro_ctor(0, 3, fields);
	fields[0] = nil();
	fields[1] = cons(data, nil());
	fields[2] = nil();
	fields[3] = ouro_nat(entry);
	return ouro_ctor(0, 4, fields);
}

static int expect_prepared(ouro_v *result, unsigned long entry, char byte)
{
	ouro_v *state;
	ouro_v *prepared;
	ouro_v *pe;
	char bytes[16];
	int i;
	if (!expect_check(result, -1, "codegen preparation"))
		return 0;
	state = OURO_F(result, 0);
	if (state == 0 || state->tag != 1 || state->n != 1)
		return 0;
	prepared = OURO_F(state, 0);
	if (prepared == 0 || prepared->tag != 0 || prepared->n != 2)
		return 0;
	pe = OURO_F(prepared, 0);
	if (pe == 0 || pe->tag != 0 || pe->n != 8 || as_nat(OURO_F(pe, 7)) != entry ||
		codes_to_buf(OURO_F(pe, 1), bytes, sizeof(bytes)) != 8 || bytes[0] != byte) {
		fprintf(stderr, "N1_HOST_CONTEXT: codegen expected entry %lu and data %c\n", entry, byte);
		return 0;
	}
	for (i = 1; i < 8; i++)
		if (bytes[i] != 0)
			return 0;
	return 1;
}

static int check_codegen_context(void)
{
	ouro_v *first = data_program(11, "A");
	ouro_v *second = data_program(12, "B");
	ouro_v *step = find_export("codegen_prepare_step");
	ouro_v *original = ouro_apply(step, first);
	ouro_v *begin = ouro_apply(find_export("codegen_prepare_begin"), first);
	ouro_v *state;
	if (!expect_check(begin, -1, "codegen begin"))
		return 1;
	state = OURO_F(begin, 0);
	if (!expect_prepared(ouro_apply(original, state), 11, 'A'))
		return 1;
	if (!expect_prepared(ouro_apply(ouro_apply(step, second), state), 12, 'B'))
		return 1;
	if (!expect_prepared(ouro_apply(original, state), 11, 'A'))
		return 1;
	return !expect_prepared(ouro_apply(ouro_apply(step, first), state), 11, 'A');
}


/* These marker values exercise host allocation/protocol ownership only.
   They are never presented to the MIR checker or used as acceptance evidence. */
static unsigned long raw_probe_calls;
static unsigned long long raw_probe_base;
static int raw_probe_failed;
static int raw_probe_mode;

static int lower_probe_fail(const char *message)
{
	fprintf(stderr, "N1_HOST_LOWER: %s\n", message);
	return 1;
}

static int lower_probe_text(ouro_v *value, const char *expected)
{
	return value != 0 && value->tag == OURO_TAG_BYTES && value->u.s != 0 &&
		value->n == (int)strlen(expected) &&
		memcmp(value->u.s, expected, strlen(expected)) == 0;
}

static ouro_v *raw_probe_step(ouro_env *env, ouro_v *contract)
{
	unsigned long id = as_nat(contract);
	ouro_v *chunk;
	ouro_v *fields[2];

	raw_probe_calls++;
	if (id != raw_probe_calls || !lower_probe_text(env->v, "captured step") ||
	    ouro_heap_live_bytes() > raw_probe_base + 65536ULL)
		raw_probe_failed = 1;
	memset(ouro_alloc(1024UL * 1024UL), 0xA5, 1024UL * 1024UL);
	if (raw_probe_mode == 1 && id == 2) {
		chunk = codes("first failure");
		chunk = ouro_ctor(7, 1, &chunk);
		return ouro_ctor(0, 1, &chunk);
	}
	if (raw_probe_mode == 2) {
		fields[0] = nil();
		fields[1] = nil();
		return ouro_ctor(1, 2, fields);
	}
	chunk = id == 2 ? nil() : cons(pair(ouro_nat(id * 10), codes("raw survivor")), nil());
	if (id == 3) {
		fields[0] = chunk;
		fields[1] = cons(pair(ouro_nat(31), codes("raw survivor")), nil());
		chunk = ouro_ctor(OURO_TAG_CAT, 2, fields);
	}
	if (raw_probe_mode == 3)
		chunk = cons(pair(ouro_nat(10), codes("raw survivor")), codes("invalid tail"));
	return ouro_ctor(1, 1, &chunk);
}

static int check_raw_lower(int mode)
{
	const unsigned long expected[4] = {10, 30, 31, 40};
	ouro_v *fields[2];
	ouro_v *contracts;
	ouro_v *step;
	ouro_v *result;
	ouro_v *current;
	unsigned long long total;
	unsigned long i;

	fields[0] = cons(ouro_nat(1), cons(ouro_nat(2), nil()));
	fields[1] = cons(ouro_nat(3), cons(ouro_nat(4), nil()));
	contracts = mode == 4 ? cons(ouro_nat(1), codes("invalid tail")) :
		ouro_ctor(OURO_TAG_CAT, 2, fields);
	step = ouro_clos(raw_probe_step, ouro_cons(codes("captured step"), 0));
	raw_probe_calls = 0;
	raw_probe_failed = 0;
	raw_probe_mode = mode;
	raw_probe_base = ouro_heap_live_bytes();
	total = ouro_heap_total_alloc_bytes();
	result = lower_raw_parts(step, contracts);
	if (mode >= 2)
		return lower_probe_fail("malformed raw protocol was accepted");
	if (raw_probe_failed || raw_probe_calls != (mode == 1 ? 2UL : 4UL) ||
	    ouro_heap_live_bytes() > raw_probe_base + 65536ULL ||
	    ouro_heap_total_alloc_bytes() < total + raw_probe_calls * 1024ULL * 1024ULL)
		return lower_probe_fail("raw order, captured closure or temporary allocation bound");
	ouro_heap_mark();
	memset(ouro_alloc(1024UL * 1024UL), 0x5A, 1024UL * 1024UL);
	ouro_heap_reset();
	if (mode == 1) {
		if (result == 0 || result->tag != 0 || result->n != 1)
			return lower_probe_fail("first raw failure did not survive reset");
		current = OURO_F(result, 0);
		return current == 0 || current->tag != 7 || current->n != 1 ||
			!lower_probe_text(OURO_F(current, 0), "first failure") ?
			lower_probe_fail("first raw failure payload changed") : 0;
	}
	if (result == 0 || result->tag != 1 || result->n != 1)
		return lower_probe_fail("raw chunks did not produce a result");
	current = OURO_F(result, 0);
	for (i = 0; i < 4; i++) {
		ouro_v *item;
		if (current == 0 || current->tag != 1 || current->n != 2)
			return lower_probe_fail("raw chunk length changed");
		item = OURO_F(current, 0);
		if (item == 0 || item->tag != 0 || item->n != 2 ||
		    as_nat(OURO_F(item, 0)) != expected[i] ||
		    !lower_probe_text(OURO_F(item, 1), "raw survivor"))
			return lower_probe_fail("raw chunk order or survivor changed");
		current = OURO_F(current, 1);
	}
	return current == 0 || current->tag != 0 || current->n != 0 ?
		lower_probe_fail("raw chunks contain unexpected trailing data") : 0;
}

static int check_lower_survivors(void)
{
	ouro_v *fuel = ouro_nat(4097);
	ouro_v *entry = ouro_nat(4098);
	ouro_v *checked = pair(codes("checked marker"), cons(ouro_nat(4099), nil()));
	ouro_v *plan = pair(checked, pair(fuel, entry));
	ouro_v *value = pair(plan, codes("raw marker"));
	int i;

	for (i = 0; i < 2; i++) {
		uintptr_t old_fuel = (uintptr_t)fuel;
		uintptr_t old_entry = (uintptr_t)entry;
		uintptr_t old_checked = (uintptr_t)checked;

		value = keep_lower_output(value, &fuel, &entry, &checked);
		plan = OURO_F(value, 0);
		if ((uintptr_t)fuel == old_fuel || (uintptr_t)entry == old_entry ||
		    (uintptr_t)checked == old_checked || as_nat(fuel) != 4097 ||
		    as_nat(entry) != 4098 || !lower_probe_text(OURO_F(checked, 0), "checked marker") ||
		    as_nat(OURO_F(OURO_F(checked, 1), 0)) != 4099 ||
		    OURO_F(plan, 0) != checked || OURO_F(OURO_F(plan, 1), 0) != fuel ||
		    OURO_F(OURO_F(plan, 1), 1) != entry ||
		    !lower_probe_text(OURO_F(value, 1), "raw marker"))
			return lower_probe_fail("checkpoint did not rebind the complete survivor graph");
	}
	return 0;
}

static int pe_probe_fail(const char *message)
{
	fprintf(stderr, "N1_HOST_PE: %s\n", message);
	return 1;
}

static unsigned char pe_probe_byte(unsigned long position)
{
	return (unsigned char)((position * 73UL) ^ (position >> 8));
}

/* Invoke the generated Ouro validator on every byte. The host only builds
   the input and compares the complete returned content and allocation bound. */
static int check_pe_large_bytes(void)
{
	const unsigned long sizes[2] = {256UL * 1024UL, 512UL * 1024UL};
	unsigned char *expected = (unsigned char *)malloc(sizes[1]);
	char *actual = (char *)malloc(sizes[1] + 1);
	ouro_v *check = find_export("pe_check_bytes");
	ouro_v *inputs[2];
	ouro_v *results[2];
	ouro_v *caller = pair(codes("caller byte context"), ouro_nat(4097));
	unsigned long long base;
	unsigned long i;
	int failed = 0;

	if (expected == 0 || actual == 0) {
		free(expected);
		free(actual);
		return pe_probe_fail("cannot allocate byte fixture");
	}
	for (i = 0; i < sizes[1]; i++)
		expected[i] = pe_probe_byte(i);
	for (i = 0; i < 2; i++)
		inputs[i] = ouro_packed(expected, sizes[i]);
	base = ouro_heap_live_bytes();
	for (i = 0; i < 2; i++)
		results[i] = ouro_apply(check, inputs[i]);
	if (ouro_heap_live_bytes() > base + 64ULL * 1024ULL * 1024ULL)
		failed = 1;
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0xA5, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	for (i = 0; i < 2; i++) {
		ouro_v *result = results[i];
		if (result == 0 || result->tag != 1 || result->n != 1 ||
		    codes_to_buf(OURO_F(result, 0), actual, (int)sizes[i] + 1) != (int)sizes[i] ||
		    memcmp(actual, expected, sizes[i]) != 0 ||
		    codes_to_buf(inputs[i], actual, (int)sizes[i] + 1) != (int)sizes[i] ||
		    memcmp(actual, expected, sizes[i]) != 0)
			failed = 1;
	}
	if (!lower_probe_text(OURO_F(caller, 0), "caller byte context") ||
	    as_nat(OURO_F(caller, 1)) != 4097)
		failed = 1;
	free(expected);
	free(actual);
	return failed ? pe_probe_fail("large byte content, caller lifetime or temporary bound") : 0;
}

static int check_pe_byte_errors(void)
{
	const unsigned long offsets[6] = {0, 0, 1023, 1024, 1025, 2055};
	const unsigned long first[6] = {256, 257, 257, 256, 257, 257};
	unsigned char prefix[2055];
	ouro_v *check = find_export("pe_check_bytes");
	ouro_v *results[6];
	unsigned long i;

	for (i = 0; i < sizeof(prefix); i++)
		prefix[i] = pe_probe_byte(i);
	for (i = 0; i < 6; i++) {
		ouro_v *fields[2] = {ouro_packed(prefix, offsets[i]),
			cons(ouro_nat(first[i]), cons(ouro_nat(first[i] == 256 ? 257 : 256), nil()))};
		results[i] = ouro_apply(check, ouro_ctor(OURO_TAG_CAT, 2, fields));
	}
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0x5A, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	for (i = 0; i < 6; i++) {
		ouro_v *error;
		if (results[i] == 0 || results[i]->tag != 0 || results[i]->n != 1)
			return pe_probe_fail("invalid byte was accepted");
		error = OURO_F(results[i], 0);
		if (error == 0 || error->tag != 0 || error->n != 1 ||
		    as_nat(OURO_F(error, 0)) != first[i])
			return pe_probe_fail("first byte error or retained payload changed");
	}
	return 0;
}

/* Typed callback results test the seam's lifetime, not PE validation. The
   preceding probes exercise the actual generated validator and its errors. */
static unsigned long pe_work_calls;
static unsigned long pe_raw_calls[2];
static int pe_work_failed;

static ouro_v *pe_captured_work(ouro_env *env, ouro_v *unit)
{
	ouro_v *capture = ouro_get(env, 0);
	ouro_v *metadata = OURO_F(capture, 0);
	ouro_v *bytes = OURO_F(capture, 1);
	ouro_v *result;
	pe_work_calls++;
	if (unit == 0 || unit->tag != 0 || unit->n != 0 ||
	    !lower_probe_text(OURO_F(metadata, 0), "captured byte thunk") ||
	    as_nat(OURO_F(metadata, 1)) != 4097 ||
	    bytes == 0 || bytes->tag != OURO_TAG_BYTES || bytes->n != 257)
		pe_work_failed = 1;
	memset(ouro_alloc(1024UL * 1024UL), 0xA5, 1024UL * 1024UL);
	if (pe_work_calls % 2UL == 0) {
		/* A phase suffix cell borrows the retained capture's packed buffer. */
		result = (ouro_v *)ouro_alloc(sizeof(ouro_v));
		result->tag = OURO_TAG_BYTES;
		result->n = bytes->n - (int)pe_work_calls;
		result->u.s = bytes->u.s + pe_work_calls;
		result = cons(ouro_nat(pe_work_calls), result);
		return ouro_ctor(1, 1, &result);
	}
	/* Left (PeInstructionError (X64ShiftOutOfRange X64Bits64 amount)). */
	result = ouro_ctor(3, 2, (ouro_v *[]){ouro_ctor(1, 0, 0),
		ouro_nat(4097 + pe_work_calls)});
	result = ouro_ctor(21, 1, &result);
	return ouro_ctor(0, 1, &result);
}

static ouro_v *pe_captured_raw(ouro_env *env, ouro_v *work)
{
	unsigned long id = as_nat(ouro_get(env, 0));
	if (id > 1) {
		pe_work_failed = 1;
		return 0;
	}
	pe_raw_calls[id]++;
	return ouro_apply(work, nil());
}

ouro_v *ouro_wrap_pe_run_byte_check(ouro_v *raw);

static int check_pe_byte_context(void)
{
	unsigned char expected[257];
	char actual[258];
	ouro_v *run = find_export("pe_run_byte_check");
	ouro_v *metadata = pair(codes("captured byte thunk"), ouro_nat(4097));
	ouro_v *capture;
	ouro_v *work;
	ouro_v *first = ouro_wrap_pe_run_byte_check(
		ouro_clos(pe_captured_raw, ouro_cons(ouro_nat(0), 0)));
	ouro_v *second = ouro_wrap_pe_run_byte_check(
		ouro_clos(pe_captured_raw, ouro_cons(ouro_nat(1), 0)));
	ouro_v *results[7];
	unsigned long long base;
	unsigned long long total;
	unsigned long i;

	for (i = 0; i < sizeof(expected); i++)
		expected[i] = pe_probe_byte(i);
	capture = pair(metadata, ouro_packed(expected, sizeof(expected)));
	work = ouro_clos(pe_captured_work, ouro_cons(capture, 0));
	base = ouro_heap_live_bytes();
	total = ouro_heap_total_alloc_bytes();
	for (i = 0; i < 4; i++)
		results[i] = ouro_apply(run, work);
	results[4] = ouro_apply(first, work);
	results[5] = ouro_apply(second, work);
	results[6] = ouro_apply(first, work);
	if (pe_work_failed || pe_work_calls != 7 || pe_raw_calls[0] != 2 || pe_raw_calls[1] != 1 ||
	    ouro_heap_live_bytes() > base + 65536ULL ||
	    ouro_heap_total_alloc_bytes() < total + pe_work_calls * 1024ULL * 1024ULL)
		return pe_probe_fail("captured callback, raw runner context or temporary bound");
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0x5A, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	for (i = 0; i < 7; i++) {
		ouro_v *result = results[i];
		ouro_v *payload;
		if (result == 0 || result->tag != (i % 2UL == 0 ? 0 : 1) || result->n != 1)
			return pe_probe_fail("callback result branch changed");
		payload = OURO_F(result, 0);
		if (i % 2UL != 0) {
			unsigned long offset = i + 1;
			unsigned long count = sizeof(expected) - offset;
			if (codes_to_buf(payload, actual, sizeof(actual)) != (int)count + 1 ||
			    (unsigned char)actual[0] != offset ||
			    memcmp(actual + 1, expected + offset, count) != 0)
				return pe_probe_fail("callback complete byte suffix changed");
			continue;
		}
		if (payload == 0 || payload->tag != 21 || payload->n != 1)
			return pe_probe_fail("callback PeError payload changed");
		payload = OURO_F(payload, 0);
		if (payload == 0 || payload->tag != 3 || payload->n != 2 ||
		    OURO_F(payload, 0) == 0 || OURO_F(payload, 0)->tag != 1 || OURO_F(payload, 0)->n != 0 ||
		    as_nat(OURO_F(payload, 1)) != 4098 + i)
			return pe_probe_fail("callback nested error payload changed");
	}
	return !lower_probe_text(OURO_F(metadata, 0), "captured byte thunk") ||
		as_nat(OURO_F(metadata, 1)) != 4097 ||
		codes_to_buf(OURO_F(capture, 1), actual, sizeof(actual)) != sizeof(expected) ||
		memcmp(actual, expected, sizeof(expected)) != 0 ?
		pe_probe_fail("captured input was released") : 0;
}

static unsigned long pe_plan_calls;
static int pe_plan_failed;

/* Synthetic curried inputs exercise storage ownership only. The PE law
   suite checks the canonical planner's patch bytes and error precedence. */
static ouro_v *pe_plan_probe_fixups(ouro_env *env, ouro_v *fixups)
{
	ouro_v *result;
	unsigned long id = as_nat(fixups);
	pe_plan_calls++;
	if (as_nat(ouro_get(env, 0)) != 26 || as_nat(ouro_get(env, 1)) != 25 ||
	    !lower_probe_text(ouro_get(env, 2), "borrowed section") ||
	    !lower_probe_text(ouro_get(env, 3), "captured planner"))
		pe_plan_failed = 1;
	memset(ouro_alloc(1024UL * 1024UL), 0xA5, 1024UL * 1024UL);
	if (id % 2UL == 0) {
		result = ouro_ctor(0, 4, (ouro_v *[]){nil(), fixups, ouro_get(env, 2), nil()});
		result = cons(result, nil());
		return ouro_ctor(1, 1, &result);
	}
	result = ouro_ctor(3, 2, (ouro_v *[]){ouro_ctor(1, 0, 0), fixups});
	result = ouro_ctor(21, 1, &result);
	return ouro_ctor(0, 1, &result);
}

static ouro_v *pe_plan_probe_imports(ouro_env *env, ouro_v *imports)
{
	return ouro_clos(pe_plan_probe_fixups, ouro_cons(imports, env));
}

static ouro_v *pe_plan_probe_symbols(ouro_env *env, ouro_v *symbols)
{
	return ouro_clos(pe_plan_probe_imports, ouro_cons(symbols, env));
}

static ouro_v *pe_plan_probe_sections(ouro_env *env, ouro_v *sections)
{
	return ouro_clos(pe_plan_probe_symbols, ouro_cons(sections, env));
}

ouro_v *ouro_wrap_pe_plan_fixups(ouro_v *raw);

static int check_pe_patch_context(void)
{
	ouro_v *caller = codes("borrowed section");
	ouro_v *raw = ouro_clos(pe_plan_probe_sections, ouro_cons(codes("captured planner"), 0));
	ouro_v *first = ouro_apply(ouro_apply(ouro_apply(ouro_wrap_pe_plan_fixups(raw), caller),
		ouro_nat(25)), ouro_nat(26));
	ouro_v *second = ouro_apply(ouro_apply(ouro_apply(ouro_wrap_pe_plan_fixups(raw), caller),
		ouro_nat(25)), ouro_nat(26));
	ouro_v *results[8];
	ouro_v *retained;
	unsigned long long base = ouro_heap_live_bytes();
	unsigned long long total = ouro_heap_total_alloc_bytes();
	ouro_heap_context *context = ouro_heap_context_enter();
	unsigned long i;
	for (i = 0; i < 8; i++)
		results[i] = ouro_apply(i == 5 ? second : first, ouro_nat(4096 + i));
	retained = ouro_heap_context_leave(context, ouro_ctor(0, 8, results));
	if (pe_plan_failed || pe_plan_calls != 8 || ouro_heap_live_bytes() > base + 65536ULL ||
	    ouro_heap_total_alloc_bytes() < total + 8ULL * 1024ULL * 1024ULL)
		return pe_probe_fail("patch planner arguments, invocation count or temporary bound");
	ouro_heap_mark();
	memset(ouro_alloc(8UL * 1024UL * 1024UL), 0x5A, 8UL * 1024UL * 1024UL);
	ouro_heap_reset();
	for (i = 0; i < 8; i++) {
		ouro_v *result = OURO_F(retained, i);
		ouro_v *payload;
		if (result == 0 || result->tag != (i % 2UL == 0 ? 1 : 0) || result->n != 1)
			return pe_probe_fail("patch planner result branch changed");
		payload = OURO_F(result, 0);
		if (i % 2UL == 0) {
			if (payload == 0 || payload->tag != 1 || payload->n != 2 ||
			    OURO_F(payload, 1)->tag != 0 || OURO_F(payload, 1)->n != 0)
				return pe_probe_fail("patch planner list changed");
			payload = OURO_F(payload, 0);
			if (payload == 0 || payload->tag != 0 || payload->n != 4 ||
			    as_nat(OURO_F(payload, 1)) != 4096 + i ||
			    !lower_probe_text(OURO_F(payload, 2), "borrowed section"))
				return pe_probe_fail("patch planner retained bytes changed");
		} else {
			if (payload == 0 || payload->tag != 21 || payload->n != 1)
				return pe_probe_fail("patch planner error changed");
			payload = OURO_F(payload, 0);
			if (payload == 0 || payload->tag != 3 || payload->n != 2 ||
			    OURO_F(payload, 0)->tag != 1 || OURO_F(payload, 0)->n != 0 ||
			    as_nat(OURO_F(payload, 1)) != 4096 + i)
				return pe_probe_fail("patch planner nested error changed");
		}
	}
	return lower_probe_text(caller, "borrowed section") ? 0 : pe_probe_fail("patch planner released caller");
}

int main(int argc, char **argv)
{
	ouro_v *image;
	int result;
	const char *mode;
	if (argc != 2)
		return 2;
	mode = argv[1];
	if (strcmp(mode, "valid-quiet") == 0)
		mode = "valid";
	else if (strcmp(mode, "lower-bad-result-quiet") == 0)
		mode = "lower-bad-result";
	else
		ouro_fe_set_progress(1);
	ouro_rt_warmup();
	if (strcmp(mode, "diagnostic-strings") == 0) {
		ouro_v *parts[2];
		const unsigned char binary[3] = {'a', 0, 'z'};
		print_string("str: ", ouro_str("text"));
		print_string("packed: ", codes("lower:entry:123"));
		print_string("list: ", ouro_bytes((const unsigned char *)"text", 4));
		parts[0] = codes("lower:");
		parts[1] = ouro_bytes((const unsigned char *)"body:456", 8);
		print_string("cat: ", ouro_ctor(OURO_TAG_CAT, 2, parts));
		print_string("empty: ", nil());
		print_string("binary: ", ouro_packed(binary, 3));
		print_string("invalid: ", ouro_ctor(77, 0, 0));
		puts("N1_HOST_DIAGNOSTICS: passed");
		return 0;
	}
	if (strcmp(mode, "pe-byte-large") == 0)
		result = check_pe_large_bytes();
	else if (strcmp(mode, "pe-byte-errors") == 0)
		result = check_pe_byte_errors();
	else if (strcmp(mode, "pe-byte-context") == 0)
		result = check_pe_byte_context();
	else if (strcmp(mode, "pe-patch-context") == 0)
		result = check_pe_patch_context();
	else
		result = -1;
	if (result >= 0) {
		if (result == 0)
			printf("N1_HOST_PE: passed %s\n", argv[1]);
		return result;
	}
	if (strcmp(mode, "lower-raw-order") == 0)
		result = check_raw_lower(0);
	else if (strcmp(mode, "lower-raw-left") == 0)
		result = check_raw_lower(1);
	else if (strcmp(mode, "lower-survivors") == 0)
		result = check_lower_survivors();
	else if (strcmp(mode, "lower-bad-result") == 0)
		result = check_raw_lower(2);
	else if (strcmp(mode, "lower-bad-chunk") == 0)
		result = check_raw_lower(3);
	else if (strcmp(mode, "lower-bad-contracts") == 0)
		result = check_raw_lower(4);
	else
		result = -1;
	if (result >= 0) {
		if (result == 0)
			printf("N1_HOST_LOWER: passed %s\n", argv[1]);
		return result;
	}
	if (strcmp(mode, "mir-program-context") == 0)
		result = check_program_context();
	else if (strcmp(mode, "mir-flow-context") == 0)
		result = check_flow_context();
	else if (strcmp(mode, "mir-phase-errors") == 0)
		result = check_mir_phase_errors(0);
	else if (strcmp(mode, "mir-phase-nested") == 0)
		result = check_mir_phase_errors(1);
	else if (strcmp(mode, "mir-reachability-rounds") == 0)
		result = check_mir_reachability_rounds();
	else if (strcmp(mode, "mir-flow-rounds") == 0)
		result = check_mir_flow_rounds();
	else if (strcmp(mode, "codegen-program-context") == 0)
		result = check_codegen_context();
	else
		result = -1;
	if (result >= 0) {
		if (result == 0)
			printf("N1_HOST_CONTEXT: passed %s\n", argv[1]);
		return result;
	}
	if (strcmp(mode, "valid") != 0 &&
	    strcmp(mode, "uninitialized") != 0 && strcmp(mode, "bad-return") != 0)
		return 2;
	image = emit_mir(probe_mir(strcmp(mode, "uninitialized") == 0,
		strcmp(mode, "bad-return") == 0));
	if (image == 0 || image->n < 1 || OURO_F(image, 0) == 0)
		return 1;
	printf("N1_HOST_MIR: emitted %s\n", argv[1]);
	return 0;
}
