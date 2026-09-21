#!/usr/bin/env python3
"""Focused syntax-quality firewall and canonical-fixer suite."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence
from unittest.mock import patch

from repo_support import bind_relative_path, read_json_value, write_json_atomic
from ourosmith.host import binary
from ourosmith.surface.text_contracts import syntax_cases
import strict_quality_firewall as strict_quality
import syntax_quality_fix as syntax_native

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
OUT = ROOT / "_build" / "syntax_quality_suite"
EXPECTED_SYNTAX_CODES = {
    "OURO-LINT037",
    "OURO-LINT040",
    "OURO-LINT041",
    "OURO-LINT042",
    "OURO-LINT043",
    "OURO-LINT044",
}
RETIRED_SYNTAX_CODES = {
    "OURO-LINT022",
    "OURO-LINT028",
    "OURO-LINT031",
    "OURO-LINT032",
    "OURO-LINT033",
    "OURO-LINT034",
    "OURO-LINT035",
    "OURO-LINT036",
    "OURO-LINT038",
    "OURO-LINT039",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str


def run(cmd: Sequence[str], *, expect: int | None = 0, stdout: Path | None = None) -> subprocess.CompletedProcess[str]:
    if stdout is not None:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("w", encoding="utf-8") as f:
            proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=f, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if expect is not None and proc.returncode != expect:
        output = "" if stdout is not None else (proc.stdout or "")
        raise AssertionError(f"{rel(Path(cmd[1])) if len(cmd) > 1 and cmd[1].endswith('.py') else cmd[0]} returned {proc.returncode}, expected {expect}\n{output[-4000:]}")
    return proc


_FIX_BINARY: list[Path | None] = [None]


def fix_binary() -> Path:
    """Prepare the native fixer once; the retired CLI wrapper rebuilt it per call."""
    if _FIX_BINARY[0] is None:
        try:
            _FIX_BINARY[0] = syntax_native.prepare_native_fix()
        except (OSError, ValueError) as exc:
            raise AssertionError(f"SYNTAX_FIX: native tool unavailable: {exc}") from exc
    prepared = _FIX_BINARY[0]
    if prepared is None:
        raise AssertionError("SYNTAX_FIX: native tool unavailable")
    return prepared


def fix_cmd(*args: str) -> list[str]:
    """Direct native invocation; file operands keep the wrapper's absolute spelling."""
    resolved = [arg if arg.startswith("--") else str(Path(arg).resolve()) for arg in args]
    return [str(fix_binary()), *resolved]


def load_json_object(path: Path) -> dict[str, Any]:
    data, error = read_json_value(path)
    if error is not None:
        raise AssertionError(f"unreadable JSON {rel(path)}: {error}")
    if not isinstance(data, dict):
        raise AssertionError(f"{rel(path)} is not a JSON object")
    return data


def check_rejected_manifest() -> Check:
    path = ROOT / "quality" / "rejected_syntax.json"
    manifest = load_json_object(path)
    diagnostics = load_json_object(ROOT / "quality" / "diagnostics.json").get("diagnostics", [])
    if not isinstance(diagnostics, list):
        raise AssertionError("quality/diagnostics.json diagnostics is not an array")
    registry = {
        item["code"]
        for item in diagnostics
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    }
    codes = {rule["code"] for rule in manifest.get("rules", [])}
    missing = sorted(EXPECTED_SYNTAX_CODES - codes)
    unknown = sorted(codes - registry)
    if missing or unknown:
        raise AssertionError(f"rejected syntax manifest mismatch missing={missing} unknown={unknown}")
    by_code = {rule["code"]: rule for rule in manifest.get("rules", []) if isinstance(rule, dict)}
    live_marked_retired = sorted(
        code for code in EXPECTED_SYNTAX_CODES if by_code.get(code, {}).get("status") == "retired"
    )
    retired_still_deny = sorted(
        code for code in RETIRED_SYNTAX_CODES
        if str(by_code.get(code, {}).get("status") or "").startswith("deny")
    )
    if live_marked_retired or retired_still_deny:
        raise AssertionError(
            f"rejected syntax status mismatch live_marked_retired={live_marked_retired} "
            f"retired_still_deny={retired_still_deny}"
        )
    return Check("rejected-syntax-manifest", "pass", f"{len(codes)} rejected forms registered")


def check_fix_cases() -> list[Check]:
    checks: list[Check] = []
    generated = [(seed, case) for seed in (1, 6) for case in syntax_cases(seed)]
    for seed, case in generated:
        inp = OUT / f"{seed}-{case.name}.in"
        golden = inp.with_suffix(".golden")
        # Materialize the contract's exact LF bytes on Windows as well. The
        # native formatter correctly reports host-inserted CRLF as drift.
        inp.write_text(case.source, encoding="utf-8", newline="")
        golden.write_text(case.expected, encoding="utf-8", newline="")
        for name, contents in case.dependencies:
            dependency = inp.parent / name
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text(contents, encoding="utf-8", newline="")
    # Pure byte-level selftests keep incomplete editor inputs. Public preview,
    # check and write all require compiler acceptance; exercise those below on
    # complete programs instead of expecting an unchecked preview to succeed.
    run([str(fix_binary()), "--selftest", "--fixtures=" + str(OUT),
         "--out=" + str(OUT / "byte-selftest")])
    for seed in (1, 6):
        inp = OUT / f"{seed}-fix-numeral.in"
        original = inp.read_bytes()
        rejected = run(fix_cmd("--write", rel(inp)), expect=1)
        if "compiler rejected" not in rejected.stdout or inp.read_bytes() != original:
            raise AssertionError("incomplete editor input was published or rejection lost its diagnostic")
        checks.append(Check(f"incomplete-write-{seed}", "pass", "compiler refusal preserves input bytes"))
    checks.extend(check_typed_writes(generated))
    return checks


def typed_write_programs(generated):
    # Keep the exact incomplete-editor preview goldens above. Publication
    # additionally needs real declarations. Combined programs use distinct
    # definition names instead of concatenating eleven duplicate value names.
    typed = []
    for seed in (1, 6):
        parts = []
        for item_seed, case in generated:
            if item_seed != seed or case.name == "combined":
                continue
            for name, contents in case.dependencies:
                # Share the same Nat identity as the root's standard library.
                declaration = "inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n"
                if not contents.startswith(declaration):
                    raise AssertionError(f"unexpected syntax dependency declaration: {name}")
                library = Path(os.path.relpath(ROOT / "std/types.ouro", OUT)).as_posix()
                rewritten = f'import "{library}";\n' + contents[len(declaration):]
                (OUT / name).write_text(rewritten, encoding="utf-8", newline="")
            label = f"value{seed}_" + case.name.replace("-", "_")
            source = case.source.replace(f"def value{seed} ", f"def {label} ")
            expected = case.automatic.replace(f"def value{seed} ", f"def {label} ")
            review = case.expected != case.automatic
            if case.name == "fix-legacy-bind":
                # Typed publication must be compiler-accepted: docs/syntax.md do
                # examples end the last statement without a trailing semicolon,
                # and the checker rejects the terminator (CErr 10). The original
                # incomplete-editor preview goldens keep their exact bytes; only
                # these typed variants drop it. Combined inherits from its parts.
                source = source.replace("; io_pure Nat x;\n", "; io_pure Nat x\n")
                expected = expected.replace("; io_pure Nat x;\n", "; io_pure Nat x\n")
            if case.name == "fix-list-element":
                for_text = "[Nil Nat, Cons Nat Z (Nil Nat)]"
                source = source.replace(for_text, "(" + for_text + " : List (List Nat))")
                expected = expected.replace(for_text, "(" + for_text + " : List (List Nat))")
            parts.append((replace(case, source=source, expected=expected), review))
        combined = replace(parts[0][0], name="combined", source="".join(case.source for case, _ in parts),
                           expected="".join(case.expected for case, _ in parts))
        for case, review in [*parts, (combined, any(review for _, review in parts))]:
            library = "std/runtime.ouro" if case.name in {"fix-legacy-bind", "combined"} else "std/string_prims.ouro"
            prefix = f'import "{Path(os.path.relpath(ROOT / library, OUT)).as_posix()}";\n'
            path = OUT / f"checked-write-{seed}-{case.name}.ouro"
            path.write_text(prefix + case.source, encoding="utf-8", newline="")
            typed.append((path, prefix + case.expected, review))
    return typed


def check_typed_writes(generated) -> list[Check]:
    typed = typed_write_programs(generated)
    inputs = [rel(path) for path, _, _ in typed]
    for path, expected, _review in typed:
        original = path.read_bytes()
        preview = subprocess.run(fix_cmd(rel(path)), cwd=ROOT, capture_output=True, text=True)
        if preview.returncode != 0 or preview.stdout != expected or path.read_bytes() != original:
            raise AssertionError(f"checked preview differs from {rel(path)} contract: {preview.stderr}")
    run(fix_cmd("--write", *inputs))
    for path, expected, review in typed:
        checked = run(fix_cmd("--check", rel(path)), expect=int(review))
        if review and "review-required suggestions (not applied)" not in checked.stdout:
            raise AssertionError("semantic suggestions lost their review-required diagnostic")
        if path.read_text(encoding="utf-8") != expected:
            raise AssertionError(f"compiler-checked write differs from {rel(path)} contract")
        repeated = subprocess.run(fix_cmd("--write", rel(path)), cwd=ROOT, capture_output=True, text=True)
        if repeated.returncode != 0 or repeated.stdout or path.read_text(encoding="utf-8") != expected:
            raise AssertionError(f"checked publication is not idempotent for {rel(path)}: {repeated.stderr}")
    return [Check("checked-syntax-writes", "pass", f"{len(typed)} complete programs; certified writes and review-only semantic suggestions")]


def check_native_fix_boundaries() -> list[Check]:
    cases = {
        "literal-peano": 'def text : String := "S (S (S Z))";\n',
        "literal-bind": 'def text : String := "do x <- action;";\n',
        "comment-bind": '-- do x <- action; S (S (S Z))\ndef value : Nat := 0;\n',
        "distinct-aliases": ('import "alias_source.ouro" as Alpha;\n'
                             'import "alias_source.ouro" as Beta;\n'
                             # The root definition must not collide with the
                             # aliased unit's `value`: the checker rejects the
                             # duplicate global (CErr 3), and --write is
                             # compiler-checked. Alias shading itself is intact.
                             'def combined : Nat := add Alpha.value Beta.value;\n'),
    }
    library = Path(os.path.relpath(ROOT / "std/string_prims.ouro", OUT)).as_posix()
    prefix = f'import "{library}";\n'
    (OUT / "alias_source.ouro").write_text(prefix + "def value : Nat := 1;\n", encoding="utf-8", newline="")
    checks = []
    for name, source in cases.items():
        prefixed = prefix + source
        path = OUT / f"native-{name}.ouro"
        path.write_text(prefixed, encoding="utf-8", newline="")
        original = path.read_bytes()
        output = OUT / f"native-{name}.out"
        run(fix_cmd(rel(path)), stdout=output)
        if output.read_text(encoding="utf-8") != prefixed:
            raise AssertionError(f"native fixer changed the meaning-bearing text in {name}")
        run(fix_cmd("--write", rel(path)))
        run(fix_cmd("--check", rel(path)))
        if path.read_bytes() != original:
            raise AssertionError(f"native fixer changed a clean file in {name}")
        checks.append(Check("native-" + name, "pass", "literal/alias preservation and idempotence"))
    missing = OUT / "native-missing-import.ouro"
    missing.write_text('import "does-not-exist.ouro";\ndef value : Nat := S (S (S Z));\n',
                       encoding="utf-8", newline="")
    original = missing.read_bytes()
    proc = run(fix_cmd("--write", rel(missing)), expect=1)
    if "cannot read import" not in proc.stdout or missing.read_bytes() != original:
        raise AssertionError("native fixer did not preserve the file on missing import")
    checks.append(Check("native-missing-import", "pass", "public CLI refusal preserves source"))
    return checks


def check_fix_metadata() -> list[Check]:
    # Independent filesystem observations around the real public executable.
    # This does not certify atomic replacement or candidate compiler checking.
    path = OUT / "native-source-metadata.ouro"
    declaration = b"inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n"
    original = declaration + b"def retained_value : Nat :=0;\n"
    expected = declaration + b"def retained_value : Nat := 0;\n"
    path.write_bytes(original)
    stream = None
    if os.name == "nt":
        import ctypes

        set_attributes = ctypes.WinDLL("kernel32", use_last_error=True).SetFileAttributesW
        set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        set_attributes.restype = ctypes.c_int
        # ARCHIVE | NOT_CONTENT_INDEXED: replacement with the artifact
        # publisher currently drops the latter and adds TEMPORARY instead.
        if not set_attributes(str(path), 0x2020):
            raise ctypes.WinError(ctypes.get_last_error())
        stream = Path(str(path) + ":quality-contract")
        stream.write_bytes(b"retained source stream\n")
    else:
        path.chmod(0o640)
    before = path.stat()
    native = str(binary("ouro-fix"))
    run([native, "--write", rel(path)])
    after = path.stat()
    if (path.read_bytes() != expected or before.st_mode != after.st_mode
            or before.st_uid != after.st_uid or before.st_gid != after.st_gid
            or (os.name == "nt" and before.st_file_attributes != after.st_file_attributes)
            or (stream is not None and stream.read_bytes() != b"retained source stream\n")):
        raise AssertionError("public fix changed source metadata or named streams")
    run([native, "--check", rel(path)])
    repeated = run([native, "--write", rel(path)])
    if repeated.stdout or path.read_bytes() != expected:
        raise AssertionError("metadata fixture did not converge through the public CLI")
    detail = "Windows attributes and named stream" if os.name == "nt" else "POSIX mode, owner and group"
    return [Check("native-source-metadata", "pass", detail + " preserved across write/check/repeat")]


def check_literal_protocol() -> list[Check]:
    native = binary("ouro-fix")
    chain = "Nil Nat"
    for _ in range(260):
        chain = "Cons Nat 1 (" + chain + ")"
    cases = {
        "empty": ("", None),
        "closed": ("def items : List Nat := Cons Nat 1 (Nil Nat);\n", "Cons Nat 1 (Nil Nat)"),
        "bare-inner-tail": ("def items := Cons Nat 1 (Cons Nat 2 Nil Nat);\n", "Cons Nat 1 (Cons Nat 2 Nil Nat)"),
        "bare-tail": ("def items := Cons Nat 1 Nil Nat ;\n", "Cons Nat 1 Nil Nat"),
        "different-tail-type": ("def items := Cons Nat 1 (Nil Bool);\n", None),
        "extra-tail-group": ("def items := Cons Nat 1 ((Nil Nat));\n", None),
        "open": ("def items : List Nat := Cons Nat 1 tail;\n", None),
        "literal": ('def text : String := "Cons Nat 1 (Nil Nat)";\n', None),
        "comment": ("-- Cons Nat 1 (Nil Nat)\ndef value : Nat := 0;\n", None),
        "composite": ("def items := Cons (Pair Nat Nat) item (Nil (Pair Nat Nat));\n", None),
        "qualified": ("def items := Cons Alpha.Item item (Nil Alpha.Item);\n", None),
        "unicode": ('-- 日本語\ndef items : List String := Cons String "漢字" (Nil String);\n',
                    'Cons String "漢字" (Nil String)'),
        "large": ("-- " + "source " * 10000 + "\ndef items := Cons Nat 1 (Nil Nat);\n", "Cons Nat 1 (Nil Nat)"),
        "large-clean": ("-- " + "source " * 150000 + "\ndef value : Nat := 0;\n", None),
        "long-chain": ("def items : List Nat := " + chain + ";\n", chain),
        "nil": ("def items : List Nat := Nil Nat;\n", ":= Nil Nat;"),
        "nil-no-semicolon": ("def items := Nil Nat\n", ":= Nil Nat"),
        "nil-spacing": ("def items :=  Nil  Nat ; -- empty\n", ":=  Nil  Nat ;"),
        "nil-unicode": ("-- 日本語\ndef items := Nil String;\n", ":= Nil String;"),
        "nil-comment": ("-- def items := Nil Nat;\n", None),
        "nil-quoted": ('def text : String := ":= Nil Nat --";\n', None),
        "nil-qualified": ("def items := Nil Alpha.Item;\n", None),
        "nil-composite": ("def items := Nil (Pair Nat Nat);\n", None),
        "nil-prefix": ("def items := NilLike Nat;\n", None),
        "nil-next-line": ("def items :=\n Nil Nat;\n", None),
        "nil-trailing-token": ("def items := Nil Nat extra;\n", None),
        "nil-large-comment": ("-- " + "Nil " * 20000 + "\ndef value : Nat := 0;\n", None),
    }
    for name, (source, expression) in cases.items():
        facts = syntax_native.native_literal_facts(source, native)
        spans = [] if expression is None else [(source.index(expression), source.index(expression) + len(expression))]
        # closed_lines retains the separate line-local Cons query; v2 spans
        # additionally contain standalone Nil assignments.
        lines = ({source.count("\n", 0, source.index(expression)) + 1}
                 if expression is not None and expression.startswith("Cons ") else set())
        if facts.spans != spans or facts.closed_lines != lines:
            raise AssertionError(f"native literal facts differ for {name}: {facts}")
    from ourosmith.limits import run_limited

    for name, values, source in (
        ("short", ["4"], "abc"), ("long", ["2"], "abc"), ("missing", [], ""),
        ("extra", ["0", "extra"], ""), ("negative", ["-1"], ""),
        ("option-value", ["--unknown"], ""), ("too-large", ["8388609"], ""),
    ):
        result = run_limited([str(native), "--literal-spans", *values],
                             cwd=ROOT, timeout_s=15, memory_mb=3072, stdin_text=source)
        if result.returncode != 2 or result.stdout or not result.stderr:
            raise AssertionError(f"native literal input contract accepted {name}: {result}")
    source = cases["unicode"][0]
    command = [str(native), "--literal-spans", str(len(source.encode("utf-8")))]
    first = run_limited(command, cwd=ROOT, timeout_s=15, memory_mb=3072, stdin_text=source)
    second = run_limited(command, cwd=ROOT, timeout_s=15, memory_mb=3072, stdin_text=source)
    if not first.ok or not second.ok or first.stdout != second.stdout or first.stderr or second.stderr:
        raise AssertionError("native literal reports are not repeatable")
    return [Check("native-literal-inputs", "pass", f"{len(cases)} real inputs, 7 rejected frames, deterministic reports")]


def check_literal_composition() -> list[Check]:
    native = binary("ouro-fix")
    cases = (
        ("def a := Nil Nat;\ndef b := Cons Nat 1 (Nil Nat);\ndef c := Nil Nat;\n",
         [":= Nil Nat;", "Cons Nat 1 (Nil Nat)", ":= Nil Nat;"], {2}),
        ("def a := Cons Nat 1 (Nil Nat);\ndef b := Nil Nat;\n",
         ["Cons Nat 1 (Nil Nat)", ":= Nil Nat;"], {1}),
        ("def a := Nil Nat;\ndef b := Nil Nat;\n", [":= Nil Nat;", ":= Nil Nat;"], set()),
        ("def a := Cons Nat (let x := Nil Nat\n in 1) (Nil Nat);\n",
         ["Cons Nat (let x := Nil Nat\n in 1) (Nil Nat)"], set()),
    )
    registry = strict_quality.load_registry()[1]
    for source, expressions, closed_lines in cases:
        spans = []
        position = 0
        for expression in expressions:
            start = source.index(expression, position)
            position = start + len(expression)
            spans.append((start, position))
        facts = syntax_native.native_literal_facts(source, native)
        if facts.spans != spans or facts.closed_lines != closed_lines:
            raise AssertionError(f"native literal composition differs: {facts}, expected {spans}")
        # The same bytes under unrelated names must preserve semantic findings.
        reports = []
        for name in ("literal-original.ouro", "renamed 日本語/ordinary.ouro"):
            findings = strict_quality.scan_source(OUT / name, source, registry, "release", native)
            reports.append([{key: value for key, value in finding.__dict__.items() if key != "path"}
                            for finding in findings if finding.code == "OURO-LINT029"])
        if reports[0] != reports[1] or len(reports[0]) != len(spans):
            raise AssertionError("LINT029 depends on source name or duplicates a nested literal")
    return [Check("native-literal-composition", "pass", "4 ordered/disjoint combinations and source rename parity")]


def check_literal_report_failures() -> list[Check]:
    clean = {"kind": "ouro.fix-literal-spans.v2", "input_bytes": 3,
             "spans": [[0, 3]], "closed_lines": [1], "complete": True}
    for field, value in (
        ("kind", "unknown"), ("kind", "ouro.fix-literal-spans.v1"),
        ("input_bytes", True), ("input_bytes", 2), ("complete", False),
        ("spans", [[True, 3]]), ("spans", [[0, 4]]), ("spans", [[2, 1]]),
        ("spans", [[0, 2], [1, 3]]), ("closed_lines", [1, 1]), ("closed_lines", [0]),
        ("closed_lines", [2]), ("extra", 0),
    ):
        report = deepcopy(clean)
        report[field] = value
        try:
            syntax_native.validate_literal_report(report, "abc")
        except ValueError:
            continue
        raise AssertionError(f"native literal report accepted damaged {field}={value!r}")
    for status, code, stdout, stderr in (
        ("timeout", None, "", ""), ("oom", None, "", ""), ("spawn-error", None, "", ""),
        ("ok", 1, "{}", ""), ("ok", 0, "{", ""), ("ok", 0, "{}\nextra", ""),
        ("ok", 0, '{"kind":"one","kind":"two"}', ""), ("ok", 0, "{}", "worker error"),
    ):
        outcome = SimpleNamespace(ok=status == "ok" and code == 0, status=status,
                                  returncode=code, stdout=stdout, stderr=stderr)
        # Stand-ins exercise only process/report transport, never rule precision.
        with patch("ourosmith.limits.run_limited", return_value=outcome):
            try:
                syntax_native.native_literal_facts("abc", OUT / "protocol-stand-in")
            except ValueError:
                continue
            raise AssertionError(f"native literal transport accepted {status} exit={code}")
    broken = deepcopy(clean)
    broken["spans"] = [[0, 1]]
    try:
        syntax_native.validate_literal_report(broken, "漢")
    except ValueError:
        pass
    else:
        raise AssertionError("native literal transport accepted a split UTF-8 character")
    return [Check("native-literal-report-errors", "pass", "strict schema and failed process transport")]


def check_native_inventory() -> list[Check]:
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    native = prepare_entry("tools/quality/inventory.ouro", "ouro-quality-inputs")
    root = OUT / "native-inventory"
    names = {
        "std/clean.ouro", "std/bad_name.ouro", "std/bad_directory/kept.ouro",
        "std/_build/hidden.ouro", "std/node_modules/package.ouro",
        "tools/generated/output.ouro", "tools/output.generated.ouro",
        "samples/tutorial/04_holes.ouro", "std/漢字 space/--value.ouro",
    }
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def value : Nat := 0;\n", encoding="utf-8", newline="")
    empty = root / "empty"
    empty.mkdir(exist_ok=True)
    plain = root / "plain.txt"
    plain.write_text("source", encoding="utf-8")
    strict_visible = {"std/clean.ouro", "std/bad_directory/kept.ouro", "std/漢字 space/--value.ouro"}
    strict_fixtures = strict_visible | {"std/bad_name.ouro", "samples/tutorial/04_holes.ouro"}
    scopes = [str(root)]
    for mode, visibility, expected in (
        ("strict", "exclude", strict_visible), ("strict", "include", strict_fixtures),
        ("clippy", "exclude", names - {"std/_build/hidden.ouro"}), ("clippy", "include", names),
    ):
        command = [str(native), mode, visibility, str(root), *scopes]
        first = run_limited(command, cwd=ROOT, timeout_s=30, memory_mb=3072)
        second = run_limited(command, cwd=ROOT, timeout_s=30, memory_mb=3072)
        if not first.ok or first.stderr or not second.ok or second.stderr or first.stdout != second.stdout:
            raise AssertionError(f"native inventory failed or was not repeatable: {mode}/{visibility}: {first}")
        report = json.loads(first.stdout)
        expected_report = {"kind": "ouro.quality-inputs.v1", "mode": mode, "include_fixtures": visibility == "include",
                           "root": root.as_posix(), "scopes": scopes, "files": sorted((root / p).as_posix() for p in expected),
                           "complete": True}
        expected_text = json.dumps(expected_report, ensure_ascii=False, separators=(",", ":")) + "\n"
        if report != expected_report or first.stdout != expected_text:
            raise AssertionError(f"native inventory policy differs for {mode}/{visibility}: {report}")
    single = root / "std/漢字 space/--value.ouro"
    overlapping = [str(single.parent), str(single), str(single.parent / ".." / single.parent.name / single.name)]
    result = run_limited([str(native), "strict", "include", str(root), *overlapping],
                         cwd=ROOT, timeout_s=30, memory_mb=3072)
    if not result.ok or result.stderr or json.loads(result.stdout)["files"] != [single.as_posix()]:
        raise AssertionError("native inventory lost Unicode or duplicated overlapping roots")
    rejected = (
        ([], 2), (["unknown", "include", str(root), str(single)], 2),
        (["strict", "unknown", str(root), str(single)], 2),
        (["strict", "include", str(root)], 2),
        (["strict", "include", str(root), str(empty)], 1),
        (["strict", "include", str(root), str(plain)], 1),
        (["strict", "include", str(root), str(root / "missing")], 1),
        (["strict", "include", str(root), str(single), str(root / "missing")], 1),
        (["strict", "include", str(single), str(single)], 1),
        (["strict", "include", str(root), str(ROOT / "std")], 1),
    )
    for values, code in rejected:
        result = run_limited([str(native), *values], cwd=ROOT, timeout_s=30, memory_mb=3072)
        if result.returncode != code or result.stdout or not result.stderr:
            raise AssertionError(f"native inventory accepted invalid input {values}: {result}")
    link = root / "unsafe-link"
    if os.name == "nt":
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root / "std")],
                                 text=True, capture_output=True, check=False)
        if created.returncode:
            raise AssertionError("cannot prepare inventory junction test: " + created.stderr)
    else:
        link.symlink_to(root / "std", target_is_directory=True)
    try:
        for scope in (link, root):
            result = run_limited([str(native), "strict", "include", str(root), str(scope)],
                                 cwd=ROOT, timeout_s=30, memory_mb=3072)
            if result.returncode != 1 or result.stdout or not result.stderr:
                raise AssertionError("native inventory accepted a linked root or published a partial walk")
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()
    requested = [str(single)]
    clean = {"kind": "ouro.quality-inputs.v1", "mode": "strict", "include_fixtures": True,
             "root": ROOT.as_posix(), "scopes": requested, "files": [single.as_posix()], "complete": True}
    for field, value in (
        ("complete", False), ("complete", 1), ("files", []), ("files", [single.as_posix()] * 2),
        ("files", [plain.as_posix()]), ("files", [str(root / "missing.ouro")]),
        ("files", [(root / "std/clean.ouro").as_posix()]), ("scopes", []),
        ("root", root.as_posix()), ("mode", "clippy"), ("include_fixtures", 1), ("extra", 0),
    ):
        broken = dict(clean)
        broken[field] = value
        outcome = SimpleNamespace(ok=True, status="ok", returncode=0, stdout=json.dumps(broken), stderr="")
        # Stand-ins verify report transport, after real binaries established selection.
        with patch("ourosmith.host.prepare_entry", return_value=native), patch("ourosmith.limits.run_limited", return_value=outcome):
            try:
                syntax_native.native_quality_inventory("strict", requested, True)
            except ValueError:
                continue
        raise AssertionError(f"native inventory accepted damaged report field {field}")
    return [Check("native-quality-inventory", "pass", "4 policies, deterministic/overlapping Unicode scopes, 12 rejected inputs, 12 damaged reports")]


def check_inventory_scale() -> list[Check]:
    from ourosmith.limits import run_limited

    native = binary("ouro-quality-inputs")
    root = OUT / "inventory-scale"
    root.mkdir(exist_ok=True)
    names = [f"source-{index:05d}.ouro" for index in range(4096)]
    for name in reversed(names):
        (root / name).write_bytes(b"def value : Nat := 0;\n")
    command = [str(native), "strict", "include", str(ROOT), str(root)]
    # Leave space for the independent observer inside the enclosing 3 GiB job.
    result = run_limited(command, cwd=ROOT, timeout_s=60, memory_mb=2944)
    expected = [str((root / name).as_posix()) for name in names]
    if not result.ok or result.stderr:
        raise AssertionError(f"native inventory could not finish 4096 sources: {result.status}/{result.returncode}")
    report = json.loads(result.stdout)
    if report.get("complete") is not True or report.get("files") != expected:
        raise AssertionError("native inventory dropped or reordered a source in the large corpus")
    repeated = run_limited(command, cwd=ROOT, timeout_s=60, memory_mb=2944)
    if not repeated.ok or repeated.stderr or repeated.stdout != result.stdout:
        raise AssertionError("large native inventory report is not repeatable")
    return [Check("native-inventory-scale", "pass", "4096 exact paths, complete and byte-repeatable within 2944 MiB")]


def strict_scan(scope: str, name: str, *, expect_rc: int, include_fixtures: bool = True) -> dict[str, Any]:
    report = OUT / f"{name}.json"
    sarif = OUT / f"{name}.sarif"
    migration = OUT / f"{name}.md"
    for artifact in (report, sarif, migration):
        artifact.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        "scripts/strict_quality_firewall.py",
        "--profile",
        "release",
        "--scope",
        scope,
        "--skip-fixture-check",
        "--report",
        rel(report),
        "--sarif",
        rel(sarif),
        "--migration-report",
        rel(migration),
    ]
    if include_fixtures:
        cmd.append("--include-fixtures")
    run(cmd, expect=expect_rc, stdout=OUT / f"{name}.log")
    return load_json_object(report)


def check_syntax_fixtures() -> list[Check]:
    _cfg, registry = strict_quality.load_registry()
    bad_path = ROOT / "quality" / "fixtures" / "bad" / "syntax_surface.ouro"
    good_path = ROOT / "quality" / "fixtures" / "good" / "syntax_surface.ouro"
    bad_findings = strict_quality.scan_source(bad_path, bad_path.read_text(encoding="utf-8"), registry, "release")
    good_findings = strict_quality.scan_source(good_path, good_path.read_text(encoding="utf-8"), registry, "release")
    bad_codes = {finding.code for finding in bad_findings}
    missing = sorted(EXPECTED_SYNTAX_CODES - bad_codes)
    if missing:
        raise AssertionError(f"bad syntax fixture did not emit {missing}")
    retired_hits = sorted(RETIRED_SYNTAX_CODES & bad_codes)
    if retired_hits:
        raise AssertionError(f"retired syntax rule fired on bad fixture: {retired_hits}")
    if good_findings:
        rendered = [f"{f.code}:{f.line}" for f in good_findings]
        raise AssertionError(f"good syntax fixture emitted findings: {rendered}")
    return [
        Check("bad-syntax-surface", "pass", ", ".join(sorted(bad_codes))),
        Check("good-syntax-surface", "pass", "no findings"),
    ]


def check_suppression_comments() -> Check:
    registry = strict_quality.load_registry()[1]
    for source in ('def text : String := "ouro-lint:disable-all";\n',
                   'def text : String := "-- ouro-lint:disable=*";\n',
                   'def value\' : Nat := 0; -- ouro-lint:disable=OURO-LINT029 reason=local-example\n'):
        findings = strict_quality.scan_source(OUT / "suppression-comments.ouro", source, registry, "release")
        if any(f.code.startswith("OURO-SUP") for f in findings):
            raise AssertionError(f"suppression scanner treated literal bytes as a directive: {source!r}")
    source = 'def text : String := "漢字 -- ouro-lint:disable-all"; -- ouro-lint:disable-all\n'
    findings = strict_quality.scan_source(OUT / "suppression-comments.ouro", source, registry, "release")
    expected_column = len(source[:source.rindex("ouro-lint:disable-all")].encode("utf-8")) + 1
    if [(f.code, f.line, f.column) for f in findings] != [("OURO-SUP001", 1, expected_column)]:
        raise AssertionError(f"real trailing suppression or its byte position was lost: {findings}")
    return Check("suppression-comments", "pass", "literal preservation, quoted comment markers, trailing directive location")


def check_release_firewall() -> Check:
    report = OUT / "release.json"
    sarif = OUT / "release.sarif"
    migration = OUT / "release.md"
    run([
        sys.executable,
        "scripts/strict_quality_firewall.py",
        "--profile",
        "release",
        "--report",
        rel(report),
        "--sarif",
        rel(sarif),
        "--migration-report",
        rel(migration),
    ], stdout=OUT / "release.log")
    data = load_json_object(report)
    debt = data.get("diagnostics_debt_allowed")
    blocking = data.get("diagnostics_blocking")
    if debt != 0 or blocking != 0:
        raise AssertionError(f"unexpected release firewall counts debt={debt} blocking={blocking}")
    return Check("release-firewall", "pass", f"debt={debt} blocking={blocking}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    try:
        checks.append(check_rejected_manifest())
        checks.extend(check_fix_cases())
        checks.extend(check_native_fix_boundaries())
        checks.extend(check_fix_metadata())
        checks.extend(check_literal_protocol())
        checks.extend(check_literal_composition())
        checks.extend(check_literal_report_failures())
        checks.extend(check_native_inventory())
        checks.extend(check_inventory_scale())
        checks.extend(check_syntax_fixtures())
        checks.append(check_suppression_comments())
        checks.append(check_release_firewall())
    except (AssertionError, OSError, UnicodeError, ValueError) as exc:
        report = {
            "kind": "ouro.syntax-quality-suite-report.v1",
            "pass": False,
            "checks": [c.__dict__ for c in checks],
            "error": str(exc),
        }
        write_json_atomic(OUT / "syntax-quality-firewall.json", report)
        print(f"SYNTAX_QUALITY_SUITE: FAIL {exc}", file=sys.stderr)
        return 1
    report = {
        "kind": "ouro.syntax-quality-suite-report.v1",
        "pass": True,
        "checks": [c.__dict__ for c in checks],
    }
    write_json_atomic(OUT / "syntax-quality-firewall.json", report)
    for c in checks:
        print(f"SYNTAX_QUALITY_CHECK {c.status} {c.name} {c.detail}")
    print(f"SYNTAX_QUALITY_SUITE: PASS report={rel(OUT / 'syntax-quality-firewall.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
