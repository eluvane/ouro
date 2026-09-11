#!/usr/bin/env sh
# Emit split frontend TUs with a seed ouro1 and pack them into driver_u.c.
# The Python helper owns deterministic TU/final caches, atomic writes, and the
# timing/cache report; this shell file remains the stable entry point.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${PYTHON:-}" ]; then
	echo "EMIT_FRONTEND: FAIL no working Python" >&2
	exit 127
fi
exec "$PYTHON" "$ROOT/scripts/frontend_regen.py" "$@"
