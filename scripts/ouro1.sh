#!/usr/bin/env sh
# check/collect use Ouro ouro-collect, not C collect_post.
# User-facing multiplexer; hot paths use a tiny shell config reader and leave full cache policy to ouro_build.py.

set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT="${OURO_ROOT:-}"
if [ -z "$ROOT" ]; then
	ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
fi
# Python/ci_gate on Windows export I:\... ; compile_units match-fails if
# that string is compared to a cygpath-unix file prefix.
if command -v cygpath >/dev/null 2>&1; then
	case "$ROOT" in
	[A-Za-z]:*) ROOT=$(cygpath -u "$ROOT") ;;
	esac
fi
ROOT=$(printf '%s\n' "$ROOT" | tr "\\\\" '/')
OLDPWD_OURO=$(pwd)
cd "$ROOT"
export OURO_ROOT="$ROOT"

usage() {
	printf '%s\n' "usage:" "  ouro1 <file.ouro> [fuel] [--module SUF] [--unit PATH]..." \
		"  ouro1 check FILE [fuel] [--emit-checked-program FILE]" "  ouro1 collect FILE" \
		"  ouro1 eval FILE (--eval EXPR | --print NAME) [--type TYPE]" \
		"  ouro1 rebuild" "  ouro1 analyze [--strict] [--dump-facts] [--enable-FAMILY|--enable-style|--enable-light|--enable-heavy|--enable-all] [--scope PATH]..." \
		"  ouro1 lint [PATH...]" \
		"  ouro1 fmt [--check | --write] FILE..." \
		"  ouro1 fix [--check | --write] FILE..." \
		"  ouro1 pkg (init | add NAME | remove NAME | install | lock | update | list | verify)" \
		"  ouro1 test [PATH...]" \
		"  ouro1 doc [--check] [--out DIR] FILE..." \
		"  ouro1 lsp   (language server on stdio)" \
		"  ouro1 build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" \
		"  ouro1 build [--profile dev|release]" "  ouro1 run FILE.ouro" \
		"  ouro1 cache status|clean" "  ouro1 config show"
}

cmd=${1:-}
case "$cmd" in
	build|cache|config|clean)
		program_build=0
		if [ "$cmd" = build ]; then
			for arg do
				case "$arg" in
				*.ouro) program_build=1 ;;
				esac
			done
		fi
		if [ "$program_build" -eq 0 ]; then
			shift
			# shellcheck source=scripts/python.sh
			. "$ROOT/scripts/python.sh"
			if [ -z "${PYTHON:-}" ]; then
				echo "OURO1: FAIL no working Python for $cmd" >&2
				exit 127
			fi
			exec "$PYTHON" "$ROOT/scripts/ouro_build.py" "$cmd" "$@"
		fi
		;;
	-h|--help|help)
		usage
		exit 2
		;;
esac

# Hot check/eval/analyze invocations should not pay Python startup just to find
# the C tool directory.  Keep this shell parser intentionally tiny: it only
# reads the simple scalar c_out / c_build_dir shape used by Ouro.seal. Full
# validation, CLI overrides, ccache, and cache policy remain owned by
# ouro_build.py.
cfg_c_build_dir() {
	[ -f "$ROOT/Ouro.seal" ] || return 0
	awk '
	function trim(s) { sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
	{
		line = $0; out = ""; quote = ""
		for (i = 1; i <= length(line); i++) {
			ch = substr(line, i, 1)
			if ((ch == "\"" || ch == "\047") && quote == "") quote = ch
			else if (ch == quote) quote = ""
			if (ch == "#" && quote == "") break
			if (ch == "-" && quote == "" && i < length(line) && substr(line, i + 1, 1) == "-") break
			out = out ch
		}
		if (out ~ /^[[:space:]]*(c_out|c_build_dir)[[:space:]]*=/) {
			sub(/^[^=]*=/, "", out); out = trim(out)
			if ((substr(out, 1, 1) == "\"" && substr(out, length(out), 1) == "\"") ||
			    (substr(out, 1, 1) == "\047" && substr(out, length(out), 1) == "\047")) {
				out = substr(out, 2, length(out) - 2)
			}
			print out; exit
		}
	}' "$ROOT/Ouro.seal"
}

make_abs() {
	case "$1" in
		/*) printf '%s\n' "$1" ;;
		[A-Za-z]:*)
			# Python on Windows exports OURO_C_BUILD_DIR as I:\path.
			# A leading drive letter is already absolute; do not prefix ROOT.
			printf '%s\n' "$1" | tr "\\\\" '/'
			;;
		*) printf '%s/%s\n' "$ROOT" "$1" ;;
	esac
}

C_BUILD_DIR=${OURO_C_BUILD_DIR:-}
if [ -z "$C_BUILD_DIR" ]; then
	C_BUILD_DIR=$(cfg_c_build_dir)
fi
if [ -z "$C_BUILD_DIR" ]; then
	C_BUILD_DIR="_build/c"
fi
C_BUILD_DIR=$(make_abs "$C_BUILD_DIR")
export OURO_C_BUILD_DIR="$C_BUILD_DIR"

COMPILER="${OURO1_COMPILER:-$C_BUILD_DIR/ouro1}"
[ -x "$COMPILER" ] || COMPILER="$ROOT/_build/ouro1"
if [ ! -x "$COMPILER" ]; then
	sh "$ROOT/scripts/bootstrap.sh"
	C_BUILD_DIR="${OURO_C_BUILD_DIR:-$C_BUILD_DIR}"
	COMPILER="${OURO1_COMPILER:-$C_BUILD_DIR/ouro1}"
	[ -x "$COMPILER" ] || COMPILER="$ROOT/_build/ouro1"
fi
# gcc -o ouro1 writes ouro1.exe. Prefer that PE so Git Bash does not exec an
# unsuffixed image (exit 127 after a long check).
if [ -z "${OURO1_COMPILER:-}" ] && [ -x "${COMPILER}.exe" ]; then
	COMPILER="${COMPILER}.exe"
elif [ -z "${OURO1_COMPILER:-}" ] && [ -x "$C_BUILD_DIR/ouro1.exe" ]; then
	COMPILER="$C_BUILD_DIR/ouro1.exe"
fi

ensure_collect() {
	COLLECT="$C_BUILD_DIR/ouro-collect"
	# Windows gcc -o ouro-collect writes ouro-collect.exe and can leave a
	# host-shim script in the un-suffixed name. ouro1 check/collect must
	# use the native collector (`collect_units: import cycle`), not
	# frontend_regen via host_tools.py.
	if [ -f "$COLLECT" ] && [ "$(wc -c <"$COLLECT")" -lt 4096 ]; then
		case "$(head -n 1 "$COLLECT" 2>/dev/null)" in
		'#!'*) rm -f "$COLLECT" ;;
		esac
	fi
	if [ -x "$C_BUILD_DIR/ouro-collect.exe" ]; then
		COLLECT="$C_BUILD_DIR/ouro-collect.exe"
	fi
	if [ ! -x "$COLLECT" ] || [ -n "$(find "$ROOT/tools/collect.ouro" \
		-newer "$COLLECT" -print -quit 2>/dev/null)" ]; then
		mkdir -p "$C_BUILD_DIR"
		# Keep successful bootstrap output out of the check/collect protocol.
		# Failed builds retain their complete diagnostics on stderr.
		if ! OURO_BUILD_TOOL_MODE=native \
			sh "$ROOT/scripts/build_tool.sh" tools/collect.ouro \
			"$C_BUILD_DIR/ouro-collect" >"$C_BUILD_DIR/ouro-collect.build.log" 2>&1; then
			cat "$C_BUILD_DIR/ouro-collect.build.log" >&2
			return 1
		fi
		if [ -x "$C_BUILD_DIR/ouro-collect.exe" ]; then
			COLLECT="$C_BUILD_DIR/ouro-collect.exe"
		else
			COLLECT="$C_BUILD_DIR/ouro-collect"
		fi
	fi
}

ensure_native_build() {
	NATIVE_BUILD="$C_BUILD_DIR/ouro-native-build"
	if [ -f "$NATIVE_BUILD" ] && [ "$(wc -c <"$NATIVE_BUILD")" -lt 4096 ]; then
		case "$(head -n 1 "$NATIVE_BUILD" 2>/dev/null)" in
		'#!'*) rm -f "$NATIVE_BUILD" ;;
		esac
	fi
	if [ -x "$C_BUILD_DIR/ouro-native-build.exe" ]; then
		NATIVE_BUILD="$C_BUILD_DIR/ouro-native-build.exe"
	fi
		if [ ! -x "$NATIVE_BUILD" ] || [ -n "$(find "$ROOT/tools/native_build.ouro" \
		"$ROOT/tools/native_build_args.ouro" \
		"$ROOT/tools/collect_core.ouro" \
		"$ROOT/compiler/native/lower_source.ouro" \
		"$ROOT/compiler/native/managed_stdio_compile.ouro" \
		"$ROOT/compiler/native/diagnostics.ouro" \
		-newer "$NATIVE_BUILD" -print -quit 2>/dev/null)" ]; then
		mkdir -p "$C_BUILD_DIR"
		if ! OURO_BUILD_TOOL_MODE=native \
			sh "$ROOT/scripts/build_tool.sh" tools/native_build.ouro \
			"$C_BUILD_DIR/ouro-native-build" 60000 \
			>"$C_BUILD_DIR/ouro-native-build.build.log" 2>&1; then
			cat "$C_BUILD_DIR/ouro-native-build.build.log" >&2
			return 1
		fi
		if [ -x "$C_BUILD_DIR/ouro-native-build.exe" ]; then
			NATIVE_BUILD="$C_BUILD_DIR/ouro-native-build.exe"
		else
			NATIVE_BUILD="$C_BUILD_DIR/ouro-native-build"
		fi
	fi
}

# Host collect on Windows may emit CRLF. IFS splitting must not keep CR in paths.
collect_unit_lines() {
	_units=$("$COLLECT" "$1") || return 1
	printf '%s\n' "$_units" | tr -d '\r'
}

# compile_units match-fails if the root is absolute under ROOT while units are
# repo-relative. Keep the same spelling as `ouro1 check`.
normalize_ouro_source() {
	_src=$1
	if command -v cygpath >/dev/null 2>&1; then
		case "$_src" in
		[A-Za-z]:*) _src=$(cygpath -u "$_src") ;;
		esac
	fi
	_src=$(printf '%s\n' "$_src" | tr "\\\\" '/')
	case "$_src" in
	"$ROOT"/*) _src=${_src#"$ROOT"/} ;;
	esac
	printf '%s\n' "$_src"
}

native_build_program() {
	_root=$(normalize_ouro_source "$1")
	_out=$2
	"$NATIVE_BUILD" "$_root" "$_out"
}

case "$cmd" in
	eval)
		shift
		file=""
		expr=""
		print=""
		eval_type="Nat"
		fuel="2000"
		while [ $# -gt 0 ]; do
			case "$1" in
				--eval)
					[ $# -ge 2 ] || { echo "EVAL_FAIL: require exactly one of --eval / --print" >&2; exit 2; }
					expr=$2
					shift 2
					;;
				--print)
					[ $# -ge 2 ] || { echo "EVAL_FAIL: require exactly one of --eval / --print" >&2; exit 2; }
					print=$2
					shift 2
					;;
				--fuel)
					[ $# -ge 2 ] || { echo "EVAL_FAIL: extra argument" >&2; exit 2; }
					fuel=$2
					shift 2
					;;
				--type)
					[ $# -ge 2 ] || { echo "EVAL_FAIL: --type requires a type" >&2; exit 2; }
					eval_type=$2
					shift 2
					;;
				-*)
					echo "EVAL_FAIL: extra argument" >&2
					exit 2
					;;
				*)
					if [ -n "$file" ]; then
						echo "EVAL_FAIL: extra argument" >&2
						exit 2
					fi
					file=$1
					shift
					;;
			esac
		done
		if [ -z "$file" ]; then
			echo "usage: ouro1 eval FILE (--eval EXPR | --print NAME) [--type TYPE]" >&2
			exit 2
		fi
		if [ -n "$expr" ] && [ -n "$print" ]; then
			echo "EVAL_FAIL: require exactly one of --eval / --print" >&2
			exit 2
		fi
		if [ -z "$expr" ] && [ -z "$print" ]; then
			echo "EVAL_FAIL: require exactly one of --eval / --print" >&2
			exit 2
		fi
		if [ ! -f "$file" ]; then
			echo "EVAL_FAIL: missing $file" >&2
			exit 2
		fi
		body=${print:-$expr}
		dir=$(dirname "$file")
		wrap="$dir/.ouro_eval_wrap_$$.ouro"
		trap 'rm -f "$wrap"' EXIT
		{
			cat "$file"
			printf '\n\ndef __ouro_eval : %s := %s;\n' "$eval_type" "$body"
		} >"$wrap"
		ensure_collect
		units=$(collect_unit_lines "$wrap") || {
			echo "EVAL_FAIL $file: front end rejected the input" >&2
			echo "EVAL_BACKEND: lexer=ouro parser=ouro elab=ouro normalize=kernel-not-invoked runtime=c" >&2
			exit 1
		}
		set --
		for u in $units; do
			set -- "$@" --unit "$u"
		done
		mkdir -p "$ROOT/_build/eval"
		emitted="$ROOT/_build/eval/wrapped.c"
		exe="$ROOT/_build/eval/wrapped.exe"
		set +e
		OURO_EMIT_IO_SHIMS=1 "$COMPILER" "$wrap" "$fuel" "$@" >"$emitted" 2>"$ROOT/_build/eval/frontend.err"
		st=$?
		set -e
		if [ "$st" -ne 0 ]; then
			echo "EVAL_FAIL $file: front end rejected the input" >&2
			cat "$ROOT/_build/eval/frontend.err" >&2 || true
			echo "EVAL_BACKEND: lexer=ouro parser=ouro elab=ouro normalize=kernel-not-invoked runtime=c" >&2
			exit 1
		fi
		CC_BIN="${CC:-cc}"
		command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
		set +e
		"$CC_BIN" -O1 -std=c99 -Werror=implicit-function-declaration \
			-I "$ROOT/runtime" -o "$exe" "$emitted" \
			"$ROOT/runtime/ouro_rt.c" "$ROOT/runtime/ouro_io.c" "$ROOT/runtime/ouro_eval_main.c" \
			>"$ROOT/_build/eval/cc.log" 2>&1
		st=$?
		set -e
		if [ "$st" -ne 0 ]; then
			echo "EVAL_FAIL $file: emitted C rejected by $CC_BIN" >&2
			cat "$ROOT/_build/eval/cc.log" >&2 || true
			exit 1
		fi
		set +e
		"$exe"
		st=$?
		set -e
		if [ "$st" -ne 0 ]; then
			echo "EVAL_FAIL $file: extracted program exited $st" >&2
			exit 1
		fi
		echo "EVAL_BACKEND: lexer=ouro parser=ouro elab=ouro normalize=kernel-not-invoked runtime=c" >&2
		exit 0
		;;
	collect)
		shift
		ensure_collect
		cd "$OLDPWD_OURO"
		exec "$COLLECT" "$@"
		;;
	build)
		shift
		ensure_native_build || exit 1
		file=""
		out=""
		backend="native"
		target="x86_64-windows"
		while [ "$#" -gt 0 ]; do
			case "$1" in
			--backend)
				backend=${2:-}
				shift 2 || exit 2
				;;
			--target)
				target=${2:-}
				shift 2 || exit 2
				;;
			--out)
				out=${2:-}
				shift 2 || exit 2
				;;
			--entry|--fuel)
				echo "ouro1: $1 is not supported on the C-hosted native driver" >&2
				exit 2
				;;
			--*)
				echo "usage: ouro1 build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" >&2
				exit 2
				;;
			*.ouro)
				if [ -n "$file" ]; then
					echo "usage: ouro1 build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" >&2
					exit 2
				fi
				file=$1
				shift
				;;
			*)
				echo "usage: ouro1 build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" >&2
				exit 2
				;;
			esac
		done
		if [ -z "$file" ]; then
			echo "usage: ouro1 build FILE.ouro [--backend native] [--target x86_64-windows] [--out FILE]" >&2
			exit 2
		fi
		if [ "$backend" != native ]; then
			echo "native-build: unsupported backend: $backend" >&2
			exit 1
		fi
		if [ "$target" != x86_64-windows ]; then
			echo "native-build: unsupported target: $target" >&2
			exit 1
		fi
		if [ -z "$out" ]; then
			stem=$(basename "$file")
			case "$stem" in
			*.ouro) stem=${stem%.ouro} ;;
			esac
			out="$ROOT/_build/native/${stem}.exe"
		fi
		native_build_program "$file" "$out"
		exit $?
		;;
	run)
		shift
		if [ "$#" -lt 1 ]; then
			echo "usage: ouro1 run FILE.ouro" >&2
			exit 2
		fi
		file=$1
		shift
		ensure_native_build || exit 1
		stem=$(basename "$file")
		case "$stem" in
		*.ouro) stem=${stem%.ouro} ;;
		esac
		outdir="$ROOT/_build/native/run"
		mkdir -p "$outdir"
		out="$outdir/${stem}.exe"
		native_build_program "$file" "$out" || exit $?
		exec "$out" "$@"
		;;
	doctor)
		shift
		ensure_native_build || exit 1
		exec "$NATIVE_BUILD" doctor "$@"
		;;
	check)
		shift
		file=${1:?usage: ouro1 check FILE [fuel] [--emit-checked-program FILE]}
		shift
		fuel=${1:-}
		artifact=""
		if [ -n "$fuel" ] && [ "${fuel#-}" != "$fuel" ]; then
			fuel=""
		elif [ -n "$fuel" ]; then
			shift
		fi
		while [ $# -gt 0 ]; do
			case "$1" in
				--emit-checked-program)
					[ $# -ge 2 ] || { echo "CHECK_FAIL: --emit-checked-program needs a path" >&2; exit 2; }
					artifact=$2
					shift 2
					;;
				*)
					break
					;;
			esac
		done
		[ -n "$fuel" ] || fuel="${OURO1_CHECK_FUEL:-16000}"
		# The wrapper already cd'd to ROOT. Relative FILE belongs to the
		# caller (pkg verify typechecks `_ouro_pkgs/...` in a temp project).
		case "$file" in
			/*) ;;
			[A-Za-z]:*) ;;
			*) file="$OLDPWD_OURO/$file" ;;
		esac
		if [ ! -f "$file" ]; then
			printf '%s\n' "CHECK_FAIL: missing $file" >&2
			exit 1
		fi
		# collect emits repo-relative --unit paths. compile_units
		# match-fails (ouro_rt tag=-1) if the root file is still an
		# absolute path under ROOT while those units are relative.
		# Windows PE tools pass I:/... (Git Bash converts PWD); map that
		# to the MSYS path so the ROOT prefix strip can fire.
		if command -v cygpath >/dev/null 2>&1; then
			case "$file" in
				[A-Za-z]:*) file=$(cygpath -u "$file") ;;
			esac
		fi
		file=$(printf '%s\n' "$file" | tr "\\\\" '/')
		case "$file" in
			"$ROOT"/*) file=${file#"$ROOT"/} ;;
		esac
		ensure_collect
		units=$(collect_unit_lines "$file") || exit 1
		set --
		nunits=0
		first_unit=""
		for u in $units; do
			nunits=$((nunits + 1))
			[ -n "$first_unit" ] || first_unit=$u
			set -- "$@" --unit "$u"
		done
		[ "$nunits" -gt 0 ] || { echo "CHECK_FAIL: empty source closure" >&2; exit 1; }
		# The collector owns path normalization and emits the entry last.
		# Use that spelling for root identity, including inputs with ./ segments.
		file=$u
		# Seed compile_units still turns some surface diagnostics
		# (OURO-LIST-001) into CErr 2. A singleton closure is the
		# compile_to_cores path and keeps the stable code.
		# Effect/perform/handle needs compile_units so fe_link can
		# run rewrite_handlers (stitch_source never does).
		if [ "$nunits" -le 1 ] && { [ -z "$first_unit" ] || [ "$first_unit" = "$file" ]; }; then
			if ! grep -Eq '(^|[[:space:]])(effect|perform|handle)[[:space:]]' "$file"
			then
				set --
			fi
		fi
		if [ -n "$artifact" ]; then
			set -- --emit-checked-program "$artifact" "$@"
		fi
		exec "$COMPILER" check "$file" "$fuel" "$@"
		;;
	rebuild)
		shift
		exec sh "$ROOT/scripts/stage_loop.sh" "$@"
		;;
	analyze)
		shift
		# A profile is a union of existing native families, not another runner.
		# Rotate the original argv once so quoted paths and option values remain
		# intact. Values named --enable-style are paths, never profile switches.
		style_value=0
		for a do
			shift
			if [ "$style_value" -eq 1 ]; then
				set -- "$@" "$a"
				style_value=0
			else
				case "$a" in
				--scope|--api-baseline)
					set -- "$@" "$a"
					style_value=1
					;;
				--enable-style)
					set -- "$@" --enable-dataflow --enable-metrics \
						--enable-simplify --enable-perf --enable-naming
					;;
				*) set -- "$@" "$a" ;;
				esac
			fi
		done
		BIN="$C_BUILD_DIR/ouro-analyze"
		DRIVE="$C_BUILD_DIR/ouro-analyze-drive"
		# Cross-host shells can report Linux while the configured compiler emits
		# PE files. Reuse the executable instead of rebuilding it on every run.
		if [ ! -e "$BIN" ] && [ -x "${BIN}.exe" ]; then
			BIN="${BIN}.exe"
		fi
		if [ ! -e "$DRIVE" ] && [ -x "${DRIVE}.exe" ]; then
			DRIVE="${DRIVE}.exe"
		fi
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/analyze/main.ouro" \
			"$ROOT/tools/analyze/model.ouro" "$ROOT/tools/analyze/extract.ouro" \
			"$ROOT/tools/analyze/extract_tokens.ouro" "$ROOT/tools/analyze/hash.ouro" \
			"$ROOT/tools/analyze/families.ouro" "$ROOT/tools/analyze/policy.ouro" \
			"$ROOT/tools/analyze/architecture.ouro" \
			"$ROOT/tools/analyze/deadcode.ouro" \
			"$ROOT/tools/analyze/suppressions.ouro" \
			"$ROOT/tools/analyze/api_surface.ouro" \
			"$ROOT/tools/analyze/trust.ouro" \
			-type f -name '*.ouro' \
			! -name 'drive_main.ouro' \
			-newer "$BIN" -print -quit 2>/dev/null)" ]; then
			# Native only: the host shim reprints a bounded-memory
			# placeholder. The cone is tools/analyze plus the five fact
			# cores policy.ouro imports; the structured cores live in
			# ouro-analyze-drive, so editing them must not rebuild this.
			OURO_BUILD_TOOL_MODE=native \
				sh "$ROOT/scripts/build_tool.sh" tools/analyze/main.ouro "$BIN" >&2
		fi
		want_drive=0
		for a in "$@"; do
			case "$a" in
			--enable-effects|--enable-capability|--enable-extract|--enable-match|--enable-cfg|--enable-dataflow|--enable-semantic|--enable-property|--enable-absint|--enable-symexec|--enable-taint|--enable-contracts|--enable-metrics|--enable-duplication|--enable-trust|--enable-simplify|--enable-perf|--enable-naming|--enable-errors|--enable-light|--enable-heavy|--enable-strict|--enable-all)
				want_drive=1
				;;
			esac
		done
		cd "$OLDPWD_OURO"
		# shellcheck source=scripts/python.sh
		. "$ROOT/scripts/python.sh"
		if [ -z "${PYTHON:-}" ] && \
			[ "${OURO_ANALYZE_ALLOW_UNBOUNDED:-0}" != "1" ]; then
			echo "ANALYZE_FAIL: bounded analyzer runner requires Python; install Python or set OURO_ANALYZE_ALLOW_UNBOUNDED=1 on a dedicated host" >&2
			exit 1
		fi
		# Nested IO can drop the `exit n` thunk. Map shown diagnostics
		# to a non-zero status so packaged analyze matches the suite
		# contract (any OURO-* line means failure).
		tmp="$ROOT/_build/analyze.last.out"
		set +e
		if [ "$want_drive" -eq 0 ]; then
			# The extracted runtime owns a process-lifetime arena. Large safe
			# profiles therefore run one native analyzer process per file plus
			# a compact native architecture pass.
			if [ -n "${PYTHON:-}" ]; then
				"$PYTHON" "$ROOT/scripts/analyze_bounded.py" \
					--bin "$BIN" --caller "$OLDPWD_OURO" -- "$@" >"$tmp"
			else
				"$BIN" "$@" >"$tmp"
			fi
		else
			if [ -n "${PYTHON:-}" ]; then
				"$PYTHON" "$ROOT/scripts/analyze_bounded.py" \
					--bin "$BIN" --caller "$OLDPWD_OURO" -- "$@" >"$tmp"
			else
				"$BIN" "$@" >"$tmp"
			fi
		fi
		st=$?
		drive_tmp="$ROOT/_build/analyze.last.drive.out"
		: >"$drive_tmp"
		st2=0
		if [ "$want_drive" -eq 1 ] && [ "$st" -ne 2 ]; then
			if [ ! -x "$DRIVE" ] || [ -n "$(find "$ROOT/tools/analyze" \
				"$ROOT/tools/analyze/drive_main.ouro" \
				-type f -name '*.ouro' ! -path '*/test/*' \
				-newer "$DRIVE" -print -quit 2>/dev/null)" ]; then
				# Build the structured cone only after the base safety preflight.
				# Ordinary rc=1 diagnostics still get their structured companions.
				OURO_BUILD_TOOL_MODE=native \
					sh "$ROOT/scripts/build_tool.sh" \
					tools/analyze/drive_main.ouro "$DRIVE" >&2
				st2=$?
			fi
			if [ "$st2" -eq 0 ]; then
				if [ -n "${PYTHON:-}" ]; then
					"$PYTHON" "$ROOT/scripts/analyze_bounded.py" --drive \
						--bin "$DRIVE" --caller "$OLDPWD_OURO" -- "$@" >"$drive_tmp"
				else
					"$DRIVE" "$@" >"$drive_tmp"
				fi
				st2=$?
			fi
		fi
		# A dropped exit thunk is not proof of a clean structured run. Require
		# complete zero-count banners as well as rc=0, and reject diagnostics
		# from either binary. The bounded runner may aggregate an empty scope.
		if [ "$want_drive" -eq 1 ] && [ "$st" -ne 2 ] && [ "$st2" -eq 0 ]; then
			drive_report=$(tr -d '\r' <"$drive_tmp" | grep '^ANALYZE_DRIVE ')
			if [ -z "$drive_report" ] ||
				printf '%s\n' "$drive_report" | grep -Ev \
					'^ANALYZE_DRIVE files=[0-9]+ findings=0 rejected=0 families=([a-z]+(,[a-z]+)*)?$' >/dev/null ||
				grep -F "OURO-" "$drive_tmp" >/dev/null; then
				echo "ANALYZE_FAIL: structured runner did not provide a consistent clean report" >&2
				st2=1
			fi
		fi
		set -e
		# ANALYZE_OK is the verdict of the whole run, never of one half alone.
		if [ "$st" -ne 0 ] || [ "$st2" -ne 0 ] || grep -F "OURO-" "$tmp" >/dev/null; then
			grep -v -e '^ANALYZE_OK ' -e '^ANALYZE_FACTS ' "$tmp" || true
			st=1
		else
			cat "$tmp"
		fi
		cat "$drive_tmp"
		if [ "$st" -ne 0 ]; then
			exit 1
		fi
		exit 0
		;;
	lint)
		shift
		BIN="$C_BUILD_DIR/ouro-lint"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/lint.ouro" "$ROOT/tools/lint_host.ouro" "$ROOT/tools/lint_names.ouro" \
			"$ROOT/compiler/lint.ouro" -newer "$BIN" -print -quit 2>/dev/null)" ]; then
			# Native only: a host-shim cannot call lintCtx, and analyze cannot
			# host this cone (char/lexer flatten + parser RSS).
			OURO_BUILD_TOOL_MODE=native \
				sh "$ROOT/scripts/build_tool.sh" tools/lint.ouro "$BIN" >&2
		fi
		cd "$OLDPWD_OURO"
		# One OS process per file bounds the process-lifetime parse/lint heap.
		# Retain the host memory cap when available and propagate failures.
		lint_one() {
			f=$1
			err=$(mktemp)
			set +e
			if command -v prlimit >/dev/null 2>&1; then
				prlimit --as=8589934592 -- "$BIN" "$f" 2>"$err"
			else
				"$BIN" "$f" 2>"$err"
			fi
			ec=$?
			set -e
			cat "$err" >&2
			rm -f "$err"
			return "$ec"
		}
		if [ "$#" -eq 1 ] && [ -f "$1" ]; then
			lint_one "$1"
			exit $?
		fi
		if [ "$#" -eq 0 ]; then
			set -- std compiler tools/analyze samples tools
		fi
		list=$(mktemp)
		trap 'rm -f "$list"' EXIT
		for p in "$@"; do
			if [ -f "$p" ]; then
				printf '%s\n' "$p" >>"$list"
			elif [ -d "$p" ]; then
				# Prune before descent so local outputs cannot flood discovery.
				# Explicit file arguments still reach lint_one above.
				if ! find "$p" \( -type d ! -path "$p" \( \
					-name _build -o -name _cache -o -name _opam -o -name _tools -o \
					-name .git -o -name node_modules -o -name test -o -name tests -o \
					-name fixtures -o -name bench -o -name future \) -prune \) -o \
					\( -type f -name '*.ouro' ! -name bad_undeclared_perform.ouro \
					! -name 04_holes.ouro -print \) >>"$list"; then
					echo "LINT_FAIL: could not enumerate $p" >&2
					exit 1
				fi
			else
				printf '%s\n' "$p" >>"$list"
			fi
		done
		sort -u "$list" -o "$list"
		st=0
		while IFS= read -r f; do
			[ -n "$f" ] || continue
			if ! lint_one "$f"; then
				st=1
			fi
		done <"$list"
		exit "$st"
		;;
	fmt)
		# The formatter is an Ouro program, so it has to be built once; rebuild
		# when its own sources moved ahead of the binary.
		shift
		BIN="$C_BUILD_DIR/ouro-fmt"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/fmt.ouro" "$ROOT/tools/fmt_pipeline.ouro" \
			"$ROOT/tools/analyze/format.ouro" \
			"$ROOT/scripts/host_tools.py" "$ROOT/scripts/python.sh" \
			-newer "$BIN" \
			-print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/fmt.ouro "$BIN" >&2
		fi
		exec "$BIN" "$@"
		;;
	fix)
		# Autofixer, same build-on-demand rule as fmt.
		shift
		BIN="$C_BUILD_DIR/ouro-fix"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/fix" -newer "$BIN" \
			-print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/fix/main.ouro "$BIN" >&2
		fi
		exec "$BIN" "$@"
		;;
	doc)
		# Reference generator, same build-on-demand rule as fmt.
		shift
		BIN="$C_BUILD_DIR/ouro-doc"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/doc.ouro" "$ROOT/tools/doc_model.ouro" -newer "$BIN" \
			-print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/doc.ouro "$BIN" >&2
		fi
		exec "$BIN" "$@"
		;;
	pkg)
		# Package manager, same build-on-demand rule as fmt. It runs in the
		# caller's directory, not the checkout: a manifest is a project's
		# file. OURO_ROOT (exported above) is how `pkg verify` finds this
		# script again for its typechecks.
		shift
		if [ -z "${OURO_PKG_CHECK:-}" ] && [ -z "${OURO_TEST_CHECK:-}" ]; then
			OURO_PKG_CHECK="$ROOT/scripts/ouro1.sh"
			export OURO_PKG_CHECK
		fi
		BIN="$C_BUILD_DIR/ouro-pkg"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/pkg" -newer "$BIN" \
			-print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/pkg/main.ouro "$BIN" >&2
		fi
		cd "$OLDPWD_OURO"
		exec "$BIN" "$@"
		;;
	test)
		# User-level test runner. Discovery stays in shell (like lint);
		# the Ouro program checks and runs explicit files.
		shift
		if [ -z "${OURO_TEST_CHECK:-}" ]; then
			OURO_TEST_CHECK="$ROOT/scripts/ouro1.sh"
			OURO_TEST_BUILD="${OURO_TEST_BUILD:-$ROOT/scripts/build_tool.sh}"
			OURO_HOSTED_COMPILER_WRAPPER="${OURO_HOSTED_COMPILER_WRAPPER:-$OURO_TEST_CHECK}"
			export OURO_TEST_CHECK OURO_TEST_BUILD OURO_HOSTED_COMPILER_WRAPPER
		fi
		BIN="$C_BUILD_DIR/ouro-test"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/test" "$ROOT/std/test.ouro" \
			-newer "$BIN" -print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/test/main.ouro "$BIN" >&2
		fi
		cd "$OLDPWD_OURO"
		case "${1:-}" in
		--manifest|--manifest=*|--native-suite|--native-suite=*|--suite-probe-failure|--help)
			exec "$BIN" "$@"
			;;
		esac
		if [ "$#" -eq 0 ]; then
			set -- .
		fi
		list=$(mktemp)
		for p in "$@"; do
			if [ -d "$p" ]; then
				find "$p" -type f -name '*_test.ouro' |
				while IFS= read -r f; do
					case "$f" in
					*/_build/*|*/_cache/*|*/_opam/*|*/_tools/*|*/.git/*|*/bad/*|*/future/*|*/fixtures/*|*/bench/*)
						continue
						;;
					esac
					printf '%s\n' "$f"
				done >>"$list"
			else
				printf '%s\n' "$p" >>"$list"
			fi
		done
		# shellcheck disable=SC2046
		set -- $(cat "$list")
		rm -f "$list"
		exec "$BIN" "$@"
		;;
	lsp)
		# Language server on stdio, for editors. Same build-on-demand rule as
		# fmt. It stays in the caller's directory so relative paths a client
		# sends resolve the way the client meant them.
		shift
		BIN="$C_BUILD_DIR/ouro-lsp"
		if [ ! -x "$BIN" ] || [ -n "$(find "$ROOT/tools/lsp.ouro" "$ROOT/tools/lsp_model.ouro" "$ROOT/tools/doc.ouro" "$ROOT/tools/doc_model.ouro" \
			-newer "$BIN" -print -quit 2>/dev/null)" ]; then
			sh "$ROOT/scripts/build_tool.sh" tools/lsp.ouro "$BIN" >&2
		fi
		cd "$OLDPWD_OURO"
		exec "$BIN" "$@"
		;;
esac

[ -x "$COMPILER" ] || {
	echo "ouro1: compiler missing" >&2
	exit 1
}
exec "$COMPILER" "$@"
