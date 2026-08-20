# 04 — Static 0.7.4 Contract Audit

## Method

All evidence below is read directly from the **isolated, detached v0.7.4
worktree**: `C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`
(`git rev-parse HEAD` → `af0b8e00b9f704e834787fd321065ca78281f2aa`,
`chore(release): prepare v0.7.4 (#1569)`; `git status --short` shows
exactly the two known local Windows patches applied —
`packages/coding-agent/src/core/kernel/bootstrap.ts` and
`packages/coding-agent/src/core/session-lease.ts` — matching
`02-local-patch-disposition.md` exactly). Nothing in this worktree, or in
the live `C:\Tools\prime-agent` checkout used for cross-reference, was
built, installed, or run. `node_modules` is not present in the worktree
(confirmed: `ls node_modules` → "No such file or directory") — no
`npm install` was performed, consistent with the read-only constraint.

Where the trace required following code into `@earendil-works/pi-agent-core`
(the `Agent`/`agentLoop` runtime that `sdk.ts` wires the extension runner
into), that package's **source is a local monorepo workspace**
(`packages/agent/src/`, not a published-only external dependency), so the
trace was completed against real source, not assumed.

## 1. Context: does a `context` handler's `{ messages }` return value still
   reach the outgoing provider request?

**Verdict: COMPATIBLE (fully traced).**

Trace, all citations from the v0.7.4 worktree:

1. **Type contract** — `packages/coding-agent/src/core/extensions/types.ts:576-579`:
   ```ts
   export interface ContextEvent {
     type: "context";
     messages: AgentMessage[];
   }
   ```
   and `types.ts:869-871`:
   ```ts
   export interface ContextEventResult {
     messages?: AgentMessage[];
   }
   ```
   registered at `types.ts:976`:
   `on(event: "context", handler: ExtensionHandler<ContextEvent, ContextEventResult>): void;`
   — identical to v0.7.3 (`git diff v0.7.3 v0.7.4 -- .../types.ts` shows
   only comment-banner removals around this block, confirmed in
   `03-upstream-delta-audit.md`).

2. **Runner dispatch** —
   `packages/coding-agent/src/core/extensions/runner.ts:852-882`,
   `emitContext(messages)`:
   ```ts
   async emitContext(messages: AgentMessage[]): Promise<AgentMessage[]> {
     ...
     const event: ContextEvent = { type: "context", messages: currentMessages };
     const handlerResult = await handler(event, ctx);
     if (handlerResult && (handlerResult as ContextEventResult).messages) {
       currentMessages = (handlerResult as ContextEventResult).messages!;
     }
     ...
     return currentMessages;
   }
   ```
   A truthy `handlerResult.messages` **does** replace `currentMessages`,
   which is the function's return value. Second Brain's `context` handler
   (`brainstem/prime-extension/src/index.ts`, `pi.on("context", ...)`)
   returns `{ messages: paged.messages }` when context paging is enabled
   and a patch was computed — exactly the shape this dispatcher consumes.

3. **Call site** — `packages/coding-agent/src/core/sdk.ts:319-322`:
   ```ts
   transformContext: async (messages) => {
     const runner = extensionRunnerRef.current;
     if (!runner) return messages;
     return runner.emitContext(messages);
   },
   ```
   `transformContext` is a named option on `Agent`'s constructor
   (`packages/agent/src/agent.ts:101`,
   `transformContext?: (messages: AgentMessage[], signal?: AbortSignal) => Promise<AgentMessage[]>;`),
   stored at `agent.ts:223` (`this.transformContext = options.transformContext;`)
   and forwarded into the loop config at `agent.ts:489`
   (`transformContext: this.transformContext,`).

4. **Consumption at the provider boundary** —
   `packages/agent/src/agent-loop.ts:489-508`,
   inside `streamAssistantResponse`:
   ```ts
   let messages = context.messages;
   if (config.transformContext) {
     messages = await maybePromiseWithAbort(config.transformContext(messages, signal), signal);
   }
   const llmMessages = await maybePromiseWithAbort(config.convertToLlm(messages), signal);
   const streamFunction = streamFn || streamSimple;
   ...
   const llmContext: Context = {
     systemPrompt: config.getSystemPrompt?.() ?? context.systemPrompt,
     messages: llmMessages,
     tools: context.tools,
   };
   const response = await maybePromiseWithAbort(
     streamFunction(config.model, llmContext, { ...config, apiKey: resolvedApiKey, signal }),
     signal,
   );
   ```
   The `messages` array returned by `transformContext` (i.e. by
   `runner.emitContext`, i.e. by Second Brain's `context` handler when it
   returns a patch) is piped **directly** into `convertToLlm` and then into
   `llmContext.messages`, which is the exact object hand to
   `streamFunction(model, llmContext, ...)` — the real outgoing-request
   builder for whichever provider adapter is active (`streamAnthropic`,
   `streamOpenAICodexResponses`, etc., in `packages/ai/src/providers/`).

`git diff v0.7.3 v0.7.4 -- packages/agent/src/agent-loop.ts
packages/agent/src/agent.ts` (both files) is comment-only — no logic
change in this chain (independently re-confirmed here; see
`03-upstream-delta-audit.md`'s provider-request section for the same
finding on the `packages/ai/src/providers/*` adapters this chain
terminates into).

**This is a complete, non-guessed trace from the `context` handler's return
value all the way to the `streamFunction(...)` call that builds the real
outgoing LLM request** — not merely "the type still allows a return value."

## 2. Tool result: does the RTD content-replacement path still work the
   same way?

**Verdict: COMPATIBLE.**

`ToolResultEventResult` — the type a `tool_result` handler returns to
patch content — byte-identical between tags:

v0.7.3 (`types.ts:945-949`) and v0.7.4
(`packages/coding-agent/src/core/extensions/types.ts:889-893`), both:
```ts
export interface ToolResultEventResult {
  content?: (TextContent | ImageContent)[];
  details?: unknown;
  isError?: boolean;
}
```
(confirmed with a direct `diff` of the two `git show`-extracted blocks —
zero output, i.e. no difference).

Registration is identical too: `on(event: "tool_result", handler:
ExtensionHandler<ToolResultEvent, ToolResultEventResult>): void;`
(v0.7.4 `types.ts:996`).

Dispatch — `packages/coding-agent/src/core/extensions/runner.ts:756-800`,
`emitToolResult(event)` — applies `handlerResult.content`/`.details`/
`.isError` onto a mutable `currentEvent` and returns a patch object only
when at least one field was set (`modified === true`), exactly the v0.7.3
mechanics. The call site in `agent-session.ts`
(`this.agent.afterToolCall = async ({ toolCall, args, result, isError }) =>
{ ... const hookResult = await runner.emitToolResult({...}); ... }`,
confirmed in `03-upstream-delta-audit.md` as outside every 0.7.3→0.7.4 diff
hunk) is unchanged.

Second Brain's RTD substitution (`pi.on("tool_result", async (event, ctx)
=> { ... return rtd.patch; })`, `index.ts`) returns exactly a
`{ content, details?, isError? }`-shaped (or `undefined`) value through
this same path — compatible.

## 3. Provider request: does `before_provider_request`'s `event.payload`
   still exist with a compatible shape?

**Verdict: COMPATIBLE, with one honest caveat.**

Type contract — `types.ts` v0.7.4 lines 582-585:
```ts
export interface BeforeProviderRequestEvent {
  type: "before_provider_request";
  payload: unknown;
}
```
`export type BeforeProviderRequestEventResult = unknown;` (line 873).
Direct `diff` against the v0.7.3 block for both declarations returns no
difference — byte-identical.

Dispatch — `sdk.ts:319-325`:
```ts
onPayload: async (payload, _model) => {
  const runner = extensionRunnerRef.current;
  if (!runner?.hasHandlers("before_provider_request")) return payload;
  return runner.emitBeforeProviderRequest(payload);
},
```
`runner.ts:890-919`, `emitBeforeProviderRequest(payload)`, threads
`currentPayload` through each handler unchanged from v0.7.3.

**What `payload` actually IS at runtime** (the caveat: `payload: unknown`
carries no compile-time shape, so this had to be traced into the provider
adapters that call `onPayload`): confirmed by grep across
`packages/ai/src/providers/*.ts` that `onPayload` is invoked with the
provider-specific **request body object built immediately before the HTTP
call** — e.g. `anthropic.ts:517`: `const nextParams = await
options?.onPayload?.(params, model);` (the real Anthropic Messages API
`params` object, including `messages`, `tools`, `system`, etc.);
`openai-completions.ts:152`, `openai-responses.ts:97`,
`openai-codex-responses.ts:145` all follow the identical pattern with
their own provider-specific `params`/`body`. This call-site pattern
(`options?.onPayload?.(params/body, model)`, called just before the fetch)
is present in both tags — confirmed by the same comment-only diffs on
`anthropic.ts`/`openai-*.ts` already cited in `03-upstream-delta-audit.md`.

Second Brain's `sensors.providerRequestMeta` (`brainstem/prime-extension/src/sensors.ts:1065-1103`)
treats `payload` as an untyped object and only reads `Object.keys(obj)`,
`obj.messages` (expects an array), and `obj.tools` — all present on every
provider's real request-body shape (`params.messages`, `params.tools` for
Anthropic/OpenAI-compatible adapters).

**Honest caveat**: because `payload` is `unknown` by design (deliberately
provider-agnostic), this audit cannot statically prove the payload's exact
field *names* are stable for every provider forever — that guarantee comes
from Second Brain's own code treating `payload` defensively
(`payload != null && typeof payload === "object" ? ... : {}`, `Array.isArray(obj.messages)`
fallback to `[]`) rather than from a stable type. This defensive handling
is unchanged and appropriate; no evidence of a shape change was found for
any of the 4 provider adapters actually exercised by Second Brain's real
pilots (Anthropic, OpenAI-Codex — see freeze/pilot reports for which
providers were used).

## 4. Compaction: do `session_before_compact`/`session_compact` event
   types/handler registration still exist with compatible shapes?

**Verdict: COMPATIBLE.**

v0.7.4 `types.ts:511-524`:
```ts
/** Fired before context compaction (can be cancelled or customized) */
export interface SessionBeforeCompactEvent {
  type: "session_before_compact";
  preparation: CompactionPreparation;
  branchEntries: SessionEntry[];
  customInstructions?: string;
  signal: AbortSignal;
}

/** Fired after context compaction */
export interface SessionCompactEvent {
  type: "session_compact";
  compactionEntry: CompactionEntry;
  fromExtension: boolean;
}
```
`types.ts:915-918`:
```ts
export interface SessionBeforeCompactResult {
  cancel?: boolean;
  compaction?: CompactionResult;
}
```
Registration: `types.ts:969-972`
```ts
on(event: "session_before_compact", handler: ExtensionHandler<SessionBeforeCompactEvent, SessionBeforeCompactResult>): void;
on(event: "session_compact", handler: ExtensionHandler<SessionCompactEvent>): void;
```
Direct `diff` of all three blocks against the v0.7.3 originals: **zero
output for all three** (byte-identical).

Dispatch — `agent-session.ts` (live checkout, since this is where the real
emission lives, cross-referenced against the same code confirmed present
unchanged in the worktree's patched files):
- `session_before_compact`: 0.7.3 line 7256/7258 → 0.7.4 line 6983/6985
  (line-shift only, from the unrelated upstream comment-stripping earlier
  in the same file — confirmed by direct byte-diff of the surrounding
  block in `03-upstream-delta-audit.md`). Awaited, and the checkpoint
  cancellation path (`return { cancel: true }` on a failed pre-compaction
  ledger checkpoint) still maps onto `SessionBeforeCompactResult.cancel`.
- `session_compact`: 0.7.3 line 7302 → 0.7.4 line 7028 (same line-shift
  situation), still carries `event.fromExtension` used by Second Brain's
  `wire<SessionCompactEvent>("session_compact", (event, ctx, session) =>
  mirror(session, "compaction_completed", { from_extension:
  event.fromExtension === true }, ...))`.

Second Brain's handlers (`pi.on("session_before_compact", async (event,
ctx) => { ... const compactEvent = event as SessionBeforeCompactEvent; ...
mirror(session, "compaction_started", { branch_entries:
Array.isArray(compactEvent.branchEntries) ? ... }); ... return { cancel:
true } / undefined; })` and the `session_compact` wire above) consume
exactly `branchEntries` and `fromExtension` — both present, unchanged.

## 5. Session identity: is the host session id still available to
   extensions, stably?

**Verdict: COMPATIBLE.**

`ExtensionContext` — v0.7.4 `types.ts:281-310`:
```ts
export interface ExtensionContext {
  ui: ExtensionUIContext;
  hasUI: boolean;
  cwd: string;
  sessionManager: ReadonlySessionManager;
  modelRegistry: ModelRegistry;
  model: Model<any> | undefined;
  isIdle(): boolean;
  signal: AbortSignal | undefined;
  abort(): void;
  hasPendingMessages(): boolean;
  shutdown(): void;
  getContextUsage(): ContextUsage | undefined;
  compact(options?: CompactOptions): void;
  getSystemPrompt(): string;
}
```
`ReadonlySessionManager` — `session-manager.ts:260-274`:
```ts
export type ReadonlySessionManager = Pick<
  SessionManager,
  | "getCwd" | "getSessionDir" | "getSessionId" | "getSessionFile"
  | "getLeafId" | "getLeafEntry" | "getEntry" | "getLabel" | "getBranch"
  | "getHeader" | "getEntries" | "getTree" | "getSessionName"
>;
```
Both `getSessionId(): string` (session-manager.ts:1309-1311) and
`getSessionFile(): string | undefined` (session-manager.ts:1313-1315) are
present and exposed through `ReadonlySessionManager`. Second Brain's
`resolveSessionId(ctx, anonSession)` (`index.ts`) calls
`ctx?.sessionManager?.getSessionFile?.()` — this exact method exists,
unchanged, confirmed **not present in the 0.7.3→0.7.4 diff at all** (a
direct `grep -n "getSessionFile"` of the diff returns nothing — the method
body is untouched, only surrounding comments elsewhere in the 251-line
`session-manager.ts` diff were stripped, as detailed in
`03-upstream-delta-audit.md`).

`cwd: string` and `model: Model<any> | undefined` on `ExtensionContext`
(used by Second Brain's `ctxCwd(ctx)` helper and `sensors.modelToString(ctx.model)`)
are likewise unchanged.

## Summary table

| Item | Verdict | Confidence |
|---|---|---|
| Context `{messages}` reaches provider request | **COMPATIBLE** | Fully traced to `streamFunction(...)` call site, not assumed |
| Tool-result content-replacement type | **COMPATIBLE** | Byte-identical type + dispatch |
| `before_provider_request` payload shape | **COMPATIBLE** | Type unchanged; runtime shape traced into 4 provider adapters, all unchanged; caveat: `payload: unknown` is deliberately untyped, no stronger static guarantee is possible without a runtime capture (Second Brain's own pilot evidence already provides that for 0.7.3; a fresh 0.7.4 pilot capture would close this) |
| Compaction event types/dispatch | **COMPATIBLE** | Byte-identical types; dispatch line-shifted only, byte-diffed unchanged |
| Session identity (`ctx.sessionManager`) | **COMPATIBLE** | `getSessionFile`/`getSessionId` unchanged, not present in diff at all |

## What still requires runtime proof (honest gap)

This is a **static** audit of source code, types, and call-site wiring —
it proves the contract shapes and dispatch code paths are unchanged, which
is strong evidence, but it is **not** a substitute for actually running
Second Brain's RC4 candidate extension against a real, running Prime 0.7.4
daemon and observing a live session (the same kind of live-pilot evidence
`00-pilot5-freeze.md` recorded for 0.7.3). In particular:
- The exact real-world JSON shape of `before_provider_request`'s
  `event.payload` for each provider (Anthropic vs OpenAI-Codex) was
  confirmed unchanged in *source*, but was not re-captured live from a
  running 0.7.4 process in this pass (0.7.3's real shape was captured in
  an earlier pilot per this campaign's evidence chain; a 0.7.4 equivalent
  capture is the natural follow-up before promotion).
- Whether `pruneOversizedVariables()` (new in #1540) or the RLM
  `thinking`-level option (new in #1510) interact with Second Brain's
  telemetry/vmem/ledger code in any unexpected way was not exercised at
  runtime (these features are additive and outside Second Brain's read
  surface per `03-upstream-delta-audit.md`, but "additive and unread"
  is a static claim, not a runtime one).
This audit deliberately does **not** claim these are proven safe at
runtime — flagging them explicitly rather than asserting compatibility
beyond what static source inspection can support.
