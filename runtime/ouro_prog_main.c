/* ouro_prog_main.c: host driver for a standalone Ouro IO program emitted by
   print_c.ouro with OURO_EMIT_IO_SHIMS=1. Finds the `main` export (an IO
   thunk: closure applied to Unit) and forces it once. Argument plumbing
   only — no compiler algorithm here. */
#include "ouro_rt.h"
#include "ouro_io.h"

#include <stdio.h>
#include <string.h>
#ifndef _WIN32
#include <sys/resource.h>
#endif

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

/* ELF has no link-time stack reserve (PE and Mach-O do). Apply the documented
   128 MiB POSIX cap here so a worker launched from an 8 MiB shell does not
   SIGSEGV on a legal large source. Do not raise the inherited hard limit. */
static void ouro_reserve_native_stack(void)
{
#ifndef _WIN32
	struct rlimit limit;
	rlim_t target;

	if (getrlimit(RLIMIT_STACK, &limit) != 0)
		return;
	if (limit.rlim_cur == RLIM_INFINITY)
		return;
	target = (rlim_t)128 * 1024 * 1024;
	if (limit.rlim_max != RLIM_INFINITY && limit.rlim_max < target)
		target = limit.rlim_max;
	if (target <= limit.rlim_cur)
		return;
	limit.rlim_cur = target;
	(void)setrlimit(RLIMIT_STACK, &limit);
#endif
}

int main(int argc, char **argv)
{
	int i;
	int n = ouro_export_count();
	ouro_v *entry = 0;
	if (!ouro_host_utf8_argv(&argc, &argv)) {
		fputs("ouro run: invalid Windows command line\n", stderr);
		return 73;
	}
	ouro_reserve_native_stack();
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
