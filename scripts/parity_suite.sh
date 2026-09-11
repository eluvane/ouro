#!/usr/bin/env sh
# Host path vs selfhost/direct path parity.
# Host:  scripts/ouro1.sh check FILE   (ouro-collect + exec ouro1)
# Direct: _build/c/ouro1 check FILE --unit …
# After a stage loop, also compare stage0 vs last stage on the same files.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
export OURO_ROOT="$ROOT"

if [ ! -x "$ROOT/_build/c/ouro1" ]; then
	sh "$ROOT/scripts/bootstrap.sh"
fi

DIRECT="$ROOT/_build/c/ouro1"
OUT="${PARITY_OUT:-$ROOT/_build/parity}"
mkdir -p "$OUT"
FUEL="${OURO1_CHECK_FUEL:-999999}"

collect() {
	sh "$ROOT/scripts/ouro1.sh" collect "$1"
}

run_direct() {
	file=$1
	out=$2
	units=""
	n=0
	first=""
	for u in $(collect "$file"); do
		u=$(printf '%s' "$u" | tr -d '\r')
		n=$((n + 1))
		[ -n "$first" ] || first=$u
		units="$units --unit $u"
	done
	# Same singleton rule as ouro1.sh check: seed compile_units
	# collapses OURO-LIST-001 to CErr 2. Keep --unit for
	# effect/perform/handle so rewrite_handlers runs.
	if [ "$n" -le 1 ] && { [ -z "$first" ] || [ "$first" = "$file" ]; }; then
		if ! grep -Eq '(^|[[:space:]])(effect|perform|handle)[[:space:]]' "$file"
		then
			units=""
		fi
	fi
	set +e
	# Flattened `--unit` argv built above; POSIX sh has no arrays here.
	# shellcheck disable=SC2086
	"$DIRECT" check "$file" "$FUEL" $units >"$out" 2>&1
	echo $? >"$out.st"
	set -e
}

run_host() {
	file=$1
	out=$2
	set +e
	sh "$ROOT/scripts/ouro1.sh" check "$file" "$FUEL" >"$out" 2>&1
	echo $? >"$out.st"
	set -e
}

FILES="
std/io.ouro
samples/examples/nat.ouro
std/record_demo.ouro
std/import_alias_demo.ouro
compiler/extract.ouro
compiler/desugar_record.ouro
"

rows=0
fail=0

cmp_pair() {
	id=$1
	a=$2
	b=$3
	rows=$((rows + 1))
	sa=$(cat "$a.st")
	sb=$(cat "$b.st")
	if [ "$sa" != "$sb" ]; then
		echo "PARITY_FAIL $id status host=$sa direct=$sb" >&2
		fail=$((fail + 1))
		return
	fi
	# FILES and the stage comparison are positive programs. Matching failures
	# must not turn a rejected compiler module into successful parity evidence.
	if [ "$sa" != "0" ]; then
		echo "PARITY_FAIL $id positive program rejected status=$sa" >&2
		fail=$((fail + 1))
		return
	fi
	ga=$(grep -E 'CHECK_OK|CHECK_FAIL|OURO-[A-Z]+-[0-9]+' "$a" | tail -n 1 || true)
	gb=$(grep -E 'CHECK_OK|CHECK_FAIL|OURO-[A-Z]+-[0-9]+' "$b" | tail -n 1 || true)
	if [ "$ga" != "$gb" ]; then
		echo "PARITY_FAIL $id verdict host='$ga' direct='$gb'" >&2
		fail=$((fail + 1))
		return
	fi
	echo "PARITY_OK $id status=$sa"
}

for f in $FILES; do
	[ -f "$f" ] || { echo "PARITY_FAIL missing $f" >&2; exit 1; }
	id=$(echo "$f" | tr '/.' '__')
	run_host "$f" "$OUT/host_$id.txt"
	run_direct "$f" "$OUT/direct_$id.txt"
	cmp_pair "$f" "$OUT/host_$id.txt" "$OUT/direct_$id.txt"
done

"$PYTHON" scripts/ouro_smith.py replay --layer surface --seed 1 \
	--case surface-1-compiler_parity --out "$OUT/smith"

STAGE_BIN=""
# Only compare a stage binary that is a recorded FE+BE fixpoint.
# A linked stage1 whose regenerated FE does not parse is not parity evidence.
if [ -f "$ROOT/_build/stage_loop/result.json" ]; then
	if "$PYTHON" - <<'PY'
import json, sys
p = json.load(open("_build/stage_loop/result.json"))
sys.exit(0 if p.get("pass") and p.get("frontend_eq") and p.get("backend_eq") else 1)
PY
	then
		if [ -x "$ROOT/_build/stage_loop/ouro1_stage2" ]; then
			STAGE_BIN="$ROOT/_build/stage_loop/ouro1_stage2"
		elif [ -x "$ROOT/_build/stage_loop/ouro1_stage1" ]; then
			STAGE_BIN="$ROOT/_build/stage_loop/ouro1_stage1"
		fi
	fi
fi
if [ -n "$STAGE_BIN" ]; then
	f=samples/examples/nat.ouro
	id=stage_vs_seed_nat
	units=""
	for u in $(collect "$f"); do
		units="$units --unit $u"
	done
	set +e
	# shellcheck disable=SC2086
	"$DIRECT" check "$f" "$FUEL" $units >"$OUT/seed_$id.txt" 2>&1
	echo $? >"$OUT/seed_$id.txt.st"
	# shellcheck disable=SC2086
	"$STAGE_BIN" check "$f" "$FUEL" $units >"$OUT/stage_$id.txt" 2>&1
	echo $? >"$OUT/stage_$id.txt.st"
	set -e
	cmp_pair "stage-vs-seed:$f" "$OUT/seed_$id.txt" "$OUT/stage_$id.txt"
fi

if [ "$fail" -ne 0 ]; then
	echo "PARITY_SUITE: FAIL rows=$rows failures=$fail" >&2
	printf '{"pass":false,"rows":%s,"fail":%s}\n' "$rows" "$fail" >"$OUT/result.json"
	exit 1
fi
echo "PARITY_SUITE: PASS rows=$rows out=$OUT"
printf '{"pass":true,"rows":%s,"fail":0}\n' "$rows" >"$OUT/result.json"
exit 0
