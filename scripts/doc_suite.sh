#!/usr/bin/env sh
# Compatibility launcher; ouro-doc owns documentation suite cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${DOC_SUITE_OUT:-$ROOT/_build/doc_suite}"
mkdir -p "$OUT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
FIXTURES=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group doc)

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "DOC_SUITE: SKIP no system C compiler" >&2
	exit 0
fi

DOC="$OUT/ouro-doc"
if ! sh "$ROOT/scripts/build_tool.sh" tools/doc.ouro "$DOC" >"$OUT/build.log" 2>&1; then
	echo "DOC_SUITE: FAIL build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
fi

NATIVE_OUT=$OUT
case "$NATIVE_OUT" in
	"$ROOT"/*) NATIVE_OUT=${NATIVE_OUT#"$ROOT"/} ;;
esac
DOC_SUITE_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}DOC_SUITE_DISPLAY_OUT"
export DOC_SUITE_DISPLAY_OUT MSYS2_ENV_CONV_EXCL
exec "$DOC" --selftest "--out=$NATIVE_OUT" "--fixtures=$FIXTURES" "$@"
