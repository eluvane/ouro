#!/usr/bin/env sh
# Compatibility launcher; ouro-test owns sample cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

# Native acceptance uses an explicitly provisioned directory, never a C fallback.
NATIVE_TOOLS=""
if [ "${1:-}" = --native-tools ]; then
	if [ "$#" -lt 2 ] || [ -z "$2" ]; then
		echo "usage: sh scripts/samples_suite.sh --native-tools DIR [suite options]" >&2
		exit 2
	fi
	NATIVE_TOOLS=$2
	case "$NATIVE_TOOLS" in
	/* | [A-Za-z]:*) ;;
	*) NATIVE_TOOLS="$ROOT/$NATIVE_TOOLS" ;;
	esac
	NATIVE_TOOLS=$(CDPATH='' cd "$NATIVE_TOOLS" && pwd -P) || {
		echo "SAMPLES_SUITE: FAIL native candidate directory" >&2
		exit 1
	}
	shift 2
fi

OUT="${SAMPLES_SUITE_OUT:-$ROOT/_build/samples_suite}"
mkdir -p "$OUT"

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite samples \
		--receipt "$OUT/native-candidates.json"
	SUITE="$NATIVE_TOOLS/ouro-test.exe"
else
	CC_BIN="${CC:-cc}"
	command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
	if ! command -v "$CC_BIN" >/dev/null 2>&1; then
		echo "SAMPLES_SUITE: SKIP no system C compiler" >&2
		exit 0
	fi

	SUITE="$OUT/ouro-test-suite"
	OURO_TEST_CHECK="$ROOT/scripts/ouro1.sh"
	OURO_TEST_BUILD="$ROOT/scripts/build_tool.sh"
	OURO_HOSTED_COMPILER_WRAPPER="$OURO_TEST_CHECK"
	export OURO_TEST_CHECK OURO_TEST_BUILD OURO_HOSTED_COMPILER_WRAPPER
	if ! sh "$ROOT/scripts/build_tool.sh" tools/test/main.ouro "$SUITE" >"$OUT/suite.build" 2>&1; then
		echo "SAMPLES_SUITE: FAIL native suite build" >&2
		tail -n 20 "$OUT/suite.build" >&2
		exit 1
	fi
fi

# Check the actual native selector: its two shards must cover the inventory
# exactly once and balance native builds separately from check-only cases.
"$SUITE" --native-suite=samples --list >"$OUT/cases-all.txt"
"$SUITE" --native-suite=samples --list --shard=1/2 >"$OUT/cases-1.txt"
"$SUITE" --native-suite=samples --list --shard=2/2 >"$OUT/cases-2.txt"
LC_ALL=C sort "$OUT/cases-all.txt" >"$OUT/cases-expected.txt"
LC_ALL=C sort -u "$OUT/cases-all.txt" >"$OUT/cases-unique.txt"
LC_ALL=C sort "$OUT/cases-1.txt" "$OUT/cases-2.txt" >"$OUT/cases-union.txt"
cmp "$OUT/cases-expected.txt" "$OUT/cases-unique.txt"
cmp "$OUT/cases-expected.txt" "$OUT/cases-union.txt"
awk 'FNR == NR { left[$2]++; next } { right[$2]++ }
  END { for (kind in left) if (left[kind] < right[kind] || left[kind] > right[kind] + 1) exit 1;
        if (left["native"] == 0 || right["native"] == 0 || left["check"] == 0 || right["check"] == 0) exit 1 }' \
	"$OUT/cases-1.txt" "$OUT/cases-2.txt"
for bad in --shard=0/2 --shard=3/2 --shard=1/3 --shard= --shard --unknown; do
	if "$SUITE" --native-suite=samples --list "$bad" >"$OUT/shard-invalid.log" 2>&1; then
		echo "SAMPLES_SUITE: FAIL accepted $bad" >&2
		exit 1
	else
		code=$?
		if [ "$code" -ne 2 ]; then
			echo "SAMPLES_SUITE: FAIL invalid shard exited $code instead of 2" >&2
			exit 1
		fi
	fi
done

run_suite() {
	if [ -n "$NATIVE_TOOLS" ]; then
		native_status=0
		"$@" || native_status=$?
		"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite samples \
			--receipt "$OUT/native-candidates.json" --verify
		exit "$native_status"
	fi
	exec "$@"
}

OURO_TEST_SUITE_DISPLAY_OUT="$OUT"
OURO_TEST_STDIN_ADAPTER="$ROOT/scripts/process_stdin.sh"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}OURO_TEST_SUITE_DISPLAY_OUT;OURO_TEST_STDIN_ADAPTER"
export OURO_TEST_SUITE_DISPLAY_OUT OURO_TEST_STDIN_ADAPTER MSYS2_ENV_CONV_EXCL
run_suite "$SUITE" --native-suite=samples "--out=$OUT" "$@"
