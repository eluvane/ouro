"""Bind a restored historical bootstrap archive to a successful protected CI push."""
from __future__ import annotations

import argparse
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import re
import sys

from repo_support import sha256_file

WORKFLOW = ".github/workflows/ouro-pr.yml"
BRANCHES = ("main", "master")
MAX_RUN_LOOKUPS = 4
MAX_METADATA_BYTES = 256 * 1024


def github_json(path: str) -> dict | None:
    connection = http.client.HTTPSConnection("api.github.com", timeout=4)
    try:
        connection.request("GET", path, headers={"Accept": "application/vnd.github+json",
                           "User-Agent": "ouro-bootstrap-ci", "X-GitHub-Api-Version": "2022-11-28"})
        response = connection.getresponse()
        if response.status != 200:
            return None
        data = response.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            return None
        result = json.loads(data)
        return result if isinstance(result, dict) else None
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        return None
    finally:
        connection.close()


def confirmed(name: str, repository: str, repository_id: int) -> bool:
    if (repository_id <= 0 or not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+", repository)
            or repository.rsplit("/", 1)[1] in {".", ".."}):
        return False
    base = f"/repos/{repository}/actions"
    listing = github_json(f"{base}/artifacts?name={name}&per_page=100")
    if not listing or not isinstance(listing.get("artifacts"), list):
        return False
    attempts = {}
    for artifact in listing["artifacts"]:
        if not isinstance(artifact, dict) or artifact.get("name") != name or artifact.get("expired") is not False:
            continue
        origin = artifact.get("workflow_run")
        if not isinstance(origin, dict) or origin.get("repository_id") != repository_id or origin.get("head_repository_id") != repository_id:
            continue
        run_id, branch, commit = origin.get("id"), origin.get("head_branch"), origin.get("head_sha")
        if (type(run_id) is not int or run_id < 1 or branch not in BRANCHES
                or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)):
            continue
        if run_id not in attempts:
            if len(attempts) >= MAX_RUN_LOOKUPS:
                continue
            # Artifact metadata omits the run attempt. Only the first attempt may publish this name.
            attempts[run_id] = github_json(f"{base}/runs/{run_id}/attempts/1")
        run = attempts[run_id]
        if not run or any(run.get(field) != expected for field, expected in (
                ("id", run_id), ("run_attempt", 1), ("event", "push"), ("status", "completed"),
                ("conclusion", "success"), ("head_branch", branch), ("head_sha", commit))):
            continue
        if run.get("path") not in (WORKFLOW, f"{WORKFLOW}@{branch}", f"{WORKFLOW}@refs/heads/{branch}"):
            continue
        repos = (run.get("repository"), run.get("head_repository"))
        if not all(isinstance(repo, dict) and repo.get("id") == repository_id
                   and isinstance(repo.get("full_name"), str) and repo["full_name"].casefold() == repository.casefold() for repo in repos):
            continue
        try:
            started, uploaded, finished = (datetime.fromisoformat(value) for value in
                                          (run["run_started_at"], artifact["created_at"], run["updated_at"]))
            if all(stamp.tzinfo is not None for stamp in (started, uploaded, finished)) and started <= uploaded <= finished:
                return True
        except (KeyError, ValueError, TypeError):
            continue
    return False


def archive_path() -> Path:
    key = os.environ["HISTORICAL_KEY"]
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("invalid historical input key")
    temporary = Path(os.environ["RUNNER_TEMP"])
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    if not temporary.is_absolute() or not workspace.is_absolute() or temporary.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("historical cache requires runner temporary storage outside the checkout")
    archive = temporary / "bootstrap-historical" / (key + ".zip")
    if archive.parent.is_symlink() or archive.is_symlink() or not archive.is_file():
        raise ValueError("historical archive is missing or is not a regular file")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("attest", "verify"))
    action = parser.parse_args(argv).action
    value = ""
    digest = ""
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        archive = archive_path()
        digest = sha256_file(archive)
        name = f"bootstrap-history-{archive.stem}-{digest}"
        if action == "verify":
            if (os.environ.get("GITHUB_API_URL") == "https://api.github.com"
                    and confirmed(name, repository, int(os.environ["GITHUB_REPOSITORY_ID"]))):
                value = digest
            else:
                print("HISTORICAL_CACHE: no confirmed protected push. Rebuilding historical stages.", file=sys.stderr)
        else:
            ref = os.environ["GITHUB_REF"]
            if (digest == os.environ.get("BUILT_HISTORICAL_SHA256") and os.environ.get("GITHUB_EVENT_NAME") == "push"
                    and ref in {f"refs/heads/{branch}" for branch in BRANCHES}
                    and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
                    and os.environ.get("GITHUB_WORKFLOW_REF") == f"{repository}/{WORKFLOW}@{ref}"):
                with archive.with_name("attestation.txt").open("x", encoding="ascii", newline="\n") as receipt:
                    receipt.write(name + "\n")
                value = name
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"HISTORICAL_CACHE: {error}", file=sys.stderr)
    print(f"{'verified_sha256' if action == 'verify' else 'name'}={value}")
    if action == "attest":
        print(f"sha256={digest if value else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
