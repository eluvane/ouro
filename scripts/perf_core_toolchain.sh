#!/usr/bin/env sh
# Run the core toolchain performance evidence collector.

set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ -f "$ROOT/scripts/python.sh" ]; then
	# shellcheck source=scripts/python.sh
	. "$ROOT/scripts/python.sh"
fi
PY="${PYTHON:-python3}"
exec "$PY" "$ROOT/scripts/perf_core_toolchain.py" "$@"
