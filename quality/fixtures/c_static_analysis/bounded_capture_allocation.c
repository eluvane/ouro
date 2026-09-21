#include <stdlib.h>

static int fail_next_allocation;

static void *capture_malloc(size_t size)
{
	if (fail_next_allocation) {
		fail_next_allocation = 0;
		return NULL;
	}
	return malloc(size);
}

/* Inject allocation failure into the real, private Windows capture reader. */
#define malloc capture_malloc
#include "../../../runtime/ouro_io.c"
#undef malloc

int main(int argc, char **argv)
{
	unsigned char *buf = NULL;
	unsigned long len = 0;
	uint64_t actual = 0;
	DWORD error = 0;
	FILE *file;
	int result;
	SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
	if (argc != 2 || (file = fopen(argv[1], "wb")) == NULL)
		return 1;
	if (fclose(file) != 0)
		return 1;
	result = bounded_read_file(argv[1], 0, &buf, &len, &actual, &error);
	if (result != 0 || buf == NULL || buf[0] != 0 || len != 0 || actual != 0)
		return 1;
	free(buf);
	fail_next_allocation = 1;
	result = bounded_read_file(argv[1], 0, &buf, &len, &actual, &error);
	if (remove(argv[1]) != 0 || result != 2 || error != 14 ||
	    buf != NULL || len != 0 || actual != 0 || fail_next_allocation != 0)
		return 1;
	puts("BOUNDED_CAPTURE_ALLOCATION: PASS empty output and allocation failure");
	return 0;
}
