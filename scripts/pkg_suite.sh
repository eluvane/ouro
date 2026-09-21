#!/usr/bin/env sh
# Package-manager evidence uses a scratch project so registry, vendoring, lock, drift, and verify paths are exercised.

set -eu
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"

# Native acceptance uses an explicitly provisioned directory, never a C fallback.
NATIVE_TOOLS=""
if [ "${1:-}" = --native-tools ]; then
	if [ "$#" -lt 2 ] || [ -z "$2" ]; then
		echo "usage: sh scripts/pkg_suite.sh --native-tools DIR [suite options]" >&2
		exit 2
	fi
	NATIVE_TOOLS=$2
	case "$NATIVE_TOOLS" in
	/* | [A-Za-z]:*) ;;
	*) NATIVE_TOOLS="$ROOT/$NATIVE_TOOLS" ;;
	esac
	NATIVE_TOOLS=$(CDPATH='' cd "$NATIVE_TOOLS" && pwd -P) || {
		echo "PKG_SUITE: FAIL native candidate directory" >&2
		exit 1
	}
	shift 2
fi

OUT="${PKG_SUITE_OUT:-$ROOT/_build/pkg_suite}"
case "$OUT" in
/*|[A-Za-z]:*) ;;
*) OUT="$ROOT/$OUT" ;;
esac
if [ -n "$NATIVE_TOOLS" ]; then
	if [ -e "$OUT" ] || [ -L "$OUT" ]; then
		echo "PKG_SUITE: FAIL native acceptance requires a fresh PKG_SUITE_OUT" >&2
		exit 1
	fi
else
	rm -rf "$OUT"
fi
mkdir -p "$OUT"

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite pkg \
		--receipt "$OUT/native-candidates.json"
	PKG="$NATIVE_TOOLS/ouro-pkg.exe"
else
	CC_BIN="${CC:-cc}"
	command -v "$CC_BIN" >/dev/null 2>&1 || CC_BIN=gcc
	if ! command -v "$CC_BIN" >/dev/null 2>&1; then
		echo "PKG_SUITE: SKIP no system C compiler" >&2
		exit 0
	fi

	PKG="$OUT/ouro-pkg"
	sh "$ROOT/scripts/build_tool.sh" tools/pkg/main.ouro "$PKG" >"$OUT/build.log" 2>&1 || {
		echo "PKG_SUITE: FAIL build" >&2
		tail -n 20 "$OUT/build.log" >&2
		exit 1
	}
	export OURO_PKG_CHECK="$ROOT/scripts/ouro1.sh"
	export OURO_HOSTED_COMPILER_WRAPPER="$OURO_PKG_CHECK"
fi

rows=0
fail=0

ok() {
	rows=$((rows + 1))
	echo "PKG_OK $1"
}

bad() {
	rows=$((rows + 1))
	fail=$((fail + 1))
	echo "PKG_FAIL $1 $2" >&2
}

# Exit code of a command that is expected to fail; `set -e` would abort.
status() {
	set +e
	"$@" >"$OUT/last.out" 2>"$OUT/last.err"
	st=$?
	set -e
	return $st
}

PROJ="$OUT/proj"
mkdir -p "$PROJ"
cd "$PROJ"

"$PKG" init --name demo --registry "$ROOT/samples/pkg/registry" >"$OUT/init.log" 2>&1
if grep -q 'name = "demo"' Ouro.seal; then
	ok init
else
	bad init manifest
	cat Ouro.seal >&2
fi
if status "$PKG" init; then
	bad init-twice "expected nonzero"
else
	ok init-twice
fi

"$PKG" add greet --range '^0.1.0' >"$OUT/add.log" 2>&1
"$PKG" add greet --range '>=0.1.0' >>"$OUT/add.log" 2>&1
if [ "$(grep -c 'greet' Ouro.seal)" = 1 ] &&
	grep -q '">=0.1.0"' Ouro.seal; then
	ok add
else
	bad add manifest
	cat Ouro.seal >&2
fi

# install vendors greet plus its transitive dependency hello, and locks both.
"$PKG" install >"$OUT/install.log" 2>&1
if [ -f _ouro_pkgs/greet/src/lib.ouro ] &&
	[ -f _ouro_pkgs/hello/src/lib.ouro ] &&
	grep -q '"name":"hello"' Ouro.lock; then
	ok install
else
	bad install tree
	cat "$OUT/install.log" >&2
fi

"$PKG" list >"$OUT/list.log" 2>&1
if grep -q 'greet 0.1.0' "$OUT/list.log" && grep -q 'files=' "$OUT/list.log"; then
	ok list
else
	bad list output
	cat "$OUT/list.log" >&2
fi

# verify: digests match and every installed module typechecks.
if status "$PKG" verify; then
	ok verify
else
	bad verify "expected zero"
	cat "$OUT/last.err" >&2
fi

# lock is the explicit resolve-and-vendor step; it refreshes Ouro.lock.
"$PKG" lock >"$OUT/lock.log" 2>&1
if [ -f Ouro.lock ] &&
	[ -f _ouro_pkgs/greet/src/lib.ouro ] &&
	[ -f _ouro_pkgs/hello/src/lib.ouro ]; then
	ok lock
else
	bad lock tree
	cat "$OUT/lock.log" >&2
fi

# remove drops the dep from the manifest only; restore it for later rows.
"$PKG" remove greet >"$OUT/remove.log" 2>&1
if grep -q 'greet' Ouro.seal; then
	bad remove manifest
	cat Ouro.seal >&2
else
	ok remove
fi
"$PKG" add greet --range '^0.1.0' >>"$OUT/add.log" 2>&1

"$PKG" update >"$OUT/update.log" 2>&1
if status "$PKG" verify; then
	ok update
else
	bad update "expected zero"
	cat "$OUT/last.err" >&2
	cat "$OUT/update.log" >&2
fi

if status "$PKG" remove; then
	bad remove-no-name "expected nonzero"
else
	ok remove-no-name
fi

# A local edit under _ouro_pkgs/ is drift, and verify has to say so.
printf '\ndef tampered : String := "x";\n' >>_ouro_pkgs/hello/src/lib.ouro
if status "$PKG" verify; then
	bad verify-tampered "expected nonzero"
else
	if grep -q 'digest mismatch for hello' "$OUT/last.err"; then
		ok verify-tampered
	else
		bad verify-tampered "no digest report"
		cat "$OUT/last.err" >&2
	fi
fi

# install is idempotent and repairs the tampered tree.
"$PKG" install >>"$OUT/install.log" 2>&1
if status "$PKG" verify; then
	ok reinstall
else
	bad reinstall "expected zero"
	cat "$OUT/last.err" >&2
fi

# A deleted vendor tree is missing source, not an empty matching digest.
rm -rf _ouro_pkgs/hello
if status "$PKG" verify; then
	bad verify-missing-vendor "expected nonzero"
else
	if grep -q 'missing vendored source for hello' "$OUT/last.err"; then
		ok verify-missing-vendor
	else
		bad verify-missing-vendor "no missing-source report"
		cat "$OUT/last.err" >&2
	fi
fi
"$PKG" install >>"$OUT/install.log" 2>&1
if status "$PKG" verify; then
	ok reinstall-missing-vendor
else
	bad reinstall-missing-vendor "expected zero"
	cat "$OUT/last.err" >&2
fi

# A dependency the registry does not have is a resolution error, not a crash.
"$PKG" add nosuch --range '^1.0.0' >>"$OUT/add.log" 2>&1
if status "$PKG" install; then
	bad missing-dep "expected nonzero"
else
	if grep -q 'missing package nosuch' "$OUT/last.err"; then
		ok missing-dep
	else
		bad missing-dep "no report"
		cat "$OUT/last.err" >&2
	fi
fi

# A range no version in the registry satisfies is reported with both versions.
"$PKG" add greet --range '^9.0.0' >>"$OUT/add.log" 2>&1
if status "$PKG" install; then
	bad bad-range "expected nonzero"
else
	if grep -q 'version mismatch for greet' "$OUT/last.err"; then
		ok bad-range
	else
		bad bad-range "no report"
		cat "$OUT/last.err" >&2
	fi
fi

# Package names are path segments, not paths. Reject traversal at both project
# initialization and dependency mutation before a manifest or vendor path can
# be created.
BADNAME_PROJ="$OUT/proj-bad-name"
mkdir -p "$BADNAME_PROJ"
cd "$BADNAME_PROJ"
if status "$PKG" init --name '../escape' --registry "$ROOT/samples/pkg/registry"; then
	bad init-traversal-name "expected nonzero"
else
	if [ ! -e Ouro.seal ] && grep -q 'invalid package name' "$OUT/last.err"; then
		ok init-traversal-name
	else
		bad init-traversal-name "manifest created or diagnostic missing"
		cat "$OUT/last.err" >&2
	fi
fi
"$PKG" init --name safe-name --registry "$ROOT/samples/pkg/registry" \
	>"$OUT/bad-name-init.log" 2>&1
if status "$PKG" add '../escape' --range '*'; then
	bad add-traversal-name "expected nonzero"
else
	if ! grep -q '\.\./escape' Ouro.seal; then
		ok add-traversal-name
	else
		bad add-traversal-name "unsafe dependency persisted"
	fi
fi

# The requested registry directory and the package manifest must agree on the
# name; otherwise a safe directory can smuggle a different vendor target.
MISMATCH_REG="$OUT/mismatch-registry"
mkdir -p "$MISMATCH_REG/alias/src"
printf 'seal 1\n\nproject {\n  name = "other"\n  version = "0.1.0"\n}\n\ndeps {\n}\n' \
	>"$MISMATCH_REG/alias/Ouro.seal"
printf -- '-- @entry mismatch\n\ndef mismatch : Nat := Z;\n' \
	>"$MISMATCH_REG/alias/src/lib.ouro"
MISMATCH_PROJ="$OUT/proj-mismatch"
mkdir -p "$MISMATCH_PROJ"
cd "$MISMATCH_PROJ"
"$PKG" init --name mismatch-app --registry "$MISMATCH_REG" \
	>"$OUT/mismatch.log" 2>&1
"$PKG" add alias --range '^0.1.0' >>"$OUT/mismatch.log" 2>&1
if status "$PKG" install; then
	bad manifest-name-mismatch "expected nonzero"
else
	if grep -q 'manifest name mismatch' "$OUT/last.err"; then
		ok manifest-name-mismatch
	else
		bad manifest-name-mismatch "diagnostic missing"
		cat "$OUT/last.err" >&2
	fi
fi

# Registry package directories must be real directories under the registry,
# never symlinks or Windows reparse-point junctions to host files.
OUTSIDE_PKG="$OUT/outside-package"
LINK_REG="$OUT/link-registry"
mkdir -p "$OUTSIDE_PKG/src" "$LINK_REG"
printf 'seal 1\n\nproject {\n  name = "linked"\n  version = "0.1.0"\n}\n\ndeps {\n}\n' \
	>"$OUTSIDE_PKG/Ouro.seal"
printf -- '-- @entry linked\n\ndef linked : Nat := Z;\n' \
	>"$OUTSIDE_PKG/src/lib.ouro"
link_made=0
case "$(uname -s)" in
	MINGW*|MSYS*|CYGWIN*)
		if MSYS2_ARG_CONV_EXCL='*' cmd.exe /c mklink /J \
			"$(cygpath -w "$LINK_REG/linked")" \
			"$(cygpath -w "$OUTSIDE_PKG")" >"$OUT/link-create.log" 2>&1; then
			link_made=1
		fi
		;;
	*)
		if ln -s "$OUTSIDE_PKG" "$LINK_REG/linked" \
			>"$OUT/link-create.log" 2>&1; then
			link_made=1
		fi
		;;
esac
if [ "$link_made" -ne 1 ]; then
	bad registry-link-setup "could not create symlink/reparse fixture"
	cat "$OUT/link-create.log" >&2
else
	LINK_PROJ="$OUT/proj-link"
	mkdir -p "$LINK_PROJ"
	cd "$LINK_PROJ"
	"$PKG" init --name link-app --registry "$LINK_REG" >"$OUT/link.log" 2>&1
	"$PKG" add linked --range '^0.1.0' >>"$OUT/link.log" 2>&1
	if status "$PKG" install; then
		bad registry-link-rejected "expected nonzero"
	else
		if grep -Eq 'unsafe link/reparse|escapes registry' "$OUT/last.err"; then
			ok registry-link-rejected
		else
			bad registry-link-rejected "diagnostic missing"
			cat "$OUT/last.err" >&2
		fi
	fi
fi

# verify also typechecks what it installed, and the checker reports rejection in
# its output rather than in its exit status: judging by the status alone would
# call this package good.
BADREG="$OUT/badreg"
mkdir -p "$BADREG/broke/src"
printf 'seal 1\n\nproject {\n  name = "broke"\n  version = "0.1.0"\n}\n\ndeps {\n}\n' \
	>"$BADREG/broke/Ouro.seal"
printf -- '-- @entry broke\n\ndef broke : Nat := no_such_name Z;\n' \
	>"$BADREG/broke/src/lib.ouro"
PROJ2="$OUT/proj-broke"
mkdir -p "$PROJ2"
cd "$PROJ2"
"$PKG" init --name demo-broke --registry "$BADREG" >"$OUT/broke.log" 2>&1
"$PKG" add broke --range '^0.1.0' >>"$OUT/broke.log" 2>&1
"$PKG" install >>"$OUT/broke.log" 2>&1
if status "$PKG" verify; then
	bad verify-broken-module "expected nonzero"
else
	if grep -q 'check failed' "$OUT/last.err"; then
		ok verify-broken-module
	else
		bad verify-broken-module "no report"
		cat "$OUT/last.err" >&2
	fi
fi

# Lockfile package names receive the same path-segment validation as manifests.
printf '{"packages":[{"name":"../escape","version":"0.1.0","source":"x","digest":"x"}]}\n' \
	>"$PROJ2/Ouro.lock"
if status "$PKG" verify; then
	bad verify-traversal-lock "expected nonzero"
else
	if grep -q 'verify: invalid' "$OUT/last.err"; then
		ok verify-traversal-lock
	else
		bad verify-traversal-lock "no report"
		cat "$OUT/last.err" >&2
	fi
fi

# A corrupted lockfile must not look like a successful empty verify.
printf 'not-json\n' >"$PROJ2/Ouro.lock"
if status "$PKG" verify; then
	bad verify-invalid-lock "expected nonzero"
else
	if grep -q 'verify: invalid' "$OUT/last.err"; then
		ok verify-invalid-lock
	else
		bad verify-invalid-lock "no report"
		cat "$OUT/last.err" >&2
	fi
fi

cd "$ROOT"

# Preserve the legacy marker check; native checks also require a successful
# child process and reject CHECK_FAIL even if CHECK_OK was printed as well.
sample_check() {
	if [ -n "$NATIVE_TOOLS" ]; then
		"$NATIVE_TOOLS/coil.exe" check "$1" >"$2" 2>&1 || return $?
		! grep -q CHECK_FAIL "$2" || return 1
	else
		sh "$ROOT/scripts/ouro1.sh" check "$1" >"$2" 2>&1 || true
	fi
	grep -q CHECK_OK "$2"
}

# The committed sample project: install, then typecheck what it imports. The
# checker's own verdict is the text it prints, which is what parity_suite.sh
# greps for too.
( cd samples/pkg/app && "$PKG" install ) >"$OUT/sample.log" 2>&1
if sample_check samples/pkg/app/src/main.ouro "$OUT/sample_app.log"; then
	ok sample-app
else
	bad sample-app check
	cat "$OUT/sample_app.log" >&2
fi

# The registry sources themselves are ordinary modules.
if sample_check samples/pkg/registry/greet/src/lib.ouro "$OUT/sample_registry.log"; then
	ok sample-registry
else
	bad sample-registry check
	cat "$OUT/sample_registry.log" >&2
fi

# Installed packages are build output; leave the sample project as committed.
rm -rf samples/pkg/app/_ouro_pkgs samples/pkg/app/Ouro.lock

if [ -n "$NATIVE_TOOLS" ]; then
	"$PYTHON" "$ROOT/scripts/native_suite_tools.py" --directory "$NATIVE_TOOLS" --suite pkg \
		--receipt "$OUT/native-candidates.json" --verify
fi

if [ "$fail" -ne 0 ]; then
	echo "PKG_SUITE: FAIL rows=$rows failures=$fail" >&2
	exit 1
fi
echo "PKG_SUITE: PASS rows=$rows out=$OUT"
exit 0
