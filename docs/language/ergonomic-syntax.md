# Ergonomic syntax

Grouped imports, positional calls, typed local helpers, and list trailing
commas lower to existing syntax nodes. The maintained
[syntax reference](../syntax.md) states accepted
forms; this page records desugaring and compatibility boundaries.

## Grouped imports

```text
import "std/io.ouro", "std/string.ouro", "std/listx.ouro";
import
  "std/io.ouro", -- comments remain source text
  "std/string.ouro",
;
```

A group requires at least one quoted path. Subsequent paths are separated by
commas. A trailing comma is allowed only before the terminating semicolon,
ignoring whitespace and line comments. The historical optional semicolon
remains accepted when there is no trailing comma.

The declaration parser produces an ordered list of ordinary `DImport` nodes:

```text
import "a.ouro", "b.ouro";
==
import "a.ouro";
import "b.ouro";
```

This is AST construction, not splitting or rewriting source lines. Each path
retains its interned identity; canonicalization, module closure checking,
visited-path deduplication, and cycle detection remain with their existing
owners. The group does not introduce a scope or change export visibility.
Duplicate paths remain present in the parsed declarations; dependency traversal
continues to load each canonical path once. Both fast and preprocessed dependency
collection paths discover every operand, including the second edge of a cycle.

Aliases bind the directly imported source unit. Qualification is resolved by
the compiler before the complete import closure is checked. Aliases remain on
separate single-path declarations:

```text
import "a.ouro" as A;
import "b.ouro", "c.ouro";
```

The following forms are rejected:

```text
import;
import "a.ouro",,
import "a.ouro", unquoted;
import "a.ouro",                 -- EOF after a comma
import "a.ouro" as A, "b.ouro";
import "a.ouro" as A,;
```

The alias boundary explicitly rejects a comma after an alias,
including across comments, with the existing `OURO-IMP-001` diagnostic. Without
that rejection, erasing `as A` could accidentally grant meaning to a mixed
group. This guard is not the implementation of grouped imports: acceptance of
plain groups belongs to the declaration parser. An alias selects direct
declarations of its file; a transitive dependency needs its own direct import.
When imported short names collide in a reached graph using aliases, a bare use
without a local binder or current-file declaration requires qualification. A
plain-only graph still rejects duplicate declarations. Local
opens still erase their prefix and cannot resolve such a collision.

Dependency-tail diagnostics distinguish missing paths from malformed quoted
strings. The direct parser retains its existing positional `PErr` protocol;
exact error-position laws cover malformed groups. Richer parser messages and
LSP diagnostic-range verification remain outstanding.

## Positional parenthesized calls

```text
f(a, b)
f(
  a, -- first argument
  b,
)
```

A nonempty argument group after a callee expression lowers left-to-right to
ordinary application:

```text
f(a, b, c,) == ((f a) b) c
f(a,)       == f a
f(a)(b)     == (f a) b
x |> f(a,)  == (f a) x
```

The callee is an ordinary expression, including a local or higher-order value.
There is no method search, overload search, declaration-name lookup, tuple
allocation, implicit type argument, hidden conversion, or effect handler.
Each application node is checked by the existing dependent-function checker.
Type parameters remain ordinary explicit arguments, for example
`map(Nat, String, f, xs)` when that is the function's existing signature.

Existing `f (a)` and `f (a : T)` retain their meanings. Whitespace before the
opening parenthesis is not significant. Argument ascriptions are supported:
`f(a : A, b : B)` lowers to `f (a : A) (b : B)` through `EAscribe`.
Parentheses that are not in application position remain ordinary grouping;
`(a, b)` does not become a tuple.

Invalid examples:

```text
f()               -- no implicit Unit argument
f(, a)            -- missing first argument
f(a,, b)          -- missing middle argument
f(host = value)   -- named arguments are not enabled
```

A non-function callee, a wrong argument type, an unresolved hole, or a missing
required argument still fails ordinary checking. The form `f(a b)` deliberately
remains one argument: changing that would break existing application syntax.
No new binders are introduced, and argument evaluation/effects follow the
same nested `EApp` tree as ordinary application.

## Typed local helper declarations

```text
let double (x : Nat) := add x x in
  double value

let identity (A : Type) (x : A) : A := x in
  identity Nat value
```

A parameterized local binding requires typed parameters. Its result type may
be omitted when the checker can infer it from the helper value. It uses the
existing declaration telescope grammar, including grouped binders such as
`(x y : Nat)`. An explicitly annotated helper desugars as:

```text
let f (x : A) (y : B x) : C x y := value in body
==
let f : (x : A) -> (y : B x) -> C x y :=
  fun (x : A) (y : B x) => value
in body
```

Without a result annotation, `let f (x : A) := value in body` desugars to
`let f := fun (x : A) => value in body`. The existing local-binding inference
must infer the complete function type from the typed lambda. A body whose type
cannot be inferred still needs an annotation.

The parser uses `mk_pi_chain` for annotated helpers and
`mk_typed_lam_chain` for both forms, then constructs an ordinary `ELet`.
Earlier parameters scope over later parameter types, the optional result type,
and the helper value. Parameters do not escape into `body`.
The helper name scopes over `body`, not its own value. An identically spelled
outer binding remains available in that value, exactly as with ordinary `let`.
Recursion still requires explicit `fix` and the existing structural checks.

Invalid examples:

```text
let f x : Nat := x in f value
let f (x : Nat) := fun y => y in f value
let f (hidden : Nat) := hidden in hidden
```

The first lacks a parameter annotation; the second has an unannotated nested
lambda with no expected function type; the third uses an out-of-scope parameter.
Existing unparameterized `let` syntax and its inference behavior are unchanged.

## List literal trailing commas

```text
[x, y,] == [x, y]
[x,]    == [x]
```

After at least one element, a comma immediately before `]` is accepted,
including across whitespace and line comments. The parser builds the same
`EList` elements in the same order. `[,]`, `[x,,]`, and a missing `]` remain
parse errors. Empty lists keep the spelling `[]` and still need an expected
`List A` type.

## Integration and fixtures

These forms reuse existing `DImport`, `EApp`, `EAscribe`, `ELam`, `EPi`,
`ELet`, and `EList` nodes. The formatter retains grouped imports, call spelling,
compact local helpers, and list commas without expanding them in source. The
fixture inventory
is `tests/language_ergonomics/cases.json`; it includes desugaring pairs,
rejected forms, import graph/diagnostic cases, and formatter round trips.
[CI](../ci.md#local-profiles) owns validation commands and gate status.

## Scope

These forms add no selective imports, private exports, tuple or named call
syntax, implicit type argument inference, early return, or general effect
handling. For language direction and
compatibility, see [Design](../design.md#language-direction) and
[Stability](../stability.md#experimental-areas).

## Compatibility

Lint, strict quality, and analyzer import inventories read every operand,
including multiline groups. Malformed import scans return an input error.
The [bootstrap bridge](../build.md#c-bootstrap) supports grouped imports,
calls, and helpers without rewriting the current source snapshot. Compiler
bootstrap inputs do not use list trailing commas; the new parser accepts them
after bootstrapping.

`f (a b)` remains one argument; `f (a, b)` denotes two applications, regardless
of whitespace. Grouped imports cannot carry aliases. Empty `f()` calls,
named arguments, and recursive local helpers remain
unsupported. Live LSP range/navigation behavior requires its own verification;
AST reuse alone does not establish editor behavior. The dedicated parser,
formatter, frontend/security, Clippy, bootstrap, and PR gates remain required
for toolchain acceptance; [CI](../ci.md#local-profiles) owns the maintained
validation commands.
