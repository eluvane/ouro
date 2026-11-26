# Parallel agent lanes for language work

Use a rolling queue with one owner per path. Work in local `main` by default.
The coordinator owns Git integration. Use issues, PRs, branches, and remote
coordination only with maintainer authorization.
[Repository automation policy](../AGENTS.md#collaboration-and-integration)

Keep at most ten unfinished engineering tasks, including reserved, running,
validating, under review, ready, and blocked tasks. Count each until integration
or explicit cancellation.

## 1. Start and replenish the queue

A lane has one outcome, one owner, and an exact write set. For local work,
keep one coordinator-owned task record in ignored build output. Check the
current local `main` revision and active reservations before admitting a
writer. Reserve the lane's files before work starts and include both paths
of any rename. Recheck reservations before expanding a write set and before
integration. Read-only review can continue while a writer waits.

When the maintainer authorizes GitHub coordination, record reservations in
the existing issue or PR discussion. An open PR's changed paths remain
reserved if its writer stops, hands off the task, or the PR becomes a draft.
Before admitting a writer, refresh `main`, all open PR heads, their complete
changed-file lists, and any unpublished reservations. Use paginated file
results and compare their count with each PR's reported `changed_files`.
Include both paths of every rename. Verify head and base revisions before
and after the snapshot, and repeat collection if the PR set, heads, base, or
`main` changes. If data is missing or the API fails, admit only writers whose
files are known to be outside the affected reservations. Recheck the snapshot
before expanding a write set and before integration.

For each useful ready task, require a runnable acceptance plan, execution host,
reviewer, and available files and interfaces. Give one writer each path. Separate
tasks can still conflict through checker rules, ABI layouts, primitive identities,
package formats, or diagnostic schemas. Settle the provider contract before
starting consumer work.

Admit the next independent task as soon as an integration frees its paths.
Continue independent work when another area is blocked. Leave capacity unused
when no useful task fits available review and host resources.

## 2. Lane catalog

Use the current task record, reservations, and roadmap to choose lanes.
Include current PR diffs when using the authorized GitHub workflow.
Prioritize compiler acceptance, data loss, and runtime safety before optional
speed or convenience work. Keep a small ready backlog with exact file lists.
Check shared contracts even when the file sets are disjoint.
[Roadmap](roadmap.md)

Use a detached worktree from the agreed `main` revision when local isolation
is needed. Create a task branch only on explicit maintainer request. Give API
indexes, registries, and generated outputs one writer at a time. Review and
submit required metadata with the behavior that needs it.

## 3. Task briefs

Record this compact card before dispatch. Use the local task record, or the
existing issue or PR when that workflow is requested:

```text
Outcome, owner, state, reviewer, and next checkpoint:
Repository, base SHA, worktree, and any requested branch or PR:
Exact write set and read-only dependencies:
Shared interface, RFC, and prerequisite decisions:
Reproduction or warm baseline; focused success command and expected result:
Adjacent and required validation; execution host and resource limits:
Shared metadata; blocker and explicit unblock or cancellation condition:
```

If a task lacks a runnable acceptance plan, start with a bounded read-only
investigation. If the regression check passes on the baseline, determine
whether the expected behavior already holds or the check misses the reported
defect. Keep a useful regression case if it fills a coverage gap. At each
checkpoint, record new evidence or narrow the blocker. A stalled writer's
files remain reserved until explicit handoff or cancellation.

## 4. Build and verify the affected code

Build only the affected dependency closure while iterating. For performance
comparisons, record the before and after source revisions. Compare successful
runs with equivalent commands, inputs, environments, limits, cache state,
and result coverage. Record elapsed time and peak memory separately. Rebuild
when source changes invalidate an executable receipt.
[Code optimization and efficiency standard](code_optimization.md#measure-the-effect)

Use multiple writers inside a lane only with disjoint exact files and one
integrator. Stop scope growth when the task needs an occupied path, an unapproved
public contract change, a new host semantic owner, weakened assertions, higher
resource caps, or unavailable mandatory execution. Preserve the reproduction
and blocker. Use the validation matrix to choose focused checks and the local
profiles to identify the gates they contain.
[CI validation matrix](ci.md#validation-matrix) ·
[Local CI profiles](ci.md#local-profiles)

## 5. Review, merge, and replenish

Review the exact revision and diff, including positive and negative expectations,
generated artifact provenance, and affected trust and ABI boundaries. Check that
command results identify the source revision, binary, host, and resource limits.
Require applicable adjacent checks and mandatory gates. Record skipped, absent,
pending, timed-out, and out-of-memory checks as incomplete validation. In a PR,
apply review feedback to the existing task branch. Review and validate the
affected paths after any change.

Before integration, reconcile the complete changed-file list with reservations,
prerequisites, final metadata, and validation results. If the maintainer
authorizes rebasing an owned branch, stop its writers first. Inspect both
sides of each conflict. Preserve decisions to retire paths and rerun affected
checks after resolving conflicts. The maintainer handles merge and cancellation
decisions sequentially. Automation may merge its own PR only with explicit
authorization.

After local integration, inspect the actual result on local `main` and run
focused checks for the affected paths. For an authorized GitHub merge, fetch
`main` and inspect the merged revision before running those checks. Compare
the merged result with the reviewed change because a squash or rebase can
change commit ancestry. Refresh reservations and release only paths with no
remaining owner. Start each successor from the integrated revision with a new
baseline and reservation. Verify the successor even when it reuses build
caches.

## 6. Failure modes

When files collide, stop the later writer and choose one owner through review,
merge, a narrowed diff, or explicit cancellation. When a shared interface
blocks a task, keep a concrete unblock condition and continue independent
read-only investigation. A common bootstrap or checker failure pauses dependent
lanes. Avoid duplicate rebuilds and keep the failure visible if a later run
uses a larger budget or fallback. After a merged regression, preserve the
input and revision, repair or revert through review, and resume dependent work
only after the repaired tree passes its checks.

Judge throughput by delivered user or compiler outcomes and integration time,
including blocked review and post-merge regressions. PR count and agent hours do
not establish progress.
