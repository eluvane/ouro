/* Value decoding shared by the bootstrap and split frontend host adapters. */
#ifndef OURO_HOST_VALUES_H
#define OURO_HOST_VALUES_H
#include "ouro_rt.h"
#include <string.h>
#include <stdlib.h>

static inline int list_done(ouro_v *cur)
{
	if (cur == 0)
		return 1;
	if (cur->tag == 0 && cur->n == 0)
		return 1;
	if (cur->tag == OURO_TAG_NAT && cur->n == 0)
		return 1;
	if (cur->tag == OURO_TAG_BYTES && cur->n == 0)
		return 1;
	return 0;
}

static inline unsigned long as_nat(ouro_v *v)
{
	unsigned long n = 0;
	if (v != 0 && v->tag == OURO_TAG_NAT && v->n >= 0)
		return (unsigned long)v->n;
	if (v != 0 && !ouro_nat_to_ulong(v, &n)) {
		fputs("ouro host: Nat does not fit the host operation\n", stderr);
		exit(1);
	}
	return n;
}

static inline int codes_to_buf(ouro_v *xs, char *buf, int cap)
{
	int n = 0;
	ouro_v *stack[64];
	int sp = 0;
	for (;;) {
		if (list_done(xs)) {
			if (sp == 0) {
				if (n < cap)
					buf[n] = 0;
				return n;
			}
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
			int k = xs->n;
			if (k > cap - 1 - n)
				k = cap - 1 - n;
			if (k > 0 && xs->u.s != 0)
				memcpy(buf + n, xs->u.s, (size_t)k);
			n += k;
			if (sp == 0) {
				if (n < cap)
					buf[n] = 0;
				return n;
			}
			xs = stack[--sp];
			continue;
		}
		if (xs->tag == 1 && xs->n == 2) {
			unsigned long b = as_nat(OURO_F(xs, 0));
			if (n < cap - 1)
				buf[n++] = (char)(b & 0xFFUL);
			xs = OURO_F(xs, 1);
			continue;
		}
		if (n < cap)
			buf[n] = 0;
		return n;
	}
}

#endif
