# Parallel agent lanes for language work

Use a rolling queue of focused tasks when parallel work helps. [AGENTS.md](../AGENTS.md)
sets repository policy; this page governs shared file ownership and integration.
Ten unfinished engineering tasks is a ceiling, not a target. Count reserved,
running, validating, review, ready, and blocked work until integration or
explicit cancellation.

## 1. Start and replenish the queue

A lane has one outcome, one owner, and an exact write set. Reserve its files in
the existing issue or PR discussion before a writer starts. An open PR's changed
paths remain reserved even if its agent stops or the PR becomes a draft. A
handoff on the same PR changes the writer, not the task or reservation. Read-only
review can continue while a writer waits.

Before admission, refresh `main`, all open PR heads and their complete file
lists, plus unpublished reservations. Use paginated file results; compare their
count with each PR's reported `changed_files` and verify head and base revisions
before and after the snapshot. Include both sides of renames. If the PR set,
heads, base, or `main` changes during collection, restart. On API failure or
incomplete data, admit no overlapping writer. Recheck immediately before
expanding a write set and before integration; a snapshot is not a server lock.

For each useful ready task, require a runnable acceptance plan, execution host,
reviewer, and available files and interfaces. Give one writer each path. Separate
tasks can still conflict through checker rules, ABI layouts, primitive identities,
package formats, or diagnostic schemas; settle the provider contract before
consumer work. Keep one coordinator-owned task board in the existing issue/PR
workflow, not a new repository scheduler.

After each integration, verify the affected behavior on refreshed `main`, release
only paths with no remaining owner, refresh reservations, and admit the next
independent task. Do not wait for every task in a batch to finish. A blocked
area does not block unrelated work; leave capacity unused when no useful task
fits available review and host resources.

## 2. Lane catalog

The live task board, current PR diffs, and [roadmap](roadmap.md) determine lanes.
Do not use a dated file-lock table as authority. Prefer acceptance, data-loss,
and runtime-safety work before optional speed or convenience work. Keep a small
ready backlog, with exact files rather than whole directories. A free filename
does not make a task independent when it consumes a changing shared contract.

Each task gets its own branch from refreshed `main` and one reason to exist.
Shared metadata such as `CHANGELOG.md`, API indexes, registries, and generated
outputs has one writer at a time. Required metadata stays in the same PR as the
behavior; serialize that final edit and review instead of making a later
umbrella PR.

## 3. Task briefs

Record this compact card in the issue or PR before dispatch:

```text
Outcome, owner, state, reviewer, and next checkpoint:
Repository, base SHA, branch, and PR:
Exact write set and read-only dependencies:
Shared interface, RFC, and prerequisite decisions:
Reproduction or warm baseline; focused success command and expected result:
Adjacent and required validation; execution host and resource limits:
Shared metadata; blocker and explicit unblock or cancellation condition:
```

A task without a runnable acceptance plan gets a bounded read-only
investigation first. If the reported bug already passes, retain a useful
missing regression or close the investigation; do not invent a failure.
At checkpoints, require new evidence or narrow the blocker. A stalled agent's
files remain held until an explicit handoff or cancellation.

## 4. How to burn fewer hours

Build only the affected cone while iterating. For performance work, compare a
successful warm T0 and T1 using the same source, command, inputs, caps, cache
mode, and result coverage; record elapsed time and peak memory separately. A
failed cold bootstrap and a warm successful tool run are not a speedup. A source
change invalidates an older executable receipt.

Use multiple writers inside a lane only with disjoint exact files and one
integrator. Stop scope growth when the task needs an occupied path, an unapproved
public contract change, a new host semantic owner, weakened assertions, higher
resource caps, or unavailable mandatory execution. Preserve the reproduction
and blocker. [CI](ci.md#local-profiles) owns focused and required validation;
parallelism does not waive a gate.

## 5. Review, merge, and replenish

Review the exact head and diff, its positive and negative expectations, generated
artifact provenance, relevant trust and ABI boundaries, and command results
bound to source, binary, host, and resource limits. A green focused command
cannot stand in for adjacent or required checks. Skipped, absent, pending,
timed-out, and out-of-memory checks are not passes. Review feedback returns to
the same branch; changed bytes need renewed affected review and validation.

Before integration, reconcile the complete changed-file list with reservations,
prerequisites, final metadata, and [CI](ci.md) results. Stop writers before
rebasing an owned branch. Review conflict resolutions and rerun affected checks;
a rebase itself supplies no evidence. Never resolve a conflict by blindly
choosing one side or restoring retired paths. The maintainer handles merge and
cancellation decisions sequentially; automation does not self-merge without
explicit authorization.

After integration, fetch `main`, inspect the actual merged result, run the
focused affected-path smoke, and refresh locks. A squash or rebase merge may
produce a different commit, so compare the result rather than requiring the old
head to be an ancestor. Start a successor from the refreshed tree with a new
baseline and reservation. Reused caches do not carry a predecessor's acceptance
verdict.

## 6. Failure modes

When files collide, stop the later writer and choose one owner through review,
merge, a narrowed diff, or explicit cancellation. A parked draft still holds its
paths. When a shared interface blocks a task, keep a concrete unblock condition
and continue independent read-only investigation. A common bootstrap or checker
failure pauses dependent lanes; do not launch identical rebuilds or hide the
failure with a larger budget or fallback. After a merged regression, preserve the
input and revision, repair or revert through review, and resume dependent work
only after the repaired tree passes its checks.

Judge throughput by delivered user or compiler outcomes and integration time,
including blocked review and post-merge regressions. PR count and agent hours do
not establish progress.
