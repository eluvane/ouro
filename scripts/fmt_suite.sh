#!/usr/bin/env sh
# Compatibility launcher; ouro-fmt owns formatter suite cases and assertions.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${FMT_SUITE_OUT:-$ROOT/_build/fmt_suite}"
mkdir -p "$OUT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
FIXTURES=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group fmt)

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "FMT_SUITE: SKIP no system C compiler" >&2
	exit 0
fi

FMT="$OUT/ouro-fmt"
# Native selftest modes must not resolve a stale Python host shim from an older run.
rm -f "$FMT" "$FMT.exe"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tools/fmt.ouro "$FMT" >"$OUT/build.log" 2>&1; then
	echo "FMT_SUITE: FAIL build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
fi

FMT_SUITE_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}FMT_SUITE_DISPLAY_OUT"
export FMT_SUITE_DISPLAY_OUT MSYS2_ENV_CONV_EXCL
PROBE=$("$FMT" --selftest-plan "--out=$OUT" "$@")
LAUNCHER="$OUT/.fmt-selftest-launcher.sh"
exec sh "$LAUNCHER" "$FMT" "$OUT" "$OUT" "$PROBE" "$LAUNCHER" "$FIXTURES"
