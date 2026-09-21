#!/usr/bin/env python3
"""Independent CLI observations of compiler-checked source publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from repo_support import configure_native_stack

ROOT = Path(__file__).resolve().parents[1]
UNIT = "inductive Unit : Type := | UnitValue : Unit;\n"


def protocol_worker(path: Path) -> None:
    # A stand-in tests only launch/result handling. Semantic cases below use
    # the real compiler worker. No production fallback or test switch exists.
    source = path.with_suffix(".c")
    source.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif
int main(int argc, char **argv) {
  const char *mode = getenv("OURO_FIX_CHECK_TEST_MODE");
  if (!mode || argc != 3) return 3;
  if (!strcmp(mode, "exit")) return 9;
  if (!strcmp(mode, "empty")) return 0;
  if (!strcmp(mode, "timeout")) {
#ifdef _WIN32
    Sleep(130000);
#else
    sleep(130);
#endif
    return 0;
  }
  if (!strcmp(mode, "memory")) {
    for (;;) {
      volatile unsigned char *block = malloc(64 * 1024 * 1024);
      if (!block) return 23;
      for (size_t i = 0; i < 64 * 1024 * 1024; i += 4096) block[i] = 1;
    }
  }
  if (!strcmp(mode, "stderr")) fputs("unexpected diagnostic\n", stderr);
  if (!strcmp(mode, "damaged")) { puts("complete"); return 0; }
  printf("ouro.fix-check.v1\t%s\t%s\tcomplete\n%s",
         !strcmp(mode, "bytes") ? "0" : argv[2],
         !strcmp(mode, "zero-units") ? "0" : !strcmp(mode, "noncanonical") ? "01" : "1",
         !strcmp(mode, "trailing") ? "extra\n" : "");
  return 0;
}
''', encoding="utf-8")
    compiler = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc")
    if not compiler:
        raise RuntimeError("C compiler unavailable for independent process-protocol stand-ins")
    subprocess.run([compiler, str(source), "-o", str(path)], check=True, capture_output=True, timeout=60)


def run_suite(fixer: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    worker = fixer.with_name("ouro-fix-check" + (".exe" if os.name == "nt" else ""))
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (fixer, worker)}
    env = dict(os.environ)
    if os.name == "nt":
        env["PATH"] = str(Path(env["SYSTEMROOT"]) / "System32")
    env["PYTHON"] = env["PYTHON3"] = str(out / "python-unavailable")
    rows = []

    def invoke(name, command, *, source=None, success=True, contains=""):
        result = subprocess.run([str(part) for part in command], cwd=out, env=env,
                                input=source, capture_output=True, timeout=150)
        text = (result.stdout + result.stderr).decode("utf-8", errors="strict")
        rows.append(dict(name=name, command=[str(part) for part in command], exit=result.returncode,
                         stdout=result.stdout.decode("utf-8"), stderr=result.stderr.decode("utf-8")))
        assert (result.returncode == 0) is success, rows[-1]
        if not success:
            assert not result.stdout and result.stderr, rows[-1]
        assert contains in text, rows[-1]
        print("FIX_CHECK_OK", name, flush=True)
        return result

    def refusal(name, source, *, dependencies=(), mode="--write"):
        directory = out / name
        directory.mkdir(exist_ok=True)
        for filename, content in dependencies:
            (directory / filename).write_text(content, encoding="utf-8", newline="")
        path = directory / "source.ouro"
        path.write_text(source, encoding="utf-8", newline="")
        original = path.read_bytes()
        files = sorted(p.name for p in directory.iterdir())
        invoke(name, [fixer, mode, path], success=False)
        assert path.read_bytes() == original
        assert sorted(p.name for p in directory.iterdir()) == files, "refusal left transaction files"

    try:
        refusal("unbound", UNIT + "def main:Unit:=missing_name;\n")
        refusal("wrong-type", UNIT + "def main:Unit:=Type;\n")
        refusal("parse-error", UNIT + "def main:Unit:=;\n")
        refusal("clean-invalid", UNIT + "def main : Unit := missing_name;\n")
        refusal("bad-import", 'import "dep.ouro";\ndef main:Unit:=UnitValue;\n',
                dependencies=[("dep.ouro", UNIT + "def invalid : Unit := missing_name;\n")])
        refusal("malformed-import", 'import "dep.ouro";\ndef main:Unit:=UnitValue;\n',
                dependencies=[("dep.ouro", UNIT + "def invalid : Unit :=;\n")])
        refusal("missing-import", 'import "absent.ouro";\ndef main:Unit:=UnitValue;\n')
        refusal("import-cycle", 'import "dep.ouro";\ndef main:Unit:=UnitValue;\n',
                dependencies=[("dep.ouro", 'import "source.ouro";\n' + UNIT)])
        refusal("dead-error-is-not-repaired", UNIT +
                "def main : Unit := let discarded : Unit := missing_name in UnitValue;\n")

        directory = out / ("каталог \u0441 пробелами")
        directory.mkdir(exist_ok=True)
        (directory / "dep.ouro").write_text(UNIT, encoding="utf-8", newline="")
        (directory / "left.ouro").write_text('import "dep.ouro";\ndef left : Unit := UnitValue;\n', encoding="utf-8")
        (directory / "right.ouro").write_text('import "dep.ouro";\ndef right : Unit := UnitValue;\n', encoding="utf-8")
        path = directory / "漢字 source.ouro"
        # The fixer normalizes only ":=" spacing (tools/analyze/format.ouro;
        # same shape as the fix_suite.sh unicode contract), so the diamond
        # keeps ":" spaced and tests the import/Unicode path, not colon layout.
        source = 'import "left.ouro";\nimport "right.ouro";\ndef main : Unit :=left;\n'
        expected = 'import "left.ouro";\nimport "right.ouro";\ndef main : Unit := left;\n'
        path.write_text(source, encoding="utf-8", newline="")
        invoke("valid-import-diamond", [fixer, "--write", path])
        assert path.read_text(encoding="utf-8") == expected
        invoke("valid-check", [fixer, "--check", path])
        result = invoke("valid-repeat", [fixer, "--write", path])
        assert not result.stdout and not result.stderr and path.read_text(encoding="utf-8") == expected
        result = invoke("worker-full-closure", [worker, path, len(expected.encode())], source=expected.encode())
        assert result.stdout.decode().replace("\r\n", "\n") == f"ouro.fix-check.v1\t{len(expected.encode())}\t4\tcomplete\n"
        result = invoke("worker-file-mode", [worker, path, "file", path])
        assert result.stdout.decode().replace("\r\n", "\n") == f"ouro.fix-check.v1\t{len(expected.encode())}\t4\tcomplete\n"
        bad = directory / "bad-candidate.ouro"
        bad.write_text(UNIT + "def main : Unit := unknown;\n", encoding="utf-8", newline="")
        invoke("worker-file-rejected", [worker, path, "file", bad], success=False)
        invoke("worker-file-missing", [worker, path, "file", directory / "absent-candidate.ouro"], success=False)
        assert path.read_text(encoding="utf-8") == expected
        for name, size, content in (
            ("worker-short", len(expected.encode()) + 1, expected.encode()),
            ("worker-excess", len(expected.encode()) - 1, expected.encode()),
            ("worker-byte-budget", 8388609, b""),
            ("worker-invalid-count", "--write", b""),
            ("worker-rejected-candidate", len(UNIT + "def main : Unit := unknown;\n"), (UNIT + "def main : Unit := unknown;\n").encode()),
        ):
            invoke(name, [worker, path, size], source=content, success=False)
            assert path.read_text(encoding="utf-8") == expected
        invoke("worker-extra-argument", [worker, path, "0", "extra"], success=False)
        invoke("worker-missing-root", [worker, directory / "absent.ouro", "0"], source=b"", success=False)
        invoke("worker-directory-root", [worker, directory, "0"], source=b"", success=False)
        large = out / "large-source.ouro"
        # Single comment lines beyond ~32-64KB are rejected by the checker
        # itself (worker matches P2: CErr 10:0), so total-size framing is
        # tested with many short lines instead of one giant line.
        large_source = "-- pad line\n" * 11000 + UNIT + "def main : Unit := UnitValue;\n"
        large.write_text(large_source, encoding="utf-8", newline="")
        invoke("worker-large-source", [worker, large, len(large_source)], source=large_source.encode())
        many = out / "wide-imports"
        many.mkdir(exist_ok=True)
        imports = []
        for index in range(512):
            name = f"dep{index}.ouro"
            (many / name).write_text(f"inductive Item{index} : Type := | Value{index} : Item{index};\n", encoding="utf-8")
            imports.append(f'import "{name}";\n')
        many_source = "".join(imports) + UNIT
        many_root = many / "source.ouro"
        many_root.write_text(many_source, encoding="utf-8", newline="")
        invoke("worker-wide-import-budget", [worker, many_root, len(many_source)], source=many_source.encode(),
               success=False, contains="unit budget exhausted")

        isolated = out / "missing-worker"
        if isolated.exists():
            shutil.rmtree(isolated)
        isolated.mkdir()
        standalone = isolated / fixer.name
        shutil.copy2(fixer, standalone)
        path = isolated / "source.ouro"
        source = UNIT + "def main:Unit:=UnitValue;\n"
        path.write_text(source, encoding="utf-8", newline="")
        invoke("missing-worker-refusal", [standalone, "--write", path], success=False, contains="worker unavailable")
        assert path.read_text(encoding="utf-8") == source
        protocol_worker(isolated / worker.name)
        for mode in ("exit", "empty", "damaged", "bytes", "zero-units", "noncanonical", "trailing", "stderr", "memory", "timeout"):
            env["OURO_FIX_CHECK_TEST_MODE"] = mode
            invoke("worker-protocol-" + mode, [standalone, "--write", path], success=False,
                   contains=("timeout" if mode == "timeout" and os.name == "nt"
                             else "fix refused"))
            assert path.read_text(encoding="utf-8") == source
    finally:
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in hashes.items())
        (out / "report.json").write_text(json.dumps(dict(kind="ouro.fix-check-observer.v1",
            binaries=hashes, rows=rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"FIX_CHECK_SUITE: PASS rows={len(rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Match other native-compiler Python launchers. ELF children inherit this
    # process's stack; the worker also reserves 128 MiB itself at startup.
    configure_native_stack()
    run_suite(args.fix.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
