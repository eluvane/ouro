# RFC 0002: Versioned kernel core-artifact schema

- Status: superseded by the compiler-owned checking transition
- Authors: Ouro maintainers
- Created: 2026-08-20

This RFC records the retired JSON replay interface. The archived schema
preserves the original format. See
[checked snapshots and retained contracts](../kernel_core_artifact.md) for
the compiler-owned checking path.

## Summary

Kernel replay consumes one versioned JSON format,
`ouro.kernel-core-artifact.v1`. It is the explicit interchange boundary between
an untrusted core producer and the replay path.

Generated C, compiler caches, frontend ASTs, and module artifacts are not this
format and do not become trusted through reuse.

## Motivation

Without a published boundary, each producer could invent a related encoding or
a cache entry could be mistaken for checked core. A versioned schema gives
tests, compiler emitters, and replay one fail-closed contract.

## Decision

- The machine schema is
  `docs/spec/ouro.kernel-core-artifact.v1.schema.json`.
- [Core artifacts](../kernel_core_artifact.md) now distinguishes this archived
  format from the current checked snapshot.
- The top-level `kind` is exactly `ouro.kernel-core-artifact.v1`.
- Terms use tagged arrays for the current core constructors.
- Declarations are definitions, explicit axioms, or inductive declarations.
- A body-less constant must be marked as an admit.
- Host encoding and validation lived in the archived
  [Core codec](https://github.com/eluvane/ouro/blob/8ee4a175828f7eb803ca71f19bbd4c24de9b91b1/scripts/core_artifact.py).
- The versioned conformance corpus lives under `quality/smith/corpus/kernel/`;
  OuroSmith supplements it with typed generation and known rejection classes.
- The packaged checker can emit an artifact for validation and replay.

## Compatibility

A breaking encoding change requires a new `kind` and a new RFC. Version 1 is
not silently reinterpreted. Unknown tags and declaration kinds are rejected.

## Trust

The schema does not expand the logical trusted computing base. It transports
candidate core declarations; acceptance still requires structural validation
and kernel checking from a fresh environment.

## Validation and documentation

The schema, host validator, emitted-artifact path, valid/bad corpus, kernel
replay, [Kernel design](../kernel_design.md), and
[Trusted computing base](../tcb.md) move together.
