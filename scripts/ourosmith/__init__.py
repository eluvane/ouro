"""OuroSmith: generative, oracle-checked testing for the Ouro toolchain.

The package is driven by ``scripts/ouro_smith.py``.  Every module is
deterministic given a seed; bulk output goes under ``_build/smith`` and the
compact persistent corpus lives under ``quality/smith/``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

SMITH_VERSION = "1"
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parents[1]


def normalized_source_chunks(path: Path) -> Iterator[bytes]:
    """Yield source bytes with CRLF converted to LF."""
    pending_cr = False
    with path.open("rb") as stream:
        for raw_chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if pending_cr and not raw_chunk.startswith(b"\n"):
                yield b"\r"
            pending_cr = raw_chunk.endswith(b"\r")
            chunk = raw_chunk[:-1] if pending_cr else raw_chunk
            yield chunk.replace(b"\r\n", b"\n")
    if pending_cr:
        yield b"\r"


def generator_hash() -> str:
    """Bind recipes to the host code and complete native generator/law source cones."""
    from frontend_regen import iter_unit_closures

    digest = hashlib.sha256()
    sources = [*PACKAGE_DIR.rglob("*.py"), ROOT / "scripts/ouro_smith.py", ROOT / "quality/smith/seeds.json"]
    entries = "tests/compiler_smith_runner.ouro", "tests/compiler_retained_tests.ouro"
    for entry, units in iter_unit_closures(entries):
        if not units or units[-1] != entry:
            raise ValueError("native Smith generator source collection is incomplete")
        sources.extend(ROOT / name for name in units)
    for path in sorted(set(sources)):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        for chunk in normalized_source_chunks(path):
            digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()[:16]
