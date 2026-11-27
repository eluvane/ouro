/* Print one named result per export from the generated C translation unit. */
#include "ouro_rt.h"

#include <stdio.h>

int ouro_export_count(void);
const char *ouro_export_name(int i);
ouro_v *ouro_export_value(int i);

int main(void)
{
	int n = ouro_export_count();
	int i;
	for (i = 0; i < n; i++) {
		printf("%s=", ouro_export_name(i));
		ouro_show_line(ouro_export_value(i));
	}
	return 0;
}
