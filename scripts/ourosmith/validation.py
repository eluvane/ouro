"""Run the retirement checks and bind their results to one unchanged tree."""
from __future__ import annotations

import hashlib
import shutil
import sys
import time
from pathlib import Path

from ourosmith import ROOT
from local_scheduler import Allocation, available_memory_mib
from ourosmith.host import BUILD_MEMORY_MB, environment, job_count, shell
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


def ci_pr_repeat(receipt):
    workspace = ROOT / receipt["workspace"]
    repeat_out = workspace / "_build/ci/smith-pr-repeat"
    argv = list(receipt["command"])
    argv[argv.index("--out") + 1] = repeat_out.relative_to(workspace).as_posix()
    return workspace, repeat_out, argv, Allocation(receipt["jobs"], receipt["memory_mib"])


def run(args):
    out = Path(args.out).resolve() if args.out else ROOT / "_build/smith/validation"
    out.mkdir(parents=True, exist_ok=True)
    provenance = begin()
    rows = []
    allocation = Allocation(job_count(), available_memory_mib() or BUILD_MEMORY_MB)
    repeat = None
    for name, command in commands(out):
        print(f"OURO_SMITH: validation START {name}", flush=True)
        row = reuse_ci_pr(out, rows) if name == "pr" else None
        if row is not None and "workspace" in row["receipt"]:
            repeat = ci_pr_repeat(row["receipt"])
        if row is None:
            argv = command
            cwd, lease, extra = ROOT, allocation, {}
            repeated = name == "pr2" and repeat is not None
            env = environment(build=True)
            if repeated:
                from ci_gate import Gate, env_for

                cwd, repeat_out, argv, lease = repeat
                (repeat_out / "report.json").unlink(missing_ok=True)
                extra = {"execution": "ci-workspace", "workspace": cwd.relative_to(ROOT).as_posix()}
                env = {**env_for(Gate("ouro-smith", argv, ("pr",)), out / "ci", cwd, lease), "PATH": env["PATH"]}
            env.update(lease.environment())
            result = run_limited(argv, cwd=cwd, env=env, timeout_s=3600, memory_mb=lease.memory_mib)
            log = out / (name + ".log")
            output = result.stdout + result.stderr
            status = "PASS" if result.ok else "TIMEOUT" if result.status == "timeout" else "FAIL"
            if repeated and result.ok:
                target = out / "pr2/report.json"
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(repeat_out / "report.json", target)
                except OSError as exc:
                    output += f"\nOURO_SMITH: missing isolated repeat report: {exc}\n"
                    status = "FAIL"
            log.write_text(output, encoding="utf-8")
            row = {"name": name, "command": argv, "exit_code": result.returncode, "status": status,
                   "resource": result.classify(), "seconds": round(result.elapsed_s, 3), "log": str(log), **extra}
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
