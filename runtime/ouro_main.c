/* ouro_main.c: gate driver for a translation unit emitted by print_c.ouro.
   Prints one line per export so the C result can be diffed against the JS
   backend's value for the same export. */
#include "ouro_rt.h"

#include <stdio.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

int main(void)
{
	int n = ouro_export_count();
	int i;
	for (i = 0; i < n; i++) {
		printf("%s=", ouro_export_name(i));
		ouro_show_line(ouro_export_value(i));
	}
	return 0;
}
