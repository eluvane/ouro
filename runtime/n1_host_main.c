/* C-hosted N1 producer: check through frontend_link phase seams, then
   lower/codegen with the generated Ouro backend. Replaces ouro_prog_main
   so compile_checked_units inlining cannot keep every parse temporary. */
#include "ouro_host_values.h"
#include "ouro_io.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);
void ouro_fe_reset_mir_pins(void);

static ouro_v *keep_reset(ouro_v *v)
{
	v = ouro_keep(v);
	ouro_fe_reset_mir_pins();
	return v;
}


static ouro_v *find_export(const char *name)
{
	int i;
	int n = ouro_export_count();

	for (i = 0; i < n; i++) {
		if (strcmp(ouro_export_name(i), name) == 0)
			return ouro_export_value(i);
	}
	fprintf(stderr, "n1-host: missing export %s\n", name);
	exit(2);
	return 0;
}

static ouro_v *nil(void)
{
	return ouro_ctor(0, 0, 0);
}

static ouro_v *cons(ouro_v *head, ouro_v *tail)
{
	ouro_v *fields[2];

	fields[0] = head;
	fields[1] = tail;
	return ouro_ctor(1, 2, fields);
}

static ouro_v *pair(ouro_v *a, ouro_v *b)
{
	ouro_v *fields[2];

	fields[0] = a;
	fields[1] = b;
	return ouro_ctor(0, 2, fields);
}


static ouro_v *read_file_codes(const char *path)
{
	FILE *f;
	unsigned char *buf;
	long n;
	ouro_v *v;

	f = fopen(path, "rb");
	if (f == 0) {
		fprintf(stderr, "n1-host: cannot read %s\n", path);
		exit(1);
	}
	if (fseek(f, 0, SEEK_END) != 0) {
		fclose(f);
		fprintf(stderr, "n1-host: seek failed %s\n", path);
		exit(1);
	}
	n = ftell(f);
	if (n < 0) {
		fclose(f);
		fprintf(stderr, "n1-host: size failed %s\n", path);
		exit(1);
	}
	rewind(f);
	buf = (unsigned char *)malloc((size_t)n + 1U);
	if (buf == 0) {
		fclose(f);
		fputs("n1-host: out of memory reading source\n", stderr);
		exit(1);
	}
	if (n > 0 && fread(buf, 1, (size_t)n, f) != (size_t)n) {
		free(buf);
		fclose(f);
		fprintf(stderr, "n1-host: short read %s\n", path);
		exit(1);
	}
	fclose(f);
	v = ouro_packed(buf, (unsigned long)n);
	free(buf);
	return v;
}

static void die_comp(ouro_v *r)
{
	ouro_v *err;
	unsigned long code = 0;
	unsigned long detail = 0;

	if (r != 0 && r->tag == 0 && r->n >= 1) {
		err = OURO_F(r, 0);
		if (err != 0 && err->n >= 2) {
			code = as_nat(OURO_F(err, 0));
			detail = as_nat(OURO_F(err, 1));
		}
	}
	fprintf(stderr, "n1-host: check failed source:%lu:%lu\n", code, detail);
	exit(1);
}

static void print_string(const char *prefix, ouro_v *v)
{
	if (v != 0 && v->tag == OURO_TAG_STR && v->u.s != 0)
		fprintf(stderr, "%s%s\n", prefix, v->u.s);
	else
		fprintf(stderr, "%s<non-string tag=%d n=%d>\n", prefix,
			v == 0 ? -1 : v->tag, v == 0 ? -1 : v->n);
}

static void die_either(const char *phase, ouro_v *r)
{
	ouro_v *payload;
	ouro_v *msg;

	fprintf(stderr, "n1-host: %s failed tag=%d n=%d live=%llu\n", phase,
		r == 0 ? -1 : r->tag, r == 0 ? -1 : r->n, ouro_heap_live_bytes());
	if (r != 0 && r->n >= 1) {
		payload = OURO_F(r, 0);
		msg = ouro_apply(find_export("managed_driver_source_error"), payload);
		print_string("n1-host: ", msg);
	}
	exit(1);
}

static void die_as_source(const char *phase, int source_tag, ouro_v *payload)
{
	ouro_v *src = ouro_ctor(source_tag, 1, &payload);
	ouro_v *left = ouro_ctor(0, 1, &src);

	die_either(phase, left);
}

static void die_codegen(const char *phase, ouro_v *r)
{
	ouro_v *payload;
	ouro_v *msg;

	fprintf(stderr, "n1-host: %s failed tag=%d n=%d live=%llu\n", phase,
		r == 0 ? -1 : r->tag, r == 0 ? -1 : r->n, ouro_heap_live_bytes());
	if (r != 0 && r->n >= 1) {
		payload = OURO_F(r, 0);
		msg = ouro_apply(find_export("managed_driver_error"), payload);
		print_string("n1-host: ", msg);
	}
	exit(1);
}

static unsigned long count_list(ouro_v *xs)
{
	unsigned long n = 0;
	ouro_v *stack[64];
	int sp = 0;

	for (;;) {
		if (list_done(xs)) {
			if (sp == 0)
				return n;
			xs = stack[--sp];
			continue;
		}
		if (xs != 0 && xs->tag == OURO_TAG_CAT && xs->n == 2) {
			if (sp >= 63)
				return n;
			stack[sp++] = OURO_F(xs, 1);
			xs = OURO_F(xs, 0);
			continue;
		}
		if (xs != 0 && xs->tag == 1 && xs->n == 2) {
			n++;
			xs = OURO_F(xs, 1);
			continue;
		}
		return n;
	}
}

static ouro_v *compiler_limits(void);

static void die_mir(const char *phase, ouro_v *result)
{
	ouro_v *error;
	ouro_v *wrapped;
	if (result == 0 || result->tag != 0 || result->n != 1) {
		fprintf(stderr, "n1-host: %s returned an invalid MIR result\n", phase);
		exit(1);
	}
	error = OURO_F(result, 0);
	wrapped = ouro_ctor(0, 1, &error); /* NativeMirError */
	die_codegen(phase, ouro_ctor(0, 1, &wrapped));
}

static ouro_v *emit_mir(ouro_v *mir)
{
	ouro_v *flow;
	ouro_v *r;
	ouro_v *bodies;

	if (mir != 0 && mir->n >= 1)
		fprintf(stderr, "n1-host: mir functions=%lu live=%llu\n",
			count_list(OURO_F(mir, 0)), ouro_heap_live_bytes());
	/* GC annotation and successful encoding cannot establish MIR validity. */
	fprintf(stderr, "n1-host: mir-check live=%llu\n", ouro_heap_live_bytes());
	r = ouro_apply(ouro_apply(find_export("mir_check_program"), compiler_limits()), mir);
	if (r == 0 || r->tag != 1 || r->n != 1)
		die_mir("mir-check", r);
	mir = keep_reset(mir);
	flow = ouro_nat(16777216UL);
	fprintf(stderr, "n1-host: gc-infer live=%llu\n", ouro_heap_live_bytes());
	r = ouro_apply(ouro_apply(find_export("mir_gc_infer"), flow), mir);
	if (r == 0 || r->tag != 1 || r->n < 1)
		die_mir("gc-infer", r);
	bodies = OURO_F(r, 0);
	fprintf(stderr, "n1-host: annotate live=%llu\n", ouro_heap_live_bytes());
	mir = ouro_apply(ouro_apply(find_export("mir_gc_annotate"), mir), bodies);
	r = ouro_apply(ouro_apply(find_export("mir_gc_check"), mir), bodies);
	if (r == 0 || r->tag != 1)
		die_mir("gc-check", r);
	mir = keep_reset(pair(mir, bodies));
	mir = OURO_F(mir, 0);
	fprintf(stderr, "n1-host: codegen live=%llu\n", ouro_heap_live_bytes());
	r = ouro_apply(find_export("codegen_checked"), mir);
	if (r == 0 || r->tag != 1 || r->n < 1)
		die_codegen("codegen", r);
	return keep_reset(OURO_F(r, 0));
}

static ouro_v *compiler_limits(void)
{
	ouro_v *fields[3];

	fields[0] = ouro_nat(16777216UL);
	fields[1] = ouro_nat(16777216UL);
	fields[2] = ouro_nat(16777216UL);
	return ouro_clone_perm(ouro_ctor(0, 3, fields));
}

static ouro_v *lookup_main(ouro_v *checked)
{
	ouro_v *intern = ouro_apply(find_export("checked_program_intern"), checked);
	ouro_v *names;
	ouro_v *entry;

	if (intern == 0 || intern->n < 1)
		die_either("intern", intern);
	names = OURO_F(intern, 0);
	entry = ouro_apply(ouro_apply(find_export("source_lookup_id"), names),
			   ouro_string_codes("main"));
	if (entry == 0 || entry->tag != 1 || entry->n < 1) {
		fputs("n1-host: entry main not found\n", stderr);
		exit(1);
	}
	return OURO_F(entry, 0);
}


/* Preserve every value used after a phase reset, including scalar fallback
   inputs. None of the caller's old phase/permanent pointers remain valid. */
static ouro_v *keep_lower_output(ouro_v *value, ouro_v **fuel,
				 ouro_v **entry, ouro_v **checked)
{
	ouro_v *fields[4] = {value, *fuel, *entry, *checked};
	ouro_v *kept = keep_reset(ouro_ctor(0, 4, fields));

	*fuel = OURO_F(kept, 1);
	*entry = OURO_F(kept, 2);
	*checked = OURO_F(kept, 3);
	return OURO_F(kept, 0);
}

static void require_lower_result(const char *phase, ouro_v *result)
{
	if (result == 0 || (result->tag != 0 && result->tag != 1) ||
	    result->n != 1 || OURO_F(result, 0) == 0) {
		fprintf(stderr, "n1-host: %s returned an invalid lowering result\n", phase);
		exit(2);
	}
}

/* The stack is a host-owned List of list segments. Concat nodes retain their
   original order without a depth limit or recursive traversal. */
static int lower_list_next(ouro_v **pending, ouro_v **head, const char *phase)
{
	while ((*pending)->tag == 1) {
		ouro_v *segment = OURO_F(*pending, 0);
		ouro_v *rest = OURO_F(*pending, 1);

		if (segment != 0 && segment->tag == 0 && segment->n == 0) {
			*pending = rest;
		} else if (segment != 0 && segment->tag == OURO_TAG_CAT && segment->n == 2) {
			*pending = cons(OURO_F(segment, 0), cons(OURO_F(segment, 1), rest));
		} else if (segment != 0 && segment->tag == 1 && segment->n == 2 &&
			   OURO_F(segment, 0) != 0) {
			*head = OURO_F(segment, 0);
			*pending = cons(OURO_F(segment, 1), rest);
			return 1;
		} else {
			fprintf(stderr, "n1-host: %s returned an invalid list\n", phase);
			exit(2);
		}
	}
	return 0;
}

/* The generated Ouro step owns lowering and its typed failures. Only its
   temporary allocations are released here; successful chunks stay in order. */
static ouro_v *lower_raw_parts(ouro_v *step, ouro_v *contracts)
{
	ouro_v *pending = cons(contracts, nil());
	ouro_v *reversed = nil();
	ouro_v *contract;
	ouro_v *raw = nil();

	while (lower_list_next(&pending, &contract, "contracts")) {
		ouro_v *result;
		ouro_v *chunk;
		ouro_v *function;

		ouro_heap_mark();
		result = ouro_apply(step, contract);
		require_lower_result("raw", result);
		result = ouro_clone_perm(result);
		ouro_heap_reset();
		if (result->tag == 0)
			return result;
		chunk = cons(OURO_F(result, 0), nil());
		while (lower_list_next(&chunk, &function, "raw"))
			reversed = cons(function, reversed);
	}
	while (reversed->tag == 1) {
		raw = cons(OURO_F(reversed, 0), raw);
		reversed = OURO_F(reversed, 1);
	}
	return ouro_ctor(1, 1, &raw);
}

static ouro_v *build_managed_parts(ouro_v **fuel, ouro_v **entry,
				   ouro_v **checked, ouro_v *types)
{
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		find_export("managed_prepare_rechecked"), *fuel), *entry), *checked), types);
	ouro_v *plan;
	ouro_v *contracts;
	ouro_v *step;

	require_lower_result("prepare", result);
	result = keep_lower_output(result, fuel, entry, checked);
	if (result->tag == 0)
		return result;
	plan = OURO_F(result, 0);
	contracts = ouro_apply(find_export("managed_plan_contracts"), plan);
	step = ouro_apply(ouro_apply(find_export("managed_lower_raw_part"), *fuel), plan);
	result = lower_raw_parts(step, contracts);
	result = keep_lower_output(pair(plan, result), fuel, entry, checked);
	plan = OURO_F(result, 0);
	result = OURO_F(result, 1);
	if (result->tag == 0)
		return result;
	/* managed_global_function's host seam has its own non-nestable mark. */
	result = ouro_apply(ouro_apply(ouro_apply(find_export("managed_finish_plan"),
		*fuel), plan), OURO_F(result, 0));
	require_lower_result("finish", result);
	return result;
}

int main(int argc, char **argv)
{
	char root[4096];
	const char *output;
	ouro_v *files;
	ouro_v *result;
	ouro_v *checked;
	ouro_v *entry;
	ouro_v *fuel;
	ouro_v *limits;
	ouro_v *image;
	ouro_v *pe;
	ouro_v *bytes;
	int i;

	if (argc < 3) {
		fputs("usage: n1-host ROOT.ouro OUT.exe UNIT.ouro ...\n", stderr);
		return 2;
	}
	setvbuf(stderr, 0, _IONBF, 0);
	ouro_fe_reset_mir_pins();
	snprintf(root, sizeof root, "%s", argv[1]);
	ouro_slash_path(root);
	output = argv[2];
	files = nil();
	for (i = argc - 1; i >= 3; i--) {
		char path[4096];

		snprintf(path, sizeof path, "%s", argv[i]);
		ouro_slash_path(path);
		files = cons(pair(ouro_string_codes(path), read_file_codes(argv[i])), files);
	}
	if (argc == 3)
		files = cons(pair(ouro_string_codes(root), read_file_codes(argv[1])), files);

	fprintf(stderr, "n1-host: check units=%d live=%llu\n",
		argc == 3 ? 1 : argc - 3, ouro_heap_live_bytes());
	result = ouro_fe_compile_checked_units(ouro_nat(200000UL), ouro_string_codes(root), files);
	if (result == 0 || result->tag != 1 || result->n < 1)
		die_comp(result);
	checked = keep_reset(OURO_F(result, 0));
	fprintf(stderr, "n1-host: CHECK_OK live=%llu total=%llu\n",
		ouro_heap_live_bytes(), ouro_heap_total_alloc_bytes());
	ouro_heap_report("n1-after-check");

	fuel = find_export("native_build_fuel");
	fprintf(stderr, "n1-host: recheck live=%llu\n", ouro_heap_live_bytes());
	result = ouro_apply(ouro_apply(find_export("lower_recheck_program"),
				      fuel), checked);
	if (result == 0 || result->tag != 1 || result->n < 1)
		die_as_source("recheck", 1, result == 0 ? 0 : OURO_F(result, 0));
	checked = keep_reset(OURO_F(result, 0));
	fprintf(stderr, "n1-host: RECHECK_OK live=%llu\n", ouro_heap_live_bytes());
	result = ouro_apply(ouro_apply(ouro_apply(
		find_export("checked_program_type_globals_indexed"),
		find_export("normalize_checked_indexed")), fuel), checked);
	if (result == 0 || result->tag != 1 || result->n < 1)
		die_as_source("types", 0, result == 0 ? 0 : OURO_F(result, 0));
	result = keep_reset(pair(checked, OURO_F(result, 0)));
	checked = OURO_F(result, 0);
	{
		ouro_v *types = OURO_F(result, 1);

		fprintf(stderr, "n1-host: TYPES_OK live=%llu\n",
			ouro_heap_live_bytes());
		entry = lookup_main(checked);
		fprintf(stderr, "n1-host: lower live=%llu\n",
			ouro_heap_live_bytes());
		result = build_managed_parts(&fuel, &entry, &checked, types);
	}
	if (result == 0 || result->tag != 1 || result->n < 1) {
		ouro_v *err = (result != 0 && result->n >= 1) ? OURO_F(result, 0) : 0;
		int tag = err == 0 ? -1 : err->tag;

		if (tag != 4 && tag != 7)
			die_as_source("lower", 1, err);
		fprintf(stderr, "n1-host: managed miss tag=%d; scalar lower\n",
			tag);
		limits = compiler_limits();
		result = ouro_apply(ouro_apply(ouro_apply(ouro_apply(
			find_export("native_scalar_lower_checked"), fuel),
			limits), entry), checked);
		if (result == 0 || result->tag != 1 || result->n < 1)
			die_either("lower", result);
		/* NativeLoweredOf checked contracts mir */
		image = emit_mir(OURO_F(OURO_F(result, 0), 2));
	} else {
		ouro_v *parts = keep_reset(OURO_F(result, 0));

		fprintf(stderr, "n1-host: BUILD_OK live=%llu\n",
			ouro_heap_live_bytes());
		/* ManagedProgramOf checked contracts mir. emit_mir checks the
		   entire program before GC annotation or instruction encoding. */
		image = emit_mir(OURO_F(parts, 2));
	}
	fprintf(stderr, "n1-host: LOWER_OK live=%llu\n", ouro_heap_live_bytes());
	ouro_heap_report("n1-after-lower");
	if (image == 0 || image->n < 1)
		die_either("image", image);
	pe = OURO_F(image, 0);
	if (pe == 0 || pe->n < 1)
		die_either("pe", pe);
	bytes = OURO_F(pe, 0);
	/* Use the same byte verification, replacement and cleanup owner as
	   the native CLI. A failed producer must preserve the prior stage. */
	result = ouro_apply(ouro_apply(find_export("native_build_publish_checked"),
		ouro_string_codes(output)), ouro_apply(ouro_io_prim_req("prim_string_of_char_codes"), bytes));
	result = ouro_apply(result, ouro_ctor(0, 0, 0));
	if (result == 0 || result->tag != 1 || result->n != 1) {
		fprintf(stderr, "n1-host: publication failed %s\n", output);
		if (result != 0 && result->tag == 0 && result->n == 1) {
			ouro_write_codes(ouro_apply(find_export("fs_error_message"),
				OURO_F(result, 0)), stderr);
			fputc('\n', stderr);
		}
		return 1;
	}
	fprintf(stderr, "n1-host: WROTE %s live=%llu\n", output,
		ouro_heap_live_bytes());
	printf("%s\n", output);
	return 0;
}
