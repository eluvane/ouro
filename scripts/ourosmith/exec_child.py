"""Private limit launcher: establish OS limits before executing tested code."""
from __future__ import annotations

import os
import subprocess
import sys


def main():
    limit, *command = sys.argv[1:]
    try:
        if os.name == "nt":
            from windows_job import join

            join(limit)
            return subprocess.call(command, executable=command[0])
        import resource

        memory = int(limit) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # Match the native PE stack reserve. A stack as large as the whole AS
        # budget prevents Python build workers from creating even one thread.
        # Recursive compiler stacks still respect the AS and inherited hard cap.
        _soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        stack = min(memory, 128 * 1024 * 1024)
        if hard != resource.RLIM_INFINITY:
            stack = min(stack, hard)
        resource.setrlimit(resource.RLIMIT_STACK, (stack, hard))
        os.nice(5)
        os.execvpe(command[0], command, os.environ)  # noqa: S606 -- parent supplied a resolved executable and scrubbed argv environment
    except (OSError, ValueError) as exc:
        print(f"OURO_SMITH_LIMIT_SETUP: {exc}", file=sys.stderr)
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
