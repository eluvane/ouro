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

"$PYTHON" "$ROOT/scripts/frontend_host_suite.py" --compiler "$COMPILER" \
	--out "$OUT/host" --jobs 1

echo "FRONTEND_SECURITY_SUITE: PASS rows=$rows out=$OUT"
