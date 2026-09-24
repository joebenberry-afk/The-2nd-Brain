# Second Brain v3 — Performance and Efficiency Charter

**Date:** 2026-09-09  
**Status:** Proposed design and acceptance contract. Not an implementation result, release approval, or authorization to change the live installation.  
**User direction:** A task taking about four seconds without Brain should remain in the same roughly three-to-four-second experience with Brain, without additional tokens when Brain has nothing useful to contribute. Make latency, efficiency, and speed the defining priorities of v3.

## Strong goal

Make Second Brain inexpensive when it is not needed and measurably beneficial when it is. On a genuinely no-benefit turn, preserve the native model-facing request, add no Brain-attributable tokens or model calls, and contribute only a tightly bounded amount of local delay. On memory-relevant tasks, reduce total work to verified completion, counting retrieval, injected context, tool traffic, workers, retries, and maintenance attributable to the task. Preserve correctness, required knowledge, isolation, provenance, durability, and authorization.

Do not optimize apparent speed by dropping requirements, missing relevant memory, weakening verification, or moving unaccounted costs into background work.

## 1. Evidence and its limits

The historical Phase 20 report records a one-turn arithmetic pair: 33,082 versus 33,221 total tokens, and 3.99 versus 10.53 seconds, for native OMP without extensions versus the same prompt with the Brain extension. The observed difference is 139 total tokens and about 6.5 seconds. These are total usage observations, not a measurement establishing that exactly 139 tokens were directly injected by Brain. [R1]

The same report records a project-switch task improving from five turns to three, with reported model cost falling 26.7%. This is a benefit to preserve, not a regression to erase. Its procedure-retrieval task improved from six turns to one when skill visibility was deliberately enforced; the shadow configuration did not show that benefit. Cost reductions must not be relabeled as token reductions without the underlying token breakdown. [R1]

The historical Phase 21 report records 78 AutoInject samples, with median 532 ms and p95 944 ms. Three-run startup measurements reported approximately 78 ms for bare Python and 242 ms for package/CLI startup in total. The report does not fully explain the 6.5-second end-to-end difference. Its hypotheses about extension loading and routing are investigation leads, not sufficient causal proof. In particular, verify whether routing and provider spans are nested views of one request or distinct requests before counting them twice. [R2]

These reports were read from repository snapshot `6baea51b0be3ac7108ca6deafe5665ab8cca0852`. They are not fresh measurements of the user's installed configuration. No benchmark was rerun while preparing this charter.

The earlier upgrade plan already calls for near-zero no-op overhead, deterministic local management, and reuse of existing primitives. V3 should make these goals enforceable rather than create another management subsystem. [R3]

## 2. Definitions that prevent misleading results

**No-benefit turn:** A turn for which optional Brain memory, skills, or optimization contributes no required information or useful intervention. Short wording alone does not establish this: “continue” may require substantial recovery.

**Zero added model tokens:** For a controlled no-benefit comparison, Brain adds no model-visible instructions, memory packet, tool description, status wrapper, or extra model request. Compare the actual model-facing request, including schemas and retained conversation state, with the equivalent native baseline. Ignore transport-only identifiers, not substantive prompt differences. A provider cache hit does not make added tokens nonexistent.

**Incremental local delay:** Extra time attributable to Brain on the task's critical path, measured across all relevant hooks and waits—not a separate allowance for each hook. Include blocking finalization in task completion; report first-output latency separately.

**Net efficiency:** End-to-end usage and time through verified completion. Count all task-associated model calls, worker calls, retries, background model work, and retrieval effort. Separate logical input, cached input, output/reasoning where exposed, model-reported cost, local resource consumption, and subscription usage. Unknown accounting stays unknown.

**True no-op versus incremental no-op:** A fresh request with no Brain contribution is different from a later turn that adds nothing new but retains useful Brain material from earlier turns. Report the retained material and cumulative cost; do not call that full-run zero overhead.

## 3. Proposed performance targets

These numerical budgets are engineering proposals, not measured achievements or promises about provider response time. Freeze the accepted budgets before testing; do not silently relax them after a failure.

| Area | Proposed target |
|---|---|
| No-benefit model-facing request | Same substantive request and tool surface as the native control; zero Brain-added model-visible tokens |
| No-benefit management calls | Zero additional model calls or agent-directed tool round trips |
| Warm no-benefit local overhead | At most 10 ms median and 50 ms p95 incremental blocking time across the entire turn |
| Cold-start overhead | Separately target at most 100 ms p95 additional time to first dispatch; include initialization and extension discovery rather than hiding them in a warm-up |
| No-benefit hosted task completion | Practical parity with the native baseline, supported by paired intervals and a predeclared regression margin consistent with the local budget |
| Memory-relevant work | Demonstrated net reduction in tokens and completion time on representative workload classes, with no accepted quality regression |
| Reliability | No new cross-project leakage, stale reuse, lost acknowledged progress, permission bypass, or unsupported completion claim |
| Local resources | Measure memory, CPU, disk activity, and idle/background cost on the user's existing 16 GB laptop; establish bounded budgets before promotion |

Literal zero CPU time is not the target. Zero added model tokens can be tested exactly in controlled no-op requests; hosted output length and latency require repeated measurements. A native four-second response should remain approximately four seconds. Reaching three seconds requires an actual saving elsewhere, not merely making Brain cheap.

Do not use gains on long tasks to average away a failing simple-task budget. Both classes must pass independently.

## 4. Implementation priorities

### A. A genuine no-op path

Make the earliest decision local and deterministic. Consult bounded, already-available project/task state and relevance metadata. Return without changing model input when no optional intervention is warranted. Do not call another model to decide whether to call Brain.

Mandatory permissions, ownership checks, protected constraints, and context needed for correct task recovery remain separate from optional optimization. A retrieval miss or timeout cannot justify disabling those protections. Preserve a bounded escalation path for ambiguous, genuinely context-dependent tasks, and measure false abstentions.

### B. Remove repeated setup before optimizing language choice

Profile extension discovery, imports, process startup, configuration loading, repository resolution, retrieval, locks, rendering, and finalization. Use an inert extension control to separate packaging cost from active Brain work.

Prefer existing-host checks, lazy initialization, reuse of validated configuration, and fewer unavoidable bridge invocations. Batch only operations whose ordering and permissions remain correct. Do not launch a Python process merely to establish that nothing changed when an existing local version check suffices.

Do not assume a Rust rewrite or always-on daemon is needed. Keep canonical state in the existing Brain authority. Any later process-lifetime redesign requires its own measured resource and lifecycle case, not a second memory system.

### C. Spend context only where it earns its place

When memory is useful, supply the smallest sufficient fact, procedure, or evidence pointer. Track object versions and recipient/context visibility so unchanged material is not repeatedly appended. Rehydrate after genuine context loss; a past delivery record alone is not proof the recipient still has the information.

Preserve useful stable prompt prefixes. Prompt caching reuses common prefixes, but is distinct from eliminating redundant prompt content. Evaluate compaction and schema changes for both quality and cache consequences. [R4]

### D. Avoid repeated discovery and tool work safely

Reuse exact, validated prior results where their input dependencies are unchanged. Key reuse to the relevant project, worktree, task, source versions, configuration, and environment. Include relevant dirty, staged, and untracked changes in invalidation; a commit ID alone is not a sufficient freshness proof.

For SZ work, the acceptance workload should include finding known mappings, assets, and dumps through existing project/tool metadata. Do not solve discovery by injecting the entire source catalogue into every request or creating a second asset database inside Brain.

Combine independent deterministic operations when this avoids an unnecessary model round trip. Never skip a needed current-source check merely because an old answer is available. [R3, R5]

### E. Move only deferrable work off the response path

Defer noncritical telemetry aggregation, index maintenance, and report generation when correctness permits. Bound queues and resource use; report dropped optional telemetry honestly. Do not run unaccounted paid-model maintenance after the visible answer.

Persist required progress, ownership, and safety records before the corresponding durability or completion acknowledgement. A performance improvement that silently weakens crash recovery fails this charter.

## 5. Measurement campaign

Start with inexpensive local replay and profiling, then use a bounded live-provider campaign for end-to-end effects.

**Controls:** Compare native OMP, an inert extension with matching packaging, the pinned current Brain configuration, and the v3 candidate. Preserve equivalent non-Brain settings and safety policies. Test the intended shipping configuration, not only a favorable feature override. Classify optional features as active, shadow, or disabled in each result.

**Workloads:** Include no-memory arithmetic and direct answers; naturally worded known-procedure tasks; project switches; continuation after compaction/restart; small repairs; and source-location tasks involving known mappings/assets/dumps. Include cases where a short prompt needs memory and cases where an apparently related memory is stale or belongs to another project. Maintain held-out paraphrases rather than using only exact trigger phrases.

**Timing:** Record non-overlapping critical-path intervals for startup, local hooks, actual provider request/response, tools, verification, and finalization. Correlate provider request IDs and parent spans to avoid double counting. Report warm/cold runs and cache states separately. Report raw counts and distributions; a replay does not prove live-provider performance.

**Repetitions:** Use hundreds or thousands of cheap local trials for local timing. Begin live measurement with a bounded pilot, then use randomized/interleaved paired repetitions sufficient for the chosen decision and uncertainty. Thirty paired observations can be a starting point, not an automatic claim that tails or small differences are established. Record every failure and timeout; predeclare any idle-session exclusions.

**Attribution:** Maintain a component-level ablation so removing a component reveals whether it saves work or merely adds cost. Never compare a cold native arm against a deliberately warmed candidate without disclosing the difference. Do not substitute a faster model or lower reasoning effort for an optimization claim about Brain.

## 6. Delivery order and promotion boundary

1. Pin the actual runtime/configuration and preserve unresolved v2 correctness/recovery findings. Establish no-op request capture and timing baselines.
2. Deliver request-neutral no-op behavior and remove unnecessary setup. Validate cold and warm latency independently.
3. Improve safe context/result reuse and retrieval precision while checking required-memory recall.
4. Demonstrate net gains on representative end-to-end tasks in the intended shipping configuration.
5. Promote only after performance and correctness gates pass. Keep a reversible configuration/build rollback.

This direction does not authorize bypassing existing v2 release holds or modifying the live installation. A small, separately reviewed overhead repair may be appropriate before v3, but it should not turn v2 closure into an unbounded redesign.

## 7. Definition of done

V3 is ready when Brain adds no model-facing content or management calls on the controlled no-benefit path, meets the accepted cold/warm local budgets, preserves hosted-response parity within the measured uncertainty, and demonstrates net benefits on useful-memory tasks without degrading quality or recovery. Every claimed improvement must be attributable to the candidate rather than a model change, hidden startup, cache-order advantage, omitted failed run, or unpaid accounting debt.

**Release principle: Brain should save more work than it creates, and should get out of the way when it cannot help.**

## Sources

**[R1] Project evidence:** `joebenberry-afk/The-2nd-Brain`, snapshot `6baea51b0be3ac7108ca6deafe5665ab8cca0852`, `outputs/reports/v2/omp-burnin/20-token-efficiency/TOKEN_EFFICIENCY.md`. Historical recorded comparisons; not rerun for this charter.

**[R2] Project evidence:** Same repository and snapshot, `outputs/reports/v2/omp-burnin/21-latency-qualification/LATENCY_QUALIFICATION.md`. Historical latency samples, startup measurements, and explicitly unresolved end-to-end gap.

**[R3] Prior proposal:** `Second_Brain_v1_v2_Deep_Implementation_Upgrade_Research_Plan.md`, dated 2026-08-29; efficiency contract, deterministic-first management, and reuse of existing primitives. A design plan is not implementation evidence.

**[R4] Provider documentation:** OpenAI, *Prompt caching*, retrieved 2026-09-09: `https://developers.openai.com/api/docs/guides/prompt-caching`. Supports the distinction between reusing a stable prefix and eliminating added context; does not establish cache benefits for the user's particular installed adapter.

**[R5] Provider documentation:** OpenAI, *Latency optimization*, retrieved 2026-09-09: `https://developers.openai.com/api/docs/guides/latency-optimization`. Supports reducing unnecessary requests and using deterministic processing where appropriate; not evidence of Second Brain performance.
