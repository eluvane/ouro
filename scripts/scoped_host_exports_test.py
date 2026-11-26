#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from scoped_host_export_routes import FLAT_HOST_EXPORT_ROUTES, PACKED_FRONTEND_EXPORT_ROUTES
import scoped_host_exports as exports
from scoped_host_exports import (
    _cstring, _declarations, _edit_export_table_spans, _literal_prefix_matches, _scoped_label,
    scoped_host_export_aliases, scoped_host_export_original,
)
from scoped_host_export_consumers import current_native_scoped_aliases, current_packed_scoped_aliases

import bootstrap_compiler as bootstrap
import native_tool_build as native
import pack_frontend as packer
from pack_frontend import _static_symbol_matches, _static_symbol_starts

ROOT = Path(__file__).resolve().parents[1]

UNITS = ("compiler/target.ouro", "tools/entry.ouro")
SOURCES = {UNITS[0]: "def target (arg : Nat) : Nat := arg;\n",
           UNITS[1]: "private def trigger : Nat := Z;\ndef main : Nat := Z;\n"}
ROUTES = (("target", "target", (UNITS[0],)),)


def fixture_scope_closure(units, sources, *, entry=None):
    root = units[-1] if entry is None else entry

    def collect(roots, *, parse_bytes):
        assert roots == [root], roots
        for unit in units:
            parse_bytes(sources[unit].encode("utf-8"), unit)
        return {root: list(units)}
    return collect


def source(rows, module="", arities=None, default=False):
    arities = arities or {}
    parts = ['#include "ouro_rt.h"\n']
    for gid in dict.fromkeys(gid for _name, gid in rows):
        for step in reversed(range(arities.get(gid, 1))):
            suffix = "0_" * step + f"{gid}_"
            result = f"ouro_clos(ouro_f0_{suffix},env)" if step + 1 < arities.get(gid, 1) else "arg"
            parts.append(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                         f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}\n")
        parts.append(f"static ouro_v *ouro_c{gid};\n"
                     f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                     f"if(ouro_c{gid}==0){{ouro_static_begin();"
                     f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);"
                     f"ouro_static_end();}}return ouro_c{gid};}}\n")
    names = "".join(f'case {index}:return "{name}";' for index, (name, _gid) in enumerate(rows))
    values = "".join(f"case {index}:return ouro_g{gid}();" for index, (_name, gid) in enumerate(rows))
    parts.append(f"int ouro_export_count{module}(void){{return {len(rows)};}}\n")
    parts.append(f"const char *ouro_export_name{module}(int i){{switch(i){{" + names
                 + ('default:return "";}}\n' if default else '}return "";}\n'))
    parts.append(f"ouro_v *ouro_export_value{module}(int i){{switch(i){{" + values
                 + ("default:return 0;}}\n" if default else "}return 0;}\n"))
    return "".join(parts)


def normalize(text, *, units=UNITS, canonical=UNITS, sources=SOURCES,
              routes=ROUTES, module="", installed=False):
    return scoped_host_export_aliases(text, units, canonical, canonical[-1], sources,
                                      routes, module, installed=installed)


class StaticSymbolMatches(unittest.TestCase):
    def assert_match_parity(self, text, pattern, symbol):
        expected = list(re.finditer(pattern, text))
        actual = _static_symbol_matches(text, pattern, _static_symbol_starts(text), symbol)
        self.assertEqual([(match.span(), match.group(), match.groups(), match.groupdict()) for match in actual],
                         [(match.span(), match.group(), match.groups(), match.groupdict()) for match in expected])

    def test_cache_declaration_boundaries_whitespace_and_duplicate_suffixes(self):
        symbol = "ouro_c7"
        giant = "9" * 5000
        patterns = (
            (rf"\bstatic\s+ouro_v\s*\*\s*{symbol}(?:_d[0-9]+)?\b", symbol),
            (re.escape(f"static ouro_v *{symbol};"), symbol),
            (r"(?m)^static ouro_v \*ouro_c7;\r?\n", symbol),
            (r"\bstatic\s+ouro_v\s*\*\s*ouro_c7_d1\b", "ouro_c7_d1"),
        )
        texts = (
            "", "static ouro_v *ouro_c7;\n", "static\touro_v\n*\touro_c7;\r\n",
            "staticouro_v *ouro_c7;", "static ouro_v **ouro_c7;", "static ouro_v *ouro_c70;",
            "static ouro_v *ouro_c7_extra;", "static ouro_v *ouro_c7_d1_extra;",
            "notstatic ouro_v *ouro_c7;", "staticstatic ouro_v *ouro_c7;",
            "static ouro_v *ouro_c7;\nstatic ouro_v *ouro_c7;\n",
            "static ouro_v *ouro_c7_d0;\nstatic ouro_v *ouro_c7_d01;\nstatic ouro_v *ouro_c7_d1;\n",
            f"static ouro_v *ouro_c7_d{giant};\nstatic ouro_v *unrelated_d{giant};\n",
            "static ouro_v *ouro_c7é;\nstatic ouro_v *ouro_c7_d1é;\n",
            '/* static ouro_v *ouro_c7; */ "static ouro_v *ouro_c7;"',
        )
        for text in texts:
            for pattern, selected in patterns:
                with self.subTest(text=text[:120], pattern=pattern):
                    self.assert_match_parity(text, pattern, selected)

    def test_helper_body_nested_starts_and_nonoverlapping_order(self):
        symbol = "ouro_f7_"
        declaration = f"static ouro_v *{symbol}(void){{return 0;}}\n"
        patterns = (
            (rf"static ouro_v \*{symbol}\((?P<args>[^;\n]*)\)\{{(?P<body>[^\n]*)\}}\r?\n", symbol),
            (rf"(?m)^static ouro_v \*{symbol}\([^;\n]*\)\{{[^\n]*\}}\r?\n", symbol),
            (r"static ouro_v \*ouro_f7__d1\([^;\n]*\)\{[^\n]*\}\r?\n", "ouro_f7__d1"),
        )
        texts = (
            declaration, " " + declaration, "not" + declaration, declaration * 2,
            declaration.rstrip() + " " + declaration,
            f"static ouro_v *{symbol}(static ouro_v *{symbol}(void){{return 0;}}){{return 1;}}\n",
            f"static ouro_v *{symbol}(void);\n" + declaration,
            f"static ouro_v *{symbol}(void){{return 0;\n}}\n",
            f"static ouro_v *{symbol}extra(void){{return 0;}}\n" + declaration,
            "static ouro_v *ouro_f7__d1(void){return 0;}\n" + declaration,
            "static ouro_v *ouro_f7__d10(void){return 0;}\n" + declaration,
        )
        for text in texts:
            for pattern, selected in patterns:
                with self.subTest(text=text, pattern=pattern):
                    self.assert_match_parity(text, pattern, selected)

    def test_nonstatic_guards_keep_full_scan(self):
        text = '#include "ouro_rt.h"\nstatic ouro_v *ouro_c7;\n#include "ouro_rt.h"\n'
        self.assert_match_parity(text, re.escape('#include "ouro_rt.h"\n'), None)

    def test_definition_counts_preserve_word_boundaries_and_match_order(self):
        reference = re.compile(r"\bstatic\s+ouro_v\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*\{")
        declaration = "static\r\nouro_v\t* ouro_f7__d2(void) {return 0;}\n"
        prefixes = ("", "not", "static", "_", "0", "\u00e9", "\U00010400", "\u0301", "\u200d", " ", ";")
        text = "".join(prefix + declaration for prefix in prefixes)
        text += "static ouro_v *ouro_c7;\nstatic ouro_v *ouro_g7(void);\n"
        text += "static ouro_v *ouro_g7(void){return 0;}\n"
        expected = Counter(re.sub(r"_d[0-9]+$", "", name) for name in reference.findall(text))
        self.assertEqual(list(packer.StaticSymbolIndex(text).definition_counts.items()), list(expected.items()))


class ExportDeclarationMatches(unittest.TestCase):
    def assert_match_parity(self, text, pattern, prefix):
        expected = list(re.finditer(pattern, text))
        actual = _literal_prefix_matches(pattern, text, prefix)
        self.assertEqual([(match.span(), match.group(), match.groups(), match.groupdict()) for match in actual],
                         [(match.span(), match.group(), match.groups(), match.groupdict()) for match in expected])
        self.assertTrue(all(match.string is text for match in actual))

    def test_declaration_regex_parity_with_boundaries_whitespace_and_duplicates(self):
        for module in ("", "_pl"):
            for kind in ("count", "name", "value"):
                prefix = "ouro_export_" + kind + module
                argument = "void" if kind == "count" else r"int\s+i"
                pattern = rf"\b{re.escape(prefix)}\s*\({argument}\)\s*\{{"
                parameters = "void" if kind == "count" else "int i"
                header = prefix + "(" + parameters + "){"
                texts = ["", "unrelated export", header, header * 2, header + "\n" + header,
                         prefix + "_extra(" + parameters + "){", prefix + "é(" + parameters + "){",
                         prefix + "_pl(" + parameters + "){", prefix + "(wrong){",
                         prefix + "(" + parameters + ");", '/* ' + header + ' */ "' + header + '"']
                for before in ("x", "_", "é", "Ω", "漢", "²", "\U00010400", "\u0301", "\u200d", " ", "\n", ";"):
                    texts.extend((before + header, header + "\n" + before + header))
                for space in ("", " ", "\t", "\r\n", "\u00a0"):
                    args = "void" if kind == "count" else "int" + (space or " ") + "i"
                    texts.append(prefix + space + "(" + args + ")" + space + "{")
                for text in texts:
                    with self.subTest(module=module, kind=kind, text=text):
                        self.assert_match_parity(text, pattern, prefix)

    def test_candidate_matches_keep_finditer_nonoverlapping_order(self):
        prefix = "ouro_export_count"
        self.assert_match_parity(prefix + " " + prefix + "\n" + prefix,
                                 rf"\b{prefix}(?P<tail>[^\n]*)", prefix)

    def test_malformed_declaration_duplicates_are_still_rejected(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        for kind in ("count", "name", "value"):
            parameters = "void" if kind == "count" else "int\ni"
            declaration = "ouro_export_" + kind + "\n(" + parameters + ")\n{"
            with self.subTest(kind=kind), self.assertRaisesRegex(
                    RuntimeError, "missing or duplicate " + kind + " table declaration"):
                normalize(original + "\n" + declaration)


class ScopedHostExports(unittest.TestCase):
    def test_export_index_rechecks_text_suffix_and_sources(self):
        text = source((("_ouro_m_0_target", 7),)) + source((("_ouro_m_0_target", 9),), "_pl")
        export_index = exports.ScopedExportIndex()

        def getters(code, module="", sources=SOURCES):
            return exports.scoped_host_export_getters(code, UNITS, UNITS, UNITS[-1], sources, ROUTES, module,
                                                      export_index=export_index)

        with (patch.object(exports, "_scoped_label", wraps=_scoped_label) as parse,
              patch.object(exports, "_declarations", wraps=_declarations) as declarations):
            self.assertEqual(getters(text), {"target": "ouro_g7"})
            self.assertEqual(getters(text), {"target": "ouro_g7"})
            parse.assert_called_once_with("_ouro_m_0_target")
            self.assertEqual(getters(text, "_pl"), {"target": "ouro_g9"})
            self.assertEqual(getters(text), {"target": "ouro_g7"})
            declarations.assert_called_once_with(SOURCES[UNITS[0]])
        changed = text.replace("case 0:return ouro_g7();", "case 0:return ouro_g8();", 1)
        with self.assertRaisesRegex(RuntimeError, "^missing or duplicate target getter declaration$"):
            getters(changed)
        private = {**SOURCES, UNITS[0]: "private " + SOURCES[UNITS[0]]}
        with self.assertRaisesRegex(RuntimeError, "^missing, private or unsupported source declaration target in "):
            getters(text, sources=private)
        malformed = {**SOURCES, UNITS[0]: 'def target : String := "'}
        with self.assertRaisesRegex(RuntimeError, r"^compiler/target\.ouro: unsupported source lexical region$"):
            getters(text, sources=malformed)
        self.assertEqual(getters(text), {"target": "ouro_g7"})

    def test_installed_name_presence_preserves_nonoverlapping_matches(self):
        text = ('case 1:return "outer case 2:return "inner";'
                'case ٣:\treturn "visible";'
                'case 4:return "label case 5:return ouro_g7();";'
                'case 6:return ""; case 7:return "end";')
        view = native.installed_hook_view(text, include_presence=True)
        expected = set(re.findall(r'case\s+\d+:\s*return\s+"([^"]+)"', text))
        self.assertEqual(view["present_names"], expected)
        self.assertEqual(view["names"]["inner"], ["2"])
        self.assertNotIn("inner", view["present_names"])
        self.assertEqual(view["values"]["5"], ["ouro_g7"])

    def test_checked_getter_rewrites_keep_include_order(self):
        include = '#include "ouro_rt.h"\n'
        hooks = (
            ("compile_checked_units", native.hook_checked_units_getter),
            ("compile_checked_units_with_source_packet", native.hook_checked_source_packet_getter),
        )
        for export, hook in hooks:
            wrapper = f"ouro_fe_{export}_clos"
            declaration = f"ouro_v *{wrapper}(void);\n"
            body = source(((export, 7),)).removeprefix(include)
            getter_start = body.index("static ouro_v *ouro_g7(void)")
            getter = body[getter_start:body.index("\n", getter_start)]
            replacement = f"static ouro_v *ouro_g7(void){{if(ouro_c7==0)ouro_c7={wrapper}();return ouro_c7;}}"
            layouts = (
                ("adjacent", body[:getter_start] + include + body[getter_start:]),
                ("late", body + include),
                ("missing", body),
                ("declared", include + declaration + body),
            )
            for layout, text in layouts:
                with self.subTest(export=export, layout=layout):
                    expected = text.replace(getter, replacement, 1)
                    if layout != "declared":
                        expected = expected.replace(include, include + declaration, 1)
                    self.assertEqual(hook(text), expected)

    def test_installed_hooks_build_static_positions_only_when_needed(self):
        units = ("compiler/module_names_base.ouro", "compiler/native/x64.ouro")
        original = source((("module_invalid_maps", 7), ("x64_encode", 8)), arities={7: 3})
        with tempfile.TemporaryDirectory() as folder:
            generated = Path(folder) / "tool.gen.c"
            generated.write_text(original, encoding="utf-8")
            native.hook_compile_checked_units(generated, units)
            installed = generated.read_text(encoding="utf-8")
            with (patch.object(packer, "_static_symbol_starts", wraps=_static_symbol_starts) as starts,
                  patch.object(native, "_static_symbol_starts", side_effect=starts, create=True)):
                native.hook_compile_checked_units(generated, ("tools/entry.ouro",), installed=True,
                                                  source_text=source((("main", 2),)))
                starts.assert_not_called()
                native.hook_compile_checked_units(generated, units, installed=True, source_text=installed)
                starts.assert_called_once_with(installed)
                self.assertEqual(generated.read_text(encoding="utf-8"), installed)
                for duplicate, message in (
                    ("static ouro_v *ouro_g8(void){return 0;}\n",
                     "^missing, malformed or duplicate installed x64_encode getter$"),
                    ("static ouro_v *ouro_g7(void){return 0;}\n",
                     "^missing, malformed or duplicate module pure scope module_invalid_maps getter declaration$"),
                ):
                    tampered = installed + duplicate
                    starts.reset_mock()
                    with self.assertRaisesRegex(RuntimeError, message):
                        native.hook_compile_checked_units(generated, units, installed=True, source_text=tampered)
                    starts.assert_called_once_with(tampered)

    def test_crypto_scope_wraps_only_the_canonical_compression_getter(self):
        owner, entry = "std/crypto.ouro", "tools/entry.ouro"
        units = [owner, entry]
        definitions = {path: "def sha_compress (x : Nat) (y : Nat) : Nat := add x y;\n"
                       for path in units}
        original = source((("_ouro_m_0_sha_compress", 7), ("sha_compress", 8)),
                          arities={7: 2, 8: 2})
        closure = fixture_scope_closure(units, definitions)
        with patch.object(native.frontend, "collect_units_many", side_effect=closure):
            installed = native.hook_emission_scopes(original, units)
            self.assertIn("ouro_c7=ouro_wrap_quality_pure(ouro_clos(ouro_f7_,env));", installed)
            self.assertIn("ouro_c8=ouro_clos(ouro_f8_,env);", installed)
            header = '#include "ouro_quality_scope.h"\n'
            cache = "static ouro_v *ouro_c7;\n"
            invalid = (
                ("unwrapped getter", original),
                ("header after preamble", installed.replace(header, "", 1) + header),
                ("duplicate cache", installed.replace(cache, cache + cache, 1)),
            )
            with patch.object(native, "installed_hook_view", side_effect=AssertionError("scoped getter was already resolved")):
                self.assertEqual(native.hook_emission_scopes(installed, units, installed=True), installed)
                for name, text in invalid:
                    with self.subTest(name=name), self.assertRaisesRegex(
                            RuntimeError, "^missing, malformed or duplicate installed sha_compress getter$"):
                        native.hook_emission_scopes(text, units, installed=True)

    def test_exact_append_and_identity(self):
        for module, default in (("", False), ("_pl", True)):
            with self.subTest(module=module):
                original = source((("_ouro_m_0_target", 7), ("main", 2)), module, default=default)
                result = normalize(original, module=module)
                expected = original.replace("return 2;", "return 3;", 1)
                expected = expected.replace('case 1:return "main";',
                                            'case 1:return "main";case 2:return "target";', 1)
                expected = expected.replace("case 1:return ouro_g2();",
                                            "case 1:return ouro_g2();case 2:return ouro_g7();", 1)
                self.assertEqual(result, expected)
                self.assertEqual(normalize(result, module=module, installed=True), result)
                with self.assertRaises(RuntimeError):
                    normalize(result, module=module)

    def test_legacy_and_root_identity(self):
        original = source((("target", 7), ("main", 2)))
        self.assertEqual(normalize(original), original)
        units = (UNITS[0], "std/unrelated_io.ouro", UNITS[-1])
        bodies = {**SOURCES, units[1]:
                  "def emit : IO Unit := do io_pure Unit MkUnit; io_unit\n"
                  "def read : IO String := prim_stdin_read_line\n"
                  "def concat : String -> String -> String := prim_string_concat\n"}
        self.assertEqual(normalize(original, units=units, canonical=units, sources=bodies), original)
        bodies[units[1]] += "def target : Nat := Z;\n"
        with self.assertRaises(RuntimeError):
            normalize(original, units=units, canonical=units, sources=bodies)
        qualified = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(qualified)
        for text, verifying in ((qualified, False), (installed, True)):
            with self.subTest(installed=verifying), self.assertRaises(RuntimeError):
                normalize(text, sources={**SOURCES, UNITS[0]: bodies[units[1]]}, installed=verifying)
        routes = (("main", "main", (UNITS[-1],)),)
        self.assertEqual(normalize(source((("main", 2),)), routes=routes), source((("main", 2),)))

    def test_absent_owner_is_optional_only_without_bare_export(self):
        routes = (("target", "target", ("compiler/absent.ouro",)),)
        original = source((("main", 2),))
        self.assertEqual(normalize(original, routes=routes), original)
        with self.assertRaises(RuntimeError):
            normalize(source((("target", 7),)), routes=routes)

    def test_mandatory_consumers_and_packed_entry(self):
        units = (UNITS[0], "tools/native_build.ouro")
        sources = {units[0]: SOURCES[UNITS[0]], units[-1]: SOURCES[UNITS[-1]]}
        original = source((("main", 2),))
        with self.assertRaises(RuntimeError):
            current_native_scoped_aliases(original, units, units, units[-1], sources)
        with self.assertRaises(RuntimeError):
            current_packed_scoped_aliases(original, UNITS, UNITS, UNITS[-1], SOURCES, "_pl")

    def test_frontend_emission_closes_scoped_exports_and_rechecks_the_cache(self):
        import frontend_regen as frontend

        owner, entry = packer.MODULE_PURE_SCOPE_OWNER, "compiler/parse_a.ouro"
        names = [name for name, _arity in packer.MODULE_PURE_SCOPE_ARITIES]
        rows = [(f"_ouro_m_0_{name}", 10 + index) for index, name in enumerate(names)]
        rows.append(("parse_a", 21))
        arities = {10 + index: arity for index, (_name, arity) in enumerate(packer.MODULE_PURE_SCOPE_ARITIES)}
        original = source(rows, "_pa", arities=arities)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "compiler").mkdir()
            (work / owner).write_text("".join(f"def {name} : Nat := Z;\n" for name in names), encoding="utf-8")
            (work / entry).write_text("def parse_a : Nat := Z;\n", encoding="utf-8")
            cache = work / "cache"
            cache.mkdir()
            bindings = {name: {"selected": False} for name in (
                "module_lookup", "lower_local_lookup", "source_name_compare_scope", "elem_scope", "prelude_arithmetic",
            )}

            def emit(command, *, stdout, **_options):
                stdout.write(original.encode())
                return subprocess.CompletedProcess(command, 0)

            with (patch.object(frontend, "ROOT", work), patch.object(frontend, "_tu_scope_bindings", return_value=bindings),
                  patch.object(frontend, "_tu_key_inputs", return_value={"lower_ctor_lookup": {"selected": False}}),
                  patch.object(frontend, "ouro1_cmd", return_value=["fixture"]),
                  patch.object(frontend.subprocess, "run", side_effect=emit) as emitted):
                options = dict(ouro1=work / "seed", fuel="100", work=work, cache_enabled=True, tu_cache=cache,
                               tag="pa", mod="_pa", root=entry, file_name="pa.c", units=[owner, entry],
                               digests={}, close_exports=True)
                cold = frontend.emit_one(**options)
                installed = (work / "pa.c").read_text(encoding="utf-8")
                self.assertIn('return "module_members";', installed)
                self.assertIn("ouro_wrap_module_pure_scope(ouro_clos(ouro_f10_,env),7)", installed)
                self.assertEqual(frontend.emit_one(**options).cache, "hit")
                self.assertEqual((work / "pa.c").read_text(encoding="utf-8"), installed)
                emitted.assert_called_once()

                index = exports.ScopedExportIndex().tables_for(installed, "_pa").labels["module_members"]
                cached = cache / f"_pa_{cold.key}.c"
                cached.write_text(installed.replace(f"case {index}:return ouro_g10();", f"case {index}:return ouro_g21();"),
                                  encoding="utf-8")
                frontend.record_cached_output(cached, cold.key)
                with self.assertRaises(RuntimeError):
                    frontend.emit_one(**options)
                self.assertEqual((work / "pa.c").read_text(encoding="utf-8"), installed)

    def test_missing_private_or_duplicate_source_declaration(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        for body in ("", "private def target : Nat := Z;\n",
                     "def target : Nat := Z;\ndef target : Nat := Z;\n"):
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                normalize(original, sources={**SOURCES, UNITS[0]: body})
        with self.assertRaises(RuntimeError):
            normalize(source((("main", 2),)))

    def test_private_trivia_and_unsupported_heads_refuse(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(original)
        for body in (
            "private -- modifier comment\ndef target : Nat := Z;\n",
            "private\n-- modifier comment\n\n  def target : Nat := Z;\n",
            "private\r\n-- modifier comment\r\n\tdef\r\n target : Nat := Z;\r\n",
            "private; def target : Nat := Z;\n",
            "private private def target : Nat := Z;\n",
            "def prior : Nat := match True with | True => Z | False => Z end\n"
            "private -- modifier comment\ndef target : Nat := Z;\n",
            "def prior : Nat := match True with | True => Z | False => Z end\n"
            "unknown def target : Nat := Z;\n",
            "def prior : Nat := match True with | True => Z | False => Z end\n"
            "public def target : Nat := Z;\n",
            "public def target : Nat := Z;\n",
            "unknown def target : Nat := Z;\n",
            "def target' : Nat := Z;\n",
            'def text : String := "unterminated\ndef target : Nat := Z;\n',
            'def text : String := r#"unterminated\ndef target : Nat := Z;\n',
            'def text : String := """\n  def target : Nat := Z;\n',
        ):
            for text, verifying in ((original, False), (installed, True)):
                with self.subTest(body=body, installed=verifying), self.assertRaises(RuntimeError):
                    normalize(text, sources={**SOURCES, UNITS[0]: body}, installed=verifying)

    def test_public_heads_and_opaque_literals(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        for body in (
            "-- private def target : Nat := Z;\ndef target : Nat := Z;\n",
            "def\n-- header comment\n target : Nat := Z;\n",
            "private -- modifier comment\ndef unrelated : Nat := Z;\ndef target : Nat := Z;\n",
            "private axiom hidden : Nat;\ndef target : Nat := Z;\n",
            "def prior : Nat := match True with | True => Z | False => Z end\ndef target : Nat := Z;\n",
            "def prior : IO Unit := do let! value := io_pure Unit MkUnit;\n"
            "  match True with | True => io_pure Unit value | False => io_pure Unit value end\n"
            "-- declaration separator\ndef target : Nat := Z;\n",
            'def text : String := "private -- fake def target";\ndef target : Nat := Z;\n',
            'def text : String := r#"private -- fake\ndef target : Nat := Z;"#;\ndef target : Nat := Z;\n',
            'def text : String := """\n  private def target : Nat := Z;\n  """;\ndef target : Nat := Z;\n',
            'def text : Bytes := b"private -- fake def target";\ndef target : Nat := Z;\n',
            "def char : Char := 'd';\ndef target : Nat := Z;\n",
            "def earlier' : Nat := Z;\ndef target : Nat := Z;\n",
        ):
            with self.subTest(body=body):
                result = normalize(original, sources={**SOURCES, UNITS[0]: body})
                self.assertIn('case 2:return "target";', result)
                self.assertIn("case 2:return ouro_g7();", result)
                self.assertEqual(normalize(result, sources={**SOURCES, UNITS[0]: body}, installed=True), result)

    def test_wrong_owner_ordinal_and_malformed_ordinal(self):
        for name in ("_ouro_m_1_target", "_ouro_m_9_target", "_ouro_m_00_target", "_ouro_m_x_target",
                     "_ouro_m__target", "_ouro_m_-1_target", "_ouro_m_0x0_target"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                normalize(source(((name, 7), ("main", 2))))
        bad = source((("_ouro_m_0_target", 7), ("_ouro_m_00_target", 8), ("main", 2)))
        with self.assertRaises(RuntimeError):
            normalize(bad)

    def test_scoped_labels_are_indexed_once_and_checked_in_table_order(self):
        sources = {**SOURCES, UNITS[0]: SOURCES[UNITS[0]] + "def second : Nat := Z;\n"}
        routes = ROUTES + (("second", "second", (UNITS[0],)),)
        rows = (("_ouro_m_0_target", 7), ("_ouro_m_0_second", 8),
                ("_ouro_m_bad_unrelated", 9), ("main", 2))
        original = source(rows)
        with patch.object(exports, "_scoped_label", wraps=_scoped_label) as parse:
            installed = normalize(original, sources=sources, routes=routes)
        self.assertEqual([call.args[0] for call in parse.call_args_list], [name for name, _getter in rows])
        self.assertEqual(scoped_host_export_original(installed, UNITS, UNITS, UNITS[-1], sources, routes), original)

        wrong, malformed = ("_ouro_m_1_target", 11), ("_ouro_m_bad_target", 12)
        for other_rows, message in (((wrong, malformed), "wrong owner or ordinal target"),
                                    ((malformed, wrong), "malformed source ordinal target")):
            with self.subTest(rows=other_rows), self.assertRaisesRegex(RuntimeError, message):
                normalize(source(rows + other_rows), sources=sources, routes=routes)

    def test_complete_basename_prevents_suffix_homonym_confusion(self):
        units = ("compiler/driver.ouro", "compiler/pipeline.ouro", UNITS[-1])
        sources = {units[0]: "def compile_checked_source : Nat := Z;\n",
                   units[1]: "def pipeline_compile_checked_source : Nat := Z;\n",
                   units[-1]: SOURCES[UNITS[-1]]}
        routes = (("compile_checked_source", "compile_checked_source", (units[0],)),)
        original = source((("_ouro_m_0_compile_checked_source", 7),
                           ("_ouro_m_1_pipeline_compile_checked_source", 8), ("main", 2)))
        result = normalize(original, units=units, canonical=units, sources=sources, routes=routes)
        self.assertIn('case 1:return "_ouro_m_1_pipeline_compile_checked_source";', result)
        self.assertIn('case 3:return "compile_checked_source";', result)
        self.assertIn("case 3:return ouro_g7();", result)
        self.assertEqual(normalize(result, units=units, canonical=units, sources=sources,
                                   routes=routes, installed=True), result)
        original = source((("compile_checked_source", 7),
                           ("_ouro_m_1_pipeline_compile_checked_source", 8), ("main", 2)))
        self.assertEqual(normalize(original, units=units, canonical=units, sources=sources,
                                   routes=routes), original)

    def test_homonym_keeps_qualified_identity_and_conflicting_bare_fails(self):
        units = (UNITS[0], "compiler/homonym.ouro", UNITS[1])
        sources = {**SOURCES, units[1]: "private def target : Nat := Z;\n"}
        original = source((("_ouro_m_0_target", 7), ("_ouro_m_1_target", 8), ("main", 2)))
        result = normalize(original, units=units, canonical=units, sources=sources)
        self.assertIn('case 3:return "target";', result)
        self.assertIn("case 3:return ouro_g7();", result)
        with self.assertRaises(RuntimeError):
            normalize(source((("target", 7), ("main", 2))), units=units, canonical=units, sources=sources)
        sources = {**sources, units[-1]: SOURCES[units[-1]] + "def target : Nat := Z;\n"}
        with self.assertRaises(RuntimeError):
            normalize(source((("_ouro_m_0_target", 7), ("target", 2))),
                      units=units, canonical=units, sources=sources)

    def test_alternative_owner_and_route_duplicates_fail(self):
        units = (UNITS[0], "compiler/alternative.ouro", UNITS[1])
        sources = {**SOURCES, units[1]: "def target : Nat := Z;\n"}
        routes = (("target", "target", units[:2]),)
        with self.assertRaises(RuntimeError):
            normalize(source((("_ouro_m_0_target", 7),)), units=units,
                      canonical=units, sources=sources, routes=routes)
        with self.assertRaises(RuntimeError):
            normalize(source((("_ouro_m_0_target", 7),)), routes=ROUTES + ROUTES)

    def test_ordered_complete_closure_and_suffix_fail_closed(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        for units in (UNITS[::-1], UNITS[:1], (*UNITS, UNITS[-1]),
                      ("../compiler/target.ouro", UNITS[-1]), (*UNITS, "extra.ouro")):
            with self.subTest(units=units), self.assertRaises(RuntimeError):
                normalize(original, units=units)
        with self.assertRaises(RuntimeError):
            normalize(original, sources={UNITS[0]: SOURCES[UNITS[0]]})
        with self.assertRaises(RuntimeError):
            normalize(original, module="_pl;bad")

    def test_malformed_tables_getter_injectivity_and_strings(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        cases = (
            original.replace("return 2;", "return 3;", 1),
            original.replace("case 1:", "case 0:", 1),
            original.replace("case 1:", "case 01:", 1),
            original.replace('return "main";', 'return "_ouro_m_0_target";', 1),
            original.replace('return "main";', 'return "\\137ouro_m_0_target";', 1),
            original.replace('return "main";', 'return "bad\\000label";', 1),
            original.replace("case 1:return ouro_g2();", "case 1:return ouro_g7();", 1),
            original.replace("static ouro_v *ouro_g7(void){", "static ouro_v *removed7(void){", 1),
            original + "int ouro_export_count(void) { return 2; }\n",
            original + "const char *ouro_export_name(int i) { return 0; }\n",
            original + "ouro_v *ouro_export_value(int i) { return 0; }\n",
            original + "static ouro_v *ouro_g7(void){return 0;}\n",
        )
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                normalize(bad)

    def test_export_labels_decode_raw_text_and_escapes(self):
        self.assertEqual(_cstring("_ouro_m_0_target"), "_ouro_m_0_target")
        self.assertEqual(_cstring("café"), "café")
        self.assertEqual(_cstring(r"\137ouro_m_0_target"), "_ouro_m_0_target")
        self.assertEqual(_cstring(r"caf\xc3\xa9"), "café")
        for bad in ("bad\0label", r"bad\000label"):
            with self.subTest(label=bad), self.assertRaisesRegex(RuntimeError, "NUL in export label"):
                _cstring(bad)

    def test_multiple_getter_declarations_keep_exact_output(self):
        names = ("target_zero", "target_short", "target_prefix", "target_long")
        gids = (0, 7, 71, 713)
        sources = {**SOURCES, UNITS[0]: "".join(f"def {name} : Nat := Z;\n" for name in names)}
        routes = tuple((name, name, (UNITS[0],)) for name in names)
        rows = tuple((f"_ouro_m_0_{name}", gid) for name, gid in zip(names, gids, strict=True))
        original = source((*rows, ("main", 9999)))
        original += "static ouro_v *ouro_g07(void){return 0;}\n"
        original += "static ouro_v *ouro_g7_extra(void){return 0;}\n"
        original += "static ouro_v *ouro_g700(void){return 0;}\n"
        for gid in gids:
            original = original.replace(f"static ouro_v *ouro_g{gid}(void){{",
                                        f"static\r\nouro_v\t* \touro_g{gid}\r\n(void)\t{{", 1)
        expected = original.replace("return 5;", "return 9;", 1)
        added_names = "".join(f'case {5 + index}:return "{name}";' for index, name in enumerate(names))
        added_values = "".join(f"case {5 + index}:return ouro_g{gid}();" for index, gid in enumerate(gids))
        expected = expected.replace('case 4:return "main";', 'case 4:return "main";' + added_names, 1)
        expected = expected.replace("case 4:return ouro_g9999();", "case 4:return ouro_g9999();" + added_values, 1)
        result = normalize(original, sources=sources, routes=routes)
        self.assertEqual(result, expected)
        self.assertEqual(normalize(result, sources=sources, routes=routes, installed=True), result)

    def test_getter_declaration_mutations_are_rechecked(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(original)
        duplicates = (
            "static ouro_v *ouro_g7(void){return 0;}\n",
            "static\r\nouro_v\t* \touro_g7\r\n(void)\t{return 0;}\n",
        )
        word_prefixes = ("not", "_", "0", "static", "\u00e9", "\u00b2", "\U00010400")
        decoys = "".join(prefix + duplicates[0] for prefix in word_prefixes)
        for text, verifying in ((original, False), (installed, True)):
            self.assertEqual(normalize(text + decoys, installed=verifying), installed + decoys)
            invalid = [text.replace("static ouro_v *ouro_g7(void){", "static ouro_v *ouro_g71(void){", 1),
                       text.replace("static ouro_v *ouro_g7(void){", "static ouro_v *ouro_g7(int arg){", 1),
                       text.replace("static ouro_v *ouro_g7(void){", "static ouro_v *ouro_g7(void);{", 1),
                       *(text + duplicate for duplicate in duplicates),
                       *(text + prefix + duplicates[0] for prefix in (" ", ";", "\u0301", "\u200d"))]
            for index, changed in enumerate(invalid):
                with self.subTest(installed=verifying, mutation=index), self.assertRaisesRegex(
                        RuntimeError, "missing or duplicate target getter declaration"):
                    normalize(changed, installed=verifying)

    def test_installed_cache_binding(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(original)
        cases = (
            original,
            installed.replace("case 2:return ouro_g7();", "case 2:return ouro_g2();", 1),
            installed.replace('case 2:return "target";', 'case 2:return "stale";', 1),
            installed.replace('case 2:return "target";', 'case 4:return "target";', 1),
            installed.replace('case 0:return "_ouro_m_0_target";', 'case 0:return "_ouro_m_1_target";', 1),
        )
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                normalize(bad, installed=True)
        with self.assertRaises(RuntimeError):
            normalize(installed, sources={**SOURCES, UNITS[0]: "private def target : Nat := Z;\n"},
                      installed=True)

    def test_original_projection_preserves_exact_tables(self):
        for module, default in (("", False), ("_pl", True)):
            with self.subTest(module=module):
                original = source((("_ouro_m_0_target", 7), ("main", 2)), module, default=default)
                installed = normalize(original, module=module)
                result = scoped_host_export_original(installed, UNITS, UNITS, UNITS[-1], SOURCES, ROUTES, module)
                self.assertEqual(result, original)
        original = source((("target", 7), ("main", 2)))
        self.assertIs(scoped_host_export_original(original, UNITS, UNITS, UNITS[-1], SOURCES, ROUTES), original)

    def test_export_table_edits_keep_reverse_splice_order(self):
        text = "prefixabcdefghij"
        for edits in ([(6, 8, "XY"), (9, 11, ""), (11, 11, "Δ")],
                      [(6, 13, "XY"), (9, 11, ""), (11, 11, "Δ"), (11, 11, "Z")]):
            expected = text
            for low, high, replacement in sorted(edits, reverse=True):
                expected = expected[:low] + replacement + expected[high:]
            self.assertEqual(_edit_export_table_spans(text, edits), expected)

    def test_original_projection_keeps_installed_refusals_and_error_order(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(original)
        private = {**SOURCES, UNITS[0]: "private def target : Nat := Z;\n"}
        cases = (
            (original, SOURCES),
            (installed.replace("case 2:return ouro_g7();", "case 2:return ouro_g2();", 1), SOURCES),
            (installed.replace('case 2:return "target";', 'case 2:return "stale";', 1), SOURCES),
            (installed.replace('case 2:return "target";', 'case 4:return "target";', 1), SOURCES),
            (installed + "\nouro_export_count(void) {", SOURCES),
            (installed + "\nouro_export_count(void) {", private),
            (installed, private),
        )
        for index, (text, sources) in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(RuntimeError) as expected:
                    normalize(text, sources=sources, installed=True)
                with self.assertRaises(RuntimeError) as actual:
                    scoped_host_export_original(text, UNITS, UNITS, UNITS[-1], sources, ROUTES)
                self.assertEqual(str(actual.exception), str(expected.exception))

    def test_original_projection_rechecks_source_and_getter_mutations(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        installed = normalize(original)
        sources = dict(SOURCES)
        self.assertEqual(scoped_host_export_original(installed, UNITS, UNITS, UNITS[-1], sources, ROUTES), original)
        sources[UNITS[0]] = "private def target : Nat := Z;\n"
        with self.assertRaisesRegex(RuntimeError, "missing, private or unsupported source declaration"):
            scoped_host_export_original(installed, UNITS, UNITS, UNITS[-1], sources, ROUTES)
        duplicate = installed + "static ouro_v *ouro_g7(void){return 0;}\n"
        with self.assertRaisesRegex(RuntimeError, "missing or duplicate target getter declaration"):
            scoped_host_export_original(duplicate, UNITS, UNITS, UNITS[-1], SOURCES, ROUTES)

    def test_flat_and_packed_elaborator_owners(self):
        units = ("compiler/file_elab_lookup.ouro", "compiler/elab.ouro", UNITS[-1])
        sources = {units[0]: "def elaborate : Nat := Z;\n",
                   units[1]: "def elaborate : Nat := Z;\ndef elaborate_fuel : Nat := Z;\n",
                   units[-1]: SOURCES[UNITS[-1]]}
        flat = (("elaborate", "elaborate", (units[0],)),)
        packed = (("elaborate_fuel", "elaborate_fuel", (units[1],)),)
        original = source((("_ouro_m_0_elaborate", 7), ("_ouro_m_1_elaborate", 8),
                           ("_ouro_m_1_elaborate_fuel", 9)))
        self.assertIn("case 3:return ouro_g7();", normalize(original, units=units, canonical=units,
                                                         sources=sources, routes=flat))
        original = source((("_ouro_m_1_elaborate_fuel", 9),), "_el")
        self.assertIn("case 1:return ouro_g9();", normalize(original, units=units, canonical=units,
                                                         sources=sources, routes=packed, module="_el"))

    def test_prepare_lookup_hook_owners(self):
        expected = (
            ("check_environment_from_entries", "ouro_wrap_check_environment_from_entries",
             ("compiler/file_check_environment.ouro",)),
            ("managed_source_symbol_using", "ouro_wrap_managed_source_symbol_using",
             ("compiler/native/managed_model.ouro",)),
            ("managed_source_spelling", "ouro_wrap_managed_source_spelling",
             ("compiler/native/managed_model.ouro",)),
        )
        for name, wrapper, owners in expected:
            with self.subTest(name=name):
                self.assertIn((name, wrapper, owners), native.HOST_HOOKS)
                self.assertIn((name, name, owners), FLAT_HOST_EXPORT_ROUTES)
                units = (owners[0], "tests/homonym.ouro", UNITS[-1])
                sources = {unit: f"def {name} : Nat := Z;\n" for unit in units}
                route = ((name, name, owners),)
                original = source(((f"_ouro_m_0_{name}", 7), (f"_ouro_m_1_{name}", 8)))
                installed = normalize(original, units=units, canonical=units, sources=sources, routes=route)
                self.assertIn("case 2:return ouro_g7();", installed)
                with self.assertRaises(RuntimeError):
                    normalize(source(((name, 7),)), units=units, canonical=units, sources=sources, routes=route)

    def test_frontend_link_lookups_have_packed_routes(self):
        runtime = (ROOT / "runtime/frontend_link.c").read_text(encoding="utf-8")
        lookups = re.findall(r'\bFIND(?:_OPTIONAL)?\(\s*(\w+)\s*,\s*"(\w+)"\s*\)', runtime)
        self.assertTrue(lookups)
        routes = {(module, alias) for module, alias, _name, _owners in PACKED_FRONTEND_EXPORT_ROUTES}
        self.assertFalse({("_" + module, name) for module, name in lookups} - routes)

    def test_preflight_routes_bind_the_compiler_getters(self):
        owner, entry = "compiler/compiler.ouro", UNITS[-1]
        units = (owner, entry)
        sources = {owner: (ROOT / owner).read_text(encoding="utf-8"), entry: SOURCES[entry]}
        names = ("compile_program_with_location_with", "compile_program_with_location_indexed_with")
        rows = tuple((f"_ouro_m_0_{name}", getter) for getter, name in enumerate(names, 7))
        packed = tuple((alias, name, owners) for module, alias, name, owners in PACKED_FRONTEND_EXPORT_ROUTES
                       if module == "_co")
        for module, inventory in (("", FLAT_HOST_EXPORT_ROUTES), ("_co", packed)):
            with self.subTest(module=module):
                routes = tuple(route for route in inventory if route[0] in names)
                self.assertEqual(len(routes), len(names))
                original = source(rows + (("main", 2),), module)
                options = {"units": units, "canonical": units, "sources": sources,
                           "routes": routes, "module": module}
                installed = normalize(original, **options)
                for getter, name in enumerate(names, 7):
                    match = re.search(rf'case (\d+):return "{name}";', installed)
                    self.assertIsNotNone(match)
                    self.assertIn(f"case {match[1]}:return ouro_g{getter}();", installed)
                self.assertEqual(normalize(installed, installed=True, **options), installed)

    def test_closed_inventory_and_existing_full_hooks(self):
        aliases = [alias for alias, _name, _owners in FLAT_HOST_EXPORT_ROUTES]
        self.assertEqual(len(aliases), 190)
        self.assertEqual(len(set(aliases)), 190)
        self.assertEqual(len(PACKED_FRONTEND_EXPORT_ROUTES), 69)
        self.assertFalse({"expect_tag", "expect_keyword"}.intersection(aliases))
        self.assertTrue({"compile_checked_from_decls_with_origin", "compile_checked_from_decls_with_source_packet",
                         "module_resolve_units", "module_resolve_units_with_slots", "live_runtime_calls",
                         "live_runtime_reclaim", "lower_expr_env2", "compile_program"}.issubset(aliases))
        for name, _wrapper, owners in native.HOST_HOOKS:
            self.assertIn((name, name, owners), FLAT_HOST_EXPORT_ROUTES)
        scopes = (*((name, arity, packer.MODULE_PURE_SCOPE_OWNER)
                    for name, arity in packer.MODULE_PURE_SCOPE_ARITIES),
                  packer.MODULE_REWRITE_UNIT_PURE_SCOPE,
                  packer.MODULE_REWRITE_CACHED_UNIT_PURE_SCOPE,
                  *((name, arity, owner) for name, arity, _prefix, owner, _wrapper
                    in packer.MODULE_PURE_SCOPE_PREFIXES))
        arities = {name: arity for name, arity, _owner in scopes}
        entry = "tests/frontend_host_codegen.ouro"
        owners = sorted({owners[0] for _alias, _name, owners in FLAT_HOST_EXPORT_ROUTES} - {entry})
        units = (*owners, entry)
        sources = {owner: "" for owner in units}
        rows, gids, curry = [], {}, {}
        for index, (alias, name, owners) in enumerate(FLAT_HOST_EXPORT_ROUTES):
            owner, gid = owners[0], 31 + index * 97
            sources[owner] += f"def {name} (arg : Nat) : Nat := arg;\n"
            rows.append((name if owner == entry else f"_ouro_m_{units.index(owner)}_{name}", gid))
            gids[alias], curry[gid] = gid, arities.get(name, 1)
        sources[entry] += "private def trigger : Nat := Z;\ndef main : Nat := Z;\n"
        rows.append(("main", 99999))
        for module in ("", "_pl"):
            original = source(rows, module, arities=curry)
            aliases = (normalize(original, units=units, canonical=units, sources=sources,
                                 routes=FLAT_HOST_EXPORT_ROUTES, module=module) if module else
                       current_native_scoped_aliases(original, units, units, entry, sources))
            if module:
                hooked = packer.hook_module_pure_scopes(aliases, units, module)
                self.assertEqual(packer.hook_module_pure_scopes(hooked, units, module, installed=True), hooked)
            else:
                with tempfile.TemporaryDirectory() as folder:
                    output = Path(folder) / "hooks.c"
                    output.write_text(aliases, encoding="utf-8")
                    native.hook_compile_checked_units(output, units)
                    hooked = output.read_text(encoding="utf-8")
                self.assertEqual(hooked.count("=ouro_fe_compile_checked_units_clos();"), 1)
                self.assertEqual(hooked.count("=ouro_fe_compile_checked_units_with_source_packet_clos();"), 1)
                for name, wrapper, _owners in native.HOST_HOOKS:
                    self.assertIn(f"ouro_c{gids[name]}={wrapper}(ouro_clos(", hooked)
            self.assertEqual(normalize(hooked, units=units, canonical=units, sources=sources,
                                       routes=FLAT_HOST_EXPORT_ROUTES, module=module, installed=True), hooked)
            for index, (label, gid) in enumerate(rows):
                self.assertIn(f'case {index}:return "{label}";', hooked)
                self.assertIn(f"case {index}:return ouro_g{gid}();", hooked)
            broken = aliases.replace(f"ouro_clos(ouro_f0_{gids['module_members']}_,env)", "arg", 1)
            with self.assertRaises(RuntimeError):
                packer.hook_module_pure_scopes(broken, units, module)

    def test_native_emit_failure_never_publishes_partial_output(self):
        original = source((("_ouro_m_0_target", 7), ("main", 2)))
        for late in (False, True):
            with self.subTest(late=late), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / "accepted.c"
                output.write_bytes(b"previous complete output\n")
                events = []

                def run(argv, *, recorded=events, **kwargs):
                    if "stdout" in kwargs:
                        recorded.append("compiler")
                        kwargs["stdout"].write(original.encode())
                    else:
                        recorded.append("uniquify")
                        self.assertIn("--uniquify-only", argv)
                    return subprocess.CompletedProcess(argv, 0)

                def aliases(text, units, canonical_units, entry, sources, *, recorded=events, delayed=late, **_kwargs):
                    recorded.append("aliases")
                    routes = ROUTES if delayed else ROUTES + (("missing", "missing", (UNITS[0],)),)
                    return scoped_host_export_aliases(text, units, canonical_units, entry, sources, routes)

                def hook(_path, units, *, source_text, recorded=events):
                    recorded.append("hooks")
                    self.assertEqual(tuple(units), UNITS)
                    self.assertIn('case 2:return "target";', source_text)
                    self.assertIn("case 2:return ouro_g7();", source_text)
                    raise RuntimeError("late host hook refusal")

                closure = fixture_scope_closure(UNITS, SOURCES)
                with patch.object(native, "ROOT", ROOT), \
                     patch.object(native.frontend, "collect_units_many", side_effect=closure) as collector, \
                     patch.object(native.frontend, "ouro1_cmd", return_value=["synthetic-seed"]), \
                     patch.object(native.subprocess, "run", side_effect=run), \
                     patch.object(native, "current_native_scoped_aliases", side_effect=aliases), \
                     patch.object(native, "hook_compile_checked_units", side_effect=hook):
                    with self.assertRaises(RuntimeError):
                        native.emit(Path("synthetic-seed"), list(UNITS), 200000, output)
                collector.assert_called_once()
                self.assertEqual(events, ["compiler", "uniquify", "aliases"] + (["hooks"] if late else []))
                self.assertEqual(output.read_bytes(), b"previous complete output\n")
                self.assertEqual(list(output.parent.glob("emit.*.c")), [])


class PeFixupStepControls(unittest.TestCase):
    def fixture(self):
        units = (*native.frontend.collect_units(packer.PE_FIXUP_STEP_OWNER), "tools/entry.ouro")
        sources = {unit: (ROOT / unit).read_text(encoding="utf-8") for unit in units[:-1]}
        sources[units[-1]] = 'import "../compiler/native/pe_fixups.ouro";\nprivate def trigger : Nat := Z;\n'
        ordinal = units.index(packer.PE_FIXUP_STEP_OWNER)
        original = source(((f"_ouro_m_{ordinal}_pe_run_fixup_step", 7),))
        original = original.replace("(void)env;return arg;}",
                                    "(void)env;return ouro_app(ouro_get(env,0),ouro_ctor(0,0,0));}", 1)
        return original, units, sources

    def hook(self, text, units, sources, *, canonical=None, entry=None, installed=False):
        return packer.hook_pe_fixup_step(text, units, units if canonical is None else canonical,
                                        units[-1] if entry is None else entry, sources, installed=installed)

    def test_full_output_and_installed_readback(self):
        original, units, sources = self.fixture()
        include = '#include "ouro_rt.h"\n'
        declaration = "ouro_v *ouro_wrap_pe_run_fixup_step(ouro_v *raw);\n"
        raw = "ouro_c7=ouro_clos(ouro_f7_,env);"
        wrapped = "ouro_c7=ouro_wrap_pe_run_fixup_step(ouro_clos(ouro_f7_,env));"
        expected = original.replace(include, include + declaration, 1).replace(raw, wrapped, 1)
        hooked = self.hook(original, units, sources)
        self.assertEqual(hooked, expected)
        self.assertEqual(self.hook(hooked, units, sources, installed=True), expected)
        with self.assertRaises(RuntimeError):
            self.hook(hooked, units, sources)
        with self.assertRaises(RuntimeError):
            self.hook(original, units, sources, installed=True)

        body = original.removeprefix(include)
        getter = body.index("static ouro_v *ouro_g7(void)")
        adjacent = body[:getter] + include + body[getter:]
        expected = adjacent.replace(include, include + declaration, 1).replace(raw, wrapped, 1)
        self.assertEqual(self.hook(adjacent, units, sources), expected)
        self.assertEqual(self.hook(expected, units, sources, installed=True), expected)

        for text, installed in ((body + include, False), (hooked.removeprefix(include) + include, True)):
            with self.subTest(installed=installed), self.assertRaisesRegex(
                    RuntimeError, "^PE fixup step runtime include must precede getter$"):
                self.hook(text, units, sources, installed=installed)
        late_declaration = hooked.replace(declaration, "", 1) + declaration
        with self.assertRaisesRegex(RuntimeError, "^PE fixup step wrapper declaration must precede getter$"):
            self.hook(late_declaration, units, sources, installed=True)

    def test_source_algorithm_and_result_layout_are_exact(self):
        original, units, sources = self.fixture()
        owner = packer.PE_FIXUP_STEP_OWNER
        changes = (
            ("work MkUnit;", "Left(PeError, PeFixupStep, PeInvalidFixup 0);"),
            ("PePatch -> Nat -> Nat -> List Nat", "PePatch -> Nat -> List Nat -> Nat"),
            ("pe_bytes_equal(take Nat width slot, pe_zeros width)",
             "pe_bytes_equal(take Nat width slot, take Nat width slot)"),
            ("pe_resolve_fixup_indexed_with lookup index imports fixup extent",
             "pe_resolve_fixup_with lookup [] imports fixup extent"),
            ("(drop Nat width slot)", "slot"),
            ("(go tail code next_end True next_source)", "(go tail code next_end True source)"),
            ("pe_plan_fixups_with pe_run_fixup_step sections symbols imports fixups",
             "Right(PeError, List PePatch, [] : List PePatch)"),
            ("def pe_run_fixup_step", "private def pe_run_fixup_step"),
        )
        hooked = self.hook(original, units, sources)
        for before, after in changes:
            self.assertIn(before, sources[owner])
            altered = {**sources, owner: sources[owner].replace(before, after, 1)}
            for text, installed in ((original, False), (hooked, True)):
                with self.subTest(before=before, installed=installed), self.assertRaises(RuntimeError):
                    self.hook(text, units, altered, installed=installed)
        for shape_owner, kind, name, declaration in packer.PE_FIXUP_STEP_SOURCE_SHAPES:
            altered = {**sources, shape_owner: sources[shape_owner] + declaration + "\n"}
            with self.subTest(kind=kind, name=name), self.assertRaises(RuntimeError):
                self.hook(original, units, altered)

    def test_closure_ownership_and_generated_envelopes_refuse(self):
        original, units, sources = self.fixture()
        owner = packer.PE_FIXUP_STEP_OWNER
        ordinal = units.index(owner)
        changed = (
            original.replace("ouro_get(env,0)", "ouro_get(env,1)", 1),
            original.replace("ouro_ctor(0,0,0)", "ouro_ctor(1,0,0)", 1),
            original.replace("static ouro_v *ouro_c7;", "static ouro_v *ouro_c7;\nstatic ouro_v *ouro_c7;", 1),
            original.replace("static ouro_v *ouro_g7(void)", "static ouro_v *ouro_g7(void)\n/*changed*/", 1),
            original.replace("ouro_export_count(void){return 1;}", "ouro_export_count(void){return 2;}", 1),
            original.replace(f"_ouro_m_{ordinal}_pe_run_fixup_step", "_ouro_m_999_pe_run_fixup_step", 1),
            original + "static ouro_v *ouro_f0_7_(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + "static ouro_v *ouro_f7__d1(ouro_env *env0,ouro_v *arg){return arg;}\n",
            original + '#include "ouro_rt.h"\n',
        )
        for text in changed:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                self.hook(text, units, sources)
        for controls in ({"canonical": units[::-1]}, {"entry": "tools/other.ouro"}):
            with self.subTest(controls=controls), self.assertRaises(RuntimeError):
                self.hook(original, units, sources, **controls)
        for altered in ({unit: body for unit, body in sources.items() if unit != owner},
                        {**sources, "tools/extra.ouro": "def extra : Nat := Z;"}):
            with self.subTest(sources=altered), self.assertRaises(RuntimeError):
                self.hook(original, units, altered)
        homonym = {**sources, units[-1]: sources[units[-1]] + "def pe_run_fixup_step : Nat := Z;"}
        self.assertEqual(self.hook(original, units, homonym), self.hook(original, units, sources))
        bare = original.replace(f"_ouro_m_{ordinal}_pe_run_fixup_step", "pe_run_fixup_step", 1)
        with self.assertRaises(RuntimeError):
            self.hook(bare, units, homonym)
        absent = tuple(unit for unit in units if unit != owner)
        with self.assertRaises(RuntimeError):
            self.hook(original, absent, {unit: sources[unit] for unit in absent})
        self.assertEqual(self.hook(source((("main", 2),)), UNITS, SOURCES), source((("main", 2),)))

    def test_duplicate_cache_suffixes_refuse_original_and_installed(self):
        original, units, sources = self.fixture()
        installed = self.hook(original, units, sources)
        for suffix in ("0", "01", "1", "9" * 5000):
            for text, verifying in ((original, False), (installed, True)):
                altered = text + f"static ouro_v *ouro_c7_d{suffix};\n"
                with self.subTest(suffix=suffix[:20], installed=verifying), self.assertRaisesRegex(
                        RuntimeError, "duplicate PE fixup step cache declaration"):
                    self.hook(altered, units, sources, installed=verifying)
        unrelated = "static ouro_v *unrelated_d" + "9" * 5000 + ";\n"
        self.assertEqual(self.hook(original + unrelated, units, sources), installed + unrelated)
        self.assertEqual(self.hook(installed + unrelated, units, sources, installed=True), installed + unrelated)

    def test_native_cache_key_binds_step_source_and_installers(self):
        units = (packer.PE_FIXUP_STEP_OWNER, "tools/entry.ouro")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = tuple(dict.fromkeys((*units, *native.BUILD_INPUTS, *native.RUNTIME)))
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture " + name + "\n", encoding="utf-8")
            compiler = root / "seed.fixture"
            compiler.write_bytes(b"source-bound seed fixture\n")
            cc = root / "cc.fixture"
            cc.write_bytes(b"C compiler fixture\n")
            with patch.object(native, "ROOT", root), \
                 patch.object(native.frontend, "collect_units_many", return_value={units[-1]: list(units)}), \
                 patch.object(native.build, "locate_cc", return_value=(str(cc), None)), \
                 patch.object(native.build, "compiler_id", return_value="fixture"), \
                 patch.object(native.build, "profile_cflags", return_value=[]), \
                 patch.object(native.build, "host_link_flags", return_value=[]):
                collected, baseline = native.tool_inputs(units[-1], compiler, 200000, object())
                self.assertEqual(collected, list(units))
                for name in (packer.PE_FIXUP_STEP_OWNER, "runtime/frontend_link.c",
                             "scripts/pack_frontend.py", "scripts/native_tool_build.py",
                             "scripts/scoped_host_export_routes.py", "scripts/scoped_host_export_consumers.py"):
                    target = root / name
                    original = target.read_bytes()
                    target.write_bytes(original + b"changed source\n")
                    _collected, changed = native.tool_inputs(units[-1], compiler, 200000, object())
                    self.assertNotEqual(native.hash_json(baseline), native.hash_json(changed), name)
                    self.assertEqual({key for key in baseline["sources"]
                                      if baseline["sources"][key] != changed["sources"][key]}, {name})
                    target.write_bytes(original)


FLAT_OWNER, FLAT_ENTRY = "compiler/native/mir_live.ouro", "tools/source_control.ouro"
FLAT_UNITS = (FLAT_OWNER, FLAT_ENTRY)
FLAT_NAMES = tuple(alias for alias, _name, owners in FLAT_HOST_EXPORT_ROUTES if FLAT_OWNER in owners)
FLAT_SOURCES = {FLAT_OWNER: "".join(f"def {name} (arg : Nat) : Nat := arg;\n" for name in FLAT_NAMES),
           FLAT_ENTRY: "private def trigger : Nat := Z;\ndef main : Nat := Z;\n"}
FLAT_ROWS = tuple((f"_ouro_m_0_{name}", 31 + index * 97) for index, name in enumerate(FLAT_NAMES)) + (("main", 99999),)


class FlatIntegration(unittest.TestCase):
    def test_helper_inputs_are_mandatory(self):
        helpers = ("scripts/scoped_host_exports.py", "scripts/scoped_host_export_routes.py",
                   "scripts/scoped_host_export_consumers.py", "scripts/structural_quality_legacy.py")
        for name in helpers:
            self.assertEqual(native.BUILD_INPUTS.count(name), 1)
            self.assertEqual(bootstrap.HELPERS.count(name), 1)

    def emit_control(self, *, text=None, sources=None, canonical=FLAT_UNITS, late=False):
        text = source(FLAT_ROWS) if text is None else text
        sources = FLAT_SOURCES if sources is None else sources
        events = []
        original_hook = native.hook_compile_checked_units

        def run(argv, **kwargs):
            if "stdout" in kwargs:
                events.append("compiler")
                self.assertEqual(kwargs["cwd"], ROOT)
                self.assertEqual(kwargs["env"]["OURO_EMIT_IO_SHIMS"], "1")
                kwargs["stdout"].write(text.encode())
            else:
                events.append("uniquify")
                self.assertIn("--uniquify-only", argv)
            return subprocess.CompletedProcess(argv, 0)

        def aliases(*args, **kwargs):
            events.append("aliases")
            return current_native_scoped_aliases(*args, **kwargs)

        def hook(path, units, *, source_text):
            events.append("hooks")
            self.assertEqual(tuple(units), FLAT_UNITS)
            for name in FLAT_NAMES:
                self.assertIn(f'return "{name}";', source_text)
            if late:
                raise RuntimeError("late closed host hook refusal")
            original_hook(path, units, source_text=source_text)

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "accepted.c"
            output.write_bytes(b"previous complete output\n")
            error = None
            closure = fixture_scope_closure(canonical, sources, entry=FLAT_ENTRY)
            with patch.object(native, "ROOT", ROOT), \
                 patch.object(native.frontend, "collect_units_many", side_effect=closure) as collector, \
                 patch.object(native.frontend, "ouro1_cmd", return_value=["synthetic-seed"]), \
                 patch.object(native.subprocess, "run", side_effect=run), \
                 patch.object(native, "current_native_scoped_aliases", side_effect=aliases), \
                 patch.object(native, "hook_compile_checked_units", side_effect=hook):
                try:
                    native.emit(Path("synthetic-seed"), list(FLAT_UNITS), 200000, output)
                except RuntimeError as failure:
                    error = failure
            collector.assert_called_once()
            result = output.read_bytes()
            self.assertEqual(list(output.parent.glob("emit.*.c")), [])
        return result, events, error

    def test_aliases_precede_existing_hooks_and_publication(self):
        result, events, error = self.emit_control()
        self.assertIsNone(error)
        self.assertEqual(events, ["compiler", "uniquify", "aliases", "hooks"])
        result = result.decode()
        for index, (label, gid) in enumerate(FLAT_ROWS):
            self.assertIn(f'case {index}:return "{label}";', result)
            self.assertIn(f"case {index}:return ouro_g{gid}();", result)
        for index, name in enumerate(FLAT_NAMES):
            self.assertIn(f'case {len(FLAT_ROWS) + index}:return "{name}";', result)
            self.assertIn(f"case {len(FLAT_ROWS) + index}:return ouro_g{31 + index * 97}();", result)
        for name, wrapper, _owners in native.HOST_HOOKS:
            if name in FLAT_NAMES:
                gid = 31 + FLAT_NAMES.index(name) * 97
                self.assertEqual(result.count(f"ouro_c{gid}={wrapper}(ouro_clos("), 1)

    def test_private_missing_wrong_ordinal_and_closure_never_publish(self):
        private = {**FLAT_SOURCES, FLAT_OWNER: FLAT_SOURCES[FLAT_OWNER].replace("def mir_live_facts",
                                                          "private -- modifier comment\ndef mir_live_facts", 1)}
        cases = (
            {"sources": private},
            {"text": source(FLAT_ROWS[1:])},
            {"text": source(FLAT_ROWS).replace("_ouro_m_0_mir_live_facts", "_ouro_m_1_mir_live_facts", 1)},
            {"canonical": FLAT_UNITS[::-1]},
        )
        for options in cases:
            with self.subTest(options=options):
                result, events, error = self.emit_control(**options)
                self.assertIsInstance(error, RuntimeError)
                self.assertEqual(result, b"previous complete output\n")
                self.assertNotIn("hooks", events)

    def test_late_hook_refusal_never_publishes_aliases(self):
        result, events, error = self.emit_control(late=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(events, ["compiler", "uniquify", "aliases", "hooks"])
        self.assertEqual(result, b"previous complete output\n")


if __name__ == "__main__":
    unittest.main()
