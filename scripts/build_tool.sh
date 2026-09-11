#!/usr/bin/env sh
# Build an Ouro IO entry as a native binary. Host wrappers are compatibility-only
# and require an explicit OURO_BUILD_TOOL_MODE=host-wrapper or =auto selection.
# OURO_EMIT_IO_SHIMS binds runtime axioms to runtime/ouro_io.c for standalone programs.

set -eu
if ! ulimit -s unlimited 2>/dev/null; then
	echo "BUILD_TOOL: stack limit unchanged" >&2
fi
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

ENTRY=${1:?usage: build_tool.sh <entry.ouro> <out-binary> [fuel]}
OUT=${2:?usage: build_tool.sh <entry.ouro> <out-binary> [fuel]}
FUEL=${3:-60000}
MODE="${OURO_BUILD_TOOL_MODE:-native}"
PY="${PYTHON:-python3}"

case "$MODE" in
native|host-wrapper|auto) ;;
*)
	echo "BUILD_TOOL: FAIL unknown OURO_BUILD_TOOL_MODE=$MODE (expected native, host-wrapper, or auto)" >&2
	exit 2
	;;
esac

command -v "$PY" >/dev/null 2>&1 || {
	echo "BUILD_TOOL: FAIL no working Python for source collection/packing (PYTHON=$PY)" >&2
	exit 127
}

SOURCE_MANIFEST="$OUT.sources"
SOURCE_MANIFEST_TMP="$SOURCE_MANIFEST.tmp.$$"
OUT_TMP="$OUT.tmp.$$"
trap 'rm -f "$SOURCE_MANIFEST_TMP" "$OUT_TMP" "${OUT_TMP}.exe"' EXIT

write_host_manifest() {
	{
		printf '%s\n' "$ENTRY"
		printf '%s\n' \
			scripts/build_tool.sh \
			scripts/host_tools.py \
			scripts/frontend_regen.py \
			scripts/repo_support.py \
			scripts/python.sh
	} | awk 'NF && !seen[$0]++' >"$SOURCE_MANIFEST_TMP"
}

install_host_wrapper() {
	rm -f "$OUT_TMP" "${OUT_TMP}.exe" "$SOURCE_MANIFEST_TMP"
	st=0
	"$PY" "$ROOT/scripts/host_tools.py" install-wrapper "$ENTRY" "$OUT_TMP" || st=$?
	if [ "$st" -ne 0 ]; then
		return "$st"
	fi
	[ -x "$OUT_TMP" ] || {
		echo "BUILD_TOOL: FAIL host wrapper installer produced no executable: $OUT_TMP" >&2
		return 1
	}
	write_host_manifest
	[ -s "$SOURCE_MANIFEST_TMP" ] || {
		echo "BUILD_TOOL: FAIL host wrapper source manifest is empty: $SOURCE_MANIFEST_TMP" >&2
		return 1
	}
	mv "$OUT_TMP" "$OUT"
	mv "$SOURCE_MANIFEST_TMP" "$SOURCE_MANIFEST"
	echo "BUILD_TOOL_BACKEND: host-wrapper mode=$MODE entry=$ENTRY out=$OUT"
	echo "BUILD_TOOL: OK $OUT"
	return 0
}

case "$MODE" in
host-wrapper)
	st=0
	install_host_wrapper || st=$?
	if [ "$st" -eq 0 ]; then
		exit 0
	fi
	if [ "$st" -eq 3 ]; then
		echo "BUILD_TOOL: FAIL host-wrapper backend does not support $ENTRY; select OURO_BUILD_TOOL_MODE=native" >&2
		exit 2
	fi
	echo "BUILD_TOOL: FAIL host-wrapper backend entry=$ENTRY status=$st" >&2
	exit "$st"
	;;
auto)
	echo "BUILD_TOOL_MODE: explicit compatibility auto entry=$ENTRY" >&2
	st=0
	install_host_wrapper || st=$?
	if [ "$st" -eq 0 ]; then
		exit 0
	fi
	if [ "$st" -ne 3 ]; then
		echo "BUILD_TOOL: FAIL host-wrapper attempt entry=$ENTRY status=$st" >&2
		exit "$st"
	fi
	echo "BUILD_TOOL_BACKEND: native-binary mode=auto reason=host-wrapper-unsupported entry=$ENTRY" >&2
	;;
native)
	echo "BUILD_TOOL_BACKEND: native-binary mode=native entry=$ENTRY" >&2
	;;
esac

C_BUILD_DIR="${OURO_C_BUILD_DIR:-_build/c}"
OURO1="$C_BUILD_DIR/ouro1"
if [ ! -x "$OURO1" ]; then
	echo "BOOTSTRAP_BUILD_REQUIRED compiler=$OURO1" >&2
	if ! sh "$ROOT/scripts/bootstrap.sh"; then
		echo "BOOTSTRAP_BUILD_FAILED compiler=$OURO1" >&2
		exit 1
	fi
fi
[ -x "$OURO1" ] || {
	echo "BUILD_TOOL: FAIL bootstrap completed without executable compiler: $OURO1" >&2
	exit 1
}

# The native build driver owns content keys, common runtime objects and atomic
# binary/source-manifest publication. Host-wrapper mode remains explicit above.
exec "$PY" "$ROOT/scripts/native_tool_build.py" "$ENTRY" "$OUT" \
	--compiler "$OURO1" --fuel "$FUEL"
