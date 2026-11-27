#!/usr/bin/env python3
"""Generated-C shard/cache and runtime ABI regressions.

The fake compiler exercises stage-loop shard invalidation. A bounded real C
fixture checks cross-shard runtime and host declarations without bootstrapping.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import os
import shutil
import stat
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)


def write_fake_cc(path: Path) -> None:
    path.write_text(
        r'''#!/usr/bin/env python3
import hashlib, os, stat, sys
from pathlib import Path

args = sys.argv[1:]
if "--version" in args:
    print(os.environ.get("FAKE_CC_VERSION", "fake-shard-cc 1.0"))
    sys.exit(0)

def arg_after(flag):
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        raise SystemExit(f"missing {flag} value")
    return args[i + 1]

out = arg_after("-o")
if not out:
    raise SystemExit("missing -o")
outp = Path(out)
outp.parent.mkdir(parents=True, exist_ok=True)
log_base = Path(os.environ["FAKE_CC_LOG"])
# Compiler jobs run concurrently. A separate file per process avoids relying on
# cross-process append semantics, which can lose records on Windows.
log = log_base.with_name(log_base.name + "." + str(os.getpid()))

if "-c" in args:
    src = Path(args[args.index("-c") + 1])
    mf = arg_after("-MF")
    h = hashlib.sha256(src.read_bytes()).hexdigest()
    outp.write_text("OBJ " + str(src) + " " + h + "\n", encoding="utf-8")
    if mf:
        # Enough for ouro_build's dep parser; real compiler depfiles are covered
        # by the ordinary build cache suite.
        Path(mf).write_text(str(outp) + ": " + str(src) + "\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write("COMPILE " + str(src) + "\n")
    sys.exit(0)

payload = ["#!/bin/sh", "# fake linked stage binary", "exit 0"]
for a in args:
    p = Path(a)
    if p.suffix == ".o" and p.exists():
        payload.append(p.read_text(encoding="utf-8", errors="replace"))
outp.write_text("\n".join(payload) + "\n", encoding="utf-8")
outp.chmod(outp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
with log.open("a", encoding="utf-8") as f:
    f.write("LINK " + str(outp) + "\n")
''',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def import_stage_loop(repo: Path):
    names = ("stage_loop_under_test", "frontend_regen", "generated_c_shards", "ouro_build", "selfhost_module_cache")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        with patch.object(sys, "path", [str(repo / "scripts"), *sys.path]):
            spec = importlib.util.spec_from_file_location("stage_loop_under_test", repo / "scripts/stage_loop.py")
            if spec is None or spec.loader is None:
                raise AssertionError("cannot import stage_loop.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["stage_loop_under_test"] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def counts(log: Path) -> tuple[int, int]:
    paths = [log, *sorted(log.parent.glob(log.name + ".*"))]
    text = "".join(path.read_text(encoding="utf-8") for path in paths if path.is_file())
    return text.count("COMPILE "), text.count("LINK ")


def make_cfg(mod):
    return mod.build_config(argparse.Namespace(promote=False))


def write_generated_sources(stage_dir: Path) -> tuple[Path, Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    fe = stage_dir / "driver_u.c"
    be = stage_dir / "backend_u.c"
    fe.write_text(
        '''/* Generated frontend pack: fake */
/* ---- frontend TU module=lx ---- */
#include "ouro_rt.h"
static ouro_v *ouro_lx_g1(void){return 0;}
int ouro_export_count_lx(void){return 1;}
const char *ouro_export_name_lx(int i){return i == 0 ? "lx" : "";}
ouro_v *ouro_export_value_lx(int i){return i == 0 ? ouro_lx_g1() : 0;}
/* ---- frontend TU module=pa ---- */
#include "ouro_rt.h"
static ouro_v *ouro_pa_g1(void){return 0;}
int ouro_export_count_pa(void){return 1;}
const char *ouro_export_name_pa(int i){return i == 0 ? "pa" : "";}
ouro_v *ouro_export_value_pa(int i){return i == 0 ? ouro_pa_g1() : 0;}
''',
        encoding="utf-8",
    )
    be.write_text(
        '''#include "ouro_rt.h"
static ouro_v *ouro_g1(void);
static ouro_v *ouro_g2(void);
static ouro_v *ouro_g3(void);
static ouro_v *ouro_c1;
static ouro_v *ouro_g1(void){if(ouro_c1==0)ouro_c1=ouro_fast("one");return ouro_c1;}
static ouro_v *ouro_c2;
static ouro_v *ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_g1();return ouro_c2;}
static ouro_v *ouro_c3;
static ouro_v *ouro_g3(void){if(ouro_c3==0)ouro_c3=ouro_g2();return ouro_c3;}
int ouro_export_count_be(void){return 3;}
const char *ouro_export_name_be(int i){switch(i){case 0: return "one"; case 1: return "two"; case 2: return "three"; default: return "";}}
ouro_v *ouro_export_value_be(int i){switch(i){case 0: return ouro_g1(); case 1: return ouro_g2(); case 2: return ouro_g3(); default: return 0;}}
''',
        encoding="utf-8",
    )
    return fe, be


def shard_mtimes(repo: Path, report: dict) -> dict[str, int]:
    shards = report["generated_c_shards"]["shards"]
    return {s["label"]: (repo / s["path"]).stat().st_mtime_ns for s in shards if s.get("compile")}


def miss_labels(report: dict) -> list[str]:
    return [s["label"] for s in report["sources"] if s.get("cache") == "miss"]


def test_shard_invalidation(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_repo(repo)
    fake_cc = tmp / "fake-shard-cc.py"
    cc_log = tmp / "fake-shard-cc.log"
    write_fake_cc(fake_cc)
    env = {
        "CC": str(fake_cc),
        "FAKE_CC_LOG": str(cc_log),
        "OURO_CCACHE": "disabled",
        "OURO_CACHE": "1",
        "OURO_BUILD_DIR": str(repo / "_build"),
        "OURO_C_BUILD_DIR": str(repo / "_build/c"),
        "OURO_CACHE_DIR": str(repo / "_cache_test"),
        "OURO_JOBS": "10",
        "OURO_GENERATED_C_SHARD_BACKEND_GROUPS": "1",
    }
    with patch.dict(os.environ, env):
        mod = import_stage_loop(repo)
        cfg = make_cfg(mod)
        stage_dir = repo / "_build/stage_loop/stage1"
        fe, be = write_generated_sources(stage_dir)
        out = repo / "_build/stage_loop/ouro1_stage1"

        first = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert first["generated_c_shards"]["summary"]["compile_shards"] == 6, first
        assert counts(cc_log) == (9, 1), first
        mtimes_first = shard_mtimes(repo, first)
        manifest = repo / first["generated_c_shards"]["manifest_path"]
        manifest_stat_first = manifest.stat()
        gcs_module = mod.GCS
        original_write = gcs_module.write_bytes_if_changed
        shard_compare_calls: list[str] = []

        def counted_write(path: Path, content: bytes) -> str:
            if path.suffix in {".c", ".h"}:
                shard_compare_calls.append(str(path))
            return original_write(path, content)

        gcs_module.write_bytes_if_changed = counted_write
        try:
            second = mod.build_stage_binary(fe, be, out, 1, cfg)
        finally:
            gcs_module.write_bytes_if_changed = original_write
        assert counts(cc_log) == (9, 1), second
        assert second["generated_c_shards"]["summary"]["shard_hits"] >= 6, second
        assert shard_mtimes(repo, second) == mtimes_first, "no-change run rewrote shard files"
        manifest_stat_second = manifest.stat()
        assert (manifest_stat_second.st_ino, manifest_stat_second.st_mtime_ns) == (
            manifest_stat_first.st_ino,
            manifest_stat_first.st_mtime_ns,
        ), "no-change run rewrote the stable shard manifest"
        assert shard_compare_calls == [], shard_compare_calls
        warm_summary = second["generated_c_shards"]["summary"]
        assert warm_summary["source_reads"] == 2, warm_summary
        assert warm_summary["plan_metadata_hashes"] == len(second["generated_c_shards"]["shards"]), warm_summary
        assert warm_summary["content_compare_calls"] == 0, warm_summary
        assert warm_summary["content_compare_calls_avoided"] == len(second["generated_c_shards"]["shards"]), warm_summary
        assert warm_summary["content_compare_bytes_avoided"] == warm_summary["total_bytes"], warm_summary

        fe.write_text(fe.read_text(encoding="utf-8").replace('return i == 0 ? "pa" : "";', 'return i == 0 ? "pa2" : "";'), encoding="utf-8")
        third = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (10, 2), third
        assert miss_labels(third) == ["stage1/frontend/pa"], third

        be.write_text(be.read_text(encoding="utf-8").replace('ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_g1();return ouro_c2;}', 'ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_fast("two2");return ouro_c2;}'), encoding="utf-8")
        fourth = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (11, 3), fourth
        assert miss_labels(fourth) == ["stage1/backend/g001-001"], fourth

        # A generator/tool hash change must flow into shard content and object
        # command/dependency hashes without changing canonical generated inputs.
        gcs = repo / "scripts/generated_c_shards.py"
        gcs.write_text(gcs.read_text(encoding="utf-8") + "\n# fake tool hash invalidation\n", encoding="utf-8")
        mod2 = import_stage_loop(repo)
        cfg2 = make_cfg(mod2)
        fifth = mod2.build_stage_binary(fe, be, out, 1, cfg2)
        assert counts(cc_log) == (17, 4), fifth
        assert len(miss_labels(fifth)) == 6, fifth

        manifest = repo / fifth["generated_c_shards"]["manifest_path"]
        manifest.write_text('{"kind":"ouro.generated-c-shards.v1"', encoding="utf-8")
        sixth = mod2.build_stage_binary(fe, be, out, 1, cfg2)
        assert counts(cc_log) == (17, 4), sixth
        assert sixth["generated_c_shards"]["manifest_cache"] == "miss", sixth
        assert sixth["generated_c_shards"]["summary"]["shard_revalidated"] > 0, sixth

        order1 = [s["label"] for s in fifth["generated_c_shards"]["shards"]]
        order2 = [s["label"] for s in sixth["generated_c_shards"]["shards"]]
        assert order1 == order2, "shard order changed across runs"


def test_backend_cluster_memory_shape() -> None:
    source = (ROOT / "scripts/generated_c_shards.py").read_text(encoding="utf-8")
    assert "clusters: List[Tuple[str, int, int]]" in source
    assert "clusters.append((g_name, list(lines[cluster_start" not in source
    assert "transform_backend_cluster(\n                lines," in source


def test_backend_cluster_output_bytes() -> None:
    import generated_c_shards as gcs

    unchanged = 'static ouro_v *ouro_f7_(void){return ouro_fast("\u00e9");}\n'
    lines = ["skip\n", unchanged, "\tstatic ouro_v *ouro_c7;\t\n",
             "\tstatic ouro_v *ouro_g7_d2(void){return ouro_c7;}\n", "tail\n"]
    out = ['#include "backend_u__shards.h"\n']
    gcs.transform_backend_cluster(lines, {2: "ouro_c7"}, "ouro_g7_d2", start=1, end=4, out=out)
    assert out[1] is unchanged
    assert "".join(out).encode("utf-8") == (
        '#include "backend_u__shards.h"\n'
        + unchanged
        + "/* shared duplicate generated cache declared in header: ouro_c7 */\n"
        + "\touro_v *ouro_g7_d2(void){return ouro_c7;}\n"
    ).encode("utf-8")

    options = {"role": "backend", "label": "fixture", "generator_hash": "fixture",
               "boundary": "fixture", "provenance": "fixture.c"}
    for body in (
        "", "\n", "\r\n", "\u00a0", "body", "body\n", "body\n\n", "body\n\n\n", "body\n\n\n\n",
        "body \t\r\n", "body\u00a0\n\n\n", "\u00e9\udcff\n", "\u00e9\udcff\n\n\n",
    ):
        header = gcs.banner(**options, content_hash=gcs.sha256_bytes(body.encode("utf-8", errors="surrogateescape")))
        expected = header + body.rstrip() + "\n"
        assert gcs.bannered_bytes(body, **options) == expected.encode("utf-8", errors="surrogateescape")


def test_backend_clusters_only_match_getter_and_cache_candidates() -> None:
    import generated_c_shards as gcs

    source = '''#include "ouro_rt.h"
\tstatic ouro_v *ouro_c7;\t
\tstatic ouro_v *ouro_f7_(void){return ouro_c7;}
\tstatic ouro_v *ouro_g7(void){return ouro_f7_();}
\tstatic ouro_v *ouro_c7;
\tstatic ouro_v *ouro_g7_d2(void){return ouro_c7;}
int ouro_export_count(void){return 2;}
const char *ouro_export_name(int i){switch(i){case 0:return "one";case 1:return "alias";}return "";}
ouro_v *ouro_export_value(int i){switch(i){case 0:return ouro_g7();case 1:return ouro_g7_d2();}return 0;}
'''
    backend = ROOT / "fixture.c"
    with (patch.object(gcs, "BACKEND_G_DEF", wraps=gcs.BACKEND_G_DEF) as getter,
          patch.object(gcs, "BACKEND_CACHE", wraps=gcs.BACKEND_CACHE) as cache,
          patch.object(gcs, "rel", wraps=gcs.rel) as rel):
        plans = gcs.backend_shards(backend, source, ROOT / "shards", "fixture", "generator",
                                   1, export_suffix="")

    assert [plan.boundary for plan in plans] == [
        "backend-header", "backend-duplicate-cache-state", "backend-functions:ouro_g7..ouro_g7",
        "backend-functions:ouro_g7_d2..ouro_g7_d2", "backend-export-table",
    ]
    assert b"\tstatic ouro_v *ouro_f7_(void){return ouro_c7;}\n" in plans[2].content
    assert b"\touro_v *ouro_g7_d2(void){return ouro_c7;}\n" in plans[3].content
    assert all(b"shared duplicate generated cache declared in header: ouro_c7" in plan.content
               for plan in plans[2:4])
    assert [plan.provenance for plan in plans] == [
        "fixture.c", "fixture.c", "fixture.c#functions=ouro_g7..ouro_g7",
        "fixture.c#functions=ouro_g7_d2..ouro_g7_d2", "fixture.c#exports",
    ]
    assert getter.match.call_count == 4
    assert cache.match.call_count == 2
    rel.assert_called_once_with(backend)


def test_backend_prelude_keeps_declarations_in_one_pass() -> None:
    from generated_c_shards import scan_backend_prelude

    inspected = []

    class TrackedLine(str):
        __slots__ = ()

        def strip(self, chars=None):
            inspected.append(self)
            return super().strip(chars)

    header = '\t#include "extra.h" \r\n'
    declaration = "  ouro_v *ouro_fixture(ouro_v *value);\t\n"
    lines = [TrackedLine(line) for line in (
        " \t\n", '\t#include "ouro_rt.h"\n', header, "static ouro_v *ouro_g7_d2(void);\t\n",
        declaration, "static ouro_v *ouro_g8(void); unexpected\n", "static ouro_v *ouro_g9(void);\n",
    )]
    assert scan_backend_prelude(lines) == (5, [header, declaration])
    assert inspected == lines[:6]


def test_backend_export_names_match_lf_anchored_definitions() -> None:
    from generated_c_shards import _backend_export_names

    source = (
        'int ouro_export_count_be(void){return 1;}\r\n'
        'const char *ouro_export_name_be(int i){return "";}\n'
        'ouro_v *ouro_export_value_be(int i){return ouro_g1();}\n'
        'int ouro_export_count_be(void){return 2;}\n'
        'int ouro_export_count_extra(\vvoid){return 0;}\n'
        'static int ouro_export_count_static(void){return 0;}\n'
        ' int ouro_export_count_indented(void){return 0;}\n'
        'int ouro_export_count_prototype(void);\n'
        'int ouro_export_count_newline(\nvoid){return 0;}\n'
        'int ouro_export_other(void){return 0;}\n'
        '/* ignore */\u2028int ouro_export_count_unicode(void){return 0;}\n'
        'void prose(void){ puts("int ouro_export_count_in_text(void){"); }\n'
    )
    assert _backend_export_names(source) == [
        "ouro_export_count_be", "ouro_export_name_be", "ouro_export_value_be",
        "ouro_export_count_be", "ouro_export_count_extra",
    ]


def test_host_backend_shards(tmp: Path) -> None:
    import generated_c_shards as gcs
    from ourosmith.limits import run_limited

    fixture = '''#include "ouro_rt.h"
#include "ouro_quality_scope.h"
ouro_v *ouro_fe_compile_checked_units_clos(void);
static ouro_v *ouro_g1(void);
static ouro_v *ouro_g2(void);
static ouro_v *ouro_g3(void);
static ouro_v *ouro_g4(void);
static ouro_v *ouro_g5(void);
static ouro_v *ouro_g99(void);
static ouro_v *ouro_g99_d0(void);
ouro_v *ouro_io_prim_req(const char *name);
ouro_v *ouro_io_type_stub(const char *name);
static ouro_v *ouro_c1;
static ouro_v *ouro_g1(void){if(ouro_c1==0)ouro_c1=ouro_io_prim_req("prim_string_length");return ouro_c1;}
static ouro_v *ouro_c2;
static ouro_v *ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_g1();return ouro_c2;}
static ouro_v *ouro_f3_a(ouro_env *env,ouro_v *arg){(void)env;(void)arg;return ouro_g2();}
static ouro_v *ouro_f3_(ouro_env *env,ouro_v *arg){return ouro_clos(ouro_f3_a,ouro_cons(arg,env));}
static ouro_v *ouro_c3;
static ouro_v *ouro_g3(void){if(ouro_c3==0)ouro_c3=ouro_wrap_quality_pure(ouro_clos(ouro_f3_,0));return ouro_c3;}
static ouro_v *ouro_c4;
static ouro_v *ouro_g4(void){if(ouro_c4==0)ouro_c4=ouro_fe_compile_checked_units_clos();return ouro_c4;}
static ouro_v *ouro_c5;
static ouro_v *ouro_g5(void){if(ouro_c5==0)ouro_c5=ouro_io_type_stub("Shape");return ouro_c5;}
static ouro_v *ouro_c99;
static ouro_v *ouro_g99(void){if(ouro_c99==0)ouro_c99=ouro_g2();return ouro_c99;}
static ouro_v *ouro_c99;
static ouro_v *ouro_g99_d0(void){if(ouro_c99==0)ouro_c99=ouro_g2();return ouro_c99;}
int ouro_export_countEXPORT_SUFFIX(void){return 7;}
const char *ouro_export_nameEXPORT_SUFFIX(int i){switch(i){case 0:return "primitive";case 1:return "alias";case 2:return "quality";case 3:return "frontend";case 4:return "type";case 5:return "shared";case 6:return "shared-alias";default:return "";}}
ouro_v *ouro_export_valueEXPORT_SUFFIX(int i){switch(i){case 0:return ouro_g1();case 1:return ouro_g2();case 2:return ouro_g3();case 3:return ouro_g4();case 4:return ouro_g5();case 5:return ouro_g99();case 6:return ouro_g99_d0();default:return 0;}}
'''
    fixture = fixture.replace("static ouro_v *ouro_c99;\n", "\tstatic ouro_v *ouro_c99;\t\n")
    fixture = fixture.replace("static ouro_v *ouro_g99_d0(void){", "\tstatic ouro_v *ouro_g99_d0(void){")
    driver = '''#include "backend_u__shards.h"
#include <string.h>
ouro_v *ouro_fe_compile_checked_units_clos(void){return ouro_g3();}
int main(void){
 const char *names[]={"primitive","alias","quality","frontend","type","shared","shared-alias"};
 ouro_v *primitive=ouro_export_valueEXPORT_SUFFIX(0);
 ouro_v *quality=ouro_export_valueEXPORT_SUFFIX(2);
 ouro_v *type=ouro_export_valueEXPORT_SUFFIX(4);
 unsigned long length=0;
 int i;
 if(ouro_export_countEXPORT_SUFFIX()!=7)return 1;
 for(i=0;i<7;i++)if(strcmp(ouro_export_nameEXPORT_SUFFIX(i),names[i])!=0)return 2;
 if(primitive!=ouro_export_valueEXPORT_SUFFIX(1)||primitive!=ouro_export_valueEXPORT_SUFFIX(5)||primitive!=ouro_export_valueEXPORT_SUFFIX(6))return 3;
 if(quality!=ouro_export_valueEXPORT_SUFFIX(3)||type==0||type->tag!=OURO_TAG_CLOS||type!=ouro_export_valueEXPORT_SUFFIX(4))return 4;
 if(!ouro_nat_to_ulong(ouro_apply(primitive,ouro_str("hello")),&length)||length!=5)return 5;
 primitive=ouro_apply(ouro_apply(quality,ouro_nat(0)),ouro_nat(0));
 if(!ouro_nat_to_ulong(ouro_apply(primitive,ouro_str("hello")),&length)||length!=5)return 6;
 puts("BACKEND_SHARD_ABI: PASS SUFFIX_LABEL");return 0;
}
'''
    for suffix, label in (("", "flat"), ("_be", "be")):
        work = tmp / ("host-shards-" + label)
        work.mkdir()
        backend = work / "backend.gen.c"
        backend.write_text(fixture.replace("EXPORT_SUFFIX", suffix), encoding="utf-8")
        original_hash = gcs.sha256_file(backend)
        options = {"backend_export_suffix": ""} if not suffix else {}
        sources, report = gcs.materialize_generated_c_shards(
            frontend_c=None, backend_c=backend, out_dir=work / "shards", label_prefix="host",
            backend_group_size=1, **options)
        assert report["summary"]["frontend_shards"] == 0 and report["summary"]["source_reads"] == 1, report
        assert report["summary"]["compile_shards"] == 9, report
        assert report["shards"][-1]["symbols"] == [f"ouro_export_{kind}{suffix}" for kind in ("count", "name", "value")]
        header = work / "shards/backend_u__shards.h"
        header_text = header.read_text(encoding="utf-8")
        for declaration in ('#include "ouro_quality_scope.h"', "ouro_v *ouro_fe_compile_checked_units_clos(void);",
                            "ouro_v *ouro_io_prim_req(const char *name);", "ouro_v *ouro_io_type_stub(const char *name);"):
            assert declaration in header_text, declaration
        assert "extern ouro_v *ouro_c99;" in header_text
        shard_texts = [path.read_text(encoding="utf-8") for _label, path in sources]
        assert sum(text.count("/* shared duplicate generated cache declared in header: ouro_c99 */")
                   for text in shard_texts) == 2
        assert any("\n\touro_v *ouro_g99_d0(void){" in text for text in shard_texts)
        main = work / "main.c"
        main.write_text(driver.replace("EXPORT_SUFFIX", suffix).replace("SUFFIX_LABEL", label), encoding="utf-8")
        binary = work / ("shard-abi.exe" if os.name == "nt" else "shard-abi")
        compiler = os.environ.get("CC", "cc")
        command = [compiler, "-O0", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-Werror=implicit-function-declaration",
                   "-I" + str(ROOT / "runtime"), "-I" + str(header.parent),
                   *(str(path) for _name, path in sources), str(ROOT / "runtime/ouro_rt.c"),
                   str(ROOT / "runtime/ouro_io.c"), str(main), "-o", str(binary)]
        compiled = run_limited(command, cwd=ROOT, timeout_s=120, memory_mb=1536)
        assert compiled.ok, compiled
        executed = run_limited([str(binary)], cwd=ROOT, timeout_s=15, memory_mb=256)
        assert executed.ok and executed.stdout == f"BACKEND_SHARD_ABI: PASS {label}\n" and executed.stderr == "", executed
        mtimes = {str(path): path.stat().st_mtime_ns for _name, path in sources}
        _sources, warm = gcs.materialize_generated_c_shards(
            frontend_c=None, backend_c=backend, out_dir=work / "shards", label_prefix="host",
            backend_group_size=1, **options)
        assert warm["manifest_cache"] == "hit" and all(row["cache"] == "hit" for row in warm["shards"]), warm
        assert mtimes == {str(path): path.stat().st_mtime_ns for _name, path in sources}
        assert original_hash == gcs.sha256_file(backend), "sharding changed the canonical backend"
        header.write_text(header_text + "\n/* changed header */\n", encoding="utf-8")
        ok, reason = gcs.manifest_valid(gcs.read_json(Path(report["manifest_path"])),
            generator_hash=report["generator_hash"], source_digests=report["sources"], plan_meta=report["shards"])
        assert not ok and reason == "shard-hash", reason

    for text, suffix in ((fixture.replace("EXPORT_SUFFIX", ""), "_be"),
                         (fixture.replace("EXPORT_SUFFIX", ""), ";invalid"),
                         (fixture.replace("EXPORT_SUFFIX", "_be") +
                          "int ouro_export_count_extra(void){return 0;}\n", "_be"),
                         (fixture.replace("EXPORT_SUFFIX", "").replace('#include "ouro_rt.h"', '#include "ouro_rt.h"\n#define UNKNOWN_PRELUDE 1'), "")):
        try:
            gcs.backend_shards(backend, text, work / "rejected", "host", "fixture", 1, export_suffix=suffix)
        except ValueError:
            pass
        else:
            raise AssertionError("unsupported backend prefix or suffix accepted")


SPLIT_FRONTEND = '''/* Generated frontend pack: split fixture */

/* ---- frontend TU module=sm ---- */
#include "ouro_rt.h"
static ouro_v *ouro_sm_g1(void);
static ouro_v *ouro_sm_c1;
static ouro_v *ouro_sm_g1(void){if(ouro_sm_c1==0)ouro_sm_c1=ouro_nat(7);return ouro_sm_c1;}
int ouro_export_count_sm(void){return 1;}
const char *ouro_export_name_sm(int i){switch(i){case 0: return "seven";
}return "";}
ouro_v *ouro_export_value_sm(int i){switch(i){case 0: return ouro_sm_g1();
}return 0;}

/* ---- frontend TU module=sp ---- */
#include "ouro_rt.h"
ouro_v *ouro_fixture_offset(ouro_v *raw);
static ouro_v *ouro_sp_g1(void);
static ouro_v *ouro_sp_g2(void);
static ouro_v *ouro_sp_g3(void);
static ouro_v *ouro_sp_g4(void);
static ouro_v *ouro_sp_g5(void);
static ouro_v *ouro_sp_g4_d2(void);
static ouro_v *ouro_sp_c1;
static ouro_v *ouro_sp_g1(void){if(ouro_sp_c1==0)ouro_sp_c1=ouro_fast("add");return ouro_sp_c1;}
static ouro_v *ouro_sp_f2_(ouro_env *env0,ouro_v *arg){ouro_env *env=ouro_cons(arg,env0);(void)env;PAD;return ouro_app(ouro_app(ouro_sp_g1(),ouro_get(env,0)),ouro_nat(2));}
static ouro_v *ouro_sp_c2;
static ouro_v *ouro_sp_g2(void){ouro_env *env=0;(void)env;if(ouro_sp_c2==0){ouro_static_begin();ouro_sp_c2=ouro_clos(ouro_sp_f2_,env);ouro_static_end();}return ouro_sp_c2;}
static ouro_v *ouro_sp_t1_3_(ouro_env *env,ouro_v *arg){(void)arg;(void)env;return ouro_nat(40);}
static ouro_v *ouro_sp_c3;
static ouro_v *ouro_sp_g3(void){if(ouro_sp_c3==0){ouro_static_begin();ouro_sp_c3=ouro_apply(ouro_sp_g2(),ouro_sp_t1_3_(0,0));ouro_static_end();}return ouro_sp_c3;}
static ouro_v *ouro_sp_c4;
static ouro_v *ouro_sp_g4(void){if(ouro_sp_c4==0){ouro_static_begin();ouro_sp_c4=ouro_fixture_offset(ouro_sp_g3());ouro_static_end();}return ouro_sp_c4;}
static ouro_v *ouro_sp_f5_(ouro_env *env0,ouro_v *arg){ouro_env *env=ouro_cons(arg,env0);(void)env;PAD;return ouro_get(env,0);}
static ouro_v *ouro_sp_c5;
static ouro_v *ouro_sp_g5(void){ouro_env *env=0;(void)env;if(ouro_sp_c5==0){ouro_static_begin();ouro_sp_c5=ouro_clos(ouro_sp_f5_,env);ouro_static_end();}return ouro_sp_c5;}
static ouro_v *ouro_sp_c4;
static ouro_v *ouro_sp_g4_d2(void){if(ouro_sp_c4==0)ouro_sp_c4=ouro_nat(0);return ouro_sp_c4;}
int ouro_export_count_sp(void){return 6;}
const char *ouro_export_name_sp(int i){switch(i){case 0: return "add";
case 1: return "add-two";
case 2: return "forty-two";
case 3: return "offset";
case 4: return "identity";
case 5: return "offset-alias";
}return "";}
ouro_v *ouro_export_value_sp(int i){switch(i){case 0: return ouro_sp_g1();
case 1: return ouro_sp_g2();
case 2: return ouro_sp_g3();
case 3: return ouro_sp_g4();
case 4: return ouro_sp_g5();
case 5: return ouro_sp_g4_d2();
}return 0;}
'''

SPLIT_BACKEND = '''#include "ouro_rt.h"
static ouro_v *ouro_g1(void);
static ouro_v *ouro_c1;
static ouro_v *ouro_g1(void){if(ouro_c1==0)ouro_c1=ouro_nat(1);return ouro_c1;}
int ouro_export_count_be(void){return 1;}
const char *ouro_export_name_be(int i){return i==0?"one":"";}
ouro_v *ouro_export_value_be(int i){return i==0?ouro_g1():0;}
'''

SPLIT_MAIN = '''#include "ouro_rt.h"
#include <stdio.h>
#include <string.h>
int ouro_export_count_sm(void);
const char *ouro_export_name_sm(int i);
ouro_v *ouro_export_value_sm(int i);
int ouro_export_count_sp(void);
const char *ouro_export_name_sp(int i);
ouro_v *ouro_export_value_sp(int i);
ouro_v *ouro_fixture_offset(ouro_v *raw){unsigned long n=0;return ouro_nat(ouro_nat_to_ulong(raw,&n)?n+100:0);}
static unsigned long nat_of(ouro_v *value){unsigned long n=0;return ouro_nat_to_ulong(value,&n)?n:9999;}
int main(void){
 const char *names[]={"add","add-two","forty-two","offset","identity","offset-alias"};
 int i;
 if(ouro_export_count_sm()!=1||strcmp(ouro_export_name_sm(0),"seven")!=0||nat_of(ouro_export_value_sm(0))!=7)return 1;
 if(ouro_export_count_sp()!=6||strcmp(ouro_export_name_sp(6),"")!=0||ouro_export_value_sp(6)!=0)return 2;
 for(i=0;i<6;i++)if(strcmp(ouro_export_name_sp(i),names[i])!=0)return 3;
 if(nat_of(ouro_apply(ouro_apply(ouro_export_value_sp(0),ouro_nat(3)),ouro_nat(4)))!=7)return 4;
 if(nat_of(ouro_apply(ouro_export_value_sp(1),ouro_nat(5)))!=7||nat_of(ouro_export_value_sp(2))!=42)return 5;
 if(nat_of(ouro_export_value_sp(3))!=142||ouro_export_value_sp(5)!=ouro_export_value_sp(3))return 6;
 if(nat_of(ouro_apply(ouro_export_value_sp(4),ouro_nat(9)))!=9)return 7;
 puts("FRONTEND_SHARD_SPLIT: PASS");
 return 0;
}
'''


def test_frontend_module_split(tmp: Path) -> None:
    import generated_c_shards as gcs
    from ourosmith.limits import run_limited

    work = tmp / "frontend-split"
    work.mkdir()
    frontend, backend, shard_dir = work / "driver_u.c", work / "backend_u.c", work / "shards"
    # Padded helpers exceed the piece size, so each one is cut away from its users.
    text = SPLIT_FRONTEND.replace("PAD", '(void)"' + "x" * 1200 + '"')
    frontend.write_bytes(text.encode("utf-8"))
    backend.write_bytes(SPLIT_BACKEND.encode("utf-8"))
    original_hash = gcs.sha256_file(frontend)
    options = {"backend_c": backend, "label_prefix": "split", "frontend_split_bytes": 2048, "frontend_piece_bytes": 1024}
    sources, report = gcs.materialize_generated_c_shards(frontend_c=frontend, out_dir=shard_dir, **options)
    rows = {row["label"]: row for row in report["shards"]}
    paths = dict(sources)
    pieces = [label for label in paths if label.startswith("split/frontend/sp/p")]
    assert pieces == [f"split/frontend/sp/p{number:02d}" for number in range(5)], report
    assert report["settings"]["frontend_split_bytes"] == 2048 and report["settings"]["frontend_piece_bytes"] == 1024
    summary = report["summary"]
    assert summary["frontend_shards"] == 7 and summary["compile_shards"] == 9 and summary["header_shards"] == 2, summary
    assert summary["frontend_split_fallbacks"] == [], summary
    assert rows["split/frontend/sp/header"]["compile"] is False
    assert all(rows[label]["deps"] == ["frontend__001_sp__shards.h"] for label in [*pieces, "split/frontend/sp/exports"])
    assert rows["split/frontend/sp/exports"]["symbols"] == [f"ouro_export_{kind}_sp" for kind in ("count", "name", "value")]

    sm_chunk = text[text.index("/* ---- frontend TU module=sm"):text.index("/* ---- frontend TU module=sp")]
    unsplit = gcs.bannered_bytes(sm_chunk, role="frontend", label="split/frontend/sm", generator_hash=report["generator_hash"],
                                  boundary="frontend-module:sm", provenance=gcs.rel(frontend) + "#module=sm")
    assert paths["split/frontend/sm"] == shard_dir / "frontend__000_sm.c" and rows["split/frontend/sm"]["symbols"] == ["sm"]
    assert paths["split/frontend/sm"].read_bytes() == unsplit, "small module shard changed"

    header = (shard_dir / "frontend__001_sp__shards.h").read_text(encoding="utf-8")
    for declaration in ("ouro_v *ouro_fixture_offset(ouro_v *raw);", "extern ouro_v *ouro_sp_c4;",
                        "ouro_v *ouro_sp_f2_(ouro_env *env0,ouro_v *arg);", "ouro_v *ouro_sp_f5_(ouro_env *env0,ouro_v *arg);",
                        "ouro_v *ouro_sp_g1(void);", "ouro_v *ouro_sp_g4_d2(void);"):
        assert declaration + "\n" in header, declaration
    assert "ouro_sp_t1_3_" not in header and "ouro_sp_c3" not in header and "static ouro_v" not in header, header
    piece_text = {label: paths[label].read_text(encoding="utf-8") for label in pieces}
    joined = "".join(piece_text.values())
    assert joined.count("\nouro_v *ouro_sp_c4;\n") == 1 and "static ouro_v *ouro_sp_c4;" not in joined
    assert "\nstatic ouro_v *ouro_sp_t1_3_(" in joined and "static ouro_v *ouro_sp_g" not in joined

    def piece_of(fragment: str) -> str:
        return next(label for label, body in piece_text.items() if fragment in body)

    assert piece_of("\nouro_v *ouro_sp_f2_(") != piece_of("\nouro_v *ouro_sp_g2(void){")
    assert piece_of("\nouro_v *ouro_sp_g4(void){") != piece_of("\nouro_v *ouro_sp_g4_d2(void){")
    assert piece_of("\nstatic ouro_v *ouro_sp_t1_3_(") == piece_of("\nouro_v *ouro_sp_g3(void){")

    main = work / "main.c"
    main.write_text(SPLIT_MAIN, encoding="utf-8")
    binary = work / ("frontend-split.exe" if os.name == "nt" else "frontend-split")
    compiler = os.environ.get("CC", "cc")
    # -fno-common turns a second definition of a shared cache into a link error.
    command = [compiler, "-O0", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-Werror=implicit-function-declaration",
               "-fno-common", "-I" + str(ROOT / "runtime"), *(str(path) for path in paths.values()),
               str(ROOT / "runtime/ouro_rt.c"), str(main), "-o", str(binary)]
    compiled = run_limited(command, cwd=ROOT, timeout_s=120, memory_mb=1536)
    assert compiled.ok, compiled
    executed = run_limited([str(binary)], cwd=ROOT, timeout_s=15, memory_mb=256)
    assert executed.ok and executed.stdout == "FRONTEND_SHARD_SPLIT: PASS\n" and executed.stderr == "", executed

    mtimes = {path.name: path.stat().st_mtime_ns for path in shard_dir.iterdir()}
    _sources, warm = gcs.materialize_generated_c_shards(frontend_c=frontend, out_dir=shard_dir, **options)
    assert warm["manifest_cache"] == "hit" and all(row["cache"] == "hit" for row in warm["shards"]), warm
    assert mtimes == {path.name: path.stat().st_mtime_ns for path in shard_dir.iterdir()}
    assert original_hash == gcs.sha256_file(frontend), "sharding changed the canonical frontend"

    broken_inputs = (
        ("unrecognized line", text.replace("static ouro_v *ouro_sp_c5;\n", "static int ouro_sp_flag;\nstatic ouro_v *ouro_sp_c5;\n")),
        ("unresolved reference ouro_sp_g9", text.replace("return ouro_get(env,0);}", "return ouro_sp_g9();}")),
    )
    for number, (reason, broken) in enumerate(broken_inputs):
        frontend.write_bytes(broken.encode("utf-8"))
        fallback_sources, fallback = gcs.materialize_generated_c_shards(
            frontend_c=frontend, out_dir=work / f"fallback-{number}", **options)
        failures = fallback["summary"]["frontend_split_fallbacks"]
        assert len(failures) == 1 and failures[0]["module"] == "sp" and failures[0]["reason"].startswith(reason), failures
        whole = dict(fallback_sources)
        assert [label for label in whole if "/frontend/" in label] == ["split/frontend/sm", "split/frontend/sp"], whole
        expected = gcs.bannered_bytes(broken[broken.index("/* ---- frontend TU module=sp"):], role="frontend",
                                       label="split/frontend/sp", generator_hash=fallback["generator_hash"],
                                       boundary="frontend-module:sp", provenance=gcs.rel(frontend) + "#module=sp")
        assert whole["split/frontend/sp"] == work / f"fallback-{number}" / "frontend__001_sp.c"
        assert whole["split/frontend/sp"].read_bytes() == expected, reason


def test_generated_c_exact_write(tmp: Path) -> None:
    from generated_c_shards import write_text_if_changed

    path = tmp / "exact-write.c"
    content = "a" * (1024 * 1024) + "\r\n\u00e9\0\udcff\n"
    expected = content.encode("utf-8", errors="surrogateescape")
    assert write_text_if_changed(path, content) == "updated"
    assert path.read_bytes() == expected
    mtime = path.stat().st_mtime_ns
    assert write_text_if_changed(path, content) == "unchanged"
    assert path.stat().st_mtime_ns == mtime

    for changed in (b"b" + expected[1:], expected[:-1], expected + b"\0",
                    expected.replace(b"\xff", b"\xfe")):
        path.write_bytes(changed)
        assert write_text_if_changed(path, content) == "updated"
        assert path.read_bytes() == expected

    assert write_text_if_changed(path, "") == "updated"
    assert path.read_bytes() == b""
    assert write_text_if_changed(path, "") == "unchanged"


def test_generated_c_source_snapshot() -> None:
    import generated_c_shards as gcs

    path = Path("fixture.c")
    raw = b"\r\n\xc3\xa9\r\r\n\0\xff\n\xf0\x9f\xa7\xad\r\xe2\x82"
    normalized = b"\n\xc3\xa9\n\n\0\xff\n\xf0\x9f\xa7\xad\n\xe2\x82"
    expected = {"path": gcs.rel(path), "sha256": gcs.sha256_bytes(normalized), "bytes": len(normalized)}
    for chunk_bytes in (1, 2, 3, 4, 5, len(raw) + 1):
        source = io.BytesIO(raw)
        with (patch.object(Path, "open", autospec=True, return_value=source) as opened,
              patch.object(source, "read", wraps=source.read) as reads):
            text, digest = gcs.read_source_text_digest(path, chunk_bytes=chunk_bytes)
        opened.assert_called_once_with(path, "rb")
        assert len(reads.call_args_list) == (len(raw) + chunk_bytes - 1) // chunk_bytes + 1
        assert all(call.args == (chunk_bytes,) for call in reads.call_args_list)
        assert source.closed and text.encode("utf-8", errors="surrogateescape") == normalized
        assert digest == expected

    source = io.BytesIO(raw)
    with (patch.object(Path, "open", autospec=True, return_value=source) as opened,
          patch.object(gcs.codecs, "getincrementaldecoder", side_effect=AssertionError("unexpected decode"))):
        assert gcs.read_normalized_source_digest(path, chunk_bytes=3) == expected
    opened.assert_called_once_with(path, "rb")

    source = io.BytesIO(raw)
    failure = OSError("incomplete generated C read")
    with (patch.object(Path, "open", autospec=True, return_value=source),
          patch.object(source, "read", side_effect=[raw[:3], failure])):
        try:
            gcs.read_source_text_digest(path, chunk_bytes=3)
        except OSError as observed:
            assert observed is failure and source.closed
        else:
            raise AssertionError("accepted an incomplete generated C snapshot")


def test_shard_plan_reuses_payload_bytes(tmp: Path) -> None:
    import generated_c_shards as gcs

    backend = tmp / "payload.c"
    backend.write_bytes(b'/* \xc3\xa9\xff */\r\n\xc2\xa0\r\n')
    out = tmp / "payload-shards"
    plans = []
    plan_backend = gcs.backend_shards

    def capture_plan(*args, **kwargs):
        result = plan_backend(*args, **kwargs)
        plans.extend(result)
        return result

    options = {"frontend_c": None, "backend_c": backend, "out_dir": out, "label_prefix": "payload"}
    with (patch.object(gcs, "backend_shards", side_effect=capture_plan),
          patch.object(gcs, "sha256_bytes", wraps=gcs.sha256_bytes) as hashes,
          patch.object(gcs, "write_bytes_if_changed", wraps=gcs.write_bytes_if_changed) as writes):
        [(_label, path)], cold = gcs.materialize_generated_c_shards(**options)
    [plan] = plans
    [write] = [call for call in writes.call_args_list if call.args[0] == path]
    assert isinstance(plan.content, bytes) and write.args[1] is plan.content
    assert any(call.args[0] is plan.content for call in hashes.call_args_list)
    expected = path.read_bytes()
    assert expected == plan.content and expected.endswith(b'/* \xc3\xa9\xff */\n')
    assert cold["shards"][0]["sha256"] == gcs.sha256_file(path)

    mtime = path.stat().st_mtime_ns
    _sources, warm = gcs.materialize_generated_c_shards(**options)
    assert warm["manifest_cache"] == "hit" and path.stat().st_mtime_ns == mtime
    path.write_bytes(b"!" + expected[1:])
    os.utime(path, ns=(mtime, mtime))
    _sources, repaired = gcs.materialize_generated_c_shards(**options)
    assert repaired["manifest_reason"] == "shard-hash" and path.read_bytes() == expected


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-generated-c-shard-suite-") as d:
        test_shard_invalidation(Path(d))
        test_host_backend_shards(Path(d))
        test_frontend_module_split(Path(d))
        test_generated_c_exact_write(Path(d))
        test_shard_plan_reuses_payload_bytes(Path(d))
    test_backend_cluster_memory_shape()
    test_generated_c_source_snapshot()
    test_backend_cluster_output_bytes()
    test_backend_clusters_only_match_getter_and_cache_candidates()
    test_backend_prelude_keeps_declarations_in_one_pass()
    test_backend_export_names_match_lf_anchored_definitions()
    print("GENERATED_C_SHARD_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
