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

## Systems design decisions

The E1 models use D01–D06 as working assumptions. The systems foundation
remains a proposal. [Proposed systems foundation](../design.md#proposed-systems-foundation) ·
[Systems contract support](../architecture.md#systems-contract-support)

| ID | Proposal | E1 status | Decision needed for later work |
| --- | --- | --- | --- |
| D01 | Keep managed values and the collector. Add explicit resources in a separate systems fragment. | E1 assumption | Define how managed and explicitly owned values can cross the fragment boundary. |
| D02 | Start with a separate affine fragment. Reject affine or loan-carrying payloads in unrestricted legacy containers and actions, and such captures in ordinary closures. | E1 assumption | Review the fragment boundary and representation of restricted captures before E3. |
| D03 | Start with lexical loans, explicit initialization, and one-shot actions that consume captured resources. | E1 assumption | Approve the scope, initialization, and consumption rules before E3. |
| D04 | Keep systems operations out of pure conversion and track the dependencies of safety obligations. | E1 assumption | Specify the axioms and primitive assumptions permitted by a strict safety profile. |
| D05 | Check resource usage separately from runtime relevance. | E1 assumption | Define the checks that allow a proof or capability to be erased while preserving rights and behavior. |
| D06 | Retain current raw bit operations and give checked pointers a separate access contract. | E1 assumption | Approve the checked pointer API, any versioned exposed-address contract, and migration for existing raw round trips. |
| D07 | Give target and layout rules one owner, with `Native`, `C`, and `Explicit` representation classes. | Pending | Choose the first target and ABI combinations and identify unsupported aggregate cases before E2. |
| D08 | Use a small `SystemsCore` layer before MIR for checked resources, places, and invariants. | Pending | Approve its boundary and integration with the existing checker before E3. |
| D09 | Use the direct native backend for the first integrated systems slice. | Existing native path | Approve the integration scope and the boundary of any separate LLVM or Cranelift experiments. |
| D10 | Keep the C producer and bootstrap gates through a verified replacement. | Existing migration requirement | Review any replacement against the current migration and generated-artifact contracts. |
| D11 | Choose a library and link mode before E6. | Pending | Choose between a narrow shared-image format and an external linker in a separately approved integration mode. |
| D12 | Defer concurrency and advanced target features. Keep transfer, thread affinity, and effects explicit where they cross a boundary. | Deferred in E1 | Approve the memory model and the transfer and sharing rules before exposing atomics or thread APIs. |

D07–D10 need decisions before the affected compiler work begins. The current
build and release requirements apply throughout.
[Native toolchain contract](../design.md#native-toolchain-contract) ·
[Generated artifacts and stage loop](../build.md#generated-artifacts-and-stage-loop)
