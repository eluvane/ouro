#!/usr/bin/env sh
# Security regressions at the public bootstrap compiler boundary.
set -eu

ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

OUT="${FRONTEND_SECURITY_OUT:-$ROOT/_build/frontend_security}"
mkdir -p "$OUT"
FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group security --out "$OUT/inputs")

if ! sh "$ROOT/scripts/bootstrap.sh" >"$OUT/bootstrap.out" 2>"$OUT/bootstrap.err"; then
	cat "$OUT/bootstrap.out" >&2
	cat "$OUT/bootstrap.err" >&2
	echo "FRONTEND_SECURITY_SUITE: FAIL bootstrap" >&2
	exit 1
fi

COMPILER="$ROOT/_build/c/ouro1"
if [ -x "$COMPILER.exe" ]; then
	COMPILER="$COMPILER.exe"
fi
if [ ! -x "$COMPILER" ]; then
	echo "FRONTEND_SECURITY_SUITE: FAIL compiler missing: $COMPILER" >&2
	exit 1
fi

rows=0

expect_good_module() {
	label=$1
	suffix=$2
	out="$OUT/module-good-$label.c"
	err="$OUT/module-good-$label.err"
	if ! "$COMPILER" "$FIXTURES/id.ouro" 999999 --module "$suffix" \
		>"$out" 2>"$err"; then
		cat "$err" >&2
		echo "FRONTEND_SECURITY_FAIL module-good-$label" >&2
		exit 1
	fi
	case "$suffix" in
	"") symbol='int ouro_export_count(void)' ;;
	*) symbol="int ouro_export_count${suffix}(void)" ;;
	esac
	if ! grep -Fq "$symbol" "$out"; then
		echo "FRONTEND_SECURITY_FAIL module-good-$label missing symbol: $symbol" >&2
		exit 1
	fi
	rows=$((rows + 1))
	echo "FRONTEND_SECURITY_OK module-good-$label"
}

expect_bad_module() {
	label=$1
	suffix=$2
	out="$OUT/module-bad-$label.out"
	err="$OUT/module-bad-$label.err"
	set +e
	"$COMPILER" "$FIXTURES/id.ouro" 999999 --module "$suffix" \
		>"$out" 2>"$err"
	status=$?
	set -e
	if [ "$status" -ne 2 ] || [ -s "$out" ] ||
		! grep -Fq -- '--module must be empty or match _[A-Za-z0-9_]+' "$err"; then
		cat "$out" >&2
		cat "$err" >&2
		echo "FRONTEND_SECURITY_FAIL module-bad-$label status=$status" >&2
		exit 1
	fi
	rows=$((rows + 1))
	echo "FRONTEND_SECURITY_OK module-bad-$label"
}

expect_lex_reject() {
	label=$1
	file=$2
	fuel=$3
	want=$4
	shift 4
	out="$OUT/lex-$label.out"
	err="$OUT/lex-$label.err"
	set +e
	"$COMPILER" check "$file" "$fuel" "$@" >"$out" 2>"$err"
	status=$?
	set -e
	if [ "$status" -ne 1 ] || ! grep -Fq "$want" "$err"; then
		cat "$out" >&2
		cat "$err" >&2
		echo "FRONTEND_SECURITY_FAIL lex-$label status=$status want=$want" >&2
		exit 1
	fi
	rows=$((rows + 1))
	echo "FRONTEND_SECURITY_OK lex-$label"
}

expect_good_module empty ""
expect_good_module identifier _safe_09

expect_bad_module no-underscore unsafe
expect_bad_module empty-identifier _
expect_bad_module whitespace '_bad suffix'
expect_bad_module comment '_bad/*comment*/'
expect_bad_module preprocessor '_bad#directive'
expect_bad_module quote '_bad"quote'
expect_bad_module punctuation '_bad;statement'
newline_suffix=$(printf '_bad\nstatement')
expect_bad_module newline "$newline_suffix"

expect_lex_reject trailing-invalid \
	"$FIXTURES/lex-trailing-invalid.ouro" 999999 'CErr code=11'
expect_lex_reject unterminated-string \
	"$FIXTURES/lex-unterminated-string.ouro" 999999 'CErr code=11'
expect_lex_reject bare-operator \
	"$FIXTURES/lex-bare-operator.ouro" 999999 'CErr code=11'
expect_lex_reject fuel-exhausted "$FIXTURES/id.ouro" 0 'CErr code=12'

# Errors at every incremental seam must retain their typed diagnostic without
# re-running the removed whole-unit compiler fallback.
expect_lex_reject parse-error "$FIXTURES/parse-missing-colon.ouro" 999999 'CErr code=10'
expect_lex_reject preprocess-error "$FIXTURES/record-malformed.ouro" 999999 'OURO-REC-001'
expect_lex_reject resolve-error "$FIXTURES/id.ouro" 999999 'CErr code=92' \
	--unit "$FIXTURES/other.ouro"

# These inputs establish a false source-scanner accusation independently of
# the typed transport. The public producer must retain raw refusal and owner.
TRACE_INPUTS="$OUT/lower-owner"
mkdir -p "$TRACE_INPUTS"
cat >"$TRACE_INPUTS/prefix.ouro" <<'EOF'
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
def values : List Nat := [Z,];
EOF
cp "$TRACE_INPUTS/prefix.ouro" "$TRACE_INPUTS/prior-list.ouro"
printf '%s\n' 'def unrelated : Nat := missing;' >>"$TRACE_INPUTS/prior-list.ouro"
cat >"$TRACE_INPUTS/no-list.ouro" <<'EOF'
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
def unrelated : Nat := missing;
EOF
cat >"$TRACE_INPUTS/bad-list.ouro" <<'EOF'
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
def bad : Nat := [];
EOF
cat >"$TRACE_INPUTS/nested.ouro" <<'EOF'
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
def nested (x : Nat) : Nat := [];
EOF
cat >"$TRACE_INPUTS/named.ouro" <<'EOF'
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
def goal : Nat := ?pending;
EOF
cat >"$TRACE_INPUTS/import-unrelated.ouro" <<'EOF'
import "prefix.ouro";
def unrelated : Nat := missing;
EOF
cat >"$TRACE_INPUTS/import-bad.ouro" <<'EOF'
import "bad-list.ouro";
def value : Nat := Z;
EOF

expect_source_owner() {
	label=$1
	file=$2
	want=$3
	forbidden=$4
	shift 4
	out="$OUT/owner-$label.out"
	err="$OUT/owner-$label.err"
	set +e
	"$COMPILER" check "$file" 999999 "$@" >"$out" 2>"$err"
	status=$?
	set -e
	if [ "$status" -ne 1 ] || [ -s "$out" ] ||
		! grep -Fq 'CErr code=2 det=0' "$err" || ! grep -Fq "$want" "$err" ||
		grep -Fq "$forbidden" "$err"; then
		cat "$out" >&2
		cat "$err" >&2
		echo "FRONTEND_SECURITY_FAIL owner-$label status=$status" >&2
		exit 1
	fi
	rows=$((rows + 1))
	echo "FRONTEND_SECURITY_OK owner-$label"
}

if ! "$COMPILER" check "$TRACE_INPUTS/prefix.ouro" 999999 \
	>"$OUT/owner-prefix.out" 2>"$OUT/owner-prefix.err" ||
	! grep -Fq 'CHECK_OK' "$OUT/owner-prefix.out"; then
	cat "$OUT/owner-prefix.out" >&2
	cat "$OUT/owner-prefix.err" >&2
	echo "FRONTEND_SECURITY_FAIL owner-prefix" >&2
	exit 1
fi
rows=$((rows + 1))
echo "FRONTEND_SECURITY_OK owner-prefix"
expect_source_owner prior-list "$TRACE_INPUTS/prior-list.ouro" \
	'<input>: compilation failed in unrelated (surface); code=2 detail=0' 'OURO-LIST-001'
expect_source_owner no-list "$TRACE_INPUTS/no-list.ouro" \
	'<input>: compilation failed in unrelated (surface); code=2 detail=0' 'OURO-LIST-001'
expect_source_owner root-list "$TRACE_INPUTS/bad-list.ouro" \
	'<input>: OURO-LIST-001: list literal without known List A context in bad (surface)' '<input>:1:1'
expect_source_owner nested "$TRACE_INPUTS/nested.ouro" \
	'<input>: compilation failed in nested (surface); code=2 detail=0' 'OURO-LIST-001'
expect_source_owner named "$TRACE_INPUTS/named.ouro" \
	'<input>: OURO-HOLE-001: unresolved named hole in goal (surface)' '<input>:1:1'
expect_source_owner imported-prior-list "$TRACE_INPUTS/import-unrelated.ouro" \
	'import-unrelated.ouro: compilation failed in unrelated (surface); code=2 detail=0' 'OURO-LIST-001' \
	--unit "$TRACE_INPUTS/prefix.ouro" --unit "$TRACE_INPUTS/import-unrelated.ouro"
expect_source_owner imported-bad "$TRACE_INPUTS/import-bad.ouro" \
	'bad-list.ouro: OURO-LIST-001: list literal without known List A context in bad (surface)' 'import-bad.ouro: OURO-LIST-001' \
	--unit "$TRACE_INPUTS/bad-list.ouro" --unit "$TRACE_INPUTS/import-bad.ouro"

"$PYTHON" "$ROOT/scripts/frontend_host_suite.py" --compiler "$COMPILER" \
	--out "$OUT/host" --jobs 1

echo "FRONTEND_SECURITY_SUITE: PASS rows=$rows out=$OUT"
