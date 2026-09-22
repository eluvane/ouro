#!/usr/bin/env sh
# shellcheck disable=SC2317
# Resolve a working interpreter into PYTHON.
# SC2317: `return || exit` is the sourced-or-executed seam; one arm is live
# depending on how this file is invoked.
if [ -n "${PYTHON:-}" ]; then
	return 0 2>/dev/null || exit 0
fi
# Windows Store `python3` aliases can lack an interpreter, so probe it only on
# Windows. Elsewhere, language_speed_simplicity_suite puts a failing `python3`
# first on PATH to prove check/help do not need Python.
_probe=0
case "$(uname -s 2>/dev/null || echo unknown)" in
MINGW*|MSYS*|CYGWIN*|Windows_NT*) _probe=1 ;;
esac
for _ouro_py in python3 python; do
	command -v "$_ouro_py" >/dev/null 2>&1 || continue
	if [ "$_probe" -eq 1 ]; then
		"$_ouro_py" -c "import sys" >/dev/null 2>&1 || continue
	fi
	PYTHON=$_ouro_py
	export PYTHON
	unset _ouro_py
	return 0 2>/dev/null || exit 0
done
unset _ouro_py
