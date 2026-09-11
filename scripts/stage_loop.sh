#!/usr/bin/env sh
# Closed bootstrap stage loop wrapper.
# Python owns signatures, per-stage stamps, deterministic frontend/backend
# caches, timing reports, and --promote. This file stays as the stable command.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
export OURO_ROOT="$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
exec "$PYTHON" "$ROOT/scripts/stage_loop.py" "$@"
