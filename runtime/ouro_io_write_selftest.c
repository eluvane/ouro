#include "ouro_io.h"
#include "ouro_rt.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *write_mode;
static FILE *write_stream;
static unsigned long write_calls;
static unsigned long close_calls;
static unsigned long ferror_calls;

static int mode_is(const char *name)
{
	return strcmp(write_mode, name) == 0;
}

static void report_counts(void)
{
	fprintf(stderr, "WRITE_FAULT_COUNTS writes=%lu ferrors=%lu closes=%lu\n", write_calls, ferror_calls, close_calls);
}

size_t ouro_write_test_fwrite(const void *data, size_t size, size_t count, FILE *stream)
{
	size_t actual;

	if (stream == stdout || stream == stderr)
		return fwrite(data, size, count, stream);
	if (write_stream == 0)
		write_stream = stream;
	if (stream != write_stream)
		return fwrite(data, size, count, stream);
	write_calls++;
	if (mode_is("write-zero") || mode_is("write-close-error")) {
		errno = EIO;
		return 0;
	}
	if (mode_is("write-short")) {
		actual = fwrite(data, size, count == 0 ? 0 : count - 1U, stream);
		errno = EIO;
		return actual;
	}
	return fwrite(data, size, count, stream);
}

int ouro_write_test_fclose(FILE *stream)
{
	int status;

	if (stream != write_stream)
		return fclose(stream);
	close_calls++;
	status = fclose(stream);
	if (mode_is("close-error") || mode_is("empty-close-error") || mode_is("write-close-error")) {
		errno = EIO;
		return EOF;
	}
	return status;
}

int ouro_write_test_ferror(FILE *stream)
{
	if (stream != write_stream)
		return ferror(stream);
	ferror_calls++;
	if (mode_is("full-ferror") || mode_is("empty-ferror"))
		return 1;
	return ferror(stream);
}

int main(int argc, char **argv)
{
	static const unsigned char payload[] = {65, 0, 255, 128, 13, 10, 90};
	ouro_v *content;
	ouro_v *action;
	ouro_v *unit;

	if (argc != 3)
		return 2;
	write_mode = argv[1];
	if (!mode_is("valid") && !mode_is("empty") && !mode_is("write-zero") &&
	    !mode_is("write-short") && !mode_is("close-error") &&
	    !mode_is("empty-close-error") && !mode_is("write-close-error") &&
	    !mode_is("full-ferror") && !mode_is("empty-ferror"))
		return 2;
	if (atexit(report_counts) != 0)
		return 2;
	ouro_rt_warmup();
	content = mode_is("empty") || mode_is("empty-close-error") ||
		mode_is("empty-ferror")
		? ouro_packed((const unsigned char *)"", 0)
		: ouro_packed(payload, sizeof payload);
	action = ouro_apply(ouro_io_prim_req("prim_fs_write_file"), ouro_str(argv[2]));
	action = ouro_apply(action, content);
	unit = ouro_apply(action, ouro_ctor(0, 0, 0));
	if (unit == 0 || unit->tag != 0 || unit->n != 0)
		return 91;
	return 0;
}
