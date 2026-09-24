# Getting started

This guide takes a fresh checkout to a checked module, an evaluated expression,
and a native program.

## Requirements

The maintained command path expects:

- Python 3;
- a POSIX-compatible shell;
- a C compiler available as `cc` or `gcc`.

Linux and macOS provide a suitable shell environment directly. On Windows, use
WSL or Git Bash. The current toolchain and compiler-checking suites do not
require OCaml, opam, or Dune.

## Build the bootstrap toolchain

From the repository root:

```sh
sh scripts/bootstrap.sh
```

The command builds the current bootstrap toolchain. Use `scripts/ouro1.sh` for
the steps below; [Build and bootstrap](build.md#entry-points) owns the build
driver, configuration, cache, and host requirements.

## Check a module

```sh
sh scripts/ouro1.sh check samples/tutorial/02_nat.ouro
```

`check` resolves the module's relative imports, collects the dependency closure,
and typechecks the complete unit set. Success is reported as `CHECK_OK`;
failures include a stable `OURO-*` diagnostic when one is available.

## Evaluate an expression

```sh
sh scripts/ouro1.sh eval samples/examples/nat.ouro --print four
sh scripts/ouro1.sh eval samples/examples/nat.ouro --eval 'add four two'
```

`--print` evaluates a declared name. `--eval` elaborates an expression in the
module's scope and prints its value. Evaluation defaults to `Nat`; pass
`--type TYPE` when the expression has another type.

## Run a native program

A runnable program exports `main : IO Unit`. The repository's smallest example
is `samples/demo/01_hello.ouro`:

```ouro
import "../../std/io.ouro";

-- @entry main
def main : IO Unit :=
  do println "hello";
     exit 0
```

Build and run it as a Windows x86-64 PE:

```sh
sh scripts/ouro1.sh build samples/demo/01_hello.ouro
./_build/native/01_hello.exe
sh scripts/ouro1.sh run samples/demo/01_hello.ouro
```

The other programs in `samples/demo/` use the same command; echo-style samples
read one stdin line. [Tooling](tooling.md#native-program-compile) documents
build options and the native target.

## Format, test, and document code

```sh
sh scripts/ouro1.sh fmt --check samples/demo/01_hello.ouro
sh scripts/ouro1.sh test samples/examples/test_demo.ouro
```

The repository also provides analyzers, a linter, a local package manager, an
experimental language server, and a VS Code extension. See
[Tooling](tooling.md), including the [documentation generator](tooling.md#documentation-generator),
and [Packages](pkg.md).

## Learn the language

Continue with the [tutorial sequence](../samples/tutorial/README.md),
[syntax reference](syntax.md), the
[example gallery](../samples/examples/README.md), and the generated
[standard-library API](api/README.md).

## Compiler checking development

For compiler work, read [Compiler checking](kernel_design.md) and use the
focused checks in [CI](ci.md#local-profiles).
