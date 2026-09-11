#include <stdlib.h>

int main(void)
{
	int *value = (int *)malloc(sizeof(*value));
	if (value == 0)
		return 1;
	free(value);
	return *value;
}
