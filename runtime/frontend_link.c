#define _POSIX_C_SOURCE 200809L
/* Source for _build/gen/fe_link.c. The linker releases temporary arenas
   between compilation units and reports the original typed failures.
   Ouro owns parsing, preprocessing, import resolution, lowering and checking.
   Type-argument erasure belongs to extract.ouro. */
#include "ouro_host_values.h"

#include <stdio.h>
#include <math.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

/* Quality tooling uses the same compiler-owned parser repeatedly without the
   driver's compile-unit phase seam. Scope only its temporary allocations;
   source, intern identities, grammar and typed error results stay in Ouro.
   The hooked harvest (`cm_load_file`) keeps imported function bodies in this
   nested arena so leave() copies signatures, intern deltas and the selected
   file. Caller intern identities are shared across the seam.
   No retry, alternate parser, process-global source cache or semantic
   decision lives here. This two-argument hook also applies in the flat
   native quality tool build. */
static ouro_v *quality_parse_intern(ouro_env *env, ouro_v *intern)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_get(env, 1),
		ouro_get(env, 0)), intern);
	return ouro_heap_context_leave(scope, result);
}

static ouro_v *quality_parse_source(ouro_env *env, ouro_v *source)
{
	return ouro_clos(quality_parse_intern, ouro_cons(source, env));
}

ouro_v *ouro_wrap_quality_parse(ouro_v *raw)
{
	return ouro_clos(quality_parse_source, ouro_cons(raw, 0));
}

static int lower_ctor_lookup_packed_name(ouro_v *value, unsigned long *name)
{
	if (value != 0 && value->tag == OURO_TAG_NAT && value->n >= 0) {
		*name = (unsigned long)value->n;
		return 1;
	}
	if (value == 0 ||
	    !((value->tag == OURO_TAG_NAT && value->n >= 0) ||
	      (value->tag == OURO_TAG_BIG_NAT && value->n > 0 && value->n <= 2)))
		return 0;
	/* Preserve raw equality for noncanonical BIG_NAT limbs. */
	if (value->tag == OURO_TAG_BIG_NAT &&
	    ((const uint32_t *)(value + 1))[value->n - 1] == 0)
		return 0;
	return ouro_nat_to_ulong(value, name);
}

static ouro_v *lower_ctor_lookup_list(ouro_env *env, ouro_v *original)
{
	ouro_v *raw = ouro_get(env, 1);
	ouro_v *name = ouro_get(env, 0);
	ouro_v *cursor = original;
	unsigned long wanted, current;

	if (!lower_ctor_lookup_packed_name(name, &wanted))
		return ouro_apply(ouro_apply(raw, name), original);
	while (cursor != 0) {
		ouro_v *info;
		if (cursor->tag == 0 && cursor->n == 0)
			return ouro_ctor(0, 0, 0);
		if (cursor->tag != 1 || cursor->n != 2)
			break;
		info = OURO_F(cursor, 0);
		if (info == 0 || info->tag != 0 || info->n != 6 ||
		    !lower_ctor_lookup_packed_name(OURO_F(info, 0), &current))
			break;
		/* Preserve the first hit without reading the other fields or tail. */
		if (current == wanted)
			return ouro_ctor(1, 1, &info);
		cursor = OURO_F(cursor, 1);
	}
	/* Retry from the original head with the captured canonical function. */
	return ouro_apply(ouro_apply(raw, name), original);
}

static ouro_v *lower_ctor_lookup_name(ouro_env *env, ouro_v *name)
{
	return ouro_clos(lower_ctor_lookup_list, ouro_cons(name, env));
}

ouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw)
{
	return ouro_clos(lower_ctor_lookup_name, ouro_cons(raw, 0));
}

static ouro_v *module_lookup_list(ouro_env *env, ouro_v *original)
{
	ouro_v *raw = ouro_get(env, 1);
	ouro_v *name = ouro_get(env, 0);
	ouro_v *cursor = original;
	unsigned long wanted, current;

	if (!lower_ctor_lookup_packed_name(name, &wanted))
		return ouro_apply(ouro_apply(raw, name), original);
	while (cursor != 0) {
		ouro_v *row;
		if (cursor->tag == 0 && cursor->n == 0)
			return ouro_ctor(0, 0, 0);
		if (cursor->tag != 1 || cursor->n != 2)
			break;
		row = OURO_F(cursor, 0);
		if (row == 0 || row->tag != 0 || row->n != 2 ||
		    !lower_ctor_lookup_packed_name(OURO_F(row, 0), &current))
			break;
		if (current == wanted) {
			/* The payload and the unvisited tail remain opaque to raw lookup. */
			ouro_v *payload = OURO_F(row, 1);
			return ouro_ctor(1, 1, &payload);
		}
		cursor = OURO_F(cursor, 1);
	}
	/* Preserve the scanned prefix when an unsupported shape requires raw lookup. */
	return ouro_apply(ouro_apply(raw, name), original);
}

static ouro_v *module_lookup_name(ouro_env *env, ouro_v *name)
{
	return ouro_clos(module_lookup_list, ouro_cons(name, env));
}

ouro_v *ouro_wrap_module_lookup(ouro_v *raw)
{
	return ouro_clos(module_lookup_name, ouro_cons(raw, 0));
}

ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity);

ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw)
{
	return ouro_wrap_module_pure_scope(raw, 2);
}

ouro_v *ouro_wrap_elem_scope(ouro_v *raw)
{
	return ouro_wrap_module_pure_scope(raw, 3);
}

#define MAX_PATH 4096
#define FE_PARSE_ERR 10UL

#ifndef OURO_FE_FLAT_EXPORTS
int ouro_export_count_lx(void);
const char *ouro_export_name_lx(int i);
ouro_v *ouro_export_value_lx(int i);
int ouro_export_count_pa(void);
const char *ouro_export_name_pa(int i);
ouro_v *ouro_export_value_pa(int i);
int ouro_export_count_pb(void);
const char *ouro_export_name_pb(int i);
ouro_v *ouro_export_value_pb(int i);
int ouro_export_count_pf(void);
const char *ouro_export_name_pf(int i);
ouro_v *ouro_export_value_pf(int i);
int ouro_export_count_ds(void);
const char *ouro_export_name_ds(int i);
ouro_v *ouro_export_value_ds(int i);
int ouro_export_count_ir(void);
const char *ouro_export_name_ir(int i);
ouro_v *ouro_export_value_ir(int i);
int ouro_export_count_lr(void);
const char *ouro_export_name_lr(int i);
ouro_v *ouro_export_value_lr(int i);
int ouro_export_count_lo(void);
const char *ouro_export_name_lo(int i);
ouro_v *ouro_export_value_lo(int i);
int ouro_export_count_el(void);
const char *ouro_export_name_el(int i);
ouro_v *ouro_export_value_el(int i);
int ouro_export_count_co(void);
const char *ouro_export_name_co(int i);
ouro_v *ouro_export_value_co(int i);
int ouro_export_count_fc(void);
const char *ouro_export_name_fc(int i);
ouro_v *ouro_export_value_fc(int i);
int ouro_export_count_pi(void);
const char *ouro_export_name_pi(int i);
ouro_v *ouro_export_value_pi(int i);
int ouro_export_count_pr(void);
const char *ouro_export_name_pr(int i);
ouro_v *ouro_export_value_pr(int i);
int ouro_export_count_pl(void);
const char *ouro_export_name_pl(int i);
ouro_v *ouro_export_value_pl(int i);
#else
int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);
#endif

static ouro_v *compile_to_cores_clos(ouro_env *env, ouro_v *fuel);
static ouro_v *compile_to_cores_src(ouro_env *env, ouro_v *src);
static ouro_v *compile_units_clos(ouro_env *env, ouro_v *fuel);
static ouro_v *compile_units_root(ouro_env *env, ouro_v *root);
static ouro_v *compile_units_files(ouro_env *env, ouro_v *files);
static ouro_v *compile_checked_units_clos(ouro_env *env, ouro_v *fuel);
static ouro_v *compile_checked_units_root(ouro_env *env, ouro_v *root);
static ouro_v *compile_checked_units_files(ouro_env *env, ouro_v *files);
static ouro_v *compile_source_units_clos(ouro_env *env, ouro_v *fuel);
static ouro_v *compile_source_units_root(ouro_env *env, ouro_v *root);
static ouro_v *compile_source_units_files(ouro_env *env, ouro_v *files);
static ouro_v *compile_to_cores_impl(ouro_v *fuel, ouro_v *src);
static ouro_v *compile_units_impl(ouro_v *fuel, ouro_v *root, ouro_v *files);
static ouro_v *compile_checked_units_impl(ouro_v *fuel, ouro_v *root, ouro_v *files,
					 int legacy_result);
void ouro_fe_reset_mir_pins(void);
static ouro_v *list_from_items(ouro_v **items, int n);
static ouro_v *perm_nil(void);
static ouro_v *perm_cons(ouro_v *head, ouro_v *tail);
static ouro_v *perm_pair(ouro_v *a, ouro_v *b);
static int collect_file_pairs(ouro_v *files, ouro_v ***out_items, int *out_n);
static ouro_v *pair_fst(ouro_v *p);
static ouro_v *pair_snd(ouro_v *p);

enum { FE_EXPORT_CACHE_SIZE = 128 };

typedef struct {
	const char *name;
	const char *(*table)(int);
	int count;
	int index;
} fe_export_index;

/* Requests use static names and the linked export tables are immutable.
   Keep indices across heap contexts and invoke the getter in each context. */
static fe_export_index fe_export_cache[FE_EXPORT_CACHE_SIZE];

static ouro_v *find_exp(const char *name, int n, const char *(*nm)(int),
			ouro_v *(*val)(int), int required)
{
	uintptr_t key = (uintptr_t)name;
	fe_export_index *cached = &fe_export_cache[
		((key >> 3) ^ (key >> 9)) & (FE_EXPORT_CACHE_SIZE - 1U)];
	int i;
	if (cached->name == name && cached->table == nm && cached->count == n) {
		i = cached->index;
	} else {
		for (i = 0; i < n; i++) {
			if (strcmp(nm(i), name) == 0) {
				*cached = (fe_export_index){name, nm, n, i};
				break;
			}
		}
	}
	if (i < n) {
		ouro_v *value = val(i);
		if (value != 0 || required)
			return value;
		fprintf(stderr, "ouro1: frontend glue invalid export %s\n", name);
		exit(2);
	}
	if (required) {
		fprintf(stderr, "ouro1: frontend glue missing export %s\n", name);
		exit(2);
	}
	return 0;
}

#ifdef OURO_FE_FLAT_EXPORTS
/* Fat native-build export table uses driver names for the elaborator. */
static const char *fe_flat_alias(const char *name)
{
	if (strcmp(name, "elaborate_surfaces") == 0)
		return "driver_elaborate_surfaces";
	if (strcmp(name, "elaborate_fuel") == 0)
		return "elaborate";
	return name;
}

#define FIND(mod, name)                                                        \
	find_exp(fe_flat_alias(name), ouro_export_count(), ouro_export_name,    \
		 ouro_export_value, 1)
#define FIND_OPTIONAL(mod, name)                                               \
	find_exp(fe_flat_alias(name), ouro_export_count(), ouro_export_name,    \
		 ouro_export_value, 0)
#else
#define FIND(mod, name)                                                        \
	find_exp((name), ouro_export_count_##mod(), ouro_export_name_##mod,    \
		 ouro_export_value_##mod, 1)
#define FIND_OPTIONAL(mod, name)                                               \
	find_exp((name), ouro_export_count_##mod(), ouro_export_name_##mod,    \
		 ouro_export_value_##mod, 0)
#endif




static ouro_v *cerr(unsigned long code, unsigned long det)
{
	ouro_v *err[2];
	ouro_v *box[1];
	err[0] = ouro_nat(code);
	err[1] = ouro_nat(det);
	box[0] = ouro_ctor(0, 2, err);
	return ouro_ctor(0, 1, box);
}

static ouro_v *g_closed_parse_file_visibility;
static ouro_v *g_last_intern;
static ouro_v *g_last_checked_program;

ouro_v *ouro_fe_last_intern(void)
{
	return g_last_intern;
}

ouro_v *ouro_fe_checked_dump(ouro_v *fuel)
{
	if (g_last_checked_program == 0)
		return cerr(49, 0);
	return ouro_apply(ouro_apply(FIND(pl, "checked_program_dump"), fuel),
			  g_last_checked_program);
}

ouro_v *ouro_fe_checked_type_globals(ouro_v *fuel)
{
	ouro_v *fn;
	if (g_last_checked_program == 0)
		return cerr(49, 0);
	fn = ouro_apply(FIND(pl, "checked_program_type_globals_indexed"),
			FIND(fc, "whnf_checked_indexed"));
	return ouro_apply(ouro_apply(fn, fuel), g_last_checked_program);
}

ouro_v *ouro_fe_checked_c_shims(void)
{
	if (g_last_checked_program == 0)
		return 0;
	return ouro_apply(FIND(pl, "checked_program_c_shims"), g_last_checked_program);
}

/* Each accepted body owns temporary inference and normalization allocations.
   Retain its typed preparation result before processing the next declaration. */
static ouro_v *emission_prepare_term(ouro_env *env, ouro_v *term)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		ouro_get(env, 3), ouro_get(env, 2)), ouro_get(env, 1)),
		ouro_get(env, 0)), term);
	return ouro_heap_context_leave(scope, result);
}

static ouro_v *emission_prepare_types(ouro_env *env, ouro_v *types)
{
	return ouro_clos(emission_prepare_term, ouro_cons(types, env));
}

static ouro_v *emission_prepare_environment(ouro_env *env, ouro_v *environment)
{
	return ouro_clos(emission_prepare_types, ouro_cons(environment, env));
}

static ouro_v *emission_prepare_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(emission_prepare_environment, ouro_cons(fuel, env));
}

ouro_v *ouro_fe_checked_emission_cores(ouro_v *fuel)
{
	ouro_v *fn;
	if (g_last_checked_program == 0)
		return cerr(49, 0);
	fn = ouro_apply(FIND(pl, "checked_program_emission_cores_indexed"),
			ouro_clos(emission_prepare_fuel,
				ouro_cons(FIND(pl, "erasure_prepare_closed_indexed"), 0)));
	fn = ouro_apply(fn, FIND(fc, "whnf_checked_indexed"));
	return ouro_apply(ouro_apply(fn, fuel), g_last_checked_program);
}

/* The C host retains the checked value but does not interpret its entries.
   Only the explicit legacy projection is returned to old C consumers. */
static ouro_v *publish_checked_result(ouro_v *result)
{
	g_last_checked_program = 0;
	if (result == 0 || result->n != 1 ||
	    (result->tag != 0 && result->tag != 1))
		return cerr(49, 0);
	if (result->tag == 1)
		g_last_checked_program = OURO_F(result, 0);
	return ouro_apply(FIND(pl, "checked_program_erase"), result);
}

static void line_col(const char *s, size_t pos, int *line, int *col)
{
	size_t i;
	*line = 1;
	*col = 1;
	for (i = 0; i < pos && s[i]; i++) {
		if (s[i] == '\n') {
			(*line)++;
			*col = 1;
		} else
			(*col)++;
	}
}

static void print_diag(const char *code, const char *path, const char *src,
		       size_t pos, const char *msg, const char *hint)
{
	int line, col;
	const char *use = path && path[0] ? path : "<input>";
	line_col(src ? src : "", pos, &line, &col);
	fprintf(stderr, "%s error %s:%d:%d %s\n", code, use, line, col, msg);
	fprintf(stderr, "hint: %s\n", hint);
}

static char *src_from_codes(ouro_v *xs, size_t *out_n)
{
	char *buf;
	int n;
	*out_n = 0;
	if (xs == 0)
		return 0;
	buf = (char *)malloc(1 << 20);
	if (buf == 0)
		return 0;
	n = codes_to_buf(xs, buf, 1 << 20);
	*out_n = (size_t)n;
	return buf;
}

/* Import and record failure source mapping. Expansion runs in packed
   stitch_* (pi then pr); these helpers print OURO-IMP-* / OURO-REC-* from
   CErr codes 81-84 and 71-77. */

static void imp_print_err(const char *path, ouro_v *src_codes,
			  unsigned long pos, unsigned long code)
{
	const char *cname = "OURO-IMP-001";
	const char *msg = "malformed import alias or local open";
	const char *hint =
		"Use: import \"path.ouro\" as Alias;  open Alias;  open Alias in expr;  Alias.name";
	char *src;
	size_t n = 0;
	switch ((int)code) {
	case 2:
		cname = "OURO-IMP-002";
		msg = "duplicate import alias";
		hint = "Each import alias name may appear only once in a file.";
		break;
	case 3:
		cname = "OURO-IMP-003";
		msg = "unknown import alias in open or qualifier";
		hint = "Open or qualify only an alias introduced by import \"path\" as Alias;";
		break;
	case 4:
		cname = "OURO-IMP-004";
		msg = "invalid import alias name";
		hint = "Choose a non-keyword identifier as the alias.";
		break;
	default:
		break;
	}
	src = src_from_codes(src_codes, &n);
	print_diag(cname, path && path[0] ? path : "<input>", src ? src : "",
		   (size_t)pos, msg, hint);
	free(src);
}

static void rec_print_err(const char *path, ouro_v *src_codes,
			  unsigned long code, unsigned long pos)
{
	const char *cname = "OURO-REC-001";
	const char *msg = "malformed record declaration";
	const char *hint = "Use: record Name : Type where field : Type; end;";
	char *src;
	size_t n = 0;
	switch ((int)code) {
	case 2:
		cname = "OURO-REC-002";
		msg = "duplicate record field";
		hint = "Each field name may appear only once in a record.";
		break;
	case 3:
		cname = "OURO-REC-003";
		msg = "record literal/update needs known expected record type";
		hint = "Give the enclosing definition a concrete record result type.";
		break;
	case 4:
		cname = "OURO-REC-004";
		msg = "missing required field in record literal";
		hint = "Assign every field declared by the record.";
		break;
	case 5:
		cname = "OURO-REC-005";
		msg = "unknown field in record literal";
		hint = "Remove the field or use the target record's exact field names.";
		break;
	case 6:
		cname = "OURO-REC-006";
		msg = "generated record constructor/accessor name collides";
		hint = "Rename the record, constructor or existing declaration.";
		break;
	case 7:
		cname = "OURO-REC-007";
		msg = "projection target is not a known record type or field is not known";
		hint = "Project only fields declared by the target record.";
		break;
	default:
		break;
	}
	src = src_from_codes(src_codes, &n);
	print_diag(cname, path && path[0] ? path : "<input>", src ? src : "",
		   (size_t)pos, msg, hint);
	free(src);
}

static int cerr_code(ouro_v *r)
{
	if (r == 0 || r->tag != 0 || r->n < 1 || OURO_F(r, 0) == 0 || OURO_F(r, 0)->n < 1)
		return -1;
	return (int)as_nat(OURO_F(OURO_F(r, 0), 0));
}

static int cerr_det(ouro_v *r)
{
	if (r == 0 || r->tag != 0 || r->n < 1 || OURO_F(r, 0) == 0 || OURO_F(r, 0)->n < 2)
		return 0;
	return (int)as_nat(OURO_F(OURO_F(r, 0), 1));
}

static int decl_name_from_intern(int id, char *buf, int cap)
{
	ouro_v *codes;
	if (g_last_intern == 0 || buf == 0 || cap <= 0)
		return 0;
	codes = ouro_apply(ouro_apply(FIND(pl, "name_of_id"), g_last_intern),
		ouro_nat((unsigned long)id));
	return codes_to_buf(codes, buf, cap);
}

static int print_prep_diag(const char *path, ouro_v *src, int code, int det)
{
	if (code == 11 || code == 12) {
		const char *kind = code == 11 ? "malformed token" : "lexer fuel exhausted";
		(void)src;
		fprintf(stderr, "%s: %s\n",
			path != 0 && path[0] != 0 ? path : "<input>", kind);
		return 1;
	}
	if (code >= 41 && code <= 49) {
		const char *msg = "declaration check failed";
		char namebuf[256];
		int have_name;
		(void)src;
		switch (code) {
		case 41: msg = "type mismatch"; break;
		case 42: msg = "declared type is not a type"; break;
		case 43: msg = "positivity"; break;
		case 44: msg = "checker fuel exhausted"; break;
		case 45: msg = "duplicate declaration"; break;
		case 46: msg = "malformed declaration/core plan"; break;
		case 47: msg = "unsupported checker operation"; break;
		case 48: msg = "checking cancelled"; break;
		case 49: msg = "internal checker failure"; break;
		}
		have_name = decl_name_from_intern(det, namebuf, (int)sizeof namebuf);
		fprintf(stderr, "%s: %s%s%s\n",
			path != 0 && path[0] != 0 ? path : "<input>", msg,
			have_name > 0 ? " in " : "", have_name > 0 ? namebuf : "");
		return 1;
	}
	if (code >= 81 && code <= 84) {
		imp_print_err(path, src, (unsigned long)det,
			      (unsigned long)(code - 80));
		return 1;
	}
	if (code >= 95 && code <= 98) {
		const char *msg = "invalid imported name mapping";
		char namebuf[256];
		int have_name = (code == 95 || code == 96) && det != 0
			? decl_name_from_intern(det, namebuf, (int)sizeof namebuf) : 0;
		switch (code) {
		case 95: msg = "name is not declared by the aliased module"; break;
		case 96: msg = "ambiguous module name"; break;
		case 97: msg = "module name resolution fuel exhausted"; break;
		case 98: msg = "invalid module name mapping"; break;
		}
		fprintf(stderr, "%s: %s%s%s\n",
			path != 0 && path[0] != 0 ? path : "<input>", msg,
			have_name > 0 ? " in " : "", have_name > 0 ? namebuf : "");
		return 1;
	}
	if (code >= 71 && code <= 77) {
		rec_print_err(path, src, (unsigned long)(code - 70),
			      (unsigned long)det);
		return 1;
	}
	if (code >= 61 && code <= 65) {
		const char *cname = "OURO-HOLE-001";
		const char *msg = "unresolved named hole";
		const char *hint =
			"Replace the named hole before release/profile checking.";
		switch (code) {
		case 62:
			cname = "OURO-DO-001";
			msg = "let! outside a do statement";
			hint = "Move let! under do or use an ordinary let.";
			break;
		case 63:
			cname = "OURO-PIPE-001";
			msg = "dangling or incomplete pipe";
			hint = "Write value |> function or remove/parenthesize the pipe.";
			break;
		case 64:
			cname = "OURO-LIST-001";
			msg = "list literal without known List A context";
			hint = "Add a declaration/ascription such as : List Nat.";
			break;
		case 65:
			cname = "OURO-LIST-002";
			msg = "invalid list literal syntax";
			hint = "Remove the extra comma or close the list.";
			break;
		default:
			break;
		}
		{
			char *s;
			size_t n = 0;
			s = src_from_codes(src, &n);
			print_diag(cname, path && path[0] ? path : "<input>",
				   s ? s : "", (size_t)det, msg, hint);
			free(s);
		}
		return 1;
	}
	return 0;
}


static void print_units_diag(ouro_v *files, ouro_v *r)
{
	int code;
	char pbuf[MAX_PATH];
	ouro_v **items = 0;
	ouro_v *file = 0;
	int nitems = 0;
	if (r != 0 && r->tag == 1)
		return;
	code = cerr_code(r);
	pbuf[0] = 0;
	/* Collected units are dependency-first and the requested root is last. */
	if (collect_file_pairs(files, &items, &nitems) && nitems > 0)
		file = items[nitems - 1];
	free(items);
	if (file != 0 && file->n >= 2)
		codes_to_buf(pair_fst(file), pbuf, MAX_PATH);
	(void)print_prep_diag(pbuf, file != 0 ? pair_snd(file) : 0,
	                      code, cerr_det(r));
}

/* Only the compiler-owned envelope selects declaration, unit and cause. The
   renderer never searches source or turns an absent span into byte zero. */
static void print_source_result_diag(ouro_v *source_result, ouro_v *raw_result, ouro_v *src)
{
	ouro_v *failure, *view, *diagnostic, *owner, *info, *unit, *cause, *phase;
	const char *phase_name;
	char pathbuf[MAX_PATH];
	char namebuf[256];
	int code = cerr_code(raw_result);
	unsigned long name;
	if (source_result == 0 || source_result->tag != 0 || source_result->n < 1)
		return;
	failure = OURO_F(source_result, source_result->n - 1);
	view = ouro_apply(FIND(pl, "source_failure_diagnostic"), failure);
	if (view == 0 || view->tag != 1 || view->n < 1) {
		(void)print_prep_diag("<input>", src, code, cerr_det(raw_result));
		return;
	}
	diagnostic = OURO_F(view, view->n - 1);
	owner = pair_fst(diagnostic);
	info = pair_snd(diagnostic);
	phase = pair_snd(owner);
	if (owner == 0 || info == 0 || phase == 0 || phase->tag > 4) {
		fprintf(stderr, "<input>: invalid compilation failure metadata; code=%d detail=%d\n",
			code, cerr_det(raw_result));
		return;
	}
	name = as_nat(pair_fst(owner));
	unit = pair_fst(info);
	cause = pair_snd(info);
	pathbuf[0] = 0;
	if (unit != 0 && unit->tag == 1 && unit->n >= 1) {
		ouro_v *path = ouro_apply(ouro_apply(FIND(pl, "str_of_id"), g_last_intern),
			OURO_F(unit, unit->n - 1));
		codes_to_buf(path, pathbuf, MAX_PATH);
	}
	if (pathbuf[0] == 0)
		snprintf(pathbuf, sizeof pathbuf, "<input>");
	if (name > INT_MAX || decl_name_from_intern((int)name, namebuf, (int)sizeof namebuf) <= 0)
		snprintf(namebuf, sizeof namebuf, "declaration#%lu", name);
	switch (phase->tag) {
	case 0: phase_name = "future-slot"; break;
	case 1: phase_name = "duplicate"; break;
	case 2: phase_name = "future-global"; break;
	case 3: phase_name = "surface"; break;
	case 4: phase_name = "core"; break;
	default: return;
	}
	if (cause != 0 && cause->tag == 1 && cause->n >= 1) {
		ouro_v *root = OURO_F(cause, cause->n - 1);
		if (root != 0 && root->tag == 0 && root->n >= 1) {
			ouro_v *list_refusal = OURO_F(root, root->n - 1);
			if (list_refusal != 0 && list_refusal->tag <= 3) {
				fprintf(stderr, "%s: OURO-LIST-001: list literal without known List A context in %s (%s)\n",
					pathbuf, namebuf, phase_name);
				fputs("  hint: Add a declaration/ascription such as : List Nat.\n", stderr);
				return;
			}
		}
		if (root != 0 && root->tag == 1 && root->n >= 1) {
			fprintf(stderr, "%s: OURO-HOLE-001: unresolved named hole in %s (%s)\n",
				pathbuf, namebuf, phase_name);
			fputs("  hint: Replace the named hole before release/profile checking.\n", stderr);
			return;
		}
	}
	if (phase->tag == 4 && code >= 41 && code <= 49 &&
	    name <= INT_MAX && (int)name == cerr_det(raw_result)) {
		(void)print_prep_diag(pathbuf, src, code, cerr_det(raw_result));
		return;
	}
	fprintf(stderr, "%s: compilation failed in %s (%s); code=%d detail=%d\n",
		pathbuf, namebuf, phase_name, code, cerr_det(raw_result));
}

static ouro_v *pair_fst(ouro_v *p)
{
	if (p == 0 || p->n < 2)
		return 0;
	return OURO_F(p, p->n - 2);
}

static ouro_v *pair_snd(ouro_v *p)
{
	if (p == 0 || p->n < 1)
		return 0;
	return OURO_F(p, p->n - 1);
}

static ouro_v *closed_parse_file_visibility(void)
{
	ouro_v *fn;
	if (g_closed_parse_file_visibility != 0)
		return g_closed_parse_file_visibility;
	ouro_static_begin();
	fn = FIND(pf, "closed_parse_file_visibility");
	fn = ouro_apply(fn, FIND(pa, "parse_a"));
	fn = ouro_apply(fn, FIND(pb, "parse_b"));
	g_closed_parse_file_visibility = fn;
	ouro_static_end();
	return fn;
}

static ouro_v *g_stitch_source;

static ouro_v *packed_stitch_source(void)
{
	ouro_v *fn;
	if (g_stitch_source != 0)
		return g_stitch_source;
	ouro_static_begin();
	fn = FIND(pl, "stitch_checked_source_with_origin");
	fn = ouro_apply(fn, FIND(lx, "lex_go_import"));
	fn = ouro_apply(fn, closed_parse_file_visibility());
	fn = ouro_apply(fn, FIND(ds, "desugar_file"));
	fn = ouro_apply(fn, FIND(lr, "rewrite_declarations"));
	fn = ouro_apply(fn, FIND(lo, "lower_expr_env2_with_cause"));
	fn = ouro_apply(fn, FIND(co, "compile_program_with_location"));
	fn = ouro_apply(fn, FIND(el, "elaborate_surfaces"));
	fn = ouro_apply(fn, FIND(el, "elaborate_fuel"));
	fn = ouro_apply(fn, FIND(fc, "check_module"));
	fn = ouro_apply(fn, FIND(pi, "preprocess_imports_reg"));
	fn = ouro_apply(fn, FIND(pr, "preprocess_records_reg"));
	g_stitch_source = fn;
	ouro_static_end();
	return fn;
}

static ouro_v *compile_to_cores_impl(ouro_v *fuel, ouro_v *src)
{
	ouro_v *pair;
	ouro_v *r;
	g_last_checked_program = 0;
	pair = ouro_apply(ouro_apply(packed_stitch_source(), fuel), src);
	r = ouro_apply(FIND(pl, "source_result_comp"), pair_fst(pair));
	g_last_intern = pair_snd(pair);
	print_source_result_diag(pair_fst(pair), r, src);
	return publish_checked_result(r);
}


static void fe_phase_done(const char *label);

static ouro_v *g_closed_preprocess_src;
static ouro_v *g_closed_parse_unit;
static ouro_v *g_closed_compile_from_decls;
static ouro_v *g_closed_compile_source_packet;

static ouro_v *closed_preprocess_src(void)
{
	ouro_v *fn;
	if (g_closed_preprocess_src != 0)
		return g_closed_preprocess_src;
	ouro_static_begin();
	fn = FIND(pl, "preprocess_src");
	fn = ouro_apply(fn, FIND(pi, "preprocess_imports_reg"));
	fn = ouro_apply(fn, FIND(pr, "preprocess_records_reg"));
	g_closed_preprocess_src = fn;
	ouro_static_end();
	return fn;
}

/* These non-reentrant seams share one lifetime protocol. Arguments and the
   caller's stack predate the mark; only the callee's temporaries are reclaimed.
   The selected clone operation preserves the data needed after the reset. */
static ouro_v *bounded_call(ouro_v *fn, int count, ouro_v **args,
			    ouro_v *(*clone_result)(ouro_v *))
{
	ouro_v *result;
	int i;
	ouro_heap_mark();
	for (i = 0; i < count; i++)
		fn = ouro_apply(fn, args[i]);
	result = clone_result(fn);
	ouro_heap_reset();
	return result;
}

/* Compile / elaborate / lower seams keep their result in the caller's
   allocator. A nested work context drops the callee graph without parking
   a permanent clone of every intermediate stage. */
static ouro_v *context_call(ouro_v *fn, int count, ouro_v **args)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	int i;
	for (i = 0; i < count; i++)
		fn = ouro_apply(fn, args[i]);
	return ouro_heap_context_leave(context, fn);
}

enum check_profile_phase {
	CHECK_PROFILE_LOWER,
	CHECK_PROFILE_PREFLIGHT,
	CHECK_PROFILE_FALLBACK,
	CHECK_PROFILE_PHASE_COUNT
};

struct check_profile_total {
	unsigned long long calls;
	unsigned long long allocated_bytes;
	double elapsed_s;
	int invalid_allocation;
	int invalid_clock;
};

static double (*g_check_profile_clock)(void);
static struct check_profile_total g_check_profile_totals[CHECK_PROFILE_PHASE_COUNT];
static unsigned long long g_check_profile_preflight_items;

/* Preflight totals include the bounded item calls and their result copies. */
static ouro_v *check_profile_context_call(enum check_profile_phase phase,
	ouro_v *fn, int count, ouro_v **args)
{
	struct check_profile_total *total = &g_check_profile_totals[phase];
	unsigned long long before_alloc, after_alloc, allocated_delta;
	double before, after, elapsed;
	ouro_v *result;
	if (g_check_profile_clock == 0)
		return context_call(fn, count, args);
	before_alloc = ouro_heap_total_alloc_bytes();
	before = g_check_profile_clock();
	result = context_call(fn, count, args);
	after = g_check_profile_clock();
	after_alloc = ouro_heap_total_alloc_bytes();
	total->calls++;
	if (after_alloc < before_alloc) {
		total->invalid_allocation = 1;
	} else {
		allocated_delta = after_alloc - before_alloc;
		if (allocated_delta > ULLONG_MAX - total->allocated_bytes)
			total->invalid_allocation = 1;
		else
			total->allocated_bytes += allocated_delta;
	}
	if (!isfinite(before) || !isfinite(after) || before < 0.0 || after < before) {
		total->invalid_clock = 1;
	} else {
		elapsed = total->elapsed_s + (after - before);
		if (!isfinite(elapsed))
			total->invalid_clock = 1;
		else
			total->elapsed_s = elapsed;
	}
	return result;
}

static void check_profile_report_totals(void)
{
	static const char *const names[] = {"lower-expr", "preflight", "fallback-elaborate"};
	int i;
	for (i = 0; i < CHECK_PROFILE_PHASE_COUNT; i++) {
		const struct check_profile_total *total = &g_check_profile_totals[i];
		fprintf(stderr, "n1-host: check-profile phase=%s calls=%llu", names[i], total->calls);
		if (i == CHECK_PROFILE_PREFLIGHT)
			fprintf(stderr, " items=%llu", g_check_profile_preflight_items);
		if (total->invalid_clock)
			fputs(" elapsed_s=unavailable", stderr);
		else
			fprintf(stderr, " elapsed_s=%.6f", total->elapsed_s);
		if (total->invalid_allocation)
			fputs(" allocated_bytes=unavailable\n", stderr);
		else
			fprintf(stderr, " allocated_bytes=%llu\n", total->allocated_bytes);
	}
}

static ouro_v *bounded_token_state(ouro_env *env, ouro_v *st)
{
	return bounded_call(ouro_get(env, 2), 3,
		(ouro_v *[]){ouro_get(env, 1), ouro_get(env, 0), st},
		ouro_clone_perm_with_stack_scratch);
}

static ouro_v *bounded_token_source(ouro_env *env, ouro_v *src)
{
	return ouro_clos(bounded_token_state, ouro_cons(src, env));
}

static ouro_v *bounded_token_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(bounded_token_source, ouro_cons(fuel, env));
}

/* Token/span callbacks borrow caller values, which may belong to an outer
   phase mark. Copy survivors into the restored caller allocator so an outer
   clone cannot share a permanent node that still points into that phase. */
static ouro_v *import_token_state(ouro_env *env, ouro_v *st)
{
	ouro_v *fn = ouro_get(env, 2);
	ouro_v *fuel = ouro_get(env, 1);
	ouro_v *src = ouro_get(env, 0);
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(fn, fuel), src), st);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *import_token_source(ouro_env *env, ouro_v *src)
{
	return ouro_clos(import_token_state, ouro_cons(src, env));
}

static ouro_v *import_token_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(import_token_source, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_settled3(ouro_v *raw)
{
	return ouro_clos(import_token_fuel, ouro_cons(raw, 0));
}

static ouro_v *mir_settled_first_argument(ouro_env *env, ouro_v *argument)
{
	return ouro_wrap_settled3(ouro_apply(ouro_get(env, 0), argument));
}

ouro_v *ouro_wrap_mir_check_instruction(ouro_v *raw)
{
	return ouro_clos(mir_settled_first_argument, ouro_cons(raw, 0));
}

/* Bootstrap-only: borrow caller inputs and retain the complete pure result. */
static ouro_v *module_pure_scope_argument(ouro_env *env, ouro_v *argument)
{
	unsigned long remaining;
	ouro_v *args[7], *result;
	ouro_heap_context *context;
	int count = 0;
	if (env == 0 || !ouro_nat_to_ulong(env->v, &remaining) ||
	    remaining < 1 || remaining > 7) {
		fputs("ouro_rt: invalid module pure scope curry state\n", stderr);
		exit(1);
	}
	if (remaining > 1)
		return ouro_clos(module_pure_scope_argument,
			ouro_cons(ouro_nat(remaining - 1), ouro_cons(argument, env->next)));
	args[count++] = argument;
	env = env->next;
	while (env != 0 && env->next != 0) {
		if (count == 7) {
			fputs("ouro_rt: invalid module pure scope arguments\n", stderr);
			exit(1);
		}
		args[count++] = env->v;
		env = env->next;
	}
	if (env == 0 || env->v == 0 || env->v->tag != OURO_TAG_CLOS ||
	    (count != 1 && count != 2 && count != 3 && count != 7)) {
		fputs("ouro_rt: invalid module pure scope callable\n", stderr);
		exit(1);
	}
	context = ouro_heap_context_enter();
	result = env->v;
	while (count > 0)
		result = ouro_apply(result, args[--count]);
	return ouro_heap_context_leave(context, result);
}

ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity)
{
	if (raw == 0 || raw->tag != OURO_TAG_CLOS ||
	    (arity != 1 && arity != 2 && arity != 3 && arity != 7)) {
		fputs("ouro_rt: invalid module pure scope arity or callable\n", stderr);
		exit(1);
	}
	return ouro_clos(module_pure_scope_argument,
		ouro_cons(ouro_nat(arity), ouro_cons(raw, 0)));
}

static ouro_v *module_pure_scope_prefix_last(ouro_env *env, ouro_v *argument)
{
	return ouro_wrap_module_pure_scope(ouro_apply(ouro_get(env, 0), argument), 7);
}

static ouro_v *module_pure_scope_prefix_second(ouro_env *env, ouro_v *argument)
{
	return ouro_clos(module_pure_scope_prefix_last,
		ouro_cons(ouro_apply(ouro_get(env, 0), argument), 0));
}

static ouro_v *module_pure_scope_prefix_third(ouro_env *env, ouro_v *argument)
{
	return ouro_clos(module_pure_scope_prefix_second,
		ouro_cons(ouro_apply(ouro_get(env, 0), argument), 0));
}

/* Leading lambdas capture caller values; only the saturated body needs a scope. */
ouro_v *ouro_wrap_module_maps_for_scope(ouro_v *raw)
{
	return ouro_clos(module_pure_scope_prefix_second, ouro_cons(raw, 0));
}

ouro_v *ouro_wrap_module_rewrite_decls_scope(ouro_v *raw)
{
	return ouro_clos(module_pure_scope_prefix_third, ouro_cons(raw, 0));
}

static ouro_v *module_pure_scope_body2_prefix_last(ouro_env *env, ouro_v *argument)
{
	return ouro_wrap_module_pure_scope(ouro_apply(ouro_get(env, 0), argument), 2);
}

static ouro_v *module_pure_scope_body2_prefix_second(ouro_env *env, ouro_v *argument)
{
	return ouro_clos(module_pure_scope_body2_prefix_last,
		ouro_cons(ouro_apply(ouro_get(env, 0), argument), 0));
}

static ouro_v *module_pure_scope_body2_prefix_third(ouro_env *env, ouro_v *argument)
{
	return ouro_clos(module_pure_scope_body2_prefix_second,
		ouro_cons(ouro_apply(ouro_get(env, 0), argument), 0));
}

ouro_v *ouro_wrap_module_scope_maps_scope(ouro_v *raw)
{
	return ouro_clos(module_pure_scope_body2_prefix_second, ouro_cons(raw, 0));
}

ouro_v *ouro_wrap_module_bare_ctors_scope(ouro_v *raw)
{
	return ouro_clos(module_pure_scope_body2_prefix_third, ouro_cons(raw, 0));
}

ouro_v *ouro_wrap_module_invalid_maps_scope(ouro_v *raw)
{
	return ouro_clos(module_pure_scope_body2_prefix_last, ouro_cons(raw, 0));
}

/* PE operations borrow immutable caller inputs. Only their complete
   canonical results cross this boundary; traversal and encoding temporaries
   must not accumulate over thousands of fixups and function records. */
static ouro_v *pe_scoped_argument(ouro_env *env, ouro_v *argument)
{
	unsigned long remaining;
	ouro_v *args[5];
	ouro_v *result;
	ouro_heap_context *context;
	int count = 0;
	if (!ouro_nat_to_ulong(ouro_get(env, 0), &remaining) || remaining < 1 || remaining > 5) {
		fputs("ouro_rt: invalid PE lifetime arity\n", stderr);
		exit(1);
	}
	if (remaining > 1)
		return ouro_clos(pe_scoped_argument,
			ouro_cons(ouro_nat(remaining - 1), ouro_cons(argument, env->next)));
	args[count++] = argument;
	env = env->next;
	while (env->next != 0) {
		if (count == 5) {
			fputs("ouro_rt: invalid PE lifetime arguments\n", stderr);
			exit(1);
		}
		args[count++] = env->v;
		env = env->next;
	}
	context = ouro_heap_context_enter();
	result = env->v;
	while (count > 0)
		result = ouro_apply(result, args[--count]);
	return ouro_heap_context_leave(context, result);
}

ouro_v *ouro_wrap_pe_word32(ouro_v *raw)
{
	return ouro_clos(pe_scoped_argument, ouro_cons(ouro_nat(1), ouro_cons(raw, 0)));
}

ouro_v *ouro_wrap_pe_apply_patches(ouro_v *raw)
{
	return ouro_clos(pe_scoped_argument, ouro_cons(ouro_nat(2), ouro_cons(raw, 0)));
}

/* The unary pure step uses the same complete-result context protocol. */
ouro_v *ouro_wrap_pe_patch_prefix_step(ouro_v *raw)
{
	return ouro_wrap_pe_word32(raw);
}

/* The thunk and its immutable captures predate the complete-result context. */
ouro_v *ouro_wrap_pe_run_fixup_step(ouro_v *raw)
{
	return ouro_wrap_pe_word32(raw);
}

ouro_v *ouro_wrap_pe_function_scan(ouro_v *raw)
{
	return ouro_clos(pe_scoped_argument, ouro_cons(ouro_nat(4), ouro_cons(raw, 0)));
}

ouro_v *ouro_wrap_pe_resolve_fixup_indexed(ouro_v *raw)
{
	return ouro_clos(pe_scoped_argument, ouro_cons(ouro_nat(5), ouro_cons(raw, 0)));
}

ouro_v *ouro_wrap_import_token(ouro_v *raw)
{
	return ouro_wrap_settled3(raw);
}

static ouro_v *closed_parse_unit(void)
{
	ouro_v *fn;
	if (g_closed_parse_unit != 0)
		return g_closed_parse_unit;
	ouro_static_begin();
	fn = FIND(pl, "parse_unit_indexed");
	fn = ouro_apply(fn, ouro_apply(FIND(lx, "lex_go_carried_with"),
		ouro_clos(bounded_token_fuel,
			ouro_cons(FIND(lx, "next_import_token_indexed"), 0))));
	fn = ouro_apply(fn, closed_parse_file_visibility());
	g_closed_parse_unit = fn;
	ouro_static_end();
	return fn;
}

/* The generated pipeline retains its own stack and phase values while lowering
   successive declarations. Reclaim only allocations made inside one lowerer
   call, after copying its data result into the caller heap. This seam is not
   recursively re-entered: recursion inside lower_expr_env2_with_cause stays
   in the generated lowerer. */
static ouro_v *bounded_lower_expr(ouro_env *env, ouro_v *expr)
{
	return check_profile_context_call(CHECK_PROFILE_LOWER, FIND(lo, "lower_expr_env2_with_cause"), 3,
		(ouro_v *[]){ouro_get(env, 1), ouro_get(env, 0), expr});
}

static ouro_v *bounded_lower_expected(ouro_env *env, ouro_v *expected)
{
	return ouro_clos(bounded_lower_expr, ouro_cons(expected, env));
}

static ouro_v *bounded_lower_environment(ouro_env *env, ouro_v *lower_env)
{
	return ouro_clos(bounded_lower_expected, ouro_cons(lower_env, env));
}

/* Borrow item inputs from the suspended traversal. Retain the complete
   phase/error or future/core result before releasing the work context. */
static ouro_v *bounded_compile_program_item_seen(ouro_env *env, ouro_v *seen)
{
	ouro_v *fn = ouro_get(env, 4);
	ouro_v *name = ouro_get(env, 3);
	ouro_v *surface = ouro_get(env, 2);
	ouro_v *future = ouro_get(env, 1);
	ouro_v *ctx = ouro_get(env, 0);
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		fn, name), surface), future), ctx), seen);
	result = ouro_heap_context_leave(context, result);
	if (g_check_profile_clock != 0)
		g_check_profile_preflight_items++;
	return result;
}

static ouro_v *bounded_compile_program_item_context(ouro_env *env, ouro_v *ctx)
{
	return ouro_clos(bounded_compile_program_item_seen, ouro_cons(ctx, env));
}

static ouro_v *bounded_compile_program_item_future(ouro_env *env, ouro_v *future)
{
	return ouro_clos(bounded_compile_program_item_context, ouro_cons(future, env));
}

static ouro_v *bounded_compile_program_item_surface(ouro_env *env, ouro_v *surface)
{
	return ouro_clos(bounded_compile_program_item_future, ouro_cons(surface, env));
}

static ouro_v *bounded_compile_program_item_name(ouro_env *env, ouro_v *name)
{
	return ouro_clos(bounded_compile_program_item_surface, ouro_cons(name, env));
}

static ouro_v *bounded_compile_program_item_scope(ouro_env *env, ouro_v *item)
{
	(void)env;
	return ouro_clos(bounded_compile_program_item_name, ouro_cons(item, 0));
}

/* Preflight compilation may return an error and fall back to elaboration.
   Neither attempt's temporary graph is needed by the next pipeline step.
   These generated callbacks do not invoke the bounded lower/check callbacks,
   so each work context belongs to one complete, non-reentrant pure pass. */
static ouro_v *bounded_compile_program(ouro_env *env, ouro_v *surfaces)
{
	ouro_v *indexed, *compile_item;
	(void)env;
	indexed = FIND_OPTIONAL(co, "compile_program_with_location_indexed_with");
	if (indexed != 0)
		return check_profile_context_call(CHECK_PROFILE_PREFLIGHT, indexed, 2,
			(ouro_v *[]){ouro_clos(bounded_compile_program_item_scope, 0), surfaces});
	/* Older export tables use the list-based walk with the same item scope. */
	compile_item = bounded_compile_program_item_scope(0, FIND(co, "compile_program_item_pure"));
	return check_profile_context_call(CHECK_PROFILE_PREFLIGHT,
		FIND(co, "compile_program_with_location_with"), 2,
		(ouro_v *[]){compile_item, surfaces});
}

static ouro_v *bounded_elaborate_surfaces(ouro_env *env, ouro_v *surfaces)
{
	return check_profile_context_call(CHECK_PROFILE_FALLBACK, FIND(el, "elaborate_surfaces"), 2,
		(ouro_v *[]){ouro_get(env, 0), surfaces});
}

static ouro_v *bounded_elaborate_surfaces_fuel(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(bounded_elaborate_surfaces, ouro_cons(fuel, 0));
}

static ouro_v *bounded_elaborate_context(ouro_env *env, ouro_v *names)
{
	return context_call(FIND(el, "elaborate_fuel"), 3,
		(ouro_v *[]){ouro_get(env, 1), ouro_get(env, 0), names});
}

static ouro_v *bounded_elaborate_surface(ouro_env *env, ouro_v *surface)
{
	return ouro_clos(bounded_elaborate_context, ouro_cons(surface, env));
}

static ouro_v *bounded_elaborate_fuel(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(bounded_elaborate_surface, ouro_cons(fuel, 0));
}

static ouro_v *g_check_profile_intern;
static unsigned long long g_check_profile_ordinal;

void ouro_fe_set_check_profile(double (*clock_now)(void))
{
	if (g_check_profile_clock != 0 && clock_now == 0)
		check_profile_report_totals();
	if (clock_now != 0) {
		memset(g_check_profile_totals, 0, sizeof(g_check_profile_totals));
		g_check_profile_preflight_items = 0;
	}
	g_check_profile_clock = clock_now;
	g_check_profile_intern = 0;
	g_check_profile_ordinal = 0;
}

static void check_profile_identity(ouro_v *mode, ouro_v *fuel, ouro_v *item)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *name = ouro_apply(FIND(fc, "file_item_name"), item);
	ouro_v *decimal = ouro_nat_decimal(name);
	ouro_v *spelling = g_check_profile_intern == 0 ? 0 :
		ouro_apply(ouro_apply(FIND(pl, "name_of_id"), g_check_profile_intern), name);
	const char *kind = mode != 0 && mode->n == 0 ?
		(mode->tag == 1 ? "source" : mode->tag == 0 ? "exact" : "unknown") : "unknown";
	fprintf(stderr, "n1-host: declaration-start ordinal=%llu mode=%s name_id=",
		g_check_profile_ordinal, kind);
	fputs(decimal->u.s, stderr);
	fputs(" name=", stderr);
	if (list_done(spelling))
		fputs("<unknown>", stderr);
	else
		ouro_write_codes(spelling, stderr);
	fputs(" fuel=", stderr);
	fputs(ouro_nat_decimal(fuel)->u.s, stderr);
	fputc('\n', stderr);
	(void)ouro_heap_context_leave(context, 0);
}

/* The generated checker owns coverage, ordering and judgments. Suspend the
   caller's growing signature while checking one declaration; copy only the
   result's new cells back, sharing caller-owned terms and accepted entries. */
static ouro_v *bounded_check_item(ouro_env *env, ouro_v *item)
{
	ouro_v *fn = ouro_get(env, 3);
	ouro_v *mode = ouro_get(env, 2);
	ouro_v *fuel = ouro_get(env, 1);
	ouro_v *sig = ouro_get(env, 0);
	ouro_heap_context *context;
	ouro_v *result;
	double before = -1.0, after;
	unsigned long long allocated = 0, total;
	if (g_check_profile_clock != 0) {
		g_check_profile_ordinal++;
		check_profile_identity(mode, fuel, item);
		allocated = ouro_heap_total_alloc_bytes();
		before = g_check_profile_clock();
	}
	context = ouro_heap_context_enter();
	result = ouro_apply(ouro_apply(ouro_apply(ouro_apply(fn, mode), fuel), sig), item);
	result = ouro_heap_context_leave(context, result);
	if (g_check_profile_clock != 0) {
		after = g_check_profile_clock();
		total = ouro_heap_total_alloc_bytes();
		fprintf(stderr, "n1-host: declaration-end ordinal=%llu result=%s elapsed_s=",
			g_check_profile_ordinal, result != 0 && result->tag == 0 && result->n == 1 ? "ok" :
			result != 0 && result->tag == 1 && result->n == 3 ? "refused" : "invalid-result");
		if (isfinite(before) && isfinite(after) && before >= 0.0 && after >= before)
			fprintf(stderr, "%.6f", after - before);
		else
			fputs("unavailable", stderr);
		if (total >= allocated)
			fprintf(stderr, " allocated_bytes=%llu\n", total - allocated);
		else
			fputs(" allocated_bytes=unavailable\n", stderr);
	}
	return result;
}

static ouro_v *bounded_check_signature(ouro_env *env, ouro_v *sig)
{
	return ouro_clos(bounded_check_item, ouro_cons(sig, env));
}

static ouro_v *bounded_check_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(bounded_check_signature, ouro_cons(fuel, env));
}

static ouro_v *bounded_check_mode(ouro_env *env, ouro_v *mode)
{
	return ouro_clos(bounded_check_fuel, ouro_cons(mode, env));
}

static ouro_v *bounded_check_declaration(void)
{
	return ouro_clos(bounded_check_mode,
		ouro_cons(FIND(fc, "check_indexed_declaration"), 0));
}

static ouro_v *closed_compile_decls_entry(const char *name, ouro_v **cache)
{
	ouro_v *fn;
	if (*cache != 0)
		return *cache;
	ouro_static_begin();
	fn = FIND(pl, name);
	fn = ouro_apply(fn, FIND(ds, "desugar_file"));
	fn = ouro_apply(fn, FIND(lr, "rewrite_declarations"));
	fn = ouro_apply(fn, ouro_clos(bounded_lower_environment, 0));
	fn = ouro_apply(fn, ouro_clos(bounded_compile_program, 0));
	fn = ouro_apply(fn, ouro_clos(bounded_elaborate_surfaces_fuel, 0));
	fn = ouro_apply(fn, ouro_clos(bounded_elaborate_fuel, 0));
	fn = ouro_apply(fn, ouro_apply(FIND(fc, "check_indexed_module_with"),
		bounded_check_declaration()));
	*cache = fn;
	ouro_static_end();
	return fn;
}

static ouro_v *closed_compile_from_decls(void)
{
	return closed_compile_decls_entry("compile_checked_from_decls_with_origin",
		&g_closed_compile_from_decls);
}

static ouro_v *closed_compile_source_packet(void)
{
	return closed_compile_decls_entry("compile_checked_from_decls_with_source_packet",
		&g_closed_compile_source_packet);
}

static ouro_v *perm_nil(void)
{
	ouro_v *v;
	ouro_perm_begin();
	v = ouro_ctor(0, 0, 0);
	ouro_perm_end();
	return v;
}

static ouro_v *perm_cons(ouro_v *head, ouro_v *tail)
{
	ouro_v *cell[2];
	ouro_v *v;
	cell[0] = head;
	cell[1] = tail;
	ouro_perm_begin();
	v = ouro_ctor(1, 2, cell);
	ouro_perm_end();
	return v;
}


static ouro_v *perm_pair(ouro_v *a, ouro_v *b)
{
	ouro_v *cell[2];
	ouro_v *v;
	cell[0] = a;
	cell[1] = b;
	ouro_perm_begin();
	v = ouro_ctor(0, 2, cell);
	ouro_perm_end();
	return v;
}

static int append_unit(ouro_v ***items, int *n, int *cap, ouro_v *u)
{
	ouro_v **next;
	if (*n == *cap) {
		int nc = *cap == 0 ? 32 : *cap * 2;
		next = (ouro_v **)realloc(*items, (unsigned long)nc * sizeof(ouro_v *));
		if (next == 0)
			return 0;
		*items = next;
		*cap = nc;
	}
	(*items)[*n] = u;
	(*n)++;
	return 1;
}



static int collect_file_pairs(ouro_v *files, ouro_v ***out_items, int *out_n)
{
	ouro_v **items = 0;
	int n = 0;
	int cap = 0;
	ouro_v *cur = files;
	while (!list_done(cur)) {
		if (cur->tag != 1 || cur->n < 2) {
			free(items);
			return 0;
		}
		if (!append_unit(&items, &n, &cap, OURO_F(cur, 0))) {
			free(items);
			return 0;
		}
		cur = OURO_F(cur, 1);
	}
	*out_items = items;
	*out_n = n;
	return 1;
}

static ouro_v *list_from_items(ouro_v **items, int n)
{
	ouro_v *xs = perm_nil();
	int i;
	for (i = n; i > 0;) {
		--i;
		xs = perm_cons(items[i], xs);
	}
	return xs;
}

static int unit_prepass_incremental(ouro_v *files, ouro_v **out_files,
				   ouro_v **out_alias_files, ouro_v **out_error)
{
	ouro_v *preprocess_src = closed_preprocess_src();
	ouro_v *reg = FIND(pl, "empty_rec_reg_pl");
	ouro_v **in_items = 0;
	ouro_v *prepared;
	ouro_v *alias_files;
	int n = 0;
	int i;
	if (!collect_file_pairs(files, &in_items, &n))
		return 0;
	/* All input fields are retained in this bank. Check every pair before
	   source diagnostics can take precedence over a malformed input list. */
	for (i = 0; i < n; i++) {
		ouro_v *f = in_items[i];
		if (f == 0 || f->n < 2) {
			free(in_items);
			return 0;
		}
	}
	prepared = perm_nil();
	alias_files = perm_nil();
	for (i = n - 1; i >= 0; i--) {
		ouro_v *path = pair_fst(in_items[i]);
		ouro_v *src = pair_snd(in_items[i]);
		ouro_v *r = ouro_apply(ouro_apply(ouro_apply(preprocess_src, path), reg), src);
		ouro_v *aliases;
		ouro_v *expanded;
		if (r == 0 || r->tag != 1 || r->n < 3) {
			if (r != 0 && r->tag == 0 && r->n >= 2)
				*out_error = ouro_clone_perm_deep(cerr(
					as_nat(pair_fst(r)), as_nat(pair_snd(r))));
			fe_phase_done("frontend-after-preprocess-unit-error");
			free(in_items);
			return 0;
		}
		/* Retain only the new phase nodes in the accumulated registry. */
		reg = ouro_clone_perm(OURO_F(r, r->n - 3));
		aliases = ouro_clone_perm(OURO_F(r, r->n - 2));
		expanded = ouro_clone_perm(OURO_F(r, r->n - 1));
		prepared = perm_cons(perm_pair(path, expanded), prepared);
		alias_files = perm_cons(perm_pair(path, aliases), alias_files);
		fe_phase_done("frontend-after-preprocess-unit");
	}
	free(in_items);
	*out_files = prepared;
	*out_alias_files = alias_files;
	return 1;
}

static int parse_units_incremental(ouro_v *fuel, ouro_v *files,
				   ouro_v **out_units, ouro_v **out_st,
				   ouro_v **out_error)
{
	ouro_v *parse_unit = closed_parse_unit();
	ouro_v *indexed = ouro_apply(FIND(lx, "lexer_intern_from"), FIND(lx, "empty_intern"));
	ouro_v **items = 0;
	int nitems = 0;
	int cap = 0;
	ouro_v *cur = files;
	int ok = 1;
	while (!list_done(cur)) {
		ouro_v *f;
		ouro_v *path;
		ouro_v *src;
		ouro_v *r;
		ouro_v *u;
		if (cur->tag != 1 || cur->n < 2) {
			ok = 0;
			break;
		}
		f = OURO_F(cur, 0);
		if (f == 0 || f->n < 2) {
			ok = 0;
			break;
		}
		path = pair_fst(f);
		src = pair_snd(f);
		r = ouro_apply(ouro_apply(ouro_apply(ouro_apply(parse_unit, fuel), indexed), path), src);
		if (r == 0 || r->tag != 0 || r->n < 2) {
			if (r != 0 && r->tag == 1 && r->n >= 3) {
				ouro_v *error = ouro_apply(ouro_apply(ouro_apply(
					FIND(pl, "frontend_parse_error"), list_from_items(&f, 1)),
					OURO_F(r, 0)), OURO_F(r, 1));
				*out_st = ouro_clone_perm_deep(OURO_F(r, 2));
				*out_error = ouro_clone_perm_deep(ouro_ctor(0, 1, &error));
			}
			fe_phase_done("frontend-after-parse-unit-error");
			ok = 0;
			break;
		}
		/* Parsed units and the lexer indexes share immutable nodes in this
		   bank. The resolver retains only the ordered intern state. */
		u = ouro_clone_perm(OURO_F(r, r->n - 2));
		indexed = ouro_clone_perm(OURO_F(r, r->n - 1));
		if (!append_unit(&items, &nitems, &cap, u)) {
			fe_phase_done("frontend-after-parse-unit-oom");
			ok = 0;
			break;
		}
		fe_phase_done("frontend-after-parse-unit");
		cur = OURO_F(cur, 1);
	}
	if (!ok) {
		free(items);
		return 0;
	}
	*out_units = list_from_items(items, nitems);
	*out_st = ouro_clone_perm(ouro_apply(FIND(lx, "lexer_intern_state"), indexed));
	free(items);
	return 1;
}

static void fe_phase_done(const char *label)
{
	ouro_heap_discard_phase();
	ouro_heap_report(label);
}

enum fe_units_result {
	FE_UNITS_RAW,
	FE_UNITS_LEGACY,
	FE_UNITS_ORIGIN,
	FE_UNITS_PACKET
};

static ouro_v *compile_units_source_impl(ouro_v *fuel, ouro_v *root, ouro_v *files,
					enum fe_units_result mode)
{
	ouro_v *files1 = 0;
	ouro_v *alias_files = 0;
	ouro_v *units = 0;
	ouro_v *scoped = 0;
	ouro_v *st = 0;
	ouro_v *pair = 0;
	ouro_v *root_id = 0;
	ouro_v *selected = 0;
	ouro_v *st2 = 0;
	ouro_v *resolved = 0;
	ouro_v *module_plan = 0;
	ouro_v *canonical_root = 0;
	ouro_v *ds = 0;
	ouro_v *fn = 0;
	ouro_v *r = 0;
	ouro_v *intern_fn = 0;
	ouro_v *resolve_fn = 0;
	ouro_v *source_result = 0;
	ouro_v *slots = 0;
	int packet_result = mode == FE_UNITS_PACKET;
	int with_state = packet_result || mode == FE_UNITS_ORIGIN;

	/* Survivors are ouro_clone_perm_deep (static share only). Mid-cone
	   discard_phase then drops the parse/preprocess bump. Host prims
	   from ouro_fast live in the static heap so eqNat survives. */
	ouro_fe_reset_mir_pins();
	ouro_perm_reset_bank(0);
	ouro_perm_reset_bank(1);
	ouro_perm_select(0);
	fuel = ouro_clone_perm_deep(fuel);
	root = ouro_clone_perm_deep(root);
	files = ouro_clone_perm_deep(files);
	g_last_intern = FIND(lx, "empty_intern");
	g_last_checked_program = 0;

	if (!unit_prepass_incremental(files, &files1, &alias_files, &r))
		goto failed;
	fe_phase_done("frontend-after-preprocess");

	ouro_perm_select(1);
	if (!parse_units_incremental(fuel, files1, &units, &st, &r)) {
		if (st != 0)
			g_last_intern = st;
		goto failed;
	}
	fe_phase_done("frontend-after-parse-units");

	intern_fn = FIND(lx, "intern_string");
	resolve_fn = FIND(ir, "resolve_imports_with_sources");
	ouro_perm_select(0);
	canonical_root = ouro_apply(ouro_apply(FIND(pl, "canon_path"), perm_nil()), root);
	pair = ouro_apply(ouro_apply(intern_fn, st), canonical_root);
	root_id = pair_fst(pair);
	st2 = pair_snd(pair);
	module_plan = ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		FIND(pl, packet_result ? "module_resolve_units_with_slots" : "module_resolve_units"),
		fuel), units), alias_files), root_id);
	module_plan = ouro_apply(module_plan, st2);
	if (module_plan == 0 || module_plan->tag != 0) {
		g_last_intern = ouro_clone_perm_deep(st2);
		if (module_plan != 0 && module_plan->tag == 1 && module_plan->n >= 2)
			r = ouro_clone_perm_deep(ouro_apply(ouro_apply(
			FIND(pl, "import_err"), pair_fst(module_plan)), pair_snd(module_plan)));
		fe_phase_done("frontend-after-module-resolve-error");
		goto failed;
	}
	if (with_state && module_plan->n != 1) {
		fputs(packet_result ? "ouro1: frontend glue invalid ModuleResolvedUnits\n"
			: "ouro1: frontend glue invalid resolved-unit result\n", stderr);
		exit(2);
	}
	pair = OURO_F(module_plan, 0);
	if (packet_result) {
		/* ModuleResolvedUnits has exactly the two erased nominal fields. */
		if (pair == 0 || pair->tag != 0 || pair->n != 2) {
			fputs("ouro1: frontend glue invalid ModuleResolvedUnits\n", stderr);
			exit(2);
		}
		slots = OURO_F(pair, 1);
		pair = OURO_F(pair, 0);
	}
	if (with_state && (pair == 0 || pair->tag != 0 || pair->n != 2)) {
		fputs("ouro1: frontend glue invalid resolved-unit pair\n", stderr);
		exit(2);
	}
	scoped = pair_fst(pair);
	st2 = pair_snd(pair);
	selected = ouro_apply(ouro_apply(FIND(pl, "unit_decl_names"), scoped), root_id);
	resolved = ouro_apply(ouro_apply(resolve_fn, scoped), root_id);
	if (resolved == 0 || resolved->tag != 0) {
		g_last_intern = ouro_clone_perm_deep(st2);
		if (resolved != 0 && resolved->tag == 1 && resolved->n >= 2)
			r = ouro_clone_perm_deep(ouro_apply(ouro_apply(
				FIND(pl, "import_err"), pair_fst(resolved)), pair_snd(resolved)));
		fe_phase_done("frontend-after-resolve-error");
		goto failed;
	}
	if (with_state) {
		pair = ouro_clone_perm_deep(perm_pair(
			perm_pair(OURO_F(resolved, 0), selected),
			packet_result ? perm_pair(st2, slots) : st2));
		ds = pair_fst(pair_fst(pair));
		selected = pair_snd(pair_fst(pair));
		st2 = pair_snd(pair);
		if (packet_result) {
			slots = pair_snd(st2);
			st2 = pair_fst(st2);
		}
	} else {
		ds = ouro_clone_perm_deep(OURO_F(resolved, 0));
		selected = ouro_clone_perm_deep(selected);
		st2 = ouro_clone_perm_deep(st2);
	}
	ouro_perm_reset_bank(1);
	fe_phase_done("frontend-after-resolve-imports");

	fn = packet_result ? ouro_apply(closed_compile_source_packet(), slots)
		: closed_compile_from_decls();
	ouro_perm_select(1);
	g_check_profile_intern = g_check_profile_clock == 0 ? 0 : st2;
	r = ouro_apply(ouro_apply(ouro_apply(ouro_apply(fn, selected), fuel), st2), ds);
	g_check_profile_intern = 0;
	/* Preserve shared references with the intern table before releasing bank 0. */
	if (packet_result)
		pair = ouro_clone_perm_deep(ouro_apply(ouro_apply(
			FIND(pl, "checked_source_packet_snapshot"), r), st2));
	else
		pair = ouro_clone_perm_deep(ouro_ctor(0, 2, (ouro_v *[]){r, st2}));
	source_result = pair_fst(pair);
	st2 = pair_snd(pair);
	fe_phase_done("frontend-after-check-decls");
	if (packet_result)
		source_result = ouro_apply(FIND(pl, "checked_source_packet_project"), source_result);
	if (mode != FE_UNITS_ORIGIN)
		r = ouro_apply(FIND(pl, "source_result_comp"), source_result);
	g_last_intern = st2;
	if (!with_state)
		print_source_result_diag(source_result, r, 0);
	if (with_state) {
		g_last_checked_program = 0;
		ouro_perm_reset_bank(0);
		fe_phase_done("frontend-after-compile-from-decls");
		return pair;
	}
	/* The ordinary Ouro getter retains numeric compatibility diagnostics.
	   The renderer above and direct/CLI callers keep the original error. */
	if (mode == FE_UNITS_LEGACY)
		r = ouro_apply(ouro_apply(ouro_apply(FIND(pl, "remap_comp_files_for"),
			ouro_ctor(1, 0, 0)), files1), r);
	/* Reuse bank-1 payloads; still retain new phase or old-bank cells. */
	r = ouro_clone_perm(r);
	ouro_perm_reset_bank(0);
	fe_phase_done("frontend-after-compile-from-decls");
	if (r != 0 && r->tag == 1 && r->n >= 1)
		g_last_checked_program = OURO_F(r, 0);
	return r;

failed:
	/* Retain the typed failure. Retrying an unbounded stitch on rejected input
	   can exhaust memory. */
	if (r == 0)
		r = cerr(FE_PARSE_ERR, 0);
	if (with_state) {
		if (r->tag != 0 || r->n != 1) {
			fputs("ouro1: frontend glue invalid compiler failure\n", stderr);
			exit(2);
		}
		source_result = ouro_apply(FIND(pl, "checked_source_packet_reject"), OURO_F(r, 0));
		if (!packet_result) {
			source_result = ouro_apply(FIND(pl, "checked_source_packet_project"), source_result);
			return ouro_clone_perm_deep(ouro_ctor(0, 2, (ouro_v *[]){source_result, g_last_intern}));
		}
		return ouro_clone_perm_deep(ouro_apply(ouro_apply(
			FIND(pl, "checked_source_packet_snapshot"), source_result), g_last_intern));
	}
	print_units_diag(files1 != 0 ? files1 : files, r);
	return r;
}

static ouro_v *compile_checked_units_impl(ouro_v *fuel, ouro_v *root, ouro_v *files,
					 int legacy_result)
{
	return compile_units_source_impl(fuel, root, files,
		legacy_result ? FE_UNITS_LEGACY : FE_UNITS_RAW);
}

static ouro_v *compile_units_impl(ouro_v *fuel, ouro_v *root, ouro_v *files)
{
	ouro_v *r = compile_checked_units_impl(fuel, root, files, 0);
	if (r != 0 && r->tag == 1)
		return publish_checked_result(r);
	return r;
}

static ouro_v *compile_to_cores_clos(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(compile_to_cores_src, ouro_cons(fuel, 0));
}

static ouro_v *compile_to_cores_src(ouro_env *env, ouro_v *src)
{
	return compile_to_cores_impl(ouro_get(env, 0), src);
}

static ouro_v *compile_units_clos(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(compile_units_root, ouro_cons(fuel, 0));
}

static ouro_v *compile_units_root(ouro_env *env, ouro_v *root)
{
	return ouro_clos(compile_units_files, ouro_cons(root, env));
}

static ouro_v *compile_units_files(ouro_env *env, ouro_v *files)
{
	return compile_units_impl(ouro_get(env, 1), ouro_get(env, 0), files);
}

static ouro_v *compile_checked_units_clos(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(compile_checked_units_root, ouro_cons(fuel, 0));
}

static ouro_v *compile_checked_units_root(ouro_env *env, ouro_v *root)
{
	return ouro_clos(compile_checked_units_files, ouro_cons(root, env));
}

static ouro_v *compile_checked_units_files(ouro_env *env, ouro_v *files)
{
	ouro_v *fuel = ouro_get(env, 1);
	ouro_v *root = ouro_get(env, 0);
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = compile_checked_units_impl(fuel, root, files, 1);
	ouro_v *survivors = ouro_ctor(0, 2, (ouro_v *[]){result, g_last_intern});
	ouro_fe_reset_mir_pins();
	survivors = ouro_heap_context_leave(context, survivors);
	result = OURO_F(survivors, 0);
	g_last_intern = OURO_F(survivors, 1);
	g_last_checked_program = result != 0 && result->tag == 1 && result->n >= 1
		? OURO_F(result, 0) : 0;
	return result;
}

ouro_v *ouro_fe_compile_checked_units(ouro_v *fuel, ouro_v *root, ouro_v *files)
{
	return compile_checked_units_impl(fuel, root, files, 0);
}

static ouro_v *compile_source_units_clos(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(compile_source_units_root, ouro_cons(fuel, env));
}

static ouro_v *compile_source_units_root(ouro_env *env, ouro_v *root)
{
	return ouro_clos(compile_source_units_files, ouro_cons(root, env));
}

static ouro_v *compile_source_units_files(ouro_env *env, ouro_v *files)
{
	enum fe_units_result mode = (enum fe_units_result)ouro_get(env, 2)->n;
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = compile_units_source_impl(ouro_get(env, 1), ouro_get(env, 0), files, mode);
	ouro_fe_reset_mir_pins();
	result = ouro_heap_context_leave(context, result);
	g_last_intern = pair_snd(result);
	g_last_checked_program = 0;
	return result;
}

ouro_v *ouro_wrap_compile_checked_units_with_origin(ouro_v *raw)
{
	(void)raw;
	return ouro_clos(compile_source_units_clos, ouro_cons(ouro_nat(FE_UNITS_ORIGIN), 0));
}

static ouro_v *g_compile_to_cores;
static ouro_v *g_compile_units;
static ouro_v *g_compile_checked_units;
static ouro_v *g_compile_source_packet_units;

ouro_v *ouro_fe_compile_checked_units_clos(void)
{
	if (g_compile_checked_units == 0) {
		ouro_static_begin();
		g_compile_checked_units = ouro_clos(compile_checked_units_clos, 0);
		ouro_static_end();
	}
	return g_compile_checked_units;
}

ouro_v *ouro_fe_compile_checked_units_with_source_packet_clos(void)
{
	if (g_compile_source_packet_units == 0) {
		ouro_static_begin();
		g_compile_source_packet_units = ouro_clos(compile_source_units_clos,
			ouro_cons(ouro_nat(FE_UNITS_PACKET), 0));
		ouro_static_end();
	}
	return g_compile_source_packet_units;
}

int ouro_export_count_fe(void)
{
	return 6;
}

const char *ouro_export_name_fe(int i)
{
	switch (i) {
	case 0:
		return "compile_units";
	case 1:
		return "compile_to_cores";
	case 2:
		return "lex_go";
	case 3:
		return "empty_intern";
	case 4:
		return "compile_checked_units";
	case 5:
		return "compile_checked_units_with_source_packet";
	default:
		return "";
	}
}

ouro_v *ouro_export_value_fe(int i)
{
	switch (i) {
	case 0:
		if (g_compile_units == 0)
			g_compile_units = ouro_clos(compile_units_clos, 0);
		return g_compile_units;
	case 1:
		if (g_compile_to_cores == 0)
			g_compile_to_cores = ouro_clos(compile_to_cores_clos, 0);
		return g_compile_to_cores;
	case 2:
		return FIND(lx, "lex_go");
	case 3:
		return FIND(lx, "empty_intern");
	case 4:
		return ouro_fe_compile_checked_units_clos();
	case 5:
		return ouro_fe_compile_checked_units_with_source_packet_clos();
	default:
		return 0;
	}
}

#ifdef OURO_FE_FLAT_EXPORTS
/* Ordinary generated programs keep stderr for diagnostics. Only the
   diagnostic N1 executable explicitly enables these progress messages. */
static int g_fe_progress;
static int g_fe_lowering_timings;
static unsigned long g_fe_prepare_depth;
static unsigned long long g_fe_prepare_spelling_calls;

void ouro_fe_set_progress(int enabled)
{
	g_fe_progress = enabled != 0;
}

void ouro_fe_set_lowering_timings(int enabled)
{
	g_fe_lowering_timings = enabled != 0;
}

static void fe_progress(const char *format, ...)
{
	va_list args;
	if (!g_fe_progress)
		return;
	va_start(args, format);
	vfprintf(stderr, format, args);
	va_end(args);
}

/* The generated source checker keeps the full module plan and typed result.
   Release each declaration's scratch before checking the next declaration;
   the outer three-argument scope retains the complete result in the caller. */
ouro_v *ouro_wrap_check_module(ouro_v *raw)
{
	(void)raw;
	return ouro_wrap_settled3(ouro_apply(FIND(fc, "check_indexed_module_with"),
		bounded_check_declaration()));
}

/* Retain the complete exact replay before releasing its work banks.
   Declaration scopes still borrow earlier entries; ordering, metadata,
   bodies and typed failures remain in Ouro. */
ouro_v *ouro_wrap_lower_recheck_program(ouro_v *raw)
{
	(void)raw;
	return ouro_wrap_module_pure_scope(ouro_apply(FIND(lo, "lower_recheck_program_with"),
		bounded_check_declaration()), 2);
}

/* Borrow immutable caller captures. Copy the complete typed result back
   before releasing normalization scratch; fuel, malformed-input checks
   and error mapping remain in the generated function. */
static ouro_v *lower_normalize_term(ouro_env *env, ouro_v *term)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(
		ouro_get(env, 2), ouro_get(env, 1)), ouro_get(env, 0)), term);

	return ouro_heap_context_leave(context, result);
}

static ouro_v *lower_normalize_sig(ouro_env *env, ouro_v *sig)
{
	return ouro_clos(lower_normalize_term, ouro_cons(sig, env));
}

static ouro_v *lower_normalize_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(lower_normalize_sig, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_lower_normalize(ouro_v *raw)
{
	return ouro_clos(lower_normalize_fuel, ouro_cons(raw, 0));
}

/* Borrow caller-owned inputs; retain the full Either before releasing the
   per-contract signature and primitive-environment scratch. */
static ouro_v *lower_make_contract_binding(ouro_env *env, ouro_v *binding)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_get(env, 4);
	int i;
	for (i = 3; i >= 0; i--)
		result = ouro_apply(result, ouro_get(env, i));
	result = ouro_apply(result, binding);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *lower_make_contract_typ(ouro_env *env, ouro_v *typ)
{
	return ouro_clos(lower_make_contract_binding, ouro_cons(typ, env));
}

static ouro_v *lower_make_contract_id(ouro_env *env, ouro_v *id)
{
	return ouro_clos(lower_make_contract_typ, ouro_cons(id, env));
}

static ouro_v *lower_make_contract_sig(ouro_env *env, ouro_v *sig)
{
	return ouro_clos(lower_make_contract_id, ouro_cons(sig, env));
}

static ouro_v *lower_make_contract_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(lower_make_contract_sig, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_lower_make_contract_indexed(ouro_v *raw)
{
	return ouro_clos(lower_make_contract_fuel, ouro_cons(raw, 0));
}

static void native_lower_progress(const char *phase)
{
	if (g_fe_lowering_timings)
		fe_progress("n1-host: lowering-phase=%s live=%llu total=%llu\n",
			phase, ouro_heap_live_bytes(), ouro_heap_total_alloc_bytes());
	ouro_heap_report(phase);
}

/* These pure callbacks have no host cache. Borrow immutable caller inputs
   and retain the complete index, Either or Bool before releasing scratch. */
static ouro_v *check_environment_entries(ouro_env *env, ouro_v *entries)
{
	ouro_v *result;
	if (g_fe_lowering_timings && g_fe_prepare_depth != 0)
		native_lower_progress("native-prepare-environment-start");
	result = ouro_apply(ouro_get(env, 0), entries);
	if (g_fe_lowering_timings && g_fe_prepare_depth != 0)
		native_lower_progress("native-prepare-environment-end");
	return result;
}

ouro_v *ouro_wrap_check_environment_from_entries(ouro_v *raw)
{
	return ouro_clos(check_environment_entries,
		ouro_cons(ouro_wrap_module_pure_scope(raw, 1), 0));
}

static ouro_v *managed_symbol_name(ouro_env *env, ouro_v *name)
{
	ouro_v *result;
	if (g_fe_lowering_timings && g_fe_prepare_depth != 0)
		native_lower_progress("native-prepare-symbol-start");
	result = ouro_apply(ouro_get(env, 0), name);
	if (g_fe_lowering_timings && g_fe_prepare_depth != 0)
		native_lower_progress("native-prepare-symbol-end");
	return result;
}

static ouro_v *managed_symbol_environment(ouro_env *env, ouro_v *environment)
{
	return ouro_clos(managed_symbol_name,
		ouro_cons(ouro_apply(ouro_get(env, 0), environment), 0));
}

static ouro_v *managed_symbol_program(ouro_env *env, ouro_v *program)
{
	return ouro_clos(managed_symbol_environment,
		ouro_cons(ouro_apply(ouro_get(env, 0), program), 0));
}

ouro_v *ouro_wrap_managed_source_symbol_using(ouro_v *raw)
{
	return ouro_clos(managed_symbol_program,
		ouro_cons(ouro_wrap_module_pure_scope(raw, 3), 0));
}

static ouro_v *managed_spelling_value(ouro_env *env, ouro_v *spelling)
{
	ouro_v *result = ouro_apply(ouro_get(env, 0), spelling);
	if (g_fe_lowering_timings && g_fe_prepare_depth != 0) {
		g_fe_prepare_spelling_calls++;
		/* Long intern tables must not produce a trace line for every comparison. */
		if ((g_fe_prepare_spelling_calls & (g_fe_prepare_spelling_calls - 1)) == 0)
			fe_progress("n1-host: native-prepare-spelling calls=%llu live=%llu total=%llu\n",
				g_fe_prepare_spelling_calls, ouro_heap_live_bytes(), ouro_heap_total_alloc_bytes());
	}
	return result;
}

static ouro_v *managed_spelling_requested(ouro_env *env, ouro_v *requested)
{
	return ouro_clos(managed_spelling_value,
		ouro_cons(ouro_apply(ouro_get(env, 0), requested), 0));
}

ouro_v *ouro_wrap_managed_source_spelling(ouro_v *raw)
{
	return ouro_clos(managed_spelling_requested,
		ouro_cons(ouro_wrap_module_pure_scope(raw, 2), 0));
}

/* The plan and raw-function builders only traverse immutable Core and return
   data. Keep their complete typed result; downstream managed/MIR/codegen
   wrappers cache permanent pointers and must remain outside these contexts. */
static ouro_v *managed_prepare_types(ouro_env *env, ouro_v *types)
{
	ouro_heap_context *context;
	ouro_v *result;
	int i;
	native_lower_progress("native-prepare-start");
	if (g_fe_prepare_depth == 0)
		g_fe_prepare_spelling_calls = 0;
	g_fe_prepare_depth++;
	context = ouro_heap_context_enter();
	result = ouro_get(env, 3);
	for (i = 2; i >= 0; i--)
		result = ouro_apply(result, ouro_get(env, i));
	result = ouro_apply(result, types);
	g_fe_prepare_depth--;
	native_lower_progress("native-prepare-return");
	result = ouro_heap_context_leave(context, result);
	native_lower_progress("native-prepare-end");
	return result;
}

static ouro_v *managed_prepare_program(ouro_env *env, ouro_v *program)
{
	return ouro_clos(managed_prepare_types, ouro_cons(program, env));
}

static ouro_v *managed_prepare_entry(ouro_env *env, ouro_v *entry)
{
	return ouro_clos(managed_prepare_program, ouro_cons(entry, env));
}

static ouro_v *managed_prepare_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(managed_prepare_entry, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_managed_prepare_rechecked(ouro_v *raw)
{
	return ouro_clos(managed_prepare_fuel, ouro_cons(raw, 0));
}

static ouro_v *lower_function_body(ouro_env *env, ouro_v *body)
{
	ouro_heap_context *context;
	ouro_v *result;
	int i;
	native_lower_progress("native-raw-start");
	context = ouro_heap_context_enter();
	result = ouro_get(env, 5);
	for (i = 4; i >= 0; i--)
		result = ouro_apply(result, ouro_get(env, i));
	result = ouro_apply(result, body);
	native_lower_progress("native-raw-return");
	result = ouro_heap_context_leave(context, result);
	native_lower_progress("native-raw-end");
	return result;
}

static ouro_v *lower_function_contract(ouro_env *env, ouro_v *contract)
{
	return ouro_clos(lower_function_body, ouro_cons(contract, env));
}

static ouro_v *lower_function_contracts(ouro_env *env, ouro_v *contracts)
{
	return ouro_clos(lower_function_contract, ouro_cons(contracts, env));
}

static ouro_v *lower_function_sig(ouro_env *env, ouro_v *sig)
{
	return ouro_clos(lower_function_contracts, ouro_cons(sig, env));
}

static ouro_v *lower_function_program(ouro_env *env, ouro_v *program)
{
	return ouro_clos(lower_function_sig, ouro_cons(program, env));
}

static ouro_v *lower_function_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(lower_function_program, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_lower_function_indexed(ouro_v *raw)
{
	return ouro_clos(lower_function_fuel, ouro_cons(raw, 0));
}

/* Trace the existing whole finish call without reclaiming its banks: mg_*
   deliberately retain compiler/fuel pointers until the existing cache fence. */
static ouro_v *managed_finish_raw(ouro_env *env, ouro_v *functions)
{
	ouro_v *result;
	native_lower_progress("native-finish-start");
	result = ouro_apply(ouro_apply(ouro_apply(ouro_get(env, 2),
		ouro_get(env, 1)), ouro_get(env, 0)), functions);
	native_lower_progress("native-finish-end");
	return result;
}

static ouro_v *managed_finish_plan(ouro_env *env, ouro_v *plan)
{
	return ouro_clos(managed_finish_raw, ouro_cons(plan, env));
}

static ouro_v *managed_finish_fuel(ouro_env *env, ouro_v *fuel)
{
	return ouro_clos(managed_finish_plan, ouro_cons(fuel, env));
}

ouro_v *ouro_wrap_managed_finish_plan(ouro_v *raw)
{
	return ouro_clos(managed_finish_fuel, ouro_cons(raw, 0));
}


static ouro_v *g_raw_managed_global;
static ouro_v *g_source_managed_compiler;
static ouro_v *g_perm_managed_compiler;
static ouro_v *g_source_managed_fuel;
static ouro_v *g_perm_managed_fuel;
static unsigned long g_mg_count;

static ouro_v *mg_state(ouro_env *env, ouro_v *state)
{
	ouro_v *r;
	ouro_v *st = ouro_clone_perm(state);

	g_mg_count++;
	if ((g_mg_count % 25UL) == 0UL)
		fe_progress("n1-host: global %lu live=%llu\n",
			g_mg_count, ouro_heap_live_bytes());
	ouro_heap_mark();
	r = ouro_apply(ouro_apply(ouro_apply(ouro_apply(g_raw_managed_global,
		ouro_get(env, 2)), ouro_get(env, 1)), ouro_get(env, 0)), st);
	r = ouro_clone_perm(r);
	ouro_heap_reset();
	return r;
}

static ouro_v *mg_id(ouro_env *env, ouro_v *id)
{
	return ouro_clos(mg_state, ouro_cons(ouro_clone_perm(id), env));
}

static ouro_v *mg_fuel(ouro_env *env, ouro_v *fuel)
{
	if (g_perm_managed_fuel == 0 || g_source_managed_fuel != fuel) {
		g_source_managed_fuel = fuel;
		g_perm_managed_fuel = ouro_clone_perm(fuel);
	}
	return ouro_clos(mg_id, ouro_cons(g_perm_managed_fuel, env));
}

static ouro_v *mg_compiler(ouro_env *env, ouro_v *compiler)
{
	(void)env;
	if (g_perm_managed_compiler == 0 || g_source_managed_compiler != compiler) {
		g_source_managed_compiler = compiler;
		g_perm_managed_compiler = ouro_clone_perm(compiler);
	}
	return ouro_clos(mg_fuel, ouro_cons(g_perm_managed_compiler, 0));
}

/* The raw Ouro function owns lowering; only its temporary arena is reclaimed. */
ouro_v *ouro_wrap_managed_global_function(ouro_v *raw)
{
	g_raw_managed_global = raw;
	g_mg_count = 0;
	return ouro_clos(mg_compiler, 0);
}

static ouro_v *mir_left_resource(void)
{
	ouro_v *err = ouro_ctor(0, 0, 0);

	return ouro_ctor(0, 1, &err);
}

static ouro_v *mir_right_unit(void)
{
	ouro_v *unit = ouro_ctor(0, 0, 0);

	return ouro_ctor(1, 1, &unit);
}

static int mir_either_ok(ouro_v *r, ouro_v **out)
{
	if (r == 0 || r->tag != 1 || r->n < 1) {
		if (out != 0)
			*out = r;
		return 0;
	}
	if (out != 0)
		*out = OURO_F(r, 0);
	return 1;
}

static ouro_v *mir_bounds_program(ouro_env *env, ouro_v *program)
{
	ouro_v *limits = ouro_get(env, 0);
	ouro_v *nodes;
	ouro_v *bytes;
	ouro_v *flow;
	ouro_v *r;
	ouro_v *left;

	if (limits == 0 || limits->n < 3 || program == 0 || program->n < 3)
		return mir_left_resource();
	nodes = OURO_F(limits, 0);
	bytes = OURO_F(limits, 1);
	flow = OURO_F(limits, 2);
	if (as_nat(nodes) > 16777216UL || as_nat(bytes) > 16777216UL
	    || as_nat(flow) > 16777216UL)
		return mir_left_resource();
	r = ouro_apply(ouro_apply(FIND(lo, "mir_count_functions"),
				 OURO_F(program, 0)), nodes);
	if (!mir_either_ok(r, &left))
		return r;
	r = ouro_apply(ouro_apply(FIND(lo, "mir_count_libraries"),
				 OURO_F(program, 2)), left);
	if (!mir_either_ok(r, &left))
		return r;
	r = ouro_apply(ouro_apply(FIND(lo, "mir_spend"), left),
		       OURO_F(program, 1));
	if (!mir_either_ok(r, &left))
		return r;
	r = ouro_apply(ouro_apply(FIND(lo, "mir_count_data"),
				 OURO_F(program, 1)), bytes);
	if (!mir_either_ok(r, &left))
		return r;
	return mir_right_unit();
}

static ouro_v *mir_bounds_limits(ouro_env *env, ouro_v *limits)
{
	(void)env;
	return ouro_clos(mir_bounds_program, ouro_cons(limits, 0));
}

ouro_v *ouro_wrap_mir_check_bounds(ouro_v *raw)
{
	(void)raw;
	return ouro_wrap_module_pure_scope(ouro_clos(mir_bounds_limits, 0), 2);
}

static unsigned long g_cf_count;

static ouro_v *g_source_cg_program;
static ouro_v *g_perm_cg_program;
static ouro_v *g_cgn_prog;
static int g_cgn_meta_ok;

typedef struct {
	unsigned long id;
	int ordinal;
} cgn_id_position;

typedef struct {
	unsigned long *ids;
	int count;
	int capacity;
	int available;
} cgn_extern_index;

/* The pinned program owns the indexes. They retain only numeric data. */
static cgn_id_position *g_cgn_function_positions;
static int g_cgn_function_count;
static int g_cgn_function_index_ready;
static cgn_extern_index g_cgn_externs;

static void cgn_release_extern_index(cgn_extern_index *index)
{
	free(index->ids);
	*index = (cgn_extern_index){ 0 };
}

static void cgn_reset_program_indexes(void)
{
	free(g_cgn_function_positions);
	g_cgn_function_positions = 0;
	g_cgn_function_count = 0;
	g_cgn_function_index_ready = 0;
	cgn_release_extern_index(&g_cgn_externs);
}

void ouro_fe_reset_mir_pins(void)
{
	g_source_managed_compiler = 0;
	g_perm_managed_compiler = 0;
	g_source_managed_fuel = 0;
	g_perm_managed_fuel = 0;
	g_source_cg_program = 0;
	g_perm_cg_program = 0;
	/* A later MIR program can reuse the address after an arena reset. */
	g_cgn_prog = 0;
	g_cgn_meta_ok = 0;
	cgn_reset_program_indexes();
}

/* The frontier thunk borrows the current reachability round's immutable
   captures. Keep its complete List Nat result in that caller before freeing
   the nested round banks; neither the round's fold nor its fuel is in C. */
static ouro_v *mir_reachable_ids(ouro_env *env, ouro_v *work)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result;
	(void)env;
	result = ouro_apply(work, ouro_ctor(0, 0, 0));
	return ouro_heap_context_leave(context, result);
}

ouro_v *ouro_wrap_mir_reachable(ouro_v *raw)
{
	(void)raw;
	return ouro_apply(FIND(lo, "mir_reachable_with"),
		ouro_clos(mir_reachable_ids, 0));
}

/* The Ouro callbacks retain phase order and exact typed results. A nested
   heap context releases one unit phase or complete flow round without
   freeing the thunk's borrowed captures. Copying the
   complete round together preserves sharing between its block facts. */
static ouro_v *mir_check_phase(ouro_env *env, ouro_v *work)
{
	return mir_reachable_ids(env, work);
}

/* Borrow the immutable caller inputs. Retain the complete typed result in
   that caller before releasing this function's nested work banks. */
static ouro_v *cf_function(ouro_env *env, ouro_v *function)
{
	ouro_heap_context *context;
	ouro_v *r;
	ouro_v *run_unit;
	ouro_v *check_flow;
	ouro_v *predecessors;

	g_cf_count++;
	if ((g_cf_count % 25UL) == 0UL)
		fe_progress("n1-host: checkfn %lu live=%llu\n",
			g_cf_count, ouro_heap_live_bytes());
	context = ouro_heap_context_enter();
	run_unit = ouro_clos(mir_check_phase, 0);
	predecessors = ouro_clos(mir_settled_first_argument,
		ouro_cons(FIND(lo, "mir_predecessor_declared"), 0));
	check_flow = ouro_apply(ouro_apply(ouro_apply(FIND(lo, "mir_check_declared_flow_with"),
		run_unit), run_unit), predecessors);
	r = ouro_apply(ouro_apply(FIND(lo, "mir_check_function_with"), run_unit), check_flow);
	r = ouro_apply(ouro_apply(ouro_apply(r, ouro_get(env, 1)), ouro_get(env, 0)), function);
	return ouro_heap_context_leave(context, r);
}

static ouro_v *cf_flow(ouro_env *env, ouro_v *flow)
{
	return ouro_clos(cf_function, ouro_cons(flow, env));
}

static ouro_v *cf_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(cf_flow, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_mir_check_function(ouro_v *raw)
{
	(void)raw;
	g_cf_count = 0;
	return ouro_clos(cf_program, 0);
}

static ouro_v *g_raw_prepare_step;
static unsigned long g_prep_count;

static int x64enc_dec_nat(ouro_v *v, unsigned long *out);
static int host_list_collect(ouro_v *list, ouro_v ***out, int *n, int *cons_list);

static int cgasm_grow(void **p, int *cap, int n, unsigned long elem);

static int cgp_walk_bytes(ouro_v *v, unsigned char *dst, unsigned long *off,
			  unsigned long limit, ouro_v ***stack, int *cap)
{
	int depth = 0;

	while (v != 0) {
		if (v->tag == 0 && v->n == 0)
			v = 0;
		else if (v->tag == OURO_TAG_BYTES) {
			unsigned long length;

			if (v->n < 0 || (v->n > 0 && v->u.s == 0))
				return -1;
			length = (unsigned long)v->n;
			if (length > limit - *off)
				return -1;
			if (dst != 0 && length != 0)
				memcpy(dst + *off, v->u.s, (size_t)length);
			*off += length;
			v = 0;
		} else if (v->tag == OURO_TAG_CAT && v->n == 2) {
			if (depth == *cap &&
			    (*cap > INT_MAX / 2 || (unsigned long)*cap > ULONG_MAX / 2 / sizeof **stack
			     || !cgasm_grow((void **)stack, cap, depth, sizeof **stack)))
				return -1;
			(*stack)[depth++] = OURO_F(v, 1);
			v = OURO_F(v, 0);
		} else if (v->tag == 1 && v->n == 2) {
			unsigned long byte;

			if (x64enc_dec_nat(OURO_F(v, 0), &byte) != 0 || byte > 255UL || *off == limit)
				return -1;
			if (dst != 0)
				dst[*off] = (unsigned char)byte;
			(*off)++;
			v = OURO_F(v, 1);
		} else {
			return -1;
		}
		if (v == 0 && depth > 0)
			v = (*stack)[--depth];
	}
	return 0;
}

static ouro_v *cgp_cat(ouro_v *a, ouro_v *b)
{
	ouro_v *cell[2];

	if (a == 0 || (a->tag == 0 && a->n == 0))
		return b == 0 ? ouro_ctor(0, 0, 0) : b;
	if (b == 0 || (b->tag == 0 && b->n == 0))
		return a;
	cell[0] = a;
	cell[1] = b;
	return ouro_ctor(OURO_TAG_CAT, 2, cell);
}

static ouro_v *cgp_concat_functions(ouro_v *completed)
{
	ouro_v **items = 0;
	ouro_v **stack = 0;
	unsigned char *buf = 0;
	ouro_v *cur = completed;
	ouro_v *result = 0;
	ouro_v *symbols = 0;
	ouro_v *fixups = 0;
	ouro_v *records = 0;
	ouro_v *frames = 0;
	ouro_v *fields[5];
	unsigned long nbytes = 0;
	unsigned long off = 0;
	int n = 0;
	int cap = 0;
	int stack_cap = 0;
	int i;

	while (cur != 0 && cur->tag == 1 && cur->n == 2) {
		if (cap < n + 1) {
			int nc = cap == 0 ? 64 : cap * 2;
			ouro_v **p = (ouro_v **)realloc(items,
				sizeof(ouro_v *) * (unsigned long)nc);

			if (p == 0)
				goto done;
			items = p;
			cap = nc;
		}
		items[n++] = OURO_F(cur, 0);
		cur = OURO_F(cur, 1);
	}
	if (cur != 0 && !(cur->tag == 0 && cur->n == 0))
		goto done;
	for (i = n - 1; i >= 0; i--) {
		if (items[i] == 0 || items[i]->n < 5
		    || cgp_walk_bytes(OURO_F(items[i], 0), 0, &nbytes, INT_MAX, &stack, &stack_cap) != 0)
			goto done;
	}
	if (nbytes > 0) {
		buf = (unsigned char *)malloc(nbytes);
		if (buf == 0)
			goto done;
	}
	symbols = ouro_ctor(0, 0, 0);
	fixups = ouro_ctor(0, 0, 0);
	records = ouro_ctor(0, 0, 0);
	frames = ouro_ctor(0, 0, 0);
	for (i = n - 1; i >= 0; i--) {
		if (cgp_walk_bytes(OURO_F(items[i], 0), buf, &off, nbytes, &stack, &stack_cap) != 0)
			goto done;
		symbols = cgp_cat(symbols, OURO_F(items[i], 1));
		fixups = cgp_cat(fixups, OURO_F(items[i], 2));
		records = cgp_cat(records, OURO_F(items[i], 3));
		frames = cgp_cat(frames, OURO_F(items[i], 4));
	}
	if (off != nbytes)
		goto done;
	fields[0] = ouro_packed(buf, nbytes);
	fields[1] = symbols;
	fields[2] = fixups;
	fields[3] = records;
	fields[4] = frames;
	fe_progress("n1-host: finish-c functions=%d bytes=%lu\n", n,
		nbytes);
	fflush(stderr);
	result = ouro_ctor(0, 5, fields);
done:
	free(items);
	free(buf);
	free(stack);
	return result;
}

static ouro_v *ps_state(ouro_env *env, ouro_v *state)
{
	ouro_v *r;

	g_prep_count++;
	if ((g_prep_count % 25UL) == 0UL) {
		fe_progress("n1-host: encode %lu live=%llu\n",
			g_prep_count, ouro_heap_live_bytes());
		fflush(stderr);
	}
	state = ouro_clone_perm(state);
	if (state != 0 && state->tag == 0 && state->n >= 4
	    && OURO_F(state, 1) != 0
	    && OURO_F(state, 1)->tag == 0 && OURO_F(state, 1)->n == 0) {
		ouro_v *encoded = cgp_concat_functions(OURO_F(state, 3));
		ouro_v *nil = ouro_ctor(0, 0, 0);
		ouro_v *one;
		ouro_v *fields[4];

		if (encoded == 0)
			return 0;
		one = ouro_ctor(1, 2, (ouro_v *[]){ encoded, nil });
		fields[0] = OURO_F(state, 0);
		fields[1] = nil;
		fields[2] = OURO_F(state, 2);
		fields[3] = one;
		state = ouro_ctor(0, 4, fields);
	}
	ouro_heap_mark();
	r = ouro_apply(ouro_apply(g_raw_prepare_step, ouro_get(env, 0)), state);
	r = ouro_clone_perm(r);
	ouro_heap_reset();
	return r;
}

static ouro_v *ps_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	if (g_perm_cg_program == 0 || g_source_cg_program != program) {
		cgn_reset_program_indexes();
		g_source_cg_program = program;
		g_perm_cg_program = ouro_clone_perm(program);
	}
	return ouro_clos(ps_state, ouro_cons(g_perm_cg_program, 0));
}

ouro_v *ouro_wrap_codegen_prepare_step(ouro_v *raw)
{
	g_raw_prepare_step = raw;
	g_prep_count = 0;
	return ouro_clos(ps_program, 0);
}

/* Host x64_encode. Constructor tags follow declaration order in
   compiler/native/x64.ouro. Unrecognized shapes apply the raw Ouro
   encoder so a missed tag cannot silently emit the wrong bytes. */
#define X64ENC_OK 0
#define X64ENC_ERR_BYTE 1
#define X64ENC_ERR_DISP 2
#define X64ENC_ERR_SIB 3
#define X64ENC_ERR_SHIFT 4
#define X64ENC_FALLBACK 5

typedef struct {
	unsigned char b[32];
	int n;
	int err;
	unsigned long err_nat;
	int err_width;
} x64enc_buf;

typedef struct {
	int tag;
	int width;
	int r0;
	int r1;
	int arith;
	int shift;
	int sign;
	int cond;
	int mem;
	int akind;
	int abase;
	int aindex;
	int ascale;
	int aback;
	unsigned long disp[4];
	unsigned long imm32[4];
	unsigned long imm64[8];
	unsigned long nat;
} x64enc_ins;

typedef struct {
	int x;
	int b;
	unsigned char tail[16];
	int tn;
} x64enc_addr;

static ouro_v *g_raw_x64_encode;
static unsigned long g_x64enc_count;
static unsigned long g_x64enc_fallback;

static int x64enc_dec_nat(ouro_v *v, unsigned long *out)
{
	unsigned long n = 0;

	if (v == 0)
		return -1;
	if (v->tag == OURO_TAG_NAT) {
		return ouro_nat_to_ulong(v, out) ? 0 : -1;
	}
	while (v != 0 && v->tag == 1 && v->n == 1) {
		n++;
		if (n > 16777216UL)
			return -1;
		v = OURO_F(v, 0);
	}
	if (v != 0 && (v->tag == OURO_TAG_NAT || v->tag == OURO_TAG_BIG_NAT)) {
		unsigned long tail;
		if (!ouro_nat_to_ulong(v, &tail) || tail > ULONG_MAX - n)
			return -1;
		*out = n + tail;
		return 0;
	}
	if (v != 0 && v->tag == 0 && v->n == 0) {
		*out = n;
		return 0;
	}
	return -1;
}

static int x64enc_dec_unit(ouro_v *v, int max_tag, int *out)
{
	if (v == 0 || v->tag < 0 || v->tag > max_tag || v->n != 0)
		return -1;
	*out = v->tag;
	return 0;
}

static int x64enc_dec_reg(ouro_v *v, int *out)
{
	return x64enc_dec_unit(v, 15, out);
}

static int x64enc_dec_word32(ouro_v *v, unsigned long b[4])
{
	if (v == 0 || v->tag != 0 || v->n != 4)
		return -1;
	if (x64enc_dec_nat(OURO_F(v, 0), &b[0]) != 0)
		return -1;
	if (x64enc_dec_nat(OURO_F(v, 1), &b[1]) != 0)
		return -1;
	if (x64enc_dec_nat(OURO_F(v, 2), &b[2]) != 0)
		return -1;
	return x64enc_dec_nat(OURO_F(v, 3), &b[3]);
}

static int x64enc_dec_word64(ouro_v *v, unsigned long b[8])
{
	if (v == 0 || v->tag != 0 || v->n != 2)
		return -1;
	if (x64enc_dec_word32(OURO_F(v, 0), b) != 0)
		return -1;
	return x64enc_dec_word32(OURO_F(v, 1), b + 4);
}

static int x64enc_dec_disp(ouro_v *v, unsigned long b[4], int *backward)
{
	if (v == 0 || (v->tag != 0 && v->tag != 1) || v->n != 1)
		return -1;
	*backward = v->tag;
	return x64enc_dec_word32(OURO_F(v, 0), b);
}

static int x64enc_dec_addr(ouro_v *v, int *kind, int *base, int *index,
			   int *scale, unsigned long db[4], int *backward)
{
	if (v == 0)
		return -1;
	if (v->tag == 0 && v->n == 2) {
		*kind = 0;
		*index = 0;
		*scale = 0;
		if (x64enc_dec_reg(OURO_F(v, 0), base) != 0)
			return -1;
		return x64enc_dec_disp(OURO_F(v, 1), db, backward);
	}
	if (v->tag == 1 && v->n == 4) {
		*kind = 1;
		if (x64enc_dec_reg(OURO_F(v, 0), base) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(v, 1), index) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(v, 2), 3, scale) != 0)
			return -1;
		return x64enc_dec_disp(OURO_F(v, 3), db, backward);
	}
	if (v->tag == 2 && v->n == 1) {
		*kind = 2;
		*base = 0;
		*index = 0;
		*scale = 0;
		return x64enc_dec_disp(OURO_F(v, 0), db, backward);
	}
	return -1;
}

static int x64enc_dec_operand(ouro_v *v, int *mem, int *reg, int *kind,
			      int *base, int *index, int *scale,
			      unsigned long db[4], int *backward)
{
	if (v == 0)
		return -1;
	if (v->tag == 0 && v->n == 1) {
		*mem = 0;
		return x64enc_dec_reg(OURO_F(v, 0), reg);
	}
	if (v->tag == 1 && v->n == 1) {
		*mem = 1;
		*reg = 0;
		return x64enc_dec_addr(OURO_F(v, 0), kind, base, index, scale,
				       db, backward);
	}
	return -1;
}

static int x64enc_dec_ins(ouro_v *ins, x64enc_ins *d)
{
	static const int arity[27] = {
		2, 2, 3, 3, 3, 2, 2, 2, 2, 2,
		4, 4, 3, 3, 1, 4, 3, 1, 1, 2,
		1, 1, 1, 1, 0, 0, 1
	};

	if (ins == 0 || ins->tag < 0 || ins->tag > 26)
		return -1;
	if (ins->n != arity[ins->tag])
		return -1;
	memset(d, 0, sizeof *d);
	d->tag = ins->tag;
	switch (ins->tag) {
	case 0:
		if (x64enc_dec_reg(OURO_F(ins, 0), &d->r0) != 0)
			return -1;
		return x64enc_dec_word32(OURO_F(ins, 1), d->imm32);
	case 1:
		if (x64enc_dec_reg(OURO_F(ins, 0), &d->r0) != 0)
			return -1;
		return x64enc_dec_word64(OURO_F(ins, 1), d->imm64);
	case 2:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 1), &d->r0) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 2), &d->r1);
	case 3:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 1), &d->r0) != 0)
			return -1;
		return x64enc_dec_addr(OURO_F(ins, 2), &d->akind, &d->abase,
				       &d->aindex, &d->ascale, d->disp,
				       &d->aback);
	case 4:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_addr(OURO_F(ins, 1), &d->akind, &d->abase,
				    &d->aindex, &d->ascale, d->disp,
				    &d->aback) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 2), &d->r0);
	case 5:
		if (x64enc_dec_reg(OURO_F(ins, 0), &d->r0) != 0)
			return -1;
		return x64enc_dec_addr(OURO_F(ins, 1), &d->akind, &d->abase,
				       &d->aindex, &d->ascale, d->disp,
				       &d->aback);
	case 6:
		if (x64enc_dec_addr(OURO_F(ins, 0), &d->akind, &d->abase,
				    &d->aindex, &d->ascale, d->disp,
				    &d->aback) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 1), &d->r0);
	case 7:
		if (x64enc_dec_reg(OURO_F(ins, 0), &d->r0) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 1), &d->r1);
	case 8:
		if (x64enc_dec_addr(OURO_F(ins, 0), &d->akind, &d->abase,
				    &d->aindex, &d->ascale, d->disp,
				    &d->aback) != 0)
			return -1;
		return x64enc_dec_nat(OURO_F(ins, 1), &d->nat);
	case 9:
		if (x64enc_dec_reg(OURO_F(ins, 0), &d->r0) != 0)
			return -1;
		return x64enc_dec_addr(OURO_F(ins, 1), &d->akind, &d->abase,
				       &d->aindex, &d->ascale, d->disp,
				       &d->aback);
	case 10:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(ins, 1), 5, &d->arith) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 2), &d->r0) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 3), &d->r1);
	case 11:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(ins, 1), 5, &d->arith) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 2), &d->r0) != 0)
			return -1;
		return x64enc_dec_word32(OURO_F(ins, 3), d->imm32);
	case 12:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 1), &d->r0) != 0)
			return -1;
		return x64enc_dec_operand(OURO_F(ins, 2), &d->mem, &d->r1,
					  &d->akind, &d->abase, &d->aindex,
					  &d->ascale, d->disp, &d->aback);
	case 13:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(ins, 1), 1, &d->sign) != 0)
			return -1;
		return x64enc_dec_operand(OURO_F(ins, 2), &d->mem, &d->r1,
					  &d->akind, &d->abase, &d->aindex,
					  &d->ascale, d->disp, &d->aback);
	case 14:
		return x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width);
	case 15:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(ins, 1), 2, &d->shift) != 0)
			return -1;
		if (x64enc_dec_reg(OURO_F(ins, 2), &d->r0) != 0)
			return -1;
		return x64enc_dec_nat(OURO_F(ins, 3), &d->nat);
	case 16:
		if (x64enc_dec_unit(OURO_F(ins, 0), 1, &d->width) != 0)
			return -1;
		if (x64enc_dec_unit(OURO_F(ins, 1), 2, &d->shift) != 0)
			return -1;
		return x64enc_dec_reg(OURO_F(ins, 2), &d->r0);
	case 17:
	case 18:
		return x64enc_dec_disp(OURO_F(ins, 0), d->disp, &d->aback);
	case 19:
		if (x64enc_dec_unit(OURO_F(ins, 0), 15, &d->cond) != 0)
			return -1;
		return x64enc_dec_disp(OURO_F(ins, 1), d->disp, &d->aback);
	case 20:
	case 21:
		return x64enc_dec_operand(OURO_F(ins, 0), &d->mem, &d->r1,
					  &d->akind, &d->abase, &d->aindex,
					  &d->ascale, d->disp, &d->aback);
	case 22:
	case 23:
		return x64enc_dec_reg(OURO_F(ins, 0), &d->r0);
	case 24:
	case 25:
		return 0;
	case 26:
		return x64enc_dec_addr(OURO_F(ins, 0), &d->akind, &d->abase,
				       &d->aindex, &d->ascale, d->disp,
				       &d->aback);
	default:
		return -1;
	}
}

static int x64enc_disp_fits(const unsigned long w[4], int backward)
{
	if (!backward)
		return w[3] < 128UL;
	return w[3] < 128UL
		|| (w[3] == 128UL && w[0] == 0 && w[1] == 0 && w[2] == 0);
}

static int x64enc_disp_zero(const unsigned long w[4])
{
	return w[0] == 0 && w[1] == 0 && w[2] == 0 && w[3] == 0;
}

static int x64enc_disp_small(const unsigned long w[4], int backward)
{
	unsigned long limit = backward ? 128UL : 127UL;

	return w[0] <= limit && w[1] == 0 && w[2] == 0 && w[3] == 0;
}

static int x64enc_disp_bytes(const unsigned long w[4], int backward,
			     unsigned long out[4], x64enc_buf *x)
{
	unsigned long carry = 1;
	int i;

	for (i = 0; i < 4; i++) {
		if (w[i] >= 256UL) {
			x->err = X64ENC_ERR_BYTE;
			x->err_nat = w[i];
			return -1;
		}
	}
	if (!x64enc_disp_fits(w, backward)) {
		x->err = X64ENC_ERR_DISP;
		return -1;
	}
	if (!backward) {
		for (i = 0; i < 4; i++)
			out[i] = w[i];
		return 0;
	}
	for (i = 0; i < 4; i++) {
		unsigned long value = (255UL - w[i]) + carry;

		if (value < 256UL) {
			out[i] = value;
			carry = 0;
		} else {
			out[i] = 0;
			carry = 1;
		}
	}
	return 0;
}

static void x64enc_put(x64enc_buf *x, unsigned long v)
{
	if (x->err)
		return;
	if (v >= 256UL) {
		x->err = X64ENC_ERR_BYTE;
		x->err_nat = v;
		return;
	}
	if (x->n >= 32) {
		x->err = X64ENC_FALLBACK;
		return;
	}
	x->b[x->n++] = (unsigned char)v;
}

static void x64enc_rex(x64enc_buf *x, int width64, int r, int idx, int base)
{
	int bits = (width64 ? 8 : 0) + 4 * r + 2 * idx + base;

	if (bits != 0)
		x64enc_put(x, 64UL + (unsigned long)bits);
}

static int x64enc_base_address(int reg_field, int base, int index_high,
			       const unsigned char *sib, int sib_n,
			       const unsigned long dw[4], int backward,
			       x64enc_addr *ae, x64enc_buf *x)
{
	unsigned long db[4];
	int base_low = base & 7;
	int mode;
	int rm;
	int i;
	int dn;

	if (x64enc_disp_bytes(dw, backward, db, x) != 0)
		return -1;
	if (x64enc_disp_zero(dw) && base_low != 5)
		mode = 0;
	else if (x64enc_disp_small(dw, backward))
		mode = 64;
	else
		mode = 128;
	rm = sib_n ? 4 : base_low;
	ae->x = index_high;
	ae->b = (base >> 3) & 1;
	ae->tn = 0;
	ae->tail[ae->tn++] = (unsigned char)(mode + 8 * reg_field + rm);
	for (i = 0; i < sib_n; i++)
		ae->tail[ae->tn++] = sib[i];
	dn = mode == 0 ? 0 : mode == 64 ? 1 : 4;
	for (i = 0; i < dn; i++)
		ae->tail[ae->tn++] = (unsigned char)db[i];
	return 0;
}

static int x64enc_address_bytes(int reg_field, int kind, int base, int index,
				int scale, const unsigned long dw[4],
				int backward, x64enc_addr *ae, x64enc_buf *x)
{
	unsigned char sib[1];

	if (kind == 0) {
		int sib_n = 0;

		if ((base & 7) == 4) {
			sib[0] = 36;
			sib_n = 1;
		}
		return x64enc_base_address(reg_field, base, 0, sib, sib_n, dw,
					   backward, ae, x);
	}
	if (kind == 1) {
		int scale_bits;

		if (index == 4) {
			x->err = X64ENC_ERR_SIB;
			return -1;
		}
		scale_bits = scale == 0 ? 0 : scale == 1 ? 64 :
			scale == 2 ? 128 : 192;
		sib[0] = (unsigned char)(scale_bits + 8 * (index & 7)
					 + (base & 7));
		return x64enc_base_address(reg_field, base, (index >> 3) & 1,
					   sib, 1, dw, backward, ae, x);
	}
	if (kind == 2) {
		unsigned long db[4];
		int i;

		if (x64enc_disp_bytes(dw, backward, db, x) != 0)
			return -1;
		ae->x = 0;
		ae->b = 0;
		ae->tn = 0;
		ae->tail[ae->tn++] = (unsigned char)(8 * reg_field + 5);
		for (i = 0; i < 4; i++)
			ae->tail[ae->tn++] = (unsigned char)db[i];
		return 0;
	}
	x->err = X64ENC_FALLBACK;
	return -1;
}

static int x64enc_operand_bytes(int reg_field, int mem, int reg, int kind,
				int base, int index, int scale,
				const unsigned long dw[4], int backward,
				x64enc_addr *ae, x64enc_buf *x)
{
	if (!mem) {
		ae->x = 0;
		ae->b = (reg >> 3) & 1;
		ae->tn = 1;
		ae->tail[0] = (unsigned char)(192 + 8 * reg_field + (reg & 7));
		return 0;
	}
	return x64enc_address_bytes(reg_field, kind, base, index, scale, dw,
				    backward, ae, x);
}

static void x64enc_modrm(x64enc_buf *x, int width64, const unsigned char *ops,
			 int nop, int reg_field, int reg_high, int mem, int reg,
			 int kind, int base, int index, int scale,
			 const unsigned long dw[4], int backward)
{
	x64enc_addr ae;
	int i;

	if (x64enc_operand_bytes(reg_field, mem, reg, kind, base, index, scale,
				 dw, backward, &ae, x) != 0)
		return;
	x64enc_rex(x, width64, reg_high, ae.x, ae.b);
	for (i = 0; i < nop; i++)
		x64enc_put(x, ops[i]);
	for (i = 0; i < ae.tn; i++)
		x64enc_put(x, ae.tail[i]);
}

static void x64enc_imm_move(x64enc_buf *x, int width64, int reg,
			    const unsigned long *imm, int nimm)
{
	int i;

	x64enc_rex(x, width64, 0, 0, (reg >> 3) & 1);
	x64enc_put(x, 184UL + (unsigned long)(reg & 7));
	for (i = 0; i < nimm; i++)
		x64enc_put(x, imm[i]);
}

static void x64enc_byte_store(x64enc_buf *x, const x64enc_ins *d)
{
	x64enc_addr ae;
	int i;
	int bits;

	if (x64enc_address_bytes(d->r0 & 7, d->akind, d->abase, d->aindex,
				 d->ascale, d->disp, d->aback, &ae, x) != 0)
		return;
	bits = 4 * ((d->r0 >> 3) & 1) + 2 * ae.x + ae.b;
	if (bits != 0)
		x64enc_put(x, 64UL + (unsigned long)bits);
	else if (d->r0 >= 4)
		x64enc_put(x, 64UL);
	x64enc_put(x, 136UL);
	for (i = 0; i < ae.tn; i++)
		x64enc_put(x, ae.tail[i]);
}

static void x64enc_rel(x64enc_buf *x, const unsigned char *ops, int nop,
		       const unsigned long dw[4], int backward)
{
	unsigned long db[4];
	int i;

	if (x64enc_disp_bytes(dw, backward, db, x) != 0)
		return;
	for (i = 0; i < nop; i++)
		x64enc_put(x, ops[i]);
	for (i = 0; i < 4; i++)
		x64enc_put(x, db[i]);
}

static void x64enc_emit(const x64enc_ins *d, x64enc_buf *x)
{
	unsigned char op[2];
	unsigned long z[4];
	int i;

	for (i = 0; i < 4; i++)
		z[i] = 0;
	switch (d->tag) {
	case 0:
		x64enc_imm_move(x, 0, d->r0, d->imm32, 4);
		return;
	case 1:
		x64enc_imm_move(x, 1, d->r0, d->imm64, 8);
		return;
	case 2:
		op[0] = 137;
		x64enc_modrm(x, d->width, op, 1, d->r1 & 7, (d->r1 >> 3) & 1, 0,
			     d->r0, 0, 0, 0, 0, z, 0);
		return;
	case 3:
		op[0] = 139;
		x64enc_modrm(x, d->width, op, 1, d->r0 & 7, (d->r0 >> 3) & 1, 1,
			     0, d->akind, d->abase, d->aindex, d->ascale,
			     d->disp, d->aback);
		return;
	case 4:
		op[0] = 137;
		x64enc_modrm(x, d->width, op, 1, d->r0 & 7, (d->r0 >> 3) & 1, 1,
			     0, d->akind, d->abase, d->aindex, d->ascale,
			     d->disp, d->aback);
		return;
	case 5:
		op[0] = 15;
		op[1] = 182;
		x64enc_modrm(x, 0, op, 2, d->r0 & 7, (d->r0 >> 3) & 1, 1, 0,
			     d->akind, d->abase, d->aindex, d->ascale, d->disp,
			     d->aback);
		return;
	case 6:
		x64enc_byte_store(x, d);
		return;
	case 7:
		op[0] = 99;
		x64enc_modrm(x, 1, op, 1, d->r0 & 7, (d->r0 >> 3) & 1, 0, d->r1,
			     0, 0, 0, 0, z, 0);
		return;
	case 8:
		op[0] = 246;
		x64enc_modrm(x, 0, op, 1, 0, 0, 1, 0, d->akind, d->abase,
			     d->aindex, d->ascale, d->disp, d->aback);
		x64enc_put(x, d->nat);
		return;
	case 9:
		op[0] = 141;
		x64enc_modrm(x, 1, op, 1, d->r0 & 7, (d->r0 >> 3) & 1, 1, 0,
			     d->akind, d->abase, d->aindex, d->ascale, d->disp,
			     d->aback);
		return;
	case 10:
		{
			static const int group[6] = { 0, 1, 4, 5, 6, 7 };

			op[0] = (unsigned char)(1 + 8 * group[d->arith]);
			x64enc_modrm(x, d->width, op, 1, d->r1 & 7,
				     (d->r1 >> 3) & 1, 0, d->r0, 0, 0, 0, 0, z,
				     0);
			return;
		}
	case 11:
		{
			static const int group[6] = { 0, 1, 4, 5, 6, 7 };
			int k;

			op[0] = 129;
			x64enc_modrm(x, d->width, op, 1, group[d->arith], 0, 0,
				     d->r0, 0, 0, 0, 0, z, 0);
			for (k = 0; k < 4; k++)
				x64enc_put(x, d->imm32[k]);
			return;
		}
	case 12:
		op[0] = 15;
		op[1] = 175;
		x64enc_modrm(x, d->width, op, 2, d->r0 & 7, (d->r0 >> 3) & 1,
			     d->mem, d->r1, d->akind, d->abase, d->aindex,
			     d->ascale, d->disp, d->aback);
		return;
	case 13:
		op[0] = 247;
		x64enc_modrm(x, d->width, op, 1, d->sign ? 7 : 6, 0, d->mem,
			     d->r1, d->akind, d->abase, d->aindex, d->ascale,
			     d->disp, d->aback);
		return;
	case 14:
		x64enc_rex(x, d->width, 0, 0, 0);
		x64enc_put(x, 153UL);
		return;
	case 15:
		{
			static const int group[3] = { 4, 5, 7 };
			unsigned long limit = d->width ? 64UL : 32UL;

			if (d->nat >= limit) {
				x->err = X64ENC_ERR_SHIFT;
				x->err_width = d->width;
				x->err_nat = d->nat;
				return;
			}
			if (d->nat == 1UL) {
				op[0] = 209;
				x64enc_modrm(x, d->width, op, 1, group[d->shift],
					     0, 0, d->r0, 0, 0, 0, 0, z, 0);
			} else {
				op[0] = 193;
				x64enc_modrm(x, d->width, op, 1, group[d->shift],
					     0, 0, d->r0, 0, 0, 0, 0, z, 0);
				x64enc_put(x, d->nat);
			}
			return;
		}
	case 16:
		{
			static const int group[3] = { 4, 5, 7 };

			op[0] = 211;
			x64enc_modrm(x, d->width, op, 1, group[d->shift], 0, 0,
				     d->r0, 0, 0, 0, 0, z, 0);
			return;
		}
	case 17:
		op[0] = 232;
		x64enc_rel(x, op, 1, d->disp, d->aback);
		return;
	case 18:
		op[0] = 233;
		x64enc_rel(x, op, 1, d->disp, d->aback);
		return;
	case 19:
		op[0] = 15;
		op[1] = (unsigned char)(128 + d->cond);
		x64enc_rel(x, op, 2, d->disp, d->aback);
		return;
	case 20:
		op[0] = 255;
		x64enc_modrm(x, 0, op, 1, 2, 0, d->mem, d->r1, d->akind,
			     d->abase, d->aindex, d->ascale, d->disp, d->aback);
		return;
	case 21:
		op[0] = 255;
		x64enc_modrm(x, 0, op, 1, 4, 0, d->mem, d->r1, d->akind,
			     d->abase, d->aindex, d->ascale, d->disp, d->aback);
		return;
	case 22:
		x64enc_rex(x, 0, 0, 0, (d->r0 >> 3) & 1);
		x64enc_put(x, 80UL + (unsigned long)(d->r0 & 7));
		return;
	case 23:
		x64enc_rex(x, 0, 0, 0, (d->r0 >> 3) & 1);
		x64enc_put(x, 88UL + (unsigned long)(d->r0 & 7));
		return;
	case 24:
		x64enc_put(x, 195UL);
		return;
	case 25:
		x64enc_put(x, 15UL);
		x64enc_put(x, 11UL);
		return;
	case 26:
		op[0] = 255;
		x64enc_modrm(x, 1, op, 1, 4, 0, 1, 0, d->akind, d->abase,
			     d->aindex, d->ascale, d->disp, d->aback);
		return;
	default:
		x->err = X64ENC_FALLBACK;
		return;
	}
}

static ouro_v *x64enc_to_ouro(const x64enc_buf *x)
{
	ouro_v *payload;
	ouro_v *fields[2];

	if (x->err == X64ENC_OK) {
		/* Packed codes: length/append are C prims and stay O(1). */
		payload = ouro_packed(x->b, (unsigned long)x->n);
		return ouro_ctor(1, 1, &payload);
	}
	if (x->err == X64ENC_ERR_BYTE) {
		fields[0] = ouro_nat(x->err_nat);
		payload = ouro_ctor(0, 1, fields);
	} else if (x->err == X64ENC_ERR_DISP) {
		payload = ouro_ctor(1, 0, 0);
	} else if (x->err == X64ENC_ERR_SIB) {
		payload = ouro_ctor(2, 0, 0);
	} else if (x->err == X64ENC_ERR_SHIFT) {
		fields[0] = ouro_ctor(x->err_width, 0, 0);
		fields[1] = ouro_nat(x->err_nat);
		payload = ouro_ctor(3, 2, fields);
	} else {
		return 0;
	}
	return ouro_ctor(0, 1, &payload);
}

static ouro_v *x64enc_apply(ouro_env *env, ouro_v *instruction)
{
	x64enc_ins decoded;
	x64enc_buf encoded;
	ouro_v *result;

	(void)env;
	g_x64enc_count++;
	if ((g_x64enc_count % 10000UL) == 0UL)
		fe_progress("n1-host: x64enc %lu\n", g_x64enc_count);
	memset(&encoded, 0, sizeof encoded);
	if (x64enc_dec_ins(instruction, &decoded) != 0) {
		g_x64enc_fallback++;
		return ouro_apply(g_raw_x64_encode, instruction);
	}
	x64enc_emit(&decoded, &encoded);
	result = x64enc_to_ouro(&encoded);
	if (result == 0) {
		g_x64enc_fallback++;
		return ouro_apply(g_raw_x64_encode, instruction);
	}
	return result;
}

ouro_v *ouro_wrap_x64_encode(ouro_v *raw)
{
	g_raw_x64_encode = raw;
	g_x64enc_count = 0;
	g_x64enc_fallback = 0;
	return ouro_clos(x64enc_apply, 0);
}

/* Host codegen_assemble. Tags follow declaration order in
   codegen_model.ouro / pe_model.ouro. Unrecognized atom or list
   shapes apply the raw Ouro assembler. */
#define CGASM_OK 0
#define CGASM_FALLBACK 1
#define CGASM_FAIL 2
#define CGASM_MAX_INS 32
#define PE_MAX_RVA 2147483647UL
#define PE_SECTION_ALIGN 4096UL

typedef struct {
	int tag;
	int n;
	int cond;
	int imported;
	int lab_kind;
	unsigned long lab[3];
	unsigned long id;
	unsigned long site;
	unsigned long off;
} cgasm_atom;

typedef struct {
	int kind;
	unsigned long ids[3];
	unsigned long off;
} cgasm_lab;

static ouro_v *g_raw_codegen_assemble;
static unsigned long g_asm_count;
static unsigned long g_asm_fallback;

static const int cgasm_arity[8] = { 1, 1, 1, 2, 1, 1, 2, 2 };

static ouro_v *cgasm_left(int tag, ouro_v *field, int has_field)
{
	ouro_v *err;

	err = has_field ? ouro_ctor(tag, 1, &field) : ouro_ctor(tag, 0, 0);
	return ouro_ctor(0, 1, &err);
}

static ouro_v *cgasm_enc_err(const x64enc_buf *x)
{
	ouro_v *fields[2];
	ouro_v *payload;

	if (x->err == X64ENC_ERR_BYTE) {
		fields[0] = ouro_nat(x->err_nat);
		payload = ouro_ctor(0, 1, fields);
	} else if (x->err == X64ENC_ERR_DISP) {
		payload = ouro_ctor(1, 0, 0);
	} else if (x->err == X64ENC_ERR_SIB) {
		payload = ouro_ctor(2, 0, 0);
	} else if (x->err == X64ENC_ERR_SHIFT) {
		fields[0] = ouro_ctor(x->err_width, 0, 0);
		fields[1] = ouro_nat(x->err_nat);
		payload = ouro_ctor(3, 2, fields);
	} else {
		return 0;
	}
	return cgasm_left(1, payload, 1);
}

static int cgasm_run_enc(x64enc_ins *d, x64enc_buf *x)
{
	memset(x, 0, sizeof *x);
	x64enc_emit(d, x);
	if (x->err == X64ENC_OK)
		return CGASM_OK;
	if (x->err == X64ENC_FALLBACK)
		return CGASM_FALLBACK;
	return CGASM_FAIL;
}

static int cgasm_enc_ins(ouro_v *ins, x64enc_buf *x)
{
	x64enc_ins d;

	if (x64enc_dec_ins(ins, &d) != 0)
		return CGASM_FALLBACK;
	return cgasm_run_enc(&d, x);
}

static int cgasm_enc_rel(int tag, int cond, const unsigned long disp[4],
			 int back, x64enc_buf *x)
{
	x64enc_ins d;

	memset(&d, 0, sizeof d);
	d.tag = tag;
	d.cond = cond;
	d.disp[0] = disp[0];
	d.disp[1] = disp[1];
	d.disp[2] = disp[2];
	d.disp[3] = disp[3];
	d.aback = back;
	return cgasm_run_enc(&d, x);
}

static int cgasm_enc_rip(int tag, int width, int reg, x64enc_buf *x)
{
	x64enc_ins d;

	memset(&d, 0, sizeof d);
	d.tag = tag;
	d.width = width;
	d.r0 = reg;
	d.mem = 1;
	d.akind = 2;
	return cgasm_run_enc(&d, x);
}

static int cgasm_dec_label(ouro_v *v, int *kind, unsigned long ids[3])
{
	ids[0] = ids[1] = ids[2] = 0;
	if (v == 0)
		return -1;
	if (v->tag == 0 && v->n == 1) {
		*kind = 0;
		return x64enc_dec_nat(OURO_F(v, 0), &ids[0]);
	}
	if (v->tag == 1 && v->n == 3) {
		*kind = 1;
		if (x64enc_dec_nat(OURO_F(v, 0), &ids[0]) != 0)
			return -1;
		if (x64enc_dec_nat(OURO_F(v, 1), &ids[1]) != 0)
			return -1;
		return x64enc_dec_nat(OURO_F(v, 2), &ids[2]);
	}
	return -1;
}

static int cgasm_read_atom(ouro_v *atom, cgasm_atom *a)
{
	memset(a, 0, sizeof *a);
	if (atom == 0 || atom->tag < 0 || atom->tag > 7)
		return CGASM_FALLBACK;
	if (atom->n != cgasm_arity[atom->tag])
		return CGASM_FALLBACK;
	a->tag = atom->tag;
	switch (atom->tag) {
	case 0:
		return CGASM_OK;
	case 1:
	case 2:
		return cgasm_dec_label(OURO_F(atom, 0), &a->lab_kind, a->lab) == 0
			? CGASM_OK : CGASM_FALLBACK;
	case 3:
		if (x64enc_dec_unit(OURO_F(atom, 0), 15, &a->cond) != 0)
			return CGASM_FALLBACK;
		return cgasm_dec_label(OURO_F(atom, 1), &a->lab_kind, a->lab) == 0
			? CGASM_OK : CGASM_FALLBACK;
	case 4:
	case 5:
		return x64enc_dec_nat(OURO_F(atom, 0), &a->id) == 0
			? CGASM_OK : CGASM_FALLBACK;
	case 6:
		if (x64enc_dec_nat(OURO_F(atom, 0), &a->id) != 0)
			return CGASM_FALLBACK;
		/* std/types.ouro: True tag 0, False tag 1. */
		if (OURO_F(atom, 1) == 0 || OURO_F(atom, 1)->n != 0)
			return CGASM_FALLBACK;
		if (OURO_F(atom, 1)->tag == 0)
			a->imported = 1;
		else if (OURO_F(atom, 1)->tag == 1)
			a->imported = 0;
		else
			return CGASM_FALLBACK;
		return CGASM_OK;
	case 7:
		if (x64enc_dec_nat(OURO_F(atom, 0), &a->id) != 0)
			return CGASM_FALLBACK;
		return x64enc_dec_nat(OURO_F(atom, 1), &a->site) == 0
			? CGASM_OK : CGASM_FALLBACK;
	default:
		return CGASM_FALLBACK;
	}
}

static int cgasm_measure_atom(ouro_v *atom, const cgasm_atom *a, x64enc_buf *x)
{
	static const unsigned long z[4] = { 0, 0, 0, 0 };

	memset(x, 0, sizeof *x);
	switch (a->tag) {
	case 0:
		return cgasm_enc_ins(OURO_F(atom, 0), x);
	case 1:
	case 7:
		return CGASM_OK;
	case 2:
		return cgasm_enc_rel(18, 0, z, 0, x);
	case 3:
		return cgasm_enc_rel(19, a->cond, z, 0, x);
	case 4:
		return cgasm_enc_rel(17, 0, z, 0, x);
	case 5:
		return cgasm_enc_rip(20, 0, 0, x);
	case 6:
		return a->imported ? cgasm_enc_rip(3, 1, 0, x)
				  : cgasm_enc_rip(9, 0, 0, x);
	default:
		return CGASM_FALLBACK;
	}
}

static void cgasm_relative(unsigned long target, unsigned long origin,
			   unsigned long disp[4], int *backward)
{
	unsigned long d;

	if (origin <= target) {
		d = target - origin;
		*backward = 0;
	} else {
		d = origin - target;
		*backward = 1;
	}
	disp[0] = d & 255UL;
	disp[1] = (d >> 8) & 255UL;
	disp[2] = (d >> 16) & 255UL;
	disp[3] = (d >> 24) & 255UL;
}

static int cgasm_label_key_order(const cgasm_lab *left, const cgasm_lab *right)
{
	int i;

	if (left->kind != right->kind)
		return left->kind < right->kind ? -1 : 1;
	for (i = 0; i < (left->kind == 1 ? 3 : 1); i++) {
		if (left->ids[i] != right->ids[i])
			return left->ids[i] < right->ids[i] ? -1 : 1;
	}
	return 0;
}

static int cgasm_label_order(const void *left, const void *right)
{
	const cgasm_lab *a = left;
	const cgasm_lab *b = right;
	int order = cgasm_label_key_order(a, b);

	if (order != 0)
		return order;
	/* Measured offsets never decrease, so the lowest offset is the first mark. */
	return a->off < b->off ? -1 : a->off > b->off;
}

static int cgasm_find_label(const cgasm_lab *labs, int n, int kind,
			    const unsigned long ids[3], unsigned long *off)
{
	cgasm_lab key = { kind, { ids[0], ids[1], ids[2] }, 0 };
	int lo = 0;
	int hi = n;

	while (lo < hi) {
		int mid = lo + (hi - lo) / 2;

		if (cgasm_label_key_order(&labs[mid], &key) < 0)
			lo = mid + 1;
		else
			hi = mid;
	}
	if (lo == n || cgasm_label_key_order(&labs[lo], &key) != 0)
		return -1;
	*off = labs[lo].off;
	return 0;
}

static ouro_v *cgasm_rel32(unsigned long at, unsigned long end,
			   unsigned long id, int import_tgt)
{
	ouro_v *f[4];
	ouro_v *tid = ouro_nat(id);

	f[0] = ouro_ctor(0, 0, 0);
	f[1] = ouro_nat(at);
	f[2] = ouro_nat(end);
	f[3] = ouro_ctor(import_tgt ? 1 : 0, 1, &tid);
	return ouro_ctor(0, 4, f);
}

static ouro_v *cgasm_call_at(unsigned long block, unsigned long site,
			     unsigned long rva)
{
	ouro_v *f[3];

	f[0] = ouro_nat(block);
	f[1] = ouro_nat(site);
	f[2] = ouro_nat(rva);
	return ouro_ctor(0, 3, f);
}

static ouro_v *cgasm_list(ouro_v **items, int n)
{
	ouro_v *xs = ouro_ctor(0, 0, 0);
	int i;

	for (i = n - 1; i >= 0; i--) {
		ouro_v *cell[2];

		cell[0] = items[i];
		cell[1] = xs;
		xs = ouro_ctor(1, 2, cell);
	}
	return xs;
}

static int cgasm_grow(void **p, int *cap, int n, unsigned long elem)
{
	void *next;
	int nc;

	if (n < *cap)
		return 1;
	nc = *cap == 0 ? 64 : *cap * 2;
	next = realloc(*p, (unsigned long)nc * elem);
	if (next == 0)
		return 0;
	*p = next;
	*cap = nc;
	return 1;
}

static int host_list_next_g(ouro_v ***stack, int *sp, int *scap,
			    ouro_v **cur, ouro_v **head)
{
	for (;;) {
		if (list_done(*cur)) {
			if (*sp == 0)
				return 0;
			*cur = (*stack)[--(*sp)];
			continue;
		}
		if ((*cur)->tag == OURO_TAG_CAT && (*cur)->n == 2) {
			if (!cgasm_grow((void **)stack, scap, *sp + 1,
					sizeof(ouro_v *)))
				return -1;
			(*stack)[(*sp)++] = OURO_F(*cur, 1);
			*cur = OURO_F(*cur, 0);
			continue;
		}
		if ((*cur)->tag == 1 && (*cur)->n == 2) {
			*head = OURO_F(*cur, 0);
			*cur = OURO_F(*cur, 1);
			return 1;
		}
		return -1;
	}
}

static int cgasm_next_atom(ouro_v ***stack, int *sp, int *scap, ouro_v **cur,
			   ouro_v **atom)
{
	return host_list_next_g(stack, sp, scap, cur, atom);
}

static ouro_v *cgasm_try(ouro_v *atoms, ouro_v *base_v, ouro_v *initial_v)
{
	cgasm_atom *pending = 0;
	cgasm_lab *labs = 0;
	ouro_v **fixups = 0;
	ouro_v **calls = 0;
	unsigned char *bytes = 0;
	ouro_v *cur;
	ouro_v *atom;
	ouro_v **stack = 0;
	ouro_v *out = 0;
	x64enc_buf enc;
	unsigned long base;
	unsigned long initial;
	unsigned long offset;
	unsigned long remain;
	int natoms = 0;
	int npending = 0;
	int pcap = 0;
	int nlab = 0;
	int lcap = 0;
	int labels_sorted = 0;
	int nfix = 0;
	int fcap = 0;
	int ncall = 0;
	int ccap = 0;
	int nbytes = 0;
	int bcap = 0;
	int i;
	int rc;
	int sp = 0;
	int scap = 0;
	int step;

	if (x64enc_dec_nat(base_v, &base) != 0
	    || x64enc_dec_nat(initial_v, &initial) != 0)
		return 0;
	offset = initial;
	cur = atoms;
	for (;;) {
		cgasm_atom a;

		step = cgasm_next_atom(&stack, &sp, &scap, &cur, &atom);
		if (step == 0)
			break;
		if (step < 0 || natoms >= 16777216)
			goto fallback;
		if (cgasm_read_atom(atom, &a) != CGASM_OK)
			goto fallback;
		rc = cgasm_measure_atom(atom, &a, &enc);
		if (rc == CGASM_FALLBACK)
			goto fallback;
		if (rc == CGASM_FAIL) {
			out = cgasm_enc_err(&enc);
			if (out == 0)
				goto fallback;
			goto done;
		}
		if (enc.n < 0 || enc.n > CGASM_MAX_INS)
			goto fallback;
		a.n = enc.n;
		remain = offset > PE_MAX_RVA ? 0UL : PE_MAX_RVA - offset;
		if ((unsigned long)a.n > remain) {
			out = cgasm_left(5, 0, 0);
			goto done;
		}
		if (a.tag == 1) {
			if (!cgasm_grow((void **)&labs, &lcap, nlab + 1,
					sizeof *labs))
				goto fallback;
			labs[nlab].kind = a.lab_kind;
			labs[nlab].ids[0] = a.lab[0];
			labs[nlab].ids[1] = a.lab[1];
			labs[nlab].ids[2] = a.lab[2];
			labs[nlab].off = offset;
			nlab++;
		} else if (a.tag != 0) {
			if (!cgasm_grow((void **)&pending, &pcap, npending + 1,
					sizeof *pending))
				goto fallback;
			a.off = offset;
			pending[npending++] = a;
		}
		if (a.n > 0) {
			/* A single grow covers an instruction of at most 32 bytes. */
			if (!cgasm_grow((void **)&bytes, &bcap, nbytes + a.n - 1, 1))
				goto fallback;
			memcpy(bytes + nbytes, enc.b, (size_t)a.n);
			nbytes += a.n;
		}
		natoms++;
		offset += (unsigned long)a.n;
	}

	/* Measurement errors take precedence over unresolved labels. */
	for (i = 0; i < npending; i++) {
		const cgasm_atom *a = &pending[i];
		unsigned long absv = base + a->off;

		if (a->tag == 2 || a->tag == 3) {
			unsigned long target;
			unsigned long disp[4];
			int back;
			unsigned long origin;

			if (nlab > 1 && !labels_sorted) {
				qsort(labs, (size_t)nlab, sizeof *labs, cgasm_label_order);
				labels_sorted = 1;
			}
			if (cgasm_find_label(labs, nlab, a->lab_kind, a->lab,
					     &target) != 0) {
				out = cgasm_left(4, ouro_nat(a->lab[0]), 1);
				goto done;
			}
			origin = a->off + (a->tag == 2 ? 5UL : 6UL);
			cgasm_relative(target, origin, disp, &back);
			rc = cgasm_enc_rel(a->tag == 2 ? 18 : 19, a->cond, disp,
					   back, &enc);
			if (rc == CGASM_FALLBACK)
				goto fallback;
			if (rc == CGASM_FAIL) {
				out = cgasm_enc_err(&enc);
				if (out == 0)
					goto fallback;
				goto done;
			}
			if (enc.n != a->n)
				goto fallback;
			memcpy(bytes + (a->off - initial), enc.b, (size_t)enc.n);
		}
		if (a->tag == 4) {
			if (!cgasm_grow((void **)&fixups, &fcap, nfix + 1,
					sizeof *fixups))
				goto fallback;
			fixups[nfix++] = cgasm_rel32(absv + 1UL, absv + 5UL,
						     a->id, 0);
		} else if (a->tag == 5) {
			if (!cgasm_grow((void **)&fixups, &fcap, nfix + 1,
					sizeof *fixups))
				goto fallback;
			fixups[nfix++] = cgasm_rel32(absv + 2UL, absv + 6UL,
						     a->id, 1);
		} else if (a->tag == 6) {
			if (!cgasm_grow((void **)&fixups, &fcap, nfix + 1,
					sizeof *fixups))
				goto fallback;
			fixups[nfix++] = cgasm_rel32(absv + 3UL, absv + 7UL,
						     a->id, a->imported);
		} else if (a->tag == 7) {
			if (!cgasm_grow((void **)&calls, &ccap, ncall + 1,
					sizeof *calls))
				goto fallback;
			calls[ncall++] = cgasm_call_at(a->id, a->site,
						      PE_SECTION_ALIGN + absv);
		}
	}

	{
		ouro_v *fields[3];
		ouro_v *parts;

		fields[0] = ouro_packed(bytes, (unsigned long)nbytes);
		fields[1] = cgasm_list(fixups, nfix);
		fields[2] = cgasm_list(calls, ncall);
		parts = ouro_ctor(0, 3, fields);
		out = ouro_ctor(1, 1, &parts);
	}
	g_asm_count++;
	if (g_asm_count == 1UL || (g_asm_count % 25UL) == 0UL)
		fe_progress("n1-host: assemble %lu atoms=%d bytes=%d\n",
			g_asm_count, natoms, nbytes);
	goto done;

fallback:
	g_asm_fallback++;
	if (g_asm_fallback <= 3UL)
		fe_progress("n1-host: assemble fallback %lu\n",
			g_asm_fallback);
	out = 0;
done:
	free(pending);
	free(labs);
	free(fixups);
	free(calls);
	free(bytes);
	free(stack);
	return out;
}

static ouro_v *cgasm_initial(ouro_env *env, ouro_v *initial)
{
	ouro_v *base = ouro_get(env, 0);
	ouro_v *atoms = ouro_get(env, 1);
	ouro_v *fast = cgasm_try(atoms, base, initial);

	if (fast != 0)
		return fast;
	return ouro_apply(ouro_apply(ouro_apply(g_raw_codegen_assemble, atoms),
				     base), initial);
}

static ouro_v *cgasm_base(ouro_env *env, ouro_v *base)
{
	return ouro_clos(cgasm_initial, ouro_cons(base, env));
}

static ouro_v *cgasm_atoms(ouro_env *env, ouro_v *atoms)
{
	(void)env;
	return ouro_clos(cgasm_base, ouro_cons(atoms, 0));
}

ouro_v *ouro_wrap_codegen_assemble(ouro_v *raw)
{
	g_raw_codegen_assemble = raw;
	g_asm_count = 0;
	g_asm_fallback = 0;
	return ouro_clos(cgasm_atoms, 0);
}

/* The canonical Ouro solver owns exact live facts, edge errors and fuel.
   Retain its complete result before releasing one call's temporary graph. */
static ouro_v *g_raw_live_facts;

static int host_list_next(ouro_v **stack, int *sp, ouro_v **cur, ouro_v **head)
{
	for (;;) {
		if (list_done(*cur)) {
			if (*sp == 0)
				return 0;
			*cur = stack[--(*sp)];
			continue;
		}
		if ((*cur)->tag == OURO_TAG_CAT && (*cur)->n == 2) {
			if (*sp >= 63)
				return -1;
			stack[(*sp)++] = OURO_F(*cur, 1);
			*cur = OURO_F(*cur, 0);
			continue;
		}
		if ((*cur)->tag == 1 && (*cur)->n == 2) {
			*head = OURO_F(*cur, 0);
			*cur = OURO_F(*cur, 1);
			return 1;
		}
		return -1;
	}
}

static int host_list_collect(ouro_v *list, ouro_v ***out, int *n, int *cons_list)
{
	ouro_v **stack = 0;
	ouro_v *cur = list;
	ouro_v *item;
	int sp = 0;
	int scap = 0;
	int cap = 0;
	int step;

	*out = 0;
	*n = 0;
	for (;;) {
		step = host_list_next_g(&stack, &sp, &scap, &cur, &item);
		if (step == 0) {
			/* A concat node allocates the stack even if its branches are empty. */
			if (cons_list != 0)
				*cons_list = stack == 0 && cur != 0 && cur->tag == 0 && cur->n == 0;
			free(stack);
			return 0;
		}
		if (step < 0) {
			free(stack);
			return -1;
		}
		if (!cgasm_grow((void **)out, &cap, *n + 1, sizeof(ouro_v *))) {
			free(stack);
			return -1;
		}
		(*out)[(*n)++] = item;
	}
}

static int live_fuel_zero(ouro_v *fuel)
{
	unsigned long n;

	if (fuel == 0)
		return 1;
	if (fuel->tag == 0 && fuel->n == 0)
		return 1;
	if (x64enc_dec_nat(fuel, &n) == 0)
		return n == 0UL;
	return 0;
}

static ouro_v *live_exact(ouro_v *fuel, ouro_v *roots, ouro_v *blocks)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *raw = g_raw_live_facts != 0 ? g_raw_live_facts : FIND(lo, "mir_live_facts");
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(raw, fuel), roots), blocks);
	return ouro_heap_context_leave(context, result);
}

/* A Jacobi round reads frozen facts and returns one complete typed result.
   Its captures remain in the caller while only the round's temporaries die. */
static ouro_v *live_summary_blocks(ouro_env *env, ouro_v *summaries)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_get(env, 1),
		ouro_get(env, 0)), summaries);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *live_summary_facts(ouro_env *env, ouro_v *facts)
{
	return ouro_clos(live_summary_blocks, ouro_cons(facts, env));
}

ouro_v *ouro_wrap_mir_live_summary_step(ouro_v *raw)
{
	return ouro_clos(live_summary_facts, ouro_cons(raw, 0));
}

static ouro_v *live_blocks(ouro_env *env, ouro_v *blocks)
{
	return live_exact(ouro_get(env, 1), ouro_get(env, 0), blocks);
}

static ouro_v *live_roots(ouro_env *env, ouro_v *roots)
{
	return ouro_clos(live_blocks, ouro_cons(roots, env));
}

static ouro_v *live_fuel(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(live_roots, ouro_cons(fuel, 0));
}

ouro_v *ouro_wrap_mir_live_facts(ouro_v *raw)
{
	g_raw_live_facts = raw;
	return ouro_clos(live_fuel, 0);
}

static ouro_v *g_raw_codegen_parts;
static unsigned long g_parts_count;
static unsigned long g_parts_fallback;

static ouro_v *parts_try(ouro_v *parts)
{
	ouro_v *stack[64];
	ouro_v *cur = parts;
	ouro_v *part;
	ouro_v **rights = 0;
	ouro_v *out;
	int n = 0;
	int cap = 0;
	int sp = 0;
	int step;
	int i;

	for (;;) {
		step = host_list_next(stack, &sp, &cur, &part);
		if (step == 0)
			break;
		if (step < 0 || part == 0 || part->n < 1)
			goto fallback;
		if (part->tag == 0) {
			ouro_v *err = OURO_F(part, 0);

			free(rights);
			return ouro_ctor(0, 1, &err);
		}
		if (part->tag != 1)
			goto fallback;
		if (!cgasm_grow((void **)&rights, &cap, n + 1, sizeof *rights))
			goto fallback;
		rights[n++] = OURO_F(part, 0);
	}
	out = ouro_ctor(0, 0, 0);
	for (i = n - 1; i >= 0; i--) {
		ouro_v *cell[2];

		if (list_done(rights[i]))
			continue;
		if (list_done(out)) {
			out = rights[i];
			continue;
		}
		cell[0] = rights[i];
		cell[1] = out;
		out = ouro_ctor(OURO_TAG_CAT, 2, cell);
	}
	free(rights);
	g_parts_count++;
	return ouro_ctor(1, 1, &out);

fallback:
	g_parts_fallback++;
	if (g_parts_fallback <= 3UL)
		fe_progress("n1-host: parts fallback %lu\n",
			g_parts_fallback);
	free(rights);
	return 0;
}

static ouro_v *parts_apply(ouro_env *env, ouro_v *parts)
{
	ouro_v *fast;

	(void)env;
	fast = parts_try(parts);
	if (fast != 0)
		return fast;
	return ouro_apply(g_raw_codegen_parts, parts);
}

ouro_v *ouro_wrap_codegen_parts(ouro_v *raw)
{
	g_raw_codegen_parts = raw;
	g_parts_count = 0;
	g_parts_fallback = 0;
	return ouro_clos(parts_apply, 0);
}

/* Only the canonical transfer may authorize removing managed roots. */
static ouro_v *g_raw_live_ins;

static ouro_v *cli_block(ouro_env *env, ouro_v *block)
{
	ouro_v *facts = ouro_get(env, 0);
	ouro_v *slots = ouro_get(env, 1);
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_apply(g_raw_live_ins,
		slots), facts), block);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *cli_facts(ouro_env *env, ouro_v *facts)
{
	return ouro_clos(cli_block, ouro_cons(facts, env));
}

static ouro_v *cli_slots(ouro_env *env, ouro_v *slots)
{
	(void)env;
	return ouro_clos(cli_facts, ouro_cons(slots, 0));
}

ouro_v *ouro_wrap_codegen_live_instructions(ouro_v *raw)
{
	g_raw_live_ins = raw;
	return ouro_clos(cli_slots, 0);
}

static ouro_v *g_raw_clear_roots;

static ouro_v *cdroot_live(ouro_env *env, ouro_v *live)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(g_raw_clear_roots,
		ouro_get(env, 0)), live);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *cdroot_slots(ouro_env *env, ouro_v *slots)
{
	(void)env;
	return ouro_clos(cdroot_live, ouro_cons(slots, 0));
}

ouro_v *ouro_wrap_codegen_clear_dead_roots(ouro_v *raw)
{
	g_raw_clear_roots = raw;
	return ouro_clos(cdroot_slots, 0);
}

static ouro_v *g_raw_cgi;
static unsigned long g_cgi_count;
static unsigned long g_cgi_fallback;

static ouro_v *cgn_unit(int tag)
{
	return ouro_ctor(tag, 0, 0);
}

static ouro_v *cgn_word32(unsigned long n)
{
	ouro_v *b[4];

	b[0] = ouro_nat(n & 255UL);
	b[1] = ouro_nat((n >> 8) & 255UL);
	b[2] = ouro_nat((n >> 16) & 255UL);
	b[3] = ouro_nat((n >> 24) & 255UL);
	return ouro_ctor(0, 4, b);
}

static ouro_v *cgn_disp(unsigned long n)
{
	ouro_v *w = cgn_word32(n);

	return ouro_ctor(0, 1, &w);
}

static ouro_v *cgn_base(int reg, unsigned long off)
{
	ouro_v *f[2];

	f[0] = cgn_unit(reg);
	f[1] = cgn_disp(off);
	return ouro_ctor(0, 2, f);
}

static ouro_v *cgn_base_disp(int reg, ouro_v *disp)
{
	ouro_v *f[2];

	f[0] = cgn_unit(reg);
	f[1] = disp;
	return ouro_ctor(0, 2, f);
}

static ouro_v *cgn_indexed(int base, int index)
{
	ouro_v *f[4];

	f[0] = cgn_unit(base);
	f[1] = cgn_unit(index);
	f[2] = cgn_unit(0);
	f[3] = cgn_disp(0);
	return ouro_ctor(1, 4, f);
}

static ouro_v *cgn_atom(ouro_v *ins)
{
	return ouro_ctor(0, 1, &ins);
}

static ouro_v *cgn_cat(ouro_v *a, ouro_v *b)
{
	ouro_v *cell[2];

	if (list_done(a))
		return b;
	if (list_done(b))
		return a;
	cell[0] = a;
	cell[1] = b;
	return ouro_ctor(OURO_TAG_CAT, 2, cell);
}

static ouro_v *cgn_one(ouro_v *atom)
{
	return cgasm_list(&atom, 1);
}

static ouro_v *cgn_right(ouro_v *atoms)
{
	return ouro_ctor(1, 1, &atoms);
}

static ouro_v *cgn_load(int bits64, int reg, ouro_v *addr)
{
	ouro_v *f[3];

	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = cgn_unit(reg);
	f[2] = addr;
	return cgn_atom(ouro_ctor(3, 3, f));
}

static ouro_v *cgn_store(int bits64, ouro_v *addr, int reg)
{
	ouro_v *f[3];

	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = addr;
	f[2] = cgn_unit(reg);
	return cgn_atom(ouro_ctor(4, 3, f));
}

static ouro_v *cgn_arith_reg(int bits64, int op, int dst, int src)
{
	ouro_v *f[4];

	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = cgn_unit(op);
	f[2] = cgn_unit(dst);
	f[3] = cgn_unit(src);
	return cgn_atom(ouro_ctor(10, 4, f));
}

static ouro_v *cgn_arith_imm(int bits64, int op, int reg, unsigned long imm)
{
	ouro_v *f[4];

	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = cgn_unit(op);
	f[2] = cgn_unit(reg);
	f[3] = cgn_word32(imm);
	return cgn_atom(ouro_ctor(11, 4, f));
}

static ouro_v *cgn_mov(int bits64, int dst, int src)
{
	ouro_v *f[3];

	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = cgn_unit(dst);
	f[2] = cgn_unit(src);
	return cgn_atom(ouro_ctor(2, 3, f));
}

static int cgn_bits64(int ty)
{
	return ty == 2 || ty >= 4;
}

typedef struct {
	unsigned long id;
	int position;
	ouro_v *value;
} cgn_slot_entry;

typedef struct {
	ouro_v *source;
	cgn_slot_entry *entries;
	int count;
	enum { CGN_SLOTS_UNINDEXED, CGN_SLOTS_INDEXED, CGN_SLOTS_FAILED } state;
	/* The immutable slot list is shared by the prologue and all epilogues. */
	enum { CGN_ROOTS_UNKNOWN, CGN_ROOTS_ABSENT, CGN_ROOTS_PRESENT, CGN_ROOTS_SCALAR_FRAME } roots;
} cgn_frame_slots;

static int cgn_slot_order(const void *left, const void *right)
{
	const cgn_slot_entry *a = left;
	const cgn_slot_entry *b = right;

	if (a->id != b->id)
		return a->id < b->id ? -1 : 1;
	return a->position < b->position ? -1 : a->position > b->position;
}

static void cgn_index_slots(cgn_frame_slots *slots)
{
	ouro_v **stack = 0;
	ouro_v *cur = slots->source;
	ouro_v *item;
	int sp = 0;
	int scap = 0;
	int cap = 0;
	int ordered = 1;
	int step;

	while ((step = host_list_next_g(&stack, &sp, &scap, &cur, &item)) > 0) {
		unsigned long id;
		int position = slots->count;

		if (item == 0 || item->tag != 0 || item->n < 3
		    || x64enc_dec_nat(OURO_F(item, 0), &id) != 0)
			continue;
		if ((position + 1 >= cap
		     && (cap > INT_MAX / 2 || (size_t)cap > ULONG_MAX / 2 / sizeof *slots->entries))
		    || !cgasm_grow((void **)&slots->entries, &cap, position + 1, sizeof *slots->entries)) {
			step = -1;
			break;
		}
		if (position > 0 && slots->entries[position - 1].id > id)
			ordered = 0;
		slots->entries[position] = (cgn_slot_entry){ id, position, item };
		slots->count++;
	}
	free(stack);
	if (step < 0) {
		slots->state = CGN_SLOTS_FAILED;
		return;
	}
	if (!ordered)
		qsort(slots->entries, (size_t)slots->count,
		      sizeof *slots->entries, cgn_slot_order);
	slots->state = CGN_SLOTS_INDEXED;
}

static int cgn_slot(cgn_frame_slots *slots, unsigned long id, unsigned long *off, int *ty)
{
	ouro_v *item;
	int lo = 0;
	int hi;

	if (slots->state == CGN_SLOTS_UNINDEXED)
		cgn_index_slots(slots);
	if (slots->state == CGN_SLOTS_FAILED)
		return -1;
	hi = slots->count;
	while (lo < hi) {
		int mid = lo + (hi - lo) / 2;

		if (slots->entries[mid].id < id)
			lo = mid + 1;
		else
			hi = mid;
	}
	if (lo == slots->count || slots->entries[lo].id != id)
		return -1;
	item = slots->entries[lo].value;
	/* An invalid first match still requires fallback, even if a later slot is valid. */
	if (OURO_F(item, 1) == 0 || x64enc_dec_nat(OURO_F(item, 2), off) != 0)
		return -1;
	*ty = OURO_F(item, 1)->tag;
	return 0;
}

static ouro_v *cgn_load_value(cgn_frame_slots *slots, int reg, ouro_v *value)
{
	unsigned long off;
	int ty;

	if (value == 0)
		return 0;
	if (value->tag == 0 && value->n >= 1) {
		unsigned long id;

		if (x64enc_dec_nat(OURO_F(value, 0), &id) != 0)
			return 0;
		if (cgn_slot(slots, id, &off, &ty) != 0)
			return 0;
		return cgn_one(cgn_load(1, reg, cgn_base(4, off)));
	}
	if (value->tag == 1 && value->n >= 2) {
		ouro_v *word = OURO_F(value, 1);
		ouro_v *f[2];

		if (OURO_F(value, 0) == 0)
			return 0;
		ty = OURO_F(value, 0)->tag;
		f[0] = cgn_unit(reg);
		if (cgn_bits64(ty)) {
			f[1] = word;
			return cgn_one(cgn_atom(ouro_ctor(1, 2, f)));
		}
		if (word == 0 || word->n < 1)
			return 0;
		f[1] = OURO_F(word, 0);
		return cgn_one(cgn_atom(ouro_ctor(0, 2, f)));
	}
	return 0;
}

static ouro_v *cgn_save_off(int ty, unsigned long off, int reg)
{
	ouro_v *store = cgn_one(cgn_store(1, cgn_base(4, off), reg));

	if (ty == 0)
		return cgn_cat(cgn_one(cgn_arith_imm(0, 2, reg, 255UL)), store);
	if (ty == 1 || ty == 3)
		return cgn_cat(cgn_one(cgn_mov(0, reg, reg)), store);
	return store;
}

static ouro_v *cgn_save(cgn_frame_slots *slots, unsigned long id, int reg)
{
	unsigned long off;
	int ty;

	if (cgn_slot(slots, id, &off, &ty) != 0)
		return 0;
	return cgn_save_off(ty, off, reg);
}

static int cgn_list_has_id(ouro_v *list, unsigned long want, int field)
{
	ouro_v **items = 0;
	int n = 0;
	int i;

	if (host_list_collect(list, &items, &n, 0) != 0) {
		free(items);
		return -1;
	}
	for (i = 0; i < n; i++) {
		unsigned long id;

		if (items[i] == 0 || items[i]->n <= field)
			continue;
		if (x64enc_dec_nat(OURO_F(items[i], field), &id) != 0)
			continue;
		if (id == want) {
			free(items);
			return 1;
		}
	}
	free(items);
	return 0;
}

static int cgn_find_id_position(const cgn_id_position *positions, int count, unsigned long id)
{
	int low = 0;
	int high = count;

	while (low < high) {
		int middle = low + (high - low) / 2;

		if (positions[middle].id < id)
			low = middle + 1;
		else
			high = middle;
	}
	return low < count && positions[low].id == id ? positions[low].ordinal : -1;
}

static int cgn_find_pinned_function(ouro_v *program, unsigned long id, int *position)
{
	if (program != g_perm_cg_program || !g_cgn_function_index_ready)
		return 0;
	*position = cgn_find_id_position(g_cgn_function_positions, g_cgn_function_count, id);
	return 1;
}

static int cgn_has_function(ouro_v *program, unsigned long id)
{
	int position;

	if (cgn_find_pinned_function(program, id, &position))
		return position >= 0;
	if (program == 0 || program->n < 1)
		return -1;
	return cgn_list_has_id(OURO_F(program, 0), id, 0);
}

static int cgn_has_extern(ouro_v *program, unsigned long id)
{
	ouro_v **libs = 0;
	int n = 0;
	int i;
	int found = 0;

	if (program == 0 || program->n < 3)
		return -1;
	if (program == g_perm_cg_program && g_cgn_externs.available) {
		int lo = 0;
		int hi = g_cgn_externs.count;

		while (lo < hi) {
			int mid = lo + (hi - lo) / 2;
			unsigned long current = g_cgn_externs.ids[mid];

			if (current == id)
				return 1;
			if (current < id)
				lo = mid + 1;
			else
				hi = mid;
		}
		return 0;
	}
	if (host_list_collect(OURO_F(program, 2), &libs, &n, 0) != 0) {
		free(libs);
		return -1;
	}
	for (i = 0; i < n; i++) {
		int hit;

		if (libs[i] == 0 || libs[i]->n < 2)
			continue;
		hit = cgn_list_has_id(OURO_F(libs[i], 1), id, 1);
		if (hit < 0) {
			free(libs);
			return -1;
		}
		if (hit) {
			found = 1;
			break;
		}
	}
	free(libs);
	return found;
}

static ouro_v *cgn_mem_load(int ty, ouro_v *addr)
{
	if (ty == 0)
		return cgn_atom(ouro_ctor(5, 2, (ouro_v *[]){ cgn_unit(0), addr }));
	return cgn_load(cgn_bits64(ty), 0, addr);
}

static ouro_v *cgn_mem_store(int ty, ouro_v *addr)
{
	if (ty == 0)
		return cgn_atom(ouro_ctor(6, 2, (ouro_v *[]){ addr, cgn_unit(0) }));
	return cgn_store(cgn_bits64(ty), addr, 0);
}

static ouro_v *cgn_value_ty(cgn_frame_slots *slots, ouro_v *value, int *ty)
{
	unsigned long off;

	if (value == 0)
		return 0;
	if (value->tag == 1 && value->n >= 1 && OURO_F(value, 0) != 0) {
		*ty = OURO_F(value, 0)->tag;
		return value;
	}
	if (value->tag == 0 && value->n >= 1) {
		unsigned long id;

		if (x64enc_dec_nat(OURO_F(value, 0), &id) != 0)
			return 0;
		if (cgn_slot(slots, id, &off, ty) != 0)
			return 0;
		return value;
	}
	return 0;
}

typedef struct {
	ouro_v **items;
	int count;
} cgn_call_args;

static ouro_v *cgn_emit_args(cgn_frame_slots *slots, ouro_v *const *items, int n)
{
	ouro_v *out = ouro_ctor(0, 0, 0);
	int i;
	static const int argreg[4] = { 1, 2, 8, 9 };

	for (i = 0; i < n; i++) {
		ouro_v *load = cgn_load_value(slots, 0, items[i]);
		ouro_v *place;

		if (load == 0)
			return 0;
		if (i < 4)
			place = cgn_one(cgn_mov(1, argreg[i], 0));
		else
			place = cgn_one(cgn_store(1, cgn_base(4, (unsigned long)i * 8UL), 0));
		out = cgn_cat(out, cgn_cat(load, place));
	}
	return out;
}

static ouro_v *cgn_args(cgn_frame_slots *slots, ouro_v *args)
{
	ouro_v **items = 0;
	ouro_v *out = 0;
	int n = 0;

	if (host_list_collect(args, &items, &n, 0) == 0)
		out = cgn_emit_args(slots, items, n);
	free(items);
	return out;
}

static ouro_v *cgn_site_label(unsigned long block, unsigned long site,
			      unsigned long step)
{
	ouro_v *f[3];

	f[0] = ouro_nat(block);
	f[1] = ouro_nat(site);
	f[2] = ouro_nat(step);
	return ouro_ctor(1, 3, f);
}

static int cgn_cond(int ty, int cmp)
{
	int signed_i32 = ty == 3;

	if (cmp == 0)
		return 4;
	if (cmp == 1)
		return 5;
	if (cmp == 2)
		return signed_i32 ? 12 : 2;
	if (cmp == 3)
		return signed_i32 ? 14 : 6;
	if (cmp == 4)
		return signed_i32 ? 15 : 7;
	if (cmp == 5)
		return signed_i32 ? 13 : 3;
	return -1;
}

static unsigned long g_cgn_runtime_id;
static unsigned long g_cgn_budget_off;
static unsigned long g_cgn_entry;
static int g_cgn_nobj;
static unsigned long g_cgn_max_object_id;
static unsigned long *g_cgn_alldesc;
static int g_cgn_nall;

static int cgn_fn_has_roots(ouro_v *fn)
{
	ouro_v **stack = 0;
	int capacity = 0;
	int field;
	int roots = 0;

	if (fn == 0 || fn->tag != 0 || fn->n != 7)
		return -1;
	for (field = 2; field <= 3; field++) {
		ouro_v *cursor = OURO_F(fn, field);
		ouro_v *item;
		int depth = 0;
		int step;

		while ((step = host_list_next_g(&stack, &depth, &capacity, &cursor, &item)) > 0) {
			ouro_v *type;

			if (item == 0 || item->tag != 0 || item->n != 2)
				goto fail;
			type = OURO_F(item, 1);
			if (type == 0 || type->n != 0 || type->tag < 0 || type->tag > 6)
				goto fail;
			if (type->tag == 6)
				roots = 1;
		}
		if (step < 0)
			goto fail;
	}
	free(stack);
	return roots;

fail:
	free(stack);
	return -1;
}

static void cgn_record_extern_id(cgn_extern_index *index, unsigned long id)
{
	if (index == 0 || !index->available)
		return;
	if (index->count + 1 >= index->capacity &&
	    (index->capacity > INT_MAX / 2 ||
	     (unsigned long)index->capacity > ULONG_MAX / 2 / sizeof *index->ids ||
	     !cgasm_grow((void **)&index->ids, &index->capacity, index->count + 1,
			 sizeof *index->ids))) {
		cgn_release_extern_index(index);
		return;
	}
	index->ids[index->count++] = id;
}

static int cgn_decode_item_id(ouro_v *item, int field, unsigned long *id)
{
	if (item == 0 || item->tag != 0 || item->n <= field)
		return -1;
	return x64enc_dec_nat(OURO_F(item, field), id);
}

static int cgn_max_list_id(ouro_v *list, int field, unsigned long *max_id,
			  cgn_extern_index *externs)
{
	ouro_v **stack = 0;
	ouro_v *item;
	int depth = 0;
	int capacity = 0;
	int step;

	while ((step = host_list_next_g(&stack, &depth, &capacity, &list, &item)) > 0) {
		unsigned long id;

		if (cgn_decode_item_id(item, field, &id) != 0) {
			step = -1;
			break;
		}
		if (id > *max_id)
			*max_id = id;
		cgn_record_extern_id(externs, id);
	}
	free(stack);
	return step;
}

typedef struct {
	unsigned long id;
	int site;
} cgn_descriptor;

static int cgn_push_allocs(ouro_v *fn, cgn_descriptor **descs, int *n, int *cap)
{
	ouro_v **block_stack = 0;
	ouro_v **instruction_stack = 0;
	ouro_v *blocks;
	ouro_v *block;
	int block_depth = 0;
	int block_capacity = 0;
	int instruction_capacity = 0;
	int block_step;
	int result = -1;

	if (fn == 0 || fn->tag != 0 || fn->n != 7)
		return -1;
	blocks = OURO_F(fn, 6);
	while ((block_step = host_list_next_g(&block_stack, &block_depth, &block_capacity,
					     &blocks, &block)) > 0) {
		ouro_v *cursor;
		ouro_v *instruction;
		int depth = 0;
		int step;

		if (block == 0 || block->tag != 0 || block->n != 3)
			goto done;
		cursor = OURO_F(block, 1);
		while ((step = host_list_next_g(&instruction_stack, &depth, &instruction_capacity,
						&cursor, &instruction)) > 0) {
			unsigned long desc;

			if (instruction != 0 && instruction->tag != 11)
				continue;
			if (instruction == 0 || instruction->n != 5
			    || x64enc_dec_nat(OURO_F(instruction, 3), &desc) != 0
			    || *n == INT_MAX
			    || (*n + 1 >= *cap && (*cap > INT_MAX / 2
			        || (unsigned long)*cap > ULONG_MAX / 2 / sizeof **descs))
			    || !cgasm_grow((void **)descs, cap, *n + 1, sizeof **descs))
				goto done;
			(*descs)[*n] = (cgn_descriptor){desc, *n};
			(*n)++;
		}
		if (step < 0)
			goto done;
	}
	result = block_step;
done:
	free(instruction_stack);
	free(block_stack);
	return result;
}

static int cgn_descriptor_id_order(const void *left, const void *right)
{
	const cgn_descriptor *a = (const cgn_descriptor *)left;
	const cgn_descriptor *b = (const cgn_descriptor *)right;

	if (a->id != b->id)
		return a->id < b->id ? -1 : 1;
	return a->site > b->site ? -1 : a->site < b->site;
}

static int cgn_descriptor_site_order(const void *left, const void *right)
{
	const cgn_descriptor *a = (const cgn_descriptor *)left;
	const cgn_descriptor *b = (const cgn_descriptor *)right;

	return a->site < b->site ? -1 : a->site > b->site;
}

static int cgn_id_position_order(const void *left, const void *right)
{
	const cgn_id_position *a = (const cgn_id_position *)left;
	const cgn_id_position *b = (const cgn_id_position *)right;

	if (a->id != b->id)
		return a->id < b->id ? -1 : 1;
	return a->ordinal < b->ordinal ? -1 : a->ordinal > b->ordinal;
}

static int cgn_extern_id_order(const void *left, const void *right)
{
	unsigned long a = *(const unsigned long *)left;
	unsigned long b = *(const unsigned long *)right;

	return a < b ? -1 : a > b;
}

static int cgn_refresh_meta(ouro_v *program)
{
	ouro_v **fns = 0;
	ouro_v **libs = 0;
	cgn_descriptor *descs = 0;
	cgn_id_position *positions = 0;
	unsigned long *all = 0;
	unsigned char *function_roots = 0;
	cgn_extern_index externs = {
		.available = program != 0 && program == g_perm_cg_program && !g_cgn_externs.available
	};
	unsigned long max_id = 0;
	unsigned long max_object_id = 0;
	unsigned long entry;
	int n = 0;
	int nlib = 0;
	int nalloc = 0;
	int acap = 0;
	int nuniq = 0;
	int nroot = 0;
	int nall;
	int index_functions = program == g_perm_cg_program && !g_cgn_function_index_ready;
	int i;
	int result = -1;

	if (program == g_cgn_prog && g_cgn_meta_ok)
		return 0;
	g_cgn_meta_ok = 0;
	if (program == 0 || program->tag != 0 || program->n != 4
	    || x64enc_dec_nat(OURO_F(program, 3), &entry) != 0)
		return -1;
	if (host_list_collect(OURO_F(program, 0), &fns, &n, 0) != 0)
		goto done;
	if (index_functions && n > 0 && (size_t)n <= (size_t)-1 / sizeof *positions)
		positions = (cgn_id_position *)malloc((size_t)n * sizeof *positions);
	for (i = 0; i < n; i++) {
		unsigned long id;

		if (cgn_decode_item_id(fns[i], 0, &id) != 0)
			goto done;
		if (id > max_id)
			max_id = id;
		if (positions != 0)
			positions[i] = (cgn_id_position){id, i};
	}
	if (cgn_max_list_id(OURO_F(program, 1), 0, &max_id, 0) != 0)
		goto done;
	if (host_list_collect(OURO_F(program, 2), &libs, &nlib, 0) != 0)
		goto done;
	for (i = 0; i < nlib; i++) {
		if (libs[i] == 0 || libs[i]->tag != 0 || libs[i]->n != 2
		    || cgn_max_list_id(OURO_F(libs[i], 1), 1, &max_id, &externs) != 0)
			goto done;
	}
	if (max_id > ULONG_MAX - 2UL
	    || (n > 0 && max_id > ULONG_MAX - 2UL - (unsigned long)n))
		goto done;
	if (n > 0)
		function_roots = (unsigned char *)malloc((size_t)n);
	for (i = 0; i < n; i++) {
		int roots = cgn_fn_has_roots(fns[i]);

		if (roots < 0 || cgn_push_allocs(fns[i], &descs, &nalloc, &acap) != 0)
			goto done;
		if (function_roots != 0)
			function_roots[i] = (unsigned char)roots;
		if (roots)
			nroot++;
	}
	if (nalloc > 0) {
		/* Ouro foldr/mir_add retains each ID at its last occurrence. */
		qsort(descs, (size_t)nalloc, sizeof *descs, cgn_descriptor_id_order);
		max_object_id = descs[nalloc - 1].id;
		for (i = 0; i < nalloc; i++) {
			if (nuniq == 0 || descs[i].id != descs[nuniq - 1].id)
				descs[nuniq++] = descs[i];
		}
		qsort(descs, (size_t)nuniq, sizeof *descs, cgn_descriptor_site_order);
	}
	if (nroot > INT_MAX - nuniq)
		goto done;
	nall = nuniq + nroot;
	if ((unsigned long)nall > (ULONG_MAX - 40UL) / 16UL
	    || (size_t)nall > (size_t)-1 / sizeof *all)
		goto done;
	if (nall > 0) {
		int next = nuniq;

		all = (unsigned long *)malloc((size_t)nall * sizeof *all);
		if (all == 0)
			goto done;
		for (i = 0; i < nuniq; i++)
			all[i] = descs[i].id;
		for (i = 0; i < n; i++) {
			int roots = function_roots != 0 ? function_roots[i] : cgn_fn_has_roots(fns[i]);

			if (roots < 0)
				goto done;
			if (roots)
				all[next++] = max_id + 3UL + (unsigned long)i;
		}
	}
	free(g_cgn_alldesc);
	g_cgn_alldesc = all;
	all = 0;
	g_cgn_nobj = nuniq;
	g_cgn_max_object_id = max_object_id;
	g_cgn_nall = nall;
	g_cgn_entry = entry;
	g_cgn_prog = program;
	g_cgn_runtime_id = max_id + 2UL;
	g_cgn_budget_off = 40UL + 16UL * (unsigned long)nall;
	g_cgn_meta_ok = 1;
	if (index_functions && (n == 0 || positions != 0)) {
		if (n > 1)
			qsort(positions, (size_t)n, sizeof *positions, cgn_id_position_order);
		g_cgn_function_positions = positions;
		g_cgn_function_count = n;
		g_cgn_function_index_ready = 1;
		positions = 0;
	}
	if (externs.available) {
		if (externs.count > 1)
			qsort(externs.ids, (size_t)externs.count, sizeof *externs.ids,
			      cgn_extern_id_order);
		g_cgn_externs = externs;
		externs.ids = 0;
	}
	result = 0;
done:
	free(fns);
	free(libs);
	free(descs);
	free(positions);
	free(all);
	free(function_roots);
	cgn_release_extern_index(&externs);
	return result;
}

static ouro_v *cgn_sym(unsigned long id)
{
	ouro_v *f[2];

	f[0] = ouro_nat(id);
	f[1] = cgn_unit(1);
	return ouro_ctor(6, 2, f);
}

static ouro_v *cgn_direct(unsigned long id)
{
	ouro_v *n = ouro_nat(id);

	return ouro_ctor(4, 1, &n);
}

static ouro_v *cgn_bound(unsigned long block, unsigned long site)
{
	ouro_v *f[2];

	f[0] = ouro_nat(block);
	f[1] = ouro_nat(site);
	return ouro_ctor(7, 2, f);
}

static ouro_v *cgn_check(int cond, unsigned long block, unsigned long site,
			 unsigned long step)
{
	ouro_v *lab = cgn_site_label(block, site, step);
	ouro_v *a[3];

	a[0] = ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(cond), lab });
	a[1] = cgn_atom(ouro_ctor(25, 0, 0));
	a[2] = ouro_ctor(1, 1, &lab);
	return cgasm_list(a, 3);
}

static ouro_v *cgn_load_abs(int bits64, int reg, int base, unsigned long off)
{
	return cgn_load(bits64, reg, cgn_base(base, off));
}

static ouro_v *cgn_division(int ty, int rem, unsigned long block,
			    unsigned long site)
{
	int bits64 = cgn_bits64(ty);
	int signed_i32 = ty == 3;
	ouro_v *nonzero = cgn_site_label(block, site, 0);
	ouro_v *safe = cgn_site_label(block, site, 1);
	ouro_v *a;
	ouro_v *f[3];

	a = cgn_one(cgn_arith_imm(bits64, 5, 10, 0UL));
	a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(5), nonzero })));
	a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(25, 0, 0))));
	a = cgn_cat(a, cgn_one(ouro_ctor(1, 1, &nonzero)));
	if (signed_i32) {
		a = cgn_cat(a, cgn_one(cgn_arith_imm(0, 5, 0, 0x80000000UL)));
		a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(5), safe })));
		a = cgn_cat(a, cgn_one(cgn_arith_imm(0, 5, 10, 0xFFFFFFFFUL)));
		a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(5), safe })));
		a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(25, 0, 0))));
		a = cgn_cat(a, cgn_one(ouro_ctor(1, 1, &safe)));
		a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(14, 1, (ouro_v *[]){
			cgn_unit(bits64 ? 1 : 0) }))));
	} else {
		a = cgn_cat(a, cgn_one(cgn_arith_reg(bits64, 4, 2, 2)));
	}
	f[0] = cgn_unit(bits64 ? 1 : 0);
	f[1] = cgn_unit(signed_i32 ? 1 : 0);
	f[2] = ouro_ctor(0, 1, (ouro_v *[]){ cgn_unit(10) });
	a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(13, 3, f))));
	if (rem)
		a = cgn_cat(a, cgn_one(cgn_mov(bits64, 0, 2)));
	return a;
}

static ouro_v *cgi_try(ouro_v *program, cgn_frame_slots *slots, ouro_v *blockv,
		       ouro_v *sitev, ouro_v *ins, const cgn_call_args *call_args)
{
	unsigned long block;
	unsigned long site;
	unsigned long id;
	unsigned long off;
	int ty;
	ouro_v *atoms;
	ouro_v *a;
	ouro_v *b;

	if (ins == 0 || x64enc_dec_nat(blockv, &block) != 0
	    || x64enc_dec_nat(sitev, &site) != 0)
		return 0;
	switch (ins->tag) {
	case 0:
		if (ins->n < 2 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(ins, 1));
		b = cgn_save(slots, id, 0);
		if (a == 0 || b == 0)
			return 0;
		return cgn_right(cgn_cat(a, b));
	case 1:
		if (ins->n < 4 || OURO_F(ins, 1) == 0
		    || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		{
			int op = OURO_F(ins, 1)->tag;
			int rreg = (op == 8 || op == 9) ? 1 : 10;

			if (cgn_slot(slots, id, &off, &ty) != 0)
				return 0;
			a = cgn_load_value(slots, 0, OURO_F(ins, 2));
			b = cgn_load_value(slots, rreg, OURO_F(ins, 3));
			if (a == 0 || b == 0)
				return 0;
			atoms = cgn_cat(a, b);
			if (op == 6 || op == 7) {
				atoms = cgn_cat(atoms, cgn_division(ty, op == 7,
								   block, site));
				return cgn_right(cgn_cat(atoms,
							 cgn_save_off(ty, off, 0)));
			}
			if (op <= 5) {
				static const int arith[6] = { 0, 3, -1, 2, 1, 4 };

				if (op == 2) {
					ouro_v *f[3];

					f[0] = cgn_unit(cgn_bits64(ty) ? 1 : 0);
					f[1] = cgn_unit(0);
					f[2] = ouro_ctor(0, 1, (ouro_v *[]){ cgn_unit(10) });
					atoms = cgn_cat(atoms, cgn_one(cgn_atom(ouro_ctor(12, 3, f))));
				} else {
					atoms = cgn_cat(atoms, cgn_one(cgn_arith_reg(
						cgn_bits64(ty), arith[op], 0, 10)));
				}
			} else {
				unsigned long mask = ty == 0 ? 7UL : (cgn_bits64(ty) ? 63UL : 31UL);
				ouro_v *f[3];

				atoms = cgn_cat(atoms, cgn_one(cgn_arith_imm(0, 2, 1, mask)));
				f[0] = cgn_unit(cgn_bits64(ty) ? 1 : 0);
				f[1] = cgn_unit(op == 9 && ty == 3 ? 2 : (op == 8 ? 0 : 1));
				f[2] = cgn_unit(0);
				atoms = cgn_cat(atoms, cgn_one(cgn_atom(ouro_ctor(16, 3, f))));
			}
			return cgn_right(cgn_cat(atoms, cgn_save_off(ty, off, 0)));
		}
	case 2:
		if (ins->n < 4 || OURO_F(ins, 1) == 0
		    || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		if (cgn_value_ty(slots, OURO_F(ins, 2), &ty) == 0)
			return 0;
		{
			int cond = cgn_cond(ty, OURO_F(ins, 1)->tag);
			ouro_v *yes = cgn_site_label(block, site, 0);
			ouro_v *fin = cgn_site_label(block, site, 1);
			ouro_v *parts[6];
			ouro_v *imm[2];

			if (cond < 0)
				return 0;
			a = cgn_load_value(slots, 0, OURO_F(ins, 2));
			b = cgn_load_value(slots, 10, OURO_F(ins, 3));
			if (a == 0 || b == 0)
				return 0;
			imm[0] = cgn_unit(0);
			imm[1] = cgn_word32(0);
			parts[0] = cgn_arith_reg(cgn_bits64(ty), 5, 0, 10);
			parts[1] = cgn_atom(ouro_ctor(0, 2, imm));
			parts[2] = ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(cond), yes });
			parts[3] = ouro_ctor(2, 1, &fin);
			parts[4] = ouro_ctor(1, 1, &yes);
			imm[1] = cgn_word32(1);
			parts[5] = cgn_atom(ouro_ctor(0, 2, imm));
			atoms = cgn_cat(a, cgn_cat(b, cgasm_list(parts, 6)));
			atoms = cgn_cat(atoms, cgn_one(ouro_ctor(1, 1, &fin)));
			return cgn_right(cgn_cat(atoms, cgn_save(slots, id, 0)));
		}
	case 3:
		if (ins->n < 3 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(ins, 2));
		b = cgn_save(slots, id, 0);
		if (a == 0 || b == 0 || OURO_F(ins, 1) == 0)
			return 0;
		if (OURO_F(ins, 1)->tag == 2) {
			ouro_v *f[2];

			f[0] = cgn_unit(0);
			f[1] = cgn_unit(0);
			a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(7, 2, f))));
		}
		return cgn_right(cgn_cat(a, b));
	case 4:
		if (ins->n < 3 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		if (cgn_slot(slots, id, &off, &ty) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(ins, 1));
		if (a == 0)
			return 0;
		return cgn_right(cgn_cat(a, cgn_cat(
			cgn_one(cgn_mem_load(ty, cgn_base_disp(0, OURO_F(ins, 2)))),
			cgn_save_off(ty, off, 0))));
	case 5:
		if (ins->n < 3)
			return 0;
		if (cgn_value_ty(slots, OURO_F(ins, 2), &ty) == 0)
			return 0;
		a = cgn_load_value(slots, 10, OURO_F(ins, 0));
		b = cgn_load_value(slots, 0, OURO_F(ins, 2));
		if (a == 0 || b == 0)
			return 0;
		return cgn_right(cgn_cat(a, cgn_cat(b, cgn_one(
			cgn_mem_store(ty, cgn_base_disp(10, OURO_F(ins, 1)))))));
	case 6:
		if (ins->n < 3 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		if (cgn_slot(slots, id, &off, &ty) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(ins, 1));
		b = cgn_load_value(slots, 10, OURO_F(ins, 2));
		if (a == 0 || b == 0)
			return 0;
		return cgn_right(cgn_cat(a, cgn_cat(b, cgn_cat(
			cgn_one(cgn_mem_load(ty, cgn_indexed(0, 10))),
			cgn_save_off(ty, off, 0)))));
	case 7:
		if (ins->n < 3)
			return 0;
		if (cgn_value_ty(slots, OURO_F(ins, 2), &ty) == 0)
			return 0;
		a = cgn_load_value(slots, 10, OURO_F(ins, 0));
		b = cgn_load_value(slots, 11, OURO_F(ins, 1));
		atoms = cgn_load_value(slots, 0, OURO_F(ins, 2));
		if (a == 0 || b == 0 || atoms == 0)
			return 0;
		return cgn_right(cgn_cat(a, cgn_cat(b, cgn_cat(atoms, cgn_one(
			cgn_mem_store(ty, cgn_indexed(10, 11)))))));
	case 8:
		if (ins->n < 2 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0
		    || x64enc_dec_nat(OURO_F(ins, 1), &off) != 0)
			return 0;
		{
			int ext = cgn_has_extern(program, off);
			ouro_v *f[2];

			if (ext < 0)
				return 0;
			f[0] = ouro_nat(off);
			f[1] = cgn_unit(ext ? 0 : 1);
			a = cgn_one(ouro_ctor(6, 2, f));
			b = cgn_save(slots, id, 0);
			if (b == 0)
				return 0;
			return cgn_right(cgn_cat(a, b));
		}
	case 9:
		if (ins->n < 3 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(ins, 1));
		b = cgn_load_value(slots, 10, OURO_F(ins, 2));
		if (a == 0 || b == 0)
			return 0;
		return cgn_right(cgn_cat(a, cgn_cat(b, cgn_cat(
			cgn_one(cgn_arith_reg(1, 0, 0, 10)),
			cgn_save(slots, id, 0)))));
	case 10:
		if (ins->n < 4)
			return 0;
		a = call_args != 0 ? cgn_emit_args(slots, call_args->items, call_args->count)
			: cgn_args(slots, OURO_F(ins, 3));
		if (a == 0 || OURO_F(ins, 2) == 0)
			return 0;
		{
			ouro_v *target = OURO_F(ins, 2);
			ouro_v *call;
			ouro_v *bound[2];
			int local;

			if (target->tag == 1 && target->n >= 2) {
				b = cgn_load_value(slots, 11, OURO_F(target, 1));
				if (b == 0)
					return 0;
				{
					ouro_v *op = ouro_ctor(0, 1, (ouro_v *[]){ cgn_unit(11) });

					call = cgn_cat(b, cgn_one(cgn_atom(ouro_ctor(20, 1, &op))));
				}
			} else if (target->tag == 0 && target->n >= 1
				   && x64enc_dec_nat(OURO_F(target, 0), &id) == 0) {
				local = cgn_has_function(program, id);
				if (local < 0)
					return 0;
				call = cgn_one(ouro_ctor(local ? 4 : 5, 1, (ouro_v *[]){ ouro_nat(id) }));
			} else {
				return 0;
			}
			bound[0] = ouro_nat(block);
			bound[1] = ouro_nat(site);
			atoms = cgn_cat(a, cgn_cat(call, cgn_one(ouro_ctor(7, 2, bound))));
			if (OURO_F(ins, 1) != 0 && OURO_F(ins, 1)->tag == 1
			    && OURO_F(ins, 1)->n >= 1
			    && x64enc_dec_nat(OURO_F(OURO_F(ins, 1), 0), &id) == 0) {
				b = cgn_save(slots, id, 0);
				if (b == 0)
					return 0;
				atoms = cgn_cat(atoms, b);
			}
			return cgn_right(atoms);
		}
	case 11:
		if (ins->n < 5 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		{
			unsigned long allocator;
			unsigned long collector;
			unsigned long descriptor;
			ouro_v *collect;
			ouro_v *allocate;
			ouro_v *bytes;

			if (x64enc_dec_nat(OURO_F(ins, 1), &allocator) != 0
			    || x64enc_dec_nat(OURO_F(ins, 2), &collector) != 0
			    || x64enc_dec_nat(OURO_F(ins, 3), &descriptor) != 0)
				return 0;
			if (cgn_refresh_meta(program) != 0)
				return 0;
			bytes = OURO_F(ins, 4);
			collect = cgn_site_label(block, site, 7);
			allocate = cgn_site_label(block, site, 8);
			a = cgn_one(cgn_sym(g_cgn_runtime_id));
			a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 0, g_cgn_budget_off)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 5, 10, 4096UL)));
			a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(2), collect })));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 3, 10, 4096UL)));
			b = cgn_load_value(slots, 0, bytes);
			if (b == 0)
				return 0;
			a = cgn_cat(a, b);
			a = cgn_cat(a, cgn_one(cgn_arith_reg(1, 5, 10, 0)));
			a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(2), collect })));
			a = cgn_cat(a, cgn_one(ouro_ctor(2, 1, &allocate)));
			a = cgn_cat(a, cgn_one(ouro_ctor(1, 1, &collect)));
			a = cgn_cat(a, cgn_one(cgn_sym(g_cgn_runtime_id)));
			a = cgn_cat(a, cgn_one(cgn_mov(1, 1, 0)));
			a = cgn_cat(a, cgn_one(cgn_direct(collector)));
			a = cgn_cat(a, cgn_one(cgn_bound(block, site)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(0, 5, 0, 1UL)));
			a = cgn_cat(a, cgn_check(4, block, site, 6));
			a = cgn_cat(a, cgn_one(ouro_ctor(1, 1, &allocate)));
			a = cgn_cat(a, cgn_one(cgn_sym(g_cgn_runtime_id)));
			a = cgn_cat(a, cgn_one(cgn_mov(1, 1, 0)));
			a = cgn_cat(a, cgn_one(cgn_sym(descriptor)));
			a = cgn_cat(a, cgn_one(cgn_mov(1, 2, 0)));
			b = cgn_load_value(slots, 8, bytes);
			if (b == 0)
				return 0;
			a = cgn_cat(a, b);
			a = cgn_cat(a, cgn_one(cgn_direct(allocator)));
			a = cgn_cat(a, cgn_one(cgn_bound(block, site)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 5, 0, 0UL)));
			a = cgn_cat(a, cgn_check(5, block, site, 0));
			a = cgn_cat(a, cgn_one(cgn_mov(1, 11, 0)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 2, 0, 7UL)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 5, 0, 0UL)));
			a = cgn_cat(a, cgn_check(4, block, site, 1));
			a = cgn_cat(a, cgn_one(cgn_sym(g_cgn_runtime_id)));
			a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 0, 0)));
			a = cgn_cat(a, cgn_one(cgn_arith_reg(1, 5, 10, 11)));
			a = cgn_cat(a, cgn_check(4, block, site, 2));
			a = cgn_cat(a, cgn_one(cgn_sym(descriptor)));
			a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 11, 0)));
			a = cgn_cat(a, cgn_one(cgn_arith_reg(1, 5, 10, 0)));
			a = cgn_cat(a, cgn_check(4, block, site, 3));
			b = cgn_load_value(slots, 0, bytes);
			if (b == 0)
				return 0;
			a = cgn_cat(a, b);
			a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 11, 8)));
			a = cgn_cat(a, cgn_one(cgn_arith_reg(1, 5, 10, 0)));
			a = cgn_cat(a, cgn_check(4, block, site, 4));
			a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 11, 24)));
			a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 5, 10, 0UL)));
			a = cgn_cat(a, cgn_check(4, block, site, 5));
			b = cgn_save(slots, id, 11);
			if (b == 0)
				return 0;
			return cgn_right(cgn_cat(a, b));
		}
	case 12:
		if (ins->n < 1 || x64enc_dec_nat(OURO_F(ins, 0), &id) != 0)
			return 0;
		if (cgn_refresh_meta(program) != 0)
			return 0;
		a = cgn_one(cgn_sym(g_cgn_runtime_id));
		b = cgn_save(slots, id, 0);
		if (b == 0)
			return 0;
		return cgn_right(cgn_cat(a, b));
	default:
		return 0;
	}
}

static ouro_v *cgn_block_label(unsigned long id)
{
	ouro_v *n = ouro_nat(id);

	return ouro_ctor(0, 1, &n);
}

static ouro_v *cgn_jump_block(unsigned long id)
{
	ouro_v *lab = cgn_block_label(id);

	return ouro_ctor(2, 1, &lab);
}

static ouro_v *cgn_mark_block(unsigned long id)
{
	ouro_v *lab = cgn_block_label(id);

	return ouro_ctor(1, 1, &lab);
}

static ouro_v *cgn_lea(int reg, ouro_v *addr)
{
	ouro_v *f[2];

	f[0] = cgn_unit(reg);
	f[1] = addr;
	return cgn_atom(ouro_ctor(9, 2, f));
}

static int cgb_is_root_slot(ouro_v *slot)
{
	return slot != 0 && slot->n >= 2 && OURO_F(slot, 1) != 0
		&& OURO_F(slot, 1)->tag == 6;
}

static int cgb_slot_roots(cgn_frame_slots *slots)
{
	ouro_v **stack = 0;
	ouro_v *cur = slots->source;
	ouro_v *item;
	int depth = 0;
	int capacity = 0;
	int step;
	int roots = 0;

	if (slots->roots != CGN_ROOTS_UNKNOWN)
		return slots->roots == CGN_ROOTS_PRESENT;
	while ((step = host_list_next_g(&stack, &depth, &capacity, &cur, &item)) > 0)
		roots |= cgb_is_root_slot(item);
	free(stack);
	if (step < 0)
		return -1;
	slots->roots = roots ? CGN_ROOTS_PRESENT : CGN_ROOTS_ABSENT;
	return roots;
}

static ouro_v *cgb_shadow_leave(ouro_v *program, unsigned long allocation,
				cgn_frame_slots *slots, unsigned long block,
				unsigned long site)
{
	int roots = cgb_slot_roots(slots);
	unsigned long off;
	ouro_v *valid;
	ouro_v *a;

	if (roots < 0)
		return 0;
	if (roots == 0)
		return ouro_ctor(0, 0, 0);
	if (allocation < 24UL || cgn_refresh_meta(program) != 0)
		return 0;
	off = allocation - 24UL;
	valid = cgn_site_label(block, site, 16);
	a = cgn_one(cgn_sym(g_cgn_runtime_id));
	a = cgn_cat(a, cgn_one(cgn_lea(10, cgn_base(4, off))));
	a = cgn_cat(a, cgn_one(cgn_load_abs(1, 11, 0, 8)));
	a = cgn_cat(a, cgn_one(cgn_arith_reg(1, 5, 10, 11)));
	a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){ cgn_unit(4), valid })));
	a = cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(25, 0, 0))));
	a = cgn_cat(a, cgn_one(ouro_ctor(1, 1, &valid)));
	a = cgn_cat(a, cgn_one(cgn_load(1, 10, cgn_base(4, off))));
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(0, 8), 10)));
	return a;
}

static ouro_v *cgb_term(ouro_v *program, cgn_frame_slots *slots,
			unsigned long allocation, unsigned long block,
			unsigned long site, ouro_v *term)
{
	unsigned long target;
	unsigned long yes;
	unsigned long no;
	ouro_v *a;
	ouro_v *b;

	if (term == 0)
		return 0;
	if (term->tag == 0) {
		if (term->n < 1 || x64enc_dec_nat(OURO_F(term, 0), &target) != 0)
			return 0;
		return cgn_one(cgn_jump_block(target));
	}
	if (term->tag == 1) {
		if (term->n < 3
		    || x64enc_dec_nat(OURO_F(term, 1), &yes) != 0
		    || x64enc_dec_nat(OURO_F(term, 2), &no) != 0)
			return 0;
		a = cgn_load_value(slots, 0, OURO_F(term, 0));
		if (a == 0)
			return 0;
		a = cgn_cat(a, cgn_one(cgn_arith_imm(0, 5, 0, 0UL)));
		a = cgn_cat(a, cgn_one(ouro_ctor(3, 2, (ouro_v *[]){
			cgn_unit(5), cgn_block_label(yes) })));
		return cgn_cat(a, cgn_one(cgn_jump_block(no)));
	}
	if (term->tag == 2) {
		a = cgb_shadow_leave(program, allocation, slots, block, site);
		if (a == 0 || term->n < 1 || OURO_F(term, 0) == 0)
			return 0;
		if (OURO_F(term, 0)->tag == 1 && OURO_F(term, 0)->n >= 1) {
			b = cgn_load_value(slots, 0, OURO_F(OURO_F(term, 0), 0));
			if (b == 0)
				return 0;
			a = cgn_cat(a, b);
		} else if (OURO_F(term, 0)->tag != 0) {
			return 0;
		}
		a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 0, 4, allocation)));
		return cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(24, 0, 0))));
	}
	if (term->tag == 3)
		return cgn_one(cgn_atom(ouro_ctor(25, 0, 0)));
	return 0;
}

static int cgb_tail_move(ouro_v *ins, unsigned long *cur)
{
	unsigned long dest;
	unsigned long src;

	if (ins == 0 || ins->tag != 0 || ins->n < 2)
		return 0;
	if (x64enc_dec_nat(OURO_F(ins, 0), &dest) != 0
	    || OURO_F(ins, 1) == 0 || OURO_F(ins, 1)->tag != 0
	    || OURO_F(ins, 1)->n < 1
	    || x64enc_dec_nat(OURO_F(OURO_F(ins, 1), 0), &src) != 0
	    || src != *cur)
		return 0;
	*cur = dest;
	return 1;
}

typedef struct {
	ouro_v *source;
	ouro_v **entries;
	int count;
	cgn_id_position *positions;
	int position_count;
	size_t scanned;
	int index_attempted;
	/* The generated export getters retain these callbacks for the image lifetime. */
	ouro_v *annotate;
	ouro_v *clear_roots;
} cgb_block_context;

enum { CGB_BLOCK_INDEX_MIN = 16 };

static int cgb_block_id(ouro_v *block, unsigned long *id)
{
	return block != 0 && block->n >= 1 && x64enc_dec_nat(OURO_F(block, 0), id) == 0;
}

static void cgb_index_blocks(cgb_block_context *blocks)
{
	cgn_id_position *positions;
	int count = 0;
	int ordered = 1;
	int i;
	blocks->index_attempted = 1;
	if ((size_t)blocks->count > SIZE_MAX / sizeof *positions)
		return;
	positions = (cgn_id_position *)malloc((size_t)blocks->count * sizeof *positions);
	if (positions == 0)
		return;
	for (i = 0; i < blocks->count; i++) {
		ouro_v *block = blocks->entries[i];
		ouro_v *id;

		if (block == 0 || block->n < 1)
			continue;
		id = OURO_F(block, 0);
		/* Leave unpacked Nat decoding to the original lookup. */
		if (id == 0 || id->tag != OURO_TAG_NAT || id->n < 0) {
			free(positions);
			return;
		}
		if (count > 0 && positions[count - 1].id > (unsigned long)id->n)
			ordered = 0;
		positions[count++] = (cgn_id_position){(unsigned long)id->n, i};
	}
	if (!ordered)
		qsort(positions, (size_t)count, sizeof *positions, cgn_id_position_order);
	blocks->positions = positions;
	blocks->position_count = count;
}

static ouro_v *cgb_find_block(cgb_block_context *blocks, unsigned long id)
{
	int i;
	int can_index = blocks->count >= CGB_BLOCK_INDEX_MIN && !blocks->index_attempted;

	/* Defer allocation until linear lookups have visited at least count entries. */
	if (can_index && blocks->scanned >= (size_t)blocks->count) {
		cgb_index_blocks(blocks);
		can_index = 0;
	}
	if (blocks->positions != 0) {
		i = cgn_find_id_position(blocks->positions, blocks->position_count, id);
		return i >= 0 ? blocks->entries[i] : 0;
	}
	for (i = 0; i < blocks->count; i++) {
		unsigned long bid;

		if (cgb_block_id(blocks->entries[i], &bid) && bid == id)
			break;
	}
	if (can_index)
		blocks->scanned += (size_t)i + (i < blocks->count);
	return i < blocks->count ? blocks->entries[i] : 0;
}

static int cgb_tail_return(cgb_block_context *blocks, unsigned long fuel,
			   unsigned long value, ouro_v *term)
{
	ouro_v **stack = 0;
	int capacity = 0;
	int matched = 0;

	while (fuel > 0UL && term != 0) {
		unsigned long target;
		ouro_v *blk;
		ouro_v *instructions;
		ouro_v *instruction;
		int depth = 0;
		int step;

		if (term->tag == 2) {
			ouro_v *payload;
			unsigned long id;

			if (term->n < 1 || OURO_F(term, 0) == 0
			    || OURO_F(term, 0)->tag != 1 || OURO_F(term, 0)->n < 1)
				break;
			payload = OURO_F(OURO_F(term, 0), 0);
			matched = payload != 0 && payload->tag == 0 && payload->n >= 1
				&& x64enc_dec_nat(OURO_F(payload, 0), &id) == 0 && id == value;
			break;
		}
		if (term->tag != 0 || term->n < 1
		    || x64enc_dec_nat(OURO_F(term, 0), &target) != 0)
			break;
		blk = cgb_find_block(blocks, target);
		if (blk == 0 || blk->n < 3)
			break;
		instructions = OURO_F(blk, 1);
		while ((step = host_list_next_g(&stack, &depth, &capacity,
						&instructions, &instruction)) > 0)
			if (!cgb_tail_move(instruction, &value))
				break;
		if (step != 0)
			break;
		term = OURO_F(blk, 2);
		fuel--;
	}
	free(stack);
	return matched;
}

static int cgb_tail_result(cgb_block_context *blocks, ouro_v *term,
			   unsigned long value, ouro_v **insns, int from, int n)
{
	unsigned long cur = value;
	int i;

	for (i = from; i < n; i++) {
		if (!cgb_tail_move(insns[i], &cur))
			return 0;
	}
	return cgb_tail_return(blocks, (unsigned long)blocks->count + 1UL,
			       cur, term);
}

static ouro_v *cgb_tail_call(ouro_v *program, cgn_frame_slots *slots,
			     unsigned long allocation, unsigned long block,
			     unsigned long site, ouro_v *target, ouro_v *const *args, int nargs)
{
	ouro_v *a;
	ouro_v *b;
	unsigned long home = allocation + 8UL;
	unsigned long id;
	int local;

	a = cgb_shadow_leave(program, allocation, slots, block, site);
	if (a == 0 || target == 0)
		return 0;
	if (target->tag == 1 && target->n >= 2) {
		b = cgn_load_value(slots, 0, OURO_F(target, 1));
		if (b == 0)
			return 0;
		a = cgn_cat(a, b);
	} else if (target->tag == 0 && target->n >= 1
		   && x64enc_dec_nat(OURO_F(target, 0), &id) == 0) {
		local = cgn_has_function(program, id);
		if (local < 0)
			return 0;
		a = cgn_cat(a, cgn_one(ouro_ctor(6, 2, (ouro_v *[]){
			ouro_nat(id), cgn_unit(local ? 1 : 0) })));
	} else {
		return 0;
	}
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(4, home), 0)));
	b = cgn_emit_args(slots, args, nargs);
	if (b == 0)
		return 0;
	a = cgn_cat(a, b);
	a = cgn_cat(a, cgn_one(cgn_lea(11, cgn_base(4, home))));
	a = cgn_cat(a, cgn_one(cgn_arith_imm(1, 0, 4, allocation)));
	return cgn_cat(a, cgn_one(cgn_atom(ouro_ctor(26, 1, (ouro_v *[]){
		cgn_base(11, 0) }))));
}

static ouro_v *cgb_ins_atoms(ouro_v *program, cgn_frame_slots *slots,
			     unsigned long block, unsigned long site, ouro_v *ins,
			     const cgn_call_args *call_args)
{
	ouro_v *fast = cgi_try(program, slots, ouro_nat(block),
			       ouro_nat(site), ins, call_args);
	ouro_v *raw;

	if (fast != 0) {
		g_cgi_count++;
		if (g_cgi_count == 1UL || (g_cgi_count % 10000UL) == 0UL)
			fe_progress("n1-host: ins-c %lu\n", g_cgi_count);
		if (fast->tag != 1 || fast->n < 1)
			return 0;
		return OURO_F(fast, 0);
	}
	g_cgi_fallback++;
	if (g_cgi_fallback <= 8UL)
		fe_progress("n1-host: ins fallback tag=%d n=%lu\n",
			ins == 0 ? -1 : ins->tag, g_cgi_fallback);
	if (g_raw_cgi == 0)
		return 0;
	raw = ouro_apply(ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		g_raw_cgi, program), slots->source), ouro_nat(block)),
		ouro_nat(site)), ins);
	if (raw == 0 || raw->tag != 1 || raw->n < 1)
		return 0;
	return OURO_F(raw, 0);
}

static unsigned long g_cgb_count;
static unsigned long g_cgb_fallback;
static ouro_v *g_raw_cgb;

static int cgb_collect_blocks(cgb_block_context *blocks)
{
	return host_list_collect(blocks->source, &blocks->entries, &blocks->count, 0);
}

static void cgb_release_blocks(cgb_block_context *blocks)
{
	free(blocks->positions);
	free(blocks->entries);
}

static ouro_v *cgb_emit_block(ouro_v *program, cgn_frame_slots *slots, ouro_v *allocv,
			      ouro_v *facts, cgb_block_context *blocks, ouro_v *block)
{
	unsigned long allocation;
	unsigned long id;
	unsigned long site;
	ouro_v **insns = 0;
	ouro_v **annotated = 0;
	ouro_v *atoms;
	ouro_v *part;
	int n = 0;
	int nannotated = 0;
	int cons_list;
	int needs_annotations;
	int i;

	if (block == 0 || block->n < 3
	    || x64enc_dec_nat(allocv, &allocation) != 0
	    || x64enc_dec_nat(OURO_F(block, 0), &id) != 0)
		return 0;
	if (host_list_collect(OURO_F(block, 1), &insns, &n, &cons_list) != 0) {
		free(insns);
		return 0;
	}
	if (blocks->entries == 0 && cgb_collect_blocks(blocks) != 0) {
		free(insns);
		return 0;
	}
	/* Without roots the callback adds an empty live set to every instruction. */
	needs_annotations = slots->roots != CGN_ROOTS_SCALAR_FRAME || block->tag != 0
		|| block->n != 3 || !cons_list;
	if (needs_annotations) {
		if (blocks->annotate == 0)
			blocks->annotate = FIND(lo, "codegen_live_instructions");
		part = ouro_apply(ouro_apply(ouro_apply(blocks->annotate, slots->source),
					     facts), block);
		if (part != 0 && part->tag == 0 && part->n == 1) {
			free(insns);
			return part;
		}
		if (part == 0 || part->tag != 1 || part->n != 1
		    || host_list_collect(OURO_F(part, 0), &annotated, &nannotated, 0) != 0
		    || nannotated != n) {
			free(insns);
			free(annotated);
			return 0;
		}
	}
	atoms = cgn_one(cgn_mark_block(id));
	for (i = 0; i < n; i++) {
		ouro_v *ins = insns[i];
		cgn_call_args call_args = { 0 };
		int args_ready = 0;
		unsigned long dest;
		ouro_v *annotation = needs_annotations ? annotated[i] : 0;

		if (needs_annotations && (annotation == 0 || annotation->tag != 0
					  || annotation->n != 2)) {
			free(insns);
			free(annotated);
			return 0;
		}

		site = (unsigned long)i;
		if (ins != 0 && ins->tag == 10 && ins->n >= 4
		    && OURO_F(ins, 1) != 0 && OURO_F(ins, 1)->tag == 1
		    && OURO_F(ins, 1)->n >= 1
		    && x64enc_dec_nat(OURO_F(OURO_F(ins, 1), 0), &dest) == 0) {
			args_ready = host_list_collect(OURO_F(ins, 3), &call_args.items,
						       &call_args.count, 0) == 0;
			if (!args_ready) {
				free(call_args.items);
				call_args.items = 0;
			}
		}
		if (args_ready && call_args.count <= 4
		    && cgb_tail_result(blocks, OURO_F(block, 2),
				       dest, insns, i + 1, n)) {
			part = cgb_tail_call(program, slots, allocation, id,
					     site, OURO_F(ins, 2), call_args.items, call_args.count);
			free(call_args.items);
			if (part == 0) {
				free(insns);
				free(annotated);
				return 0;
			}
			atoms = cgn_cat(atoms, part);
			free(insns);
			free(annotated);
			return cgn_right(atoms);
		}
		if (needs_annotations && ins != 0 && (ins->tag == 11
		    || (ins->tag == 10 && ins->n >= 1
			&& OURO_F(ins, 0) != 0 && OURO_F(ins, 0)->tag == 1))) {
			if (blocks->clear_roots == 0)
				blocks->clear_roots = FIND(lo, "codegen_clear_dead_roots");
			part = ouro_apply(ouro_apply(blocks->clear_roots,
				slots->source), OURO_F(annotation, 1));
			atoms = cgn_cat(atoms, part);
		}
		part = cgb_ins_atoms(program, slots, id, site, ins, args_ready ? &call_args : 0);
		free(call_args.items);
		if (part == 0) {
			free(insns);
			free(annotated);
			return 0;
		}
		atoms = cgn_cat(atoms, part);
	}
	part = cgb_term(program, slots, allocation, id, (unsigned long)n,
			OURO_F(block, 2));
	free(insns);
	free(annotated);
	if (part == 0)
		return 0;
	return cgn_right(cgn_cat(atoms, part));
}

static ouro_v *cgb_try(ouro_v *program, ouro_v *slots, ouro_v *allocv,
		       ouro_v *facts, ouro_v *blocksv, ouro_v *block)
{
	cgn_frame_slots frame = { .source = slots };
	cgb_block_context blocks = { .source = blocksv };
	ouro_v *result = cgb_emit_block(program, &frame, allocv, facts, &blocks, block);

	cgb_release_blocks(&blocks);
	free(frame.entries);
	return result;
}

static ouro_v *cgb_block(ouro_env *env, ouro_v *block)
{
	ouro_v *fast = cgb_try(ouro_get(env, 4), ouro_get(env, 3),
			       ouro_get(env, 2), ouro_get(env, 1),
			       ouro_get(env, 0), block);

	if (fast != 0) {
		g_cgb_count++;
		if (g_cgb_count == 1UL || (g_cgb_count % 1000UL) == 0UL)
			fe_progress("n1-host: blk-c %lu\n", g_cgb_count);
		return fast;
	}
	g_cgb_fallback++;
	if (g_cgb_fallback <= 8UL)
		fe_progress("n1-host: blk fallback n=%lu\n", g_cgb_fallback);
	return ouro_apply(ouro_apply(ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		g_raw_cgb, ouro_get(env, 4)), ouro_get(env, 3)),
		ouro_get(env, 2)), ouro_get(env, 1)), ouro_get(env, 0)), block);
}

static ouro_v *cgb_blocks(ouro_env *env, ouro_v *blocks)
{
	return ouro_clos(cgb_block, ouro_cons(blocks, env));
}

static ouro_v *cgb_facts(ouro_env *env, ouro_v *facts)
{
	return ouro_clos(cgb_blocks, ouro_cons(facts, env));
}

static ouro_v *cgb_alloc(ouro_env *env, ouro_v *allocation)
{
	return ouro_clos(cgb_facts, ouro_cons(allocation, env));
}

static ouro_v *cgb_slots(ouro_env *env, ouro_v *slots)
{
	return ouro_clos(cgb_alloc, ouro_cons(slots, env));
}

static ouro_v *cgb_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(cgb_slots, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_codegen_block(ouro_v *raw)
{
	g_raw_cgb = raw;
	g_cgb_count = 0;
	g_cgb_fallback = 0;
	return ouro_clos(cgb_program, 0);
}

static ouro_v *cgn_movimm32(int reg, unsigned long imm)
{
	ouro_v *f[2];

	f[0] = cgn_unit(reg);
	f[1] = cgn_word32(imm);
	return cgn_atom(ouro_ctor(0, 2, f));
}

static int cgb_is_scalar_slot(ouro_v *slot)
{
	ouro_v *type;

	if (slot == 0 || slot->tag != 0 || slot->n != 3)
		return 0;
	type = OURO_F(slot, 1);
	return type != 0 && type->n == 0 && type->tag >= 0 && type->tag < 6;
}

static ouro_v *cgb_zero_roots(cgn_frame_slots *slots)
{
	ouro_v **items = 0;
	ouro_v *out = 0;
	int n = 0;
	int cons_list;
	int i;
	int roots = 0;
	int scalar_frame = 1;

	if (host_list_collect(slots->source, &items, &n, &cons_list) != 0) {
		free(items);
		return 0;
	}
	for (i = 0; i < n; i++) {
		unsigned long off;

		if (!cgb_is_root_slot(items[i])) {
			scalar_frame = scalar_frame && cgb_is_scalar_slot(items[i]);
			continue;
		}
		if (!roots) {
			out = cgn_one(cgn_movimm32(0, 0UL));
			roots = 1;
		}
		if (items[i]->n < 3)
			continue;
		if (x64enc_dec_nat(OURO_F(items[i], 2), &off) != 0) {
			free(items);
			return 0;
		}
		out = cgn_cat(out, cgn_one(cgn_store(1, cgn_base(4, off), 0)));
	}
	free(items);
	slots->roots = CGN_ROOTS_ABSENT;
	if (roots)
		slots->roots = CGN_ROOTS_PRESENT;
	else if (scalar_frame && cons_list)
		slots->roots = CGN_ROOTS_SCALAR_FRAME;
	return roots ? out : ouro_ctor(0, 0, 0);
}

static ouro_v *cgb_spill(cgn_frame_slots *slots, unsigned long allocation, ouro_v *args)
{
	ouro_v **items = 0;
	ouro_v *out;
	int n = 0;
	int i;
	static const int argreg[4] = { 1, 2, 8, 9 };

	if (host_list_collect(args, &items, &n, 0) != 0) {
		free(items);
		return 0;
	}
	out = ouro_ctor(0, 0, 0);
	for (i = 0; i < n; i++) {
		unsigned long id;
		ouro_v *save;

		if (items[i] == 0 || items[i]->n < 1
		    || x64enc_dec_nat(OURO_F(items[i], 0), &id) != 0) {
			free(items);
			return 0;
		}
		if (i < 4)
			out = cgn_cat(out, cgn_one(cgn_mov(1, 0, argreg[i])));
		else
			out = cgn_cat(out, cgn_one(cgn_load(1, 0, cgn_base(4,
				allocation + 8UL + (unsigned long)i * 8UL))));
		save = cgn_save(slots, id, 0);
		if (save == 0) {
			free(items);
			return 0;
		}
		out = cgn_cat(out, save);
	}
	free(items);
	return out;
}

static unsigned long cgb_descriptor_kind(int index)
{
	unsigned long id = g_cgn_alldesc[index];
	int i;

	if (index < g_cgn_nobj)
		return 1UL;
	if (id > g_cgn_max_object_id)
		return 2UL;
	/* Preserve object precedence if a frame ID also appears in the object prefix. */
	for (i = 0; i < g_cgn_nobj; i++) {
		if (g_cgn_alldesc[i] == id)
			return 1UL;
	}
	return 2UL;
}

static ouro_v *cgb_runtime_init(unsigned long id)
{
	ouro_v *a;
	int i;
	unsigned long off = 40UL;

	if (id != g_cgn_entry || g_cgn_nall <= 0)
		return ouro_ctor(0, 0, 0);
	a = cgn_one(cgn_sym(g_cgn_runtime_id));
	a = cgn_cat(a, cgn_one(cgn_mov(1, 10, 0)));
	a = cgn_cat(a, cgn_one(cgn_movimm32(0, (unsigned long)g_cgn_nall)));
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(10, 32), 0)));
	for (i = 0; i < g_cgn_nall; i++) {
		a = cgn_cat(a, cgn_one(cgn_sym(g_cgn_alldesc[i])));
		a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(10, off), 0)));
		a = cgn_cat(a, cgn_one(cgn_movimm32(0, cgb_descriptor_kind(i))));
		a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(10, off + 8UL), 0)));
		off += 16UL;
	}
	return a;
}

static ouro_v *cgb_shadow_enter(unsigned long allocation, unsigned long index)
{
	unsigned long off;
	unsigned long desc;
	ouro_v *a;

	if (allocation < 24UL)
		return 0;
	off = allocation - 24UL;
	desc = g_cgn_runtime_id + 1UL + index;
	a = cgn_one(cgn_sym(g_cgn_runtime_id));
	a = cgn_cat(a, cgn_one(cgn_load_abs(1, 10, 0, 8)));
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(4, off), 10)));
	a = cgn_cat(a, cgn_one(cgn_sym(desc)));
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(4, off + 8UL), 0)));
	a = cgn_cat(a, cgn_one(cgn_store(1, cgn_base(4, off + 16UL), 4)));
	a = cgn_cat(a, cgn_one(cgn_lea(10, cgn_base(4, off))));
	a = cgn_cat(a, cgn_one(cgn_sym(g_cgn_runtime_id)));
	return cgn_cat(a, cgn_one(cgn_store(1, cgn_base(0, 8), 10)));
}

static int cgb_fn_index(ouro_v *program, unsigned long id, unsigned long *index)
{
	ouro_v **fns = 0;
	int n = 0;
	int i;

	if (cgn_find_pinned_function(program, id, &i)) {
		if (i < 0)
			return -1;
		*index = (unsigned long)i;
		return 0;
	}
	if (program == 0 || program->n < 1)
		return -1;
	if (host_list_collect(OURO_F(program, 0), &fns, &n, 0) != 0) {
		free(fns);
		return -1;
	}
	for (i = 0; i < n; i++) {
		unsigned long fid;

		if (fns[i] != 0 && fns[i]->n >= 1
		    && x64enc_dec_nat(OURO_F(fns[i], 0), &fid) == 0
		    && fid == id) {
			free(fns);
			*index = (unsigned long)i;
			return 0;
		}
	}
	free(fns);
	return -1;
}

static unsigned long g_cbody_count;
static unsigned long g_cbody_fallback;
static ouro_v *g_raw_cbody;

static ouro_v *cgb_emit_body(ouro_v *program, ouro_v *function, ouro_v *frame,
			     cgn_frame_slots *slots, cgb_block_context *blocks)
{
	unsigned long id;
	unsigned long entry;
	unsigned long allocation;
	unsigned long index;
	ouro_v *atoms;
	ouro_v *part;
	ouro_v *facts = ouro_ctor(0, 0, 0);
	int i;
	int roots;

	if (function == 0 || function->n < 7)
		return 0;
	if (x64enc_dec_nat(OURO_F(function, 0), &id) != 0
	    || x64enc_dec_nat(OURO_F(function, 5), &entry) != 0
	    || x64enc_dec_nat(OURO_F(frame, 0), &allocation) != 0)
		return 0;
	blocks->source = OURO_F(function, 6);
	if (cgn_refresh_meta(program) != 0)
		return 0;
	roots = cgn_fn_has_roots(function);
	if (roots < 0)
		return 0;
	if (roots) {
		ouro_v *analyzed;
		ouro_v *root_ids;
		if (cgb_collect_blocks(blocks) != 0)
			return 0;
		root_ids = ouro_apply(FIND(lo, "mir_live_roots"), function);
		analyzed = live_exact(ouro_nat((unsigned long)blocks->count + 1UL),
				      root_ids, blocks->source);
		if (analyzed != 0 && analyzed->tag == 0 && analyzed->n == 1) {
			ouro_v *error = OURO_F(analyzed, 0);
			error = ouro_ctor(0, 1, &error); /* NativeMirError */
			return ouro_ctor(0, 1, &error);
		}
		if (analyzed == 0 || analyzed->tag != 1 || analyzed->n != 1)
			return 0;
		facts = OURO_F(analyzed, 0);
	}
	atoms = cgb_zero_roots(slots);
	part = cgb_spill(slots, allocation, OURO_F(function, 2));
	if (atoms == 0 || part == 0)
		return 0;
	atoms = cgn_cat(atoms, part);
	part = cgb_runtime_init(id);
	if (part == 0)
		return 0;
	atoms = cgn_cat(atoms, part);
	if (roots) {
		if (cgb_fn_index(program, id, &index) != 0)
			return 0;
		part = cgb_shadow_enter(allocation, index);
		if (part == 0)
			return 0;
		atoms = cgn_cat(atoms, part);
	}
	atoms = cgn_cat(atoms, cgn_one(cgn_jump_block(entry)));
	if (!roots && cgb_collect_blocks(blocks) != 0)
		return 0;
	for (i = 0; i < blocks->count; i++) {
		part = cgb_emit_block(program, slots, ouro_nat(allocation), facts, blocks,
				      blocks->entries[i]);
		if (part == 0 || part->tag != 1 || part->n < 1)
			return 0;
		atoms = cgn_cat(atoms, OURO_F(part, 0));
	}
	return cgn_right(atoms);
}

static ouro_v *cgb_body_try(ouro_v *program, ouro_v *function, ouro_v *frame)
{
	cgn_frame_slots slots = { 0 };
	cgb_block_context blocks = { 0 };
	ouro_v *result;

	if (frame == 0 || frame->n < 2)
		return 0;
	slots.source = OURO_F(frame, 1);
	result = cgb_emit_body(program, function, frame, &slots, &blocks);
	cgb_release_blocks(&blocks);
	free(slots.entries);
	return result;
}

static ouro_v *cbody_frame(ouro_env *env, ouro_v *frame)
{
	ouro_v *fast = cgb_body_try(ouro_get(env, 1), ouro_get(env, 0), frame);

	if (fast != 0) {
		g_cbody_count++;
		if (g_cbody_count == 1UL || (g_cbody_count % 25UL) == 0UL)
			fe_progress("n1-host: body-c %lu\n", g_cbody_count);
		return fast;
	}
	g_cbody_fallback++;
	if (g_cbody_fallback <= 8UL)
		fe_progress("n1-host: body fallback n=%lu\n",
			g_cbody_fallback);
	return ouro_apply(ouro_apply(ouro_apply(g_raw_cbody, ouro_get(env, 1)),
				     ouro_get(env, 0)), frame);
}

static ouro_v *cbody_function(ouro_env *env, ouro_v *function)
{
	return ouro_clos(cbody_frame, ouro_cons(function, env));
}

static ouro_v *cbody_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(cbody_function, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_codegen_body(ouro_v *raw)
{
	g_raw_cbody = raw;
	g_cbody_count = 0;
	g_cbody_fallback = 0;
	return ouro_clos(cbody_program, 0);
}

static ouro_v *cgi_ins(ouro_env *env, ouro_v *ins)
{
	cgn_frame_slots slots = { .source = ouro_get(env, 2) };
	ouro_v *fast = cgi_try(ouro_get(env, 3), &slots,
			       ouro_get(env, 1), ouro_get(env, 0), ins, 0);

	free(slots.entries);
	if (fast != 0) {
		g_cgi_count++;
		if (g_cgi_count == 1UL || (g_cgi_count % 10000UL) == 0UL)
			fe_progress("n1-host: ins-c %lu\n", g_cgi_count);
		return fast;
	}
	g_cgi_fallback++;
	if (g_cgi_fallback <= 8UL)
		fe_progress("n1-host: ins fallback tag=%d n=%lu\n",
			ins == 0 ? -1 : ins->tag, g_cgi_fallback);
	return ouro_apply(ouro_apply(ouro_apply(ouro_apply(ouro_apply(
		g_raw_cgi, ouro_get(env, 3)), ouro_get(env, 2)),
		ouro_get(env, 1)), ouro_get(env, 0)), ins);
}

static ouro_v *cgi_site(ouro_env *env, ouro_v *site)
{
	return ouro_clos(cgi_ins, ouro_cons(site, env));
}

static ouro_v *cgi_block(ouro_env *env, ouro_v *block)
{
	return ouro_clos(cgi_site, ouro_cons(block, env));
}

static ouro_v *cgi_slots(ouro_env *env, ouro_v *slots)
{
	return ouro_clos(cgi_block, ouro_cons(slots, env));
}

static ouro_v *cgi_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(cgi_slots, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_codegen_instruction(ouro_v *raw)
{
	g_raw_cgi = raw;
	g_cgi_count = 0;
	g_cgi_fallback = 0;
	g_cgn_prog = 0;
	g_cgn_meta_ok = 0;
	return ouro_clos(cgi_program, 0);
}

#define GCINF_ID_MAX 65536

static ouro_v *g_raw_gc_infer;
static unsigned long g_gcinf_count;

static int gcinf_bit(const unsigned char *bits, unsigned long id)
{
	return id < GCINF_ID_MAX && bits[id] != 0;
}

static int gcinf_set(unsigned char *bits, unsigned long id)
{
	if (id >= GCINF_ID_MAX)
		return 0;
	bits[id] = 1;
	return 1;
}

static int gcinf_load_ids(ouro_v *list, unsigned char *bits)
{
	ouro_v *stack[64];
	ouro_v *cur = list;
	ouro_v *item;
	int sp = 0;
	int step;
	unsigned long id;

	for (;;) {
		step = host_list_next(stack, &sp, &cur, &item);
		if (step == 0)
			return 0;
		if (step < 0 || item == 0)
			return -1;
		if (x64enc_dec_nat(item, &id) != 0 || !gcinf_set(bits, id))
			return -1;
	}
}

static int gcinf_load_externs(ouro_v *program, unsigned char *ext_seen,
			      unsigned char *ext_nogc)
{
	ouro_v *stack[64];
	ouro_v *cur;
	ouro_v *lib;
	ouro_v *item;
	int sp = 0;
	int step;
	unsigned long id;

	if (program == 0 || program->n < 3)
		return -1;
	cur = OURO_F(program, 2);
	for (;;) {
		ouro_v *ex;
		ouro_v *estack[64];
		int esp = 0;

		step = host_list_next(stack, &sp, &cur, &lib);
		if (step == 0)
			return 0;
		if (step < 0 || lib == 0 || lib->tag != 0 || lib->n < 2)
			return -1;
		ex = OURO_F(lib, 1);
		for (;;) {
			step = host_list_next(estack, &esp, &ex, &item);
			if (step == 0)
				break;
			if (step < 0 || item == 0 || item->tag != 0
			    || item->n < 2)
				return -1;
			if (x64enc_dec_nat(OURO_F(item, 1), &id) != 0
			    || id >= GCINF_ID_MAX)
				return -1;
			if (!gcinf_set(ext_seen, id))
				return -1;
			if (OURO_F(item, 0) != 0 && OURO_F(item, 0)->tag == 0)
				if (!gcinf_set(ext_nogc, id))
					return -1;
		}
	}
}

static int gcinf_walk_instr(ouro_v *instr, int (*fn)(ouro_v *, void *),
			    void *ctx)
{
	ouro_v *stack[64];
	ouro_v *cur;
	ouro_v *block;
	ouro_v *ins;
	int sp;
	int step;
	int bsp;

	if (instr == 0 || instr->tag != 0 || instr->n < 7)
		return -1;
	cur = OURO_F(instr, 6);
	sp = 0;
	for (;;) {
		step = host_list_next(stack, &sp, &cur, &block);
		if (step == 0)
			return 0;
		if (step < 0 || block == 0 || block->tag != 0 || block->n < 2)
			return -1;
		{
			ouro_v *bstack[64];
			ouro_v *bcur = OURO_F(block, 1);

			bsp = 0;
			for (;;) {
				step = host_list_next(bstack, &bsp, &bcur, &ins);
				if (step == 0)
					break;
				if (step < 0 || ins == 0)
					return -1;
				if (fn(ins, ctx) != 0)
					return -1;
			}
		}
	}
}

static int gcinf_add_collector(ouro_v *ins, void *ctx)
{
	unsigned long id;

	if (ins->tag == 11 && ins->n >= 3) {
		if (x64enc_dec_nat(OURO_F(ins, 2), &id) != 0)
			return -1;
		if (!gcinf_set((unsigned char *)ctx, id))
			return -1;
	}
	return 0;
}

struct gcinf_body {
	unsigned char *collectors;
	unsigned char *bodies;
	unsigned char *ext_seen;
	unsigned char *ext_nogc;
	int ok;
};

static int gcinf_target_nogc(unsigned long id, struct gcinf_body *st)
{
	if (gcinf_bit(st->collectors, id))
		return 0;
	if (gcinf_bit(st->bodies, id))
		return 1;
	if (gcinf_bit(st->ext_seen, id))
		return gcinf_bit(st->ext_nogc, id);
	return 0;
}

static int gcinf_check_instr(ouro_v *ins, void *ctx)
{
	struct gcinf_body *st = (struct gcinf_body *)ctx;
	ouro_v *target;
	unsigned long id;

	if (st->ok == 0)
		return 0;
	if (ins->tag == 11) {
		st->ok = 0;
		return 0;
	}
	if (ins->tag != 10 || ins->n < 3)
		return 0;
	target = OURO_F(ins, 2);
	if (target == 0)
		return -1;
	if (target->tag == 1) {
		st->ok = 0;
		return 0;
	}
	if (target->tag != 0 || target->n < 1)
		return -1;
	if (x64enc_dec_nat(OURO_F(target, 0), &id) != 0)
		return -1;
	if (!gcinf_target_nogc(id, st))
		st->ok = 0;
	return 0;
}

static ouro_v *gcinf_try(ouro_v *fuel, ouro_v *program)
{
	ouro_v *stack[64];
	ouro_v *cur;
	ouro_v *item;
	ouro_v **fns = 0;
	unsigned long *ids = 0;
	int fcap = 0;
	int icap = 0;
	unsigned char *collectors = 0;
	unsigned char *cand = 0;
	unsigned char *ext_seen = 0;
	unsigned char *ext_nogc = 0;
	unsigned char *keep = 0;
	ouro_v **out_ids = 0;
	ouro_v *out = 0;
	unsigned long fuel_n;
	unsigned long id;
	int n = 0;
	int sp = 0;
	int step;
	int i;
	int n_cand;
	int n_keep;
	unsigned long round;

	if (live_fuel_zero(fuel) || program == 0 || program->tag != 0
	    || program->n < 3)
		return 0;
	if (x64enc_dec_nat(fuel, &fuel_n) != 0)
		return 0;
	collectors = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	cand = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_seen = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_nogc = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	keep = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	if (collectors == 0 || cand == 0 || ext_seen == 0
	    || ext_nogc == 0 || keep == 0)
		goto fallback;
	cur = OURO_F(program, 0);
	for (;;) {
		step = host_list_next(stack, &sp, &cur, &item);
		if (step == 0)
			break;
		if (step < 0 || item == 0 || item->tag != 0 || item->n < 1)
			goto fallback;
		if (x64enc_dec_nat(OURO_F(item, 0), &id) != 0 || id >= GCINF_ID_MAX)
			goto fallback;
		if (!cgasm_grow((void **)&fns, &fcap, n + 1, sizeof *fns)
		    || !cgasm_grow((void **)&ids, &icap, n + 1, sizeof *ids))
			goto fallback;
		fns[n] = item;
		ids[n] = id;
		n++;
		if (!gcinf_set(cand, id))
			goto fallback;
		if (gcinf_walk_instr(item, gcinf_add_collector, collectors) != 0)
			goto fallback;
	}
	if (gcinf_load_externs(program, ext_seen, ext_nogc) != 0)
		goto fallback;

	n_cand = n;
	for (round = 0; round < fuel_n; round++) {
		struct gcinf_body st;
		unsigned char *previous;

		memset(keep, 0, GCINF_ID_MAX);
		n_keep = 0;
		st.collectors = collectors;
		/* Calls resolve against the same candidates for the entire round. */
		st.bodies = cand;
		st.ext_seen = ext_seen;
		st.ext_nogc = ext_nogc;
		for (i = 0; i < n; i++) {
			if (!gcinf_bit(cand, ids[i]))
				continue;
			st.ok = 1;
			if (gcinf_walk_instr(fns[i], gcinf_check_instr, &st) != 0)
				goto fallback;
			if (st.ok) {
				keep[ids[i]] = 1;
				n_keep++;
			}
		}
		if (n_keep == n_cand)
			goto done;
		previous = cand;
		cand = keep;
		keep = previous;
		n_cand = n_keep;
	}
	out = cgasm_left(0, 0, 0);
	goto cleanup;

done:
	out_ids = (ouro_v **)malloc((unsigned long)(n_cand + 1) * sizeof *out_ids);
	if (n_cand > 0 && out_ids == 0)
		goto fallback;
	n_keep = 0;
	for (i = 0; i < n; i++) {
		if (!gcinf_bit(cand, ids[i]))
			continue;
		out_ids[n_keep++] = ouro_nat(ids[i]);
	}
	{
		ouro_v *xs = cgasm_list(out_ids, n_keep);

		out = ouro_ctor(1, 1, &xs);
	}
	g_gcinf_count++;
	fe_progress("n1-host: gc-infer-c rounds=%lu bodies=%d\n",
		round + 1UL, n_keep);
	goto cleanup;

fallback:
	out = 0;
cleanup:
	free(fns);
	free(ids);
	free(collectors);
	free(cand);
	free(ext_seen);
	free(ext_nogc);
	free(keep);
	free(out_ids);
	return out;
}

static ouro_v *gcinf_program(ouro_env *env, ouro_v *program)
{
	ouro_v *fuel = ouro_get(env, 0);
	ouro_v *fast = gcinf_try(fuel, program);

	if (fast != 0)
		return fast;
	fe_progress("n1-host: gc-infer fallback\n");
	return ouro_apply(ouro_apply(g_raw_gc_infer, fuel), program);
}

static ouro_v *gcinf_fuel(ouro_env *env, ouro_v *fuel)
{
	(void)env;
	return ouro_clos(gcinf_program, ouro_cons(fuel, 0));
}

ouro_v *ouro_wrap_mir_gc_infer(ouro_v *raw)
{
	g_raw_gc_infer = raw;
	g_gcinf_count = 0;
	return ouro_clos(gcinf_fuel, 0);
}

static ouro_v *g_raw_gc_annotate;
static unsigned long g_gcan_count;
static ouro_v *g_raw_gc_check;
static unsigned long g_gchk_count;

static ouro_v *gcan_gc(int nogc)
{
	return ouro_ctor(nogc ? 0 : 1, 0, 0);
}

static int gcan_call_nogc(ouro_v *ins, struct gcinf_body *st)
{
	ouro_v *target;
	unsigned long id;

	if (ins == 0 || ins->tag != 10 || ins->n < 3)
		return 0;
	target = OURO_F(ins, 2);
	if (target == 0)
		return -1;
	if (target->tag == 1)
		return 0;
	if (target->tag != 0 || target->n < 1)
		return -1;
	if (x64enc_dec_nat(OURO_F(target, 0), &id) != 0)
		return -1;
	return gcinf_target_nogc(id, st) ? 1 : 0;
}

static ouro_v *gcan_try(ouro_v *program, ouro_v *bodies)
{
	unsigned char *collectors = 0;
	unsigned char *body_bits = 0;
	unsigned char *ext_seen = 0;
	unsigned char *ext_nogc = 0;
	ouro_v **fns = 0;
	ouro_v **blocks = 0;
	ouro_v **insns = 0;
	ouro_v *out = 0;
	struct gcinf_body st;
	int nfn = 0;
	int i;
	int b;
	int k;

	if (program == 0 || program->tag != 0 || program->n < 4)
		return 0;
	collectors = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	body_bits = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_seen = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_nogc = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	if (collectors == 0 || body_bits == 0 || ext_seen == 0 || ext_nogc == 0)
		goto fallback;
	if (gcinf_load_ids(bodies, body_bits) != 0)
		goto fallback;
	if (gcinf_load_externs(program, ext_seen, ext_nogc) != 0)
		goto fallback;
	if (host_list_collect(OURO_F(program, 0), &fns, &nfn, 0) != 0)
		goto fallback;
	for (i = 0; i < nfn; i++) {
		if (fns[i] == 0 || fns[i]->tag != 0 || fns[i]->n < 7)
			goto fallback;
		if (gcinf_walk_instr(fns[i], gcinf_add_collector, collectors)
		    != 0)
			goto fallback;
	}
	st.collectors = collectors;
	st.bodies = body_bits;
	st.ext_seen = ext_seen;
	st.ext_nogc = ext_nogc;
	st.ok = 1;
	for (i = 0; i < nfn; i++) {
		ouro_v *fn = fns[i];
		ouro_v *ff[7];
		int nblk = 0;

		if (host_list_collect(OURO_F(fn, 6), &blocks, &nblk, 0) != 0)
			goto fallback;
		for (b = 0; b < nblk; b++) {
			ouro_v *block = blocks[b];
			ouro_v *bf[3];
			int nins = 0;

			if (block == 0 || block->tag != 0 || block->n < 3)
				goto fallback;
			if (host_list_collect(OURO_F(block, 1), &insns, &nins, 0) != 0)
				goto fallback;
			for (k = 0; k < nins; k++) {
				ouro_v *ins = insns[k];
				int nogc;

				if (ins == 0 || ins->tag != 10)
					continue;
				nogc = gcan_call_nogc(ins, &st);
				if (nogc < 0)
					goto fallback;
				if (ins->n < 4)
					goto fallback;
				{
					ouro_v *cf[4];

					cf[0] = gcan_gc(nogc);
					cf[1] = OURO_F(ins, 1);
					cf[2] = OURO_F(ins, 2);
					cf[3] = OURO_F(ins, 3);
					insns[k] = ouro_ctor(10, 4, cf);
				}
			}
			bf[0] = OURO_F(block, 0);
			bf[1] = cgasm_list(insns, nins);
			bf[2] = OURO_F(block, 2);
			blocks[b] = ouro_ctor(0, 3, bf);
			free(insns);
			insns = 0;
		}
		for (k = 0; k < 6; k++)
			ff[k] = OURO_F(fn, k);
		ff[6] = cgasm_list(blocks, nblk);
		fns[i] = ouro_ctor(0, 7, ff);
		free(blocks);
		blocks = 0;
	}
	{
		ouro_v *pf[4];

		pf[0] = cgasm_list(fns, nfn);
		pf[1] = OURO_F(program, 1);
		pf[2] = OURO_F(program, 2);
		pf[3] = OURO_F(program, 3);
		out = ouro_ctor(0, 4, pf);
	}
	g_gcan_count++;
	fe_progress("n1-host: gc-annotate-c functions=%d\n", nfn);
	goto cleanup;

fallback:
	out = 0;
cleanup:
	free(collectors);
	free(body_bits);
	free(ext_seen);
	free(ext_nogc);
	free(fns);
	free(blocks);
	free(insns);
	return out;
}

static ouro_v *gcan_bodies(ouro_env *env, ouro_v *bodies)
{
	ouro_v *program = ouro_get(env, 0);
	ouro_v *fast = gcan_try(program, bodies);

	if (fast != 0)
		return fast;
	fe_progress("n1-host: gc-annotate fallback\n");
	return ouro_apply(ouro_apply(g_raw_gc_annotate, program), bodies);
}

static ouro_v *gcan_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(gcan_bodies, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_mir_gc_annotate(ouro_v *raw)
{
	g_raw_gc_annotate = raw;
	g_gcan_count = 0;
	return ouro_clos(gcan_program, 0);
}

static ouro_v *gchk_left_mismatch(unsigned long caller, unsigned long target)
{
	ouro_v *f[2];
	ouro_v *err;

	f[0] = ouro_nat(caller);
	f[1] = ouro_nat(target);
	err = ouro_ctor(19, 2, f);
	return ouro_ctor(0, 1, &err);
}

static ouro_v *gchk_left_unsafe(unsigned long id)
{
	ouro_v *f = ouro_nat(id);
	ouro_v *err = ouro_ctor(20, 1, &f);

	return ouro_ctor(0, 1, &err);
}

static ouro_v *gchk_right(void)
{
	return mir_right_unit();
}

typedef struct {
	struct gcinf_body facts;
	unsigned long caller;
	ouro_v *error;
} gchk_context;

static int gchk_instruction(ouro_v *ins, void *context)
{
	gchk_context *check = (gchk_context *)context;
	ouro_v *target;
	unsigned long id = 0;
	int nogc;

	if (ins->tag == 11) {
		unsigned long alloc_id;
		unsigned long coll_id;

		if (ins->n < 3 || x64enc_dec_nat(OURO_F(ins, 1), &alloc_id) != 0
		    || x64enc_dec_nat(OURO_F(ins, 2), &coll_id) != 0)
			return -1;
		if (!gcinf_bit(check->facts.bodies, alloc_id))
			check->error = gchk_left_unsafe(alloc_id);
		else if (!gcinf_bit(check->facts.bodies, coll_id))
			check->error = gchk_left_unsafe(coll_id);
		return check->error != 0;
	}
	if (ins->tag != 10 || ins->n < 3
	    || (OURO_F(ins, 0) != 0 && OURO_F(ins, 0)->tag != 0))
		return 0;
	nogc = gcan_call_nogc(ins, &check->facts);
	if (nogc < 0)
		return -1;
	if (nogc)
		return 0;
	target = OURO_F(ins, 2);
	if (target->tag == 0 && x64enc_dec_nat(OURO_F(target, 0), &id) != 0)
		return -1;
	check->error = gchk_left_mismatch(check->caller, id);
	return 1;
}

static ouro_v *gchk_try(ouro_v *program, ouro_v *bodies)
{
	unsigned char *collectors = 0;
	unsigned char *body_bits = 0;
	unsigned char *ext_seen = 0;
	unsigned char *ext_nogc = 0;
	ouro_v **fns = 0;
	ouro_v *out = 0;
	gchk_context check;
	int nfn = 0;
	int i;

	if (program == 0 || program->tag != 0 || program->n < 3)
		return 0;
	collectors = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	body_bits = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_seen = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	ext_nogc = (unsigned char *)calloc(GCINF_ID_MAX, 1);
	if (collectors == 0 || body_bits == 0 || ext_seen == 0 || ext_nogc == 0)
		goto cleanup;
	if (gcinf_load_ids(bodies, body_bits) != 0)
		goto cleanup;
	if (gcinf_load_externs(program, ext_seen, ext_nogc) != 0)
		goto cleanup;
	if (host_list_collect(OURO_F(program, 0), &fns, &nfn, 0) != 0)
		goto cleanup;
	/* Validate all list spines before reporting the first instruction error. */
	for (i = 0; i < nfn; i++) {
		if (gcinf_walk_instr(fns[i], gcinf_add_collector, collectors) != 0)
			goto cleanup;
	}
	check.facts = (struct gcinf_body){collectors, body_bits, ext_seen, ext_nogc, 1};
	check.error = 0;
	for (i = 0; i < nfn; i++) {
		ouro_v *fn = fns[i];

		if (x64enc_dec_nat(OURO_F(fn, 0), &check.caller) != 0)
			goto cleanup;
		if (gcinf_walk_instr(fn, gchk_instruction, &check) != 0) {
			out = check.error;
			goto cleanup;
		}
	}
	out = gchk_right();
	g_gchk_count++;
	fe_progress("n1-host: gc-check-c functions=%d\n", nfn);

cleanup:
	free(collectors);
	free(body_bits);
	free(ext_seen);
	free(ext_nogc);
	free(fns);
	return out;
}

static ouro_v *gchk_bodies(ouro_env *env, ouro_v *bodies)
{
	ouro_v *program = ouro_get(env, 0);
	ouro_v *fast = gchk_try(program, bodies);

	if (fast != 0)
		return fast;
	fe_progress("n1-host: gc-check fallback\n");
	return ouro_apply(ouro_apply(g_raw_gc_check, program), bodies);
}

static ouro_v *gchk_program(ouro_env *env, ouro_v *program)
{
	(void)env;
	return ouro_clos(gchk_bodies, ouro_cons(program, 0));
}

ouro_v *ouro_wrap_mir_gc_check(ouro_v *raw)
{
	g_raw_gc_check = raw;
	g_gchk_count = 0;
	return ouro_clos(gchk_program, 0);
}

/* The canonical PE runner checks a chunk and returns its unvisited suffix.
   Retain the thunk's capture before the mark so packed suffix results share
   that immutable buffer. Only the chunk's checking and traversal temporaries
   are released; both typed result branches and the caller remain live. */
static ouro_v *pe_byte_check_work(ouro_env *env, ouro_v *work)
{
	work = ouro_clone_perm(work);
	return bounded_call(ouro_get(env, 0), 1, &work, ouro_clone_perm);
}

ouro_v *ouro_wrap_pe_run_byte_check(ouro_v *raw)
{
	return ouro_clos(pe_byte_check_work, ouro_cons(raw, 0));
}

/* Retain the complete canonical plan (or typed error), then release symbol
   index and traversal temporaries before applying patches and writing PE.
   The curried caller and all four immutable arguments keep their own banks. */
static ouro_v *pe_plan_fixups_work(ouro_env *env, ouro_v *fixups)
{
	ouro_heap_context *context = ouro_heap_context_enter();
	ouro_v *result = ouro_get(env, 3);
	int i;
	for (i = 2; i >= 0; i--)
		result = ouro_apply(result, ouro_get(env, i));
	result = ouro_apply(result, fixups);
	return ouro_heap_context_leave(context, result);
}

static ouro_v *pe_plan_imports(ouro_env *env, ouro_v *imports)
{
	return ouro_clos(pe_plan_fixups_work, ouro_cons(imports, env));
}

static ouro_v *pe_plan_symbols(ouro_env *env, ouro_v *symbols)
{
	return ouro_clos(pe_plan_imports, ouro_cons(symbols, env));
}

static ouro_v *pe_plan_sections(ouro_env *env, ouro_v *sections)
{
	return ouro_clos(pe_plan_symbols, ouro_cons(sections, env));
}

ouro_v *ouro_wrap_pe_plan_fixups(ouro_v *raw)
{
	return ouro_clos(pe_plan_sections, ouro_cons(raw, 0));
}
#else
ouro_v *ouro_wrap_check_environment_from_entries(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_managed_source_symbol_using(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_managed_source_spelling(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_managed_prepare_rechecked(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_lower_function_indexed(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_managed_finish_plan(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_check_module(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_lower_recheck_program(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_lower_normalize(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_lower_make_contract_indexed(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_managed_global_function(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_check_bounds(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_reachable(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_check_function(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_prepare_step(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_x64_encode(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_assemble(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_live_facts(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_live_summary_step(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_parts(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_live_instructions(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_instruction(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_block(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_codegen_body(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_gc_infer(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_gc_annotate(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_mir_gc_check(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_pe_run_byte_check(ouro_v *raw)
{
	return raw;
}

ouro_v *ouro_wrap_pe_plan_fixups(ouro_v *raw)
{
	return raw;
}

void ouro_fe_reset_mir_pins(void)
{
}
#endif
