# Semantic proof pass: evidence record

The 2026-09-18 pass used provisional P1-generated tools from
`ouro-dev-main-updated.zip`. It was a useful work-in-progress snapshot, not
release acceptance. Exact commands, source hashes, limits, and outcomes are in
[semantic_proof_validation.json](semantic_proof_validation.json); rule ownership
and applicability are in [semantic_proof_rule_audit.json](semantic_proof_rule_audit.json).

The pass introduced typed proof kinds, bounded snapshot-local contract
summaries, and syntax repair certificates. The current behavior and limits are
documented in [Clippy-grade rules](../docs/clippy_grade_firewall.md#semantic-boundary)
and [safe rewrites](../docs/quality.md#precision-and-safe-rewrites). The
compiler still owns program acceptance.

The recorded native proof, contract, resource, precision, fix, and lifetime
checks completed with the provisional compiler, as did the 48-case source
matrix. The complete bootstrap did not finish within its validation limit;
strict/release production Clippy and lint runs timed out or exhausted their
budgets. Four isolated whole-production fix/format attempts returned 1 and
changed zero files. No final release seal, production convergence, or
repository-gate result was established by this pass.

The parser lifetime probe measured about 44.1 MB of retained runtime heap after
a checked-read chain; that is not peak process memory. The retained JSON
record distinguishes this measurement and provisional checks from current CI
results. See [CI](../docs/ci.md#local-profiles) for the maintained gates.
