#!/usr/bin/env sh
# Compatibility launcher; ouro-fix owns autofix suite cases and assertions.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${FIX_SUITE_OUT:-$ROOT/_build/fix_suite}"
mkdir -p "$OUT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
FIXTURES=$("$PYTHON" "$ROOT/scripts/ouro_smith.py" prepare --group fix)

CC_BIN="${CC:-cc}"
command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
if ! command -v "$CC_BIN" >/dev/null 2>&1; then
	echo "FIX_SUITE: FAIL no system C compiler; native fixes were not tested" >&2
	exit 1
fi

FIX="$OUT/ouro-fix"
rm -f "$FIX" "$FIX.exe"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tools/fix/main.ouro "$FIX" >"$OUT/build.log" 2>&1; then
	echo "FIX_SUITE: FAIL build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
fi
if [ -f "$FIX.exe" ]; then FIX="$FIX.exe"; fi

# Exercise the production planner, not the legacy raw-proposal golden helper.
PRECISION="$OUT/fix-precision"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tests/fix_precision.ouro "$PRECISION" >"$OUT/precision.build.log" 2>&1; then
	echo "FIX_SUITE: FAIL precision build" >&2
	tail -n 20 "$OUT/precision.build.log" >&2
	exit 1
fi
if [ -f "$PRECISION.exe" ]; then PRECISION="$PRECISION.exe"; fi
"$PRECISION"

PROOFS="$OUT/fix-proofs"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tests/fix_proofs.ouro "$PROOFS" >"$OUT/proofs.build.log" 2>&1; then
	echo "FIX_SUITE: FAIL proof build" >&2
	tail -n 20 "$OUT/proofs.build.log" >&2
	exit 1
fi
if [ -f "$PROOFS.exe" ]; then PROOFS="$PROOFS.exe"; fi
"$PROOFS"

# Invalid invocation must be rejected before any source is changed. Keep the
# drifted input and a clean input: conflicting modes used to succeed on clean.
printf '%s\n' 'def argument_value : Nat :=0;' >"$OUT/arguments.original"
printf '%s\n' 'def argument_value : Nat := 0;' >"$OUT/arguments-clean.ouro"
argument_refusal() {
	name=$1
	shift
	cp "$OUT/arguments.original" "$OUT/arguments.ouro"
	set +e
	"$FIX" "$@" >"$OUT/arguments-$name.out" 2>"$OUT/arguments-$name.err"
	status=$?
	set -e
	test "$status" -eq 2
	test ! -s "$OUT/arguments-$name.out"
	grep -F 'fix: invalid arguments' "$OUT/arguments-$name.err" >/dev/null
	cmp "$OUT/arguments.original" "$OUT/arguments.ouro"
}
argument_refusal unknown-value --write --unknown=1 "$OUT/arguments.ouro"
argument_refusal unknown-flag --write "$OUT/arguments.ouro" --unknown
argument_refusal unknown-short --write -x "$OUT/arguments.ouro"
argument_refusal bool-value --write=true "$OUT/arguments.ouro"
argument_refusal conflicting --check --write "$OUT/arguments.ouro"
argument_refusal conflicting-clean --check --write "$OUT/arguments-clean.ouro"
argument_refusal selftest-write --selftest --write "$OUT/arguments.ouro"
argument_refusal selftest-check --selftest --check
argument_refusal selftest-positional --selftest "$OUT/arguments.ouro"
argument_refusal selftest-missing --selftest --out
argument_refusal selftest-empty --selftest --out=
argument_refusal selftest-unknown --selftest --unknown=1

# The real write/check CLI must preserve a Unicode target and converge there.
unicode_dir="$OUT/каталог с пробелами"
unicode_file="$unicode_dir/漢字 file.ouro"
mkdir -p "$unicode_dir"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def unicode_value : Nat :=0;' >"$unicode_file"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def unicode_value : Nat := 0;' >"$OUT/unicode.expected"
set +e
"$FIX" --check "$unicode_file" >"$OUT/unicode-check.out" 2>"$OUT/unicode-check.err"
unicode_status=$?
set -e
test "$unicode_status" -eq 1
grep -F '漢字 file.ouro: needs formatting' "$OUT/unicode-check.err" >/dev/null
"$FIX" --write "$unicode_file" >"$OUT/unicode-write.out" 2>"$OUT/unicode-write.err"
cmp "$OUT/unicode.expected" "$unicode_file"
"$FIX" --check "$unicode_file"
"$FIX" --write "$unicode_file" >"$OUT/unicode-repeat.out" 2>"$OUT/unicode-repeat.err"
test ! -s "$OUT/unicode-repeat.out"
test ! -s "$OUT/unicode-repeat.err"
cmp "$OUT/unicode.expected" "$unicode_file"

# Directories select sorted .ouro files. Build/cache trees stay skipped unless
# a file under them is named explicitly. Empty scopes stay fail-closed.
dir_root="$OUT/dir-case"
mkdir -p "$dir_root/sub" "$dir_root/_build" "$OUT/empty-dir" "$OUT/notes-only"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def dirty_value : Nat :=0;' >"$dir_root/dirty.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def clean_value : Nat := 0;' >"$dir_root/clean.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def nested_value : Nat :=0;;' >"$dir_root/sub/nested.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def ignored_value : Nat :=0;;' >"$dir_root/_build/ignored.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def note_value : Nat :=0;;' >"$dir_root/note.txt"
cp "$dir_root/_build/ignored.ouro" "$OUT/ignored.original"
cp "$dir_root/note.txt" "$OUT/note.original"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def notes_only : Nat :=0;;' >"$OUT/notes-only/readme.txt"
cp "$dir_root/clean.ouro" "$OUT/dir-clean.original"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def dirty_value : Nat := 0;' >"$OUT/dir-dirty.expected"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' 'def nested_value : Nat := 0;' >"$OUT/dir-nested.expected"
set +e
"$FIX" --check "$dir_root" >"$OUT/dir-check.out" 2>"$OUT/dir-check.err"
dir_check_status=$?
set -e
test "$dir_check_status" -eq 1
test ! -s "$OUT/dir-check.out"
grep -F 'dirty.ouro: needs formatting' "$OUT/dir-check.err" >/dev/null
grep -F 'nested.ouro: needs' "$OUT/dir-check.err" >/dev/null
if grep -F 'clean.ouro' "$OUT/dir-check.err" >/dev/null; then
	echo "FIX_SUITE: FAIL clean directory member reported" >&2
	exit 1
fi
if grep -F 'ignored.ouro' "$OUT/dir-check.err" >/dev/null; then
	echo "FIX_SUITE: FAIL skipped _build member reported" >&2
	exit 1
fi
if grep -F 'note.txt' "$OUT/dir-check.err" >/dev/null; then
	echo "FIX_SUITE: FAIL non-ouro directory member reported" >&2
	exit 1
fi
cmp "$OUT/ignored.original" "$dir_root/_build/ignored.ouro"
cmp "$OUT/note.original" "$dir_root/note.txt"
"$FIX" --write "$dir_root" >"$OUT/dir-write.out" 2>"$OUT/dir-write.err"
cmp "$OUT/dir-dirty.expected" "$dir_root/dirty.ouro"
cmp "$OUT/dir-nested.expected" "$dir_root/sub/nested.ouro"
cmp "$OUT/dir-clean.original" "$dir_root/clean.ouro"
cmp "$OUT/ignored.original" "$dir_root/_build/ignored.ouro"
cmp "$OUT/note.original" "$dir_root/note.txt"
grep -F 'fixed ' "$OUT/dir-write.out" >/dev/null
grep -F 'dirty.ouro' "$OUT/dir-write.out" >/dev/null
grep -F 'nested.ouro' "$OUT/dir-write.out" >/dev/null
if grep -F 'ignored.ouro' "$OUT/dir-write.out" >/dev/null; then
	echo "FIX_SUITE: FAIL skipped _build member written" >&2
	exit 1
fi
"$FIX" --check "$dir_root"
"$FIX" --write "$dir_root" >"$OUT/dir-repeat.out" 2>"$OUT/dir-repeat.err"
test ! -s "$OUT/dir-repeat.out"
test ! -s "$OUT/dir-repeat.err"
set +e
"$FIX" --check "$dir_root/_build/ignored.ouro" >"$OUT/dir-explicit.out" 2>"$OUT/dir-explicit.err"
explicit_status=$?
set -e
test "$explicit_status" -eq 1
grep -F 'ignored.ouro: needs' "$OUT/dir-explicit.err" >/dev/null
set +e
"$FIX" --write "$OUT/empty-dir" >"$OUT/empty-dir.out" 2>"$OUT/empty-dir.err"
empty_status=$?
"$FIX" --check "$OUT/notes-only" >"$OUT/notes-only.out" 2>"$OUT/notes-only.err"
notes_status=$?
"$FIX" --check "$OUT/missing-dir.ouro" "$dir_root/clean.ouro" >"$OUT/mixed-missing.out" 2>"$OUT/mixed-missing.err"
mixed_status=$?
set -e
test "$empty_status" -eq 1
test ! -s "$OUT/empty-dir.out"
grep -F 'empty-dir: no .ouro files' "$OUT/empty-dir.err" >/dev/null
test "$notes_status" -eq 1
grep -F 'notes-only: no .ouro files' "$OUT/notes-only.err" >/dev/null
test "$mixed_status" -eq 1
grep -F 'missing-dir.ouro: no such file' "$OUT/mixed-missing.err" >/dev/null
if grep -F 'clean.ouro: needs' "$OUT/mixed-missing.err" >/dev/null; then
	echo "FIX_SUITE: FAIL clean sibling reported after missing path" >&2
	exit 1
fi

# Ambiguous constructor spellings must not be erased and then renamed as
# unused binders. Exercise both public refusal paths and preserve exact bytes.
binding_refusal() {
	name=$1
	source=$2
	input="$OUT/binding-$name.ouro"
	printf '%s\n' "$source" >"$input"
	cp "$input" "$OUT/binding-$name.original"
	for mode in check write; do
		set +e
		"$FIX" "--$mode" "$input" >"$OUT/binding-$name-$mode.out" 2>"$OUT/binding-$name-$mode.err"
		status=$?
		set -e
		test "$status" -eq 1
		grep -F 'fix refused: literal rewrite requires unbound built-in constructor names' "$OUT/binding-$name-$mode.err" >/dev/null
		cmp "$OUT/binding-$name.original" "$input"
	done
}
binding_refusal successor 'def keep (S : Nat -> Nat) : Nat := S (S (S Z));'
binding_refusal zero 'def keep (Z : Nat) : Nat := S (S (S Z));'
binding_refusal cons 'def keep (Cons : (A : Type) -> A -> List A -> List A) : List Nat := Cons Nat 1 (Nil Nat);'
binding_refusal nil 'def keep (Nil : (A : Type) -> List A) : List Nat := Cons Nat 1 (Nil Nat);'
binding_refusal lambda 'def keep : Nat -> Nat -> Nat -> Nat := fun x S y => S (S (S Z));'
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' >"$OUT/literal-nat.ouro"
printf '%s\n' 'import "literal-nat.ouro";' 'def literal_good (step : Nat -> Nat) : Nat := step (S (S (S Z)));' >"$OUT/literal-good.ouro"
cp "$OUT/literal-good.ouro" "$OUT/literal-good.expected"
"$FIX" --write "$OUT/literal-good.ouro" >"$OUT/literal-good.out" 2>"$OUT/literal-good.err"
cmp "$OUT/literal-good.expected" "$OUT/literal-good.ouro"
grep -F 'review-required suggestions (not applied)' "$OUT/literal-good.err" >/dev/null
set +e
"$FIX" --check "$OUT/literal-good.ouro" >"$OUT/literal-good.check.out" 2>"$OUT/literal-good.check.err"
literal_status=$?
set -e
test "$literal_status" -eq 1
cmp "$OUT/literal-good.expected" "$OUT/literal-good.ouro"

# Semantic let proposals remain review-only until preservation is certified.
# Repeated writes must retain the exact source and continue reporting review.
let_case() {
	name=$1
	before=$2
	after=$3
	review=${4:-0}
	input="$OUT/let-$name.ouro"
	printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' "$before" >"$input"
	printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' "$after" >"$OUT/let-$name.expected"
	"$FIX" --write "$input" >"$OUT/let-$name.out" 2>"$OUT/let-$name.err"
	cmp "$OUT/let-$name.expected" "$input"
	set +e
	"$FIX" --check "$input" >"$OUT/let-$name.check.out" 2>"$OUT/let-$name.check.err"
	check_status=$?
	set -e
	test "$check_status" -eq "$review"
	"$FIX" --write "$input" >"$OUT/let-$name.repeat.out" 2>"$OUT/let-$name.repeat.err"
	cmp "$OUT/let-$name.expected" "$input"
	test ! -s "$OUT/let-$name.repeat.out"
	if [ "$review" -eq 0 ]; then
		test ! -s "$OUT/let-$name.repeat.err"
	else
		grep -F 'review-required suggestions (not applied)' "$OUT/let-$name.repeat.err" >/dev/null
	fi
}
let_case literal \
	'def keep (value : Nat) : Nat := let unused := 7 in value;' \
	'def keep (value : Nat) : Nat := let unused := 7 in value;' 1
let_case opaque-call \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let unused := step value in value;' \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let unused := step value in value;' 1
let_case identity \
	'def keep (value : Nat) : Nat := let result := value in result;' \
	'def keep (value : Nat) : Nat := let result := value in result;' 1
let_case identity-call \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let result := step value in result;' \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let result := step value in result;' 1
let_case shadowed-identity \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let value := step value in value;' \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let value := step value in value;' 1
let_case typed-identity \
	'def keep (value : Nat) : Nat := let result : Nat := value in result;' \
	'def keep (value : Nat) : Nat := let result : Nat := value in result;'
let_case dependent-use \
	'def keep (value : Nat) : Nat := let ResultType := Nat in let result : ResultType := value in result;' \
	'def keep (value : Nat) : Nat := let ResultType := Nat in let result : ResultType := value in result;'
let_case application-tail \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let result := step in result value;' \
	'def keep (step : Nat -> Nat) (value : Nat) : Nat := let result := step in result value;'

# Comments belong to the source, not to a disposable initializer. Preserve
# the rationale and evaluation; an unproved binder rename stays review-only.
comment_source="$OUT/let-comment.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' \
	'def keep (value : Nat) : Nat := let unused := -- protocol rationale' \
	'    7 in value;' >"$comment_source"
"$FIX" --write "$comment_source" >"$OUT/let-comment.out" 2>"$OUT/let-comment.err"
grep -F -- '-- protocol rationale' "$comment_source" >/dev/null
grep -F 'let unused :=' "$comment_source" >/dev/null
grep -F 'review-required suggestions (not applied)' "$OUT/let-comment.err" >/dev/null
cp "$comment_source" "$OUT/let-comment.fixed"
"$FIX" --write "$comment_source" >"$OUT/let-comment.repeat.out" 2>"$OUT/let-comment.repeat.err"
cmp "$OUT/let-comment.fixed" "$comment_source"
test ! -s "$OUT/let-comment.repeat.out"
grep -F 'review-required suggestions (not applied)' "$OUT/let-comment.repeat.err" >/dev/null

# A review-only semantic finding must remain visible after an unchanged write.
set +e
"$PYTHON" scripts/clippy_grade_firewall.py --profile strict --include-fixtures \
	--scope "$OUT/let-identity.ouro" --report "$OUT/quality-review.json" --sarif "$OUT/quality-review.sarif" \
	>"$OUT/quality-review.out" 2>"$OUT/quality-review.err"
quality_review_status=$?
set -e
test "$quality_review_status" -eq 1
grep -F 'OURO-CLIPPY-REDUNDANT-001' "$OUT/quality-review.out" >/dev/null

# An automatically fixable syntax finding must disappear across all quality
# tools. Keep before/after logs and require a second write to be a no-op.
quality_source="$OUT/quality-after-fix.ouro"
printf '%s\n' 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;' \
	'def quality_identity (value : Nat) : Nat := value;;' >"$quality_source"
set +e
sh scripts/ouro1.sh lint --deny --family style "$quality_source" \
	>"$OUT/quality-before.out" 2>"$OUT/quality-before.err"
quality_before_status=$?
set -e
test "$quality_before_status" -eq 1
grep -F 'OURO-LINT042' "$OUT/quality-before.out" >/dev/null
"$FIX" --write "$quality_source" >"$OUT/quality-fix.out" 2>"$OUT/quality-fix.err"
sh scripts/ouro1.sh fmt --check "$quality_source" >"$OUT/quality-fmt.out" 2>"$OUT/quality-fmt.err"
sh scripts/ouro1.sh lint --deny "$quality_source" >"$OUT/quality-lint.out" 2>"$OUT/quality-lint.err"
"$PYTHON" scripts/clippy_grade_firewall.py --profile strict --include-fixtures \
	--scope "$quality_source" --report "$OUT/quality-after.json" --sarif "$OUT/quality-after.sarif" \
	>"$OUT/quality-clippy.out" 2>"$OUT/quality-clippy.err"
sh scripts/ouro1.sh analyze --strict --include-fixtures --enable-simplify --enable-dataflow \
	--scope "$quality_source" >"$OUT/quality-analyze.out" 2>"$OUT/quality-analyze.err"
cp "$quality_source" "$OUT/quality-fixed.original"
"$FIX" --check "$quality_source" >"$OUT/quality-check.out" 2>"$OUT/quality-check.err"
"$FIX" --write "$quality_source" >"$OUT/quality-repeat.out" 2>"$OUT/quality-repeat.err"
cmp "$OUT/quality-fixed.original" "$quality_source"
test ! -s "$OUT/quality-repeat.out"
test ! -s "$OUT/quality-repeat.err"

SOURCE_WRITE="$OUT/quality-source-write"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" tests/quality_source_write_driver.ouro "$SOURCE_WRITE" >"$OUT/source-write.build" 2>&1; then
	echo "FIX_SUITE: FAIL source transaction driver build" >&2
	tail -n 20 "$OUT/source-write.build" >&2
	exit 1
fi
if [ -f "$SOURCE_WRITE.exe" ]; then
	SOURCE_WRITE="$SOURCE_WRITE.exe"
fi
"$PYTHON" scripts/fs_replace_suite.py --driver "$SOURCE_WRITE" --fix "$FIX" \
	--recovery --out "$OUT/source-transactions"

"$PYTHON" scripts/fix_check_suite.py --fix "$FIX" --out "$OUT/compiler-check"
exec "$FIX" --selftest "--out=$OUT" "--fixtures=$FIXTURES" "$@"
