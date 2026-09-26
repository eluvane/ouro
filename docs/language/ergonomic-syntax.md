# Ergonomic syntax

Grouped imports, positional calls, typed local helpers, pure expression
blocks, and list trailing commas lower to existing syntax nodes. The
maintained [syntax reference](../syntax.md) states accepted forms; this page
records desugaring and compatibility boundaries.

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

The existing alias implementation is a source rewrite over a flattened
namespace, not compiler-owned module identity. Aliases therefore remain on
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

The legacy alias boundary now explicitly rejects a comma after an alias,
including across comments, with the existing `OURO-IMP-001` diagnostic. Without
that rejection, erasing `as A` could accidentally grant meaning to a mixed
group. This guard is not the implementation of grouped imports: acceptance of
plain groups belongs to the declaration parser. Compiler-owned alias scoping,
qualification, and shadowing are not provided by this syntax.

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

## Pure expression blocks

```ouro
let {
  let base : Nat := value;
  let double (x : Nat) := add x x;
  double base
}
```

The contextual `let {` opener begins an expression block. The block has zero
or more semicolon-terminated local bindings and one mandatory final expression
without a trailing semicolon. The bindings use the ordinary local `let` grammar,
including optional annotations and typed helper parameters. Each binding scopes
over the following bindings and final expression, but not over its own value.
The example lowers to:

```ouro
let base : Nat := value in
let double (x : Nat) := add x x in
double base
```

The parser constructs nested `ELet` nodes; it does not introduce an AST or
checker form. The final expression may itself be a nested block or an ordinary
`let ... in` expression. Values and final expressions keep their usual typing
rules, including when their type is `IO A`. A block does not sequence actions:
standalone expression statements and `let!` are not accepted. Use `do` for
effectful sequencing. Empty blocks, missing final expressions, and a final
semicolon are rejected. Unresolved holes retain their ordinary rejection.

The opener is distinguished from record braces by the preceding `let`.
Ordinary record syntax and existing identifiers such as `block`, `result`,
and `maybe` keep their meanings. Comments and multiline layout are allowed
between tokens. Record literals inside a block still need the same supported
type context as record literals elsewhere.

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

## Record field punning

```ouro
{ x, y := next }  -- the x field uses the variable x
```

A record literal still needs a known nominal record type. A bare field name
uses the value with that name in the enclosing lexical scope; it does not
introduce a binder. The record preprocessor expands it to the same constructor
argument as `x := x`, preserving declaration field order. Missing, duplicate,
and unknown fields remain errors.

## Functional record update

```ouro
{ person with age := next_age, active := True }
```

With a known nominal result type, update checks the base as that record type,
binds it once, then binds changed values in source order. It constructs the new
record in declaration field order, reading omitted fields from the bound base.
Unknown and repeated fields are errors. A bare update name without `:=` is not
an assignment. Paths through nominal record fields, such as
`{ person with address.city := next_city, address.zip := next_zip }`, rebuild
each affected nested record. Sibling paths are accepted; exact duplicates and
ancestor/descendant overlaps are errors. Changed right-hand sides are bound
once in source order. A typed local binding, record-valued field, or explicit
literal ascription `({ city := next_city, zip := saved_zip } : Address)` supplies a nominal
expected type for that value. It does not infer a type for arbitrary call
arguments. Updates without nominal context and dependent record fields remain
unsupported.

## Integration and fixtures

These forms reuse existing `DImport`, `EApp`, `EAscribe`, `ELam`, `EPi`,
`ELet`, and `EList` nodes. The formatter retains grouped imports, call
spelling, compact local helpers, block spelling, and list commas without
expanding them in source. The fixture inventory
is `tests/language_ergonomics/cases.json`; it includes desugaring pairs,
rejected forms, import graph/diagnostic cases, and formatter round trips.
[CI](../ci.md#local-profiles) owns validation commands and gate status.

## Scope

These forms add no module identity, tuple or named call syntax, implicit type
argument inference, early return, or general effect handling. Aliases remain
the existing flattened-namespace source rewrite. For language direction and
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
