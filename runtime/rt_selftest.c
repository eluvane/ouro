/* rt_selftest.c: hand-written in the exact shape print_c.ouro must emit for
   samples/examples/nat.ouro. Fixes the calling convention, the environment
   indexing, the fix knot and the static-bank global caches before the emitter
   is written. Not generated. Global caches must sit in the static bank:
   ouro_app reclaims a closure that is the newest phase cell, so a cached
   phase closure applied right after creation would be overwritten. */
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

static void check_packed_clone_lifetime(void)
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
	value = ouro_clone_perm(ouro_packed(bytes, sizeof bytes));
	before = ouro_heap_total_alloc_bytes();
	/* The lexer retains a suffix after each token, then drops that token's
	   phase allocations. Retaining 64 suffixes must not copy 64 full inputs. */
	for (i = 0; i < 64; i++) {
		ouro_v *branches[2];
		ouro_heap_mark();
		branches[0] = ouro_ctor(0, 0, 0);
		branches[1] = ouro_clos(list_tail_head, 0);
		value = ouro_clone_perm(ouro_case(value, 2, branches));
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
	copied = ouro_clone_perm(value);
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

int main(int argc, char **argv)
{
	if (argc == 2) {
		ouro_v *invalid = strstr(argv[1], "-null") != 0 ? 0 : ouro_nat(0);
		if (strncmp(argv[1], "app-", 4) == 0)
			(void)ouro_app(invalid, 0);
		else if (strncmp(argv[1], "apply-", 6) == 0)
			(void)ouro_apply(invalid, 0);
		else
			return 2;
		return 0;
	}
	ouro_show_line(ouro_g_four());
	check_phase_apply();
	check_list_lookup();
	check_packed_clone_lifetime();
	check_wide_naturals();
	return 0;
}
