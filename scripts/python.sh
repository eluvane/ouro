#!/usr/bin/env sh
# shellcheck disable=SC2317
# Resolve a working interpreter into PYTHON.
# SC2317: Use exit as a fallback when the shell rejects return in a script.
if [ -n "${PYTHON:-}" ]; then
	return 0 2>/dev/null || exit 0
fi
# Probe Windows candidates because a Store alias may lack an interpreter.
# Other hosts resolve the path without starting Python so check and help can
# run without it.
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
