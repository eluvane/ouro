"""Compiler-owned syntax regression inputs; no surface evaluator or parser."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/language_ergonomics"
LINT_DIAGNOSTICS = {
    "OURO-LINT003": "lint/unused: unused local binder",
    "OURO-LINT004": "lint/shadow: binder shadows an outer name",
}


def load_cases():
    manifest = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    names = set()
    for group in ("positive", "negative"):
        rows = manifest[group]
        if not rows:
            raise ValueError("empty ergonomics case group: " + group)
        for case in rows:
            name = case["name"]
            if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
                raise ValueError("invalid ergonomics case name: " + name)
            if name in names:
                raise ValueError("duplicate ergonomics case name: " + name)
            names.add(name)
            required = ("type", "sugar", "canonical") if group == "positive" else ("source",)
            if any(not isinstance(case.get(key), str) or not case[key] for key in required):
                raise ValueError("missing source field: " + name)
            if "lint" in case:
                expected = case["lint"]
                if group != "positive" or not isinstance(expected, dict) or set(expected) != {"language", "semantic"}:
                    raise ValueError("invalid lint families: " + name)
                for variants in expected.values():
                    if not isinstance(variants, dict) or set(variants) != {"candidate", "canonical"}:
                        raise ValueError("invalid lint variants: " + name)
                    if any(not isinstance(codes, list) or any(not isinstance(code, str) or code not in LINT_DIAGNOSTICS for code in codes)
                           for codes in variants.values()):
                        raise ValueError("invalid lint diagnostics: " + name)
            for module in case.get("imports_std", []):
                path = Path(module)
                if path.is_absolute() or ".." in path.parts or not module.startswith("std/"):
                    raise ValueError("non-stdlib fixture import: " + module)
    return manifest


def support_source():
    return (FIXTURES / "support.ouro").read_text(encoding="utf-8")


def render(case, directory):
    header = '-- ERGO_KEEP: комментарий 漢字\n'
    # Load the standard Nat before the fixture's same-shaped ErgNat.
    for module in case.get("imports_std", []):
        spelling = os.path.relpath(ROOT / module, directory).replace("\\", "/")
        header += "import " + json.dumps(spelling, ensure_ascii=False) + ";\n"
    header += 'import "support.ouro";\n'
    if "source" in case:
        return header + case["source"] + "\n"
    ty = "(" + case["type"] + ")"
    return header + (
        f'def ergo_expansion_candidate : {ty} := {case["sugar"]};\n'
        f'def ergo_expansion_reference : {ty} := {case["canonical"]};\n'
        f'def ergo_expansion_law : ErgEq {ty} ergo_expansion_candidate '
        f'ergo_expansion_reference := ErgRefl {ty} ergo_expansion_reference;\n'
    )


def import_cases():
    dependencies = (
        ("support.ouro", support_source()),
        ("left/common.ouro", 'import "../support.ouro";\ndef erg_left_path : ErgNat := ErgZero;\n'),
        ("right/common.ouro", 'import "../support.ouro";\ndef erg_right_path : ErgNat := ErgSucc ErgZero;\n'),
        ("путь 漢字.ouro", 'import "support.ouro";\ndef erg_unicode_path : ErgNat := ErgZero;\n'),
        ("cycle/a.ouro", 'import "../left/common.ouro", "b.ouro";\n'),
        ("cycle/b.ouro", 'import "a.ouro";\n'),
    )
    laws = (
        "def ergo_left_law : ErgEq ErgNat erg_left_path ErgZero := ErgRefl ErgNat ErgZero;\n"
        "def ergo_right_law : ErgEq ErgNat erg_right_path (ErgSucc ErgZero) := "
        "ErgRefl ErgNat (ErgSucc ErgZero);\n"
    )
    groups = {
        "group": 'import "left/common.ouro", "right/common.ouro";',
        "trailing": 'import "left/common.ouro", "right/common.ouro",;',
        "comments": 'import -- before first\n "left/common.ouro", -- before second\n "right/common.ouro", -- before terminator\n ;',
        "comments-with-alias": 'import "left/common.ouro" -- before alias\n as Old;\nimport -- before first\n "left/common.ouro", -- before second\n "right/common.ouro", -- before terminator\n ;',
        "duplicate": 'import "left/common.ouro", "left/common.ouro", "right/common.ouro";',
        "canonical": 'import "left/./common.ouro", "left/../right/common.ouro";',
        "old-and-new": 'import "left/common.ouro"; import "right/common.ouro",;',
        "legacy-alias-separate": 'import "left/common.ouro" as Old; import "left/common.ouro", "right/common.ouro";',
        "unicode": 'import "left/common.ouro", "путь 漢字.ouro", "right/common.ouro";',
        "unicode-single": 'import "left/common.ouro"; import "путь 漢字.ouro"; import "right/common.ouro";',
    }
    for name, declaration in groups.items():
        extra = ("def ergo_unicode_law : ErgEq ErgNat erg_unicode_path ErgZero := "
                 "ErgRefl ErgNat ErgZero;\n") if name in ("unicode", "unicode-single") else ""
        yield name, declaration + "\n" + laws + extra, "pass", "CHECK_OK", dependencies
    errors = {
        "alias-in-group": ('import "left/common.ouro" as Mixed, "right/common.ouro";', "OURO-IMP-001"),
        "alias-before-trailing-comma": ('import "left/common.ouro" as Mixed,;', "OURO-IMP-001"),
        "alias-comment-before-comma": ('import "left/common.ouro" as Mixed -- alias stays single\n , "right/common.ouro";', "OURO-IMP-001"),
        "missing-tail": ('import "left/common.ouro",', "expected import path after comma"),
        "double-comma": ('import "left/common.ouro",, "right/common.ouro";', "expected import path after comma"),
        "unquoted-tail": ('import "left/common.ouro", right;', "expected import path after comma"),
        "unterminated-tail": ('import "left/common.ouro", "unfinished', "malformed import string"),
        "missing-second-file": ('import "left/common.ouro", "absent.ouro";', "collect_units: missing"),
        "cycle-second-edge": ('import "left/common.ouro", "cycle/a.ouro";', "collect_units: import cycle"),
    }
    for name, (source, diagnostic) in errors.items():
        yield name, source + "\n", "fail", diagnostic, dependencies


def prepare_manifest(root, add):
    """Extend the existing ERGO/IMP gate, without defining another test protocol."""
    manifest = load_cases()
    dependency = (("support.ouro", support_source()),)
    for group in ("positive", "negative"):
        for case in manifest[group]:
            name = "ERGO.expansion-" + case["name"]
            passed = group == "positive"
            add(name, render(case, root / name), "pass" if passed else "fail",
                "CHECK_OK" if passed else "CHECK_FAIL", dependency)
    for name, source, verdict, diagnostic, dependencies in import_cases():
        add("IMP.expansion-" + name, source, verdict, diagnostic, dependencies)
