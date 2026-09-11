"""OuroSmith: generative, oracle-checked testing for the Ouro toolchain.

The package is driven by ``scripts/ouro_smith.py``.  Every module is
deterministic given a seed; bulk output goes under ``_build/smith`` and the
compact persistent corpus lives under ``quality/smith/``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SMITH_VERSION = "1"
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parents[1]


def generator_hash() -> str:
    """Bind recipes to the host code and complete native generator/law source cones."""
    from frontend_regen import collect_units

    digest = hashlib.sha256()
    sources = [*PACKAGE_DIR.rglob("*.py"), ROOT / "scripts/ouro_smith.py", ROOT / "quality/smith/seeds.json"]
    for entry in ("tests/compiler_smith_runner.ouro", "tests/compiler_retained_tests.ouro"):
        units = collect_units(entry)
        if not units or units[-1] != entry:
            raise ValueError("native Smith generator source collection is incomplete")
        sources.extend(ROOT / name for name in units)
    for path in sorted(set(sources)):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]
