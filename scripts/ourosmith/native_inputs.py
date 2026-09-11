"""Materialize native selftest inputs from the independent Smith specifications."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ourosmith import ROOT
from ourosmith.surface.doc_contract import program as documentation
from ourosmith.surface.gen import generate, program
from ourosmith.surface.lint_contracts import cases as lint_programs
from ourosmith.surface.mutate import mutations
from ourosmith.surface.text_contracts import cases

GROUPS = ("fmt", "fix", "doc", "lint", "manifest", "runtime", "test", "lsp", "security")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def prepare(group, out, seed):
    if group not in GROUPS or seed < 0:
        raise ValueError("known selftest group and nonnegative seed required")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=group + "-", dir=out))
    if group in {"fmt", "fix"}:
        names = {"fmt-clean": "clean", "fmt-layout": "messy", "fmt-syntax": "syntax_keep"}
        for case in cases(seed):
            if case.tool != group or (group == "fmt" and case.name not in names):
                continue
            name = names[case.name] if group == "fmt" else case.name
            write(root / (name + ".in"), case.source)
            write(root / (name + ".golden"), case.expected)
    elif group == "doc":
        dependency = os.path.relpath(ROOT / "std/prelude.ouro", root).replace("\\", "/")
        source, expected, _signature, _prose = documentation(seed, dependency)
        path = root / "sample.ouro"
        write(path, source)
        write(root / "sample.golden.md", "# " + path.as_posix() + "\n\n" + expected)
    elif group == "lint":
        for mutation in mutations(seed):
            if mutation.tool == "lint":
                write(root / "bad" / (mutation.name + ".ouro"), mutation.source)
        padding = "-- " + "x" * 15000 + "\n"
        declaration = "inductive Value : Type := | Keep : Value;\n"
        write(root / "bad" / "large-source.ouro", padding + declaration
              + "def main (value : Value) : Value := missing;\n")
        write(root / "good" / "large-source.ouro", padding + declaration
              + "def main (value : Value) : Value := value;\n")
        write(root / "bad" / "unsupported-mutual.ouro", "mutual\n" + declaration + "end\n")
        write(root / "good" / "_build" / "ignored.ouro", declaration
              + "def main (value : Value) : Value := missing;\n")
        for index in range(5):
            write(root / "good" / f"expression-{index}.ouro", program(generate(seed + index, 3)))
        for name, source, dependencies in lint_programs(seed):
            write(root / "good" / name / "main.ouro", source)
            for filename, text in dependencies:
                write(root / "good" / name / filename, text)
    elif group == "manifest":
        prepare_manifest(root, seed)
    elif group == "runtime":
        for name in ("strings", "data", "crypto"):
            prepare_library(root, name, seed)
        dependency = os.path.relpath(ROOT / "std/processx.ouro", root).replace("\\", "/")
        source = f'''import "{dependency}";
-- @entry main
def main : IO Unit :=
  do let! good := proc_exec "printf" (["shell-{seed}"] : List String);
     let! bad := proc_exec "sh" (["-c", "exit 2"] : List String);
     println (proc_stdout good);
     println (show_nat (proc_code good));
     println (show_nat (proc_code bad));
     exit 0
'''
        write(root / "io_prims.ouro", source)
        write(root / "io_prims.golden", f"shell-{seed}\n0\n2\n")
    elif group == "test":
        prepare_library(root, "helpers", seed)
        prepare_test_runner(root, seed)
    elif group == "lsp":
        dependency = os.path.relpath(ROOT / "std/prelude.ouro", root).replace("\\", "/")
        imports = f'import "{dependency}";\n'
        source = "-- @entry widget\n" + "\n" * (1 + seed % 5) + imports
        source += f'\n-- Doubles a natural.\ndef widget (n : Nat) : Nat := add n n;\n\ndef widget_zero : Nat := widget {seed % 5};\n'
        write(root / "sample.ouro", source)
        write(root / "messy.ouro", "-- @entry messy\n\n" + imports + "\ndef messy : Nat := add (S Z) Z;   \n")
    elif group == "security":
        write(root / "id.ouro", program(generate(seed, 2)))
        write(root / "other.ouro", program(generate(seed + 1, 2)))
        for mutation in mutations(seed):
            if ((mutation.name.startswith("lex-") and mutation.fuel != 0)
                    or mutation.name in {"parse-missing-colon", "record-malformed"}):
                write(root / (mutation.name + ".ouro"), mutation.source)
    return root


def prepare_manifest(root, seed):
    from ourosmith.surface.forms import programs
    from ourosmith.surface.parity import inputs

    rows = []

    def add(name, source, expected, diagnostic, dependencies=()):
        write(root / name / "main.ouro", source)
        for filename, text in dependencies:
            write(root / name / filename, text)
        rows.append(f"{name}\t{name}/main.ouro\tcheck\t{expected}\t0\t{diagnostic}\n")

    for name, source, _value, _units in programs(seed):
        add(("REC." if name == "record" else "ERGO.") + name, source, "pass", "CHECK_OK")
    for case in inputs(seed):
        if case["name"].startswith("imports"):
            name = "qualified" if case["name"] == "imports" else case["name"][8:]
            add("IMP." + name, case["source"], "pass", "CHECK_OK", case["dependencies"])
    for mutation in mutations(seed):
        if mutation.tool != "check" or mutation.fuel != 999999 or len(mutation.diagnostics) != 1:
            continue
        prefix = "IMP." if mutation.name.startswith("import-") else "REC." if mutation.name.startswith("record-") else "ERGO." if mutation.name.startswith(("pipe-", "list-", "do-", "named-hole")) else "CHECK."
        add(prefix + mutation.name, mutation.source, "fail", mutation.diagnostics[0], mutation.dependencies)
    write(root / "manifest.tsv", "".join(rows))
    # The native control-plane selftest retains malformed table contracts and
    # points their safe relative paths at generated programs.
    for filename, contents in {
        "valid.tsv": "SELF.G\tIMP.qualified/main.ouro\tcheck\tpass\t0\tCHECK_OK\nSELF.B\tIMP.import-malformed/main.ouro\tcheck\tfail\t0\tOURO-IMP-001\n",
        "malformed.tsv": "BAD\tmissing.ouro\tcheck\tpass\t0\n",
        "duplicate.tsv": "DUP\tIMP.qualified/main.ouro\tcheck\tpass\t0\t\n" * 2,
        "unsafe.tsv": "UNSAFE\t../outside.ouro\tcheck\tpass\t0\t\n",
        "unsupported.tsv": "UNSUPPORTED\tIMP.qualified/main.ouro\tlint\tpass\t0\t\n",
        "missing.tsv": "MISSING\tnot-present.ouro\tcheck\tpass\t0\t\n",
    }.items():
        write(root / filename, contents)


def prepare_library(root, family, seed):
    from ourosmith.surface.library import FAMILIES

    generate_rows, modules = FAMILIES[family]
    rows = list(generate_rows(seed))
    imports = "".join(f'import "{os.path.relpath(ROOT / name, root).replace(chr(92), "/")}";\n'
                      for name in ("std/io.ouro", "std/format.ouro", *modules))
    source = imports + "\n-- @entry main\ndef main : IO Unit :=\n  do\n"
    source += "".join(f"     println ({expression});\n" for expression, _value in rows) + "     exit 0\n"
    write(root / (family + ".ouro"), source)
    write(root / (family + ".golden"), "".join(value + "\n" for _expression, value in rows))


def prepare_test_runner(root, seed):
    dependency = os.path.relpath(ROOT / "std/test.ouro", root).replace("\\", "/")
    for failing in (False, True):
        names = [f"case{seed}-{i}" for i in range(2 + seed % 4)]
        entries = [f'test_ok "{name}"' for name in names]
        expected = "".join("ok " + name + "\n" for name in names)
        if failing:
            entries.append('test_fail "broken" "intentional"')
            expected += "FAIL broken intentional\n"
        name = "failure" if failing else "success"
        write(root / (name + ".ouro"), f'import "{dependency}";\n-- @entry main\ndef main : IO Unit :=\n  test_run ([' + ", ".join(entries) + "] : List Test)\n")
        write(root / (name + ".golden"), expected)
    compiler = os.path.relpath(ROOT / "compiler/file_elab.ouro", root).replace("\\", "/")
    io_module = os.path.relpath(ROOT / "std/io.ouro", root).replace("\\", "/")
    present, absent = 1 + seed % 5, 10 + seed % 7
    source = f'''import "{compiler}";
import "{io_module}";
def selection_rejected : Bool :=
  match check_file_selected 32 ([{absent}] : List Nat)
    ([FAxiom {present} (CSort Z)] : List FileItem) with
  | FRErr code detail => andb (eqNat code 6) (eqNat detail {absent})
  | FROk _ => False
  end;
-- @entry main
def main : IO Unit :=
  match selection_rejected with | True => exit 0 | False => exit 1 end
'''
    write(root / "selected_declaration.ouro", source)
    write(root / "selected_declaration.golden", "")


def run(args):
    print(prepare(args.group, args.out, args.seed).as_posix())
    return 0


def run_manifest(args):
    from ourosmith.host import binary, ensure_tools, environment
    from ourosmith.limits import run_limited

    if args.seed < 0:
        raise ValueError("nonnegative seed required")
    out = Path(args.out).resolve()
    reason = ensure_tools(out / "build", required=("collect", "test"))
    if reason:
        print("OURO_SMITH: manifest unavailable: " + reason)
        return 1
    fixtures = prepare("manifest", out / "inputs", args.seed)
    result = run_limited([binary("ouro-test").as_posix(), "--manifest=" + (fixtures / "manifest.tsv").as_posix(),
                          "--prefix=" + args.prefix, "--out=" + (out / "native").as_posix(),
                          "--suite-label=" + args.label], cwd=ROOT, env=environment(build=True), timeout_s=300, memory_mb=3072)
    write(out / "gate.log", result.stdout + result.stderr)
    print(result.stdout + result.stderr, end="")
    if not result.ok:
        print("OURO_SMITH: manifest " + result.classify() + " exit=" + str(result.returncode))
    return 0 if result.ok else 1
