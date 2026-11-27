#include "ouro_rt.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if !defined(OURO_MODULE_PURE_SCOPES) || !OURO_MODULE_PURE_SCOPES
#error OURO_MODULE_PURE_SCOPES is required for this selftest
#endif

ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity);
ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw);
ouro_v *ouro_wrap_elem_scope(ouro_v *raw);
ouro_v *ouro_wrap_module_maps_for_scope(ouro_v *raw);
ouro_v *ouro_wrap_module_rewrite_decls_scope(ouro_v *raw);
ouro_v *ouro_wrap_module_scope_maps_scope(ouro_v *raw);
ouro_v *ouro_wrap_module_bare_ctors_scope(ouro_v *raw);
ouro_v *ouro_wrap_module_invalid_maps_scope(ouro_v *raw);

static unsigned long calls, partial_calls;
static int failed;
static const unsigned char binary[] = {0, 255, 65, 0, 128};

static int fail(const char *message)
{
	fprintf(stderr, "MODULE_PURE_SCOPE_SELFTEST: FAIL %s\n", message);
	return 1;
}

static int packed(ouro_v *value, const unsigned char *bytes, unsigned long count)
{
	return value != 0 && value->tag == OURO_TAG_BYTES && value->n == (int)count && value->u.s != 0 &&
		memcmp(value->u.s, bytes, count) == 0;
}

static int nat_is(ouro_v *value, unsigned long expected)
{
	unsigned long actual;
	return value != 0 && ouro_nat_to_ulong(value, &actual) && actual == expected;
}

static int nil(ouro_v *value)
{
	return value != 0 && value->tag == 0 && value->n == 0;
}

static ouro_v *one(ouro_env *env, ouro_v *argument)
{
	ouro_v *fields[1] = {argument};
	(void)env;
	calls++;
	return ouro_ctor(0, 1, fields);
}

static ouro_v *two_last(ouro_env *env, ouro_v *argument)
{
	ouro_v *fields[2] = {ouro_get(env, 0), argument};
	calls++;
	return ouro_ctor(0, 2, fields);
}

static ouro_v *two_first(ouro_env *env, ouro_v *argument)
{
	partial_calls++;
	return ouro_clos(two_last, ouro_cons(argument, env));
}

static ouro_v *seven_last(ouro_env *env, ouro_v *argument)
{
	ouro_v *fields[7] = {ouro_get(env, 5), ouro_get(env, 4), ouro_get(env, 3),
		ouro_get(env, 2), ouro_get(env, 1), ouro_get(env, 0), argument};
	calls++;
	return ouro_ctor(0, 7, fields);
}

static ouro_v *three_last(ouro_env *env, ouro_v *argument)
{
	ouro_v *fields[3] = {ouro_get(env, 1), ouro_get(env, 0), argument};
	calls++;
	return ouro_ctor(0, 3, fields);
}

#define STEP(name, next) \
static ouro_v *name(ouro_env *env, ouro_v *argument) \
{ \
	partial_calls++; \
	return ouro_clos(next, ouro_cons(argument, env)); \
}
STEP(seven_sixth, seven_last)
STEP(seven_fifth, seven_sixth)
STEP(seven_fourth, seven_fifth)
STEP(seven_third, seven_fourth)
STEP(seven_second, seven_third)
STEP(seven_first, seven_second)
STEP(three_second, three_last)
STEP(three_first, three_second)
#undef STEP

static int order_check(unsigned long arity)
{
	ouro_v *raw = ouro_clos(arity == 1 ? one : arity == 2 ? two_first :
		arity == 3 ? three_first : seven_first, 0);
	ouro_v *wrapped = ouro_wrap_module_pure_scope(raw, arity);
	ouro_v *arguments[7], *result = wrapped;
	unsigned long index, old_calls = calls, old_partial = partial_calls;
	for (index = 0; index < arity; index++) {
		arguments[index] = ouro_nat(5000 + index);
		result = ouro_apply(result, arguments[index]);
		if (index + 1 < arity && (calls != old_calls || partial_calls != old_partial))
			return fail("raw evaluated before saturation");
	}
	if (calls != old_calls + 1 || partial_calls != old_partial + arity - 1 ||
	    result == 0 || result->tag != 0 || result->n != (int)arity)
		return fail("raw invocation count or argument count");
	for (index = 0; index < arity; index++)
		if (OURO_F(result, index) != arguments[index])
			return fail("argument order or borrowed identity");
	return 0;
}

static ouro_v *captured_value(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	return ouro_get(env, 0);
}

static ouro_v *probe_last(ouro_env *env, ouro_v *mode)
{
	ouro_v *owner = ouro_get(env, 0), *capture = ouro_get(env, 1);
	ouro_v *fields[4], *names, *strings, *big, *intern, *members, *result;
	ouro_heap_context *nested;
	unsigned long number;
	calls++;
	memset(ouro_alloc(2UL * 1024UL * 1024UL), 0xA5, 2UL * 1024UL * 1024UL);
	if (!ouro_nat_to_ulong(mode, &number) || number > 2) {
		failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	if (number == 1) {
		fields[0] = ouro_nat(5009);
		fields[1] = ouro_nat(5010);
		return ouro_ctor(1, 2, fields);
	}
	nested = ouro_heap_context_enter();
	ouro_perm_select(1);
	ouro_perm_begin();
	fields[0] = ouro_packed(binary, sizeof binary);
	fields[1] = ouro_nat(9);
	names = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, fields), ouro_ctor(0, 0, 0)});
	ouro_perm_end();
	names = ouro_heap_context_leave(nested, names);
	big = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	big = ouro_apply(ouro_apply(ouro_fast("add"), big), big);
	fields[0] = ouro_apply(capture, ouro_ctor(0, 0, 0));
	fields[1] = ouro_nat(10);
	strings = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, fields), ouro_ctor(0, 0, 0)});
	intern = ouro_ctor(0, 4, (ouro_v *[]){names, big, strings, big});
	members = ouro_ctor(1, 2, (ouro_v *[]){
		ouro_ctor(0, 4, (ouro_v *[]){owner, ouro_nat(2), ouro_nat(3), ouro_ctor(1, 0, 0)}),
		ouro_ctor(0, 0, 0)});
	result = ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){members, intern})});
	return number == 2 ? ouro_clos(captured_value, ouro_cons(result, 0)) : result;
}

static ouro_v *probe_first(ouro_env *env, ouro_v *owner)
{
	partial_calls++;
	return ouro_clos(probe_last, ouro_cons(owner, env));
}

static int success(ouro_v *value, ouro_v *owner, ouro_v *caller)
{
	ouro_v *pair, *members, *member, *intern, *names, *strings, *big, *name_pair, *string_pair, *visibility;
	const uint32_t expected[3] = {UINT32_C(0xeca86420), UINT32_C(0xfdb97530), 1};
	if (value == 0 || value->tag != 0 || value->n != 1)
		return 0;
	pair = OURO_F(value, 0);
	if (pair == 0 || pair->tag != 0 || pair->n != 2)
		return 0;
	members = OURO_F(pair, 0); intern = OURO_F(pair, 1);
	if (members == 0 || members->tag != 1 || members->n != 2 ||
	    intern == 0 || intern->tag != 0 || intern->n != 4)
		return 0;
	member = OURO_F(members, 0); names = OURO_F(intern, 0);
	strings = OURO_F(intern, 2); big = OURO_F(intern, 1);
	if (member == 0 || member->tag != 0 || member->n != 4 || OURO_F(member, 0) != owner ||
	    names == 0 || names->tag != 1 || names->n != 2 ||
	    strings == 0 || strings->tag != 1 || strings->n != 2 ||
	    big == 0 || big->tag != OURO_TAG_BIG_NAT || big->n != 3 ||
	    big != OURO_F(intern, 3) || memcmp(big + 1, expected, sizeof expected) != 0)
		return 0;
	name_pair = OURO_F(names, 0); string_pair = OURO_F(strings, 0);
	visibility = OURO_F(member, 3);
	return name_pair != 0 && name_pair->tag == 0 && name_pair->n == 2 &&
		string_pair != 0 && string_pair->tag == 0 && string_pair->n == 2 &&
		visibility != 0 && visibility->tag == 1 && visibility->n == 0 &&
		nat_is(OURO_F(member, 1), 2) && nat_is(OURO_F(member, 2), 3) &&
		nil(OURO_F(members, 1)) && nil(OURO_F(names, 1)) && nil(OURO_F(strings, 1)) &&
		packed(OURO_F(name_pair, 0), binary, sizeof binary) && nat_is(OURO_F(name_pair, 1), 9) &&
		OURO_F(string_pair, 0) == caller && nat_is(OURO_F(string_pair, 1), 10);
}

static int error(ouro_v *value)
{
	unsigned long code, detail;
	return value != 0 && value->tag == 1 && value->n == 2 &&
		ouro_nat_to_ulong(OURO_F(value, 0), &code) && code == 5009 &&
		ouro_nat_to_ulong(OURO_F(value, 1), &detail) && detail == 5010;
}

static int survivor_check(void)
{
	ouro_v *caller = ouro_string_codes("borrowed caller");
	ouro_v *owner = ouro_nat(6000);
	ouro_v *capture = ouro_clos(captured_value, ouro_cons(caller, 0));
	ouro_v *raw = ouro_clos(probe_first, ouro_cons(capture, 0));
	ouro_v *wrapped = ouro_wrap_module_pure_scope(raw, 2);
	ouro_v *partial = ouro_apply(wrapped, owner), *retained[64], *closure, *bundle;
	ouro_heap_context *outer;
	unsigned long index, before_calls = calls;
	unsigned long long before, total;
	outer = ouro_heap_context_enter();
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 64; index++) {
		retained[index] = ouro_apply(partial, ouro_nat(index % 2));
		if ((index % 2 == 0 ? !success(retained[index], owner, caller) : !error(retained[index])) ||
		    !packed(caller, (const unsigned char *)"borrowed caller", 15) ||
		    ouro_heap_live_bytes() > before + 65536ULL)
			return fail("full result, caller identity or scratch bound");
		if (index != 0 && !success(retained[0], owner, caller))
			return fail("prior result released");
	}
	closure = ouro_apply(partial, ouro_nat(2));
	if (calls != before_calls + 65 || failed ||
	    ouro_heap_total_alloc_bytes() < total + 65ULL * 2ULL * 1024ULL * 1024ULL ||
	    !success(ouro_apply(closure, ouro_ctor(0, 0, 0)), owner, caller))
		return fail("captured raw/partial reuse, child closure or actual scratch calls");
	bundle = ouro_heap_context_leave(outer, ouro_ctor(0, 3, (ouro_v *[]){retained[0], retained[1], closure}));
	if (!success(OURO_F(bundle, 0), owner, caller) || !error(OURO_F(bundle, 1)) ||
	    !success(ouro_apply(OURO_F(bundle, 2), ouro_ctor(0, 0, 0)), owner, caller) ||
	    !success(ouro_apply(ouro_apply(raw, owner), ouro_nat(0)), owner, caller) ||
	    !success(ouro_apply(partial, ouro_nat(0)), owner, caller))
		return fail("nested survivor, raw or partial after enclosing leave");
	return 0;
}

/* The test double selects an Ordering. Both raw curry calls allocate scratch. */
static ouro_v *name_compare_left, *name_compare_right, *name_compare_cached;
static unsigned long name_compare_tag, name_compare_calls, name_compare_partial_calls;
static int name_compare_failed;

static ouro_v *name_compare_scope_last(ouro_env *env, ouro_v *argument)
{
	if (ouro_get(env, 0) != name_compare_left || argument != name_compare_right)
		name_compare_failed = 1;
	name_compare_calls++;
	(void)ouro_perm_alloc(2UL * 1024UL * 1024UL);
	return ouro_ctor((int)name_compare_tag, 0, 0);
}

static ouro_v *name_compare_scope_first(ouro_env *env, ouro_v *argument)
{
	if (argument != name_compare_left)
		name_compare_failed = 1;
	name_compare_partial_calls++;
	(void)ouro_alloc(2UL * 1024UL * 1024UL);
	return ouro_clos(name_compare_scope_last, ouro_cons(argument, env));
}

static ouro_v *name_compare_scope_getter(void)
{
	if (name_compare_cached == 0) {
		ouro_static_begin();
		name_compare_cached = ouro_wrap_source_name_compare_scope(ouro_fix(name_compare_scope_first, 0));
		ouro_static_end();
	}
	return name_compare_cached;
}

/* This test double probes three delayed stages and captured predicate storage. */
static ouro_v *elem_scope_cached;
static unsigned long elem_scope_first_calls, elem_scope_second_calls, elem_scope_calls;
static unsigned long elem_scope_predicate_first_calls, elem_scope_predicate_calls, elem_scope_tag;
static int elem_scope_failed;
static const unsigned char elem_scope_binary[] = {0, 255, 129};

static int elem_scope_value(ouro_v *value, unsigned long variant, int right)
{
	unsigned long number;
	if (variant == 0)
		return value != 0 && value->tag == 37 && value->n == 2 &&
			ouro_nat_to_ulong(OURO_F(value, 0), &number) && number == 70001 &&
			packed(OURO_F(value, 1), elem_scope_binary, sizeof elem_scope_binary);
	return ouro_nat_to_ulong(value, &number) && number == (right ? 0UL : 65537UL);
}

static ouro_v *elem_scope_predicate_last(ouro_env *env, ouro_v *argument)
{
	ouro_v *capture = ouro_get(env, 1);
	unsigned long variant;
	elem_scope_predicate_calls++;
	((unsigned char *)ouro_alloc(1024UL * 1024UL))[0] = 43;
	if (capture == 0 || capture->tag != 67 || capture->n != 2 ||
	    !ouro_nat_to_ulong(OURO_F(capture, 0), &variant) || variant > 1 ||
	    !packed(OURO_F(capture, 1), elem_scope_binary, sizeof elem_scope_binary) ||
	    !elem_scope_value(ouro_get(env, 0), variant, 0) || !elem_scope_value(argument, variant, 1))
		elem_scope_failed = 1;
	return ouro_ctor((int)elem_scope_tag, 0, 0);
}

static ouro_v *elem_scope_predicate_first(ouro_env *env, ouro_v *argument)
{
	elem_scope_predicate_first_calls++;
	((unsigned char *)ouro_alloc(1024UL * 1024UL))[0] = 44;
	return ouro_clos(elem_scope_predicate_last, ouro_cons(argument, env));
}

static ouro_v *elem_scope_list(ouro_env *env, ouro_v *argument)
{
	ouro_v *predicate = ouro_get(env, 2), *value = ouro_get(env, 1), *head;
	ouro_v *capture = predicate != 0 && predicate->tag == OURO_TAG_CLOS ?
		ouro_get(predicate->u.c.env, 0) : 0;
	unsigned long variant, length;
	elem_scope_calls++;
	((unsigned char *)ouro_alloc(1024UL * 1024UL))[0] = 45;
	if (capture == 0 || capture->tag != 67 || capture->n != 2 ||
	    !ouro_nat_to_ulong(OURO_F(capture, 0), &variant) || variant > 1 ||
	    !ouro_nat_to_ulong(ouro_apply(ouro_fast("length"), argument), &length) ||
	    length != (variant == 0 ? 1UL : 7UL)) {
		elem_scope_failed = 1;
		return ouro_ctor(1, 0, 0);
	}
	head = ouro_apply(ouro_apply(ouro_fast("nth"), argument), ouro_nat(0));
	if (head == 0 || head->tag != 1 || head->n != 1) {
		elem_scope_failed = 1;
		return ouro_ctor(1, 0, 0);
	}
	return ouro_apply(ouro_apply(predicate, value), OURO_F(head, 0));
}

static ouro_v *elem_scope_target(ouro_env *env, ouro_v *argument)
{
	elem_scope_second_calls++;
	((unsigned char *)ouro_alloc(4UL * 1024UL * 1024UL))[0] = 46;
	return ouro_fix(elem_scope_list, ouro_cons(argument, env));
}

static ouro_v *elem_scope_predicate(ouro_env *env, ouro_v *argument)
{
	elem_scope_first_calls++;
	((unsigned char *)ouro_alloc(4UL * 1024UL * 1024UL))[0] = 47;
	return ouro_clos(elem_scope_target, ouro_cons(argument, env));
}

static ouro_v *elem_scope_getter(void)
{
	if (elem_scope_cached == 0) {
		ouro_static_begin();
		elem_scope_cached = ouro_wrap_elem_scope(ouro_clos(elem_scope_predicate, 0));
		ouro_static_end();
	}
	return elem_scope_cached;
}

static int elem_scope_check(void)
{
	unsigned long variant, index;
	for (variant = 0; variant < 2; variant++) {
		ouro_v *target, *items, *capture, *predicate, *first, *second, *bundle, *kept[2];
		ouro_heap_context *outer;
		unsigned long long before, total;
		elem_scope_first_calls = elem_scope_second_calls = elem_scope_calls = 0;
		elem_scope_predicate_first_calls = elem_scope_predicate_calls = 0;
		elem_scope_failed = 0;
		target = variant == 0 ? ouro_ctor(37, 2, (ouro_v *[]){ouro_nat(70001),
			ouro_packed(elem_scope_binary, sizeof elem_scope_binary)}) : ouro_nat(65537);
		items = ouro_ctor(1, 2, (ouro_v *[]){target, ouro_ctor(0, 0, 0)});
		if (variant == 1) {
			items = ouro_ctor(1, 2, (ouro_v *[]){target, ouro_packed(elem_scope_binary, sizeof elem_scope_binary)});
			items = ouro_apply(ouro_apply(ouro_fast("append"),
				ouro_packed(elem_scope_binary, sizeof elem_scope_binary)), items);
		}
		outer = ouro_heap_context_enter();
		capture = ouro_ctor(67, 2, (ouro_v *[]){ouro_nat(variant),
			ouro_packed(elem_scope_binary, sizeof elem_scope_binary)});
		predicate = ouro_clos(elem_scope_predicate_first, ouro_cons(capture, 0));
		first = ouro_apply(elem_scope_getter(), predicate);
		second = ouro_apply(first, target);
		if (elem_scope_first_calls || elem_scope_second_calls || elem_scope_calls || elem_scope_predicate_calls)
			return fail("elem scope raw or predicate evaluated before third argument");
		before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
		for (index = 0; index < 16; index++) {
			ouro_v *result;
			elem_scope_tag = index % 2;
			result = ouro_apply(second, items);
			if (result == 0 || result->tag != (int)elem_scope_tag || result->n != 0 ||
			    elem_scope_failed || ouro_heap_live_bytes() > before + 65536ULL)
				return fail("elem scope complete Bool, callback captures, values or scratch lifetime");
			if (index < 2)
				kept[index] = result;
			if (kept[0]->tag != 0 || kept[0]->n != 0)
				return fail("elem scope prior Bool released");
		}
		if (elem_scope_first_calls != 16 || elem_scope_second_calls != 16 || elem_scope_calls != 16 ||
		    elem_scope_predicate_first_calls != 16 || elem_scope_predicate_calls != 16 ||
		    ouro_heap_total_alloc_bytes() < total + 16ULL * 8ULL * 1024ULL * 1024ULL)
			return fail("elem scope raw stages or callback were skipped");
		bundle = ouro_heap_context_leave(outer,
			ouro_ctor(0, 4, (ouro_v *[]){first, second, kept[0], kept[1]}));
		if (OURO_F(bundle, 2)->tag != 0 || OURO_F(bundle, 2)->n != 0 ||
		    OURO_F(bundle, 3)->tag != 1 || OURO_F(bundle, 3)->n != 0)
			return fail("elem scope complete retained Bool after enclosing leave");
		elem_scope_tag = 1;
		kept[0] = ouro_apply(ouro_apply(OURO_F(bundle, 0), target), items);
		kept[1] = ouro_apply(OURO_F(bundle, 1), items);
		if (kept[0] == 0 || kept[1] == 0 || kept[0]->tag != 1 || kept[0]->n != 0 ||
		    kept[1]->tag != 1 || kept[1]->n != 0 || elem_scope_failed || elem_scope_getter() == 0 ||
		    !elem_scope_value(target, variant, 0))
			return fail("elem scope both partial stages, predicate captures or static cache after outer leave");
	}
	return 0;
}

static int source_name_compare_scope_check(void)
{
	ouro_v *partial, *kept[16], *bundle, *result;
	ouro_heap_context *outer;
	unsigned long index;
	unsigned long long before, total;
	name_compare_left = ouro_packed(binary, sizeof binary);
	name_compare_right = ouro_ctor(1, 2, (ouro_v *[]){ouro_nat(65537), ouro_packed(binary, sizeof binary)});
	name_compare_right = ouro_apply(ouro_apply(ouro_fast("append"), name_compare_left), name_compare_right);
	outer = ouro_heap_context_enter();
	partial = ouro_apply(name_compare_scope_getter(), name_compare_left);
	if (name_compare_calls != 0 || name_compare_partial_calls != 0)
		return fail("source name compare raw evaluated before saturation");
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 16; index++) {
		name_compare_tag = index % 3;
		kept[index] = ouro_apply(partial, name_compare_right);
		if (kept[index] == 0 || kept[index]->tag != (int)name_compare_tag || kept[index]->n != 0 ||
		    name_compare_failed || ouro_heap_live_bytes() > before + 65536ULL)
			return fail("source name compare complete Ordering, borrowed inputs or scratch bound");
		if (kept[0]->tag != 0 || kept[0]->n != 0)
			return fail("source name compare prior Ordering released");
	}
	if (name_compare_calls != 16 || name_compare_partial_calls != 16 ||
	    ouro_heap_total_alloc_bytes() < total + 16ULL * 4ULL * 1024ULL * 1024ULL)
		return fail("source name compare raw curry replay or actual scratch calls");
	bundle = ouro_heap_context_leave(outer, ouro_ctor(0, 4, (ouro_v *[]){partial, kept[0], kept[1], kept[2]}));
	for (index = 0; index < 3; index++)
		if (OURO_F(bundle, index + 1) == 0 || OURO_F(bundle, index + 1)->tag != (int)index ||
		    OURO_F(bundle, index + 1)->n != 0)
			return fail("source name compare retained Ordering after outer leave");
	name_compare_tag = 1;
	result = ouro_apply(OURO_F(bundle, 0), name_compare_right);
	if (result == 0 || result->tag != 1 || result->n != 0 || name_compare_failed ||
	    !packed(name_compare_left, binary, sizeof binary) || name_compare_scope_getter() == 0)
		return fail("source name compare retained partial or static cache after outer leave");
	name_compare_left = name_compare_right = 0;
	return 0;
}

static ouro_v *cold_dependency, *cold_wrapper, *cold_result;
static unsigned long cold_calls;

static ouro_v *cold_dependency_getter(void)
{
	if (cold_dependency == 0) {
		ouro_static_begin();
		cold_dependency = ouro_packed(binary, sizeof binary);
		ouro_static_end();
	}
	return cold_dependency;
}

static ouro_v *cold_body(ouro_env *env, ouro_v *argument)
{
	(void)env;
	cold_calls++;
	memset(ouro_alloc(2UL * 1024UL * 1024UL), 0x5A, 2UL * 1024UL * 1024UL);
	return ouro_ctor(0, 2, (ouro_v *[]){cold_dependency_getter(), argument});
}

static ouro_v *cold_wrapper_getter(void)
{
	if (cold_wrapper == 0) {
		ouro_static_begin();
		cold_wrapper = ouro_wrap_module_pure_scope(ouro_clos(cold_body, 0), 1);
		ouro_static_end();
	}
	return cold_wrapper;
}

static int allocation_check(void)
{
	ouro_v *wrapped, *result, *permanent;
	unsigned long long before;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(0);
	wrapped = cold_wrapper_getter();
	before = ouro_heap_live_bytes();
	ouro_static_begin();
	cold_result = ouro_apply(wrapped, ouro_nat(17));
	ouro_static_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1);
	if (cold_wrapper_getter() != wrapped || cold_calls != 1 ||
	    cold_result == 0 || cold_result->tag != 0 || cold_result->n != 2 ||
	    OURO_F(cold_result, 0) != cold_dependency_getter() ||
	    !packed(OURO_F(cold_result, 0), binary, sizeof binary) || !nat_is(OURO_F(cold_result, 1), 17) ||
	    ouro_heap_live_bytes() > before + 4096ULL)
		return fail("cold static cache identity, restoration or scratch retained");
	ouro_perm_select(1); ouro_perm_begin();
	permanent = ouro_string_codes("permanent caller");
	result = ouro_apply(wrapped, ouro_nat(19));
	ouro_perm_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0);
	if (!packed(permanent, (const unsigned char *)"permanent caller", 16) ||
	    result == 0 || result->tag != 0 || result->n != 2 ||
	    OURO_F(result, 0) != cold_dependency || !nat_is(OURO_F(result, 1), 19) ||
	    cold_calls != 2 || cold_wrapper_getter() != wrapped)
		return fail("caller permanent bank/depth not restored");
	ouro_perm_reset_bank(1); ouro_perm_select(0);
	return 0;
}

static unsigned long lazy_calls;
static int extended_failed;

static ouro_v *cycle_value(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	return ouro_ctor(0, 2, (ouro_v *[]){ouro_get(env, 0), ouro_get(env, 1)});
}

static ouro_v *lazy_value(ouro_env *env, ouro_v *argument)
{
	ouro_v *opaque = ouro_get(env, 0), *owner = ouro_get(env, 1);
	ouro_v *caller = ouro_get(env, 2), *bytes = ouro_get(env, 3);
	ouro_v *big = ouro_get(env, 4), *cycle = ouro_get(env, 5), *intern;
	(void)argument;
	lazy_calls++;
	if (!success(opaque, owner, caller)) {
		extended_failed = 1;
		return 0;
	}
	intern = OURO_F(OURO_F(opaque, 0), 1);
	if (!packed(bytes, binary, sizeof binary) ||
	    bytes != OURO_F(OURO_F(OURO_F(intern, 0), 0), 0) || big != OURO_F(intern, 1)) {
		extended_failed = 1;
		return 0;
	}
	return ouro_ctor(0, 2, (ouro_v *[]){opaque, cycle});
}

static ouro_v *thunk_cycle_body(ouro_env *env, ouro_v *owner)
{
	ouro_v *caller = ouro_get(env, 0);
	ouro_v *capture = ouro_clos(captured_value, ouro_cons(caller, 0));
	ouro_v *opaque = probe_last(ouro_cons(owner, ouro_cons(capture, 0)), ouro_nat(0));
	ouro_v *intern, *bytes, *big, *cycle, *thunk;
	if (!success(opaque, owner, caller)) {
		extended_failed = 1;
		return 0;
	}
	intern = OURO_F(OURO_F(opaque, 0), 1);
	bytes = OURO_F(OURO_F(OURO_F(intern, 0), 0), 0); big = OURO_F(intern, 1);
	cycle = ouro_fix(cycle_value, ouro_cons(opaque, 0));
	thunk = ouro_thunk(lazy_value, ouro_cons(opaque, ouro_cons(owner,
		ouro_cons(caller, ouro_cons(bytes, ouro_cons(big, ouro_cons(cycle, 0)))))));
	return ouro_ctor(0, 6, (ouro_v *[]){thunk, thunk, opaque, opaque, cycle, cycle});
}

static int graph_aliases(ouro_v *bundle, ouro_v *owner, ouro_v *caller)
{
	ouro_v *thunk, *opaque, *cycle, *view;
	if (bundle == 0 || bundle->tag != 0 || bundle->n != 6)
		return 0;
	thunk = OURO_F(bundle, 0); opaque = OURO_F(bundle, 2); cycle = OURO_F(bundle, 4);
	if (thunk == 0 || thunk->tag != OURO_TAG_THUNK || thunk != OURO_F(bundle, 1) ||
	    opaque != OURO_F(bundle, 3) || !success(opaque, owner, caller) ||
	    cycle == 0 || cycle->tag != OURO_TAG_CLOS || cycle != OURO_F(bundle, 5))
		return 0;
	view = ouro_apply(cycle, ouro_ctor(0, 0, 0));
	return view != 0 && view->tag == 0 && view->n == 2 &&
		OURO_F(view, 0) == cycle && OURO_F(view, 1) == opaque;
}

/* Caller perm depth prevents ouro_case from popping the retained THUNK. */
static int force_alias(ouro_v *bundle, ouro_v *owner, ouro_v *caller)
{
	ouro_v *result = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){OURO_F(bundle, 0)});
	return result != 0 && result->tag == 0 && result->n == 2 &&
		OURO_F(result, 0) == OURO_F(bundle, 2) && OURO_F(result, 1) == OURO_F(bundle, 4) &&
		success(OURO_F(result, 0), owner, caller);
}

static int thunk_cycle_check(void)
{
	ouro_v *caller = ouro_string_codes("lazy caller"), *owner = ouro_nat(6100);
	ouro_v *raw = ouro_clos(thunk_cycle_body, ouro_cons(caller, 0));
	ouro_v *wrapped = ouro_wrap_module_pure_scope(raw, 1), *bundle, *kept;
	unsigned long old_lazy = lazy_calls, old_calls = calls;
	unsigned long long before = ouro_heap_live_bytes(), total = ouro_heap_total_alloc_bytes();
	bundle = ouro_apply(wrapped, owner);
	if (lazy_calls != old_lazy || calls != old_calls + 1 || failed || extended_failed ||
	    !graph_aliases(bundle, owner, caller) || ouro_heap_live_bytes() > before + 65536ULL ||
	    ouro_heap_total_alloc_bytes() < total + 2ULL * 1024ULL * 1024ULL)
		return fail("returned THUNK, cyclic alias or actual child scratch");
	ouro_perm_select(0);
	ouro_perm_begin();
	if (!force_alias(bundle, owner, caller) || !force_alias(bundle, owner, caller) ||
	    lazy_calls != old_lazy + 2 || extended_failed) {
		ouro_perm_end();
		return fail("lazy force after scope leave or captured aliases");
	}
	ouro_perm_end();
	kept = ouro_clone_perm_deep(ouro_ctor(0, 3, (ouro_v *[]){bundle, owner, caller}));
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1);
	bundle = OURO_F(kept, 0); owner = OURO_F(kept, 1); caller = OURO_F(kept, 2);
	memset(ouro_alloc(4096UL), 0xCC, 4096UL);
	if (!nat_is(owner, 6100) || !packed(caller, (const unsigned char *)"lazy caller", 11) ||
	    !graph_aliases(bundle, owner, caller))
		return fail("complete promotion lost THUNK, cycle, opaque result or captures");
	ouro_perm_begin();
	if (!force_alias(bundle, owner, caller) || lazy_calls != old_lazy + 3 || extended_failed) {
		ouro_perm_end();
		return fail("lazy force after source phase reset");
	}
	ouro_perm_end();
	return 0;
}

static int outer_mark_check(void)
{
	ouro_v *caller, *owner, *capture, *raw, *partial, *result, *kept;
	unsigned long mark_n, mark_used, actual_n, actual_used;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(0);
	caller = ouro_string_codes("marked caller"); owner = ouro_nat(6200);
	capture = ouro_clos(captured_value, ouro_cons(caller, 0));
	raw = ouro_clos(probe_first, ouro_cons(capture, 0));
	partial = ouro_apply(ouro_wrap_module_pure_scope(raw, 2), owner);
	ouro_heap_mark(); ouro_heap_mark_save(&mark_n, &mark_used);
	if (mark_n == 0 || mark_used == 0)
		return fail("outer mark is vacuous");
	result = ouro_apply(partial, ouro_nat(0));
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used || !success(result, owner, caller))
		return fail("caller mark not restored by actual wrapper");
	kept = ouro_clone_since_mark(result);
	ouro_heap_reset(); ouro_perm_reset_bank(1);
	memset(ouro_alloc(4096UL), 0xA5, 4096UL);
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used ||
	    !packed(caller, (const unsigned char *)"marked caller", 13) ||
	    !nat_is(owner, 6200) || !success(kept, owner, caller) ||
	    !success(ouro_apply(partial, ouro_nat(0)), owner, caller))
		return fail("outer mark reset, promoted result or pre-mark caller released");
	return 0;
}

static int permanent_zero_check(void)
{
	ouro_v *caller, *owner, *capture, *raw, *partial, *result, *after;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(0);
	ouro_perm_begin();
	caller = ouro_string_codes("permanent zero"); owner = ouro_nat(6300);
	capture = ouro_clos(captured_value, ouro_cons(caller, 0));
	raw = ouro_clos(probe_first, ouro_cons(capture, 0));
	partial = ouro_apply(ouro_wrap_module_pure_scope(raw, 2), owner);
	result = ouro_apply(partial, ouro_nat(0));
	after = ouro_string_codes("after zero");
	ouro_perm_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1);
	if (!packed(caller, (const unsigned char *)"permanent zero", 14) ||
	    !packed(after, (const unsigned char *)"after zero", 10) ||
	    !nat_is(owner, 6300) || !success(result, owner, caller) ||
	    !error(ouro_apply(partial, ouro_nat(1))))
		return fail("caller permanent0 bank, depth, values or partial not restored");
	return 0;
}

static unsigned long prefix_raw_calls, prefix_body_calls, prefix_lazy_calls;
static uintptr_t prefix_token_addresses[3];
static int prefix_failed;

static ouro_v *prefix_borrowed_value(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	prefix_lazy_calls++;
	return ouro_ctor(0, 2, (ouro_v *[]){ouro_get(env, 0), ouro_get(env, 1)});
}

static ouro_v *prefix_raw_argument(ouro_env *env, ouro_v *argument)
{
	unsigned long remaining, arity, prefix, ordinal, index, mode;
	ouro_v *reversed, *tokens, *cursor, *arguments[10], *ordered, *view, *graph;
	if (!ouro_nat_to_ulong(ouro_get(env, 0), &remaining) ||
	    !ouro_nat_to_ulong(ouro_get(env, 1), &arity) ||
	    !ouro_nat_to_ulong(ouro_get(env, 2), &prefix) ||
	    (prefix != 2 && prefix != 3) || arity != prefix + 7 ||
	    remaining == 0 || remaining > arity) {
		prefix_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	ordinal = arity - remaining;
	prefix_raw_calls++;
	reversed = ouro_ctor(1, 2, (ouro_v *[]){argument, ouro_get(env, 3)});
	tokens = ouro_get(env, 4);
	if (ordinal < prefix) {
		ouro_v *token = ouro_ctor(0, 2, (ouro_v *[]){argument, ouro_nat(7000 + ordinal)});
		prefix_token_addresses[ordinal] = (uintptr_t)token;
		tokens = ouro_ctor(1, 2, (ouro_v *[]){token, tokens});
	}
	if (remaining > 1)
		return ouro_clos(prefix_raw_argument, ouro_cons(ouro_nat(remaining - 1),
			ouro_cons(ouro_get(env, 1), ouro_cons(ouro_get(env, 2),
			ouro_cons(reversed, ouro_cons(tokens, env->next->next->next->next->next))))));
	prefix_body_calls++;
	memset(ouro_alloc(2UL * 1024UL * 1024UL), 0x5C, 2UL * 1024UL * 1024UL);
	cursor = reversed;
	for (index = arity; index > 0; index--) {
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2) {
			prefix_failed = 1;
			return ouro_ctor(0, 0, 0);
		}
		arguments[index - 1] = OURO_F(cursor, 0);
		cursor = OURO_F(cursor, 1);
	}
	if (!nil(cursor) || !ouro_nat_to_ulong(argument, &mode) || mode > 2) {
		prefix_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	if (mode == 1)
		return ouro_ctor(1, 2, (ouro_v *[]){ouro_nat(7), ouro_ctor(0, 0, 0)});
	if (mode == 2)
		return ouro_ctor(1, 2, (ouro_v *[]){ouro_nat(8), ouro_get(env, 6)});
	ordered = ouro_ctor(0, 0, 0);
	for (index = arity; index > 0; index--)
		ordered = ouro_ctor(1, 2, (ouro_v *[]){arguments[index - 1], ordered});
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){arguments[1]});
	graph = thunk_cycle_body(ouro_cons(ouro_get(env, 5), 0), ouro_get(env, 6));
	return ouro_ctor(0, 1, (ouro_v *[]){ouro_ctor(0, 4,
		(ouro_v *[]){ordered, tokens, view, graph})});
}

static ouro_v *prefix_raw(unsigned long prefix, ouro_v *caller, ouro_v *owner)
{
	return ouro_clos(prefix_raw_argument, ouro_cons(ouro_nat(prefix + 7),
		ouro_cons(ouro_nat(prefix + 7), ouro_cons(ouro_nat(prefix),
		ouro_cons(ouro_ctor(0, 0, 0), ouro_cons(ouro_ctor(0, 0, 0),
		ouro_cons(caller, ouro_cons(owner, 0))))))));
}

static int prefix_error(ouro_v *value, unsigned long mode, ouro_v *owner)
{
	return value != 0 && value->tag == 1 && value->n == 2 &&
		nat_is(OURO_F(value, 0), mode == 1 ? 7 : 8) &&
		(mode == 1 ? nil(OURO_F(value, 1)) : OURO_F(value, 1) == owner);
}

static int prefix_result(ouro_v *value, ouro_v **arguments, unsigned long prefix,
	ouro_v *caller, ouro_v *owner, const uintptr_t *addresses)
{
	ouro_v *payload, *ordered, *tokens, *view, *token;
	unsigned long index;
	if (value == 0 || value->tag != 0 || value->n != 1)
		return 0;
	payload = OURO_F(value, 0);
	if (payload == 0 || payload->tag != 0 || payload->n != 4)
		return 0;
	ordered = OURO_F(payload, 0); tokens = OURO_F(payload, 1); view = OURO_F(payload, 2);
	for (index = 0; index < prefix + 7; index++) {
		if (ordered == 0 || ordered->tag != 1 || ordered->n != 2 ||
		    OURO_F(ordered, 0) != arguments[index])
			return 0;
		ordered = OURO_F(ordered, 1);
	}
	for (index = prefix; index > 0; index--) {
		if (tokens == 0 || tokens->tag != 1 || tokens->n != 2)
			return 0;
		token = OURO_F(tokens, 0);
		if (token == 0 || token->tag != 0 || token->n != 2 ||
		    OURO_F(token, 0) != arguments[index - 1] ||
		    !nat_is(OURO_F(token, 1), 7000 + index - 1) ||
		    (addresses != 0 && (uintptr_t)token != addresses[index - 1]))
			return 0;
		tokens = OURO_F(tokens, 1);
	}
	return nil(ordered) && nil(tokens) && view != 0 && view->tag == 0 && view->n == 2 &&
		OURO_F(view, 0) == owner && OURO_F(view, 1) == caller &&
		graph_aliases(OURO_F(payload, 3), owner, caller);
}

static int prefix_scope_check(unsigned long prefix, int bank)
{
	ouro_v *caller, *owner, *borrowed, *raw, *wrapped, *partial, *result, *after, *view;
	ouro_v *arguments[10], *success_arguments[10], *retained[64], *bundle, *reference;
	uintptr_t addresses[3];
	ouro_heap_context *outer;
	unsigned long index, arity = prefix + 7, old_raw, old_body, old_lazy, mark_n, mark_used;
	unsigned long actual_n, actual_used, success_count = 0;
	unsigned long long before, total;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(bank);
	(void)ouro_packed(binary, sizeof binary);
	ouro_heap_mark(); ouro_heap_mark_save(&mark_n, &mark_used);
	if (mark_n == 0 || mark_used == 0)
		return fail("prefix caller mark is vacuous");
	ouro_perm_begin();
	caller = ouro_string_codes("prefix caller");
	owner = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	owner = ouro_apply(ouro_apply(ouro_fast("add"), owner), owner);
	borrowed = ouro_thunk(prefix_borrowed_value, ouro_cons(owner, ouro_cons(caller, 0)));
	raw = prefix_raw(prefix, caller, owner);
	wrapped = prefix == 2 ? ouro_wrap_module_maps_for_scope(raw) : ouro_wrap_module_rewrite_decls_scope(raw);
	for (index = 0; index < arity; index++)
		arguments[index] = index == 0 ? ouro_ctor(0, 0, 0) :
			index == 1 ? borrowed : index == 2 ? owner : ouro_nat(8000 + index);
	arguments[arity - 1] = ouro_nat(0);
	memcpy(success_arguments, arguments, arity * sizeof(*arguments));
	old_raw = prefix_raw_calls; old_body = prefix_body_calls; old_lazy = prefix_lazy_calls;
	partial = wrapped;
	for (index = 0; index + 1 < arity; index++) {
		partial = ouro_apply(partial, arguments[index]);
		if (prefix_raw_calls != old_raw + (index + 1 < prefix ? index + 1 : prefix) ||
		    prefix_body_calls != old_body || prefix_lazy_calls != old_lazy)
			return fail("prefix caller application count, forcing or premature body");
	}
	memcpy(addresses, prefix_token_addresses, prefix * sizeof(*addresses));
	outer = ouro_heap_context_enter();
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 64; index++) {
		unsigned long mode = index % 3;
		arguments[arity - 1] = ouro_nat(mode);
		retained[index] = ouro_apply(partial, arguments[arity - 1]);
		if (mode == 0)
			success_count++;
		if ((mode == 0 ? !prefix_result(retained[index], arguments, prefix, caller, owner, addresses) :
		    !prefix_error(retained[index], mode, owner)) || prefix_failed || failed || extended_failed ||
		    prefix_raw_calls != old_raw + prefix + 7 * (index + 1) ||
		    prefix_body_calls != old_body + index + 1 || prefix_lazy_calls != old_lazy + success_count ||
		    !prefix_result(retained[0], success_arguments, prefix, caller, owner, addresses) ||
		    ouro_heap_live_bytes() > before + 262144ULL)
			return fail("prefix full result, typed failure, captures, invocation count or scratch growth");
	}
	if (ouro_heap_total_alloc_bytes() < total + 64ULL * 2ULL * 1024ULL * 1024ULL)
		return fail("prefix raw scratch control did not execute");
	bundle = ouro_heap_context_leave(outer, ouro_ctor(0, 3,
		(ouro_v *[]){retained[0], retained[1], retained[2]}));
	after = ouro_packed(binary, sizeof binary);
	ouro_perm_end();
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used)
		return fail("prefix caller mark not restored");
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1 - bank);
	if (!packed(after, binary, sizeof binary) ||
	    !packed(caller, (const unsigned char *)"prefix caller", 13) ||
	    owner == 0 || owner->tag != OURO_TAG_BIG_NAT || owner->n != 3 ||
	    memcmp(owner + 1, (const uint32_t[]){UINT32_C(0xeca86420), UINT32_C(0xfdb97530), 1}, 12) != 0 ||
	    !prefix_result(OURO_F(bundle, 0), success_arguments, prefix, caller, owner, addresses) ||
	    !prefix_error(OURO_F(bundle, 1), 1, owner) || !prefix_error(OURO_F(bundle, 2), 2, owner))
		return fail("prefix permanent bank/depth or complete nested survivor lost");
	ouro_perm_begin();
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){borrowed});
	if (view == 0 || view->tag != 0 || view->n != 2 ||
	    OURO_F(view, 0) != owner || OURO_F(view, 1) != caller ||
	    !force_alias(OURO_F(OURO_F(OURO_F(bundle, 0), 0), 3), owner, caller)) {
		ouro_perm_end();
		return fail("prefix caller branch or returned child THUNK after reset");
	}
	ouro_perm_end();
	result = ouro_apply(partial, ouro_nat(0));
	if (!prefix_result(result, success_arguments, prefix, caller, owner, addresses) ||
	    !prefix_error(ouro_apply(partial, ouro_nat(1)), 1, owner) ||
	    !prefix_error(ouro_apply(partial, ouro_nat(2)), 2, owner))
		return fail("prefix reusable borrowed partial after both error paths");
	reference = raw;
	for (index = 0; index < arity; index++)
		reference = ouro_apply(reference, success_arguments[index]);
	if (!prefix_result(reference, success_arguments, prefix, caller, owner, 0) ||
	    !prefix_result(OURO_F(bundle, 0), success_arguments, prefix, caller, owner, addresses))
		return fail("prefix original raw, prior result or complete direct contract changed");
	return 0;
}

static int prefix_nested_scope_check(int bank)
{
	ouro_v *parent, *owner, *maps, *parent_branch, *caller, *borrowed, *unit_maps;
	ouro_v *raw, *partial, *result, *packet, *kept, *tokens, *cursor, *after;
	ouro_v *arguments[10], *modes[3], *retained[64], *results, *view;
	uintptr_t unit_addresses[3], kept_addresses[3];
	ouro_heap_context *unit;
	unsigned long index, old_raw, old_body, old_lazy, success_count = 0;
	unsigned long mark_n, mark_used, unit_n, unit_used, actual_n, actual_used;
	unsigned long long before, total;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(bank);
	(void)ouro_packed(binary, sizeof binary);
	ouro_heap_mark(); ouro_heap_mark_save(&mark_n, &mark_used);
	if (mark_n == 0 || mark_used == 0)
		return fail("nested prefix parent mark is vacuous");
	ouro_perm_begin();
	parent = ouro_string_codes("nested parent caller");
	owner = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	owner = ouro_apply(ouro_apply(ouro_fast("add"), owner), owner);
	maps = ouro_ctor(0, 3, (ouro_v *[]){parent, owner, ouro_packed(binary, sizeof binary)});
	parent_branch = ouro_thunk(prefix_borrowed_value, ouro_cons(owner, ouro_cons(parent, 0)));
	unit = ouro_heap_context_enter();
	(void)ouro_packed(binary, sizeof binary);
	ouro_heap_mark(); ouro_heap_mark_save(&unit_n, &unit_used);
	if (unit_n == 0 || unit_used == 0)
		return fail("nested prefix unit mark is vacuous");
	ouro_perm_select(1 - bank); ouro_perm_begin();
	caller = ouro_string_codes("nested unit caller");
	borrowed = ouro_thunk(prefix_borrowed_value, ouro_cons(owner, ouro_cons(caller, 0)));
	unit_maps = ouro_ctor(0, 3, (ouro_v *[]){maps, caller, owner});
	raw = prefix_raw(3, caller, owner);
	partial = ouro_wrap_module_rewrite_decls_scope(raw);
	for (index = 0; index < 3; index++)
		modes[index] = ouro_nat(index);
	for (index = 0; index < 10; index++)
		arguments[index] = index == 0 ? ouro_ctor(0, 0, 0) : index == 1 ? borrowed :
			index == 2 ? owner : index == 3 ? unit_maps : ouro_nat(8100 + index);
	arguments[9] = modes[0];
	old_raw = prefix_raw_calls; old_body = prefix_body_calls; old_lazy = prefix_lazy_calls;
	for (index = 0; index < 9; index++) {
		partial = ouro_apply(partial, arguments[index]);
		if (prefix_raw_calls != old_raw + (index < 3 ? index + 1 : 3) ||
		    prefix_body_calls != old_body || prefix_lazy_calls != old_lazy)
			return fail("nested prefix unit partial forced before declaration saturation");
	}
	memcpy(unit_addresses, prefix_token_addresses, sizeof unit_addresses);
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 64; index++) {
		unsigned long mode = index % 3;
		arguments[9] = modes[mode];
		retained[index] = ouro_apply(partial, arguments[9]);
		if (mode == 0)
			success_count++;
		ouro_heap_mark_save(&actual_n, &actual_used);
		if ((mode == 0 ? !prefix_result(retained[index], arguments, 3, caller, owner, unit_addresses) :
		    !prefix_error(retained[index], mode, owner)) || prefix_failed || failed || extended_failed ||
		    prefix_raw_calls != old_raw + 3 + 7 * (index + 1) ||
		    prefix_body_calls != old_body + index + 1 || prefix_lazy_calls != old_lazy + success_count ||
		    actual_n != unit_n || actual_used != unit_used ||
		    ouro_heap_live_bytes() > before + 262144ULL)
			return fail("nested prefix complete declaration, borrowed captures, unit mark or scratch growth");
		arguments[9] = modes[0];
		if (!prefix_result(retained[0], arguments, 3, caller, owner, unit_addresses) ||
		    unit_maps == 0 || unit_maps->tag != 0 || unit_maps->n != 3 ||
		    OURO_F(unit_maps, 0) != maps || OURO_F(unit_maps, 1) != caller || OURO_F(unit_maps, 2) != owner)
			return fail("nested prefix prior declaration or borrowed maps released");
	}
	if (ouro_heap_total_alloc_bytes() < total + 64ULL * 2ULL * 1024ULL * 1024ULL)
		return fail("nested prefix declaration scratch control did not execute");
	results = ouro_ctor(0, 0, 0);
	for (index = 64; index > 0; index--)
		results = ouro_ctor(1, 2, (ouro_v *[]){retained[index - 1], results});
	tokens = OURO_F(OURO_F(retained[0], 0), 1);
	packet = ouro_ctor(0, 10, arguments);
	after = ouro_packed(binary, sizeof binary);
	ouro_perm_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(bank);
	if (!packed(after, binary, sizeof binary) || !prefix_result(retained[0], arguments, 3,
	    caller, owner, unit_addresses) || !prefix_error(retained[1], 1, owner) ||
	    !prefix_error(retained[2], 2, owner))
		return fail("nested prefix unit bank/depth or declarations lost after unit phase reset");
	kept = ouro_heap_context_leave(unit, ouro_ctor(0, 10, (ouro_v *[]){results, caller,
		borrowed, raw, partial, packet, tokens, unit_maps, ouro_ctor(0, 3, modes), after}));
	after = ouro_packed(binary, sizeof binary);
	ouro_perm_end();
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used)
		return fail("nested prefix parent mark not restored");
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1 - bank);
	memset(ouro_alloc(4096UL), 0xD3, 4096UL);
	if (!packed(after, binary, sizeof binary) || !packed(parent,
	    (const unsigned char *)"nested parent caller", sizeof("nested parent caller") - 1) ||
	    owner == 0 || owner->tag != OURO_TAG_BIG_NAT || owner->n != 3 ||
	    memcmp(owner + 1, (const uint32_t[]){UINT32_C(0xeca86420), UINT32_C(0xfdb97530), 1}, 12) != 0 ||
	    maps == 0 || maps->tag != 0 || maps->n != 3 || OURO_F(maps, 0) != parent ||
	    OURO_F(maps, 1) != owner || !packed(OURO_F(maps, 2), binary, sizeof binary) ||
	    kept == 0 || kept->tag != 0 || kept->n != 10)
		return fail("nested prefix parent bank/depth or full unit survivor lost");
	results = OURO_F(kept, 0); caller = OURO_F(kept, 1); borrowed = OURO_F(kept, 2);
	raw = OURO_F(kept, 3); partial = OURO_F(kept, 4); packet = OURO_F(kept, 5);
	tokens = OURO_F(kept, 6); unit_maps = OURO_F(kept, 7); cursor = OURO_F(kept, 8);
	if (!packed(caller, (const unsigned char *)"nested unit caller", sizeof("nested unit caller") - 1) ||
	    packet == 0 || packet->tag != 0 || packet->n != 10 || cursor == 0 || cursor->tag != 0 ||
	    cursor->n != 3 || unit_maps == 0 || unit_maps->tag != 0 || unit_maps->n != 3 ||
	    OURO_F(unit_maps, 0) != maps || OURO_F(unit_maps, 1) != caller || OURO_F(unit_maps, 2) != owner ||
	    !packed(OURO_F(kept, 9), binary, sizeof binary))
		return fail("nested prefix unit captures or opaque argument packet changed");
	for (index = 0; index < 10; index++)
		arguments[index] = OURO_F(packet, index);
	for (index = 0; index < 3; index++) {
		modes[index] = OURO_F(cursor, index);
		if (!nat_is(modes[index], index))
			return fail("nested prefix mode capture changed");
	}
	if (!nil(arguments[0]) || arguments[1] != borrowed || arguments[2] != owner || arguments[3] != unit_maps)
		return fail("nested prefix shared unit/caller capture identity changed");
	/* Unit tokens move on outer leave; parent map identities stay shared. */
	cursor = tokens;
	for (index = 3; index > 0; index--) {
		ouro_v *token;
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2)
			return fail("nested prefix promoted token list changed");
		token = OURO_F(cursor, 0);
		kept_addresses[index - 1] = (uintptr_t)token;
		if (token == 0 || kept_addresses[index - 1] == unit_addresses[index - 1])
			return fail("nested prefix unit token was not promoted");
		cursor = OURO_F(cursor, 1);
	}
	if (!nil(cursor))
		return fail("nested prefix promoted token tail changed");
	ouro_perm_begin();
	cursor = results;
	for (index = 0; index < 64; index++) {
		unsigned long mode = index % 3;
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2) {
			ouro_perm_end();
			return fail("nested prefix complete declaration list changed");
		}
		arguments[9] = modes[mode]; result = OURO_F(cursor, 0);
		if (mode == 0 ? !prefix_result(result, arguments, 3, caller, owner, kept_addresses) :
		    !prefix_error(result, mode, owner)) {
			ouro_perm_end();
			return fail("nested prefix declaration result after outer leave changed");
		}
		cursor = OURO_F(cursor, 1);
	}
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){parent_branch});
	if (!nil(cursor) || view == 0 || view->tag != 0 || view->n != 2 ||
	    OURO_F(view, 0) != owner || OURO_F(view, 1) != parent) {
		ouro_perm_end();
		return fail("nested prefix parent branch after outer leave changed");
	}
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){borrowed});
	if (view == 0 || view->tag != 0 || view->n != 2 || OURO_F(view, 0) != owner ||
	    OURO_F(view, 1) != caller || !force_alias(OURO_F(OURO_F(OURO_F(results, 0), 0), 3), owner, caller)) {
		ouro_perm_end();
		return fail("nested prefix promoted borrowed or returned THUNK changed");
	}
	arguments[9] = modes[0]; result = ouro_apply(partial, modes[0]);
	if (!prefix_result(result, arguments, 3, caller, owner, kept_addresses) ||
	    !prefix_error(ouro_apply(partial, modes[1]), 1, owner) ||
	    !prefix_error(ouro_apply(partial, modes[2]), 2, owner)) {
		ouro_perm_end();
		return fail("nested prefix unit partial after enclosing leave changed");
	}
	result = raw;
	for (index = 0; index < 10; index++)
		result = ouro_apply(result, arguments[index]);
	if (!prefix_result(result, arguments, 3, caller, owner, 0) ||
	    !prefix_result(OURO_F(results, 0), arguments, 3, caller, owner, kept_addresses)) {
		ouro_perm_end();
		return fail("nested prefix original unit raw or retained declaration changed");
	}
	ouro_perm_end();
	return 0;
}

static unsigned long body2_raw_calls, body2_body_calls, body2_lazy_calls;
static uintptr_t body2_token_addresses[3];
static int body2_failed;

static ouro_v *body2_borrowed_value(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	body2_lazy_calls++;
	return ouro_ctor(0, 3, (ouro_v *[]){ouro_get(env, 0), ouro_get(env, 1), ouro_get(env, 2)});
}

static ouro_v *body2_raw_argument(ouro_env *env, ouro_v *argument)
{
	unsigned long remaining, arity, prefix, ordinal, index, mode;
	ouro_v *reversed, *tokens, *cursor, *arguments[5], *ordered, *domain, *graph, *view;
	ouro_v *owner = ouro_get(env, 6), *maps = ouro_get(env, 7), *pair, *heads, *refs, *errors;
	if (!ouro_nat_to_ulong(ouro_get(env, 0), &remaining) ||
	    !ouro_nat_to_ulong(ouro_get(env, 1), &arity) ||
	    !ouro_nat_to_ulong(ouro_get(env, 2), &prefix) ||
	    (prefix != 2 && prefix != 3) || arity != prefix + 2 || remaining == 0 || remaining > arity) {
		body2_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	ordinal = arity - remaining; body2_raw_calls++;
	reversed = ouro_ctor(1, 2, (ouro_v *[]){argument, ouro_get(env, 3)});
	tokens = ouro_get(env, 4);
	if (ordinal < prefix) {
		ouro_v *token = ouro_ctor(0, 2, (ouro_v *[]){argument, ouro_nat(7600 + ordinal)});
		body2_token_addresses[ordinal] = (uintptr_t)token;
		tokens = ouro_ctor(1, 2, (ouro_v *[]){token, tokens});
	}
	if (remaining > 1)
		return ouro_clos(body2_raw_argument, ouro_cons(ouro_nat(remaining - 1),
			ouro_cons(ouro_get(env, 1), ouro_cons(ouro_get(env, 2),
			ouro_cons(reversed, ouro_cons(tokens, env->next->next->next->next->next))))));
	body2_body_calls++;
	memset(ouro_alloc(2UL * 1024UL * 1024UL), 0xB2, 2UL * 1024UL * 1024UL);
	cursor = reversed;
	for (index = arity; index > 0; index--) {
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2) {
			body2_failed = 1;
			return ouro_ctor(0, 0, 0);
		}
		arguments[index - 1] = OURO_F(cursor, 0); cursor = OURO_F(cursor, 1);
	}
	if (!nil(cursor) || !ouro_nat_to_ulong(argument, &mode) || mode > 2) {
		body2_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	if (mode == 1)
		return ouro_ctor(1, 2, (ouro_v *[]){ouro_nat(7), ouro_ctor(0, 0, 0)});
	if (mode == 2)
		return ouro_ctor(1, 2, (ouro_v *[]){ouro_nat(8), owner});
	ordered = ouro_ctor(0, 0, 0);
	for (index = arity; index > 0; index--)
		ordered = ouro_ctor(1, 2, (ouro_v *[]){arguments[index - 1], ordered});
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){arguments[1]});
	graph = thunk_cycle_body(ouro_cons(ouro_get(env, 5), 0), owner);
	if (prefix == 2) {
		pair = ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(11), owner});
		heads = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){owner, ouro_nat(7)}), ouro_ctor(0, 0, 0)});
		refs = ouro_ctor(1, 2, (ouro_v *[]){pair, ouro_ctor(1, 2, (ouro_v *[]){pair, ouro_ctor(0, 0, 0)})});
		errors = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){ouro_nat(13), owner}), ouro_ctor(0, 0, 0)});
		domain = ouro_ctor(0, 3, (ouro_v *[]){heads, refs, errors});
	} else {
		domain = ouro_ctor(1, 2, (ouro_v *[]){owner, ouro_ctor(1, 2,
			(ouro_v *[]){ouro_nat(17), ouro_ctor(1, 2, (ouro_v *[]){owner, ouro_ctor(0, 0, 0)})})});
	}
	return ouro_ctor(0, 6, (ouro_v *[]){ordered, tokens, domain, graph, view, maps});
}

static ouro_v *body2_raw(unsigned long prefix, ouro_v *caller, ouro_v *owner, ouro_v *maps)
{
	return ouro_clos(body2_raw_argument, ouro_cons(ouro_nat(prefix + 2),
		ouro_cons(ouro_nat(prefix + 2), ouro_cons(ouro_nat(prefix), ouro_cons(ouro_ctor(0, 0, 0),
		ouro_cons(ouro_ctor(0, 0, 0), ouro_cons(caller, ouro_cons(owner, ouro_cons(maps, 0)))))))));
}

static int body2_result(ouro_v *value, ouro_v **arguments, unsigned long prefix,
	ouro_v *caller, ouro_v *owner, ouro_v *maps, const uintptr_t *addresses)
{
	ouro_v *ordered, *tokens, *view, *domain, *token, *heads, *refs, *errors, *pair, *tail;
	unsigned long index;
	if (value == 0 || value->tag != 0 || value->n != 6 || OURO_F(value, 5) != maps)
		return 0;
	ordered = OURO_F(value, 0); tokens = OURO_F(value, 1); domain = OURO_F(value, 2); view = OURO_F(value, 4);
	for (index = 0; index < prefix + 2; index++) {
		if (ordered == 0 || ordered->tag != 1 || ordered->n != 2 || OURO_F(ordered, 0) != arguments[index])
			return 0;
		ordered = OURO_F(ordered, 1);
	}
	for (index = prefix; index > 0; index--) {
		if (tokens == 0 || tokens->tag != 1 || tokens->n != 2)
			return 0;
		token = OURO_F(tokens, 0);
		if (token == 0 || token->tag != 0 || token->n != 2 || OURO_F(token, 0) != arguments[index - 1] ||
		    !nat_is(OURO_F(token, 1), 7600 + index - 1) ||
		    (addresses != 0 && (uintptr_t)token != addresses[index - 1]))
			return 0;
		tokens = OURO_F(tokens, 1);
	}
	if (!nil(ordered) || !nil(tokens) || view == 0 || view->tag != 0 || view->n != 3 ||
	    OURO_F(view, 0) != owner || OURO_F(view, 1) != caller || OURO_F(view, 2) != maps ||
	    !graph_aliases(OURO_F(value, 3), owner, caller))
		return 0;
	if (prefix == 3) {
		if (domain == 0 || domain->tag != 1 || domain->n != 2 || OURO_F(domain, 0) != owner)
			return 0;
		tail = OURO_F(domain, 1);
		if (tail == 0 || tail->tag != 1 || tail->n != 2 || !nat_is(OURO_F(tail, 0), 17))
			return 0;
		tail = OURO_F(tail, 1);
		return tail != 0 && tail->tag == 1 && tail->n == 2 && OURO_F(tail, 0) == owner && nil(OURO_F(tail, 1));
	}
	if (domain == 0 || domain->tag != 0 || domain->n != 3)
		return 0;
	heads = OURO_F(domain, 0); refs = OURO_F(domain, 1); errors = OURO_F(domain, 2);
	if (heads == 0 || heads->tag != 1 || heads->n != 2 || !nil(OURO_F(heads, 1)) ||
	    refs == 0 || refs->tag != 1 || refs->n != 2 || errors == 0 || errors->tag != 1 ||
	    errors->n != 2 || !nil(OURO_F(errors, 1)))
		return 0;
	pair = OURO_F(heads, 0);
	if (pair == 0 || pair->tag != 0 || pair->n != 2 || OURO_F(pair, 0) != owner || !nat_is(OURO_F(pair, 1), 7))
		return 0;
	pair = OURO_F(refs, 0); tail = OURO_F(refs, 1);
	if (pair == 0 || pair->tag != 0 || pair->n != 2 || !nat_is(OURO_F(pair, 0), 11) ||
	    OURO_F(pair, 1) != owner || tail == 0 || tail->tag != 1 || tail->n != 2 ||
	    OURO_F(tail, 0) != pair || !nil(OURO_F(tail, 1)))
		return 0;
	pair = OURO_F(errors, 0);
	return pair != 0 && pair->tag == 0 && pair->n == 2 && nat_is(OURO_F(pair, 0), 13) && OURO_F(pair, 1) == owner;
}

static int body2_nested_scope_check(unsigned long prefix, int bank)
{
	ouro_v *parent, *owner, *parent_maps, *parent_branch, *caller, *borrowed, *maps;
	ouro_v *raw, *partial, *result, *packet, *kept, *tokens, *cursor, *after, *view, *results;
	ouro_v *arguments[5], *modes[3], *retained[64];
	uintptr_t unit_addresses[3], kept_addresses[3];
	ouro_heap_context *unit;
	unsigned long index, arity = prefix + 2, old_raw, old_body, old_lazy, successes = 0;
	unsigned long mark_n, mark_used, unit_n, unit_used, actual_n, actual_used;
	unsigned long long before, total;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(bank);
	(void)ouro_packed(binary, sizeof binary); ouro_heap_mark(); ouro_heap_mark_save(&mark_n, &mark_used);
	if (mark_n == 0 || mark_used == 0)
		return fail("body2 parent mark is vacuous");
	ouro_perm_begin();
	parent = ouro_string_codes("body2 parent caller");
	owner = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	owner = ouro_apply(ouro_apply(ouro_fast("add"), owner), owner);
	parent_maps = ouro_ctor(0, 3, (ouro_v *[]){parent, owner, ouro_packed(binary, sizeof binary)});
	parent_branch = ouro_thunk(body2_borrowed_value, ouro_cons(owner, ouro_cons(parent, ouro_cons(parent_maps, 0))));
	unit = ouro_heap_context_enter();
	(void)ouro_packed(binary, sizeof binary); ouro_heap_mark(); ouro_heap_mark_save(&unit_n, &unit_used);
	if (unit_n == 0 || unit_used == 0)
		return fail("body2 unit mark is vacuous");
	ouro_perm_select(1 - bank); ouro_perm_begin();
	caller = ouro_string_codes("body2 unit caller");
	maps = ouro_ctor(0, 3, (ouro_v *[]){parent_maps, caller, owner});
	borrowed = ouro_thunk(body2_borrowed_value, ouro_cons(owner, ouro_cons(caller, ouro_cons(maps, 0))));
	raw = body2_raw(prefix, caller, owner, maps);
	partial = prefix == 2 ? ouro_wrap_module_scope_maps_scope(raw) : ouro_wrap_module_bare_ctors_scope(raw);
	for (index = 0; index < 3; index++)
		modes[index] = ouro_nat(index);
	arguments[0] = ouro_ctor(0, 0, 0); arguments[1] = borrowed;
	if (prefix == 3)
		arguments[2] = owner;
	arguments[prefix] = maps; arguments[arity - 1] = modes[0];
	old_raw = body2_raw_calls; old_body = body2_body_calls; old_lazy = body2_lazy_calls;
	for (index = 0; index + 1 < arity; index++) {
		partial = ouro_apply(partial, arguments[index]);
		if (body2_raw_calls != old_raw + (index < prefix ? index + 1 : prefix) ||
		    body2_body_calls != old_body || body2_lazy_calls != old_lazy)
			return fail("body2 raw application, body or borrowed forcing before saturation");
	}
	memcpy(unit_addresses, body2_token_addresses, prefix * sizeof(*unit_addresses));
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 64; index++) {
		unsigned long mode = index % 3;
		arguments[arity - 1] = modes[mode]; retained[index] = ouro_apply(partial, arguments[arity - 1]);
		if (mode == 0)
			successes++;
		ouro_heap_mark_save(&actual_n, &actual_used);
		if ((mode == 0 ? !body2_result(retained[index], arguments, prefix, caller, owner, maps, unit_addresses) :
		    !prefix_error(retained[index], mode, owner)) || body2_failed || failed || extended_failed ||
		    body2_raw_calls != old_raw + prefix + 2 * (index + 1) || body2_body_calls != old_body + index + 1 ||
		    body2_lazy_calls != old_lazy + successes || actual_n != unit_n || actual_used != unit_used ||
		    ouro_heap_live_bytes() > before + 262144ULL)
			return fail("body2 full output, errors, unit marks or retained scratch growth");
		arguments[arity - 1] = modes[0];
		if (!body2_result(retained[0], arguments, prefix, caller, owner, maps, unit_addresses))
			return fail("body2 prior full output released");
	}
	if (ouro_heap_total_alloc_bytes() < total + 64ULL * 2ULL * 1024ULL * 1024ULL)
		return fail("body2 actual raw scratch control did not execute");
	results = ouro_ctor(0, 0, 0);
	for (index = 64; index > 0; index--)
		results = ouro_ctor(1, 2, (ouro_v *[]){retained[index - 1], results});
	tokens = OURO_F(retained[0], 1); packet = ouro_ctor(0, (int)arity, arguments);
	after = ouro_packed(binary, sizeof binary); ouro_perm_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(bank);
	if (!packed(after, binary, sizeof binary) || !body2_result(retained[0], arguments, prefix,
	    caller, owner, maps, unit_addresses) || !prefix_error(retained[1], 1, owner) || !prefix_error(retained[2], 2, owner))
		return fail("body2 unit bank/depth lost after phase reset");
	kept = ouro_heap_context_leave(unit, ouro_ctor(0, 10, (ouro_v *[]){results, caller,
		borrowed, raw, partial, packet, tokens, maps, ouro_ctor(0, 3, modes), after}));
	after = ouro_packed(binary, sizeof binary); ouro_perm_end();
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used)
		return fail("body2 parent mark not restored");
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1 - bank); memset(ouro_alloc(4096UL), 0xC2, 4096UL);
	if (!packed(after, binary, sizeof binary) || !packed(parent,
	    (const unsigned char *)"body2 parent caller", sizeof("body2 parent caller") - 1) ||
	    owner == 0 || owner->tag != OURO_TAG_BIG_NAT || owner->n != 3 ||
	    memcmp(owner + 1, (const uint32_t[]){UINT32_C(0xeca86420), UINT32_C(0xfdb97530), 1}, 12) != 0 ||
	    parent_maps == 0 || parent_maps->tag != 0 || parent_maps->n != 3 || OURO_F(parent_maps, 0) != parent ||
	    OURO_F(parent_maps, 1) != owner || !packed(OURO_F(parent_maps, 2), binary, sizeof binary) ||
	    kept == 0 || kept->tag != 0 || kept->n != 10)
		return fail("body2 parent bank/depth, maps or full survivor lost");
	results = OURO_F(kept, 0); caller = OURO_F(kept, 1); borrowed = OURO_F(kept, 2);
	raw = OURO_F(kept, 3); partial = OURO_F(kept, 4); packet = OURO_F(kept, 5);
	tokens = OURO_F(kept, 6); maps = OURO_F(kept, 7); cursor = OURO_F(kept, 8);
	if (!packed(caller, (const unsigned char *)"body2 unit caller", sizeof("body2 unit caller") - 1) ||
	    packet == 0 || packet->tag != 0 || packet->n != (int)arity || cursor == 0 || cursor->tag != 0 || cursor->n != 3 ||
	    maps == 0 || maps->tag != 0 || maps->n != 3 || OURO_F(maps, 0) != parent_maps ||
	    OURO_F(maps, 1) != caller || OURO_F(maps, 2) != owner || !packed(OURO_F(kept, 9), binary, sizeof binary))
		return fail("body2 complete unit captures changed");
	for (index = 0; index < arity; index++)
		arguments[index] = OURO_F(packet, index);
	for (index = 0; index < 3; index++) {
		modes[index] = OURO_F(cursor, index);
		if (!nat_is(modes[index], index))
			return fail("body2 mode capture changed");
	}
	if (!nil(arguments[0]) || arguments[1] != borrowed || arguments[prefix] != maps ||
	    (prefix == 3 && arguments[2] != owner))
		return fail("body2 shared caller/unit argument identities changed");
	cursor = tokens;
	for (index = prefix; index > 0; index--) {
		ouro_v *token;
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2)
			return fail("body2 promoted prefix list changed");
		token = OURO_F(cursor, 0); kept_addresses[index - 1] = (uintptr_t)token;
		if (token == 0 || kept_addresses[index - 1] == unit_addresses[index - 1])
			return fail("body2 unit prefix token not promoted");
		cursor = OURO_F(cursor, 1);
	}
	if (!nil(cursor))
		return fail("body2 promoted prefix tail changed");
	ouro_perm_begin(); cursor = results;
	for (index = 0; index < 64; index++) {
		unsigned long mode = index % 3;
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2) {
			ouro_perm_end(); return fail("body2 full result list changed");
		}
		arguments[arity - 1] = modes[mode]; result = OURO_F(cursor, 0);
		if (mode == 0 ? !body2_result(result, arguments, prefix, caller, owner, maps, kept_addresses) :
		    !prefix_error(result, mode, owner)) {
			ouro_perm_end(); return fail("body2 complete output after enclosing leave changed");
		}
		cursor = OURO_F(cursor, 1);
	}
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){parent_branch});
	if (!nil(cursor) || view == 0 || view->tag != 0 || view->n != 3 || OURO_F(view, 0) != owner ||
	    OURO_F(view, 1) != parent || OURO_F(view, 2) != parent_maps) {
		ouro_perm_end(); return fail("body2 borrowed parent branch changed");
	}
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){borrowed});
	if (view == 0 || view->tag != 0 || view->n != 3 || OURO_F(view, 0) != owner || OURO_F(view, 1) != caller ||
	    OURO_F(view, 2) != maps || !force_alias(OURO_F(OURO_F(results, 0), 3), owner, caller)) {
		ouro_perm_end(); return fail("body2 unit/returned THUNK or self-cycle changed");
	}
	arguments[arity - 1] = modes[0]; result = ouro_apply(partial, modes[0]);
	if (!body2_result(result, arguments, prefix, caller, owner, maps, kept_addresses) ||
	    !prefix_error(ouro_apply(partial, modes[1]), 1, owner) || !prefix_error(ouro_apply(partial, modes[2]), 2, owner)) {
		ouro_perm_end(); return fail("body2 unit partial after errors/enclosing leave changed");
	}
	result = raw;
	for (index = 0; index < arity; index++)
		result = ouro_apply(result, arguments[index]);
	if (!body2_result(result, arguments, prefix, caller, owner, maps, 0) ||
	    !body2_result(OURO_F(results, 0), arguments, prefix, caller, owner, maps, kept_addresses)) {
		ouro_perm_end(); return fail("body2 original raw or prior full output changed");
	}
	ouro_perm_end(); return 0;
}

static unsigned long invalid_maps_raw_calls, invalid_maps_body_calls, invalid_maps_lazy_calls;
static unsigned long invalid_maps_prefix_n, invalid_maps_prefix_used, invalid_maps_body_n, invalid_maps_body_used;
static int invalid_maps_failed;

static ouro_v *invalid_maps_refs_value(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	invalid_maps_lazy_calls++;
	return ouro_get(env, 0);
}

static ouro_v *invalid_maps_raw_errors(ouro_env *env, ouro_v *errors)
{
	ouro_v *refs = ouro_get(env, 0), *heads = ouro_get(env, 1), *token = ouro_get(env, 2);
	ouro_v *maps = ouro_get(env, 3), *borrowed = ouro_get(env, 4), *expected_refs = ouro_get(env, 5);
	ouro_v *row, *key, *view;
	invalid_maps_raw_calls++; invalid_maps_body_calls++;
	ouro_heap_mark_save(&invalid_maps_body_n, &invalid_maps_body_used);
	memset(ouro_alloc(2UL * 1024UL * 1024UL), 0xB1, 2UL * 1024UL * 1024UL);
	if (refs != borrowed || token == 0 || token->tag != 0 || token->n != 2 ||
	    OURO_F(token, 0) != heads || !nat_is(OURO_F(token, 1), 7701) ||
	    maps == 0 || maps->tag != 0 || maps->n != 3) {
		invalid_maps_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){borrowed});
	if (view != expected_refs) {
		invalid_maps_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	if (nil(errors))
		return ouro_ctor(0, 0, 0);
	if (errors == 0 || errors->tag != 1 || errors->n != 2 ||
	    (row = OURO_F(errors, 0)) == 0 || row->tag != 0 || row->n != 2) {
		invalid_maps_failed = 1;
		return ouro_ctor(0, 0, 0);
	}
	key = OURO_F(row, 0);
	return ouro_ctor(1, 1, (ouro_v *[]){key});
}

static ouro_v *invalid_maps_raw_refs(ouro_env *env, ouro_v *refs)
{
	invalid_maps_raw_calls++;
	return ouro_clos(invalid_maps_raw_errors, ouro_cons(refs, env));
}

static ouro_v *invalid_maps_raw_heads(ouro_env *env, ouro_v *heads)
{
	ouro_v *token = ouro_ctor(0, 2, (ouro_v *[]){heads, ouro_nat(7701)});
	invalid_maps_raw_calls++;
	ouro_heap_mark_save(&invalid_maps_prefix_n, &invalid_maps_prefix_used);
	return ouro_clos(invalid_maps_raw_refs, ouro_cons(heads, ouro_cons(token, env)));
}

static int invalid_maps_result(ouro_v *value, ouro_v *key)
{
	return key == 0 ? nil(value) :
		value != 0 && value->tag == 1 && value->n == 1 && OURO_F(value, 0) == key;
}

static int invalid_maps_scope_check(int bank)
{
	ouro_v *parent, *wide, *peano, *fast, *parent_maps, *parent_branch;
	ouro_v *caller, *maps, *cycle, *heads, *refs, *borrowed, *zero, *raw, *partial, *body, *sibling;
	ouro_v *raw_prefix, *token, *retained[64], *errors[4], *keys[4], *results, *kept, *after, *view, *cursor;
	ouro_v *cases, *payloads, *result;
	ouro_heap_context *unit;
	uintptr_t unit_token;
	unsigned long old_raw, old_body, old_lazy, index, mode, mark_n, mark_used, unit_n, unit_used, actual_n, actual_used;
	unsigned long long before, total;
	ouro_heap_discard_phase(); ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(bank);
	(void)ouro_packed(binary, sizeof binary); ouro_heap_mark(); ouro_heap_mark_save(&mark_n, &mark_used);
	if (mark_n == 0 || mark_used == 0)
		return fail("invalid maps parent mark is vacuous");
	ouro_perm_begin();
	parent = ouro_string_codes("invalid maps parent");
	wide = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	wide = ouro_apply(ouro_apply(ouro_fast("add"), wide), wide);
	peano = ouro_ctor(1, 1, (ouro_v *[]){wide});
	fast = ouro_apply(ouro_apply(ouro_fast("add"), wide), ouro_nat(1));
	parent_maps = ouro_ctor(0, 3, (ouro_v *[]){parent, peano, fast});
	parent_branch = ouro_thunk(captured_value, ouro_cons(parent_maps, 0));
	unit = ouro_heap_context_enter();
	(void)ouro_packed(binary, sizeof binary); ouro_heap_mark(); ouro_heap_mark_save(&unit_n, &unit_used);
	if (unit_n == 0 || unit_used == 0)
		return fail("invalid maps unit mark is vacuous");
	ouro_perm_select(1 - bank); ouro_perm_begin();
	caller = ouro_string_codes("invalid maps unit");
	maps = ouro_ctor(0, 3, (ouro_v *[]){parent_maps, caller, wide});
	cycle = ouro_fix(cycle_value, ouro_cons(maps, 0));
	heads = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){peano, ouro_nat(7)}), ouro_ctor(0, 0, 0)});
	refs = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){fast, peano}), ouro_ctor(0, 0, 0)});
	borrowed = ouro_thunk(invalid_maps_refs_value, ouro_cons(refs, ouro_cons(maps, ouro_cons(cycle, 0))));
	zero = ouro_ctor(0, 0, 0);
	errors[0] = ouro_ctor(0, 0, 0);
	for (index = 1; index < 4; index++) {
		ouro_v *key = index == 1 ? zero : index == 2 ? peano : fast;
		errors[index] = ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){key, ouro_nat(99)}),
			ouro_ctor(1, 2, (ouro_v *[]){ouro_ctor(0, 2, (ouro_v *[]){index == 1 ? peano : zero, ouro_nat(99)}), errors[0]})});
	}
	keys[0] = 0; keys[1] = zero; keys[2] = peano; keys[3] = fast;
	raw = ouro_clos(invalid_maps_raw_heads, ouro_cons(maps, ouro_cons(borrowed, ouro_cons(refs, ouro_cons(cycle, 0)))));
	old_raw = invalid_maps_raw_calls; old_body = invalid_maps_body_calls; old_lazy = invalid_maps_lazy_calls;
	partial = ouro_wrap_module_invalid_maps_scope(raw);
	if (invalid_maps_raw_calls != old_raw || invalid_maps_body_calls != old_body || invalid_maps_lazy_calls != old_lazy)
		return fail("invalid maps wrapper executed raw or borrowed capture");
	partial = ouro_apply(partial, heads);
	body = ouro_apply(partial, borrowed); sibling = ouro_apply(partial, borrowed);
	if (invalid_maps_raw_calls != old_raw + 1 || invalid_maps_body_calls != old_body ||
	    invalid_maps_lazy_calls != old_lazy || invalid_maps_prefix_n != unit_n || invalid_maps_prefix_used != unit_used)
		return fail("invalid maps prefix was deferred, repeated, child-owned or forced early");
	if (partial == 0 || partial->tag != OURO_TAG_CLOS || body == 0 || body->tag != OURO_TAG_CLOS ||
	    sibling == 0 || sibling->tag != OURO_TAG_CLOS)
		return fail("invalid maps prefix or captured body is not a callable");
	raw_prefix = ouro_get(partial->u.c.env, 1);
	if (raw_prefix == 0 || raw_prefix->tag != OURO_TAG_CLOS)
		return fail("invalid maps raw prefix is not a callable");
	token = ouro_get(raw_prefix->u.c.env, 1); unit_token = (uintptr_t)token;
	if (token == 0 || token->tag != 0 || token->n != 2 ||
	    OURO_F(token, 0) != heads || !nat_is(OURO_F(token, 1), 7701))
		return fail("invalid maps caller prefix token changed");
	before = ouro_heap_live_bytes(); total = ouro_heap_total_alloc_bytes();
	for (index = 0; index < 64; index++) {
		mode = index % 4; retained[index] = ouro_apply(body, errors[mode]);
		ouro_heap_mark_save(&actual_n, &actual_used);
		if (invalid_maps_failed || !invalid_maps_result(retained[index], keys[mode]) ||
		    invalid_maps_raw_calls != old_raw + 1 + 2 * (index + 1) || invalid_maps_body_calls != old_body + index + 1 ||
		    invalid_maps_lazy_calls != old_lazy + index + 1 || invalid_maps_body_n != 0 || invalid_maps_body_used != 0 ||
		    actual_n != unit_n || actual_used != unit_used || ouro_heap_live_bytes() > before + 262144ULL ||
		    (uintptr_t)ouro_get(raw_prefix->u.c.env, 1) != unit_token)
			return fail("invalid maps complete Maybe, first key, child saturation, mark or scratch plateau");
		if (!invalid_maps_result(retained[0], 0) || (index > 0 && !invalid_maps_result(retained[1], zero)))
			return fail("invalid maps retained Nothing or Just zero changed");
	}
	if (ouro_heap_total_alloc_bytes() < total + 64ULL * 2ULL * 1024ULL * 1024ULL)
		return fail("invalid maps actual 128MiB raw scratch was not executed");
	results = ouro_ctor(0, 0, 0);
	for (index = 64; index > 0; index--)
		results = ouro_ctor(1, 2, (ouro_v *[]){retained[index - 1], results});
	cases = ouro_ctor(0, 4, errors); payloads = ouro_ctor(0, 3, (ouro_v *[]){zero, peano, fast});
	after = ouro_packed(binary, sizeof binary); ouro_perm_end();
	ouro_heap_discard_phase(); ouro_perm_reset_bank(bank);
	if (!packed(after, binary, sizeof binary) || !invalid_maps_result(retained[1], zero))
		return fail("invalid maps unit allocation bank or depth lost");
	kept = ouro_heap_context_leave(unit, ouro_ctor(0, 14, (ouro_v *[]){results, raw, partial, body, sibling,
		heads, borrowed, cases, payloads, token, maps, cycle, caller, after}));
	after = ouro_packed(binary, sizeof binary); ouro_perm_end();
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used)
		return fail("invalid maps parent mark not restored");
	ouro_heap_discard_phase(); ouro_perm_reset_bank(1 - bank); memset(ouro_alloc(4096UL), 0xB3, 4096UL);
	if (!packed(after, binary, sizeof binary) || !packed(parent, (const unsigned char *)"invalid maps parent", 19) ||
	    wide == 0 || wide->tag != OURO_TAG_BIG_NAT || wide->n != 3 ||
	    memcmp(wide + 1, (const uint32_t[]){UINT32_C(0xeca86420), UINT32_C(0xfdb97530), 1}, 12) != 0 ||
	    peano == 0 || peano->tag != 1 || peano->n != 1 || OURO_F(peano, 0) != wide ||
	    fast == 0 || fast->tag != OURO_TAG_BIG_NAT || fast->n != 3 ||
	    memcmp(fast + 1, (const uint32_t[]){UINT32_C(0xeca86421), UINT32_C(0xfdb97530), 1}, 12) != 0 ||
	    kept == 0 || kept->tag != 0 || kept->n != 14)
		return fail("invalid maps parent bank, full Peano/FAST key or full carrier lost");
	results = OURO_F(kept, 0); raw = OURO_F(kept, 1); partial = OURO_F(kept, 2); body = OURO_F(kept, 3);
	sibling = OURO_F(kept, 4); heads = OURO_F(kept, 5); borrowed = OURO_F(kept, 6); cases = OURO_F(kept, 7);
	payloads = OURO_F(kept, 8); token = OURO_F(kept, 9); maps = OURO_F(kept, 10); cycle = OURO_F(kept, 11); caller = OURO_F(kept, 12);
	if (cases == 0 || cases->tag != 0 || cases->n != 4 || payloads == 0 || payloads->tag != 0 || payloads->n != 3 ||
	    token == 0 || token->tag != 0 || token->n != 2 || (uintptr_t)token == unit_token || OURO_F(token, 0) != heads ||
	    maps == 0 || maps->tag != 0 || maps->n != 3 || OURO_F(maps, 0) != parent_maps || OURO_F(maps, 1) != caller ||
	    OURO_F(maps, 2) != wide || !packed(caller, (const unsigned char *)"invalid maps unit", 17) ||
	    !packed(OURO_F(kept, 13), binary, sizeof binary))
		return fail("invalid maps complete captures, unit prefix promotion or caller aliases changed");
	keys[0] = 0;
	for (index = 0; index < 3; index++)
		keys[index + 1] = OURO_F(payloads, index);
	for (index = 0; index < 4; index++)
		errors[index] = OURO_F(cases, index);
	if (raw == 0 || raw->tag != OURO_TAG_CLOS || partial == 0 || partial->tag != OURO_TAG_CLOS ||
	    body == 0 || body->tag != OURO_TAG_CLOS || sibling == 0 || sibling->tag != OURO_TAG_CLOS ||
	    borrowed == 0 || borrowed->tag != OURO_TAG_THUNK || cycle == 0 || cycle->tag != OURO_TAG_CLOS)
		return fail("invalid maps complete caller callable captures changed");
	raw_prefix = ouro_get(partial->u.c.env, 1);
	if (raw_prefix == 0 || raw_prefix->tag != OURO_TAG_CLOS)
		return fail("invalid maps promoted raw prefix is not a callable");
	if (keys[1] == 0 || keys[1]->tag != 0 || keys[1]->n != 0 || keys[2] != peano || keys[3] != fast ||
	    ouro_get(raw->u.c.env, 0) != maps || ouro_get(raw->u.c.env, 1) != borrowed ||
	    ouro_get(raw_prefix->u.c.env, 0) != heads || ouro_get(raw_prefix->u.c.env, 1) != token ||
	    ouro_get(body->u.c.env, 1) != borrowed || ouro_get(body->u.c.env, 2) != raw_prefix ||
	    ouro_get(sibling->u.c.env, 1) != borrowed || ouro_get(sibling->u.c.env, 2) != raw_prefix)
		return fail("invalid maps raw, sibling, partial or promoted capture aliases changed");
	ouro_perm_begin(); cursor = results;
	for (index = 0; index < 64; index++) {
		if (cursor == 0 || cursor->tag != 1 || cursor->n != 2 || !invalid_maps_result(OURO_F(cursor, 0), keys[index % 4])) {
			ouro_perm_end(); return fail("invalid maps all 64 complete Maybe survivors changed after outer leave");
		}
		cursor = OURO_F(cursor, 1);
	}
	refs = ouro_get(borrowed->u.c.env, 0);
	view = ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){borrowed});
	if (!nil(cursor) || view != refs || ouro_get(borrowed->u.c.env, 1) != maps || ouro_get(borrowed->u.c.env, 2) != cycle ||
	    ouro_case(ouro_ctor(0, 0, 0), 1, (ouro_v *[]){parent_branch}) != parent_maps) {
		ouro_perm_end(); return fail("invalid maps original unit or parent borrowed THUNK changed");
	}
	view = ouro_apply(cycle, ouro_ctor(0, 0, 0));
	if (view == 0 || view->tag != 0 || view->n != 2 || OURO_F(view, 0) != cycle || OURO_F(view, 1) != maps) {
		ouro_perm_end(); return fail("invalid maps retained caller self cycle changed");
	}
	for (index = 0; index < 4; index++)
		if (!invalid_maps_result(ouro_apply(body, errors[index]), keys[index]) ||
		    !invalid_maps_result(ouro_apply(sibling, errors[index]), keys[index])) {
			ouro_perm_end(); return fail("invalid maps complete partial or sibling reuse changed");
		}
	result = ouro_apply(ouro_apply(raw, heads), borrowed);
	result = ouro_apply(result, errors[1]);
	if (!invalid_maps_result(result, keys[1]) || !invalid_maps_result(ouro_apply(ouro_apply(partial, borrowed), errors[2]), peano) ||
	    !invalid_maps_result(OURO_F(OURO_F(results, 1), 0), keys[1]) || invalid_maps_failed) {
		ouro_perm_end(); return fail("invalid maps original raw, prefix partial or prior Just zero changed");
	}
	ouro_perm_end(); return 0;
}

ouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw);
ouro_v *ouro_wrap_module_lookup(ouro_v *raw);

static unsigned long lower_ctor_control_names, lower_ctor_control_lists;
static ouro_v *lower_ctor_control_name, *lower_ctor_control_list;

static ouro_v *lower_ctor_control_raw_list(ouro_env *env, ouro_v *list)
{
	lower_ctor_control_lists++;
	lower_ctor_control_name = ouro_get(env, 0);
	lower_ctor_control_list = list;
	return ouro_get(env, 1);
}

static ouro_v *lower_ctor_control_raw_name(ouro_env *env, ouro_v *name)
{
	lower_ctor_control_names++;
	return ouro_clos(lower_ctor_control_raw_list, ouro_cons(name, env));
}

static ouro_v *lower_ctor_control_info(ouro_v *name)
{
	return ouro_ctor(0, 6, (ouro_v *[]){name, ouro_nat(21), ouro_nat(22),
		ouro_nat(23), ouro_nat(24), ouro_nat(25)});
}

static ouro_v *lower_ctor_control_cons(ouro_v *info, ouro_v *tail)
{
	return ouro_ctor(1, 2, (ouro_v *[]){info, tail});
}

static ouro_v *lower_ctor_control_big(const uint32_t *words, unsigned long count)
{
	unsigned long size = (unsigned long)sizeof(ouro_v) + count * (unsigned long)sizeof(uint32_t);
	ouro_v *value = (ouro_v *)ouro_alloc(size);
	memset(value, 0, size);
	value->tag = OURO_TAG_BIG_NAT;
	value->n = (int)count;
	memcpy(value + 1, words, count * sizeof(uint32_t));
	return value;
}

static int lower_ctor_control_expect(ouro_v *partial, ouro_v *name, ouro_v *list,
	ouro_v *expected, int fallback, const char *label)
{
	unsigned long names = lower_ctor_control_names, lists = lower_ctor_control_lists;
	ouro_v *result = ouro_apply(partial, list);
	if (fallback) {
		if (result != expected || lower_ctor_control_names != names + 1 ||
		    lower_ctor_control_lists != lists + 1 || lower_ctor_control_name != name ||
		    lower_ctor_control_list != list)
			return fail(label);
	} else if (lower_ctor_control_names != names || lower_ctor_control_lists != lists ||
		   result == 0 || (expected == 0 ? !nil(result) :
		   result->tag != 1 || result->n != 1 || OURO_F(result, 0) != expected)) {
		return fail(label);
	}
	return 0;
}

static int lower_ctor_lookup_check(void)
{
	const uint32_t top_zero[2] = {7, 0}, zero_word[1] = {0}, small_word[1] = {7};
	const uint32_t wide_words[3] = {7, 0, 1};
	ouro_v *name = ouro_nat(7), *empty = ouro_ctor(0, 0, 0);
	ouro_v *returned = ouro_ctor(37, 0, 0);
	ouro_v *raw = ouro_clos(lower_ctor_control_raw_name, ouro_cons(returned, 0));
	ouro_v *wrapped = ouro_wrap_lower_ctor_lookup(raw), *partial = ouro_apply(wrapped, name);
	ouro_v *first = lower_ctor_control_info(ouro_nat(1));
	ouro_v *middle = lower_ctor_control_info(name), *duplicate = lower_ctor_control_info(ouro_nat(7));
	ouro_v *last = lower_ctor_control_info(ouro_nat(9));
	ouro_v *list = lower_ctor_control_cons(first,
		lower_ctor_control_cons(middle, lower_ctor_control_cons(last, empty)));
	ouro_v *poison = ouro_ctor(0, 6, (ouro_v *[]){name, 0, 0, 0, 0, 0});
	ouro_v *zero = ouro_nat(0), *zero_info = lower_ctor_control_info(zero);
	ouro_v *high = ouro_nat_u64(UINT64_C(0xffffffff)), *high_info = lower_ctor_control_info(high);
	ouro_v *huge = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	ouro_v *huge_info = lower_ctor_control_info(huge);
	ouro_v *unsupported[7], *bad_lists[9], *cursor, *result, *child_partial, *kept;
	ouro_heap_context *child;
	unsigned long index, names, lists, mark_n, mark_used, actual_n, actual_used;
	int error = 0, huge_fallback = ULONG_MAX < UINT64_C(0xfedcba9876543210);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS ||
	    lower_ctor_control_names != 0 || lower_ctor_control_lists != 0)
		return fail("lower ctor lookup evaluated raw before saturation");
	if (lower_ctor_control_expect(partial, name, lower_ctor_control_cons(middle, empty), middle, 0,
		"lower ctor lookup first original row") ||
	    lower_ctor_control_expect(partial, name, list, middle, 0, "lower ctor lookup middle original row") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, ouro_nat(99)), ouro_nat(99), list, 0, 0,
		"lower ctor lookup proper miss") ||
	    lower_ctor_control_expect(partial, name, empty, 0, 0, "lower ctor lookup empty list") ||
	    lower_ctor_control_expect(partial, name, lower_ctor_control_cons(middle,
		lower_ctor_control_cons(duplicate, empty)), middle, 0, "lower ctor lookup first duplicate row") ||
	    lower_ctor_control_expect(partial, name, lower_ctor_control_cons(poison, ouro_ctor(23, 0, 0)), poison, 0,
		"lower ctor lookup hit before bad fields and tail") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, zero), zero, lower_ctor_control_cons(zero_info, empty),
		zero_info, 0, "lower ctor lookup packed zero") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, ouro_nat_u64(UINT64_C(0xffffffff))), high,
		lower_ctor_control_cons(high_info, empty), high_info, 0, "lower ctor lookup canonical 32-bit Nat") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, lower_ctor_control_big(small_word, 1)), name,
		list, middle, 0, "lower ctor lookup one nonzero limb") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, huge), huge, lower_ctor_control_cons(huge_info, empty),
		huge_fallback ? returned : huge_info, huge_fallback, "lower ctor lookup host width query") ||
	    lower_ctor_control_expect(partial, name, lower_ctor_control_cons(huge_info, list),
		huge_fallback ? returned : middle, huge_fallback, "lower ctor lookup host width row"))
		return 1;
	unsupported[0] = lower_ctor_control_big(top_zero, 2);
	unsupported[1] = lower_ctor_control_big(zero_word, 1);
	unsupported[2] = ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(6)});
	unsupported[3] = ouro_ctor(0, 0, 0);
	unsupported[4] = lower_ctor_control_big(wide_words, 3);
	unsupported[5] = ouro_ctor(23, 0, 0);
	unsupported[6] = 0;
	for (index = 0; index < sizeof unsupported / sizeof unsupported[0]; index++) {
		if (lower_ctor_control_expect(ouro_apply(wrapped, unsupported[index]), unsupported[index], list,
			returned, 1, "lower ctor lookup unsupported query complete fallback"))
			return 1;
		cursor = lower_ctor_control_cons(first,
			lower_ctor_control_cons(lower_ctor_control_info(unsupported[index]), list));
		if (lower_ctor_control_expect(partial, name, cursor, returned, 1,
			"lower ctor lookup unsupported row complete fallback"))
			return 1;
	}
	bad_lists[0] = 0;
	bad_lists[1] = ouro_ctor(23, 0, 0);
	bad_lists[2] = ouro_ctor(1, 1, (ouro_v *[]){middle});
	bad_lists[3] = lower_ctor_control_cons(ouro_ctor(0, 5,
		(ouro_v *[]){name, 0, 0, 0, 0}), list);
	bad_lists[4] = lower_ctor_control_cons(ouro_ctor(1, 6,
		(ouro_v *[]){name, 0, 0, 0, 0, 0}), list);
	bad_lists[5] = lower_ctor_control_cons(0, list);
	bad_lists[6] = ouro_ctor(OURO_TAG_CAT, 2, (ouro_v *[]){list, list});
	bad_lists[7] = lower_ctor_control_cons(first, 0);
	bad_lists[8] = lower_ctor_control_cons(first, ouro_ctor(23, 0, 0));
	for (index = 0; index < sizeof bad_lists / sizeof bad_lists[0]; index++)
		if (lower_ctor_control_expect(partial, name, bad_lists[index], returned, 1,
			"lower ctor lookup malformed list complete fallback"))
			return 1;
	lower_ctor_control_name = lower_ctor_control_list = 0;
	ouro_heap_mark_save(&mark_n, &mark_used);
	child = ouro_heap_context_enter();
	names = lower_ctor_control_names; lists = lower_ctor_control_lists;
	child_partial = ouro_apply(wrapped, name);
	if (child_partial == 0 || child_partial->tag != OURO_TAG_CLOS ||
	    lower_ctor_control_names != names || lower_ctor_control_lists != lists ||
	    lower_ctor_control_expect(child_partial, name, list, middle, 0,
		"lower ctor lookup child partial borrowed row")) {
		error = fail("lower ctor lookup child partial evaluated raw or changed caller row");
		goto leave_child;
	}
	result = ouro_apply(child_partial, list);
	if (result == 0 || result->tag != 1 || result->n != 1 || OURO_F(result, 0) != middle) {
		error = fail("lower ctor lookup child result changed caller pointer");
		goto leave_child;
	}
	cursor = lower_ctor_control_cons(first, 0);
	if (lower_ctor_control_expect(child_partial, name, cursor, returned, 1,
		"lower ctor lookup child complete fallback")) {
		error = 1;
		goto leave_child;
	}
	lower_ctor_control_name = lower_ctor_control_list = 0;
	kept = ouro_heap_context_leave(child, ouro_ctor(0, 2, (ouro_v *[]){result, child_partial}));
	memset(ouro_alloc(4096), 0xA5, 4096);
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used || kept == 0 || kept->tag != 0 || kept->n != 2 ||
	    OURO_F(kept, 0) == 0 || OURO_F(kept, 0)->tag != 1 || OURO_F(kept, 0)->n != 1 ||
	    OURO_F(OURO_F(kept, 0), 0) != middle || OURO_F(middle, 0) != name ||
	    !nat_is(OURO_F(middle, 1), 21) || !nat_is(OURO_F(middle, 5), 25) ||
	    lower_ctor_control_expect(partial, name, list, middle, 0,
		"lower ctor lookup parent partial after child leave") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, list, middle, 0,
		"lower ctor lookup retained child partial") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, bad_lists[7], returned, 1,
		"lower ctor lookup retained raw capture complete fallback"))
		error = fail("lower ctor lookup child leave, complete survivor or caller identity");
	lower_ctor_control_name = lower_ctor_control_list = 0;
	return error;
leave_child:
	lower_ctor_control_name = lower_ctor_control_list = 0;
	(void)ouro_heap_context_leave(child, 0);
	return error;
}

static ouro_v *module_lookup_control_pair(ouro_v *name, ouro_v *payload)
{
	return ouro_ctor(0, 2, (ouro_v *[]){name, payload});
}

static int module_lookup_check(void)
{
	const uint32_t top_zero[2] = {7, 0}, zero_word[1] = {0}, small_word[1] = {7};
	const uint32_t wide_words[3] = {7, 0, 1};
	ouro_v *name = ouro_nat(7), *empty = ouro_ctor(0, 0, 0);
	ouro_v *returned = ouro_ctor(37, 0, 0), *payload = lower_ctor_control_big(wide_words, 3);
	ouro_v *raw = ouro_clos(lower_ctor_control_raw_name, ouro_cons(returned, 0));
	ouro_v *wrapped, *partial;
	ouro_v *first = module_lookup_control_pair(ouro_nat(1), ouro_nat(11));
	ouro_v *middle = module_lookup_control_pair(name, payload);
	ouro_v *duplicate = module_lookup_control_pair(ouro_nat(7), ouro_nat(22));
	ouro_v *list = lower_ctor_control_cons(first, lower_ctor_control_cons(middle, empty));
	ouro_v *high = ouro_nat_u64(UINT64_C(0xffffffff));
	ouro_v *huge = ouro_nat_u64(UINT64_C(0xfedcba9876543210));
	ouro_v *unsupported[8], *bad_lists[9], *cursor, *result, *child_partial, *kept;
	ouro_heap_context *child;
	unsigned long index, names, lists, mark_n, mark_used, actual_n, actual_used;
	int error = 0, huge_fallback = ULONG_MAX < UINT64_C(0xfedcba9876543210);
	lower_ctor_control_names = lower_ctor_control_lists = 0;
	wrapped = ouro_wrap_module_lookup(raw);
	partial = ouro_apply(wrapped, name);
	if (partial == 0 || partial->tag != OURO_TAG_CLOS ||
	    lower_ctor_control_names != 0 || lower_ctor_control_lists != 0)
		return fail("module lookup partial is not a closure");
	if (lower_ctor_control_expect(partial, name, lower_ctor_control_cons(middle, empty), payload, 0,
		"module lookup first original payload") ||
	    lower_ctor_control_expect(partial, name, list, payload, 0, "module lookup tail original payload") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, ouro_nat(99)), ouro_nat(99), list, 0, 0,
		"module lookup proper miss") ||
	    lower_ctor_control_expect(partial, name, empty, 0, 0, "module lookup empty list") ||
	    lower_ctor_control_expect(partial, name, lower_ctor_control_cons(middle,
		lower_ctor_control_cons(duplicate, empty)), payload, 0, "module lookup first duplicate") ||
	    lower_ctor_control_expect(partial, name, lower_ctor_control_cons(middle, 0), payload, 0,
		"module lookup hit before malformed tail") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, ouro_nat(0)), ouro_nat(0),
		lower_ctor_control_cons(module_lookup_control_pair(ouro_nat(0), payload), empty), payload, 0,
		"module lookup zero key") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, high), high,
		lower_ctor_control_cons(module_lookup_control_pair(high, payload), empty), payload, 0,
		"module lookup canonical 32-bit key") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, lower_ctor_control_big(small_word, 1)), name,
		list, payload, 0, "module lookup one nonzero limb") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, huge), huge,
		lower_ctor_control_cons(module_lookup_control_pair(huge, payload), empty),
		huge_fallback ? returned : payload, huge_fallback, "module lookup host width query") ||
	    lower_ctor_control_expect(partial, name,
		lower_ctor_control_cons(module_lookup_control_pair(huge, payload), list),
		huge_fallback ? returned : payload, huge_fallback, "module lookup host width row"))
		return 1;
	result = ouro_apply(partial, lower_ctor_control_cons(module_lookup_control_pair(name, 0), 0));
	if (result == 0 || result->tag != 1 || result->n != 1 || OURO_F(result, 0) != 0 ||
	    lower_ctor_control_names != 2 * (unsigned long)huge_fallback)
		return fail("module lookup inspected opaque payload or hit tail");
	unsupported[0] = lower_ctor_control_big(top_zero, 2);
	unsupported[1] = lower_ctor_control_big(zero_word, 1);
	unsupported[2] = ouro_ctor(1, 1, (ouro_v *[]){ouro_nat(6)});
	unsupported[3] = ouro_ctor(0, 0, 0);
	unsupported[4] = lower_ctor_control_big(wide_words, 3);
	unsupported[5] = ouro_ctor(23, 0, 0);
	unsupported[6] = 0;
	unsupported[7] = ouro_ctor(OURO_TAG_NAT, 0, 0);
	unsupported[7]->n = -1;
	for (index = 0; index < sizeof unsupported / sizeof unsupported[0]; index++) {
		if (lower_ctor_control_expect(ouro_apply(wrapped, unsupported[index]), unsupported[index], list,
			returned, 1, "module lookup unsupported query complete fallback"))
			return 1;
		cursor = lower_ctor_control_cons(first,
			lower_ctor_control_cons(module_lookup_control_pair(unsupported[index], payload), list));
		if (lower_ctor_control_expect(partial, name, cursor, returned, 1,
			"module lookup unsupported row complete fallback"))
			return 1;
	}
	bad_lists[0] = 0;
	bad_lists[1] = ouro_ctor(23, 0, 0);
	bad_lists[2] = ouro_ctor(1, 1, (ouro_v *[]){middle});
	bad_lists[3] = lower_ctor_control_cons(ouro_ctor(0, 1, (ouro_v *[]){name}), list);
	bad_lists[4] = lower_ctor_control_cons(ouro_ctor(1, 2, (ouro_v *[]){name, payload}), list);
	bad_lists[5] = lower_ctor_control_cons(0, list);
	bad_lists[6] = ouro_ctor(OURO_TAG_CAT, 2, (ouro_v *[]){list, list});
	bad_lists[7] = lower_ctor_control_cons(first, 0);
	bad_lists[8] = lower_ctor_control_cons(first, ouro_ctor(23, 0, 0));
	for (index = 0; index < sizeof bad_lists / sizeof bad_lists[0]; index++)
		if (lower_ctor_control_expect(partial, name, bad_lists[index], returned, 1,
			"module lookup malformed list complete fallback"))
			return 1;
	lower_ctor_control_name = lower_ctor_control_list = 0;
	ouro_heap_mark_save(&mark_n, &mark_used);
	child = ouro_heap_context_enter();
	names = lower_ctor_control_names; lists = lower_ctor_control_lists;
	child_partial = ouro_apply(wrapped, name);
	result = ouro_apply(child_partial, list);
	if (result == 0 || result->tag != 1 || result->n != 1 || OURO_F(result, 0) != payload ||
	    lower_ctor_control_names != names || lower_ctor_control_lists != lists) {
		error = fail("module lookup child partial changed borrowed payload");
		goto leave_module_child;
	}
	kept = ouro_heap_context_leave(child, ouro_ctor(0, 2, (ouro_v *[]){result, child_partial}));
	memset(ouro_alloc(4096), 0xA5, 4096);
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used || kept == 0 || kept->tag != 0 || kept->n != 2 ||
	    OURO_F(kept, 0) == 0 || OURO_F(kept, 0)->tag != 1 || OURO_F(kept, 0)->n != 1 ||
	    OURO_F(OURO_F(kept, 0), 0) != payload || OURO_F(middle, 0) != name || OURO_F(middle, 1) != payload ||
	    lower_ctor_control_expect(partial, name, list, payload, 0, "module lookup parent after child leave") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, list, payload, 0, "module lookup retained partial") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, bad_lists[7], returned, 1,
		"module lookup retained raw complete fallback"))
		error = fail("module lookup survivor or caller identity");
	lower_ctor_control_name = lower_ctor_control_list = 0;
	return error;
leave_module_child:
	lower_ctor_control_name = lower_ctor_control_list = 0;
	(void)ouro_heap_context_leave(child, 0);
	return error;
}

static int lower_local_lookup_payload_check(void)
{
	ouro_v *name = ouro_nat(7), *empty = ouro_ctor(0, 0, 0);
	ouro_v *zero = ouro_nat(0), *one = ouro_nat(1);
	ouro_v *first = ouro_ctor(1, 1, &zero), *second = ouro_ctor(0, 1, &name);
	ouro_v *returned = ouro_ctor(37, 0, 0);
	ouro_v *raw = ouro_clos(lower_ctor_control_raw_name, ouro_cons(returned, 0));
	ouro_v *wrapped = ouro_wrap_module_lookup(raw), *partial = ouro_apply(wrapped, name);
	ouro_v *list = lower_ctor_control_cons(module_lookup_control_pair(name, first),
		lower_ctor_control_cons(module_lookup_control_pair(name, second), empty));
	ouro_v *other = lower_ctor_control_cons(module_lookup_control_pair(name, second), empty);
	ouro_v *child_payload, *child_list, *result, *kept, *child_partial, *payload;
	ouro_heap_context *child;
	unsigned long names, lists, mark_n, mark_used, actual_n, actual_used;
	int error = 0;
	lower_ctor_control_names = lower_ctor_control_lists = 0;
	if (lower_ctor_control_expect(partial, name, list, first, 0, "lower local first shadowing payload") ||
	    lower_ctor_control_expect(partial, name, other, second, 0, "lower local changed list payload") ||
	    lower_ctor_control_expect(partial, name, list, first, 0, "lower local earlier list payload") ||
	    lower_ctor_control_expect(partial, name, empty, 0, 0, "lower local empty list") ||
	    lower_ctor_control_expect(ouro_apply(wrapped, one), one, list, 0, 0, "lower local missing key"))
		return 1;
	ouro_heap_mark_save(&mark_n, &mark_used);
	child = ouro_heap_context_enter();
	names = lower_ctor_control_names; lists = lower_ctor_control_lists;
	child_payload = ouro_ctor(4, 2, (ouro_v *[]){ouro_ctor(1, 1, &one), second});
	child_list = lower_ctor_control_cons(module_lookup_control_pair(name, child_payload), empty);
	child_partial = ouro_apply(wrapped, name);
	result = ouro_apply(child_partial, child_list);
	if (result == 0 || result->tag != 1 || result->n != 1 || OURO_F(result, 0) != child_payload ||
	    lower_ctor_control_names != names || lower_ctor_control_lists != lists) {
		error = fail("lower local child Surface payload changed before leave");
		goto leave_lower_local_child;
	}
	kept = ouro_heap_context_leave(child, ouro_ctor(0, 2, (ouro_v *[]){result, child_partial}));
	memset(ouro_alloc(4096), 0xA5, 4096);
	ouro_heap_mark_save(&actual_n, &actual_used);
	if (actual_n != mark_n || actual_used != mark_used || kept == 0 || kept->tag != 0 || kept->n != 2 ||
	    OURO_F(kept, 0) == 0 || OURO_F(kept, 0)->tag != 1 || OURO_F(kept, 0)->n != 1)
		return fail("lower local child Surface result did not survive leave");
	payload = OURO_F(OURO_F(kept, 0), 0);
	if (payload == 0 || payload->tag != 4 || payload->n != 2 || OURO_F(payload, 1) != second ||
	    OURO_F(payload, 0) == 0 || OURO_F(payload, 0)->tag != 1 || OURO_F(payload, 0)->n != 1 ||
	    !nat_is(OURO_F(OURO_F(payload, 0), 0), 1) ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, list, first, 0,
		"lower local retained partial earlier list") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name, other, second, 0,
		"lower local retained partial changed list") ||
	    lower_ctor_control_expect(OURO_F(kept, 1), name,
		lower_ctor_control_cons(module_lookup_control_pair(ouro_ctor(0, 0, 0), first), list),
		returned, 1, "lower local retained raw complete fallback"))
		error = fail("lower local Surface survivor or retained partial changed");
	lower_ctor_control_name = lower_ctor_control_list = 0;
	return error;
leave_lower_local_child:
	lower_ctor_control_name = lower_ctor_control_list = 0;
	(void)ouro_heap_context_leave(child, 0);
	return error;
}

int main(int argc, char **argv)
{
	const char *mode;
	int result = 0;
	ouro_rt_warmup();
	if (argc != 2)
		return 2;
	mode = argv[1];
	if (strcmp(mode, "prefix2") == 0 || strcmp(mode, "prefix3") == 0) {
		unsigned long prefix = mode[6] == '2' ? 2 : 3;
		result = prefix_scope_check(prefix, 0);
		if (result == 0)
			result = prefix_scope_check(prefix, 1);
		if (result == 0 && prefix == 3)
			result = prefix_nested_scope_check(0);
		if (result == 0 && prefix == 3)
			result = prefix_nested_scope_check(1);
		if (result == 0)
			result = body2_nested_scope_check(prefix, 0);
		if (result == 0)
			result = body2_nested_scope_check(prefix, 1);
		if (result == 0)
			printf("MODULE_PURE_SCOPE_SELFTEST: passed %s\n", mode);
		return result;
	}
	if (strcmp(mode, "extended") == 0 || strcmp(mode, "thunk-cycle") == 0 ||
	    strcmp(mode, "outer-mark") == 0 || strcmp(mode, "perm0") == 0) {
		if (strcmp(mode, "extended") == 0 || strcmp(mode, "thunk-cycle") == 0)
			result = thunk_cycle_check();
		if (result == 0 && (strcmp(mode, "extended") == 0 || strcmp(mode, "outer-mark") == 0))
			result = outer_mark_check();
		if (result == 0 && (strcmp(mode, "extended") == 0 || strcmp(mode, "perm0") == 0))
			result = permanent_zero_check();
		if (result == 0)
			printf("MODULE_PURE_SCOPE_SELFTEST: passed %s\n", mode);
		return result;
	}
	if (strcmp(mode, "invalid-arity0") == 0 || strcmp(mode, "invalid-arity4") == 0 ||
	    strcmp(mode, "invalid-arity8") == 0) {
		unsigned long arity = mode[13] == '0' ? 0 : mode[13] == '4' ? 4 : 8;
		(void)ouro_wrap_module_pure_scope(ouro_clos(one, 0), arity);
		return fail("invalid arity accepted");
	}
	if (strcmp(mode, "all") == 0 || strcmp(mode, "order") == 0)
		result = order_check(1) || order_check(2) || order_check(7);
	if (result == 0 && (strcmp(mode, "all") == 0 || strcmp(mode, "survivors") == 0))
		result = survivor_check();
	if (result == 0 && (strcmp(mode, "all") == 0 || strcmp(mode, "allocation") == 0))
		result = allocation_check();
	if (result == 0 && strcmp(mode, "all") == 0)
		result = invalid_maps_scope_check(0) || invalid_maps_scope_check(1) ||
			lower_ctor_lookup_check() || module_lookup_check() || lower_local_lookup_payload_check() ||
			source_name_compare_scope_check() ||
			order_check(3) || elem_scope_check();
	if (strcmp(mode, "all") != 0 && strcmp(mode, "order") != 0 &&
	    strcmp(mode, "survivors") != 0 && strcmp(mode, "allocation") != 0)
		return 2;
	if (result == 0)
		printf("MODULE_PURE_SCOPE_SELFTEST: passed %s\n", mode);
	return result;
}
