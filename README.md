<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="site/public/ouro-horizontal-inverse.png">
    <source media="(prefers-color-scheme: light)" srcset="site/public/ouro-horizontal.png">
    <img src="site/public/ouro-horizontal.png" alt="Ouro" width="768">
  </picture>
</p>

Ouro is an experimental dependently typed language. Its compiler checks
programs and their imports before evaluation or native compilation. See the
[pre-1.0 compatibility policy](docs/stability.md) before adopting it.

This example defines addition by structural recursion and adds two natural
numbers.

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

Follow [Getting started](docs/getting_started.md) to build the toolchain and
evaluate `four`.

- [Language and tool documentation](docs/README.md)
- [Contribution workflow](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Ouro website](https://eluvane.github.io/ouro/)

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
