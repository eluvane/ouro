#!/usr/bin/env sh
# Compatibility launcher; ouro-lines owns the self-test cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${LINES_SUITE_OUT:-$ROOT/_build/lines_suite}"
mkdir -p "$OUT"

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "LINES_SUITE: SKIP no system C compiler" >&2
	exit 0
fi

LINES="$OUT/ouro-lines"
sh "$ROOT/scripts/build_tool.sh" tools/lines.ouro "$LINES" >"$OUT/build.log" 2>&1 || {
	echo "LINES_SUITE: FAIL build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
}

LINES_SUITE_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}LINES_SUITE_DISPLAY_OUT"
export LINES_SUITE_DISPLAY_OUT MSYS2_ENV_CONV_EXCL
exec "$LINES" --selftest "--out=$OUT"
