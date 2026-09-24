# Ouro concept and native transition

> **A language that helps write itself.**

**Document status:** current direction followed by a historical research concept;
neither is a language specification or a product-readiness promise.

**Comparative claims last externally checked:** 2026-07-27.

## Current direction: standalone native Ouro

The accepted native product target is in [Design](design.md); staged acceptance
is in [Roadmap](roadmap.md). [Architecture](architecture.md), [Build](build.md),
and [TCB](tcb.md) describe current implementation and host assumptions. The
research proposal below predates that decision and does not supersede it.

## Historical research concept

Sections 1–27 and the appendices below retain the earlier research proposal for
context. Their fixed independent-kernel requirement, optional self-hosting,
backend alternatives, phase ordering, and implementation-status claims are
superseded by the current direction above. They do not impose additional
release gates or authorize an alternative permanent backend. Consult the
canonical [Syntax](syntax.md) and [Tooling](tooling.md) pages for current language
behavior. The research labels below apply only within this historical proposal:

- **Fixed** — a direction invariant that changes only through an explicit
  architectural review.
- **Working hypothesis** — a decision that is good enough for the next prototype
  but not final.
- **Open question** — a fork where the project does not yet have enough data.
- **Research goal** — a high-risk research target outside the promises of the
  first version.
- **Fallback** — an intentionally allowed simplification or move to an existing
  platform.

## 1. Executive summary

Ouro is an experimental dependently typed language where verified generation and
self-applicable metaprogramming are central design axes. A small hand-written
kernel remains the fixed trusted boundary for a concrete language version;
components above it are gradually implemented in Ouro and may participate in
checked generation.

A "fixed kernel" does not mean the kernel source never changes. It means that
metaprograms, tactics, generators, and external tools cannot modify the rules for
accepting programs during elaboration or build. Kernel changes happen only as a
separate human-reviewed release with a new core-language version, renewed audit,
and migration plan.

The main Ouro experiment is not whether generation is possible. Existing systems
already support it in different forms. The question is whether systematic,
self-applicable, kernel-rechecked generation reduces the **total cost** of
developing checked programs: user code, proofs, generator construction,
debugging, regeneration, maintenance, and trusted-base audit.

The first practically meaningful Ouro version does not require a complete effect
system, full self-hosting, verified extraction, or deep self-generation. It needs
a narrow vertical slice:

1. a minimal core calculus and working type checker;
2. metavariables and holes;
3. simple elaboration;
4. restricted type-directed synthesis;
5. mandatory kernel rechecking of generated results;
6. provenance for generated declarations;
7. one demonstration task where generation payoff can be measured;
8. minimal interactive tooling.

The project should work first, become pleasant next, and become fast after that.
Here, "works" means not only passing a toy example but also having a reproducible
experiment whose negative result the project is willing to accept.

### 1.1. Status of key decisions

| Area | Status | Formulation |
| --- | --- | --- |
| Architectural identity | **Fixed** | Small hand-written kernel; metaprograms do not change the kernel; accepted generated core declarations are rechecked by the kernel. |
| Own kernel | **Fixed direction with review gates** | The first prototype is built around Ouro Core-0, but the need for a full custom toolchain is re-evaluated at checkpoints. |
| Target type theory | **Working hypothesis** | Predicative MLTT-like basis with explicit universes; exact sort system, cumulativity, and inductive fragment are not fully specified yet. |
| Generation | **Fixed** | Early payoff matters more than early language completeness. First synthesis arrives before complete inductives, effects, and extraction. |
| Progressive disclosure | **Working hypothesis** | A UX direction and benchmark question, not an already-proven property. |
| Effects | **Open question** | Algebraic effects, effect rows, indexed monads, and linear/quantitative types are considered separately. |
| Self-hosting | **Usable prototype goal** | Components above the kernel move to Ouro gradually; bootstrap reality stays explicit. |
| Deep self-generation | **Research goal** | Specifications may generate selected above-kernel components; autonomous self-improvement is not promised. |
| Hybrid AI | **Long-term optional layer** | AI proposes candidates but is not a source of truth and is not part of the kernel. |
| Product adoption | **Not a research-success criterion** | The research track succeeds if it produces a reproducible answer to the central question, including a negative answer. |

## 2. Central research question

> **Can a dependently typed language with a fixed hand-written kernel and
> self-applicable elaborator reflection reduce the total cost of developing and
> maintaining checked programs through kernel-rechecked generation, compared with
> comparable workflows in existing systems, without expanding the logical TCB,
> losing reproducibility, or moving the main complexity from user code into
> generators and debugging?**

The question allows a negative answer. It connects six mandatory parts of the
project:

- dependent types express checkable specifications and invariants;
- elaborator reflection gives metaprograms controlled access to syntax, goals,
  and type-checking services;
- generation creates implementations, proofs, or structural boilerplate;
- the fixed kernel independently checks final core terms and declarations;
- self-application allows generators and parts of the toolchain to be written in
  Ouro;
- success is evaluated by development cost, proof cost, debugging,
  reproducibility, and TCB impact, not by the number of announced features.

## 3. Main hypothesis and falsification criteria

### 3.1. Main hypothesis

**H1.** On tasks with regular structure and nontrivial invariants, untrusted
self-applicable generators using typed reflection and bounded synthesis can
reduce manual implementation volume, manual proof actions, and time to change a
program again. At the same time:

- every accepted result is independently rechecked by the kernel;
- the generator does not enter the logical TCB;
- committed artifacts are reproducible from pinned inputs and toolchain;
- the cost of writing and maintaining the generator is counted, not hidden;
- debugging generated code does not cost more than the manual work saved.

### 3.2. Null hypothesis and negative results

**H0.** After counting specifications, generator engineering, proof obligations,
provenance, debugging, and maintenance, generation does not deliver a stable win
or only works on toy tasks.

The following outcomes also count as negative results:

1. Useful synthesis requires search, reflection, or effectful primitives inside
   the kernel, noticeably expanding the logical TCB.
2. Generator bugs do not formally break soundness but make the system practically
   unusable because of instability, timeouts, or undebuggable artifacts.
3. The same capability invariants can be implemented on Lean, Idris,
   Rocq/MetaRocq, or Agda with less cost and a comparable trusted boundary.
4. A custom kernel delays the first generation payoff so much that the project
   never reaches the research vertical slice.
5. Reproducibility requires an environment so rigid that self-generation stops
   being practical.
6. User specifications and proof obligations are harder than the manual
   implementation, so generation only moves work around.

### 3.3. Experiments for the hypothesis

| Experiment | Built artifact | Measured | Acceptable negative result |
| --- | --- | --- | --- |
| E1. First vertical slice | Core-0, holes, bounded synthesis, kernel rechecking, one benchmark task | Time to checked artifact, manual edits, proof actions, generated AST share | Synthesis is not useful even on a preselected regular task |
| E2. Comparative prototype | Same generator idea on one existing system | Feasibility of capability invariants, TCB delta, effort | Existing host reproduces the idea more cheaply and without a new kernel |
| E3. Fault injection | Intentionally buggy generators and corrupted artifacts | Errors rejected by the kernel, diagnostics quality, DoS behavior | Kernel accepts an invalid term or the trust boundary is wider than claimed |
| E4. Regeneration and maintenance | Specification change after first program version | Regeneration time, manual merge/edit steps, provenance stability | Generated code is cheap to create but expensive to change or debug |
| E5. Self-application | A generator or elaborator tool written in Ouro | Bootstrap cost, determinism, performance, auditability | Self-application adds no benefit or creates cyclic dependencies without a clear trust story |
| E6. TCB audit | Versioned manifest of trusted components | Size, composition, mutation rate, and review cost of the TCB | "Small kernel" does not lead to a small practical trusted base |

### 3.4. Research success even if the product fails

The research track succeeds, even if Ouro does not become a standalone language,
when the following are published and reproducible:

- a positive or negative answer to H1;
- a minimal core checker and executable specification;
- a benchmark suite for verified generation;
- data on generator break-even costs;
- a provenance and deterministic-regeneration model;
- a comparative capability report against existing systems;
- documented pivots and reasons for rejecting architectural paths.

## 4. What Ouro is

Ouro is an experimental dependently typed programming system for studying four
things together:

1. **Checked generation.** A tool generates candidate core terms, declarations,
   or proofs; the kernel independently checks them before acceptance.
2. **Hole-driven development.** Users move from incomplete programs to complete
   ones through goals, refinement, and bounded search.
3. **Self-applicable metaprogramming.** Metaprograms are written in Ouro and
   applied to Ouro programs and selected system components above the kernel.
4. **Controlled trust boundary.** Soundness of an accepted core artifact must not
   depend on tactics, generators, external provers, or AI being correct.

Ouro connects programming and proof, but it does not equate type correctness with
requirement correctness. Types guarantee only the properties that are actually
encoded in the types and correctly connected to the outside world.

The target development model is:

> The user states a data model, type-level invariants, and local intentions.
> Elaboration and synthesis handle regular transformations and propose
> candidates. The kernel checks the resulting core. Tooling shows what was
> written by a human, what was generated, what inputs produced it, and what
> assumptions remain.

"Everything above the kernel in Ouro" describes a **target post-bootstrap
state**, not the initial implementation. Seed parsers, elaborators, CLIs, and
some tooling may be written in OCaml at first. They are replaced component by
component after the language exists.

## 5. What Ouro is not trying to do

The first Ouro version does not try to:

- generate complex applications autonomously from natural language;
- modify the kernel or expand its own authority;
- prove that a specification is correct merely because type checking succeeded;
- become a general-purpose production language before research data exists;
- implement a full effect system, linear types, verified extraction,
  self-hosting, and AI integration at the same time;
- declare that a custom kernel is necessary before a comparative prototype;
- replace Lean, Idris, Rocq/Coq, Agda, F*, or other systems;
- treat self-hosting as the same thing as self-generation, evolution, or
  self-improvement;
- treat provenance as semantic correctness proof;
- treat differential testing as extraction-correctness proof;
- guarantee absence of runtime errors outside explicitly modeled invariants,
  runtime, FFI, and backend assumptions.

## 6. Design principles

### 6.1. A small kernel as a fixed boundary

**Fixed.** The kernel must have a narrow, versioned input format and a minimal
responsibility set. Its size is evaluated not only in lines of code but also in
trusted primitives, conversion complexity, universe rules, inductive checking,
and required review effort.

### 6.2. Metaprograms do not change acceptance rules

**Fixed.** Metaprograms do not access mutable kernel internals, register new
typing rules, or disable checks. They may use versioned elaborator services and
produce candidates.

### 6.3. Generated core is always rechecked

**Fixed.** Any generated core term or declaration that enters the checked
environment follows the same kernel path as a hand-written result. Exceptions
must be explicitly marked as `unsafe` or external assumptions and forbidden in
release profiles.

### 6.4. Generation payoff appears before language completeness

**Fixed.** Generic effects, self-hosting, and verified extraction do not block
the first hole-filling experiment. The language must not spend years on kernel
work before it has measurable user-facing generation.

### 6.5. Work first, pleasant next, fast later

**Fixed.** Priority order: semantic correctness of the prototype, then a usable
feedback loop, then performance engineering. Optimizations, parallel elaboration,
and multicore work come after profiling.

### 6.6. Progressive disclosure is tested, not declared

**Working hypothesis.** The ability to start with ordinary functional code and
gradually introduce proofs is measured on frozen tasks and users. Complexity
must not be hidden behind the slogan "proofs are added only when needed."

### 6.7. Trust claims depend on the claim type

**Fixed.** Theorem acceptance, executable behavior, FFI safety, and reproducible
builds have different TCBs. This document does not use "trust only depends on the
kernel" without specifying the claim.

### 6.8. Reproducibility and semantic correctness are different

**Fixed.** Deterministic regeneration shows that the same inputs produce the same
artifact. It does not prove that the artifact matches intent. Kernel checking
shows well-typedness but not origin. Provenance explains origin but does not
prove the specification true.

### 6.9. The custom kernel is periodically rejustified

**Fixed.** Core-0 is the chosen starting path. A full custom production kernel
continues only if it demonstrates a capability or TCB advantage over a
host-language prototype.

### 6.10. Research success does not depend on adoption

**Fixed.** Mass ecosystem, market, and production deployment belong to the
product track. They are not conditions for completing the research experiment.

## 7. Architectural boundaries

### 7.1. Acceptance path

```text
surface source / specification
        │
        ▼
parser, desugaring, macro expansion                    [untrusted]
        │
        ▼
elaborator, unification, holes, totality, synthesis   [untrusted]
        │
        ├── provenance recorder / source maps          [integrity-sensitive]
        ▼
versioned Core Package
  { declarations, universe constraints, assumptions,
    generated-artifact references, core-format version }
        │
        ▼
hand-written kernel                                    [logical TCB]
        │
        ▼
Checked Environment
        ├── kernel evaluator / interpreter
        ├── tooling and query services
        └── erasure → IR → backend → runtime / FFI     [execution TCB]
```

The kernel accepts neither surface syntax, tactic state, nor generator objects.
It accepts a versioned core representation with closed metavariables and an
explicit assumption list.

### 7.2. Component split

| Component | Responsibilities | Logical TCB? | Execution TCB? |
| --- | --- | ---: | ---: |
| Kernel | Core typing, conversion, universe checks, declaration validation | Yes | Indirectly: it defines source semantics |
| Core decoder/serializer | Safe reading of canonical core format | Yes, if bugs change parsed terms | Yes |
| Parser/desugarer | Surface syntax, source locations, sugar | No | No, if output is rechecked; it can distort intent |
| Elaborator/unifier | Implicits, constraints, overloads, metavariables | No | No for soundness; yes for usability/build availability |
| Totality/coverage layer | Check/build structurally recursive definitions | Should not, if kernel checks recursors | No directly |
| Tactics/synthesis/generators | Candidate search, proof scripts, derivations | No | No for accepted core; may cause DoS or bad codegen |
| Metaprogram runtime | Compile-time program execution | No for logical soundness when rechecked | Yes for availability/reproducibility |
| Extractor/erasure | Checked core to executable IR | No for theorem acceptance | Yes until verified |
| Backend compiler/linker | Machine code | No | Yes |
| Runtime/effect handlers/GC | Effectful program execution | No | Yes |
| FFI boundary | Foreign code and data | No | Yes |
| LSP/tooling | Goals, diagnostics, navigation, provenance UI | No | No, but critical for usability |
| External AI/provers | Candidate generation | No | No, if output is rechecked and no trusted oracle is used |

### 7.3. Bootstrap reality

The first working implementation may have:

- an OCaml kernel;
- seed parser and elaborator in OCaml;
- runtime in OCaml or on top of a selected backend;
- build scripts and tests using host tooling.

That does not violate the self-hosting goal. It would be a violation to hide
these dependencies or call them untrusted for claims where they are required.

The move to Ouro implementations is componentwise. A simultaneous rewrite of the
whole compiler stack is forbidden as a roadmap strategy because it increases
bootstrap risk and delays generation payoff.

## 8. Core language and kernel

### 8.1. Target foundation

**Working hypothesis.** Ouro targets a predicative MLTT-like system with an
explicit universe hierarchy, dependent function types, equality, and inductive
families. PCUIC/MetaRocq is treated as an important source of comparative
decisions and metatheory, but Ouro is not described as "a PCUIC fragment" until
there is an exact mapping for syntax, typing, conversion, universes, and
inductives.

"Full dependent types" is not used as a specification. Expressiveness is defined
only by published core rules and tests.

### 8.2. Core profiles instead of implementing everything at once

#### Core-0: generation bootstrap profile

Minimum for the first vertical slice:

- variables, `λ`, application, dependent `Π`, `let`;
- explicit universe levels in a restricted form;
- definitional equality with fixed reduction rules;
- a small sealed set of data primitives or prechecked declarations: `Unit`,
  `Bool`, `Nat`, products/sums, equality;
- recursors for those primitives;
- minimal constants and modules;
- no unrestricted general recursion;
- no user-defined general inductive declarations;
- no effects or runtime primitives inside the logical core.

Core-0 is not the final theory. Its job is to enable holes, elaboration, and
kernel-rechecked generation before implementing the full inductive/universe
stack.

#### Core-1: usable research core

Added after the first generation experiment:

- generic strictly positive indexed inductive types;
- universe constraints and a chosen cumulativity model;
- generated recursors and kernel validation for them;
- structural recursion elaborated to recursors;
- surface-level coverage checking;
- well-founded recursion through library constructions and proof obligations;
- versioned quotation representation for metaprogramming.

#### Core-2: research extensions

These are not automatically kernel features:

- separate `Prop` or proof-irrelevant sort;
- impredicativity;
- large eliminations, if they become a separate issue for the chosen sort system;
- quotient types;
- η-rules in conversion;
- coinduction;
- native primitives;
- effect typing;
- linear or quantitative typing.

Each requires a separate design note covering metatheory, conversion, extraction,
and TCB impact.

### 8.3. Kernel responsibilities

The kernel must:

1. check well-scopedness of core terms and environments;
2. check typing of variables, binders, applications, lambdas, lets, and constants;
3. implement or check definitional equality;
4. check universe levels, constraints, and cumulativity if the profile supports
   them;
5. check inductive-family declarations, including positivity and universe
   conditions, when generic inductives become primitive core features;
6. check generated recursors or independently build them from validated
   inductive declarations;
7. reject unresolved metavariables and implicit holes;
8. treat assumptions/axioms as explicit environment parts;
9. emit machine-readable failures localized in the core package;
10. expose a stable, fuzzable, versioned input format.

### 8.4. What is not a kernel responsibility

The kernel does not need to:

- parse user-facing syntax;
- infer implicit arguments;
- resolve overloads and type classes;
- perform proof search;
- execute tactics and generators;
- check pattern coverage as a surface property;
- choose recursion schemes;
- provide friendly diagnostics;
- execute effects;
- extract runtime code;
- manage LSP, cache, or package dependencies;
- store the full provenance graph.

A component does not become part of the kernel just because it is important.

### 8.5. Termination and coverage

**Working hypothesis.** The logical core has no unrestricted fixpoint. Surface
structural recursion is transformed into recursors. Bugs in the totality checker
may reject correct programs or produce bad terms, but the kernel must not accept
unrestricted recursion as proof.

For more general recursion, the project considers:

- well-founded recursion with an explicit decreasing proof;
- sized or guarded approaches as a separate research branch;
- partial runtime definitions that are opaque to conversion and forbidden in
  proofs/types.

Coverage is an elaborator responsibility. The elaborator compiles pattern
matching into eliminators. The kernel checks the resulting term but does not need
to reconstruct the original pattern matrix.

### 8.6. Universes and cumulativity

Universe checking is one of the project's main risks. Therefore:

- representation of universe expressions is chosen before large elaborator work;
- the universe solver may be untrusted, but the kernel must independently check
  constraints or certificates;
- Core-0 may restrict polymorphism, but must not use `Type : Type` as a shortcut
  for proof-sound claims;
- cumulativity is not a "simple option": its effect on inductives, conversion,
  and elaboration is tested separately;
- failure to stabilize universe design triggers moving the experiment to an
  existing kernel.

### 8.7. Inductives, positivity, and large elimination

**Open question.** Core-1 must choose one model:

1. the kernel directly checks positivity and builds recursors;
2. the untrusted elaborator builds declarations and certificates that the kernel
   checks;
3. a restricted set of inductive schemas compiles to a simpler core.

The first path is simpler initially but grows the kernel. The second may reduce
TCB size but requires a formal certificate format. The third accelerates the
vertical slice but limits the language.

`Large elimination` is not fixed as a separate feature until the sort system is
chosen. If v1 has no impredicative proof sort, some classic large-elimination
issues may not arise in the same form.

### 8.8. Conversion

Conversion must have:

- an exhaustive list of reduction rules;
- a reference evaluator for differential tests;
- an adversarial corpus for terms, universes, and inductives;
- resource limits against pathological normalization;
- separation between semantic equality and performance optimizations;
- a plan for an independent checker or verified implementation.

Optimized normalization-by-evaluation, caching, or native conversion is added
only after a simple reference path exists.

## 9. Elaborator, holes, totality, and synthesis

### 9.1. Elaborator

The elaborator transforms convenient surface language into explicit core. It
handles:

- names and scopes;
- implicit arguments;
- metavariables and constraints;
- bidirectional checking;
- unification and postponement;
- overloads and type classes, if added;
- pattern-match compilation;
- recursion elaboration;
- source maps and diagnostics;
- metaprogram and bounded synthesis execution.

The elaborator is untrusted for logical soundness. Its output is always
kernel-rechecked. This does not make elaborator bugs unimportant: they can
distort intent, hang, lose source locations, produce wrong suggestions, or
generate unusable code.

### 9.2. Holes

Every hole has a stable ID and record:

- expected type;
- local context and multiplicity/usage information, if any;
- source range;
- dependencies on other holes;
- whether it is computationally relevant;
- search attempts and accepted candidate;
- provenance of automatic changes;
- status: unresolved, admitted, solved-by-user, solved-by-generator, invalidated.

A hole is not a core term accepted by the release kernel. Before kernel checking
it must be closed or turned into an explicitly tagged assumption in a draft
environment.

### 9.3. Minimal synthesis

The first synthesis layer is intentionally limited:

1. exact match from local context;
2. constructor application;
3. bounded lambda introduction;
4. simple recursion templates for known primitives;
5. deterministic candidate ordering;
6. configurable depth, node, and time budgets;
7. kernel rechecking for every proposed candidate;
8. top-k suggestions instead of completeness promises.

Synthesis must not search forever or hide cost. Tooling shows the search budget,
candidate count, rejection reasons, and selected seed.

### 9.4. Interactive refinement

For complex tasks, the primary workflow is not "press generate" but:

```text
hole → inspect goal → apply/refine → new subgoals → optional search → kernel check
```

Users must be able to:

- accept a candidate completely or partially;
- view the explicit term;
- pin choices so later regeneration does not change them;
- undo automatic actions;
- compare candidates;
- save a replayable refinement script.

### 9.5. Self-applicable metaprogramming API

The first API provides capabilities, not raw mutable internals:

- quote surface and core terms;
- inspect declarations and goals;
- request type inference, conversion, and unification as services;
- create candidate declarations;
- register syntax/elaboration extensions at versioned extension points;
- emit structured diagnostics;
- attach user annotations to provenance records.

In reproducible mode, metaprograms do not have arbitrary access to network,
clock, environment, or filesystem. Additional effects are capability-based and
enter provenance.

### 9.6. Totality checker

The totality checker is a separate component. It either:

- builds a core term through a recursor or well-founded combinator;
- rejects or leaves an obligation;
- marks a definition `partial`, excluding it from type-level computation and
  proofs.

Accepting `partial` code must not allow construction of an inhabitant of every
proposition. Release profiles distinguish verified pure code from runtime-only
partial computations.

## 10. Verified generation: guarantee levels

The word `verified` is not used without qualification in design documents or
diagnostics. Ouro distinguishes these properties.

| Term | What is guaranteed | Checked by | Not guaranteed | Generator in TCB? | Status |
| --- | --- | --- | --- | ---: | --- |
| **Kernel-checked generation** | Generated core term has the claimed type in the selected environment | Kernel | Specification correctness, performance, backend side effects | No | **Must-have vertical slice** |
| **Generation of proofs** | Output is a proof term of some proposition | Kernel | That the proposition expresses the desired property; that the generator will find a proof | No | **Must-have for proof examples** |
| **Proof-producing generation** | Transformation emits artifact plus proof/certificate of a relation | Kernel checks certificate | Generator completeness, optimal artifact, external-spec correctness | No, if certificate is sufficient | **Prototype goal** |
| **Verified generator** | Generator is proven to return correct output or explicit error for all valid inputs | Separate formal proof and checker | Compiler/runtime correctness for generator execution; usefulness of result | Implementation may remain outside logical TCB, execution chain still matters | **Research goal** |
| **Deterministic regeneration** | Same pinned inputs and environment produce canonical-identical artifact | Build/replay infrastructure | Semantic correctness | No | **Must-have for committed generated artifacts** |
| **Provenance-attested generation** | Inputs, generator version, toolchain, assumptions, and transformation path are knowable | Host recorder and integrity checks | Truth of generator claims if recorder trusts self-report | Recorder affects provenance trust, not logical soundness | **Must-have in minimal form** |
| **Synthesis** | System performs bounded search for a type/goal candidate | Elaborator plus kernel for accepted candidate | Completeness, determinism in interactive mode, match with intent | No | **Primitive form is must-have** |
| **Interactive refinement** | User and system build a term step by step; accepted steps are rechecked | Elaborator plus kernel | Automation or low proof cost | No | **Usable prototype goal** |
| **Self-generation** | Target artifact is an Ouro component above the kernel | Normal checking plus regeneration policy | Self-hosting, autonomous improvement, generator correctness | No for logical acceptance | **Research goal by levels** |

### 10.1. Minimal first-version guarantee

The first version promises only this:

> A generator may be wrong, but a generated core declaration is not accepted until
> the fixed kernel confirms its type in an environment with explicit assumptions.

This is stronger than plain text generation but much weaker than a verified
generator, and it does not solve specification correctness.

### 10.2. Generated DSLs

A DSL extension is `kernel-checked` if its expansion passes the kernel. That does
not prove the expansion matches the intended DSL semantics. That claim requires
proof-producing translation or formal DSL semantics.

## 11. Trust model and full TCB

### 11.1. TCB depends on the claim

| Claim | Must be trusted before formal verification |
| --- | --- |
| "Core declaration has type `T`" | Kernel implementation, core decoder, declared axioms/primitives, host runtime/compiler running the checker, and the physical platform in the practical sense |
| "The theorem uses no assumptions" | All of the above plus correct dependency/axiom tracking |
| "The extracted executable implements the checked program" | All of the above plus erasure, IR transformations, backend compiler, linker, runtime, FFI, and target-platform semantic assumptions |
| "The build is reproducible" | Source/dependency identity, build instructions, normalized environment, toolchain versions, canonical serializer, replay infrastructure |
| "Artifact was generated by this generator" | Integrity of provenance recorder, hashes/signatures, policy against self-reported-only metadata |
| "Specification matches the real requirement" | Human/domain validation and correctness of the external-world model; the kernel does not establish this |

### 11.2. Permanent trusted base for a release

For logical claims:

- hand-written kernel;
- core representation decoder and environment loader;
- trusted primitives and allowed axioms;
- release-profile policy forbidding unresolved assumptions and unsafe bypasses.

For executable claims, additionally:

- runtime surface;
- effect handlers;
- FFI boundary;
- extractor and backend until verified;
- target compiler/linker/runtime.

A kernel may be formally verified later, but formal verification moves some trust
to the formal specification, proof assistant, and extraction chain. It does not
make trust disappear.

### 11.3. Bootstrap dependencies

Before and after self-hosting, the project must account for:

- OCaml compiler and runtime;
- package manager and build tools;
- seed binary or generated bootstrap sources;
- operating system, filesystem, and linker;
- target native compiler;
- CI runners and dependency mirrors;
- hardware assumptions.

Self-hosting does not remove the trusting-trust problem. Possible mitigations
include reproducible staged bootstrap, independent checker, diverse double
compilation, and publishing the bootstrap chain. This is a separate security
track, not a consequence of self-hosting.

### 11.4. Untrusted components

Relative to logical soundness, these are untrusted:

- parser and surface desugaring;
- elaborator and unifier;
- totality/coverage search, if output is elaborated to checked core;
- tactics, generators, and user metaprograms;
- external AI;
- external provers without a trusted oracle;
- formatters and IDEs;
- generated source before kernel acceptance.

### 11.5. What an untrusted-component bug can do

Kernel rechecking should prevent acceptance of ill-typed core terms, but a bug
can still cause:

- denial of service, memory exhaustion, or elaborator nontermination;
- a typed but unintended overload/implicit choice;
- poor error messages and source maps;
- missing useful candidates or search-space explosion;
- useless, slow, or unreadable generated code;
- wrong provenance if the recorder is not independent from the generator;
- data leaks through metaprogram capabilities;
- runtime failure if extraction/FFI is incorrectly excluded from the TCB;
- false theorems if an unsafe axiom or kernel defect exists;
- reproducibility failure due to time, locale, unordered collections, parallel
  scheduling, or unpinned dependencies.

### 11.6. Interim trust before formal verification

Before a formal kernel proof, trust is improved by a combination of:

- maximally simple reference implementation;
- property-based, metamorphic, differential, and regression tests;
- fuzzing for core decoder, conversion, universes, and inductives;
- independent slow checker for release artifacts;
- explicit TCB manifest;
- corpus of known-invalid terms;
- code review and mutation testing;
- reproducible kernel builds;
- versioned semantics document.

## 12. Progressive disclosure

### 12.1. What users can write without proofs

At the base layer users can write:

- algebraic data and ordinary total functions;
- pattern matching;
- inferred non-dependent types;
- explicit `IO`/computation values after a runtime layer exists;
- tests and examples;
- partial runtime functions when explicitly marked and not used in types/proofs.

Users should not need to write proof terms merely because the language
implementation is dependently typed.

### 12.2. Where obligations appear

Obligations appear when users:

- use indexed data and type-level equalities;
- require totality that the checker cannot infer automatically;
- leave a non-exhaustive match in a verified definition;
- call a partial function from a total context;
- state a semantic property;
- ask a generator for a proof-producing transformation;
- cross an FFI/effect boundary with a claimed invariant;
- use an unsafe assumption.

The IDE must explain **why** an obligation appeared and which minimal program
fragment caused it.

### 12.3. Draft mode

The `draft` profile allows unresolved holes and `admit`, but creates a separate
draft artifact:

- every unresolved item has a stable ID;
- a dependency graph shows which declarations depend on it;
- the artifact is not marked `verified` or `release`;
- package publishing and release CI reject it;
- the kernel can type-check the rest of the program in an environment with
  tagged assumptions;
- diagnostics always show assumption count and computational relevance.

### 12.4. Meaning of `admit`

`admit` does not mean "the kernel believed a proof." It means that an explicitly
tagged assumption was added to a draft environment.

An `admit` has:

- proposition/type;
- source location;
- reason/comment;
- author/tool identity;
- creation time outside canonical semantic hash;
- dependency closure;
- production policy status.

### 12.5. Running admitted code

By default:

- code with computationally relevant `admit` does not run;
- code where admits are proven erased and runtime-irrelevant may run only as a
  clearly marked draft;
- a separate `unsafe-draft-run` may exist for prototyping, but its output has no
  verified guarantees and is not used in release CI;
- any FFI or extraction path rechecks reachable assumptions.

### 12.6. Production build

A release profile requires:

- zero unresolved holes;
- zero non-whitelisted assumptions;
- no unsafe kernel bypass;
- pinned dependency and toolchain versions;
- clean-environment kernel recheck;
- provenance manifest for generated declarations;
- extraction/runtime test profile when releasing an executable.

### 12.7. IDE transition from ordinary to dependent code

Minimal UX includes:

- inline goal and local context;
- distinction between user-written, generated, and admitted code;
- totality and coverage badges;
- "why is proof needed" command;
- suggestions with factual statuses only: checked, rejected, timed out;
- jump from generated fragment to generator/specification;
- assumptions tree;
- explicit core preview;
- replay history for refinement steps.

### 12.8. Testing progressive disclosure

Comparison uses one frozen benchmark set with Lean and Idris, and Agda if
needed. Metrics include:

- fraction of tasks completed without explicit proof syntax;
- location of first mandatory proof obligation;
- context switches between programming and proving;
- time to first executable draft and checked release;
- unclear diagnostic count under a predefined coding scheme;
- manual proof/refinement actions;
- subjective difficulty only through a predefined user-study protocol.

Numeric pass/fail thresholds are set before the experiment from pilot data, not
after obtaining a desired result.

## 13. Effects and runtime

### 13.1. Effects are not one preselected feature

The project source mixed algebraic effects and linear types. Ouro treats them as
different design axes.

| Approach | Potential value | Main risks | Kernel impact |
| --- | --- | --- | --- |
| Explicit `IO` / indexed monads | Simple pure/effect boundary; library-first reasoning | Verbosity, difficult composition | May require no kernel change |
| Effect rows | Ergonomic polymorphic effect tracking | Inference and dependent-unification complexity | Prefer elaboration to pure core |
| Algebraic effects and handlers | Modular handlers, user-defined effects | Semantics with dependent types, continuations, runtime complexity | Must not automatically become kernel primitives |
| Linear/quantitative types | Resource usage, erasure, protocols | Binder, elaboration, and runtime representation impact | May require core-level extension |
| Combined mechanisms | More precise guarantees | Risk of an overly complex system and large TCB | Only after separate prototypes |

### 13.2. Initial working hypothesis

The first executable profile uses:

- pure logical core;
- explicit computation type or simple indexed monad;
- types depending only on pure total terms;
- partial/effectful computations that do not participate in conversion;
- minimal trusted runtime;
- no user-defined handlers in the kernel.

This keeps generation research from being blocked by the whole theory of
effects.

### 13.3. Choosing an effect design

The choice is evaluated by:

- compatibility with dependent types;
- clarity of pure/effect separation;
- interaction with totality and nontermination;
- predictable elaboration;
- erasure and extraction feasibility;
- runtime and FFI simplicity;
- local reasoning suitability;
- impact on logical and execution TCB;
- ergonomics on concrete benchmarks;
- ability to implement the mechanism as library/elaboration feature.

### 13.4. Simplification trigger

If the effect design blocks Core-1, destabilizes conversion, or requires broad
runtime/kernel change, Ouro fixes an explicit `IO`/indexed-monad profile and
moves advanced effects into a separate research branch.

## 14. Extraction

### 14.1. Extraction is not part of the kernel

The pipeline is separate:

```text
checked core
  → proof/type erasure
  → typed or untyped IR
  → normalization/lowering
  → backend representation
  → target compiler/linker
  → runtime and FFI
```

Every transition has its own correctness claim and TCB.

### 14.2. Implementation order

1. The first vertical slice runs through a reference evaluator/interpreter, not
   production extraction.
2. After Core-1 stabilizes, choose one backend.
3. Choose the backend for semantic simplicity, debugging, and bootstrap, not for
   popular target coverage.
4. Multi-backend support waits for demonstrated need.

OCaml, C, LLVM, and JavaScript remain candidates, not simultaneous promises.

### 14.3. Early extraction guarantees

Before verified extraction:

- the kernel guarantees type correctness of source core;
- tests can compare kernel evaluation and backend execution on terminating
  closed programs;
- differential testing finds bugs but does not prove semantic preservation;
- extractor, backend, runtime, and FFI are in the execution TCB;
- optimizations are enabled one at a time with a regression corpus.

### 14.4. Stronger possible levels

- proof-producing pass for selected transformations;
- verified erasure to a small IR;
- semantic preservation theorem for a backend subset;
- per-program translation certificate;
- independent IR interpreter;
- verified compilation through an existing verified backend when justified.

### 14.5. Interoperability

Even verified extraction does not automatically prove safe interoperability with
arbitrary effectful higher-order foreign code. The FFI contract must define
representations, ownership, exceptions, callbacks, nontermination, and trusted
wrappers.

## 15. Self-hosting and self-generation levels

### 15.1. Terms

| Term | Ouro working definition |
| --- | --- |
| **Bootstrapping** | Building a working toolchain from seed compiler/sources and host dependencies |
| **Self-hosting** | A meaningful part of compiler/toolchain is implemented in Ouro and built by the previous Ouro version |
| **Self-application** | A metaprogram written in Ouro is applied to Ouro programs or artifacts |
| **Self-generation** | A generator creates an artifact that is an Ouro component above the kernel |
| **Deterministic regeneration** | Pinned inputs/environment produce a canonical-identical artifact |
| **Evolution of components** | Human-approved change to a specification/generator/component with migration and review |
| **Autonomous improvement** | The system proposes and accepts improvement without independent review; Ouro does not promise this |

### 15.2. Maturity ladder

1. **Programs on Ouro.** User programs pass kernel checking.
2. **Standard library on Ouro.** A meaningful part of the library is written in
   the language.
3. **Elaborator components on Ouro.** Selected tactics, generators,
   pretty-printers, parsers, or search modules are self-applied.
4. **Self-hosted toolchain.** Frontend/compiler components are built by the
   previous Ouro version; the bootstrap chain is documented.
5. **Deterministically generated components.** For example AST visitors,
   serializers, codecs, or repetitive declarations are regenerated in CI.
6. **Specification-driven component generation.** A formal specification
   generates and proof-validates a selected system component.
7. **System-proposed changes.** Tool proposes a patch to its own component
   specification or implementation.
8. **Independent verification and human review.** Proposal is accepted only after
   kernel checking, regression/benchmark evaluation, provenance audit, and human
   approval.

Levels 1–2 belong to a usable prototype. Level 3 is the nearest
self-application goal. Level 4 is a difficult research milestone. Levels 5–6 are
research goals. Levels 7–8 are long-term experiments, not roadmap promises.

### 15.3. Kernel remains the fixed point

The canonical kernel does not self-generate and is not modified by metaprograms.
Possible related work includes:

- formal kernel specification in Ouro or another proof assistant;
- independently generated test suites;
- verified alternative checker;
- human-reviewed new kernel version.

The acceptance authority of a concrete release remains a separate fixed artifact.

### 15.4. Self-hosting does not shrink the TCB automatically

A self-hosted compiler depends on seed artifacts and runtime. Trusting-trust risk
requires its own bootstrap protocol. Self-hosting is valuable for dogfooding,
expressiveness, and self-application experiments, but it is not a soundness proof.

## 16. Tooling, provenance, and reproducibility

### 16.1. Minimal tooling

The first practically useful version needs:

- command-line checker;
- goal inspection;
- stable diagnostics format;
- editor protocol or minimal LSP subset;
- jump-to-definition and source locations;
- hole/refinement actions;
- generated-code/provenance view;
- deterministic replay command;
- test harness for benchmarks.

Incremental compilation and caching come after a correct dependency graph.
Parallel checking comes only after profiling and determinism tests.

### 16.2. Provenance record

For a generated declaration, record:

- canonical core artifact hash;
- generator name, package, version, and source hash;
- specification/input hashes;
- core, elaborator, and kernel format versions;
- dependency lock hash;
- search strategy, budget, and seed;
- enabled capabilities;
- assumptions and admitted dependencies;
- parent generated artifacts;
- kernel check result;
- user edits or override layer;
- environment identity required for replay.

Timestamp, username, and absolute build path do not enter semantic artifact
identity unless explicitly declared as inputs.

### 16.3. Recorder does not trust self-report

A generator may add explanatory annotations, but authoritative provenance is
collected by the host runtime from observed inputs, capabilities, and outputs.
Otherwise a malicious or buggy generator could attribute an artifact to another
source.

### 16.4. Determinism policy

A fixed seed is not enough. Reproducible mode requires:

- pinned dependencies and compiler versions;
- stable iteration order for collections;
- canonical serialization and name generation;
- normalized locale, timezone, paths, and timestamps;
- controlled concurrency;
- no network or ambient filesystem reads;
- explicit environment variables;
- deterministic pretty-printing, or comparison of canonical core instead of
  text;
- replay in a clean environment and hash comparison.

Interactive mode may be nondeterministic, but accepted committed results must be
materialized and checkable. If a candidate comes from a nondeterministic tool, the
committed artifact becomes a pinned input for the next reproducible build.

### 16.5. Source-of-truth policy

For generated components, source of truth is specification plus generator plus
manifest. Two modes are possible:

- generated source is committed for review and bootstrap, while CI checks
  regeneration;
- generated source is not committed, but canonical artifact and toolchain are
  fully pinned.

Manual edits to a generated file are either forbidden or stored as explicit
patch/override with provenance. Silent edits that disappear on regeneration are
not allowed.

### 16.6. Debugging generated code

Provenance must support:

- jump from generated node to specification and generator step;
- expansion view from surface to core;
- replayable search trace;
- before/after regeneration comparison;
- minimization of failing generated terms;
- blame separation: specification, generator, elaborator, kernel, extractor, or
  runtime;
- readable stable names independent of traversal order.

Usefulness is measured by bug-localization time on the benchmark set.

## 17. Hybrid AI

Hybrid AI remains an external optional proposal layer.

**Fixed:**

- AI is not part of the kernel;
- AI is not a source of truth;
- AI proposes syntax/core candidates, tests, specifications, or proof sketches;
- accepted core candidates pass normal elaboration and kernel checking;
- successful type checking does not guarantee specification correctness;
- AI cannot add kernel rules, enable unsafe mode, or extend its own capabilities;
- models receive minimal context; secrets and the entire repository are not sent
  without explicit need and policy;
- output has provenance: provider/model identifier, request hash, selected
  context, tool version, and human edits;
- AI nondeterminism is not part of release regeneration: accepted output is
  committed or turned into deterministic input;
- external calls are forbidden in hermetic build profiles.

AI is not part of early roadmap phases. Its value is evaluated only after stable
holes, benchmarks, and provenance exist.

## 18. Differences from existing systems

### 18.1. Comparison rule

Ouro does not claim uniqueness by word combination. A difference is established
only when:

1. a concrete capability or design invariant is stated;
2. it is marked as fundamental or a matter of degree/policy;
3. a prototype test exists;
4. it is checked whether the property can be implemented as a library, plugin,
   or fork of an existing system;
5. TCB, effort, and usability consequences are measured;
6. a condition is defined under which a custom kernel is no longer justified.

The comparison below is based on official documentation and primary project
sources, but it does not replace source audit or executable prototypes.

### 18.2. Observed system capabilities

#### Lean 4

Lean has extensible elaboration/metaprogramming, kernel-level proof checking, and
a bootstrapped frontend/compiler. Its reference manual separately describes how
`unsafe` definitions can bypass the kernel, so comparison must fix a safe policy
profile instead of treating the entire system as automatically equivalent to a
small trusted checker.[^lean-elab][^lean-unsafe][^lean-bootstrap]

Implication for Ouro: kernel-rechecked generated terms, self-hosting, and rich
metaprogramming are not unique by themselves. Possible difference must live in
mandatory provenance protocol, capability discipline, regeneration invariants, or
some other core-level requirement — and each still requires a prototype.

#### Idris 2

Idris 2 provides holes, type-directed development, QTT, elaborator scripts, code
generation, and self-hosting.[^idris-impl][^idris-elab][^idris-selfhost][^idris-qtt]
It is a close comparator for Ouro.

Version-specific soundness profiles must be fixed before benchmarking: official
documentation warns about totality-checker limits, and the current repository
README contains implementation caveats about cumulativity and `Type : Type`.[^idris-totality][^idris-readme]
Those caveats are not permanent claims about Idris design and must be checked for
the selected version.

#### Rocq/Coq and MetaRocq/MetaCoq

MetaRocq provides kernel-term metaprogramming, PCUIC formalization, verified type
checker work, and certified erasure with an explicitly described scope.[^metarocq][^metarocq-checker]
It is a strong counterexample to any claim that verified metaprogramming or
verified checking fundamentally requires a new language.

Implication for Ouro: a custom kernel must be justified not by the desire for
formal verification alone, but by a concrete difference in acceptance protocol,
calculus, TCB target, or experimental generation cost.

#### Agda

Agda has reflection, metavariables, termination/positivity checking, and safe
mode, which restricts unsafe options.[^agda-reflection][^agda-safe] It is a useful
comparator for holes, metaprogramming, and progressive disclosure even if its
implementation and self-hosting priorities differ from Ouro.

### 18.3. Capability-gap matrix

| Proposed Ouro difference | Difference type | Prototype test | Implementable on existing systems? | When own kernel is not justified |
| --- | --- | --- | --- | --- |
| All accepted generated core terms are rechecked by a fixed kernel | Mostly known invariant, not unique | Fault-injection generator suite | Yes, in many proof assistants with a safe policy | If this remains the only difference |
| Metaprograms get capabilities, not kernel internals | API/policy; possibly architecture-level | Same generator API in Ouro and Lean/Idris host | Likely; needs audit | If a plugin layer reaches the same boundary without TCB growth |
| Provenance is mandatory for generated declarations | Tooling/process invariant | End-to-end provenance and replay coverage | Likely yes | If host extension gives the same result at lower cost |
| Deterministic regeneration is a CI invariant | Build invariant, not type-theory novelty | Clean multi-environment rebuild | Yes | If fork/plugin gives identical result |
| Generator is self-applicable and written in object language | Already exists in different forms | One generator in Ouro and baseline | Yes in Lean/Idris/MetaRocq/Agda with differences | If Ouro shows no cost/clarity advantage |
| Proof-producing generation is first-class in workflow | Degree and UX question | Codec/compiler-pass case study | Partly yes | If baseline reaches same guarantees and ergonomics |
| Stable minimal acceptance protocol designed for generation | Potentially fundamental | Formal core interface plus independent checker | Possible, but may require kernel fork | Own kernel only if a core-level gap is demonstrated |
| Deep specification-driven self-generation of components | Research goal, not established capability | Generate one nontrivial above-kernel component | Possibly on existing language | If custom core has no measurable benefit |
| Early generation payoff as roadmap constraint | Project strategy | Time-to-first-useful-generation | Does not require new kernel | Cannot itself justify a new language |

### 18.4. Decision rule for a custom kernel

Continuing a full custom kernel is justified if a prototype shows at least one
of these:

- required acceptance invariant cannot be implemented without changing an
  existing kernel;
- existing host requires a substantially wider logical TCB for the same claim;
- stable quoted core or reflection boundary cannot be obtained without unsafe
  internals;
- required calculus/extraction boundary is fundamentally different;
- measured complexity or reproducibility of the existing-host solution is higher
  after maintenance is counted.

A custom implementation is **not justified** if provenance, regeneration,
self-applicable generators, and proof-producing workflows can be implemented on
top of an existing safe kernel at lower cost, with branding or control preference
as the only remaining difference.

### 18.5. Mandatory comparative prototype

Before final Core-1 commitment, at least one benchmark generator is implemented:

- on Ouro Core-0;
- on one mature baseline selected after capability review.

Compare effort, TCB, diagnostics, performance, and reproducibility. Without this
prototype, the claim that "generation as an axis requires a custom kernel" stays
a working hypothesis.

## 19. Research scenarios and benchmarks

A benchmark must be small enough for one research prototype but contain repeated
boilerplate, nontrivial invariants, and a meaningful change scenario.

### 19.1. Length-indexed binary protocol codec

**Task.** Small message schema with length fields, tagged variants, and bounded
payloads.

**Generated:** data declarations or representations, encoder, decoder skeleton,
bounds checks, round-trip proof obligations, tests, and provenance.

**Invariants:** decoded length matches payload; invalid tag rejected; `decode
(encode x) = x` in the declared subset.

**Metrics:** manual AST/LOC, proof actions, time to add a new variant, generated
fraction, replay success, backend differential tests.

**Baseline:** Lean or Idris implementation with analogous schema/generator
strategy.

### 19.2. Typed finite-state protocol

**Task.** Handshake or transactional state machine with 5–10 states and limited
transitions.

**Generated:** transition functions, impossible-case eliminations, command
dispatcher, trace validator, and proof obligations.

**Invariants:** forbidden transition is not representable or is rejected;
accepted trace respects state evolution.

**Metrics:** manual cases, holes closed, changes needed to add a state,
diagnostics for invalid transitions.

**Baseline:** hand-written dependent implementation and one existing dependently
typed language.

### 19.3. AST infrastructure for a small language

**Task.** Typed expression language or tiny compiler IR with binders.

**Generated:** visitors, renaming/substitution boilerplate, pretty
printer/serializer, equality/decidable instances, traversal lemmas or
obligations.

**Invariants:** scope preservation, round-trip serialization, selected
transformation preserves type.

**Metrics:** generator amortization across added constructors, maintenance cost,
provenance debugging, proof-producing pass viability.

**Baseline:** MetaRocq, Lean, or Agda tooling where appropriate.

### 19.4. Validated configuration/schema

**Task.** Small config schema with defaults, field dependencies, and versioned
migration.

**Generated:** parser, validator, normalized representation, serializer,
migration skeleton, and tests.

**Invariants:** accepted config satisfies schema; parse/print round-trips in
the normalized subset; migration preserves declared fields.

**Metrics:** time to schema change, manual validation code volume, error
localization quality, generated provenance correctness.

### 19.5. Resource protocol — later effects benchmark

**Task.** API for acquire/use/release resource or short session protocol.

**Goal:** compare indexed monad, effect rows, handlers, and linear/QTT variants.

This benchmark does not block early phases. It starts only after stable pure core
and helps choose effect design, not demonstrate first-generation capability.

### 19.6. Benchmark protocol

Every scenario predefines:

- specification and allowed libraries;
- baseline versions and hardware;
- manual and generated variants;
- post-initial-implementation change requests;
- LOC/AST/proof-action counting rules;
- time measurement procedure;
- generator-development cost treatment;
- failure and timeout policy;
- artifact publication format.

## 20. Must-haves, prototype goals, research goals, and product horizon

### 20.1. Necessary for the first vertical slice

- Core-0 syntax and canonical serializer;
- reference kernel checker;
- minimal evaluator;
- metavariables and named holes;
- simple elaborator;
- bounded deterministic synthesis;
- kernel rechecking of generated candidates;
- minimal provenance record;
- one demonstration scenario;
- CLI goal view and structured diagnostics;
- regression/fuzz corpus;
- reproducible build instructions.

### 20.2. Necessary for a usable research prototype

- Core-1 generic inductives and universe design;
- totality/coverage workflow;
- module/dependency system;
- LSP subset and interactive refinement;
- self-applicable generator API;
- benchmark harness and baseline implementations;
- deterministic regeneration in clean CI;
- readable generated-code debugging;
- one extraction backend or executable IR path;
- explicit TCB manifest;
- draft/release profiles;
- documentation of assumptions and unsafe boundaries.

### 20.3. Research goals

- verified generator for one nontrivial transformation;
- proof-producing compiler or schema pass;
- verified kernel implementation or independently verified checker;
- verified erasure/extraction subset;
- partial self-hosting of elaborator/toolchain;
- generic self-generation of selected system components;
- advanced synthesis with predictable resource use;
- formal provenance semantics;
- dependent effects or quantitative typing experiment.

### 20.4. Long-term product possibilities

- multiple optimized backends;
- broad package ecosystem;
- high-performance incremental and parallel compilation;
- stable FFI across platforms;
- production security hardening;
- large standard library;
- industrial integrations;
- external AI/prover marketplace;
- broad adoption.

These do not define the early architecture scope.

## 21. Roadmap

The roadmap is organized around research artifacts, not calendar promises. Every
phase has a stop/pivot condition.

### Phase 0. Research contract and comparative baseline

**Goal:** turn the vision into a testable experiment before large implementation.

**Artifact:** versioned research protocol; Core-0 draft; TCB taxonomy; selected
first benchmark; existing-system capability matrix.

**Completion criterion:** central question, counting rules, baseline plan, core
boundary, and first demo are clear enough for two independent reviewers to agree
on what counts as success or failure.

**Research question:** what minimum kernel is actually required for the first
generation payoff?

**Main risk:** scope creep disguised as architecture preparation.

**Stop/pivot:** if the first benchmark does not need a custom core-level
property, implement the comparative host prototype before expanding the kernel.

**Dependencies:** only the initial concept and external capability review.

### Phase 1. Core-0 and reference checker

**Goal:** produce an executable small trusted boundary.

**Artifact:** explicit core parser/serializer, checker, evaluator, primitive
declarations, valid/invalid term tests.

**Completion criterion:** checker deterministically accepts/rejects corpus;
unresolved metavariables are impossible; core format is versioned; clean rebuild
reproduces checker artifact.

**Research question:** can the acceptance path remain simple without premature
generic inductives and effects?

**Main risk:** conversion/universe complexity absorbs the project.

**Stop/pivot:** restrict universes and data schemas in Core-0, or use an
existing kernel for the generation experiment.

**Dependencies:** Phase 0 core draft.

### Phase 2. First generation vertical slice

**Goal:** demonstrate early measurable generation payoff.

**Artifact:** metavariables, holes, minimal elaborator, bounded synthesis, kernel
rechecking, provenance, CLI/goal UI, and one end-to-end demo.

**Completion criterion:** user writes an incomplete program/specification; system
proposes a candidate; kernel accepts or rejects it; artifact is replayable;
metrics include generator cost.

**Research question:** is even limited typed generation useful before full
language infrastructure?

**Main risk:** demo stays toy-sized and fails to test the central hypothesis.

**Stop/pivot:** choose a more regular scenario or acknowledge lack of early
payoff and move generation layer to a mature host.

**Dependencies:** Phase 1.

### Phase 3. Usable research core and tooling

**Goal:** move from demo to repeatable experiments.

**Artifact:** chosen Core-1 inductive/universe fragment, totality/coverage
pipeline, modules, draft/release profiles, minimal LSP, benchmark harness.

**Completion criterion:** at least three benchmark scenarios are implemented
without changing kernel rules between tasks; diagnostics and metrics are stable;
no-admit release is checked by a clean kernel run.

**Research question:** does generation payoff remain after real invariants and
maintenance changes?

**Main risk:** generic inductives, positivity, and cumulativity delay
experiments.

**Stop/pivot:** freeze a restricted core; encode unsupported features; build a
comparative prototype on MetaRocq/Lean/Agda.

**Dependencies:** Phase 2 data and core limitations.

### Phase 4. Self-applicable metaprogramming and provenance hardening

**Goal:** move selected generators/tooling to Ouro and test self-application.

**Artifact:** versioned quote/reflect API, capability runtime, generator written
in Ouro, host-recorded provenance, deterministic regeneration CI.

**Completion criterion:** an Ouro generator reproducibly creates a nontrivial
artifact above the kernel; faulty variants are rejected; source-to-generated
debugging works on benchmark.

**Research question:** does self-application provide practical leverage, not just
symbolic self-hosting value?

**Main risk:** stage separation, bootstrap cycles, and compile-time performance.

**Stop/pivot:** keep generators on host or restrict the Ouro meta subset; retain
the core checking model.

**Dependencies:** stable Core-1 and Phase 3 tooling.

### Phase 5. Execution track: extraction and minimal effects

**Goal:** run useful programs without mixing runtime claims with logical
soundness.

**Artifact:** one backend/IR path, minimal runtime, explicit computation type,
FFI contract, differential test suite, execution TCB manifest.

**Completion criterion:** selected closed programs agree between evaluator and
backend in the defined subset; runtime failures are localized; no claim of
verified extraction without proof.

**Research question:** what minimum runtime/effect design is compatible with
reasoning and generation workflows?

**Main risk:** effects and backend become a second independent language project.

**Stop/pivot:** interpreter-first release; explicit `IO` only; postpone handlers
and linearity; use an existing target runtime.

**Dependencies:** stable checked core and benchmark programs.

### Phase 6. Partial self-hosting

**Goal:** test Ouro on its own toolchain without rewriting the kernel.

**Artifact:** standard library, selected frontend/elaborator modules, and build
stages in Ouro; documented seed chain.

**Completion criterion:** staged build reaches a fixed point for selected
components; bootstrap is reproducible; old host component remains a fallback.

**Research question:** does self-hosting improve reliability/maintainability and
reveal design flaws?

**Main risk:** bootstrap debugging and trusting-trust overshadow research.

**Stop/pivot:** stop at self-hosted libraries/generators; do not wholesale-port
parser/compiler.

**Dependencies:** Phase 4 self-application and Phase 5 runtime.

### Phase 7. Formal specification and verified components

**Goal:** reduce implementation trust and clarify metatheory.

**Artifact:** formal core specification; proof or independent validation checker;
verified subset conversion/erasure or proof-producing pass.

**Completion criterion:** theorem statement, assumptions, and coverage are
explicit; extracted/verified artifact checks published corpus; divergence from
hand-written kernel is investigated.

**Research question:** how much of the TCB can be replaced by a trusted theory
base without unacceptable complexity?

**Main risk:** formalization diverges from evolving implementation.

**Stop/pivot:** verify stable subset or independent checker; do not block usable
prototype on full formalization.

**Dependencies:** stabilized core semantics, with specification work started in
earlier phases.

### Phase 8. Deep self-generation and Hybrid AI experiments

**Goal:** study specification-driven generation of components above the kernel.

**Artifact:** one self-generated component, independent checks, human review
protocol; optional AI proposal adapter.

**Completion criterion:** artifact is reproducible or materialized with honest
provenance; change improves predeclared metrics; rollback and audit are possible.

**Research question:** where is the practical limit of self-generation without
expanding the TCB or losing maintainability?

**Main risk:** anthropomorphic claims and non-reproducible demos.

**Stop/pivot:** restrict AI to interactive suggestions; keep deterministic
committed artifacts; reject evolution claims.

**Dependencies:** all earlier trust, benchmark, and provenance infrastructure.

### 21.1. 18-month checkpoint

This checkpoint is retained as a governance trigger, not a justified schedule
estimate.

By the checkpoint, the project should have:

- Core-0 checker and versioned core format;
- holes, minimal elaboration, and bounded synthesis;
- mandatory kernel recheck;
- one nontrivial benchmark task;
- minimal provenance/replay;
- published TCB manifest and invalid-term corpus;
- time-to-first-generation data.

If not, allowed pivots are:

1. freeze the custom kernel as a research artifact and move generation prototype
   to Lean/Idris/MetaRocq/Agda;
2. shrink Core-0 to fixed schemas/primitives;
3. end the product track and publish a negative result for the kernel-first
   strategy.

The core spec, tests, benchmarks, generator protocol, provenance schema, and
comparative research are preserved.

### 21.2. 24-month checkpoint

By the checkpoint, the project should have:

- reusable research prototype, not only a one-off demo;
- at least three benchmark scenarios;
- comparative implementation on an existing system;
- measurements of generation payoff and generator amortization;
- draft/release profile;
- minimal interactive tooling;
- reproducible clean builds;
- documented own-kernel justification review.

If the custom kernel does not show measurable capability or TCB advantage, the
default pivot is to continue the research layer on an existing kernel. This is
not a failure of verified generation as a central idea; it is a negative result
for a specific implementation strategy.

## 22. Success metrics and falsifiability

### 22.1. Generation payoff

The main metric counts total cost:

```text
C_generator_build + C_generator_maintenance + N × C_generated_use
    versus
N × C_manual_implementation
```

Positive payoff is claimed only after break-even across related tasks or
maintenance changes, not after one impressive demo.

Measured:

- user-authored core/surface AST nodes;
- manual edits accepted after generation;
- proof/refinement actions;
- elapsed active development time;
- time to change specification;
- generator build/maintenance time;
- review effort;
- debugging time;
- resulting artifact complexity/performance.

### 22.2. Boilerplate reduction

Boilerplate is classified before the benchmark. Count:

- repeated structural declarations;
- generated share of relevant AST;
- hand-written cases after schema change;
- duplication before/after generation;
- hidden complexity in generator source.

LOC is used only together with AST and time metrics.

### 22.3. Manual proof work

- user-issued tactics/refinements;
- obligation count and depth;
- manual proof term size;
- time spent understanding goals;
- percentage of proofs generated and kernel-accepted;
- proof maintenance after implementation changes.

### 22.4. Hole-driven development

- holes closed automatically;
- top-1 and top-k accepted candidate rate;
- median search time and timeout rate;
- irrelevant suggestion rate;
- user corrections;
- time from hole creation to checked closure;
- regressions after context change.

### 22.5. Progressive disclosure

- tasks completed with ordinary functional syntax only;
- location of first dependent obligation;
- transitions into proof mode;
- time to executable draft versus verified release;
- diagnostic comprehension in a fixed user study;
- comparison with pinned Lean/Idris baselines.

### 22.6. Reproducibility

- canonical core hash equality across clean builders;
- success rate replaying generated artifacts;
- ambient inputs detected;
- dependency/toolchain completeness;
- divergence under parallelism;
- stable name/source-map behavior.

### 22.7. Kernel size and understandability

- source size excluding tests/generated tables;
- trusted constructors/rules/primitives;
- cyclomatic and call-graph complexity;
- new-contributor review time;
- mutation survival rate in tests;
- kernel bug count/severity;
- core semantics change frequency;
- independent checker size.

Small LOC with complex implicit invariants is not success.

### 22.8. Provenance

- coverage for generated declarations/nodes;
- replayable inputs percentage;
- time to locate generator/spec origin of a bug;
- integrity failures caught;
- dependency/assumption closure correctness;
- ability to distinguish generated, user-edited, and external-AI content.

### 22.9. Synthesis usefulness

- accepted candidate rate;
- time budget compliance;
- generated-code performance;
- maintenance success after spec changes;
- cases where suggestion typechecks but violates user intent;
- user choice stability across versions.

### 22.10. Custom-kernel justification

- capability gaps reproduced or refuted by host prototype;
- logical TCB size/delta;
- implementation and maintenance effort;
- time-to-first-payoff;
- performance and diagnostics;
- need for unsafe host internals;
- portability of generators and benchmarks.

Acceptance criteria for every experiment are pre-registered before results.

## 23. Risks, pivots, and fallbacks

Probability and damage are qualitative and revisited at every checkpoint.

### 23.1. Architecture and implementation risks

| Risk | Probability | Damage | Early signal | Mitigation | Review trigger | Fallback |
| --- | --- | --- | --- | --- | --- | --- |
| Endless kernel work | High | Critical | No end-to-end generated demo after stable Core-0 subset | Freeze scope; primitive schemas; vertical slice first | Kernel work does not reduce the E1 blocker for two review cycles | Host generation layer on Lean/MetaRocq/Agda |
| Universe checking complexity | High | High | Frequent semantic rewrites, inconsistent constraints, performance blowups | Explicit levels; reference solver; kernel certificates; adversarial tests | Cumulativity blocks Phase 2/3 | Restricted universes; postpone polymorphism; existing kernel |
| Termination/positivity bugs | Medium-high | Critical | Suspicious recursion/inductives accepted; checker disagreements | Elaborate to recursors; invalid corpus; certificate design | Soundness uncertainty cannot be bounded | Fixed inductive schemas; external checker |
| Conversion performance | High | High | Small examples normalize pathologically; cache-sensitive results | Reference evaluator, profiling, resource limits | Performance requires unsafe native oracle in TCB | Restrict definitional equality; explicit lemmas |
| Elaborator complexity/performance | High | High | Unification postponement dominates; nondiagnostic failures | Bidirectional core, bounded search, tracing, benchmark corpus | Interactive loop unusable on target scenarios | Simpler surface syntax; explicit arguments; host elaborator |
| Nondeterministic synthesis | High | Medium-high | Candidate order changes across runs; flaky CI | Deterministic committed mode, stable ordering, seed, replay | Clean builds diverge | Materialize result; disable nondeterministic search in build |
| Debugging generated code | High | High | Users inspect expanded core manually; provenance gaps | Source maps, replay, stable names, minimization | Debugging time exceeds manual savings | Limit generation granularity; generate suggestions, not files |
| Excessive TCB | Medium-high | Critical | Kernel/runtime/extractor manifests grow every phase | Claim-specific TCB; no effects/reflection in kernel; independent checker | Own TCB not smaller/clearer than baseline | Existing trusted kernel; interpreter-only track |
| Extraction errors | High | Critical for executables | Evaluator/backend mismatch; FFI crashes | One backend, differential tests, simple IR, no overclaim | Bugs block benchmark execution | Reference interpreter; verified external backend subset |
| Trusting-trust/bootstrap compromise | Medium | Critical | Non-reproducible stages; opaque seed lineage | Reproducible bootstrap, independent checker, DDC research | Seed chain cannot be rebuilt | Distribute checked core plus multiple builders |
| Self-hosting difficulty | High | High | Bootstrap cycles, slow compiler, rewrite churn | Componentwise migration, host fallback | Self-hosting delays research experiments | Stop at self-hosted library/generators |
| Effects conflict with dependent reasoning | High | High | Effectful terms leak into types/conversion; unclear semantics | Pure/value restriction; explicit computation type; separate prototypes | Core soundness or elaboration becomes unclear | Indexed monad / explicit IO only |

### 23.2. Research and product risks

| Risk | Probability | Damage | Early signal | Mitigation | Review trigger | Fallback |
| --- | --- | --- | --- | --- | --- | --- |
| Weak differentiation | High | High | Capability matrix filled by existing systems | Comparative prototype early; claim invariants, not slogans | No core-level or measured workflow advantage | Research as tooling layer/plugin |
| No real benchmarks/users | Medium-high | High | Only identity/vector demos; metrics do not repeat | Pre-register 3–5 scenarios; recruit external reviewers | No third-party reproduction by checkpoint | Publish benchmark/tooling artifact, stop product track |
| Loss of motivation before payoff | High | High | Months spent below user-visible layer | Protect Phase 2 priority; keep a weekly runnable artifact | No visible generation loop | Reduce calculus; use host kernel immediately |
| Generator cost hides benefit | High | High | Demo excludes generator authoring/maintenance | Break-even accounting; repeated changes/tasks | Payoff only at unrealistic N | Narrow domain-specific generator or negative result |
| Provenance creates false trust | Medium | High | Metadata self-reported; gaps after manual edits | Host recorder, integrity hashes, coverage metrics | Artifact origin cannot be reconstructed | Treat provenance as advisory; commit artifacts explicitly |
| External AI leaks data or breaks reproducibility | Medium | High | Whole repo sent externally; build calls live model | Least privilege, local policy, no AI in hermetic build | AI required for release build | Disable AI; commit checked candidate as source |
| Incorrect specification | High | Critical by domain | Well-typed program fails domain tests | Domain review, executable specs, property tests, model validation | Claims exceed modeled properties | Narrow claim; add assumptions and validation layer |
| Performance optimization destabilizes semantics | Medium | High | Fast path disagrees with reference checker | Differential checks, release recheck by reference path | Repeated semantic divergence | Disable optimization; slower trusted path |

## 24. Open questions

| Question | Options | Selection criterion | Decide no later than |
| --- | --- | --- | --- |
| Exact sort system | Predicative `Type u`; separate `Prop`; proof irrelevance | Kernel simplicity, erasure, large-elimination needs | Core-1 design |
| Universe polymorphism/cumulativity | Restricted explicit levels; polymorphic constraints; cumulative hierarchy | Decidability, performance, benchmark need | Before generic libraries |
| Generic inductives | Direct kernel checker; certificates; restricted schemas | TCB size, implementation effort, expressiveness | Phase 3 |
| Recursion representation | Recursors; well-founded library; guarded/sized extension | Soundness, definitional equations, usability | Phase 3 |
| η and extensionality | No η in conversion; selected η; propositional lemmas | Conversion complexity versus ergonomics | Before core freeze |
| Equality | Intensional equality; proof irrelevance; heterogeneous equality library | Metatheory and generated proof burden | Core-1 |
| Quote/reflect boundary | Surface AST; elaborated core; typed quotations | Stability, hygiene, API safety | Phase 4 |
| Metaprogram effects | Pure/capability monad; controlled filesystem; interactive-only network | Reproducibility and usability | Phase 4 |
| Provenance granularity | Declaration-level; node-level; transformation events | Storage versus debugging benefit | Phase 2 pilot, finalize Phase 4 |
| Module system | Simple namespaces/imports; parameterized modules; functors | Kernel impact and incremental builds | Phase 3 |
| Draft assumptions | Tagged axioms; separate draft environment; proof-only erasure | Clarity and release enforcement | Phase 2 |
| Effect system | Explicit IO/indexed monad; rows; handlers; QTT/linear | Section 13 benchmark criteria | After Phase 3 |
| First backend | OCaml, C, LLVM, JS, custom IR interpreter | Semantic simplicity, debugging, bootstrap | Phase 5 |
| Verification host | Ouro; Rocq/MetaRocq; Agda; Lean; mixed | Trusted theory, extraction, contributor expertise | Explore from Phase 1, decide in Phase 7 |
| Independent checker | Separate OCaml implementation; verified extracted checker; baseline host | Diversity and maintenance | Phase 3–7 |
| Own-kernel exit criteria | TCB threshold, capability gap, time-to-payoff | Pre-registered comparison | 18/24-month checkpoints |
| Benchmark participants | Author-only; external contributors; controlled user study | Bias, cost, reproducibility | Before progressive-disclosure claim |
| Generated artifact storage | Commit source; commit core; build-only | Bootstrap, review, reproducibility | Phase 4 |
| FFI contract | Minimal C ABI; target-native; capability wrappers | Runtime TCB and portability | Phase 5 |
| Metaprogram security/resource model | Process sandbox; interpreter quotas; capabilities | DoS resistance and portability | Phase 4 |

## 25. Claims requiring further evidence

The following claims are not established by this document:

1. Ouro reduces proof burden relative to Lean/Idris on real tasks.
2. Mandatory provenance gives noticeably better debugging than existing info-tree
   or source-map mechanisms.
3. A custom kernel is necessary for a generation capability boundary.
4. Deterministic self-generation is practical for large system components.
5. Core-0 can expand smoothly to Core-1 with cumulativity and generic inductives.
6. Self-applicable generators retain performance and maintainability during
   bootstrap.
7. The selected effect system is compatible with dependent reasoning and
   extraction.
8. Verified extraction has a favorable cost/benefit profile for Ouro.
9. Progressive disclosure is objectively and subjectively better than baseline
   systems.
10. Deep self-generation provides advantages over ordinary metaprogramming/build
    generation.

Each claim needs one or more evidence types:

- literature and documentation review;
- exact-version source audit;
- executable prototype;
- benchmark;
- user study;
- formal specification;
- proof or independent checker;
- architecture experiment.

## 26. Final project formulation

Ouro studies whether a small fixed kernel can act as a stable trust point for a
language where self-applicable generation is a normal part of development rather
than a separate magic layer. The programmer states structure and properties;
untrusted tools propose implementations and proofs; the kernel checks accepted
core; provenance and reproducibility make the process observable and repeatable.

Ouro does not promise that the language will "write programs by itself." A more
precise formulation is:

> **Ouro helps write correct code and takes over checkable routine work without
> gaining the authority to change the checking rules.**

The custom kernel is a starting path, not dogma. Deep self-generation is a
research goal, not a first-version feature. Progressive disclosure is a
hypothesis, not a slogan. Product adoption is a possible horizon, but research
success is defined by experiment quality, artifact reproducibility, and an honest
answer to the central question.

**Ouro. A language that helps write itself.**

## 27. Historical language-ergonomics increment: pipe, list literals, `let!`

The self-host frontend source contains a small, connected surface-ergonomics
layer without changing kernel/checker semantics.

Implemented as source-level desugaring/lowering:

- `x |> f` and `x |> f a` — forward pipe. Ouro currently uses final-argument
  pipe convention: `x |> f a` desugars to `(f a) x`. This preserves the current
  application-spine model and does not introduce a general operator table.
- `[]`, `[x]`, `[x, y]` — list literals. In the AST this is `EList`; the lowerer
  desugars to existing `Nil`/`Cons` when an explicit expected type `List A` is
  available. Reliable current style: `([Z, S Z] : List Nat)`.
- `do let! x := action; tail` — do-ergonomics alias for the existing `EDoBind`;
  the lowerer still uses the current `io_bind`, with no new effect semantics.
- Existing string literals and anonymous/named holes are documented as bounded
  features. Holes remain fail-closed for production/release profiles.

Intentionally not implemented as parser-only stubs: records, deriving, implicit
arguments, sections/shared telescopes, local open/import aliases, where-clauses,
operator sections, match or-patterns, wildcard exhaustiveness, first-class type
aliases, and `pure` syntax. They require additional prerequisites: deterministic
name-resolution facts, expected-type plumbing, typed AST facts, field namespace
policy, stable diagnostics, and/or an effect return contract.

Main limitation: the committed stage0 C frontend has not yet been regenerated
from the updated self-host frontend source. The new syntax is therefore source
truth and typechecks through the changed self-host modules, but it is not
declared active in the packaged `ouro1` binary until a separate frontend
regeneration/parity pass. This is an intentional trust-boundary choice: generated
artifacts are not edited by hand.

## Appendix A. External cross-check and sources

The external cross-check is used to constrain comparative claims, not to declare
Ouro unique.

### A.1. What documentation supports

- Lean 4 has separate elaboration/kernel paths, extensible metaprogramming,
  safe/unsafe distinctions, and a bootstrapped frontend/compiler.
- Idris 2 has self-hosting, QTT, holes, elaborator reflection/code generation;
  version-specific totality/universe caveats require a pinned baseline.
- MetaRocq formalizes PCUIC and contains verified checker/erasure work with
  explicitly limited scope.
- Agda provides reflection, termination/positivity mechanisms, and safe mode.
- Reproducible generation requires more than a seed: environment, dependency
  identity, stable ordering, timestamps, and canonical artifacts matter.
- Dependent types plus effects are a separate design space, not a ready-made
  interchangeable feature.

### A.2. What the external cross-check does not establish

- Ouro superiority in usability, proof cost, or performance;
- impossibility of implementing Ouro invariants on existing systems;
- minimality of a future kernel;
- correctness of an implementation that does not exist yet;
- benchmark results;
- uniqueness of the deep self-generation concept;
- optimal effect/extraction design.

### A.3. Primary and official references

[^lean-elab]: Lean 4 Reference Manual, [Elaboration and Compilation](https://lean-lang.org/doc/reference/latest/Elaboration-and-Compilation/).
[^lean-unsafe]: Lean 4 Reference Manual, [Definition Modifiers](https://lean-lang.org/doc/reference/latest/Definitions/Modifiers/) and [Validating a Lean Proof](https://lean-lang.org/doc/reference/latest/ValidatingProofs/).
[^lean-bootstrap]: Lean 4 repository, [Bootstrap documentation](https://github.com/leanprover/lean4/blob/master/doc/dev/bootstrap.md).
[^idris-impl]: Idris 2 Documentation, [Implementation Overview](https://idris2.readthedocs.io/en/latest/implementation/overview.html).
[^idris-elab]: Idris 2 Documentation, [Pragmas: `%runElab`, `%macro` and reflection literals](https://idris2.readthedocs.io/en/latest/reference/pragmas.html).
[^idris-selfhost]: Idris 2 Documentation, [Frequently Asked Questions: self-hosting](https://idris2.readthedocs.io/en/latest/faq/faq.html).
[^idris-qtt]: Edwin Brady, [Idris 2: Quantitative Type Theory in Practice](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ECOOP.2021.9).
[^idris-totality]: Idris 2 Documentation, [Theorem Proving and Totality](https://idris2.readthedocs.io/en/latest/tutorial/theorems.html).
[^idris-readme]: Idris 2 repository, [README and current implementation caveats](https://github.com/idris-lang/Idris2).
[^metarocq]: [MetaRocq Project](https://metarocq.github.io/).
[^metarocq-checker]: Rocq project paper page, [Correct and Complete Type Checking and Certified Erasure for Coq, in Coq](https://rocq-prover.org/papers/correct-and-complete-type-checking-and-certified-erasure-for-coq-in-coq).
[^agda-reflection]: Agda Documentation, [Reflection](https://agda.readthedocs.io/en/latest/language/reflection.html).
[^agda-safe]: Agda Documentation, [Safe Agda](https://agda.readthedocs.io/en/latest/language/safe-agda.html).

Additional orientation:

- Reproducible Builds, [Definition](https://reproducible-builds.org/docs/definition/), [Variations in the build environment](https://reproducible-builds.org/docs/env-variations/), and [Randomness](https://reproducible-builds.org/docs/randomness/).
- Danel Ahman, Neil Ghani, Gordon Plotkin, [Dependent Types and Fibred Computational Effects](https://homepages.inf.ed.ac.uk/gdp/publications/dep_types_effects.pdf).
- Gabriel Ebner et al., [A Metaprogramming Framework for Formal Verification](https://doi.org/10.1145/3110278).

## Appendix B. Glossary

- **Kernel** — small hand-written checker for the versioned core language.
- **Core** — explicit language checked by the kernel; not surface syntax.
- **TCB** — components whose correctness is required for a specific trust claim.
- **Generation** — creating a program, proof, or artifact from a specification,
  context, or metaprogram.
- **Synthesis** — bounded and potentially incomplete candidate search by
  type/goal.
- **Kernel-checked generation** — generator output passes ordinary kernel check.
- **Proof-producing generation** — transformation emits artifact plus
  machine-checkable proof/certificate.
- **Verified generator** — generator correctness is proven against a formal
  specification.
- **Self-hosting** — the toolchain is implemented and built in Ouro.
- **Self-application** — an Ouro metaprogram is applied to an Ouro artifact.
- **Self-generation** — generated artifact is an Ouro component above the kernel.
- **Deterministic regeneration** — pinned inputs/environment produce a
  canonical-identical artifact.
- **Provenance** — machine-readable origin and transformation path of an
  artifact; not proof of semantic correctness.
- **Draft mode** — profile with explicitly tracked holes/assumptions, not allowed
  in release.
- **Release profile** — build policy with no unresolved assumptions or unsafe
  bypasses, plus clean kernel recheck.
