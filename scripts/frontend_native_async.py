#!/usr/bin/env python3
"""Fresh-host native sleep acceptance: source faults, exact bytes and OS timing."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from frontend_native_process import inspect_image, require
from frontend_regen import collect_units
from ourosmith.limits import clean_env, run_limited
from repo_support import sha256_file, write_json_atomic
import selfhost_module_cache as modules

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.frontend-native-async.v1"
ENTRY = "tests/native_async_sleep_probe.ouro"
SLEEP = "runtime/platform/windows_sleep.ouro"
VARIANTS = ("original", "milliseconds", "flag")
FAULTS = {"milliseconds": ("u32_from_nat windows_sleep_milliseconds_per_second", "Nothing U32"),
          "flag": ("u8_from_nat 1", "Nothing U8")}
IMPORTS = ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll")
VALUES = ("millisecond-constant", "loop-flag-constant", "last-finite-word",
          "infinite-word-recognized-not-called", "over-u32-conversion-rejected",
          "over-u64-conversion-rejected", "wide32-seconds-preserved", "wide64-seconds-preserved")
BEGIN = ["ASYNC_BEFORE", "ASYNC_CONSTRUCTED"]
MESSAGES = {"milliseconds": "sleep_s: one-second duration conversion failed\n",
            "flag": "sleep_s: runtime-loop flag conversion failed\n"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_snapshot():
    units = collect_units(ENTRY)
    require(units and units[-1] == ENTRY and len(units) == len(set(units)) and SLEEP in units,
            "native async source closure is incomplete")
    require(all((ROOT / unit).resolve().is_relative_to(ROOT) for unit in units),
            "native async source escapes repository")
    body = (ROOT / SLEEP).read_text(encoding="utf-8")
    require(all(body.count(old) == 1 for old, _ in FAULTS.values()), "sleep source-fault anchors changed")
    return {"entry": ENTRY, "units": units, "sources": {unit: sha256_file(ROOT / unit) for unit in units}}


def variant_bytes(before, variant):
    require(variant in VARIANTS, "unknown native async source variant")
    result = {}
    for unit in before["units"]:
        body = (ROOT / unit).read_bytes()
        require(hashlib.sha256(body).hexdigest() == before["sources"][unit], "native async source changed: " + unit)
        if unit == SLEEP and variant in FAULTS:
            old, new = (value.encode("utf-8") for value in FAULTS[variant])
            require(body.count(old) == 1, "native async mutation anchor is not unique")
            body = body.replace(old, new)
        result[unit] = body
    return result


def build_inputs(directory, before, variant):
    bodies = variant_bytes(before, variant)
    return {"kind": KIND + ".inputs", "variant": variant, "entry": ENTRY,
            "source_root": str(directory / variant / "source-root"), "units": before["units"],
            "sources": {unit: hashlib.sha256(body).hexdigest() for unit, body in bodies.items()},
            "original_sources": before["sources"], "mutation": list(FAULTS[variant]) if variant in FAULTS else None,
            "fuel": 200000, "mir_limits": [16777216] * 3, "target": "x86_64-windows", "entry_name": "main"}


def verify_source_root(inputs):
    root = Path(inputs["source_root"]).resolve(strict=True)
    require(root.is_relative_to(ROOT), "native async copied root escapes repository")
    units = inputs["units"]
    require(set(inputs["sources"]) == set(units), "native async source manifest omits a unit")
    for unit in units:
        path = (root / unit).resolve(strict=True)
        require(path.is_relative_to(root) and sha256_file(path) == inputs["sources"][unit],
                "native async copied source changed: " + unit)
    actual = modules.collect_units(ENTRY,
        imports=lambda unit: modules.quoted_import_targets((root / unit).read_text(encoding="utf-8"), unit),
        normalize=lambda path: path.replace("\\", "/"))
    require(actual == units, "native async copied import order differs")


def freeze_sources(directory, before):
    for variant in VARIANTS:
        inputs = build_inputs(directory, before, variant)
        root = Path(inputs["source_root"])
        for unit, body in variant_bytes(before, variant).items():
            target = root / unit
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        verify_source_root(inputs)
        write_json_atomic(directory / variant / "inputs.json", inputs)


def image_info(path, variant):
    required = {"kernel32.dll": {"Sleep"}} if variant == "original" else None
    return inspect_image(path, IMPORTS, required)


def verify_builds(directory, before, producer, producer_hash, receipts, complete=True):
    require(set(receipts) == set(VARIANTS) if complete else set(receipts).issubset(VARIANTS),
            "native async requires the original and both source-fault builds")
    require(source_snapshot() == before and sha256_file(producer) == producer_hash,
            "native async source or fresh producer changed")
    images = {}
    for variant in VARIANTS:
        inputs = build_inputs(directory, before, variant)
        inputs_path = directory / variant / "inputs.json"
        require(read_json(inputs_path) == inputs, "native async build input manifest differs")
        verify_source_root(inputs)
        if variant not in receipts:
            continue
        output = directory / variant / "probe.exe"
        receipt_path = directory / variant / "receipt.json"
        require(sha256_file(receipt_path) == receipts[variant], "native async build receipt changed")
        receipt = read_json(receipt_path)
        command = [str(producer), ENTRY, output.as_posix(), *inputs["units"]]
        image = image_info(output, variant)
        expected = {"kind": KIND + ".build", "status": "passed", "variant": variant,
            "producer": str(producer), "producer_sha256": producer_hash, "argv": command,
            "cwd": inputs["source_root"], "inputs": str(inputs_path), "inputs_sha256": sha256_file(inputs_path),
            "output": str(output), "image": image, "result_status": "ok", "returncode": 0,
            "stdout": output.as_posix() + "\n", "inputs_unchanged": True, "producer_unchanged": True}
        require(type(receipt.get("returncode")) is int and receipt.get("inputs_unchanged") is True
                and receipt.get("producer_unchanged") is True
                and all(receipt.get(key) == value for key, value in expected.items()),
                "native async image lacks a successful exact-source build: " + variant)
        images[variant] = {"path": str(output), **image}
    require(not complete or len({entry["sha256"] for entry in images.values()}) == 3,
            "native async original and fault images are not distinct")
    return images


def run_section(producer, work, run, build_timeout, _probe_timeout, verify_inputs):
    if os.name != "nt":
        return {"kind": KIND, "status": "unavailable", "reason": "Windows x86-64 runtime required",
                "native_bootstrap": False, "rows": []}
    directory = work / "native-async"
    directory.mkdir()
    before = source_snapshot()
    producer_hash = sha256_file(producer)
    receipts = {}
    report = {"kind": KIND, "status": "running", "execution_backend": "direct-windows-pe",
              "external_supervisor": "python", "native_bootstrap": False, "inputs": before,
              "producer": str(producer), "producer_sha256": producer_hash, "receipts": receipts}

    def unchanged():
        verify_inputs()
        return verify_builds(directory, before, producer, producer_hash, receipts, complete=False)

    try:
        freeze_sources(directory, before)
        for variant in VARIANTS:
            unchanged()
            inputs = build_inputs(directory, before, variant)
            inputs_path = directory / variant / "inputs.json"
            output = directory / variant / "probe.exe"
            command = [str(producer), ENTRY, output.as_posix(), *inputs["units"]]
            receipt = {"kind": KIND + ".build", "status": "running", "variant": variant,
                "producer": str(producer), "producer_sha256": producer_hash, "argv": command,
                "cwd": inputs["source_root"], "inputs": str(inputs_path), "inputs_sha256": sha256_file(inputs_path),
                "output": str(output)}
            try:
                result = run("native-async-build-" + variant, command, build_timeout, cwd=Path(inputs["source_root"]))
                receipt.update(result_status=result.status, returncode=result.returncode, stdout=result.stdout)
                require(result.ok and result.stdout == output.as_posix() + "\n", "native async build failed: " + variant)
                receipt["image"] = image_info(output, variant)
                unchanged()
                receipt.update(status="passed", inputs_unchanged=True, producer_unchanged=True)
            finally:
                if receipt["status"] != "passed":
                    receipt["status"] = "failed"
                write_json_atomic(directory / variant / "receipt.json", receipt)
            receipts[variant] = sha256_file(directory / variant / "receipt.json")
            unchanged()
        images = verify_builds(directory, before, producer, producer_hash, receipts)
        spec = {"kind": KIND + ".spec", "inputs": before, "producer": str(producer),
                "producer_sha256": producer_hash, "receipts": receipts, "images": images}
        spec_path = directory / "spec.json"
        write_json_atomic(spec_path, spec)
        spec_hash = sha256_file(spec_path)
        result = run("native-async-runtime", [sys.executable, "-B", str(Path(__file__).resolve()),
                     "--observe", str(spec_path)], 150)
        require(result.ok and result.stdout == "FRONTEND_NATIVE_ASYNC: PASS cases=11\n" and result.stderr == "",
                "native async runtime observer failed")
        require(sha256_file(spec_path) == spec_hash, "native async observer inputs changed")
        observer = read_json(directory / "observer.json")
        verify_observer_report(observer, spec_hash)
        evidence = read_json(directory / "runtime" / "report.json")
        verify_runtime_report(evidence, images, directory / "runtime")
        unchanged()
        report.update(status="passed", source_lineage_confirmed=True, images=images, runtime=evidence,
                      observer=observer, spec_sha256=spec_hash)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def case_specs():
    def case(name, variant, mode, lines, code=0, stderr="", waits=(), held=False):
        return {"case": name, "variant": variant, "mode": mode, "lines": lines,
                "exit": code, "stderr": stderr, "waits": waits, "held": held}
    cases = [case("zero", "original", "zero", BEGIN + ["ASYNC_AFTER"]),
        case("short", "original", "short", BEGIN + ["ASYNC_AFTER"], waits=[("ASYNC_CONSTRUCTED", "ASYNC_AFTER")]),
        case("delay", "original", "delay", BEGIN + ["ASYNC_ACTION", "ASYNC_AFTER"], waits=[("ASYNC_CONSTRUCTED", "ASYNC_ACTION")]),
        case("reused", "original", "reused", BEGIN + ["ASYNC_FIRST", "ASYNC_AFTER"],
             waits=[("ASYNC_CONSTRUCTED", "ASYNC_FIRST"), ("ASYNC_FIRST", "ASYNC_AFTER")]),
        case("values", "original", "values", ["PRECISION_OK async-sleep/" + name for name in VALUES]
             + ["PRECISION_SUITE async-sleep rows=8"])]
    cases.extend(case(mode, "original", mode, BEGIN, held=True) for mode in ("wide32", "wide64"))
    cases.extend(case(fault + "-failure-" + mode, fault, mode, BEGIN, 73, MESSAGES[fault])
                 for fault in FAULTS for mode in ("zero", "delay"))
    return cases


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def verify_observer_report(report, spec_hash):
    supervisor = report.get("supervisor", {})
    require(report.get("kind") == KIND + ".observer" and report.get("status") == "passed"
            and report.get("spec_sha256") == spec_hash and report.get("memory_mib") == 768
            and report.get("suite_timeout_s") == 120 and report.get("case_timeout_s") == 15
            and supervisor.get("status") == "ok" and type(supervisor.get("returncode")) is int
            and supervisor.get("returncode") == 0
            and supervisor.get("stdout") == "FRONTEND_NATIVE_ASYNC_WORKER: PASS cases=11\n"
            and supervisor.get("stderr") == "", "native async supervisor receipt differs")


def verify_row(row, case):
    require(all(row.get(key) == case[key] for key in ("case", "variant", "mode")), "native async case identity differs")
    expected = "".join(line + "\n" for line in case["lines"]).encode("ascii")
    require(row.get("stdout_hex") == expected.hex() and row.get("stderr_hex") == case["stderr"].encode("ascii").hex(),
            "native async exact byte protocol differs: " + case["case"])
    require(type(row.get("exit")) is int and row.get("image_unchanged") is True
            and type(row.get("pid")) is int and 0 < row["pid"] <= 0xFFFFFFFF
            and finite(row.get("elapsed_s")), "native async process/image evidence differs")
    events = row.get("events", [])
    require(isinstance(events, list) and all(isinstance(event, dict) for event in events)
            and [event.get("line") for event in events] == case["lines"], "native async event order differs")
    times = [event.get("observed_s") for event in events]
    require(all(finite(value) and value <= 15 and value <= row["elapsed_s"] for value in times)
            and times == sorted(times), "native async observation times are invalid")
    at = dict(zip(case["lines"], times, strict=True))
    for first, second in case["waits"]:
        require(0.85 <= at[second] - at[first] <= 12, "native async one-second interval differs")
    if case["lines"][:2] == BEGIN:
        require(at[BEGIN[1]] - at[BEGIN[0]] <= 0.80, "native async action construction waited")
    if case["case"] == "zero":
        require(at["ASYNC_AFTER"] - at["ASYNC_CONSTRUCTED"] <= 0.80, "native async zero delay waited")
    if case["held"]:
        require(row.get("cancelled_by_harness") is True and row.get("alive_before_cancel") is True
                and finite(row.get("held_after_construction_s")) and 1.30 <= row["held_after_construction_s"] < 15
                and row["held_after_construction_s"] + at["ASYNC_CONSTRUCTED"] <= row["elapsed_s"],
                "native async wide Nat delay returned early or lacks held-process evidence")
    else:
        require(row["exit"] == case["exit"] and row.get("cancelled_by_harness") is False,
                "native async exit status differs")


def verify_runtime_report(report, images, directory=None):
    require(report.get("kind") == KIND + ".runtime" and report.get("status") == "passed"
            and report.get("native_bootstrap") is False and report.get("long_delays_completed") is False
            and report.get("source_lineage_confirmed") is True and report.get("images_unchanged") is True
            and report.get("image_hashes") == {key: value["sha256"] for key, value in images.items()},
            "native async runtime receipt is incomplete or stale")
    rows = report.get("rows", [])
    cases = case_specs()
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and [row.get("case") for row in rows] == [case["case"] for case in cases],
            "native async runtime cases missing, duplicated or reordered")
    for row, case in zip(rows, cases, strict=True):
        verify_row(row, case)
        if directory is not None:
            for stream in ("stdout", "stderr"):
                path = directory / case["case"] / (stream + ".bin")
                require(read_small(path).hex() == row[stream + "_hex"], "native async byte artifact differs")


def read_small(path):
    with path.open("rb") as stream:
        content = stream.read(1024 * 1024 + 1)
    require(len(content) <= 1024 * 1024, "native async stream exceeds 1 MiB observation cap")
    return content


def observe_case(image, directory, case, row):
    work = directory / case["case"]
    work.mkdir()
    binary = Path(image["path"])
    require(sha256_file(binary) == image["sha256"], "native async image changed before execution")
    proc = None
    events = []
    started = time.perf_counter()

    def observe(content, now):
        complete = content.split(b"\n")[:-1]
        require(complete[:len(events)] == [event[0] for event in events], "native async stdout changed before cursor")
        events.extend((line, now - started) for line in complete[len(events):])

    try:
        with (work / "stdout.bin").open("xb") as output, (work / "stderr.bin").open("xb") as errors:
            proc = subprocess.Popen([str(binary), case["mode"]], executable=str(binary), cwd=work,
                stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            row["pid"] = proc.pid
            while True:
                now = time.perf_counter()
                require(now - started < 15, "native async case exceeded 15-second deadline")
                observe(read_small(work / "stdout.bin"), now)
                read_small(work / "stderr.bin")
                status = proc.poll()
                if case["held"] and len(events) >= 2 and now - started - events[1][1] >= 1.30:
                    require(status is None, "native async wide Nat returned within observation window")
                    row.update(alive_before_cancel=True, held_after_construction_s=now - started - events[1][1])
                    proc.kill()
                    proc.wait(timeout=2)
                    row["cancelled_by_harness"] = True
                    break
                if status is not None:
                    observe(read_small(work / "stdout.bin"), time.perf_counter())
                    break
                time.sleep(0.01)
        row.update(exit=proc.returncode, stdout_hex=read_small(work / "stdout.bin").hex(),
                   stderr_hex=read_small(work / "stderr.bin").hex(),
                   events=[{"line": line.decode("ascii"), "observed_s": at} for line, at in events])
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        row["elapsed_s"] = time.perf_counter() - started
        row["image_unchanged"] = binary.is_file() and sha256_file(binary) == image["sha256"]
    verify_row(row, case)


def load_lineage(spec_path):
    spec = read_json(spec_path)
    require(spec.get("kind") == KIND + ".spec", "native async observer specification differs")
    producer = Path(spec["producer"]).resolve(strict=True)
    require(spec_path.resolve().is_relative_to(ROOT) and producer.is_relative_to(ROOT), "native async observer path escapes repository")
    images = verify_builds(spec_path.parent, spec["inputs"], producer, spec["producer_sha256"], spec["receipts"])
    require(images == spec["images"], "native async build image set changed")
    return spec, images


def worker(spec_path):
    spec, images = load_lineage(spec_path)
    spec_hash = sha256_file(spec_path)
    directory = spec_path.parent / "runtime"
    directory.mkdir()
    report = {"kind": KIND + ".runtime", "status": "running", "rows": [], "native_bootstrap": False,
              "image_hashes": {key: row["sha256"] for key, row in images.items()},
              "source_lineage_confirmed": False, "images_unchanged": False, "long_delays_completed": False}
    try:
        for case in case_specs():
            require(load_lineage(spec_path) == (spec, images) and sha256_file(spec_path) == spec_hash,
                    "native async lineage changed before a runtime case")
            row = {key: case[key] for key in ("case", "variant", "mode")}
            row["cancelled_by_harness"] = False
            report["rows"].append(row)
            observe_case(images[case["variant"]], directory, case, row)
            write_json_atomic(directory / "report.json", report)
        require(load_lineage(spec_path) == (spec, images) and sha256_file(spec_path) == spec_hash,
                "native async lineage changed after runtime cases")
        report.update(status="passed", source_lineage_confirmed=True, images_unchanged=True)
        verify_runtime_report(report, images, directory)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    print("FRONTEND_NATIVE_ASYNC_WORKER: PASS cases=11")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--observe", type=Path)
    mode.add_argument("--worker", type=Path)
    args = parser.parse_args()
    require(os.name == "nt", "native async observer requires Windows")
    spec_path = (args.observe or args.worker).resolve(strict=True)
    if args.worker:
        worker(spec_path)
        return
    spec, images = load_lineage(spec_path)
    spec_hash = sha256_file(spec_path)
    interpreter = getattr(sys, "_base_executable", sys.executable)
    result = run_limited([interpreter, "-B", str(Path(__file__).resolve()), "--worker", str(spec_path)],
                        timeout_s=120, memory_mb=768, cwd=ROOT, env=clean_env())
    observer = {"kind": KIND + ".observer", "status": "failed", "spec_sha256": spec_hash,
                "memory_mib": 768, "suite_timeout_s": 120, "case_timeout_s": 15, "supervisor": asdict(result)}
    try:
        require(result.ok and result.stdout == "FRONTEND_NATIVE_ASYNC_WORKER: PASS cases=11\n" and result.stderr == "",
                "native async bounded worker failed")
        require(load_lineage(spec_path) == (spec, images) and sha256_file(spec_path) == spec_hash,
                "native async lineage changed during bounded worker")
        verify_runtime_report(read_json(spec_path.parent / "runtime/report.json"), images, spec_path.parent / "runtime")
        observer["status"] = "passed"
        verify_observer_report(observer, spec_hash)
    finally:
        write_json_atomic(spec_path.parent / "observer.json", observer)
    print("FRONTEND_NATIVE_ASYNC: PASS cases=11")


if __name__ == "__main__":
    main()
