# Packages

`ouro-pkg.exe` resolves, vendors, locks and verifies packages. It reads
dependencies from a local directory registry, vendors their source into
the project, and records the resolved contents in `Ouro.lock`. Build the
standalone native tool as described in [Tooling](tooling.md#standalone-native-tools).

The compiler has no package-specific import mechanism. Installed packages are
ordinary Ouro files reached through ordinary relative imports.

A package unit may be called a ring in branding. The current commands and
paths still say `pkg`, and the vendor directory is still `_ouro_pkgs/`.

## Commands

Run package commands from the project directory:

```powershell
C:\path\to\ouro\_build\native\ouro-pkg.exe init [--name NAME] [--registry DIR]
C:\path\to\ouro\_build\native\ouro-pkg.exe add NAME [--range RANGE]
C:\path\to\ouro\_build\native\ouro-pkg.exe install
C:\path\to\ouro\_build\native\ouro-pkg.exe lock
C:\path\to\ouro\_build\native\ouro-pkg.exe remove NAME
C:\path\to\ouro\_build\native\ouro-pkg.exe update
C:\path\to\ouro\_build\native\ouro-pkg.exe list
C:\path\to\ouro\_build\native\ouro-pkg.exe verify
```

`--help` and `help` print usage and exit 0. A missing `--name`, `--registry`,
or `--range` value is rejected instead of falling back to the default. `add`
rejects an unreadable range before `Ouro.seal` changes, and prints `updated`
when it replaces an existing dependency range. `remove` fails if the name is
not a current direct dependency.

The compatibility `scripts/coil.sh` wrapper retains `resolve` and `seal`
aliases for `lock`. Native `coil.exe` has no package dispatch yet; run
`ouro-pkg.exe` directly. Keep `coil.exe` beside it for verification.

## Seal

`Ouro.seal` is the handwritten project form. It is not TOML. Version 1 is a
header plus named blocks of `key = value`. Comments are `#` or `--` outside
quotes. Strings use `"..."` with no escapes.

```text
seal 1

project {
  name = "app"
  version = "0.1.0"
}

deps {
  greet = "^0.1.0"
}

registry {
  source = "../registry"
}

```

The package tool reads `project`, `deps`, and `registry` while preserving
other blocks. [Build configuration](build.md#configuration) owns `build` and
`cache`; [Trusted computing base](tcb.md) explains the `trust` declaration.

Supported ranges include `*`, exact versions, `^x.y.z`, `~x.y.z`, and the
ordinary comparison operators. `add` rejects a range that does not parse as
one of those forms. A relative registry path is resolved from the
project directory.

Package and dependency names are single portable path segments of at most 128
bytes. They use letters, digits, `-`, `.`, or `_`, must begin and end with an
alphanumeric character, and cannot contain separators, dot segments, drive
prefixes, whitespace, or controls. A requested/registry directory name must
match the package identity in `Ouro.seal`, and lockfile names are checked by
the same rule.

## Local registry

A registry contains one directory per package:

```text
registry/
  hello/
    Ouro.seal
    src/lib.ouro
  greet/
    Ouro.seal
    src/lib.ouro
```

The current layout stores one directory per package name.

Registry package directories and copied files must be canonical regular
directories/files beneath the configured registry root. Symlinks, Windows
reparse points, canonical escapes, unreadable entries, and truncated source
walks are rejected before installation.

A complete example lives under `samples/pkg/`.

## Installation and imports

`install` resolves the dependency graph and copies each package to
`_ouro_pkgs/<name>/` in the project. Transitive dependencies are installed
alongside direct dependencies.

A project imports the vendored source by path:

```ouro
import "../_ouro_pkgs/greet/src/lib.ouro";
```

`_ouro_pkgs/` is generated output. Edit the source package or registry entry,
then reinstall; do not maintain the vendored copy by hand.

## Lockfile and verification

`Ouro.lock` records the resolved package versions, source paths, and a
deterministic digest of the vendored files. The current lock body is generated
JSON. `list` and `verify` reject an unreadable lockfile instead of treating it
as empty. `verify` recomputes that digest and typechecks every installed
`.ouro` file through sibling `coil.exe check`. Verification requires exit
0 and `CHECK_OK` without `CHECK_FAIL`; process errors remain failures.
`OURO_PKG_CHECK` no longer selects a checker. Each source has a provisional
120-second, one-CPU, 3072-MiB child-tree limit and 16 MiB per captured stream.

The digest detects drift; [current limits](#current-limits) describe what it
does not authenticate. The seal and lock formats remain experimental before 1.0.

## Current limits

Packages use one version per name from a local registry. There is no public or
network registry, authenticated source or cryptographic content hash, `pkg:`
import scheme, or `coil publish` command. The seal and lock formats follow the
[pre-1.0 compatibility policy](stability.md#experimental-areas).

Native acceptance must provision a direct-PE package executable and its
sibling checker before running the retained package suite:

```sh
sh scripts/pkg_suite.sh
```
