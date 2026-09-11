#!/usr/bin/env sh
# LSP evidence feeds a scripted stdio session at once; replies are still verified in protocol order.

set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

# Native acceptance uses an explicitly provisioned directory, never a C fallback.
NATIVE_TOOLS=""
if [ "${1:-}" = --native-tools ]; then
	if [ "$#" -lt 2 ] || [ -z "$2" ]; then
		echo "usage: sh scripts/lsp_suite.sh --native-tools DIR [suite options]" >&2
		exit 2
	fi
	NATIVE_TOOLS=$2
	case "$NATIVE_TOOLS" in
	/* | [A-Za-z]:*) ;;
	*) NATIVE_TOOLS="$ROOT/$NATIVE_TOOLS" ;;
	esac
	NATIVE_TOOLS=$(CDPATH='' cd "$NATIVE_TOOLS" && pwd -P) || {
		echo "LSP_SUITE: FAIL native candidate directory" >&2
		exit 1
	}
	shift 2
fi

OUT="${LSP_SUITE_OUT:-$ROOT/_build/lsp_suite}"
mkdir -p "$OUT"

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite lsp \
		--receipt "$OUT/native-candidates.json"
	LSP="$NATIVE_TOOLS/ouro-lsp.exe"
else
	CC_BIN="${CC:-cc}"
	command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
	if ! command -v "$CC_BIN" >/dev/null 2>&1; then
		echo "LSP_SUITE: SKIP no system C compiler" >&2
		exit 0
	fi

	LSP="$OUT/ouro-lsp"
	# Mixed WSL/Windows trees leave an ELF next to a PE checkout (or the reverse).
	# build_tool will not replace a still-newer foreign binary; drop it first.
	if [ -e "$LSP" ]; then
		case "$(uname -s 2>/dev/null || echo unknown)" in
		MINGW*|MSYS*|CYGWIN*|Windows_NT*)
			file "$LSP" 2>/dev/null | grep -qi 'PE32' || rm -f "$LSP"
			;;
		Linux)
			file "$LSP" 2>/dev/null | grep -qi 'ELF' || rm -f "$LSP"
			;;
		esac
	fi
	sh "$ROOT/scripts/build_tool.sh" tools/lsp.ouro "$LSP" >"$OUT/build.log" 2>&1 || {
		echo "LSP_SUITE: FAIL build" >&2
		tail -n 20 "$OUT/build.log" >&2
		exit 1
	}
fi

rows=0
fail=0
ok() {
	rows=$((rows + 1))
	echo "LSP_OK $1"
}
bad() {
	rows=$((rows + 1))
	fail=$((fail + 1))
	echo "LSP_FAIL $1 $2" >&2
}

# One framed message. Content-Length counts bytes of the body.
frame() {
	printf 'Content-Length: %d\r\n\r\n%s' "$(printf '%s' "$1" | wc -c)" "$1"
}

# A file as a JSON string body, so the client sends the same text the checker
# reads from disk and the reported positions line up.
json_text() {
	sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' "$1" | awk '{ printf "%s\\n", $0 }'
}

FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group lsp --out "$OUT/inputs")
SAMPLE="$FIXTURES/sample.ouro"
MESSY="$FIXTURES/messy.ouro"
BROKEN="$OUT/broken.ouro"
printf -- '-- @entry broken\n\ndef broken : Nat := no_such_name Z;\n' >"$BROKEN"
UNSAVED="$OUT/unsaved.ouro"
printf -- 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n\ndef ok : Nat := Z;\n' >"$UNSAVED"

uri_of_path() {
	case "$(uname -s 2>/dev/null || echo unknown)" in
	MINGW*|MSYS*|CYGWIN*|Windows_NT*)
		printf 'file:///%s\n' "$(cygpath -m "$1")"
		;;
	*) printf 'file://%s\n' "$1" ;;
	esac
}
SAMPLE_URI=$(uri_of_path "$SAMPLE")
MESSY_URI=$(uri_of_path "$MESSY")
BROKEN_URI=$(uri_of_path "$BROKEN")
UNSAVED_URI=$(uri_of_path "$UNSAVED")

# Declaration padding varies with the seed; the expected position follows
# the generated source, independently of the LSP reply.
WIDGET_LINE=$(grep -n '^def widget ' "$SAMPLE" | cut -d: -f1)
WIDGET_COL=5
DEF_LINE=$((WIDGET_LINE - 1))

{
	frame '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"processId":null,"rootUri":null,"capabilities":{}}}'
	frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$SAMPLE")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"textDocument/hover\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":$DEF_LINE,\"character\":$WIDGET_COL}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"textDocument/definition\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":$DEF_LINE,\"character\":$WIDGET_COL}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":8,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":$DEF_LINE,\"character\":7}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"textDocument/documentSymbol\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"}}}"
	frame '{"jsonrpc":"2.0","id":10,"method":"workspace/symbol","params":{"query":"widget"}}'
	frame "{\"jsonrpc\":\"2.0\",\"id\":11,\"method\":\"textDocument/prepareRename\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":$DEF_LINE,\"character\":$WIDGET_COL}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"textDocument/hover\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":0,\"character\":0}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$MESSY_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$MESSY")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"textDocument/formatting\",\"params\":{\"textDocument\":{\"uri\":\"$MESSY_URI\"},\"options\":{\"tabSize\":4,\"insertSpaces\":true}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$BROKEN_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$BROKEN")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$BROKEN_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"$(json_text "$BROKEN")\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didSave\",\"params\":{\"textDocument\":{\"uri\":\"$BROKEN_URI\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$UNSAVED_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$UNSAVED")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$UNSAVED_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"$(json_text "$BROKEN")\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didClose\",\"params\":{\"textDocument\":{\"uri\":\"$BROKEN_URI\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":6,\"method\":\"textDocument/rename\",\"params\":{\"textDocument\":{\"uri\":\"$SAMPLE_URI\"},\"position\":{\"line\":$DEF_LINE,\"character\":$WIDGET_COL},\"newName\":\"widget2\"}}"
	frame '{"jsonrpc":"2.0","id":7,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/session.in"

set +e
OURO_ROOT="$ROOT" "$LSP" <"$OUT/session.in" >"$OUT/session.out" 2>"$OUT/session.err"
status=$?
set -e

if [ "$status" -eq 0 ]; then
	ok "exit status=0 after shutdown"
else
	bad exit "status=$status"
	tail -n 5 "$OUT/session.err" >&2
fi
if [ -s "$OUT/session.err" ]; then
	bad stderr "$(head -n 1 "$OUT/session.err")"
else
	ok "stderr empty"
fi

# Replies are one long line each; split them so a grep cannot match across two.
tr '\r' '\n' <"$OUT/session.out" | grep '^{' >"$OUT/session.jsonl" || true

want() {
	if grep -q -- "$2" "$OUT/session.jsonl"; then
		ok "$1"
	else
		bad "$1" "missing: $2"
	fi
}

want framing '"jsonrpc":"2.0"'
want capabilities '"documentFormattingProvider":true'
want capabilities-completion '"completionProvider":true'
want capabilities-document-symbol '"documentSymbolProvider":true'
want capabilities-workspace-symbol '"workspaceSymbolProvider":true'
want capabilities-rename '"renameProvider":true'
want diagnostics-clean "\"uri\":\"$SAMPLE_URI\",\"diagnostics\":\[\]"
# Literal JSON needle; backslashes must not expand.
# shellcheck disable=SC2016
want hover-signature '"id":2,"result":{"contents":{"kind":"markdown","value":"```ouro\\ndef widget (n : Nat) : Nat\\n```'
want hover-doc 'Doubles a natural'
want definition-line "\"id\":3,\"result\":{\"uri\":\"$SAMPLE_URI\",\"range\":{\"start\":{\"line\":$DEF_LINE,"
want completion-widget '"id":8,"result":'
want completion-label '"label":"widget"'
want completion-prefix '"label":"widget_zero"'
want document-symbol '"id":9,"result":\['
want document-symbol-widget '"name":"widget"'
want workspace-symbol '"id":10,"result":\['
want workspace-symbol-widget '"name":"widget"'
want prepare-rename '"id":11,"result":{"start"'
want hover-miss '"id":4,"result":null'
want formatting-strips-trailing-ws '"newText":".*def messy : Nat := add (S Z) Z;\\n"'
want diagnostics-error "\"uri\":\"$BROKEN_URI\",\"diagnostics\":\[{\"range\""
want diagnostics-severity '"severity":1,"code":"CHECK_FAIL"'
# Open, change, and save each re-run check; then close clears.
broken_fail=$(grep -c -- "\"uri\":\"$BROKEN_URI\",\"diagnostics\":\[{\"range\"" "$OUT/session.jsonl" || true)
if [ "$broken_fail" -ge 3 ]; then
	ok "diagnostics-on-save"
else
	bad "diagnostics-on-save" "CHECK_FAIL publishes=$broken_fail want>=3"
fi
if grep -q -- "\"uri\":\"$UNSAVED_URI\",\"diagnostics\":\[{\"range\"" "$OUT/session.jsonl"; then
	ok "diagnostics-on-change"
else
	bad "diagnostics-on-change" "unsaved buffer CHECK_FAIL missing"
fi
want diagnostics-cleared-on-close "\"uri\":\"$BROKEN_URI\",\"diagnostics\":\[\]"
want rename-edit "\"id\":6,\"result\":{\"changes\":{\"$SAMPLE_URI\""
want rename-widget2 widget2
want shutdown '"id":7,"result":null'

# The formatter must not leave the trailing blank it was asked to remove.
if grep -q 'Z;   ' "$OUT/session.jsonl"; then
	bad formatting "trailing whitespace survived"
else
	ok "formatting removed trailing whitespace"
fi

# A document root is launch-authorized. Relative traversal, absolute imports,
# and non-file URIs must never enter the symbol index.
ATTACK_ROOT="$OUT/attack-root"
ATTACK_BUILD="$ATTACK_ROOT/_build"
mkdir -p "$ATTACK_BUILD"
OUTSIDE="$OUT/outside.ouro"
ATTACK_DOC="$ATTACK_ROOT/main.ouro"
printf -- 'def secret_outside : Nat := Z;\n' >"$OUTSIDE"
printf -- 'import "../outside.ouro";\n\ndef local : Nat := secret\n' >"$ATTACK_DOC"
ATTACK_URI=$(uri_of_path "$ATTACK_DOC")
OUTSIDE_HOST="$OUTSIDE"
case "$(uname -s 2>/dev/null || echo unknown)" in
MINGW*|MSYS*|CYGWIN*|Windows_NT*) OUTSIDE_HOST=$(cygpath -m "$OUTSIDE") ;;
esac
{
	frame '{"jsonrpc":"2.0","id":100,"method":"initialize","params":{"capabilities":{}}}'
	frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$ATTACK_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":101,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\"},\"position\":{\"line\":2,\"character\":25}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"import \\\"$OUTSIDE_HOST\\\";\\n\\ndef local : Nat := secret\\n\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":102,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\"},\"position\":{\"line\":2,\"character\":25}}}"
	frame '{"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":"untitled:outside","languageId":"ouro","version":1,"text":"secret"}}}'
	frame '{"jsonrpc":"2.0","id":103,"method":"textDocument/completion","params":{"textDocument":{"uri":"untitled:outside"},"position":{"line":0,"character":6}}}'
	frame '{"jsonrpc":"2.0","id":104,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/attack.in"
set +e
OURO_ROOT="$ATTACK_ROOT" OURO_LSP_OURO1=/dev/null \
	"$LSP" <"$OUT/attack.in" >"$OUT/attack.out" 2>"$OUT/attack.err"
attack_status=$?
set -e
tr '\r' '\n' <"$OUT/attack.out" | grep '^{' >"$OUT/attack.jsonl" || true
if [ "$attack_status" -eq 0 ]; then
	ok "workspace attack session exits after shutdown"
else
	bad workspace-attack-exit "status=$attack_status"
fi
if grep -q 'secret_outside' "$OUT/attack.jsonl"; then
	bad workspace-containment "external declaration disclosed"
else
	ok "workspace traversal and absolute imports hidden"
fi
want_attack() {
	if grep -q -- "$2" "$OUT/attack.jsonl"; then
		ok "$1"
	else
		bad "$1" "missing: $2"
	fi
}
want_attack traversal-completion-empty '"id":101,"result":\[\]'
want_attack absolute-completion-empty '"id":102,"result":\[\]'
want_attack non-file-uri-empty '"id":103,"result":\[\]'

# Oversized framing is rejected from the header, and a valid value one level
# beyond the JSON nesting budget receives a parse error without killing the
# subsequent shutdown handshake.
set +e
printf 'Content-Length: 1048577\r\n\r\n' | OURO_ROOT="$ROOT" "$LSP" \
	>"$OUT/oversize.out" 2>"$OUT/oversize.err"
oversize_status=$?
set -e
if [ "$oversize_status" -eq 1 ] && [ ! -s "$OUT/oversize.out" ] && [ ! -s "$OUT/oversize.err" ]; then
	ok "oversized frame rejected before body read"
else
	bad oversized-frame "status=$oversize_status stdout=$(wc -c <"$OUT/oversize.out") stderr=$(wc -c <"$OUT/oversize.err")"
fi
DEEP=$(awk 'BEGIN { for (i=0;i<129;i++) printf "["; printf "0"; for (i=0;i<129;i++) printf "]" }')
{
	frame "$DEEP"
	frame '{"jsonrpc":"2.0","id":105,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/deep.in"
set +e
OURO_ROOT="$ROOT" "$LSP" <"$OUT/deep.in" >"$OUT/deep.out" 2>"$OUT/deep.err"
deep_status=$?
set -e
if [ "$deep_status" -eq 0 ] && grep -q '"code":-32700' "$OUT/deep.out"; then
	ok "deep JSON rejected and server stayed responsive"
else
	bad deep-json "status=$deep_status"
fi

# The frame stays below 1 MiB, but its full-sync document exceeds the retained
# 512 KiB limit. This also exercises a long JSON string through the linear
# byte cursor and proves the server remains responsive afterwards.
BIG_DOC="$ATTACK_ROOT/big.ouro"
awk 'BEGIN { for (i=0;i<540000;i++) printf "a"; printf "\n" }' >"$BIG_DOC"
BIG_URI=$(uri_of_path "$BIG_DOC")
{
	frame '{"jsonrpc":"2.0","id":106,"method":"initialize","params":{"capabilities":{}}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$BIG_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$BIG_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":107,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$BIG_URI\"},\"position\":{\"line\":0,\"character\":1}}}"
	frame '{"jsonrpc":"2.0","id":108,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/big.in"
set +e
OURO_ROOT="$ATTACK_ROOT" OURO_LSP_OURO1=/dev/null \
	"$LSP" <"$OUT/big.in" >"$OUT/big.out" 2>"$OUT/big.err"
big_status=$?
set -e
if [ "$big_status" -eq 0 ] && grep -q '"id":107,"result":\[\]' "$OUT/big.out"; then
	ok "over-limit document rejected after bounded linear JSON parse"
else
	bad document-limit "status=$big_status"
fi

if find "$ROOT/_build" "$ATTACK_BUILD" -maxdepth 1 -type f -name 'ouro_tmp_*' -print -quit | grep -q .; then
	bad scratch-cleanup "unique LSP scratch remains"
else
	ok "unique LSP scratch cleaned after success and failure"
fi
if grep -q 'ouro-lsp-format\.ouro\|ouro-lsp-buf\.ouro' tools/lsp.ouro; then
	bad fixed-scratch "fixed scratch name remains in LSP source"
else
	ok "fixed scratch names removed"
fi

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite lsp \
		--receipt "$OUT/native-candidates.json" --verify
fi

if [ "$fail" -ne 0 ]; then
	echo "LSP_SUITE: FAIL rows=$rows failures=$fail out=$OUT" >&2
	exit 1
fi
echo "LSP_SUITE: PASS rows=$rows out=$OUT"
exit 0
