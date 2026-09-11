<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=START&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="START banner"
  />
</p>

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

This builds the committed C bootstrap path into `_build/c/`.
`scripts/ouro1.sh` selects and rebuilds the required binaries for each command,
so use it instead of invoking files under `_build/` directly.

The Python build driver exposes the same project configuration. Defaults live
in `Ouro.seal` under the `build` and `cache` blocks; CLI and environment
overrides still win. See [Packages](pkg.md) for the seal form.

```sh
python3 scripts/ouro_build.py config show
python3 scripts/ouro_build.py build
sh scripts/coil.sh config show
```

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

`ouro1 build` / `ouro1 run` lower through the compiler-owned checker and the
native PE backend. `legacy-c` is rejected. The other `samples/demo/` programs
(`02_io_echo`, `03_do_bind`, `04_pure_handler`, `05_effect_handler`) use the
same command; echo-style samples read one stdin line. File, argv, and
environment programs use the same native PE path. The C-hosted
`scripts/build_tool.sh` path still exists for emitting repository tools; it is
not the program compile command.

## Format, test, and document code

```sh
sh scripts/ouro1.sh fmt --check samples/demo/01_hello.ouro
sh scripts/ouro1.sh test samples/examples/test_demo.ouro
sh scripts/ouro1.sh doc --out _build/api std/io.ouro
```

The repository also provides analyzers, a linter, a local package manager, an
experimental language server, and a VS Code extension. See
[Tooling](tooling.md) and [Packages](pkg.md).

## Learn the language

The tutorial sequence is:

1. `samples/tutorial/01_hello.ouro`
2. `samples/tutorial/02_nat.ouro`
3. `samples/tutorial/03_list.ouro`
4. `samples/tutorial/04_holes.ouro`
5. `samples/tutorial/05_fix.ouro`
6. `samples/tutorial/06_effects.ouro`

Continue with the [syntax reference](syntax.md), the
[example gallery](../samples/examples/README.md), and the generated
[standard-library API](api/README.md).

## Compiler checking development

Run the complete compiler laws and focused checking profile:

```sh
sh scripts/test_suite.sh --compiler-checking
python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel
```

The profile name is retained for command compatibility. Its required checks
exercise the compiler-owned Ouro implementation. Read
[Compiler checking](kernel_design.md) and [Contributing](../CONTRIBUTING.md)
before changing its rules.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
