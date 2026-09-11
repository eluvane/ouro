#!/bin/sh
# Native lint fixtures live in tools/lint; Python remains the Clippy-grade host reference.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
ulimit -s unlimited 2>/dev/null || true
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${PYTHON:-}" ]; then
	echo "LINT_SUITE: FAIL no working Python" >&2
	exit 127
fi

BIN="${OURO_C_BUILD_DIR:-_build/c}/ouro-lint"
if [ -e "$BIN" ]; then
	case "$(uname -s 2>/dev/null || echo unknown)" in
	MINGW*|MSYS*|CYGWIN*|Windows_NT*)
		file "$BIN" 2>/dev/null | grep -qi 'PE32' || rm -f "$BIN"
		;;
	Linux)
		file "$BIN" 2>/dev/null | grep -qi 'ELF' || rm -f "$BIN"
		;;
	esac
fi
if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/lint.ouro" "$ROOT/tools/lint_host.ouro" "$ROOT/tools/lint_names.ouro" \
	"$ROOT/compiler/lint.ouro" -newer "$BIN" -print -quit 2>/dev/null)" ]; then
	OURO_BUILD_TOOL_MODE=native \
		sh "$ROOT/scripts/build_tool.sh" tools/lint.ouro "$BIN"
fi

out="${LINT_SUITE_OUT:-$ROOT/_build/tmp/lint_suite}"
mkdir -p "$out"
fixtures=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group lint)
"$BIN" --selftest "--out=$out" "--bad-root=$fixtures/bad" "--good-root=$fixtures/good"

# Directory discovery must reach the large fixture, and a crashed child must
# fail the public launcher instead of being reported as a successful skip.
out=$(CDPATH='' cd "$out" && pwd)
(
	cd "$fixtures"
	set +e
	sh "$ROOT/scripts/ouro1.sh" lint bad >"$out/launcher-bad.out" 2>"$out/launcher-bad.err"
	st=$?
	set -e
	if [ "$st" -ne 1 ] ||
		! grep -E '^bad/large-source\.ouro:[0-9]+:[0-9]+: warning\[OURO-LINT002\]' "$out/launcher-bad.out" >/dev/null; then
		echo "LINT_SUITE: FAIL launcher missed large-source unbound diagnostic" >&2
		exit 1
	fi
	sh "$ROOT/scripts/ouro1.sh" lint good >"$out/launcher-good.out" 2>"$out/launcher-good.err"
	if [ -s "$out/launcher-good.out" ] || [ -s "$out/launcher-good.err" ]; then
		echo "LINT_SUITE: FAIL launcher reported a clean fixture" >&2
		exit 1
	fi
	set +e
	sh "$ROOT/scripts/ouro1.sh" lint good/_build/ignored.ouro \
		>"$out/launcher-explicit.out" 2>"$out/launcher-explicit.err"
	st=$?
	set -e
	if [ "$st" -ne 1 ] || ! grep -F 'OURO-LINT002' "$out/launcher-explicit.out" >/dev/null; then
		echo "LINT_SUITE: FAIL explicit file was hidden by directory exclusions" >&2
		exit 1
	fi
	grep -F 'bad/unsupported-mutual.ouro: parse-fail' "$out/launcher-bad.out" >/dev/null || {
		echo "LINT_SUITE: FAIL parser rejection was masked" >&2
		exit 1
	}
	broken="$out/launcher-failure"
	mkdir -p "$broken"
	printf '%s\n' '#!/bin/sh' 'echo "simulated out of memory" >&2' 'exit 137' >"$broken/ouro-lint"
	printf '%s\n' '#!/bin/sh' 'exit 99' >"$broken/ouro1"
	chmod +x "$broken/ouro-lint" "$broken/ouro1"
	set +e
	OURO_C_BUILD_DIR="$broken" OURO1_COMPILER="$broken/ouro1" \
		sh "$ROOT/scripts/ouro1.sh" lint good/expression-0.ouro \
		>"$out/launcher-failure.out" 2>"$out/launcher-failure.err"
	st=$?
	set -e
	if [ "$st" -ne 137 ] || ! grep -F 'simulated out of memory' "$out/launcher-failure.err" >/dev/null; then
		echo "LINT_SUITE: FAIL launcher masked child failure" >&2
		exit 1
	fi
)

echo "=== native lint production sources ==="
sh "$ROOT/scripts/ouro1.sh" lint std compiler tools samples samples/bench/core_suite.ouro

echo "=== clippy-grade deny firewall fixtures ==="
"$PYTHON" "$ROOT/scripts/clippy_grade_suite.py" --out "$out/clippy_grade"

echo "=== clippy-grade project discovery (warn-only production scan) ==="
"$PYTHON" "$ROOT/scripts/clippy_grade_firewall.py" \
	--profile project \
	--warn-only \
	--scope std \
	--scope compiler \
	--scope tools/analyze \
	--scope tools \
	--scope samples \
	--report "$out/clippy_grade_project.json" \
	--sarif "$out/clippy_grade_project.sarif"

echo "lint_suite: OK"
