#!/usr/bin/env sh
# Minimal host adapter for structured process execution until proc_exec accepts stdin.
set -eu

INPUT=${1:?usage: process_stdin.sh INPUT COMMAND [ARG...]}
shift
[ "$#" -gt 0 ] || {
	echo "process_stdin.sh: missing command" >&2
	exit 2
}
exec "$@" <"$INPUT"
