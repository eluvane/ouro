# Writing good Ouro

A practical handbook for programmers, coding agents, and reviewers.

**Repository:** `eluvane/ouro` · **Revision:** `182f7210c0e989cd7526b54e6c6a1a58f774134b` · **Reviewed:** 2026-09-30.

This guide describes the `main` snapshot above, not an imagined future language. Ouro is pre-1.0: pin the compiler and standard library together, and recheck programs when upgrading. All repository links below are pinned to the reviewed revision. See the [compatibility policy][stability].

**Verification boundary.** Recommendations were checked against the language contracts, compiler and tool implementations, standard-library source, maintained samples, and focused fixtures. The examples were source-audited, **not compiled or executed in this session**: a runnable toolchain could not be obtained in the execution environment. Illustrative results below describe the reviewed implementation, not newly measured runs.

**Reading code examples.** Unless a block states otherwise, examples are separate modules placed one directory below the repository root, so `import "../std/...";` resolves. Do not concatenate all examples: some intentionally compare alternative declarations with the same responsibility. Adjust relative imports for your own layout. Expression-only examples identify their required scope. Names declared in examples are application code, not claimed standard-library APIs.

“Prefer” states a recommendation. “Requires” or “rejects” states the reviewed language or tool contract. Implementation-specific limitations and performance observations are labeled where they matter.

## Contents

1. [The working mental model](#1-the-working-mental-model)
2. [Modules, visibility, and dependency direction](#2-modules-visibility-and-dependency-direction)
3. [Imports that preserve ownership](#3-imports-that-preserve-ownership)
4. [Names and public interfaces](#4-names-and-public-interfaces)
5. [Functions, annotations, and argument inference](#5-functions-annotations-and-argument-inference)
6. [Local structure: let, blocks, where, and pipes](#6-local-structure-let-blocks-where-and-pipes)
7. [Data modeling without unnecessary proofs](#7-data-modeling-without-unnecessary-proofs)
8. [Pattern matching](#8-pattern-matching)
9. [Structural recursion that the checker can see](#9-structural-recursion-that-the-checker-can-see)
10. [Dependent types where they earn their cost](#10-dependent-types-where-they-earn-their-cost)
11. [Effects and IO boundaries](#11-effects-and-io-boundaries)
12. [Errors, propagation, and validation](#12-errors-propagation-and-validation)
13. [A practical standard-library map](#13-a-practical-standard-library-map)
14. [Collections, iteration, and ranges](#14-collections-iteration-and-ranges)
15. [Strings, Unicode scalars, and bytes](#15-strings-unicode-scalars-and-bytes)
16. [Filesystem and process programs](#16-filesystem-and-process-programs)
17. [A small CLI with honest failure behavior](#17-a-small-cli-with-honest-failure-behavior)
18. [Performance: remove demonstrated work](#18-performance-remove-demonstrated-work)
19. [Comments, documentation, and directives](#19-comments-documentation-and-directives)
20. [Formatting, linting, fixing, and the development loop](#20-formatting-linting-fixing-and-the-development-loop)
21. [Testing programs, not just acceptance](#21-testing-programs-not-just-acceptance)
22. [Project organization and packages](#22-project-organization-and-packages)
23. [Compact cookbook](#23-compact-cookbook)
24. [Common Ouro anti-patterns](#24-common-ouro-anti-patterns)
25. [Rules for AI-generated Ouro](#25-rules-for-ai-generated-ouro)
26. [Quick reference](#26-quick-reference)
27. [Code-review checklist](#27-code-review-checklist)

## 1. The working mental model

Write a small typed computation first; put parsing, process execution, files, and reporting around it. This fits the actual separation between ordinary checked terms and `IO`/`Runtime` actions, rather than merely imposing a functional style. [Checking][checking] · [IO][effects]

The consequences that matter in daily work are these:

| Property | Consequence for program design |
| --- | --- |
| Dependent function types and indexed inductives | An argument can determine a later argument's type or the result type. Add that dependency only when callers benefit from the enforced relationship. |
| Checked inductives, cases, and structural fixpoints | Constructor ownership, coverage, branch types, positivity, and recursive descent matter. A plausible-looking match or recursive call is not enough. |
| Ordered declarations and checked import closures | Arrange dependencies before their consumers. An unused import or private helper is not an escape from checking. |
| Effects represented as actions | Constructing an `IO A` value is different from executing it. Separate pure validation from action sequencing. |
| `Maybe` and `Either` as ordinary data | Failure policy is explicit, but not every result is automatically must-use. You still have to handle domain failures correctly. |
| Bounded compiler operations | A resource-limit diagnostic is not a proof that the source is ill typed, and it is not successful partial checking either. |

The current declaration checker lives in `compiler/file_elab.ouro`; the former independent OCaml and Python Core checkers are retired. Compiler checking is not the same thing as passing lint, generating a native image, or proving that a program does what its specification intended. The repository does not claim a complete machine-checked proof of checker soundness. Do not describe ordinary Ouro application code as automatically verified for runtime resource safety, host behavior, security, or business correctness. [Checker boundary][checking]

Likewise, structural recursion does not mean “cheap,” and returning `IO Unit` does not mean an action cannot fail. Keep these boundaries visible in APIs and tests.

## 2. Modules, visibility, and dependency direction

A source file is the practical module boundary. Prefer one coherent responsibility: a domain model, a decoder, a collection algorithm, or a filesystem adapter. Split a file when another consumer needs a stable part of it, when imports are widening unnecessarily, or when unrelated change reasons have accumulated. Do not split every five-line helper into a file. [Module syntax][syntax] · [Repository conventions][agents]

Declarations are public by default. Mark an implementation detail `private`; an underscore is not a visibility modifier.

```ouro
import "../std/text.ouro";

private def normalized_key (text : String) : String :=
  str_lower (str_trim text);

def same_key (left : String) (right : String) : Bool :=
  str_eq (normalized_key left) (normalized_key right);
```

The helper's visibility is the meaningful improvement here. A consumer should depend on the comparison policy, not its temporary normalization helper. Removing the helper would also be reasonable if the expression were genuinely clearer inline; privacy is not a reason to create wrappers.

Use a local helper when it belongs to one definition. Use a private top-level helper when several definitions in the file share the implementation. Use a public declaration when another module should deliberately depend on its contract.

`private` also applies to inductives, records, effects, axioms, intrinsics, and externs. A private inductive hides its constructors; a private record hides its generated constructor and accessors; a private effect hides its operations. The declarations still participate in checking. Privacy prevents source-level access from consumers; it does not remove a dependency or prove an abstraction correct. [Visibility contract][syntax]

A useful dependency direction is:

```text
shared domain types
        ↑
pure decoding / validation / transformations
        ↑
filesystem or process adapters
        ↑
CLI entry point and diagnostic rendering
```

Here arrows mean “is imported by.” A domain type should not need the CLI module that prints it. Import the small `std/types.ouro` for shared data declarations, or `std/prelude.ouro` for basic functions, rather than pulling in platform IO through a convenience umbrella. This follows the standard library's actual small-core layering. [Shared types][types] · [Prelude][prelude]

## 3. Imports that preserve ownership

An alias names the **directly imported file**, not every declaration in that file's transitive closure. Selective imports restrict visibility, including qualified access. These details are easy to get wrong when transferring habits from another language. [Import contract][syntax] · [Lowering and examples][ergonomics]

### Choose the smallest useful form

```ouro
import "../std/prelude.ouro";
import "../std/listx.ouro" as Lists exposing (foldl as fold);

def sum_values (values : List Nat) : Nat :=
  fold Nat Nat add 0 values;
```

In that module:

| Expression or name | Meaning |
| --- | --- |
| `fold` | The selected local name for `foldl`. |
| `Lists.foldl` | The original member name, qualified by its owner. |
| `Lists.fold` | Not a member created by the local rename. |
| `Lists.reverse_lin` | Not available through this selective import: it was not exposed. |
| `Lists.Nat` | Not a way to reach a declaration owned by a transitive dependency. |

The last three rows describe invalid references, not alternate spellings. Import a declaration's owner directly when you need to qualify it.

A plain import is reasonable when its visible surface is small and unambiguous. An alias is useful when ownership matters or short names collide. An `exposing (...)` clause is useful when a module has a large public surface but the consumer needs a small part. `exposing ()` selects no declarations; it does not skip checking the dependency.

Importing a type does not automatically select all its constructors or record accessors. Select the members needed by the intended source forms. Do not treat record sugar as a way around visibility.

### Keep opens local

```ouro
import "../std/prelude.ouro";
import "../std/listx.ouro" as Lists;

def sum_values (values : List Nat) : Nat :=
  open Lists in foldl Nat Nat add 0 values;
```

Use `open Alias in expression` for a small expression with several references to the same owner. Qualification is clearer when only one name is needed. The legacy top-level `open Alias;` form is erased; it is not a substitute for a scoped open and does not resolve collisions. [Scoped opens][syntax]

For bare names, local binders and current-file declarations take precedence; the innermost scoped open can choose an imported member; otherwise an imported short name must be unambiguous. A local binder does not retarget an explicit `Alias.member` reference.

Plain imports can expose transitive names. Aliased or selective graphs support qualification when imported names collide, while a plain-only graph still rejects duplicate declarations. Therefore “I do not use the colliding function” is not a reliable repair for a plain-only graph. Fix the import boundary rather than adding arbitrary spelling changes at call sites.

Grouped imports are only a compact form for plain imports:

```ouro
import "../std/io.ouro", "../std/text.ouro";
```

Keep aliases on separate single-path declarations. Do not combine an alias with a comma-separated import group, repeat the same canonical file with conflicting exposure clauses, or expect explicit re-export declarations that the current module system does not provide.

**Practical default:** start with direct task-specific imports; qualify where it prevents ambiguity; narrow exposure when it prevents accidental API dependence. An alias on every five-line example is not a virtue by itself.

## 4. Names and public interfaces

The maintained sources use a mixture of conventions: practical APIs such as `fs_read_checked`, `list_traverse_result`, and `cli_required_nat` use descriptive snake case; older APIs include `readLine`, `fromMaybe`, and `mapRight`; types and many constructors use capitalized names, while demonstration constructors such as `vnil` exist too. Follow the vocabulary of the owning module instead of inventing a universal rename campaign. [Types][types] · [IO][io] · [Results][result] · [Vectors][vec]

For new application code, descriptive snake-case functions and capitalized type/constructor names fit much of the practical surface. Treat that as a style choice, not parser law. Name constants for their meaning; do not invent a mandatory uppercase-constant convention.

Public names should remain searchable without reading the body. `decode_config`, `process_error_message`, and `count_nonblank` communicate roles better than `go2`, `handle`, or `do_it`. Short names remain useful for a tightly scoped accumulator or a mathematical binder. Private implementation names should still explain their job when the surrounding scope is large.

A prefix such as `_unused` communicates an intentional discard to the quality tools. Do not give a used value a discard name, and do not hide an unhandled error by renaming it `_result`. Those are different concerns. `_checked` is a library naming convention, not a magic compiler annotation; inspect the actual result and runtime contract. Current semantic Clippy does not establish obligations from the spelling alone. [Quality][quality] · [Semantic rule boundary][clippy]

Use suffixes such as `_message`, `_code`, `_checked`, `_or`, and `_or_else` consistently with neighboring APIs. A default-returning conversion and an error-preserving conversion should not have interchangeable names. A function that launches a process should not masquerade as a pure formatter.

Public argument labels are also API surface. Renaming a binder can break named calls unless the public label is kept separate; see the next section.

## 5. Functions, annotations, and argument inference

Give public definitions explicit parameter and result types. Use a result annotation to document the contract and provide an expected type for constructors, records, empty lists, and short lambdas. Omit local annotations when inference is unambiguous and the annotation only repeats the obvious. [Functions and local typing][syntax] · [Inference boundaries][ergonomics]

```ouro
import "../std/prelude.ouro";

def twice (value : Nat) : Nat := add value value;

def increment_all (values : List Nat) : List Nat :=
  map Nat Nat (fun value => S value) values;
```

The short lambda has an expected `Nat -> Nat` type from `map`. A standalone unannotated lambda with no expected function type does not acquire arbitrary inference. Write `fun (value : Nat) => ...` when that context is absent or fragile.

Ordinary generic parameters are explicit:

```ouro
import "../std/data.ouro";

def present : Maybe Nat := Just Nat 3;
def absent : Maybe Nat := Nothing Nat;
```

The standard `Maybe`, `List`, `Either`, and core helper declarations do not become implicitly polymorphic because another language would infer their parameters. Keep type arguments in the order of the actual signature.

A dependent signature is ordinary Ouro syntax:

```ouro
def apply_dependent (A : Type) (B : A -> Type)
    (function : (value : A) -> B value) (value : A) : B value :=
  function value;
```

Use this shape when the result really depends on the supplied value. A nondependent arrow is easier to call, compose, and use with the current named-call and inference conveniences when no such relationship exists.

### Marked parameters are opt-in, bounded inference

```ouro
import "../std/prelude.ouro";

def keep {A : Type} (value : A) : A := value;

def kept : Nat := keep 3;
def explicit_kept : Nat := keep Nat 3;
```

Only a leading prefix of type parameters at universe level zero (`Type`) can be marked in this slice. Definitions infer omitted parameters from supported argument/result hints at the required saturation; explicit full and partial calls remain available. Marked constructors have their own bounded rules, and the initial constructor slice excludes indexed families. This is not general implicit-argument search, type-class resolution, or arbitrary type unification. When a hint is unavailable, supply the types instead of fighting the elaborator. [Marked parameter contracts][ergonomics]

### Named calls for independent, direct top-level APIs

```ouro
import "../std/string.ouro";

def surround (prefix => left : String) (text : String)
    (suffix => right : String) : String :=
  str_concat left (str_concat text right);

def message : String :=
  surround(text := "ouro", suffix := "]", prefix := "[");
```

The public label `prefix` is independent of the internal binder `left`. The current form requires a directly resolved top-level definition with no marked parameters and independent parameter domains. It does not work as a generic named-call protocol for local functions or higher-order values.

A call may have a positional prefix followed by named arguments. Every declared argument must be supplied exactly once; positional arguments cannot follow a named one. `label :=` is shorthand for `label := label` in the caller's scope. There are no declaration-site defaults. Values are bound once in **source order**, then applied in declaration order. [Named calls][ergonomics]

Prefer names for genuinely confusable arguments, not for every two-argument mathematical operation. Use positional calls when dependency or higher-order use makes the named form unavailable.

## 6. Local structure: let, blocks, where, and pipes

Use the form that exposes the data flow with the least scaffolding. All three binding styles below lower to ordinary local bindings; none supplies implicit recursion. [Local syntax][ergonomics]

```ouro
import "../std/text.ouro";

-- One meaningful intermediate value.
def clean_key (input : String) : String :=
  let trimmed := str_trim input in
  str_lower trimmed;

-- A short sequence with several named intermediate values.
def display_key (input : String) : String :=
  let {
    let key := clean_key input;
    let wrap (value : String) : String := str_concat "key=" value;
    wrap key
  };

-- Main expression first; implementation helpers follow it.
def doubled_one : Nat :=
  double one where
    let one : Nat := 1;
    let double (value : Nat) : Nat := add value value;
  end;
```

An initializer sees outer bindings and earlier bindings, not its own newly introduced name or a later helper. Each helper's parameters stay inside that helper. `where` does not mean a mutually recursive declaration group.

A pure `let { ... }` block requires a final expression without a trailing semicolon. Its earlier bindings are semicolon-terminated. It cannot contain standalone action statements or `let!`; use `do` for that. A pure block can *return an IO action* without executing it.

A parameterized local helper needs typed parameters. Its result can be inferred when the body supplies enough information. Avoid shadowing a type name needed by a later annotation or a fallible block: bounded surface inference deliberately rejects some capture-prone shapes.

Name an intermediate when it records a domain step, avoids repeated work, preserves a needed type context, or is reused. Remove an unannotated `let result := expression in result` when it contributes none of those. Do not erase annotations or bindings that control constructor inference, evaluation, or sharing merely to reduce lines.

### Application, pipes, and callbacks

`f x y` and `f(x, y)` are the same curried application. The parenthesized form does not allocate a tuple. `f (x y)` is one argument; `f()` does not supply an implicit `Unit`.

The pipe supplies the **last** argument:

```ouro
import "../std/text.ouro";

def normalized_lines (input : String) : List String :=
  input |> str_lines |> map String String str_trim;
```

Use a pipe when that convention makes each step obvious. Do not simulate methods or placeholder arguments. A typed lambda is usually clearer than a pipeline whose argument positions require guesswork.

A supported trailing callback is `with_value(2) { value -> S value }` when `with_value` is a function taking a value and then a callback. It requires a nonempty positional call and one inferred callback binder; it is not general brace-block call syntax. Prefer an ordinary lambda when more elaborate parameter structure is needed. [Call forms][ergonomics]

## 7. Data modeling without unnecessary proofs

Use an inductive for a choice, a record for a fixed product, and a constructor carrying only the data valid for that case. Use a small nominal wrapper when confusing two otherwise identical types is a real risk. Do not build a hierarchy of wrappers whose only effect is forwarding arguments. [Inductives and records][syntax] · [Shared representations][types]

```ouro
import "../std/string.ouro";

inductive Destination : Type :=
  | ToStdout : Destination
  | ToFile : String -> Destination;

record Settings : Type where
  destination : Destination;
  verbose : Bool;
end;

def defaults : Settings :=
  { destination := ToStdout, verbose := False };

def verbose_defaults : Settings :=
  { defaults with verbose := True };
```

This avoids a `write_file : Bool` paired with a meaningless file path in the stdout case. It does **not** prove that the `ToFile` string is a valid path; validate at the filesystem boundary.

A type alias such as `def UserId : Type := Nat;` does not distinguish user identifiers from all other naturals. A new inductive does. Conversely, wrapping `Nat` in a constructor named `NonZero` does not prove nonzeroness when the constructor still accepts zero. Public smart constructors do not establish an invariant if consumers can also call an unchecked public constructor. Specify exactly which property the representation enforces.

Often an ordinary ADT is enough:

```ouro
import "../std/types.ouro";

inductive NonEmpty (A : Type) : Type :=
  | FirstAndRest : A -> List A -> NonEmpty A;

def first (A : Type) (values : NonEmpty A) : A :=
  match values with
  | FirstAndRest value _ => value
  end;
```

No length proof is needed to make `first` total on this representation. Use an indexed collection only when the exact length relationship matters to callers.

### Records: useful sugar, nominal boundaries

A `record Point` generates `MkPoint` and accessors such as `Point_x`. A literal needs a known nominal record type and every field exactly once; `{ x, y := next }` is supported field punning. An update constructs a new value; it is not mutation. [Record details][syntax]

Local field destructuring has a narrower contract than general pattern matching:

```ouro
import "../std/types.ouro";

record Point : Type where
  x : Nat;
  y : Nat;
end;

def point_x (point : Point) : Nat :=
  let { x } : Point := point in x;
```

That form requires a directly named **local** record, distinct selected fields, and an `in` body. Imported record destructuring, field renaming, and general record patterns are not supplied by this form. For an imported record, use the owner's visible accessor when projection provenance is unclear.

Nested update paths are supported through nominal record fields, but dependent fields and some generated imported compound-field annotations remain limited. Supply a known nominal result type. Do not assume anonymous records, row polymorphism, structural subtyping, or overloaded field lookup.

## 8. Pattern matching

Match constructors to make each meaningful case explicit. Constructor patterns omit family parameters and bind the constructor's fields. The ordinary field patterns are flat names or `_`; an underscore discards a field, not a checked error policy. Do not assume Rust, Haskell, or OCaml pattern syntax. [Patterns][syntax] · [Positive and negative surface fixtures][ergo-tests]

```ouro
import "../std/data.ouro";

def successor_when_present (value : Maybe Nat) : Maybe Nat :=
  match value with
  | Nothing => Nothing Nat
  | Just number => Just Nat (S number)
  end;
```

Use `if` for a Boolean decision. Use `if let` when one constructor deserves a special branch and all others have the same fallback:

```ouro
import "../std/data.ouro";

def value_or_zero (value : Maybe Nat) : Nat :=
  if let Just number := value then number else 0;
```

That fallback is appropriate only when absence really means zero. A required parsed field should normally return an error instead. Both branches are checked, and `if let` requires an `else`; the bound names are available only in the successful branch. The current `if let` slice needs a supported known, nonindexed constructor family.

For a single-constructor product, checked destructuring avoids an unnecessary match wrapper:

```ouro
import "../std/prelude.ouro";

def pair_sum (pair : Pair Nat Nat) : Nat :=
  let (MkPair left right) := pair in add left right;
```

The one-branch match must be exhaustive. `let (Just value) := maybe_value in ...` is not an implicit assertion and is rejected when `Nothing` remains possible.

The compiler also supports multi-scrutinee constructor matches; use them for a small product of cases, not to create a difficult cross-product table. Nested constructor patterns, alternatives, guards, arbitrary catch-all patterns, and general record patterns must not be assumed from other languages. Use an inner match or a helper for a field that needs further inspection. [Compiler use of multi-match][term-checker] · [AST coverage tests][span-tests]

Extract a helper when an arm has become its own operation with a name and contract. Do not replace explicit failure branches with a wildcard just to make a match shorter. Removing a redundant-looking arm or identical branches still requires preserving scrutinee evaluation and type dependencies; leave review-required rewrites to an actual review.

## 9. Structural recursion that the checker can see

Prefer an existing traversal before writing a fixpoint. When recursion is necessary, expose the decreasing structure in a match and recurse on the resulting strict-subterm binder. Do not expect the checker to prove an arbitrary arithmetic inequality or a shrinking property of another function. [Structural checking][checking] · [Implementation][term-checker] · [Standard traversals][listx]

A list traversal with a growing accumulator is a useful teaching example:

```ouro
import "../std/types.ouro";

def reverse_example (A : Type) (values : List A) : List A :=
  (fix go (remaining : List A) (reversed : List A) : List A :=
    match remaining with
    | Nil => reversed
    | Cons value rest => go rest (Cons A value reversed)
    end) values (Nil A);
```

The recursive input is `rest`, obtained from `remaining`. The accumulator is allowed to grow because it is not the decreasing argument. In real application code, use `reverse_lin` from `std/listx.ouro` instead of copying this implementation.

Put the traversed structure first in helpers like this, matching common library code. The checker tracks the fixpoint's selected structural argument, arity, and strict-subterm evidence; it does not treat every argument as decreasing. Recursive calls must supply the required arguments. Passing an escaping recursive function around is not a substitute for an accepted recursive call.

### Reshape rejected designs

| Problematic design | Better shape |
| --- | --- |
| Call the recursive function again with the original input. | Match the input and recurse on a strict subterm, or show that this is a loop requiring a different bounded interface. |
| Recurse on `sub n 1`, expecting arithmetic reasoning to establish descent. | Match `n` as `S previous` and recurse on `previous`. |
| Recurse on `filter predicate rest` or another transformed structure. | Traverse `rest` directly, use a suitable library combinator, or introduce an explicit structurally decreasing budget with an honest exhaustion result. |
| Put the ever-growing accumulator in the structural position. | Separate the decreasing input from the state being accumulated. |
| Name a local helper and call it from its own ordinary `let` initializer. | Use an explicit `fix`; ordinary local binding is not recursive. |
| Leave `fix` around a helper that never calls itself. | Write an ordinary function or lambda. |

For example, predecessor is a case analysis, not recursion:

```ouro
import "../std/types.ouro";

def predecessor (value : Nat) : Nat :=
  match value with
  | Z => Z
  | S previous => previous
  end;
```

The maintained `05_fix` tutorial currently uses this nonrecursive shape. Follow what the source does, not what its filename seems to promise. [Tutorial source][tutorial-fix]

### Budgets are contracts, not termination camouflage

A `Nat` fuel argument can make a traversal structurally checkable even when its other state is not visibly shrinking. Give the budget a defined unit: pulls, input nodes, attempts, or another observable step. At exhaustion, return a typed limit result when completeness matters. Returning the accumulated prefix as ordinary success hides an incomplete operation.

The current `collect_list` and `iter_fold` APIs demonstrate this distinction: budget exhaustion is `IterPullLimit`, not an accepted partial answer. A bound on the number of callbacks does not bound the work inside each callback. [Bounded iteration][iter]

An immediately applied nested fixpoint can inherit strict-subterm evidence under the current checker rules, but that does not enable unrestricted recursion. `std/wf.ouro` currently provides accessibility projections and nonrecursive elimination, not a general well-founded-recursion facility. Do not import it expecting arbitrary recursive algorithms to become accepted. [Nested fixpoints][checking] · [Current accessibility helpers][wf]

Accumulator style is a way to express state flow and avoid some repeated construction. Do not call it universally stack-safe or faster on every backend without corresponding runtime evidence.

## 10. Dependent types where they earn their cost

Use dependency when it removes a real mismatch at the interface: a vector's length, an index's relationship to its container, or an operation whose result type depends on the input. Keep unrelated runtime values out of type computation. [Dependent Core][checking] · [Vector demonstration][vec]

This small adaptation of the repository's vector declaration uses the shared standard `Nat`:

```ouro
import "../std/types.ouro";

inductive Vec (A : Type) : Nat -> Type :=
  | VNil : Vec A Z
  | VCons : (size : Nat) -> A -> Vec A size -> Vec A (S size);

def singleton_vec (value : Nat) : Vec Nat (S Z) :=
  VCons Nat Z value (VNil Nat);
```

The constructor ties the tail length to the result length. A caller cannot substitute an empty vector where that exact singleton type is expected. This is a useful checked relationship, not just an extra name.

The demonstration module itself declares its own `Nat`; it is not a drop-in practical vector package over `std/types.ouro`. Avoid importing educational standalone preludes into a program already using the shared standard families. Nominal identity and registered representations matter even when two declarations have the same spelling or shape. [Demo source][vec] · [Representation identity][syntax]

Before introducing an indexed API, ask whether the consumer needs the index. For “may be absent,” use `Maybe`. For “failed for this reason,” use `Either`. For “cannot be empty,” an ordinary head-and-tail inductive may suffice. For configuration values, runtime validation with a small domain error usually communicates more than a proof parameter at every call.

Make proofs serve an invariant with observable consequences. Explain the invariant and, where necessary, the proof strategy—not each mechanical proof step. Do not use axioms or unresolved holes to turn an unproved invariant into a supposedly checked API. An axiom is an explicit assumption, not a proof or executable implementation. The checker does not execute IO, raw memory operations, or platform calls during type conversion. [Acceptance and assumptions][checking] · [Syntax][syntax]

Also account for elaboration and normalization cost. A correct type-level computation can still exhaust the current checking budget. Prefer small, stable type relationships over computing an entire application result in a signature.

## 11. Effects and IO boundaries

`IO A` is currently a transparent alias of `Runtime A`; the ordinary user surface remains `io_pure`, `io_bind`, `do`, and `let!`. Use `main : IO Unit` for a normal executable. Keep the pure transformation callable without an IO environment. [Runtime representation][syntax] · [IO implementation][io]

```ouro
import "../std/io.ouro", "../std/string.ouro";

private def tagged (line : String) : String :=
  str_concat "input=" line;

-- @entry main
def main : IO Unit :=
  do let! line := readLine;
     println (tagged line);
     exit 0
```

Within `do`, use ordinary `let` for a pure value or a stored action; use `let!` to execute an action and bind its result. The final statement must have the required IO result type. To return a pure `Nat` from an `IO Nat` computation, use `io_pure Nat value`, not a bare `value`.

A stored action is reusable, not a memoized result. Running the same filesystem, environment, clock, input, or process action again can observe a different world and perform the effect again. `io_pure (IO A) action` returns a deferred action as a value; it does not execute the nested action. [Runtime action contracts][effects] · [Effect-aware diagnostics][clippy]

**Current native input limit:** `readLine` stops at LF or 8191 bytes, removes the LF but not a preceding CR, and leaves an overlong line's remainder for later reads. Do not treat one call as an unbounded logical-line reader. [Input contract][effects]

Use `io_foreach` or `io_fold` for sequential action traversal when their signatures fit. They are not parallel map/fold operations. Build a pure report before printing it when that makes ordering and tests clearer, but do not claim that every report should be fully buffered regardless of size.

### Typed failures do not catch the whole runtime

An `IO (Either FsError A)` action lets the library return typed failures. It does not mean every OS, allocation, conversion, or cleanup failure becomes `Left`. Some current native runtime failures terminate the process with status 73. The compatibility C host also differs from native Windows in some IO details. Read the runtime contract for the operation and backend you actually use. [Runtime failures][effects] · [Checked filesystem wrappers][fs]

This distinction matters when publishing files or promising recovery: a checked wrapper may perform precondition and postcondition queries without offering an atomic transaction or catching every lower-level failure.

### Do not import an imagined concurrency model

The supported `effect`/`perform`/`handle` slice is narrow and one-shot. It is not a general algebraic-effects implementation; use the maintained effect fixtures before introducing a new handler shape. Ordinary application IO does not require custom handlers. [Effects scope][effects] · [Tutorial inventory][tutorial-index]

`std/async.ouro` currently offers sequential, blocking Windows-native delays (`sleep_s`, `delay_then`). It provides no scheduler, cancellation API, futures, or automatic concurrency. Do not name a design “asynchronous” merely because it imports that module. [Current async surface][practical]

## 12. Errors, propagation, and validation

Choose the failure representation according to the information the caller needs. Keep policy at the layer that owns it. [Results][result] · [Validation][validation] · [CLI errors][cli]

| Situation | Prefer |
| --- | --- |
| Absence is expected and its cause is irrelevant. | `Maybe A`. |
| The caller must distinguish invalid input, missing input, or different failure causes. | `Either DomainError A`. |
| Several independent input problems should be reported together. | `Validation E A`, currently `Either (List E) A`. |
| Failure occurs during an action. | `IO (Either E A)` when the current API provides it, while retaining its runtime-failure limitations. |
| A fallback is an intentional product policy. | An explicit default operation or branch, documented at the decision point. |

### Do not erase malformed input

**Works, but weak for required input:**

```ouro
import "../std/text.ouro";

def amount_or_zero (text : String) : Nat :=
  fromMaybe Nat 0 (str_parse_nat text);
```

This makes malformed input indistinguishable from a valid zero. A domain-aware replacement keeps that distinction:

```ouro
import "../std/text.ouro";

inductive AmountError : Type :=
  | AmountMalformed : String -> AmountError
  | AmountMustBePositive : AmountError;

def parse_amount (text : String) : Either AmountError Nat :=
  match str_parse_nat text with
  | Nothing => Left AmountError Nat (AmountMalformed text)
  | Just value =>
      match value with
      | Z => Left AmountError Nat AmountMustBePositive
      | S _ => Right AmountError Nat value
      end
  end;
```

The error remains data until a CLI or reporting boundary decides how to render it. Do not invent a line number or parse reason that the underlying `Maybe` parser did not provide.

A missing optional setting can legitimately default while a supplied malformed value remains an error. `cli_optional_nat` and `cli_optional_bool` implement that distinction. Do not replace them with a parse followed by an unconditional default. [CLI implementation][cli]

### Flatten dependent failure chains with `let?`

Continuing the `AmountError`/`parse_amount` module above:

```ouro
def sum_amounts (left : String) (right : String) : Either AmountError Nat :=
  let? (Left, Right) : Either AmountError Nat do
    let first : Nat := (parse_amount left)?;
    let second : Nat := (parse_amount right)?;
    add first second
  end;
```

The header states the failure constructor, success constructor, and whole result type. On failure, propagation stops. The final expression is the **success payload** and is wrapped automatically; do not wrap it in `Right` a second time. A final `expression?` forwards the checked container. A corresponding `let? (Nothing, Just) : Maybe A do ... end` works for the supported Maybe shape. [Fallible block contract][ergonomics]

This is not general `try`, exception handling, or a postfix operator available everywhere. Propagation belongs at the root of a supported block binding, standalone statement, or final expression. There is no automatic conversion between different error types. Use `result_map_err` deliberately before joining a common error channel.

For a single continuation, `result_bind E A B result next` is often clearer than a block. For a pipe-friendly continuation, `result_and_then E A B next result` places the result last. Inspect the signature instead of assuming argument order. [Result combinators][result]

An IO action must still be executed before handling its result:

```ouro
import "../std/fsx.ouro";

def print_file (path : String) : IO Unit :=
  do let! loaded := fsx_read_text path;
     match loaded with
     | Left error =>
         do eprintln (fs_error_message error);
            exit 1
     | Right text => print text
     end
```

A pure fallible block does not automatically unwrap `IO (Either E A)`. Keep the `do` boundary explicit.

### Accumulate only independent validation

```ouro
import "../std/validation.ouro";

def validate_required_inputs (has_input : Bool) (has_output : Bool)
    : Validation String Unit :=
  validation_collect_unit String
    [ validation_require String "missing input" has_input
    , validation_require String "missing output" has_output
    ];
```

`validation_collect_unit` consumes validations with **Unit payloads**. `validation_require_nonempty` instead preserves a successful `String`; it cannot be dropped into the same list without an explicit payload conversion. The result type, not the name “validation,” determines which combinations are legal. [Exact validation signatures][validation]

Use fail-fast propagation when later work depends on earlier success. Use accumulation when checks are independent and a complete error report helps the user. Do not run dependent operations with dummy values merely to accumulate more errors.

### Defaults and discards must be intentional

`result_to_maybe` loses an error; `result_or` loses an error in exchange for a default. Both are legitimate policy tools, not neutral conversions. For a costly fallback, use a branch, `??` for a registered `Maybe`, or the appropriate `_unwrap_or_else` callback rather than eagerly preparing a value that might never be selected. [Fallback implementations][result] · [Maybe operator][ergonomics]

Do not turn `Left` into success without a real recovery operation. Printing an error is not recovery. Returning `io_unit`, an empty collection, or exit status zero after an unrecovered failed write is fake success.

The linter can detect some ignored registered parser and checked-IO results. It does **not** give every `Maybe` or `Either` a universal must-use property. An absence of warnings is not evidence that every error path has been handled. [Observation rules][clippy]

## 13. A practical standard-library map

Start at the task layer, then inspect the generated signature or source. Do not reproduce an existing parser, scanner, checked process wrapper, or list traversal simply because a low-level primitive is easier to find. `std/practical.ouro` is a convenience umbrella for small tools; narrower imports are a better dependency contract for reusable libraries. [Practical surface][practical] · [API index][api]

| Task | Starting point | Selection guidance |
| --- | --- | --- |
| Shared data and small pure functions | `std/types.ouro`, `std/prelude.ouro` | Shared nominal families; basic `map`, `append`, `length`, `foldr`, arithmetic. |
| Optional and fallible values | `std/data.ouro`, `std/result.ouro` | Explicit type arguments; bind/map errors rather than rebuilding nested cases everywhere. |
| General list algorithms | `std/listx.ouro`, `std/collections.ouro` | `foldl`, `find`, `count_if`, `reverse_lin`, `nth_maybe`, indexed operations, traversal and checked folds. |
| Bounded pull processing | `std/iter.ouro`, `std/range.ouro` | Lazy adapters plus explicit pull budgets; not a hidden streaming runtime. |
| Numbers | `std/num.ouro` | Practical Nat comparisons, checked division/modulo, aggregate and eager-range helpers. |
| Strings and small text tools | `std/string.ouro`, `std/text.ouro` | Byte-oriented strings; tokenization, trimming, typed Nat/Bool parsing. |
| Scalar encoding and bytes | `std/utf8_scalar.ouro`, `std/bytes.ouro` | Validate scalars before encoding; inspect strictness of convenience decoders. |
| CLI input | `std/args.ouro`, `std/cli.ouro` | Strict precheck before forgiving argument parsing; typed required/optional fields. |
| Configuration | `std/config.ouro`, `std/configx.ouro` | Parse key/value text, then validate field types/schema. Reading config is not schema validation. |
| Files and paths | `std/fsx.ouro`, `std/fs.ouro`, `std/pathx.ouro` | Prefer checked practical operations; path text manipulation is not an OS identity or safety proof. |
| Directory inventory and publication | `std/fs_walk.ouro`, `std/fs_replace.ouro`, `std/workspace.ouro` | Distinguish incomplete walks and recovery states; read the exact replacement contract. |
| Line processing | `std/lines.ouro` | Bounded, in-memory line transformations and reports, not true streaming. |
| JSON | `std/json.ouro`, `std/jsonx.ouro` | Keep `parse_json` failure distinct from JSON null; typed accessors return `Maybe`. |
| CSV and tabular data | `std/csv.ouro`, `std/table.ouro`, `std/tablex.ouro` | Bounded parsing, named columns, required-column validation; not a full serialization framework. |
| Processes | `std/processx.ouro`, `std/process.ouro` | Program plus argv; inherited execution or bounded capture according to requirements. |
| HTTP | `std/http.ouro` | Message parsing and the Windows-native POST surface; not a promise of a portable general-purpose HTTP client. |
| Validation and reports | `std/validation.ouro`, `std/report.ouro`, `std/workflow.ouro` | Accumulate independent input errors; deterministic rendering; sequential workflow composition. |
| Application tests | `std/test.ouro` | Named assertions and an IO runner with failure exit status. |
| Delays | `std/async.ouro` | Blocking sequential Windows-native delay helpers only. |

Several modules deliberately overlap. `std/fsx` is a practical layer over `std/fs`, not a new guarantee that all host errors are recoverable. `std/jsonx` adds accessors, not strict schema inference. `std/collections` builds on `std/listx` and the small prelude. When qualifying a function, use the file that directly owns it, not whichever umbrella made its bare name visible.

Configuration currently uses line-based `key=value`, ignores blank lines and `#` comments, and lets later duplicate keys win. Reject duplicates separately when that would be unsafe for your format. Table access must distinguish a missing column or a short row from a real empty cell; `tablex` required-column validation also matters for header-only input. [Configuration and table contracts][practical]

## 14. Collections, iteration, and ranges

Choose a traversal by the required result. Do not build an intermediate collection merely to ask a scalar question about it. Preserve the callback's semantics and result ordering when changing traversals. [List implementations][listx] · [Collections][collections] · [Audited composition laws][collection-perf]

| Needed result | Typical choice |
| --- | --- |
| Transform every element. | `map A B function values`. |
| Accumulate a state from left to right. | `foldl A State step initial values`. |
| Keep successful optional conversions. | `filter_map A B function values`, only when dropping failures/absence is intentional. |
| Find one matching item. | `find A predicate values`. |
| Count matching items. | `count_if A predicate values`. |
| Safely index a list. | `nth_maybe A index values`. |
| Convert every item, stopping at first failure. | `list_traverse_result E A B function values` or its Maybe counterpart. |
| Accumulate without a result list, stopping at failure. | `list_try_fold_result E A State step initial values`. |
| Produce outputs and a final state together. | `list_map_accum A State B step initial values`. |
| Consume a pull source without a final list. | `iter_fold State Error Item Acc step initial max_pulls source`. |

### Before/after: count without a filtered list

```ouro
import "../std/text.ouro";

-- Valid, but materializes selected lines only to count them.
def count_nonblank_weak (lines : List String) : Nat :=
  length String
    (filter String (fun line => notb (str_is_blank line)) lines);

-- Same application-level predicate and result; no selected-list allocation.
def count_nonblank (lines : List String) : Nat :=
  count_if String (fun line => notb (str_is_blank line)) lines;
```

That rewrite is justified by this predicate and these library implementations. It is not permission to remove, duplicate, or reorder an arbitrary callback. Current Clippy composition rules require narrow identity, purity, totality, ownership, and traversal evidence; they can intentionally miss a safe application-specific improvement. All these composition findings are review-only. [Proof boundaries][collection-perf]

### Avoid growing-left append

`append A left right` traverses and rebuilds the left spine. `snoc A values value` uses `append` with a singleton. Repeatedly adding to the end of a growing list therefore creates quadratic spine work. For a simple transformation, use `map`; for a stateful builder, prepend to an accumulator and reverse once. [Prelude append][prelude] · [Snoc and linear reversal][listx]

```ouro
import "../std/listx.ouro";

-- Valid, but repeatedly copies the growing output prefix.
def successors_weak (values : List Nat) : List Nat :=
  foldl Nat (List Nat)
    (fun (output : List Nat) (value : Nat) => snoc Nat output (S value))
    (Nil Nat) values;

-- One direct result-building traversal.
def successors (values : List Nat) : List Nat :=
  map Nat Nat (fun value => S value) values;
```

For reversal, prefer `reverse_lin`: the older `reverse` in `std/data.ouro` recursively reverses the tail and appends a singleton, giving quadratic source-level list-spine work rather than the linear traversal of `rev_append`. Do not assume an optimizer will erase that difference. [Data implementation][data] · [Linear reversal][listx]

A final-tail list spread is another useful exact construction: `[first, second, ..rest]` allocates the new prefix and reuses `rest`. It is not an arbitrary flattening operator. [List spread lowering][ergonomics]

### Short-circuit only where the implementation does

`find` branches before recursing. The current `any` and `all` implementations instead pass the recursive Boolean as an eagerly evaluated argument to `orb`/`andb`. Do not assume they stop at the first decisive element. When early exit matters, use a branching traversal such as `find`, or a directly checked structural match. [Source][listx] · [Explicit evaluation note][collection-perf]

`list_traverse_result` calls the converter in input order and stops on the first `Left`. `list_collect_results` consumes results already present in a list. Computing `map convert inputs` first can do work on the entire input before collection sees the first error. Prefer traversal when the conversion itself should stop early. [Exact traversals][collections]

Names do not prove implementation complexity. In this snapshot, `split_at` uses `take` and `drop`, `list_take_last` first obtains a length, and `list_group_by` searches existing list-backed groups. The latter has quadratic worst-case work. Keep these implementations in mind before using them repeatedly on large inputs.

### Bounded iterators

```ouro
import "../std/iter.ouro";
import "../std/string.ouro";

def iterator_sum : Either (IterCollectError String) Nat :=
  iter_fold (List Nat) String Nat Nat add 0 4
    (iter_from_list String Nat ([1, 2, 3] : List Nat));
```

The reviewed implementation succeeds with payload `6`: three item pulls and one end observation. This is a semantic example, not an executed test report. [Iterator source][iter]

A pull can yield an item, skip an item, finish, or fail. **All four observations consume the pull budget.** A filter's rejected items still cost pulls; `iter_take` counts emitted items instead. Zero pulls always gives `IterPullLimit`, including for an empty source. A finite list of `n` items needs `n + 1` pulls to observe the end.

`iter_map`, `iter_filter`, and `iter_take` defer processing rather than creating intermediate lists. Wrappers and step results still allocate. `collect_list` builds a reversed list and reverses it at completion; there is no advertised automatic fusion or constant-allocation guarantee. Use `iter_fold` when only the aggregate is needed. Failure or exhaustion returns an error rather than a partial aggregate disguised as success.

### Ranges are values, not lists

With `std/range.ouro`, `0..10` is an exclusive step-one `NatRange`, and `0..=10` is inclusive. These literal forms require literal endpoints. Use `nat_range_exclusive`, `nat_range_inclusive`, and checked `nat_range_by` for computed endpoints or a different step. Zero step is an error. [Range contract][range] · [Literal syntax][syntax]

Direction comes from the endpoints; descending ranges are supported. An inclusive endpoint is produced only when the step lands on it. For example, descending 10 to 0 by 3 yields 10, 7, 4, 1—not an invented final zero.

`iter_from_nat_range` validates the range and returns a fallible iterator. Its consumer still needs a pull budget. Do not confuse this API with the eager list-producing range helpers in `std/num.ouro`, or invent a `for` loop syntax from the existence of range literals.

## 15. Strings, Unicode scalars, and bytes

`String` is the registered `ouro.string` type. Import its standard declaration rather than inventing `axiom String : Type;`. A same-spelled opaque type does not authenticate String literals or primitive behavior. [String representation and literals][syntax]

The current string operations are **byte-based**. Lengths and slice offsets count bytes, comparison/search use byte semantics, and conversion to codes exposes byte values. A character literal such as `'€'` is different: it produces a `Nat` Unicode scalar value. Neither is a grapheme-cluster abstraction. [Literal contract][syntax] · [Runtime string behavior][practical]

```ouro
import "../std/string.ouro";

-- A Nat scalar ordinal, not one byte.
def euro_scalar : Nat := '€';

-- The UTF-8 bytes of that scalar in a String.
def euro_text : String := "€";

-- A List Nat with explicit byte values, including NUL and a non-ASCII byte.
def packet : List Nat := b"A\x00\xFF";
```

Use `utf8_scalar_checked` when converting an untrusted scalar ordinal to UTF-8; `utf8_scalar_bytes` requires an already validated scalar. A `List Nat` used as bytes does not itself enforce `0..255`; some construction paths reduce values modulo 256. Validate the intended byte domain instead of assuming that the representation enforces it. [Scalar and byte APIs][practical] · [Byte helpers][bytes]

Current byte lookup outside a String returns zero, and slices clamp ranges. Zero is also a valid byte. These behaviors are not a substitute for validating an index, required field width, or UTF-8 boundary. Embedded NUL is preserved by the managed String/native byte paths, but path APIs reject NUL and compatibility host adapters have operation-specific differences. [String and host contracts][practical] · [IO boundary][effects]

`str_lower`, `str_upper`, and the related character rules are not a Unicode case-folding or locale framework. Source text helpers operate over the existing byte/ASCII contracts. A byte reversal is not a human-text reversal. Avoid converting `String -> List Nat -> String` simply to call an API that already accepts String. [Text source][text] · [Case-law boundary][collection-perf]

Raw `r#"..."#` literals are useful for paths and backslashes. The supported raw delimiter has exactly one `#`. Multiline triple-quoted literals have a precise indentation-removal contract; treat their whitespace as data and let the formatter refuse a transformation that would change it. Do not transplant another language's escape rules.

`str_words` currently splits on a literal space and removes empty pieces; use `str_tokens` for the documented space/tab/CR/LF tokenization. `str_unlines` joins lines with LF but does not append a final LF. These names do not import Haskell's or another library's contracts. [String functions][string] · [Line joining][stringx] · [Text tokens][text]

### Parsing convenience is not strict validation

`str_parse_nat` trims then delegates to the current Nat parser. `str_parse_bool` trims and normalizes case, accepting the documented words and numeric Boolean forms. The source language's hexadecimal/binary literal syntax does not by itself prove that a runtime text parser accepts the same grammar. [Text parsers][text]

Two particularly important convenience boundaries are:

| Convenience | Information or strictness lost | Better choice when rejection matters |
| --- | --- | --- |
| `jsonx_parse_or_null text` | A rejected parse becomes the same `JNull` value as valid JSON null. | Match `parse_json text`, then decode fields. |
| `hex_decode_str text` | It filters non-hex characters before decoding. | Call `hex_decode (str_codes text)` and handle `Nothing`. |

These are implementation observations, not naming guesses. JSON typed getters also return `Nothing` for several different conditions, such as missing members and wrong value types. Introduce only distinctions your decoder actually establishes. [JSON helpers][jsonx] · [Hex implementation][bytes]

The JSON parser's documented nesting bound is 128. Its balanced string decoder has specific linear-work/logarithmic-call-depth behavior; that does not establish a complexity bound for every JSON operation or make the parser an unbounded streaming API. Line, CSV, and table helpers are likewise bounded practical tools. [Data limits][practical]

## 16. Filesystem and process programs

### Read and write through the right contract

Use `fsx_read_text`/`fsx_write_text` for the practical checked text interface, and `std/fs.ouro` when a lower-level checked operation is needed. Handle the result before claiming success. A successful empty file is not a failed read; a failed read is not an empty document. [Practical wrappers][fsx] · [Checked implementation][fs]

`fs_read_checked` performs a file check before executing the read. `fs_write_checked` checks path conditions and a resulting file postcondition. Neither is an atomic snapshot or a guarantee that every low-level failure becomes a typed `FsError`. In particular, the runtime contract documents compatibility-host write limitations; an existence check alone does not verify the bytes of a published artifact. [Host and publication limits][effects]

For important output, separate generation, staging, verification, and publication. Use the documented `std/fs_replace.ouro` workflow only after understanding its source/stage/backup contract; retain recovery files until the outcome and installed contents are verified. Do not replace its refusal path with “delete the old file, then copy.” A candidate flush is not a directory-durability guarantee, and replacement does not lock out concurrent editors. [Replacement contract][effects] · [Practical usage][practical]

`fs_rename_checked` is a checked same-volume rename/replacement with its own preconditions. It is not interchangeable with the stronger source-publication workflow. Temp and backup naming helpers do not promise unpredictable names or secure reservations merely because their names contain “temp.”

For security-sensitive or complete inventory, use `fs_walk_checked` from `std/fs_walk.ouro`. It distinguishes complete, truncated, unreadable, and unsafe walks and sorts children. Compatibility `fs_walk` turns non-complete outcomes into an empty list; **do not interpret that empty list as evidence that a directory contains nothing**. Raw directory enumeration also does not promise a stable host order. [Walk contracts][practical] · [Compatibility implementation][fs]

Use path helpers to construct paths, but distinguish lexical spelling from filesystem identity. Attribute queries, path normalization, and a root prefix are not by themselves an atomic no-follow authorization check. Use the actual checked operation required by the threat model.

### Process specifications are not shell strings

```ouro
import "../std/processx.ouro";

def tool_output (program : String) (input_path : String)
    : IO (Either ProcessError String) :=
  process_stdout_checked
    (command_spec program (["--input", input_path] : List String));
```

Keep the executable and each argument separate. `command_render` produces display text, not a correctly quoted shell command. Do not execute their output through a shell. Selecting an attacker-controlled executable or dangerous arguments remains a separate application policy problem. [Command source][processx]

Choose the runner according to what counts as a result:

| Requirement | Current direction |
| --- | --- |
| Obtain stdout and require a successful child exit. | `process_stdout_checked` / checked `CommandSpec` helpers. |
| Preserve the exit code of a completed child with inherited streams. | `process_run_spec_inherited`; its `_checked` variant maps nonzero completion to `ProcessExited`. |
| Accept a specific set of nonzero/zero exits. | `process_run_expected_codes`, retaining captured streams for accepted results. |
| Bound captured output, time, and memory. | `process_run_spec_captured_bounded` with explicit `ProcessCaptureLimits`. |
| Supply exact binary stdin to bounded capture. | The corresponding `_with_input` form. |

A nonzero exit is still a completed bounded capture; timeout, stream overflow, containment/OS refusal, or incomplete cleanup are different failures. Inspect the result type instead of treating all process APIs as interchangeable `IO Bool`. Some errors belong to `ProcessError`, others to the inherited/capture-specific error types. [Runner contracts][practical] · [Exact wrapper signatures][processx]

Do not assume every executable name in an example is a standalone binary on every platform: `echo`, for instance, may be a shell facility rather than the program you intended. The application controls the program path and its deployment requirements. The current native target is Windows x86-64; host-side tooling availability does not change that target.

Process plans execute sequentially through the existing helpers. They are not shell pipelines, concurrent jobs, or streaming connections between processes. Avoid launching a child once per line when one invocation and structured input can perform the same bounded task.

## 17. A small CLI with honest failure behavior

A useful CLI boundary has a pure argument policy, explicit IO results, deterministic stdout, diagnostics on stderr, and distinct success/usage/operation exits. The current Args parser is intentionally forgiving; strict command entry points should call `args_argv_options_complete` **before** parsing and then reject unknown options or an invalid positional shape themselves. The precheck is not a complete command schema. [Args implementation][args] · [CLI helpers][cli] · [Maintained file program][file-sample]

The following two example files live under `handbook/` in an Ouro checkout. They form a complete small program which accepts one filename, optionally preceded by `--`, and prints its number of nonblank lines. It deliberately does not implement flags or a help mode.

**`handbook/count_core.ouro` — pure application logic and argument validation:**

```ouro
import "../std/cli.ouro";

private def no_options (parsed : Args) : Bool :=
  andb (nullb String (args_flags parsed))
    (nullb (Pair String String) (map_pairs String (args_opts parsed)));

def count_nonblank (text : String) : Nat :=
  count_if String (fun line => notb (str_is_blank line)) (str_lines text);

def count_input_path (arguments : List String) : Either CliError String :=
  if args_argv_options_complete (Nil String) arguments then
    let parsed : Args := cli_from_argv (Nil String) arguments in
    if andb (no_options parsed)
        (eq_nat (length String (args_positional parsed)) 1) then
      cli_required_pos parsed 0 "input"
    else
      Left CliError String (CliUsage "expected one file and no options")
  else
    Left CliError String (CliUsage "missing long-option value");
```

The full native `argv` includes the program name; `cli_from_argv` removes it. The explicit `--` terminator permits a path beginning with a dash. Rejecting an option is deliberate here, not an assumption that `cli_from_argv` automatically knows which options are legal. [Argv grammar][args]

**`handbook/count_cli.ouro` — IO and reporting:**

```ouro
import "../std/io.ouro", "../std/cli.ouro", "../std/fsx.ouro";
import "count_core.ouro" as Count;

private def run_file (path : String) : IO Unit :=
  do let! loaded := fsx_read_text path;
     match loaded with
     | Left error =>
         do eprintln (fs_error_message error);
            exit 1
     | Right text =>
         do println (str_of_nat (Count.count_nonblank text));
            exit 0
     end

-- @entry main
def main : IO Unit :=
  do let! arguments := argv;
     match Count.count_input_path arguments with
     | Left error =>
         do eprintln (cli_error_block "count-nonblank" "[--] FILE" error);
            exit 2
     | Right path => run_file path
     end
```

`cli_error_block` uses `str_unlines`, whose current implementation joins with `"\n"` but does **not** add a final newline. Hence this program uses `eprintln` to terminate the diagnostic block. The file is read once, and blank-line counting does not allocate a filtered line list. The original split into lines still materializes a list: this is an in-memory text tool, not a streaming implementation. [CLI rendering][cli] · [Exact line-joining behavior][stringx] · [Text and list operations][text]

Exit codes 0, 1, and 2 are this application's success/operation/usage convention, consistent with the maintained tools; they are not a universal language requirement. Lower-level fatal runtime exits remain possible. Do not print a success count after a failed read.

An application with Boolean switches should pass their names to the parser, so `--flag file` does not consume `file` as the flag's value. Explicitly decide duplicate-option, unknown-option, repeated-positional, and output-format policies rather than inheriting accidental parser behavior.

## 18. Performance: remove demonstrated work

Optimize from the actual data flow and implementation, then measure the relevant backend. A rule about eliminated traversal is not a measured speedup, and a cleaner expression is not automatically cheaper. [Performance diagnostic boundary][collection-perf] · [Semantic facts][clippy]

### Implementation-backed priorities

| Observed implementation | Practical response |
| --- | --- |
| `append` rebuilds its left list spine; `snoc` delegates to it. | Avoid repeated append to a growing output. Use the direct traversal or prepend/reverse construction in section 14. |
| `std/data.reverse` recursively appends while `reverse_lin` uses an accumulator. | Choose the explicit linear-spine implementation for substantial lists. |
| `length (filter ...)` builds selected cells before counting. | Use `count_if` when the predicate/evaluation policy is preserved. |
| `list_traverse_result` stops before later conversions after failure. | Prefer it to eagerly creating a whole list of results when work should stop early. |
| `split_at` calls both `take` and `drop`; several suffix helpers first obtain a length. | Do not infer one-pass behavior from a helper's name, especially inside another traversal. |
| `list_group_by` searches list-backed groups. | Avoid assuming hash-map complexity. Benchmark large/high-cardinality inputs before choosing it for a hot path. |
| Pull adapters avoid intermediate lists, but step/wrapper values and collection still allocate. | Use `iter_fold` for aggregates; do not promise zero-cost iterator fusion. |
| `fs_append_checked` reads the current whole file and writes concatenated contents. | Batch generated lines where appropriate instead of repeatedly calling `fsx_append_line` on a growing file. This is not an atomic append primitive. |
| `io.read_all` has a finite fuel bound and accumulates concatenated chunks. | Do not advertise it as unbounded streaming or as a checked complete-input result. Choose a suitable input contract for large data. |
| Some size constants in `std/io` are expressed as products of smaller literals to limit extractor work. | Distinguish literal/elaboration cost from runtime arithmetic cost. Do not infer that every native Nat operation walks a Peano chain. |

Sources: [Prelude][prelude], [Data helpers][data], [List algorithms][listx], [Collections][collections], [Iterators][iter], [Filesystem append][fs], [IO source][io].

When normalizing or parsing a dynamic value twice in the same pure context, bind the first result and reuse it. Keep the parsed value, not just a success flag that forces another parse. The current semantic diagnostics deliberately consider resolved callee identity, argument identity, branches, and intervening effects before reporting repeated work. [Repeated-work rules][clippy]

For Strings, prefer APIs that already accept the current representation. Repeatedly converting to byte-code lists, normalizing, reconstructing text, and then converting again can introduce unnecessary traversal and allocation. But do not assert a zero-copy property, a concatenation complexity bound, or an optimization pass merely from a function name. Inspect the implementation involved in the measured path.

An abstraction can be worthwhile because it owns error mapping, a platform boundary, or a stable public contract. Do not inline those boundaries just to eliminate a call. Conversely, a wrapper that adds no contract, policy, reuse, or readability is not automatically justified by “architecture.” Treat wrapper deletion as an API review, not an automatic performance law.

### Measurement and equivalence

For a performance change, retain the revision, backend, input size/distribution, output size, and cold/warm state. Separate compiler/bootstrap/cache time from program runtime. Compare scaling and allocation or peak-memory behavior where observable, not only one elapsed-time sample.

Check outputs, failure behavior, ordering, and the number/order of effectful operations before accepting the optimization. In particular, map/filter fusion or moving a limit ahead of a callback can change which callbacks execute. Purity alone is not a license to omit potentially failing or unproved computations. Current Clippy intentionally accepts only a narrow total-callback vocabulary for automatic *diagnosis*, and publishes those collection transformations as manual suggestions. [Equivalence conditions][collection-perf]

No benchmark was run for this handbook. The claims above concern inspected work and representation paths, not fabricated throughput, nanoseconds, or universal backend behavior.

## 19. Comments, documentation, and directives

Document public behavior, accepted inputs, failure policy, units, ordering, and non-obvious invariants. Explain why a representation or proof step is necessary. Avoid comments that merely translate the next line into English or preserve an editing diary. [Repository writing conventions][agents]

The current documentation generator scans original source text. Use a contiguous run of ordinary, unindented `--` comments immediately above the top-level declaration. A blank line closes the pending run. The opening comment run can serve as module documentation. There is no need to invent `///`, `/** */`, or a separate language doc-comment syntax. [Documentation scanner][doc-model]

```ouro
import "../std/text.ouro";

-- Count nonblank logical lines after the current byte-oriented line split.
-- Whitespace-only lines do not contribute; this materializes the line list.
def nonblank_count (text : String) : Nat :=
  count_if String (fun line => notb (str_is_blank line)) (str_lines text);
```

Directive comments are different:

```text
-- @entry main
-- @bound(nodes <= 52)
```

A comment whose trimmed body starts with `@` participates in the source-directive surface. `@entry` marks an analyzer root; it does not change the function's type or make a non-entry value runnable. Bounds and other recognized annotations have tool-specific meanings, not a universal runtime-complexity or correctness proof. The documentation generator excludes marker lines from prose. [Canonical source/directives][canonical] · [Doc scanner][doc-model]

Do not copy a suppression or bound from unrelated code merely to satisfy a gate. Preserve the reason and scope of a legitimate exception. Likewise, do not strip directives while “removing comments”: semantic compaction and source-aware tools have different responsibilities.

Canonical compact source is an internal compiler representation, not a recommended human authoring format. Write readable source and let the toolchain derive its compact form.

## 20. Formatting, linting, fixing, and the development loop

Use the existing host bootstrap and tool setup from [Getting started][getting-started]. A POSIX shell, Python, and a C compiler support the documented hosted bootstrap path. Native program output currently targets **Windows x86-64 PE**; being able to run the hosted tools on another OS does not make the resulting application native to that OS. [Tooling][tooling]

### A focused daily loop

From an Ouro checkout, with the example files from section 17 in `handbook/`:

```sh
# Edit, then normalize source layout.
sh scripts/ouro1.sh fmt --write handbook/count_core.ouro handbook/count_cli.ouro

# Check the entry point and its complete import closure.
sh scripts/ouro1.sh check handbook/count_cli.ouro

# Apply the current application-oriented quality policy.
sh scripts/ouro1.sh lint --deny --profile project handbook/count_core.ouro handbook/count_cli.ouro

# After creating the test file in section 21:
sh scripts/ouro1.sh test handbook/count_test.ouro

# Emit the current supported native target.
sh scripts/ouro1.sh build handbook/count_cli.ouro --target x86_64-windows --out _build/count.exe
```

Run the emitted `.exe` in a supported Windows execution environment. `ouro1 run FILE.ouro` is a build-and-execute convenience for the native path; it is not portable interpretation of IO on every host. Build flags belong to `build`, not to a child program's argument list.

Check earlier whenever a change is syntactically or semantically uncertain; there is no reason to wait for lint to discover a type error. After a rewrite, repeat the relevant checks and tests. Use targeted tests while developing and the application's full test inventory before accepting the change.

Pure evaluation can answer small questions without building a CLI:

```sh
sh scripts/ouro1.sh eval std/prelude.ouro --eval 'add 2 3'
sh scripts/ouro1.sh eval std/prelude.ouro --eval 'notb True' --type Bool
```

The evaluator's default result type is Nat; provide `--type` for other results. `--print NAME` selects a named value. This is not evidence that arbitrary runtime IO can execute during type conversion. [Evaluation commands][getting-started]

### Formatting is conservative, not a full reprint

```sh
sh scripts/ouro1.sh fmt handbook/count_core.ouro
sh scripts/ouro1.sh fmt --check handbook/count_core.ouro
sh scripts/ouro1.sh fmt --write handbook/count_core.ouro
```

The first form previews; `--check` checks for a clean result; `--write` saves it. The formatter normalizes such details as end-of-line handling, tabs, trailing whitespace, pipe spacing, and final newline, with a limited rule for flat multiline comma calls. It deliberately preserves many continuation layouts instead of reprinting every AST into one universal layout. [Formatter behavior][tooling] · [Implementation][formatter]

The checked pipeline compares token kinds and literal spellings and requires an idempotent result. It may refuse a valid file when normalization would alter a literal. Treat refusal as a diagnostic, not as authorization to force a text rewrite. Do not repeatedly undo the formatter's accepted output to preserve a personal spacing rule.

### Lint is not analyze, and neither is check

| Tool | Use it for | Do not infer |
| --- | --- | --- |
| `ouro1 check` | Compiler acceptance of the source/import closure. | Correct business behavior, complete tests, or failure-free host execution. |
| `ouro1 lint` | User-facing language, style, and semantic findings under the chosen profile. | A complete compiler check or universal must-use/error-path proof. |
| `ouro1 fix` | The current authorized rewrite subset and review suggestions. | That every lint diagnostic has an automatic repair. |
| `ouro1 analyze` | Repository-graph, architecture, and heavier opt-in structured analysis. | That repository policy is a language rule or a mandatory daily app gate. |

`--deny` makes lint suitable as a failing quality gate rather than merely advisory output; the selected profile determines policy and severities. For example, the documented collection-composition family is warning-level in baseline/project and deny-level in strict/release. This does not change its review-only edit status. A stricter severity is not a stronger compiler theorem. [Tool split][quality] · [Profiles and semantic boundaries][clippy] · [Composition policy][collection-perf]

Useful targeted forms include:

```sh
sh scripts/ouro1.sh lint --deny --family language handbook/count_core.ouro
sh scripts/ouro1.sh lint --deny --family semantic --profile project handbook/count_core.ouro
sh scripts/ouro1.sh analyze --enable-style --scope handbook/count_core.ouro
```

The last command is an optional targeted analyzer investigation, not an additional required typing pass. Normal Ouro application edits do not require the compiler repository's full bootstrap, trust-boundary, mutation, structural-clone, and release gates.

### Automatic fixes have a narrower publication boundary

```sh
sh scripts/ouro1.sh fix handbook/count_core.ouro
sh scripts/ouro1.sh fix --check handbook/count_core.ouro
sh scripts/ouro1.sh fix --write handbook/count_core.ouro
```

Inspect the preview and review the saved diff. At the reviewed revision, the **production planner and certificate pipeline** authorize the following split:

| Publication status | Rule families |
| --- | --- |
| Automatic mechanical edits, subject to planning/trivia/certificate checks | `dup-import`, `do-bind`, `double-semi`. |
| Review-required suggestions, not automatically authorized semantic rewrites | `dead-let`, `identity-let`, `list-literal`, `peano-literal`, `unused-binder`, `unreachable-arm`, `import-alias`, `list-type`, `nonrec-fix`. |

**Source/documentation discrepancy:** parts of the quality/tooling prose describe a wider automatic subset. The current `fx_applicability` in `tools/fix/plan.ouro` and syntax-only certificates in `tools/fix/proof.ouro` are narrower, including for dead-let and identity-let edits. This handbook follows those production owners. [Planner][fix-plan] · [Certificates][fix-proof] · [Convergence pipeline][fix-pipeline]

The write path performs additional checking and guarded publication. Do not bypass those safeguards by piping a raw internal candidate directly into a source file. Compile acceptance of a candidate alone does not establish semantic equivalence: removing a callback, changing a binder, or changing public labels also requires the corresponding reasoning and tests.

For a suspected false positive, inspect the resolved declaration and triggering expression. Reduce it to a focused example where practical. Do not “fix” a diagnostic by dropping an error, broadening a suppression, manufacturing success, or swapping in a same-spelled function. An incomplete frontend or exhausted analysis is a failure to analyze, not a clean bill of health.

### Hosted wrappers and standalone native tools are different entry points

The shell wrapper documents the broad `ouro1` command surface. The current standalone `coil.exe` dispatch is narrower: use the separately built native tools such as `ouro-test.exe`, `ouro-fmt.exe`, and `ouro-pkg.exe` for those operations. Do not invent `coil test`, `coil pkg`, or equivalent native subcommands because the hosted wrapper accepts a similarly named operation. Likewise, `build --profile dev|release` without an application source is the toolchain build/cache surface, not a generic application optimization knob. [Current command boundaries][tooling] · [Package dispatch][packages]

## 21. Testing programs, not just acceptance

Put pure application behavior in a module that tests can import without importing another executable's `main`. Name ordinary discoverable test files `*_test.ouro`. The standard test API is small: `Test`, `assert_true`, String-valued `assert_eq`, and `test_run`. Do not invent polymorphic assertions, attributes, fixtures, or a property-testing DSL. [Test API source][test] · [Maintained example][test-sample]

The following file tests the pure module from section 17.

**`handbook/count_test.ouro`:**

```ouro
import "../std/test.ouro";
import "count_core.ouro" as Count;

private def rejects (arguments : List String) : Bool :=
  match Count.count_input_path arguments with
  | Left _ => True
  | Right _ => False
  end;

private def accepts_path (arguments : List String) (expected : String) : Bool :=
  match Count.count_input_path arguments with
  | Left _ => False
  | Right actual => str_eq actual expected
  end;

def cases : List Test :=
  [ assert_true "empty input" (eq_nat (Count.count_nonblank "") 0)
  , assert_true "blank lines ignored"
      (eq_nat (Count.count_nonblank "first\n \nsecond\n") 2)
  , assert_eq "count rendering"
      (str_of_nat (Count.count_nonblank "one")) "1"
  , assert_true "missing filename" (rejects ["count-nonblank"])
  , assert_true "unknown option"
      (rejects ["count-nonblank", "--unknown", "value", "file.txt"])
  , assert_true "incomplete long option"
      (rejects ["count-nonblank", "--output"])
  , assert_true "extra filename"
      (rejects ["count-nonblank", "one.txt", "two.txt"])
  , assert_true "dash-prefixed path after terminator"
      (accepts_path ["count-nonblank", "--", "-notes.txt"] "-notes.txt")
  ];

-- @entry main
def main : IO Unit := test_run cases
```

`assert_eq` compares Strings. For a Nat property, use `assert_true` with the relevant Nat equality, or intentionally test a String rendering as the third case does. A test runner exiting zero is only useful when the intended tests were actually discovered and executed.

```sh
sh scripts/ouro1.sh test handbook/count_test.ouro
sh scripts/ouro1.sh test handbook
```

The documented native equivalent is `ouro-test.exe FILE_OR_DIRECTORY`, with a sibling `coil.exe` for checking/building. With no input, it discovers `*_test.ouro`; explicitly named files need not match that pattern. Discovery is sorted and skips generated/build and fixture-oriented directories. An empty discovery result fails rather than silently succeeding. A sibling `.golden` file, when present, is compared with program output. [Runner contract][tooling]

For this CLI, add executable integration coverage for missing files, unreadable paths, successful empty files, exact stdout/stderr, and nonzero exits. Use temporary inputs under an explicit test directory and a current checked process API when invoking the program. Do not make tests depend on arbitrary directory enumeration order, the current wall clock, or an installed shell utility that the deployment does not require.

Negative *input* cases belong in application tests. Intentionally rejected *source* programs belong in a compiler/fixture harness that expects rejection, not in ordinary positive discovery. The repository's parser desugaring pairs, exact diagnostic fixtures, mutation laws, and golden tool suites are evidence for language/tool maintenance; ordinary applications need the subset that tests their own contracts. [Surface fixtures][ergo-tests] · [Parser agreement tests][span-tests]

## 22. Project organization and packages

Start with relative source imports; a package system is not required to organize a small program. A larger application might use this layout:

```text
my-tool/
  src/
    domain.ouro          # data and pure domain operations
    decode.ouro          # input validation and typed errors
    main.ouro            # effects, argument policy, reporting
  tests/
    domain_test.ouro
    decode_test.ouro
  vendor/
    ouro/                # illustrative pinned checkout, not a package convention
  Ouro.seal              # only when using the current package/configuration surface
  Ouro.lock              # generated resolution record
  _ouro_pkgs/            # generated vendored package sources
```

`vendor/ouro/` is one explicit way to place a pinned toolchain/stdlib source tree inside an application's root. It is **not** a directory that the package manager creates automatically. Use the arrangement your build actually maintains, and adjust imports accordingly. For that illustrative layout, a file in `src/` can import `"../vendor/ouro/std/text.ouro"`; a test can import `"../src/domain.ouro"`.

Keep implementation helpers local/private. Avoid depending on another executable's `main` or on accidental transitive names. Split a pure library away from CLI-specific types when another consumer needs it independently. Generated vendor content is not the place to maintain handwritten fixes.

### The package contract that exists now

The current package manager resolves from a **local directory registry**, vendors source into `_ouro_pkgs/<name>/`, and writes `Ouro.lock`. Installed files are imported by ordinary relative paths. There is no package-specific import resolver. [Package guide][packages]

`Ouro.seal` is not TOML. Its version-one form uses a header and named blocks. Its quoted strings do not process escapes; do not copy Ouro String-literal escape syntax into this separate format:

```text
seal 1

project {
  name = "my-tool"
  version = "0.1.0"
}

deps {
  greet = "^0.1.0"
}

registry {
  source = "../registry"
}
```

That example requires a matching local `greet` package; it is not a request to a public registry. From `src/main.ouro`, the documented vendored layout permits:

```ouro
import "../_ouro_pkgs/greet/src/lib.ouro";
```

Use the native `ouro-pkg.exe` from the project directory; keep its checker beside it. For example, with the toolchain installed at the illustrative path `C:\src\ouro`:

```powershell
$pkg = "C:\src\ouro\_build\native\ouro-pkg.exe"
& $pkg install
& $pkg lock
& $pkg verify
```

`verify` checks the recorded contents and typechecks installed `.ouro` files through the sibling checker. The current deterministic digest detects drift; it is not authenticated supply-chain provenance or a cryptographic content identity. Lock formats and package behavior are part of the pinned toolchain contract.

Do not invent a public/network registry, multiple simultaneous versions per package name, `pkg:` imports, `coil publish`, or native `coil.exe pkg` dispatch. Change a dependency's source package or registry entry and reinstall, rather than editing `_ouro_pkgs/` by hand. [Current package limits][packages]

## 23. Compact cookbook

The earlier examples are also reusable recipes: [private helpers](#2-modules-visibility-and-dependency-direction), [import ambiguity](#3-imports-that-preserve-ownership), [local helpers](#6-local-structure-let-blocks-where-and-pipes), [small ADTs and records](#7-data-modeling-without-unnecessary-proofs), [structural recursion](#9-structural-recursion-that-the-checker-can-see), [typed failures and file reads](#12-errors-propagation-and-validation), [list transformations](#14-collections-iteration-and-ranges), [process execution](#16-filesystem-and-process-programs), and the linked [CLI](#17-a-small-cli-with-honest-failure-behavior)/[test](#21-testing-programs-not-just-acceptance) example. Do not copy a primitive implementation when the recipe identifies a suitable library function.

### Decode structured input without turning failure into a default

```ouro
import "../std/jsonx.ouro", "../std/result.ouro";

inductive NameDecodeError : Type :=
  | NameJsonRejected : NameDecodeError
  | NameMissingOrNotString : NameDecodeError;

def decode_name (text : String) : Either NameDecodeError String :=
  let? (Left, Right) : Either NameDecodeError String do
    let document : Json :=
      (result_from_maybe NameDecodeError Json NameJsonRejected
        (parse_json text))?;
    let name : String :=
      (result_from_maybe NameDecodeError String NameMissingOrNotString
        (jsonx_get_string document "name"))?;
    name
  end;
```

This preserves parse rejection separately from field extraction failure. The second error deliberately combines absence, a non-object input, and a non-String member because that is what the chosen getter can establish. It also does not reject an empty String name; add a separate domain validation if needed. [JSON accessors][jsonx] · [Maybe-to-result conversion][result]

### Decode strict hexadecimal bytes

```ouro
import "../std/bytes.ouro";

def decode_hex_strict (text : String) : Maybe (List Nat) :=
  hex_decode (str_codes text);
```

Unlike `hex_decode_str`, this does not pre-filter unwanted characters. Odd length or an invalid nibble returns `Nothing`; empty input is a valid empty byte list. Wrap that absence in a domain error when the caller needs a reason category. [Hex decoder][bytes]

### Convert an entire list, failing at the first rejected item

In the `AmountError` module from section 12, add `import "../std/collections.ouro";` to the imports before the declarations. Then:

```ouro
def parse_amounts (texts : List String) : Either AmountError (List Nat) :=
  list_traverse_result AmountError String Nat parse_amount texts;
```

Use `filter_map` instead only when dropping rejected items is the actual specification. A parser that silently discards invalid configuration entries is a different program, not a faster version of this one. [Traversal source][collections]

### Keep range-construction and pull-limit errors distinct

```ouro
import "../std/range.ouro";

def selected_range : Either NatRangeError NatRange :=
  nat_range_by 3 (nat_range_inclusive 10 0);
```

A consumer first handles this construction error, then handles `iter_from_nat_range`, then the bounded collection/fold result. That may look more explicit than one large expression, but the errors describe different decisions: invalid step, source behavior, and insufficient traversal budget. Map them into one application error only at a boundary that can preserve their meaning. [Range implementation][range] · [Iterator errors][iter]

## 24. Common Ouro anti-patterns

| Weak pattern | Why it is problematic here | Preferred replacement |
| --- | --- | --- |
| Import a large umbrella and depend on whatever short names happen to appear. | Transitive visibility and collisions become hidden dependencies. | Direct task imports, qualification, and selective exposure where useful. |
| Prefix a helper with `_` and assume it is private. | Visibility is explicit and declarations are public by default. | `private def` or an ordinary local helper. |
| Copy an educational module's `Nat` beside the standard `Nat`. | Same spelling/shape does not give the same family or representation identity. | Reuse shared standard types, or keep a standalone demo isolated. |
| Add `fix` to every helper, or recurse on a computed “smaller” value. | A recursive shape needs checked structural descent, not a mathematical guess. | Ordinary functions for nonrecursion; matched subterms or an honest bounded interface for recursion. |
| Add a wrapper named `NonZero` while its constructor still accepts zero. | The claimed invariant is not enforced. | A representation that actually excludes the bad state, or explicit validation without a false type-level claim. |
| Convert a failed parse to zero, empty text, `JNull`, or a dropped row. | Malformed input becomes a valid-looking result. | Typed failure, or a clearly documented optional/default policy. |
| Use `hex_decode_str` as strict validation. | It removes non-hex characters first. | `hex_decode (str_codes input)` with explicit failure handling. |
| Execute checked IO and ignore its result. | The action may have failed even though its type checked. | Match, propagate, or perform verified recovery before reporting success. |
| Treat `IO (Either E A)` as a catch-all runtime exception channel. | Some current host failures are process-terminal. | Respect the operation/backend contract and test publication/recovery boundaries. |
| Assume `any`/`all` short-circuit, or that range pull count equals yield count. | The current implementations have different evaluation/budget rules. | Use an explicit early-exit traversal and count all iterator observations. |
| Build a list by repeated `snoc`, or choose naive `reverse` for a large list. | The source implementations repeatedly rebuild prefixes. | Direct combinators, `Cons` plus one reversal, or `reverse_lin`. |
| Render a `CommandSpec` and execute the resulting string through a shell. | Rendering is for display, not shell quoting. | Execute program and argv separately through the appropriate process runner. |
| Interpret an empty compatibility walk as a proven empty directory. | Failed or incomplete walks can be collapsed to an empty list. | Inspect the checked walk outcome. |
| Silence quality tools by weakening error paths or blindly applying suggestions. | Lint is not acceptance, and review-only fixes lack automatic authorization. | Inspect the finding, preserve behavior, then check and test the actual change. |
| Introduce proofs, wrappers, or modules without a consumer-visible invariant or responsibility. | Complexity grows without making invalid programs harder to write. | The simpler record, inductive, function, or validation result. |

The table summarizes the implementation and contracts cited in the corresponding sections; it does not make every style recommendation a compiler rule.

## 25. Rules for AI-generated Ouro

1. **Use the checked-out revision as authority.** Read the local `AGENTS.md` where applicable, current syntax/tool docs, and nearby maintained `.ouro` sources. Do not implement from `future/` sketches or memories of another Ouro revision.
2. **Resolve names to their owner.** Inspect the declaration and signature. An alias exposes its direct source unit, not an arbitrary transitive namespace; selected local renames do not rename qualified members.
3. **Preserve explicit type arguments unless a declaration opted into marked inference.** Do not silently turn ordinary `map`, `Just`, `Nothing`, `Left`, or `Right` into another language's implicit-generic API.
4. **Use only demonstrated syntax.** Do not invent methods, traits, macros, declaration defaults, empty `f()` calls, general pattern guards, arbitrary record patterns, or an unrestricted recursion facility. Named calls, trailing callbacks, marked parameters, and `let?` each have narrower current contracts.
5. **Choose existing standard APIs before adding helpers.** Read their bodies when strictness, allocation, ordering, or error policy matters. A familiar name or `_checked` suffix is not sufficient evidence.
6. **Keep failures typed and observable.** Do not repair a type mismatch by returning a success default, discarding a parser result, or hiding a checked result behind `_unused`. Preserve error categories when mapping them.
7. **Keep action execution explicit.** `let` can store an action; `let!` executes one inside `do`. Reusing an action value does not memoize the world. Do not invent concurrency behind `std/async`.
8. **Make recursive descent visible.** Prefer standard traversals; otherwise recurse on checked subterm binders or an explicitly bounded state machine with an honest limit result.
9. **Give public APIs stable, readable signatures.** Keep helpers private/local, respect public argument labels, and avoid stronger type-level claims than the representation enforces.
10. **Validate with the real tools when available.** Check compiler acceptance, run focused tests, use formatter/linter, and review rewrites. Tool refusal, incomplete analysis, and budget exhaustion are not successful checks.
11. **Preserve semantics while optimizing.** Respect callback order, failure, sharing, and IO boundaries. Describe unmeasured work reductions as such; do not fabricate benchmark numbers, zero-copy behavior, or backend guarantees.
12. **Report verification honestly.** Distinguish source review, authored tests, compiled snippets, executed tests, and measured performance. Record the revision and exact commands actually run.

## 26. Quick reference

### Surface forms worth remembering

These are schematic forms, not one file to compile:

| Purpose | Form / boundary |
| --- | --- |
| Definition | `def name (argument : A) : B := body;` |
| Hidden helper | `private def helper ...` |
| Lambda | `fun (argument : A) => body`; shorter binders need a suitable expected type. |
| Ordinary application | `f a b` or `f(a, b)`; no tuple or implicit Unit. |
| Dependent function | `(value : A) -> B value` |
| Marked parameter | `def f {A : Type} ...`; bounded opt-in inference, not a blanket rule. |
| Local helper | `let helper (value : A) : B := expression in body` |
| Pure block | `let { let value := expression; final_expression }` |
| Postfix helpers | `expression where let helper ... := ...; end` |
| Alias/selective import | `import "file.ouro" as M exposing (original as local_name);` |
| Scoped open | `open M in expression` |
| Match | `match value with \| Constructor fields => body ... end` |
| Safe product destructure | `let (MkPair left right) := pair in body` |
| Conditional constructor case | `if let Just value := optional then use value else fallback` |
| Typed propagation | `let? (Left, Right) : Either E A do let x : B := expression?; payload end` |
| Maybe fallback | `optional ?? fallback`; write `(optional ?? fallback) \|> f` to pipe the selected value. |
| IO sequencing | `do let! value := action; next_action` |
| Pure IO return | `io_pure A value` |
| Tail sharing | `[first, second, ..rest]` |
| Literal Nat range | `0..10` / `0..=10`, with `std/range.ouro`. |
| Record update | `{ value with field := replacement }`, with known nominal result type. |

Use `Maybe` for absence, `Either` for a failure reason, and validation for independent accumulated errors. Prefer `nth_maybe` over a fabricated index default, `count_if` over counting a filtered list, `reverse_lin` over the naive source reversal, and typed process specifications over shell strings.

### Everyday commands

In this reference, `FILE`, `TEST`, `NAME`, and `TYPE` are placeholders for actual paths or declarations:

```sh
sh scripts/ouro1.sh check FILE.ouro
sh scripts/ouro1.sh eval FILE.ouro --print NAME --type TYPE
sh scripts/ouro1.sh eval FILE.ouro --eval 'EXPRESSION' --type TYPE
sh scripts/ouro1.sh fmt --check FILE.ouro
sh scripts/ouro1.sh fmt --write FILE.ouro
sh scripts/ouro1.sh lint --deny --profile project FILE.ouro
sh scripts/ouro1.sh fix FILE.ouro
sh scripts/ouro1.sh fix --write FILE.ouro
sh scripts/ouro1.sh test TEST.ouro
sh scripts/ouro1.sh build FILE.ouro --target x86_64-windows --out _build/app.exe
sh scripts/ouro1.sh run FILE.ouro
```

Omit `--type` only when the evaluator's Nat default is appropriate. `fix` is not an automatic repair for every warning. `build`/`run` above use the current Windows-native target; standalone native tool dispatch differs from the hosted wrapper. See [tooling][tooling] for setup and exact command limits.

### Fast standard-library choices

`types`/`prelude` for the shared pure base; `text` for practical byte-oriented text; `collections` for safe indexing and traversals; `iter`/`range` for bounded pull processing; `result`/`validation` for failure policy; `cli` for typed arguments; `fsx` plus checked `fs_walk`/replacement APIs for files; `json`/`jsonx` and `csv`/`tablex` for structured data; `processx` for subprocesses; `test` for application assertions. Check the [API index][api] for the exact declaring file and signature.

## 27. Code-review checklist

- [ ] **Acceptance:** The changed source and relevant import closure pass the actual compiler; no unresolved holes, invented features, or hidden assumptions were substituted for a solution.
- [ ] **Types and invariants:** The representation enforces the properties claimed for it. Dependent types or wrappers remove a real class of misuse rather than adding ceremony.
- [ ] **Imports and public API:** Declaration ownership is clear, ambiguity is resolved deliberately, helpers are local/private where appropriate, and public names/labels changed only intentionally.
- [ ] **Failure and effects:** Required input is validated; errors remain distinguishable and observed; success follows completed work or real recovery; stored actions are not mistaken for executed or memoized results.
- [ ] **Patterns and recursion:** Cases are complete under the current constructor rules; recursive calls use accepted structural descent; any budget has defined units and an honest exhaustion outcome.
- [ ] **Library use and cost:** Existing practical APIs are reused, their strictness is understood, and the change avoids demonstrated redundant traversal, conversion, allocation, file rewriting, or process spawning.
- [ ] **Host boundaries:** Byte/scalar assumptions, filesystem completeness/publication, process exit/capture policy, and target-platform requirements match the actual APIs used.
- [ ] **Tests:** Successful, malformed, absent, empty, boundary, and failure cases relevant to the change are covered; ordering and output are deterministic where required; the intended tests actually ran.
- [ ] **Tools and rewrites:** Formatter/linter output was reviewed; a review-only suggestion was not mistaken for an automatic proof; rewritten code was rechecked and retested.
- [ ] **Clarity and evidence:** Comments explain contracts or non-obvious reasoning, directives retain their meaning, and claims about execution or performance are supported by the checks actually performed.


[agents]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/AGENTS.md
[getting-started]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/getting_started.md
[syntax]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/syntax.md
[quality]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/quality.md
[clippy]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/clippy_grade_firewall.md
[collection-perf]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/clippy-collections-performance.md
[ergonomics]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/language/ergonomic-syntax.md
[checking]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/kernel_design.md
[effects]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/effects_design.md
[practical]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/practical_stdlib.md
[stability]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/stability.md
[canonical]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/canonical_source.md
[tooling]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/tooling.md
[packages]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/pkg.md
[api]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/docs/api/README.md
[prelude]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/prelude.ouro
[data]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/data.ouro
[types]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/types.ouro
[vec]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/vec_demo.ouro
[wf]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/wf.ouro
[io]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/io.ouro
[result]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/result.ouro
[listx]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/listx.ouro
[collections]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/collections.ouro
[iter]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/iter.ouro
[range]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/range.ouro
[text]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/text.ouro
[bytes]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/bytes.ouro
[jsonx]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/jsonx.ouro
[validation]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/validation.ouro
[args]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/args.ouro
[cli]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/cli.ouro
[fs]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/fs.ouro
[fsx]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/fsx.ouro
[processx]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/processx.ouro
[test]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/test.ouro
[formatter]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tools/fmt_pipeline.ouro
[fix-plan]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tools/fix/plan.ouro
[fix-proof]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tools/fix/proof.ouro
[fix-pipeline]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tools/fix/pipeline.ouro
[doc-model]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tools/doc_model.ouro
[term-checker]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/compiler/file_elab_term.ouro
[ergo-tests]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tests/language_ergonomics/cases.json
[span-tests]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/tests/source_span_tests.ouro
[tutorial-index]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/samples/tutorial/README.md
[tutorial-fix]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/samples/tutorial/05_fix.ouro
[file-sample]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/samples/examples/io_file_stats.ouro
[test-sample]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/samples/examples/test_demo.ouro
[string]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/string.ouro
[stringx]: https://github.com/eluvane/ouro/blob/182f7210c0e989cd7526b54e6c6a1a58f774134b/std/stringx.ouro
