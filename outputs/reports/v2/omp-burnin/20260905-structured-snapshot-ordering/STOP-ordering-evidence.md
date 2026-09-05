# Structured snapshot authority — STOP / HOLD

Runtime source unchanged: `c106865d9ae620e531b64fdaaf448a1b76e160fb`. Prior evidence HEAD: `d7cab4b79d5cebf21cb157cf9b05e90f4b88c68b`. No release tag, deployment, provider campaign, or text-authority repair was performed.

The audit correction is valid: OMP exposes ctx.getAsyncJobSnapshot(), and normal settled rows carry structured status and agentId. The earlier claim that text was the only status source was incomplete.

## Exact pinned ordering

OMP18.1.10 commit `f241301c83726afe75a847e919b89977a54dafbe`:

1. [job-manager.ts](https://github.com/can1357/oh-my-pi/blob/f241301c83726afe75a847e919b89977a54dafbe/packages/coding-agent/src/async/job-manager.ts):362–377 sets terminal status before enqueueing delivery, then schedules eviction. Default retention is five minutes.
2. [agent-session.ts](https://github.com/can1357/oh-my-pi/blob/f241301c83726afe75a847e919b89977a54dafbe/packages/coding-agent/src/session/agent-session.ts):2053–2076 builds snapshots from running jobs and only five recent settled jobs. The extension binding at6492 does not expose the optional recentLimit argument.
3. AgentSession:2167–2187 awaits yieldQueue.enqueueWithReceipt. Delivery can remain pending while the owner continues its current turn.
4. Job manager:785–800 explicitly documents that job-row eviction is independent of delivery and an owner can leave delivery in flight past retention. At876–905 eviction removes the row from #jobs without waiting for message commit.
5. Job manager:1066–1069 can pass a reconstructed enqueue-time snapshot to the delivery sink after eviction. That snapshot is not restored into #jobs and is not returned by ctx.getAsyncJobSnapshot(). Rendered message details omit its status/agentId.

Thus structured status is available at immediate sink entry, but is NOT guaranteed at the extension's delayed async-result message boundary. Missing rows can be permanently unavailable, not just temporarily retryable. The five-recent limit is a second visibility limitation; no claim that every normal two-worker delivery misses its snapshot is made.

## Executed proof

`bun snapshot-ordering-smoke.ts`, elapsed300135ms, exit0. Uses the pinned job manager implementation with only its logger import adapted to console; lifecycle logic is unchanged. No provider and no shortened retention. The sink is held pending like an uncommitted yield-queue receipt.

- At sink entry: completed, agentId=worker visible in recent snapshot.
- After default300000ms retention: job absent from recent snapshot.
- Delivery still pending for that same job ID.

`proof.json` preserves exact output/command. This exercises manager retention/queue state, not a full interactive OMP session. Source citations establish the session enqueue/extension snapshot connection.

## Decision

The requested stop condition fires for a delayed supported delivery. Do not implement a text fallback or pretend a missing settled row can always recover by re-reading this API. No Brain runtime implementation was changed and the requested worker regression matrix was not claimed complete.

Smallest prerequisite: pinned host must expose immutable structured status/agent identity for each delivered job, including queued/evicted deliveries, or retain/query those job rows through message commit. Then add failing Brain regressions before implementation. Pyright, latency optimization, new source freeze, deployment, natural20, Gate22/23 and economics remain blocked by the worker-authority prerequisite; existing failures are not waived. Release remains HOLD.
