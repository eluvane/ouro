# Ergonomic syntax

Grouped imports, positional calls, typed local helpers, pure expression
blocks, list trailing commas, and final-tail list spreads lower to existing
checked constructors. The
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
When imported short names collide in a reached graph using aliases or
selective imports, a bare use without a local binder, current-file declaration,
or local open requires qualification. A plain-only graph still rejects
duplicate declarations. [Module syntax](../syntax.md#modules-and-imports)
defines exposing clauses, local names, and scoped opens.

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
allocation, implicit argument for ordinary functions, hidden conversion, or effect handler.
Each application node is checked by the existing dependent-function checker.
Except for opt-in marked constructors described below, type parameters remain
ordinary explicit arguments, for example
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
f(host = value)   -- `=` is not a named-argument marker
```

A non-function callee, a wrong argument type, an unresolved hole, or a missing
required argument still fails ordinary checking. The form `f(a b)` deliberately
remains one argument: changing that would break existing application syntax.
No new binders are introduced, and argument evaluation/effects follow the
same nested `EApp` tree as ordinary application.

## Named calls and public labels

A top-level definition can give a parameter a public call label distinct from
its internal binder. The `=>` in a typed binder group is contextual; ordinary
identifiers, including `as`, retain their existing meaning:

```ouro
def choose (front => first : Nat) (back : Nat) : Nat := first;

choose(back := 2, front := 1)
let front : Nat := 1 in choose(front :=, back := 2)
```

`host :=` is shorthand for `host := host` in the caller's lexical scope.
Unlabeled parameters use their binder spelling as the public label. A named
call may start with positional arguments, followed by labeled arguments in any
order. It must supply every declared parameter exactly once. The compiler
rejects missing, duplicate, unknown, or ambiguous labels and positional
arguments after a named argument. Ordinary positional full and partial calls
retain their meaning, including for definitions with public labels or marked
type parameters.

This first form applies only to direct, resolved top-level definitions with no
marked parameters and independent parameter domains. A local or higher-order
callee, a parameter domain depending on an earlier parameter, or an ambiguous
domain needs a positional call. Declaration-site defaults are not accepted.
Argument values are lowered once in source order into fresh local lets; the
final ordinary application uses declaration order. The existing checker proves
every argument and the result. A call label has no binding effect on the value
expression, and a local value shadowing the definition does not inherit its
labels. Unqualified label spelling remains stable when the definition is
referred to through a module alias.

Quality analysis reads only argument values as expressions. Clippy retains
known-callee effect and checked-result obligations for named calls while
using unknown positional facts for argument-specific proofs; exact
argument-position precision requires declaration metadata in that analyzer.

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

## Expected types in short lambdas

The existing `fun x => body` and `fun x y => body` forms use an expected
function type when one is available, for example from a definition, an
annotated local value, or a typed function argument. Lowering also uses each
known parameter type inside the body, so a callback through an unannotated
parameter can retain the type needed by a nested callback or parameterized
match:

```ouro
let apply : ((Nat -> List Nat) -> List Nat) -> List Nat :=
  fun consume => consume (fun value => [value])
in apply (fun (callback : Nat -> List Nat) => callback 0)
```

The checker still validates the complete function and every application.
For dependent function types, the expected codomain follows the lambda's
actual binder name. If renaming could capture another binder, or a domain
contains a hole, an unresolved name, or a shadowed local type name, lowering
does not use that hint; annotate the relevant lambda parameter. An
unannotated lambda without an expected function type still needs an
annotation. Parameterized local helpers still require typed parameters.

## Marked constructor parameters

An inductive family may mark a **leading** prefix of its universe parameters:

```ouro
inductive Box {A : Type} : Type :=
  | MkBox : A -> Box A;

def value : Box Nat := MkBox Z;
def explicit : Box Nat := MkBox Nat Z;
```

The `{A : Type}` group is an opt-in declaration marker. It binds `A` just
like an ordinary parameter and is retained as metadata through parsing and
constructor lookup. Several leading groups may be marked; later ordinary
`(B : Type)` parameters remain explicit. Marked groups must precede all
ordinary parameters and have universe level zero (`Type` or `Type0`). Indexed families
cannot use the marker in this first slice.

With an expected result, the omitted prefix is inserted when that result
is a direct application of the constructor's own family with every family
parameter supplied, and the source supplies exactly the remaining family
parameters and constructor fields. For example, `MkBox Z` at expected
`Box Nat` becomes the ordinary checked call `MkBox Nat Z`.

Without an expected result, a saturated `MkBox Z` can also infer `A` from
the type of `Z`, including in an unannotated local binding. This narrower
rule requires **all** family parameters to be marked, at least one constructor
field, a reliable `Type0` hint for the first value, and one usable
value-type hint for each marked parameter. The first value cannot borrow a
hint from a later field; annotate it or supply the constructor parameters
when its type is unknown. A field contributes a hint only when its declared
type is directly that parameter;
`List A` does not trigger inference of `A`. Repeated direct fields must give
the same finite structural hint. Bound type names must have a known `Type0`
kind in scope; inductive applications and function types need a known `Type0`
shape. Holes, escaped or shadowed names, incomplete hints, and exhausted
scans provide no hint. A type-valued first argument is kept as an explicit
partial call.
Indexed, mixed marked/ordinary, and nullary constructors still need an
expected result or explicit parameters for omission.

Both paths insert ordinary constructor applications, and the compiler checker
checks the result and every argument. Explicit full and partial calls remain
valid. Local binders shadow global constructor names. This does not infer
parameters of ordinary definitions, search for instances, or solve arbitrary
type equations. Annotate the result or supply constructor parameters when
the bounded hints are unavailable.

## Marked definition parameters

A definition may opt in by marking a leading prefix of its source parameters:

```ouro
def apply {A : Type} {B : Type} (f : A -> B) (x : A) : B := f x;
def example : Nat := apply (fun (n : Nat) => n) Z;
def explicit : Nat := apply Nat Nat (fun (n : Nat) => n) Z;
```

Only leading `{A : Type}` groups are marked. Their domains must be `Type0`;
ordinary `(A : Type)` parameters stay explicit. The compiler stores both the
marked count and the number of declared parameter binders, so a function type
returned by the definition does not become another inferred source argument.

For an omitted prefix, the call must supply exactly the remaining declared
arguments. A known, non-universe type for its first value is required even
when an expected result exists; this keeps an explicit partial call such as
`apply Nat Nat` explicit. A definition with no remaining source arguments may
instead use a known expected result. Later argument types and the expected
result can contribute constraints for the marked parameters.

The bounded matcher recognizes direct marked type variables, known inductive
or constant heads, their applications, and nondependent function types.
For example, a callback of type `Nat -> Bool` and a `List Nat` argument can
determine `A = Nat` and `B = Bool` in a marked map-like definition. Different
names for unused callback binders are accepted. Dependent callback types,
unknown or shadowed hints, holes, conflicting constraints, and partially
supplied value arguments need explicit type arguments or an annotation. This
does not infer omitted parameters of unmarked definitions or invent a type
parameter from an unknown name.

Lowering inserts ordinary applications in source argument order. The compiler
checker validates the resulting function call and every source argument;
source values occur once in the emitted term. Existing explicit full and
partial calls remain valid. The standard definitions and constructors that
still use ordinary `(A : Type)` declarations retain explicit arguments.

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

## List spreads

```text
[first, second, ..rest]  ==  Cons A first (Cons A second rest)
[..rest,]                ==  rest
```

The only spread marker is `..` before one final list tail. The parser makes
an `EListSpread` rather than inserting a call to a user-defined `append`.
Lowering requires the registered nominal `List A` constructor family and
checks every prefix value and the tail at that exact type. When no expected
type is present, a complete type hint from the tail may establish `List A`.
Each prefix value and the tail receive a fresh typed local binding in source
order; fresh IDs exceed the source tree and lowered terms, including IDs in
direct AST inputs. The resulting constructor spine reuses the original tail.
No spread is accepted outside list brackets, and extra elements after the
tail, a second spread, or a second trailing comma are rejected.

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
Imported record updates have an [annotation provenance limit](../syntax.md#records).

## Typed fallible blocks

```ouro
let? (Left, Right) : Either Error Value do
  let first : Item := loadFirst?;
  let second : Item := loadSecond?;
  combine first second
end
```

`let?` is contextual syntax after `let`; `result` and `maybe` remain ordinary
identifiers. The header gives the whole result type and names its failure and
success constructors **in that order**. The type must be a direct application
of a checked two-constructor inductive family. A Result-shaped family has
`E` and `A` parameters, with one-argument failure and success constructors;
a Maybe-shaped family has an `A` parameter, a nullary failure constructor,
and a one-argument success constructor. The header's order defines the roles;
the names are resolved as actual constructors, even when a local term binder
uses the same spelling. The declared order and constructor spelling do not
choose the roles. The checker validates their complete types and every
expanded branch. Standard-library `Either E A`
and `Maybe A` have these shapes; a separate `Result` type is not required.

Within the block, `let x : B := e?;` evaluates `e` as the same family with
payload `B`. Failure immediately returns the header's failure constructor;
success binds its payload to `x` for the rest of the block. The annotation
may be omitted when the existing bounded surface hint can identify `B` from
`e`. An ambiguous payload needs an explicit annotation. A standalone `e?;`
discards its successful payload. Ordinary local `let` bindings are also
allowed. The mandatory final expression is the success payload and is wrapped
in the header's success constructor. A final `e?` returns the checked
container directly. There is no automatic conversion between error types.
The bounded lowering rejects a local binding that reuses an outer type name
referenced by the block header, avoiding capture of that type in the result.

Only a postfix `?` at the root of a block binding's value, a standalone
statement, or the final expression propagates. A `?` nested inside an
application, lambda, `do`, or a nested block belongs to that expression's own
boundary and does not escape into the enclosing block. Nested fallible blocks
must state their own header. Bare `?` outside propagation and all unresolved
named or anonymous holes remain rejected. Empty blocks, missing final
expressions, and trailing semicolons are rejected. The block lowers to
ordinary checked `case`, constructor applications, and local lets; it adds no
new kernel form or effect handler.

## Integration and fixtures

Grouped imports, calls, local helpers, pure expression blocks, and list syntax
reuse existing `DImport`, `EApp`, `EAscribe`, `ELam`, `EPi`, `ELet`, and `EList`
nodes. Typed fallible blocks retain a frontend node until lowering verifies
their constructor roles. The formatter retains the source spelling of these
forms. The fixture inventory is
`tests/language_ergonomics/cases.json`; it includes desugaring pairs,
rejected forms, import graph/diagnostic cases, and formatter round trips.
[CI](../ci.md#local-profiles) owns validation commands and gate status.

## Scope

These forms add no private exports, re-exports, tuple allocation,
declaration-site defaults, early return, or general effect handling. For language direction and
compatibility, see [Design](../design.md#language-direction) and
[Stability](../stability.md#experimental-areas).

## Compatibility

Lint, strict quality, and analyzer import inventories read every operand,
including multiline groups. Malformed import scans return an input error.
The [bootstrap bridge](../build.md#c-bootstrap) supports grouped imports,
calls, and helpers without rewriting the current source snapshot. Compiler
bootstrap inputs do not use list trailing commas or spreads; the new parser
accepts them after bootstrapping.

`f (a b)` remains one argument; `f (a, b)` denotes two applications, regardless
of whitespace. Grouped imports cannot carry aliases. Empty `f()` calls and
recursive local helpers remain
unsupported. Live LSP range/navigation behavior requires its own verification;
AST reuse alone does not establish editor behavior. The dedicated parser,
formatter, frontend/security, Clippy, bootstrap, and PR gates remain required
for toolchain acceptance; [CI](../ci.md#local-profiles) owns the maintained
validation commands.
