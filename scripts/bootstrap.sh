#!/usr/bin/env sh
# Build a current compiler through the verified historical bootstrap inputs.
# The Python driver checks current sources and complete successor C equality.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -n "${PYTHON:-}" ]; then
	exec "$PYTHON" "$ROOT/scripts/ouro_build.py" build "$@"
fi
echo "BOOTSTRAP: FAIL Python 3 is required for the verified current-source bootstrap" >&2
exit 1
