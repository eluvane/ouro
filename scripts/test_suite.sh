#!/usr/bin/env sh
# Compatibility launcher; ouro-test owns user and compiler suite assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

# Native acceptance uses an explicitly provisioned directory, never a C fallback.
NATIVE_TOOLS=""
if [ "${1:-}" = --native-tools ]; then
	[ "$#" -ge 2 ] && [ -n "$2" ] || {
		echo "usage: sh scripts/test_suite.sh --native-tools DIR [suite options]" >&2
		exit 2
	}
	NATIVE_TOOLS=$2
	case "$NATIVE_TOOLS" in
	/* | [A-Za-z]:*) ;;
	*) NATIVE_TOOLS="$ROOT/$NATIVE_TOOLS" ;;
	esac
	NATIVE_TOOLS=$(CDPATH='' cd "$NATIVE_TOOLS" && pwd -P) || {
		echo "TEST_SUITE: FAIL native candidate directory" >&2
		exit 1
	}
	shift 2
fi

SUITE_MODE="test"
DEFAULT_OUT="$ROOT/_build/test_suite"
case "${1:-}" in
--native-build-collection)
	[ "$#" -eq 2 ] && [ -n "$2" ] || {
		echo "usage: sh scripts/test_suite.sh --native-build-collection DRIVER.exe" >&2
		exit 2
	}
	SUITE_MODE="native-build-collection"
	NATIVE_BUILD_DRIVER=$2
	DEFAULT_OUT="$ROOT/_build/native_build_collection"
	shift 2
	;;
--compiler-checking)
	SUITE_MODE="compiler-checking"
	DEFAULT_OUT="$ROOT/_build/compiler_check_suite"
	OURO_JOBS=1
	OURO_FRONTEND_JOBS=1
	export OURO_JOBS OURO_FRONTEND_JOBS
	shift
	;;
esac

if [ -n "$NATIVE_TOOLS" ] && [ "$SUITE_MODE" = native-build-collection ]; then
	echo "TEST_SUITE: FAIL --native-build-collection is a separate C harness; omit --native-tools" >&2
	exit 2
fi

OUT="${TEST_SUITE_OUT:-$DEFAULT_OUT}"
mkdir -p "$OUT"

if [ -z "$NATIVE_TOOLS" ]; then
	CC_BIN="${CC:-cc}"
	command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
	if ! command -v "$CC_BIN" >/dev/null 2>&1; then
		if [ "$SUITE_MODE" = native-build-collection ]; then
			echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL no system C compiler" >&2
			exit 1
		fi
		if [ "$SUITE_MODE" = compiler-checking ]; then
			echo "COMPILER_CHECK_SUITE: FAIL no system C compiler" >&2
			exit 1
		fi
		echo "TEST_SUITE: SKIP no system C compiler" >&2
		exit 0
	fi
fi

if [ "$SUITE_MODE" = native-build-collection ]; then
	[ -x "$NATIVE_BUILD_DRIVER" ] || {
		echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL driver is not executable: $NATIVE_BUILD_DRIVER" >&2
		exit 1
	}
	SUITE="$OUT/native-build-collection"
	if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" \
		tests/native_build_collection_tests.ouro "$SUITE" >"$OUT/suite.build" 2>&1; then
		tail -n 20 "$OUT/suite.build" >&2
		echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL regression build" >&2
		exit 1
	fi
	if ! "$SUITE" "$NATIVE_BUILD_DRIVER" "$OUT" >"$OUT/collection.raw" 2>"$OUT/collection.err"; then
		cat "$OUT/collection.raw"
		cat "$OUT/collection.err" >&2
		echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL native assertions" >&2
		exit 1
	fi
	tr -d '\r' <"$OUT/collection.raw" >"$OUT/collection.out"
	cat "$OUT/collection.out"
	if [ -s "$OUT/collection.err" ] || \
		[ "$(grep -c '^PRECISION_OK ' "$OUT/collection.out")" -ne 38 ] || \
		[ "$(wc -l <"$OUT/collection.out")" -ne 39 ] || \
		! grep -Fxq 'PRECISION_SUITE native-build-collection rows=38' "$OUT/collection.out"; then
		cat "$OUT/collection.err" >&2
		echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL incomplete assertion protocol" >&2
		exit 1
	fi
	echo "NATIVE_BUILD_COLLECTION_SUITE: PASS cases=38 out=$OUT"
	exit 0
fi

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite test \
		--receipt "$OUT/native-candidates.json"
	SUITE="$NATIVE_TOOLS/ouro-test.exe"
else
	SUITE="$OUT/ouro-test-suite"
	if ! sh "$ROOT/scripts/build_tool.sh" tools/test/main.ouro "$SUITE" >"$OUT/suite.build" 2>&1; then
		echo "TEST_SUITE: FAIL native suite build" >&2
		tail -n 20 "$OUT/suite.build" >&2
		exit 1
	fi
fi

run_suite() {
	if [ -n "$NATIVE_TOOLS" ]; then
		native_status=0
		if ! "$@"; then
			native_status=$?
		fi
		"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite test \
			--receipt "$OUT/native-candidates.json" --verify
		exit "$native_status"
	fi
	exec "$@"
}

OURO_TEST_SUITE_DISPLAY_OUT="$OUT"
LINES_SUITE_OUT="$OUT/lines"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}OURO_TEST_SUITE_DISPLAY_OUT;LINES_SUITE_OUT"
export OURO_TEST_SUITE_DISPLAY_OUT LINES_SUITE_OUT MSYS2_ENV_CONV_EXCL
if [ "$SUITE_MODE" = compiler-checking ]; then
	run_suite "$SUITE" --native-suite=compiler-checking "--out=$OUT" "$@"
fi
FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group test --out "$OUT/inputs")
run_suite "$SUITE" --native-suite=test "--out=$OUT" "--fixtures=$FIXTURES" "$@"
