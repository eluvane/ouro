# Surface syntax

This page describes the source forms accepted by the current toolchain.
[Stability](stability.md) owns the pre-1.0 compatibility policy.

## Modules and imports

Source files are modules. Imports use paths relative to the importing file:

```ouro
import "../std/list.ouro";
import "nat_lib.ouro" as N;
```

Multiple plain paths can share a declaration, with an optional final comma
before `;`:

```ouro
import "../std/string.ouro", "../std/list.ouro",;
```

The parser expands the group into ordered imports. Aliases remain on separate
single-path declarations. [Ergonomic syntax](language/ergonomic-syntax.md#grouped-imports)
explains the desugaring and rejected forms.

An import alias qualifies names from the imported file:

```ouro
def two : N.Nat := N.S N.one;
```

Ouro currently uses a flat imported namespace. Import aliases and local opens
are bounded conveniences, not a full module system:

```ouro
def three : Nat := open N in add two one;
```

Top-level `open` declarations, selective imports, hidden exports, and nested
module declarations are not supported.

## Definitions and dependent functions

A definition names a term and its type:

```ouro
def id (A : Type) (x : A) : A := x;
def apply (A : Type) (B : A -> Type)
          (f : (x : A) -> B x) (x : A) : B x :=
  f x;
```

Function types use `->`. A named binder makes the result type dependent on the
argument:

```ouro
(x : A) -> B x
```

Lambdas and local bindings use:

```ouro
fun (x : A) => body
let x : A := value in body
```

A local helper can put its typed parameters next to its name:

```ouro
let twice (x : Nat) := add x x in twice 2
```

This is a non-recursive lambda-binding. Parameterized local helpers require
typed parameters; the result annotation may be omitted when the body type can
be inferred. [Ergonomic syntax](language/ergonomic-syntax.md#typed-local-helper-declarations)
explains their scope and desugaring.

## Inductive data and pattern matching

```ouro
inductive Nat : Type :=
  | Z : Nat
  | S : Nat -> Nat;

def pred (n : Nat) : Nat :=
  match n with
  | Z => Z
  | S k => k
  end;
```

Matches are constructor-based. The current implementation does not provide the
full pattern language of a mature functional language; advanced patterns,
or-patterns, and general wildcard exhaustiveness are outside the maintained
surface.

## Structural recursion

Recursive definitions use an explicit `fix`:

```ouro
def add : Nat -> Nat -> Nat :=
  fix add (n : Nat) (m : Nat) : Nat :=
    match n with
    | Z => m
    | S k => S (add k m)
    end;
```

The compiler checker verifies structural recursion metadata and decreasing
arguments. General unrestricted recursion is not part of the supported Core.

## Universes, axioms, and holes

`Type` classifies ordinary types. The core has universe levels; the surface
keeps the common case compact.

```ouro
axiom externalValue : Nat;
```

Axioms are explicit trusted assumptions. They are not ordinary implementations.

Anonymous holes use `_`; named holes use `?name`:

```ouro
def pending : Nat := ?result;
```

The frontend can report goals for holes, but unresolved holes are rejected by
the packaged checking path. They belong in tutorials and negative fixtures, not
released code.

## Experimental native declarations

`intrinsic` and `extern` declare globals without Ouro bodies, with checked
signatures and explicit native metadata. They are reserved keywords outside
strings and comments. Declaration checking establishes the binding's contract;
the selected backend must also implement it. The experimental Windows backend
supports the operations described in [Architecture](architecture.md#backends-and-runtime)
and rejects unsupported bindings before producing an executable.

```ouro
intrinsic U32 : Type := "ouro.u32";
intrinsic Runtime : Type -> Type := "ouro.runtime";
extern get_pid : Runtime U32 := "windows-x86_64" "win64" "kernel32.dll" "GetCurrentProcessId" "maygc";
```

An intrinsic has one quoted registry key, optionally followed by one
specialization expression before `;`. The specialization is type metadata,
with ordinary name resolution; it is not an executable body. The declared name
alone does not select a primitive.

`ouro.raw.load` and `ouro.raw.store` require a concrete storage specialization.
It must resolve to a registered machine word, raw pointer, or typed raw function
pointer; ordinary inductives, managed values, and closures cannot be loaded or
stored through a generic `(A : Type)` declaration. The operations return
`Runtime` actions. For example, after the declarations above:

```ouro
intrinsic Ptr : Type -> Type := "ouro.raw_ptr";
intrinsic read_word : Ptr U32 -> Runtime U32 := "ouro.raw.load" (U32);
```

The checker preserves the normalized specialization, including through type
aliases. A pointer specialization stores an address; it does not make the
pointed-to object a scalar or establish its lifetime or alignment.

An extern has exactly five quoted fields, in order: target, calling convention,
library, symbol, and GC policy. The initial checked target and convention are
`windows-x86_64` and `win64`; GC policy is `maygc` or `nogc`. Unknown field values
remain intact through parsing so the declaration checker can report an
unsupported value. Missing or extra fields, unquoted metadata, and a missing
final `;` are parse errors. Variadic extern syntax is not supported.

Both forms use the same declaration parser in roots and imports. Their
signatures and intrinsic specializations retain references for facts and lint;
the analysis unit treats them as opaque declarations without body ASTs.

`representation` assigns a native role to an inductive that has already been
checked. It declares no global name or executable body:

```ouro
inductive Natural : Type :=
  | Zero : Natural
  | Succ : Natural -> Natural;
representation Natural := "ouro.nat";
```

The target uses ordinary import alias and local-open resolution. The checker
checks the inductive's shape and rejects duplicate role assignments. The
initial role keys are `ouro.nat`, `ouro.bool`, `ouro.unit`, `ouro.list`,
`ouro.maybe`, and `ouro.pair`. Parsing retains unknown keys for checker
diagnostics. Exactly one quoted key and a final `;` are required; a type
signature or expression body is not part of this annotation. `representation`
is a reserved keyword, and the target remains a reference for facts and lint.

The standard library and raw runtime use the same registered data types.
`IO A` is a transparent alias of `Runtime A`; `io_pure`, `io_bind`, and `do`
retain their standard-library surface. Native managed `main` can return `U32`,
`Runtime U32`, or `IO Unit`. A pure Unit value is not a native entry action.
Runtime loops and effects do not unfold during type conversion.

## Numbers and strings

Natural-number literals elaborate to the current `Nat` representation:

```ouro
def two : Nat := 2;
```

String literals support `\n`, `\t`, `\r`, `\"`, and `\\` escapes:

```ouro
def message : String := "hello\n";
```

Import `std/string.ouro` to use the standard `String` type and helpers. A
standalone prelude must declare `intrinsic String : Type := "ouro.string";`.
An opaque `axiom String : Type;` does not authenticate string literals, even
when its name is `String`. Transparent aliases of the registered type work.

Declaration checking resolves literal-table entries to byte sequences before
accepting Core. Missing entries, unresolved literal IDs, and bytes outside
`0..255` are explicit errors. Literal equality preserves every byte, including
embedded NUL; lengths and slice offsets count bytes, so UTF-8 characters can
occupy more than one position.

Type conversion evaluates registered pure String intrinsics on concrete
arguments. Their checked bindings select the operation, and `representation`
bindings select its Nat, Bool, List, and Maybe results. Transparent aliases keep
those identities. Ordinary axioms, externs, and Runtime operations stay neutral
during conversion.

The [runtime contract](effects_design.md#runtime-surface) covers host IO and
embedded-NUL limits.

## Lists

List literals use an expected `List A` type when one is available:

```ouro
def values : List Nat := [Z, S Z, S (S Z)];
def empty : List Nat := [];
```

A nonempty literal without an expected type can infer its element type from
its first element. Later elements must have that type:

```ouro
def inferred : List Nat := let values := [Z, S Z] in values;
def nested : List (List Nat) := let rows := [[Z], []] in rows;
```

A local type ascription can provide the expected element type:

```ouro
def count : Nat := (([Z, S Z] : List Nat) |> length Nat);
```

Untyped `[]` still requires context. If the first element has no inferable
type, annotate the literal or binding; later elements do not resolve it.
This is a bounded first-element hint, not general type unification. A free
local type name shadowed by a later binding also needs an explicit `List A`
annotation so the earlier type is not rebound under the later name.
Heterogeneous lists and trailing commas are rejected. List literals lower to
the standard `Nil` and `Cons` constructors, and the compiler checks every
element against the selected type.

## Records

Records are a bounded surface form over a single-constructor inductive type and
generated accessors:

```ouro
record Point : Type where
  x : Nat;
  y : Nat;
end;

def origin : Point := { x := Z, y := Z };
def originX : Nat := origin.x;
```

The default constructor is `MkPoint`; generated accessor names use
`Point_x`, `Point_y`, and so on. Record literals require a known record type,
and every field must appear exactly once.

Record update, record pattern matching, anonymous records, row polymorphism,
subtyping, and overloaded field resolution are not implemented.

## Application and the pipe operator

Application is whitespace-separated:

```ouro
f x y
```

Positional arguments may also be comma-separated inside parentheses:

```ouro
f(x, y,)
```

This is left-associated application; a trailing comma is optional.
`f (x y)` still passes one argument, while `f()` is rejected. See
[Ergonomic syntax](language/ergonomic-syntax.md#positional-parenthesized-calls)
for desugaring and compatibility details.

The forward pipe appends its left-hand value as the final argument of the
application on the right:

```ouro
x |> f       -- f x
x |> f a     -- f a x
x |> f |> g  -- g (f x)
```

Use `|>` when the data flow is clearer than nested application and the final
argument convention is obvious.

## IO and `do`

Runnable programs export `main : IO Unit`. The maintained `do` subset supports
sequencing and `let!` binding:

```ouro
def echo : IO Unit :=
  do let! line := readLine;
     println line
```

`do let!` is valid only inside a `do` expression. The older `<-` binding
spelling is not accepted by the strict project profile.

## Effects and handlers

The repository contains a narrow one-shot `effect`, `perform`, and `handle`
slice used by examples and fixtures. It is experimental and does not constitute
a general algebraic-effects implementation.

See [Effects and IO](effects_design.md) for the supported shape and runtime
boundary.

## Comments and declarations

Line comments begin with `--`:

```ouro
-- A normal comment.
-- @entry main
```

`-- @entry` marks a root for repository analyzers; it does not change the term's
type.

Top-level declarations end with `;`. Constructor arms inside an inductive
declaration do not require a trailing semicolon per arm.

## Current limits

The [design goals](design.md#language-direction) and
[stability policy](stability.md#experimental-areas) describe planned and
experimental language areas. Record updates, unrestricted recursion, implicit
arguments, and type classes are outside this surface.
