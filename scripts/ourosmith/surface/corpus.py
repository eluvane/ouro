"""Portable surface regression records containing input and oracle contract."""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from ourosmith import ROOT
from ourosmith.corpus import NAME_RE
from ourosmith.surface.gen import Expr, validate

DIRECTORY = ROOT / "quality/smith/regressions"
KIND = "ouro.smith-surface-regression.v1"


def validate_sources(sources):
    for filename, contents in sources:
        path = PurePosixPath(filename)
        if path.is_absolute() or ".." in path.parts or ":" in filename or "\\" in filename or not isinstance(contents, str):
            raise ValueError("saved files need a relative sandbox path and source text")


def validate_input(value):
    if not isinstance(value, dict):
        raise ValueError("surface input must be an object")
    if "ast" in value:
        validate(Expr.from_json(value["ast"]))
    elif "mutation" in value:
        diagnostics = value.get("diagnostics")
        if not isinstance(value.get("source"), str) or not isinstance(diagnostics, (list, tuple)) or not diagnostics or not all(isinstance(code, str) and code for code in diagnostics):
            raise ValueError("surface mutation needs source and exact diagnostic contract")
        if value.get("tool", "check") not in {"check", "lint"}:
            raise ValueError("surface mutation tool must be check or lint")
        if not isinstance(value.get("fuel", 999999), int) or value.get("fuel", 999999) < 0:
            raise ValueError("surface mutation fuel must be a nonnegative integer")
        for filename, contents in value.get("dependencies", []):
            path = PurePosixPath(filename)
            if path.is_absolute() or ".." in path.parts or ":" in filename or "\\" in filename or not isinstance(contents, str):
                raise ValueError("mutation dependency must be a relative sandbox path and source text")
    elif "recipe" in value:
        from ourosmith.surface.forms import FEATURES
        from ourosmith.surface.tools import PROPERTIES

        known = {"form-" + name for name in FEATURES} | {prop.__name__ for prop in PROPERTIES}
        if value["recipe"] not in known:
            raise ValueError(f"unknown surface recipe {value['recipe']}")
        if value["recipe"] == "compiler_parity" and "cases" in value:
            cases = value["cases"]
            if not isinstance(cases, list) or not cases:
                raise ValueError("saved parity needs a nonempty case list")
            names = set()
            for case in cases:
                if not isinstance(case, dict) or not isinstance(case.get("name"), str) or not NAME_RE.fullmatch(case["name"]) or case["name"] in names:
                    raise ValueError("parity case names must be unique sandbox names")
                names.add(case["name"])
                if not isinstance(case.get("source"), str) or type(case.get("units_needed", False)) is not bool:
                    raise ValueError("parity case needs source and a boolean units flag")
                validate_sources(case.get("dependencies", []))
                if "diagnostics" in case:
                    codes = case["diagnostics"]
                    if not isinstance(codes, list) or not codes or not all(isinstance(code, str) and code for code in codes):
                        raise ValueError("negative parity needs diagnostic codes")
                elif type(case.get("expected")) is not int or case["expected"] < 0:
                    raise ValueError("positive parity needs a natural-number oracle")
                elif not all(isinstance(case.get(key), str) and case[key] for key in ("type_name", "successor")):
                    raise ValueError("positive parity needs its eval type and successor names")
            if not any("expected" in case for case in cases):
                raise ValueError("parity needs a positive input for its eval CLI contract")
        if value["recipe"] == "manifest_contract" and "sources" in value:
            if not isinstance(value["sources"], dict) or set(value["sources"]) != {"good.ouro", "bad.ouro"}:
                raise ValueError("manifest contract needs its positive and negative sources")
            validate_sources(value["sources"].items())
        if "source" in value:
            if not isinstance(value["source"], str):
                raise ValueError("saved source must be text")
            if value["recipe"].startswith("stdlib_") or value["recipe"] in {"analyzer_ast", "analyzer_lines", "parser_contract"}:
                if not isinstance(value.get("expected_stdout"), str):
                    raise ValueError("saved expression program needs an exact stdout oracle")
            elif value["recipe"] == "lint_contracts":
                from ourosmith.surface.lint_contracts import FEATURES

                if value.get("case") not in FEATURES:
                    raise ValueError("saved lint contract needs a known positive case")
                for filename, contents in value.get("dependencies", []):
                    path = PurePosixPath(filename)
                    if path.is_absolute() or ".." in path.parts or ":" in filename or "\\" in filename or not isinstance(contents, str):
                        raise ValueError("lint dependency must be a relative sandbox path and source text")
            elif value["recipe"] == "text_tools":
                from ourosmith.surface.text_contracts import FEATURES

                if value.get("tool") not in {"fmt", "fix"} or value.get("case") not in FEATURES or not isinstance(value.get("expected_source"), str):
                    raise ValueError("saved text contract needs a known case, tool, and exact output")
                validate_sources(value.get("dependencies", []))
            elif value["recipe"] == "documentation":
                if not all(isinstance(value.get(key), str) for key in ("expected_markdown", "signature", "prose")):
                    raise ValueError("saved documentation needs a complete signature, prose, and layout oracle")
            elif value["recipe"] == "backend_depth":
                if type(value.get("expected")) is not int or value["expected"] < 0:
                    raise ValueError("saved backend recursion needs a natural-number oracle")
            elif value["recipe"] == "runtime_io":
                if not all(isinstance(value.get(key), str) for key in ("child_source", "env_value", "stdin")):
                    raise ValueError("saved IO needs helper source, environment value, and stdin")
                arguments = value.get("arguments")
                if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
                    raise ValueError("saved IO arguments must be strings")
                expected, files = value.get("expected_values"), value.get("expected_files")
                if not isinstance(expected, dict) or "clock" not in expected or expected["clock"] is not None:
                    raise ValueError("saved IO needs a clock observation contract")
                if not all(isinstance(key, str) and (isinstance(item, str) or (key == "clock" and item is None)) for key, item in expected.items()):
                    raise ValueError("saved IO observations must be text, with a dynamic clock")
                if not isinstance(files, dict):
                    raise ValueError("saved IO needs expected file bytes")
                validate_sources(files.items())
                for data in files.values():
                    bytes.fromhex(data)
            elif not value["recipe"].startswith("form-"):
                raise ValueError("this tool recipe does not support saved source")
            elif type(value.get("expected")) is not int or value["expected"] < 0 or type(value.get("units_needed", False)) is not bool:
                raise ValueError("saved surface form needs a natural-number oracle and boolean units flag")
    else:
        raise ValueError("surface input needs ast, mutation, or recipe")


def promote(finding, name, *, directory=DIRECTORY, note=""):
    if not NAME_RE.fullmatch(name):
        raise ValueError("invalid surface regression name")
    validate_input(finding.get("minimal_input"))
    if finding.get("layer") != "surface" or not isinstance(finding.get("seed"), int):
        raise ValueError("expected a seeded surface finding")
    record = {"kind": KIND, "name": name, "seed": finding["seed"], "profile": finding["profile"],
              "input": finding["minimal_input"], "property": finding["prop"], "expected": finding["expected"],
              "origin": {"generator_hash": finding["generator_hash"], "phase": finding["failing_phase"],
                         "actual": finding["actual"], "replay": finding["replay"], "note": note}}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return path


def load():
    records = []
    for path in sorted(DIRECTORY.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("kind") != KIND or record.get("name") != path.stem or not isinstance(record.get("seed"), int):
            raise ValueError(f"invalid surface regression: {path}")
        validate_input(record.get("input"))
        records.append(record)
    return records
