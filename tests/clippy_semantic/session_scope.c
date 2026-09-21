/* The real host allocator is required for these lifetime contracts:
   cc -std=c99 -Iruntime tests/clippy_semantic/session_scope.c \
      runtime/ouro_rt.c -o _build/session-scope && _build/session-scope
   These are synthetic allocation laws, not tooling throughput/RSS evidence. */
#include "ouro_quality_scope.h"

#include <stdio.h>
#include <stdlib.h>

#define WORK_BYTES (1024UL * 1024UL)
static unsigned long constructed;
static unsigned long executed;
static int failed;
static int error_result;
static ouro_v *expected_request;
static ouro_v *expected_state;
static ouro_v *root_action;

static ouro_v *marker(int tag, ouro_v *a, ouro_v *b)
{
	ouro_v *v = (ouro_v *)ouro_alloc(sizeof(*v));
	v->tag = tag;
	v->n = 2;
	v->u.inl[0] = a;
	v->u.inl[1] = b;
	return v;
}

static void require(int condition, const char *law)
{
	if (!condition) {
		fprintf(stderr, "SESSION_SCOPE: FAIL %s\n", law);
		failed = 1;
	}
}

static void temporary_work(void)
{
	unsigned char *data = (unsigned char *)ouro_alloc(WORK_BYTES);
	data[0] = 1;
	data[WORK_BYTES - 1] = 2;
}

static ouro_v *retained_closure(ouro_env *env, ouro_v *unit)
{
	(void)unit;
	return ouro_get(env, 0);
}

static ouro_v *request_io(ouro_env *env, ouro_v *unit)
{
	ouro_v *owned;
	(void)unit;
	executed++;
	require(ouro_get(env, 1) == expected_request, "request argument identity");
	require(ouro_get(env, 0) == expected_state, "state argument identity");
	temporary_work();
	owned = marker(error_result ? 0 : 1, expected_request, expected_state);
	return ouro_clos(retained_closure, ouro_cons(owned, 0));
}

static ouro_v *request_state(ouro_env *env, ouro_v *state)
{
	return ouro_clos(request_io, ouro_cons(state, env));
}

static ouro_v *request_first(ouro_env *env, ouro_v *request)
{
	(void)env;
	constructed++;
	/* Allocation before constructing the thunk must also be scoped. */
	temporary_work();
	return ouro_clos(request_state, ouro_cons(request, 0));
}

static void inspect_result(ouro_v *closure, ouro_v *unit, int tag)
{
	ouro_v *value = ouro_apply(closure, unit);
	require(value != 0 && value->tag == tag && value->n == 2,
		"typed result survives nested arena release");
	if (value != 0 && value->n == 2) {
		require(OURO_F(value, 0) == expected_request, "caller request is shared");
		require(OURO_F(value, 1) == expected_state, "caller state is shared");
	}
}

static ouro_v *epoch_io(ouro_env *env, ouro_v *unit)
{
	ouro_v *earlier;
	ouro_v *later;
	(void)env;
	temporary_work();
	error_result = 0;
	earlier = ouro_apply(root_action, unit);
	error_result = 1;
	later = ouro_apply(root_action, unit);
	inspect_result(earlier, unit, 1);
	inspect_result(later, unit, 0);
	error_result = 0;
	/* No root state or output escapes the epoch. */
	return unit;
}

static ouro_v *epoch_state(ouro_env *env, ouro_v *state)
{
	return ouro_clos(epoch_io, ouro_cons(state, env));
}

static ouro_v *epoch_first(ouro_env *env, ouro_v *request)
{
	(void)env;
	return ouro_clos(epoch_state, ouro_cons(request, 0));
}

/* Only dependency-shaped data escapes the root and epoch. */
static ouro_v *cache_epoch_io(ouro_env *env, ouro_v *unit)
{
	ouro_v *state = ouro_get(env, 0);
	ouro_v *fact;
	ouro_heap_context *scope = ouro_heap_context_enter();
	temporary_work();
	if (state == unit)
		fact = marker(8, ouro_str("immutable dependency"), ouro_nat(41));
	else
		fact = OURO_F(state, 0);
	fact = ouro_heap_context_leave(scope, fact);
	temporary_work();
	return marker(7, fact, unit);
}

static ouro_v *cache_epoch_state(ouro_env *env, ouro_v *state)
{
	return ouro_clos(cache_epoch_io, ouro_cons(state, env));
}

static ouro_v *cache_epoch_first(ouro_env *env, ouro_v *request)
{
	(void)env;
	return ouro_clos(cache_epoch_state, ouro_cons(request, 0));
}

static void cache_survivor_law(ouro_v *unit)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *worker = ouro_wrap_quality_io(ouro_clos(cache_epoch_first, 0));
	ouro_v *state = unit;
	ouro_v *fact = 0;
	unsigned long long before = ouro_heap_live_bytes();
	unsigned long long allocations = ouro_heap_total_alloc_bytes();
	unsigned long i;
	for (i = 0; i < 100; i++) {
		state = ouro_apply(ouro_apply(ouro_apply(worker, unit), state), unit);
		require(state != 0 && state->tag == 7 && state->n == 2,
			"cache state survives epoch reset");
		if (state == 0 || state->tag != 7 || state->n != 2)
			break;
		if (fact == 0)
			fact = OURO_F(state, 0);
		require(OURO_F(state, 0) == fact, "dependency identity shared across epochs");
		require(fact != 0 && fact->tag == 8 && fact->n == 2,
			"root-owned cache fact survives root and epoch reset");
		require(ouro_heap_live_bytes() - before < 65536ULL,
			"100 cache epochs do not retain root graphs");
	}
	require(ouro_heap_total_alloc_bytes() - allocations >= 200ULL * WORK_BYTES,
		"cache lifetime test performed real root and epoch allocation");
	(void)ouro_heap_context_leave(scope, unit);
}

static ouro_v *pure_state(ouro_env *env, ouro_v *state)
{
	temporary_work();
	return marker(9, ouro_get(env, 0), state);
}

static ouro_v *pure_first(ouro_env *env, ouro_v *request)
{
	(void)env;
	temporary_work();
	return ouro_clos(pure_state, ouro_cons(request, 0));
}

static void pure_survivor_law(ouro_v *unit)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *worker = ouro_wrap_quality_pure(ouro_clos(pure_first, 0));
	unsigned long long before = ouro_heap_live_bytes();
	ouro_v *value = ouro_apply(ouro_apply(worker, unit), unit);
	require(value != 0 && value->tag == 9 && value->n == 2,
		"pure decoder result survives arena release");
	if (value != 0 && value->tag == 9 && value->n == 2)
		require(OURO_F(value, 0) == unit && OURO_F(value, 1) == unit,
			"pure seam shares parent-owned arguments");
	require(ouro_heap_live_bytes() - before < 65536ULL,
		"pure decoder temporaries reclaimed");
	(void)ouro_heap_context_leave(scope, unit);
}

int main(void)
{
	ouro_v *unit;
	ouro_v *raw;
	ouro_v *wrapped;
	ouro_v *epoch;
	ouro_v *survivor;
	ouro_v *heap_action;
	unsigned long sampled;
	ouro_heap_context *control;
	unsigned long long before;
	unsigned long long allocations;
	unsigned long i;

	unit = marker(0, 0, 0);
	expected_request = marker(3, unit, unit);
	expected_state = marker(4, expected_request, unit);
	raw = ouro_clos(request_first, 0);
	wrapped = ouro_wrap_quality_io(raw);
	root_action = ouro_apply(ouro_apply(wrapped, expected_request), expected_state);
	require(constructed == 0 && executed == 0, "partial applications do not execute IO");

	heap_action = ouro_apply(ouro_apply(ouro_wrap_quality_heap(raw), expected_request), expected_state);
	before = ouro_heap_live_bytes();
	require(ouro_nat_to_ulong(ouro_apply(heap_action, unit), &sampled) &&
		(unsigned long long)sampled == before, "heap observer samples the real allocator");
	require(constructed == 0 && executed == 0, "heap observer does not execute raw analysis");
	cache_survivor_law(unit);
	pure_survivor_law(unit);
	before = ouro_heap_live_bytes();
	survivor = ouro_apply(root_action, unit);
	require(constructed == 1 && executed == 1, "one execution per request");
	require(ouro_heap_live_bytes() - before < 65536ULL, "request temporaries reclaimed");
	inspect_result(survivor, unit, 1);
	error_result = 1;
	inspect_result(ouro_apply(root_action, unit), unit, 0);
	inspect_result(survivor, unit, 1);
	error_result = 0;
	inspect_result(ouro_apply(root_action, unit), unit, 1);

	/* A control without the IO wrapper must retain its temporary work.
	   This ensures the reclamation assertion detects a missing seam. */
	control = ouro_heap_context_enter();
	before = ouro_heap_live_bytes();
	(void)ouro_apply(ouro_apply(ouro_apply(raw, expected_request), expected_state), unit);
	require(ouro_heap_live_bytes() - before >= 2ULL * WORK_BYTES,
		"unwrapped control retains temporary work");
	(void)ouro_heap_context_leave(control, unit);

	epoch = ouro_apply(ouro_apply(ouro_wrap_quality_io(ouro_clos(epoch_first, 0)),
		expected_request), expected_state);
	before = ouro_heap_live_bytes();
	allocations = ouro_heap_total_alloc_bytes();
	for (i = 0; i < 100; i++) {
		require(ouro_apply(epoch, unit) == unit, "epoch returns only caller-owned completion");
		require(ouro_heap_live_bytes() == before, "epoch retained bytes do not accumulate");
	}
	require(ouro_heap_total_alloc_bytes() - allocations >= 500ULL * WORK_BYTES,
		"repeated work really ran");
	require(constructed == 204 && executed == 204, "failure does not suppress later requests");
	inspect_result(survivor, unit, 1);
	if (failed)
		return 1;
	puts("SESSION_SCOPE: PASS deferred IO, typed survivors, nested epochs, 100 resets");
	return 0;
}
