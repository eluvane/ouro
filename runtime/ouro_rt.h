/* ouro_rt.h: runtime for the Ouro C backend (print_c.ouro output).
   Value model mirrors the JS backend: constructors are {tag, fields},
   closures carry a linked environment, variables are static indices.
   Phase heap can be reset at native compiler seams; cloned phase results move to a permanent heap. */
#ifndef OURO_RT_H
#define OURO_RT_H

#include <stdio.h> /* FILE, for ouro_write_codes */
#include <stdint.h>

typedef struct ouro_v ouro_v;
typedef struct ouro_env ouro_env;
typedef struct ouro_heap_context ouro_heap_context;

#define OURO_TAG_CLOS (-1)
#define OURO_TAG_STR (-2)
#define OURO_TAG_THUNK (-3)
#define OURO_TAG_NAT (-4)
#define OURO_TAG_BYTES (-5)
#define OURO_TAG_CAT (-6)
#define OURO_TAG_BIG_NAT (-7)

/* One 24-byte cell for every value. The payload is variant-specific:
   constructors and OURO_TAG_CAT keep up to two fields inline and larger
   field lists directly after the cell (see ouro_fields), closures and
   thunks keep their code and environment, strings and byte strings keep
   their bytes, small packed nats use n, and larger naturals keep n
   little-endian 32-bit limbs after the cell. Generated C never reads these
   members; it goes through ouro_ctor / ouro_case / ouro_app / ouro_get. */
struct ouro_v {
	int tag;
	int n;
	union {
		ouro_v *inl[2];
		struct {
			ouro_v *(*fn)(ouro_env *, ouro_v *);
			ouro_env *env;
		} c;
		const char *s;
	} u;
};

struct ouro_env {
	ouro_v *v;
	ouro_env *next;
};

#define OURO_INLINE_FIELDS 2

/* Field vector of a constructor or concat cell; valid for tag >= 0 and
   OURO_TAG_CAT only. Never call it on closures, strings, or packed nats. */
static inline ouro_v **ouro_fields(ouro_v *v)
{
	return v->n <= OURO_INLINE_FIELDS ? v->u.inl : (ouro_v **)(v + 1);
}

#define OURO_F(v, i) (ouro_fields(v)[(i)])

void *ouro_alloc(unsigned long size);
/* Host seam: clone survivors, then drop the phase bump. Used between
   compile/lower stages when the C arena would otherwise retain every
   temporary from the previous unit or declaration. */
ouro_v *ouro_keep(ouro_v *v);
void ouro_static_begin(void);
void ouro_static_end(void);
void ouro_perm_begin(void);
void ouro_perm_end(void);
void ouro_perm_select(int bank);
void ouro_perm_reset_bank(int bank);
void *ouro_perm_alloc(unsigned long size);
ouro_v *ouro_clone_perm(ouro_v *v);
/* Like ouro_clone_perm, but only static nodes are shared. A perm spine
   with phase children is copied instead of returned as-is. */
ouro_v *ouro_clone_perm_deep(ouro_v *v);
void ouro_gc_set_stack_base(void *p);
void ouro_gc_collect(void);
void ouro_gc_push_root(ouro_v **slot);
void ouro_gc_pop_roots(unsigned long n);
unsigned long ouro_gc_root_count(void);
void ouro_heap_report(const char *label);
unsigned long long ouro_heap_live_bytes(void);
unsigned long long ouro_heap_total_alloc_bytes(void);
/* Phase bytes returned early by ouro_app / ouro_case (see ouro_rt.c). */
unsigned long long ouro_heap_reclaimed_bytes(void);
void ouro_heap_mark(void);
void ouro_heap_reset(void);
void ouro_heap_discard_phase(void);
/* Suspend the caller's phase/permanent banks while a bounded host operation
   uses fresh banks. Leave restores the caller's allocation domain and copies
   only the survivor nodes allocated in the nested banks. Caller-owned intern
   and AST identities are shared so repeated parses do not recopy the table. */
ouro_heap_context *ouro_heap_context_enter(void);
ouro_v *ouro_heap_context_leave(ouro_heap_context *context, ouro_v *survivor);
void ouro_rt_warmup(void);

ouro_v *ouro_ctor(int tag, int n, ouro_v **fields);
ouro_v *ouro_clos(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env);
/* Self-referential closure: the value is pushed onto its own environment. */
ouro_v *ouro_fix(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env);
/* Branch that binds no field. Held unevaluated so a match costs only the
   branch it takes, matching the JS backend's switch. Forced by ouro_case. */
ouro_v *ouro_thunk(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env);
ouro_v *ouro_str(const char *s);

/* Host-side construction of the standard Nat/List layout (Z=0, S=1, Nil=0,
   Cons=1). Lets a C host feed real input into compiled Ouro without any
   algorithm in C. */
ouro_v *ouro_nat(unsigned long n);
/* Full 64-bit Nat construction for byte counts and peaks. */
ouro_v *ouro_nat_u64(uint64_t number);
/* Checked host-size conversion; no truncation of a large or malformed Nat. */
int ouro_nat_to_ulong(ouro_v *value, unsigned long *out);
uint32_t ouro_nat_low32(ouro_v *value);
ouro_v *ouro_nat_decimal(ouro_v *value);
ouro_v *ouro_bytes(const unsigned char *b, unsigned long len);
/* One-cell packed byte string. The lexer matches it as List Nat. */
ouro_v *ouro_packed(const unsigned char *b, unsigned long len);
ouro_v *ouro_string_codes(const char *s);
void ouro_slash_path(char *p);
void ouro_write_codes(ouro_v *list, FILE *out);

ouro_env *ouro_cons(ouro_v *v, ouro_env *next);
ouro_v *ouro_get(ouro_env *env, int k);

/* Application for generated code. When f is the newest phase-heap cell it is
   a single-use temporary (an intermediate partial application or a branch
   closure) and its bytes are handed back before the body runs. Callers must
   not use f again after ouro_app. */
ouro_v *ouro_app(ouro_v *f, ouro_v *a);
/* Application for handwritten hosts: never reclaims, so a closure held in a
   C local or a host cache can be applied any number of times. */
ouro_v *ouro_apply(ouro_v *f, ouro_v *a);
/* Branch dispatch: branches stay curried, the scrutinee's fields are applied
   here, so the emitter needs no name for the match itself. Fresh branch cells
   that sit on top of the phase heap are reclaimed once the arm is chosen;
   callers must not reuse the branch array after ouro_case. */
ouro_v *ouro_case(ouro_v *s, int n, ouro_v **branches);
ouro_v *ouro_err(int code);

/* Host replacements for extracted Peano/list recursion. Same values, linear
   work. The C emitter does not rewrite tail calls; ouro1 needs these to print
   a compiler module without quadratic Peano append. */
ouro_v *ouro_fast(const char *name);

/* Structural rendering shared with the JS comparator: {t:N,a:[...]}. */
void ouro_show(ouro_v *v);
void ouro_show_line(ouro_v *v);

/* Last intern table from the frontend glue compile (ids → names). */
ouro_v *ouro_fe_last_intern(void);

/* Views of the last successful CheckedProgram, before the legacy projection. */
ouro_v *ouro_fe_checked_dump(ouro_v *fuel);
ouro_v *ouro_fe_checked_type_globals(ouro_v *fuel);
ouro_v *ouro_fe_checked_c_shims(void);
/* Explicit C ownership boundary: discards phase storage and replaces both
   permanent banks. The caller must retain unrelated data outside those banks.
   The curried entry instead isolates work storage for ordinary Ouro callers.
   Both return CompResult CheckedProgram when frontend_link.c is linked. */
ouro_v *ouro_fe_compile_checked_units(ouro_v *fuel, ouro_v *root, ouro_v *files);
ouro_v *ouro_fe_compile_checked_units_clos(void);

#endif
