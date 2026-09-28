#!/usr/bin/env python3
"""Diagnostic-only copy of pinned handwritten frontend glue; never a Host receipt."""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

STOCK_BLOB = "f10104eb4bc30055dabb3163a82f181c6eae9f1a"

HELPERS = r"""
/* Diagnostic inputs and original results predate each bounded_call mark.
   Only numeric snapshots survive the callback; name lookup runs before cleanup. */
static ouro_v *perm_nil(void);
static ouro_v *perm_cons(ouro_v *head, ouro_v *tail);

static struct {
    int active, complete, found, found_hole;
    int depth, hole, surface_depth, surface_hole, surface_tag;
    unsigned long raw_code, raw_detail, name, hole_name, code, detail;
} nltp_observed;

static int nltp_error(ouro_v *value, unsigned long *code, unsigned long *detail)
{
    ouro_v *error;
    if (value == 0 || value->tag != 0 || value->n != 1)
        return 0;
    error = OURO_F(value, 0);
    return error != 0 && error->tag == 0 && error->n == 2
        && ouro_nat_to_ulong(OURO_F(error, 0), code)
        && ouro_nat_to_ulong(OURO_F(error, 1), detail);
}

static int nltp_bool(ouro_v *value, int *out)
{
    if (value == 0 || value->n != 0 || (value->tag != 0 && value->tag != 1))
        return 0;
    *out = value->tag == 0;
    return 1;
}

static int nltp_surface_flag(const char *function, ouro_v *surface, int *out)
{
    ouro_v *result = bounded_call(FIND(pl, function), 1,
        (ouro_v *[]){surface}, ouro_clone_perm);
    return nltp_bool(result, out);
}

static void nltp_observe_surfaces(ouro_v *surfaces, ouro_v *original)
{
    const char *enabled = getenv("OURO_NATIVE_LOWER_PROBE");
    ouro_v *current, *context, *result;
    if (enabled == 0 || strcmp(enabled, "1") != 0)
        return;
    memset(&nltp_observed, 0, sizeof(nltp_observed));
    if (!nltp_error(original, &nltp_observed.raw_code, &nltp_observed.raw_detail)
        || nltp_observed.raw_code != 2)
        return;
    nltp_observed.active = 1;
    result = bounded_call(FIND(pl, "surfaces_depth_at_least"), 2,
        (ouro_v *[]){FIND(pl, "depth_gate"), surfaces}, ouro_clone_perm);
    if (!nltp_bool(result, &nltp_observed.depth))
        return;
    result = bounded_call(FIND(pl, "surfaces_have_hole"), 1,
        (ouro_v *[]){surfaces}, ouro_clone_perm);
    if (!nltp_bool(result, &nltp_observed.hole))
        return;
    fprintf(stderr, "NLT_NATIVE_RAW code=%lu detail=%lu depth32=%d hole=%d\n",
        nltp_observed.raw_code, nltp_observed.raw_detail,
        nltp_observed.depth, nltp_observed.hole);
    fflush(stderr);
    if (nltp_observed.hole) {
        for (current = surfaces; !list_done(current); current = OURO_F(current, 1)) {
            ouro_v *pair;
            int has_hole;
            if (current == 0 || current->tag != 1 || current->n != 2)
                return;
            pair = OURO_F(current, 0);
            if (pair == 0 || pair->tag != 0 || pair->n != 2
                || !nltp_surface_flag("surface_has_hole", OURO_F(pair, 1), &has_hole))
                return;
            if (has_hole) {
                if (!ouro_nat_to_ulong(OURO_F(pair, 0), &nltp_observed.hole_name))
                    return;
                nltp_observed.found_hole = 1;
                break;
            }
        }
        if (!nltp_observed.found_hole)
            return;
    }
    context = perm_nil();
    for (current = surfaces; !list_done(current); current = OURO_F(current, 1)) {
        ouro_v *pair, *name, *surface;
        if (current == 0 || current->tag != 1 || current->n != 2)
            return;
        pair = OURO_F(current, 0);
        if (pair == 0 || pair->tag != 0 || pair->n != 2)
            return;
        name = OURO_F(pair, 0);
        surface = OURO_F(pair, 1);
        result = bounded_call(FIND(co, "compile_pipeline"), 2,
            (ouro_v *[]){surface, context}, ouro_clone_perm);
        if (result != 0 && result->tag == 0) {
            if (!nltp_error(result, &nltp_observed.code, &nltp_observed.detail)
                || !ouro_nat_to_ulong(name, &nltp_observed.name)
                || surface == 0
                || !nltp_surface_flag("surface_has_hole", surface, &nltp_observed.surface_hole))
                return;
            result = bounded_call(FIND(pl, "surface_depth_at_least"), 2,
                (ouro_v *[]){FIND(pl, "depth_gate"), surface}, ouro_clone_perm);
            if (!nltp_bool(result, &nltp_observed.surface_depth))
                return;
            nltp_observed.surface_tag = surface->tag;
            nltp_observed.found = 1;
            break;
        }
        if (result == 0 || result->tag != 1 || result->n != 1)
            return;
        context = perm_cons(name, context);
    }
    nltp_observed.complete = nltp_observed.found
        && nltp_observed.code == nltp_observed.raw_code
        && nltp_observed.detail == nltp_observed.raw_detail;
    fprintf(stderr, "NLT_NATIVE_FIRST id=%lu code=%lu detail=%lu surface_tag=%d depth32=%d hole=%d complete=%d\n",
        nltp_observed.name, nltp_observed.code, nltp_observed.detail,
        nltp_observed.surface_tag, nltp_observed.surface_depth,
        nltp_observed.surface_hole, nltp_observed.complete);
    fflush(stderr);
}

static int nltp_name(ouro_v *intern, unsigned long wanted, char *buffer, int capacity)
{
    ouro_v *current;
    unsigned long left = 100000UL;
    if (intern == 0 || intern->tag != 0 || intern->n != 4)
        return 0;
    current = OURO_F(intern, 0);
    while (!list_done(current) && left-- != 0) {
        ouro_v *pair;
        unsigned long id;
        if (current == 0 || current->tag != 1 || current->n != 2)
            return 0;
        pair = OURO_F(current, 0);
        if (pair == 0 || pair->tag != 0 || pair->n != 2
            || !ouro_nat_to_ulong(OURO_F(pair, 1), &id))
            return 0;
        if (id == wanted) {
            int length = codes_to_buf(OURO_F(pair, 0), buffer, capacity);
            return length > 0 && length < capacity - 1;
        }
        current = OURO_F(current, 1);
    }
    return 0;
}

static void nltp_report_before_cleanup(ouro_v *intern, ouro_v *original)
{
    char first[512], hole[512];
    unsigned long code = 0, detail = 0;
    int name_ok, hole_ok;
    if (!nltp_observed.active)
        return;
    name_ok = nltp_observed.found && nltp_name(intern, nltp_observed.name, first, sizeof(first));
    hole_ok = !nltp_observed.found_hole
        || nltp_name(intern, nltp_observed.hole_name, hole, sizeof(hole));
    if (!nltp_error(original, &code, &detail))
        nltp_observed.complete = 0;
    fprintf(stderr, "NLT_NATIVE_NAME id=%lu name=%s lookup=%d\n",
        nltp_observed.name, name_ok ? first : "UNAVAILABLE", name_ok);
    if (nltp_observed.found_hole)
        fprintf(stderr, "NLT_NATIVE_HOLE id=%lu name=%s lookup=%d\n",
            nltp_observed.hole_name, hole_ok ? hole : "UNAVAILABLE", hole_ok);
    else
        fputs("NLT_NATIVE_HOLE status=none\n", stderr);
    fprintf(stderr, "NLT_NATIVE_FINAL code=%lu detail=%lu checker=%s complete=%d\n",
        code, detail, (!nltp_observed.depth || nltp_observed.hole)
            ? "NOT_RUN_BLOCKED_PREFLIGHT" : "NOT_OBSERVED_FALLBACK_POSSIBLE",
        nltp_observed.complete && name_ok && hole_ok);
    fflush(stderr);
}
"""

ORIGINAL = """static ouro_v *bounded_compile_program(ouro_env *env, ouro_v *surfaces)
{
\t(void)env;
\treturn bounded_call(FIND(co, "compile_program"), 1,
\t\t(ouro_v *[]){surfaces}, ouro_clone_perm);
}"""

REPLACEMENT = """static ouro_v *bounded_compile_program(ouro_env *env, ouro_v *surfaces)
{
\touro_v *original;
\t(void)env;
\toriginal = bounded_call(FIND(co, "compile_program"), 1,
\t\t(ouro_v *[]){surfaces}, ouro_clone_perm);
\tnltp_observe_surfaces(surfaces, original);
\treturn original;
}"""

FINAL_MARKER = "\tg_last_intern = ouro_clone_perm_deep(st2);\n\touro_perm_reset_bank(0);"

def generate(source: Path, output: Path) -> dict:
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != STOCK_BLOB:
        raise ValueError(f"stock frontend blob mismatch: {blob}")
    text = raw.decode("utf-8")
    if text.count(ORIGINAL) != 1 or text.count(FINAL_MARKER) != 1:
        raise ValueError("observer insertion boundary does not occur exactly once")
    result = text.replace(ORIGINAL, HELPERS + "\n" + REPLACEMENT)
    result = result.replace(FINAL_MARKER,
        "\tg_last_intern = ouro_clone_perm_deep(st2);\n"
        "\tnltp_report_before_cleanup(g_last_intern, r);\n"
        "\touro_perm_reset_bank(0);")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding="utf-8", newline="\n")
    return {"stock_blob": blob, "stock_sha256": hashlib.sha256(raw).hexdigest(),
            "observer_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "generated_p2_c_changed": False, "official_host_changed": False}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.out.resolve():
        parser.error("diagnostic output must not overwrite stock source")
    import json
    print(json.dumps(generate(args.source, args.out), sort_keys=True))

if __name__ == "__main__":
    main()
