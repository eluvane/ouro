/* Driver for the packed frontend/backend blob; it wires host globals but does not typecheck. */
#include "ouro_host_values.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#define MAX_UNITS 512
#define MAX_NAME 256

int ouro_export_count_fe(void);
const char *ouro_export_name_fe(int i);
ouro_v *ouro_export_value_fe(int i);

int ouro_export_count_be(void);
const char *ouro_export_name_be(int i);
ouro_v *ouro_export_value_be(int i);

static ouro_v *find_in(const char *name, int n, const char *(*nm)(int),
		       ouro_v *(*val)(int))
{
	int i;
	for (i = 0; i < n; i++) {
		if (strcmp(nm(i), name) == 0)
			return val(i);
	}
	fprintf(stderr, "ouro1: no export named %s\n", name);
	exit(2);
	return 0;
}




static ouro_v *file_codes(const char *path)
{
	FILE *f = fopen(path, "rb");
	unsigned char *buf;
	long len;
	ouro_v *v;
	if (f == 0) {
		fprintf(stderr, "ouro1: cannot open %s\n", path);
		exit(2);
	}
	if (fseek(f, 0L, SEEK_END) != 0 || (len = ftell(f)) < 0) {
		fprintf(stderr, "ouro1: cannot size %s\n", path);
		fclose(f);
		exit(2);
	}
	rewind(f);
	buf = (unsigned char *)malloc((unsigned long)len + 1UL);
	if (buf == 0) {
		fputs("ouro1: out of memory\n", stderr);
		fclose(f);
		exit(1);
	}
	if (len > 0 && fread(buf, 1, (unsigned long)len, f) != (unsigned long)len) {
		fprintf(stderr, "ouro1: cannot read %s\n", path);
		free(buf);
		fclose(f);
		exit(2);
	}
	fclose(f);
	v = ouro_packed(buf, (unsigned long)len);
	free(buf);
	return v;
}


static ouro_v *unit_list_from(char **paths, int n)
{
	ouro_v *list = ouro_ctor(0, 0, 0);
	int i;
	for (i = n - 1; i >= 0; i--) {
		ouro_v *cell[2];
		cell[0] = ouro_string_codes(paths[i]);
		cell[1] = file_codes(paths[i]);
		cell[0] = ouro_ctor(0, 2, cell);
		cell[1] = list;
		list = ouro_ctor(1, 2, cell);
	}
	return list;
}

static int is_fast(const char *name)
{
	/* Same host bindings the committed blob uses. Type apps are
	   dropped from JsIR before print_c, so these 2-arg forms match
	   call sites. */
	return strcmp(name, "add") == 0 || strcmp(name, "eqNat") == 0 ||
	       strcmp(name, "sub") == 0 || strcmp(name, "compareNat") == 0 ||
	       strcmp(name, "memNat") == 0 || strcmp(name, "append") == 0 ||
	       strcmp(name, "length") == 0 || strcmp(name, "reverse") == 0 ||
	       strcmp(name, "mul") == 0 || strcmp(name, "nth") == 0 ||
	       strcmp(name, "xor32") == 0 || strcmp(name, "and32") == 0 ||
	       strcmp(name, "or32") == 0 || strcmp(name, "not32") == 0 ||
	       strcmp(name, "shl32") == 0 || strcmp(name, "shr32") == 0 ||
	       strcmp(name, "rotr32") == 0 || strcmp(name, "add32") == 0;
}

/* Two of those host bindings do not have the shape the stdlib declares:
   ouro_rt.c's nth takes (list, index) while std/listx.ouro's nth takes
   (default, index, list), and memNat exists only inside selfhost, where the
   copies disagree on argument order. Programs get the Ouro definition. */
static int is_fast_shape_mismatch(const char *name)
{
	return strcmp(name, "nth") == 0 || strcmp(name, "memNat") == 0;
}

struct intern_name {
	unsigned long id;
	char s[MAX_NAME];
};

static void intern_push(struct intern_name **tab, int *n, int *cap,
			unsigned long id, const char *s)
{
	if (*n == *cap) {
		*cap = *cap == 0 ? 64 : *cap * 2;
		*tab = (struct intern_name *)realloc(
			*tab, (unsigned)(*cap) * sizeof(**tab));
		if (*tab == 0) {
			fputs("ouro1: out of memory\n", stderr);
			exit(1);
		}
	}
	(*tab)[*n].id = id;
	snprintf((*tab)[*n].s, MAX_NAME, "%s", s);
	(*n)++;
}

static void walk_ids(ouro_v *xs, struct intern_name **tab, int *n, int *cap)
{
	ouro_v *stack[256];
	int sp = 0;
	stack[sp++] = xs;
	while (sp > 0) {
		ouro_v *cur = stack[--sp];
		char buf[MAX_NAME];
		if (list_done(cur))
			continue;
		if (cur->tag == OURO_TAG_CAT && cur->n == 2) {
			if (sp + 2 > 256)
				continue;
			stack[sp++] = OURO_F(cur, 1);
			stack[sp++] = OURO_F(cur, 0);
			continue;
		}
		if (cur->tag == 1 && cur->n == 2) {
			ouro_v *p = OURO_F(cur, 0);
			if (p != 0 && p->n >= 2) {
				codes_to_buf(OURO_F(p, 0), buf, MAX_NAME);
				intern_push(tab, n, cap, as_nat(OURO_F(p, 1)), buf);
			}
			stack[sp++] = OURO_F(cur, 1);
		}
	}
}

static void recover_names_from_intern(ouro_v *st, struct intern_name **tab,
				      int *nn)
{
	int cap = 0;
	*tab = 0;
	*nn = 0;
	if (st == 0 || st->n < 1)
		return;
	walk_ids(OURO_F(st, 0), tab, nn, &cap);
}

static const char *lookup_name(struct intern_name *tab, int n, unsigned long id)
{
	int i;
	for (i = 0; i < n; i++) {
		if (tab[i].id == id)
			return tab[i].s;
	}
	return 0;
}

static ouro_v *names_list(struct intern_name *tab, int ntab, ouro_v **orig_ids,
			  int n)
{
	ouro_v *list = ouro_ctor(0, 0, 0);
	int i;
	for (i = n - 1; i >= 0; i--) {
		unsigned long id = as_nat(orig_ids[i]);
		const char *nm = lookup_name(tab, ntab, id);
		ouro_v *cell[2];
		ouro_v *pr[2];
		char fallback[32];
		if (nm == 0) {
			snprintf(fallback, sizeof fallback, "c%lu", id);
			nm = fallback;
		}
		pr[0] = orig_ids[i];
		pr[1] = ouro_bytes((const unsigned char *)nm,
				   (unsigned long)strlen(nm));
		cell[0] = ouro_ctor(0, 2, pr);
		cell[1] = list;
		list = ouro_ctor(1, 2, cell);
	}
	return list;
}

/* Full-length copy of an interned byte list (codes_to_buf truncates at
   MAX_NAME, which is fine for identifiers but not for string literals). */
static char *codes_to_heap(ouro_v *xs, unsigned long *len_out)
{
	unsigned long cap = 64;
	unsigned long n = 0;
	char *buf = (char *)malloc(cap);
	ouro_v *stack[64];
	int sp = 0;
	if (buf == 0) {
		fputs("ouro1: out of memory\n", stderr);
		exit(1);
	}
	for (;;) {
		if (list_done(xs)) {
			if (sp == 0)
				break;
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == OURO_TAG_CAT && xs->n == 2) {
			if (sp < 63)
				stack[sp++] = OURO_F(xs, 1);
			xs = OURO_F(xs, 0);
			continue;
		}
		if (xs->tag == OURO_TAG_BYTES) {
			unsigned long k = (unsigned long)xs->n;
			while (n + k + 1 > cap)
				cap *= 2;
			buf = (char *)realloc(buf, cap);
			if (buf == 0) {
				fputs("ouro1: out of memory\n", stderr);
				exit(1);
			}
			if (k > 0 && xs->u.s != 0)
				memcpy(buf + n, xs->u.s, (size_t)k);
			n += k;
			if (sp == 0)
				break;
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == 1 && xs->n == 2) {
			if (n + 2 > cap) {
				cap *= 2;
				buf = (char *)realloc(buf, cap);
				if (buf == 0) {
					fputs("ouro1: out of memory\n",
					      stderr);
					exit(1);
				}
			}
			buf[n++] = (char)(as_nat(OURO_F(xs, 0)) & 0xFFUL);
			xs = OURO_F(xs, 1);
			continue;
		}
		break;
	}
	buf[n] = 0;
	*len_out = n;
	return buf;
}

static int shim_is_prim_name(const char *nm)
{
	return strcmp(nm, "io_pure") == 0 || strcmp(nm, "io_bind") == 0 ||
	       strncmp(nm, "prim_", 5) == 0;
}

struct shim_entry {
	char *bytes;
	unsigned long len;
	unsigned long id;
};

/* Flatten a lexer alist (List (Pair (List Nat) Nat)) into an array. */
static struct shim_entry *collect_alist(ouro_v *xs, int *n_out)
{
	struct shim_entry *out = 0;
	int n = 0;
	int cap = 0;
	ouro_v *stack[256];
	int sp = 0;
	*n_out = 0;
	if (xs == 0)
		return 0;
	stack[sp++] = xs;
	while (sp > 0) {
		ouro_v *cur = stack[--sp];
		if (list_done(cur))
			continue;
		if (cur->tag == OURO_TAG_CAT && cur->n == 2) {
			if (sp + 2 > 256)
				continue;
			stack[sp++] = OURO_F(cur, 1);
			stack[sp++] = OURO_F(cur, 0);
			continue;
		}
		if (cur->tag == 1 && cur->n == 2) {
			ouro_v *p = OURO_F(cur, 0);
			stack[sp++] = OURO_F(cur, 1);
			if (p == 0 || p->n < 2)
				continue;
			if (n == cap) {
				cap = cap == 0 ? 64 : cap * 2;
				out = (struct shim_entry *)realloc(
					out, (unsigned)cap * sizeof(*out));
				if (out == 0) {
					fputs("ouro1: out of memory\n", stderr);
					exit(1);
				}
			}
			out[n].bytes = codes_to_heap(OURO_F(p, 0), &out[n].len);
			out[n].id = as_nat(OURO_F(p, 1));
			n++;
		}
	}
	*n_out = n;
	return out;
}

static void free_alist(struct shim_entry *xs, int n)
{
	int i;
	for (i = 0; i < n; i++)
		free(xs[i].bytes);
	free(xs);
}

static void shim_emit_c_string(const char *s, unsigned long len)
{
	unsigned long i;
	putchar('"');
	for (i = 0; i < len; i++) {
		unsigned char c = (unsigned char)s[i];
		if (c == '"' || c == '\\') {
			putchar('\\');
			putchar((int)c);
		} else if (c >= 32 && c < 127) {
			putchar((int)c);
		} else {
			printf("\\%03o", (unsigned)c);
		}
	}
	putchar('"');
}

/* Standalone-program mode (OURO_EMIT_IO_SHIMS=1). Two kinds of global the
   compiler-emission path never has to resolve:

     - runtime axioms (io_pure / io_bind / prim_*), bound here to the C host
       in ouro_io.c;
     - string literals, which print_c.ouro spells `ouro_gN` from the lexer's
       string table — an id space disjoint from name ids, so the two would
       otherwise collide. String ids are shifted by g_str_base and the IR is
       rewritten to match (see rewrite_node).

   Emitted before any global definition, so C sees a declaration first.
   Literals a program never forces stay dead statics. */
static unsigned long g_str_base;

/* Ouro classifies type formers from checked declaration types. This same list
   drives extraction and the temporary IO shim rewrite; names never grant a
   value permission to disappear as a type argument. */
static unsigned long *g_type_ids;
static int g_ntype;
static int g_type_cap;
static unsigned long g_typearg_drops;

static void type_id_push(unsigned long id)
{
	if (g_ntype == g_type_cap) {
		g_type_cap = g_type_cap == 0 ? 64 : g_type_cap * 2;
		g_type_ids = (unsigned long *)realloc(
			g_type_ids, (unsigned)g_type_cap * sizeof(*g_type_ids));
		if (g_type_ids == 0) {
			fputs("ouro1: out of memory\n", stderr);
			exit(1);
		}
	}
	g_type_ids[g_ntype++] = id;
}

static int is_type_id(unsigned long id)
{
	int i;
	for (i = 0; i < g_ntype; i++) {
		if (g_type_ids[i] == id)
			return 1;
	}
	return 0;
}

static char *checked_shim_key(ouro_v *bindings, unsigned long id,
			     unsigned long *length)
{
	while (!list_done(bindings)) {
		ouro_v *pair;
		if (bindings->tag != 1 || bindings->n != 2 ||
		    (pair = OURO_F(bindings, 0)) == 0 || pair->n != 2) {
			fputs("ouro1: malformed checked runtime bindings\n", stderr);
			exit(1);
		}
		if (as_nat(OURO_F(pair, 0)) == id)
			return codes_to_heap(OURO_F(pair, 1), length);
		bindings = OURO_F(bindings, 1);
	}
	return 0;
}

static void emit_runtime_shims(ouro_v *st, ouro_v **ids, int nids,
			       ouro_v *type_ids, ouro_v *bindings)
{
	struct shim_entry *names;
	struct shim_entry *strs = 0;
	int nnames = 0;
	int nstrs = 0;
	int i;
	int j;
	if (st == 0 || st->n < 1)
		return;
	while (!list_done(type_ids)) {
		if (type_ids->tag != 1 || type_ids->n != 2) {
			fputs("ouro1: malformed checked type globals\n", stderr);
			exit(1);
		}
		type_id_push(as_nat(OURO_F(type_ids, 0)));
		type_ids = OURO_F(type_ids, 1);
	}
	names = collect_alist(OURO_F(st, 0), &nnames);
	if (st->n >= 3)
		strs = collect_alist(OURO_F(st, 2), &nstrs);

	g_str_base = 1;
	for (i = 0; i < nnames; i++) {
		if (names[i].id >= g_str_base)
			g_str_base = names[i].id + 1;
	}
	for (i = 0; i < nids; i++) {
		if (as_nat(ids[i]) >= g_str_base)
			g_str_base = as_nat(ids[i]) + 1;
	}

	fputs("ouro_v *ouro_io_prim_req(const char *name);\n", stdout);
	fputs("ouro_v *ouro_io_type_stub(const char *name);\n", stdout);
	for (i = 0; i < nnames; i++) {
		int skip = 0;
		unsigned long key_length;
		char *checked_key;
		const char *key;
		const char *maker;
		for (j = 0; j < nids && !skip; j++) {
			if (as_nat(ids[j]) == names[i].id)
				skip = 1;
		}
		for (j = 0; j < i && !skip; j++) {
			if (names[j].id == names[i].id)
				skip = 1;
		}
		if (skip)
			continue;
		checked_key = checked_shim_key(bindings, names[i].id, &key_length);
		key = checked_key != 0 ? checked_key : names[i].bytes;
		if (checked_key == 0)
			key_length = names[i].len;
		maker = !is_type_id(names[i].id) &&
			(checked_key != 0 || shim_is_prim_name(names[i].bytes)) ?
			"ouro_io_prim_req" : "ouro_io_type_stub";
		printf("static ouro_v *ouro_c%lu;\n", names[i].id);
		printf("static ouro_v *ouro_g%lu(void){if(ouro_c%lu==0)"
		       "ouro_c%lu=%s(",
		       names[i].id, names[i].id, names[i].id, maker);
		shim_emit_c_string(key, key_length);
		printf(");return ouro_c%lu;}\n", names[i].id);
		free(checked_key);
	}
	for (i = 0; i < nstrs; i++) {
		unsigned long id = g_str_base + strs[i].id;
		printf("static ouro_v *ouro_c%lu;\n", id);
		printf("static ouro_v *ouro_g%lu(void){if(ouro_c%lu==0)"
		       "ouro_c%lu=ouro_str(",
		       id, id, id);
		shim_emit_c_string(strs[i].bytes, strs[i].len);
		printf(");return ouro_c%lu;}\n", id);
	}
	free_alist(names, nnames);
	free_alist(strs, nstrs);
}

/* JsIR tags match compiler/jsir.ouro constructor order. */
#define J_VAR 0
#define J_GLOB 1
#define J_LAM 2
#define J_APP 3
#define J_CTOR 4
#define J_SWITCH 5
#define J_FIX 6
#define J_LET 7
#define J_ERR 8
#define J_STR 9

static int js_nil(ouro_v *xs)
{
	return xs == 0 || (xs->tag == 0 && xs->n == 0) ||
	       (xs->tag == OURO_TAG_NAT && xs->n == 0);
}

static ouro_v *js_cons(ouro_v *h, ouro_v *t)
{
	ouro_v *c[2];
	c[0] = h;
	c[1] = t;
	return ouro_ctor(1, 2, c);
}

static ouro_v *js_append(ouro_v *a, ouro_v *b)
{
	if (js_nil(a))
		return b;
	if (!(a->tag == 1 && a->n >= 2))
		return b;
	return js_cons(OURO_F(a, 0), js_append(OURO_F(a, 1), b));
}

static ouro_v *peel_apps(ouro_v *j, ouro_v **args_out)
{
	/* Collect args by walking to the head, then reverse so the
	   leftmost application is first (type args come first). */
	ouro_v *stack[256];
	int n = 0;
	while (j != 0 && j->tag == J_APP && j->n >= 2) {
		if (n >= 256) {
			fputs("ouro1: app spine too deep\n", stderr);
			exit(1);
		}
		stack[n++] = OURO_F(j, 1);
		j = OURO_F(j, 0);
	}
	{
		/* stack[0] is the rightmost arg. cons front-to-back
		   from index 0 so the list is leftmost-first. */
		ouro_v *args = ouro_ctor(0, 0, 0);
		int i;
		for (i = 0; i < n; i++)
			args = js_cons(stack[i], args);
		*args_out = args;
	}
	return j;
}

static ouro_v *rebuild_apps(ouro_v *base, ouro_v *args)
{
	while (!js_nil(args) && args->tag == 1 && args->n >= 2) {
		ouro_v *f[2];
		f[0] = base;
		f[1] = OURO_F(args, 0);
		base = ouro_ctor(J_APP, 2, f);
		args = OURO_F(args, 1);
	}
	return base;
}

static ouro_v *rewrite_jsir(ouro_v *j);

static ouro_v *rewrite_list(ouro_v *xs)
{
	if (js_nil(xs))
		return xs;
	if (!(xs->tag == 1 && xs->n >= 2))
		return xs;
	return js_cons(rewrite_jsir(OURO_F(xs, 0)), rewrite_list(OURO_F(xs, 1)));
}

/* IO-program walk only: shift string ids and drop type-stub spine args.
   Stage emit skips this; extract.ouro already normalized the IR. */
static ouro_v *rewrite_node(ouro_v *j)
{
	ouro_v *fld[3];
	if (j == 0)
		return j;
	switch (j->tag) {
	case J_LAM:
		if (j->n < 2)
			return j;
		fld[0] = OURO_F(j, 0);
		fld[1] = rewrite_jsir(OURO_F(j, 1));
		return ouro_ctor(J_LAM, 2, fld);
	case J_CTOR:
		if (j->n < 3)
			return j;
		fld[0] = OURO_F(j, 0);
		fld[1] = OURO_F(j, 1);
		fld[2] = rewrite_list(OURO_F(j, 2));
		return ouro_ctor(J_CTOR, 3, fld);
	case J_SWITCH:
		if (j->n < 3)
			return j;
		fld[0] = rewrite_jsir(OURO_F(j, 0));
		fld[1] = OURO_F(j, 1);
		fld[2] = rewrite_list(OURO_F(j, 2));
		return ouro_ctor(J_SWITCH, 3, fld);
	case J_FIX:
		if (j->n < 3)
			return j;
		fld[0] = OURO_F(j, 0);
		fld[1] = OURO_F(j, 1);
		fld[2] = rewrite_jsir(OURO_F(j, 2));
		return ouro_ctor(J_FIX, 3, fld);
	case J_LET:
		if (j->n < 3)
			return j;
		fld[0] = OURO_F(j, 0);
		fld[1] = rewrite_jsir(OURO_F(j, 1));
		fld[2] = rewrite_jsir(OURO_F(j, 2));
		return ouro_ctor(J_LET, 3, fld);
	case J_STR:
		/* String ids live in their own space; shift them clear of the
		   name ids so both can share the ouro_gN spelling. */
		if (g_str_base == 0 || j->n < 1)
			return j;
		fld[0] = ouro_nat(g_str_base + as_nat(OURO_F(j, 0)));
		return ouro_ctor(J_GLOB, 1, fld);
	default:
		return j;
	}
}

/* A spine argument carries no runtime value when its head is a type-level
   global: `String`, `List String`, ... (see g_type_ids). */
static int is_type_arg(ouro_v *j)
{
	while (j != 0 && j->tag == J_APP && j->n >= 2)
		j = OURO_F(j, 0);
	return j != 0 && j->tag == J_GLOB && j->n >= 1 &&
	       is_type_id(as_nat(OURO_F(j, 0)));
}

static ouro_v *drop_type_args(ouro_v *args)
{
	ouro_v *kept;
	if (g_ntype == 0 || js_nil(args))
		return args;
	if (!(args->tag == 1 && args->n >= 2))
		return args;
	kept = drop_type_args(OURO_F(args, 1));
	if (is_type_arg(OURO_F(args, 0))) {
		g_typearg_drops++;
		return kept;
	}
	return js_cons(OURO_F(args, 0), kept);
}

static ouro_v *rewrite_jsir(ouro_v *j)
{
	ouro_v *fld[3];
	ouro_v *args;
	ouro_v *base;
	ouro_v *all;
	if (j == 0)
		return j;
	base = peel_apps(j, &args);
	base = rewrite_node(base);
	args = rewrite_list(args);
	args = drop_type_args(args);
	if (base != 0 && base->tag == J_CTOR && base->n >= 3) {
		all = js_append(drop_type_args(OURO_F(base, 2)), args);
		fld[0] = OURO_F(base, 0);
		fld[1] = OURO_F(base, 1);
		fld[2] = all;
		return ouro_ctor(J_CTOR, 3, fld);
	}
	return rebuild_apps(base, args);
}

static void report_checked_error(ouro_v *result)
{
	ouro_v *error;
	if (result == 0 || result->tag != 0 || result->n != 1 ||
	    (error = OURO_F(result, 0)) == 0 || error->tag != 0 || error->n != 2) {
		fputs("ouro1: invalid compiler result\n", stderr);
		return;
	}
	fprintf(stderr, "ouro1: CErr code=%lu det=%lu\n",
		as_nat(OURO_F(error, 0)), as_nat(OURO_F(error, 1)));
}

/* The canonical Ouro serializer consumes the complete CheckedProgram. The
   host only writes its bytes and reports IO errors; it never synthesizes types. */
static int write_checked_program(const char *path, unsigned long fuel)
{
	ouro_v *result = ouro_fe_checked_dump(ouro_nat(fuel));
	FILE *file;
	int failed;
	if (result == 0 || result->tag != 1 || result->n != 1) {
		fputs("ouro1: checked-program output failed\n", stderr);
		report_checked_error(result);
		return 1;
	}
	file = fopen(path, "wb");
	if (file == 0) {
		fprintf(stderr, "ouro1: cannot write checked program %s\n", path);
		return 1;
	}
	ouro_write_codes(OURO_F(result, 0), file);
	failed = ferror(file);
	if (fclose(file) != 0)
		failed = 1;
	if (failed) {
		fprintf(stderr, "ouro1: cannot finish checked program %s\n", path);
		return 1;
	}
	return 0;
}

static int valid_module_suffix(const char *suffix)
{
	const unsigned char *p = (const unsigned char *)suffix;

	if (p == 0 || *p == 0)
		return 1;
	if (*p++ != '_' || *p == 0)
		return 0;
	for (; *p != 0; p++) {
		if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
		      (*p >= '0' && *p <= '9') || *p == '_'))
			return 0;
	}
	return 1;
}

int main(int argc, char **argv)
{
	ouro_v *fe;
	ouro_v *res;
	ouro_v *cores;
	unsigned long fuel = 600UL;
	int check_only = 0;
	const char *file = 0;
	const char *mod = "";
	const char *checked_out = 0;
	char *units[MAX_UNITS];
	int nunits = 0;
	int i;

	i = 1;
	if (argc >= 2 && strcmp(argv[1], "check") == 0) {
		check_only = 1;
		i = 2;
	}
	for (; i < argc; i++) {
		if (strcmp(argv[i], "--unit") == 0 && i + 1 < argc) {
			if (nunits >= MAX_UNITS) {
				fputs("ouro1: too many --unit\n", stderr);
				return 2;
			}
			units[nunits++] = argv[++i];
		} else if (strcmp(argv[i], "--module") == 0 && i + 1 < argc) {
			mod = argv[++i];
		} else if (strcmp(argv[i], "--emit-checked-program") == 0 &&
			   i + 1 < argc) {
			checked_out = argv[++i];
		} else if (argv[i][0] == '-') {
			fprintf(stderr, "ouro1: unknown flag %s\n", argv[i]);
			return 2;
		} else if (file == 0) {
			file = argv[i];
		} else {
			fuel = strtoul(argv[i], 0, 10);
		}
	}

	if (file == 0) {
		fputs("usage: ouro1 [check] <file.ouro> [fuel] [--module SUF] [--unit PATH]... [--emit-checked-program FILE]\n",
		      stderr);
		return 2;
	}
	if (checked_out != 0 && !check_only) {
		fputs("ouro1: --emit-checked-program requires check\n", stderr);
		return 2;
	}
	if (!valid_module_suffix(mod)) {
		fputs("ouro1: --module must be empty or match _[A-Za-z0-9_]+\n",
		      stderr);
		return 2;
	}
	ouro_gc_set_stack_base(&argc);
	ouro_heap_report("process-start");
#ifdef _WIN32
	_setmode(_fileno(stdout), _O_BINARY);
#endif

	if (nunits > 0) {
		ouro_heap_report("before-unit-list");
		fe = find_in("compile_units", ouro_export_count_fe(),
			     ouro_export_name_fe, ouro_export_value_fe);
		res = ouro_apply(ouro_apply(ouro_apply(fe, ouro_nat(fuel)),
					ouro_string_codes(file)),
			       unit_list_from(units, nunits));
		ouro_heap_report("after-compile-units");
	} else {
		ouro_heap_report("before-source-read");
		fe = find_in("compile_to_cores", ouro_export_count_fe(),
			     ouro_export_name_fe, ouro_export_value_fe);
		res = ouro_apply(ouro_apply(fe, ouro_nat(fuel)), file_codes(file));
		ouro_heap_report("after-compile-source");
	}

	if (res == 0 || res->tag != 1 || res->n < 1) {
		if (check_only)
			fputs("CHECK_FAIL: front end rejected the input\n", stderr);
		else
			fputs("ouro1: front end rejected the input\n", stderr);
		if (res != 0) {
			fprintf(stderr, "ouro1: CErr tag=%d n=%d\n", res->tag, res->n);
			if (res->n >= 1 && OURO_F(res, 0) != 0 && OURO_F(res, 0)->n >= 1) {
				unsigned long code = 0;
				unsigned long det = 0;
				ouro_v *e = OURO_F(res, 0);
				if (e->tag == OURO_TAG_NAT)
					code = (unsigned long)e->n;
				else if (e->n >= 1) {
					ouro_v *c = OURO_F(e, 0);
					while (c != 0 && c->tag == 1 && c->n == 1) {
						code++;
						c = OURO_F(c, 0);
					}
					if (c != 0 && c->tag == OURO_TAG_NAT)
						code += (unsigned long)c->n;
				}
				if (e->n >= 2) {
					ouro_v *d = OURO_F(e, 1);
					if (d != 0 && d->tag == OURO_TAG_NAT)
						det = (unsigned long)d->n;
					else {
						while (d != 0 && d->tag == 1 && d->n == 1) {
							det++;
							d = OURO_F(d, 0);
						}
					}
				}
				fprintf(stderr, "ouro1: CErr code=%lu det=%lu\n", code, det);
			}
			if (!check_only)
				ouro_show_line(res);
		}
		return 1;
	}
	if (!check_only)
		fprintf(stderr, "ouro1: compiled ok\n");

	if (check_only) {
		if (checked_out != 0) {
			if (write_checked_program(checked_out, fuel) != 0)
				return 1;
		}
		ouro_gc_push_root(&res);
		ouro_gc_collect();
		ouro_heap_report("check-ok-after-gc");
		ouro_gc_pop_roots(1);
		fputs("CHECK_OK\n", stdout);
		return 0;
	}

	cores = OURO_F(res, 0);
	{
		ouro_v **ids = 0;
		ouro_v **terms = 0;
		ouro_v *stack[256];
		ouro_v *cur;
		ouro_v *intern_perm = 0;
		int sp = 0;
		int n = 0;
		int cap = 64;
		ouro_v *extract_with;
		ouro_v *type_ids_v;
		ouro_v *bindings_v;
		ouro_v *metadata;
		ouro_v *emit_g;
		ouro_v *emit_f;
		ouro_v *emit_ex;
		ouro_v *hdr;
		ouro_v *nil;
		ouro_v *dummy;
		ouro_v *pieces;
		ouro_v *nlist;
		ouro_v *modv;
		ouro_v *fld[2];
		struct intern_name *tab = 0;
		int backend_failed = 0;
		int ntab = 0;

		/* Retain checked metadata before dropping the frontend phase. */
		metadata = ouro_fe_checked_type_globals(ouro_nat(fuel));
		if (metadata == 0 || metadata->tag != 1 || metadata->n != 1) {
			fputs("ouro1: checked type-global classification failed\n", stderr);
			report_checked_error(metadata);
			backend_failed = 1;
			goto backend_done;
		}
		type_ids_v = ouro_clone_perm(OURO_F(metadata, 0));
		bindings_v = ouro_clone_perm(ouro_fe_checked_c_shims());
		if (type_ids_v == 0 || bindings_v == 0) {
			fputs("ouro1: clone checked metadata failed\n", stderr);
			backend_failed = 1;
			goto backend_done;
		}

		/* Keep intern names and cores; drop the compile phase heap so
		   backend constants are not built on a spent bump bank. */
		if (getenv("OURO_EMIT_IO_SHIMS") != 0 && ouro_fe_last_intern() != 0)
			intern_perm = ouro_clone_perm(ouro_fe_last_intern());
		recover_names_from_intern(ouro_fe_last_intern(), &tab, &ntab);
		cores = ouro_clone_perm(cores);
		if (cores == 0) {
			fputs("ouro1: clone cores failed\n", stderr);
			backend_failed = 1;
			goto backend_done;
		}
		ouro_heap_discard_phase();
		ouro_heap_report("after-phase-discard");
		fputs("ouro1: walking cores\n", stderr);

		ids = (ouro_v **)malloc(sizeof(ouro_v *) * (unsigned)cap);
		if (ids == 0) {
			fputs("ouro1: out of memory\n", stderr);
			backend_failed = 1;
			goto backend_done;
		}
		terms = (ouro_v **)malloc(sizeof(ouro_v *) * (unsigned)cap);
		if (terms == 0) {
			fputs("ouro1: out of memory\n", stderr);
			backend_failed = 1;
			goto backend_done;
		}
		stack[sp++] = cores;
		while (sp > 0) {
			cur = stack[--sp];
			if (list_done(cur))
				continue;
			if (cur->tag == OURO_TAG_CAT && cur->n == 2) {
				if (sp + 2 > 256) {
					fputs("ouro1: cores nest too deep\n", stderr);
					backend_failed = 1;
					goto backend_done;
				}
				stack[sp++] = OURO_F(cur, 1);
				stack[sp++] = OURO_F(cur, 0);
				continue;
			}
			if (cur->tag == 1 && cur->n == 2) {
				ouro_v *pair = OURO_F(cur, 0);
				if (pair == 0 || pair->n < 2) {
					fputs("ouro1: core pair expected\n", stderr);
					backend_failed = 1;
					goto backend_done;
				}
				if (n == cap) {
					ouro_v **grown;
					if (n > 20000) {
						fprintf(stderr,
							"ouro1: too many cores n=%d (cycle?)\n",
							n);
						backend_failed = 1;
						goto backend_done;
					}
					cap *= 2;
					grown = (ouro_v **)realloc(
						ids, sizeof(ouro_v *) * (unsigned)cap);
					if (grown == 0) {
						fputs("ouro1: out of memory\n", stderr);
						backend_failed = 1;
						goto backend_done;
					}
					ids = grown;
					grown = (ouro_v **)realloc(
						terms, sizeof(ouro_v *) * (unsigned)cap);
					if (grown == 0) {
						fputs("ouro1: out of memory\n", stderr);
						backend_failed = 1;
						goto backend_done;
					}
					terms = grown;
				}
				ids[n] = OURO_F(pair, 0);
				terms[n] = OURO_F(pair, 1);
				n++;
				if ((n & 63) == 0) {
					fprintf(stderr, "ouro1: walk n=%d sp=%d\n", n, sp);
					fflush(stderr);
				}
				if (n > 5000) {
					fprintf(stderr,
						"ouro1: abort walk n=%d (cycle?)\n", n);
					backend_failed = 1;
					goto backend_done;
				}
				stack[sp++] = OURO_F(cur, 1);
				continue;
			}
			fputs("ouro1: cores is not a list\n", stderr);
			if (cur)
				fprintf(stderr, "ouro1: bad core cell tag=%d n=%d\n",
					cur->tag, cur->n);
			backend_failed = 1;
			goto backend_done;
		}
		fprintf(stderr, "ouro1: walked cores n=%d\n", n);

		extract_with = find_in("extract_term_with", ouro_export_count_be(),
				       ouro_export_name_be, ouro_export_value_be);
		emit_g = find_in("emit_global", ouro_export_count_be(),
				 ouro_export_name_be, ouro_export_value_be);
		emit_f = find_in("emit_fwd", ouro_export_count_be(),
			      ouro_export_name_be, ouro_export_value_be);
		emit_ex = find_in("emit_exports", ouro_export_count_be(),
				  ouro_export_name_be, ouro_export_value_be);
		hdr = find_in("c_hdr", ouro_export_count_be(),
			      ouro_export_name_be, ouro_export_value_be);

		fprintf(stderr, "ouro1: emit cores=%d names=%d\n", n, ntab);

		ouro_write_codes(hdr, stdout);
		for (i = 0; i < n; i++)
			ouro_write_codes(ouro_apply(emit_f, ids[i]), stdout);

		/* Standalone-program mode: bind runtime axioms and string
		   literals to the C host. Off by default so stage emission
		   stays byte-identical; scripts/build_tool.sh turns it on. */
		if (getenv("OURO_EMIT_IO_SHIMS") != 0)
			emit_runtime_shims(intern_perm, ids, n, type_ids_v, bindings_v);

		for (i = 0; i < ouro_export_count_be(); i++)
			(void)ouro_export_value_be(i);
		ouro_rt_warmup();
		ouro_heap_mark();
		for (i = 0; i < n; i++) {
			const char *nm = lookup_name(tab, ntab, as_nat(ids[i]));
			if (nm != 0 && is_fast(nm) &&
			    !(g_ntype > 0 && is_fast_shape_mismatch(nm))) {
				unsigned long gid = as_nat(ids[i]);
				printf("static ouro_v *ouro_c%lu;\n", gid);
				printf("static ouro_v *ouro_g%lu(void){if(ouro_c%lu==0)"
				       "ouro_c%lu=ouro_fast(\"%s\");return ouro_c%lu;}\n",
				       gid, gid, gid, nm, gid);
				continue;
			}
			{
				ouro_v *ir;
				ouro_v *g1;
				ouro_v *chunk;
				ir = ouro_apply(ouro_apply(extract_with, type_ids_v),
					      terms[i]);
				if (g_ntype > 0 || g_str_base > 0)
					ir = rewrite_jsir(ir);
				g1 = ouro_apply(emit_g, ids[i]);
				if (g1 == 0 || g1->tag != OURO_TAG_CLOS) {
					fprintf(stderr,
						"ouro1: emit_global id[%d] not a function\n",
						i);
					backend_failed = 1;
					goto backend_done;
				}
				chunk = ouro_apply(g1, ir);
				ouro_write_codes(chunk, stdout);
				ouro_heap_reset();
			}
		}

		nil = ouro_ctor(0, 0, 0);
		fld[0] = ouro_nat(0);
		dummy = ouro_ctor(0, 1, fld);
		pieces = nil;
		for (i = n - 1; i >= 0; i--) {
			ouro_v *pr[2];
			pr[0] = ids[i];
			pr[1] = dummy;
			fld[0] = ouro_ctor(0, 2, pr);
			fld[1] = pieces;
			pieces = ouro_ctor(1, 2, fld);
		}
		nlist = names_list(tab, ntab, ids, n);
		modv = ouro_bytes((const unsigned char *)mod,
				  (unsigned long)strlen(mod));
		ouro_write_codes(
			ouro_apply(ouro_apply(ouro_apply(emit_ex, nlist), pieces), modv),
			stdout);
		ouro_gc_collect();
		ouro_heap_report("after-backend-emit");
	backend_done:
		free(ids);
		free(terms);
		free(tab);
		if (backend_failed)
			return 1;
		if (g_typearg_drops > 0)
			fprintf(stderr, "EXTRACT_TYPEARG count=%lu\n",
				g_typearg_drops);
	}
	return 0;
}
