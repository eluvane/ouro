#!/usr/bin/env python3
"""Exercise real parser/checker/fmt/fix entry points for ergonomic syntax."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ourosmith.ergonomics_inputs import (
    LINT_DIAGNOSTICS, ROOT, import_cases, load_cases, render, support_source,
)


def assert_lint(result, path, expected):
    if result.returncode != (1 if expected else 0) or result.stderr:
        raise AssertionError(f"unexpected lint status/stderr: {path}\n{result.stdout}{result.stderr}")
    actual = []
    prefix = re.escape(path.as_posix()) + r":[1-9][0-9]*:[1-9][0-9]*: warning\[(OURO-LINT[0-9]+)\] (.+)"
    for line in result.stdout.splitlines():
        diagnostic = re.fullmatch(prefix, line)
        if diagnostic is None or LINT_DIAGNOSTICS.get(diagnostic[1]) != diagnostic[2]:
            raise AssertionError(f"unexpected lint diagnostic: {path}\n{line}")
        actual.append(diagnostic[1])
    if actual != expected:
        raise AssertionError(f"lint diagnostics for {path}: expected {expected}, got {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    manifest = load_cases()
    imports = list(import_cases())
    if args.validate_manifest:
        print(f"ERGO_MANIFEST_OK: {len(manifest['positive'])} equivalence, "
              f"{len(manifest['negative'])} negative, {len(imports)} import cases; compiler not run")
        return 0
    for required in ("scripts/ouro1.sh", "scripts/build_tool.sh", "compiler/stage0"):
        if not (ROOT / required).exists():
            raise RuntimeError("full checkout required; missing " + required)
    out = ROOT / "_build/language_ergonomics"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=out))
    command_number = 0

    def run(command, *, fail_marker=None, expected_exit=0):
        nonlocal command_number
        command_number += 1
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=args.timeout,
                                env=os.environ.copy(), check=False)
        text = result.stdout + result.stderr
        (work / f"command-{command_number:03d}.log").write_text(
            repr(command) + "\nexit=" + str(result.returncode) + "\n" + text, encoding="utf-8")
        if fail_marker is None:
            if result.returncode != expected_exit:
                raise AssertionError(f"command failed ({result.returncode}): {command}\n{text}")
        elif result.returncode != 1 or fail_marker not in text:
            raise AssertionError(f"expected controlled rejection {fail_marker!r}: {command}\n{text}")
        return result

    def ouro(*arguments, fail_marker=None, expected_exit=0):
        return run(["sh", "scripts/ouro1.sh", *map(str, arguments)],
                   fail_marker=fail_marker, expected_exit=expected_exit)

    def lint(path, family, expected):
        result = ouro("lint", "--family", family, path, expected_exit=1 if expected else 0)
        assert_lint(result, path, expected)

    def checked(path):
        result = ouro("check", path, "60000")
        if "CHECK_OK" not in result.stdout + result.stderr:
            raise AssertionError("missing CHECK_OK: " + str(path))

    def fixture(name, source, dependencies):
        directory = work / name
        directory.mkdir(parents=True)
        for spelling, content in dependencies:
            target = directory / spelling
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        path = directory / "main.ouro"
        path.write_text(source, encoding="utf-8")
        return path

    # Verify and install the current compiler, reusing source-bound build evidence.
    run([sys.executable, "scripts/ouro_build.py", "build"])
    # A fresh native binary avoids silently testing only the stage0 parser.
    driver = work / "parser-laws"
    run(["sh", "scripts/build_tool.sh", "tests/language_ergonomics/parser_laws.ouro",
         str(driver), "60000"])
    if driver.with_suffix(".exe").exists():
        driver = driver.with_suffix(".exe")
    result = run([str(driver)])
    if "ERGO_PARSER_OK" not in result.stdout:
        raise AssertionError("native parser laws did not report success")

    support = (("support.ouro", support_source()),)
    canary = fixture("canary", 'import "support.ouro";\ndef valid : ErgNat := ErgZero;\n', support)
    checked(canary)
    for case in manifest["positive"]:
        path = fixture(case["name"], render(case, work / case["name"]), support)
        checked(path)  # The kernel checks sugar == canonical via ErgRefl.
        original = path.read_text(encoding="utf-8")
        comments = [line[line.index("--"):] for line in original.splitlines() if "--" in line]
        ouro("fmt", "--write", path)
        first = path.read_bytes()
        checked(path)
        ouro("fmt", "--check", path)
        ouro("fmt", "--write", path)
        if first != path.read_bytes():
            raise AssertionError("formatter not idempotent: " + case["name"])
        formatted = first.decode("utf-8")
        if any(comment not in formatted for comment in comments):
            raise AssertionError("formatter lost a comment: " + case["name"])
        if "lint" in case:
            # Intentional shadowing/unused binders remain exact, required diagnostics.
            for variant, key in (("candidate", "sugar"), ("canonical", "canonical")):
                name = case["name"] + "-lint-" + variant
                lint_case = dict(case, source=f'def ergo_expansion_{variant} : ({case["type"]}) := {case[key]};')
                lint_path = fixture(name, render(lint_case, work / name), support)
                for family in ("language", "semantic"):
                    lint(lint_path, family, case["lint"][family][variant])
        else:
            for family in ("language", "semantic"):
                lint(path, family, [])
        ouro("fix", "--write", path)
        checked(path)
    for case in manifest["negative"]:
        path = fixture(case["name"], render(case, work / case["name"]), support)
        ouro("check", path, "60000", fail_marker="CHECK_FAIL")
    checked(canary)  # Toolchain failures must not turn negatives into a pass.
    for name, source, verdict, diagnostic, dependencies in imports:
        path = fixture("import-" + name, source, dependencies)
        if name in ("unicode", "unicode-single"):
            path = path.rename(path.with_name("корень 漢字.ouro"))
        if verdict == "fail":
            ouro("collect", path, fail_marker=diagnostic)
            continue
        checked(path)
        collected = ouro("collect", path).stdout.replace("\\", "/")
        for suffix in ("left/common.ouro", "right/common.ouro"):
            if sum(line.strip().endswith(suffix) for line in collected.splitlines()) != 1:
                raise AssertionError("dependency missing or duplicated: " + name + " / " + suffix)
        ouro("fmt", "--write", path)
        first = path.read_bytes()
        ouro("fmt", "--check", path)
        ouro("fmt", "--write", path)
        if first != path.read_bytes():
            raise AssertionError("import formatting not idempotent: " + name)
        checked(path)
        # A duplicate first path must not cause deletion of the whole group.
        ouro("fix", "--write", path)
        checked(path)
    checked(canary)
    print(f"ERGO_SUITE_OK: {command_number} commands; logs: {work}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        print("ERGO_SUITE_FAIL: " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
