#!/usr/bin/env python3
"""Explicit bootstrap collector adapter; never a quality implementation.

This adapter does not implement formatting, lint or analysis. Unsupported
wrapper entries return 3 before creating or modifying any output, so the build
launcher can select its native backend or reject explicit host-wrapper mode.
"""
from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path
from typing import Sequence

from repo_support import relative_path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HOST_TOOL_MAP = {"tools/collect.ouro": "collect"}


def canon(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return relative_path(ROOT, candidate)


def command_collect(argv: Sequence[str]) -> int:
    # Source collection is a bootstrap dependency, not a lint or analyzer
    # decision. Do not import the compiler build driver for rejected commands.
    import frontend_regen as freg

    ap = argparse.ArgumentParser(prog="ouro-collect", description="collect Ouro import closure")
    ap.add_argument("file")
    args = ap.parse_args(argv)
    try:
        units = freg.collect_units(canon(args.file))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, OSError, ValueError):
        pass
    for unit in units:
        sys.stdout.write(unit + "\n")
    return 0


def command_install_wrapper(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="host_tools.py install-wrapper")
    ap.add_argument("entry")
    ap.add_argument("out")
    args = ap.parse_args(argv)
    entry = canon(args.entry)
    if entry.startswith("./"):
        entry = entry[2:]
    tool = HOST_TOOL_MAP.get(entry)
    if tool is None:
        return 3
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    script = f"""#!/usr/bin/env sh
set -eu
ROOT={str(ROOT)!r}
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${{PYTHON:-}}" ]; then
    echo "HOST_TOOL: FAIL no working Python" >&2
    exit 127
fi
exec "$PYTHON" "$ROOT/scripts/host_tools.py" {tool} "$@"
"""
    out.write_text(script, encoding="utf-8")
    mode = out.stat().st_mode
    out.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"BUILD_TOOL: OK {args.out} host-shim={tool}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: host_tools.py collect|install-wrapper ...", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "collect":
        return command_collect(rest)
    if cmd == "install-wrapper":
        return command_install_wrapper(rest)
    print(f"host_tools.py: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
