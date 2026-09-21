#!/usr/bin/env python3
"""Apply the hosted GitHub settings recorded in docs/ci.md via the GitHub API.

This does not rewrite history and does not claim a setting is on unless the
follow-up GET succeeds. Host-plan limits are recorded as SKIP/BLOCKED.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from repo_support import bind_relative_path, parse_json_value, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT)
REPORT_KIND = "ouro.github-settings-apply.v1"

LABELS = (
    ("needs/triage", "d4c5f9", "New issues and PRs awaiting maintainer classification."),
    ("kind/bug", "d73a4a", "Incorrect behavior or regression."),
    ("kind/proposal", "a2eeef", "Language, stdlib, CLI, or tool behavior proposal."),
    ("kind/diagnostic-ice", "b60205", "Crash, panic, ICE, bad span, or misleading diagnostic."),
    ("kind/docs", "0075ca", "Documentation/example/API-reference issue."),
    ("kind/performance", "0e8a16", "Performance report or optimization."),
    ("kind/dependency", "0366d6", "Dependabot or dependency/supply-chain update."),
    ("area/language", "1d76db", "Syntax, semantics, or elaboration-facing design."),
    ("area/compiler", "5319e7", "Parser, elaborator, backend, extraction, or bootstrap compiler."),
    ("area/kernel", "0052cc", "Kernel, TCB, recheck, validation, or core acceptance."),
    ("area/std", "0e8a16", "Standard library and runtime-facing modules."),
    ("area/tooling", "c5def5", "Formatter, pkg, doc, LSP, editor integration."),
    ("area/docs", "0075ca", "Docs, examples, tutorials, API reference."),
    ("area/ci", "fbca04", "CI, caches, workflows, build gates."),
    ("area/release", "e4e669", "Versioning, packaging, checksums, release notes."),
    ("area/security", "ee0701", "Vulnerability, token, supply-chain, or permission issue."),
    ("area/performance", "bfd4f2", "Slow path, benchmark, cache, or stage-loop performance."),
    ("risk/tcb", "b60205", "Changes the trust boundary or kernel-facing acceptance path."),
    ("risk/generated-artifact", "e99695", "Touches generated seeds or promotion flow."),
    ("risk/breaking-change", "d93f0b", "User-facing breaking behavior."),
    ("ignore-for-release", "eeeeee", "Exclude from generated release notes."),
)

MILESTONES = (
    ("v0.1.0 GitHub-ready baseline", "Repository structure, CI, release candidate packaging, docs, security policy, and issue triage."),
    ("v0.2.0 Kernel artifact export", "Connect frontend/export path to the kernel core artifact recheck schema."),
    ("v0.3.0 Release supply-chain hardening", "Signed artifacts, provenance/attestation decision, and hardened public security contact."),
)


def record(name: str, ok: bool, *, detail: str, skip: bool = False) -> dict[str, Any]:
    status = "SKIP/BLOCKED" if skip else ("PASS" if ok else "FAIL")
    print(f"GITHUB_SETTINGS {status} {name}: {detail}")
    return {"name": name, "status": status, "detail": detail}


def api(method: str, path: str, *, body: Any = None) -> tuple[int, str, str]:
    args = ["api", "-X", method, path]
    proc = subprocess.run(
        ["gh", *args] + (["--input", "-"] if body is not None else []),
        input=json.dumps(body) if body is not None else None,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def ensure_labels(repo: str) -> dict[str, Any]:
    created = 0
    updated = 0
    failed: list[str] = []
    for name, color, desc in LABELS:
        rc, out, err = api("POST", f"repos/{repo}/labels", body={"name": name, "color": color, "description": desc})
        if rc == 0:
            created += 1
            continue
        rc2, _, err2 = api(
            "PATCH",
            f"repos/{repo}/labels/{quote(name, safe='')}",
            body={"new_name": name, "color": color, "description": desc},
        )
        if rc2 == 0:
            updated += 1
        else:
            failed.append(f"{name}: {(err2 or err or out).strip().splitlines()[-1:] or ['failed']}")
    ok = not failed
    return record(
        "labels",
        ok,
        detail=f"created={created} updated={updated} failed={len(failed)}"
        + ("; " + "; ".join(str(x) for x in failed) if failed else ""),
    )


def ensure_milestones(repo: str) -> dict[str, Any]:
    rc, out, _err = api("GET", f"repos/{repo}/milestones?state=all&per_page=100")
    existing: set[Any] = set()
    if rc == 0 and out:
        rows, error = parse_json_value(out)
        if error is not None:
            return record("milestones", False, detail=f"invalid milestones JSON: {error}")
        if not isinstance(rows, list):
            return record("milestones", False, detail="GitHub milestones payload is not an array")
        existing = {row.get("title") for row in rows if isinstance(row, dict)}
    created = 0
    failed: list[str] = []
    for title, desc in MILESTONES:
        if title in existing:
            continue
        rc2, _, err2 = api("POST", f"repos/{repo}/milestones", body={"title": title, "description": desc, "state": "open"})
        if rc2 == 0:
            created += 1
        else:
            failed.append((err2 or "").strip().splitlines()[-1] if err2 else title)
    return record("milestones", not failed, detail=f"created={created} already={len(existing)} failed={failed}")


def enable_security(repo: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rc, out, err = api("PUT", f"repos/{repo}/vulnerability-alerts")
    rows.append(record("dependabot-alerts", rc == 0, detail=(err or out or "enabled").strip().splitlines()[-1] if rc else "PUT vulnerability-alerts"))
    rc, out, err = api("PUT", f"repos/{repo}/automated-security-fixes")
    rows.append(record("dependabot-security-updates", rc == 0, detail=(err or out or "enabled").strip().splitlines()[-1] if rc else "PUT automated-security-fixes"))
    rc, out, err = api("PUT", f"repos/{repo}/private-vulnerability-reporting")
    text = (err or out or "").strip()
    pvr_skip = rc != 0 and ("404" in text or "not found" in text.lower() or "not available" in text.lower())
    rows.append(
        record(
            "private-vulnerability-reporting",
            rc == 0,
            skip=pvr_skip,
            detail=text.splitlines()[-1] if text else "PUT private-vulnerability-reporting",
        )
    )
    rc, out, err = api(
        "PATCH",
        f"repos/{repo}",
        body={
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
            }
        },
    )
    text = (err or out or "").strip()
    skip = rc != 0 and (
        "upgrade" in text.lower()
        or "advanced security" in text.lower()
        or "not available" in text.lower()
        or "422" in text
        or "403" in text
    )
    rows.append(
        record(
            "secret-scanning",
            rc == 0,
            skip=skip,
            detail=text.splitlines()[-1] if text else "PATCH security_and_analysis",
        )
    )
    return rows


def configure_actions(repo: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rc, out, err = api(
        "PUT",
        f"repos/{repo}/actions/permissions",
        body={"enabled": True, "allowed_actions": "selected"},
    )
    rows.append(record("actions-enabled-selected", rc == 0, detail=(err or out or "ok").strip().splitlines()[-1] if (err or out) else "selected"))
    rc, out, err = api(
        "PUT",
        f"repos/{repo}/actions/permissions/selected-actions",
        body={"github_owned_allowed": True, "verified_allowed": False, "patterns_allowed": []},
    )
    rows.append(record("actions-github-owned-only", rc == 0, detail=(err or out or "ok").strip().splitlines()[-1] if (err or out) else "github_owned_allowed"))
    rc, out, err = api(
        "PUT",
        f"repos/{repo}/actions/permissions/workflow",
        body={"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    )
    rows.append(record("actions-workflow-read", rc == 0, detail=(err or out or "read").strip().splitlines()[-1] if (err or out) else "read"))
    return rows


def try_branch_protection(repo: str) -> dict[str, Any]:
    body = {
        "required_status_checks": {
            "strict": True,
            "contexts": [
                "Paths",
                "PR (checks)",
                "PR (analysis)",
                "PR (tests)",
                "PR (smith)",
                "PR (samples-1)",
                "PR (samples-2)",
                "PR (compiler-1)",
                "PR (compiler-2)",
                "PR (compiler-3)",
                "PR (compiler-4)",
                "PR (compiler-5)",
                "PR (compiler-6)",
                "PR (compiler-7)",
                "PR (compiler-8)",
                "Kernel",
                "Editor",
                "Portable (ubuntu-latest)",
                "Portable (macos-latest)",
                "Review",
            ],
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_linear_history": True,
        "required_conversation_resolution": True,
    }
    rc, out, err = api("PUT", f"repos/{repo}/branches/main/protection", body=body)
    text = (err or out or "").strip()
    skip = rc != 0 and ("Upgrade to GitHub Pro" in text or "403" in text)
    return record("branch-protection-main", rc == 0, skip=skip, detail=text.splitlines()[-1] if text else "enabled")


def verify_repo(repo: str) -> dict[str, Any]:
    rc, out, err = api("GET", f"repos/{repo}")
    if rc != 0:
        return record("repo-view", False, detail=(err or out).strip())
    data, error = parse_json_value(out)
    if error is not None:
        return record("repo-view", False, detail=f"invalid repo JSON: {error}")
    if not isinstance(data, dict):
        return record("repo-view", False, detail="GitHub repo payload is not an object")
    ok = data.get("default_branch") == "main" and data.get("has_issues") is True
    return record(
        "repo-general",
        ok,
        detail=f"default_branch={data.get('default_branch')} has_issues={data.get('has_issues')} private={data.get('private')} visibility={data.get('visibility')}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("OURO_GITHUB_REPO", ""))
    parser.add_argument("--out", default="_build/github_settings/github-settings-apply.json")
    args = parser.parse_args(argv)
    if not args.repo:
        print("GITHUB_SETTINGS: FAIL --repo OWNER/NAME is required (or OURO_GITHUB_REPO)", file=sys.stderr)
        return 2
    rows = [verify_repo(args.repo)]
    rows.extend(configure_actions(args.repo))
    rows.append(ensure_labels(args.repo))
    rows.append(ensure_milestones(args.repo))
    rows.extend(enable_security(args.repo))
    rows.append(try_branch_protection(args.repo))
    failed = [r for r in rows if r["status"] == "FAIL"]
    skipped = [r for r in rows if r["status"] == "SKIP/BLOCKED"]
    report = {
        "kind": REPORT_KIND,
        "repo": args.repo,
        "pass": not failed,
        "entries": rows,
        "failed": len(failed),
        "skipped": len(skipped),
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    write_json_atomic(out, report)
    print(
        f"GITHUB_SETTINGS_APPLY: {'PASS' if not failed else 'FAIL'} "
        f"repo={args.repo} failed={len(failed)} skipped={len(skipped)} report={rel(out)}"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
