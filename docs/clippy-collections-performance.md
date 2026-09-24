# Collection and string composition diagnostics

This diagnostic family contains 20 rules: `OURO-CLIPPY-PERF-008` through `023`,
and `OURO-CLIPPY-REDUNDANT-022` through `025`.

## Integration and proof boundary

The canonical policy inventory remains `quality/clippy_grade_rules.json`.
`semantic_collection_proof.ouro` supplies a closed `CmCollectionLaw` vocabulary;
`CmCollectionProof law` is a constructor of the existing `CmProofKind`.
`cc_rule` maps each of the 20 inhabitants to its canonical registry ID.
It is not a parallel policy registry or a refactor of contract roles.

`semantic_collections.ouro` consumes `ClippyCallFact` and the existing resolved
`CmApiIndex`. `cm_collection_laws_with_bindings` invokes it at the existing
sorted producer join. The production definition fold still builds each
semantic definition once. The existing repeated-work consumer and completed
traversal failure boundary are retained. No second AST traversal, source grep,
source-spelling test, per-call search through the event stream, or new dataflow
graph is introduced. Old fact-only entry points remain available.

The local API discriminators refine existing canonical contract keys because
map/filter share work role 20, string normalizers share role 42, and reversals
share role 43. A discriminator requires lookup by the compiler-owned callee ID,
matching canonical module/export contract, matching direct contract role and
cost, and exact arity. A same-spelled user function or a changing wrapper does
not acquire an API law from its name or inferred work role.

Every collection proof requires the existing owner, subject, and completed
traversal obligations, together with:

- resolved callees, known non-IO arguments, pure calls, and exact arity;
- the consumed value's exact producer identity, branch identity and effect epoch;
- canonical contract agreement and compatible intermediate element-type identity;
- registered traversal cost and a nonconstant lexical original source;
- an allocation/work-elimination condition, total callbacks, and the specific
  collection equivalence condition.

`cm_proof_valid` remains the publication gate. Missing, unknown, false,
duplicated or contradictory evidence invalidates the proof. Performance cost
is not inferred from an arbitrary call result, constant constructor, literal,
or unresolved value. A runtime input can still be empty or short; a finding is
an allocation/traversal law, not a promise of measurable speedup on every input.

### Callback totality and ownership

Purity alone does not permit skipping or reordering calls: a pure function can
be partial or nonterminating. The initial total-callback vocabulary accepts
only direct unary canonical `notb`, `str_len`, `str_trim`, `str_ltrim`,
`str_rtrim`, `str_lower`, and `str_upper`. Filters additionally require the
known Boolean predicate `notb`. This deliberately leaves many valid fusions
unreported. Local lambdas, unknown function arguments, partially applied
functions, and inferred wrappers are not promoted to total callbacks.
Aliases that retain the actual canonical declaration identity can qualify.

Intermediate-allocation rules require an unbound producer. Existing binder
facts, including producer aliases, conservatively exclude possible sharing.
Repeated filtering and side-trim after full trim are the two exceptions:
they remove only the outer traversal and can preserve the inner result and
its other consumers. A second occurrence is not treated as exclusive ownership.

All 20 rules are review-only: baseline/project `warn`, strict/release `deny`.
No replacement range, edit, or machine-applicable fix is added. Review must
preserve argument evaluation, ordering, ownership, public types and comments.

## Rule laws

Notation below omits explicit Ouro type arguments. `T(f)` means the audited
total callback obligation above; `fresh` means no binding of the intermediate
producer. Every row also requires the shared proof boundary above. Every row
has its own bad/good fixture and native detector/equivalence law.

| Rule ID | Proof inhabitant | Reported pattern and safe direction | Additional conditions / exclusions |
| --- | --- | --- | --- |
| OURO-CLIPPY-PERF-008 | CcLengthMap | `length (map f xs)` → `length xs` | `T(f)`, fresh mapped cells; no removal of unknown callbacks. |
| OURO-CLIPPY-PERF-009 | CcLengthFilter | `length (filter p xs)` → `count_if p xs` | `T(p)`, fresh selected cells; same predicate and element type. |
| OURO-CLIPPY-PERF-010 | CcMapMap | `map f (map g xs)` → one map with `f (g x)` | `T(f)`, `T(g)`, fresh inner map; producer output type equals consumer input type, not necessarily every map type. |
| OURO-CLIPPY-PERF-011 | CcLengthTake | `length (take n xs)` → a count-bounded length traversal | Proven literal `n > 0`, fresh prefix; do **not** replace it with full `length xs`, which may traverse much more. |
| OURO-CLIPPY-PERF-012 | CcMapFilter | `map f (filter p xs)` → one selection/mapping traversal | `T(f)`, `T(p)`, fresh filter; map only selected elements. |
| OURO-CLIPPY-PERF-013 | CcFilterMap | `filter p (map f xs)` → one map/test traversal | `T(f)`, `T(p)`, fresh map; bind each mapped value once, test it and reuse it, never duplicate mapper calls. |
| OURO-CLIPPY-PERF-014 | CcTakeMap | `take n (map f xs)` → `map f (take n xs)` | `T(f)`, fresh map, literal `n > 0`; avoid work on a discarded suffix when present. |
| OURO-CLIPPY-PERF-015 | CcDropMap | `drop n (map f xs)` → `map f (drop n xs)` | `T(f)`, fresh map, literal `n > 0`; discarded prefix need not be mapped or copied. |
| OURO-CLIPPY-PERF-016 | CcNarrowTake | `take a (take b xs)` → `take a xs` | Fresh producer and literal `0 < a < b`; equal/larger outer bounds belong to the existing dominated-take rule, not this one. |
| OURO-CLIPPY-PERF-017 | CcDropTakeWindow | `drop d (take n xs)` → `take (n-d) (drop d xs)` | Fresh producer and literal `0 < d < n`; unknown, zero and exhausting counts do not establish this rule. |
| OURO-CLIPPY-PERF-018 | CcReverseAppend | `reverse (append xs ys)` → `rev_append ys (reverse xs)` | Fresh append with a dynamic left input; the **right** input is rev-appended onto the reversed **left** input. |
| OURO-CLIPPY-PERF-019 | CcLeftAppend | `append (append xs ys) zs` → `append xs (append ys zs)` | Fresh inner append and dynamic original left input; only the copied left producer edge qualifies. Right association is already clean. |
| OURO-CLIPPY-PERF-020 | CcMapReverse | `map f (reverse xs)` → forward fold accumulating `Cons (f x)` | `T(f)`, fresh reversal; preserve reversed final order, callback reordering needs totality. |
| OURO-CLIPPY-PERF-021 | CcFilterReverse | `filter p (reverse xs)` → forward fold selecting and prepending | `T(p)`, fresh reversal; preserve reversed survivor order. |
| OURO-CLIPPY-PERF-022 | CcReverseMap | `reverse (map f xs)` → forward map-and-prepend fold | `T(f)`, fresh map; no second allocation of all mapped cells. |
| OURO-CLIPPY-PERF-023 | CcReverseFilter | `reverse (filter p xs)` → forward select-and-prepend fold | `T(p)`, fresh filter; preserve final order while avoiding the selected intermediate. |
| OURO-CLIPPY-REDUNDANT-022 | CcFilterFilter | `filter p (filter p xs)` → inner result | Same total predicate identity and element type; inner result may remain shared. Different predicates do not qualify. |
| OURO-CLIPPY-REDUNDANT-023 | CcTrimSide | `str_trim (str_ltrim s)` / `str_trim (str_rtrim s)` → `str_trim s` | Fresh canonical side trim; full trim already includes both boundaries. |
| OURO-CLIPPY-REDUNDANT-024 | CcSideTrim | `str_ltrim (str_trim s)` / `str_rtrim (str_trim s)` → inner trim | Canonical full trim; preserve any other consumers of the inner result. |
| OURO-CLIPPY-REDUNDANT-025 | CcCaseAbsorption | `str_lower (str_upper s)` → `str_lower s`, and the opposite direction | Fresh inner normalization; specifically the registered ASCII case semantics, not locale-sensitive or Unicode case folding. |

The list laws follow the definitions of `map`, `append`, `length`, `filter`,
`take`, `drop`, `reverse`, `rev_append`, `reverse_lin`, `foldl`, `foldr` and
`count_if` in `std/prelude.ouro`, `std/data.ouro`, and `std/listx.ouro`.
The string laws use `std/string.ouro` and ASCII character/whitespace operations
in `std/char.ouro`. No short-circuit behavior is assumed for `any` or `all`:
their recursive Boolean argument is evaluated eagerly in this implementation.
Round-trip conversion laws and arbitrary fold/callback transformations remain
out of scope until their domain, evaluation and totality obligations are known.

## Fixtures and native tests

`tests/clippy_semantic/cases.json` retains its earlier 48 cases and adds 52:
40 files named `collections-{perf,redundant}-NNN-{bad,good}.ouro`, plus 12
focused identity/negative-space fixtures. Each bad file expects its exact new
ID; each good file expects no diagnostics. Two extra positives check callback
alias preservation and heterogeneous map composition.

The other extra fixtures cover same-spelled user functions, shadowed map and
callback names, bound producer aliases, changing collection and normalization
wrappers, effects, branches, constant list/string inputs, and unknown counts.
The existing Python runner only launches the native semantic worker and
validates its registered proof protocol and exact diagnostic inventory; it
does not recognize patterns or reimplement the detector.

`tests/clippy_semantic/collection_laws.ouro`, imported by `proofs.ouro`, adds:

- A positive production-join case for every rule, plus independent producer
  and consumer mutations of purity, role, cost, argument availability, IO,
  arity, branch, effect epoch, callee and type identity; bound producer policy,
  missing producers and missing API indexes are checked as well.
- Explicit same-spelling/work-role rejection, unknown totality, changed
  predicate identity, incorrect lineage, clean right association, heterogeneous
  types, unknown/zero/equal/exhausting counts, and both string law directions.
- Executable std value laws over all Boolean lists of length at most four and
  all four total Boolean callbacks, including empty/short lists, asymmetric
  append operands, and bounds beyond length. String cases include whitespace,
  non-ASCII text, NUL and byte-oriented inputs. These finite checks are
  regression tests for the audited std laws, not a claim of formal universal
  verification by enumeration.

`pr_rule_kinds` also includes all 20 `CmCollectionProof` inhabitants. Existing
proof-law tests remove, falsify, make unknown and duplicate **every required
premise** for each of these kinds. Earlier proof tests are retained.

## Validation commands

[CI](ci.md#local-profiles) owns the Clippy laws, precision fixture, and full
suite commands. Authored fixtures alone do not establish a successful run.
