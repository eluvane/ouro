#!/usr/bin/env sh
# Compatibility launcher; ouro-test owns runtime/IO suite cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

OUT="${RUNTIME_IO_OUT:-$ROOT/_build/runtime_io}"
mkdir -p "$OUT"

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "RUNTIME_IO_SUITE: SKIP no system C compiler" >&2
	exit 0
fi

IO_SELFTEST="$OUT/ouro-io-selftest"
if ! "$CC_BIN" -O1 -std=c99 -D_POSIX_C_SOURCE=200809L \
	-Werror=implicit-function-declaration -I "$ROOT/runtime" \
	-o "$IO_SELFTEST" "$ROOT/runtime/ouro_rt.c" \
	"$ROOT/runtime/ouro_io.c" "$ROOT/runtime/ouro_io_selftest.c" \
	>"$OUT/io-selftest.build" 2>&1; then
	cat "$OUT/io-selftest.build" >&2
	echo "RUNTIME_IO_SUITE: FAIL C IO self-test build" >&2
	exit 1
fi
if [ -f "$IO_SELFTEST.exe" ]; then
	IO_SELFTEST="$IO_SELFTEST.exe"
fi
if ! "$IO_SELFTEST" >"$OUT/io-selftest.out" 2>"$OUT/io-selftest.err"; then
	cat "$OUT/io-selftest.out" >&2
	cat "$OUT/io-selftest.err" >&2
	echo "RUNTIME_IO_SUITE: FAIL C IO self-test run" >&2
	exit 1
fi
if ! grep -q 'OURO_IO_SELFTEST: PASS' "$OUT/io-selftest.out"; then
	cat "$OUT/io-selftest.out" >&2
	echo "RUNTIME_IO_SUITE: FAIL C IO self-test verdict" >&2
	exit 1
fi
echo "RUNTIME_IO_C_SELFTEST: PASS"
"$PYTHON" scripts/fs_replace_suite.py --driver "$IO_SELFTEST" --out "$OUT/source-replacement"
"$PYTHON" scripts/fs_read_suite.py --driver "$IO_SELFTEST" --mode raw --out "$OUT/source-reading"

SUITE="$OUT/ouro-test-suite"
OURO_TEST_CHECK="$ROOT/scripts/ouro1.sh"
OURO_TEST_BUILD="$ROOT/scripts/build_tool.sh"
OURO_HOSTED_COMPILER_WRAPPER="$OURO_TEST_CHECK"
export OURO_TEST_CHECK OURO_TEST_BUILD OURO_HOSTED_COMPILER_WRAPPER
if ! sh "$ROOT/scripts/build_tool.sh" tools/test/main.ouro "$SUITE" >"$OUT/suite.build" 2>&1; then
	echo "RUNTIME_IO_SUITE: FAIL native suite build" >&2
	tail -n 20 "$OUT/suite.build" >&2
	exit 1
fi

OURO_TEST_SUITE_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}OURO_TEST_SUITE_DISPLAY_OUT"
export OURO_TEST_SUITE_DISPLAY_OUT MSYS2_ENV_CONV_EXCL
FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group runtime --out "$OUT/inputs")
"$SUITE" --native-suite=runtime-io "--out=$OUT" "--fixtures=$FIXTURES" "$@" || exit $?
"$PYTHON" scripts/ouro_smith.py replay --layer surface --seed 1 \
	--case surface-1-runtime_io --out "$OUT/smith-io"

# A PE process starts Git's usr/bin/sh.exe without the launcher path setup.
# Keep the default shell discovery usable even when the inherited PATH has no
# Git directories; this is the environment used by native nested runners.
case "$(uname -s)" in
	MINGW*|MSYS*|CYGWIN*)
		(
			unset OURO_POSIX_SH
			# Intentional: the probe starts a PE helper with a stripped PATH.
			# shellcheck disable=SC2123
			PATH=/c/Windows/System32
			export PATH
			"$OUT/io_prims"
		) >"$OUT/io_prims.windows-minimal-path.out" \
			2>"$OUT/io_prims.windows-minimal-path.err" || {
			cat "$OUT/io_prims.windows-minimal-path.err" >&2
			echo "RUNTIME_IO_SUITE: FAIL Windows minimal-PATH process probe" >&2
			exit 1
		}
		tr -d '\r' <"$OUT/io_prims.windows-minimal-path.out" \
			>"$OUT/io_prims.windows-minimal-path.out.lf"
		if ! diff -u "$FIXTURES/io_prims.golden" \
			"$OUT/io_prims.windows-minimal-path.out.lf" \
			>"$OUT/io_prims.windows-minimal-path.diff" 2>&1; then
			cat "$OUT/io_prims.windows-minimal-path.diff" >&2
			echo "RUNTIME_IO_SUITE: FAIL Windows minimal-PATH process output" >&2
			exit 1
		fi
		echo "RUNTIME_IO_WINDOWS_SHELL_PATH: PASS"
		;;
esac
