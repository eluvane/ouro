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

if [ -f "$FMT.exe" ]; then FMT="$FMT.exe"; fi
printf '%s\n' 'def argument_value : Nat :=0;' >"$OUT/arguments.original"
printf '%s\n' 'def argument_value : Nat := 0;' >"$OUT/arguments-clean.ouro"
argument_refusal() {
	name=$1
	shift
	cp "$OUT/arguments.original" "$OUT/arguments.ouro"
	set +e
	"$FMT" "$@" >"$OUT/arguments-$name.out" 2>"$OUT/arguments-$name.err"
	status=$?
	set -e
	test "$status" -eq 2
	test ! -s "$OUT/arguments-$name.out"
	grep -F 'fmt: invalid arguments' "$OUT/arguments-$name.err" >/dev/null
	cmp "$OUT/arguments.original" "$OUT/arguments.ouro"
}
argument_refusal unknown-value --write --unknown=1 "$OUT/arguments.ouro"
argument_refusal unknown-flag --write "$OUT/arguments.ouro" --unknown
argument_refusal unknown-short --write -x "$OUT/arguments.ouro"
argument_refusal bool-value --write=true "$OUT/arguments.ouro"
argument_refusal conflicting --check --write "$OUT/arguments.ouro"
argument_refusal conflicting-clean --check --write "$OUT/arguments-clean.ouro"
argument_refusal selftest-write --selftest --write "$OUT/arguments.ouro"
argument_refusal selftest-positional --selftest "$OUT/arguments.ouro"
argument_refusal selftest-missing --selftest --out
argument_refusal selftest-empty --selftest --out=
argument_refusal selftest-unknown --selftest --unknown=1
argument_refusal worker-write --selftest-worker=clean --write
argument_refusal mixed-workers --selftest-worker=clean --selftest-plan
argument_refusal orphan-tree-flag --tree-failed "$OUT/arguments.ouro"
argument_refusal orphan-probe-flag --selftest-probe-failure "$OUT/arguments.ouro"
SOURCE_WRITE="$OUT/quality-source-write"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tests/quality_source_write_driver.ouro "$SOURCE_WRITE" >"$OUT/source-write.build" 2>&1; then
	echo "FMT_SUITE: FAIL source transaction driver build" >&2
	tail -n 20 "$OUT/source-write.build" >&2
	exit 1
fi
if [ -f "$SOURCE_WRITE.exe" ]; then SOURCE_WRITE="$SOURCE_WRITE.exe"; fi
"$PYTHON" scripts/fs_replace_suite.py --driver "$SOURCE_WRITE" --fmt "$FMT" \
	--out "$OUT/source-transactions"

# Exercise the public IO path as well as pure formatting cases. Both UTF-8
# argv and the write target must survive spaces and non-ASCII directory names.
unicode_dir="$OUT/каталог с пробелами"
unicode_file="$unicode_dir/漢字 file.ouro"
mkdir -p "$unicode_dir"
printf '%s\n' 'def unicode_value : Nat :=0;' >"$unicode_file"
printf '%s\n' 'def unicode_value : Nat := 0;' >"$OUT/unicode.expected"
set +e
"$FMT" --check "$unicode_file" >"$OUT/unicode-check.out" 2>"$OUT/unicode-check.err"
unicode_status=$?
set -e
test "$unicode_status" -eq 1
grep -F '漢字 file.ouro: needs formatting' "$OUT/unicode-check.err" >/dev/null
"$FMT" --write "$unicode_file" >"$OUT/unicode-write.out" 2>"$OUT/unicode-write.err"
cmp "$OUT/unicode.expected" "$unicode_file"
"$FMT" --check "$unicode_file"
"$FMT" --write "$unicode_file" >"$OUT/unicode-repeat.out" 2>"$OUT/unicode-repeat.err"
test ! -s "$OUT/unicode-repeat.out"
test ! -s "$OUT/unicode-repeat.err"
cmp "$OUT/unicode.expected" "$unicode_file"

FMT_SUITE_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}FMT_SUITE_DISPLAY_OUT"
export FMT_SUITE_DISPLAY_OUT MSYS2_ENV_CONV_EXCL
PROBE=$("$FMT" --selftest-plan "--out=$OUT" "$@")
LAUNCHER="$OUT/.fmt-selftest-launcher.sh"
exec sh "$LAUNCHER" "$FMT" "$OUT" "$OUT" "$PROBE" "$LAUNCHER" "$FIXTURES"
