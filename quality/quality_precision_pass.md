# Quality precision validation on 2026-09-17

This historical report covers a source snapshot built with a provisional P1
compiler. The [validation record](quality_precision_validation.json) identifies
the sources, commands, limits, and results. The [rule audit](clippy_rule_audit.json)
records the decisions behind the changes.

The snapshot replaced line, name, and size heuristics. It changed semantic
indexing and clone comparison and restricted result and repeated-work facts to
registered contracts.

P1 completed the native fact, fix, analyzer-style, protocol, and selected
public CLI checks. The full bootstrap failed at P2 frontend. The public fixer
build and production strict and lint runs were incomplete. Resource limits
blocked 14 of the 33 semantic source cases across the recorded attempts.

Release readiness, clean production diagnostics, and whole-tree fix and format
convergence remained unverified. See the [CI profiles](../docs/ci.md#local-profiles),
[active rule contracts](../docs/clippy_grade_firewall.md#active-rules), and
[rewrite policy](../docs/quality.md#precision-and-safe-rewrites).
