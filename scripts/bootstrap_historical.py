"""Store and verify historical C-bootstrap producers in an exact-key cache."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from itertools import pairwise
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile

from repo_support import hash_json, sha256_bytes, sha256_file

KIND = "ouro.historical-c-bootstrap.v1"
METADATA = ("receipt.json", "inputs.json", "report.json")
PAYLOADS = ("out/c0/c/ouro1", "out/bridge/ouro1", "out/bridge/driver_u.c", "out/bridge/backend_u.c")


def historical_phases(snapshot: dict) -> tuple[str, ...]:
    return ("c0", "bridge", "bridge2") if "bridge2" in snapshot["roots"] else ("c0", "bridge")


def payload_names(snapshot: dict) -> tuple[str, ...]:
    if "bridge2" not in snapshot["roots"]:
        return PAYLOADS
    return (*PAYLOADS, "out/bridge2/ouro1", "out/bridge2/driver_u.c", "out/bridge2/backend_u.c")


def payload_hashes(phases) -> tuple[str, ...]:
    return (phases[0]["binary_sha256"], *(phase[key] for phase in phases[1:]
              for key in ("binary_sha256", "frontend_sha256", "backend_sha256")))


def host_identity() -> dict:
    tools = {}
    for name in ("as", "ld"):
        executable = shutil.which(name)
        tools[name] = sha256_file(Path(executable)) if executable else None
    return {"image": os.environ.get("ImageVersion", ""), "image_os": os.environ.get("ImageOS", ""),
            "python": sys.version, "tools": tools}


def copy_hash(source, destination) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        destination.write(block)
        digest.update(block)
    return digest.hexdigest()


def historical_inputs(snapshot: dict) -> dict:
    return {name: digest for name, digest in snapshot["inputs"].items() if name.startswith("historical/")}


def verified_origin(receipt, original, report, snapshot, key, key_for) -> tuple:
    phases = report["phases"]
    historical = historical_phases(snapshot)
    if (set(receipt) != {"kind", "key", "report_sha256"} or receipt["kind"] != KIND or receipt["key"] != key
            or original["kind"] != snapshot["kind"] or report["kind"] != snapshot["selected"]["kind"]
            or report["key"] != original["key"] or original["key"] != hash_json(original["selected"])
            or original.get("historical_host") != snapshot.get("historical_host")
            or key_for(original["selected"], report["workers"], host=original.get("historical_host")) != key
            or key_for(snapshot["selected"], report["workers"], host=snapshot.get("historical_host")) != key
            or historical_inputs(original) != historical_inputs(snapshot) or original["bridge_graph"] != snapshot["bridge_graph"]
            or original.get("bridge2_graph") != snapshot.get("bridge2_graph")
            or historical_phases(original) != historical
            or report["pass"] is not True or report["changed_inputs"] != []
            or [row["phase"] for row in phases] != [*historical, "p1", "p2"]
            or any(row["pass"] is not True or row["source_root"] != original["roots"][row["phase"]] for row in phases)):
        raise ValueError("historical bootstrap provenance mismatch")
    c0, bridge = phases[:2]
    p1, p2 = phases[-2:]
    if ([c0["source_root"], bridge["source_root"]] != ["historical/c0", "historical/bridge"]
            or [snapshot["roots"]["c0"], snapshot["roots"]["bridge"]] != [c0["source_root"], bridge["source_root"]]
            or [c0["binary"], bridge["binary"]] != list(PAYLOADS[:2])
            or [cmd["label"] for cmd in c0["commands"]] != ["c0"]
            or [cmd["label"] for cmd in bridge["commands"]] != ["frontend", "backend", "link"]
            or any(cmd["status"] != "ok" or cmd["returncode"] != 0 for row in (c0, bridge) for cmd in row["commands"])
            or any(prev["binary_sha256"] != nxt["producer_sha256"] for prev, nxt in pairwise(phases))
            or any(row["all_current_roots_strictly_checked_before_use"] is not True for row in (p1, p2))
            or p2["binary_sha256"] != report["binary_sha256"]):
        raise ValueError("historical bootstrap phase mismatch")
    if "bridge2" in historical:
        second = phases[2]
        checks = [f"check-{index:02}" for index in range(len(snapshot["selected"]["roots"]))]
        if (second["source_root"] != "historical/next/bridge2" or second["source_root"] != snapshot["roots"]["bridge2"]
                or second["binary"] != "out/bridge2/ouro1"
                or second["all_current_roots_strictly_checked_before_use"] is not True
                or [cmd["label"] for cmd in second["commands"]] != [*checks, "frontend", "backend", "link"]
                or any(cmd["status"] != "ok" or cmd["returncode"] != 0 for cmd in second["commands"])):
            raise ValueError("second historical bridge phase mismatch")
    comparison = report["complete_generated_c_comparison"]
    if set(comparison) != {"driver_u.c", "backend_u.c"} or any(
            comparison[name]["p1_sha256"] != p1[field] or p1[field] != p2[field] or p2[field] != comparison[name]["p2_sha256"]
            for name, field in (("driver_u.c", "frontend_sha256"), ("backend_u.c", "backend_sha256"))):
        raise ValueError("historical bootstrap comparison mismatch")
    return tuple(phases[:-2])


def restore(packet: Path, work: Path, snapshot: dict, key_for, *, expected_sha256: str | None = None) -> dict | None:
    if expected_sha256 is not None and not re.fullmatch("[0-9a-f]{64}", expected_sha256):
        return None
    if packet.is_symlink() or packet.parent.is_symlink() or not packet.is_file() or (work / "out").exists():
        return None
    try:
        with ExitStack() as stack:
            source = stack.enter_context(packet.open("rb"))
            staged = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=work)))
            # The recorded digest and extracted producers must refer to the same bytes.
            verified = stack.enter_context(tempfile.TemporaryFile(dir=staged))
            packet_sha256 = copy_hash(source, verified)
            if expected_sha256 is not None and packet_sha256 != expected_sha256:
                return None
            verified.seek(0)
            archive = stack.enter_context(zipfile.ZipFile(verified))
            members = archive.infolist()
            payloads = payload_names(snapshot)
            if (sorted(info.filename for info in members) != sorted((*METADATA, *payloads))
                    or any(info.compress_type != zipfile.ZIP_STORED or info.compress_size != info.file_size
                           or info.flag_bits & 1 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                           for info in members)
                    or any(archive.getinfo(name).file_size > 16 * 1024 * 1024 for name in METADATA)):
                return None
            receipt_data, inputs_data, report_data = (archive.read(name) for name in METADATA)
            receipt, original, report = (json.loads(data) for data in (receipt_data, inputs_data, report_data))
            if receipt["report_sha256"] != sha256_bytes(report_data) or report["inputs_sha256"] != sha256_bytes(inputs_data):
                return None
            phases = verified_origin(receipt, original, report, snapshot, packet.stem, key_for)
            for name, expected in zip(payloads, payload_hashes(phases), strict=True):
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("xb") as output:
                    if copy_hash(source, output) != expected:
                        return None
                if name.endswith("/ouro1"):
                    if target.stat().st_size <= 4096:
                        return None
                    target.chmod(0o755)
            (staged / "out").rename(work / "out")
            return {**receipt, "sha256": packet_sha256, "phases": list(phases)}
    except (OSError, EOFError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, zipfile.BadZipFile):
        return None


def publish(packet: Path, work: Path, report: dict) -> str:
    if packet.parent.is_symlink():
        raise OSError("historical bootstrap cache path is a symlink")
    packet.parent.mkdir(parents=True, exist_ok=True)
    report_data = (work / "report.json").read_bytes()
    inputs_data = (work / "inputs.json").read_bytes()
    if json.loads(report_data) != report or sha256_bytes(inputs_data) != report["inputs_sha256"]:
        raise ValueError("historical bootstrap evidence changed before publication")
    receipt = {"kind": KIND, "key": packet.stem, "report_sha256": sha256_bytes(report_data)}
    snapshot = json.loads(inputs_data)
    phases = report["phases"][:-2]
    hold = tempfile.NamedTemporaryFile(dir=packet.parent, suffix=".tmp", delete=False)
    try:
        with hold, zipfile.ZipFile(hold, "w") as archive:
            archive.writestr(zipfile.ZipInfo("receipt.json"), json.dumps(receipt, sort_keys=True))
            archive.writestr(zipfile.ZipInfo("inputs.json"), inputs_data)
            archive.writestr(zipfile.ZipInfo("report.json"), report_data)
            for name, expected in zip(payload_names(snapshot), payload_hashes(phases), strict=True):
                path = work / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("historical bootstrap output missing before publication: " + name)
                with path.open("rb") as source, archive.open(name, "w") as destination:
                    actual = copy_hash(source, destination)
                if actual != expected:
                    raise ValueError("historical bootstrap output changed before publication: " + name)
        packet_sha256 = sha256_file(Path(hold.name))
        for attempt in range(4):
            try:
                os.replace(hold.name, packet)
                break
            except PermissionError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 3:
                    raise
                # Windows may deny a second replace while the first publisher finishes.
                try:
                    if not packet.is_symlink() and sha256_file(packet) == packet_sha256:
                        break
                except (FileNotFoundError, PermissionError):
                    pass
                time.sleep(0.025 * (attempt + 1))
        return packet_sha256
    finally:
        Path(hold.name).unlink(missing_ok=True)
