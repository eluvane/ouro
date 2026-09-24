# Core artifacts and checked snapshots

The compiler's current diagnostic format is `ouro.checked-program.v1`.
`compiler/checked_program_output.ouro` emits it only after the complete
declaration plan has passed compiler checking. The public
`--emit-checked-program` option and framing contract are described in
[Tooling](tooling.md#check-and-evaluate).

## Current checked snapshot

The snapshot contains declared types, bodies, inductive descriptors, intrinsic
and extern contracts, representation roles, and emission order. Its Ouro
serializer resolves global identifiers to names and preserves local de Bruijn
indices. Surface transformation tests compare the entire framed output rather
than a subset of declaration names or printer summaries.

This is a diagnostic comparison format, not an accepted input format or a
certificate authorizing unchecked compilation. The checker consumes typed
declarations, and native lowering rechecks a supplied `CheckedProgram` wrapper
and its metadata. Caches and build receipts do not bypass that boundary.

## Archived JSON format

`ouro.kernel-core-artifact.v1` was the JSON transport for independent OCaml
and Python kernel replay. Those replay owners and their command-line consumers
are retired. The schema at
`docs/spec/ouro.kernel-core-artifact.v1.schema.json`, RFC 0002, and historical
cases under `quality/smith/corpus/kernel/` remain recovery and migration data.
They are not the current compiler input or an active second checker.

The historical document used a `kind` field and an ordered `declarations`
array. Tagged arrays represented `Rel`, `Sort`, `StringLit`, `Pi`, `Lam`,
`App`, `LetIn`, `Const`, `Ind`, `Construct`, `Case`, and `Fix`; declarations
were `def`, `axiom`, or `ind`. A body-less ordinary definition was invalid.
The archived schema records its exact shape without reinterpreting old data.

## Retained contracts

The semantic contracts now execute as typed Ouro fixtures: scope and reference
errors, declaration ordering and duplicates, explicit assumptions, universes,
inductives and positivity, case metadata and motives, structural recursion,
substitution, conversion, string normalization, and resource outcomes.
`tests/compiler_retained_tests.ouro`, the compiler property suites, and
OuroSmith's canonical Core laws own this coverage.

JSON decoder shape policy and the former private OCaml facade, memo, and
replay APIs retired with their implementations. They are not counted as
ported language capabilities. Compiler inputs retain their own explicit
shape, type, and failure checks. [Compiler checking](kernel_design.md) and
[OuroSmith](ouro_smith.md) describe the active commands and evidence rules.
