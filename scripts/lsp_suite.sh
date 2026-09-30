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
# file:// URIs sent to the server must be absolute; uri_file_path drops relative paths.
OUT=$(CDPATH='' cd "$OUT" && pwd)

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
	FMT="$OUT/ouro-fmt"
	sh "$ROOT/scripts/build_tool.sh" tools/fmt.ouro "$FMT" >"$OUT/fmt.build.log" 2>&1 || {
		echo "LSP_SUITE: FAIL formatter build" >&2
		tail -n 20 "$OUT/fmt.build.log" >&2
		exit 1
	}
	OURO_HOSTED_COMPILER_WRAPPER="$ROOT/scripts/ouro1.sh"
	OURO_HOSTED_FMT="$FMT"
	export OURO_HOSTED_COMPILER_WRAPPER OURO_HOSTED_FMT
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
	"$PYTHON" -c 'import json, pathlib, sys
text = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
sys.stdout.write(json.dumps(text, ensure_ascii=False)[1:-1])' "$1"
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
want hover-signature '"id":2,"result":{"contents":{"kind":"markdown","value":"```ouro\\ndef widget (n : Nat)\\n    : Nat\\n```'
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

# A direct annotated definition can offer nullary constructors from a local
# family. A constructor with a value field, another family, or a nested
# expression must not become an expected-type suggestion.
CTOR_DOC="$OUT/constructors.ouro"
STRING_REL=$("$PYTHON" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]).replace("\\", "/"))' "$ROOT/std/string.ouro" "$OUT")
printf 'import "%s";\n' "$STRING_REL" >"$CTOR_DOC"
cat >>"$CTOR_DOC" <<'EOF'
inductive LspChoice : Type := | LspRed : LspChoice | LspWrap : LspChoice -> LspChoice | LspBlue : LspChoice;
inductive LspOther : Type := | LspOrange : LspOther;
def chosen : LspChoice := LspRed;
def other : LspOther := LspOrange;
def nested : LspChoice := let picked : LspChoice := LspRed in picked;
def commented : LspChoice := -- Lsp
  LspRed;
def quoted : String := "
def fakeQuoted : LspChoice := Lsp
";
def raw : String := r#"
def fakeRaw : LspChoice := Lsp
"#;
EOF
CTOR_URI=$(uri_of_path "$CTOR_DOC")
CHOICE_PREFIX='def chosen : LspChoice := Lsp'
OTHER_PREFIX='def other : LspOther := Lsp'
NESTED_PREFIX='def nested : LspChoice := let picked : LspChoice := Lsp'
COMMENT_PREFIX='def commented : LspChoice := -- Lsp'
QUOTED_PREFIX='def fakeQuoted : LspChoice := Lsp'
RAW_PREFIX='def fakeRaw : LspChoice := Lsp'
DUP_DOC="$OUT/duplicate-constructors.ouro"
cat >"$DUP_DOC" <<'EOF'
inductive LspDuplicate : Type := | LspSame : LspDuplicate | LspSame : LspDuplicate;
def duplicate : LspDuplicate := LspSame;
EOF
DUP_URI=$(uri_of_path "$DUP_DOC")
DUP_PREFIX='def duplicate : LspDuplicate := LspS'
ADJ_DOC="$OUT/adjacent-constructors.ouro"
printf 'inductive LspAdjacent : Type := | LspOnly : LspAdjacent;\ndef\tadjacent : LspAdjacent := LspOnly;\ndef untyped := LspOnly;\n' >"$ADJ_DOC"
ADJ_URI=$(uri_of_path "$ADJ_DOC")
ADJ_PREFIX=$(printf 'def\tadjacent : LspAdjacent := Lsp')
UNTYPED_PREFIX='def untyped := Lsp'
LARGE_DOC="$OUT/large-constructors.ouro"
{
	printf 'inductive LspLarge : Type := '
	arm=1
	while [ "$arm" -le 128 ]; do
		printf '| LspArm%s : LspLarge ' "$arm"
		arm=$((arm + 1))
	done
	printf ';\ndef large : LspLarge := LspArm128;\n'
	printf 'inductive LspBoundary : Type := '
	arm=1
	while [ "$arm" -le 256 ]; do
		printf '| LspBoundaryArm%s : LspBoundary ' "$arm"
		arm=$((arm + 1))
	done
	printf ';\ndef boundary : LspBoundary := LspBoundaryArm256;\n'
	printf 'inductive LspOver : Type := '
	arm=1
	while [ "$arm" -le 257 ]; do
		printf '| LspOverArm%s : LspOver ' "$arm"
		arm=$((arm + 1))
	done
	printf ';\ndef over : LspOver := LspOverArm257;\n'
} >"$LARGE_DOC"
LARGE_URI=$(uri_of_path "$LARGE_DOC")
LARGE_PREFIX='def large : LspLarge := LspArm128'
BOUNDARY_PREFIX='def boundary : LspBoundary := LspBoundaryArm256'
OVER_PREFIX='def over : LspOver := LspOverArm257'
{
	frame '{"jsonrpc":"2.0","id":300,"method":"initialize","params":{"capabilities":{}}}'
	frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$CTOR_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":301,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":3,\"character\":${#CHOICE_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":302,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":4,\"character\":${#OTHER_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":303,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":5,\"character\":${#NESTED_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":305,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":6,\"character\":${#COMMENT_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":306,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":9,\"character\":${#QUOTED_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":307,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$CTOR_URI\"},\"position\":{\"line\":12,\"character\":${#RAW_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$DUP_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$DUP_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":308,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$DUP_URI\"},\"position\":{\"line\":1,\"character\":${#DUP_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$ADJ_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$ADJ_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":304,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ADJ_URI\"},\"position\":{\"line\":1,\"character\":${#ADJ_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":313,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ADJ_URI\"},\"position\":{\"line\":2,\"character\":${#UNTYPED_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$LARGE_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$LARGE_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":309,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$LARGE_URI\"},\"position\":{\"line\":1,\"character\":${#LARGE_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":310,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$LARGE_URI\"},\"position\":{\"line\":3,\"character\":${#BOUNDARY_PREFIX}}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":311,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$LARGE_URI\"},\"position\":{\"line\":5,\"character\":${#OVER_PREFIX}}}}"
	frame '{"jsonrpc":"2.0","id":314,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/constructors.in"
set +e
OURO_ROOT="$ROOT" "$LSP" <"$OUT/constructors.in" >"$OUT/constructors.out" 2>"$OUT/constructors.err"
ctor_status=$?
set -e
tr '\r' '\n' <"$OUT/constructors.out" | grep '^{' >"$OUT/constructors.jsonl" || true
if [ "$ctor_status" -eq 0 ] && [ ! -s "$OUT/constructors.err" ]; then
	ok "constructor completion session exits cleanly"
else
	bad constructor-session "status=$ctor_status"
fi
choice_result=$(grep -F '"id":301,"result":' "$OUT/constructors.jsonl" || true)
other_result=$(grep -F '"id":302,"result":' "$OUT/constructors.jsonl" || true)
nested_result=$(grep -F '"id":303,"result":' "$OUT/constructors.jsonl" || true)
comment_result=$(grep -F '"id":305,"result":' "$OUT/constructors.jsonl" || true)
quoted_result=$(grep -F '"id":306,"result":' "$OUT/constructors.jsonl" || true)
raw_result=$(grep -F '"id":307,"result":' "$OUT/constructors.jsonl" || true)
duplicate_result=$(grep -F '"id":308,"result":' "$OUT/constructors.jsonl" || true)
adjacent_result=$(grep -F '"id":304,"result":' "$OUT/constructors.jsonl" || true)
untyped_result=$(grep -F '"id":313,"result":' "$OUT/constructors.jsonl" || true)
large_result=$(grep -F '"id":309,"result":' "$OUT/constructors.jsonl" || true)
boundary_result=$(grep -F '"id":310,"result":' "$OUT/constructors.jsonl" || true)
over_result=$(grep -F '"id":311,"result":' "$OUT/constructors.jsonl" || true)
case "$choice_result" in
	*'"label":"LspRed","kind":4'*'"label":"LspBlue","kind":4'*) ok "local nullary constructors match explicit type" ;;
	*) bad constructor-choice "missing LspRed or LspBlue" ;;
esac
case "$choice_result" in
	*'"label":"LspWrap"'*) bad constructor-arity "non-nullary constructor suggested" ;;
	*) ok "constructor with a value field is omitted" ;;
esac
case "$other_result" in
	*'"label":"LspOrange","kind":4'*) ok "other family suggests its own constructor" ;;
	*) bad constructor-other "missing LspOrange" ;;
esac
case "$other_result" in
	*'"label":"LspRed"'* | *'"label":"LspBlue"'*) bad constructor-family "wrong-family constructor suggested" ;;
	*) ok "other family excludes LspChoice constructors" ;;
esac
case "$nested_result" in
	*'"kind":4'*) bad constructor-nested "nested expression acquired a direct result type" ;;
	*'"label":"LspChoice"'*) ok "nested expression keeps ordinary prefix completion" ;;
	*) bad constructor-nested "ordinary prefix completion missing" ;;
esac
case "$adjacent_result" in
	*'"label":"LspOnly","kind":4'*) ok "adjacent family and tab-separated def use the LSP line" ;;
	*) bad constructor-adjacent "adjacent constructor missing" ;;
esac
for response in "$comment_result" "$quoted_result" "$raw_result" "$duplicate_result" "$untyped_result"; do
	case "$response" in
		*'"result":'*)
			case "$response" in
				*'"kind":4'*) bad constructor-context "constructor suggested in comment, string, duplicate family, or unannotated def" ;;
				*) ok "unsupported context omits constructor hint" ;;
			esac ;;
		*) bad constructor-context "completion reply missing" ;;
	esac
done
case "$large_result" in
	*'"label":"LspArm128","kind":4'*) ok "large family keeps a late nullary constructor" ;;
	*) bad constructor-large "late constructor missing" ;;
esac
case "$boundary_result" in
	*'"label":"LspBoundaryArm256","kind":4'*) ok "exact arm budget keeps its last constructor" ;;
	*) bad constructor-boundary "constructor at exact arm budget missing" ;;
esac
case "$over_result" in
	*'"kind":4'*) bad constructor-budget "family beyond arm budget produced a hint" ;;
	*'"result":'*) ok "family beyond arm budget keeps ordinary completion" ;;
	*) bad constructor-budget "completion reply missing" ;;
esac

# A document root is launch-authorized. Relative traversal, absolute imports,
# and non-file URIs must never enter the symbol index.
ATTACK_ROOT="$OUT/attack-root"
ATTACK_BUILD="$ATTACK_ROOT/_build"
mkdir -p "$ATTACK_BUILD"
OUTSIDE="$OUT/outside.ouro"
ATTACK_DOC="$ATTACK_ROOT/main.ouro"
printf -- 'def allowed_name : Nat := Z;\n' >"$ATTACK_ROOT/allowed.ouro"
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
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\",\"version\":3},\"contentChanges\":[{\"text\":\"import \\\"allowed.ouro\\\", -- second path\\n \\\"../outside.ouro\\\",;\\n\\ndef local : Nat := secret\\n\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":109,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\"},\"position\":{\"line\":3,\"character\":25}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\",\"version\":4},\"contentChanges\":[{\"text\":\"import \\\"allowed.ouro\\\", \\\"$OUTSIDE_HOST\\\";\\n\\ndef local : Nat := secret\\n\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":110,\"method\":\"textDocument/completion\",\"params\":{\"textDocument\":{\"uri\":\"$ATTACK_URI\"},\"position\":{\"line\":2,\"character\":25}}}"
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
want_attack grouped-traversal-completion-empty '"id":109,"result":\[\]'
want_attack grouped-absolute-completion-empty '"id":110,"result":\[\]'

# Group operands all enter the index, including a decoded Unicode escape in
# an unsaved multiline group relocated to the private checker scratch file.
GROUP_DIR="$OUT/group-imports"
mkdir -p "$GROUP_DIR"
GROUP_LEFT="$GROUP_DIR/left.ouro"
GROUP_RIGHT="$GROUP_DIR/right.ouro"
GROUP_DOC="$GROUP_DIR/main.ouro"
GROUP_BUFFER="$GROUP_DIR/buffer.ouro"
printf -- 'inductive LspGroupNat : Type := | LspGroupZero : LspGroupNat;\n' >"$GROUP_LEFT"
printf -- 'import "left.ouro";\ndef lsp_group_right : LspGroupNat := LspGroupZero;\n' >"$GROUP_RIGHT"
printf -- 'import "left.ouro", "right.ouro";\n\ndef use_group : LspGroupNat := lsp_group_right;\n' >"$GROUP_DOC"
printf -- 'import -- first operand\n "left.ouro", -- second operand\n "\\u{72}ight.ouro",;\n\ndef use_group : LspGroupNat := lsp_group_right;\n' >"$GROUP_BUFFER"
GROUP_URI=$(uri_of_path "$GROUP_DOC")
GROUP_RIGHT_URI=$(uri_of_path "$GROUP_RIGHT")
{
	frame '{"jsonrpc":"2.0","id":200,"method":"initialize","params":{"capabilities":{}}}'
	frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$GROUP_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$GROUP_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$GROUP_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"$(json_text "$GROUP_BUFFER")\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":201,\"method\":\"textDocument/hover\",\"params\":{\"textDocument\":{\"uri\":\"$GROUP_URI\"},\"position\":{\"line\":4,\"character\":34}}}"
	frame "{\"jsonrpc\":\"2.0\",\"id\":202,\"method\":\"textDocument/definition\",\"params\":{\"textDocument\":{\"uri\":\"$GROUP_URI\"},\"position\":{\"line\":4,\"character\":34}}}"
	frame '{"jsonrpc":"2.0","id":203,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/group-imports.in"
set +e
OURO_ROOT="$ROOT" "$LSP" <"$OUT/group-imports.in" >"$OUT/group-imports.out" 2>"$OUT/group-imports.err"
group_status=$?
set -e
tr '\r' '\n' <"$OUT/group-imports.out" | grep '^{' >"$OUT/group-imports.jsonl" || true
if [ "$group_status" -eq 0 ] && [ ! -s "$OUT/group-imports.err" ]; then
	ok "group import session exits cleanly"
else
	bad group-import-session "status=$group_status"
fi
group_clean=$(grep -c -- "\"uri\":\"$GROUP_URI\",\"diagnostics\":\[\]" "$OUT/group-imports.jsonl" || true)
if [ "$group_clean" -eq 2 ]; then
	ok "inline and unsaved multiline group diagnostics are clean"
else
	bad group-import-diagnostics "clean publishes=$group_clean want=2"
fi
if grep -q '"id":201,"result":{"contents".*def lsp_group_right' "$OUT/group-imports.jsonl" &&
	grep -q "\"id\":202,\"result\":{\"uri\":\"$GROUP_RIGHT_URI\"" "$OUT/group-imports.jsonl"; then
	ok "second group operand supplies hover and definition"
else
	bad group-import-index "second dependency missing from hover or definition"
fi

# A dirty buffer must keep its diagnostics when some other .ouro file
# changes. The editor sends didChangeWatchedFiles for sibling saves; the
# server used to recheck the saved path and clear the unsaved error.
WATCH_DIR="$OUT/watch-root"
mkdir -p "$WATCH_DIR"
WATCH_CLEAN="$WATCH_DIR/dirty.ouro"
WATCH_BROKEN="$WATCH_DIR/watch-broken.ouro"
WATCH_OTHER="$WATCH_DIR/other.ouro"
printf -- 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n\ndef ok : Nat := Z;\n' >"$WATCH_CLEAN"
printf -- '-- @entry broken\n\ndef broken : Nat := no_such_name Z;\n' >"$WATCH_BROKEN"
printf -- 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n\ndef other : Nat := Z;\n' >"$WATCH_OTHER"
WATCH_URI=$(uri_of_path "$WATCH_CLEAN")
WATCH_OTHER_URI=$(uri_of_path "$WATCH_OTHER")
{
	frame '{"jsonrpc":"2.0","id":300,"method":"initialize","params":{"capabilities":{}}}'
	frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$WATCH_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$WATCH_CLEAN")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$WATCH_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"$(json_text "$WATCH_BROKEN")\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"workspace/didChangeWatchedFiles\",\"params\":{\"changes\":[{\"uri\":\"$WATCH_OTHER_URI\",\"type\":2}]}}"
	frame '{"jsonrpc":"2.0","id":301,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/watch.in"
set +e
OURO_ROOT="$ROOT" "$LSP" <"$OUT/watch.in" >"$OUT/watch.out" 2>"$OUT/watch.err"
watch_status=$?
set -e
tr '\r' '\n' <"$OUT/watch.out" | grep '^{' >"$OUT/watch.jsonl" || true
if [ "$watch_status" -eq 0 ]; then
	ok "watch session exits after shutdown"
else
	bad watch-exit "status=$watch_status"
fi
watch_fail=$(grep -c -- "\"uri\":\"$WATCH_URI\",\"diagnostics\":\[{\"range\"" "$OUT/watch.jsonl" || true)
if [ "$watch_fail" -ge 2 ]; then
	ok "diagnostics-on-watch-keep-unsaved"
else
	bad "diagnostics-on-watch-keep-unsaved" "CHECK_FAIL publishes=$watch_fail want>=2"
fi
# The last publish for the dirty URI must still be the buffer error, not
# a disk-clean wipe.
watch_last=$(grep -- "\"uri\":\"$WATCH_URI\",\"diagnostics\":" "$OUT/watch.jsonl" | tail -n 1 || true)
case "$watch_last" in
*"\"diagnostics\":[]"*)
	bad "diagnostics-on-watch-last" "final publish cleared unsaved CHECK_FAIL"
	;;
*"\"diagnostics\":[{\"range\""*)
	ok "diagnostics-on-watch-last"
	;;
*)
	bad "diagnostics-on-watch-last" "missing final publish"
	;;
esac

# An authorized document can fail scratch creation before invoking the checker.
# The failure must stay visible through open/change, followed by a normal close.
SCRATCH_ROOT=$(mktemp -d "$OUT/no-scratch-XXXXXX")
SCRATCH_DOC="$SCRATCH_ROOT/main.ouro"
printf 'inductive Nat : Type := | Z : Nat;\ndef good : Nat := Z;\n' >"$SCRATCH_DOC"
SCRATCH_URI=$(uri_of_path "$SCRATCH_DOC")
{
	frame '{"jsonrpc":"2.0","id":109,"method":"initialize","params":{"capabilities":{}}}'
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didOpen\",\"params\":{\"textDocument\":{\"uri\":\"$SCRATCH_URI\",\"languageId\":\"ouro\",\"version\":1,\"text\":\"$(json_text "$SCRATCH_DOC")\"}}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didChange\",\"params\":{\"textDocument\":{\"uri\":\"$SCRATCH_URI\",\"version\":2},\"contentChanges\":[{\"text\":\"$(json_text "$BROKEN")\"}]}}"
	frame "{\"jsonrpc\":\"2.0\",\"method\":\"textDocument/didClose\",\"params\":{\"textDocument\":{\"uri\":\"$SCRATCH_URI\"}}}"
	frame '{"jsonrpc":"2.0","id":110,"method":"shutdown","params":{}}'
	frame '{"jsonrpc":"2.0","method":"exit"}'
} >"$OUT/scratch-failure.in"
set +e
OURO_ROOT="$SCRATCH_ROOT" "$LSP" <"$OUT/scratch-failure.in" \
	>"$OUT/scratch-failure.out" 2>"$OUT/scratch-failure.err"
scratch_status=$?
set -e
if [ "$scratch_status" -eq 0 ] && [ ! -s "$OUT/scratch-failure.err" ] &&
	"$PYTHON" - "$OUT/scratch-failure.out" "$SCRATCH_URI" <<'PY'
import json, pathlib, sys
messages = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.startswith("{")]
publications = [m["params"]["diagnostics"] for m in messages
                if m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == sys.argv[2]]
assert len(publications) == 3, publications
for diagnostics in publications[:2]:
    assert len(diagnostics) == 1, diagnostics
    assert diagnostics[0]["code"] == "TOOL_ERROR", diagnostics
    assert diagnostics[0]["severity"] == 1, diagnostics
    assert diagnostics[0]["message"] == "could not create checker scratch file", diagnostics
assert publications[2] == [], publications
assert any(m.get("id") == 110 and m.get("result", "missing") is None for m in messages), messages
PY
then
	ok "scratch creation failure remains a tool diagnostic until close"
else
	bad scratch-failure "status=$scratch_status or unexpected diagnostic protocol"
fi

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
