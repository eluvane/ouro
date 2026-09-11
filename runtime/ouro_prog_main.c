/* ouro_prog_main.c: host driver for a standalone Ouro IO program emitted by
   print_c.ouro with OURO_EMIT_IO_SHIMS=1. Finds the `main` export (an IO
   thunk: closure applied to Unit) and forces it once. Argument plumbing
   only — no compiler algorithm here. */
#include "ouro_rt.h"
#include "ouro_io.h"

#include <stdio.h>
#include <string.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

int main(int argc, char **argv)
{
	int i;
	int n = ouro_export_count();
	ouro_v *entry = 0;
	ouro_io_set_argv(argc, argv);
	for (i = 0; i < n; i++) {
		if (strcmp(ouro_export_name(i), "main") == 0)
			entry = ouro_export_value(i);
	}
	if (entry == 0) {
		fputs("ouro run: program has no `main` export\n", stderr);
		return 2;
	}
	ouro_apply(entry, ouro_ctor(0, 0, 0));
	return ouro_io_exit_status();
}
