#include <wchar.h>
char *s = "hello \"world\"\n";
char c = 'x';
int n = 42;
wchar_t *wide = L"{ not a body } \"quoted\" \\";
int separator(int value) {
	if (value == L'/')
		return L'\\';
	return L':';
}
