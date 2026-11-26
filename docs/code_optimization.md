# Code optimization and efficiency standard

Version 1.0

Use this standard when designing, reviewing, or optimizing code. Target a cost
that matters to a defined workload. Preserve behavior and verify the effect
with evidence appropriate to the claim.

`MUST` and `MUST NOT` express requirements. `SHOULD` expresses a preferred
practice that requires a reason to depart from. `MAY` permits a choice when the
stated conditions hold.

## Contents

- [Set the goal and preserve contracts](#set-the-goal-and-preserve-contracts)
- [Find and prioritize the cost](#find-and-prioritize-the-cost)
- [Choose an optimization](#choose-an-optimization)
- [Measure the effect](#measure-the-effect)
- [Examples](#examples)
- [Review and report the change](#review-and-report-the-change)
- [References](#references)

## Set the goal and preserve contracts

Give priority to correctness, security, compatibility, reliability,
performance, and maintainability, in that order. The change MUST preserve
observable behavior within the contract. Check public APIs and type semantics,
errors and cancellation, effect order, transaction boundaries, concurrency,
determinism, and resource limits. Resolve ambiguous contracts or record a safe
assumption before editing. Obtain approval before changing a public contract.

Redundant work is an operation whose result or effect the contract does not
require, or whose result is already available for safe reuse. Before removing
validation, authorization, audit, error handling, or synchronization, establish
its purpose and show that the remaining operations preserve the required
protection. Repeated checks can observe different mutable state or enforce
different permissions. Repeated calls can also produce distinct effects.

In automated work, follow the repository's instructions and the authorized
scope. Inspect the working tree, implementation, callers, and existing checks
before editing. Make the smallest coherent change in the component that owns
the cost. Justify new dependencies in terms of performance, security,
licensing, and maintenance. Stop when the code meets the requirement or the next change would
need an unauthorized contract change or an unacceptable risk.

## Find and prioritize the cost

A workload describes inputs, request or task frequency, concurrency, and
operation order. Characterize typical inputs, extremes, and known pathological
cases. Include distributions, resource limits, and any service-level objective
(SLO) that affects the decision. Record material unknowns.

Use these steps before a substantial optimization.

1. Trace the execution path, including loops, calls, errors, asynchronous
   boundaries, and external resources. Examine per-request, task, transaction,
   and process costs where relevant.
2. Identify the operation, why it runs, and the resource it uses. Count passes,
   searches, allocations, copies, I/O operations, and round trips where they
   explain the cost. Check what called functions do.
3. State the workload under which the cost matters, the metric or operation
   count expected to change, and what the proposed change could make worse.
   Compare plausible fixes and choose the smallest one that addresses the cause.
4. Define the correctness checks and the method for verifying the effect before
   editing. Record a baseline when the change requires measurement.

Treat a costly-looking pattern as a hypothesis. Static analysis can establish
avoidable work or a change in complexity when the operation model is explicit
and the change is local. Use profiling when the decision depends on the
executed path, the runtime, I/O, or contention. A bottleneck is the resource or
stage that limits the target metric under the workload. Use representative
measurements to establish one.

Address verified SLO violations, resource exhaustion, and failure risk first.
Then prioritize expensive operations, poor scaling, and confirmed repeat work
on hot paths. Consider frequency, cost per operation, growth with input size,
system-wide effects, and the cost and risk of the fix. Investigate plausible
issues when a focused check can resolve the uncertainty. Treat line count and
syntax changes as readability concerns unless evidence establishes a runtime
effect.

## Choose an optimization

### Algorithms and data structures

Estimate time and space costs across the expected input range. Include
initialization, updates, sorting, intermediate representations, and amortized
costs. A linear operation inside a loop can make total work quadratic. A
streaming path can lose its memory bound if it materializes the full input.

Choose a structure for the operations callers need. Hash tables suit key
lookups when hashing is suitable. Ordered trees also support range queries.
Queues and deques support access at the ends. Compact arrays suit sequential
scans.
A set can pay for itself when membership checks are frequent. Check build and
update costs, memory, equality, collisions, duplicates, ordering, and
thread safety. A scan can be cheaper for small inputs. Complexity describes
growth. Actual time also depends on constants, data distribution, and locality.

### Reuse work within its valid lifetime

Move computations out of a loop or reuse a result only when inputs, state,
timing, and effects allow it. Use the narrowest scope that removes the
repetition. Preserve the empty-input path and when errors occur. Check
configuration, time, randomness, locale, and any mutable or external state the
operation reads.

Reuse parsed data or encoded bytes only within a valid ownership and freshness
boundary. Check schema versions, encoding settings, validation, and error
behavior. If multiple layers normalize, filter, or copy data, determine which
layer owns the operation. Preserve boundaries that enforce security, auditing,
compatibility, isolation, or transaction guarantees. Measure across components
when a change may move costs between them.

### Memory and resource lifetime

Inspect allocation rate and size, retained and peak memory, object lifetimes,
copies, buffer growth, fragmentation, and garbage collection where applicable.
A slice or view can avoid a copy while retaining its backing storage. Check
aliasing, mutation, and whether the consumer holds the data after returning.
Use an allocation or heap profile to distinguish allocation churn from
retention. Measure changes to layout or access order on the target when the
expected benefit depends on memory locality.

Reuse expensive resources only when their lifecycle allows it. Before adding
an object pool, profile the workload to confirm that allocation or
initialization is a substantial cost. A pool needs a size limit, ownership
and reset rules, and defined behavior for exhaustion, cancellation, failure,
and close. Check whether a lower allocation rate is worth the retained memory,
contention, and lifecycle complexity. Manual memory management or unsafe
operations require demonstrated need, explicit invariants, review, and
focused tests.

### Databases, files, and networks

Measure operation counts together with elapsed time, transferred bytes, and
processing cost. For database queries, check the plan and actual row counts.
Look for N+1 queries, where loading a collection triggers one further query
per result. A join, eager loading, or a bulk operation can reduce round trips.
A projection can reduce transferred data. Check duplicate and missing rows,
indexes, pagination, locks, result size, and transaction consistency.

Use bounded batches when reducing round trips or write overhead matters.
Choose limits that fit the workload and service. Check latency to the first
result, memory, timeouts, and partial failure. Define retry and idempotency
behavior before resending a batch. Streaming can bound memory when producers
respect backpressure. Account for error propagation, retries, and transaction
semantics. Connection reuse requires limits, state cleanup, and recovery.

### Concurrency and parallelism

Use parallel work when tasks can run independently and their cost can justify
scheduling, synchronization, and data exchange. Unbounded parallelism
requires specific justification. Check available CPUs, whether
work waits on I/O, task size, contention, critical sections, and competing
work. Bound concurrency and queues according to available resources. Define
backpressure and cancellation, and test for races, deadlocks, and starvation.
Measure both throughput and tail latency if either can affect the workload.

Before removing or narrowing a lock, establish which state and operations it
protects. Evaluate a lock-free design against the same correctness and
measurement requirements.

### Caching and precomputation

A cache trades repeated work for lookup, storage, refresh, and invalidation.
Define the policies that apply before adding one.

- Include every input that determines the result in the key. Set the cache's
  scope, including authorization and tenant isolation.
- Define freshness and invalidation using a version, expiry, or change event.
  Account for stale and negative entries where the cache permits them.
- Set size, eviction, and lifetime limits. Define behavior when the cache is
  unavailable, contains invalid data, or is cold.
- Define concurrent miss and update behavior. Check races and bursts of
  duplicate work when many requests miss at once.

Compare hit rate and avoided cost with serialization, remote access,
invalidation, memory pressure, and contention. Memoize only when the key
captures stable dependencies and reuse preserves effects. Incremental
computation also requires reliable dependency tracking and invalidation.

### Compiler and runtime

Use an optimized build for release-performance claims. When a hypothesis
depends on inlining, vectorization, allocation removal, specialization, or
another compiler transformation, inspect optimization reports, intermediate
representation, generated code, or a profile. Check the relevant versions,
flags, target architecture, and runtime. Account for just-in-time compilation
and garbage collection when they affect the measurement.

Keep an abstraction if it serves a contract or a useful design boundary.
Before replacing it for performance, establish its runtime cost. Favor a
change to the algorithm or external calls when those costs dominate.

## Measure the effect

### Select metrics and a baseline

Choose a metric that answers the workload question. Record units and the
measurement boundary.

| Question | Measure |
| --- | --- |
| How long does a request take? | Latency distribution. Report the percentiles the workload needs, with enough observations to estimate them. |
| How much work can the system handle? | Completed operations per unit of time at a specified load, with errors and timeouts reported. |
| Which resource limits the workload? | CPU time or utilization, live and peak memory, resident set size, allocation rate, or I/O wait as applicable. |
| Where does external work occur? | Database query count, plan and rows, read and write operations, round trips, and transferred bytes including retries. |
| How long does startup or build take? | Time to readiness, or build time in separate clean and incremental runs. |

For a substantial change, record the before and after revisions, workload,
inputs, load and concurrency, configuration, build mode, runtime, hardware,
operating system or container limits, and relevant external dependencies.
Keep measurement boundaries and conditions comparable. Record repetitions,
aggregation, variability, and any excluded runs. Preserve the command and
raw results when available.

### Control measurement conditions

Separate cold start, cold and warm caches, first-request costs, and steady
state where they matter. Keep warm-up outside a measured steady-state interval.
Run enough repetitions to assess noise from scheduling, CPU frequency,
background work, storage, and external services. Report a median and
spread, and use confidence intervals or statistical tests when the data and
model support them. Report inconclusive results when the difference is within
the observed variation.

Choose a profiler for the hypothesis. CPU and allocation profiles answer
different questions from lock profiles or end-to-end traces. Check profiler
overhead and collect interfering profiles in separate runs. Use microbenchmarks
for isolated costs, load tests for queueing and saturation, and production
observations for deployed behavior. Account for uncontrolled variables before
generalizing an observation. Follow the environment's authorization rules.

### Interpret the comparison

Compare the target metric and relevant regressions in CPU, memory, I/O,
latency, throughput, startup, or errors. State any differences in semantics,
durability, transaction size, or configuration that affect the comparison.
Exclude failed and incorrect runs from successful results and record why.

Report measured improvements only when supported by comparable runs. If a
baseline or measurement is unavailable, give the reason. Report proven changes
in operation count or complexity with their assumptions. State any expected
runtime effect as unmeasured. Record neutral, worse, and inconclusive outcomes
where observed.

## Examples

These examples use language-neutral pseudocode. Their applicability depends
on the stated contracts.

### Reuse a loop invariant

If the settings stay fixed and `derive_threshold` has no effects and cannot
fail for those settings, compute the threshold once for a nonempty input.
The empty-input guard preserves the original zero calls for an empty sequence.

```text
if items is not empty:
    threshold = derive_threshold(settings)
    for item in items:
        if item.value > threshold:
            accept(item)
```

### Index repeated membership checks

A hash set can replace a scan of all blocked IDs for each user. For `m` IDs
and `n` users, this changes up to `O(n * m)` comparisons to expected
`O(m + n)` work under the hash table's usual constant-time operation
assumptions. Use the same equality rules. Collapsing duplicates is valid when
the contract calls for marking each matching user once.

```text
blocked = set(blocked_ids)
for user in users:
    if blocked.contains(user.id):
        mark_blocked(user)
```

### Batch related database reads

If the orders can be traversed twice and per-order reads dominate, fetch
customer records in bounded batches. Render the orders in their original
order. Preserve the original missing-customer behavior and use the required
consistent snapshot and authorization context.

```text
customer_ids = unique_customer_ids(orders)
customers_by_id = load_customers_in_batches(customer_ids, batch_limit)
for order in orders:
    render_order(order, customers_by_id.lookup(order.customer_id))
```

### Reuse a buffer

Reuse a buffer when the writer finishes consuming it before the next clear
and the encoder can start with an empty buffer each time. Allocate on the
first chunk so an empty stream still needs no buffer. Check the maximum
retained capacity and preserve error behavior.

```text
buffer = none
for chunk in chunks:
    if buffer is none:
        buffer = new_buffer()
    buffer.clear()
    encode(chunk, buffer)
    write_and_wait(buffer)
```

A serialized round trip can also be removed when the consumer can accept the
same object and the round trip provided no isolation, validation, or format
conversion required by the contract.

## Review and report the change

Before completion, review the diff and run checks that exercise the changed
behavior and its callers. Use the applicable unit, integration, regression,
property, differential, concurrency, or load tests. Add or update tests when
behavior or invariants change. Cover empty and large inputs, duplicates,
missing data, errors, cancellation, retries, timeouts, partial failures, and
overflow as applicable. Check numerical tolerances when operation reordering
can change floating-point rounding. Check time-of-check to time-of-use races
when reusing authorization decisions.

For each applicable item, record the evidence or explain why the item does
not apply.

- [ ] The workload, affected path, contract, and target cost are defined.
- [ ] The change addresses the cause and accounts for costs shifted elsewhere.
- [ ] Applicable behavior, security, and resource checks cover the final revision.
- [ ] The evidence supports the reported effect under the stated conditions.
- [ ] The diff preserves unrelated work and stays within the authorized scope.

Report the problem, location, cause, evidence, change, and expected effect.
Include observed test and measurement results, the baseline and conditions,
checks that did not run, tradeoffs, and remaining risks. Complete the task
when the required behavior and checks are satisfied and the cost has been
addressed or evidence shows that the workload already meets its requirements.

## References

Use the documentation for the tool version under test when applying
version-specific options. When updating a reference, verify its availability
and that it supports the claim.

- CPU, heap, block, and mutex profiling and execution traces.
  [Go diagnostics](https://go.dev/doc/diagnostics)
- Query plans, estimates, actual row counts, and instrumentation options.
  [Using PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
  and [PostgreSQL EXPLAIN reference](https://www.postgresql.org/docs/current/sql-explain.html)
- Compiler reports for applied and missed optimizations.
  [LLVM optimization remarks](https://llvm.org/docs/Remarks.html)
- Metric types, aggregation, and time series.
  [OpenTelemetry metrics data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/)
