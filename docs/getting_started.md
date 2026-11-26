# Getting started

Build the toolchain from source, check a module, and evaluate a natural-number
expression. The last exercise runs a Windows x86-64 executable.

## Requirements

Install the following tools before building.

- Git to clone the repository
- Python 3.12 recommended. The default bootstrap cache needs Python 3.10
  or later.
- A POSIX-compatible shell
- A GCC-compatible C compiler available as `cc` or `gcc`

Linux and macOS provide a POSIX shell. On Windows, use WSL with a Linux C
compiler or Git Bash with a Windows C compiler such as MinGW-w64. The Windows
PE exercise requires an environment that can execute the image. The current
toolchain and compiler-checking suites run without OCaml, opam, or Dune.

## Build the bootstrap toolchain

If you need a checkout, use network access to clone the source into `ouro/`.

```sh
git clone https://github.com/eluvane/ouro.git
cd ouro
```

Run the build from the repository root. Use that directory for the remaining
commands. The default configuration writes build outputs to `_build/` and
cache data to `_cache/ouro/`.

```sh
sh scripts/bootstrap.sh
```

A successful build exits with status 0. With normal verbosity, the build
driver also reports `BUILD: OK`.
See [build commands and configuration](build.md#entry-points) for details.

## Check a module

```sh
sh scripts/ouro1.sh check samples/tutorial/02_nat.ouro
```

`check` resolves relative imports and typechecks the module and its dependencies.
It prints `CHECK_OK` on success. A failure includes an `OURO-*` diagnostic
when one is available.

## Evaluate an expression

```sh
sh scripts/ouro1.sh eval samples/examples/nat.ouro --print four
sh scripts/ouro1.sh eval samples/examples/nat.ouro --eval 'add four two'
```

`--print` evaluates the declaration `four`. `--eval` evaluates an expression
in the module's scope. The results are four and six, printed as `Nat`
constructors. Evaluation defaults to `Nat`. Pass `--type TYPE` when the
expression has another type.

## Run a native program

The example in `samples/demo/01_hello.ouro` declares `main : IO Unit` to run
standard-library IO actions. See the
[native declaration reference](syntax.md#experimental-native-declarations)
for the supported managed entry types.

```ouro
import "../../std/io.ouro";

-- @entry main
def main : IO Unit :=
  do println "hello";
     exit 0
```

In a POSIX-compatible shell that can execute Windows x86-64 PE files, build
the program to `_build/native/01_hello.exe` and run it.

```sh
sh scripts/ouro1.sh build samples/demo/01_hello.ouro
./_build/native/01_hello.exe
```

To build and execute it in one command, use `run`, which writes the image to
`_build/native/run/01_hello.exe`.

```sh
sh scripts/ouro1.sh run samples/demo/01_hello.ouro
```

The program prints `hello`. The echo samples in `samples/demo/` also read
one line from stdin. See the [native build command reference](tooling.md#native-program-compile)
for target and output options.

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
