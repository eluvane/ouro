#!/usr/bin/env sh
# Compatibility launcher; ouro-fix owns autofix suite cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${FIX_SUITE_OUT:-$ROOT/_build/fix_suite}"
mkdir -p "$OUT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
FIXTURES=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group fix)

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "FIX_SUITE: SKIP no system C compiler" >&2
	exit 0
fi

FIX="$OUT/ouro-fix"
rm -f "$FIX" "$FIX.exe"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tools/fix/main.ouro "$FIX" >"$OUT/build.log" 2>&1; then
	echo "FIX_SUITE: FAIL build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
fi

exec "$FIX" --selftest "--out=$OUT" "--fixtures=$FIXTURES" "$@"
