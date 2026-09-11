"""Run the retirement checks and bind their results to one unchanged tree."""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from ourosmith import ROOT
from ourosmith.host import environment, shell
from ourosmith.limits import run_limited
from ourosmith.provenance import begin, source_state
from repo_support import write_json_atomic

KIND = "ouro.smith-validation.v1"


def commands(out):
    python, sh = sys.executable, str(shell())
    smith = [python, "scripts/ouro_smith.py"]
    # The aggregate may rebuild installed tools. Record Smith's binary hashes
    # afterwards, so every profile refers to those final installed binaries.
    return [
        ("ci", [python, "scripts/ci_gate.py", "--profile", "pr", "--out", str(out / "ci")]),
        ("native", [sh, "scripts/ouro_native_repo_ci_suite.sh"]),
        ("hardening", [python, "scripts/kernel_hardening_suite.py"]),
        ("scale", [python, "scripts/kernel_scale.py", "--profile", "scale", "--out", str(out / "scale")]),
        ("depth", [python, "scripts/kernel_scale.py", "--profile", "depth", "--out", str(out / "depth")]),
        ("selftest", [*smith, "--self-test"]),
        *[(name, [*smith, "--profile", profile, "--out", str(out / name)])
          for name, profile in (("pr", "pr"), ("pr2", "pr"), ("kernel", "kernel"), ("nightly", "nightly"))],
        ("faults", [*smith, "--faults", "--profile", "pr", "--out", str(out / "faults")]),
        ("diff", ["git", "diff", "--check"]),
    ]


def reuse_ci_pr(out, rows):
    """Account for CI's real PR run without recording a fictitious subprocess."""
    from ourosmith.evidence import ci_pr_receipt

    ci_command = dict(commands(out))["ci"]
    if not any(row.get("name") == "ci" and row.get("command") == ci_command
               and row.get("status") == "PASS" and row.get("exit_code") == 0 for row in rows):
        return None
    started = time.perf_counter()
    receipt, problems = ci_pr_receipt(out, source_state())
    if receipt is None:
        print("OURO_SMITH: validation pr requires a fresh run: " + "; ".join(problems), flush=True)
        return None
    # Read the verified bytes again and reject replacement during the copy.
    try:
        data = Path(receipt["report"]).read_bytes()
    except OSError as exc:
        print(f"OURO_SMITH: validation pr requires a fresh run: CI report unavailable: {exc}", flush=True)
        return None
    if hashlib.sha256(data).hexdigest() != receipt["report_sha256"]:
        print("OURO_SMITH: validation pr requires a fresh run: CI report changed", flush=True)
        return None
    target = out / "pr/report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    log = out / "pr.log"
    write_json_atomic(log, receipt)
    print("OURO_SMITH: validation pr uses the full PR run executed by CI gate ouro-smith", flush=True)
    return {"name": "pr", "command": receipt["command"], "execution": "ci", "receipt": receipt,
            "exit_code": 0, "status": "PASS", "resource": "ok",
            "seconds": round(time.perf_counter() - started, 3), "log": str(log)}


def run(args):
    out = Path(args.out).resolve() if args.out else ROOT / "_build/smith/validation"
    out.mkdir(parents=True, exist_ok=True)
    provenance = begin()
    rows = []
    for name, argv in commands(out):
        print(f"OURO_SMITH: validation START {name}", flush=True)
        row = reuse_ci_pr(out, rows) if name == "pr" else None
        if row is None:
            result = run_limited(argv, cwd=ROOT, env=environment(build=True), timeout_s=3600, memory_mb=3072)
            log = out / (name + ".log")
            log.write_text(result.stdout + result.stderr, encoding="utf-8")
            status = "PASS" if result.ok else "TIMEOUT" if result.status == "timeout" else "FAIL"
            row = {"name": name, "command": argv, "exit_code": result.returncode, "status": status,
                   "resource": result.classify(), "seconds": round(result.elapsed_s, 3), "log": str(log)}
        rows.append(row)
        print(f"OURO_SMITH: validation {name} {row['status']} exit={row['exit_code']} log={row['log']}", flush=True)
        write_json_atomic(out / "commands.json", {"kind": KIND, "pass": False, "complete": False,
                                                  "provenance": provenance, "commands": rows})
    unchanged = provenance["source"] == source_state()
    result = {"kind": KIND, "pass": unchanged and all(row["status"] == "PASS" for row in rows),
              "complete": True, "unchanged": unchanged, "provenance": provenance, "commands": rows}
    write_json_atomic(out / "commands.json", result)
    # Gate semantics and determinism are checked separately from exit codes.
    from ourosmith.evidence import validation_problems

    problems = validation_problems(out)
    result["problems"] = problems
    result["pass"] = result["pass"] and not problems
    result["finished_unix"] = int(time.time())
    write_json_atomic(out / "commands.json", result)
    for problem in problems:
        print(f"OURO_SMITH: validation FAIL {problem}")
    print("OURO_SMITH: validation " + ("PASS" if result["pass"] else "FAIL"))
    return int(not result["pass"])
