#!/usr/bin/env python3
"""Check that callers cannot fabricate prepared stage inputs."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from frontend_regen import ROOT, collect_units, ouro1_cmd
from repo_support import configure_native_stack


CASES = (
    (
        "snapshot-private-constructor",
        95,
        "",
        'import "../../tools/collect_core.ouro" as Capture;\n'
        'def forged : Capture.CollectSnapshot := Capture.MkCollectSnapshot "." [];\n',
    ),
    (
        "references-require-prepared-index",
        41,
        "wrong_index",
        'import "../../tools/analyze/families.ouro", "../../tools/analyze/model_types.ouro";\n'
        'def wrong_index (decls : List ADecl) : List ARef := refs_for_file_indexed 0 [] decls;\n',
    ),
    (
        "formatting-requires-convergence",
        41,
        "unchecked_format",
        'import "../../tools/fix/pipeline.ouro";\n'
        'def unchecked_format (outcome : FxOutcome) : Either FxPrepareError FxOutcome :=\n'
        '  fx_format_converged outcome;\n',
    ),
    (
        "certification-requires-lexed-source",
        41,
        "unchecked_transaction",
        'import "../../tools/fix/proof.ouro";\n'
        'def unchecked_transaction (source : String) (edits : List FxEdit)\n'
        '    : Either FxPlanError FxTransactionProof := fx_certify_lexed_transaction source edits;\n',
    ),
    (
        "native-recheck-private-constructor",
        95,
        "",
        'import "../../compiler/native/lower.ouro" as Replay,\n'
        '  "../../compiler/checked_program.ouro" as Program;\n'
        'def forged (input : Program.CheckedProgram) : Replay.NativeRecheckedProgram :=\n'
        '  Replay.MkNativeRecheckedProgram 500 input;\n',
    ),
)


def check_cases(compiler: Path) -> None:
    output = ROOT / "_build"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compiler-stage-contracts-", dir=output) as temporary:
        for name, code, declaration, source in CASES:
            fixture = Path(temporary) / f"{name}.ouro"
            fixture.write_text(source, encoding="utf-8")
            entry = fixture.relative_to(ROOT).as_posix()
            command = [*ouro1_cmd(compiler), "check", entry, "60000"]
            for unit in collect_units(entry):
                command.extend(("--unit", unit))
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
            marker = f"ouro1: CErr code={code} "
            if (result.returncode != 1 or marker not in result.stderr
                    or (declaration and f"type mismatch in {declaration}" not in result.stderr)):
                raise SystemExit(
                    f"COMPILER_STAGE_CONTRACTS: FAIL {name} wanted compiler error {code}\n"
                    f"{result.stdout}{result.stderr}"
                )
            print(f"COMPILER_STAGE_CONTRACTS: OK {name} code={code}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    configure_native_stack()
    check_cases(args.compiler.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
