#!/usr/bin/env sh
# coil is the project-facing toolchain name. It maps verbs onto the existing
# ouro1 multiplexer and package tool. It does not replace bootstrap or kernel
# replay.

set -eu
ROOT="${OURO_ROOT:-}"
if [ -z "$ROOT" ]; then
	ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
fi
if command -v cygpath >/dev/null 2>&1; then
	case "$ROOT" in
	[A-Za-z]:*) ROOT=$(cygpath -u "$ROOT") ;;
	esac
fi
ROOT=$(printf '%s\n' "$ROOT" | tr "\\\\" '/')
OURO1="$ROOT/scripts/ouro1.sh"

usage() {
	printf '%s\n' "usage:" \
		"  coil check FILE [fuel]" \
		"  coil eval FILE (--eval EXPR | --print NAME) [--type TYPE]" \
		"  coil fmt [--check | --write] FILE..." \
		"  coil fix [--check | --write] FILE..." \
		"  coil analyze [ARGS...]" \
		"  coil lint [--deny] [--profile project|strict|release] [--family language|style|semantic] [PATH...]" \
		"  coil test [PATH...]" \
		"  coil doc [--check] [--out DIR] FILE..." \
		"  coil build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" \
		"  coil build [--profile dev|release]" \
		"  coil run FILE.ouro" \
		"  coil cache status|clean" \
		"  coil config show" \
		"  coil init [--name NAME] [--registry DIR]" \
		"  coil add NAME [--range RANGE]" \
		"  coil remove NAME" \
		"  coil install" \
		"  coil lock | coil resolve | coil seal" \
		"  coil update" \
		"  coil list" \
		"  coil verify" \
		"  coil doctor"
}

cmd=${1:-}
case "$cmd" in
	""|-h|--help|help)
		usage
		exit 2
		;;
	init|add|remove|install|lock|update|list|verify)
		shift
		exec sh "$OURO1" pkg "$cmd" "$@"
		;;
	resolve|seal)
		shift
		exec sh "$OURO1" pkg lock "$@"
		;;
	publish)
		echo "coil publish: not implemented" >&2
		exit 2
		;;
	pkg)
		shift
		exec sh "$OURO1" pkg "$@"
		;;
	doctor)
		shift
		exec sh "$OURO1" doctor "$@"
		;;
	check|collect|eval|rebuild|analyze|lint|fmt|fix|test|doc|lsp|build|run|cache|config|clean)
		exec sh "$OURO1" "$@"
		;;
	*)
		echo "coil: unknown command: $cmd" >&2
		usage
		exit 2
		;;
esac
