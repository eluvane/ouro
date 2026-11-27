# Core artifacts and checked snapshots

Use `ouro.checked-program.v1` to compare complete, checked declaration
snapshots. The [serializer](../compiler/checked_program_output.ouro) runs
after declaration checking succeeds. Request this format with
[`--emit-checked-program`](tooling.md#check-and-evaluate).

## Current checked snapshot

The snapshot contains declared types, bodies, inductive descriptors, intrinsic
and extern contracts, representation roles, and emission order. Its Ouro
serializer resolves global identifiers to names and preserves local de Bruijn
indices. Surface transformation tests compare the entire framed output rather
than a subset of declaration names or printer summaries.

The format serves diagnostic comparison only. The checker consumes typed
declarations. Native lowering rechecks a supplied `CheckedProgram` and its
metadata even when caches and build receipts are present.

## Archived JSON format

`ouro.kernel-core-artifact.v1` was the JSON transport for the retired OCaml
and Python kernel replay tools. The schema, RFC, and corpus preserve the
format for recovery and migration.
[Archived schema](spec/ouro.kernel-core-artifact.v1.schema.json) ·
[RFC 0002](rfc/0002-kernel-core-artifact.md) ·
[Archived corpus](../quality/smith/corpus/kernel/)

An archived artifact has four required fields. `kind` identifies the format,
`name` names the case, `expect` records `accept` or `reject`, and `decls`
contains the ordered declarations. The declaration kinds are `def`, `axiom`,
and `ind`. The historical replay contract required a body for an ordinary
`def`. Terms use tagged arrays such as `Rel`, `Sort`, and `StringLit`. Use
the archived schema for the full field and tag definitions.

## Retained contracts

The semantic contracts now execute as typed Ouro fixtures: scope and reference
errors, declaration ordering and duplicates, explicit assumptions, universes,
inductives and positivity, case metadata and motives, structural recursion,
substitution, conversion, string normalization, and resource outcomes.
The retained laws, compiler property suites, and OuroSmith Core laws cover
these cases.
[Retained laws](../tests/compiler_retained_tests.ouro) ·
[OuroSmith](ouro_smith.md)

The historical JSON decoder and private OCaml facade, memo, and replay APIs
are retired. Compiler inputs have their own shape, type, and failure checks.
[Compiler checking](kernel_design.md)
