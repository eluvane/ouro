/* Runtime for generated C: bump allocation is safe here because compiler/tool runs are short-lived. */

#include "ouro_rt.h"

unsigned long long ouro_heap_live_bytes(void);
unsigned long long ouro_heap_total_alloc_bytes(void);

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define OURO_BLOCK (1024UL * 1024UL)
/* Cells hold ints and pointers only, so pointer alignment is enough. The
   trailing field vector of a wide constructor relies on the cell size being a
   whole number of pointers. */
#define OURO_ALIGN 8UL
#define OURO_ROUND(size) (((size) + (OURO_ALIGN - 1UL)) & ~(OURO_ALIGN - 1UL))
typedef char ouro_cell_size_check[sizeof(ouro_v) % OURO_ALIGN == 0 &&
                                  sizeof(ouro_v) % sizeof(void *) == 0 ? 1 : -1];
/* Nullary constructors and small packed nats are immutable and structurally
   identical, so one static cell per (tag) or (value) serves every use. */
#define OURO_NULLARY_CACHE 64
#define OURO_NAT_CACHE 1024

static char **ouro_blocks;
static unsigned long *ouro_bsizes;
static unsigned long ouro_nblocks;
static unsigned long ouro_bcap;
static char *ouro_block;
static unsigned long ouro_used;
static unsigned long ouro_cap;
static unsigned long ouro_mark_n;
static unsigned long ouro_mark_used;
static unsigned long long ouro_total_alloc_bytes;
static unsigned long ouro_static_depth;
static unsigned long ouro_perm_depth;
static int ouro_perm_bank;
static ouro_v *ouro_nullary[OURO_NULLARY_CACHE];
static ouro_v *ouro_small_nat[OURO_NAT_CACHE];
/* Phase-heap bytes handed back early by ouro_app / ouro_case. */
static unsigned long long ouro_reclaimed_bytes;

static char **ouro_perm_blocks;
static unsigned long *ouro_perm_bsizes;
static unsigned long ouro_perm_nblocks;
static unsigned long ouro_perm_bcap;
static char *ouro_perm_block;
static unsigned long ouro_perm_used;
static unsigned long ouro_perm_cap;

static char **ouro_perm1_blocks;
static unsigned long *ouro_perm1_bsizes;
static unsigned long ouro_perm1_nblocks;
static unsigned long ouro_perm1_bcap;
static char *ouro_perm1_block;
static unsigned long ouro_perm1_used;
static unsigned long ouro_perm1_cap;

static char **ouro_static_blocks;
static unsigned long *ouro_static_bsizes;
static unsigned long ouro_static_nblocks;
static unsigned long ouro_static_bcap;
static char *ouro_static_block;
static unsigned long ouro_static_used;
static unsigned long ouro_static_cap;

typedef struct {
	char **blocks;
	unsigned long *bsizes;
	unsigned long nblocks;
	unsigned long bcap;
	char *block;
	unsigned long used;
	unsigned long cap;
} ouro_bank_state;

struct ouro_heap_context {
	ouro_bank_state phase;
	ouro_bank_state perm[2];
	unsigned long mark_n;
	unsigned long mark_used;
	unsigned long static_depth;
	unsigned long perm_depth;
	int perm_bank;
	ouro_heap_context *previous;
};

static ouro_heap_context *ouro_active_context;

static void ouro_oom(const char *where, unsigned long want)
{
	fprintf(stderr,
		"ouro_rt: out of memory (%s want=%lu live_bytes=%llu total_alloc_bytes=%llu)\n",
		where == 0 ? "?" : where, want, ouro_heap_live_bytes(),
		ouro_heap_total_alloc_bytes());
	exit(1);
}

static void *alloc_bank(unsigned long size, char ***blocks, unsigned long **bsizes,
                        unsigned long *nblocks, unsigned long *bcap,
                        char **block, unsigned long *used, unsigned long *cap)
{
	void *p;
	size = OURO_ROUND(size);
	if (*block == 0 || *used + size > *cap) {
		unsigned long want = size > OURO_BLOCK ? size : OURO_BLOCK;
		if (*nblocks == *bcap) {
			unsigned long nc = *bcap == 0 ? 16UL : *bcap * 2UL;
			*blocks = (char **)realloc(*blocks, nc * sizeof(char *));
			*bsizes = (unsigned long *)realloc(*bsizes, nc * sizeof(unsigned long));
			if (*blocks == 0 || *bsizes == 0)
				ouro_oom("realloc-bank", nc * (unsigned long)sizeof(char *));
			*bcap = nc;
		}
		*block = (char *)malloc(want);
		if (*block == 0)
			ouro_oom("malloc-bank", want);
		(*blocks)[*nblocks] = *block;
		(*bsizes)[*nblocks] = want;
		(*nblocks)++;
		*used = 0;
		*cap = want;
	}
	p = *block + *used;
	*used += size;
	ouro_total_alloc_bytes += size;
	return p;
}

static void reset_bank(char ***blocks, unsigned long **bsizes,
                       unsigned long *nblocks, unsigned long *bcap,
                       char **block, unsigned long *used, unsigned long *cap)
{
	while (*nblocks > 0) {
		(*nblocks)--;
		free((*blocks)[*nblocks]);
		(*blocks)[*nblocks] = 0;
	}
	*block = 0;
	*used = 0;
	*cap = 0;
	(void)bsizes;
	(void)bcap;
}

static void exchange_bank(ouro_bank_state *saved, char ***blocks,
	unsigned long **bsizes, unsigned long *nblocks, unsigned long *bcap,
	char **block, unsigned long *used, unsigned long *cap)
{
	ouro_bank_state current = {*blocks, *bsizes, *nblocks, *bcap, *block, *used, *cap};
	*blocks = saved->blocks;
	*bsizes = saved->bsizes;
	*nblocks = saved->nblocks;
	*bcap = saved->bcap;
	*block = saved->block;
	*used = saved->used;
	*cap = saved->cap;
	*saved = current;
}

static void exchange_heap_context(ouro_heap_context *context)
{
	unsigned long mark_n = ouro_mark_n;
	unsigned long mark_used = ouro_mark_used;
	unsigned long static_depth = ouro_static_depth;
	unsigned long perm_depth = ouro_perm_depth;
	int perm_bank = ouro_perm_bank;
	exchange_bank(&context->phase, &ouro_blocks, &ouro_bsizes, &ouro_nblocks,
		&ouro_bcap, &ouro_block, &ouro_used, &ouro_cap);
	exchange_bank(&context->perm[0], &ouro_perm_blocks, &ouro_perm_bsizes,
		&ouro_perm_nblocks, &ouro_perm_bcap, &ouro_perm_block,
		&ouro_perm_used, &ouro_perm_cap);
	exchange_bank(&context->perm[1], &ouro_perm1_blocks, &ouro_perm1_bsizes,
		&ouro_perm1_nblocks, &ouro_perm1_bcap, &ouro_perm1_block,
		&ouro_perm1_used, &ouro_perm1_cap);
	ouro_mark_n = context->mark_n;
	ouro_mark_used = context->mark_used;
	ouro_static_depth = context->static_depth;
	ouro_perm_depth = context->perm_depth;
	ouro_perm_bank = context->perm_bank;
	context->mark_n = mark_n;
	context->mark_used = mark_used;
	context->static_depth = static_depth;
	context->perm_depth = perm_depth;
	context->perm_bank = perm_bank;
}

ouro_heap_context *ouro_heap_context_enter(void)
{
	ouro_heap_context *context = (ouro_heap_context *)calloc(1, sizeof(*context));
	if (context == 0)
		ouro_oom("heap-context", (unsigned long)sizeof(*context));
	context->previous = ouro_active_context;
	exchange_heap_context(context);
	ouro_active_context = context;
	return context;
}

static void free_context_bank(ouro_bank_state *bank)
{
	reset_bank(&bank->blocks, &bank->bsizes, &bank->nblocks, &bank->bcap,
		&bank->block, &bank->used, &bank->cap);
	free(bank->blocks);
	free(bank->bsizes);
}

static void *ouro_static_alloc(unsigned long size)
{
	return alloc_bank(size, &ouro_static_blocks, &ouro_static_bsizes,
	                  &ouro_static_nblocks, &ouro_static_bcap,
	                  &ouro_static_block, &ouro_static_used, &ouro_static_cap);
}

void ouro_static_begin(void)
{
	ouro_static_depth++;
}

void ouro_static_end(void)
{
	if (ouro_static_depth > 0)
		ouro_static_depth--;
}

void ouro_perm_begin(void)
{
	ouro_perm_depth++;
}

void ouro_perm_end(void)
{
	if (ouro_perm_depth > 0)
		ouro_perm_depth--;
}

void ouro_perm_select(int bank)
{
	ouro_perm_bank = bank == 1 ? 1 : 0;
}

void ouro_perm_reset_bank(int bank)
{
	if (bank == 1)
		reset_bank(&ouro_perm1_blocks, &ouro_perm1_bsizes, &ouro_perm1_nblocks,
		           &ouro_perm1_bcap, &ouro_perm1_block, &ouro_perm1_used,
		           &ouro_perm1_cap);
	else
		reset_bank(&ouro_perm_blocks, &ouro_perm_bsizes, &ouro_perm_nblocks,
		           &ouro_perm_bcap, &ouro_perm_block, &ouro_perm_used,
		           &ouro_perm_cap);
}

void *ouro_alloc(unsigned long size)
{
	void *p;
	if (ouro_static_depth > 0)
		return ouro_static_alloc(size);
	if (ouro_perm_depth > 0)
		return ouro_perm_alloc(size);
	size = OURO_ROUND(size);
	if (ouro_block == 0 || ouro_used + size > ouro_cap) {
		unsigned long want = size > OURO_BLOCK ? size : OURO_BLOCK;
		if (ouro_nblocks == ouro_bcap) {
			unsigned long nc = ouro_bcap == 0 ? 16UL : ouro_bcap * 2UL;
			ouro_blocks = (char **)realloc(ouro_blocks, nc * sizeof(char *));
			ouro_bsizes = (unsigned long *)realloc(
				ouro_bsizes, nc * sizeof(unsigned long));
			if (ouro_blocks == 0 || ouro_bsizes == 0)
				ouro_oom("realloc-phase", nc * (unsigned long)sizeof(char *));
			ouro_bcap = nc;
		}
		ouro_block = (char *)malloc(want);
		if (ouro_block == 0)
			ouro_oom("malloc-phase", want);
		ouro_blocks[ouro_nblocks] = ouro_block;
		ouro_bsizes[ouro_nblocks] = want;
		ouro_nblocks++;
		ouro_used = 0;
		ouro_cap = want;
	}
	p = ouro_block + ouro_used;
	ouro_used += size;
	ouro_total_alloc_bytes += size;
	return p;
}

void *ouro_perm_alloc(unsigned long size)
{
	if (ouro_perm_bank == 1)
		return alloc_bank(size, &ouro_perm1_blocks, &ouro_perm1_bsizes,
		                  &ouro_perm1_nblocks, &ouro_perm1_bcap,
		                  &ouro_perm1_block, &ouro_perm1_used, &ouro_perm1_cap);
	return alloc_bank(size, &ouro_perm_blocks, &ouro_perm_bsizes,
	                  &ouro_perm_nblocks, &ouro_perm_bcap,
	                  &ouro_perm_block, &ouro_perm_used, &ouro_perm_cap);
}

void ouro_heap_mark(void)
{
	ouro_mark_n = ouro_nblocks;
	ouro_mark_used = ouro_used;
}

void ouro_heap_reset(void)
{
	while (ouro_nblocks > ouro_mark_n) {
		ouro_nblocks--;
		free(ouro_blocks[ouro_nblocks]);
		ouro_blocks[ouro_nblocks] = 0;
	}
	if (ouro_nblocks == 0) {
		ouro_block = 0;
		ouro_used = 0;
		ouro_cap = 0;
		return;
	}
	ouro_block = ouro_blocks[ouro_nblocks - 1];
	ouro_cap = ouro_bsizes[ouro_nblocks - 1];
	ouro_used = ouro_mark_used;
}

void ouro_heap_discard_phase(void)
{
	/* Drop the whole phase bank. Compiler seams clone the values they
	   still need onto the permanent heap first. */
	ouro_mark_n = 0;
	ouro_mark_used = 0;
	ouro_heap_reset();
}


static unsigned long long heap_bytes(unsigned long *bsizes, unsigned long nblocks,
                                     unsigned long used)
{
	unsigned long i;
	unsigned long long n = 0;
	if (bsizes == 0 || nblocks == 0)
		return 0;
	for (i = 0; i + 1 < nblocks; i++)
		n += (unsigned long long)bsizes[i];
	n += (unsigned long long)used;
	return n;
}

unsigned long long ouro_heap_live_bytes(void)
{
	ouro_heap_context *context;
	unsigned long long live = heap_bytes(ouro_bsizes, ouro_nblocks, ouro_used) +
	       heap_bytes(ouro_perm_bsizes, ouro_perm_nblocks, ouro_perm_used) +
	       heap_bytes(ouro_perm1_bsizes, ouro_perm1_nblocks, ouro_perm1_used) +
	       heap_bytes(ouro_static_bsizes, ouro_static_nblocks, ouro_static_used);
	for (context = ouro_active_context; context != 0; context = context->previous) {
		live += heap_bytes(context->phase.bsizes, context->phase.nblocks, context->phase.used);
		live += heap_bytes(context->perm[0].bsizes, context->perm[0].nblocks, context->perm[0].used);
		live += heap_bytes(context->perm[1].bsizes, context->perm[1].nblocks, context->perm[1].used);
	}
	return live;
}

unsigned long long ouro_heap_total_alloc_bytes(void)
{
	return ouro_total_alloc_bytes;
}

static int ouro_trace_enabled(void)
{
	const char *s = getenv("OURO_MEM_TRACE");
	return s != 0 && s[0] != 0 && strcmp(s, "0") != 0;
}

void ouro_heap_report(const char *label)
{
	if (!ouro_trace_enabled())
		return;
	fprintf(stderr,
		"OURO_MEM_HEAP label=%s live_bytes=%llu phase_blocks=%lu perm_blocks=%lu static_blocks=%lu total_alloc_bytes=%llu reclaimed_bytes=%llu\n",
		label == 0 ? "" : label, ouro_heap_live_bytes(), ouro_nblocks,
		ouro_perm_nblocks + ouro_perm1_nblocks, ouro_static_nblocks,
		ouro_total_alloc_bytes, ouro_reclaimed_bytes);
}

unsigned long long ouro_heap_reclaimed_bytes(void)
{
	return ouro_reclaimed_bytes;
}

void ouro_gc_set_stack_base(void *p) { (void)p; }
void ouro_gc_collect(void) { }
void ouro_gc_push_root(ouro_v **slot) { (void)slot; }
void ouro_gc_pop_roots(unsigned long n) { (void)n; }
unsigned long ouro_gc_root_count(void) { return 0; }

static int ptr_in_blocks(const void *p, char **blocks, unsigned long *bsizes,
                         unsigned long nblocks)
{
	unsigned long i;
	const char *cp = (const char *)p;
	if (p == 0 || blocks == 0)
		return 0;
	for (i = 0; i < nblocks; i++) {
		char *b = blocks[i];
		if (b != 0 && cp >= b && cp < b + bsizes[i])
			return 1;
	}
	return 0;
}

static int ptr_is_static(const void *p)
{
	return ptr_in_blocks(p, ouro_static_blocks, ouro_static_bsizes,
	                     ouro_static_nblocks);
}

static int ptr_is_current_perm(const void *p)
{
	if (ouro_perm_bank == 1)
		return ptr_in_blocks(p, ouro_perm1_blocks, ouro_perm1_bsizes,
		                     ouro_perm1_nblocks);
	return ptr_in_blocks(p, ouro_perm_blocks, ouro_perm_bsizes,
	                     ouro_perm_nblocks);
}

typedef struct {
	const void **k;
	void **v;
	unsigned long cap;
	unsigned long used;
	void *(*allocate)(unsigned long);
} clone_tab;

static unsigned long clone_hash(const void *p)
{
	uintptr_t x = (uintptr_t)p;
	x ^= x >> 16;
	x *= (uintptr_t)0x45d9f3bUL;
	x ^= x >> 16;
	return (unsigned long)x;
}

static int clone_tab_init(clone_tab *t, unsigned long cap, void *(*allocate)(unsigned long))
{
	t->k = (const void **)calloc(cap, sizeof(const void *));
	t->v = (void **)calloc(cap, sizeof(void *));
	t->cap = cap;
	t->used = 0;
	t->allocate = allocate;
	if (t->k != 0 && t->v != 0)
		return 1;
	free(t->k);
	free(t->v);
	t->k = 0;
	t->v = 0;
	t->cap = 0;
	return 0;
}

static void clone_tab_free(clone_tab *t)
{
	free(t->k);
	free(t->v);
	t->k = 0;
	t->v = 0;
	t->cap = 0;
	t->used = 0;
}

static int clone_tab_grow(clone_tab *t);

static void *clone_tab_get(clone_tab *t, const void *key)
{
	unsigned long i;
	unsigned long mask;
	if (t->cap == 0 || key == 0)
		return 0;
	mask = t->cap - 1UL;
	i = clone_hash(key) & mask;
	for (;;) {
		if (t->k[i] == 0)
			return 0;
		if (t->k[i] == key)
			return t->v[i];
		i = (i + 1UL) & mask;
	}
}

static int clone_tab_put(clone_tab *t, const void *key, void *val)
{
	unsigned long i;
	unsigned long mask;
	if (key == 0)
		return 1;
	if (t->used * 2UL >= t->cap && !clone_tab_grow(t))
		return 0;
	mask = t->cap - 1UL;
	i = clone_hash(key) & mask;
	for (;;) {
		if (t->k[i] == 0) {
			t->k[i] = key;
			t->v[i] = val;
			t->used++;
			return 1;
		}
		if (t->k[i] == key) {
			t->v[i] = val;
			return 1;
		}
		i = (i + 1UL) & mask;
	}
}

static int clone_tab_grow(clone_tab *t)
{
	clone_tab n;
	unsigned long i;
	unsigned long cap = t->cap == 0 ? 64UL : t->cap * 2UL;
	if (!clone_tab_init(&n, cap, t->allocate))
		return 0;
	for (i = 0; i < t->cap; i++) {
		if (t->k[i] != 0 && !clone_tab_put(&n, t->k[i], t->v[i])) {
			clone_tab_free(&n);
			return 0;
		}
	}
	clone_tab_free(t);
	*t = n;
	return 1;
}

static ouro_env *clone_env_rec(ouro_env *e, clone_tab *tab, int skip_cur_perm);
static ouro_v *clone_perm_rec(ouro_v *v, clone_tab *tab, int skip_cur_perm);

static int clone_share_env(const ouro_env *e, int skip_cur_perm)
{
	if (e == 0)
		return 1;
	if (ptr_is_static(e))
		return 1;
	return skip_cur_perm && ptr_is_current_perm(e);
}

static int clone_share_val(const ouro_v *v, int skip_cur_perm)
{
	if (v == 0)
		return 1;
	if (ptr_is_static(v))
		return 1;
	return skip_cur_perm && ptr_is_current_perm(v);
}

static ouro_env *clone_env_rec(ouro_env *e, clone_tab *tab, int skip_cur_perm)
{
	ouro_env *out;
	void *seen;
	if (e == 0)
		return 0;
	if (clone_share_env(e, skip_cur_perm))
		return e;
	seen = clone_tab_get(tab, e);
	if (seen != 0)
		return (ouro_env *)seen;
	out = (ouro_env *)tab->allocate(sizeof(ouro_env));
	if (!clone_tab_put(tab, e, out))
		ouro_oom("clone-tab-growth", tab->cap * 2UL);
	out->v = 0;
	out->next = 0;
	out->v = clone_perm_rec(e->v, tab, skip_cur_perm);
	out->next = clone_env_rec(e->next, tab, skip_cur_perm);
	return out;
}

/* Constructors (tag >= 0) and concat nodes carry a field vector; every other
   variant keeps its payload in the cell itself. */
static int has_fields(const ouro_v *v)
{
	return v->tag >= 0 || v->tag == OURO_TAG_CAT;
}

/* Bytes of one cell including the trailing field vector of a wide
   constructor. */
static unsigned long cell_size(const ouro_v *v)
{
	unsigned long size = sizeof(ouro_v);
	if (has_fields(v) && v->n > OURO_INLINE_FIELDS)
		size += (unsigned long)v->n * sizeof(ouro_v *);
	return size;
}

static ouro_v *clone_perm_rec(ouro_v *v, clone_tab *tab, int skip_cur_perm)
{
	ouro_v *out;
	void *seen;
	int i;
	if (v == 0)
		return 0;
	if (clone_share_val(v, skip_cur_perm))
		return v;
	seen = clone_tab_get(tab, v);
	if (seen != 0)
		return (ouro_v *)seen;
	out = (ouro_v *)tab->allocate(cell_size(v));
	if (!clone_tab_put(tab, v, out))
		ouro_oom("clone-tab-growth", tab->cap * 2UL);
	out->tag = v->tag;
	out->n = v->n;
	out->u = v->u;
	if (v->tag == OURO_TAG_CLOS || v->tag == OURO_TAG_THUNK) {
		out->u.c.env = 0;
		out->u.c.env = clone_env_rec(v->u.c.env, tab, skip_cur_perm);
		return out;
	}
	if ((v->tag == OURO_TAG_BYTES || v->tag == OURO_TAG_STR) && v->u.s != 0 && v->n >= 0) {
		/* Pattern matching creates phase cells for immutable byte suffixes.
		   Their backing buffer may already have the clone's lifetime. Copying
		   it for every token otherwise retains quadratic source bytes. Deep
		   clones still copy buffers in the current bank before its reset. */
		if (ptr_is_static(v->u.s) || (skip_cur_perm && ptr_is_current_perm(v->u.s)))
			return out;
		unsigned long n = v->tag == OURO_TAG_STR ? (unsigned long)strlen(v->u.s)
		                                      : (unsigned long)v->n;
		char *copy = (char *)tab->allocate(n + 1UL);
		if (n > 0)
			memcpy(copy, v->u.s, (size_t)n);
		copy[n] = 0;
		out->u.s = copy;
		if (v->tag == OURO_TAG_STR && v->n == 0 && n > 0)
			out->n = (int)n;
		return out;
	}
	if (has_fields(v) && v->n > 0) {
		ouro_v **src = ouro_fields(v);
		ouro_v **dst = ouro_fields(out);
		for (i = 0; i < v->n; i++)
			dst[i] = 0;
		for (i = 0; i < v->n; i++)
			dst[i] = clone_perm_rec(src[i], tab, skip_cur_perm);
	}
	return out;
}

static ouro_v *clone_mode(ouro_v *v, int skip_cur_perm, void *(*allocate)(unsigned long))
{
	clone_tab tab;
	ouro_v *out;
	if (v == 0)
		return 0;
	if (clone_share_val(v, skip_cur_perm))
		return v;
	if (!clone_tab_init(&tab, 64UL, allocate))
		ouro_oom("clone-tab", 64UL);
	out = clone_perm_rec(v, &tab, skip_cur_perm);
	clone_tab_free(&tab);
	return out;
}

ouro_v *ouro_clone_perm(ouro_v *v)
{
	return clone_mode(v, 1, ouro_perm_alloc);
}

ouro_v *ouro_clone_perm_deep(ouro_v *v)
{
	return clone_mode(v, 0, ouro_perm_alloc);
}

ouro_v *ouro_heap_context_leave(ouro_heap_context *context, ouro_v *survivor)
{
	ouro_v *retained;
	if (context == 0 || context != ouro_active_context) {
		fputs("ouro_rt: heap contexts must leave in reverse entry order\n", stderr);
		exit(1);
	}
	/* The work banks stay allocated but are no longer current. Deep cloning
	   therefore copies their byte buffers instead of borrowing freed storage.
	   The caller's depths also restore static getter and permanent ownership. */
	exchange_heap_context(context);
	retained = clone_mode(survivor, 0, ouro_alloc);
	free_context_bank(&context->phase);
	free_context_bank(&context->perm[0]);
	free_context_bank(&context->perm[1]);
	ouro_active_context = context->previous;
	free(context);
	return retained;
}

/* Keep one survivor across a phase reset. Ping-pong the perm banks so
   the previous kept value is dropped instead of accumulating copies. */
ouro_v *ouro_keep(ouro_v *v)
{
	int next = ouro_perm_bank == 0 ? 1 : 0;
	ouro_v *kept;

	ouro_perm_select(next);
	ouro_perm_reset_bank(next);
	kept = ouro_clone_perm_deep(v);
	ouro_heap_discard_phase();
	ouro_perm_reset_bank(1 - next);
	return kept;
}

static ouro_v *ouro_new(int tag, int n)
{
	ouro_v *v = (ouro_v *)ouro_alloc(sizeof(ouro_v));
	v->tag = tag;
	v->n = n;
	v->u.inl[0] = 0;
	v->u.inl[1] = 0;
	return v;
}

static ouro_v *mk_cat(ouro_v *a, ouro_v *b)
{
	ouro_v *v = ouro_new(OURO_TAG_CAT, 2);
	v->u.inl[0] = a;
	v->u.inl[1] = b;
	return v;
}

static ouro_v *mk_bytes(unsigned char *buf, unsigned long len)
{
	ouro_v *v = ouro_new(OURO_TAG_BYTES, (int)len);
	v->u.s = (const char *)buf;
	return v;
}

static int is_empty_list(ouro_v *xs)
{
	return xs == 0 || (xs->tag == 0 && xs->n == 0);
}

/* Nullary constructors of the same tag are indistinguishable, so Nil, Z,
   True, Unit, ... of the common tags share one static cell each. */
static ouro_v *nullary(int tag)
{
	ouro_v *v = ouro_nullary[tag];
	if (v == 0) {
		ouro_static_begin();
		v = ouro_new(tag, 0);
		ouro_static_end();
		ouro_nullary[tag] = v;
	}
	return v;
}

ouro_v *ouro_ctor(int tag, int n, ouro_v **fields)
{
	ouro_v *v;
	ouro_v **dst;
	int i;
	if (n <= 0) {
		if (tag >= 0 && tag < OURO_NULLARY_CACHE)
			return nullary(tag);
		return ouro_new(tag, 0);
	}
	if (n <= OURO_INLINE_FIELDS) {
		v = ouro_new(tag, n);
		dst = v->u.inl;
	} else {
		v = (ouro_v *)ouro_alloc(sizeof(ouro_v) +
		                         (unsigned long)n * sizeof(ouro_v *));
		v->tag = tag;
		v->n = n;
		v->u.inl[0] = 0;
		v->u.inl[1] = 0;
		dst = (ouro_v **)(v + 1);
	}
	for (i = 0; i < n; i++)
		dst[i] = fields[i];
	return v;
}

ouro_v *ouro_clos(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env)
{
	ouro_v *v = ouro_new(OURO_TAG_CLOS, 0);
	v->u.c.fn = fn;
	v->u.c.env = env;
	return v;
}

ouro_v *ouro_fix(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env)
{
	ouro_v *v = ouro_clos(fn, env);
	v->u.c.env = ouro_cons(v, env);
	return v;
}

ouro_v *ouro_thunk(ouro_v *(*fn)(ouro_env *, ouro_v *), ouro_env *env)
{
	ouro_v *v = ouro_clos(fn, env);
	v->tag = OURO_TAG_THUNK;
	return v;
}

ouro_v *ouro_str(const char *s)
{
	/* Native strings carry their byte length so parser cursors can inspect
	   successive bytes without re-running strlen for every character. */
	ouro_v *v = ouro_new(OURO_TAG_STR, s != 0 ? (int)strlen(s) : 0);
	v->u.s = s;
	return v;
}

ouro_v *ouro_nat(unsigned long n)
{
	ouro_v *v;
	/* Host nats (fuel, file bytes) stay one cell. ouro_case unfolds
	   them as Z/S so extracted matches keep their meaning. Small values
	   (every byte code, most counters) come from a static table. */
	if (n < OURO_NAT_CACHE) {
		v = ouro_small_nat[n];
		if (v == 0) {
			ouro_static_begin();
			v = ouro_new(OURO_TAG_NAT, (int)n);
			ouro_static_end();
			ouro_small_nat[n] = v;
		}
		return v;
	}
	return ouro_new(OURO_TAG_NAT, (int)n);
}

ouro_v *ouro_bytes(const unsigned char *b, unsigned long len)
{
	ouro_v *v = ouro_ctor(0, 0, 0);
	ouro_v *cell[2];
	while (len > 0) {
		len--;
		cell[0] = ouro_nat((unsigned long)b[len]);
		cell[1] = v;
		v = ouro_ctor(1, 2, cell);
	}
	return v;
}

ouro_v *ouro_packed(const unsigned char *b, unsigned long len)
{
	unsigned char *copy;
	ouro_v *v = ouro_new(OURO_TAG_BYTES, (int)len);
	copy = (unsigned char *)ouro_alloc(len + 1UL);
	if (len > 0 && b != 0)
		memcpy(copy, b, (size_t)len);
	copy[len] = 0;
	v->u.s = (const char *)copy;
	return v;
}

ouro_v *ouro_string_codes(const char *s)
{
	if (s == 0)
		return ouro_packed(0, 0);
	return ouro_packed((const unsigned char *)s, (unsigned long)strlen(s));
}

void ouro_slash_path(char *p)
{
	for (; p != 0 && *p != 0; p++) {
		if (*p == '\\')
			*p = '/';
	}
}

/* Inverse of ouro_bytes: a List Nat back out to a stream, so text a compiled
   module produced can leave without any algorithm in C. Peano depth is the
   byte value, and a cell that is neither Nil nor Cons is a bug in the caller,
   not something to paper over. Packed host nats are the same values. Concat
   nodes and packed chunks are the same string, just not yet flattened. */
void ouro_write_codes(ouro_v *list, FILE *out)
{
	ouro_v *stack[4096];
	int sp = 0;
	for (;;) {
		if (list == 0) {
			if (sp == 0)
				return;
			list = stack[--sp];
			continue;
		}
		if (list->tag == OURO_TAG_CAT && list->n == 2) {
			if (sp < 4095) {
				stack[sp++] = OURO_F(list, 1);
				list = OURO_F(list, 0);
			} else {
				ouro_write_codes(OURO_F(list, 0), out);
				list = OURO_F(list, 1);
			}
			continue;
		}
		if (list->tag == OURO_TAG_BYTES) {
			if (list->n > 0 && list->u.s != 0)
				fwrite(list->u.s, 1, (size_t)list->n, out);
			if (sp == 0)
				return;
			list = stack[--sp];
			continue;
		}
		if (list->tag == 1 && list->n == 2) {
			ouro_v *d = OURO_F(list, 0);
			unsigned long b = 0;
			if (d != 0 && d->tag == OURO_TAG_CAT && d->n == 2) {
				ouro_write_codes(d, out);
				list = OURO_F(list, 1);
				continue;
			}
			if (d != 0 && d->tag == OURO_TAG_BYTES) {
				if (d->n > 0 && d->u.s != 0)
					fwrite(d->u.s, 1, (size_t)d->n, out);
				list = OURO_F(list, 1);
				continue;
			}
			if (d != 0 && d->tag == OURO_TAG_NAT) {
				b = (unsigned long)d->n;
			} else {
				while (d != 0 && d->tag == 1 && d->n == 1) {
					b++;
					d = OURO_F(d, 0);
				}
				if (d != 0 && d->tag == OURO_TAG_NAT) {
					b += (unsigned long)d->n;
				} else if (d == 0 || d->tag != 0) {
					fputs("ouro_rt: write_codes: element is not a Nat\n",
					      stderr);
					exit(1);
				}
			}
			fputc((int)(b & 0xFFUL), out);
			list = OURO_F(list, 1);
			continue;
		}
		if (list->tag == 0) {
			if (sp == 0)
				return;
			list = stack[--sp];
			continue;
		}
		fprintf(stderr, "ouro_rt: write_codes: not a List Nat tag=%d n=%d",
			list->tag, list->n);
		if (has_fields(list) && list->n >= 1 && OURO_F(list, 0) != 0)
			fprintf(stderr, " a0.tag=%d a0.n=%d",
				OURO_F(list, 0)->tag, OURO_F(list, 0)->n);
		if (has_fields(list) && list->n >= 2 && OURO_F(list, 1) != 0)
			fprintf(stderr, " a1.tag=%d a1.n=%d",
				OURO_F(list, 1)->tag, OURO_F(list, 1)->n);
		fputc('\n', stderr);
		exit(1);
	}
}

ouro_env *ouro_cons(ouro_v *v, ouro_env *next)
{
	ouro_env *e = (ouro_env *)ouro_alloc(sizeof(ouro_env));
	e->v = v;
	e->next = next;
	return e;
}

ouro_v *ouro_get(ouro_env *env, int k)
{
	while (k > 0 && env != 0) {
		env = env->next;
		k--;
	}
	if (env == 0) {
		fputs("ouro_rt: unbound variable\n", stderr);
		exit(1);
	}
	return env->v;
}

/* Early reclamation.

   Generated code builds a fresh closure or thunk for every partial
   application and every case branch, uses it exactly once, and never keeps a
   pointer to it anywhere else: closures reach other cells only through
   ouro_cons / ouro_ctor, and those cells are allocated after the closure,
   which puts them above it in the bump heap. So a closure or thunk that is
   still the newest phase allocation when it is applied or when a branch is
   selected is referenced by nothing except the C expression consuming it, and
   its bytes can be handed straight back to the allocator. Handwritten hosts
   may hold closures in C locals and call them repeatedly; they use ouro_apply,
   which never reclaims. Static and permanent sections never reclaim either,
   because generated caches live there and are called many times. */
static int phase_top(const void *p, unsigned long bytes)
{
	return ouro_block != 0 && ouro_static_depth == 0 &&
	       ouro_perm_depth == 0 && ouro_used >= bytes &&
	       (const char *)p == ouro_block + (ouro_used - bytes);
}

static void phase_pop(unsigned long bytes)
{
	ouro_used -= bytes;
	ouro_reclaimed_bytes += bytes;
}

static void app_check(const ouro_v *f)
{
	if (f == 0 || f->tag != OURO_TAG_CLOS) {
		fputs("ouro_rt: apply of non-function\n", stderr);
		exit(1);
	}
}

ouro_v *ouro_app(ouro_v *f, ouro_v *a)
{
	ouro_v *(*fn)(ouro_env *, ouro_v *);
	ouro_env *env;
	app_check(f);
	fn = f->u.c.fn;
	env = f->u.c.env;
	if (a != f && phase_top(f, sizeof(ouro_v)))
		phase_pop(sizeof(ouro_v));
	return fn(env, a);
}

ouro_v *ouro_apply(ouro_v *f, ouro_v *a)
{
	app_check(f);
	return f->u.c.fn(f->u.c.env, a);
}

/* A branch array whose n cells are distinct closures or thunks occupying
   exactly the newest n cells of the phase heap can be reclaimed once the
   selected arm has been read out. Anything else (values reused from the
   environment, static cells, an array split across a block boundary) is left
   alone. */
#define OURO_CASE_MAX_POP 64

static int case_region_top(int n, ouro_v **branches)
{
	unsigned long bytes;
	unsigned long long mask = 0;
	const char *lo;
	int i;
	if (n <= 0 || n > OURO_CASE_MAX_POP)
		return 0;
	bytes = (unsigned long)n * sizeof(ouro_v);
	if (ouro_block == 0 || ouro_static_depth != 0 || ouro_perm_depth != 0 ||
	    ouro_used < bytes)
		return 0;
	lo = ouro_block + (ouro_used - bytes);
	for (i = 0; i < n; i++) {
		const ouro_v *b = branches[i];
		unsigned long off;
		if (b == 0 || (b->tag != OURO_TAG_CLOS && b->tag != OURO_TAG_THUNK))
			return 0;
		if ((const char *)b < lo)
			return 0;
		off = (unsigned long)((const char *)b - lo);
		if (off >= bytes || off % sizeof(ouro_v) != 0)
			return 0;
		off /= sizeof(ouro_v);
		if ((mask >> off) & 1ULL)
			return 0;
		mask |= 1ULL << off;
	}
	return 1;
}

static void case_release(int n)
{
	phase_pop((unsigned long)n * sizeof(ouro_v));
}

static void match_failure(void)
{
	fputs("ouro_rt: match failure\n", stderr);
	exit(1);
}

/* Nil/Z arm of a stream or nat scrutinee: a thunk runs, anything else is the
   value itself. */
static ouro_v *run_nil_arm(ouro_v *f)
{
	if (f != 0 && f->tag == OURO_TAG_THUNK)
		return f->u.c.fn(f->u.c.env, 0);
	return f;
}

/* One unfolding step of a stream scrutinee. Returns 1 with head/tail set
   when s is a non-empty list, 0 when s is an empty list, and -1 when s is
   not a list shape at all (the caller decides how to fail). Concat nodes are
   re-associated to the right so the head is always one cell deep. */
static int stream_step(ouro_v **sp, ouro_v **head, ouro_v **tail)
{
	for (;;) {
		ouro_v *s = *sp;
		if (s != 0 && s->tag == OURO_TAG_CAT && s->n == 2) {
			ouro_v *left = OURO_F(s, 0);
			ouro_v *right = OURO_F(s, 1);
			if (is_empty_list(left)) {
				*sp = right;
				continue;
			}
			if (left->tag == OURO_TAG_CAT && left->n == 2) {
				*sp = mk_cat(OURO_F(left, 0), mk_cat(OURO_F(left, 1), right));
				continue;
			}
			if (left->tag == OURO_TAG_BYTES) {
				if (left->n <= 0) {
					*sp = right;
					continue;
				}
				*head = ouro_nat((unsigned long)(unsigned char)left->u.s[0]);
				*tail = mk_cat(mk_bytes((unsigned char *)(left->u.s + 1),
							(unsigned long)left->n - 1UL),
					       right);
				return 1;
			}
			if (left->tag == 1 && left->n == 2) {
				*head = OURO_F(left, 0);
				*tail = mk_cat(OURO_F(left, 1), right);
				return 1;
			}
			*sp = left;
			continue;
		}
		if (s != 0 && s->tag == OURO_TAG_BYTES) {
			if (s->n <= 0)
				return 0;
			*head = ouro_nat((unsigned long)(unsigned char)s->u.s[0]);
			*tail = mk_bytes((unsigned char *)(s->u.s + 1),
					 (unsigned long)s->n - 1UL);
			return 1;
		}
		if (s != 0 && s->tag == OURO_TAG_NAT) {
			if (s->n == 0)
				return 0;
			*head = ouro_nat((unsigned long)s->n - 1UL);
			*tail = 0;
			return 1;
		}
		if (s != 0 && s->tag == 0 && s->n == 0)
			return 0;
		if (s != 0 && s->tag == 1 && s->n == 2) {
			*head = OURO_F(s, 0);
			*tail = OURO_F(s, 1);
			return 1;
		}
		return -1;
	}
}

/* Scrutinees that are not plain constructor cells: concat nodes, packed byte
   strings, and packed nats unfold to Nil/Cons or Z/S on demand. When both
   arms are fresh cells at the top of the heap they are captured and released
   before the unfolding allocates, so the unfolding reuses their space. */
static ouro_v *case_stream(ouro_v *s, int n, ouro_v **branches)
{
	ouro_v *head = 0;
	ouro_v *tail = 0;
	int step;
	if (n >= 2 && branches[0] != 0 && branches[0]->tag == OURO_TAG_THUNK &&
	    branches[1] != 0 && branches[1]->tag == OURO_TAG_CLOS &&
	    case_region_top(n, branches)) {
		ouro_v *(*nil_fn)(ouro_env *, ouro_v *) = branches[0]->u.c.fn;
		ouro_env *nil_env = branches[0]->u.c.env;
		ouro_v *(*cons_fn)(ouro_env *, ouro_v *) = branches[1]->u.c.fn;
		ouro_env *cons_env = branches[1]->u.c.env;
		case_release(n);
		step = stream_step(&s, &head, &tail);
		if (step == 0)
			return nil_fn(nil_env, 0);
		if (step > 0) {
			if (tail == 0)
				return cons_fn(cons_env, head);
			return ouro_app(cons_fn(cons_env, head), tail);
		}
		fprintf(stderr, "ouro_rt: match failure tag=%d n=%d branches=%d\n",
			s == 0 ? -999 : s->tag, s == 0 ? -1 : s->n, n);
		exit(1);
	}
	step = stream_step(&s, &head, &tail);
	if (step < 0)
		return ouro_case(s, n, branches);
	if (n < 2)
		match_failure();
	if (step == 0)
		return run_nil_arm(branches[0]);
	if (tail == 0)
		return ouro_app(branches[1], head);
	return ouro_app(ouro_app(branches[1], head), tail);
}

ouro_v *ouro_case(ouro_v *s, int n, ouro_v **branches)
{
	ouro_v *f;
	ouro_v **fields;
	int i;
	if (s != 0 && ((s->tag == OURO_TAG_CAT && s->n == 2) ||
		       s->tag == OURO_TAG_BYTES || s->tag == OURO_TAG_NAT))
		return case_stream(s, n, branches);
	if (s == 0 || s->tag < 0 || s->tag >= n) {
		fprintf(stderr, "ouro_rt: match failure tag=%d n=%d branches=%d\n",
			s == 0 ? -999 : s->tag, s == 0 ? -1 : s->n, n);
		exit(1);
	}
	f = branches[s->tag];
	if (f != 0 && f->tag == OURO_TAG_THUNK) {
		ouro_v *(*fn)(ouro_env *, ouro_v *) = f->u.c.fn;
		ouro_env *env = f->u.c.env;
		if (case_region_top(n, branches))
			case_release(n);
		return fn(env, 0);
	}
	fields = ouro_fields(s);
	if (f != 0 && f->tag == OURO_TAG_CLOS && s->n > 0) {
		ouro_v *(*fn)(ouro_env *, ouro_v *) = f->u.c.fn;
		ouro_env *env = f->u.c.env;
		if (case_region_top(n, branches))
			case_release(n);
		f = fn(env, fields[0]);
		for (i = 1; i < s->n; i++)
			f = ouro_app(f, fields[i]);
		return f;
	}
	for (i = 0; i < s->n; i++)
		f = ouro_app(f, fields[i]);
	return f;
}

ouro_v *ouro_err(int code)
{
	fprintf(stderr, "ouro_rt: extract err %d\n", code);
	exit(1);
	return 0;
}

/* Nullary constructors are interned by ouro_ctor. True is the first Bool
   constructor; Nil and Z share tag 0 with it, Lt/Eq/Gt are tags 0/1/2. */
static ouro_v *b_true(void)
{
	return nullary(0);
}

static ouro_v *b_false(void)
{
	return nullary(1);
}

static ouro_v *l_nil(void)
{
	return nullary(0);
}

void ouro_rt_warmup(void)
{
	(void)nullary(0);
	(void)nullary(1);
	(void)nullary(2);
	(void)ouro_nat(0);
}

static ouro_v *list_append_codes(ouro_v *xs, ouro_v *ys)
{
	if (is_empty_list(xs))
		return ys;
	if (is_empty_list(ys))
		return xs;
	return mk_cat(xs, ys);
}

static ouro_v *list_reverse(ouro_v *xs)
{
	ouro_v *r = l_nil();
	ouro_v *stack[128];
	int sp = 0;
	stack[sp++] = xs;
	while (sp > 0) {
		xs = stack[--sp];
		if (is_empty_list(xs))
			continue;
		if (xs->tag == OURO_TAG_CAT && xs->n == 2) {
			if (sp + 2 > 128) {
				fputs("ouro_rt: reverse overflow\n", stderr);
				exit(1);
			}
			stack[sp++] = OURO_F(xs, 1);
			stack[sp++] = OURO_F(xs, 0);
			continue;
		}
		if (xs->tag == OURO_TAG_BYTES) {
			/* Packed codes, the shape prim_string_to_char_codes returns
			   and ouro_case unfolds byte by byte: each byte becomes a
			   host nat, the first byte ending up deepest. */
			int i;
			for (i = 0; i < xs->n; i++) {
				ouro_v *cell[2];
				cell[0] = ouro_nat((unsigned long)(unsigned char)xs->u.s[i]);
				cell[1] = r;
				r = ouro_ctor(1, 2, cell);
			}
			continue;
		}
		if (xs->tag == 1 && xs->n == 2) {
			ouro_v *cell[2];
			cell[0] = OURO_F(xs, 0);
			cell[1] = r;
			r = ouro_ctor(1, 2, cell);
			stack[sp++] = OURO_F(xs, 1);
			continue;
		}
	}
	return r;
}

static ouro_v *list_length(ouro_v *xs)
{
	unsigned long n = 0;
	ouro_v *stack[64];
	int sp = 0;
	for (;;) {
		if (is_empty_list(xs)) {
			if (sp == 0)
				return ouro_nat(n);
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
			n += (unsigned long)xs->n;
			if (sp == 0)
				return ouro_nat(n);
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == 1 && xs->n == 2) {
			n++;
			xs = OURO_F(xs, 1);
			continue;
		}
		return ouro_nat(n);
	}
}

/* A Nat can mix both shapes: S applied to a packed value builds an S cell
   whose field is OURO_TAG_NAT, so the chain walk has to add what it lands on
   instead of treating it as Z. */
static unsigned long nat_value(ouro_v *n)
{
	unsigned long v = 0;
	if (n == 0)
		return 0;
	if (n->tag == OURO_TAG_NAT)
		return (unsigned long)n->n;
	while (n != 0 && n->tag == 1 && n->n == 1) {
		v++;
		n = OURO_F(n, 0);
	}
	if (n != 0 && n->tag == OURO_TAG_NAT && n->n > 0)
		v += (unsigned long)n->n;
	return v;
}

static int nat_eq(ouro_v *a, ouro_v *b)
{
	if (a != 0 && b != 0 && a->tag == OURO_TAG_NAT && b->tag == OURO_TAG_NAT)
		return a->n == b->n;
	return nat_value(a) == nat_value(b);
}

static ouro_v *nat_add(ouro_v *n, ouro_v *m)
{
	return ouro_nat(nat_value(n) + nat_value(m));
}

static ouro_v *nat_sub(ouro_v *n, ouro_v *m)
{
	unsigned long a = nat_value(n);
	unsigned long b = nat_value(m);
	return ouro_nat(a > b ? a - b : 0UL);
}

static ouro_v *nat_cmp(ouro_v *n, ouro_v *m)
{
	unsigned long a = nat_value(n);
	unsigned long b = nat_value(m);
	if (a < b)
		return nullary(0);
	if (a == b)
		return nullary(1);
	return nullary(2);
}

static ouro_v *mem_nat(ouro_v *x, ouro_v *xs)
{
	for (;;) {
		ouro_v *head = 0;
		ouro_v *tail = 0;
		int step = stream_step(&xs, &head, &tail);
		if (step == 0)
			return b_false();
		if (step < 0 || tail == 0)
			match_failure();
		if (nat_eq(head, x))
			return b_true();
		xs = tail;
	}
}

static ouro_v *f_append_ys(ouro_env *env, ouro_v *ys)
{
	return list_append_codes(env->v, ys);
}

static ouro_v *f_append_xs(ouro_env *env, ouro_v *xs)
{
	(void)env;
	return ouro_clos(f_append_ys, ouro_cons(xs, 0));
}



static ouro_v *f_eq_m(ouro_env *env, ouro_v *m)
{
	return nat_eq(env->v, m) ? b_true() : b_false();
}

static ouro_v *f_eq_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_eq_m, ouro_cons(n, 0));
}

static ouro_v *f_add_m(ouro_env *env, ouro_v *m)
{
	return nat_add(env->v, m);
}

static ouro_v *f_add_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_add_m, ouro_cons(n, 0));
}

static ouro_v *f_sub_m(ouro_env *env, ouro_v *m)
{
	return nat_sub(env->v, m);
}

static ouro_v *f_sub_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_sub_m, ouro_cons(n, 0));
}

static ouro_v *f_cmp_m(ouro_env *env, ouro_v *m)
{
	return nat_cmp(env->v, m);
}

static ouro_v *f_cmp_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_cmp_m, ouro_cons(n, 0));
}

static ouro_v *f_length_xs(ouro_env *env, ouro_v *xs)
{
	(void)env;
	return list_length(xs);
}

static ouro_v *f_reverse_xs(ouro_env *env, ouro_v *xs)
{
	(void)env;
	return list_reverse(xs);
}

static ouro_v *f_mem_xs(ouro_env *env, ouro_v *xs)
{
	return mem_nat(env->v, xs);
}

static ouro_v *f_mem_x(ouro_env *env, ouro_v *x)
{
	(void)env;
	return ouro_clos(f_mem_xs, ouro_cons(x, 0));
}

static ouro_v *nat_mul(ouro_v *n, ouro_v *m)
{
	return ouro_nat(nat_value(n) * nat_value(m));
}

static ouro_v *f_mul_m(ouro_env *env, ouro_v *m)
{
	return nat_mul(env->v, m);
}

static ouro_v *f_mul_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_mul_m, ouro_cons(n, 0));
}

/* Word32 ops for Ouro std/crypto. Packed Nat stores the bit pattern in
   v->n; the low 32 bits are the word. Not a kernel/TCB change. */
static uint32_t nat32(ouro_v *n)
{
	return (uint32_t)nat_value(n);
}

static ouro_v *w32(uint32_t x)
{
	return ouro_nat((unsigned long)x);
}

static ouro_v *f_xor32_m(ouro_env *env, ouro_v *m)
{
	return w32(nat32(env->v) ^ nat32(m));
}

static ouro_v *f_xor32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_xor32_m, ouro_cons(n, 0));
}

static ouro_v *f_and32_m(ouro_env *env, ouro_v *m)
{
	return w32(nat32(env->v) & nat32(m));
}

static ouro_v *f_and32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_and32_m, ouro_cons(n, 0));
}

static ouro_v *f_or32_m(ouro_env *env, ouro_v *m)
{
	return w32(nat32(env->v) | nat32(m));
}

static ouro_v *f_or32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_or32_m, ouro_cons(n, 0));
}

static ouro_v *f_not32(ouro_env *env, ouro_v *n)
{
	(void)env;
	return w32(~nat32(n));
}

static ouro_v *f_shl32_m(ouro_env *env, ouro_v *m)
{
	unsigned int k = nat32(m) & 31U;
	return w32(nat32(env->v) << k);
}

static ouro_v *f_shl32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_shl32_m, ouro_cons(n, 0));
}

static ouro_v *f_shr32_m(ouro_env *env, ouro_v *m)
{
	unsigned int k = nat32(m) & 31U;
	return w32(nat32(env->v) >> k);
}

static ouro_v *f_shr32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_shr32_m, ouro_cons(n, 0));
}

static ouro_v *f_rotr32_m(ouro_env *env, ouro_v *m)
{
	unsigned int k = nat32(m) & 31U;
	uint32_t x = nat32(env->v);
	if (k == 0)
		return w32(x);
	return w32((x >> k) | (x << (32U - k)));
}

static ouro_v *f_rotr32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_rotr32_m, ouro_cons(n, 0));
}

static ouro_v *f_add32_m(ouro_env *env, ouro_v *m)
{
	return w32(nat32(env->v) + nat32(m));
}

static ouro_v *f_add32_n(ouro_env *env, ouro_v *n)
{
	(void)env;
	return ouro_clos(f_add32_m, ouro_cons(n, 0));
}

static ouro_v *opt_none(void)
{
	return ouro_ctor(0, 0, 0);
}

static ouro_v *opt_some(ouro_v *x)
{
	ouro_v *c[1];
	c[0] = x;
	return ouro_ctor(1, 1, c);
}

static ouro_v *list_nth(ouro_v *xs, ouro_v *idx)
{
	unsigned long k = nat_value(idx);
	for (;;) {
		ouro_v *head = 0;
		ouro_v *tail = 0;
		int step = stream_step(&xs, &head, &tail);
		if (step == 0)
			return opt_none();
		if (step < 0 || tail == 0)
			match_failure();
		if (k == 0)
			return opt_some(head);
		k--;
		xs = tail;
	}
}

static ouro_v *f_nth_i(ouro_env *env, ouro_v *i)
{
	return list_nth(env->v, i);
}

static ouro_v *f_nth_xs(ouro_env *env, ouro_v *xs)
{
	(void)env;
	return ouro_clos(f_nth_i, ouro_cons(xs, 0));
}

ouro_v *ouro_fast(const char *name)
{
	ouro_v *v = 0;
	/* Host prims are process-lifetime. Generated `ouro_cN=ouro_fast(...)`
	   caches the clos without ouro_static_begin; a phase clos dies at
	   fe_phase_done and the next eqNat/append is apply of non-function. */
	ouro_static_begin();
	if (strcmp(name, "append") == 0)
		v = ouro_clos(f_append_xs, 0);
	else if (strcmp(name, "append_codes") == 0)
		v = ouro_clos(f_append_xs, 0);
	else if (strcmp(name, "eqNat") == 0)
		v = ouro_clos(f_eq_n, 0);
	else if (strcmp(name, "add") == 0)
		v = ouro_clos(f_add_n, 0);
	else if (strcmp(name, "mul") == 0)
		v = ouro_clos(f_mul_n, 0);
	else if (strcmp(name, "nth") == 0)
		v = ouro_clos(f_nth_xs, 0);
	else if (strcmp(name, "sub") == 0)
		v = ouro_clos(f_sub_n, 0);
	else if (strcmp(name, "compareNat") == 0)
		v = ouro_clos(f_cmp_n, 0);
	else if (strcmp(name, "length") == 0)
		v = ouro_clos(f_length_xs, 0);
	else if (strcmp(name, "reverse") == 0)
		v = ouro_clos(f_reverse_xs, 0);
	else if (strcmp(name, "memNat") == 0)
		v = ouro_clos(f_mem_x, 0);
	else if (strcmp(name, "xor32") == 0)
		v = ouro_clos(f_xor32_n, 0);
	else if (strcmp(name, "and32") == 0)
		v = ouro_clos(f_and32_n, 0);
	else if (strcmp(name, "or32") == 0)
		v = ouro_clos(f_or32_n, 0);
	else if (strcmp(name, "not32") == 0)
		v = ouro_clos(f_not32, 0);
	else if (strcmp(name, "shl32") == 0)
		v = ouro_clos(f_shl32_n, 0);
	else if (strcmp(name, "shr32") == 0)
		v = ouro_clos(f_shr32_n, 0);
	else if (strcmp(name, "rotr32") == 0)
		v = ouro_clos(f_rotr32_n, 0);
	else if (strcmp(name, "add32") == 0)
		v = ouro_clos(f_add32_n, 0);
	ouro_static_end();
	return v;
}

void ouro_show(ouro_v *v)
{
	int i;
	if (v == 0) {
		fputs("null", stdout);
		return;
	}
	if (v->tag == OURO_TAG_CLOS) {
		fputs("<fun>", stdout);
		return;
	}
	if (v->tag == OURO_TAG_STR) {
		printf("\"%s\"", v->u.s == 0 ? "" : v->u.s);
		return;
	}
	if (v->tag == OURO_TAG_NAT) {
		printf("{nat:%d}", v->n);
		return;
	}
	if (v->tag == OURO_TAG_BYTES) {
		printf("{bytes:%d}", v->n);
		return;
	}
	printf("{t:%d,a:[", v->tag);
	for (i = 0; i < v->n && has_fields(v); i++) {
		if (i > 0)
			fputc(',', stdout);
		ouro_show(OURO_F(v, i));
	}
	fputs("]}", stdout);
}

void ouro_show_line(ouro_v *v)
{
	ouro_show(v);
	fputc('\n', stdout);
}
