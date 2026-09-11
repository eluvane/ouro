#!/usr/bin/env sh
# Seed hygiene is fail-closed: blobs, hashes, banners, packer, kernel hardening, and stage evidence must agree.

set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${PYTHON:-}" ]; then
	echo "HYGIENE_FAIL no working python (set PYTHON=)" >&2
	exit 1
fi

fail=0
ok() { echo "HYGIENE_OK  $*"; }
bad() { echo "HYGIENE_FAIL $*" >&2; fail=$((fail + 1)); }

if [ -f docs/generated_artifact_hashes.sha256 ]; then
	if sha256sum -c docs/generated_artifact_hashes.sha256 >/dev/null 2>&1; then
		ok "stage0 hashes"
	else
		bad "stage0 hashes drifted"
		sha256sum -c docs/generated_artifact_hashes.sha256 || true
	fi
else
	bad "missing docs/generated_artifact_hashes.sha256"
fi

for f in compiler/stage0/driver_u.c compiler/stage0/backend_u.c; do
	if grep -q "Do not hand-edit\|Generated frontend pack\|static ouro_v \*ouro_g" "$f"; then
		ok "generated shape $f"
	else
		bad "unexpected shape in $f"
	fi
done

if "$PYTHON" scripts/pack_frontend.py --selftest >/tmp/pack_selftest.out 2>&1; then
	ok "packer selftest"
else
	bad "packer selftest"
	cat /tmp/pack_selftest.out >&2 || true
fi

if "$PYTHON" scripts/kernel_hardening_suite.py >/tmp/kernel_hardening_suite.out 2>&1; then
	ok "kernel hardening suite"
else
	bad "kernel hardening suite"
	cat /tmp/kernel_hardening_suite.out >&2 || true
fi

if "$PYTHON" scripts/github_workflow_gate.py >/tmp/github_workflow_gate.out 2>&1; then
	ok "github workflow gate"
else
	bad "github workflow gate"
	cat /tmp/github_workflow_gate.out >&2 || true
fi

if "$PYTHON" scripts/generated_artifact_drift_check.py --mode hashes >/tmp/generated_artifact_drift_hashes.out 2>&1; then
	ok "generated artifact hash drift gate"
else
	bad "generated artifact hash drift gate"
	cat /tmp/generated_artifact_drift_hashes.out >&2 || true
fi

if "$PYTHON" scripts/github_project_gate.py >/tmp/github_project_gate.out 2>&1; then
	ok "github project gate"
else
	bad "github project gate"
	cat /tmp/github_project_gate.out >&2 || true
fi

if "$PYTHON" scripts/release_package.py --check --out _build/release_check >/tmp/release_package_check.out 2>&1; then
	ok "release package check"
else
	bad "release package check"
	cat /tmp/release_package_check.out >&2 || true
fi

if "$PYTHON" scripts/docs_examples_gate.py >/tmp/docs_examples_gate.out 2>&1; then
	ok "docs/examples gate"
else
	bad "docs/examples gate"
	cat /tmp/docs_examples_gate.out >&2 || true
fi

if "$PYTHON" scripts/strict_quality_firewall.py --profile release --report _build/quality/strict-quality-firewall.json --sarif _build/quality/strict-quality-firewall.sarif --migration-report _build/quality/migration-report.md >/tmp/strict_quality_firewall.out 2>&1; then
	ok "strict quality firewall"
else
	bad "strict quality firewall"
	cat /tmp/strict_quality_firewall.out >&2 || true
fi

for f in \
	compiler/extract.ouro \
	compiler/pipeline.ouro \
	compiler/desugar_record.ouro \
	compiler/preprocess_record.ouro \
	compiler/preprocess_import.ouro \
	tools/collect.ouro \
	compiler/backend.ouro \
	compiler/print_c.ouro \
	scripts/stage_loop.sh \
	scripts/stage_loop.py \
	scripts/frontend_regen.py \
	scripts/parity_suite.sh
do
	if [ -f "$f" ]; then
		ok "present $f"
	else
		bad "missing $f"
	fi
done

if grep -q "normalize_ir" compiler/extract.ouro \
	&& ! grep -q "ctor_type_drop" runtime/bootstrap.c \
	&& ! grep -q "fun_type_drop" runtime/bootstrap.c \
	&& ! grep -q "strip_jsir" runtime/bootstrap.c \
	&& ! grep -q "g_extract_strips" runtime/bootstrap.c \
	&& ! grep -q "text, dropped = strip_poly_type_apps" scripts/pack_frontend.py \
	&& ! grep -q "static int shadowed" runtime/bootstrap.c \
	&& ! test -f runtime/ouro1_main.c; then
	ok "extract.ouro is the only type-app erasure; bootstrap.c is a runtime driver"
else
	bad "type-app strip, IR proof-walk, or dead ouro1_main.c still present"
fi

if grep -q "compile_checked_from_decls" compiler/pipeline.ouro \
	&& grep -q "pipeline_compile_checked_source" compiler/driver.ouro \
	&& grep -q "pipeline_compile_checked_units" compiler/driver.ouro \
	&& grep -q "check_module fuel selected items" compiler/pipeline_support.ouro \
	&& grep -q "checked_program_erase (compile_checked_source" compiler/driver.ouro \
	&& grep -q "checked_program_erase (compile_checked_units" compiler/driver.ouro; then
	ok "host/selfhost stitch share checked declaration pipeline"
else
	bad "pipeline/driver stitch drift"
fi

if grep -q '("pl", "_pl", "compiler/pipeline.ouro", "pl.c")' scripts/frontend_regen.py \
	&& grep -q 'scripts/frontend_regen.py' scripts/emit_frontend.sh \
	&& grep -q 'emit_frontend(prev' scripts/stage_loop.py \
	&& grep -q 'FIND(pl, "compile_checked_from_decls")' runtime/frontend_link.c \
	&& grep -q 'parse_units_incremental(fuel' runtime/frontend_link.c \
	&& ! grep -q 'compile_units_legacy_impl' runtime/frontend_link.c \
	&& grep -q 'FIND(pl, "stitch_checked_source")' runtime/frontend_link.c \
	&& grep -q 'ouro_fe_compile_checked_units' runtime/frontend_link.c \
	&& [ ! -f runtime/ouro_fe_glue.c ]; then
	ok "pipeline.ouro packed as pl TU (main stitcher); glue is generated fe_link"
else
	bad "pipeline.ouro is not the packed stitcher"
fi

if grep -q "expand_records" compiler/desugar_record.ouro \
	&& grep -q "preprocess_records_reg" compiler/preprocess_record.ouro; then
	ok "record expansion specified on Ouro"
else
	bad "record expansion source missing"
fi

# Needles are literal source text, including `$` assignments.
# shellcheck disable=SC2016
if grep -q 'COLLECT="$C_BUILD_DIR/ouro-collect"' scripts/ouro1.sh \
	&& grep -q 'ensure_collect' scripts/ouro1.sh \
	&& grep -q 'tools/collect.ouro' scripts/ouro1.sh \
	&& grep -q 'collect_unit_lines' scripts/ouro1.sh \
	&& grep -q 'scripts/native_tool_build.py' scripts/build_tool.sh \
	&& grep -q 'frontend.collect_units' scripts/native_tool_build.py \
	&& ! grep -q 'ouro1_host collect' scripts/ouro1.sh \
	&& ! grep -q 'HOST.*collect' scripts/ouro1.sh; then
	ok "check/collect use Ouro ouro-collect, not C collect_post"
else
	bad "check/collect still call C collect_post or ouro-collect is not wired"
fi

# shellcheck disable=SC2016
if grep -q 'BIN="$C_BUILD_DIR/ouro-analyze"' scripts/ouro1.sh \
	&& grep -q 'tools/analyze/main.ouro' scripts/ouro1.sh \
	&& [ -f tools/analyze/main.ouro ] \
	&& [ ! -f runtime/ouro_analyze_families.c ] \
	&& [ ! -f runtime/ouro1_host.c ] \
	&& ! grep -q 'ouro1_host' scripts/ouro1.sh; then
	ok "analyze uses Ouro ouro-analyze, not C ouro1_host analyze"
else
	bad "analyze still calls C host or ouro-analyze is not wired"
fi

if [ ! -f runtime/ouro1_host.c ] \
	&& grep -q 'def __ouro_eval' scripts/ouro1.sh \
	&& grep -q 'ouro_eval_main.c' scripts/ouro1.sh \
	&& ! grep -q 'ouro1_host' scripts/ouro1.sh; then
	ok "eval/check use ouro-collect + compiler; ouro1_host.c is gone"
else
	bad "eval still uses C ouro1_host or wrap/emit is not wired"
fi

if [ ! -f runtime/ouro8_rebuild.c ] \
	&& [ ! -f scripts/o8_rebuild.sh ] \
	&& grep -q 'stage_loop.sh' scripts/ouro1.sh \
	&& ! grep -q 'frontend emit skipped' scripts/stage_loop.py; then
	ok "rebuild is stage_loop; obsolete aliases are gone"
else
	bad "ouro8_rebuild or its obsolete alias is still present"
fi

if grep -q '("pi", "_pi", "compiler/preprocess_import.ouro", "pi.c")' scripts/frontend_regen.py \
	&& grep -q 'FIND(pi, "preprocess_imports_reg")' runtime/frontend_link.c \
	&& grep -q "preprocess_imports_reg" compiler/preprocess_import.ouro \
	&& grep -q "preprocess_file_list" compiler/pipeline.ouro \
	&& ! grep -q "src_has_record_keyword" runtime/frontend_link.c \
	&& ! grep -q "preprocess_files" runtime/frontend_link.c \
	&& grep -q "classify_ergo" compiler/pipeline.ouro \
	&& ! grep -q "print_ergo_diags" runtime/frontend_link.c \
	&& grep -q "closed_parse_file" compiler/parser_file.ouro \
	&& grep -q 'FIND(pf, "closed_parse_file")' runtime/frontend_link.c \
	&& ! grep -q "is_core_mode" runtime/frontend_link.c \
	&& grep -q "def ensure_fe_link" scripts/ouro_build.py; then
	ok "preprocess + ergo classify + parse dispatch run in packed TUs"
else
	bad "preprocess/ergo/parse dispatch still live in C or are not wired"
fi

if [ ! -f runtime/ouro8_rebuild.c ] \
	&& ! grep -q "frontend emit skipped" scripts/stage_loop.py; then
	ok "O8 has no silent frontend skip (C rebuild gone)"
else
	bad "O8 still silently skips frontend emit or C rebuild remains"
fi

if [ -f _build/stage_loop/result.json ]; then
	"$PYTHON" - <<'PY'
import json, sys
p = json.load(open("_build/stage_loop/result.json"))
fp = bool(p.get("pass") and p.get("frontend_eq") and p.get("backend_eq"))
print(("HYGIENE_OK  stage_loop fixpoint" if fp else "HYGIENE_INFO stage_loop ran, no frontend+backend fixpoint yet"))
sys.exit(0)
PY
else
	echo "HYGIENE_SKIP stage_loop result (not yet run)"
fi

if [ "$fail" -ne 0 ]; then
	echo "HYGIENE: FAIL checks=$fail" >&2
	exit 1
fi
echo "HYGIENE: PASS"
exit 0
