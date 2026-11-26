#!/usr/bin/env sh
# Compatibility launcher; ouro-test owns user and compiler suite assertions.
set -eu
# Hosted law drivers need the same stack reserve as OuroSmith. The build
# subprocess's stack setting does not propagate back to this suite runner.
if ! ulimit -s 131072 2>/dev/null; then
	echo "TEST_SUITE: stack limit unchanged" >&2
fi
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

# Native acceptance uses an explicitly provisioned directory, never a C fallback.
NATIVE_TOOLS=""
if [ "${1:-}" = --native-tools ]; then
	if [ "$#" -lt 2 ] || [ -z "$2" ]; then
		echo "usage: sh scripts/test_suite.sh --native-tools DIR [suite options]" >&2
		exit 2
	fi
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

REQUIRE_CC=0
if [ "${1:-}" = --require-cc ]; then
	REQUIRE_CC=1
	shift
fi

SUITE_MODE="test"
DEFAULT_OUT="$ROOT/_build/test_suite"
SHARD_COMPILER_SUITE=""
COMPILER_PROBE=""

full_compiler_suite() {
	shard_seen=""
	while [ "$#" -gt 0 ]; do
		case "$1" in
		--shard)
			[ "${2:-}" = all ] || return 1
			shift
			;;
		--shard=all) ;;
		--suite-probe-failure)
			COMPILER_PROBE=--suite-probe-failure
			shift
			continue
			;;
		*) return 1 ;;
		esac
		[ -z "$shard_seen" ] || return 1
		shard_seen=1
		shift
	done
}

case "${1:-}" in
--native-build-collection)
	if [ "$#" -ne 2 ] || [ -z "$2" ]; then
		echo "usage: sh scripts/test_suite.sh --native-build-collection DRIVER.exe" >&2
		exit 2
	fi
	SUITE_MODE="native-build-collection"
	NATIVE_BUILD_DRIVER=$2
	DEFAULT_OUT="$ROOT/_build/native_build_collection"
	shift 2
	;;
--compiler-checking)
	SUITE_MODE="compiler-checking"
	DEFAULT_OUT="$ROOT/_build/compiler_check_suite"
	shift
	if full_compiler_suite "$@"; then
		SHARD_COMPILER_SUITE=1
		COMPILER_JOBS="${OURO_JOBS:-}"
	else
		OURO_JOBS=1
		OURO_FRONTEND_JOBS=1
		export OURO_JOBS OURO_FRONTEND_JOBS
	fi
	;;
esac

if [ -n "$NATIVE_TOOLS" ] && [ "$SUITE_MODE" = native-build-collection ]; then
	echo "TEST_SUITE: FAIL --native-build-collection is a separate C harness; omit --native-tools" >&2
	exit 2
fi

OUT="${TEST_SUITE_OUT:-$DEFAULT_OUT}"
mkdir -p "$OUT"
if [ -n "$SHARD_COMPILER_SUITE" ]; then
	OUT=$(mktemp -d "$OUT/run.XXXXXX")
fi

# The required test gate uses the builder's compiler settings.
if [ -z "$NATIVE_TOOLS" ] && [ "$SUITE_MODE" = test ] && [ "$REQUIRE_CC" = 1 ]; then
	if [ -z "${PYTHON:-}" ]; then
		echo "TEST_SUITE: FAIL no working Python" >&2
		exit 1
	fi
	"$PYTHON" -B - <<'PY_TEST_COMPILER'
import sys
from argparse import Namespace

sys.path.insert(0, "scripts")
from ouro_build import load_config, locate_cc

try:
    cfg = load_config(Namespace())
except (OSError, ValueError) as error:
    raise SystemExit(f"TEST_SUITE: FAIL compiler configuration: {error}") from None
try:
    locate_cc(cfg)
except SystemExit:
    raise SystemExit("TEST_SUITE: FAIL no system C compiler") from None
PY_TEST_COMPILER
elif [ -z "$NATIVE_TOOLS" ]; then
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
		[ "$(grep -c '^PRECISION_OK ' "$OUT/collection.out")" -ne 59 ] || \
		[ "$(wc -l <"$OUT/collection.out")" -ne 60 ] || \
		! grep -Fxq 'PRECISION_SUITE native-build-collection rows=59' "$OUT/collection.out"; then
		cat "$OUT/collection.err" >&2
		echo "NATIVE_BUILD_COLLECTION_SUITE: FAIL incomplete assertion protocol" >&2
		exit 1
	fi
	echo "NATIVE_BUILD_COLLECTION_SUITE: PASS cases=59 out=$OUT"
	exit 0
fi

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite test \
		--receipt "$OUT/native-candidates.json"
	SUITE="$NATIVE_TOOLS/ouro-test.exe"
else
	SUITE="$OUT/ouro-test-suite"
	OURO_TEST_CHECK="$ROOT/scripts/ouro1.sh"
	OURO_TEST_BUILD="$ROOT/scripts/build_tool.sh"
	OURO_HOSTED_COMPILER_WRAPPER="$OURO_TEST_CHECK"
	export OURO_TEST_CHECK OURO_TEST_BUILD OURO_HOSTED_COMPILER_WRAPPER
	if [ "${OURO_CI_PREPARED_TEST:-}" = 1 ]; then
		"$PYTHON" "$ROOT/scripts/compiler_shards.py" --runner "$SUITE" \
			--verify-with "${OURO_C_BUILD_DIR:-_build/c}/ouro1"
	elif ! sh "$ROOT/scripts/build_tool.sh" tools/test/main.ouro "$SUITE" >"$OUT/suite.build" 2>&1; then
		echo "TEST_SUITE: FAIL native suite build" >&2
		tail -n 20 "$OUT/suite.build" >&2
		exit 1
	fi
fi

run_suite() {
	if [ -n "$NATIVE_TOOLS" ]; then
		native_status=0
		"$@" || native_status=$?
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

cli_probe() {
	probe_name=$1
	probe_want=$2
	probe_needle=$3
	shift 3
	probe_status=0
	"$@" >"$OUT/cli-$probe_name.out" 2>"$OUT/cli-$probe_name.err" || probe_status=$?
	if [ "$probe_status" -ne "$probe_want" ] ||
		! grep -F -q "$probe_needle" "$OUT/cli-$probe_name.out" "$OUT/cli-$probe_name.err"; then
		echo "TEST_SUITE: FAIL cli probe $probe_name exit=$probe_status want=$probe_want" >&2
		cat "$OUT/cli-$probe_name.out"
		cat "$OUT/cli-$probe_name.err" >&2
		exit 1
	fi
}

mkdir -p "$OUT/cli-empty"
cli_probe help 0 "usage: ouro-test" "$SUITE" --help
cli_probe incomplete-out 2 "usage: ouro-test" "$SUITE" --out
cli_probe unknown-option 2 "usage: ouro-test" "$SUITE" --verbose "$OUT/cli-empty"
cli_probe empty-discovery 1 "test: no tests found" "$SUITE" --out "$OUT/cli-empty-out" "$OUT/cli-empty"

if [ "$SUITE_MODE" = compiler-checking ]; then
	if [ -n "$SHARD_COMPILER_SUITE" ]; then
		set -- --runner "$SUITE" --out "$OUT" --jobs "$COMPILER_JOBS"
		if [ -n "$NATIVE_TOOLS" ]; then
			set -- "$@" --native
		fi
		if [ -n "$COMPILER_PROBE" ]; then
			set -- "$@" "$COMPILER_PROBE"
		fi
		run_suite "$PYTHON" "$ROOT/scripts/compiler_shards.py" "$@"
	fi
	run_suite "$SUITE" --native-suite=compiler-checking "--out=$OUT" "$@"
fi
FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group test --out "$OUT/inputs" --stable)
run_suite "$SUITE" --native-suite=test "--out=$OUT" "--fixtures=$FIXTURES" "$@"
