/* C host IO / string prims for std/runtime.ouro. Host only. */
#ifndef OURO_IO_H
#define OURO_IO_H

#include "ouro_rt.h"

void ouro_io_set_argv(int argc, char **argv);
void ouro_io_set_sandbox(int on);
/* Last `exit n` construction. prog_main returns this if the thunk
   was built but not forced (nested-IO leak). */
int ouro_io_exit_status(void);
ouro_v *ouro_io_prim(const char *name);
/* Like ouro_io_prim, but a missing prim is a hard error (exit 70), so a
   program linked against the C host cannot silently call into a null. */
ouro_v *ouro_io_prim_req(const char *name);
/* Placeholder value for a global with no runtime content (erased type
   argument); it fails loudly if a program ever applies or matches it. */
ouro_v *ouro_io_type_stub(const char *name);

#endif
