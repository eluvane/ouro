/* Deferred two-argument IO lifetime seam for native quality tools.
   Policy, source loading, parsing and diagnostics remain in Ouro. */
#ifndef OURO_QUALITY_SCOPE_H
#define OURO_QUALITY_SCOPE_H

#include "ouro_rt.h"

/* Enter only when the IO action is executed. Entering while constructing
   the action would copy a thunk out and run all its work in the caller.
   The captured function and arguments belong to the suspended caller. */
static ouro_v *ouro_quality_io_run(ouro_env *env, ouro_v *unit)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *action = ouro_apply(ouro_apply(ouro_get(env, 2),
		ouro_get(env, 1)), ouro_get(env, 0));
	ouro_v *result = ouro_apply(action, unit);
	return ouro_heap_context_leave(scope, result);
}

static ouro_v *ouro_quality_io_state(ouro_env *env, ouro_v *state)
{
	return ouro_clos(ouro_quality_io_run, ouro_cons(state, env));
}

static ouro_v *ouro_quality_io_request(ouro_env *env, ouro_v *request)
{
	return ouro_clos(ouro_quality_io_state, ouro_cons(request, env));
}

static ouro_v *ouro_wrap_quality_io(ouro_v *raw)
{
	return ouro_clos(ouro_quality_io_request, ouro_cons(raw, 0));
}

/* Pure reporting work uses the same nested arena without linking the
   compiler/frontend object into the lightweight JSON consumer. */
static ouro_v *ouro_quality_pure_state(ouro_env *env, ouro_v *state)
{
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *result = ouro_apply(ouro_apply(ouro_get(env, 1),
		ouro_get(env, 0)), state);
	return ouro_heap_context_leave(scope, result);
}

static ouro_v *ouro_quality_pure_request(ouro_env *env, ouro_v *request)
{
	return ouro_clos(ouro_quality_pure_state, ouro_cons(request, env));
}

static inline ouro_v *ouro_wrap_quality_pure(ouro_v *raw)
{
	return ouro_clos(ouro_quality_pure_request, ouro_cons(raw, 0));
}

/* The allocator already counts suspended parent banks. Sample after an
   epoch has returned, rather than counting its temporary working set. */
static ouro_v *ouro_quality_heap_run(ouro_env *env, ouro_v *unit)
{
	(void)env;
	(void)unit;
	return ouro_nat_u64(ouro_heap_live_bytes());
}

static ouro_v *ouro_quality_heap_state(ouro_env *env, ouro_v *state)
{
	(void)env;
	(void)state;
	return ouro_clos(ouro_quality_heap_run, 0);
}

static ouro_v *ouro_quality_heap_request(ouro_env *env, ouro_v *request)
{
	(void)env;
	(void)request;
	return ouro_clos(ouro_quality_heap_state, 0);
}

static inline ouro_v *ouro_wrap_quality_heap(ouro_v *raw)
{
	(void)raw;
	return ouro_clos(ouro_quality_heap_request, 0);
}

#endif
