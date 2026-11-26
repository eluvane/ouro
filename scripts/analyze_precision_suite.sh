#!/usr/bin/env sh
# Precision-hardening analyzer smoke suite: native runner + pure-core check gates.
# Diagnostic fixtures retain their line-by-line goldens. Native precision
# assertions additionally check exact issue lists, safe output and fixpoints.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT_DIR="${OUT_DIR:-_build/analyze_precision}"
mkdir -p "$OUT_DIR"
OUT_DIR=$(CDPATH='' cd "$OUT_DIR" && pwd)
GOLDEN_DIR="tests/analyze/golden"

REGEN=0
for arg in "$@"; do
	case "$arg" in
	--regen) REGEN=1 ;;
	*)
		echo "usage: sh scripts/analyze_precision_suite.sh [--regen]" >&2
		exit 2
		;;
	esac
done

# run NAME CMD...: stdout to $OUT_DIR/NAME.out, stderr to NAME.err, status in $st.
# Native binaries on Windows hosts emit CRLF; goldens are LF.
run_case() {
	name=$1
	shift
	set +e
	"$@" >"$OUT_DIR/$name.raw" 2>"$OUT_DIR/$name.err"
	st=$?
	set -e
	tr -d '\r' <"$OUT_DIR/$name.raw" >"$OUT_DIR/$name.out"
}

fail_case() {
	name=$1
	shift
	cat "$OUT_DIR/$name.out" >&2
	cat "$OUT_DIR/$name.err" >&2
	echo "ANALYZE_SUITE_FAIL $name $*" >&2
	exit 1
}

# check_golden NAME: stdout of the last run must equal $GOLDEN_DIR/NAME.txt.
check_golden() {
	name=$1
	golden="$GOLDEN_DIR/$name.txt"
	if [ "$REGEN" -eq 1 ]; then
		cp "$OUT_DIR/$name.out" "$golden"
		echo "ANALYZE_SUITE_REGEN $name"
		return 0
	fi
	if [ ! -f "$golden" ]; then
		fail_case "$name" "missing golden $golden (run with --regen)"
	fi
	if ! diff -u "$golden" "$OUT_DIR/$name.out" >"$OUT_DIR/$name.diff"; then
		cat "$OUT_DIR/$name.diff" >&2
		echo "ANALYZE_SUITE_FAIL $name output differs from $golden" >&2
		exit 1
	fi
}

# expect_ok NAME CMD...: exit 0 and an ANALYZE_OK banner.
expect_ok() {
	name=$1
	shift
	run_case "$name" "$@"
	[ "$st" -eq 0 ] || fail_case "$name" "expected ok, exit=$st"
	grep -q '^ANALYZE_OK ' "$OUT_DIR/$name.out" || fail_case "$name" "missing ANALYZE_OK"
}

# expect_codes NAME "CODE..." CMD...: nonzero exit, every code reported,
# no ANALYZE_OK banner.
expect_codes() {
	name=$1
	codes=$2
	shift 2
	run_case "$name" "$@"
	[ "$st" -ne 0 ] || fail_case "$name" "expected diagnostics $codes"
	for code in $codes; do
		grep -q "$code" "$OUT_DIR/$name.out" || fail_case "$name" "missing $code"
	done
	if grep -q '^ANALYZE_OK ' "$OUT_DIR/$name.out"; then
		fail_case "$name" "ANALYZE_OK printed together with diagnostics"
	fi
}

# golden_ok / golden_codes: the expectation plus the golden comparison.
golden_ok() {
	expect_ok "$@"
	check_golden "$1"
}

golden_codes() {
	expect_codes "$@"
	check_golden "$1"
}

# Host-bound argv/verdict checks use stand-in processes, not stand-in analysis.
# They run before the separate, mandatory native-core and end-to-end checks.
check_style_launcher() (
	launcher_dir=$(mktemp -d "$OUT_DIR/style-launcher.XXXXXX")
	launcher_dir=$(CDPATH='' cd "$launcher_dir" && pwd)
	trap 'rm -rf "$launcher_dir"' EXIT
	mkdir -p "$launcher_dir/scripts" "$launcher_dir/_build/c"
	printf '%s\n' 'PYTHON=' >"$launcher_dir/scripts/python.sh"
	printf '%s\n' '#!/usr/bin/env sh' 'exit 99' >"$launcher_dir/_build/c/ouro1"
	cat >"$launcher_dir/_build/c/ouro-analyze" <<'BASE'
#!/usr/bin/env sh
printf '%s\000' "$@" >"$LAUNCHER_DIR/base.args"
printf '%s\n' "$BASE_TEXT"
exit "$BASE_STATUS"
BASE
	cat >"$launcher_dir/_build/c/ouro-analyze-drive" <<'DRIVE'
#!/usr/bin/env sh
printf '%s\000' "$@" >"$LAUNCHER_DIR/drive.args"
printf '%s\n' "$DRIVE_TEXT"
exit "$DRIVE_STATUS"
DRIVE
	chmod +x "$launcher_dir/_build/c/ouro1" "$launcher_dir/_build/c/ouro-analyze" \
		"$launcher_dir/_build/c/ouro-analyze-drive"
	base_clean='ANALYZE_OK profile=strict files=1'
	drive_clean='ANALYZE_DRIVE files=1 findings=0 rejected=0 families=dataflow,metrics,simplify,perf,naming'
	base_text=$base_clean
	drive_text=$drive_clean
	base_status=0
	drive_status=0
	launcher_rows=0

	launcher_run() {
		launcher_name=$1
		launcher_expected=$2
		shift 2
		rm -f "$launcher_dir/base.args" "$launcher_dir/drive.args"
		run_case "$launcher_name" env OURO_ROOT="$launcher_dir" \
			OURO_C_BUILD_DIR="$launcher_dir/_build/c" \
			OURO1_COMPILER="$launcher_dir/_build/c/ouro1" \
			OURO_ANALYZE_ALLOW_UNBOUNDED=1 LAUNCHER_DIR="$launcher_dir" \
			BASE_STATUS="$base_status" DRIVE_STATUS="$drive_status" \
			BASE_TEXT="$base_text" DRIVE_TEXT="$drive_text" \
			"${OURO_LAUNCHER_TEST_SHELL:-sh}" "$ROOT/scripts/ouro1.sh" analyze "$@"
		[ "$st" -eq "$launcher_expected" ] || \
			fail_case "$launcher_name" "expected exit=$launcher_expected, got $st"
		if [ "$st" -ne 0 ] && grep -q '^ANALYZE_OK ' "$OUT_DIR/$launcher_name.out"; then
			fail_case "$launcher_name" "failed run claimed ANALYZE_OK"
		fi
		launcher_rows=$((launcher_rows + 1))
	}

	launcher_args() {
		launcher_side=$1
		shift
		printf '%s\000' "$@" >"$launcher_dir/expected.args"
		cmp -s "$launcher_dir/expected.args" "$launcher_dir/$launcher_side.args" || \
			fail_case "$launcher_name" "$launcher_side argv changed"
	}

	launcher_run launcher_style 0 --enable-style --scope 'project with spaces/main.ouro'
	launcher_args base --enable-dataflow --enable-metrics --enable-simplify \
		--enable-perf --enable-naming --scope 'project with spaces/main.ouro'
	launcher_args drive --enable-dataflow --enable-metrics --enable-simplify \
		--enable-perf --enable-naming --scope 'project with spaces/main.ouro'

	launcher_run launcher_values 0 --scope --enable-style --enable-style \
		--api-baseline --enable-style 'каталог/source.ouro'
	launcher_args base --scope --enable-style --enable-dataflow --enable-metrics \
		--enable-simplify --enable-perf --enable-naming --api-baseline --enable-style 'каталог/source.ouro'
	launcher_args drive --scope --enable-style --enable-dataflow --enable-metrics \
		--enable-simplify --enable-perf --enable-naming --api-baseline --enable-style 'каталог/source.ouro'

	launcher_run launcher_scope_value_only 0 --scope --enable-style
	launcher_args base --scope --enable-style
	[ ! -e "$launcher_dir/drive.args" ] || fail_case launcher_scope_value_only "scope value enabled drive"

	launcher_run launcher_repeated 0 --enable-style --enable-style --enable-naming
	launcher_args drive --enable-dataflow --enable-metrics --enable-simplify --enable-perf --enable-naming \
		--enable-dataflow --enable-metrics --enable-simplify --enable-perf --enable-naming --enable-naming

	base_status=1
	launcher_run launcher_base_failure 1 --enable-style
	[ -e "$launcher_dir/drive.args" ] || fail_case launcher_base_failure "ordinary finding skipped drive"
	base_status=2
	launcher_run launcher_base_preflight 1 --enable-style
	[ ! -e "$launcher_dir/drive.args" ] || fail_case launcher_base_preflight "fatal preflight ran drive"
	base_status=0

	drive_status=1
	launcher_run launcher_drive_failure 1 --enable-style
	drive_status=0
	drive_text=$(printf '%s\n%s\n' 'test:1:1: warning[OURO-SIMP005] double negation' "$drive_clean")
	launcher_run launcher_drive_zero_with_diagnostic 1 --enable-style
	drive_text='ANALYZE_DRIVE files=1 findings=1 rejected=0 families=simplify'
	launcher_run launcher_drive_nonzero_count 1 --enable-style
	drive_text='ANALYZE_DRIVE files=1 findings=0 rejected=1 families=simplify'
	launcher_run launcher_drive_rejection 1 --enable-style
	drive_text=
	launcher_run launcher_drive_missing_report 1 --enable-style
	drive_text='ANALYZE_DRIVE files=one findings=0 rejected=0 families=simplify'
	launcher_run launcher_drive_malformed_report 1 --enable-style
	drive_text=$(printf '%s\n%s\n' "$drive_clean" \
		'ANALYZE_DRIVE files=1 findings=1 rejected=0 families=simplify')
	launcher_run launcher_drive_mixed_reports 1 --enable-style
	drive_text=$(printf '%s\r\n' "$drive_clean")
	launcher_run launcher_drive_crlf 0 --enable-style
	drive_text='ANALYZE_DRIVE files=0 findings=0 rejected=0 families='
	launcher_run launcher_empty_scope 1 --enable-style
	drive_text=$(printf '%s\n%s\n' "$drive_clean" "$drive_clean")
	launcher_run launcher_repeated_clean_report 1 --enable-style
	drive_text=$drive_clean
	base_text=$(printf '%s\n%s\n' "$base_clean" 'test:1:1: warning[OURO-FMT005] format')
	launcher_run launcher_base_zero_with_diagnostic 1 --enable-style
	base_text=$base_clean
	launcher_run launcher_base_only 0 --scope source.ouro
	[ ! -e "$launcher_dir/drive.args" ] || fail_case launcher_base_only "base-only run started drive"

	echo "ANALYZE_LAUNCHER_SUITE rows=$launcher_rows"
)
check_style_launcher

# Pure cores remain typechecked through the canonical frontend. The helper
# warms the compiler/collector serially before its bounded check-only pool.
set -- tools/analyze/architecture.ouro \
	tools/analyze/deadcode.ouro \
	tools/analyze/duplication.ouro \
	tools/analyze/api_surface.ouro \
	tools/analyze/trust.ouro \
	tools/analyze/suppressions.ouro \
	tools/analyze/host.ouro \
	tools/analyze/ast.ouro \
	tools/analyze/expr_adapt.ouro \
	compiler/facts.ouro \
	compiler/lint.ouro \
	compiler/extract.ouro \
	compiler/parse_a.ouro \
	compiler/parse_b.ouro \
	compiler/kernel_core.ouro \
	std/module_demo.ouro \
	std/mutual_demo.ouro \
	tools/analyze/cfg.ouro \
	tools/analyze/complexity.ouro \
	tools/analyze/bounds.ouro \
	tools/analyze/minimal.ouro \
	tools/analyze/dataflow.ouro \
	tools/analyze/semantic.ouro \
	tools/analyze/effects.ouro \
	tools/analyze/capability.ouro \
	tools/analyze/extract_leak.ouro \
	tools/analyze/match_cover.ouro \
	tools/analyze/policy_ids.ouro \
	tools/analyze/unit.ouro \
	tools/analyze/finding.ouro \
	tools/analyze/drive_env.ouro \
	std/string_prims.ouro \
	tools/quality/diagnostic.ouro \
	tools/analyze/drive_smells.ouro \
	tools/analyze/drive.ouro \
	tools/analyze/drive_main.ouro \
	tools/analyze/property.ouro \
	tools/analyze/format.ouro \
	tools/analyze/taint.ouro \
	tools/analyze/absint.ouro \
	tools/analyze/symexec.ouro \
	tools/analyze/runtime_contracts.ouro \
	tools/analyze/contracts.ouro \
	tools/analyze/simplify.ouro \
	tools/analyze/perf.ouro \
	tools/analyze/naming.ouro \
	tools/analyze/errors.ouro \
	tools/analyze/bounded_text.ouro \
	tools/analyze/bounded_report.ouro \
	tools/analyze/bounded_report_main.ouro \
	tests/analyze/precision/bounded_report.ouro \
	tests/analyze/precision/absint.ouro \
	tests/analyze/precision/lint.ouro \
	tests/analyze/precision/format_fix.ouro \
	tests/analyze/precision/host.ouro \
	tests/analyze/precision/style.ouro \
	tests/analyze/precision/kernel_mirror.ouro \
	tests/analyze/precision/frontend_helpers.ouro \
	tests/analyze/precision/deadcode_patterns.ouro \
	tests/analyze/precision/architecture.ouro \
	tests/analyze/precision/imports.ouro
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
[ -n "${PYTHON:-}" ] || { echo "ANALYZE_SUITE_FAIL no working Python" >&2; exit 127; }
"$PYTHON" "$ROOT/scripts/analyze_bounded.py" --self-test
"$PYTHON" "$ROOT/scripts/analyze_core_checks.py" --out "$OUT_DIR/core" "$@"

# Exercise the standalone parser and inventory with a freshly prepared native
# drive. Launcher stand-ins above cover only the separate process protocol.
check_native_drive_args() (
	native_dir=$(mktemp -d "$OUT_DIR/native-drive-argv.XXXXXX")
	native_dir=$(CDPATH='' cd "$native_dir" && pwd)
	native_bin="$native_dir/ouro-analyze-drive"
	run_case native_argv_build env OURO_BUILD_TOOL_MODE=native \
		sh scripts/build_tool.sh tools/analyze/drive_main.ouro "$native_bin"
	[ "$st" -eq 0 ] || fail_case native_argv_build "native drive build failed, exit=$st"
	[ -x "$native_bin" ] || fail_case native_argv_build "native drive binary is missing"
	if [ -f "$native_bin.exe" ]; then native_bin="$native_bin.exe"; fi
	"$PYTHON" "$ROOT/scripts/fs_read_suite.py" --driver "$native_bin" --mode drive \
		--out "$native_dir/source-reading"
	mkdir -p "$native_dir/sources/каталог с пробелами" "$native_dir/renamed" \
		"$native_dir/empty" "$native_dir/--enable-style"
	printf '%s\n' 'inductive Nat : Type := | Z : Nat;' \
		'def argv_unused (unused : Nat) : Nat := Z;' >"$native_dir/sources/one.ouro"
	cp "$native_dir/sources/one.ouro" "$native_dir/sources/каталог с пробелами/второй файл.ouro"
	cp "$native_dir/sources/one.ouro" "$native_dir/漢字 file.ouro"
	cp "$native_dir/sources/one.ouro" "$native_dir/renamed/bad_переименовано.ouro"
	printf '%s\n' 'inductive Nat : Type := | Z : Nat;' \
		'def argv_keep (value : Nat) : Nat := value;' >"$native_dir/--enable-style/clean.ouro"
	cd "$native_dir"
	native_rows=0
	for native_case in unknown_family unknown_option scope_without_value baseline_without_value \
		missing_scope missing_after_source empty_scope empty_scope_value; do
		case "$native_case" in
		unknown_family)
			set -- --enable-no-such-family
			native_error='unknown analyzer option: --enable-no-such-family' ;;
		unknown_option)
			set -- --no-such-option
			native_error='unknown analyzer option: --no-such-option' ;;
		scope_without_value)
			set -- --scope
			native_error='missing value for --scope' ;;
		baseline_without_value)
			set -- --api-baseline
			native_error='missing value for --api-baseline' ;;
		missing_scope)
			set -- --scope nonexistent.ouro
			native_error='missing or unsafe quality input: nonexistent.ouro' ;;
		missing_after_source)
			set -- --scope sources/one.ouro --scope nonexistent.ouro
			native_error='missing or unsafe quality input: nonexistent.ouro' ;;
		empty_scope)
			set -- --scope empty
			native_error='quality scope contains no selected source files' ;;
		empty_scope_value)
			set -- --scope ''
			native_error='missing or unsafe quality input: ' ;;
		esac
		run_case "native_argv_$native_case" "$native_bin" --enable-dataflow --include-fixtures "$@"
		[ "$st" -eq 2 ] || fail_case "native_argv_$native_case" "expected input failure, exit=$st"
		[ ! -s "$OUT_DIR/native_argv_$native_case.out" ] || \
			fail_case "native_argv_$native_case" "incomplete input produced analysis output"
		grep -Fq "ANALYZE_FAIL: $native_error" "$OUT_DIR/native_argv_$native_case.err" || \
			fail_case "native_argv_$native_case" "missing precise input diagnostic"
		native_rows=$((native_rows + 1))
	done

	native_drive_case() {
		native_case=$1
		native_status=$2
		native_files=$3
		native_findings=$4
		native_families=$5
		shift 5
		run_case "$native_case" "$native_bin" --include-fixtures "$@"
		[ "$st" -eq "$native_status" ] || fail_case "$native_case" "expected exit=$native_status, got $st"
		[ ! -s "$OUT_DIR/$native_case.err" ] || fail_case "$native_case" "unexpected rejection or error"
		[ "$(grep -c '^ANALYZE_DRIVE ' "$OUT_DIR/$native_case.out")" -eq 1 ] || \
			fail_case "$native_case" "expected one completion report"
		grep -Fxq "ANALYZE_DRIVE files=$native_files findings=$native_findings rejected=0 families=$native_families" \
			"$OUT_DIR/$native_case.out" || fail_case "$native_case" "incorrect coverage or families"
		native_count=$(grep -Ec ': (warning|error)\[OURO-[A-Z]+[0-9]+\]' "$OUT_DIR/$native_case.out" || true)
		[ "$native_count" -eq "$native_findings" ] || fail_case "$native_case" "finding count disagrees with report"
		native_rows=$((native_rows + 1))
	}

	native_style='dataflow,metrics,simplify,perf,naming'
	native_all='effects,capability,extract,match,cfg,dataflow,semantic,property,absint,symexec,taint,contracts,metrics,duplication,trust,simplify,perf,naming,errors'
	for native_profile in --enable-style --enable-all --enable-strict; do
		case "$native_profile" in
		--enable-style) expected_families=$native_style ;;
		*) expected_families=$native_all ;;
		esac
		run_case "native_families_$native_profile" "$native_bin" --print-families "$native_profile" "$native_profile"
		[ "$st" -eq 0 ] || fail_case native_families "native family query failed"
		printf 'ANALYZE_FAMILIES families=%s\n' "$expected_families" >"$OUT_DIR/native_families.expected"
		cmp -s "$OUT_DIR/native_families.expected" "$OUT_DIR/native_families_$native_profile.out" || \
			fail_case native_families "profile metadata differs from actual run families"
		[ ! -s "$OUT_DIR/native_families_$native_profile.err" ] || fail_case native_families "unexpected query error"
		native_rows=$((native_rows + 1))
	done
	native_drive_case native_argv_explicit 1 1 1 "$native_style" --scope sources/one.ouro \
		--enable-dataflow --enable-metrics --enable-simplify --enable-perf --enable-naming
	grep -Fq '[OURO-DF001]' "$OUT_DIR/native_argv_explicit.out" || \
		fail_case native_argv_explicit "unused parameter was not analyzed"
	native_drive_case native_argv_repeated 1 1 1 "$native_style" --scope sources/one.ouro \
		--enable-style --enable-dataflow --enable-style --enable-dataflow --enable-naming
	cmp -s "$OUT_DIR/native_argv_explicit.out" "$OUT_DIR/native_argv_repeated.out" || \
		fail_case native_argv_repeated "repeated profiles or families changed findings"
	native_drive_case native_argv_all 1 1 1 "$native_all" --enable-all --scope sources/one.ouro
	native_drive_case native_argv_union 1 1 1 "$native_all" --scope sources/one.ouro \
		--enable-light --enable-heavy --enable-style --enable-light
	cmp -s "$OUT_DIR/native_argv_all.out" "$OUT_DIR/native_argv_union.out" || \
		fail_case native_argv_union "profile union differs from all families"
	native_drive_case native_argv_strict 1 1 1 "$native_all" --scope sources/one.ouro \
		--enable-strict --enable-strict --enable-all
	cmp -s "$OUT_DIR/native_argv_all.out" "$OUT_DIR/native_argv_strict.out" || \
		fail_case native_argv_strict "repeated strict/all profiles changed findings"
	cat >unit-facts.ouro <<'OURO'
def first : Nat := div_nat (S Z) Z;
def clean : Nat := Z;
def last : Nat := prim_fs_write_file prim_argv;
OURO
	native_drive_case native_unit_facts 1 1 2 absint,taint --enable-absint --enable-taint \
		--scope unit-facts.ouro
	sed -n 's/^unit-facts\.ouro:\([0-9][0-9]*\):1: [a-z]*\[\(OURO-[A-Z0-9]*\)\].*/\1 \2/p' \
		"$OUT_DIR/native_unit_facts.out" >"$OUT_DIR/native_unit_facts.codes"
	printf '%s\n' '1 OURO-ABS001' '3 OURO-TAINT001' >"$OUT_DIR/native_unit_facts.expected"
	cmp -s "$OUT_DIR/native_unit_facts.expected" "$OUT_DIR/native_unit_facts.codes" || \
		fail_case native_unit_facts "shared unit facts changed definition findings or order"
	sed -e 's/^-- @complexity$/-- @complexity @bound(nodes <= 0) @bound(cyclo = 0) @minimal/' \
		-e '/^def main /s/:=$/:= let copy : Bool := b in/' \
		-e 's/match b with/match copy with/g' \
		"$ROOT/tests/analyze/metrics_bad/cyclomatic.ouro" >metrics-shared.ouro
	printf '\ndef unannotated (b : Bool) : Bool := let copy : Bool := b in copy;\n' >>metrics-shared.ouro
	native_drive_case native_metrics_shared 1 1 4 metrics --enable-metrics --scope metrics-shared.ouro
	sed -n 's/^  witness: //p' "$OUT_DIR/native_metrics_shared.out" >"$OUT_DIR/native_metrics_shared.witnesses"
	printf '%s\n' 'def main: malformed @bound(cyclo = 0)' 'def main: nodes = 110 violates @bound(nodes <= 0)' \
		'def main: cyclomatic 43 exceeds 40' 'def main: let copy aliases a variable or literal' \
		>"$OUT_DIR/native_metrics_shared.expected"
	cmp -s "$OUT_DIR/native_metrics_shared.expected" "$OUT_DIR/native_metrics_shared.witnesses" || \
		fail_case native_metrics_shared "shared AST size changed metric claims, order, or unannotated coverage"
	printf '%s\n' '-- @requires nonempty' 'inductive Empty : Type := ;' >orphan-contract.ouro
	native_drive_case native_orphan_contract 1 1 1 contracts --enable-contracts --scope orphan-contract.ouro
	grep -Fq '[OURO-CTR001]' "$OUT_DIR/native_orphan_contract.out" || \
		fail_case native_orphan_contract "definition-free unit lost its orphan contract"
	native_drive_case native_argv_literal_values 0 1 0 dataflow --enable-dataflow \
		--scope --enable-style --api-baseline --enable-simplify
	native_drive_case native_argv_unknown_value 0 1 0 dataflow --enable-dataflow \
		--scope --enable-style --api-baseline --no-such-option
	native_drive_case native_argv_aliases 1 1 1 "$native_style" --enable-style \
		--scope sources/one.ouro --scope ./sources/one.ouro --scope sources/../sources/one.ouro
	native_drive_case native_argv_aliases_reordered 1 1 1 "$native_style" --enable-style \
		--scope sources/../sources/one.ouro --scope sources/one.ouro --scope ./sources/one.ouro
	cmp -s "$OUT_DIR/native_argv_aliases.out" "$OUT_DIR/native_argv_aliases_reordered.out" || \
		fail_case native_argv_aliases_reordered "scope aliases changed deterministic findings"
	native_drive_case native_argv_unicode 1 1 1 "$native_style" --enable-style \
		--scope 'sources/каталог с пробелами/второй файл.ouro'
	grep -Fq 'sources/каталог с пробелами/второй файл.ouro:2:1: warning[OURO-DF001]' \
		"$OUT_DIR/native_argv_unicode.out" || fail_case native_argv_unicode "Unicode source location changed"
	native_drive_case native_argv_cjk 1 1 1 "$native_style" --enable-style --scope '漢字 file.ouro'
	grep -Fq '漢字 file.ouro:2:1: warning[OURO-DF001]' "$OUT_DIR/native_argv_cjk.out" || \
		fail_case native_argv_cjk "CJK source location changed"
	native_drive_case native_argv_inventory 1 2 2 "$native_style" --enable-style --scope sources
	native_drive_case native_argv_overlap 1 2 2 "$native_style" --enable-style \
		--scope 'sources/каталог с пробелами' --scope sources/one.ouro --scope sources --scope sources/one.ouro
	cmp -s "$OUT_DIR/native_argv_inventory.out" "$OUT_DIR/native_argv_overlap.out" || \
		fail_case native_argv_overlap "overlapping or repeated scopes lost or duplicated files"
	native_drive_case native_argv_renamed 1 1 1 "$native_style" --enable-style \
		--scope renamed/bad_переименовано.ouro
	for native_case in explicit unicode cjk renamed; do
		LC_ALL=C sed 's/^[^:]*:\([0-9][0-9]*:[0-9][0-9]*: \)/SOURCE:\1/' \
			"$OUT_DIR/native_argv_$native_case.out" >"$OUT_DIR/native_argv_$native_case.normalized"
	done
	for native_case in unicode cjk renamed; do
		cmp -s "$OUT_DIR/native_argv_explicit.normalized" "$OUT_DIR/native_argv_$native_case.normalized" || \
			fail_case "native_argv_$native_case" "moving identical source changed semantic findings"
	done
	echo "ANALYZE_NATIVE_ARGV_SUITE rows=$native_rows"
)
check_native_drive_args

# Base facts retain their own fixture policy while sharing checked inventory.
check_native_base_inputs() (
	native_dir=$(mktemp -d "$OUT_DIR/native-base-input.XXXXXX")
	native_bin="$native_dir/ouro-analyze"
	run_case native_base_build env OURO_BUILD_TOOL_MODE=native \
		sh scripts/build_tool.sh tools/analyze/main.ouro "$native_bin"
	[ "$st" -eq 0 ] || fail_case native_base_build "native base build failed, exit=$st"
	[ -x "$native_bin" ] || fail_case native_base_build "native base binary is missing"
	mkdir -p "$native_dir/empty" "$native_dir/tests" "$native_dir/каталог с пробелами"
	for native_subdir in _build _cache .git node_modules; do
		mkdir -p "$native_dir/walk/$native_subdir"
		printf '%s\n' 'def main : Nat := 0;' >"$native_dir/walk/$native_subdir/hidden.ouro"
	done
	for native_path in one.ouro two.ouro walk/main.ouro tests/fixture.ouro \
		'каталог с пробелами/имя.ouro' '漢字 file.ouro'; do
		printf '%s\n' 'def main : Nat := 0;' >"$native_dir/$native_path"
	done
	cd "$native_dir"
	native_rows=0
	for native_case in empty excluded_fixture missing missing_then_valid; do
		case "$native_case" in
		empty) set -- --scope empty ;;
		excluded_fixture) set -- --scope tests ;;
		missing) set -- --scope nonexistent.ouro ;;
		missing_then_valid) set -- --scope nonexistent.ouro --scope one.ouro ;;
		esac
		run_case "native_base_$native_case" "$native_bin" --strict --local-only --dump-facts "$@"
		[ "$st" -eq 2 ] || fail_case "native_base_$native_case" "expected inventory failure, exit=$st"
		[ ! -s "$OUT_DIR/native_base_$native_case.out" ] || \
			fail_case "native_base_$native_case" "incomplete input produced facts or a success report"
		grep -q '^ANALYZE_FAIL: ' "$OUT_DIR/native_base_$native_case.err" || \
			fail_case "native_base_$native_case" "missing inventory diagnostic"
		native_rows=$((native_rows + 1))
	done
	for native_case in repeated reordered equals mixed terminator overlap duplicate aliases aliases_reordered empty_and_valid walk include_fixtures unicode \
		cjk explicit_build explicit_cache explicit_git explicit_dependencies; do
		native_files=1
		case "$native_case" in
		repeated | reordered | equals | mixed | terminator)
			native_files=2
			native_paths=$(printf '%s\n' one.ouro two.ouro)
			case "$native_case" in
			repeated) set -- --scope one.ouro --scope two.ouro ;;
			reordered) set -- --scope two.ouro --scope one.ouro ;;
			equals) set -- --scope=one.ouro --scope=two.ouro ;;
			mixed) set -- --scope=one.ouro --scope two.ouro ;;
			terminator) set -- --scope one.ouro -- two.ouro ;;
			esac ;;
		overlap) native_paths=walk/main.ouro; set -- --scope walk/main.ouro --scope walk ;;
		duplicate) native_paths=one.ouro; set -- --scope one.ouro --scope one.ouro ;;
		aliases) native_paths=./one.ouro; set -- --scope one.ouro --scope ./one.ouro --scope empty/../one.ouro ;;
		aliases_reordered) native_paths=./one.ouro; set -- --scope empty/../one.ouro --scope one.ouro --scope ./one.ouro ;;
		empty_and_valid) native_paths=one.ouro; set -- --scope empty --scope one.ouro ;;
		walk) native_paths=walk/main.ouro; set -- --scope walk ;;
		include_fixtures) native_paths=tests/fixture.ouro; set -- --include-fixtures --scope tests ;;
		unicode) native_paths='каталог с пробелами/имя.ouro'; set -- --scope 'каталог с пробелами' ;;
		cjk) native_paths='漢字 file.ouro'; set -- --scope "$native_paths" ;;
		explicit_build) native_paths=walk/_build/hidden.ouro; set -- --scope "$native_paths" ;;
		explicit_cache) native_paths=walk/_cache/hidden.ouro; set -- --scope "$native_paths" ;;
		explicit_git) native_paths=walk/.git/hidden.ouro; set -- --scope "$native_paths" ;;
		explicit_dependencies) native_paths=walk/node_modules/hidden.ouro; set -- --scope "$native_paths" ;;
		esac
		expect_ok "native_base_$native_case" "$native_bin" --strict --local-only --dump-facts "$@"
		[ ! -s "$OUT_DIR/native_base_$native_case.err" ] || fail_case "native_base_$native_case" "unexpected error"
		# --dump-facts adds one module declaration beside each source definition.
		native_decls=$((native_files * 2))
		grep -Eq "^ANALYZE_OK profile=strict files=$native_files imports=0 decls=$native_decls " \
			"$OUT_DIR/native_base_$native_case.out" || fail_case "native_base_$native_case" "incorrect file coverage"
		[ "$(grep -c '^FACT declaration ' "$OUT_DIR/native_base_$native_case.out")" -eq "$native_files" ] || \
			fail_case "native_base_$native_case" "declaration coverage disagrees with selected sources"
		printf '%s\n' "$native_paths" | while IFS= read -r native_path; do
			grep -Fq "FACT declaration $native_path:" "$OUT_DIR/native_base_$native_case.out" || \
				fail_case "native_base_$native_case" "source was not processed: $native_path"
		done
		native_rows=$((native_rows + 1))
	done
	for native_case in reordered equals mixed terminator; do
		cmp -s "$OUT_DIR/native_base_repeated.out" "$OUT_DIR/native_base_$native_case.out" || \
			fail_case "native_base_$native_case" "scope syntax or order changed facts"
	done
	cmp -s "$OUT_DIR/native_base_walk.out" "$OUT_DIR/native_base_overlap.out" || \
		fail_case native_base_overlap "overlapping scopes changed facts"
	cmp -s "$OUT_DIR/native_base_aliases.out" "$OUT_DIR/native_base_aliases_reordered.out" || \
		fail_case native_base_aliases_reordered "scope aliases changed deterministic facts"
	echo "ANALYZE_NATIVE_BASE_INPUT_SUITE rows=$native_rows"
)
check_native_base_inputs

# The assertions run in Ouro. This launcher only builds, executes and retains
# logs; failed builds, missing binaries and empty/missing reports fail closed.
# The deadcode root exercises the host fact extractors through their native ABI.
for precision_core in absint lint format_fix host style kernel_mirror frontend_helpers deadcode_patterns architecture imports bounded_report; do
	precision_bin="$OUT_DIR/precision-$precision_core"
	run_case "precision_build_$precision_core" env OURO_BUILD_TOOL_MODE=native \
		sh scripts/build_tool.sh "tests/analyze/precision/$precision_core.ouro" "$precision_bin"
	[ "$st" -eq 0 ] || fail_case "precision_build_$precision_core" "native build failed, exit=$st"
	run_case "precision_run_$precision_core" "$precision_bin"
	[ "$st" -eq 0 ] || fail_case "precision_run_$precision_core" "native assertion failed, exit=$st"
	grep -q '^PRECISION_SUITE .* rows=[1-9][0-9]*$' "$OUT_DIR/precision_run_$precision_core.out" || \
		fail_case "precision_run_$precision_core" "missing nonempty native suite report"
done

# Retain host lexical observations while executing the sole native verdict owner.
"$PYTHON" - <<'PY'
import contextlib
import io
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import sys
sys.path.insert(0, "scripts")
import analyze_bounded as bounded
from ourosmith.limits import RunResult, run_limited

clean = "ANALYZE_DRIVE files=1 findings=0 rejected=0 families=dataflow\n"
path = "C:/каталог/漢字 file.ouro"
finding = (f"{path}:2:1: warning[OURO-DF001] dataflow/unused-param: unused\n"
           "  hint: use it\n  witness: value\n")
diagnostic = finding + clean.replace("findings=0", "findings=1")
cases = [
    (0, clean, "", ""),
    (0, clean.replace("\n", "\r\n"), "", ""),
    (0, clean.replace("files=1", "files=١"), "", ""),
    (0, clean.replace("files=1", "files=0001").replace("findings=0", "findings=000"), "", ""),
    (1, diagnostic, "", ""),
    (0, clean + clean, "crash\n", "missing, malformed or repeated structured completion report"),
    (0, clean.replace("files=1", "files=-1"), "", "missing, malformed or repeated structured completion report"),
    (0, clean.replace("files=1", "files=0").replace("dataflow", "effects"), "crash\n",
     "structured report omitted or duplicated requested files"),
    (1, clean.replace("dataflow", "effects").replace("findings=0", "findings=1"), "crash\n",
     "structured report did not run the requested families"),
    (1, clean.replace("findings=0", "findings=1"), "crash\n",
     "structured diagnostic counts disagree with the completion report"),
    (1, diagnostic.replace("  witness: value\n", ""), "",
     "structured worker emitted unreported output"),
    (137, clean, "crash\n", "structured worker emitted an unexpected error"),
    (137, clean + "unreported\n", "", "structured worker emitted unreported output"),
    (-9, clean, "", "structured exit code disagrees with the completion report"),
]
for code, stdout, stderr, expected in cases:
    actual = bounded.drive_result_error(subprocess.CompletedProcess([], code, stdout, stderr),
                                       files=1, families="dataflow")
    assert actual == expected, (expected, actual)
assert bounded.drive_result_error(subprocess.CompletedProcess([], 1, diagnostic, ""),
                                  files=1, families="dataflow", path=path) == ""
assert bounded.drive_result_error(subprocess.CompletedProcess([], 0, clean, ""),
                                  files=-1, families="effects") == "structured report omitted or duplicated requested files"

large_count = "1" + "0" * 1001
large = clean.replace("files=1", "files=" + large_count)
assert bounded.drive_banner(large) == ({"files": int(large_count), "findings": 0, "rejected": 0}, "dataflow")
assert bounded.drive_result_error(subprocess.CompletedProcess([], 0, large, ""),
                                  files=1, families="dataflow") == "structured report omitted or duplicated requested files"
assert bounded.drive_result_error(subprocess.CompletedProcess([], 0, large + clean, ""),
                                  files=1, families="dataflow") == "missing, malformed or repeated structured completion report"
for field in ("findings", "rejected"):
    large_diagnostics = clean.replace(field + "=0", field + "=" + large_count)
    assert bounded.drive_result_error(subprocess.CompletedProcess([], 1, large_diagnostics, ""),
                                      files=1, families="dataflow") == "structured diagnostic counts disagree with the completion report"

# Native branch one must run before any public whole-count integer conversion.
saved_digit_limit = sys.get_int_max_str_digits()
try:
    sys.set_int_max_str_digits(640)
    for digits, valid_error in (
        ("1" + "0" * 640, "structured report omitted or duplicated requested files"),
        ("١" + "٠" * 1001, "structured report omitted or duplicated requested files"),
        ("0" * 640 + "1", ""),
    ):
        oversized = clean.replace("files=1", "files=" + digits)
        for output in (oversized + clean, oversized.replace("dataflow", "dataflow,dataflow")):
            assert bounded.drive_banner(output) is None
            error = bounded.drive_result_error(subprocess.CompletedProcess([], 0, output, ""),
                                              files=1, families="dataflow")
            assert error == "missing, malformed or repeated structured completion report", error
        try:
            bounded.drive_banner(oversized)
        except ValueError:
            pass
        else:
            raise AssertionError("valid banner must retain the public integer digit limit")
        error = bounded.drive_result_error(subprocess.CompletedProcess([], 0, oversized, ""),
                                          files=1, families="dataflow")
        assert error == valid_error, (valid_error, error)
finally:
    sys.set_int_max_str_digits(saved_digit_limit)

binary = bounded._drive_report_binary()
request = {
    "kind": "ouro.analyze-bounded-report-request.v1", "mode": "verify",
    "expected": {"files": "1", "families": "dataflow", "path": None},
    "banners": [{"files": "1", "findings": "0", "rejected": "0", "families": "dataflow"}],
    "finding_paths": [], "rejection_paths": [], "stdout_unreported": False,
    "stderr_unexpected": False, "exit": "0", "family_metadata": None,
}
payload = json.dumps(request, separators=(",", ":"))
duplicate = payload[:-1] + ',"exit":"0"}'
for text in ("{}", duplicate, payload.replace('"stdout_unreported":false', '"stdout_unreported":"false"')):
    result = run_limited([str(binary), "--input-bytes", str(len(text.encode("utf-8")))],
                         cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=text)
    assert result.status == "ok" and result.returncode == 2 and not result.stdout, result
    assert "ANALYZE_REPORT_FAIL: invalid provider request" in result.stderr, result
for count in ("01", "-1", "+1", " 1 ", "1.0", "", "١", 1):
    invalid = {**request, "banners": [{**request["banners"][0], "files": count}]}
    text = json.dumps(invalid, ensure_ascii=False, separators=(",", ":"))
    result = run_limited([str(binary), "--input-bytes", str(len(text.encode("utf-8")))],
                         cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=text)
    assert result.status == "ok" and result.returncode == 2 and not result.stdout, result
    assert "ANALYZE_REPORT_FAIL: invalid provider request" in result.stderr, result
result = run_limited([str(binary), "--input-bytes", str(len(payload.encode("utf-8")) + 1)],
                     cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=payload)
assert result.status == "ok" and result.returncode == 2 and not result.stdout, result
assert "incomplete or excess stdin bytes" in result.stderr, result
result = run_limited([str(binary), "--input-bytes", str(len(payload.encode("utf-8")))],
                     cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=payload + "x")
assert result.status == "ok" and result.returncode == 2 and not result.stdout, result
assert "incomplete or excess stdin bytes" in result.stderr, result
result = run_limited([str(binary), "--input-bytes", str(len(payload.encode("utf-8")))],
                     cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=payload + "\0")
assert result.status == "ok" and result.returncode == 2 and not result.stdout, result
assert "incomplete or excess stdin bytes" in result.stderr, result

# Aggregate finding arrays can exceed 1000 rows; paths remain real repo inputs.
selected = bounded.parse_analyzer_args([], bounded.ROOT)
assert selected is not None and selected[1]
real_paths = [bounded.repo_relative(path) for path in selected[1]]
assert all(path is not None for path in real_paths)
finding_paths = (real_paths * ((1002 + len(real_paths) - 1) // len(real_paths)))[:1002]
aggregate = {
    **request, "expected": {**request["expected"], "files": str(len(real_paths))},
    "banners": [{"files": str(len(real_paths)), "findings": "1002", "rejected": "0", "families": "dataflow"}],
    "finding_paths": finding_paths, "exit": "1",
}
text = json.dumps(aggregate, ensure_ascii=False, separators=(",", ":"))
result = run_limited([str(binary), "--input-bytes", str(len(text.encode("utf-8")))],
                     cwd=bounded.ROOT, timeout_s=30, memory_mb=3072, stdin_text=text)
assert result.status == "ok" and result.returncode == 0 and not result.stderr, result
response = json.loads(result.stdout)
assert response["error"] == "" and response["banner"] == aggregate["banners"][0], response

# A broken provider cannot invoke the old Python policy or fabricate success.
for result in (RunResult("spawn-error", None, "", "missing", 0, 0),
               RunResult("timeout", None, "", "", 0, 0),
               RunResult("ok", 2, "", "invalid request", 0, 0),
               RunResult("ok", 0, "{}", "", 0, 0)):
    with patch("ourosmith.limits.run_limited", return_value=result), \
         patch.object(bounded, "_drive_report_binary", return_value=Path("unused-provider")):
        proc = subprocess.CompletedProcess([], 0, clean, "")
        assert bounded.drive_banner(clean) is None
        assert bounded.drive_result_error(proc, files=1, families="dataflow").startswith(
            "structured report verifier unavailable:")
# Even a currently consistent replacement must not become this run's provider.
initial = ({"key": "initial-key", "binary_sha256": "initial-image"},
           ["tools/analyze/bounded_report_main.ouro"], {"entry": "initial-source"})
replacement = ({"key": "replacement-key", "binary_sha256": "replacement-image"},
               ["tools/analyze/bounded_report_main.ouro", "std/jsonx.ouro"],
               {"entry": "replacement-source", "std/jsonx.ouro": "replacement-json"})
accepted = json.dumps({"kind": "ouro.analyze-bounded-report-response.v1",
                       "banner": request["banners"][0], "families": None, "error": ""})
for phase, receipts in (("before", [initial, replacement]),
                        ("during", [initial, initial, replacement])):
    with patch.dict(bounded._DRIVE_REPORT_CACHE, clear=True), \
         patch("ourosmith.host.prepare_entry", return_value=Path("unused-provider")), \
         patch("ourosmith.host.compiler_path", return_value=Path("unused-compiler")), \
         patch("ourosmith.native.receipt_for", side_effect=receipts), \
         patch("ourosmith.limits.run_limited",
               return_value=RunResult("ok", 0, accepted, "", 0, 0)) as child:
        assert bounded._drive_report_binary() == Path("unused-provider")
        error = bounded.drive_result_error(subprocess.CompletedProcess([], 0, clean, ""),
                                          files=1, families="dataflow")
        assert error == ("structured report verifier unavailable: "
                         "report provider inputs changed since preparation"), (phase, error)
        assert child.call_count == (1 if phase == "during" else 0), (phase, child.call_count)
# One complete verification supplies the banner used for aggregation.
files = ["std/io.ouro", "std/fs.ouro"]
finding_body = finding.replace(path, files[1])
worker_results = [
    subprocess.CompletedProcess([], 0, clean.replace("files=1", "files=٠٠١"), ""),
    subprocess.CompletedProcess([], 1, finding_body + clean.replace("findings=0", "findings=1"), ""),
]
verified = json.loads(accepted)
responses = [
    verified, {**verified, "banner": {**verified["banner"], "findings": "1"}},
]
out, err = io.StringIO(), io.StringIO()
with patch.object(bounded, "requested_drive_families", return_value="dataflow"), \
     patch.object(bounded, "run_native", side_effect=worker_results), \
     patch.object(bounded, "_drive_report_binary", return_value=Path("unused-provider")) as provider, \
     patch("ourosmith.limits.run_limited", side_effect=[
         RunResult("ok", 0, json.dumps(response), "", 0, 0) for response in responses
     ]) as report_run, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    assert bounded.run_drive_bounded(Path("unused-drive"), [], [bounded.ROOT / name for name in files]) == 1
    requests = [json.loads(call.kwargs["stdin_text"]) for call in report_run.call_args_list]
    assert [row["mode"] for row in requests] == ["verify", "verify"]
    assert [row["expected"]["path"] for row in requests] == files
    assert [row["banners"][0]["files"] for row in requests] == ["1", "1"]
    assert provider.call_count == 4
assert err.getvalue() == ""
assert out.getvalue() == finding_body + "ANALYZE_DRIVE files=2 findings=1 rejected=0 families=dataflow\n"

malformed = clean + clean
message = "missing, malformed or repeated structured completion report"
refused = {**verified, "banner": None, "error": message}
out, err = io.StringIO(), io.StringIO()
with patch.object(bounded, "requested_drive_families", return_value="dataflow"), \
     patch.object(bounded, "run_native", return_value=subprocess.CompletedProcess([], 0, malformed, "")), \
     patch.object(bounded, "_drive_report_binary", return_value=Path("unused-provider")), \
     patch("ourosmith.limits.run_limited",
           return_value=RunResult("ok", 1, json.dumps(refused), "", 0, 0)) as report_run, \
     contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    assert bounded.run_drive_bounded(Path("unused-drive"), [], [bounded.ROOT / files[0]]) == 2
    report_run.assert_called_once()
assert out.getvalue() == malformed
assert err.getvalue() == f"ANALYZE_FAIL: {files[0]}: {message}\n"
print("ANALYZE_REPORT_PROVIDER_SUITE rows=56")
PY


analyze() {
	sh scripts/ouro1.sh analyze --strict --include-fixtures "$@"
}
FIX="tests/analyze"

# The production tree carries counts that move with every source change, so
# it is an expectation, not a golden.
expect_ok project_no_fp sh scripts/ouro1.sh analyze --strict

golden_codes architecture_bad "OURO-ARCH001 OURO-ARCH002 OURO-ARCH003 OURO-ARCH004 OURO-ARCH005" \
	analyze --scope "$FIX/architecture_bad"
golden_codes grouped_imports_bad "OURO-ARCH001 OURO-ARCH002 OURO-ARCH003 OURO-ARCH004 OURO-ARCH005" \
	analyze --scope "$FIX/grouped_imports_bad"
golden_ok architecture_good analyze --scope "$FIX/architecture_good"

golden_codes deadcode_bad "OURO-DEAD001 OURO-DEAD002" \
	analyze --enable-deadcode --scope "$FIX/deadcode_bad"
golden_ok deadcode_good analyze --enable-deadcode --scope "$FIX/deadcode_good"
golden_codes deadcode_ctor_bad OURO-DEAD003 analyze --enable-deadcode --scope "$FIX/deadcode_bad_ctor"
golden_ok deadcode_ctor_good analyze --enable-deadcode --scope "$FIX/deadcode_good_ctor"
golden_codes deadcode_branch_bad OURO-DEAD005 analyze --enable-deadcode --scope "$FIX/deadcode_bad_branch"
expect_ok deadcode_patterns_good analyze --enable-deadcode --scope "$FIX/deadcode_good_patterns"
golden_codes deadcode_module_bad OURO-DEAD004 analyze --enable-deadcode --scope "$FIX/deadcode_bad_module"

expect_ok facts_dump_ok analyze --dump-facts --scope "$FIX/facts_good"
for fact in 'FACT declaration' 'FACT constructor' 'FACT module' 'FACT branch' \
	'FACT reference' 'FACT export' 'FACT_SUMMARY'; do
	grep -q "$fact" "$OUT_DIR/facts_dump_ok.out" || \
		fail_case facts_dump_ok "missing typed fact family: $fact"
	done

golden_codes duplication_bad "OURO-DUP001 OURO-DUP002" \
	analyze --enable-duplication --scope "$FIX/duplication_bad"
golden_ok duplication_good analyze --enable-duplication --scope "$FIX/duplication_good"

golden_codes api_surface_bad "OURO-API001 OURO-API002 OURO-API003 OURO-API004 OURO-API005" \
	analyze --api-baseline "$FIX/api_surface.tsv" --scope "$FIX/api_surface_bad"
golden_ok api_surface_good analyze --api-baseline "$FIX/api_surface.tsv" --scope "$FIX/api_surface_good"

golden_codes suppressions_bad "OURO-SUP001 OURO-SUP002 OURO-SUP003 OURO-SUP004 OURO-SUP005 OURO-SUP006" \
	analyze --scope "$FIX/suppressions_bad"
golden_ok suppressions_good analyze --scope "$FIX/suppressions_good"

golden_codes cfg_bad "OURO-CFG001 OURO-CFG002 OURO-CFG003 OURO-CFG004" \
	analyze --enable-cfg --scope "$FIX/cfg_bad"
golden_ok cfg_good analyze --enable-cfg --scope "$FIX/cfg_good"

golden_codes dataflow_bad "OURO-DF001 OURO-DF002 OURO-DF003 OURO-DF004" \
	analyze --enable-dataflow --scope "$FIX/dataflow_bad"
golden_ok dataflow_good analyze --enable-dataflow --scope "$FIX/dataflow_good"

golden_codes semantic_bad "OURO-SEM001 OURO-SEM002 OURO-SEM003 OURO-SEM004 OURO-SEM005" \
	analyze --enable-semantic --scope "$FIX/semantic_bad"
golden_ok semantic_good analyze --enable-semantic --scope "$FIX/semantic_good"

golden_codes absint_bad "OURO-ABS001 OURO-ABS002 OURO-ABS003" \
	analyze --enable-absint --scope "$FIX/absint_bad"
golden_ok absint_good analyze --enable-absint --scope "$FIX/absint_good"

golden_codes symexec_bad "OURO-SYM001 OURO-SYM002 OURO-SYM003" \
	analyze --enable-symexec --scope "$FIX/symexec_bad"
golden_ok symexec_good analyze --enable-symexec --scope "$FIX/symexec_good"

golden_codes metrics_bad "OURO-CX001 OURO-CX002 OURO-BND001 OURO-MIN001" \
	analyze --enable-metrics --scope "$FIX/metrics_bad"
golden_ok metrics_good analyze --enable-metrics --scope "$FIX/metrics_good"

# The CRLF fixture is materialised outside git so checkout normalisation
# cannot rewrite it; its path depends on OUT_DIR, so it has no golden.
format_bad_dir="$OUT_DIR/format_bad_crlf"
mkdir -p "$format_bad_dir"
LC_ALL=C awk '{ printf "%s\r\n", $0 }' \
	"$FIX/format_bad/crlf.ouro" >"$format_bad_dir/crlf.ouro"
expect_codes format_bad "OURO-FMT001 OURO-FMT005" analyze --enable-format --scope "$format_bad_dir"
golden_ok format_good analyze --enable-format --scope "$FIX/format_good"

golden_codes effects_bad "OURO-EFF001 OURO-EFF003 OURO-EFF004 OURO-EFF005 OURO-EFF006" \
	analyze --enable-effects --scope "$FIX/effects_bad"
golden_ok effects_good analyze --enable-effects --scope "$FIX/effects_good"

golden_codes capability_bad "OURO-CAP001 OURO-CAP002 OURO-CAP003 OURO-CAP004" \
	analyze --enable-capability --scope "$FIX/capability_bad"
golden_ok capability_good analyze --enable-capability --scope "$FIX/capability_good"
expect_codes runtime_capability_bad "OURO-CAP001 OURO-CAP002 OURO-CAP003" \
	analyze --enable-capability --scope "$FIX/runtime_capability_bad"
expect_ok runtime_capability_good analyze --enable-capability --scope "$FIX/runtime_wrappers_good"
expect_codes runtime_effects_bad "OURO-EFF003" \
	analyze --enable-effects --scope "$FIX/runtime_capability_bad"
expect_ok runtime_effects_good analyze --enable-effects --scope "$FIX/runtime_wrappers_good"

golden_codes extract_bad "OURO-XTR001 OURO-XTR002 OURO-XTR003" \
	analyze --enable-extract --scope "$FIX/extract_bad"
golden_ok extract_good analyze --enable-extract --scope "$FIX/extract_good"

golden_codes match_bad "OURO-MATCH001 OURO-MATCH002" analyze --enable-match --scope "$FIX/match_bad"
golden_ok match_good analyze --enable-match --scope "$FIX/match_good"

golden_codes property_bad "OURO-PROP001 OURO-PROP002 OURO-PROP003 OURO-PROP004" \
	analyze --enable-property --scope "$FIX/property_bad"
golden_ok property_good analyze --enable-property --scope "$FIX/property_good"

golden_codes taint_bad "OURO-TAINT001 OURO-TAINT002 OURO-TAINT003" \
	analyze --enable-taint --scope "$FIX/taint_bad"
golden_ok taint_good analyze --enable-taint --scope "$FIX/taint_good"
expect_codes runtime_taint_bad "OURO-TAINT001" \
	analyze --enable-taint --scope "$FIX/runtime_taint_bad"
expect_ok runtime_taint_good analyze --enable-taint --scope "$FIX/runtime_wrappers_good"

golden_codes contracts_bad \
	"OURO-CTR001 OURO-CTR002 OURO-CTR003 OURO-CTR004 OURO-CTR005 OURO-CTR006 OURO-CTR007 OURO-CTR008" \
	analyze --enable-contracts --scope "$FIX/contracts_bad"
golden_ok contracts_good analyze --enable-contracts --scope "$FIX/contracts_good"

golden_codes trust_bad "OURO-TRUST001 OURO-TRUST002 OURO-TRUST003 OURO-TRUST004 OURO-TRUST005" \
	analyze --enable-trust --scope "$FIX/trust_bad"
golden_ok trust_good analyze --enable-trust --scope "$FIX/trust_good"

golden_codes simplify_bad \
	"OURO-SIMP001 OURO-SIMP002 OURO-SIMP003 OURO-SIMP004 OURO-SIMP005 OURO-SIMP006 OURO-SIMP007" \
	analyze --enable-simplify --scope "$FIX/simplify_bad"
golden_ok simplify_good analyze --enable-simplify --scope "$FIX/simplify_good"

golden_codes perf_bad "OURO-PERF001 OURO-PERF002 OURO-PERF003 OURO-PERF004 OURO-PERF005" \
	analyze --enable-perf --scope "$FIX/perf_bad"
golden_ok perf_good analyze --enable-perf --scope "$FIX/perf_good"

golden_codes naming_bad "OURO-NAME001 OURO-NAME003 OURO-NAME004" \
	analyze --enable-naming --scope "$FIX/naming_bad"
golden_ok naming_good analyze --enable-naming --scope "$FIX/naming_good"

golden_codes errors_bad "OURO-ERR001 OURO-ERR002 OURO-ERR003" \
	analyze --enable-errors --scope "$FIX/errors_bad"
golden_ok errors_good analyze --enable-errors --scope "$FIX/errors_good"

# The profile is exactly the existing families, including when flags repeat.
expect_codes style_explicit "OURO-DF001 OURO-NAME001 OURO-SIMP005" analyze \
	--enable-dataflow --enable-metrics --enable-simplify --enable-perf --enable-naming \
	--scope "$FIX/style_bad"
[ "$st" -eq 1 ] || fail_case style_explicit "expected ordinary findings, exit=$st"
expect_codes style_profile "OURO-DF001 OURO-NAME001 OURO-SIMP005" \
	analyze --enable-style --scope "$FIX/style_bad"
[ "$st" -eq 1 ] || fail_case style_profile "expected ordinary findings, exit=$st"
grep -q '^ANALYZE_DRIVE files=1 findings=3 rejected=0 families=dataflow,metrics,simplify,perf,naming$' \
	"$OUT_DIR/style_profile.out" || fail_case style_profile "unexpected style finding set"
cmp -s "$OUT_DIR/style_explicit.out" "$OUT_DIR/style_profile.out" || \
	fail_case style_profile "profile differs from its explicit family union"
expect_codes style_repeated "OURO-DF001 OURO-NAME001 OURO-SIMP005" \
	analyze --enable-style --enable-style --enable-naming --scope "$FIX/style_bad"
cmp -s "$OUT_DIR/style_profile.out" "$OUT_DIR/style_repeated.out" || \
	fail_case style_repeated "repeated profile duplicated diagnostics"
expect_ok style_good analyze --enable-style --scope "$FIX/style_good"
grep -q '^ANALYZE_DRIVE files=1 findings=0 rejected=0 families=dataflow,metrics,simplify,perf,naming$' \
	"$OUT_DIR/style_good.out" || fail_case style_good "missing complete style report"

run_case style_unknown analyze --enable-style --unknown-style-option --scope "$FIX/style_good"
[ "$st" -ne 0 ] || fail_case style_unknown "unknown option was accepted"
run_case style_unknown_value analyze --enable-style --unknown-style-option value --scope "$FIX/style_good"
[ "$st" -ne 0 ] || fail_case style_unknown_value "unknown option with a value was accepted"
run_case style_unknown_last analyze --enable-style --scope "$FIX/style_good" --unknown-style-option
[ "$st" -ne 0 ] || fail_case style_unknown_last "trailing unknown option was accepted"
run_case style_scope_without_value analyze --enable-style --scope
[ "$st" -ne 0 ] || fail_case style_scope_without_value "scope without a value was accepted"
run_case style_baseline_without_value analyze --enable-style --api-baseline
[ "$st" -ne 0 ] || fail_case style_baseline_without_value "baseline without a value was accepted"
run_case style_missing analyze --enable-style --scope "$OUT_DIR/nonexistent-style-scope"
[ "$st" -ne 0 ] || fail_case style_missing "missing scope was accepted"

# Semantic binder suggestions stay review-only; an explicit reviewed edit must
# converge through the native formatter, fixer and style analyzer.
# A stable-depth workspace keeps the import valid for custom OUT_DIR values.
mkdir -p "$ROOT/_build"
style_dir=$(mktemp -d "$ROOT/_build/style-roundtrip.XXXXXX")
trap 'rm -rf "$style_dir"' EXIT
style_source="$style_dir/input.ouro"
printf '%s\n' 'import "../../std/data.ouro";' \
	'def style_unused (unused : Nat) : Nat := 0;' >"$style_source"
expect_codes style_fix_before OURO-DF001 analyze --enable-style --scope "$style_source"
for style_tool in fix fmt; do
	case "$style_tool" in
	fix) style_root=tools/fix/main.ouro ;;
	fmt) style_root=tools/fmt.ouro ;;
	esac
	run_case "style_build_$style_tool" env OURO_BUILD_TOOL_MODE=native \
		sh scripts/build_tool.sh "$style_root" "$OUT_DIR/style-$style_tool"
	[ "$st" -eq 0 ] || fail_case "style_build_$style_tool" "native tool build failed, exit=$st"
done
cp "$style_source" "$OUT_DIR/style_review_original.ouro"
run_case style_fix_write "$OUT_DIR/style-fix" --write "$style_source"
[ "$st" -eq 0 ] || fail_case style_fix_write "safe fix failed, exit=$st"
cmp -s "$style_source" "$OUT_DIR/style_review_original.ouro" || \
	fail_case style_fix_write "review-only source bytes changed"
grep -q '(unused : Nat)' "$style_source" || fail_case style_fix_write "review-only binder was changed"
grep -q 'review-required suggestions (not applied)' "$OUT_DIR/style_fix_write.err" || \
	fail_case style_fix_write "missing binder review diagnostic"
expect_codes style_review_retained OURO-DF001 analyze --enable-style --scope "$style_source"
run_case style_review_check "$OUT_DIR/style-fix" --check "$style_source"
[ "$st" -eq 1 ] || fail_case style_review_check "review-only suggestion was accepted as clean"
# Apply the reviewed discard explicitly; automatic publication cannot certify it.
printf '%s\n' 'import "../../std/data.ouro";' \
	'def style_unused (_unused : Nat) : Nat := 0;' >"$style_source"
run_case style_fmt_write "$OUT_DIR/style-fmt" --write "$style_source"
[ "$st" -eq 0 ] || fail_case style_fmt_write "format failed, exit=$st"
grep -q '(_unused : Nat)' "$style_source" || fail_case style_fix_write "discard convention not applied"
cp "$style_source" "$OUT_DIR/style_roundtrip_once.ouro"
run_case style_fix_check "$OUT_DIR/style-fix" --check "$style_source"
[ "$st" -eq 0 ] || fail_case style_fix_check "fix reopened after formatting"
run_case style_fmt_check "$OUT_DIR/style-fmt" --check "$style_source"
[ "$st" -eq 0 ] || fail_case style_fmt_check "format is not idempotent"
cmp -s "$style_source" "$OUT_DIR/style_roundtrip_once.ouro" || \
	fail_case style_fmt_check "check-only invocation wrote the source"
expect_ok style_fix_after analyze --enable-style --scope "$style_source"
grep -q '^ANALYZE_DRIVE files=1 findings=0 rejected=0 families=dataflow,metrics,simplify,perf,naming$' \
	"$OUT_DIR/style_fix_after.out" || fail_case style_fix_after "roundtrip was not fully analyzed"

echo "ANALYZE_SUITE_OK out=$OUT_DIR"
