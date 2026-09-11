#!/usr/bin/env sh
# Shared startup boundary for the public Ouro-native gate launchers.
# Sourced with fixed tool metadata; argument forwarding and exec remain here.

set -eu
if ! ulimit -s unlimited 2>/dev/null; then
	echo "$NATIVE_GATE_PREFIX: stack limit unchanged" >&2
fi
cd "$ROOT"

C_BUILD_DIR=${OURO_C_BUILD_DIR:-$ROOT/_build/c}
case "$C_BUILD_DIR" in
	/*|[A-Za-z]:*) ;;
	*) C_BUILD_DIR="$ROOT/$C_BUILD_DIR" ;;
esac
mkdir -p "$C_BUILD_DIR"

TOOL_REBUILD_REASON=""
TOOL_RUN_BIN=""
TOOL_MANIFEST=""

tool_binary_path() {
	logical=$1
	exe=""
	# MSYS -x may resolve a missing name to name.exe. Enumerate physical
	# names so the selected binary and its sidecar have the same spelling.
	for physical in "$logical"*; do
		case "$physical" in
			"$logical")
				if [ -x "$physical" ]; then
					printf '%s\n' "$physical"
					return 0
				fi
				;;
			"${logical}.exe")
				if [ -x "$physical" ]; then exe=$physical; fi
				;;
		esac
	done
	if [ -n "$exe" ]; then
		printf '%s\n' "$exe"
		return 0
	fi
	return 1
}

tool_manifest_path() {
	bin=$1
	manifest="$bin.sources"
	case "$bin" in
		*.exe)
			base_manifest="${bin%.exe}.sources"
			if [ ! -s "$manifest" ] && [ -s "$base_manifest" ]; then
				manifest=$base_manifest
			fi
			;;
	esac
	printf '%s\n' "$manifest"
}

tool_manifest_source_abs() {
	src=$1
	case "$src" in
		""|/*|[A-Za-z]:*|..|../*|*/../*|*\\*) return 1 ;;
		*) printf '%s/%s\n' "$ROOT" "$src" ;;
	esac
}

tool_needs_rebuild() {
	logical=$1
	TOOL_REBUILD_REASON=""
	TOOL_RUN_BIN=$(tool_binary_path "$logical") || {
		TOOL_REBUILD_REASON="binary_missing"
		return 0
	}
	TOOL_MANIFEST=$(tool_manifest_path "$TOOL_RUN_BIN")
	if [ ! -e "$TOOL_MANIFEST" ]; then
		TOOL_REBUILD_REASON="manifest_missing"
		return 0
	fi
	if [ ! -s "$TOOL_MANIFEST" ]; then
		TOOL_REBUILD_REASON="manifest_empty"
		return 0
	fi
	seen=0
	while IFS= read -r src || [ -n "$src" ]; do
		seen=1
		abs=$(tool_manifest_source_abs "$src") || {
			TOOL_REBUILD_REASON="manifest_path_invalid:$src"
			return 0
		}
		if [ ! -e "$abs" ]; then
			TOOL_REBUILD_REASON="source_missing:$src"
			return 0
		fi
		newer=$(find -H "$abs" -prune -newer "$TOOL_RUN_BIN" -print) || {
			TOOL_REBUILD_REASON="source_stat_failed:$src"
			return 0
		}
		if [ -n "$newer" ]; then
			TOOL_REBUILD_REASON="source_newer:$src"
			return 0
		fi
	done <"$TOOL_MANIFEST"
	if [ "$seen" -eq 0 ]; then
		TOOL_REBUILD_REASON="manifest_empty"
		return 0
	fi
	return 1
}

BIN="$C_BUILD_DIR/$NATIVE_GATE_NAME"
if tool_needs_rebuild "$BIN"; then
	reason=$TOOL_REBUILD_REASON
	old_bin=$TOOL_RUN_BIN
	echo "BOOTSTRAP_BUILD_REQUIRED tool=$NATIVE_GATE_NAME reason=$reason" >&2
	if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" \
		"$NATIVE_GATE_ENTRY" "$BIN" >&2; then
		echo "NATIVE_TOOL_REBUILD_FAILED tool=$NATIVE_GATE_NAME reason=$reason" >&2
		if [ -n "$old_bin" ]; then
			echo "STALE_BINARY_REJECTED tool=$NATIVE_GATE_NAME path=$old_bin" >&2
		fi
		exit 1
	fi
	echo "NATIVE_TOOL_REBUILT tool=$NATIVE_GATE_NAME reason=$reason" >&2
fi

if tool_needs_rebuild "$BIN"; then
	echo "NATIVE_TOOL_INVALID_AFTER_REBUILD tool=$NATIVE_GATE_NAME reason=$TOOL_REBUILD_REASON" >&2
	[ -z "$TOOL_RUN_BIN" ] || echo "STALE_BINARY_REJECTED tool=$NATIVE_GATE_NAME path=$TOOL_RUN_BIN" >&2
	exit 1
fi

echo "EXECUTION_BACKEND=$NATIVE_GATE_BACKEND binary=$TOOL_RUN_BIN manifest=$TOOL_MANIFEST" >&2
exec "$TOOL_RUN_BIN" "$@"
