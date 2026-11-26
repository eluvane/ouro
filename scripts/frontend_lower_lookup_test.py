#!/usr/bin/env python3
"""Test source-bound lookup installation and cache rejection."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import frontend_regen as REGEN
import pack_frontend as PACKER
import native_tool_build as NATIVE
import scoped_host_exports as exports
from frontend_regen import _source_scope_contracts
from pack_frontend import _base_ver, _static_definition_family_counts, _static_symbol_starts
from scoped_host_export_consumers import current_native_scoped_original
from scoped_host_exports import _declarations, _read_export_tables
from scoped_host_exports_test import fixture_scope_closure, source as export_source

REPO = Path(__file__).resolve().parents[1]


def raw_source():
    return (
        '#include "ouro_rt.h"\n'
        'static ouro_v *ouro_f0_31_(ouro_env *env0,ouro_v *arg){'
        'ouro_env *env=ouro_cons(arg,env0);(void)env;return ouro_ctor(0,0,0);}\n'
        'static ouro_v *ouro_f31_(ouro_env *env0,ouro_v *arg){'
        'ouro_env *env=ouro_cons(arg,env0);(void)env;return ouro_fix(ouro_f0_31_,env);}\n'
        'static ouro_v *ouro_c31;\n'
        'static ouro_v *ouro_g31(void){ouro_env *env=0;(void)env;'
        'if(ouro_c31==0){ouro_static_begin();ouro_c31=ouro_clos(ouro_f31_,env);'
        'ouro_static_end();}return ouro_c31;}\n'
        'int ouro_export_count_lo(void){return 1;}\n'
        'const char *ouro_export_name_lo(int i){switch(i){case 0:return "lookup_ctor";default:return "";}}\n'
        'ouro_v *ouro_export_value_lo(int i){switch(i){case 0:return ouro_g31();default:return 0;}}\n'
    )


MODULE_UNITS = (*PACKER.MODULE_LOOKUP_SOURCE_PATHS, "tools/entry.ouro")
MODULE_SOURCES = {path: (REPO / path).read_text(encoding="utf-8")
                  for path in PACKER.MODULE_LOOKUP_SOURCE_PATHS}
MODULE_SOURCES[MODULE_UNITS[-1]] = "def main : Nat := Z;\n"


def module_source(module="", *, qualified=True, offset=0, fast=False, scopes=False):
    labels = [("module_lookup", 51 + offset), ("lookup", 31 + offset), ("eqNat", 41 + offset)]
    owners = {name: owner for owner, kind, name, _expected in PACKER.MODULE_LOOKUP_SOURCE_SHAPES
              if kind == "def"}
    rows = [(f"_ouro_m_{MODULE_UNITS.index(owners[name])}_{name}" if qualified else name, gid)
            for name, gid in labels]
    if scopes:
        rows.append(("module_invalid_maps", 61 + offset))
    text = export_source(rows, module, arities={31 + offset: 3, 41 + offset: 2, 61 + offset: 3})
    text = text.replace(f"ouro_c{51 + offset}=ouro_clos(ouro_f{51 + offset}_,env);",
                        f"ouro_c{51 + offset}=ouro_app(ouro_g{31 + offset}(),ouro_g{41 + offset}());", 1)
    if fast:
        gid = 41 + offset
        start = (f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                 f"if(ouro_c{gid}==0){{ouro_static_begin();ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);"
                 f"ouro_static_end();}}return ouro_c{gid};}}")
        text = text.replace(start, f'static ouro_v *ouro_g{gid}(void){{if(ouro_c{gid}==0)'
                            f'ouro_c{gid}=ouro_fast("eqNat");return ouro_c{gid};}}', 1)
    return text


COMPOSED_MODULE_UNITS = (
    "std/types.ouro", "std/prelude.ouro", "std/data.ouro", "compiler/base.ouro",
    "std/listx.ouro", PACKER.MODULE_LOOKUP_OWNER, MODULE_UNITS[-1],
)
COMPOSED_MODULE_SOURCES = {path: (REPO / path).read_text(encoding="utf-8")
                           for path in COMPOSED_MODULE_UNITS[:-1]}
COMPOSED_MODULE_SOURCES[COMPOSED_MODULE_UNITS[-1]] = (
    'import "../compiler/module_names_base.ouro";\ndef main : Nat := Z;\n'
)
LOCAL_LOOKUP_UNITS = (*PACKER.LOWER_LOCAL_LOOKUP_SOURCE_PATHS, "tools/local_entry.ouro")
LOCAL_LOOKUP_SOURCES = {path: (REPO / path).read_text(encoding="utf-8")
                        for path in PACKER.LOWER_LOCAL_LOOKUP_SOURCE_PATHS}
LOCAL_LOOKUP_SOURCES[LOCAL_LOOKUP_UNITS[-1]] = "def main : Nat := Z;\n"
LOCAL_COMPOSED_UNITS = (*COMPOSED_MODULE_UNITS[:-1], "compiler/core.ouro",
                        PACKER.LOWER_LOCAL_LOOKUP_OWNER, COMPOSED_MODULE_UNITS[-1])
LOCAL_COMPOSED_SOURCES = {**COMPOSED_MODULE_SOURCES, **{
    path: (REPO / path).read_text(encoding="utf-8")
    for path in ("compiler/core.ouro", PACKER.LOWER_LOCAL_LOOKUP_OWNER)}}
COMPOSED_ARITHMETIC_GETTERS = (("add", 71), ("mul", 81), ("compareNat", 91), ("eqNat", 41),
                               ("length", 101), ("append", 111), ("sub", 141))


def append_helpers(gid):
    bodies = (
        (f"1_0_{gid}_", "ouro_get(env,0)"),
        (f"0_0_2_0_{gid}_", "ouro_ctor(1,2,(ouro_v *[]){ouro_get(env,2),"
         "ouro_app(ouro_app(ouro_get(env,4),ouro_get(env,1)),ouro_get(env,0))})"),
        (f"0_2_0_{gid}_", f"ouro_clos(ouro_f0_0_2_0_{gid}_,env)"),
        (f"2_0_{gid}_", f"ouro_clos(ouro_f0_2_0_{gid}_,env)"),
        (f"{gid}_", "ouro_case(ouro_get(env,0),2,(ouro_v *[]){"
         f"ouro_clos(ouro_f1_0_{gid}_,env),ouro_clos(ouro_f2_0_{gid}_,env)}})"),
    )
    return "".join(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                   f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {body};}}\n"
                   for suffix, body in bodies)


def elem_helpers(gid, orb_gid):
    bodies = (
        (f"0_2_0_0_0_{gid}_", f"ouro_app(ouro_app(ouro_g{orb_gid}(),"
         "ouro_app(ouro_app(ouro_get(env,5),ouro_get(env,4)),ouro_get(env,1))),"
         "ouro_app(ouro_get(env,3),ouro_get(env,0)))"),
        (f"2_0_0_0_{gid}_", f"ouro_clos(ouro_f0_2_0_0_0_{gid}_,env)"),
        (f"0_0_{gid}_", "ouro_case(ouro_get(env,0),2,(ouro_v *[]){"
         f"ouro_thunk(ouro_t1_0_0_0_{gid}_,env),ouro_clos(ouro_f2_0_0_0_{gid}_,env)}})"),
        (f"0_{gid}_", f"ouro_fix(ouro_f0_0_{gid}_,env)"),
        (f"{gid}_", f"ouro_clos(ouro_f0_{gid}_,env)"),
    )
    nil = (f"static ouro_v *ouro_t1_0_0_0_{gid}_(ouro_env *env,ouro_v *arg){{"
           "(void)arg;(void)env;return ouro_ctor(1,0,0);}\n")
    return nil + "".join(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                          f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {body};}}\n"
                          for suffix, body in bodies)


def composed_module_source(module="", *, qualified=True, scopes=False, local=False):
    bindings = (("module_lookup", 51, PACKER.MODULE_LOOKUP_OWNER),
                ("lookup", 31, "std/listx.ouro"), ("eqNat", 41, "compiler/base.ouro"),
                ("add", 71, "std/prelude.ouro"), ("mul", 81, "std/prelude.ouro"),
                ("compareNat", 91, "std/data.ouro"), ("length", 101, "std/prelude.ouro"),
                ("append", 111, "std/prelude.ouro"), ("elem", 121, "std/data.ouro"),
                ("orb", 131, "std/prelude.ouro"), ("sub", 141, "std/prelude.ouro"))
    if local:
        bindings += (("lookup_local", 151, PACKER.LOWER_LOCAL_LOOKUP_OWNER),)
    units = LOCAL_COMPOSED_UNITS if local else COMPOSED_MODULE_UNITS
    rows = [(f"_ouro_m_{units.index(owner)}_{name}" if qualified else name, gid)
            for name, gid, owner in bindings]
    if scopes:
        rows.append(("module_invalid_maps", 61))
    text = export_source(rows, module,
                         arities={31: 3, 41: 2, 61: 3, 71: 2, 81: 2, 91: 2, 101: 1, 111: 2, 121: 3, 131: 2, 141: 2, 151: 2})
    text = re.sub(r"^static ouro_v \*ouro_f(?:0_){0,2}121_\([^\n]*\n", "", text, flags=re.MULTILINE)
    text = text.replace("static ouro_v *ouro_c121;", elem_helpers(121, 131) + "static ouro_v *ouro_c121;", 1)
    text = re.sub(r"^static ouro_v \*ouro_f(?:0_)?111_\([^\n]*\n", "", text, flags=re.MULTILINE)
    text = text.replace("static ouro_v *ouro_c111;", append_helpers(111) + "static ouro_v *ouro_c111;", 1)
    text = text.replace("ouro_c111=ouro_clos(ouro_f111_,env);", "ouro_c111=ouro_fix(ouro_f111_,env);", 1)
    return text.replace("ouro_c51=ouro_clos(ouro_f51_,env);",
                        "ouro_c51=ouro_app(ouro_g31(),ouro_g41());", 1)


def install_composed_module_sources(repo, root):
    for name in COMPOSED_MODULE_UNITS[:-1]:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(COMPOSED_MODULE_SOURCES[name], encoding="utf-8")
    (repo / root).write_text('import "module_names_base.ouro";\ndef main : Nat := Z;\n',
                            encoding="utf-8")
    return [*COMPOSED_MODULE_UNITS[:-1], root]


class ModuleLookupSourceControls(unittest.TestCase):
    def hook(self, text, module="", *, sources=None, units=MODULE_UNITS,
             canonical=MODULE_UNITS, installed=False):
        return PACKER.hook_module_lookup(text, units, canonical, canonical[-1],
                                         MODULE_SOURCES if sources is None else sources,
                                         module, installed=installed)

    def assert_composed_arithmetic(self, text):
        self.assertEqual(text.count("ouro_fast("), len(COMPOSED_ARITHMETIC_GETTERS))
        for name, gid in COMPOSED_ARITHMETIC_GETTERS:
            self.assertIn(f'static ouro_v *ouro_g{gid}(void){{if(ouro_c{gid}==0)'
                          f'ouro_c{gid}=ouro_fast("{name}");return ouro_c{gid};}}', text)
            self.assertNotIn(f"ouro_f{gid}_", text)

    def test_bound_alias_and_exact_raw_projection(self):
        prototype = "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"
        for module, qualified, offset, fast in (("", True, 0, False), ("_pl", True, 1000, True),
                                                ("_lo", False, 37, False), ("", False, 91, True)):
            with self.subTest(module=module, qualified=qualified, offset=offset, fast=fast):
                original = module_source(module, qualified=qualified, offset=offset, fast=fast)
                transformed = self.hook(original, module)
                raw = f"ouro_app(ouro_g{31 + offset}(),ouro_g{41 + offset}())"
                self.assertEqual(transformed.count(f"ouro_wrap_module_lookup({raw})"), 1)
                self.assertEqual(transformed.replace(prototype, "", 1).replace(
                    f"ouro_wrap_module_lookup({raw})", raw, 1), original)
                with patch.object(PACKER, "_base_ver", wraps=_base_ver) as families:
                    self.assertEqual(self.hook(transformed, module, installed=True), transformed)
                names = [call.args[0] for call in families.call_args_list]
                self.assertEqual(names.count(f"ouro_g{31 + offset}"), 1)
                with self.assertRaises(RuntimeError):
                    self.hook(transformed, module)
                with self.assertRaises(RuntimeError):
                    self.hook(original, module, installed=True)
        source = module_source()
        self.assertEqual(PACKER.hook_module_lookup(source, ("tools/unrelated.ouro",),
                                                  ("tools/unrelated.ouro",), "tools/unrelated.ouro", {}), source)
        opaque = {owner: '-- def module_lookup := wrong;\n' + text.replace(" :=", " -- binding\n :=")
                  for owner, text in MODULE_SOURCES.items()}
        self.assertEqual(self.hook(source, sources=opaque), self.hook(source))

    def test_source_drift_is_rejected(self):
        changes = (
            (PACKER.MODULE_LOOKUP_OWNER, "lookup Nat Nat eqNat", "lookup Nat Nat eq_nat"),
            (PACKER.MODULE_LOOKUP_OWNER, "def module_lookup", "private def module_lookup"),
            (PACKER.MODULE_LOOKUP_OWNER, "end;\n\ndef module_lookup", "end wrong\n\ndef module_lookup"),
            ("std/listx.ouro", "match eq a k with", "match eq k a with"),
            ("std/listx.ouro", "Just B b", "Just B a"),
            ("compiler/base.ouro", "| Z => True", "| Z => False"),
            ("compiler/base.ouro", "eqNat n' m'", "eqNat m' n'"),
            ("std/types.ouro", "| Nil : List A\n  | Cons : A -> List A -> List A", "| Cons : A -> List A -> List A\n  | Nil : List A"),
            ("std/types.ouro", "| MkPair : A -> B -> Pair A B", "| MkPair : B -> A -> Pair A B"),
            ("std/types.ouro", 'representation Maybe := "ouro.maybe"', 'representation Maybe := "ouro.pair"'),
            ("std/types.ouro", "inductive Nat", "private inductive Nat"),
        )
        for owner, old, new in changes:
            self.assertIn(old, MODULE_SOURCES[owner])
            sources = {**MODULE_SOURCES, owner: MODULE_SOURCES[owner].replace(old, new, 1)}
            with self.subTest(owner=owner, change=new), self.assertRaises(RuntimeError):
                self.hook(module_source(), sources=sources)
        for owner, kind, name, expected in PACKER.MODULE_LOOKUP_SOURCE_SHAPES:
            sources = {**MODULE_SOURCES, owner: MODULE_SOURCES[owner] + expected}
            with self.subTest(duplicate=name, kind=kind), self.assertRaises(RuntimeError):
                self.hook(module_source(), sources=sources)
        for owner in PACKER.MODULE_LOOKUP_SOURCE_PATHS:
            sources = {name: text for name, text in MODULE_SOURCES.items() if name != owner}
            with self.subTest(missing=owner), self.assertRaises(RuntimeError):
                self.hook(module_source(), sources=sources)
        sources = {**MODULE_SOURCES, PACKER.MODULE_LOOKUP_OWNER:
                   'def text : String := """def module_lookup : Nat := Z;""";\n'}
        with self.assertRaises(RuntimeError):
            self.hook(module_source(), sources=sources)

    def test_getter_table_and_curry_drift_is_rejected(self):
        original = module_source()
        invalid = (
            original.replace('"_ouro_m_0_module_lookup"', '"_ouro_m_1_module_lookup"'),
            original.replace('"_ouro_m_0_module_lookup"', '"_ouro_m_00_module_lookup"'),
            original.replace('"_ouro_m_2_eqNat"', '"_ouro_m_4_eqNat"'),
            original.replace('"_ouro_m_1_lookup"', '"_ouro_m_2_lookup"'),
            original.replace("return 3;", "return 4;", 1),
            original.replace("case 1:return ouro_g31();", "case 2:return ouro_g31();"),
            original.replace("case 2:return ouro_g41();", "case 2:return ouro_g31();"),
            original.replace("ouro_app(ouro_g31(),ouro_g41())", "ouro_app(ouro_g41(),ouro_g31())"),
            original.replace("ouro_app(ouro_g31(),ouro_g41())", "ouro_app(ouro_app(ouro_g31(),ouro_g41()),ouro_nat(0))"),
            original.replace("ouro_c51=ouro_app", "ouro_c51=ouro_nat(0);ouro_c51=ouro_app"),
            original.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;"),
            original.replace("return arg;}\nstatic ouro_v *ouro_f0_31_", "return ouro_clos(ouro_f0_0_0_31_,env);}\nstatic ouro_v *ouro_f0_31_"),
            original + "static ouro_v *ouro_g51_d2(void){return 0;}\n",
            original + "static ouro_v *ouro_c51_d2;\n",
            original + "static ouro_v *ouro_f0_31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + 'const char *ouro_export_name(int i){return "";}\n',
            original.replace('#include "ouro_rt.h"\n', ""),
        )
        for text in invalid:
            self.assertNotEqual(text, original)
            with self.subTest(text=text[-110:]), self.assertRaises(RuntimeError):
                self.hook(text)
        fast = module_source(fast=True)
        for text in (fast.replace('ouro_fast("eqNat")', 'ouro_fast("eq_nat")'),
                     fast.replace('ouro_c41=ouro_fast', 'ouro_c51=ouro_fast'),
                     fast.replace('return ouro_c41;}', 'return ouro_c31;}')):
            with self.assertRaises(RuntimeError):
                self.hook(text)
        transformed = self.hook(original)
        declaration = "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"
        for text in (transformed.replace(declaration, ""), transformed + declaration,
                     transformed.replace("ouro_wrap_module_lookup(ouro_app(ouro_g31(),ouro_g41()))",
                                         "ouro_wrap_module_lookup(ouro_app(ouro_g31(),ouro_g51()))")):
            with self.assertRaises(RuntimeError):
                self.hook(text, installed=True)
        for units in (MODULE_UNITS[::-1], MODULE_UNITS + MODULE_UNITS[:1]):
            with self.assertRaises(RuntimeError):
                self.hook(original, units=units)
        owner = "compiler/kernel_core.ouro"
        units = (*MODULE_UNITS[:-1], owner, MODULE_UNITS[-1])
        sources = {**MODULE_SOURCES, owner: MODULE_SOURCES["compiler/base.ouro"]}
        with self.assertRaises(RuntimeError):
            self.hook(module_source(qualified=False), sources=sources, units=units, canonical=units)

    def test_selected_cache_requires_installed_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = LookupCtorSourceControls().setup_repo(repo)
            root, module = "compiler/pipeline.ouro", "_pl"
            units = install_composed_module_sources(repo, root)
            graph[root] = units
            work = repo / "work"
            work.mkdir()
            calls = []
            def emit_mock(command, **kwargs):
                calls.append(command)
                kwargs["stdout"].write(composed_module_source(module, qualified=False, scopes=True).encode())
                return SimpleNamespace(returncode=0)
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph), \
                    patch.object(REGEN, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]):
                _units, inputs, _full = REGEN.all_frontend_inputs(seed, "16000")
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pl", mod=module, root=root,
                               file_name="pl.c", units=units, digests=inputs)
                with patch.object(REGEN.subprocess, "run", side_effect=emit_mock):
                    cold = REGEN.emit_one(**options)
                    with patch.object(PACKER, "_static_symbol_starts", wraps=_static_symbol_starts) as starts:
                        warm = REGEN.emit_one(**options)
                    starts.assert_called_once()
                    self.assertEqual((cold.cache, warm.cache, len(calls)), ("miss", "hit", 1))
                    self.assert_composed_arithmetic((work / "pl.c").read_text(encoding="utf-8"))
                    cache = repo / "cache" / (module + "_" + cold.key + ".c")
                    captured = cache.read_bytes()
                    verify = PACKER.hook_module_pure_scopes

                    def mutate_after_verify(*args, **kwargs):
                        result = verify(*args, **kwargs)
                        cache.write_bytes(b"replaced during validation")
                        return result

                    with patch.object(PACKER, "hook_module_pure_scopes", side_effect=mutate_after_verify):
                        self.assertEqual(REGEN.emit_one(**options).cache, "hit")
                    self.assertEqual((work / "pl.c").read_bytes(), captured)
                    cache.write_bytes(captured)
                    malformed = cache.read_text(encoding="utf-8").replace(
                        "ouro_wrap_module_lookup(ouro_app(ouro_g31(),ouro_g41()))",
                        "ouro_app(ouro_g31(),ouro_g41())")
                    cache.write_text(malformed, encoding="utf-8")
                    REGEN.record_cached_output(cache, cold.key)
                    previous = (work / "pl.c").read_bytes()
                    with self.assertRaises(RuntimeError):
                        REGEN.emit_one(**options)
                    self.assertEqual((work / "pl.c").read_bytes(), previous)

    def test_whitespace_duplicate_getter_and_curry_families_are_rejected(self):
        for fast in (False, True):
            raw = module_source(fast=fast)
            for installed in (False, True):
                original = self.hook(raw) if installed else raw
                duplicates = [f"static\nouro_v * ouro_g{gid}_d2(void){{return ouro_c{gid};}}\n"
                              for gid in (31, 41, 51)]
                duplicates.append("static ouro_v * ouro_f0_31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n")
                for duplicate in duplicates:
                    with self.subTest(fast=fast, installed=installed, duplicate=duplicate), self.assertRaises(RuntimeError):
                        self.hook(original + duplicate, installed=installed)

    def test_installer_helper_bytes_invalidate_all_cache_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = LookupCtorSourceControls().setup_repo(repo)
            root, module = "compiler/pipeline.ouro", "_pl"
            units = install_composed_module_sources(repo, root)
            graph[root] = units
            piece = repo / "piece.c"
            piece.write_text(composed_module_source(module), encoding="utf-8")
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph):
                _units, inputs, full = REGEN.all_frontend_inputs(seed, "16000")
                for helper in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
                    original = (repo / helper).read_bytes()
                    before_tu = REGEN.tu_key("pl", module, root, units, inputs, "16000")
                    before_pack = REGEN.pack_key([("pl", piece)], inputs)
                    (repo / helper).write_bytes(original + b"# changed SOURCE helper\n")
                    with self.assertRaises(RuntimeError):
                        REGEN.module_lookup_binding(root, units, inputs)
                    _units, changed, changed_full = REGEN.all_frontend_inputs(seed, "16000")
                    self.assertNotEqual(changed_full, full)
                    self.assertNotEqual(REGEN.tu_key("pl", module, root, units, changed, "16000"), before_tu)
                    self.assertNotEqual(REGEN.pack_key([("pl", piece)], changed), before_pack)
                    (repo / helper).write_bytes(original)

    def test_flat_emit_binds_before_aliases_and_keeps_previous_output_on_failure(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "accepted.c"
                output.write_bytes(b"previous complete output\n")
                emitted = composed_module_source()
                if not valid:
                    emitted = emitted.replace("ouro_app(ouro_g31(),ouro_g41())",
                                              "ouro_app(ouro_g41(),ouro_g31())")
                events = []
                lookup_hook = PACKER.hook_module_lookup
                def emit_mock(command, _emitted=emitted, **kwargs):
                    if command[0] == "SOURCE-mocked-compiler":
                        kwargs["stdout"].write(_emitted.encode())
                    return subprocess.CompletedProcess(command, 0)
                def lookup(text, *args, _hook=lookup_hook, _events=events, **kwargs):
                    self.assert_composed_arithmetic(text)
                    _events.append("lookup")
                    return _hook(text, *args, **kwargs)
                def aliases(text, *_args, _events=events, **_kwargs):
                    self.assert_composed_arithmetic(text)
                    self.assertIn("ouro_wrap_module_lookup(ouro_app(ouro_g31(),ouro_g41()))", text)
                    _events.append("aliases")
                    return text
                closure = fixture_scope_closure(COMPOSED_MODULE_UNITS, COMPOSED_MODULE_SOURCES)
                with patch.object(NATIVE.frontend, "collect_units_many", side_effect=closure), \
                        patch.object(NATIVE.frontend, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]), \
                        patch.object(NATIVE.subprocess, "run", side_effect=emit_mock), \
                        patch.object(PACKER, "hook_module_lookup", side_effect=lookup), \
                        patch.object(PACKER, "hook_module_pure_scopes", side_effect=lambda text, *_args, **_kwargs: text), \
                        patch.object(NATIVE, "current_native_scoped_aliases", side_effect=aliases):
                    if valid:
                        NATIVE.emit(Path("SOURCE-seed"), list(COMPOSED_MODULE_UNITS), 200000, output)
                        self.assertIn(b"ouro_wrap_module_lookup", output.read_bytes())
                        self.assertEqual(events, ["lookup", "aliases"])
                    else:
                        with self.assertRaises(RuntimeError):
                            NATIVE.emit(Path("SOURCE-seed"), list(COMPOSED_MODULE_UNITS), 200000, output)
                        self.assertEqual(output.read_bytes(), b"previous complete output\n")
                        self.assertEqual(events, ["lookup"])


def source_name_compare_fixture(module="", *, units=None, qualified=True):
    units = tuple(units or (*REGEN.collect_units(PACKER.SOURCE_NAME_COMPARE_OWNER), "tools/name_scope_entry.ouro"))
    entry = units[-1]
    sources = {unit: (REPO / unit).read_text(encoding="utf-8") for unit in units if unit != entry}
    sources[entry] = ('import "../compiler/source_name_index.ouro";\n'
                      + ('private def source_name_compare : Nat := Z;\n' if qualified else '')
                      + 'def main : Nat := Z;\n')
    bindings = [("source_name_compare", PACKER.SOURCE_NAME_COMPARE_OWNER, 31, 2)]
    bindings.extend((("elem", PACKER.ELEM_OWNER, 351, 3), ("orb", PACKER.ELEM_ORB_OWNER, 361, 2)))
    bindings.extend((name, owner, 101 + index * 10,
                     PACKER.PRELUDE_LIST_LENGTH_ROUTE[2] if name == "length" else 2)
                    for index, (name, owner) in enumerate((*PACKER.PRELUDE_ARITHMETIC_ROUTES,
                        PACKER.PRELUDE_LIST_LENGTH_ROUTE[:2], PACKER.PRELUDE_LIST_APPEND_ROUTE[:2]))
                    if owner in units)
    rows = [(f"_ouro_m_{units.index(owner)}_{name}" if qualified else name, gid)
            for name, owner, gid, _arity in bindings]
    rows.append(("main", 9999))
    text = export_source(rows, module, arities={gid: arity for _name, _owner, gid, arity in bindings})
    text = text.replace("ouro_c31=ouro_clos(ouro_f31_,env)", "ouro_c31=ouro_fix(ouro_f31_,env)", 1)
    text = re.sub(r"^static ouro_v \*ouro_f(?:0_){0,2}351_\([^\n]*\n", "", text, flags=re.MULTILINE)
    text = text.replace("static ouro_v *ouro_c351;", elem_helpers(351, 361) + "static ouro_v *ouro_c351;", 1)
    append_gid = next((gid for name, _owner, gid, _arity in bindings if name == "append"), None)
    if append_gid is not None:
        for step in reversed(range(2)):
            suffix = "0_" * step + str(append_gid) + "_"
            result = f"ouro_clos(ouro_f0_{suffix},env)" if step == 0 else "arg"
            body = (f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                    f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}\n")
            text = text.replace(body, "", 1)
        text = text.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + append_helpers(append_gid), 1)
        text = text.replace(f"ouro_c{append_gid}=ouro_clos(ouro_f{append_gid}_,env)",
                            f"ouro_c{append_gid}=ouro_fix(ouro_f{append_gid}_,env)", 1)
    return text, units, sources


def elem_scope_fixture(module="", *, units=None, qualified=True):
    units = tuple(units or (*REGEN.collect_units(PACKER.ELEM_OWNER), "tools/elem_scope_entry.ouro"))
    sources = {unit: (REPO / unit).read_text(encoding="utf-8") for unit in units[:-1]}
    sources[units[-1]] = ('import "../std/data.ouro";\n'
                         + ('private def elem : Nat := Z;\n' if qualified else '')
                         + 'def main : Nat := Z;\n')
    bindings = [("elem", PACKER.ELEM_OWNER, 31, 3), ("orb", PACKER.ELEM_ORB_OWNER, 41, 2)]
    bindings.extend((name, owner, 101 + index * 10,
                     PACKER.PRELUDE_LIST_LENGTH_ROUTE[2] if name == "length" else 2)
                    for index, (name, owner) in enumerate((*PACKER.PRELUDE_ARITHMETIC_ROUTES,
                        PACKER.PRELUDE_LIST_LENGTH_ROUTE[:2], PACKER.PRELUDE_LIST_APPEND_ROUTE[:2]))
                    if owner in units)
    rows = [(f"_ouro_m_{units.index(owner)}_{name}" if qualified else name, gid)
            for name, owner, gid, _arity in bindings]
    rows.append(("main", 9999))
    text = export_source(rows, module, arities={gid: arity for _name, _owner, gid, arity in bindings})
    text = re.sub(r"^static ouro_v \*ouro_f(?:0_){0,2}31_\([^\n]*\n", "", text, flags=re.MULTILINE)
    text = text.replace("static ouro_v *ouro_c31;", elem_helpers(31, 41) + "static ouro_v *ouro_c31;", 1)
    append_gid = next((gid for name, _owner, gid, _arity in bindings if name == "append"), None)
    if append_gid is not None:
        text = re.sub(rf"^static ouro_v \*ouro_f(?:0_)?{append_gid}_\([^\n]*\n", "", text,
                      flags=re.MULTILINE)
        text = text.replace(f"static ouro_v *ouro_c{append_gid};",
                            append_helpers(append_gid) + f"static ouro_v *ouro_c{append_gid};", 1)
        text = text.replace(f"ouro_c{append_gid}=ouro_clos(ouro_f{append_gid}_,env)",
                            f"ouro_c{append_gid}=ouro_fix(ouro_f{append_gid}_,env)", 1)
    return text, units, sources


class ElemScopeControls(unittest.TestCase):
    def hook(self, text, units, sources, module="", *, canonical=None, installed=False):
        return PACKER.hook_elem_scope(text, units, units if canonical is None else canonical,
                                     units[-1], sources, module, installed=installed)

    def test_exact_raw_projection_and_homonym_precision(self):
        declaration = "ouro_v *ouro_wrap_elem_scope(ouro_v *raw);\n"
        for module in ("", "_pa"):
            for qualified in (True, False):
                raw, units, sources = elem_scope_fixture(module, qualified=qualified)
                bound = self.hook(raw, units, sources, module)
                self.assertEqual(bound.replace(declaration, "", 1).replace(
                    "ouro_wrap_elem_scope(ouro_clos(ouro_f31_,env))", "ouro_clos(ouro_f31_,env)", 1), raw)
                with patch.object(PACKER, "_base_ver", wraps=_base_ver) as families:
                    self.assertEqual(self.hook(bound, units, sources, module, installed=True), bound)
                self.assertEqual([call.args[0] for call in families.call_args_list].count("ouro_f31_"), 1)
                with self.assertRaises(RuntimeError):
                    self.hook(raw, units, sources, module, installed=True)
                if qualified and not module:
                    aliased = NATIVE.current_native_scoped_aliases(bound, units, units, units[-1], sources)
                    self.assertIn('return "elem_scope";', aliased)
                    self.assertIn('return "_ouro_m_2_elem";', aliased)
                    self.assertIn("ouro_wrap_elem_scope(ouro_clos(ouro_f31_,env))", aliased)
                    with self.assertRaises(RuntimeError):
                        self.hook(aliased, units, sources, installed=True)
        units = ("tools/elem_only_types.ouro",)
        sources = {units[0]: 'import "../std/types.ouro";\ndef elem : Bool := False;\n'}
        raw = export_source((("elem", 31),))
        self.assertEqual(self.hook(raw, units, sources), raw)
        with self.assertRaises(RuntimeError):
            self.hook(raw + declaration, units, sources)

    def test_literal_source_body_import_type_and_layout_refusals(self):
        raw, units, sources = elem_scope_fixture()
        mutations = (
            (PACKER.ELEM_OWNER, "orb(eq x y, elem ys)", "eq x y"),
            (PACKER.ELEM_OWNER, "eq : A -> A -> Bool", "eq : A -> Bool"),
            (PACKER.ELEM_OWNER, "| Nil => False", "| Nil => True"),
            (PACKER.ELEM_OWNER, "def elem", "private def elem"),
            (PACKER.ELEM_OWNER, 'import "prelude.ouro";', 'import "types.ouro";'),
            (PACKER.ELEM_ORB_OWNER, "| False => y", "| False => False"),
            (PACKER.ELEM_ORB_OWNER, 'import "types.ouro";', 'import "data.ouro";'),
            ("std/types.ouro", '| True : Bool\n  | False : Bool', '| False : Bool\n  | True : Bool'),
            ("std/types.ouro", '"ouro.bool"', '"changed.bool"'),
            ("std/types.ouro", '"ouro.list"', '"changed.list"'),
        )
        for owner, old, new in mutations:
            changed = sources[owner].replace(old, new, 1)
            self.assertNotEqual(changed, sources[owner])
            with self.subTest(owner=owner, new=new), self.assertRaises(RuntimeError):
                self.hook(raw, units, {**sources, owner: changed})
        for owner, extra in ((PACKER.ELEM_OWNER, "def elem : Bool := False;\n"),
                             (PACKER.ELEM_ORB_OWNER, "def orb : Bool := False;\n")):
            with self.assertRaises(RuntimeError):
                self.hook(raw, units, {**sources, owner: sources[owner] + extra})

    def test_all_six_helper_bodies_cache_owner_and_getter_refusals(self):
        raw, units, sources = elem_scope_fixture()
        for body in elem_helpers(31, 41).splitlines(keepends=True):
            self.assertIn(body, raw)
            malformed = ["", body + body, body.replace("{", "{\n", 1),
                         body.replace("ouro_v *arg)", "ouro_v *arg,ouro_v *extra)")]
            if "ouro_cons(arg,env0)" in body:
                malformed.append(body.replace("ouro_cons(arg,env0)", "ouro_cons(arg,0)"))
            for replacement in malformed:
                self.assertNotEqual(replacement, body)
                with self.subTest(body=body[:50]), self.assertRaises(RuntimeError):
                    self.hook(raw.replace(body, replacement, 1), units, sources)
            symbol = re.search(r"\*(ouro_[ft][^ (]+)\(", body).group(1)
            with self.assertRaises(RuntimeError):
                self.hook(raw + f"ouro_v *outside(void){{return {symbol}(0,0);}}\n", units, sources)
        for old, new in (
            ('"_ouro_m_2_elem"', '"_ouro_m_999_elem"'),
            ('"_ouro_m_1_orb"', '"_ouro_m_999_orb"'),
            ("ouro_c31=ouro_clos(ouro_f31_,env)", "ouro_c31=ouro_fix(ouro_f31_,env)"),
            ("ouro_fix(ouro_f0_0_31_,env)", "ouro_clos(ouro_f0_0_31_,env)"),
            ("ouro_ctor(1,0,0)", "ouro_ctor(0,0,0)"),
            ("ouro_g41()", "ouro_g101()"),
            ("ouro_get(env,5)", "ouro_get(env,4)"),
            ("ouro_app(ouro_get(env,3),ouro_get(env,0))", "ouro_get(env,0)"),
            ("static ouro_v *ouro_c31;", "static ouro_v * ouro_c31;"),
            ("return ouro_g41();", "return ouro_g31();"),
        ):
            self.assertIn(old, raw)
            changed = raw.replace(old, new, 1)
            self.assertNotEqual(changed, raw)
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                self.hook(changed, units, sources)
        with self.assertRaises(RuntimeError):
            self.hook(raw, units, sources, canonical=tuple(reversed(units)))
        for extra in ("static ouro_v *ouro_f9_31_(ouro_env *env0,ouro_v *arg){return arg;}\n",
                      "static ouro_v *ouro_g31_d2(void){return ouro_c31;}\n",
                      "static ouro_v *ouro_c31;\n"):
            with self.assertRaises(RuntimeError):
                self.hook(raw + extra, units, sources)
        declaration = "ouro_v *ouro_wrap_elem_scope(ouro_v *raw);\n"
        bound = self.hook(raw, units, sources)
        version = "static ouro_v *ouro_f31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n"
        with self.assertRaisesRegex(RuntimeError, "^missing, unexpected or duplicate elem scope helper family$"):
            self.hook(bound + version, units, sources, installed=True)
        for malformed in (bound.replace(declaration, ""), bound + declaration,
                          bound.replace("ouro_wrap_elem_scope(ouro_clos(ouro_f31_,env))",
                                        "ouro_wrap_elem_scope(ouro_clos(ouro_f0_31_,env))")):
            with self.assertRaises(RuntimeError):
                self.hook(malformed, units, sources, installed=True)

    def test_capability_placement_and_saturated_arity(self):
        runtime = (REPO / "runtime/frontend_link.c").read_text(encoding="utf-8")
        definition = ("ouro_v *ouro_wrap_elem_scope(ouro_v *raw)\n{\n"
                      "\treturn ouro_wrap_module_pure_scope(raw, 3);\n}")
        self.assertTrue(REGEN.elem_scope_capability(runtime))
        self.assertFalse(REGEN.elem_scope_capability("#ifndef OURO_FE_FLAT_EXPORTS\n#endif\n"))
        for changed in (runtime.replace(definition, definition.replace("raw, 3", "raw, 2")),
                        runtime.replace(definition, definition + definition),
                        runtime.replace(definition, "") + definition):
            self.assertNotEqual(changed, runtime)
            with self.assertRaises(RuntimeError):
                REGEN.elem_scope_capability(changed)

    def test_tu_cache_binding_helper_freshness_and_installed_body_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = LookupCtorSourceControls().setup_repo(repo)
            root, module = "compiler/parse_a.ouro", "_pa"
            closure = (*REGEN.collect_units(PACKER.ELEM_OWNER), root)
            raw, _units, sources = elem_scope_fixture(module, units=closure)
            for unit in closure:
                target = repo / unit
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(sources[unit], encoding="utf-8")
            graph[root] = list(closure)
            work = repo / "work"
            work.mkdir()

            def emit_mock(_command, **kwargs):
                kwargs["stdout"].write(raw.encode())
                return SimpleNamespace(returncode=0)

            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph), \
                    patch.object(REGEN, "collect_units", side_effect=lambda selected: graph[selected]), \
                    patch.object(REGEN, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]):
                _graph, inputs, full = REGEN.all_frontend_inputs(seed, "16000")
                self.assertTrue(REGEN.elem_scope_binding(root, closure, inputs)["selected"])
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=closure, digests=inputs)
                with patch.object(REGEN.subprocess, "run", side_effect=emit_mock) as calls:
                    cold, warm = REGEN.emit_one(**options), REGEN.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                    output = work / "pa.c"
                    installed = output.read_text(encoding="utf-8")
                    self.assertIn("ouro_wrap_elem_scope(ouro_clos(ouro_f31_,env))", installed)
                    cache = repo / "cache" / (module + "_" + cold.key + ".c")
                    cache.write_text(installed.replace("ouro_get(env,5)", "ouro_get(env,4)", 1), encoding="utf-8")
                    REGEN.record_cached_output(cache, cold.key)
                    with self.assertRaises(RuntimeError):
                        REGEN.emit_one(**options)
                    self.assertEqual(output.read_text(encoding="utf-8"), installed)
                    self.assertEqual(calls.call_count, 1)
                baseline_tu = REGEN.tu_key("pa", module, root, closure, inputs, "16000")
                pieces = [("pa", output)]
                baseline_pack = REGEN.pack_key(pieces, inputs)
                for selected_path in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py",
                                      *PACKER.ELEM_SOURCE_PATHS, "runtime/frontend_link.c"):
                    target = repo / selected_path
                    original = target.read_text(encoding="utf-8")
                    comment = ("--" if selected_path.endswith(".ouro") else
                               "//" if selected_path.endswith(".c") else "#")
                    target.write_text(original + f"\n{comment} SOURCE digest mutation\n", encoding="utf-8")
                    with self.assertRaises(RuntimeError):
                        REGEN.elem_scope_binding(root, closure, inputs)
                    _graph, changed, changed_full = REGEN.all_frontend_inputs(seed, "16000")
                    self.assertNotEqual(changed_full, full)
                    self.assertNotEqual(REGEN.tu_key("pa", module, root, closure, changed, "16000"), baseline_tu)
                    self.assertNotEqual(REGEN.pack_key(pieces, changed), baseline_pack)
                    target.write_text(original, encoding="utf-8")
                for missing in ("frontend_runtime", *PACKER.ELEM_SOURCE_PATHS,
                                "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
                    absent = {name: value for name, value in inputs.items() if name != missing}
                    with self.assertRaises(RuntimeError):
                        REGEN.elem_scope_binding(root, closure, absent)
                with self.assertRaises(RuntimeError):
                    REGEN.elem_scope_binding(root, (*closure, PACKER.ELEM_OWNER), inputs)


class SourceNameCompareScopeControls(unittest.TestCase):
    def hook(self, text, units, sources, module="", *, canonical=None, installed=False):
        return PACKER.hook_source_name_compare_scope(text, units, units if canonical is None else canonical,
            units[-1], sources, module, installed=installed)

    def test_only_getter_and_prototype_change(self):
        declaration = "ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw);\n"
        for module, qualified in (("", True), ("_lx", True), ("_pl", False)):
            with self.subTest(module=module, qualified=qualified):
                raw, units, sources = source_name_compare_fixture(module, qualified=qualified)
                bound = self.hook(raw, units, sources, module)
                self.assertEqual(bound.replace(declaration, "", 1).replace(
                    "ouro_wrap_source_name_compare_scope(ouro_fix(ouro_f31_,env))", "ouro_fix(ouro_f31_,env)", 1), raw)
                with patch.object(PACKER, "_base_ver", wraps=_base_ver) as families:
                    self.assertEqual(self.hook(bound, units, sources, module, installed=True), bound)
                self.assertEqual([call.args[0] for call in families.call_args_list].count("ouro_f0_31_"), 1)
                with self.assertRaises(RuntimeError):
                    self.hook(raw, units, sources, module, installed=True)
                with self.assertRaises(RuntimeError):
                    self.hook(bound, units, sources, module)
        raw = export_source((("source_name_compare", 31), ("main", 41)))
        units = ("tools/root_homonym.ouro",)
        sources = {units[0]: "def source_name_compare (arg : Nat) : Nat := arg;\ndef main : Nat := Z;"}
        self.assertEqual(self.hook(raw, units, sources), raw)
        self.assertEqual(NATIVE.current_native_scoped_aliases(raw, units, units, units[-1], sources), raw)
        with self.assertRaises(RuntimeError):
            self.hook(raw + declaration, units, {})

    def test_source_body_type_layout_import_and_visibility_mutations(self):
        raw, units, sources = source_name_compare_fixture()
        changes = (
            (PACKER.SOURCE_NAME_COMPARE_OWNER, "| EQ => compare rest tail", "| EQ => EQ"),
            (PACKER.SOURCE_NAME_COMPARE_OWNER, "List Nat -> List Nat -> Ordering", "List Nat -> Ordering"),
            (PACKER.SOURCE_NAME_COMPARE_OWNER, 'import "source_text.ouro";', 'import "base.ouro";'),
            (PACKER.SOURCE_NAME_COMPARE_OWNER, 'import "source_text.ouro";',
             'import "source_text.ouro";\nimport "base.ouro";'),
            (PACKER.SOURCE_NAME_COMPARE_OWNER, "def source_name_compare", "private def source_name_compare"),
            ("std/types.ouro", "LT : Ordering\n  | EQ : Ordering\n  | GT : Ordering",
             "EQ : Ordering\n  | LT : Ordering\n  | GT : Ordering"),
            ("std/types.ouro", 'representation List := "ouro.list";', 'representation List := "changed";'),
            ("std/data.ouro", "| S n', S m' => compareNat n' m'", "| S n', S m' => EQ"),
            ("std/data.ouro", 'import "prelude.ouro";', 'import "types.ouro";'),
        )
        for owner, old, new in changes:
            with self.subTest(owner=owner, new=new):
                changed = {**sources, owner: sources[owner].replace(old, new, 1)}
                self.assertNotEqual(changed[owner], sources[owner])
                with self.assertRaises(RuntimeError):
                    self.hook(raw, units, changed)
        for owner, extra in ((PACKER.SOURCE_NAME_COMPARE_OWNER, "def source_name_compare : Nat := Z;"),
                             ("std/types.ouro", 'representation Ordering := "changed";')):
            with self.assertRaises(RuntimeError):
                self.hook(raw, units, {**sources, owner: sources[owner] + extra})

    def test_original_owner_inventory_cache_and_curry_refusals(self):
        raw, units, sources = source_name_compare_fixture()
        ordinal = units.index(PACKER.SOURCE_NAME_COMPARE_OWNER)
        for original, installed in ((raw, False), (self.hook(raw, units, sources), True)):
            changes = (
                original.replace(f'"_ouro_m_{ordinal}_source_name_compare"', '"_ouro_m_999_source_name_compare"'),
                original.replace("case 0:return ouro_g31();", "case 0:return ouro_g9999();"),
                original.replace("static ouro_v *ouro_c31;", "static ouro_v *ouro_c31;\nstatic ouro_v *ouro_c31;"),
                original.replace("ouro_fix(ouro_f31_,env)", "ouro_clos(ouro_f31_,env)", 1),
                original.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;", 1),
                original.replace("static ouro_v *ouro_f0_31_(ouro_env *env0,ouro_v *arg)",
                                 "static ouro_v *ouro_f0_31_(ouro_env *wrong,ouro_v *arg)", 1),
                original.replace("static ouro_v *ouro_f0_31_(ouro_env *env0,ouro_v *arg){"
                                 "ouro_env *env=ouro_cons(arg,env0);(void)env;return arg;}",
                                 "static ouro_v *ouro_f0_31_(ouro_env *env0,ouro_v *arg){"
                                 "ouro_env *env=ouro_cons(arg,env0);(void)env;return ouro_clos(ouro_f0_0_31_,env);}"),
                original + "static ouro_v *ouro_f31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            )
            for changed in changes:
                with self.subTest(installed=installed, changed=changed[-80:]):
                    self.assertNotEqual(changed, original)
                    with self.assertRaises(RuntimeError):
                        self.hook(changed, units, sources, installed=installed)
        with self.assertRaises(RuntimeError):
            self.hook(raw, units, sources, canonical=units[::-1])
        with self.assertRaises(RuntimeError):
            self.hook(raw, (*units[:-1], units[0], units[-1]), sources)
        bound = self.hook(raw, units, sources)
        declaration = "ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw);\n"
        for changed in (bound.replace(declaration, ""), bound + declaration,
                        bound.replace("ouro_wrap_source_name_compare_scope(ouro_fix(ouro_f31_,env))",
                                      "ouro_wrap_module_pure_scope(ouro_fix(ouro_f31_,env),2)")):
            with self.assertRaises(RuntimeError):
                self.hook(changed, units, sources, installed=True)

    def test_exact_runtime_capability_and_historical_absence(self):
        runtime = (REPO / "runtime/frontend_link.c").read_text(encoding="utf-8")
        definition = ("ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw)\n{\n"
                      "\treturn ouro_wrap_module_pure_scope(raw, 2);\n}")
        self.assertTrue(REGEN.source_name_compare_capability(runtime))
        self.assertFalse(REGEN.source_name_compare_capability("#ifndef OURO_FE_FLAT_EXPORTS\n#endif\n"))
        for changed in (runtime.replace("return ouro_wrap_module_pure_scope(raw, 2);",
                                        "return ouro_wrap_module_pure_scope(raw, 1);", 1),
                        runtime + definition,
                        "#ifndef OURO_FE_FLAT_EXPORTS\n" + definition + "\n#endif\n"):
            with self.assertRaises(RuntimeError):
                REGEN.source_name_compare_capability(changed)

    def test_frontend_installed_cache_readback_and_helper_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = LookupCtorSourceControls().setup_repo(repo)
            root, module = "compiler/parse_a.ouro", "_pa"
            closure = (*REGEN.collect_units(PACKER.SOURCE_NAME_COMPARE_OWNER), root)
            for unit in closure[:-1]:
                target = repo / unit
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / unit, target)
            (repo / root).write_text('import "source_name_index.ouro";\ndef main : Nat := Z;\n', encoding="utf-8")
            graph[root] = list(closure)
            raw, _units, _sources = source_name_compare_fixture(module, units=closure)
            work = repo / "work"
            work.mkdir()
            def emit_mock(_command, **kwargs):
                kwargs["stdout"].write(raw.encode())
                return SimpleNamespace(returncode=0)
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph), \
                    patch.object(REGEN, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]):
                _units, inputs, full = REGEN.all_frontend_inputs(seed, "16000")
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                    tu_cache=repo / "cache", tag="pa", mod=module, root=root, file_name="pa.c",
                    units=closure, digests=inputs)
                expected_key = REGEN.tu_key("pa", module, root, closure, inputs, "16000")
                with (patch.object(REGEN.subprocess, "run", side_effect=emit_mock) as calls,
                      patch.object(REGEN, "source_name_compare_binding",
                                   wraps=REGEN.source_name_compare_binding) as scope,
                      patch.object(REGEN, "lower_ctor_lookup_binding",
                                   wraps=REGEN.lower_ctor_lookup_binding) as ctor):
                    cold = REGEN.emit_one(**options)
                    cold_bytes = (work / "pa.c").read_bytes()
                    warm = REGEN.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                    self.assertEqual((cold.key, warm.key), (expected_key, expected_key))
                    self.assertEqual((scope.call_count, ctor.call_count), (2, 2))
                    self.assertEqual((work / "pa.c").read_bytes(), cold_bytes)
                    installed = (work / "pa.c").read_text(encoding="utf-8")
                    self.assertIn("ouro_wrap_source_name_compare_scope(ouro_fix(ouro_f31_,env))", installed)
                    cache = repo / "cache" / (module + "_" + cold.key + ".c")
                    cache.write_text(installed.replace("ouro_wrap_source_name_compare_scope(ouro_fix(ouro_f31_,env))",
                                                     "ouro_fix(ouro_f31_,env)"), encoding="utf-8")
                    REGEN.record_cached_output(cache, cold.key)
                    with self.assertRaises(RuntimeError):
                        REGEN.emit_one(**options)
                    self.assertEqual((work / "pa.c").read_text(encoding="utf-8"), installed)
                    self.assertEqual(calls.call_count, 1)
                piece = repo / "piece.c"
                piece.write_text(installed, encoding="utf-8")
                pack = REGEN.pack_key([("pa", piece)], inputs)
                for owner in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py",
                              "runtime/frontend_link.c", PACKER.SOURCE_NAME_COMPARE_OWNER):
                    target = repo / owner
                    saved = target.read_bytes()
                    target.write_bytes(saved + (b"\n// SOURCE hash change\n" if owner.endswith(".c")
                                                else b"\n-- SOURCE hash change\n" if owner.endswith(".ouro")
                                                else b"\n# SOURCE hash change\n"))
                    with self.assertRaises(RuntimeError):
                        REGEN.source_name_compare_binding(root, closure, inputs)
                    _graph, changed, changed_full = REGEN.all_frontend_inputs(seed, "16000")
                    self.assertNotEqual(changed_full, full)
                    self.assertNotEqual(REGEN.tu_key("pa", module, root, closure, changed, "16000"), cold.key)
                    self.assertNotEqual(REGEN.pack_key([("pa", piece)], changed), pack)
                    target.write_bytes(saved)


def lower_local_source(module="", *, units=LOCAL_LOOKUP_UNITS, qualified=True, fast=False):
    bindings = (("lookup_local", 31, PACKER.LOWER_LOCAL_LOOKUP_OWNER),
                ("eqNat", 41, "compiler/base.ouro"))
    rows = [(f"_ouro_m_{units.index(owner)}_{name}" if qualified and owner != units[-1] else name, gid)
            for name, gid, owner in bindings]
    text = export_source(rows, module, arities={31: 2, 41: 2})
    if fast:
        original = ('static ouro_v *ouro_g41(void){ouro_env *env=0;(void)env;'
                    'if(ouro_c41==0){ouro_static_begin();ouro_c41=ouro_clos(ouro_f41_,env);'
                    'ouro_static_end();}return ouro_c41;}')
        text = text.replace(original, 'static ouro_v *ouro_g41(void){if(ouro_c41==0)'
                            'ouro_c41=ouro_fast("eqNat");return ouro_c41;}', 1)
    return text


class LowerLocalLookupSourceControls(unittest.TestCase):
    def hook(self, text, module="", *, sources=None, units=LOCAL_LOOKUP_UNITS,
             canonical=None, installed=False):
        return PACKER.hook_lower_local_lookup(
            text, units, units if canonical is None else canonical, units[-1],
            LOCAL_LOOKUP_SOURCES if sources is None else sources, module, installed=installed)

    def test_exact_getter_bare_scoped_fast_and_prefix_contract(self):
        prototype = "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"
        for module, qualified, fast in (("", True, False), ("_lo", False, False), ("_pl", True, True)):
            with self.subTest(module=module, qualified=qualified, fast=fast):
                raw = lower_local_source(module, qualified=qualified, fast=fast)
                bound = self.hook(raw, module)
                expected = raw.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + prototype, 1)
                expected = expected.replace("ouro_c31=ouro_clos(ouro_f31_,env);",
                    "ouro_c31=ouro_wrap_module_lookup(ouro_clos(ouro_f31_,env));", 1)
                self.assertEqual(bound, expected)
                with patch.object(PACKER, "_base_ver", wraps=_base_ver) as families:
                    self.assertEqual(self.hook(bound, module, installed=True), bound)
                self.assertEqual([call.args[0] for call in families.call_args_list].count("ouro_f31_"), 1)
                with self.assertRaises(RuntimeError):
                    self.hook(raw, module, installed=True)
                with self.assertRaises(RuntimeError):
                    self.hook(bound, module)
                prefixed = PACKER.prefix_blob(bound, "lo")
                self.assertIn("ouro_lo_c31=ouro_wrap_module_lookup(ouro_clos(ouro_lo_f31_,env));", prefixed)

    def test_module_companion_requires_both_exact_getters_and_one_prototype(self):
        for module in ("", "_pl"):
            raw = composed_module_source(module, local=True)
            module_bound = PACKER.hook_module_lookup(raw, LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS,
                LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES, module)
            bound = self.hook(module_bound, module, units=LOCAL_COMPOSED_UNITS, sources=LOCAL_COMPOSED_SOURCES)
            self.assertEqual(bound.count("ouro_wrap_module_lookup"), 3)
            self.assertEqual(bound.count("ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"), 1)
            self.assertEqual(PACKER.hook_module_lookup(bound, LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS,
                LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES, module, installed=True), bound)
            self.assertEqual(self.hook(bound, module, units=LOCAL_COMPOSED_UNITS,
                sources=LOCAL_COMPOSED_SOURCES, installed=True), bound)
            for malformed in (bound.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))",
                                            "ouro_clos(ouro_f151_,env)"),
                              bound.replace("ouro_wrap_module_lookup(ouro_app(ouro_g31(),ouro_g41()))",
                                            "ouro_wrap_module_lookup(ouro_app(ouro_g41(),ouro_g31()))")):
                with self.assertRaises(RuntimeError):
                    self.hook(malformed, module, units=LOCAL_COMPOSED_UNITS,
                              sources=LOCAL_COMPOSED_SOURCES, installed=True)

    def test_source_body_import_identity_and_layout_mutations_fail_closed(self):
        changes = (
            (PACKER.LOWER_LOCAL_LOOKUP_OWNER, "match eqNat n nameId with", "match eqNat nameId nameId with"),
            (PACKER.LOWER_LOCAL_LOOKUP_OWNER, "| True => Just Surface ty", "| True => Nothing Surface"),
            (PACKER.LOWER_LOCAL_LOOKUP_OWNER, "| False => go xs'", "| False => Nothing Surface"),
            (PACKER.LOWER_LOCAL_LOOKUP_OWNER, "def lookup_local", "private def lookup_local"),
            (PACKER.LOWER_LOCAL_LOOKUP_OWNER, '"core.ouro"', '"other.ouro"'),
            ("compiler/core.ouro", "| SVar       : Nat -> Surface", "| SVar : Nat -> Nat -> Surface"),
            ("compiler/core.ouro", '"base.ouro"', '"other.ouro"'),
            ("compiler/base.ouro", "eqNat n' m'", "eqNat n' n'"),
            ("std/types.ouro", 'representation Pair := "ouro.pair"', 'representation Pair := "ouro.list"'),
            ("std/types.ouro", "| Just : A -> Maybe A", "| Just : A -> A -> Maybe A"),
        )
        for owner, old, new in changes:
            self.assertIn(old, LOCAL_LOOKUP_SOURCES[owner])
            sources = {**LOCAL_LOOKUP_SOURCES, owner: LOCAL_LOOKUP_SOURCES[owner].replace(old, new, 1)}
            with self.subTest(owner=owner, new=new), self.assertRaises(RuntimeError):
                self.hook(lower_local_source(), sources=sources)
        for owner, _kind, name, expected in PACKER.LOWER_LOCAL_LOOKUP_SOURCE_SHAPES:
            sources = {**LOCAL_LOOKUP_SOURCES, owner: LOCAL_LOOKUP_SOURCES[owner] + expected}
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                self.hook(lower_local_source(), sources=sources)

    def test_curry_owner_alias_cache_and_closure_mutations_are_rejected(self):
        raw = lower_local_source()
        malformed = (
            raw.replace('"_ouro_m_0_lookup_local"', '"_ouro_m_1_lookup_local"'),
            raw.replace("case 0:return ouro_g31();", "case 0:return ouro_g41();"),
            raw.replace("ouro_c31=ouro_clos(ouro_f31_,env);", "ouro_c31=ouro_nat(0);"),
            raw.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;"),
            raw.replace("(void)env;return arg;", "(void)env;return ouro_clos(ouro_f0_0_31_,env);", 1),
            raw + "static ouro_v *ouro_g31_d2(void){return 0;}\n",
            raw + "static ouro_v *ouro_f0_31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
        )
        for changed in malformed:
            with self.subTest(changed=changed[-100:]), self.assertRaises(RuntimeError):
                self.hook(changed)
        for units, canonical in ((LOCAL_LOOKUP_UNITS + (LOCAL_LOOKUP_UNITS[0],), LOCAL_LOOKUP_UNITS),
                                 (LOCAL_LOOKUP_UNITS, tuple(reversed(LOCAL_LOOKUP_UNITS)))):
            with self.assertRaises(RuntimeError):
                self.hook(raw, units=units, canonical=canonical)
        bound = self.hook(raw)
        for changed in (bound + "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n",
                        bound.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f31_,env))",
                                      "ouro_wrap_module_lookup(ouro_clos(ouro_f41_,env))")):
            with self.assertRaises(RuntimeError):
                self.hook(changed, installed=True)

    def test_compiler_cold_warm_cache_and_source_input_freshness(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = LookupCtorSourceControls().setup_repo(repo)
            root, module = "compiler/pipeline.ouro", "_pl"
            closure = [*LOCAL_COMPOSED_UNITS[:-1], root]
            for path in LOCAL_COMPOSED_UNITS[:-1]:
                (repo / path).write_text(LOCAL_COMPOSED_SOURCES[path], encoding="utf-8")
            graph[root] = closure
            work = repo / "work"
            work.mkdir()
            calls = []
            def emit_mock(command, **kwargs):
                calls.append(command)
                kwargs["stdout"].write(composed_module_source(module, scopes=True, local=True).encode())
                return SimpleNamespace(returncode=0)
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph), \
                    patch.object(REGEN, "collect_units", side_effect=lambda selected: graph[selected]), \
                    patch.object(REGEN, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]):
                _graph, inputs, full = REGEN.all_frontend_inputs(seed, "16000")
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                    tu_cache=repo / "cache", tag="pl", mod=module, root=root,
                    file_name="pl.c", units=closure, digests=inputs)
                with patch.object(REGEN.subprocess, "run", side_effect=emit_mock):
                    cold, warm = REGEN.emit_one(**options), REGEN.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, len(calls)), ("miss", "hit", 1))
                    installed = (work / "pl.c").read_text(encoding="utf-8")
                    self.assertIn("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))", installed)
                    cache = repo / "cache" / (module + "_" + cold.key + ".c")
                    cache.write_text(installed.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))",
                                                      "ouro_clos(ouro_f151_,env)"), encoding="utf-8")
                    REGEN.record_cached_output(cache, cold.key)
                    with self.assertRaises(RuntimeError):
                        REGEN.emit_one(**options)
                    self.assertEqual((work / "pl.c").read_text(encoding="utf-8"), installed)
                    self.assertEqual(len(calls), 1)
                piece = repo / "piece.c"
                piece.write_text(installed, encoding="utf-8")
                pack = REGEN.pack_key([("pl", piece)], inputs)
                for owner in (*PACKER.LOWER_LOCAL_LOOKUP_SOURCE_PATHS, "runtime/frontend_link.c",
                              "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
                    target = repo / owner
                    original = target.read_bytes()
                    target.write_bytes(original + (b"\n/* Source hash change */\n" if owner.endswith(".c")
                        else b"\n-- Source hash change\n" if owner.endswith(".ouro") else b"\n# Source hash change\n"))
                    with self.assertRaises(RuntimeError):
                        REGEN.lower_local_lookup_binding(root, closure, inputs)
                    _graph, changed, changed_full = REGEN.all_frontend_inputs(seed, "16000")
                    self.assertNotEqual(changed_full, full)
                    self.assertNotEqual(REGEN.tu_key("pl", module, root, closure, changed, "16000"), cold.key)
                    self.assertNotEqual(REGEN.pack_key([("pl", piece)], changed), pack)
                    target.write_bytes(original)

    def test_native_owner_binds_before_aliases_and_preserves_output_on_failure(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "accepted.c"
                output.write_bytes(b"previous complete output\n")
                emitted = composed_module_source(scopes=True, local=True)
                if not valid:
                    emitted = emitted.replace("ouro_c151=ouro_clos(ouro_f151_,env);", "ouro_c151=ouro_nat(0);")
                events = []
                def emit_mock(command, *, _emitted=emitted, **kwargs):
                    if command[0] == "SOURCE-mocked-compiler":
                        kwargs["stdout"].write(_emitted.encode())
                    return subprocess.CompletedProcess(command, 0)
                def lookup(text, *args, _events=events, local_hook=PACKER.hook_lower_local_lookup, **kwargs):
                    _events.append("lookup_local")
                    return local_hook(text, *args, **kwargs)
                def aliases(text, *_args, _events=events, **_kwargs):
                    self.assertIn("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))", text)
                    _events.append("aliases")
                    return text
                closure = fixture_scope_closure(LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_SOURCES)
                with patch.object(NATIVE.frontend, "collect_units_many", side_effect=closure), \
                        patch.object(NATIVE.frontend, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]), \
                        patch.object(NATIVE.subprocess, "run", side_effect=emit_mock), \
                        patch.object(PACKER, "hook_lower_local_lookup", side_effect=lookup), \
                        patch.object(NATIVE, "current_native_scoped_aliases", side_effect=aliases):
                    if valid:
                        NATIVE.emit(Path("SOURCE-seed"), list(LOCAL_COMPOSED_UNITS), 200000, output)
                        self.assertEqual(events, ["lookup_local", "aliases"])
                        self.assertIn(b"ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))", output.read_bytes())
                    else:
                        with self.assertRaises(RuntimeError):
                            NATIVE.emit(Path("SOURCE-seed"), list(LOCAL_COMPOSED_UNITS), 200000, output)
                        self.assertEqual(events, ["lookup_local"])
                        self.assertEqual(output.read_bytes(), b"previous complete output\n")

    def native_installed_source(self):
        raw = composed_module_source(scopes=True, local=True)
        module_bound = PACKER.hook_module_lookup(raw, LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        bound = self.hook(module_bound, units=LOCAL_COMPOSED_UNITS, sources=LOCAL_COMPOSED_SOURCES)
        aliased = NATIVE.current_native_scoped_aliases(bound, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        return module_bound, bound, aliased

    def test_native_original_view_preserves_bodies_and_rejects_unknown_aliases(self):
        module_bound, bound, aliased = self.native_installed_source()
        self.assertNotEqual(aliased, bound)
        self.assertIn('return "elem_scope";', aliased)
        original = current_native_scoped_original(aliased, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        self.assertEqual(original, bound)
        self.assertEqual(self.hook(original, units=LOCAL_COMPOSED_UNITS,
            sources=LOCAL_COMPOSED_SOURCES, installed=True), bound)
        with self.assertRaises(RuntimeError):
            self.hook(aliased, units=LOCAL_COMPOSED_UNITS, sources=LOCAL_COMPOSED_SOURCES, installed=True)
        for malformed in (bound, aliased.replace('return "elem_scope";', 'return "unknown_scope";'),
                          aliased.replace("case 13:return ouro_g121();", "case 13:return ouro_g41();"),
                          aliased.replace("case 0:return ouro_g51();", "case 0:return ouro_g31();")):
            with self.subTest(malformed=malformed[-250:]), self.assertRaises(RuntimeError):
                current_native_scoped_original(malformed, LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS,
                    LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        unbound_aliases = NATIVE.current_native_scoped_aliases(module_bound, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        projected = current_native_scoped_original(unbound_aliases, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES)
        installed = self.hook(projected, units=LOCAL_COMPOSED_UNITS, sources=LOCAL_COMPOSED_SOURCES)
        self.assertEqual(NATIVE.current_native_scoped_aliases(installed, LOCAL_COMPOSED_UNITS,
            LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_UNITS[-1], LOCAL_COMPOSED_SOURCES), aliased)
        closure = fixture_scope_closure(LOCAL_COMPOSED_UNITS, LOCAL_COMPOSED_SOURCES)
        units = list(LOCAL_COMPOSED_UNITS)
        with patch.object(NATIVE.frontend, "collect_units_many", side_effect=closure):
            emitted = NATIVE.hook_emission_scopes(composed_module_source(scopes=True, local=True), units)
            with (patch.object(PACKER, "_static_symbol_starts", wraps=_static_symbol_starts) as starts,
                  patch.object(PACKER, "_static_definition_family_counts", wraps=_static_definition_family_counts) as counts,
                  patch.object(exports, "_read_export_tables", wraps=_read_export_tables) as tables,
                  patch.object(exports, "_declarations", wraps=_declarations) as declarations,
                  patch.object(PACKER, "lex", wraps=PACKER.lex) as shape_lex):
                self.assertEqual(NATIVE.hook_emission_scopes(emitted, units, installed=True), emitted)
            starts.assert_called_once()
            counts.assert_called_once()
            self.assertEqual([call.args[0] for call in tables.call_args_list], [emitted, starts.call_args.args[0]])
            self.assertEqual(declarations.call_count, len({id(call.args[0]) for call in declarations.call_args_list}))
            owner_sources = set(LOCAL_COMPOSED_SOURCES.values())
            shaped = [call.args[0] for call in shape_lex.call_args_list if call.args[0] in owner_sources]
            self.assertTrue(shaped)
            self.assertEqual(len(shaped), len(set(shaped)))
            malformed = emitted.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))",
                                        "ouro_clos(ouro_f151_,env)")
            with self.assertRaises(RuntimeError):
                NATIVE.hook_emission_scopes(malformed, units, installed=True)

    def test_lookup_index_is_rebuilt_for_changed_c_text(self):
        _module_bound, original, _aliased = self.native_installed_source()
        units = LOCAL_COMPOSED_UNITS
        index = PACKER.StaticSymbolIndex(original)

        def verify(text):
            return PACKER.hook_lower_local_lookup(text, units, units, units[-1], LOCAL_COMPOSED_SOURCES,
                                                  installed=True, static_index=index)

        self.assertEqual(verify(original), original)
        shifted = "\n" + original
        self.assertEqual(verify(shifted), shifted)
        duplicate = "static ouro_v *ouro_f151__d2(ouro_env *env,ouro_v *arg){return arg;}\n"
        with self.assertRaisesRegex(RuntimeError, "^missing or duplicate lower local lookup curry family$"):
            verify(original + duplicate)

    def warm_native_record(self, repo, text):
        for unit, source in LOCAL_COMPOSED_SOURCES.items():
            target = repo / unit
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        for unit in NATIVE.RUNTIME:
            target = repo / unit
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / unit).read_bytes())
        cc = "SOURCE-cc"
        inputs = {"kind": NATIVE.KIND, "entry": LOCAL_COMPOSED_UNITS[-1], "fuel": 200000,
            "compiler_sha256": "1" * 64, "cc": NATIVE.json.dumps({"version": []}),
            "cc_sha256": "2" * 64, "platform": sys.platform, "machine": "SOURCE",
            "cflags": ["-O1"], "link_flags": [], "environment": {},
            "sources": {unit: NATIVE.sha256_file(repo / unit)
                        for unit in (*LOCAL_COMPOSED_UNITS, *NATIVE.RUNTIME)}}
        cfg = SimpleNamespace(get_bool=lambda _name: True, path=lambda _name: repo / "cache")
        directory = repo / "cache/tool"
        directory.mkdir(parents=True, exist_ok=True)
        generated = directory / "tool.gen.c"
        generated.write_bytes(text.encode("utf-8"))
        shard_sources, shards = NATIVE.build.GCS.materialize_generated_c_shards(
            frontend_c=None, backend_c=generated, out_dir=directory / "generated-c-shards",
            label_prefix="native-tool", backend_group_size=NATIVE.SHARD_GROUP_SIZE,
            backend_export_suffix="")
        flags = [*inputs["cflags"], *NATIVE.EXTRA_CFLAGS, "-I" + str(repo / "runtime")]
        object_dir = NATIVE.tool_object_dir(cfg, inputs, directory)
        object_dir.mkdir(parents=True, exist_ok=True)
        sources, objects = [], []
        for label, src in (*shard_sources, *((unit, repo / unit) for unit in NATIVE.RUNTIME)):
            flags_key = NATIVE.hash_json({"flags": flags, "target": "native-tool",
                "source": NATIVE.build.path_key(src), "label": label})
            obj = object_dir / NATIVE.build.safe_obj_name("native-tool", label, flags_key)
            dep, stamp = obj.with_suffix(".d"), obj.with_suffix(".cmdhash")
            obj.write_bytes((label + NATIVE.sha256_file(src)).encode())
            dep.write_text(str(obj) + ": " + str(src).replace(" ", "\\ ") + "\n", encoding="utf-8")
            command = [cc, *flags, "-MMD", "-MP", "-MF", str(dep), "-c",
                       NATIVE.build.path_key(src), "-o", str(obj)]
            NATIVE.write_json_atomic(stamp, {"kind": "ouro.c-object.v2", "target": "native-tool",
                "compiler_id": inputs["cc"], "command": command,
                "command_hash": NATIVE.build.command_hash(command, inputs["cc"]),
                "source": NATIVE.build.path_key(src),
                "dependencies": NATIVE.build.dep_digests_from_depfile(dep, src),
                "object_sha256": NATIVE.sha256_file(obj), "depfile_sha256": NATIVE.sha256_file(dep)})
            sources.append({"label": label, "source": NATIVE.build.path_key(src),
                "object": NATIVE.build.rel(obj), "depfile": NATIVE.build.rel(dep),
                "cmdhash": NATIVE.build.rel(stamp), "object_sha256": NATIVE.sha256_file(obj)})
            objects.append(obj)
        binary = directory / ("tool.exe" if NATIVE.os.name == "nt" else "tool")
        binary.write_bytes(b"SOURCE linked evidence\n")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        link_stamp = Path(str(binary) + ".cmdhash")
        command = [cc, *inputs["cflags"], *inputs["link_flags"], "-o", str(binary),
                   *(str(obj) for obj in objects)]
        NATIVE.write_json_atomic(link_stamp, {"kind": "ouro.c-link.v2", "target": "native-tool",
            "compiler_id": inputs["cc"], "command": command,
            "command_hash": NATIVE.build.command_hash(command, inputs["cc"]),
            "objects": {NATIVE.build.path_key(obj): NATIVE.sha256_file(obj) for obj in objects},
            "output_sha256": NATIVE.sha256_file(binary)})
        key = NATIVE.hash_json(inputs)
        record = {"kind": NATIVE.KIND, "key": key, "cache": "hit", "inputs": inputs,
            "binary_sha256": NATIVE.sha256_file(binary), "generated_sha256": NATIVE.sha256_file(generated),
            "shard_manifest_sha256": NATIVE.sha256_file(directory / "generated-c-shards/generated-c-shards.manifest.json"),
            "build": {"kind": "ouro.c-build-report.v2", "target": "native-tool", "cc": cc,
                "compiler_id": inputs["cc"], "generated_c_shards": shards, "sources": sources,
                "objects": [NATIVE.build.rel(obj) for obj in objects],
                "link": {"output": NATIVE.build.rel(binary), "cmdhash": NATIVE.build.rel(link_stamp),
                    "output_sha256": NATIVE.sha256_file(binary)}}}
        metadata = directory / "tool.json"
        NATIVE.write_json_atomic(metadata, record)
        return directory, cfg, inputs, record, binary, metadata, key

    def test_native_warm_gate_checks_semantics_with_consistent_artifact_evidence(self):
        _module_bound, _bound, aliased = self.native_installed_source()
        prototype = "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"
        cases = (
            ("valid", aliased, True),
            ("missing local wrapper", aliased.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))",
                                                      "ouro_clos(ouro_f151_,env)"), False),
            ("wrong local getter", aliased.replace("ouro_wrap_module_lookup(ouro_clos(ouro_f151_,env))",
                                                   "ouro_wrap_module_lookup(ouro_clos(ouro_f41_,env))"), False),
            ("missing prototype", aliased.replace(prototype, ""), False),
            ("wrong prototype", aliased.replace(prototype,
                                                "ouro_v *ouro_wrap_module_lookup(ouro_v *raw,int extra);\n"), False),
        )
        for name, text, valid in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary).resolve()
                def relative(path, _repo=repo):
                    return Path(path).relative_to(_repo).as_posix()
                with patch.object(NATIVE, "ROOT", repo), patch.object(NATIVE.build, "ROOT", repo), \
                        patch.object(NATIVE.build, "rel", relative), patch.object(NATIVE.build.GCS, "ROOT", repo), \
                        patch.object(NATIVE.build.GCS, "rel", relative), \
                        patch.object(NATIVE.build, "choose_cc", return_value="SOURCE-cc"), \
                        patch.object(NATIVE.frontend, "collect_units", return_value=list(LOCAL_COMPOSED_UNITS)):
                    directory, cfg, inputs, record, binary, metadata, key = self.warm_native_record(repo, text)
                    files = (directory / "tool.gen.c", binary, metadata)
                    previous = [path.read_bytes() for path in files]
                    with patch.object(NATIVE, "verify_generated_tool_source"):
                        self.assertTrue(NATIVE.build_artifacts_current(directory, cfg, inputs, record, binary))
                        self.assertIsNotNone(NATIVE.complete_tool(binary, metadata, key, directory, cfg, inputs))
                    self.assertEqual(NATIVE.build_artifacts_current(directory, cfg, inputs, record, binary), valid)
                    self.assertEqual(NATIVE.complete_tool(binary, metadata, key, directory, cfg, inputs) is not None, valid)
                    self.assertEqual([path.read_bytes() for path in files], previous)

    def test_native_warm_replay_rejects_changed_source_and_runtime_hashes(self):
        _module_bound, _bound, aliased = self.native_installed_source()
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            def relative(path):
                return Path(path).relative_to(repo).as_posix()
            with patch.object(NATIVE, "ROOT", repo), patch.object(NATIVE.build, "ROOT", repo), \
                    patch.object(NATIVE.build, "rel", relative), patch.object(NATIVE.build.GCS, "ROOT", repo), \
                    patch.object(NATIVE.build.GCS, "rel", relative), \
                    patch.object(NATIVE.frontend, "collect_units", return_value=list(LOCAL_COMPOSED_UNITS)):
                directory, _cfg, inputs, record, _binary, _metadata, _key = self.warm_native_record(repo, aliased)
                generated = directory / "tool.gen.c"
                expected_sources = record["build"]["generated_c_shards"]["sources"]
                NATIVE.verify_generated_tool_source(generated, inputs, expected_sources)
                with self.assertRaisesRegex(RuntimeError, "generated tool source digest changed"):
                    NATIVE.verify_generated_tool_source(generated, inputs, {})
                for owner in (PACKER.LOWER_LOCAL_LOOKUP_OWNER, "runtime/frontend_link.c"):
                    target = repo / owner
                    saved = target.read_bytes()
                    target.write_bytes(saved + b"\n")
                    with self.subTest(owner=owner), self.assertRaises(RuntimeError):
                        NATIVE.verify_generated_tool_source(generated, inputs, expected_sources)
                    target.write_bytes(saved)

    def test_native_warm_rechecks_each_c_stamp_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()

            def relative(path):
                return Path(path).relative_to(repo).as_posix()

            with patch.object(NATIVE, "ROOT", repo), patch.object(NATIVE.build, "ROOT", repo), \
                    patch.object(NATIVE.build, "rel", relative), patch.object(NATIVE.build.GCS, "ROOT", repo), \
                    patch.object(NATIVE.build.GCS, "rel", relative), \
                    patch.object(NATIVE.build, "choose_cc", return_value="SOURCE-cc"), \
                    patch.object(NATIVE.frontend, "collect_units", return_value=list(LOCAL_COMPOSED_UNITS)):
                directory, cfg, inputs, record, binary, metadata, key = self.warm_native_record(
                    repo, self.native_installed_source()[-1])
                stamps = [repo / row["cmdhash"] for row in (*record["build"]["sources"], record["build"]["link"])]
                shards = record["build"]["generated_c_shards"]
                manifest = repo / shards["manifest_path"]
                shard_paths = [repo / row["path"] for row in shards["shards"]]
                opened = []

                def open_path(path, *args, _open=Path.open, **kwargs):
                    if path == manifest or path in stamps:
                        opened.append(path)
                    return _open(path, *args, **kwargs)

                def current():
                    return NATIVE.complete_tool(binary, metadata, key, directory, cfg, inputs)

                with (patch.object(Path, "open", open_path),
                      patch.object(Path, "resolve", autospec=True, side_effect=Path.resolve) as resolves):
                    self.assertEqual(current(), record)
                    self.assertEqual(opened, [manifest, *stamps, manifest])
                resolved = [call.args[0] for call in resolves.call_args_list]
                self.assertEqual(resolved.count(manifest.parent), 0)
                self.assertLessEqual(set(shard_paths), set(resolved))

                def resolve_escaped_shard(path, *args, _resolve=Path.resolve, **kwargs):
                    return repo / "escaped.c" if path == shard_paths[0] else _resolve(path, *args, **kwargs)

                with (patch.object(Path, "resolve", autospec=True, side_effect=resolve_escaped_shard),
                      patch.object(NATIVE.build, "compile_stamp_digest", side_effect=AssertionError("escaped shard used"))):
                    self.assertIsNone(current())
                manifest_bytes = manifest.read_bytes()
                stamp_link = NATIVE.build.link_stamp_digest

                def change_manifest_after_link(*args, **kwargs):
                    result = stamp_link(*args, **kwargs)
                    self.assertIsNotNone(result[0])
                    manifest.write_bytes(manifest_bytes + b"\n")
                    return result

                with patch.object(NATIVE.build, "link_stamp_digest", side_effect=change_manifest_after_link):
                    self.assertIsNone(current())
                manifest.write_bytes(manifest_bytes)
                for stamp in (stamps[0], stamps[-1]):
                    saved = stamp.read_bytes()
                    stat_before = stamp.stat()
                    fields = json.loads(saved)
                    changes = {"target": "native-fake", "compiler_id": fields["compiler_id"].replace("version", "VERSION"),
                               "command": ["SOURCE-xx", *fields["command"][1:]]}
                    for field, value in changes.items():
                        with self.subTest(stamp=fields["kind"], field=field):
                            self.assertNotEqual(value, fields[field])
                            NATIVE.write_json_atomic(stamp, {**fields, field: value})
                            NATIVE.os.utime(stamp, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
                            self.assertEqual(stamp.stat().st_size, stat_before.st_size)
                            self.assertEqual(stamp.stat().st_mtime_ns, stat_before.st_mtime_ns)
                            self.assertIsNone(current())
                    stamp.write_bytes(saved)
                self.assertEqual(current(), record)

    def test_native_shard_manifest_preserves_exact_bytes_and_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shards.json"
            document = '{"label": "shard\u00e9"}'
            expected = {"label": "shard\u00e9"}
            raw = (document + "\r\n").encode("utf-8")
            oversized = raw + b" " * (1024 * 1024)
            for saved in (raw, oversized):
                with self.subTest(size=len(saved)):
                    path.write_bytes(saved)
                    self.assertEqual(NATIVE.read_current_shard_manifest(path, NATIVE.sha256_bytes(saved)), expected)
                    self.assertIsNone(NATIVE.read_current_shard_manifest(path, NATIVE.sha256_bytes(document.encode())))
            for invalid in (b"", b"[]", b"{", b"\xef\xbb\xbf" + raw, document.encode("utf-16")):
                with self.subTest(invalid=invalid):
                    path.write_bytes(invalid)
                    self.assertIsNone(NATIVE.read_current_shard_manifest(path, NATIVE.sha256_bytes(invalid)))


class LookupCtorSourceControls(unittest.TestCase):
    def test_raw_and_installed_contract(self):
        original = raw_source()
        transformed = PACKER.hook_lower_ctor_lookup(original, "_lo")
        self.assertIn("ouro_c31=ouro_wrap_lower_ctor_lookup(ouro_clos(ouro_f31_,env));", transformed)
        with patch.object(PACKER, "_base_ver", wraps=_base_ver) as families:
            self.assertEqual(PACKER.hook_lower_ctor_lookup(transformed, "_lo", installed=True), transformed)
        self.assertEqual([call.args[0] for call in families.call_args_list].count("ouro_f31_"), 1)
        with self.assertRaisesRegex(RuntimeError, "^missing, malformed or duplicate lower ctor lookup cache$"):
            PACKER.hook_lower_ctor_lookup(transformed + "nostatic ouro_v *ouro_c31;\n", "_lo", installed=True)
        self.assertEqual(PACKER.hook_lower_ctor_lookup(original, "_co"), original)
        with self.assertRaises(RuntimeError):
            PACKER.hook_lower_ctor_lookup(transformed, "_lo")
        with self.assertRaises(RuntimeError):
            PACKER.hook_lower_ctor_lookup(original, "_lo", installed=True)
        self.assertIn("ouro_lo_c31=ouro_wrap_lower_ctor_lookup(ouro_clos(ouro_lo_f31_,env));",
                      PACKER.prefix_blob(transformed, "lo"))
        malformed = (
            original.replace('"lookup_ctor"', '"other"'),
            original.replace("return 1;", "return 2;", 1),
            original.replace("case 0:return ouro_g31();", "case 1:return ouro_g31();"),
            original.replace("ouro_c31=ouro_clos(ouro_f31_,env);", "ouro_c31=ouro_nat(0);"),
            original.replace("return ouro_fix(ouro_f0_31_,env);", "return arg;"),
            original.replace("return ouro_ctor(0,0,0);", "return ouro_clos ( ouro_f0_0_31_ , env );"),
            original.replace("return ouro_ctor(0,0,0);", "return ouro_clos ( ouro_f0_0_31__d2 , env );"),
            original.replace("*ouro_f0_31_(", "*ouro_f0_31_ (", 1),
            original.replace("*ouro_f31_(", "*ouro_f31_ (", 1),
            original.replace("(void)env;return ouro_ctor", "(void)env; return ouro_ctor", 1),
            original.replace("static ouro_v *ouro_c31;", "static ouro_v * ouro_c31;"),
            original + "static ouro_v *ouro_g31_d2(void){return 0;}\n",
            original + "static ouro_v *ouro_f31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + "static ouro_v *ouro_f0_31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + "static ouro_v *ouro_f0_31_(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + 'const char *ouro_export_name_lo(int i){return "";}\n',
        )
        for source in malformed:
            with self.subTest(source=source[-140:]), self.assertRaises(RuntimeError):
                PACKER.hook_lower_ctor_lookup(source, "_lo")
        prototype = "ouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw);\n"
        for source in (
            transformed.replace(prototype, ""),
            transformed + prototype,
            transformed.replace("ouro_wrap_lower_ctor_lookup(ouro_clos(ouro_f31_,env))",
                                "ouro_wrap_lower_ctor_lookup(ouro_clos(ouro_f0_31_,env))"),
        ):
            with self.assertRaises(RuntimeError):
                PACKER.hook_lower_ctor_lookup(source, "_lo", installed=True)

    def setup_repo(self, repo, capable=True):
        for name in ("scripts/frontend_regen.py", "scripts/selfhost_module_cache.py",
                     "scripts/emit_frontend.sh", "scripts/pack_frontend.py", "scripts/compact_source.py",
                     *REGEN.PACKED_ALIAS_TOOLS):
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("SOURCE mock input\n", encoding="utf-8")
        for name in ("compiler/lower_env.ouro", "compiler/pipeline_abi.ouro", *PACKER.LOWER_LOCAL_LOOKUP_SOURCE_PATHS,
                     *PACKER.MODULE_LOOKUP_SOURCE_PATHS,
                     *PACKER.SOURCE_NAME_COMPARE_SOURCE_PATHS, *PACKER.ELEM_SOURCE_PATHS):
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        runtime = repo / "runtime/frontend_link.c"
        runtime.parent.mkdir(parents=True)
        if capable:
            shutil.copyfile(REPO / "runtime/frontend_link.c", runtime)
        else:
            runtime.write_text("#ifndef OURO_FE_FLAT_EXPORTS\n#endif\n", encoding="utf-8")
        graph = {}
        for _tag, _mod, root, _file in REGEN.FRONTEND_TUS:
            target = repo / root
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("-- SOURCE root fixture\n", encoding="utf-8")
            graph[root] = (["compiler/pipeline_abi.ouro", "compiler/lower_env.ouro", root]
                           if root == "compiler/lower.ouro" else [root])
        seed = repo / "seed.py"
        seed.write_text("# SOURCE seed identity\n", encoding="utf-8")
        return graph, seed

    def test_contracts_hash_the_bytes_used_by_shape_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = self.setup_repo(repo)
            runtime = repo / "runtime/frontend_link.c"
            helpers = ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py")
            contracts = (
                (REGEN.lower_ctor_lookup_contract, ("compiler/lower_env.ouro", "compiler/pipeline_abi.ouro")),
                (REGEN.module_lookup_contract, (*helpers, *PACKER.MODULE_LOOKUP_SOURCE_PATHS)),
                (REGEN.lower_local_lookup_contract, (*helpers, *PACKER.LOWER_LOCAL_LOOKUP_SOURCE_PATHS)),
                (REGEN.source_name_compare_contract, (*helpers, *PACKER.SOURCE_NAME_COMPARE_SOURCE_PATHS)),
                (REGEN.elem_scope_contract, (*helpers, *PACKER.ELEM_SOURCE_PATHS)),
            )
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph):
                _graph, inputs, _signature = REGEN.all_frontend_inputs(seed, "16000")
                opened = []
                original_open = Path.open

                def open_path(path, *args, **kwargs):
                    opened.append(path)
                    return original_open(path, *args, **kwargs)

                for contract, sources in contracts:
                    opened.clear()
                    with self.subTest(contract=contract.__name__), patch.object(Path, "open", open_path):
                        self.assertTrue(contract(inputs)["capability"])
                        self.assertEqual(opened, [runtime, *(repo / source for source in sources)])

                scoped_paths = [repo / source for _, sources in contracts[1:] for source in sources]
                owner_sources = {path.read_text(encoding="utf-8") for path in scoped_paths if path.suffix == ".ouro"}
                opened.clear()
                with (patch.object(Path, "open", open_path), patch.object(PACKER, "lex", wraps=PACKER.lex) as lex):
                    scope_contracts = _source_scope_contracts(inputs)
                self.assertTrue(all(contract["capability"] for contract in scope_contracts.values()))
                self.assertEqual(opened, [path for _, sources in contracts[1:] for path in
                                          (runtime, *(repo / source for source in sources))])
                owner_lexes = [call.args[0] for call in lex.call_args_list if call.args[0] in owner_sources]
                self.assertEqual(len(owner_lexes), len(owner_sources))
                self.assertEqual(set(owner_lexes), owner_sources)

                common = repo / "compiler/base.ouro"
                common_bytes = common.read_bytes()
                metadata = common.stat()
                read_bytes = Path.read_bytes

                def edit_after_first_source_read(path):
                    raw = read_bytes(path)
                    if path == common and raw == common_bytes:
                        common.write_bytes(b" " + raw[1:])
                        NATIVE.os.utime(common, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                    return raw

                with (patch.object(Path, "read_bytes", edit_after_first_source_read),
                      self.assertRaisesRegex(RuntimeError, "^lower local lookup source input changed or is missing: "
                                                           "compiler/base\\.ouro$")):
                    _source_scope_contracts(inputs)
                common.write_bytes(common_bytes)
                NATIVE.os.utime(common, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

                saved = runtime.stat()
                invalid = b"\xff" + runtime.read_bytes()[1:]
                read_bytes = Path.read_bytes

                def replace_after_read(path):
                    raw = read_bytes(path)
                    if path == runtime:
                        runtime.write_bytes(invalid)
                        NATIVE.os.utime(runtime, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                    return raw

                with patch.object(Path, "read_bytes", replace_after_read):
                    self.assertTrue(REGEN.module_lookup_contract(inputs)["capability"])
                with self.assertRaisesRegex(RuntimeError, "selected module lookup runtime input changed or is missing"):
                    REGEN.module_lookup_contract(inputs)
                current = {**inputs, "frontend_runtime": REGEN.digest(runtime)}
                with self.assertRaisesRegex(SystemExit, "frontend runtime: FAIL unreadable .*invalid start byte"):
                    REGEN.module_lookup_contract(current)

    def test_fresh_warm_and_capability_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = self.setup_repo(repo)
            work = repo / "work"
            work.mkdir()
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph), \
                    patch.object(REGEN, "lower_local_lookup_binding", return_value={"selected": False}), \
                    patch.object(REGEN, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]):
                _units, inputs, full = REGEN.all_frontend_inputs(seed, "16000")
                for name in ("compiler/lower_env.ouro", "compiler/pipeline_abi.ouro"):
                    target = repo / name
                    target.write_bytes(REGEN.compact_source.compact_source(target.read_bytes()))
                _units, inputs, compact_full = REGEN.all_frontend_inputs(seed, "16000")
                self.assertNotEqual(full, compact_full)
                self.assertTrue(REGEN.lower_ctor_lookup_contract(inputs)["capability"])
                closure = graph["compiler/lower.ouro"]
                binding = REGEN.lower_ctor_lookup_binding("lo", "_lo", "compiler/lower.ouro", closure, inputs)
                self.assertTrue(binding["selected"])
                calls = []

                def emit_mock(_command, **kwargs):
                    calls.append(_command)
                    kwargs["stdout"].write(raw_source().encode("utf-8"))
                    return SimpleNamespace(returncode=0)

                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="lo", mod="_lo", root="compiler/lower.ouro",
                               file_name="lo.c", units=closure, digests=inputs)
                with patch.object(REGEN.subprocess, "run", side_effect=emit_mock):
                    cold = REGEN.emit_one(**options)
                    warm = REGEN.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, len(calls)), ("miss", "hit", 1))
                    output = (work / "lo.c").read_text(encoding="utf-8")
                    self.assertEqual(PACKER.hook_lower_ctor_lookup(output, "_lo", installed=True), output)
                    key = cold.key
                    cache = repo / "cache" / ("_lo_" + key + ".c")
                    cache.write_text(raw_source(), encoding="utf-8")
                    REGEN.record_cached_output(cache, key)
                    with self.assertRaises(RuntimeError):
                        REGEN.emit_one(**options)
                pack = REGEN.pack_key([("lo", work / "lo.c")], inputs)
                for tag, mod, root in (("bad", "_lo", "compiler/lower.ouro"),
                                       ("lo", "_bad", "compiler/lower.ouro"),
                                       ("lo", "_lo", "compiler/elab.ouro")):
                    with self.assertRaises(RuntimeError):
                        REGEN.lower_ctor_lookup_binding(tag, mod, root, closure, inputs)
                for units in (closure[:-1], closure + [closure[0]],
                              ["compiler/lower_env.ouro", "compiler/lower.ouro"]):
                    with self.assertRaises(RuntimeError):
                        REGEN.lower_ctor_lookup_binding("lo", "_lo", "compiler/lower.ouro", units, inputs)
                (repo / "runtime/frontend_link.c").write_text("#ifndef OURO_FE_FLAT_EXPORTS\n#endif\n", encoding="utf-8")
                _units, old_inputs, old_full = REGEN.all_frontend_inputs(seed, "16000")
                self.assertFalse(REGEN.lower_ctor_lookup_contract(old_inputs)["capability"])
                self.assertNotEqual(full, old_full)
                self.assertNotEqual(key, REGEN.tu_key("lo", "_lo", "compiler/lower.ouro", closure, old_inputs, "16000"))
                self.assertNotEqual(pack, REGEN.pack_key([("lo", work / "lo.c")], old_inputs))
                options["digests"] = old_inputs
                with patch.object(REGEN.subprocess, "run", side_effect=emit_mock):
                    self.assertEqual(REGEN.emit_one(**options).cache, "miss")
                self.assertEqual((work / "lo.c").read_text(encoding="utf-8"), raw_source())

    def test_source_shapes_and_historical_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = self.setup_repo(repo)
            with patch.object(REGEN, "ROOT", repo), \
                    patch.object(REGEN, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(REGEN, "collect_units_many", return_value=graph):
                ctor = repo / "compiler/pipeline_abi.ouro"
                original = ctor.read_text(encoding="utf-8")
                ctor.write_text(original.replace("Nat -> Nat -> Nat -> Nat -> Nat -> Nat -> CtorInfo",
                                                 "Nat -> Nat -> Nat -> Nat -> Nat -> CtorInfo", 1), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    REGEN.all_frontend_inputs(seed, "16000")
                ctor.write_text(original, encoding="utf-8")
                lower = repo / "compiler/lower_env.ouro"
                lower.write_text(lower.read_text(encoding="utf-8").replace(
                    "MkCtorInfo n _ _ _ _ _ => n", "MkCtorInfo _ n _ _ _ _ => n", 1), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    REGEN.all_frontend_inputs(seed, "16000")
                (repo / "runtime/frontend_link.c").write_text("#ifndef OURO_FE_FLAT_EXPORTS\n#endif\n", encoding="utf-8")
                graph["compiler/lower.ouro"].remove("compiler/pipeline_abi.ouro")
                ctor.unlink()
                _units, inputs, _full = REGEN.all_frontend_inputs(seed, "16000")
                self.assertFalse(REGEN.lower_ctor_lookup_contract(inputs)["capability"])
                runtime = repo / "runtime/frontend_link.c"
                runtime.write_text(runtime.read_text(encoding="utf-8") +
                                   "\nouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw){return raw;}\n", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    REGEN.all_frontend_inputs(seed, "16000")

    def test_standalone_packer_keeps_lookup_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "lo.c"
            source.write_text(raw_source(), encoding="utf-8")
            result = subprocess.run([sys.executable, str(REPO / "scripts/pack_frontend.py"),
                                     "--uniquify-only", str(source)], capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(source.read_text(encoding="utf-8"), raw_source())
            with self.assertRaises(RuntimeError):
                PACKER.hook_lower_ctor_lookup(source.read_text(encoding="utf-8"), "_lo", installed=True)


class PureScopeSearchControls(unittest.TestCase):
    DEFINITIONS = (("module_members", 7), ("module_owned_exports", 2),
                   ("module_shadow_exports", 2), ("module_unique_exports", 1))
    OWNER = "compiler/module_registry_base.ouro"

    def scope_source(self, *, module="", gids=(31, 128, 225, 322)):
        rows = tuple((name, gid) for (name, _arity), gid in zip(self.DEFINITIONS, gids, strict=True))
        arities = {gid: arity for (_name, arity), gid in zip(self.DEFINITIONS, gids, strict=True)}
        return export_source(rows, module, arities=arities)

    def expected_scope(self, original, *, gids=(31, 128, 225, 322)):
        declaration = "ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity);\n"
        expected = original.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + declaration, 1)
        for (_name, arity), gid in zip(self.DEFINITIONS, gids, strict=True):
            for constructor in ("ouro_clos", "ouro_fix"):
                raw = f"{constructor}(ouro_f{gid}_,env)"
                expected = expected.replace(f"ouro_c{gid}={raw};",
                                            f"ouro_c{gid}=ouro_wrap_module_pure_scope({raw},{arity});", 1)
        return expected

    def test_exact_output_with_prefix_symbols_and_curry_constructors(self):
        gids = (0, 7, 71, 713)
        for module in ("", "_pl"):
            for constructor in ("ouro_clos", "ouro_fix"):
                with self.subTest(module=module, constructor=constructor):
                    original = self.scope_source(module=module, gids=gids).replace("ouro_clos(", constructor + "(")
                    original += "static ouro_v *ouro_c07;\nstatic ouro_v *ouro_c7_extra;\n"
                    original += "static ouro_v *ouro_f7_extra(ouro_v *arg){return arg;}\n"
                    result = PACKER.hook_module_pure_scopes(original, (self.OWNER,), module)
                    self.assertEqual(result, self.expected_scope(original, gids=gids))
                    self.assertEqual(PACKER.hook_module_pure_scopes(
                        result, (self.OWNER,), module, installed=True), result)
                    self.assertEqual(PACKER.hook_module_pure_scopes(
                        original, ("tools/unrelated.ouro",), module), original)

    def test_prefix_wrapper_keeps_exact_body_and_offsets(self):
        original = export_source((("module_invalid_maps", 71),), "_pl", arities={71: 3})
        prototype = "ouro_v *ouro_wrap_module_invalid_maps_scope(ouro_v *raw);\n"
        expected = original.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + prototype, 1)
        expected = expected.replace("ouro_c71=ouro_clos(ouro_f71_,env);",
                                    "ouro_c71=ouro_wrap_module_invalid_maps_scope(ouro_clos(ouro_f71_,env));", 1)
        result = PACKER.hook_module_pure_scopes(original, ("compiler/module_names_base.ouro",), "_pl")
        self.assertEqual(result, expected)
        self.assertEqual(PACKER.hook_module_pure_scopes(
            result, ("compiler/module_names_base.ouro",), "_pl", installed=True), result)

    def test_overlapping_declaration_search_keeps_cardinality(self):
        # This checks installer regex cardinality, not C compiler acceptance.
        header = "static ouro_v *ouro_f31_(ouro_env *env0,ouro_v *arg){"
        original = self.scope_source().replace(header, "static ouro_v *ouro_f31_( " + header, 1)
        result = PACKER.hook_module_pure_scopes(original, (self.OWNER,))
        self.assertEqual(result, self.expected_scope(original))
        self.assertEqual(PACKER.hook_module_pure_scopes(result, (self.OWNER,), installed=True), result)

    def test_export_declaration_candidates_keep_boundaries_and_error_order(self):
        for module in ("", "_pl"):
            original = self.scope_source(module=module)
            installed = PACKER.hook_module_pure_scopes(original, (self.OWNER,), module)
            for kind, args in (("count", "void"), ("name", "int\ti"), ("value", "int\ti")):
                declaration = f"ouro_export_{kind}{module}\t({args})\n{{"
                decoys = "".join(prefix + declaration + "\n" for prefix in ("x", "_", "\u00e9", "\U00010400"))
                for text, verifying in ((original, False), (installed, True)):
                    with self.subTest(module=module, kind=kind, installed=verifying):
                        self.assertEqual(PACKER.hook_module_pure_scopes(
                            text + decoys, (self.OWNER,), module, installed=verifying), installed + decoys)
                        tampered = text + "/* \u0301" + declaration + " */\nstatic ouro_v *ouro_c31;\n"
                        with self.assertRaisesRegex(
                                RuntimeError, f"^missing, malformed or duplicate module pure scope {kind} declaration$"):
                            PACKER.hook_module_pure_scopes(tampered, (self.OWNER,), module, installed=verifying)

    def test_mutated_static_regions_preserve_error_order_and_text(self):
        original = self.scope_source()
        installed = PACKER.hook_module_pure_scopes(original, (self.OWNER,))
        curry_header = "static ouro_v *ouro_f31_(ouro_env *env0,ouro_v *arg){"
        partial = curry_header + "ouro_env *env=ouro_cons(arg,env0);(void)env;return ouro_clos(ouro_f0_31_,env);}\n"
        terminal = "static ouro_v *ouro_f0_0_0_0_0_0_31_(ouro_env *env0,ouro_v *arg){"
        getter = ("static ouro_v *ouro_g31(void){ouro_env *env=0;(void)env;"
                  "if(ouro_c31==0){ouro_static_begin();ouro_c31=ouro_clos(ouro_f31_,env);"
                  "ouro_static_end();}return ouro_c31;}\n")
        for text, verifying in ((original, False), (installed, True)):
            embedded_getter = getter if not verifying else getter.replace(
                "ouro_c31=ouro_clos(ouro_f31_,env);",
                "ouro_c31=ouro_wrap_module_pure_scope(ouro_clos(ouro_f31_,env),7);")
            cases = (
                (text + "static\r\nouro_v\t* \touro_c31;\n", "module_members cache declaration"),
                (text + "/* static ouro_v *ouro_c31; */\n", "module_members cache declaration"),
                (text + "xstatic ouro_v *ouro_c31;\n", "module_members cache"),
                (text + "static ouro_v *decoy_static ouro_v *ouro_c31;\n", "module_members cache"),
                (text + "static\touro_v *ouro_g31(void){return 0;}\n", "module_members getter declaration"),
                (text + "x" + embedded_getter, "module_members getter"),
                (text.replace("ouro_static_begin();ouro_c31=", "ouro_static_begin();ouro_c31=0;ouro_c31=", 1),
                 "module_members getter"),
                (text.replace(curry_header, curry_header.replace("static ", "static\t", 1), 1),
                 "module_members curry header 1"),
                (text.replace(curry_header, curry_header.replace("ouro_v *arg", "void"), 1),
                 "module_members curry header 1"),
                (text.replace(curry_header, curry_header.replace("ouro_f31_", "ouro_f31__"), 1),
                 "module_members curry declaration 1"),
                (text + "x" + partial, "module_members curry header 1"),
                (text.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;", 1),
                 "module_members curry step 1"),
            )
            for changed, label in cases:
                with self.subTest(installed=verifying, label=label):
                    with self.assertRaises(RuntimeError) as rejected:
                        PACKER.hook_module_pure_scopes(changed, (self.OWNER,), installed=verifying)
                    self.assertEqual(str(rejected.exception),
                                     "missing, malformed or duplicate module pure scope " + label)
            changed = text.replace(terminal + "ouro_env *env=ouro_cons(arg,env0);(void)env;return arg;}",
                                   terminal + "ouro_env *env=ouro_cons(arg,env0);(void)env;"
                                   "return ouro_clos(ouro_f0_0_0_0_0_0_0_31_,env);}", 1)
            self.assertNotEqual(changed, text)
            with self.assertRaises(RuntimeError) as rejected:
                PACKER.hook_module_pure_scopes(changed, (self.OWNER,), installed=verifying)
            self.assertEqual(str(rejected.exception), "extra module pure scope curry parameter module_members")


if __name__ == "__main__":
    unittest.main()
