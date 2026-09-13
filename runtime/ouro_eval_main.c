/* ouro_eval_main.c: host printer for ouro1 eval.
   Forces the last export (the wrapped __ouro_eval body) and prints an
   Ouro-looking normal form. No compiler algorithm — constructor walk only. */
#include "ouro_rt.h"

#include <stdio.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

static int is_z(ouro_v *v)
{
	return v != 0 && ((v->tag == 0 && v->n == 0) ||
			  (v->tag == OURO_TAG_NAT && v->n == 0));
}

static int is_s(ouro_v *v)
{
	return v != 0 && v->tag == 1 && v->n == 1 && OURO_F(v, 0) != 0;
}

static void print_nat(ouro_v *v)
{
	int depth = 0;
	ouro_v *cur = v;
	while (is_s(cur)) {
		depth++;
		cur = OURO_F(cur, 0);
		if (depth > 100000) {
			fputs("<nat-too-large>", stdout);
			return;
		}
	}
	if (cur != 0 && cur->tag == OURO_TAG_BIG_NAT) {
		fputs("<nat-too-large>", stdout);
		return;
	}
	if (cur != 0 && cur->tag == OURO_TAG_NAT) {
		if (cur->n < 0 || cur->n > 100000 - depth) {
			fputs("<nat-too-large>", stdout);
			return;
		}
		depth += cur->n;
	} else if (!is_z(cur)) {
		ouro_show(v);
		return;
	}
	if (depth == 0) {
		fputs("Z", stdout);
		return;
	}
	{
		int i;
		for (i = 0; i < depth; i++) {
			if (i == 0)
				fputs("S ", stdout);
			else
				fputs("(S ", stdout);
		}
		fputs("Z", stdout);
		for (i = 1; i < depth; i++)
			fputc(')', stdout);
	}
}

int main(void)
{
	int n = ouro_export_count();
	ouro_v *v;
	if (n < 1) {
		fputs("ouro1 eval: no exports\n", stderr);
		return 1;
	}
	v = ouro_export_value(n - 1);
	if (v == 0) {
		fputs("ouro1 eval: last export is null\n", stderr);
		return 1;
	}
	if (v->tag == OURO_TAG_CLOS) {
		fputs("<fun>\n", stdout);
		return 0;
	}
	if (v->tag == OURO_TAG_NAT || v->tag == OURO_TAG_BIG_NAT || is_z(v) || is_s(v)) {
		print_nat(v);
		fputs(" : Nat\n", stdout);
		return 0;
	}
	ouro_show(v);
	fputc('\n', stdout);
	return 0;
}
