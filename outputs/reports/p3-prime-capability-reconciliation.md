# P3 — Prime Agent v0.7.2 Installed-Runtime Capability Reconciliation

- **Date:** 2026-08-16
- **Worker:** p3-prime-audit (P3 §36 Worker B)
- **Scope:** prove what the **installed** Prime Agent runtime exposes, from source, not docs
- **Baseline:** repo HEAD `3278818` on `brain/p3-lean-code` (no commits made by this task)

## 1. Installed runtime identity

| Item | Value | Evidence |
|---|---|---|
| Repo root | `C:/Tools/prime-agent/` | — |
| Package | `prime-agent` (private monorepo) | `package.json` |
| Version | **0.7.2** | `package.json` `version: "0.7.2"` |
| Git tag/HEAD | `v0.7.2` / `83a0f9f95 chore(release): prepare v0.7.2 (#1254)` | `git describe --tags` / `git log -1` |
| coding-agent package | `0.7.2` | `packages/coding-agent/package.json` |
| pi-ai (`@earendil-works/pi-ai`) | `0.7.2` (realpath `packages/ai`) | `node_modules/@earendil-works/pi-ai/package.json` |
| pi-agent-core (`@earendil-works/pi-agent-core`) | `0.7.2` (realpath `packages/agent`) | `node_modules/@earendil-works/pi-agent-core/package.json` |

**Working tree note:** `git status` shows local uncommitted modifications in the
installed tree (e.g. `agent-session.ts`, `sdk.ts`, `daemon-*.ts`, docs). The
inspection below reflects the installed source **as present on disk**, which is
the runtime that actually runs — the correct baseline for P3.

## 2. Verdict

**Every capability claimed by the official v0.7.2 docs is PRESENT in the installed
runtime**, with a real runtime dispatch implementation and (except
`after_provider_response`) a result that flows back into the agent/model path.
The earlier P0–P2 "UNAVAILABLE-not-inferred" statements were an audit-surface
artifact: audit `b8195a7` listed only the 11 events the Second Brain extension
subscribes to and missed the provider/turn hooks.

## 3. Capability matrix (§4.4)

| Capability | Official v0.7.2 docs | Installed runtime | Local prime.d.ts shim | Proven live | P3 action |
|---|---|---|---|---|---|
| before_provider_request | docs/extensions.md:601 (inspect/replace payload) | **PRESENT** — types.ts:612; dispatch runner.ts:889; wired sdk.ts:321 (`onPayload`); result replaces payload | **MISSING** (no event type, no `on` overload) | NOT YET | Add shim types; probe; use for provider-payload fingerprinting (P3 §5.4) |
| after_provider_response | docs/extensions.md:618 (status+headers, pre-stream) | **PRESENT** — types.ts:618; dispatch sdk.ts:328 (`onResponse` → `runner.emit`); read-only (no result type) | **MISSING** | NOT YET | Add shim types; probe; use for provider headers/status (P3 §5.5) |
| message_end assistant usage | docs/extensions.md:529 (replace `{message}`; usage example); session-format.md Usage block | **PRESENT** — MessageEndEvent types.ts:690, result types.ts:951 (role must be preserved); dispatch runner.ts:713 → agent-session.ts:3315 `_replaceMessageInPlace` (in-place, flows into agent state + persistence via `appendMessage` at agent-session.ts:126300) | **MISSING** (no MessageEndEvent/result/usage) | NOT YET | Add shim types; probe; use for per-message usage capture (P3 §5.1) |
| tool_result mutation | docs/extensions.md:737 (can modify; chained patches) | **PRESENT** — ToolResultEvent types.ts:818, result types.ts:945 (`content`/`details`/`isError`); dispatch runner.ts:755 → `agent.afterToolCall` agent-session.ts:1449 → returned `{content,details,isError}` is the tool result message → flows into model context | **PARTIAL** — event modeled, but handler returns `unknown`; result type not modeled | NOT YET | Add `ToolResultEventResult` to shim; probe marker proves live flow |
| context mutation | docs/extensions.md lifecycle + `#### context` (modify messages) | **PRESENT** — ContextEvent types.ts:606, result types.ts:925 (`messages?`); dispatch runner.ts:857 (`structuredClone` → chained replace); wired sdk.ts:340 `transformContext` → returned `AgentMessage[]` is the LLM context | **PARTIAL** — event modeled (`messages: unknown[]`), result `{messages}` not modeled | NOT YET | Add `ContextEventResult` to shim; use for context trimming (P3 Phase I) |
| resources_discover | docs/extensions.md:339 (skill/prompt/theme paths) | **PRESENT** — types.ts:496/503; dispatch runner.ts:989 → agent-session.ts:8343 `extendResourcesFromExtensions` (startup/reload; results feed resource loader + system prompt rebuild) | **MISSING** | NOT YET | Add shim types if P3 uses it (§9.1) |
| active-tool inspection/control | docs/extensions.md:1484 (`pi.getActiveTools/getAllTools/setActiveTools`) | **PRESENT** — API types.ts:1435–1439 (`getActiveTools`/`getAllTools`/`setActiveTools`/`refreshTools`); impl agent-session.ts:8487–8489 → `getActiveToolNames()`/`getAllTools()` (agent-session.ts:4090)/`setActiveToolsByName` (agent-session.ts:147937, rebuilds system prompt, applies next turn) | **MISSING** | NOT YET | Add to shim; P3 Phase J tool-surface measurement/restriction |
| usage input/output/cacheRead/cacheWrite/cost | docs session-format.md Usage; extensions.md:529 usage example | **PRESENT** — `Usage` @earendil-works/pi-ai `src/types.ts:201` (`input/output/cacheRead/cacheWrite/totalTokens/cost.{input,output,cacheRead,cacheWrite,total}`); `AssistantMessage.usage` pi-ai types.ts:224; exposed per assistant message via message_end; persisted in session file | **MISSING** | NOT YET | Probe logs usage numbers; P3 §5.1 uses AssistantMessage usage |
| child usage attribution | docs session-format.md `ChildUsageAttributionEntry` | **PRESENT** — session-manager.ts:170 (`child_usage_attributed` entry: targetId/childUsage/aggregateUsage/origin); folded on parse session-manager.ts:447 `applyChildUsageAttributions`; written via `attributeChildUsage` agent-session.ts:1069 (child usage added to parent billable, parent totalTokens preserved) | **MISSING** (no usage types at all) | NOT YET | Add usage types to shim; P3 §5.6 root/child attribution |
| provider headers | docs extensions.md:618 (response headers); types.ts `ProviderConfig.headers` (request) | **PRESENT** — request: `ProviderConfig.headers` types.ts:1266 (field at :1877) + `ProviderModelConfig.headers` (:2169); merged into requests sdk.ts:318 (`{...auth.headers, ...options?.headers}`); response: `after_provider_response` status+headers sdk.ts:328 | **MISSING** | NOT YET | Probe header keys only (values hashed); P3 §5.5 |
| system prompt access | docs extensions.md:958 `ctx.getSystemPrompt()` | **PRESENT** — `ExtensionContextActions.getSystemPrompt` types.ts:1458; bound to `this.systemPrompt` agent-session.ts:8521; during before_agent_start reflects chained patches (runner.ts:28208 override) | **PRESENT** — `ExtensionContext.getSystemPrompt(): string` (shim) | N/A (already used) | none |
| extension event ordering | docs extensions.md:268 lifecycle diagram | **PRESENT** — ordered chain: session_start → resources_discover → input → before_agent_start → agent_start → turn_start → context → before_provider_request → after_provider_response → message_start/update/end → tool_execution_start → tool_call → tool_execution_update → tool_result → tool_execution_end → turn_end → agent_end (dispatch: agent-session.ts:3315 `_emitExtensionEvent`, sdk.ts:321–340, runner.ts emit* methods) | not modeled (event union only) | N/A | document in shim header if needed |

## 4. Result flow-back (does a patch reach the model context?)

| Hook | Result | Flows back? | Mechanism |
|---|---|---|---|
| before_provider_request | any value ≠ undefined | **YES** | runner.ts:889 returns `currentPayload`; sdk.ts:321 `onPayload` returns it to the stream call (pi-ai) |
| after_provider_response | none (read-only) | no | sdk.ts:328 fire-and-forget `runner.emit` |
| context | `{ messages }` | **YES** | runner.ts:857 chained; sdk.ts:340 `transformContext` returns final array as LLM context |
| message_end | `{ message }` (same role) | **YES** | runner.ts:713 → agent-session.ts:3315 `_replaceMessageInPlace` mutates the finalized message object in agent state; persisted via `appendMessage` agent-session.ts:126300 |
| tool_result | `{ content?, details?, isError? }` | **YES** | runner.ts:755 chained patches; agent-session.ts:1449 `agent.afterToolCall` returns it → becomes the toolResult message content the model sees |
| resources_discover | `{ skillPaths?, promptPaths?, themePaths? }` | **YES** (into loader/system prompt) | agent-session.ts:8343 extends resource loader + rebuilds system prompt |

## 5. Local shim gaps — `brainstem/prime-extension/types/prime.d.ts`

Shim is hand-written, 5.4 KB, models only the 11 subscribed events (correct per
its own header). Gaps vs installed runtime:

1. **before_provider_request** — entirely absent (no event, no `on` overload, no result).
2. **after_provider_response** — entirely absent.
3. **message_end** — absent (no `MessageEndEvent`, no `MessageEndEventResult`, no role-preservation constraint, no `usage`).
4. **tool_result result type** — `ToolResultEvent` modeled but `on("tool_result", …)` handler returns `unknown`; `ToolResultEventResult` (`content/details/isError`) not modeled.
5. **context result** — `ContextEvent.messages: unknown[]` modeled; `ContextEventResult` `{ messages }` return not modeled.
6. **resources_discover** — absent.
7. **Tool control API** — `getActiveTools/getAllTools/setActiveTools` absent from `ExtensionAPI`.
8. **Usage types** — no `Usage` (`input/output/cacheRead/cacheWrite/totalTokens/cost`), no `AssistantMessage.usage`, no child-usage attribution types.
9. **Provider headers** — absent (request `ProviderConfig.headers`, response `after_provider_response.headers`).
10. **ExtensionContext** — missing `isIdle/getSignal/abort/hasPendingMessages/shutdown/compact` (present in runtime `ExtensionContextActions` types.ts:1449) — not needed by current extension, listed for completeness.
11. **Event ordering** — not documented (runtime/doco only).

Per plan §4.5: only the members P3 actually consumes should be added; do not
copy the full Prime type surface.

## 6. Stale P0–P2 claims to correct (historical context preserved)

Correct form per plan §4.5 (driver applies; this task is read-only on those reports):

- `outputs/reports/p0-p2-economics-skill-eval.md` — "Prime 0.7.2 exposes no before_provider_request hook" / "(no provider counters exposed)" → **correction:** campaign audit originally marked this unavailable; P3 reconciliation against the installed v0.7.2 runtime proved the hooks exist; the earlier local ambient type/audit surface was incomplete. Historical campaign measurements remain unavailable because they were not captured at the time.
- `outputs/reports/P0_P2_FINAL_IMPLEMENTATION_REPORT.md` — "Prime 0.7.2 exposes no before_provider_request hook; no provider counters reachable" and "Prime 0.7.2 has no before_provider_request/after_provider_response hook (audit b8195a7)" → same correction; audit `b8195a7` covered only the 11 extension-subscribed events.
- `outputs/reports/p1-orchestration-cache-gate.md` — "Prime 0.7.2 exposes NO before_provider_request/after_provider_response hook (audit b8195a7 hook list: …only)" → same correction.

Never fabricate old metrics retroactively; only the availability claim changes.

## 7. Live probe (smallest executable proof)

- Path: `brainstem/p3-probes/provider-probe/` (`index.ts` ~3.8 KB + `README.md`)
- Covers: `before_provider_request` fires (payload keys + sha256 + message count), `message_end` usage numbers, `tool_result` hash-only marker patch observed by subsequent model context, plus `context`/`after_provider_response`/`resources_discover` counters.
- Privacy: hashes/counts/keys only — no prompt text, no secrets, no tool output.
- **NOT installed** into `~/.prime/agent/extensions/` (daemon reload needed; live run is parent-coordinated).
- README contains exact install/reload/observe/remove steps (`Copy-Item` → daemon stop/start → `Get-Content probe.log.jsonl` → ask model to quote the `probe-marker` → `Remove-Item` both locations → daemon restart).

## 8. P3 implications (what this unblocks)

1. **§5.1 Prefer AssistantMessage usage** — viable: usage (incl. cacheRead/cacheWrite/cost) is on every assistant message and reachable via `message_end`.
2. **§5.4 Provider-request fingerprinting** — viable via `before_provider_request` (payload keys/hash; must stay hashed per probe rules).
3. **§5.5 Provider-response metadata** — viable via `after_provider_response` (status + headers).
4. **§5.6 Root/child attribution** — viable: `child_usage_attributed` entries + `applyChildUsageAttributions` already implement folding; extension-visible via session file.
5. **Phase I context pruning / Phase J tool restriction** — viable via `context` (`{messages}`) and `setActiveTools`/`getAllTools`.
6. **Phase E kernel delivery** — existing `before_agent_start` + new `resources_discover` (skill/prompt paths) both present.
7. The P0–P2 "provider cache UNAVAILABLE" rows become **measurable** going forward; historical rows stay UNAVAILABLE-not-inferred.

## 9. Evidence index (file:line)

| File (installed) | Symbol | Line |
|---|---|---|
| packages/coding-agent/src/core/extensions/types.ts | ResourcesDiscoverEvent / Result | 496 / 503 |
| packages/coding-agent/src/core/extensions/types.ts | ContextEvent / ContextEventResult | 606 / 925 |
| packages/coding-agent/src/core/extensions/types.ts | BeforeProviderRequestEvent | 612 |
| packages/coding-agent/src/core/extensions/types.ts | AfterProviderResponseEvent | 618 |
| packages/coding-agent/src/core/extensions/types.ts | MessageEndEvent / Result | 690 / 951 |
| packages/coding-agent/src/core/extensions/types.ts | ToolResultEvent(Base) / Result | 818 / 945 |
| packages/coding-agent/src/core/extensions/types.ts | ExtensionAPI | 1031 |
| packages/coding-agent/src/core/extensions/types.ts | ProviderConfig (headers) | 1266 |
| packages/coding-agent/src/core/extensions/types.ts | GetActiveTools/GetAllTools/SetActiveTools handlers | 1371 / 1378 / 1382 |
| packages/coding-agent/src/core/extensions/types.ts | ExtensionAPI tool actions | 1435–1439 |
| packages/coding-agent/src/core/extensions/types.ts | ExtensionContextActions.getSystemPrompt | 1458 |
| packages/coding-agent/src/core/extensions/runner.ts | hasHandlers | 183 |
| packages/coding-agent/src/core/extensions/runner.ts | emitMessageEnd | 713 |
| packages/coding-agent/src/core/extensions/runner.ts | emitToolResult | 755 |
| packages/coding-agent/src/core/extensions/runner.ts | emitContext | 857 |
| packages/coding-agent/src/core/extensions/runner.ts | emitBeforeProviderRequest | 889 |
| packages/coding-agent/src/core/extensions/runner.ts | emitResourcesDiscover | 989 |
| packages/coding-agent/src/core/sdk.ts | onPayload / onResponse / transformContext / headers merge | 321 / 328 / 340 / 318 |
| packages/coding-agent/src/core/agent-session.ts | attributeChildUsage | 1069 |
| packages/coding-agent/src/core/agent-session.ts | _installAgentToolHooks (tool_call/tool_result) | 1425 / 1449 |
| packages/coding-agent/src/core/agent-session.ts | message_end dispatch + in-place replace | 3315 |
| packages/coding-agent/src/core/agent-session.ts | getAllTools / getActiveToolNames | 4090 / 4083 |
| packages/coding-agent/src/core/agent-session.ts | extendResourcesFromExtensions | 8343 |
| packages/coding-agent/src/core/agent-session.ts | tool-action binding (get/getAll/setActiveTools) | 8487–8489 |
| packages/coding-agent/src/core/agent-session.ts | getSystemPrompt binding | 8521 |
| packages/coding-agent/src/core/agent-session.ts | appendMessage persistence | 126300 |
| packages/coding-agent/src/core/agent-session.ts | setActiveToolsByName | 147937 |
| packages/coding-agent/src/core/session-manager.ts | ChildUsageAttributionEntry | 170 |
| packages/coding-agent/src/core/session-manager.ts | applyChildUsageAttributions | 447 |
| packages/ai/src/types.ts | Usage / AssistantMessage | 201 / 224 |
| packages/agent/src/types.ts | AgentMessage alias | 310 |
| packages/coding-agent/docs/extensions.md | lifecycle / resources_discover / message_end / before_provider_request / after_provider_response / tool_result / ctx.getSystemPrompt / getActiveTools | 268 / 339 / 529 / 601 / 618 / 737 / 958 / 1484 |
| packages/coding-agent/docs/session-format.md | Usage / ChildUsageAttributionEntry | 102 / 267 |

*Proven live = NOT YET for every capability — live probe pending daemon reload (parent-coordinated).*
