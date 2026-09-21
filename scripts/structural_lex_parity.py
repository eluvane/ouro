#!/usr/bin/env python3
"""Compare tools/structural/lex_driver.ouro with structural_quality_legacy.lex.

The native driver is a transport for st_lex only. This script does not port
symbols, findings, or the structural launcher. Python remains the owner of
those layers.

Exit codes:
  0  native tokens/comments (or error text) match the Python oracle
  1  corpus, oracle, or native mismatch
  2  malformed invocation
 77  corpus matches the Python oracle; native driver is unavailable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import structural_quality_legacy as legacy

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "quality" / "fixtures" / "structural_lex"
DRIVER = ROOT / "tools" / "structural" / "lex_driver.ouro"
COMPILER = ROOT / "_build" / "c" / "ouro1"
OURO1 = ROOT / "scripts" / "ouro1.sh"
UNAVAILABLE = 77


def fail(message: str, code: int = 1) -> int:
    print(f"structural-lex-parity: {message}", file=sys.stderr)
    return code


def oracle_result(source: str, language: str) -> dict:
    try:
        tokens, comments = legacy.lex(source, language)
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "tokens": [{"value": token.value, "start": token.start, "end": token.end,
                    "line": token.line} for token in tokens],
        "comments": [{"line": line, "text": text} for line, text in comments],
    }


def load_cases(corpus: Path = CORPUS) -> list[dict]:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "ouro.structural-lex-corpus.v1":
        raise ValueError("structural lex manifest kind must be ouro.structural-lex-corpus.v1")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("structural lex manifest must list cases")
    loaded = []
    names = []
    for case in cases:
        if not isinstance(case, dict) or "name" not in case or "file" not in case:
            raise ValueError("each lex case needs name and file")
        name = case["name"]
        if name in names:
            raise ValueError(f"duplicate lex case name: {name}")
        names.append(name)
        path = corpus / case["file"]
        if not path.is_file() or not path.resolve().is_relative_to(corpus.resolve()):
            raise ValueError(f"lex fixture escapes corpus or is missing: {case['file']}")
        language = case.get("language")
        if not isinstance(language, str) or not language:
            raise ValueError(f"{name}: language must be a non-empty string")
        loaded.append({
            "name": name,
            "file": case["file"],
            "language": language,
            "error": bool(case.get("error", False)),
            "source": path.read_text(encoding="utf-8"),
        })
    return loaded


def check_oracle(cases: list[dict]) -> list[dict]:
    expected = []
    for case in cases:
        result = oracle_result(case["source"], case["language"])
        has_error = "error" in result
        if case["error"] != has_error:
            raise ValueError(
                f"{case['name']}: oracle error={has_error} expected={case['error']}"
                + (f" ({result['error']})" if has_error else ""))
        expected.append(result)
    return expected


def check_native_sources() -> str | None:
    if not COMPILER.is_file() or not OURO1.is_file():
        return None
    for path in (ROOT / "tools/structural/lex.ouro", DRIVER):
        process = subprocess.run(
            ["sh", str(OURO1), "check", str(path.relative_to(ROOT)), "60000"],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        stdout = process.stdout.replace("\r\n", "\n")
        if process.returncode != 0 or stdout.splitlines() != ["CHECK_OK"]:
            raise ValueError(
                f"ouro1 check {path.relative_to(ROOT)} failed "
                f"exit={process.returncode}: {stdout}{process.stderr}")
    return "checked"


def native_argv() -> list[str] | None:
    override = os.environ.get("OURO_STRUCTURAL_LEX_DRIVER")
    if override:
        return [override]
    built = ROOT / "_build" / "native" / "run" / "lex_driver.exe"
    if built.is_file():
        return [str(built)]
    # `ouro1.sh run` lowers the driver to C. That path is opt-in: this host's
    # generated C has exceeded clang's default bracket-nesting limit.
    if os.environ.get("OURO_STRUCTURAL_LEX_BUILD") == "1" and COMPILER.is_file() and OURO1.is_file():
        return ["sh", str(OURO1), "run", str(DRIVER)]
    return None


def run_native(argv: list[str], source: str, language: str) -> dict:
    payload = json.dumps({"source": source, "language": language},
                         ensure_ascii=False, separators=(",", ":"))
    process = subprocess.run(argv, input=payload, capture_output=True, text=True,
                             cwd=ROOT, timeout=600)
    if process.returncode not in {0, 2}:
        raise ValueError(
            f"native driver exit {process.returncode}: {process.stderr.strip()}")
    try:
        document = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"native driver stdout is not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("native driver result must be a JSON object")
    if process.returncode == 2:
        raise ValueError(f"native driver rejected request: {document}")
    if "error" in document:
        if set(document) != {"error"} or not isinstance(document["error"], str):
            raise ValueError(f"native error object is malformed: {document}")
        return {"error": document["error"]}
    if set(document) != {"tokens", "comments"}:
        raise ValueError(f"native success object keys must be tokens/comments: {document}")
    return document


def compare(name: str, expected: dict, actual: dict) -> None:
    if expected != actual:
        raise ValueError(
            f"{name}: native result differs from structural_quality_legacy.lex\n"
            f"  oracle={json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
            f"  native={json.dumps(actual, ensure_ascii=False, sort_keys=True)}")


def main() -> int:
    try:
        cases = load_cases()
        expected = check_oracle(cases)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return fail(str(exc))
    try:
        checked = check_native_sources()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return fail(str(exc))
    argv = native_argv()
    if argv is None:
        suffix = " after ouro1 check" if checked else ""
        print("structural-lex-parity: python oracle matched "
              f"{len(cases)} fixtures{suffix}; native driver unavailable",
              file=sys.stderr)
        return UNAVAILABLE
    try:
        for case, oracle in zip(cases, expected, strict=True):
            compare(case["name"], oracle, run_native(argv, case["source"], case["language"]))
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        return fail(str(exc))
    print(f"structural-lex-parity: {len(cases)} fixtures match native st_lex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
