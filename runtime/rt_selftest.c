/* Hand-written fixture for the calling convention of samples/examples/nat.ouro.
   It covers environment indices, recursive closures and global caches.
   Global caches require static storage because ouro_app can reclaim a
   newly allocated phase closure on its first call. */
#include "ouro_rt.h"

#include <stdio.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

static ouro_v *ouro_g_Z(void);
static ouro_v *ouro_g_S(void);
static ouro_v *ouro_g_add(void);
static ouro_v *ouro_g_two(void);
static ouro_v *ouro_g_four(void);

/* Z = JCtor 0 [] */
static ouro_v *ouro_c_Z;
static ouro_v *ouro_g_Z(void)
{
	if (ouro_c_Z == 0) {
		ouro_static_begin();
		ouro_c_Z = ouro_ctor(0, 0, 0);
		ouro_static_end();
	}
	return ouro_c_Z;
}

/* S = JLam a0 (JCtor 1 [a0]); env inside: [a0] */
static ouro_v *ouro_f_S(ouro_env *env, ouro_v *arg)
{
	ouro_env *e = ouro_cons(arg, env);
	return ouro_ctor(1, 1, (ouro_v *[]){ouro_get(e, 0)});
}

static ouro_v *ouro_c_S;
static ouro_v *ouro_g_S(void)
{
	if (ouro_c_S == 0) {
		ouro_static_begin();
		ouro_c_S = ouro_clos(ouro_f_S, 0);
		ouro_static_end();
	}
	return ouro_c_S;
}

/* add = JFix self [v5, v6] (JSwitch (JVar v5) [0,1] [JVar v6, JLam v7 ...])
   env inside the fix body: [v6, v5, self]
   env inside branch 1:     [v7, v6, v5, self] */
static ouro_v *ouro_f_add_1(ouro_env *env, ouro_v *arg);
static ouro_v *ouro_sw_add(ouro_env *env, ouro_v *s);

static ouro_v *ouro_f_add_0(ouro_env *env, ouro_v *arg)
{
	ouro_env *e = ouro_cons(arg, env);
	return ouro_clos(ouro_f_add_1, e);
}

static ouro_v *ouro_f_add_1(ouro_env *env, ouro_v *arg)
{
	ouro_env *e = ouro_cons(arg, env);
	return ouro_sw_add(e, ouro_get(e, 1));
}

static ouro_v *ouro_sw_add(ouro_env *env, ouro_v *s)
{
	switch (s->tag) {
	case 0:
		return ouro_get(env, 0);
	case 1: {
		ouro_env *e = ouro_cons(OURO_F(s, 0), env);
		return ouro_app(ouro_g_S(),
			ouro_app(ouro_app(ouro_get(e, 3), ouro_get(e, 0)),
				ouro_get(e, 1)));
	}
	default:
		return ouro_err(0);
	}
}

static ouro_v *ouro_c_add;
static ouro_v *ouro_g_add(void)
{
	if (ouro_c_add == 0) {
		ouro_static_begin();
		ouro_c_add = ouro_fix(ouro_f_add_0, 0);
		ouro_static_end();
	}
	return ouro_c_add;
}

/* two = S (S Z) */
static ouro_v *ouro_c_two;
static ouro_v *ouro_g_two(void)
{
	if (ouro_c_two == 0) {
		ouro_static_begin();
		ouro_c_two = ouro_app(ouro_g_S(), ouro_app(ouro_g_S(), ouro_g_Z()));
		ouro_static_end();
	}
	return ouro_c_two;
}

/* four = add two two */
static ouro_v *ouro_c_four;
static ouro_v *ouro_g_four(void)
{
	if (ouro_c_four == 0) {
		ouro_static_begin();
		ouro_c_four = ouro_app(ouro_app(ouro_g_add(), ouro_g_two()),
			ouro_g_two());
		ouro_static_end();
	}
	return ouro_c_four;
}

/* Phase-heap shape of a compiled expression: `add two two` evaluated outside
   any cache. The partial application `add two` is a fresh closure that
   ouro_app consumes, so the phase heap must not grow by that cell, and the
   result must still be S (S (S (S Z))). */
static unsigned long nat_depth(ouro_v *v)
{
	unsigned long depth = 0;
	while (v != 0 && v->tag == 1 && v->n == 1) {
		depth++;
		v = OURO_F(v, 0);
	}
	if (v == 0 || v->tag != 0 || v->n != 0) {
		fputs("rt_selftest: not a Peano nat\n", stderr);
		exit(1);
	}
	return depth;
}

static void check_phase_apply(void)
{
	unsigned long long before;
	unsigned long long reclaimed_before;
	ouro_v *sum;
	ouro_v *add_two;
	ouro_v *four;
	/* Prime the caches so the measured region contains only the evaluation. */
	(void)ouro_g_four();
	before = ouro_heap_total_alloc_bytes();
	reclaimed_before = ouro_heap_reclaimed_bytes();
	sum = ouro_app(ouro_app(ouro_g_add(), ouro_g_two()), ouro_g_two());
	if (nat_depth(sum) != 4) {
		fputs("rt_selftest: add two two /= four\n", stderr);
		exit(1);
	}
	if (ouro_heap_reclaimed_bytes() == reclaimed_before) {
		fputs("rt_selftest: partial application was not reclaimed\n", stderr);
		exit(1);
	}
	/* A closure kept by the host must survive repeated ouro_apply, even
	   though it is the newest phase cell when first applied. */
	add_two = ouro_apply(ouro_g_add(), ouro_g_two());
	four = ouro_apply(add_two, ouro_g_two());
	sum = ouro_apply(add_two, four);
	if (nat_depth(sum) != 6) {
		fputs("rt_selftest: ouro_apply reuse failed\n", stderr);
		exit(1);
	}
	if (ouro_heap_total_alloc_bytes() <= before) {
		fputs("rt_selftest: allocation counter did not advance\n", stderr);
		exit(1);
	}
}

static ouro_v *pair_second(ouro_env *env, ouro_v *b)
{
	return ouro_ctor(9, 2, (ouro_v *[]){env->v, b});
}

static ouro_v *pair_first(ouro_env *env, ouro_v *a)
{
	(void)env;
	return ouro_clos(pair_second, ouro_cons(a, 0));
}

static ouro_v *discard_temps(ouro_env *env, ouro_v *arg)
{
	ouro_v *junk = 0;
	int i;
	(void)env;
	for (i = 0; i < 8; i++)
		junk = ouro_ctor(20, 2, (ouro_v *[]){arg, arg});
	(void)junk;
	return ouro_ctor(4, 2, (ouro_v *[]){arg, arg});
}

static void check_call_env_reclaim(void)
{
	unsigned long long reclaimed_before;
	ouro_v *left = ouro_nat(3);
	ouro_v *right = ouro_nat(5);
	ouro_v *pair;
	ouro_v *compact;
	reclaimed_before = ouro_heap_reclaimed_bytes();
	pair = ouro_app(ouro_app(ouro_clos(pair_first, 0), left), right);
	if (pair == 0 || pair->tag != 9 || pair->n != 2 ||
	    OURO_F(pair, 0) != left || OURO_F(pair, 1) != right) {
		fputs("rt_selftest: curried pair result\n", stderr);
		exit(1);
	}
	if (ouro_heap_reclaimed_bytes() < reclaimed_before + sizeof(ouro_env)) {
		fputs("rt_selftest: curry env spine was not reclaimed\n", stderr);
		exit(1);
	}
	reclaimed_before = ouro_heap_reclaimed_bytes();
	compact = ouro_app(ouro_clos(discard_temps, 0), left);
	if (compact == 0 || compact->tag != 4 || compact->n != 2 ||
	    OURO_F(compact, 0) != left || OURO_F(compact, 1) != left) {
		fputs("rt_selftest: compacted constructor result\n", stderr);
		exit(1);
	}
	if (ouro_heap_reclaimed_bytes() < reclaimed_before + 8UL * sizeof(ouro_v)) {
		fputs("rt_selftest: call-frame temporaries were not evacuated\n", stderr);
		exit(1);
	}
}

static ouro_v *shared_pair_third(ouro_env *env0, ouro_v *arg)
{
	ouro_env *env = ouro_cons(arg, env0);
	return ouro_ctor(9, 2, (ouro_v *[]){ouro_get(env, 2), ouro_get(env, 1)});
}

static ouro_v *shared_pair_second(ouro_env *env0, ouro_v *arg)
{
	ouro_env *env = ouro_cons(arg, env0);
	return ouro_clos(shared_pair_third, env);
}

static ouro_v *shared_pair_first(ouro_env *env0, ouro_v *arg)
{
	ouro_env *env = ouro_cons(arg, env0);
	return ouro_clos(shared_pair_second, env);
}

static int pair_matches(ouro_v *value, ouro_v *left, ouro_v *right)
{
	return value != 0 && value->tag == 9 && value->n == 2 &&
		OURO_F(value, 0) == left && OURO_F(value, 1) == right;
}

static void check_cloned_call_env(void)
{
	ouro_v *a = ouro_nat(3), *b = ouro_nat(5), *c = ouro_nat(7);
	ouro_v *d = ouro_nat(11), *e = ouro_nat(13);
	ouro_v *caller = ouro_ctor(9, 2, (ouro_v *[]){a, b});
	unsigned long saved_n, saved_used, mark_n, mark_used, after_n, after_used;
	int generated;
	ouro_heap_mark_save(&saved_n, &saved_used);
	ouro_heap_mark();
	ouro_heap_mark_save(&mark_n, &mark_used);
	for (generated = 0; generated < 2; generated++) {
		ouro_heap_context *context = ouro_heap_context_enter();
		ouro_v *partial = ouro_app(ouro_clos(shared_pair_first, 0), a);
		ouro_v *sibling, *bundle, *result, *sibling_result;
		ouro_env *shared_env;
		if (partial->n != 1) {
			fputs("rt_selftest: shared partial curry hint missing\n", stderr);
			exit(1);
		}
		sibling = ouro_apply(partial, b);
		bundle = ouro_heap_context_leave(context,
			ouro_ctor(9, 2, (ouro_v *[]){sibling, partial}));
		sibling = OURO_F(bundle, 0);
		partial = OURO_F(bundle, 1);
		if (partial == 0 || sibling == 0 || partial->tag != OURO_TAG_CLOS ||
		    sibling->tag != OURO_TAG_CLOS || partial->u.c.env == 0 ||
		    sibling->u.c.env == 0 || sibling->u.c.env->next != partial->u.c.env ||
		    ouro_get(partial->u.c.env, 0) != a || ouro_get(sibling->u.c.env, 0) != b ||
		    ouro_alloc(0) != (void *)((unsigned char *)partial + sizeof *partial)) {
			fputs("rt_selftest: cloned partial shared capture or phase position\n", stderr);
			exit(1);
		}
		shared_env = partial->u.c.env;
		/* Clone can put partial on top while sibling still owns its env. Fail
		   before ouro_app can rewind that shared capture with a copied hint. */
		if (generated && partial->n != 0) {
			fputs("rt_selftest: cloned partial retained exclusive env hint\n", stderr);
			exit(1);
		}
		result = generated ? ouro_app(ouro_app(partial, c), d)
			: ouro_apply(ouro_apply(partial, c), d);
		if (!pair_matches(result, a, c) || sibling->u.c.env->next != shared_env ||
		    ouro_get(sibling->u.c.env, 1) != a) {
			fputs("rt_selftest: cloned partial result or sibling capture\n", stderr);
			exit(1);
		}
		sibling_result = ouro_apply(sibling, e);
		if (!pair_matches(sibling_result, a, b) || !pair_matches(result, a, c) ||
		    !pair_matches(caller, a, b)) {
			fputs("rt_selftest: cloned partial released a retained result\n", stderr);
			exit(1);
		}
		ouro_heap_mark_save(&after_n, &after_used);
		if (after_n != mark_n || after_used != mark_used) {
			fputs("rt_selftest: cloned partial changed the caller mark\n", stderr);
			exit(1);
		}
	}
	ouro_heap_mark_restore(saved_n, saved_used);
}

static ouro_v *null_result(ouro_env *env0, ouro_v *arg)
{
	ouro_env *env = ouro_cons(arg, env0);
	(void)ouro_ctor(9, 1, (ouro_v *[]){ouro_get(env, 0)});
	return 0;
}

static void check_null_call_env(void)
{
	ouro_v *left = ouro_nat(3), *right = ouro_nat(5);
	ouro_v *caller = ouro_ctor(9, 2, (ouro_v *[]){left, right});
	ouro_v *result;
	ouro_env *capture;
	ouro_heap_context *context;
	unsigned long saved_n, saved_used, mark_n, mark_used, after_n, after_used;
	unsigned long long live_before, allocated_before;
	void *bump;
	ouro_heap_mark_save(&saved_n, &saved_used);
	context = ouro_heap_context_enter();
	capture = ouro_cons(caller, 0);
	ouro_heap_mark();
	ouro_heap_mark_save(&mark_n, &mark_used);
	live_before = ouro_heap_live_bytes();
	allocated_before = ouro_heap_total_alloc_bytes();
	bump = ouro_alloc(0);
	result = ouro_app(ouro_clos(null_result, capture), caller);
	if (result != 0 || ouro_alloc(0) != bump || ouro_heap_live_bytes() != live_before ||
	    ouro_heap_total_alloc_bytes() - allocated_before != 2UL * sizeof(ouro_v) + sizeof(ouro_env) ||
	    ouro_get(capture, 0) != caller || !pair_matches(caller, left, right)) {
		fputs("rt_selftest: null callback result, rewind or caller state\n", stderr);
		exit(1);
	}
	ouro_heap_mark_save(&after_n, &after_used);
	if (after_n != mark_n || after_used != mark_used) {
		fputs("rt_selftest: null callback changed the caller mark\n", stderr);
		exit(1);
	}
	(void)ouro_heap_context_leave(context, 0);
	ouro_heap_mark_save(&after_n, &after_used);
	if (after_n != saved_n || after_used != saved_used || !pair_matches(caller, left, right)) {
		fputs("rt_selftest: null callback context changed its caller\n", stderr);
		exit(1);
	}
}

static ouro_v *append_list(ouro_v *left, ouro_v *right)
{
	return ouro_apply(ouro_apply(ouro_fast("append"), left), right);
}

static void check_list_lookup(void)
{
	static const unsigned char codes[] = {0, 128, 255};
	ouro_v *nil = ouro_ctor(0, 0, 0);
	ouro_v *plain = ouro_bytes(codes, sizeof(codes));
	ouro_v *packed = ouro_packed(codes, sizeof(codes));
	ouro_v *lists[] = {
		plain, packed, append_list(plain, packed),
		append_list(append_list(packed, plain), packed),
		append_list(nil, packed), append_list(plain, nil)
	};
	static const unsigned long lengths[] = {3, 3, 6, 9, 3, 3};
	size_t i;
	for (i = 0; i < sizeof(lists) / sizeof(lists[0]); i++) {
		unsigned long j;
		for (j = 0; j < lengths[i]; j++) {
			unsigned char code = codes[j % sizeof(codes)];
			ouro_v *found = ouro_apply(ouro_apply(ouro_fast("memNat"),
				ouro_nat(code)), lists[i]);
			ouro_v *at = ouro_apply(ouro_apply(ouro_fast("nth"), lists[i]),
				ouro_nat(j));
			if (found == 0 || found->tag != 0 || found->n != 0 ||
			    at == 0 || at->tag != 1 || at->n != 1 ||
			    OURO_F(at, 0)->tag != OURO_TAG_NAT ||
			    OURO_F(at, 0)->n != code) {
				fprintf(stderr, "rt_selftest: list lookup shape=%lu index=%lu\n",
					(unsigned long)i, j);
				exit(1);
			}
		}
		{
			ouro_v *absent = ouro_apply(ouro_apply(ouro_fast("memNat"),
				ouro_nat(7)), lists[i]);
			ouro_v *outside = ouro_apply(ouro_apply(ouro_fast("nth"), lists[i]),
				ouro_nat(9));
			if (absent == 0 || absent->tag != 1 || absent->n != 0 ||
			    outside == 0 || outside->tag != 0 || outside->n != 0) {
				fputs("rt_selftest: absent list element found\n", stderr);
				exit(1);
			}
		}
	}
}

static ouro_v *list_tail_value(ouro_env *env, ouro_v *tail)
{
	(void)env;
	return tail;
}

static ouro_v *list_tail_head(ouro_env *env, ouro_v *head)
{
	(void)env;
	(void)head;
	return ouro_clos(list_tail_value, 0);
}

static void check_packed_clone_lifetime(ouro_v *(*clone_to_perm)(ouro_v *))
{
	unsigned char bytes[65536];
	ouro_v *value;
	ouro_v *copied;
	unsigned long long before;
	unsigned long long allocated;
	unsigned long i;
	for (i = 0; i < sizeof bytes; i++)
		bytes[i] = (unsigned char)(i % 256UL);
	ouro_perm_select(0);
	value = clone_to_perm(ouro_packed(bytes, sizeof bytes));
	before = ouro_heap_total_alloc_bytes();
	/* The lexer retains a suffix after each token, then drops that token's
	   phase allocations. Retaining 64 suffixes must not copy 64 full inputs. */
	for (i = 0; i < 64; i++) {
		ouro_v *branches[2];
		ouro_heap_mark();
		branches[0] = ouro_ctor(0, 0, 0);
		branches[1] = ouro_clos(list_tail_head, 0);
		value = clone_to_perm(ouro_case(value, 2, branches));
		ouro_heap_reset();
	}
	allocated = ouro_heap_total_alloc_bytes() - before;
	if (value == 0 || value->tag != OURO_TAG_BYTES ||
	    value->n != (int)(sizeof bytes - 64) ||
	    memcmp(value->u.s, bytes + 64, sizeof bytes - 64) != 0) {
		fputs("rt_selftest: retained packed suffix lost bytes\n", stderr);
		exit(1);
	}
	if (allocated > 131072ULL) {
		fprintf(stderr, "rt_selftest: packed suffix retention allocated %llu bytes\n", allocated);
		exit(1);
	}
	/* A different permanent bank has an independent lifetime. Its clone
	   must still own the bytes after the source bank is released. */
	ouro_perm_select(1);
	copied = clone_to_perm(value);
	ouro_perm_reset_bank(0);
	ouro_heap_discard_phase();
	if (copied == 0 || copied->tag != OURO_TAG_BYTES ||
	    copied->n != (int)(sizeof bytes - 64) ||
	    memcmp(copied->u.s, bytes + 64, sizeof bytes - 64) != 0) {
		fputs("rt_selftest: packed clone borrowed a released bank\n", stderr);
		exit(1);
	}
	ouro_perm_reset_bank(1);
	ouro_perm_select(0);
}

static void check_stack_clone_table_growth(void)
{
	/* Exceed the initial directory's four chunks. */
	const unsigned long length = 300UL;
	ouro_heap_context *scope = ouro_heap_context_enter();
	ouro_v *empty = ouro_ctor(0, 0, 0);
	ouro_v *element = ouro_nat(7);
	ouro_v *list = empty;
	ouro_v *pair;
	ouro_v *copy;
	unsigned long i;
	ouro_perm_select(1);
	ouro_heap_mark();
	for (i = 0; i < length; i++)
		list = ouro_ctor(1, 2, (ouro_v *[]){element, list});
	pair = ouro_ctor(0, 2, (ouro_v *[]){list, list});
	copy = ouro_clone_perm_with_stack_scratch(pair);
	if (copy == 0 || copy == pair || copy->tag != 0 || copy->n != 2 ||
	    OURO_F(copy, 0) == list || OURO_F(copy, 0) != OURO_F(copy, 1)) {
		fputs("rt_selftest: stack clone growth lost shared phase data\n", stderr);
		exit(1);
	}
	ouro_heap_reset();
	list = OURO_F(copy, 0);
	for (i = 0; i < length; i++) {
		if (list == 0 || list->tag != 1 || list->n != 2 || OURO_F(list, 0) != element) {
			fputs("rt_selftest: stack clone growth changed a list element\n", stderr);
			exit(1);
		}
		list = OURO_F(list, 1);
	}
	if (list != empty) {
		fputs("rt_selftest: stack clone growth changed the list tail\n", stderr);
		exit(1);
	}
	(void)ouro_heap_context_leave(scope, 0);
}

static ouro_v *nat_binary(const char *name, ouro_v *left, ouro_v *right)
{
	return ouro_apply(ouro_apply(ouro_fast(name), left), right);
}

static void require_nat_equal(ouro_v *left, ouro_v *right, const char *label)
{
	ouro_v *equal = nat_binary("eqNat", left, right);
	if (equal == 0 || equal->tag != 0 || equal->n != 0) {
		fprintf(stderr, "rt_selftest: wide Nat %s\n", label);
		exit(1);
	}
}

static ouro_v *nat_power_two(unsigned int bits)
{
	ouro_v *value = ouro_nat(1);
	while (bits-- > 0)
		value = nat_binary("mul", value, ouro_nat(2));
	return value;
}

static ouro_v *list_append_at(ouro_v *list, unsigned long index, const char *label)
{
	ouro_v *found = ouro_apply(ouro_apply(ouro_fast("nth"), list), ouro_nat(index));
	if (found == 0 || found->tag != 1 || found->n != 1) {
		fprintf(stderr, "rt_selftest: append %s missing index %lu\n", label, index);
		exit(1);
	}
	return OURO_F(found, 0);
}

static void require_list_append_size(ouro_v *list, unsigned long count, const char *label)
{
	ouro_v *outside;
	require_nat_equal(ouro_apply(ouro_fast("length"), list), ouro_nat(count), label);
	outside = ouro_apply(ouro_apply(ouro_fast("nth"), list), ouro_nat(count));
	if (outside == 0 || outside->tag != 0 || outside->n != 0) {
		fprintf(stderr, "rt_selftest: append %s has extra elements\n", label);
		exit(1);
	}
}

static ouro_v *list_append_payload_apply(ouro_env *env, ouro_v *arg)
{
	return nat_binary("add", env->v, arg);
}

static ouro_v *list_append_payload(const char *name, unsigned long captured)
{
	ouro_v *fields[2];
	fields[0] = ouro_str(name);
	fields[1] = ouro_clos(list_append_payload_apply, ouro_cons(ouro_nat(captured), 0));
	return ouro_ctor(0, 2, fields);
}

static ouro_v *list_append_pair(void)
{
	ouro_v *fields[2];
	fields[0] = list_append_payload("beta", 11);
	fields[1] = ouro_ctor(0, 0, 0);
	fields[1] = ouro_ctor(1, 2, fields);
	fields[0] = list_append_payload("alpha", 7);
	return ouro_ctor(1, 2, fields);
}

static void require_list_append_payloads(ouro_v *list, const char *const *names,
		const unsigned long *captured, unsigned long count, const char *label)
{
	unsigned long index;
	require_list_append_size(list, count, label);
	for (index = 0; index < count; index++) {
		ouro_v *payload = list_append_at(list, index, label);
		ouro_v *name, *callable;
		if (payload == 0 || payload->tag != 0 || payload->n != 2) {
			fprintf(stderr, "rt_selftest: append %s payload index %lu\n", label, index);
			exit(1);
		}
		name = OURO_F(payload, 0);
		callable = OURO_F(payload, 1);
		if (name == 0 || name->tag != OURO_TAG_STR || strcmp(name->u.s, names[index]) != 0 ||
		    callable == 0 || callable->tag != OURO_TAG_CLOS) {
			fprintf(stderr, "rt_selftest: append %s field order index %lu\n", label, index);
			exit(1);
		}
		require_nat_equal(ouro_apply(callable, ouro_nat(3)), ouro_nat(captured[index] + 3), label);
	}
}

static void require_list_append_codes(ouro_v *list, const unsigned char *expected,
		unsigned long count, const char *label)
{
	unsigned long index;
	require_list_append_size(list, count, label);
	for (index = 0; index < count; index++) {
		unsigned long code;
		if (!ouro_nat_to_ulong(list_append_at(list, index, label), &code) || code != expected[index]) {
			fprintf(stderr, "rt_selftest: append %s code order index %lu\n", label, index);
			exit(1);
		}
	}
}

static ouro_v *list_append_cached(void)
{
	static ouro_v *cached;
	if (cached == 0)
		cached = ouro_fast("append");
	return cached;
}

static void check_list_append(void)
{
	static const char *const names[] = {"alpha", "beta", "gamma"};
	static const unsigned long captured[] = {7, 11, 19};
	static const char *const twice_names[] = {"alpha", "beta", "alpha", "beta"};
	static const unsigned long twice_captured[] = {7, 11, 7, 11};
	static const unsigned char plain_codes[] = {0, 128};
	static const unsigned char packed_codes[] = {255, 1};
	static const unsigned char mixed_codes[] = {0, 128, 42, 17, 255, 1, 0, 128};
	ouro_v *nil = ouro_ctor(0, 0, 0);
	ouro_v *left = list_append_pair();
	ouro_v *fields[2] = {list_append_payload("gamma", 19), nil};
	ouro_v *right = ouro_ctor(1, 2, fields);
	ouro_v *partial = ouro_apply(ouro_fast("append"), left);
	ouro_v *plain = ouro_bytes(plain_codes, sizeof plain_codes);
	ouro_v *packed = ouro_packed(packed_codes, sizeof packed_codes);
	ouro_v *empty = ouro_packed(packed_codes, 0);
	ouro_v *singleton, *tail, *mixed, *retained;
	ouro_heap_context *context;
	unsigned long index;
	require_list_append_payloads(append_list(nil, left), names, captured, 2, "Nil left");
	require_list_append_payloads(append_list(left, nil), names, captured, 2, "Nil right");
	require_list_append_size(append_list(nil, nil), 0, "both Nil");
	require_list_append_payloads(ouro_apply(partial, right), names, captured, 3, "partial first");
	require_list_append_payloads(ouro_apply(partial, nil), names, captured, 2, "partial Nil");
	require_list_append_payloads(ouro_apply(partial, left), twice_names, twice_captured, 4, "partial reuse");
	fields[0] = ouro_nat(42);
	fields[1] = nil;
	singleton = ouro_ctor(1, 2, fields);
	fields[0] = ouro_nat(17);
	fields[1] = append_list(packed, plain);
	tail = ouro_ctor(1, 2, fields);
	mixed = append_list(append_list(plain, singleton), append_list(empty, tail));
	require_list_append_codes(mixed, mixed_codes, sizeof mixed_codes, "Cons packed CAT");
	require_list_append_codes(append_list(nil, packed), packed_codes, sizeof packed_codes, "packed Nil left");
	require_list_append_codes(append_list(packed, nil), packed_codes, sizeof packed_codes, "packed Nil right");
	require_list_append_size(append_list(empty, empty), 0, "packed empty");
	context = ouro_heap_context_enter();
	/* Initialize the static cache inside the nested context. The retained
	   partial must own its captured List after the work banks are released. */
	retained = ouro_apply(list_append_cached(), list_append_pair());
	retained = ouro_heap_context_leave(context, retained);
	for (index = 0; index < 3; index++) {
		require_list_append_payloads(ouro_apply(retained, right), names, captured, 3, "retained partial");
		require_list_append_payloads(ouro_apply(ouro_apply(list_append_cached(), left), right),
			names, captured, 3, "static cached callable");
		require_list_append_payloads(ouro_app(ouro_app(list_append_cached(), left), right),
			names, captured, 3, "generated cached application");
	}
}

static void check_list_length(void)
{
	static const unsigned char codes[] = {0, 128, 255};
	static const unsigned char wide_codes[65536] = {0};
	ouro_v *nil = ouro_ctor(0, 0, 0);
	ouro_v *empty = ouro_packed(codes, 0);
	ouro_v *plain = ouro_bytes(codes, sizeof codes);
	ouro_v *packed = ouro_packed(codes, sizeof codes);
	ouro_v *fields[2] = {ouro_nat(7), nil};
	ouro_v *singleton = ouro_ctor(1, 2, fields);
	ouro_v *left = nil, *right = nil, *mixed = nil, *wide = nil;
	ouro_v *wide_segment;
	unsigned long i, mixed_length = 0;
	ouro_v *lists[] = {
		nil, empty, singleton, plain, packed,
		append_list(nil, packed), append_list(plain, nil),
		append_list(append_list(plain, empty), packed)
	};
	static const unsigned long lengths[] = {0, 0, 1, 3, 3, 3, 3, 6};
	for (i = 0; i < sizeof lists / sizeof lists[0]; i++)
		require_nat_equal(ouro_apply(ouro_fast("length"), lists[i]),
		                  ouro_nat(lengths[i]), "list length shape");
	fields[1] = append_list(packed, plain);
	require_nat_equal(ouro_apply(ouro_fast("length"), ouro_ctor(1, 2, fields)),
	                  ouro_nat(7), "list length Cons tail CAT");
	for (i = 0; i < 512UL; i++) {
		ouro_v *segment = i % 3UL == 0 ? packed :
		                  i % 3UL == 1 ? singleton : empty;
		left = append_list(left, singleton);
		right = append_list(singleton, right);
		mixed = append_list(mixed, segment);
		mixed_length += i % 3UL == 0 ? 3UL : i % 3UL == 1 ? 1UL : 0UL;
		if (i == 62UL || i == 63UL || i == 64UL || i == 80UL || i == 511UL)
			require_nat_equal(ouro_apply(ouro_fast("length"), left),
			                  ouro_nat(i + 1UL), "list length left CAT depth");
	}
	require_nat_equal(ouro_apply(ouro_fast("length"), right),
	                  ouro_nat(512), "list length right CAT depth");
	require_nat_equal(ouro_apply(ouro_fast("length"), mixed),
	                  ouro_nat(mixed_length), "list length mixed CAT depth");
	/* Sharing a real packed payload keeps the 2^32-length fixture bounded. */
	wide_segment = ouro_packed(wide_codes, sizeof wide_codes);
	for (i = 0; i < 65536UL; i++)
		wide = append_list(wide, wide_segment);
	require_nat_equal(ouro_apply(ouro_fast("length"), wide),
	                  ouro_nat_u64(UINT64_C(4294967296)), "list length beyond Word32");
}

static ouro_v *nat_predecessor(ouro_env *env, ouro_v *value)
{
	(void)env;
	return value;
}

static void check_wide_naturals(void)
{
	unsigned int bits;
	uint32_t seed = 17;
	unsigned long number;
	ouro_v *maximum = ouro_nat(ULONG_MAX);
	ouro_v *overflow = ouro_ctor(1, 1, &maximum);
	if (!ouro_nat_to_ulong(maximum, &number) || number != ULONG_MAX ||
	    ouro_nat_to_ulong(overflow, &number) || ouro_nat_to_ulong(ouro_str("bad"), &number) ||
	    ouro_nat_to_ulong(0, &number)) {
		fputs("rt_selftest: checked Nat host conversion\n", stderr);
		exit(1);
	}
	if (strcmp(ouro_nat_decimal(nat_power_two(64))->u.s, "18446744073709551616") != 0 ||
	    strcmp(ouro_nat_decimal(nat_power_two(128))->u.s, "340282366920938463463374607431768211456") != 0 ||
	    strcmp(ouro_nat_decimal(ouro_nat(0))->u.s, "0") != 0 ||
	    ouro_nat_low32(nat_binary("add", nat_power_two(128), ouro_nat(73))) != 73) {
		fputs("rt_selftest: full Nat decimal or low word\n", stderr);
		exit(1);
	}
	for (bits = 0; bits < 256; bits++) {
		uint32_t left, right;
		unsigned int operation;
		seed = seed * 1664525U + 1013904223U;
		left = seed;
		seed = seed * 1664525U + 1013904223U;
		right = seed;
		for (operation = 0; operation < 3; operation++) {
			const char *name = operation == 0 ? "add" : operation == 1 ? "mul" : "sub";
			uint64_t expected = operation == 0 ? (uint64_t)left + right :
			                    operation == 1 ? (uint64_t)left * right :
			                    left > right ? (uint64_t)left - right : 0;
			char text[32];
			ouro_v *actual = nat_binary(name, ouro_nat(left), ouro_nat(right));
			snprintf(text, sizeof text, "%llu", (unsigned long long)expected);
			if (strcmp(ouro_nat_decimal(actual)->u.s, text) != 0) {
				fprintf(stderr, "rt_selftest: Nat %s differs from uint64 oracle\n", name);
				exit(1);
			}
		}
	}
	for (bits = 31; bits <= 256; bits++) {
		ouro_v *bound = nat_power_two(bits);
		ouro_v *previous = nat_binary("sub", bound, ouro_nat(1));
		ouro_v *ordered = nat_binary("compareNat", bound, previous);
		ouro_v *successor = ouro_ctor(1, 1, &previous);
		ouro_v *branches[2];
		if (ordered == 0 || ordered->tag != 2 || ordered->n != 0) {
			fprintf(stderr, "rt_selftest: Nat 2^%u overflowed\n", bits);
			exit(1);
		}
		require_nat_equal(nat_binary("add", previous, ouro_nat(1)), bound, "carry");
		require_nat_equal(successor, bound, "mixed successor");
		require_nat_equal(nat_binary("sub", previous, bound), ouro_nat(0), "saturating subtraction");
		require_nat_equal(nat_binary("sub", nat_binary("mul", previous, previous),
		                    nat_binary("mul", bound, nat_binary("sub", bound, ouro_nat(2)))),
		                  ouro_nat(1), "multiplication carry");
		branches[0] = ouro_nat(0);
		branches[1] = ouro_clos(nat_predecessor, 0);
		require_nat_equal(ouro_case(bound, 2, branches), previous, "pattern predecessor");
	}
	{
		ouro_heap_context *context = ouro_heap_context_enter();
		ouro_v *value = nat_power_two(257);
		ouro_v *retained = ouro_heap_context_leave(context, value);
		require_nat_equal(retained, nat_power_two(257), "context lifetime");
		retained = ouro_keep(retained);
		require_nat_equal(retained, nat_power_two(257), "permanent clone lifetime");
	}
}

static void check_nat_subtraction(void)
{
	ouro_v *peano[9], *partial, *wide, *retained;
	ouro_heap_context *context;
	unsigned int left, right, index;
	peano[0] = ouro_ctor(0, 0, 0);
	for (index = 1; index < 9; index++)
		peano[index] = ouro_ctor(1, 1, &peano[index - 1]);
	if (nat_depth(peano[8]) != 8) {
		fputs("rt_selftest: subtraction Peano input shape\n", stderr);
		exit(1);
	}
	for (left = 0; left < 9; left++) {
		partial = ouro_apply(ouro_fast("sub"), peano[left]);
		for (right = 0; right < 9; right++) {
			ouro_v *expected = ouro_nat(left > right ? left - right : 0);
			require_nat_equal(ouro_apply(partial, peano[right]), expected, "sub Peano saturation");
			require_nat_equal(ouro_apply(partial, ouro_nat(right)), expected, "sub mixed right");
			require_nat_equal(nat_binary("sub", ouro_nat(left), peano[right]), expected, "sub mixed left");
		}
	}
	{
		ouro_v *values[4][2] = {
			{nat_binary("add", nat_power_two(65), ouro_nat(9)),
			 nat_binary("add", nat_power_two(64), ouro_nat(11))},
			{nat_power_two(128), ouro_nat(1)},
			{nat_binary("add", nat_power_two(129), ouro_nat(17)),
			 nat_binary("add", nat_power_two(128), ouro_nat(3))},
			{nat_power_two(128), peano[2]},
		};
		static const char *expected[] = {"18446744073709551614",
			"340282366920938463463374607431768211455",
			"340282366920938463463374607431768211470",
			"340282366920938463463374607431768211454"};
		for (index = 0; index < 4; index++) {
			ouro_v *actual = nat_binary("sub", values[index][0], values[index][1]);
			if (strcmp(ouro_nat_decimal(actual)->u.s, expected[index]) != 0) {
				fputs("rt_selftest: full Nat subtraction decimal oracle\n", stderr);
				exit(1);
			}
		}
	}
	wide = nat_power_two(129);
	require_nat_equal(nat_binary("sub", wide, wide), ouro_nat(0), "sub wide equality");
	require_nat_equal(nat_binary("sub", nat_power_two(128), wide), ouro_nat(0), "sub wide saturation");
	require_nat_equal(nat_binary("sub", peano[8], wide), ouro_nat(0), "sub Peano below wide");
	context = ouro_heap_context_enter();
	wide = nat_power_two(129);
	partial = ouro_apply(ouro_fast("sub"), wide);
	retained = ouro_heap_context_leave(context, ouro_ctor(87, 2, (ouro_v *[]){wide, partial}));
	retained = ouro_keep(retained);
	ouro_heap_discard_phase();
	partial = OURO_F(retained, 1);
	for (index = 0; index < 3; index++) {
		ouro_v *actual;
		memset(ouro_alloc(65536UL), 97 + (int)index, 65536UL);
		actual = ouro_apply(partial, nat_binary("add", nat_power_two(128), ouro_nat(3)));
		if (strcmp(ouro_nat_decimal(actual)->u.s, "340282366920938463463374607431768211453") != 0) {
			fputs("rt_selftest: sub partial capture after context and phase release\n", stderr);
			exit(1);
		}
		require_nat_equal(ouro_apply(partial, OURO_F(retained, 0)), ouro_nat(0), "sub partial reuse");
	}
}

static void check_clone_since_mark(void)
{
	ouro_v *settled;
	ouro_v *inner;
	ouro_v *fresh;
	ouro_v *kept;
	unsigned long long before;
	unsigned long long allocated;
	settled = ouro_nat(7);
	ouro_heap_mark();
	inner = ouro_ctor(3, 1, &settled);
	fresh = ouro_ctor(4, 1, &inner);
	before = ouro_heap_total_alloc_bytes();
	kept = ouro_clone_since_mark(fresh);
	ouro_heap_reset();
	allocated = ouro_heap_total_alloc_bytes() - before;
	if (kept == 0 || kept == fresh || kept->tag != 4 || kept->n != 1 ||
	    OURO_F(kept, 0) == 0 || OURO_F(kept, 0) == inner ||
	    OURO_F(kept, 0)->tag != 3 || OURO_F(OURO_F(kept, 0), 0) != settled) {
		fputs("rt_selftest: mark clone did not keep the settled spine\n", stderr);
		exit(1);
	}
	if (allocated > 4096ULL) {
		fprintf(stderr, "rt_selftest: mark clone allocated %llu bytes\n", allocated);
		exit(1);
	}
	{
		int step;
		ouro_v *spine = ouro_nat(1);
		unsigned long long spine_before;
		unsigned long long spine_allocated;
		spine_before = ouro_heap_total_alloc_bytes();
		for (step = 0; step < 1000; step++) {
			ouro_v *cell_fields[2];
			ouro_v *cell;
			ouro_heap_mark();
			cell_fields[0] = ouro_nat((unsigned long)(step % 50));
			cell_fields[1] = spine;
			cell = ouro_ctor(1, 2, cell_fields);
			(void)ouro_ctor(2, 0, 0);
			spine = ouro_clone_since_mark(cell);
			ouro_heap_reset();
		}
		spine_allocated = ouro_heap_total_alloc_bytes() - spine_before;
		if (spine == 0 || spine_allocated > 1000000ULL) {
			fprintf(stderr, "rt_selftest: token spine allocated %llu bytes\n",
				spine_allocated);
			exit(1);
		}
	}
}

static void *context_bank_alloc(int bank, unsigned long size)
{
	if (bank < 0)
		return ouro_alloc(size);
	ouro_perm_select(bank);
	return ouro_perm_alloc(size);
}

static void require_context_bytes(unsigned long long before, unsigned long long expected,
	const char *operation)
{
	unsigned long long actual = ouro_heap_live_bytes() - before;
	if (actual != expected) {
		fprintf(stderr, "rt_selftest: %s live bytes %llu /= %llu\n", operation, actual, expected);
		exit(1);
	}
}

/* Fragmented requests expose closed block sizes through live-byte accounting. */
static void check_child_bank_growth(int bank)
{
	static const unsigned long requests[] = {1UL, 64UL * 1024UL, 128UL * 1024UL,
		256UL * 1024UL, 512UL * 1024UL, 1024UL * 1024UL, 1024UL * 1024UL + 8UL,
		8UL, 1024UL * 1024UL};
	static const unsigned long long live[] = {8ULL, 128ULL * 1024ULL, 320ULL * 1024ULL,
		704ULL * 1024ULL, 1472ULL * 1024ULL, 3008ULL * 1024ULL,
		4032ULL * 1024ULL + 8ULL, 4032ULL * 1024ULL + 16ULL, 6080ULL * 1024ULL + 8ULL};
	unsigned char *blocks[sizeof requests / sizeof requests[0]];
	unsigned long index;
	unsigned long long before = ouro_heap_live_bytes(), total = ouro_heap_total_alloc_bytes();
	unsigned long long requested = 0;
	for (index = 0; index < sizeof requests / sizeof requests[0]; index++) {
		blocks[index] = (unsigned char *)context_bank_alloc(bank, requests[index]);
		memset(blocks[index], 31 + bank * 10 + (int)index, requests[index]);
		requested += index == 0 ? 8ULL : requests[index];
		require_context_bytes(before, live[index], "child bank growth");
		if ((uintptr_t)blocks[index] % 8U != 0 ||
		    ouro_heap_total_alloc_bytes() - total != requested) {
			fputs("rt_selftest: child bank alignment or request accounting changed\n", stderr);
			exit(1);
		}
	}
	for (index = 0; index < sizeof requests / sizeof requests[0]; index++)
		if (blocks[index][0] != (unsigned char)(31 + bank * 10 + (int)index) ||
		    blocks[index][requests[index] - 1UL] != blocks[index][0]) {
			fputs("rt_selftest: earlier child block was moved or overwritten\n", stderr);
			exit(1);
		}
}

static void check_context_block_sizes(void)
{
	static const unsigned char binary[] = {0, 255, 128, 7};
	unsigned char *root_small[3], *root_large[3], *static_small, *static_large;
	ouro_heap_context *context, *inner;
	ouro_v *retained;
	unsigned long long before, suspended, root_base;
	int bank;
	ouro_heap_discard_phase();
	ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(0);
	for (bank = -1; bank < 2; bank++) {
		before = ouro_heap_live_bytes();
		root_small[bank + 1] = (unsigned char *)context_bank_alloc(bank, 1UL);
		root_large[bank + 1] = (unsigned char *)context_bank_alloc(bank, 64UL * 1024UL);
		root_small[bank + 1][0] = (unsigned char)(91 + bank);
		memset(root_large[bank + 1], 101 + bank, 64UL * 1024UL);
		require_context_bytes(before, 64ULL * 1024ULL + 8ULL, "root bank minimum");
	}
	suspended = ouro_heap_live_bytes();
	context = ouro_heap_context_enter();
	for (bank = -1; bank < 2; bank++)
		check_child_bank_growth(bank);
	before = ouro_heap_live_bytes();
	ouro_static_begin();
	static_small = (unsigned char *)ouro_alloc(1UL);
	static_large = (unsigned char *)ouro_alloc(64UL * 1024UL);
	static_small[0] = 113;
	memset(static_large, 114, 64UL * 1024UL);
	ouro_static_end();
	require_context_bytes(before, 64ULL * 1024ULL + 8ULL, "static bank inside child");
	(void)ouro_heap_context_leave(context, 0);
	require_context_bytes(suspended, 64ULL * 1024ULL + 8ULL, "child bank release");
	for (bank = -1; bank < 2; bank++)
		if (root_small[bank + 1][0] != (unsigned char)(91 + bank) ||
		    root_large[bank + 1][0] != (unsigned char)(101 + bank) ||
		    root_large[bank + 1][64UL * 1024UL - 1UL] != root_large[bank + 1][0]) {
			fputs("rt_selftest: caller bank changed after child leave\n", stderr);
			exit(1);
		}
	if (static_small[0] != 113 || static_large[0] != 114 ||
	    static_large[64UL * 1024UL - 1UL] != 114) {
		fputs("rt_selftest: static bank freed with child\n", stderr);
		exit(1);
	}
	ouro_heap_discard_phase();
	ouro_perm_reset_bank(0); ouro_perm_reset_bank(1); ouro_perm_select(0);
	root_base = ouro_heap_live_bytes();
	context = ouro_heap_context_enter();
	inner = ouro_heap_context_enter();
	retained = ouro_heap_context_leave(inner, ouro_packed(binary, sizeof binary));
	(void)ouro_alloc(64UL * 1024UL);
	require_context_bytes(root_base, 128ULL * 1024ULL, "clone to child bank policy");
	retained = ouro_heap_context_leave(context, ouro_ctor(87, 1, &retained));
	before = ouro_heap_live_bytes();
	(void)ouro_alloc(64UL * 1024UL);
	require_context_bytes(before, 64ULL * 1024ULL, "clone to root bank policy");
	(void)ouro_alloc(1024UL * 1024UL);
	require_context_bytes(root_base, 2ULL * 1024ULL * 1024ULL, "restored root growth cap");
	if (retained == 0 || retained->tag != 87 || retained->n != 1 ||
	    OURO_F(retained, 0) == 0 || OURO_F(retained, 0)->tag != OURO_TAG_BYTES ||
	    OURO_F(retained, 0)->n != (int)sizeof binary ||
	    memcmp(OURO_F(retained, 0)->u.s, binary, sizeof binary) != 0) {
		fputs("rt_selftest: nested context survivor changed after bank growth\n", stderr);
		exit(1);
	}
}

static ouro_v *case_arm_marker(ouro_env *env, ouro_v *unused)
{
	(void)unused;
	return env->v;
}

/* Fresh arms that are exactly the newest phase cells are released in either
   array order; a repeated arm or a newer cell above them keeps every arm. */
static void check_case_arm_release(void)
{
	static const unsigned long long released[] = {
		2ULL * sizeof(ouro_v), 2ULL * sizeof(ouro_v), 0ULL, 0ULL};
	ouro_v *scrutinee = ouro_ctor(1, 0, 0);
	int shape;
	for (shape = 0; shape < 4; shape++) {
		ouro_env *first, *second;
		ouro_v *arms[2];
		ouro_v *result;
		unsigned long long before;
		ouro_heap_discard_phase();
		first = ouro_cons(ouro_nat(10), 0);
		second = ouro_cons(ouro_nat(11), 0);
		if (shape == 1) {
			arms[1] = ouro_thunk(case_arm_marker, second);
			arms[0] = ouro_thunk(case_arm_marker, first);
		} else {
			arms[0] = ouro_thunk(case_arm_marker, first);
			arms[1] = ouro_thunk(case_arm_marker, second);
		}
		if (shape == 2)
			arms[0] = arms[1];
		if (shape == 3)
			(void)ouro_cons(ouro_nat(12), 0);
		before = ouro_heap_reclaimed_bytes();
		result = ouro_case(scrutinee, 2, arms);
		if (result != ouro_nat(11) || ouro_heap_reclaimed_bytes() - before != released[shape]) {
			fprintf(stderr, "rt_selftest: case arm release shape %d\n", shape);
			exit(1);
		}
	}
}

static void require_static_pack(ouro_v *value, const char *expected, const char *label)
{
	int round, block;
	for (round = 0; round < 2; round++) {
		if (strcmp(ouro_nat_decimal(value)->u.s, expected) != 0) {
			fprintf(stderr, "rt_selftest: static Nat %s round %d\n", label, round);
			exit(1);
		}
		/* Overwrite the released phase blocks, which are reused first. */
		ouro_heap_discard_phase();
		for (block = 0; block < 16; block++)
			memset(ouro_alloc(1024UL * 1024UL), 0x5a, 1024UL * 1024UL);
	}
}

static ouro_v *successor_chain(ouro_v *value, unsigned long count)
{
	while (count-- > 0)
		value = ouro_ctor(1, 1, &value);
	return value;
}

/* Successor chains rooted in the static bank pack to values that outlive the
   phase bank, including chains packed after the static packing budget. */
static void check_static_nat_pack(void)
{
	ouro_v *value, *first;
	unsigned long index;
	unsigned long long before;
	ouro_static_begin();
	value = successor_chain(ouro_ctor(0, 0, 0), 1500UL);
	ouro_static_end();
	require_static_pack(value, "1500", "successor chain");
	ouro_static_begin();
	value = successor_chain(ouro_nat_u64(UINT64_C(1099511627781)), 3UL);
	ouro_static_end();
	require_static_pack(value, "1099511627784", "wide successor chain");
	/* A phase cell address can later hold another chain. */
	ouro_heap_discard_phase();
	(void)ouro_cons(0, 0);
	ouro_heap_mark();
	first = successor_chain(ouro_nat(0), 5UL);
	if (ouro_nat_low32(first) != 5U) {
		fputs("rt_selftest: phase successor chain\n", stderr);
		exit(1);
	}
	ouro_heap_reset();
	value = successor_chain(ouro_nat(100), 5UL);
	if (value != first || ouro_nat_low32(value) != 105U) {
		fputs("rt_selftest: reused phase successor chain\n", stderr);
		exit(1);
	}
	/* 65536 distinct wide results exceed the static packing budget. */
	for (index = 0; index < 65536UL; index++) {
		ouro_static_begin();
		value = successor_chain(ouro_nat_u64(UINT64_C(1099511627776) + index), 1UL);
		ouro_static_end();
		if (ouro_nat_low32(value) != (uint32_t)(index + 1UL)) {
			fprintf(stderr, "rt_selftest: static Nat budget index %lu\n", index);
			exit(1);
		}
	}
	/* Past the budget a result that needs allocation is rebuilt on each use. */
	before = ouro_heap_total_alloc_bytes();
	if (ouro_nat_low32(value) != 65536U || ouro_heap_total_alloc_bytes() == before) {
		fputs("rt_selftest: static Nat kept a phase result\n", stderr);
		exit(1);
	}
	require_static_pack(value, "1099511693312", "chain past the packing budget");
}

int main(int argc, char **argv)
{
	if (argc == 2) {
		ouro_v *invalid = strstr(argv[1], "-null") != 0 ? 0 : ouro_nat(0);
		if (strncmp(argv[1], "alloc-overflow-", 15) == 0) {
			(void)ouro_heap_context_enter();
			if (strcmp(argv[1], "alloc-overflow-static") == 0)
				ouro_static_begin();
			else if (strcmp(argv[1], "alloc-overflow-perm0") == 0 ||
			         strcmp(argv[1], "alloc-overflow-perm1") == 0) {
				ouro_perm_select(strcmp(argv[1], "alloc-overflow-perm1") == 0);
				ouro_perm_begin();
			} else if (strcmp(argv[1], "alloc-overflow-phase") != 0)
				return 2;
			(void)ouro_alloc(ULONG_MAX);
			fputs("rt_selftest: overflowing allocation request accepted\n", stderr);
			return 1;
		}
		if (strncmp(argv[1], "app-", 4) == 0)
			(void)ouro_app(invalid, 0);
		else if (strncmp(argv[1], "apply-", 6) == 0)
			(void)ouro_apply(invalid, 0);
		else
			return 2;
		return 0;
	}
	check_context_block_sizes();
	ouro_show_line(ouro_g_four());
	check_phase_apply();
	check_call_env_reclaim();
	check_null_call_env();
	check_cloned_call_env();
	check_list_lookup();
	check_list_append();
	check_list_length();
	check_packed_clone_lifetime(ouro_clone_perm);
	check_packed_clone_lifetime(ouro_clone_perm_with_stack_scratch);
	check_stack_clone_table_growth();
	check_clone_since_mark();
	check_wide_naturals();
	check_nat_subtraction();
	check_case_arm_release();
	check_static_nat_pack();
	return 0;
}
