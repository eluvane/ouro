# Quality precision pass: evidence record

The 2026-09-17 pass used provisional P1-generated tools from a supplied archive.
It was a partial work-in-progress snapshot. Exact commands, source hashes,
resource limits, and outcomes are in
[quality_precision_validation.json](quality_precision_validation.json);
rule decisions are in [clippy_rule_audit.json](clippy_rule_audit.json).

The pass retired line/name/size heuristics, repaired semantic indexing and
clone comparison, and narrowed result and repeated-work facts to registered
contracts. The current rule contract is in
[Clippy-grade rules](../docs/clippy_grade_firewall.md#active-rules); current
source-publication rules are in
[Tooling](../docs/tooling.md#autofixer) and
[safe rewrites](../docs/quality.md#precision-and-safe-rewrites).

Native fact, fix, analyzer-style, protocol, and selected public CLI checks
completed with P1. The complete bootstrap failed at P2/frontend; the public
fix executable build and production strict/lint runs did not finish. Fourteen
of 33 semantic source cases were resource-blocked across the recorded attempts.
The record does not establish clean production diagnostics, whole-tree
fix/format convergence, or release readiness. The validation JSON is the
source for each observed result; [CI](../docs/ci.md#local-profiles) owns current
gates.
