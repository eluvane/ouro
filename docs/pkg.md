# Packages

The package tool resolves dependencies from a local directory registry, copies
their source into `_ouro_pkgs/`, and records the resolved files in
`Ouro.lock`. Import installed packages through ordinary relative paths.

## Commands

Run package commands from the project directory that contains or will contain
`Ouro.seal`, `Ouro.lock`, and `_ouro_pkgs/`.

### Native commands

On Windows, build the [standalone native tools](tooling.md#standalone-native-tools)
first. In PowerShell, replace the example value of `$OuroPkg` with the full
path to your built tool.

```powershell
$OuroPkg = 'C:\src\ouro\_build\native\ouro-pkg.exe'
& $OuroPkg --help
```

Native `coil pkg [PACKAGE_ARG ...]` runs the fixed `ouro-pkg.exe` beside its
loaded Windows image. It forwards arguments and inherits stdin, stdout,
stderr, the working directory, and the environment. The package tool handles
help, option validation, and diagnostics. The launcher preserves the
completed child's exit code. Image or process failures produce a `coil:`
diagnostic and exit 1. Native verification needs sibling `coil.exe` and its
checked build backend.

### Hosted commands

After [building the bootstrap toolchain](getting_started.md#build-the-bootstrap-toolchain),
use a POSIX-compatible shell. Set `ouro_checkout` to the absolute path to
the checkout and run the command from your project directory.

```sh
ouro_checkout=/path/to/ouro
sh "$ouro_checkout/scripts/coil.sh" pkg --help
```

`scripts/coil.sh pkg` uses `scripts/ouro1.sh pkg`, which builds the hosted
package tool on demand. The shell wrapper also accepts `coil resolve` and
`coil seal` as aliases for `coil lock`.

### Command forms

Brackets enclose optional arguments. Replace `NAME`, `DIR`, and `RANGE` with
your values.

```text
init [--name NAME] [--registry DIR]
add NAME [--range RANGE]
install
lock
remove NAME
update
list
verify
```

`--help` and `help` print usage and exit 0. A missing value for `--name`,
`--registry`, or `--range` is an error. `add` validates the range before
changing `Ouro.seal` and prints `updated` when it replaces an existing
dependency range. `remove` fails if the name is absent from the manifest's
direct dependencies. On success it updates only `Ouro.seal`. Run `install`
to refresh the lockfile after changing dependencies.

## Seal

Write `Ouro.seal` in the versioned seal format. Version 1 starts with
`seal 1` and uses named blocks with `key = value` entries. Outside strings,
`#` and `--` start comments. Use double quotes for strings. The format has
no string escapes.

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
other blocks. See [Build configuration](build.md#configuration) for `build`
and `cache` and [Trusted computing base](tcb.md) for `trust`.

Supported ranges include `*`, exact versions, `^x.y.z`, `~x.y.z`, and the
ordinary comparison operators. Relative registry paths resolve from the
project directory.

Package and dependency names are single path segments of at most 128 bytes.
Use ASCII letters, digits, and the characters `-`, `.`, and `_`. Start and
end each name with a letter or digit. The requested name, registry directory
name, and package name in `Ouro.seal` must match. Lockfile names follow the
same character and length rules.

## Local registry

A registry contains one directory per package.

```text
registry/
  hello/
    Ouro.seal
    src/lib.ouro
  greet/
    Ouro.seal
    src/lib.ouro
```

Use regular files and directories that resolve within the configured registry
root. Before copying each package, the tool walks its source tree and rejects
symlinks, Windows reparse points, resolved paths outside that tree, unreadable
entries, and incomplete walks. The tool reports file read errors as it copies
the files.

See the [sample project and local registry](../samples/pkg/).

## Installation and imports

`install`, `lock`, and `update` all resolve the dependency graph against the
configured registry, copy direct and transitive dependencies into
`_ouro_pkgs/<name>/`, and write `Ouro.lock` when resolution and copying
succeed. Copies overwrite matching destination files. Files with no matching
source remain in the vendor tree. A failed resolution or copy leaves any
earlier writes in place, exits nonzero, and skips writing the lockfile.

For example, a module in the project's `src/` directory can import a
vendored package by relative path.

```ouro
import "../_ouro_pkgs/greet/src/lib.ouro";
```

`_ouro_pkgs/` is generated output. Edit the source package or registry entry,
then reinstall.

## Lockfile and verification

`Ouro.lock` is generated JSON. It records the resolved package versions,
source paths, and a deterministic digest of each package's vendored files
to detect drift. `list` and `verify` reject an unreadable or malformed
lockfile. With a valid manifest and no lockfile, `list` prints `locked: none`.
`verify` requires a lockfile.

`verify` walks only the vendored trees listed in `Ouro.lock`. It recomputes
each tree's digest and checks every `.ouro` file in that tree after the digest
matches. Checker success requires exit 0 and `CHECK_OK` without `CHECK_FAIL`.
Process errors fail verification.

Native verification uses sibling `coil.exe check` with provisional limits
per source of 120 seconds, one CPU, 3072 MiB per child tree, and 16 MiB per
captured stream. Before launch, native `coil pkg` refuses the first present
hosted checker selector, even if its value is empty. The order is
`OURO_TEST_CHECK`, `OURO_PKG_CHECK`, then `OURO_HOSTED_COMPILER_WRAPPER`.
The standalone tool can use these selectors to run the hosted checker for
hosted-suite compatibility.

## Current limits

Packages use one version per name from a local registry. There is no public or
network registry, authenticated source or cryptographic content hash, `pkg:`
import scheme, or `coil publish` command. The seal and lock formats follow the
[pre-1.0 compatibility policy](stability.md#experimental-areas).

## Package suite

Use the [CI validation matrix](ci.md#validation-matrix) for the hosted package
suite. For native acceptance, use the [CI provisioning procedure](ci.md#local-profiles)
for direct-PE candidates, their sibling tools, and a fresh output directory.
