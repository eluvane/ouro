<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=OURO&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="OURO banner"
  />
</p>

# Ouro

Ouro is an experimental dependently typed programming language and toolchain.

<!-- readme-example: samples/examples/nat.ouro -->
```ouro
-- Nat and structural recursion.

-- @entry four
inductive Nat : Type :=
  | Z : Nat
  | S : Nat -> Nat;

def add : Nat -> Nat -> Nat :=
  fix add (n : Nat) (m : Nat) : Nat :=
    match n with
    | Z => m
    | S n' => S (add n' m)
    end;

def two : Nat := 2;

def four : Nat := add two two;
```

The example defines natural numbers and structural addition, then evaluates the
result through the current toolchain:

```sh
sh scripts/ouro1.sh eval samples/examples/nat.ouro --print four
```

## Status

Ouro is pre-1.0 research software. The language, standard library, command-line
interfaces, package format, and editor integration may change between releases.

The current repository can typecheck and evaluate Ouro modules, build programs
for the implemented IO/runtime slice through a C backend, run project tests,
format and analyze source, generate API documentation, resolve packages from a
local registry, and serve an experimental LSP. The compiler is not fully
self-hosted, the runtime is not a production platform, and the compiler
checker has no complete formal correctness proof.

The chosen direction is a standalone native toolchain implemented in Ouro:
one compiler-owned typechecker, direct machine-code generation, executable
writing, a runtime with garbage collection, and native build/CLI tools. The first
target is Windows x86-64 with PE32+ executables. At completion, ordinary use and
rebuilding a supported release from its published native seed will require no
C compiler, external assembler/linker, OCaml, Dune, Python, or shell. This is the
transition target; the current commands and dependencies below still apply.

The compiler-owned Ouro checker validates the complete supported module and
import graph. Independent OCaml/Python Core replay is retired; its retained
semantic contracts execute in Ouro. Typechecking, explicit errors, and negative
tests remain required. The general build path still requires C and host scripts.

See [Stability](docs/stability.md) for the compatibility policy and
[Roadmap](docs/roadmap.md) for the project direction.

## Quick start

You need Python 3, a POSIX-compatible shell, and a C compiler available as
`cc` or `gcc`. On Windows, use WSL or Git Bash.

```sh
git clone https://github.com/eluvane/ouro.git
cd ouro

sh scripts/bootstrap.sh
sh scripts/ouro1.sh check samples/tutorial/02_nat.ouro
sh scripts/ouro1.sh eval samples/examples/nat.ouro --eval 'add four two'
```

To build and run a small native IO program (Windows x86-64 PE):

```sh
sh scripts/ouro1.sh build samples/demo/01_hello.ouro
./_build/native/01_hello.exe
sh scripts/ouro1.sh run samples/demo/01_hello.ouro
```

The complete walkthrough is in [Getting started](docs/getting_started.md).

## Tooling

The `scripts/ouro1.sh` wrapper exposes the maintained command-line entry points.
`scripts/coil.sh` is the project-facing name for the same toolchain. Project
defaults and package identity live in `Ouro.seal`.

```sh
sh scripts/ouro1.sh check path/to/module.ouro
sh scripts/ouro1.sh eval path/to/module.ouro --print name --type TYPE
sh scripts/ouro1.sh fmt --check path/to/module.ouro
sh scripts/ouro1.sh analyze --strict
sh scripts/ouro1.sh lint std samples
sh scripts/ouro1.sh test path/to/test.ouro
sh scripts/coil.sh install
sh scripts/ouro1.sh pkg install
sh scripts/ouro1.sh doc --out docs/api std/io.ouro
sh scripts/ouro1.sh lsp
```

Read [Tooling](docs/tooling.md) for command behavior and current limitations.
The generated standard-library reference starts at
[`docs/api/README.md`](docs/api/README.md).

## Documentation

The hosted site is [eluvane.github.io/ouro](https://eluvane.github.io/ouro/).
Start with the [documentation index](docs/README.md). The main paths are:

- [Getting started](docs/getting_started.md)
- [Language syntax](docs/syntax.md) and [design goals](docs/design.md)
- [Tooling](docs/tooling.md) and [packages](docs/pkg.md)
- [Architecture](docs/architecture.md), [compiler checking](docs/kernel_design.md),
  and [trusted computing base](docs/tcb.md)
- [Contributing](CONTRIBUTING.md)

Runnable examples live under `samples/tutorial/`, `samples/examples/`,
`samples/scientific/`, and `samples/bioinformatics/`.

## Repository map

`compiler/` contains the Ouro compiler; `compiler/stage0/` contains its generated
bootstrap inputs. `runtime/` owns the transitional C host and Ouro runtime
implementations, and `std/` the standard library. Tools live in `tools/`,
handwritten regression fixtures in `tests/`, policy and generated-test data in
`quality/`, and host orchestration in `scripts/`. User examples stay in `samples/`.
See [Architecture](docs/architecture.md#repository-map) for ownership details.

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains the
build, test, RFC, generated-artifact, and pull-request workflow.
Trust-sensitive changes should also run
`python3 scripts/kernel_hardening_suite.py`.

## License

Ouro is licensed under the [Apache License 2.0](LICENSE).

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
