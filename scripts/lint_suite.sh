#!/bin/sh
# Native lint fixtures live in tools/lint. Clippy is compiler-checked in
# split modules so one unit never imports both std/json and the compiler
# frontend. Content-addressed harvest reuse lives in the lint/clippy workers.
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

"$PYTHON" "$ROOT/scripts/tool_preparation_suite.py"
"$PYTHON" "$ROOT/scripts/bench_suite.py" --quality-selftest
"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --selftest

BIN="${OURO_C_BUILD_DIR:-_build/c}/ouro-lint"
# The builder checks the complete source/compiler/build receipt. A short mtime
# list misses changes to imports and build-owned Windows process metadata.
OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tools/lint.ouro "$BIN"

out="${LINT_SUITE_OUT:-$ROOT/_build/tmp/lint_suite}"
mkdir -p "$out"
out=$(CDPATH='' cd "$out" && pwd)
quality_inputs="$out/quality-input-tests"
quality_diagnostics="$out/quality-diagnostic-tests"
semantic_perf="$out/clippy-semantic-performance"
semantic_session="$out/clippy-session-laws"
semantic_wire="$out/clippy-session-wire-laws"
session_worker="$out/ouro-clippy-session"
pkg="$out/ouro-pkg"
# Bootstrap above remains the compiler owner. Prepare independent fixture
# tools in one host process; every binary retains its full content check.
# Execution/assertion order and writable fixture isolation stay unchanged.
"$PYTHON" "$ROOT/scripts/native_tool_build.py" \
	--compiler "${OURO_C_BUILD_DIR:-_build/c}/ouro1" \
	--batch-report "$out/tool-preparation.json" \
	--tool tests/quality_input_tests.ouro "$quality_inputs" \
	--tool tests/quality_diagnostic_tests.ouro "$quality_diagnostics" \
	--tool tests/clippy_semantic/performance.ouro "$semantic_perf" \
	--tool tests/clippy_semantic/session.ouro "$semantic_session" \
	--tool tests/clippy_semantic/session_wire.ouro "$semantic_wire" \
	--tool tools/clippy/structural_main.ouro "$session_worker" \
	--tool tools/pkg/main.ouro "$pkg"
if [ ! -x "$quality_inputs" ] && [ -x "${quality_inputs}.exe" ]; then
	quality_inputs="${quality_inputs}.exe"
fi
"$quality_inputs" "$out/input-fixtures" >"$out/quality-input-tests.out"
tr -d '\r' <"$out/quality-input-tests.out" | grep -Fx 'QUALITY_INPUT_TESTS rows=22 failures=0' >/dev/null

"$quality_diagnostics" >"$out/quality-diagnostic-tests.out" 2>"$out/quality-diagnostic-tests.err"
test ! -s "$out/quality-diagnostic-tests.err"
test "$(grep -c '^ok ' "$out/quality-diagnostic-tests.out")" -eq 29

fixtures=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group lint)
"$BIN" --selftest "--out=$out" "--bad-root=$fixtures/bad" "--good-root=$fixtures/good" \
	>"$out/selftest.out" 2>"$out/selftest.err"
cat "$out/selftest.out"
test ! -s "$out/selftest.err"
tr -d '\r' <"$out/selftest.out" | grep -Fx 'bad_miss=0' >/dev/null
tr -d '\r' <"$out/selftest.out" | grep -Fx 'good_fp=0' >/dev/null

# Invalid import syntax must retain its compiler-owned diagnostic even when
# its target is absent. A dependency read failure must not mask these IDs.
for import_case in malformed:001 duplicate:002 unknown:003 reserved:004; do
	import_name=${import_case%:*}
	import_code=${import_case#*:}
	grep -F "OURO-IMP-$import_code:" "$out/bad_lint-import-$import_name.out" >/dev/null
done

# Directory discovery must reach the large fixture, and a crashed child must
# fail the public launcher instead of being reported as a successful skip.
out=$(CDPATH='' cd "$out" && pwd)
(
	cd "$fixtures"
	set +e
	sh "$ROOT/scripts/ouro1.sh" lint --deny bad >"$out/launcher-bad.out" 2>"$out/launcher-bad.err"
	st=$?
	set -e
	if [ "$st" -ne 1 ] ||
		! grep -E '^bad/large-source\.ouro:[0-9]+:[0-9]+: warning\[OURO-LINT002\]' "$out/launcher-bad.out" >/dev/null; then
		echo "LINT_SUITE: FAIL launcher missed large-source unbound diagnostic" >&2
		exit 1
	fi
	sh "$ROOT/scripts/ouro1.sh" lint --deny good >"$out/launcher-good.out" 2>"$out/launcher-good.err"
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
	# A stale injected worker must not bypass the normal rebuild boundary.
	touch -t 200001010000 "$broken/ouro-lint"
	set +e
	OURO_C_BUILD_DIR="$broken" OURO1_COMPILER="$broken/ouro1" \
		sh "$ROOT/scripts/ouro1.sh" lint good/expression-0.ouro \
		>"$out/launcher-stale.out" 2>"$out/launcher-stale.err"
	st=$?
	set -e
	if [ "$st" -eq 0 ] || [ "$st" -eq 137 ] || \
		grep -F 'simulated out of memory' "$out/launcher-stale.err" >/dev/null; then
		echo "LINT_SUITE: FAIL launcher reused a stale injected worker" >&2
		exit 1
	fi
	grep -F 'BUILD_TOOL: FAIL' "$out/launcher-stale.err" >/dev/null
)

echo "=== native lint input boundaries ==="
boundary="$out/input-boundary"
mkdir -p "$boundary/empty"
printf '%s\n' 'import "missing.ouro";' 'def ok : Type := Type;' >"$boundary/bad.ouro"
printf '%s\n' '-- import "missing.ouro";' 'def ok : Type := Type;' >"$boundary/near-miss.ouro"
sh "$ROOT/scripts/ouro1.sh" lint --deny "$boundary/near-miss.ouro" \
	>"$out/near-miss.out" 2>"$out/near-miss.err"
test ! -s "$out/near-miss.out"
test ! -s "$out/near-miss.err"
# An explicitly excluded semantic family must not even validate its executable.
OURO_LINT_SEMANTIC_EXE="$out/semantic-must-not-be-started" \
	"$BIN" --family style "$boundary/near-miss.ouro" \
	>"$out/style-only.out" 2>"$out/style-only.err"
test ! -s "$out/style-only.out"
test ! -s "$out/style-only.err"
set +e
sh "$ROOT/scripts/ouro1.sh" lint --deny "$boundary/bad.ouro" \
	>"$out/missing-import.out" 2>"$out/missing-import.err"
missing_status=$?
sh "$ROOT/scripts/ouro1.sh" lint --deny "$boundary/empty" \
	>"$out/empty-scope.out" 2>"$out/empty-scope.err"
empty_status=$?
sh "$ROOT/scripts/ouro1.sh" lint --enable-no-such-rule \
	>"$out/unknown-option.out" 2>"$out/unknown-option.err"
unknown_status=$?
set -e
test "$missing_status" -eq 1
grep -F 'missing.ouro' "$out/missing-import.err" >/dev/null
test "$empty_status" -eq 2
grep -F 'no selected source files' "$out/empty-scope.err" >/dev/null
test "$unknown_status" -eq 2
grep -F 'unknown lint option' "$out/unknown-option.err" >/dev/null

# Import scanning must preserve the root lexer diagnostic in both worker modes.
printf '%s\n' 'def text : String := "unterminated' >"$boundary/lex-malformed.ouro"
for mode in single-file batch-files; do
	set +e
	"$BIN" "--$mode" "$boundary/lex-malformed.ouro" \
		>"$out/lex-$mode.out" 2>"$out/lex-$mode.err"
	lex_status=$?
	set -e
	test "$lex_status" -eq 1
	test ! -s "$out/lex-$mode.err"
	test "$(tr -d '\r' <"$out/lex-$mode.out")" = "$boundary/lex-malformed.ouro: lex-malformed"
done

# Directory inventory, child argv and diagnostic locations must all retain
# UTF-8; renaming the same source cannot erase an unbound-name finding.
unicode_dir="$boundary/каталог с пробелами"
mkdir -p "$unicode_dir"
printf '%s\n' 'def unicode_value : Type := not_defined;' >"$unicode_dir/漢字 file.ouro"
set +e
"$BIN" --deny "$unicode_dir" >"$out/unicode.out" 2>"$out/unicode.err"
unicode_status=$?
set -e
test "$unicode_status" -eq 1
test ! -s "$out/unicode.err"
grep -F '漢字 file.ouro:1:29: warning[OURO-LINT002]' "$out/unicode.out" >/dev/null

echo "=== semantic definition scheduling parity ==="
if [ -x "${semantic_perf}.exe" ]; then
	semantic_perf="${semantic_perf}.exe"
fi
"$semantic_perf" >"$out/semantic-performance.out" 2>"$out/semantic-performance.err"
cat "$out/semantic-performance.out"
test ! -s "$out/semantic-performance.err"
test "$(grep -c '^PASS ' "$out/semantic-performance.out")" -eq 11
if grep -q '^FAIL ' "$out/semantic-performance.out"; then
	exit 1
fi

echo "=== bounded Clippy session transport and scheduling ==="
if [ -x "${semantic_session}.exe" ]; then
	semantic_session="${semantic_session}.exe"
fi
if [ -x "${session_worker}.exe" ]; then
	session_worker="${session_worker}.exe"
fi
session_lifetime=$(mktemp -d "$out/session-lifetime.XXXXXX")
"$semantic_session" "$session_lifetime" >"$out/session-laws.out" 2>"$out/session-laws.err"
test ! -s "$out/session-laws.err"
test "$(grep -c '^PASS ' "$out/session-laws.out")" -eq 26
if grep -q '^FAIL ' "$out/session-laws.out"; then
	exit 1
fi
if [ -x "${semantic_wire}.exe" ]; then
	semantic_wire="${semantic_wire}.exe"
fi
"$semantic_wire" >"$out/session-wire-laws.out" 2>"$out/session-wire-laws.err"
test ! -s "$out/session-wire-laws.err"
test "$(grep -c '^PASS ' "$out/session-wire-laws.out")" -eq 25
if grep -q '^FAIL ' "$out/session-wire-laws.out"; then
	exit 1
fi
# Fresh captures, shared imports, repeated paths and a failure in the middle.
# The observer keeps binary source frames intact under the existing limiter.
session_dir=$(mktemp -d "$out/session.XXXXXX")
mkdir -p "$session_dir/sources"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' \
	'def shared (x : Nat) : Nat := x;' >"$session_dir/sources/dep.ouro"
printf '%s\n' 'import "dep.ouro";' \
	'inductive Pick : Type := | First : Pick | Second : Pick;' \
	'def a (p : Pick) (x : Nat) : Nat := match p with | First => x | Second => x end;' \
	>"$session_dir/sources/a.ouro"
printf '%s\n' 'import "dep.ouro";' 'def b (x : Nat) : Nat := shared x;' \
	>"$session_dir/sources/b.ouro"
printf '%s\n' 'def broken : Nat := ;' >"$session_dir/sources/bad.ouro"
printf '%s\n' '["a.ouro","b.ouro","a.ouro","bad.ouro","b.ouro","a.ouro"]' \
	>"$session_dir/paths.json"
index=0
for path in a.ouro b.ouro a.ouro bad.ouro b.ouro a.ouro; do
	"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --capture \
		"$session_dir" "single-$index" "$session_worker" "$session_dir/sources" "$path"
	if [ "$path" = bad.ouro ]; then
		test "$(sed -n '2p' "$session_dir/single-$index.out")" = error
	else
		test "$(sed -n '2p' "$session_dir/single-$index.out")" = ok
	fi
	index=$((index + 1))
done
for iteration in 0 1 2 3 4 5 6 7 8 9; do
	"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --capture \
		"$session_dir" "session-$iteration" "$session_worker" --session \
		"$session_dir/sources" a.ouro b.ouro a.ouro bad.ouro b.ouro a.ouro
done
"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --compare "$session_dir"
"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --stress "$session_dir" "$session_worker"

# Public kernel types must survive a transitive compiler import. Unknown
# signature types must still fail instead of turning into unchecked stubs.
mkdir -p "$session_dir/sources/compiler"
printf '%s\n' 'inductive Entry : Type := | Empty : Entry;' \
	>"$session_dir/sources/compiler/kernel_core.ouro"
printf '%s\n' 'import "kernel_core.ouro";' 'def identity (x : Entry) : Entry := x;' \
	>"$session_dir/sources/compiler/bridge.ouro"
printf '%s\n' 'import "compiler/bridge.ouro";' 'def root (x : Entry) : Entry := identity x;' \
	>"$session_dir/sources/transitive.ouro"
printf '%s\n' 'import "compiler/bridge.ouro";' 'def root (x : Missing) : Missing := x;' \
	>"$session_dir/sources/transitive-bad.ouro"
for path in transitive transitive-bad; do
	"$PYTHON" "$ROOT/tests/clippy_semantic/session_protocol.py" --capture \
		"$session_dir" "$path" "$session_worker" "$session_dir/sources" "$path.ouro"
done
test "$(sed -n '2p' "$session_dir/transitive.out")" = ok
test "$(sed -n '2p' "$session_dir/transitive-bad.out")" = error
grep -F 'unresolved executable declaration: Missing' "$session_dir/transitive-bad.out" >/dev/null

echo "=== native lint production sources ==="
# Only the package sample needs a writable snapshot: `pkg install` vendors
# into _ouro_pkgs/. Do not copy std/compiler/tools/samples/runtime; lint the
# live trees plus that prepared copy. The app file-relative import of
# ../../../../std/io.ouro is resolved through a directory symlink. Semantic
# harvest of std/runtime.ouro then needs ../runtime/native_types.ouro beside
# that symlink, so runtime is linked the same way.
production=$(mktemp -d "$out/production.XXXXXX")
mkdir -p "$production/samples"
cp -R samples/pkg "$production/samples/"
ln -s "$ROOT/std" "$production/std"
ln -s "$ROOT/runtime" "$production/runtime"
(
	cd "$production/samples/pkg/app"
	"$pkg" install
) >"$out/production-package.log" 2>&1
set --
for entry in samples/*; do
	[ -d "$entry" ] || continue
	name=${entry##*/}
	# pkg is prepared in a writable snapshot. bench is a lint fixture
	# directory (holes in samples/bench/synthesis); core_suite is explicit.
	if [ "$name" != "pkg" ] && [ "$name" != "bench" ]; then
		set -- "$@" "$entry"
	fi
done
# One driver: language, proven style, and semantic Clippy. Sequential
# family dispatch keeps json and the compiler frontend in separate
# processes. Do not raise the 8 GiB parent / 3072 MiB Clippy caps.
sh "$ROOT/scripts/ouro1.sh" lint --deny std compiler tools "$@" \
	"$production/samples/pkg" samples/bench/core_suite.ouro

echo "=== clippy-grade native compiler check ==="
# Check the split Clippy units. Grade and structural cones stay separate so
# one unit never imports both std/json and the compiler frontend. Do not
# treat an OOM as acceptance.
for clippy_unit in \
	tools/clippy/core.ouro \
	tools/clippy/scan.ouro \
	tools/clippy/structural_main.ouro \
	tools/clippy/main.ouro; do
	clippy_stem=$(basename "$clippy_unit" .ouro)
	set +e
	sh "$ROOT/scripts/ouro1.sh" check "$clippy_unit" 60000 \
		>"$out/clippy-check-$clippy_stem.out" 2>"$out/clippy-check-$clippy_stem.err"
	clippy_check_status=$?
	set -e
	if [ "$clippy_check_status" -ne 0 ] ||
		! grep -Fx CHECK_OK "$out/clippy-check-$clippy_stem.out" >/dev/null ||
		grep -q CHECK_FAIL "$out/clippy-check-$clippy_stem.out"; then
		echo "LINT_SUITE: FAIL clippy native check $clippy_unit" >&2
		cat "$out/clippy-check-$clippy_stem.out" >&2
		cat "$out/clippy-check-$clippy_stem.err" >&2
		exit 1
	fi
done

echo "=== clippy-grade deny firewall fixtures ==="
"$PYTHON" "$ROOT/scripts/clippy_grade_suite.py" --out "$out/clippy_grade"

echo "lint_suite: OK"
