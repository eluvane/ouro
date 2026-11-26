#!/usr/bin/env python3
from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import shutil
import os
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import frontend_regen as regen
import frontend_lower_lookup_test as lookup_controls
import native_tool_build as native
import pack_frontend as packer
from scoped_host_exports_test import source as export_source

ROOT = Path(__file__).resolve().parents[1]
UNITS = (*packer.PRELUDE_ARITHMETIC_SOURCE_PATHS, "tools/entry.ouro")
SOURCES = {name: (ROOT / name).read_text(encoding="utf-8") for name in UNITS[:-1]}
SOURCES[UNITS[-1]] = 'import "../std/prelude.ouro";\nprivate def trigger : Nat := Z;\n'
COMPARE_UNITS = (*UNITS[:-1], packer.NAT_COMPARE_OWNER, UNITS[-1])
COMPARE_SOURCES = {**SOURCES, packer.NAT_COMPARE_OWNER:
                   (ROOT / packer.NAT_COMPARE_OWNER).read_text(encoding="utf-8")}
COMPARE_SOURCES[UNITS[-1]] = 'import "../std/data.ouro";\nprivate def trigger : Nat := Z;\n'
EQUALITY_UNITS = (*COMPARE_UNITS[:-1], packer.NAT_EQUALITY_OWNER, UNITS[-1])
EQUALITY_SOURCES = {**COMPARE_SOURCES, packer.NAT_EQUALITY_OWNER:
                    (ROOT / packer.NAT_EQUALITY_OWNER).read_text(encoding="utf-8")}
EQUALITY_SOURCES[UNITS[-1]] = 'import "../compiler/base.ouro";\nprivate def trigger : Nat := Z;\n'


append_helpers = lookup_controls.append_helpers
elem_helpers = lookup_controls.elem_helpers


def arithmetic_source(module="", *, qualified=True, offset=0, fast=False, shadow=False,
                      comparison=False, equality=False, elem_scoped=False):
    bindings = [("add", 31), ("mul", 41)]
    if comparison or equality:
        bindings.append(("compareNat", 71))
    if equality:
        bindings.append(("eqNat", 91))
    bindings.append(("length", 131))
    bindings.append(("append", 171))
    bindings.append(("sub", 241))
    owners = {"add": 1, "mul": 1, "sub": 1, "length": 1, "append": 1, "compareNat": 2, "eqNat": 3}
    if comparison or equality:
        bindings.extend((("elem", 201), ("orb", 211)))
        owners.update(elem=2, orb=1)
    rows = [(f"_ouro_m_{owners[name]}_{name}" if qualified else name, gid + offset)
            for name, gid in bindings]
    if shadow:
        rows.append(("eqNat", 101 + offset) if equality else
                    ("compareNat", 81 + offset) if comparison else ("add", 51 + offset))
    text = export_source(rows, module, arities={gid: 1 if name.endswith("length") else 3 if name.endswith("elem") else 2
                                              for name, gid in rows})
    if comparison or equality:
        elem_gid = 201 + offset
        text = re.sub(rf"^static ouro_v \*ouro_f(?:0_){{0,2}}{elem_gid}_\([^\n]*\n", "", text,
                      flags=re.MULTILINE)
        text = text.replace(f"static ouro_v *ouro_c{elem_gid};",
                            elem_helpers(elem_gid, 211 + offset) + f"static ouro_v *ouro_c{elem_gid};", 1)
        if elem_scoped:
            text = text.replace(f"ouro_c{elem_gid}=ouro_clos(ouro_f{elem_gid}_,env)",
                                f"ouro_c{elem_gid}=ouro_wrap_elem_scope(ouro_clos(ouro_f{elem_gid}_,env))", 1)
            text = text.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n'
                                + "ouro_v *ouro_wrap_elem_scope(ouro_v *raw);\n", 1)
    gid = 171 + offset
    text = re.sub(rf"^static ouro_v \*ouro_f(?:0_)?{gid}_\([^\n]*\n", "", text,
                  flags=re.MULTILINE)
    text = text.replace(f"static ouro_v *ouro_c{gid};",
                        append_helpers(gid) + f"static ouro_v *ouro_c{gid};", 1)
    text = text.replace(f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);",
                        f"ouro_c{gid}=ouro_fix(ouro_f{gid}_,env);", 1)
    if fast:
        for name, unshifted in bindings:
            if name in ("elem", "orb"):
                continue
            gid = unshifted + offset
            initializer = "fix" if name == "append" else "clos"
            start = (f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                     f"if(ouro_c{gid}==0){{ouro_static_begin();ouro_c{gid}=ouro_{initializer}(ouro_f{gid}_,env);"
                     f"ouro_static_end();}}return ouro_c{gid};}}")
            text = text.replace(start, f'static ouro_v *ouro_g{gid}(void){{if(ouro_c{gid}==0)'
                                f'ouro_c{gid}=ouro_fast("{name}");return ouro_c{gid};}}', 1)
            text = re.sub(rf"^static ouro_v \*ouro_[ft](?:[0-9]+_)*{gid}_\([^\n]*\n", "", text,
                          flags=re.MULTILINE)
    return text


def hook(text, *, module="", sources=None, units=UNITS, canonical=UNITS, installed=False):
    return packer.hook_prelude_arithmetic(text, units, canonical, canonical[-1],
                                         SOURCES if sources is None else sources,
                                         module, installed=installed)


def comparison_hook(text, *, module="", sources=None, units=COMPARE_UNITS,
                    canonical=COMPARE_UNITS, installed=False):
    return hook(text, module=module, sources=COMPARE_SOURCES if sources is None else sources,
                units=units, canonical=canonical, installed=installed)


def equality_hook(text, *, module="", sources=None, units=EQUALITY_UNITS,
                  canonical=EQUALITY_UNITS, installed=False):
    return hook(text, module=module, sources=EQUALITY_SOURCES if sources is None else sources,
                units=units, canonical=canonical, installed=installed)


class PreludeArithmeticControls(unittest.TestCase):
    def test_source_contract_lexes_each_owner_once(self):
        sources = dict(EQUALITY_SOURCES)
        owners = packer.prelude_arithmetic_source_paths(EQUALITY_UNITS)
        token_cache = {}
        with patch.object(packer, "lex", wraps=packer.lex) as lex:
            packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)
            packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)
        for owner in owners:
            with self.subTest(owner=owner):
                self.assertEqual(sum(call.args[0] is sources[owner] for call in lex.call_args_list), 1)
        owner = packer.PRELUDE_ARITHMETIC_OWNER
        original = sources[owner]
        sources[owner] = original.replace("| Z => m", "| Z => Z", 1)
        self.assertEqual(len(original), len(sources[owner]))
        with self.assertRaisesRegex(RuntimeError, r"prelude arithmetic source shape changed: std/prelude\.ouro:add"):
            packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)
        sources[owner] = original + '\n"'
        with self.assertRaisesRegex(RuntimeError, r"^unsupported prelude arithmetic source std/prelude\.ouro$"):
            packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)
        sources[owner] = original
        packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)

    def test_source_contract_keeps_cross_kind_ambiguity(self):
        owner = packer.PRELUDE_ARITHMETIC_OWNER
        duplicate = SOURCES[owner] + "\naxiom add : Nat;\n"
        with self.assertRaisesRegex(RuntimeError, "^missing or duplicate prelude arithmetic source declaration add$"):
            packer.prelude_arithmetic_source_contract({**SOURCES, owner: duplicate})

    def test_canonical_getters_only_and_installed_readback(self):
        for module, qualified, offset in (("", True, 0), ("_pl", True, 72), ("_pa", False, 19)):
            with self.subTest(module=module):
                raw = arithmetic_source(module, qualified=qualified, offset=offset)
                transformed = hook(raw, module=module)
                self.assertEqual(transformed, arithmetic_source(module, qualified=qualified,
                                                                offset=offset, fast=True))
                self.assertEqual(hook(transformed, module=module, installed=True), transformed)
                self.assertEqual(hook(transformed, module=module), transformed)
                with self.assertRaises(RuntimeError):
                    hook(raw, module=module, installed=True)

    def test_helper_family_uses_final_getter_number_and_rejects_versions(self):
        unrelated = ("static ouro_v *ouro_f31_9001__d2(void){return 0;}\n"
                     "static ouro_v *ouro_t0_031_(void){return 0;}\n")
        raw = arithmetic_source() + unrelated
        installed = arithmetic_source(fast=True) + unrelated
        self.assertEqual(hook(raw), installed)
        self.assertEqual(hook(installed, installed=True), installed)

        duplicate = "static ouro_v *ouro_f0_31__d2(void){return 0;}\n"
        with self.assertRaisesRegex(RuntimeError, "^missing or duplicate canonical Nat/List fast value curry family$"):
            hook(raw + duplicate)
        with self.assertRaisesRegex(RuntimeError, "^noncanonical installed canonical Nat/List fast value getter add$"):
            hook(installed + duplicate, installed=True)

    def test_source_bodies_layouts_imports_and_opaque_literals(self):
        changes = (
            ("std/types.ouro", "| S : Nat -> Nat", "| S : Nat -> Nat -> Nat"),
            ("std/types.ouro", 'representation Nat := "ouro.nat"', 'representation Nat := "ouro.bool"'),
            ("std/prelude.ouro", "| Z => m", "| Z => Z"),
            ("std/prelude.ouro", "add(m, mul n' m)", "add(n', mul n' m)"),
            ("std/prelude.ouro", 'import "types.ouro";', 'import "other.ouro";'),
            ("std/prelude.ouro", "def add", "private def add"),
        )
        for owner, old, new in changes:
            self.assertIn(old, SOURCES[owner])
            with self.subTest(change=new), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: SOURCES[owner].replace(old, new, 1)})
        for owner, _kind, name, expected in packer.PRELUDE_ARITHMETIC_SOURCE_SHAPES:
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: SOURCES[owner] + expected})
        for owner in UNITS[:-1]:
            with self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={name: body for name, body in SOURCES.items() if name != owner})
        trivia = SOURCES["std/prelude.ouro"] + '\ndef text : String := "def add : Nat := Z;";\n'
        self.assertEqual(hook(arithmetic_source(), sources={**SOURCES, "std/prelude.ouro": trivia}),
                         hook(arithmetic_source()))

    def test_historical_fast_and_current_raw_emission_converge(self):
        raw = arithmetic_source()
        nested = ("static ouro_v *ouro_t1_0_31_(ouro_env *env,ouro_v *arg){"
                  "(void)arg;return ouro_get(env,0);}\n")
        raw = raw.replace("static ouro_v *ouro_c31;", nested + "static ouro_v *ouro_c31;")
        historical = arithmetic_source(fast=True)
        self.assertEqual(hook(raw), historical)
        self.assertEqual(hook(historical), historical)
        for text in (
            raw + "ouro_v *other(void){return ouro_f31_(0,0);}\n",
            raw + "ouro_v *other(void){return ouro_t1_0_31_(0,0);}\n",
            raw.replace(nested, nested + nested),
            raw.replace(nested, nested.replace("{", "{\n", 1)),
            raw.replace(nested, nested.rstrip("\n")
                        + "static ouro_v *sentinel(void){return ouro_nat(9);}\n"),
        ):
            with self.subTest(text=text[-100:]), self.assertRaises(RuntimeError):
                hook(text)
        fast_with_helpers = raw
        for name, gid in (("add", 31), ("mul", 41)):
            start = (f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                     f"if(ouro_c{gid}==0){{ouro_static_begin();ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);"
                     f"ouro_static_end();}}return ouro_c{gid};}}")
            fast_with_helpers = fast_with_helpers.replace(
                start, f'static ouro_v *ouro_g{gid}(void){{if(ouro_c{gid}==0)'
                f'ouro_c{gid}=ouro_fast("{name}");return ouro_c{gid};}}', 1)
        self.assertEqual(hook(fast_with_helpers), historical)
        with self.assertRaises(RuntimeError):
            hook(fast_with_helpers, installed=True)
        bodies = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]]
                  + "def ouro_f31_ : Nat := Z;\n"}
        user = export_source((("ouro_f31_", 61),)).split("int ouro_export_count", 1)[0]
        text = raw.replace("return 5;", "return 6;", 1)
        text = text.replace('case 3:return "_ouro_m_1_append";',
                            'case 3:return "_ouro_m_1_append";case 5:return "ouro_f31_";')
        text = text.replace("case 3:return ouro_g171();", "case 3:return ouro_g171();case 5:return ouro_g61();")
        text = text.replace('int ouro_export_count', user + 'int ouro_export_count', 1)
        text += "/* ouro_f31_ */\n// ouro_f0_41_\n"
        transformed = hook(text, sources=bodies)
        self.assertIn('case 5:return "ouro_f31_";', transformed)
        self.assertIn("ouro_c61=ouro_clos(ouro_f61_,env)", transformed)

    def test_wrong_owners_cache_aliases_and_curry_drift(self):
        raw = arithmetic_source()
        invalid = (
            raw.replace('"_ouro_m_1_add"', '"_ouro_m_0_add"'),
            raw.replace('"_ouro_m_1_mul"', '"_ouro_m_01_mul"'),
            raw.replace("case 1:return ouro_g41();", "case 1:return ouro_g31();"),
            raw.replace("ouro_c31=ouro_clos", "ouro_c31=ouro_nat(0);ouro_c31=ouro_clos"),
            raw.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;"),
            raw.replace("return arg;}", "return ouro_clos(ouro_f0_0_31_,env);}", 1),
            raw + "static ouro_v *ouro_g31_d2(void){return ouro_c31;}\n",
            raw + "static ouro_v *ouro_c41_d2;\n",
            raw + "static ouro_v *ouro_f0_31__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
        )
        for text in invalid:
            with self.subTest(text=text[-90:]), self.assertRaises(RuntimeError):
                hook(text)
        for units in (UNITS[::-1], UNITS + UNITS[:1], UNITS[1:]):
            with self.assertRaises(RuntimeError):
                hook(raw, units=units)
        fast = arithmetic_source(fast=True)
        for text in (fast.replace('ouro_fast("add")', 'ouro_fast("mul")', 1),
                     fast + '\nouro_v *unbound(void){return ouro_fast("add");}\n',
                     fast + '\nouro_v *unbound(void){return ouro_fast ( "mul" );}\n'):
            with self.assertRaises(RuntimeError):
                hook(text, installed=True)

    def test_user_homonym_stays_raw_and_unbound_fast_is_rejected(self):
        bodies = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]] + "def add : Nat -> Nat -> Nat := fun n m => Z;\n"}
        raw = arithmetic_source(shadow=True)
        transformed = hook(raw, sources=bodies)
        self.assertEqual(transformed, arithmetic_source(fast=True, shadow=True))
        self.assertIn("ouro_c51=ouro_clos(ouro_f51_,env)", transformed)
        with self.assertRaises(RuntimeError):
            hook(arithmetic_source(qualified=False), sources=bodies)
        with self.assertRaises(RuntimeError):
            hook(raw + '\nouro_v *unbound(void){return ouro_fast("add");}\n', sources=bodies)
        units, sources = (UNITS[-1],), {UNITS[-1]: bodies[UNITS[-1]]}
        plain = export_source((("add", 51),), arities={51: 2})
        self.assertEqual(hook(plain, units=units, canonical=units, sources=sources), plain)
        for call in ('ouro_fast("add")', 'ouro_fast \n( "mul"\n )'):
            with self.assertRaises(RuntimeError):
                hook(plain + '\nouro_v *unbound(void){return ' + call + ';}\n',
                     units=units, canonical=units, sources=sources)

    def test_regen_cache_requires_bound_arithmetic_and_tracks_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
            root, module = "compiler/parse_a.ouro", "_pa"
            units = [*UNITS[:-1], root]
            for name in UNITS[:-1]:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (repo / root).write_text(SOURCES[UNITS[-1]], encoding="utf-8")
            graph[root] = units
            work = repo / "work"
            work.mkdir()
            calls = []

            def emit_mock(command, **kwargs):
                calls.append(command)
                self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                self.assertIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"]["WSLENV"].split(":"))
                kwargs["stdout"].write(arithmetic_source(module).encode())
                return SimpleNamespace(returncode=0)

            with ExitStack() as stack:
                for name, value in (("ROOT", repo), ("rel", lambda path: path.relative_to(repo).as_posix()),
                                    ("collect_units_many", lambda _roots, **_options: graph),
                                    ("collect_units", lambda selected: graph[selected]),
                                    ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                    stack.enter_context(patch.object(regen, name, value))
                _graph, inputs, signature = regen.all_frontend_inputs(seed, "16000")
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=units, digests=inputs)
                stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                self.assertEqual((cold.cache, warm.cache, len(calls)), ("miss", "hit", 1))
                cache = repo / "cache" / (module + "_" + cold.key + ".c")
                cache.write_text(arithmetic_source(module), encoding="utf-8")
                regen.record_cached_output(cache, cold.key)
                previous = (work / "pa.c").read_bytes()
                with self.assertRaises(RuntimeError):
                    regen.emit_one(**options)
                self.assertEqual((work / "pa.c").read_bytes(), previous)
                for helper in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
                    path = repo / helper
                    original = path.read_bytes()
                    path.write_bytes(original + b"changed helper\n")
                    with self.assertRaises(RuntimeError):
                        regen.tu_key("pa", module, root, units, inputs, "16000")
                    _graph, changed, new_signature = regen.all_frontend_inputs(seed, "16000")
                    self.assertNotEqual(signature, new_signature)
                    self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, changed, "16000"))
                    path.write_bytes(original)

    def test_flat_emit_binds_before_aliases_and_never_publishes_a_failed_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for name, body in SOURCES.items():
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            target = repo / "runtime/frontend_link.c"
            target.parent.mkdir(parents=True)
            target.write_text("", encoding="utf-8")
            output = repo / "program.c"
            output.write_text("previous output\n", encoding="utf-8")

            def run_mock(_command, **kwargs):
                if "stdout" in kwargs:
                    self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                    kwargs["stdout"].write(arithmetic_source().encode())
                return SimpleNamespace(returncode=0)

            def aliases(text, *_args, **_kwargs):
                self.assertEqual(text, arithmetic_source(fast=True))
                return text

            with patch.object(native, "ROOT", repo), \
                    patch.object(native.frontend, "ROOT", repo), \
                    patch.object(native.frontend, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]), \
                    patch.object(native.subprocess, "run", side_effect=run_mock), \
                    patch.object(native, "current_native_scoped_aliases", side_effect=aliases):
                native.emit(Path("SOURCE-seed"), list(UNITS), 200000, output)
                self.assertEqual(output.read_text(encoding="utf-8"), arithmetic_source(fast=True))
                previous = output.read_bytes()
                (repo / "std/prelude.ouro").write_text(SOURCES["std/prelude.ouro"].replace("| Z => m", "| Z => Z"),
                                                      encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    native.emit(Path("SOURCE-seed"), list(UNITS), 200000, output)
                self.assertEqual(output.read_bytes(), previous)

    def test_historical_bridge_mode_is_explicit_and_has_separate_cache_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
            root, module = "compiler/parse_a.ouro", "_pa"
            units = [*UNITS[:-1], root]
            for name in UNITS[:-1]:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            graph[root] = units
            with patch.object(regen, "ROOT", repo), \
                    patch.object(regen, "rel", lambda path: path.relative_to(repo).as_posix()), \
                    patch.object(regen, "collect_units_many", return_value=graph), \
                    patch.object(regen, "collect_units", side_effect=lambda name: graph[name]):
                _graph, inputs, current = regen.all_frontend_inputs(seed, "16000")
                _graph, bridge_inputs, legacy = regen.all_frontend_inputs(seed, "16000", historical_bridge=True)
                self.assertEqual(inputs, bridge_inputs)
                self.assertNotEqual(current, legacy)
                self.assertNotEqual(regen.tu_key("pa", module, root, units, inputs, "16000"),
                                    regen.tu_key("pa", module, root, units, inputs, "16000", historical_bridge=True))
                units.remove("std/types.ouro")
                (repo / "std/types.ouro").unlink()
                _graph, legacy_inputs, _legacy = regen.all_frontend_inputs(seed, "16000", historical_bridge=True)
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, legacy_inputs, "16000")
                work = repo / "work"
                work.mkdir()
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=units, digests=legacy_inputs, historical_bridge=True)

                def emit_mock(_command, **kwargs):
                    self.assertNotIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"])
                    kwargs["stdout"].write(arithmetic_source(module, qualified=False, fast=True).encode())
                    return SimpleNamespace(returncode=0)

                with patch.dict(os.environ, {"OURO_EMIT_SCOPED_ARITHMETIC": "1"}), \
                        patch.object(regen, "ouro1_cmd", return_value=["SOURCE-mocked-historical-compiler"]), \
                        patch.object(regen.subprocess, "run", side_effect=emit_mock) as calls:
                    cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))


    def test_historical_bridge_streams_export_check_and_preserves_emitted_bytes(self):
        marker = b"ouro_export_count_pa"
        payload = b"a" * (256 * 1024 - 5) + marker + b"\r\n\xff\x00"
        expected = payload

        def emit_mock(_command, **kwargs):
            kwargs["stdout"].write(payload)
            return SimpleNamespace(returncode=0)

        read_bytes = Path.read_bytes

        def read_without_tu_copy(path):
            self.assertFalse(path.name.startswith("pa.c.tmp."))
            return read_bytes(path)

        class BrokenTail(BytesIO):
            def readinto(self, view):
                if self.tell():
                    raise OSError("injected trailing read failure")
                return super().readinto(view)

        open_path = Path.open

        def open_with_broken_tail(path, mode="r", *args, **kwargs):
            if mode == "rb" and path.name.startswith("pa.c.tmp."):
                return BrokenTail(payload)
            return open_path(path, mode, *args, **kwargs)

        disabled = {"selected": False}
        bindings = dict.fromkeys(("module_lookup", "lower_local_lookup", "source_name_compare_scope",
                                  "elem_scope", "prelude_arithmetic"), disabled)
        with (tempfile.TemporaryDirectory() as temporary,
              patch.object(regen, "_tu_scope_bindings", return_value=bindings),
              patch.object(regen, "_tu_key_inputs", return_value={"lower_ctor_lookup": disabled}),
              patch.object(regen, "ouro1_cmd", return_value=["SOURCE-mocked-historical-compiler"]),
              patch.object(regen.subprocess, "run", side_effect=emit_mock),
              patch.object(Path, "read_bytes", autospec=True, side_effect=read_without_tu_copy)):
            work = Path(temporary)
            root = "compiler/parse_a.ouro"
            options = dict(ouro1=work / "seed", fuel="16000", work=work, cache_enabled=False,
                           tu_cache=work / "cache", tag="pa", mod="_pa", root=root, file_name="pa.c",
                           units=[root], digests={}, historical_bridge=True)
            self.assertEqual(regen.emit_one(**options).cache, "miss")
            output = work / "pa.c"
            self.assertEqual(output.read_bytes(), expected)

            payload = b"a" * (256 * 1024) + marker[:-1]
            with self.assertRaisesRegex(RuntimeError, r"module=_pa missing export table _pa$"):
                regen.emit_one(**options)
            self.assertEqual(output.read_bytes(), expected)

            payload = marker
            with (patch.object(Path, "open", autospec=True, side_effect=open_with_broken_tail),
                  self.assertRaisesRegex(OSError, "^injected trailing read failure$")):
                regen.emit_one(**options)
            self.assertEqual(output.read_bytes(), expected)


class CanonicalNatSubControls(unittest.TestCase):
    def test_sub_binary_curry_and_exact_installed_readback(self):
        for module, qualified, offset in (("", True, 0), ("_pl", True, 37), ("_pa", False, 19)):
            with self.subTest(module=module):
                raw = arithmetic_source(module, qualified=qualified, offset=offset)
                fast = arithmetic_source(module, qualified=qualified, offset=offset, fast=True)
                self.assertEqual(hook(raw, module=module), fast)
                self.assertEqual(hook(fast, module=module, installed=True), fast)
                gid = 241 + offset
                self.assertIn(f'ouro_c{gid}=ouro_fast("sub")', fast)
                self.assertNotIn(f"ouro_f{gid}_", fast)
                self.assertEqual(hook(raw.replace(f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env)",
                                                 f"ouro_c{gid}=ouro_fix(ouro_f{gid}_,env)"), module=module), fast)
                with self.assertRaises(RuntimeError):
                    hook(raw, module=module, installed=True)

    def test_sub_complete_typed_source_layout_and_import_guards(self):
        expected = next(shape for _owner, kind, name, shape in packer.PRELUDE_ARITHMETIC_SOURCE_SHAPES
                        if kind == "def" and name == "sub")
        self.assertIn(expected.strip(), SOURCES["std/prelude.ouro"])
        changes = (("def sub : Nat -> Nat -> Nat", "private def sub : Nat -> Nat -> Nat"),
                   ("Nat -> Nat -> Nat", "Nat -> Nat"),
                   ("(m : Nat)", "(m : Nat) (extra : Nat)"),
                   ("| Z => n", "| Z => Z"),
                   ("sub n' m'", "sub m' n'"))
        for old, new in changes:
            self.assertIn(old, expected)
            changed = expected.replace(old, new, 1)
            source = SOURCES["std/prelude.ouro"].replace(expected.strip(), changed.strip(), 1)
            self.assertNotEqual(source, SOURCES["std/prelude.ouro"])
            for installed in (False, True):
                with self.subTest(change=new, installed=installed), self.assertRaises(RuntimeError):
                    hook(arithmetic_source(fast=installed),
                         sources={**SOURCES, "std/prelude.ouro": source}, installed=installed)
        for source in (SOURCES["std/prelude.ouro"] + expected,
                       SOURCES["std/prelude.ouro"].replace(expected.strip(), "", 1),
                       SOURCES["std/prelude.ouro"].replace('import "types.ouro";',
                                                        'import "types.ouro", "data.ouro";', 1)):
            with self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, "std/prelude.ouro": source})
        for old, new in (("| S : Nat -> Nat", "| S : Nat -> Nat -> Nat"),
                         ('representation Nat := "ouro.nat"', 'representation Nat := "ouro.bool"')):
            self.assertIn(old, SOURCES["std/types.ouro"])
            with self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, "std/types.ouro":
                                                  SOURCES["std/types.ouro"].replace(old, new, 1)})
        trivia = SOURCES["std/prelude.ouro"] + '\ndef text : String := "def sub : Nat := Z;";\n'
        self.assertEqual(hook(arithmetic_source(), sources={**SOURCES, "std/prelude.ouro": trivia}),
                         arithmetic_source(fast=True))

    def test_sub_owner_getter_cache_curry_and_unbound_fast_refusal(self):
        raw = arithmetic_source()
        final = ("static ouro_v *ouro_f0_241_(ouro_env *env0,ouro_v *arg){"
                 "ouro_env *env=ouro_cons(arg,env0);(void)env;return arg;}\n")
        self.assertIn(final, raw)
        invalid = (
            raw.replace('"_ouro_m_1_sub"', '"_ouro_m_0_sub"'),
            raw.replace('"_ouro_m_1_sub"', '"_ouro_m_01_sub"'),
            raw.replace('"_ouro_m_1_sub"', '"missing_sub"'),
            raw.replace("case 4:return ouro_g241();", "case 4:return ouro_g31();"),
            raw.replace("ouro_c241=ouro_clos", "ouro_c241=ouro_nat(0);ouro_c241=ouro_clos"),
            raw.replace("return ouro_clos(ouro_f0_241_,env);", "return arg;"),
            raw.replace(final, final.replace("ouro_cons(arg,env0)", "ouro_cons(arg,0)")),
            raw.replace(final, ""), raw.replace(final, final + final),
            raw.replace(final, final.replace("{", "{\n", 1)),
            raw.replace(final, final.replace("return arg;", "return ouro_clos(ouro_f0_0_241_,env);")),
            raw + "static ouro_v *ouro_g241_d2(void){return ouro_c241;}\n",
            raw + "static ouro_v *ouro_c241_d2;\n",
            raw + final.replace("ouro_f0_241_", "ouro_f0_241__d2"),
            raw + "ouro_v *other(void){return ouro_f241_(0,0);}\n",
        )
        for text in invalid:
            with self.subTest(text=text[-80:]), self.assertRaises(RuntimeError):
                hook(text)
        fast = arithmetic_source(fast=True)
        for text in (fast.replace('ouro_fast("sub")', 'ouro_fast("add")'),
                     fast.replace("return ouro_c241;", "return ouro_c31;"),
                     fast + '\nouro_v *other(void){return ouro_fast ( "sub" );}\n',
                     fast + final):
            with self.assertRaises(RuntimeError):
                hook(text, installed=True)

    def test_sub_canonical_selection_preserves_foreign_homonym(self):
        sources = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]]
                   + "def sub : Nat -> Nat -> Nat := fun n m => Z;\n"}
        raw = arithmetic_source().replace("return 5;", "return 6;", 1)
        raw = raw.replace('case 4:return "_ouro_m_1_sub";',
                          'case 4:return "_ouro_m_1_sub";case 5:return "sub";')
        raw = raw.replace("case 4:return ouro_g241();", "case 4:return ouro_g241();case 5:return ouro_g261();")
        user = export_source((("sub", 261),), arities={261: 2}).split("int ouro_export_count", 1)[0]
        raw = raw.replace("int ouro_export_count", user + "int ouro_export_count", 1)
        bound = hook(raw, sources=sources)
        self.assertIn('ouro_c241=ouro_fast("sub")', bound)
        self.assertIn("ouro_c261=ouro_clos(ouro_f261_,env)", bound)
        with self.assertRaises(RuntimeError):
            hook(arithmetic_source(qualified=False), sources=sources)
        only = ("std/types.ouro", UNITS[-1])
        root_source = ('import "../std/types.ouro";\n'
                       'def sub : Nat -> Nat -> Nat := fun n m => Z;\n')
        plain = export_source((("sub", 261),), arities={261: 2})
        bodies = {"std/types.ouro": SOURCES["std/types.ouro"], UNITS[-1]: root_source}
        self.assertEqual(hook(plain, units=only, canonical=only, sources=bodies), plain)
        for call in ('ouro_fast("sub")', 'ouro_fast \n( "sub"\n )'):
            with self.assertRaises(RuntimeError):
                hook(plain + '\nouro_v *other(void){return ' + call + ';}\n',
                    units=only, canonical=only, sources=bodies)

    def test_current_and_historical_sub_root_homonym_emit_protocol(self):
        for bridge in (False, True):
            with self.subTest(historical_bridge=bridge), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary).resolve()
                graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
                root, module = "compiler/parse_a.ouro", "_pa"
                units = ["std/types.ouro", root]
                (repo / "std").mkdir(exist_ok=True)
                (repo / units[0]).write_text(SOURCES[units[0]], encoding="utf-8")
                (repo / root).write_text('import "../std/types.ouro";\n'
                    + "def sub : Nat -> Nat -> Nat := fun n m => Z;\n"
                    + "private def main : Nat := sub 3 1;\n", encoding="utf-8")
                graph[root] = units
                work = repo / "work"
                work.mkdir()
                raw = export_source((("sub", 261),), module, arities={261: 2})
                raw = raw.replace("return arg;}", "return ouro_ctor(0,0,0);}", 1)
                legacy = raw.replace("ouro_c261=ouro_clos(ouro_f261_,env)",
                                     'ouro_c261=ouro_fast("sub")')
                emission = [legacy if bridge else raw]
                def emit_mock(_command, _bridge=bridge, _emission=emission, **kwargs):
                    if _bridge:
                        self.assertNotIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"])
                    else:
                        self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                        self.assertIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"]["WSLENV"].split(":"))
                    kwargs["stdout"].write(_emission[0].encode())
                    return SimpleNamespace(returncode=0)
                with ExitStack() as stack:
                    for name, value in (("ROOT", repo),
                                        ("rel", lambda path, _repo=repo: path.relative_to(_repo).as_posix()),
                                        ("collect_units_many", lambda _roots, _graph=graph, **_options: _graph),
                                        ("collect_units", lambda selected, _graph=graph: _graph[selected]),
                                        ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                        stack.enter_context(patch.object(regen, name, value))
                    stack.enter_context(patch.dict(os.environ, {"OURO_EMIT_SCOPED_ARITHMETIC": "inherited"}))
                    _graph, inputs, _signature = regen.all_frontend_inputs(seed, "16000", historical_bridge=bridge)
                    options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                                   tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                                   file_name="pa.c", units=units, digests=inputs, historical_bridge=bridge)
                    calls = stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                    cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                    installed = (work / "pa.c").read_text(encoding="utf-8")
                    if bridge:
                        self.assertEqual(installed, legacy)
                    else:
                        self.assertEqual(installed, raw)
                        self.assertNotIn('ouro_fast("sub")', installed)
                        self.assertIn("return ouro_ctor(0,0,0);", installed)
                        self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, inputs,
                                                                  "16000", historical_bridge=True))
                        emission[0] = legacy
                        previous = (work / "pa.c").read_bytes()
                        with self.assertRaises(RuntimeError):
                            regen.emit_one(**{**options, "cache_enabled": False})
                        self.assertEqual((work / "pa.c").read_bytes(), previous)


class CanonicalNatCompareControls(unittest.TestCase):
    def test_compare_getters_raw_historical_and_installed_forms(self):
        for module, qualified, offset in (("", True, 0), ("_pl", True, 72), ("_pa", False, 19)):
            with self.subTest(module=module, qualified=qualified, offset=offset):
                raw = arithmetic_source(module, qualified=qualified, offset=offset, comparison=True)
                fast = arithmetic_source(module, qualified=qualified, offset=offset,
                                         fast=True, comparison=True)
                self.assertEqual(comparison_hook(raw, module=module), fast)
                self.assertEqual(comparison_hook(fast, module=module), fast)
                self.assertEqual(comparison_hook(fast, module=module, installed=True), fast)
                with self.assertRaises(RuntimeError):
                    comparison_hook(raw, module=module, installed=True)
        units = COMPARE_UNITS[:-1]
        sources = {name: COMPARE_SOURCES[name] for name in units}
        raw = arithmetic_source(comparison=True).replace('"_ouro_m_2_compareNat"', '"compareNat"')
        fast = arithmetic_source(comparison=True, fast=True).replace('"_ouro_m_2_compareNat"', '"compareNat"')
        self.assertEqual(comparison_hook(raw, units=units, canonical=units, sources=sources), fast)
        raw = arithmetic_source(comparison=True).replace("ouro_clos(ouro_f71_,env)",
                                                         "ouro_fix(ouro_f71_,env)")
        self.assertEqual(comparison_hook(raw), arithmetic_source(comparison=True, fast=True))

    def test_compare_source_and_ordering_layout_drift(self):
        changes = (
            ("std/data.ouro", "| Z, Z => EQ", "| Z, Z => LT"),
            ("std/data.ouro", "| Z, S _ => LT", "| Z, S _ => GT"),
            ("std/data.ouro", "compareNat n' m'", "compareNat m' n'"),
            ("std/data.ouro", "def compareNat", "private def compareNat"),
            ("std/data.ouro", 'import "prelude.ouro";', 'import "types.ouro";'),
            ("std/types.ouro", "| LT : Ordering\n  | EQ : Ordering\n  | GT : Ordering",
             "| GT : Ordering\n  | EQ : Ordering\n  | LT : Ordering"),
            ("std/types.ouro", "| LT : Ordering", "| LT : Nat -> Ordering"),
            ("std/types.ouro", 'representation Nat := "ouro.nat";',
             'representation Nat := "ouro.bool";'),
        )
        raw = arithmetic_source(comparison=True)
        for owner, old, new in changes:
            self.assertIn(old, COMPARE_SOURCES[owner])
            with self.subTest(owner=owner, change=new), self.assertRaises(RuntimeError):
                comparison_hook(raw, sources={**COMPARE_SOURCES,
                    owner: COMPARE_SOURCES[owner].replace(old, new, 1)})
        for owner, _kind, name, expected in packer.NAT_COMPARE_SOURCE_SHAPES:
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                comparison_hook(raw, sources={**COMPARE_SOURCES,
                    owner: COMPARE_SOURCES[owner] + expected})
        for owner, extra in (("std/types.ouro", '\nrepresentation Ordering := "ouro.bool";\n'),
                             ("std/data.ouro", '\nimport "types.ouro";\n')):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                comparison_hook(raw, sources={**COMPARE_SOURCES,
                    owner: COMPARE_SOURCES[owner] + extra})
        for owner in COMPARE_UNITS[:-1]:
            with self.subTest(missing=owner), self.assertRaises(RuntimeError):
                comparison_hook(raw, sources={name: body for name, body in COMPARE_SOURCES.items()
                                              if name != owner})
        trivia = '-- def compareNat := unsupported;\n' + COMPARE_SOURCES["std/data.ouro"]
        trivia += '\ndef text : String := "def compareNat : Nat := Z;";\n'
        self.assertEqual(comparison_hook(raw, sources={**COMPARE_SOURCES, "std/data.ouro": trivia}),
                         comparison_hook(raw))

    def test_compare_export_getter_cache_curry_and_family_drift(self):
        raw = arithmetic_source(comparison=True)
        nested = ("static ouro_v *ouro_t1_0_71_(ouro_env *env,ouro_v *arg){"
                  "(void)arg;return ouro_get(env,0);}\n")
        raw_nested = raw.replace("static ouro_v *ouro_c71;", nested + "static ouro_v *ouro_c71;")
        self.assertEqual(comparison_hook(raw_nested), arithmetic_source(comparison=True, fast=True))
        invalid = (
            raw.replace('"_ouro_m_2_compareNat"', '"_ouro_m_1_compareNat"'),
            raw.replace('"_ouro_m_2_compareNat"', '"_ouro_m_02_compareNat"'),
            raw.replace('"_ouro_m_2_compareNat"', '"missing_compareNat"'),
            raw.replace("case 2:return ouro_g71();", "case 2:return ouro_g31();"),
            raw.replace("ouro_c71=ouro_clos", "ouro_c71=ouro_nat(0);ouro_c71=ouro_clos"),
            raw.replace("return ouro_clos(ouro_f0_71_,env);", "return arg;"),
            raw.replace("static ouro_v *ouro_f0_71_(ouro_env *env0,ouro_v *arg){"
                        "ouro_env *env=ouro_cons(arg,env0);(void)env;return arg;}",
                        "static ouro_v *ouro_f0_71_(ouro_env *env0,ouro_v *arg){"
                        "ouro_env *env=ouro_cons(arg,env0);(void)env;return ouro_clos(ouro_f0_0_71_,env);}"),
            raw + "static ouro_v *ouro_g71_d2(void){return ouro_c71;}\n",
            raw + "static ouro_v *ouro_c71_d2;\n",
            raw + "static ouro_v *ouro_f0_71__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            raw + "ouro_v *other(void){return ouro_f71_(0,0);}\n",
            raw_nested + "ouro_v *other(void){return ouro_t1_0_71_(0,0);}\n",
            raw_nested.replace(nested, nested + nested),
            raw_nested.replace(nested, nested.replace("{", "{\n", 1)),
        )
        for text in invalid:
            self.assertNotEqual(text, raw)
            with self.subTest(text=text[-110:]), self.assertRaises(RuntimeError):
                comparison_hook(text)
        for units in (COMPARE_UNITS[::-1], COMPARE_UNITS + COMPARE_UNITS[:1], COMPARE_UNITS[1:]):
            with self.subTest(units=units), self.assertRaises(RuntimeError):
                comparison_hook(raw, units=units)
        fast = arithmetic_source(comparison=True, fast=True)
        for text in (fast.replace('ouro_fast("compareNat")', 'ouro_fast("mul")', 1),
                     fast + '\nouro_v *unbound(void){return ouro_fast("compareNat");}\n'):
            with self.assertRaises(RuntimeError):
                comparison_hook(text, installed=True)

    def test_optional_owner_and_user_homonyms_remain_unaccelerated(self):
        bodies = {**COMPARE_SOURCES, UNITS[-1]: COMPARE_SOURCES[UNITS[-1]]
                  + "def compareNat : Nat -> Nat -> Ordering := fun n m => LT;\n"}
        raw = arithmetic_source(comparison=True, shadow=True)
        result = comparison_hook(raw, sources=bodies)
        self.assertEqual(result, arithmetic_source(comparison=True, shadow=True, fast=True))
        self.assertIn("ouro_c81=ouro_clos(ouro_f81_,env)", result)
        with self.assertRaises(RuntimeError):
            comparison_hook(arithmetic_source(comparison=True, qualified=False), sources=bodies)
        base_bodies = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]]
                       + "def compareNat : Nat -> Nat -> Ordering := fun n m => LT;\n"}
        raw = arithmetic_source(comparison=True).replace('"_ouro_m_2_compareNat"', '"compareNat"')
        result = hook(raw, sources=base_bodies)
        self.assertIn("ouro_c71=ouro_clos(ouro_f71_,env)", result)
        self.assertNotIn('ouro_fast("compareNat")', result)
        self.assertEqual(hook(result, sources=base_bodies, installed=True), result)
        self.assertEqual(packer.prelude_arithmetic_source_paths(UNITS),
                         packer.PRELUDE_ARITHMETIC_SOURCE_PATHS)
        types = SOURCES["std/types.ouro"].replace(
            "| LT : Ordering\n  | EQ : Ordering\n  | GT : Ordering",
            "| GT : Ordering\n  | EQ : Ordering\n  | LT : Ordering", 1)
        self.assertEqual(hook(arithmetic_source(), sources={**SOURCES, "std/types.ouro": types}),
                         arithmetic_source(fast=True))
        for text in (result + '\nouro_v *unbound(void){return ouro_fast("compareNat");}\n',
                     result + '\nouro_v *unbound(void){return ouro_fast \n( "compareNat"\n );}\n'):
            with self.assertRaises(RuntimeError):
                hook(text, sources=base_bodies, installed=True)
        units = (UNITS[-1],)
        bodies = {UNITS[-1]: base_bodies[UNITS[-1]]}
        raw = export_source((("compareNat", 71),), arities={71: 2})
        self.assertEqual(hook(raw, units=units, canonical=units, sources=bodies), raw)
        with self.assertRaises(RuntimeError):
            hook(raw + '\nouro_v *unbound(void){return ouro_fast("compareNat");}\n',
                 units=units, canonical=units, sources=bodies)

    def test_compare_cache_readback_and_preserved_timestamp_source_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
            root, module = "compiler/parse_a.ouro", "_pa"
            units = [*COMPARE_UNITS[:-1], root]
            for name in COMPARE_UNITS[:-1]:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(COMPARE_SOURCES[name], encoding="utf-8")
            (repo / root).write_text(COMPARE_SOURCES[UNITS[-1]], encoding="utf-8")
            graph[root] = units
            work = repo / "work"
            work.mkdir()

            def emit_mock(_command, **kwargs):
                self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                kwargs["stdout"].write(arithmetic_source(module, comparison=True).encode())
                return SimpleNamespace(returncode=0)

            with ExitStack() as stack:
                for name, value in (("ROOT", repo), ("rel", lambda path: path.relative_to(repo).as_posix()),
                                    ("collect_units_many", lambda _roots, **_options: graph),
                                    ("collect_units", lambda selected: graph[selected]),
                                    ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                    stack.enter_context(patch.object(regen, name, value))
                _graph, inputs, signature = regen.all_frontend_inputs(seed, "16000")
                binding = regen.prelude_arithmetic_binding(root, units, inputs)
                self.assertIn(packer.NAT_COMPARE_OWNER, [item["path"] for item in binding["inputs"]])
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=units, digests=inputs)
                calls = stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                self.assertEqual((work / "pa.c").read_text(encoding="utf-8"),
                                 arithmetic_source(module, comparison=True, fast=True))
                self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, inputs,
                                                          "16000", historical_bridge=True))
                cache = repo / "cache" / (module + "_" + cold.key + ".c")
                cache.write_text(arithmetic_source(module, comparison=True, fast=True).replace(
                    'ouro_fast("compareNat")', 'ouro_fast("mul")', 1), encoding="utf-8")
                regen.record_cached_output(cache, cold.key)
                previous = (work / "pa.c").read_bytes()
                with self.assertRaises(RuntimeError):
                    regen.emit_one(**options)
                self.assertEqual((work / "pa.c").read_bytes(), previous)
                source = repo / packer.NAT_COMPARE_OWNER
                stamp = source.stat()
                source.write_bytes(source.read_bytes() + b"\n-- SOURCE binding trivia\n")
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, inputs, "16000")
                _graph, changed, changed_signature = regen.all_frontend_inputs(seed, "16000")
                self.assertNotEqual(signature, changed_signature)
                self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, changed, "16000"))
                source.write_text(COMPARE_SOURCES[packer.NAT_COMPARE_OWNER].replace(
                    "| Z, Z => EQ", "| Z, Z => GT", 1), encoding="utf-8")
                _graph, changed, _signature = regen.all_frontend_inputs(seed, "16000")
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, changed, "16000")

    def test_flat_compare_binds_before_aliases_and_preserves_failed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for name, body in COMPARE_SOURCES.items():
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            target = repo / "runtime/frontend_link.c"
            target.parent.mkdir(parents=True)
            target.write_text("", encoding="utf-8")
            output = repo / "program.c"
            output.write_text("previous output\n", encoding="utf-8")

            def run_mock(_command, **kwargs):
                if "stdout" in kwargs:
                    self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                    kwargs["stdout"].write(arithmetic_source(comparison=True).encode())
                return SimpleNamespace(returncode=0)

            def aliases(text, *_args, **_kwargs):
                self.assertEqual(text, arithmetic_source(comparison=True, fast=True, elem_scoped=True))
                return text

            with patch.object(native, "ROOT", repo), \
                    patch.object(native.frontend, "ROOT", repo), \
                    patch.object(native.frontend, "ouro1_cmd", return_value=["SOURCE-mocked-compiler"]), \
                    patch.object(native.subprocess, "run", side_effect=run_mock), \
                    patch.object(native, "current_native_scoped_aliases", side_effect=aliases):
                native.emit(Path("SOURCE-seed"), list(COMPARE_UNITS), 200000, output)
                previous = output.read_bytes()
                source = repo / packer.NAT_COMPARE_OWNER
                source.write_text(COMPARE_SOURCES[packer.NAT_COMPARE_OWNER].replace(
                    "compareNat n' m'", "compareNat m' n'", 1), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    native.emit(Path("SOURCE-seed"), list(COMPARE_UNITS), 200000, output)
                self.assertEqual(output.read_bytes(), previous)


class CanonicalNatEqualityControls(unittest.TestCase):
    def test_equality_forms_owner_and_homonyms(self):
        for module, qualified, offset in (("", True, 0), ("_pa", True, 27), ("_pl", False, 108)):
            with self.subTest(module=module, qualified=qualified):
                raw = arithmetic_source(module, qualified=qualified, offset=offset, equality=True)
                fast = arithmetic_source(module, qualified=qualified, offset=offset, equality=True, fast=True)
                self.assertEqual(equality_hook(raw, module=module), fast)
                self.assertEqual(equality_hook(fast, module=module), fast)
                self.assertEqual(equality_hook(fast, module=module, installed=True), fast)
                with self.assertRaises(RuntimeError):
                    equality_hook(raw, module=module, installed=True)
        raw = arithmetic_source(equality=True).replace("ouro_clos(ouro_f91_,env)",
                                                       "ouro_fix(ouro_f91_,env)")
        self.assertEqual(equality_hook(raw), arithmetic_source(equality=True, fast=True))
        units = EQUALITY_UNITS[:-1]
        bodies = {name: EQUALITY_SOURCES[name] for name in units}
        raw = arithmetic_source(equality=True).replace('"_ouro_m_3_eqNat"', '"eqNat"')
        expected = arithmetic_source(equality=True, fast=True).replace('"_ouro_m_3_eqNat"', '"eqNat"')
        self.assertEqual(equality_hook(raw, units=units, canonical=units, sources=bodies), expected)
        bodies = {**EQUALITY_SOURCES, UNITS[-1]: EQUALITY_SOURCES[UNITS[-1]]
                  + "def eqNat : Nat -> Nat -> Bool := fun n m => False;\n"}
        raw = arithmetic_source(equality=True, shadow=True)
        self.assertEqual(equality_hook(raw, sources=bodies),
                         arithmetic_source(equality=True, shadow=True, fast=True))
        with self.assertRaises(RuntimeError):
            equality_hook(arithmetic_source(equality=True, qualified=False), sources=bodies)
        bodies = {**COMPARE_SOURCES, UNITS[-1]: COMPARE_SOURCES[UNITS[-1]]
                  + "def eqNat : Nat -> Nat -> Bool := fun n m => False;\n"}
        raw = arithmetic_source(equality=True).replace('"_ouro_m_3_eqNat"', '"eqNat"')
        result = comparison_hook(raw, sources=bodies)
        self.assertIn("ouro_c91=ouro_clos(ouro_f91_,env)", result)
        self.assertNotIn('ouro_fast("eqNat")', result)
        self.assertEqual(comparison_hook(result, sources=bodies, installed=True), result)
        self.assertNotIn(packer.NAT_EQUALITY_OWNER,
                         packer.prelude_arithmetic_source_paths(COMPARE_UNITS))
        with self.assertRaises(RuntimeError):
            comparison_hook(result + '\nouro_v *unbound(void){return ouro_fast("eqNat");}\n',
                            sources=bodies, installed=True)

    def test_equality_source_layout_and_generated_family_drift(self):
        raw = arithmetic_source(equality=True)
        changes = (
            ("compiler/base.ouro", "def eqNat", "private def eqNat"),
            ("compiler/base.ouro", "| Z => True", "| Z => False"),
            ("compiler/base.ouro", "eqNat n' m'", "eqNat m' n'"),
            ("compiler/base.ouro", 'import "../std/data.ouro";', 'import "../std/prelude.ouro";'),
            ("std/types.ouro", "| True : Bool\n  | False : Bool",
             "| False : Bool\n  | True : Bool"),
            ("std/types.ouro", "| True : Bool", "| True : Nat -> Bool"),
            ("std/types.ouro", 'representation Bool := "ouro.bool";',
             'representation Bool := "ouro.nat";'),
        )
        for owner, old, new in changes:
            self.assertIn(old, EQUALITY_SOURCES[owner])
            with self.subTest(owner=owner, change=new), self.assertRaises(RuntimeError):
                equality_hook(raw, sources={**EQUALITY_SOURCES,
                    owner: EQUALITY_SOURCES[owner].replace(old, new, 1)})
        for owner, _kind, name, expected in packer.NAT_EQUALITY_SOURCE_SHAPES:
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                equality_hook(raw, sources={**EQUALITY_SOURCES,
                    owner: EQUALITY_SOURCES[owner] + expected})
        for owner in EQUALITY_UNITS[:-1]:
            with self.subTest(missing=owner), self.assertRaises(RuntimeError):
                equality_hook(raw, sources={name: body for name, body in EQUALITY_SOURCES.items()
                                            if name != owner})
        invalid = (
            raw.replace('"_ouro_m_3_eqNat"', '"_ouro_m_2_eqNat"'),
            raw.replace('"_ouro_m_3_eqNat"', '"_ouro_m_03_eqNat"'),
            raw.replace("case 3:return ouro_g91();", "case 3:return ouro_g71();"),
            raw.replace("ouro_c91=ouro_clos", "ouro_c91=ouro_nat(0);ouro_c91=ouro_clos"),
            raw.replace("return ouro_clos(ouro_f0_91_,env);", "return arg;"),
            raw + "static ouro_v *ouro_g91_d2(void){return ouro_c91;}\n",
            raw + "static ouro_v *ouro_c91_d2;\n",
            raw + "static ouro_v *ouro_f0_91__d2(ouro_env *env0,ouro_v *arg){return arg;}\n",
            raw + "ouro_v *external(void){return ouro_f91_(0,0);}\n",
        )
        for text in invalid:
            self.assertNotEqual(text, raw)
            with self.assertRaises(RuntimeError):
                equality_hook(text)
        fast = arithmetic_source(equality=True, fast=True)
        with self.assertRaises(RuntimeError):
            equality_hook(fast.replace('ouro_fast("eqNat")', 'ouro_fast("compareNat")', 1),
                          installed=True)
        self.assertEqual(equality_hook(raw, sources={**EQUALITY_SOURCES,
            packer.NAT_EQUALITY_OWNER: "-- eqNat trivia\n" + EQUALITY_SOURCES[packer.NAT_EQUALITY_OWNER]}),
            fast)

    def test_equality_source_bound_cache_and_exact_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
            root, module = "compiler/parse_a.ouro", "_pa"
            units = [*EQUALITY_UNITS[:-1], root]
            for name in EQUALITY_UNITS[:-1]:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(EQUALITY_SOURCES[name], encoding="utf-8")
            (repo / root).write_text(EQUALITY_SOURCES[UNITS[-1]], encoding="utf-8")
            graph[root] = units
            work = repo / "work"
            work.mkdir()

            def emit_mock(_command, **kwargs):
                self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                kwargs["stdout"].write(arithmetic_source(module, equality=True).encode())
                return SimpleNamespace(returncode=0)

            with ExitStack() as stack:
                for name, value in (("ROOT", repo), ("rel", lambda path: path.relative_to(repo).as_posix()),
                                    ("collect_units_many", lambda _roots, **_options: graph),
                                    ("collect_units", lambda selected: graph[selected]),
                                    ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                    stack.enter_context(patch.object(regen, name, value))
                _graph, inputs, signature = regen.all_frontend_inputs(seed, "16000")
                binding = regen.prelude_arithmetic_binding(root, units, inputs)
                self.assertIn(packer.NAT_EQUALITY_OWNER, [item["path"] for item in binding["inputs"]])
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=units, digests=inputs)
                calls = stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                expected = arithmetic_source(module, equality=True, fast=True)
                self.assertEqual((work / "pa.c").read_text(encoding="utf-8"), expected)
                cache = repo / "cache" / (module + "_" + cold.key + ".c")
                cache.write_text(expected.replace('ouro_fast("eqNat")', 'ouro_fast("mul")', 1),
                                 encoding="utf-8")
                regen.record_cached_output(cache, cold.key)
                previous = (work / "pa.c").read_bytes()
                with self.assertRaises(RuntimeError):
                    regen.emit_one(**options)
                self.assertEqual((work / "pa.c").read_bytes(), previous)
                source = repo / packer.NAT_EQUALITY_OWNER
                stamp = source.stat()
                source.write_bytes(source.read_bytes() + b"\n-- SOURCE equality binding trivia\n")
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, inputs, "16000")
                _graph, changed, changed_signature = regen.all_frontend_inputs(seed, "16000")
                self.assertNotEqual(signature, changed_signature)
                self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, changed, "16000"))
                source.write_text(EQUALITY_SOURCES[packer.NAT_EQUALITY_OWNER].replace(
                    "| Z => True", "| Z => False", 1), encoding="utf-8")
                _graph, changed, _signature = regen.all_frontend_inputs(seed, "16000")
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, changed, "16000")

    def test_module_lookup_dependency_guard_accepts_bound_equality(self):
        source = lookup_controls.module_source(fast=True)
        result = lookup_controls.ModuleLookupSourceControls().hook(source)
        self.assertIn('ouro_c41=ouro_fast("eqNat")', result)
        self.assertEqual(lookup_controls.ModuleLookupSourceControls().hook(result, installed=True), result)


class PreludeListLengthControls(unittest.TestCase):
    def test_erased_unary_forms_and_exact_installed_readback(self):
        for module, qualified, offset in (("", True, 0), ("_pl", True, 59), ("_pa", False, 17)):
            with self.subTest(module=module, qualified=qualified):
                raw = arithmetic_source(module, qualified=qualified, offset=offset)
                fast = arithmetic_source(module, qualified=qualified, offset=offset, fast=True)
                self.assertEqual(hook(raw, module=module), fast)
                self.assertEqual(hook(fast, module=module, installed=True), fast)
                gid = 131 + offset
                self.assertEqual(hook(raw.replace(f"ouro_clos(ouro_f{gid}_,env)",
                                                 f"ouro_fix(ouro_f{gid}_,env)"), module=module), fast)
        with self.assertRaises(RuntimeError):
            hook(arithmetic_source(), installed=True)

    def test_length_source_list_nat_layout_and_import_mutations(self):
        changes = (
            ("std/prelude.ouro", "S (length xs')", "length xs'"),
            ("std/prelude.ouro", "def length (A : Type)", "private def length (A : Type)"),
            ("std/prelude.ouro", 'import "types.ouro";', 'import "types.ouro", "data.ouro";'),
            ("std/types.ouro", "| Nil : List A\n  | Cons : A -> List A -> List A",
             "| Cons : A -> List A -> List A\n  | Nil : List A"),
            ("std/types.ouro", "| Cons : A -> List A -> List A", "| Cons : List A -> A -> List A"),
            ("std/types.ouro", 'representation List := "ouro.list"', 'representation List := "ouro.pair"'),
            ("std/types.ouro", "| S : Nat -> Nat", "| S : Nat -> Nat -> Nat"),
        )
        for owner, old, new in changes:
            self.assertIn(old, SOURCES[owner])
            with self.subTest(change=new), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: SOURCES[owner].replace(old, new, 1)})
        for owner, _kind, name, expected in packer.PRELUDE_LIST_LENGTH_SOURCE_SHAPES:
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: SOURCES[owner] + expected})

    def test_length_owner_homonyms_curry_family_and_cache_mutations(self):
        bodies = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]]
                  + "def length (A : Type) (xs : List A) : Nat := Z;\n"}
        raw = arithmetic_source().replace('return 5;', 'return 6;', 1)
        raw = raw.replace('case 3:return "_ouro_m_1_append";',
                          'case 3:return "_ouro_m_1_append";case 5:return "length";')
        raw = raw.replace("case 3:return ouro_g171();", "case 3:return ouro_g171();case 5:return ouro_g141();")
        user = export_source((("length", 141),)).split("int ouro_export_count", 1)[0]
        raw = raw.replace("int ouro_export_count", user + "int ouro_export_count", 1)
        result = hook(raw, sources=bodies)
        self.assertIn('ouro_c131=ouro_fast("length")', result)
        self.assertIn("ouro_c141=ouro_clos(ouro_f141_,env)", result)
        with self.assertRaises(RuntimeError):
            hook(arithmetic_source(qualified=False), sources=bodies)
        only = (UNITS[-1],)
        plain = export_source((("length", 141),))
        self.assertEqual(hook(plain, units=only, canonical=only, sources=bodies), plain)
        with self.assertRaises(RuntimeError):
            hook(plain + '\nouro_v *other(void){return ouro_fast("length");}\n',
                 units=only, canonical=only, sources=bodies)
        raw = arithmetic_source()
        unary = ("static ouro_v *ouro_f131_(ouro_env *env0,ouro_v *arg){"
                 "ouro_env *env=ouro_cons(arg,env0);(void)env;return arg;}")
        self.assertIn(unary, raw)
        invalid = (
            raw.replace('"_ouro_m_1_length"', '"_ouro_m_0_length"'),
            raw.replace("case 2:return ouro_g131();", "case 2:return ouro_g31();"),
            raw.replace(unary, unary.replace("return arg;", "return ouro_clos(ouro_f0_131_,env);")),
            raw.replace(unary, ""), raw.replace(unary, unary + "\n" + unary),
            raw.replace(unary, unary.replace("{", "{\n", 1)),
            raw + "static ouro_v *ouro_g131_d2(void){return 0;}\n",
            raw + "static ouro_v *ouro_c131_d2;\n",
            raw + "ouro_v *other(void){return ouro_f131_(0,0);}\n",
        )
        for text in invalid:
            with self.subTest(text=text[-100:]), self.assertRaises(RuntimeError):
                hook(text)
        fast = arithmetic_source(fast=True)
        for text in (fast.replace('ouro_fast("length")', 'ouro_fast("add")'),
                     fast + '\nouro_v *other(void){return ouro_fast ( "length" );}\n'):
            with self.assertRaises(RuntimeError):
                hook(text, installed=True)

    def test_length_source_hash_binding_and_installed_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
            root, module = "compiler/parse_a.ouro", "_pa"
            units = [*UNITS[:-1], root]
            for name in UNITS[:-1]:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(SOURCES[name], encoding="utf-8")
            (repo / root).write_text(SOURCES[UNITS[-1]], encoding="utf-8")
            graph[root] = units
            work = repo / "work"
            work.mkdir()
            def emit_mock(_command, **kwargs):
                kwargs["stdout"].write(arithmetic_source(module).encode())
                return SimpleNamespace(returncode=0)
            with ExitStack() as stack:
                for name, value in (("ROOT", repo), ("rel", lambda path: path.relative_to(repo).as_posix()),
                                    ("collect_units_many", lambda _roots, **_options: graph),
                                    ("collect_units", lambda selected: graph[selected]),
                                    ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                    stack.enter_context(patch.object(regen, name, value))
                _graph, inputs, signature = regen.all_frontend_inputs(seed, "16000")
                binding = regen.prelude_arithmetic_binding(root, units, inputs)
                self.assertEqual(binding["prelude_list_length"],
                                 {"owner": "std/prelude.ouro", "value_arity": 1})
                self.assertEqual(binding["prelude_list_append"],
                                 {"owner": "std/prelude.ouro", "value_arity": 2})
                options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                               tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                               file_name="pa.c", units=units, digests=inputs)
                calls = stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                cache = repo / "cache" / (module + "_" + cold.key + ".c")
                previous = (work / "pa.c").read_bytes()
                for name in ("length", "append", "sub"):
                    with self.subTest(cache_binding=name):
                        cache.write_text(arithmetic_source(module, fast=True).replace(
                            f'ouro_fast("{name}")', 'ouro_fast("mul")'), encoding="utf-8")
                        regen.record_cached_output(cache, cold.key)
                        with self.assertRaises(RuntimeError):
                            regen.emit_one(**options)
                        self.assertEqual((work / "pa.c").read_bytes(), previous)
                source = repo / "std/prelude.ouro"
                stamp = source.stat()
                source.write_bytes(source.read_bytes() + b"\n-- SOURCE list length binding trivia\n")
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                with self.assertRaises(RuntimeError):
                    regen.tu_key("pa", module, root, units, inputs, "16000")
                _graph, changed, changed_signature = regen.all_frontend_inputs(seed, "16000")
                self.assertNotEqual(signature, changed_signature)
                self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, changed, "16000"))
                for old, new in (("Cons A x (append xs' ys)", "Cons A x (append ys xs')"),
                                 ("sub n' m'", "sub m' n'")):
                    source.write_text(SOURCES["std/prelude.ouro"].replace(old, new, 1), encoding="utf-8")
                    _graph, changed, _signature = regen.all_frontend_inputs(seed, "16000")
                    with self.assertRaises(RuntimeError):
                        regen.tu_key("pa", module, root, units, changed, "16000")


class PreludeListAppendControls(unittest.TestCase):
    def test_fix_match_branch_curry_forms_and_exact_installed_readback(self):
        for module, qualified, offset in (("", True, 0), ("_pl", True, 29), ("_pa", False, 11)):
            with self.subTest(module=module, qualified=qualified):
                raw = arithmetic_source(module, qualified=qualified, offset=offset)
                fast = arithmetic_source(module, qualified=qualified, offset=offset, fast=True)
                self.assertIn(f"ouro_c{171 + offset}=ouro_fix(ouro_f{171 + offset}_,env)", raw)
                self.assertEqual(hook(raw, module=module), fast)
                self.assertEqual(hook(fast, module=module, installed=True), fast)
                self.assertEqual(hook(fast, module=module), fast)
                self.assertNotIn(f"ouro_f{171 + offset}_", fast)
                with self.assertRaises(RuntimeError):
                    hook(raw, module=module, installed=True)
        result = equality_hook(arithmetic_source(equality=True))
        self.assertEqual(result, arithmetic_source(equality=True, fast=True))
        self.assertEqual(re.findall(r'ouro_fast\("([^"\n]+)"\)', result),
                         ["add", "mul", "compareNat", "eqNat", "length", "append", "sub"])
        units = UNITS[:-1]
        sources = {name: SOURCES[name] for name in units}
        self.assertEqual(hook(arithmetic_source(qualified=False), units=units, canonical=units, sources=sources),
                         arithmetic_source(qualified=False, fast=True))

    def test_current_and_historical_emit_protocol_and_root_homonym(self):
        for bridge in (False, True):
            with self.subTest(historical_bridge=bridge), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary).resolve()
                graph, seed = lookup_controls.LookupCtorSourceControls().setup_repo(repo, capable=False)
                root, module = "compiler/parse_a.ouro", "_pa"
                units = ["std/types.ouro", root]
                (repo / "std").mkdir(exist_ok=True)
                (repo / units[0]).write_text(SOURCES[units[0]], encoding="utf-8")
                (repo / root).write_text('import "../std/types.ouro";\n'
                    + "def append (A : Type) (xs : List A) (ys : List A) : List A := Nil A;\n"
                    + "private def main : List Nat := append Nat [1] [2];\n", encoding="utf-8")
                graph[root] = units
                work = repo / "work"
                work.mkdir()
                raw = export_source((("append", 191),), module, arities={191: 2})
                raw = raw.replace("return arg;}", "return ouro_ctor(0,0,0);}", 1)
                legacy = raw.replace("ouro_c191=ouro_clos(ouro_f191_,env)",
                                     'ouro_c191=ouro_fast("append")')
                emission = [legacy if bridge else raw]
                def emit_mock(_command, _bridge=bridge, _emission=emission, **kwargs):
                    if _bridge:
                        self.assertNotIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"])
                    else:
                        self.assertEqual(kwargs["env"]["OURO_EMIT_SCOPED_ARITHMETIC"], "1")
                        self.assertIn("OURO_EMIT_SCOPED_ARITHMETIC", kwargs["env"]["WSLENV"].split(":"))
                    kwargs["stdout"].write(_emission[0].encode())
                    return SimpleNamespace(returncode=0)
                with ExitStack() as stack:
                    for name, value in (("ROOT", repo),
                                        ("rel", lambda path, _repo=repo: path.relative_to(_repo).as_posix()),
                                        ("collect_units_many", lambda _roots, _graph=graph, **_options: _graph),
                                        ("collect_units", lambda selected, _graph=graph: _graph[selected]),
                                        ("ouro1_cmd", lambda _seed: ["SOURCE-mocked-compiler"])):
                        stack.enter_context(patch.object(regen, name, value))
                    stack.enter_context(patch.dict(os.environ, {"OURO_EMIT_SCOPED_ARITHMETIC": "inherited"}))
                    _graph, inputs, _signature = regen.all_frontend_inputs(seed, "16000", historical_bridge=bridge)
                    options = dict(ouro1=seed, fuel="16000", work=work, cache_enabled=True,
                                   tu_cache=repo / "cache", tag="pa", mod=module, root=root,
                                   file_name="pa.c", units=units, digests=inputs, historical_bridge=bridge)
                    calls = stack.enter_context(patch.object(regen.subprocess, "run", side_effect=emit_mock))
                    cold, warm = regen.emit_one(**options), regen.emit_one(**options)
                    self.assertEqual((cold.cache, warm.cache, calls.call_count), ("miss", "hit", 1))
                    installed = (work / "pa.c").read_text(encoding="utf-8")
                    if bridge:
                        self.assertEqual(installed, legacy)
                    else:
                        self.assertEqual(installed, raw)
                        self.assertNotIn('ouro_fast("append")', installed)
                        self.assertIn("return ouro_ctor(0,0,0);", installed)
                        self.assertNotEqual(cold.key, regen.tu_key("pa", module, root, units, inputs,
                                                                  "16000", historical_bridge=True))
                        emission[0] = legacy
                        previous = (work / "pa.c").read_bytes()
                        with self.assertRaises(RuntimeError):
                            regen.emit_one(**{**options, "cache_enabled": False})
                        self.assertEqual((work / "pa.c").read_bytes(), previous)

    def test_append_source_body_arity_layout_and_import_mutations(self):
        changes = (
            ("std/prelude.ouro", "| Nil => fun (ys : List A) => ys", "| Nil => fun (ys : List A) => Nil A"),
            ("std/prelude.ouro", "Cons A x (append xs' ys)", "Cons A x (append ys xs')"),
            ("std/prelude.ouro", "def append (A : Type)", "private def append (A : Type)"),
            ("std/prelude.ouro", "def append (A : Type)", "def append (A : Type) (B : Type)"),
            ("std/prelude.ouro", "fix append (xs : List A)", "fix append (xs : List A) (ys : List A)"),
            ("std/prelude.ouro", 'import "types.ouro";', 'import "types.ouro", "data.ouro";'),
            ("std/types.ouro", "| Nil : List A\n  | Cons : A -> List A -> List A",
             "| Cons : A -> List A -> List A\n  | Nil : List A"),
            ("std/types.ouro", "| Cons : A -> List A -> List A", "| Cons : List A -> A -> List A"),
            ("std/types.ouro", 'representation List := "ouro.list"', 'representation List := "ouro.nat"'),
            ("std/types.ouro", "| S : Nat -> Nat", "| S : Nat -> Nat -> Nat"),
            ("std/types.ouro", 'representation Nat := "ouro.nat"', 'representation Nat := "ouro.list"'),
        )
        for owner, old, new in changes:
            self.assertIn(old, SOURCES[owner])
            changed = {**SOURCES, owner: SOURCES[owner].replace(old, new, 1)}
            for installed in (False, True):
                with self.subTest(change=new, installed=installed), self.assertRaises(RuntimeError):
                    hook(arithmetic_source(fast=installed), sources=changed, installed=installed)
        for owner, _kind, name, expected in packer.PRELUDE_LIST_APPEND_SOURCE_SHAPES:
            with self.subTest(duplicate=name), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: SOURCES[owner] + expected})
            with self.subTest(missing=name), self.assertRaises(RuntimeError):
                hook(arithmetic_source(), sources={**SOURCES, owner: ""})
        trivia = SOURCES["std/prelude.ouro"] + '\ndef text : String := "def append : Nat := Z;";\n'
        self.assertEqual(hook(arithmetic_source(), sources={**SOURCES, "std/prelude.ouro": trivia}),
                         hook(arithmetic_source()))

    def test_append_owner_and_user_homonym_precision(self):
        bodies = {**SOURCES, UNITS[-1]: SOURCES[UNITS[-1]]
                  + "def append (A : Type) (xs : List A) (ys : List A) : List A := ys;\n"}
        raw = arithmetic_source().replace("return 5;", "return 6;", 1)
        raw = raw.replace('case 3:return "_ouro_m_1_append";',
                          'case 3:return "_ouro_m_1_append";case 5:return "append";')
        raw = raw.replace("case 3:return ouro_g171();", "case 3:return ouro_g171();case 5:return ouro_g191();")
        user = export_source((("append", 191),), arities={191: 2}).split("int ouro_export_count", 1)[0]
        raw = raw.replace("int ouro_export_count", user + "int ouro_export_count", 1)
        result = hook(raw, sources=bodies)
        self.assertIn('ouro_c171=ouro_fast("append")', result)
        self.assertIn("ouro_c191=ouro_clos(ouro_f191_,env)", result)
        with self.assertRaises(RuntimeError):
            hook(arithmetic_source(qualified=False), sources=bodies)
        only = (UNITS[-1],)
        plain = export_source((("append", 191),), arities={191: 2})
        self.assertEqual(hook(plain, units=only, canonical=only, sources=bodies), plain)
        with self.assertRaises(RuntimeError):
            hook(plain + '\nouro_v *other(void){return ouro_fast("append");}\n',
                 units=only, canonical=only, sources=bodies)

    def test_append_complete_family_bodies_cache_and_external_refs(self):
        raw = arithmetic_source()
        helpers = append_helpers(171).splitlines(keepends=True)
        for body in helpers:
            self.assertIn(body, raw)
            for malformed in ("", body + body, body.replace("{", "{\n", 1),
                              body.replace("ouro_cons(arg,env0)", "ouro_cons(arg,0)"),
                              body.replace("ouro_v *arg)", "ouro_v *arg,ouro_v *extra)")):
                with self.subTest(body=body[:50], malformed=malformed[:50]), self.assertRaises(RuntimeError):
                    hook(raw.replace(body, malformed, 1))
            name = re.search(r"\*(ouro_f[^ (]+)\(", body).group(1)
            with self.subTest(external=name), self.assertRaises(RuntimeError):
                hook(raw + f"ouro_v *other(void){{return {name}(0,0);}}\n")
        changed_bodies = (
            ("return ouro_get(env,0);", "return ouro_get(env,1);"),
            ("ouro_ctor(1,2,", "ouro_ctor(0,2,"),
            ("ouro_get(env,2)", "ouro_get(env,1)"),
            ("ouro_get(env,4)", "ouro_get(env,3)"),
            ("ouro_clos(ouro_f0_0_2_0_171_,env)", "ouro_fix(ouro_f0_0_2_0_171_,env)"),
            ("ouro_clos(ouro_f0_2_0_171_,env)", "ouro_clos(ouro_f0_0_2_0_171_,env)"),
            ("ouro_case(ouro_get(env,0),2,", "ouro_case(ouro_get(env,0),3,"),
            ("ouro_clos(ouro_f1_0_171_,env),ouro_clos(ouro_f2_0_171_,env)",
             "ouro_clos(ouro_f2_0_171_,env),ouro_clos(ouro_f1_0_171_,env)"),
        )
        for old, new in changed_bodies:
            family = append_helpers(171)
            self.assertIn(old, family)
            with self.subTest(body=new), self.assertRaises(RuntimeError):
                hook(raw.replace(family, family.replace(old, new, 1), 1))
        linear = export_source((("append", 171),), arities={171: 2})
        linear = linear.split("static ouro_v *ouro_c171;", 1)[0].split('\n', 1)[1]
        invalid = (
            raw.replace(append_helpers(171), linear, 1),
            raw.replace('"_ouro_m_1_append"', '"_ouro_m_0_append"'),
            raw.replace('"_ouro_m_1_append"', '"_ouro_m_01_append"'),
            raw.replace("case 3:return ouro_g171();", "case 3:return ouro_g131();"),
            raw.replace("ouro_c171=ouro_fix", "ouro_c171=ouro_clos"),
            raw + "static ouro_v *ouro_g171_d2(void){return 0;}\n",
            raw + "static ouro_v *ouro_c171_d2;\n",
            raw + "static ouro_v *ouro_f0_171_(ouro_env *env0,ouro_v *arg){return arg;}\n",
            raw + helpers[0].replace("ouro_f1_0_171_", "ouro_f1_0_171__d2"),
        )
        for text in invalid:
            with self.subTest(text=text[-90:]), self.assertRaises(RuntimeError):
                hook(text)

    def test_append_installed_getter_and_helper_drift_is_rejected(self):
        fast = arithmetic_source(fast=True)
        invalid = (
            fast.replace('ouro_fast("append")', 'ouro_fast("length")'),
            fast + '\nouro_v *other(void){return ouro_fast ( "append" );}\n',
            fast.replace("return ouro_c171;", "return ouro_c131;"),
            fast + append_helpers(171),
            fast + "ouro_v *other(void){return ouro_f0_0_2_0_171_(0,0);}\n",
        )
        for text in invalid:
            with self.subTest(text=text[-90:]), self.assertRaises(RuntimeError):
                hook(text, installed=True)
        self.assertEqual(hook(fast + append_helpers(171)), fast)
        comments = "/* ouro_f171_ */\n// ouro_f0_0_2_0_171_\n"
        self.assertEqual(hook(fast + comments, installed=True), fast + comments)


if __name__ == "__main__":
    unittest.main()
