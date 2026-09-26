"""Audit the legacy corpus against executed strategies; never delete evidence."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from ci_gate import COMPILER_SHARDS, gates
from ourosmith import ROOT
from ourosmith import migration_contracts as contracts
from ourosmith.report import load_report

MATRIX = ROOT / "quality/smith/migration_matrix.json"
KIND = "ouro.smith-migration.v1"
# One reviewed archive predates the native contract version and already points
# at immutable recovery Git objects. It may be read exactly once as historical
# accounting, then all current categories and execution status are rebuilt.
LEGACY_ARCHIVE_SHA256 = "b836980038b059816298647d49e03055a94f1f53c5fca9ecd24b4dd62790e7f3"
LEGACY_REFERENCE = re.compile(r'''(?<![\w./\\-])(?:\./)?test[/\\]|\$\{?(?:ROOT|root|OURO_ROOT)\}?[/\\]test[/\\]|(?:Path\s*\(\s*|/\s*)["']test["']|\bruntest\s+test\b|:-test\}''')

# These exact references describe user-project fixture paths or historical
# evidence. They do not open an input from the retired repository corpus.
REFERENCE_NOTES = {
    "scripts/analyze_bounded.py": "Generic analyzer policy for test directories in arbitrary user projects.",
    "tools/analyze/model.ouro": "Generic analyzer policy for test directories in arbitrary user projects.",
    "tools/analyze/drive_main.ouro": "Generic analyzer policy for test directories in arbitrary user projects.",
    "scripts/selfhost_bootstrap_evidence.py": "Recognizes relative source paths in diagnostic log text.",
}
AUDIT_SOURCES = {"scripts/ourosmith/migration.py", "scripts/ourosmith/migration_contracts.py",
                 "quality/smith/migration_matrix.json"}


def tracked_legacy():
    result = subprocess.run(["git", "ls-files", "-z", "test"], cwd=ROOT, capture_output=True, check=True, timeout=15)
    return sorted(path for path in result.stdout.decode("utf-8").split("\0") if path)


def references():
    from ourosmith.provenance import EXTENSIONS, INPUTS, git

    rows, notes = [], []
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *INPUTS)
    for relative in sorted(set(paths.split("\0")) - {""}):
        path = ROOT / relative
        if relative.startswith("test/") or relative in AUDIT_SOURCES or not path.is_file():
            continue
        if path.suffix not in EXTENSIONS | {".mli"} and path.name not in {"dune", "dune-project"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not LEGACY_REFERENCE.search(line):
                continue
            row = {"path": relative, "line": number, "text": line.strip()}
            note = ""
            if relative in REFERENCE_NOTES and '"test/"' in line:
                note = REFERENCE_NOTES[relative]
            elif relative.startswith("quality/smith/corpus/kernel/") and '"found_by": "migrated from test/kernel/' in line:
                note = "Historical origin metadata, not an active input path."
            elif relative == "docs/ouro_smith.md" and 'legacy `test/`' in line:
                note = "Explains retirement of the historical tree."
            elif relative == "scripts/ourosmith/selftest.py" and "for line in (" in line:
                note = "Positive and negative examples for this reference scanner."
            if note:
                notes.append({**row, "reason": note})
            else:
                rows.append(row)
    return rows, notes


def consumers():
    return references()[0]


def exercised(report, strategy, external=()):
    if strategy.startswith("external/"):
        return strategy in external
    layer, group, name = strategy.split("/", 2)
    return bool(report.get("summary", {}).get("layers", {}).get(layer, {}).get("coverage", {}).get(group, {}).get(name))


def external_evidence(directory):
    from ci_gate import REPORT_KIND as CI_KIND
    from ourosmith.compiler_evidence import compiler_strategies
    from ourosmith.evidence import read
    from ourosmith.provenance import source_state
    from ourosmith.validation import KIND as VALIDATION_KIND, commands as required_commands

    if directory is None:
        return set()
    directory = Path(directory).resolve()
    journal = read(directory / "commands.json")
    rows = journal.get("commands")
    provenance = journal.get("provenance")
    if (journal.get("kind") != VALIDATION_KIND or journal.get("complete") is not True
            or journal.get("unchanged") is not True or not isinstance(provenance, dict)
            or provenance.get("source") != source_state()
            or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)):
        return set()
    expected = dict(required_commands(directory))
    names = [row.get("name") for row in rows]
    if any(not isinstance(name, str) for name in names) or len(names) != len(set(names)):
        return set()
    commands = {row["name"] for row in rows if row["name"] in expected
                and row.get("command") == expected[row["name"]]
                and row.get("status") == "PASS" and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and (directory / (row["name"] + ".log")).is_file()}
    result = {"external/command/" + name for name in commands}
    if {"scale", "depth"} & commands:
        from kernel_scale import report_evidence

        # Preserve historical law identities while the new supervisor validates
        # the actual probes, resource limits, complete inventories and receipts.
        resource_laws = {
            "scale": {"external/law/scale:" + operation: "external/law/scale: " + operation
                      for operation in ("let-chain", "lam-chain", "app-spine", "nested-app",
                                        "domain-deep-pi", "const-chain")},
            "depth": {"external/law/depth": "external/law/depth: fail-closed on million-node terms"},
        }
        for profile, laws in resource_laws.items():
            if profile not in commands:
                continue
            evidence = report_evidence(directory / profile / "report.json", profile)
            if (isinstance(evidence, dict) and evidence.get("pass") is True
                    and evidence.get("credits") == list(laws) and evidence.get("failures") == []):
                result.update(laws.values())
    if "ci" in commands:
        summary = read(directory / "ci/ci-summary.json")
        entries = summary.get("gates")
        if (summary.get("kind") != CI_KIND or summary.get("profile") != "pr" or summary.get("group") != "all"
                or not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries)):
            return result
        for gate in (gate for gate in gates() if "pr" in gate.profiles):
            matches = [row for row in entries if row.get("name") == gate.name]
            if len(matches) != 1:
                continue
            row = matches[0]
            log = directory / "ci" / gate.name / "gate.log"
            if (gate.blocking and row.get("blocking") is True and row.get("command") == gate.cmd
                    and row.get("status") == "pass" and type(row.get("returncode")) is int and row["returncode"] == 0
                    and isinstance(row.get("log"), str) and (ROOT / row["log"]).resolve() == log and log.is_file()):
                result.add("external/ci/" + gate.name)
        if all(f"external/ci/compiler-checking-{index}" in result for index in range(1, COMPILER_SHARDS + 1)):
            result.update(compiler_strategies(directory))
    # Retiring an unrepresentable legacy API is a separate claim from passing
    # semantic laws. Credit requires both its removal and the current owners.
    owners = {"external/compiler/" + name for name in contracts.CURRENT_COMPILER_OWNERS}
    if ("external/ci/compiler-boundary" in result and owners <= result
            and all(not (ROOT / path).exists() for path in contracts.LEGACY_CORE_OWNER_PATHS)):
        result.add(contracts.RETIRED_CORE)
    return result


def legacy_snapshot(revision):
    """Resolve immutable recovery objects, including after a deletion commit."""
    from ourosmith.provenance import git

    if not isinstance(revision, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
        raise ValueError("legacy recovery requires a full Git commit ID")
    try:
        if git("cat-file", "-t", revision).strip() != "commit":
            raise ValueError("legacy recovery revision is not a Git commit")
        blobs = {}
        for row in git("ls-tree", "-rz", revision, "--", "test").split("\0"):
            if row:
                header, path = row.split("\t", 1)
                _mode, kind, oid = header.split()
                if kind != "blob":
                    raise ValueError("legacy recovery includes a non-file Git object")
                blobs[path] = oid
        if "test/suite/manifest.tsv" not in blobs:
            raise ValueError("legacy recovery commit has no corpus manifest")
        tree = git("rev-parse", revision + ":test").strip()
        objects = sorted(set(blobs.values()))
        result = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                                input=("\n".join(objects) + "\n").encode(), capture_output=True,
                                check=True, timeout=15)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("legacy recovery Git objects are unavailable") from exc
    stream, contents = io.BytesIO(result.stdout), {}
    for oid in objects:
        header = stream.readline().split()
        if len(header) != 3 or header[:2] != [oid.encode(), b"blob"]:
            raise ValueError("legacy recovery Git blob is unavailable")
        size = int(header[2])
        data = stream.read(size)
        if len(data) != size or stream.read(1) != b"\n":
            raise ValueError("legacy recovery Git blob is truncated")
        contents[oid] = data.replace(b"\r\n", b"\n")
    recovery = {"revision": revision, "tree": tree, "git_blobs": blobs,
                "files_sha256": {path: hashlib.sha256(contents[oid]).hexdigest() for path, oid in blobs.items()}}
    return recovery, contents[blobs["test/suite/manifest.tsv"]].decode("utf-8")


def legacy_categories(paths, manifest_text):
    groups = defaultdict(list)
    for row in csv.reader(manifest_text.splitlines(), delimiter="\t"):
        if not row or row[0].startswith("#"):
            continue
        if len(row) < 6:
            raise ValueError(f"malformed manifest row {row[0]}")
        category = ".".join(row[0].split(".")[:2])
        groups[(category, row[2], row[3], row[5])].append({"id": row[0], "path": "test/suite/" + row[1]})
    categories = []

    def add(identity, files, strategies, note="", **metadata):
        categories.append({"id": identity, "rows": [{"path": path} for path in files],
                           "strategies": strategies, "note": note, **metadata})

    for (prefix, tool, expected, diagnostic), rows in sorted(groups.items()):
        strategies, note = contracts.manifest_strategy(prefix, tool, expected, diagnostic)
        categories.append({"id": f"manifest:{prefix}:{tool}:{expected}:{diagnostic or 'status'}", "tool": tool,
                           "expect": expected, "diagnostic": diagnostic, "rows": rows,
                           "strategies": strategies, "note": note})
    for path in paths:
        if ".golden" in Path(path).name:
            stem = path.split(".golden", 1)[0]
            inputs = [candidate for candidate in (stem + ".in", stem + ".ouro") if candidate in paths]
            add("golden:" + path, [path, *inputs], contracts.GOLDENS.get(path.removeprefix("test/suite/"), []),
                "Parameterized byte/value contracts preserve the listed rewrite or runtime rules.")
        elif path.startswith(("test/kernel/bad/", "test/kernel/valid/")) and path.endswith(".json"):
            name = Path(path).stem
            strategies, note, metadata = contracts.kernel_case(name, "/bad/" in path)
            add("kernel:" + name, [path], strategies, note, **metadata)
        elif path.startswith("test/kernel/") and path.endswith(".ml"):
            filename = Path(path).name
            if filename in contracts.API_LAWS:
                for law in contracts.API_LAWS[filename]:
                    add("kernel-api:" + Path(path).stem + ":" + law, [path],
                        contracts.LAW_OWNERS[law], contracts.LAW_NOTES.get(law, ""), legacy_law=law)
            else:
                add("kernel-api:" + Path(path).stem, [path], contracts.API.get(filename, []),
                    contracts.API_NOTES.get(filename, ""))
        elif path.startswith("test/compiler_corpus/"):
            add("compiler:" + Path(path).stem, [path], contracts.COMPILER.get(Path(path).name, []),
                "Native values are checked against Python. The retired JS-backend comparison is not an oracle for current C code.")
        elif path in contracts.EXTRA:
            add("contract:" + path, [path], contracts.EXTRA[path])
        elif path in contracts.SUPPORT:
            add("support:" + path, [path], [], contracts.SUPPORT[path], support=True)
    accounted = {row["path"] for category in categories for row in category["rows"]}
    for path in sorted(set(paths) - accounted):
        add("unmapped:" + path, [path], [], "This file has no explicit category or supporting-file mapping.")
    for owner in contracts.CURRENT_COMPILER_OWNERS:
        add("canonical-owner:" + owner, ["tests/" + owner + ".ouro"], contracts.compiler(owner),
            "Current typed source inventory is owned by this separately executed complete compiler suite, not by generated Smith coverage.")
    return categories, sum(len(rows) for rows in groups.values())


def validate_archive(matrix):
    if not isinstance(matrix, dict) or not isinstance(matrix.get("recoverability"), dict):
        raise ValueError("the archived matrix has no recovery evidence")
    recovery = matrix["recoverability"]
    source = matrix.get("pre_retirement_source")
    if matrix.get("kind") != KIND or matrix.get("deletion_ready") is not True or \
            recovery.get("status") != [] or matrix.get("evidence_problems") != []:
        raise ValueError("the archived matrix did not establish safe retirement")
    if not isinstance(source, dict) or source.get("head") != recovery.get("revision") or \
            not isinstance(source.get("source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["source_sha256"]):
        raise ValueError("archived recovery revision differs from the validated pre-retirement source")
    snapshot, manifest = legacy_snapshot(recovery.get("revision"))
    paths = sorted(snapshot["git_blobs"])
    if matrix.get("legacy_files") != paths or recovery.get("tracked") != len(paths) or \
            not isinstance(source.get("files"), int) or source["files"] < len(paths) or \
            any(recovery.get(key) != value for key, value in snapshot.items()):
        raise ValueError("archived legacy inventory or hashes differ from recovery Git objects")
    if matrix.get("source_manifest_sha256") != hashlib.sha256(manifest.encode()).hexdigest():
        raise ValueError("archived manifest hash differs from recovery Git objects")
    rows = matrix.get("categories", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("archived categories are malformed")
    metadata = [{key: value for key, value in row.items() if key not in {"status", "missing_strategies"}} for row in rows]
    if matrix.get("contracts") == contracts.CONTRACT_KIND:
        categories, count = legacy_categories(paths, manifest)
        if metadata != categories or matrix.get("manifest_rows") != count:
            raise ValueError("archived categories or strategies differ from the recoverable corpus contracts")
    elif "contracts" not in matrix and archive_hash(matrix) == LEGACY_ARCHIVE_SHA256:
        # Exact pin includes every old category, coverage result and recovery
        # field. These old PASS claims never become current strategy evidence.
        categories = metadata
    else:
        raise ValueError("unrecognized or modified historical migration archive")
    support = sum(bool(row.get("support") and row.get("note")) for row in categories)
    summary = {"files": len(paths), "categories": len(categories), "covered": len(categories) - support,
               "support": support, "gaps": 0}
    fingerprint = matrix.get("evidence_fingerprint")
    if matrix.get("summary") != summary or not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or \
            any(row.get("missing_strategies") != [] or row.get("status") != ("support" if row.get("support") else "covered") or
                (not row.get("support") and not row.get("strategies")) for row in rows):
        raise ValueError("the archived matrix is not a complete pre-retirement accounting")


def archive_hash(matrix):
    return hashlib.sha256(json.dumps(matrix, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_matrix(report, validation=None):
    paths = tracked_legacy()
    manifest = ROOT / "test/suite/manifest.tsv"
    if not paths or not manifest.is_file():
        if paths or not MATRIX.is_file():
            raise ValueError("legacy evidence is incomplete; a verified pre-retirement matrix is required")
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        validate_archive(matrix)
        _snapshot, old_manifest = legacy_snapshot(matrix["recoverability"]["revision"])
        if "contracts" not in matrix:
            matrix["previous_contracts"] = {"archive_sha256": archive_hash(matrix),
                                            "evidence_fingerprint": matrix["evidence_fingerprint"]}
        matrix["contracts"] = contracts.CONTRACT_KIND
        matrix["categories"], matrix["manifest_rows"] = legacy_categories(matrix["legacy_files"], old_manifest)
        matrix["deletion_ready"] = False
        matrix["evidence_problems"] = ["current native evidence has not been checked"]
        matrix["retired"] = True
        return refresh(matrix, report, validation)
    from ourosmith.provenance import git

    recovery, _manifest = legacy_snapshot(git("rev-parse", "HEAD").strip())
    categories, count = legacy_categories(paths, manifest.read_text(encoding="utf-8"))
    status = subprocess.run(["git", "status", "--short", "--untracked-files=all", "--ignored", "--", "test"],
                            cwd=ROOT, capture_output=True, check=True, timeout=15).stdout.decode("utf-8").splitlines()
    matrix = {"kind": KIND, "contracts": contracts.CONTRACT_KIND,
            "source_manifest_sha256": hashlib.sha256(manifest.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "recoverability": {**recovery, "tracked": len(paths), "status": status},
            "pre_retirement_source": report.get("sections", {}).get("provenance", {}).get("source", {}),
            "legacy_files": paths, "manifest_rows": count,
            "categories": categories, "retired": False}
    return refresh(matrix, report, validation)


def refresh(matrix, report, validation):
    external = external_evidence(validation)
    for row in matrix["categories"]:
        row["missing_strategies"] = [strategy for strategy in row["strategies"] if not exercised(report, strategy, external)]
        row["status"] = ("support" if row.get("support") and row.get("note") else
                         "covered" if row["strategies"] and not row["missing_strategies"] else "gap")
    matrix["consumers"], matrix["reference_notes"] = references()
    matrix["gates"] = [{"name": gate.name, "command": ["python3" if arg == sys.executable else arg for arg in gate.cmd],
                        "profiles": gate.profiles} for gate in gates()]
    matrix["evidence_fingerprint"] = report.get("fingerprint")
    matrix["summary"] = {"files": len(matrix["legacy_files"]), "categories": len(matrix["categories"]),
                         **{key: sum(row["status"] == value for row in matrix["categories"])
                            for key, value in (("covered", "covered"), ("support", "support"), ("gaps", "gap"))}}
    return matrix


def run(args):
    report = load_report(Path(args.report)) if args.report else None
    if report is None:
        raise ValueError("migration requires an executed OuroSmith --report")
    matrix = build_matrix(report, args.validation)
    from ourosmith.evidence import profile_problems, validation_problems
    from ourosmith.provenance import source_state

    problems = profile_problems(report, "pr", source_state())
    if args.validation:
        problems.extend(validation_problems(Path(args.validation)))
        repeated = load_report(Path(args.validation) / "pr/report.json")
        if repeated is None or repeated.get("fingerprint") != report.get("fingerprint"):
            problems.append("migration report differs from the validated PR report")
    else:
        problems.append("complete validation evidence is required (--validation DIR)")
    if matrix["recoverability"]["status"]:
        problems.append("legacy tree contains modified, untracked, or ignored data; recovery must be resolved before retirement")
    matrix["evidence_problems"] = sorted(set(problems))
    ready = not problems and matrix["summary"]["gaps"] == 0 and not matrix["consumers"]
    matrix["deletion_ready"] = ready
    out = Path(args.out) if args.out else ROOT / "_build/smith/migration"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(matrix, indent=1, sort_keys=True) + "\n"
    (out / "migration_matrix.json").write_text(text, encoding="utf-8")
    if args.write and (ready or not matrix["retired"]):
        MATRIX.write_text(text, encoding="utf-8")
    print(f"OURO_SMITH: migration {'PASS' if ready else 'FAIL'} files={matrix['summary']['files']} rows={matrix['manifest_rows']} categories={matrix['summary']['categories']} gaps={matrix['summary']['gaps']} consumers={len(matrix['consumers'])}")
    print(f"OURO_SMITH: deletion {'ready' if ready else 'BLOCKED'}; report={out / 'migration_matrix.json'}")
    for problem in matrix["evidence_problems"]:
        print(f"OURO_SMITH: evidence MISSING {problem}")
    return 0 if ready else 1
