/* Compare the C-host codegen seam with its generated canonical callbacks.
   Including the adapter keeps raw callbacks out of the production API. */
#ifndef OURO_FE_FLAT_EXPORTS
#define OURO_FE_FLAT_EXPORTS
#endif
#include "frontend_link.c"
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

static int test_forwarded_arguments(void)
{
	ouro_v *args[6];
	ouro_v *wrapped = ouro_wrap_codegen_block(ouro_clos(test_capture, 0));
	ouro_v *out;
	int i;
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
	int nl = 0, nr = 0, cl = 0, cr = 0;
	int same = 1;
	int i;
	if (host_list_collect(left, &lhs, &nl, &cl) != 0
	    || host_list_collect(right, &rhs, &nr, &cr) != 0 || nl != nr)
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
	int n = 0, cap = 0, i;
	int live = 0, dead = 0;
	if (result == 0 || result->tag != 1 || result->n != 1
	    || host_list_collect(OURO_F(result, 0), &atoms, &n, &cap) != 0) {
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
	fast = cgb_try(program, slots, args[2], args[3], blocks, block);
	pure = test_apply6(g_raw_cgb, args);
	if (!test_bytes_equal(fast, pure))
		return test_fail("tail-call byte parity");
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
	return 0;
}

static ouro_v *test_remap_instructions(ouro_v *list, unsigned long old_id,
	ouro_v *new_id, int *references)
{
	ouro_v **items = 0;
	ouro_v *result = 0;
	int n = 0, cap = 0, i;
	if (host_list_collect(list, &items, &n, &cap) != 0)
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
	int n = 0, cap = 0, i;
	if (host_list_collect(list, &blocks, &n, &cap) != 0)
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
	int dc = 0, gc = 0, fc = 0, oc = 0;
	int definitions = 0, references = 0, i;
	if (program == 0 || program->tag != 0 || program->n != 4
	    || host_list_collect(ouro_apply(FIND(lo, "mir_managed_descriptors"), program),
		&descriptors, &nd, &dc) != 0 || nd == 0
	    || x64enc_dec_nat(descriptors[0], &old_id) != 0
	    || host_list_collect(ouro_apply(FIND(lo, "mir_global_ids"), program),
		&globals, &ng, &gc) != 0)
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
	if (host_list_collect(OURO_F(program, 0), &functions, &nf, &fc) != 0
	    || host_list_collect(OURO_F(program, 1), &objects, &no, &oc) != 0)
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

int main(int argc, char **argv)
{
	int result;
	ouro_rt_warmup();
	ouro_io_set_argv(argc, argv);
	if (argc == 3 && (strcmp(argv[1], "live-reclaim") == 0
	    || strcmp(argv[1], "live-calls") == 0 || strcmp(argv[1], "live-high-descriptor") == 0))
		result = test_live_image(argv[1], argv[2]);
	else if (argc != 2)
		return 2;
	else if (strcmp(argv[1], "fallback-forward") == 0)
		result = test_forwarded_arguments();
	else if (strcmp(argv[1], "root-parity") == 0)
		result = test_roots();
	else if (strcmp(argv[1], "root-clear-context") == 0)
		result = test_root_clear_context();
	else
		return 2;
	if (result == 0)
		printf("FRONTEND_CODEGEN_SELFTEST: passed %s\n", argv[1]);
	return result;
}
