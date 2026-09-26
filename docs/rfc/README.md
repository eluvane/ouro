# Ouro RFCs

RFCs record substantial design decisions that affect the language, kernel,
trusted boundary, compatibility, package formats, runtime contracts, or
repository architecture.

Use an RFC when a change needs alternatives, migration, and long-term rationale
beyond what a focused issue or pull request can carry.

## Process

1. Copy `0000-template.md` to the next available number.
2. Describe the problem, proposed behavior, compatibility impact, alternatives,
   tests, and documentation.
3. Open a pull request for discussion.
4. Mark the RFC `accepted`, `rejected`, `withdrawn`, or `superseded` when a
   decision is made.
5. Link implementation pull requests from the RFC without turning the RFC into
   a chronological task log.

Small bug fixes, internal refactors, documentation corrections, and behavior
already fixed by an accepted contract do not need an RFC.

## Index

| RFC | Status | Topic |
| --- | --- | --- |
| [0001](0001-strict-syntax-cleanup.md) | Accepted | Strict project syntax and quality policy |
| [0002](0002-kernel-core-artifact.md) | Superseded | Archived kernel core-artifact schema |
| [0003](0003-ouro-std-http-async-crypto.md) | Accepted | Word, crypto, HTTP-message, and sequential sleep library slice |
| [0004](0004-module-identity.md) | Proposed | Source module identity and import names |

The current implemented behavior remains defined by source, tests, and
canonical documentation. An RFC explains a decision; it is not automatically a
release guarantee.
