<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=KERNEL&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="KERNEL banner"
  />
</p>

# Compiler checking

`compiler/file_elab.ouro` owns Ouro's declaration checker. The frontend,
program builds, evaluation, compiler-source builds, and LSP checking use this
implementation. The former independent OCaml and Python Core checkers and
their replay drivers are retired. The historical filename of this page remains
stable for existing links.

## Core and declarations

Core includes universes, dependent functions, lambdas, applications,
let-bindings, global constants, inductives, constructors, dependent cases,
structural fixpoints, and typed literal forms. De Bruijn indices identify local
binders; display names do not determine equality.

`check_declarations` checks exact Core. `check_module` checks the source
declaration plan and requires every selected declaration to be present. Both
start with an empty environment and use the same declaration rules. A
declaration is available to later declarations only after its type, body, or
inductive descriptor has passed checking. Unknown globals, duplicate names,
invalid constructor references, and unresolved literals remain errors.

Import collection computes an ordered module closure. The frontend checks all
its declarations, including imported bodies and effect roots, before making a
`CheckedProgram`. Effect lowering must produce checkable Core; unsupported
handler combinations cannot skip declaration checking. Cycles and incomplete
dependency input fail at the import or declaration boundary.

Source-only APIs have no filesystem or supplied dependency inventory. They
reject any unresolved import with the missing-unit error (`92`) before
lowering, including unused imports and imports in effect roots. Call
`compile_checked_units` with the complete module closure for importing source;
direct compiler invocations supply that closure with `--unit`. The declaration
entry point also rejects residual imports rather than dropping them from its
checking plan. Comments and string contents are not import declarations.

## Entry points and results

| Entry point or type | Contract |
| --- | --- |
| `check_declarations` | Check an ordered Core declaration list with a cancellation callback. |
| `check_module` | Check the complete source plan and required declaration set. |
| `DeclarationResult` | Complete accepted environment, or the failing declaration, phase, and typed failure. |
| `infer_checked`, `check_term_checked` | Checked term inference and expected-type checking. |
| `whnf_checked`, `normalize_checked`, `conv_checked` | Bounded pure reduction and conversion with explicit malformed-input and resource outcomes. |

`CheckFailure` distinguishes type failures, malformed Core, reduction failures,
resource limits, unsupported features, cancellation, internal failures, and
primitive-contract failures. `NormalizeResult` has no successful partial value:
exhaustion stays `NormalizeExhausted`. Host diagnostics preserve this
classification when mapping it to command exit status and diagnostic codes.

The cancellation callback is polled at declaration boundaries, including
before the first declaration. A cancelled or failed module does not return its
accepted prefix as a successful module. Compatibility result views for older
Ouro fixtures call the same checker and contain no separate typing traversal.

## Inductives, cases, and structural recursion

Checking covers constructor universes, parameter and index counts, positivity,
dependent motives, branch types and coverage, and fixpoint metadata. Conversion
compares semantic fixpoint metadata such as arity and structural-argument index;
renaming a display binder does not change conversion.

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
lookup without granting unchecked declarations authority. Deferred
substitutions and application processing preserve binder scope and the
observable reduction budget. Input-work limits reject excessive input with a
typed resource failure before recursive checking; crashes and process limits
are separate test failures.

`CheckedProgram` is a compiler-owned representation, not an unforgeable module
seal. Native lowering rechecks a supplied wrapper's declarations and metadata.
The repository boundary gate restricts its constructor and success-result
owners and checks the documented pure import closure. It does not replace
semantic tests.

## Regression commands

```sh
sh scripts/test_suite.sh --compiler-checking
sh scripts/ouro_repo_gate.sh --profile compiler-boundary
python3 scripts/kernel_hardening_suite.py
python3 scripts/kernel_scale.py --profile scale --out _build/kernel_scale/scale
python3 scripts/kernel_scale.py --profile depth --out _build/kernel_scale/depth
python3 scripts/ouro_smith.py --profile kernel --out _build/smith/kernel
```

The retained laws cover the previous kernel corpus's useful semantic contracts.
Typed generated properties exercise substitutions, scopes, reduction, checking,
and rejection classes. OuroSmith rebuilds source mutants and requires the
designated law to reject each fault after a clean baseline.

The hardening suite executes retained laws in three cache modes. Scale and
checked-API depth probes enforce their own complete input and resource
contracts. [CI](ci.md) describes required profiles and report validation.
[Core artifacts](kernel_core_artifact.md) distinguishes the current checked
snapshot from the archived JSON corpus.

These checks are executable regression evidence. The checker has no complete
machine-checked proof of soundness, normalization, substitution, positivity, or
structural recursion.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
