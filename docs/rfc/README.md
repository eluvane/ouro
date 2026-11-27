# Ouro RFCs

Use an RFC to record a substantial decision about the language, trust
boundary, compatibility, packages, runtime, or repository architecture.
Include the alternatives and migration consequences that reviewers need to
evaluate the decision.

## Process

1. Copy the [RFC template](0000-template.md) to the next available number.
2. Describe the problem, proposed behavior, compatibility impact, alternatives,
   tests, and documentation.
3. Open a pull request for discussion.
4. Mark the RFC `accepted`, `rejected`, `withdrawn`, or `superseded` when a
   decision is made.
5. Link implementation pull requests that establish the RFC's status.

Small bug fixes, internal refactors, documentation corrections, and behavior
already fixed by an accepted contract do not need an RFC.

## Index

| RFC | Status | Topic |
| --- | --- | --- |
| [0001](0001-strict-syntax-cleanup.md) | Accepted | Strict project syntax and quality policy |
| [0002](0002-kernel-core-artifact.md) | Superseded | Archived kernel core-artifact schema |
| [0003](0003-ouro-std-http-async-crypto.md) | Accepted | Word, crypto, HTTP-message, and sequential sleep library slice |
| [0004](0004-module-identity.md) | Proposed | Source module identity and import names |

For implemented behavior, consult the corresponding source, tests, and
[canonical reference](../README.md).
