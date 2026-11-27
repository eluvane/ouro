# Compiler checking

The [declaration checker](../compiler/file_elab.ouro) serves the frontend,
program builds, evaluation, compiler-source builds, and LSP. The independent
OCaml and Python replay paths are described in the
[archived artifact contract](kernel_core_artifact.md#archived-json-format).

## Core and declarations

Core includes universes, dependent functions, lambdas, applications,
let-bindings, global constants, inductives, constructors, dependent cases,
structural fixpoints, and typed literal forms. De Bruijn indices identify local
binders; display names do not determine equality.

`check_declarations` accepts two modes. `CheckExactCore` checks the supplied
Core terms as written. `CheckSourceCore` refines annotations and bodies before
checking them. `check_module` uses `CheckSourceCore` to check the complete
source declaration plan and rejects a plan with a missing required declaration.
Both start with an empty environment and use the same declaration rules.
Later declarations can use a declaration only after the checker accepts it.
Unknown globals, duplicate names, invalid constructor references, and
unresolved literals remain errors.

Import collection computes an ordered module closure. The frontend checks all
its declarations, including imported bodies and effect roots, before making a
`CheckedProgram`. Effect lowering must produce checkable Core; unsupported
handler combinations cannot skip declaration checking. Cycles and incomplete
dependency input fail at the import or declaration boundary.

Source-only entry points such as `compile_checked_source` have no filesystem
access or dependency inventory. They report missing-unit error `92` before
lowering for any unresolved import, including unused imports and imports in
effect roots. `compile_checked_from_decls` also rejects unresolved imports.
For source with imports, pass the complete module closure to
`compile_checked_units` or supply it with `--unit` when invoking the compiler
directly. The lexer distinguishes imports from the same text in comments
and string literals.

## Entry points and results

| Entry point or type | Contract |
| --- | --- |
| `check_declarations` | Check an ordered Core declaration list in the selected mode. Takes a cancellation callback. |
| `check_module` | Check the complete source plan in source mode and verify the required declaration set. |
| `DeclarationResult` | Complete accepted environment, or the failing declaration, phase, and typed failure. |
| `infer_checked`, `check_term_checked` | Checked term inference and expected-type checking. |
| `whnf_checked`, `normalize_checked`, `conv_checked` | Bounded pure reduction and conversion with explicit malformed-input and resource outcomes. |

`CheckFailure` distinguishes type failures, malformed Core, reduction failures,
resource limits, unsupported features, cancellation, internal failures, and
primitive-contract failures. `NormalizeResult` reports exhaustion as
`NormalizeExhausted`. Typed callers receive the original failure. Command-line
diagnostics map failures to compatibility codes, so distinct failure classes
can share a numeric code.

`check_declarations` polls its cancellation callback at declaration boundaries,
including before the first declaration. A failed or cancelled check returns a
typed error. Only a completed check returns the accepted environment.
Compatibility result views for older Ouro fixtures use the same checker.

## Inductives, cases, and structural recursion

Checking covers constructor universes, parameter and index counts, positivity,
dependent motives, branch types and coverage, and fixpoint metadata. Conversion
compares semantic fixpoint metadata such as arity and structural-argument index;
renaming a display binder does not change conversion.

Only leading lambda parameters identify a fixpoint's structural input. The
termination walk records that binder when it enters scope; annotations, local
bindings, case fields, and nested binders cannot stand in for an input that has
not been introduced. A nonrecursive body may still return a function without
an explicit lambda prefix.

An immediately applied nested fixpoint may inherit a strict-subterm witness
from its initial structural argument. The application must supply at least its
declared arity, and that argument must already be smaller than the enclosing
fixpoint's input. Only the structural parameter inherits the witness; an
accumulator may grow without becoming a decreasing argument.

The nested fixpoint is also checked independently. Bare or escaping recursive
functions, unchanged structural inputs, and calls through growing accumulators
remain rejected. A positive nested inductive occurrence is permitted only when
the declaration's parameter variance makes it positive; negative occurrences
remain rejected. These rules have positive, negative, and source-mutation tests.

Type computation performs pure supported reduction. IO, raw memory, and
platform calls are not executed by the checker. Intrinsic and extern
declarations are verified as contracts. Optimized standard types are identified
by resolved representation bindings, so an unrelated declaration with the
same display name does not acquire primitive semantics. See [Syntax](syntax.md)
for the declaration syntax and [TCB](tcb.md) for the pure dependency boundary.

## Implementation and ownership

| Area | Owner |
| --- | --- |
| Core terms, lifting, and substitution | `compiler/core.ouro` |
| Declaration data and typed failures | `compiler/file_check_model.ouro` |
| Derived environment indexes | `compiler/file_check_environment.ouro` |
| Input-work limits | `compiler/file_check_work.ouro` |
| Lookup, lift, substitution, and surface elaboration | `compiler/file_elab_lookup.ouro` |
| Reduction and conversion | `compiler/file_elab_core.ouro` and `compiler/string_nf_*.ouro` |
| Positivity and structural recursion | `compiler/file_elab_positive.ouro` and `compiler/file_elab_term.ouro` |
| Inference and expected-type checking | `compiler/file_elab_infer.ouro` |
| Declaration traversal | `compiler/file_elab.ouro` |
| Primitive identities and signatures | `compiler/primitive_*.ouro` |
| Checked program and diagnostic serialization | `compiler/checked_program.ouro` and `compiler/checked_program_output.ouro` |

Environment indexes are derived from accepted declarations. They accelerate
lookup without granting unchecked declarations authority. Type lookup projects
the selected entry directly, preserving numeric-name normalization, first-match
shadowing, and constructor reservations. The positivity walk
derives each earlier-tail index alongside its certificates. Certificates are
rebuilt from the declaration list with the same proof fuel and failure checks.
Deferred substitutions and application processing preserve binder scope and the
observable reduction budget. Input-work limits reject excessive input with a
typed resource failure before recursive checking. The same work limit charges
demanded local-definition expansion and lifting before materializing let
substitutions, including declaration candidates before source refinement.
The local-definition work check reuses the resolved value when an alias names
the immediately preceding closed atomic definition. This avoids traversing
earlier definitions repeatedly in those chains. Open and compound definitions
retain their binder scope.
Sort and function views require positive fuel and project already exposed
`CSort` and `CPi` fields directly without intermediate `Maybe` values. Aliases
and other heads retain the original bounded reduction path and typed failures;
declaration and input-work checks remain in place.
Crashes and process limits are separate test failures.

`CheckedProgram` is a compiler-owned representation, not an unforgeable module
seal. Native lowering rechecks a supplied wrapper's declarations and metadata.
The repository boundary gate restricts its constructor and success-result
owners and checks the documented pure import closure. It does not replace
semantic tests.

## Regression commands

Use the checker commands in the validation matrix.
[CI validation matrix](ci.md#validation-matrix)

The retained laws cover semantic contracts from the archived kernel corpus.
Generated properties exercise substitution, scope, reduction, type checking,
and rejection classes. For checker fault injection, OuroSmith first runs the
designated law on the unmodified checker, then requires the same law to
detect its assigned source mutation.
[OuroSmith fault injection](ouro_smith.md#process-limits-and-fault-injection)

The hardening suite executes retained laws in three cache modes. Scale and
checked-API depth probes enforce their own complete input and resource
contracts.
[CI profiles and report validation](ci.md#local-profiles)

[Core artifacts](kernel_core_artifact.md) distinguishes the current checked
snapshot from the archived JSON corpus.

These checks are executable regression evidence. The checker has no complete
machine-checked proof of soundness, normalization, substitution, positivity, or
structural recursion.
