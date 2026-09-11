#include <stdlib.h>

int main(void)
{
	int *value = (int *)malloc(sizeof(*value));
	int result;
	if (value == 0)
		return 1;
	*value = 42;
	result = *value;
	free(value);
	return result == 42 ? 0 : 1;
}
