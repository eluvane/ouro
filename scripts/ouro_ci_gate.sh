#!/usr/bin/env sh
# Public compatibility entry point; shared host startup does not own gate policy.
set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
NATIVE_GATE_NAME=ouro-ci-gate
NATIVE_GATE_ENTRY=tools/ci_gate/main.ouro
NATIVE_GATE_BACKEND=ouro-native-ci-gate
NATIVE_GATE_PREFIX=OURO_CI_GATE_WRAPPER
# shellcheck source=scripts/native_gate_launcher.sh
. "$ROOT/scripts/native_gate_launcher.sh"
