#!/usr/bin/env python3
"""Byte-exact native-session observer; never an analyzer or clean-partial fallback."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"ouro.clippy-session.v2"
PROOF_BUDGET = 500_000


class SessionFailure(ValueError):
    """Confirmed frames are retained for inspection, not published as success."""
    def __init__(self, message: str, completed: list[bytes]):
        super().__init__(message)
        self.completed = tuple(completed)


class Reader:
    def __init__(self, data: bytes):
        self.data, self.offset = data, 0

    def line(self) -> bytes:
        end = self.data.find(b"\n", self.offset)
        if end < 0:
            raise ValueError("truncated line")
        result = self.data[self.offset:end]
        self.offset = end + 1
        return result

    def expect(self, expected: bytes) -> None:
        if self.line() != expected:
            raise ValueError(f"expected {expected!r}")

    def number(self, maximum: int) -> int:
        value = self.line()
        if (not value or not value.isdigit() or len(value) > len(str(maximum))
                or (value != b"0" and value.startswith(b"0"))):
            raise ValueError("noncanonical or oversized count")
        result = int(value)
        if result > maximum:
            raise ValueError("count exceeds bound")
        return result

    def blob(self) -> bytes:
        size = self.number(len(self.data) - self.offset)
        end = self.offset + size
        if end >= len(self.data) or self.data[end:end + 1] != b"\n":
            raise ValueError("truncated byte frame or missing delimiter")
        result = self.data[self.offset:end]
        self.offset = end + 1
        return result

    def snapshot(self) -> tuple[bytes, bool]:
        start = self.offset
        self.expect(b"ouro.clippy-semantic.v3")
        status = self.line()
        if status == b"error":
            if not self.line():
                raise ValueError("empty error")
        elif status == b"ok":
            self.blob()
            count = self.number(PROOF_BUDGET)
            for _ in range(count):
                code, owner = self.line(), self.line()
                self.number(PROOF_BUDGET)
                range_start, range_end = self.line(), self.line()
                if range_start == b"-" or range_end == b"-":
                    if range_start != b"-" or range_end != b"-":
                        raise ValueError("partial proof range")
                else:
                    for raw in (range_start, range_end):
                        if (not raw or not raw.isdigit() or (raw != b"0" and raw.startswith(b"0"))):
                            raise ValueError("noncanonical proof range")
                    if int(range_start) > int(range_end):
                        raise ValueError("inverted proof range")
                evidence = self.line()
                if not code.strip() or not owner.strip() or not evidence.strip():
                    raise ValueError("malformed proof record")
        else:
            raise ValueError("unexpected snapshot status")
        return self.data[start:self.offset], status == b"ok"

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ValueError("trailing bytes")


@dataclass(frozen=True)
class SessionPrefix:
    frames: tuple[bytes, ...]
    recycled: bool

    @property
    def completed(self) -> int:
        return len(self.frames)


def single(data: bytes, returncode: int = 0, stderr: bytes = b"") -> bytes:
    if returncode != 0 or stderr:
        raise ValueError("legacy worker failed")
    reader = Reader(data)
    frame, _ok = reader.snapshot()
    reader.finish()
    return frame


def session_prefix(data: bytes, paths: list[str], returncode: int,
                   stderr: bytes = b"") -> SessionPrefix:
    completed: list[bytes] = []
    reader = Reader(data)
    try:
        if not paths or any(not isinstance(p, str) or not p for p in paths):
            raise ValueError("empty or malformed request inventory")
        reader.expect(MAGIC)
        if reader.number(len(paths)) != len(paths):
            raise ValueError("request count mismatch")
        passed = True
        while True:
            marker = reader.line()
            if marker == b"done":
                break
            if marker != b"root" or len(completed) >= len(paths):
                raise ValueError("unknown or extra frame")
            expected = len(completed)
            if reader.number(len(paths) - 1) != expected:
                raise ValueError("duplicate, missing or reordered request ID")
            if reader.blob() != paths[expected].encode("utf-8"):
                raise ValueError("root identity mismatch")
            frame, ok = reader.snapshot()
            completed.append(frame)
            passed = passed and ok
        if reader.number(len(paths)) != len(completed) or not completed:
            raise ValueError("completion count mismatch or no progress")
        status = reader.line()
        reader.finish()
        recycled = len(completed) < len(paths)
        expected_status = b"error" if not passed else (b"recycle" if recycled else b"ok")
        if status != expected_status:
            raise ValueError("inconsistent final status")
        if stderr or returncode != (0 if passed else 1):
            raise ValueError("worker crash, unexpected stderr or inconsistent exit status")
        return SessionPrefix(tuple(completed), recycled)
    except ValueError as error:
        raise SessionFailure(str(error), completed) from error


def session(data: bytes, paths: list[str], returncode: int,
            stderr: bytes = b"") -> list[bytes]:
    result = session_prefix(data, paths, returncode, stderr)
    if result.recycled:
        raise SessionFailure("capture requires the complete request inventory", list(result.frames))
    return list(result.frames)


def compare_captures(directory: Path) -> dict:
    paths = json.loads((directory / "paths.json").read_text(encoding="utf-8"))
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise ValueError("invalid captured request inventory")
    expected = [single((directory / f"single-{i}.out").read_bytes(),
                       int((directory / f"single-{i}.status").read_text()),
                       (directory / f"single-{i}.err").read_bytes()) for i in range(len(paths))]
    for i in range(10):
        actual = session((directory / f"session-{i}.out").read_bytes(), paths,
                         int((directory / f"session-{i}.status").read_text()),
                         (directory / f"session-{i}.err").read_bytes())
        if actual != expected:
            raise ValueError(f"snapshot byte parity failed in session {i}")
    payload = b"".join(str(len(frame)).encode() + b":" + frame for frame in expected)
    return {"kind": "ouro.clippy-session-parity.v1", "pass": True,
            "requests": len(paths), "sessions": 10,
            "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
            "scope": "exact source/proof/error frames; not reporter/fix parity or performance"}


def selftest() -> int:
    def ok(source: bytes = b"source\n\x00\xff", proofs: bytes = b"") -> bytes:
        count = 1 if proofs else 0
        return (b"ouro.clippy-semantic.v3\nok\n" + str(len(source)).encode() + b"\n"
                + source + b"\n" + str(count).encode() + b"\n" + proofs)

    error = b"ouro.clippy-semantic.v3\nerror\nparse failed\n"

    def wire(paths: list[str], frames: list[bytes], status: bytes | None = None) -> bytes:
        result = MAGIC + b"\n" + str(len(paths)).encode() + b"\n"
        for i, (path, frame) in enumerate(zip(paths, frames, strict=False)):
            encoded = path.encode("utf-8")
            result += (b"root\n" + str(i).encode() + b"\n" + str(len(encoded)).encode()
                       + b"\n" + encoded + b"\n" + frame)
        if status is None:
            status = b"error" if error in frames else (b"recycle" if len(frames) < len(paths) else b"ok")
        return result + b"done\n" + str(len(frames)).encode() + b"\n" + status + b"\n"

    class SessionProtocolTests(unittest.TestCase):
        def test_exact_bytes_unicode_paths_and_embedded_frames(self):
            paths = ["каталог/漢字\nfile.ouro", "same.ouro", "same.ouro"]
            frames = [ok(b"\r\n\x00\xffdone\n3\nok\nouro.clippy-semantic.v3\n"), ok(), ok()]
            self.assertEqual(session(wire(paths, frames), paths, 0), frames)

        def test_error_is_sticky_and_next_success_survives(self):
            for frames in ([error, ok()], [ok(), error, ok()]):
                paths = [str(i) for i in range(len(frames))]
                self.assertEqual(session(wire(paths, frames), paths, 1), frames)
                with self.assertRaises(SessionFailure):
                    session(wire(paths, frames), paths, 0)
                with self.assertRaises(SessionFailure):
                    session(wire(paths, frames, b"ok"), paths, 1)

        def test_every_truncation_fails_closed(self):
            data = wire(["a", "b"], [ok(), ok()])
            for end in range(len(data)):
                with self.subTest(end=end), self.assertRaises(SessionFailure):
                    session(data[:end], ["a", "b"], 0)

        def test_completed_frames_survive_crash_for_inspection(self):
            frame = ok()
            data = wire(["a", "b"], [frame, frame])
            partial = data[:data.index(b"root\n1\n")]
            with self.assertRaises(SessionFailure) as raised:
                session_prefix(partial, ["a", "b"], 137)
            self.assertEqual(raised.exception.completed, (frame,))

        def test_crash_even_after_complete_output(self):
            for code in (-9, 1, 73, 137):
                with self.subTest(code=code), self.assertRaises(SessionFailure):
                    session(wire(["a"], [ok()]), ["a"], code)

        def test_repeated_missing_reordered_ids(self):
            data = wire(["a", "b"], [ok(), ok()])
            for changed in (data.replace(b"root\n1\n", b"root\n0\n"),
                            data.replace(b"root\n0\n", b"root\n1\n"),
                            data.replace(b"root\n1\n", b"root\n2\n")):
                with self.assertRaises(SessionFailure):
                    session(changed, ["a", "b"], 0)

        def test_counts_paths_footer_version_and_stderr(self):
            data = wire(["a"], [ok()])
            for changed in (data.replace(b"v2\n1\n", b"v2\n0\n", 1),
                            data.replace(b"done\n1\n", b"done\n0\n"),
                            data.replace(b"\n1\na\n", b"\n1\nb\n"), data + b"junk",
                            data.replace(MAGIC, b"ouro.clippy-session.v1"),
                            data.replace(b"done\n1\nok\n", b"done\n1\nrecycle\n")):
                with self.assertRaises(SessionFailure):
                    session(changed, ["a"], 0)
            with self.assertRaises(SessionFailure):
                session(data, ["a"], 0, b"fatal")

        def test_wrong_length_and_noncanonical_counts(self):
            data = wire(["a"], [ok(b"x")])
            for count in (b"01", b"-1", b"+1", b"999999999999999999999999"):
                with self.assertRaises(SessionFailure):
                    session(data.replace(MAGIC + b"\n1\n", MAGIC + b"\n" + count + b"\n"), ["a"], 0)
            with self.assertRaises(SessionFailure):
                session(data.replace(b"ok\n1\nx\n", b"ok\n2\nx\n"), ["a"], 0)

        def test_full_proof_record_and_no_trailing_bytes(self):
            frame = ok(b"x", b"CODE\nowner\n3\n-\n-\nevidence\n")
            self.assertEqual(single(frame), frame)
            for bad in (frame + b"\n", frame.replace(b"owner\n3", b"owner\n-3"),
                        frame.replace(b"owner\n3", b"owner\n500001"),
                        frame.replace(b"CODE", b" "),
                        frame.replace(b"owner", b" "),
                        frame.replace(b"evidence", b" "),
                        frame.replace(b"evidence\n", b"")):
                with self.assertRaises(ValueError):
                    single(bad)

        def test_empty_session_rejected(self):
            with self.assertRaises(SessionFailure):
                session(wire([], []), [], 0)

        def test_hundred_sequential_roots_and_determinism(self):
            paths = [f"root-{i}.ouro" for i in range(100)]
            frames = [ok(str(i).encode()) for i in range(100)]
            data = wire(paths, frames)
            for _ in range(10):
                self.assertEqual(session(data, paths, 0), frames)

        def test_forced_recycle_resumes_exact_remaining_suffix(self):
            paths = ["a", "b", "c", "d"]
            frames = [ok(str(i).encode()) for i in range(4)]
            first = session_prefix(wire(paths, frames[:2]), paths, 0)
            self.assertTrue(first.recycled)
            remaining = paths[first.completed:]
            second = session_prefix(wire(remaining, frames[2:]), remaining, 0)
            self.assertFalse(second.recycled)
            self.assertEqual(first.frames + second.frames, tuple(frames))
            with self.assertRaises(SessionFailure):
                session(wire(paths, frames[:2]), paths, 0)

        def test_partial_ok_and_zero_progress_recycle_rejected(self):
            for frames, status in (([], b"recycle"), ([ok()], b"ok"), ([error], b"recycle")):
                with self.assertRaises(SessionFailure):
                    session_prefix(wire(["a", "b"], frames, status), ["a", "b"], 0)

        def test_error_prefix_resumes_exact_suffix_and_keeps_error(self):
            paths = ["a", "b", "c", "d"]
            frames = [ok(b"first"), error, ok(b"third"), ok(b"last")]
            first = session_prefix(wire(paths, frames[:3]), paths, 1)
            self.assertTrue(first.recycled)
            self.assertEqual(first.completed, 3)
            remaining = paths[first.completed:]
            second = session_prefix(wire(remaining, frames[3:]), remaining, 0)
            self.assertFalse(second.recycled)
            self.assertEqual(first.frames + second.frames, tuple(frames))
            with self.assertRaises(SessionFailure):
                session(wire(paths, frames[:3]), paths, 1)

        def test_error_prefix_requires_error_footer_exit_and_silent_stderr(self):
            paths = ["a", "b", "c"]
            data = wire(paths, [error, ok()])
            for code, stderr in ((0, b""), (137, b""), (-9, b""), (1, b"OOM")):
                with self.subTest(code=code, stderr=stderr), self.assertRaises(SessionFailure):
                    session_prefix(data, paths, code, stderr)
            for frames, status in (([], b"error"), ([ok()], b"error"),
                                   ([error], b"ok"), ([error], b"recycle")):
                with self.subTest(status=status), self.assertRaises(SessionFailure):
                    session_prefix(wire(paths, frames, status), paths, 1)
            for end in range(len(data)):
                with self.subTest(end=end), self.assertRaises(SessionFailure):
                    session_prefix(data[:end], paths, 1)

        def test_recycle_requires_successful_exit_and_silent_stderr(self):
            data = wire(["a", "b"], [ok()])
            for code, stderr in ((137, b""), (1, b""), (0, b"OOM")):
                with self.assertRaises(SessionFailure):
                    session_prefix(data, ["a", "b"], code, stderr)

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SessionProtocolTests))
    return 0 if result.wasSuccessful() else 1


def capture(arguments: list[str], *, child: bool) -> int:
    """Keep raw byte captures while the existing limiter owns the process tree."""
    if len(arguments) < 3:
        raise ValueError("capture requires DIRECTORY STEM COMMAND [ARGUMENT...]")
    directory, stem, *command = arguments
    if not stem or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in stem):
        raise ValueError("capture stem must be a lowercase slug")
    base = Path(directory).resolve()
    status = base / f"{stem}.status"
    errors = base / f"{stem}.err"
    if child:
        with (base / f"{stem}.out").open("wb") as output, errors.open("wb") as error:
            result = subprocess.run(command, stdout=output, stderr=error, check=False)
        status.write_text(str(result.returncode) + "\n", encoding="utf-8")
        return 0
    status.write_text("incomplete\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from ourosmith.limits import clean_env, run_limited
    result = run_limited([sys.executable, str(Path(__file__).resolve()),
                          "--capture-child", str(base), stem, *command],
                         cwd=root, env=clean_env(), timeout_s=300, memory_mb=3072)
    if result.status != "ok" or result.returncode != 0:
        with errors.open("ab") as output:
            output.write(f"\nSESSION_CAPTURE: {result.status} rc={result.returncode}\n".encode())
            output.write(result.stderr.encode("utf-8", errors="replace"))
        print(f"SESSION_CAPTURE: FAIL {result.status}", file=sys.stderr)
        return 1
    return 0


def vocabulary_stress(directory: Path, worker: str) -> None:
    """Distinct compiler identities must recycle without losing a root or frame."""
    base = directory.resolve()
    sources = base / "vocabulary"
    sources.mkdir(parents=True, exist_ok=True)
    paths = [f"root-{index}.ouro" for index in range(24)]
    for index, path in enumerate(paths):
        source = "".join(
            f"def distinct_{index}_{item} (A : Type) (value : A) : A := value;\n"
            for item in range(96)
        )
        (sources / path).write_text(source, encoding="utf-8", newline="\n")

    def run(stem: str, selected: list[str]) -> SessionPrefix:
        command = [str(Path(worker).resolve()), "--session", str(sources), *selected]
        if capture([str(base), stem, *command], child=False):
            raise ValueError(f"vocabulary capture failed: {stem}")
        status = int((base / f"{stem}.status").read_text())
        if status != 0:
            raise ValueError(f"valid vocabulary root failed: {stem}, exit {status}")
        return session_prefix((base / f"{stem}.out").read_bytes(), selected,
                              status,
                              (base / f"{stem}.err").read_bytes())

    cold = [run(f"vocabulary-cold-{index}", [path]).frames[0]
            for index, path in enumerate(paths)]
    frames: list[bytes] = []
    prefixes: list[int] = []
    while len(frames) < len(paths):
        result = run(f"vocabulary-warm-{len(frames)}", paths[len(frames):])
        frames.extend(result.frames)
        prefixes.append(result.completed)
    if frames != cold:
        raise ValueError("distinct-root recycling lost, repeated or changed a cold source/proof frame")
    if len(prefixes) < 2 or not any(count % 2 for count in prefixes[:-1]):
        raise ValueError("vocabulary limit must stop before the second root of an allocation epoch")
    (base / "vocabulary.json").write_text(json.dumps({
        "pass": True, "roots": len(paths), "prefixes": prefixes,
        "exact_frame_parity": True, "memory_mb": 3072,
    }, indent=2) + "\n", encoding="utf-8")
    print("SESSION_STRESS: PASS distinct-root vocabulary, early epoch recycle and cold frame parity")


def stress(directory: Path, worker: str) -> None:
    """Run real native roots under the same limiter used by parity captures."""
    base = directory.resolve()
    executable = str(Path(worker).resolve())
    sources = str(base / "sources")
    baseline = single((base / "single-1.out").read_bytes(),
                      int((base / "single-1.status").read_text()),
                      (base / "single-1.err").read_bytes())

    def run(stem: str, paths: list[str], source_root: str = sources) -> SessionPrefix:
        if capture([str(base), stem, executable, "--session", source_root, *paths], child=False):
            raise ValueError(f"native capture failed: {stem}")
        return session_prefix((base / f"{stem}.out").read_bytes(), paths,
                              int((base / f"{stem}.status").read_text()),
                              (base / f"{stem}.err").read_bytes())

    hundred = run("stress-hundred", ["b.ouro"] * 100)
    if hundred.recycled or hundred.frames != (baseline,) * 100:
        raise ValueError("100 small roots must complete in one process with exact frame parity")
    paths = ["b.ouro"] * 130
    first = run("stress-recycle", paths)
    if not first.recycled or first.completed != 128:
        raise ValueError("root-count policy must recycle after exactly 128 small roots")
    second = run("stress-resume", paths[first.completed:])
    if second.recycled or first.frames + second.frames != (baseline,) * len(paths):
        raise ValueError("recycle must resume only the confirmed unprocessed suffix")
    print("SESSION_STRESS: PASS 100 roots, 50 epochs, 128-root recycle and exact suffix")
    vocabulary_stress(base, executable)

    # Real import fan-in exposes parser/registry temporaries that tiny roots
    # cannot exercise. Keep the existing 3072 MiB capture limit for every run.
    root = Path(__file__).resolve().parents[2]
    paths = ["tools/repo_gate/checks.ouro", "compiler/native/managed_source.ouro"] * 2
    paths.extend(["tools/repo_gate/hardening.ouro"] * 2)
    pending = paths
    frames: list[bytes] = []
    while pending:
        result = run(f"stress-production-{len(frames)}", pending, str(root))
        frames.extend(result.frames)
        pending = pending[result.completed:]
    for path, frame in zip(paths, frames, strict=True):
        reader = Reader(frame)
        reader.expect(b"ouro.clippy-semantic.v3")
        reader.expect(b"ok")
        if reader.blob() != (root / path).read_bytes():
            raise ValueError("production session changed the selected source bytes")
    if frames[:2] != frames[2:4] or frames[4] != frames[5]:
        raise ValueError("production snapshot changed across retained or recycled epochs")
    print("SESSION_STRESS: PASS 6 production roots within 3072 MiB with exact frame parity")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--compare", type=Path)
    mode.add_argument("--stress", nargs=2, metavar=("DIRECTORY", "WORKER"))
    mode.add_argument("--capture", nargs=argparse.REMAINDER)
    mode.add_argument("--capture-child", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.capture is not None or args.capture_child is not None:
        try:
            return capture(args.capture if args.capture is not None else args.capture_child,
                           child=args.capture_child is not None)
        except (OSError, ValueError) as error:
            print(f"SESSION_CAPTURE: FAIL {error}", file=sys.stderr)
            return 1
    if args.stress is not None:
        try:
            stress(Path(args.stress[0]), args.stress[1])
        except (OSError, ValueError, TypeError) as error:
            print(f"SESSION_STRESS: FAIL {error}", file=sys.stderr)
            return 1
        return 0
    report = args.compare / "parity.json"
    try:
        report.write_text(json.dumps({"kind": "ouro.clippy-session-parity.v1", "pass": False})
                          + "\n", encoding="utf-8")
        result = compare_captures(args.compare)
    except (OSError, ValueError, TypeError) as error:
        print(f"SESSION_PARITY: FAIL {error}")
        return 1
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"SESSION_PARITY: PASS {result['requests']} roots x 10 sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
