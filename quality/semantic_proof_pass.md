# Semantic proof validation on 2026-09-18

This historical report covers a snapshot built with a provisional P1 compiler.
The [validation record](semantic_proof_validation.json) identifies the sources,
commands, limits, and results. The [rule audit](semantic_proof_rule_audit.json)
records ownership and applicability.

The snapshot introduced typed proof kinds, bounded per-snapshot contract
summaries, and syntax repair certificates. The compiler determines program
acceptance. See the [semantic boundary](../docs/clippy_grade_firewall.md#semantic-boundary)
and [rewrite policy](../docs/quality.md#precision-and-safe-rewrites).

The native proof, contract, resource, precision, fix, and lifetime checks
completed with P1. All 48 cases in the source matrix also completed. The full
bootstrap exceeded its validation limit. Production Clippy and lint runs under
the strict and release profiles timed out or exhausted their budgets. Four
whole-tree fix and format runs each exited with code 1 and changed zero files.

The parser lifetime probe measured approximately 44.1 MB of retained runtime
heap after a checked-read chain. The measurement covers retained heap only.
The release seal, production convergence, and repository gates remained
unverified. See the [current CI profiles](../docs/ci.md#local-profiles).
