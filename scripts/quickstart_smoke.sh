#!/usr/bin/env sh
# Compatibility launcher; tools/ci_gate owns the quickstart command sequence.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

OUT="${QUICKSTART_OUT:-_build/ouro_ci/quickstart-native}"
sh scripts/ouro_ci_gate.sh \
  --profile=quickstart-native \
  "--root=$ROOT" \
  "--out=$OUT" \
  --fail-fast --quiet --echo-output

echo "QUICKSTART: PASS out of $ROOT"
