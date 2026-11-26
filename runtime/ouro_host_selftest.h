#ifndef OURO_HOST_SELFTEST_H
#define OURO_HOST_SELFTEST_H

#include "ouro_rt.h"

static inline ouro_v *ouro_host_test_run_unit(ouro_env *env, ouro_v *work)
{
	(void)env;
	return ouro_apply(work, ouro_ctor(0, 0, 0));
}

#endif
