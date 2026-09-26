<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="site/public/ouro-horizontal-inverse.png">
    <source media="(prefers-color-scheme: light)" srcset="site/public/ouro-horizontal.png">
    <img src="site/public/ouro-horizontal.png" alt="Ouro" width="512">
  </picture>
</p>

Ouro is an experimental dependently typed programming language and toolchain
([pre-1.0 compatibility](docs/stability.md)).

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

## Quick start

- [Getting started](docs/getting_started.md) — install, check, evaluate, and run.
- [Documentation](docs/README.md) — language, tools, architecture, and roadmap.
- [Contributing](CONTRIBUTING.md) — development and submission workflow.
- [Website](https://eluvane.github.io/ouro/).

## License

Copyright © 2026 Eluvane. Ouro is source-available under the
[Mother of Licenses 1.0](LICENSE) (`LicenseRef-MoL-1.0`), starting with the first
repository revision containing this licensing notice. Earlier published releases
and revisions remain governed by their original licenses.

Official repository: [eluvane/ouro](https://github.com/eluvane/ouro).
Licensing contact: [keiko1337@proton.me](mailto:keiko1337@proton.me).

Third-party dependencies retain their own licenses. Phosphor icons in
`site/src/assets/phosphor/` remain under their
[MIT license](site/public/licenses/phosphor-LICENSE.txt).
