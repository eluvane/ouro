#include "ouro_rt.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

typedef struct {
	void *pointer;
	size_t size;
} map_allocation;

static map_allocation map_allocations[256];
static size_t map_live_bytes;
static size_t map_peak_bytes;
static size_t map_largest_request;
static unsigned long map_calls;
static unsigned long map_fail_at;
static int map_injected;
static int map_tracking;

static void map_require(int condition, const char *rule)
{
	if (!condition) {
		fprintf(stderr, "CLONE_TAB_SELFTEST: failed %s\n", rule);
		exit(1);
	}
}

static int map_attempt(void)
{
	if (!map_tracking)
		return 1;
	map_calls++;
	if (map_fail_at != 0 && map_calls == map_fail_at) {
		map_injected = 1;
		return 0;
	}
	return 1;
}

static void map_record(void *pointer, size_t size)
{
	size_t i;
	if (!map_tracking || pointer == 0)
		return;
	for (i = 0; i < sizeof map_allocations / sizeof map_allocations[0]; i++) {
		if (map_allocations[i].pointer == 0) {
			map_require(size <= SIZE_MAX - map_live_bytes, "allocation counter overflow");
			map_allocations[i].pointer = pointer;
			map_allocations[i].size = size;
			map_live_bytes += size;
			if (map_live_bytes > map_peak_bytes)
				map_peak_bytes = map_live_bytes;
			if (size > map_largest_request)
				map_largest_request = size;
			return;
		}
	}
	map_require(0, "allocation record bound");
}

static void *map_calloc(size_t count, size_t size)
{
	void *pointer;
	if (!map_attempt() || (size != 0 && count > SIZE_MAX / size))
		return 0;
	pointer = calloc(count, size);
	map_record(pointer, count * size);
	return pointer;
}

static void *map_malloc(size_t size)
{
	void *pointer;
	if (!map_attempt())
		return 0;
	pointer = malloc(size);
	map_record(pointer, size);
	return pointer;
}

static void map_free(void *pointer)
{
	size_t i;
	if (pointer != 0) {
		for (i = 0; i < sizeof map_allocations / sizeof map_allocations[0]; i++) {
			if (map_allocations[i].pointer == pointer) {
				map_live_bytes -= map_allocations[i].size;
				map_allocations[i].pointer = 0;
				map_allocations[i].size = 0;
				break;
			}
		}
	}
	free(pointer);
}

/* Include the exact owner so fault probes need no production test hook. */
#define calloc map_calloc
#define malloc map_malloc
#define free map_free
#include "../../../runtime/ouro_rt.c"
#undef calloc
#undef malloc
#undef free

static unsigned char map_keys[8192];
static unsigned char map_values[8193];

static void map_prepare(unsigned long fail_at)
{
	map_require(map_live_bytes == 0, "unreleased map allocations");
	map_calls = 0;
	map_fail_at = fail_at;
	map_injected = 0;
	map_peak_bytes = 0;
	map_largest_request = 0;
	map_tracking = 1;
}

static void map_finish(void)
{
	size_t i;
	map_require(map_live_bytes == 0, "map cleanup bytes");
	for (i = 0; i < sizeof map_allocations / sizeof map_allocations[0]; i++)
		map_require(map_allocations[i].pointer == 0, "map cleanup pointer");
	map_tracking = 0;
}

static void check_collisions(void)
{
	clone_tab table;
	unsigned long counts[64] = {0};
	unsigned long bucket = 0;
	unsigned long selected[17];
	unsigned long i;
	unsigned long found = 0;
	for (i = 0; i < sizeof map_keys; i++)
		counts[clone_hash(&map_keys[i]) & 63UL]++;
	for (i = 1; i < 64; i++)
		if (counts[i] > counts[bucket])
			bucket = i;
	for (i = 0; i < sizeof map_keys && found < 17; i++)
		if ((clone_hash(&map_keys[i]) & 63UL) == bucket)
			selected[found++] = i;
	map_require(found == 17, "collision selection");
	map_prepare(0);
	map_require(clone_tab_init(&table, 64, ouro_perm_alloc), "collision init");
	map_require(clone_tab_put(&table, 0, &map_values[0]), "null key");
	for (i = 0; i < 16; i++)
		map_require(clone_tab_put(&table, &map_keys[selected[i]], &map_values[i]), "collision insert");
	map_require(table.used == 16, "unique collision keys");
	for (i = 0; i < 16; i++)
		map_require(clone_tab_get(&table, &map_keys[selected[i]]) == &map_values[i], "collision identity");
	map_require(clone_tab_get(&table, &map_keys[selected[16]]) == 0, "colliding missing key");
	map_require(clone_tab_put(&table, &map_keys[selected[0]], &map_values[8192]), "collision update");
	map_require(table.used == 16 &&
		clone_tab_get(&table, &map_keys[selected[0]]) == &map_values[8192], "update identity");
	clone_tab_free(&table);
	map_finish();
}

static void check_growth(void)
{
	clone_tab table;
	unsigned long i;
	map_prepare(0);
	map_require(clone_tab_init(&table, 64, ouro_perm_alloc), "growth init");
	for (i = 0; i < 4096; i++)
		map_require(clone_tab_put(&table, &map_keys[i], &map_values[i]), "growth insert");
	map_require(table.used == 4096, "growth unique keys");
	for (i = 0; i < 4096; i++)
		map_require(clone_tab_get(&table, &map_keys[i]) == &map_values[i], "growth identity");
	map_require(clone_tab_get(&table, &map_keys[4096]) == 0, "growth missing key");
	map_require(map_largest_request <= 4096U * sizeof(uint32_t), "bounded allocation request");
	map_require(map_peak_bytes < 196608U, "bounded map metadata");
	clone_tab_free(&table);
	map_finish();
}

static unsigned long fault_work(unsigned long fail_at)
{
	clone_tab table;
	unsigned long inserted = 0;
	unsigned long i;
	unsigned long calls;
	int ready;
	map_prepare(fail_at);
	ready = clone_tab_init(&table, 64, ouro_perm_alloc);
	if (ready) {
		for (inserted = 0; inserted < 512; inserted++)
			if (!clone_tab_put(&table, &map_keys[inserted], &map_values[inserted]))
				break;
		map_require(table.used == inserted, "failed insert count");
		for (i = 0; i < inserted; i++)
			map_require(clone_tab_get(&table, &map_keys[i]) == &map_values[i], "failure retained prefix");
		map_require(clone_tab_get(&table, &map_keys[inserted]) == 0, "failed key not published");
	}
	if (fail_at == 0)
		map_require(ready && inserted == 512, "fault-free control");
	else
		map_require(map_injected && map_calls == fail_at &&
			(!ready || inserted < 512), "first allocator failure");
	calls = map_calls;
	clone_tab_free(&table);
	map_finish();
	return calls;
}

static void check_allocator_failures(void)
{
	unsigned long calls = fault_work(0);
	unsigned long i;
	map_require(calls > 4, "allocation paths reached");
	for (i = 1; i <= calls; i++) {
		(void)fault_work(i);
		(void)fault_work(0);
	}
}

static void check_overflow(void)
{
	clone_tab table;
	unsigned long cap;
	uint32_t used;
	map_prepare(0);
	map_require(!clone_tab_init(&table, 0, ouro_perm_alloc), "zero capacity");
	map_require(!clone_tab_init(&table, 3, ouro_perm_alloc), "non-power capacity");
	map_require(!clone_tab_init(&table, ULONG_MAX, ouro_perm_alloc), "invalid capacity");
	{
		unsigned long candidate = ULONG_MAX / 2UL + 1UL;
		size_t count = (size_t)candidate;
		if ((unsigned long)count != candidate || count > SIZE_MAX / sizeof(uint32_t))
			map_require(!clone_tab_init(&table, candidate, ouro_perm_alloc), "head size overflow");
	}
	map_require(map_calls == 0, "invalid capacity allocation");
	map_require(clone_tab_init(&table, 64, ouro_perm_alloc), "overflow control init");
	map_require(clone_tab_put(&table, &map_keys[0], &map_values[0]), "overflow control insert");
	cap = table.cap;
	table.cap = ULONG_MAX / 2UL + 1UL;
	map_require(!clone_tab_grow(&table), "capacity overflow rejection");
	map_require(clone_tab_want(&table) == ULONG_MAX, "capacity overflow diagnostic");
	table.cap = cap;
	used = table.used;
	table.used = UINT32_MAX;
	map_require(!clone_tab_put(&table, &map_keys[1], &map_values[1]), "index exhaustion");
	table.used = used;
	map_require(clone_tab_get(&table, &map_keys[0]) == &map_values[0], "overflow retained identity");
	clone_tab_free(&table);
	map_finish();
}

static ouro_v *capture_identity(ouro_env *env, ouro_v *argument)
{
	(void)argument;
	return env->v;
}

static void check_scoped_scratch(void)
{
	static const unsigned int widths[] = {1U, 63U, 64U, 127U, 128U, 255U, 256U};
	static const unsigned char caller_bytes[] = {0, 128, 255};
	ouro_v *caller = ouro_packed(caller_bytes, sizeof caller_bytes);
	size_t case_index;
	for (case_index = 0; case_index < sizeof widths / sizeof widths[0]; case_index++) {
		unsigned int width = widths[case_index];
		ouro_v *fields[259];
		ouro_heap_context *context = ouro_heap_context_enter();
		ouro_v *root;
		ouro_v *retained;
		unsigned int i;
		for (i = 0; i < width; i++) {
			unsigned int bank = i % 3U;
			unsigned char bytes[] = {0, (unsigned char)i, (unsigned char)(i >> 8), 255};
			if (bank != 0) {
				ouro_perm_select((int)bank - 1);
				ouro_perm_begin();
			}
			fields[i] = ouro_packed(bytes, sizeof bytes);
			if (bank != 0)
				ouro_perm_end();
		}
		fields[width] = fields[0];
		fields[width + 1U] = fields[width - 1U];
		fields[width + 2U] = caller;
		root = ouro_ctor(23, (int)width + 3, fields);
		map_prepare(0);
		retained = ouro_heap_context_leave(context, root);
		map_require(width < 64U ? map_calls == 0 : map_calls > 0,
			"scoped clone inline allocation boundary");
		map_finish();
		map_require(retained != 0 && retained->tag == 23 && retained->n == (int)width + 3,
			"scoped clone root survived");
		map_require(OURO_F(retained, width) == OURO_F(retained, 0) &&
			OURO_F(retained, width + 1U) == OURO_F(retained, width - 1U) &&
			OURO_F(retained, width + 2U) == caller, "scoped clone shared identities");
		for (i = 0; i < width; i++) {
			ouro_v *value = OURO_F(retained, i);
			unsigned char bytes[] = {0, (unsigned char)i, (unsigned char)(i >> 8), 255};
			map_require(value != 0 && value->tag == OURO_TAG_BYTES &&
				value->n == (int)sizeof bytes && memcmp(value->u.s, bytes, sizeof bytes) == 0,
				"scoped clone packed bytes survived bank release");
		}
	}
}

static void check_graph_lifetime(void)
{
	ouro_v *fields[4101];
	ouro_v *cycle = ouro_ctor(19, 2, (ouro_v *[]){0, 0});
	ouro_env *environment = ouro_cons(0, 0);
	ouro_v *closure = ouro_clos(capture_identity, environment);
	ouro_v *thunk = ouro_thunk(capture_identity, environment);
	ouro_v *marker;
	ouro_v *retained;
	unsigned long i;
	environment->v = closure;
	OURO_F(cycle, 0) = cycle;
	OURO_F(cycle, 1) = closure;
	ouro_static_begin();
	marker = ouro_ctor(77, 0, 0);
	ouro_static_end();
	fields[0] = cycle;
	fields[1] = cycle;
	fields[2] = closure;
	fields[3] = thunk;
	for (i = 0; i < 4096; i++)
		fields[4 + i] = ouro_nat(i);
	fields[4100] = marker;
	retained = ouro_keep(ouro_ctor(23, 4101, fields));
	map_require(retained != 0 && retained->tag == 23 && retained->n == 4101, "full wide survivor");
	cycle = OURO_F(retained, 0);
	closure = OURO_F(retained, 2);
	thunk = OURO_F(retained, 3);
	map_require(cycle != 0 && cycle->tag == 19 && cycle->n == 2 && closure != 0 && thunk != 0,
		"survivor arms");
	map_require(cycle == OURO_F(retained, 1) && OURO_F(cycle, 0) == cycle &&
		OURO_F(cycle, 1) == closure, "constructor cycle and sharing");
	map_require(closure->tag == OURO_TAG_CLOS && thunk->tag == OURO_TAG_THUNK &&
		closure->u.c.fn == capture_identity && thunk->u.c.fn == capture_identity &&
		closure->u.c.env != 0 && closure->u.c.env == thunk->u.c.env && closure->u.c.env->v == closure &&
		closure->u.c.env->next == 0, "full capture cycle and sharing");
	map_require(ouro_apply(closure, ouro_nat(0)) == closure, "retained callback");
	for (i = 0; i < 4096; i++) {
		ouro_v *value = OURO_F(retained, 4 + i);
		map_require(value != 0 && value->tag == OURO_TAG_NAT &&
			value->n == (int)i, "full survivor scalar fields");
	}
	map_require(OURO_F(retained, 4100) == marker, "static identity");
	retained = ouro_keep(retained);
	map_require(retained != 0 && retained->tag == 23 && retained->n == 4101, "second full survivor");
	closure = OURO_F(retained, 2);
	thunk = OURO_F(retained, 3);
	map_require(closure != 0 && thunk != 0 && closure->tag == OURO_TAG_CLOS &&
		thunk->tag == OURO_TAG_THUNK && closure->u.c.env != 0 &&
		closure->u.c.env == thunk->u.c.env && closure->u.c.env->v == closure &&
		ouro_apply(closure, ouro_nat(0)) == closure, "second capture lifetime");
	for (i = 0; i < 4096; i++) {
		ouro_v *value = OURO_F(retained, 4 + i);
		map_require(value != 0 && value->tag == OURO_TAG_NAT && value->n == (int)i,
			"second survivor scalar fields");
	}
	map_require(retained != 0 && OURO_F(OURO_F(retained, 0), 0) == OURO_F(retained, 0) &&
		OURO_F(retained, 0) == OURO_F(retained, 1) &&
		OURO_F(retained, 4100) == marker, "second bank lifetime");
}

int main(int argc, char **argv)
{
	if (argc == 2) {
		if (strcmp(argv[1], "fatal-cycle") == 0) {
			clone_tab table;
			map_prepare(0);
			map_require(clone_tab_init(&table, 1, ouro_perm_alloc), "fatal cycle init");
			map_require(clone_tab_put(&table, &map_keys[0], &map_values[0]), "fatal cycle insert");
			clone_tab_chunk(&table, 1)->next[0] = 1;
			(void)clone_tab_get(&table, &map_keys[1]);
		} else if (strcmp(argv[1], "fatal-index") == 0) {
			clone_tab table;
			map_prepare(0);
			map_require(clone_tab_init(&table, 64, ouro_perm_alloc), "fatal index init");
			table.heads[clone_hash(&map_keys[0]) & 63UL] = UINT32_MAX;
			(void)clone_tab_get(&table, &map_keys[0]);
		} else if (strcmp(argv[1], "fatal-init") == 0 || strcmp(argv[1], "fatal-entry") == 0) {
			ouro_v *source = ouro_ctor(OURO_NULLARY_CACHE, 0, 0);
			(void)ouro_perm_alloc(8);
			map_prepare(strcmp(argv[1], "fatal-init") == 0 ? 1 : 2);
			(void)ouro_clone_perm_deep(source);
		} else {
			fputs("CLONE_TAB_SELFTEST: unsupported mode\n", stderr);
			return 2;
		}
		map_require(0, "fatal mode returned");
	}
	map_require(argc == 1, "argument count");
	check_collisions();
	check_growth();
	check_allocator_failures();
	check_overflow();
	check_scoped_scratch();
	check_graph_lifetime();
	fputs("CLONE_TAB_SELFTEST: passed\n", stdout);
	return 0;
}
