/* ouro_cli.c: native host driver for a translation unit emitted by
   print_c.ouro. Resolves an export by name, applies the arguments given on
   the command line, and prints the result in ouro_show format.
   Argument marshalling only — no compiler algorithm here. */
#include "ouro_rt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

static ouro_v *find_export(const char *name)
{
	int n = ouro_export_count();
	int i;
	for (i = 0; i < n; i++) {
		if (strcmp(ouro_export_name(i), name) == 0)
			return ouro_export_value(i);
	}
	fprintf(stderr, "ouro_cli: no export named %s\n", name);
	exit(2);
	return 0;
}

/* Raw bytes, so the C and JS hosts agree on CRLF instead of one of them
   silently translating it. */
static ouro_v *file_codes(const char *path)
{
	FILE *f = fopen(path, "rb");
	unsigned char *buf;
	long len;
	ouro_v *v;
	if (f == 0) {
		fprintf(stderr, "ouro_cli: cannot open %s\n", path);
		exit(2);
	}
	if (fseek(f, 0L, SEEK_END) != 0 || (len = ftell(f)) < 0) {
		fprintf(stderr, "ouro_cli: cannot size %s\n", path);
		fclose(f);
		exit(2);
	}
	rewind(f);
	buf = (unsigned char *)malloc((unsigned long)len + 1UL);
	if (buf == 0) {
		fputs("ouro_cli: out of memory\n", stderr);
		fclose(f);
		exit(1);
	}
	if (len > 0 && fread(buf, 1, (unsigned long)len, f) != (unsigned long)len) {
		fprintf(stderr, "ouro_cli: cannot read %s\n", path);
		free(buf);
		fclose(f);
		exit(2);
	}
	fclose(f);
	v = ouro_bytes(buf, (unsigned long)len);
	free(buf);
	return v;
}

int main(int argc, char **argv)
{
	ouro_v *v;
	int i;
	if (argc < 2) {
		fputs("usage: ouro_cli <export> [--nat N | --file PATH]...\n", stderr);
		return 2;
	}
	v = find_export(argv[1]);
	for (i = 2; i < argc; i++) {
		if (strcmp(argv[i], "--nat") == 0 && i + 1 < argc) {
			v = ouro_apply(v, ouro_nat(strtoul(argv[i + 1], 0, 10)));
			i++;
		} else if (strcmp(argv[i], "--file") == 0 && i + 1 < argc) {
			v = ouro_apply(v, file_codes(argv[i + 1]));
			i++;
		} else {
			fprintf(stderr, "ouro_cli: bad argument %s\n", argv[i]);
			return 2;
		}
	}
	ouro_show_line(v);
	return 0;
}
