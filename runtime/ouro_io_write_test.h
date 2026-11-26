#ifndef OURO_IO_WRITE_TEST_H
#define OURO_IO_WRITE_TEST_H

#include <stdio.h>

size_t ouro_write_test_fwrite(const void *data, size_t size, size_t count, FILE *stream);
int ouro_write_test_fclose(FILE *stream);
int ouro_write_test_ferror(FILE *stream);

#define fwrite ouro_write_test_fwrite
#define fclose ouro_write_test_fclose
#ifdef ferror
#undef ferror
#endif
#define ferror ouro_write_test_ferror

#endif
