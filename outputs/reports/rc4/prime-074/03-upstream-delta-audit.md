# 03 — Upstream Delta Audit (Prime 0.7.3 → 0.7.4)

## Method

All commands are read-only `git show`/`git diff`/`git log` against the LIVE
checkout `C:\Tools\prime-agent` (currently at the exact `v0.7.3` tag commit
`61131b2d195ba7a67a4ce8ac60bb10cecae07b67`, plus the two known local
Windows patches — see `01-prime-073-known-good-baseline.md`). No file in
that checkout, or in the isolated `v0.7.4` worktree, was written during this
pass. Tags confirmed present and resolvable on `origin`:
`v0.7.3`, `v0.7.4` (`af0b8e00b9f704e834787fd321065ca78281f2aa`,
`chore(release): prepare v0.7.4 (#1569)`).

**The entire 0.7.3 → 0.7.4 release is 14 commits.** Full list
(`git log v0.7.3..v0.7.4 --oneline`):

```
af0b8e00b chore(release): prepare v0.7.4 (#1569)
b09fbdb46 fix(coding-agent): rank model search by intent (#539)
f8f0036cc docs: add Trendshift badge (#1500)
1663d443d Keep large IPython state from slowing later turns (#1540)
e7b8cae97 CI: require a linked Linear ticket on PRs (#1480)
8189b12d6 Normalize daemon socket paths before deriving identity (#1520)
824a9ee3b Let subagents be spawned with their own reasoning level (#1510)
d51590c41 Keep the draft when opening the agents view (#1372)
8ee310c5d fix(coding-agent): keep Shift+Enter newline working where it sends a raw \n (#1522)
aa0bdfa6a prompt: remove reference to unshipped async bash() kernel helper (#1508)
032e3ee74 chore: remove redundant comments and unused internals (#1505)
20b54977a fix(coding-agent): preserve goal continuation after compaction (#1316)
7ca44937f prompt: make long-running RLM work nonblocking, visible, and clear (#1188)
e85a67ac4 fix(coding-agent): reset daemon root depth (#1496)
```

Of these, `#1500` (docs badge), `#1480` (CI policy), `#1372` (agents-view
TUI draft state), `#1522` (TUI Shift+Enter), `#539` (model-selector search
ranking) are UI/CI/docs-only and outside this audit's surface (no files
under `core/extensions`, `core/sdk.ts`, `core/agent-session*.ts`,
`core/rlm-runtime.ts`, `core/session-manager.ts`, `core/compaction/`,
`packages/ai/src/providers/`, or `core/model-registry.ts` were touched by
any of them, confirmed by `git show --stat` on each).

**The single dominant commit is `032e3ee74` ("chore: remove redundant
comments and unused internals", #1505).** It accounts for the overwhelming
majority of the 117-file, 2571-line-deletion diff (`git diff --numstat
v0.7.3 v0.7.4 -- packages/coding-agent/src packages/ai/src`) across this
whole surface: JSDoc/section-banner comment stripping plus removal of a
handful of genuinely dead/unused exported functions. It changes **zero**
runtime behavior in every file checked below — confirmed by isolating the
non-comment `-`/`+` lines of every large diff and finding either nothing,
or an unrelated real change attributable to one of the other 4 functional
commits (#1540, #1510, #1520, #1316, #1496, #1188).

## Extension loader/runner API

### `packages/coding-agent/src/core/extensions/loader.ts`
Diff is comment-only (`// Registration methods - write to extension`,
`// Flag access...`, `// Check for package.json...`, numbered-step comments
in `discoverAndLoadExtensions` all removed). `createExtensionAPI`'s method
bodies (`on`, `getFlag`, `sendMessage`, ...) and
`discoverAndLoadExtensions`'s 3-tier discovery order (project-local →
global `agentDir/extensions/` → explicitly configured paths) are
byte-identical.
**Classification: NO_IMPACT.**
Justification: Second Brain's extension is discovered via the global
`agentDir/extensions/` tier (`C:\Users\assas\.prime\agent\extensions\second-brain\`,
confirmed in `00-pilot5-freeze.md`); that discovery path is untouched.

### `packages/coding-agent/src/core/extensions/runner.ts`
Diff is comment-only (`// Copy actions into the shared runtime...`,
`// Context actions (required)`, `// Flush provider registrations...`
removed). Directly inspected the real dispatch bodies this audit depends
on and confirmed byte-identical logic in both tags:
- `emitContext(messages)` (runner.ts:858-889 in the live 0.7.3 checkout):
  `structuredClone(messages)` → per-extension `context` handlers → if
  `handlerResult.messages` is truthy, `currentMessages = handlerResult.messages`
  → returns `currentMessages`.
- `emitToolResult(event)` (runner.ts:756-800): applies `handlerResult.content`
  / `.details` / `.isError` onto `currentEvent`, returns a patch object only
  when `modified`.
- `emitBeforeProviderRequest(payload)` (runner.ts:890-919): threads
  `currentPayload` through each `before_provider_request` handler,
  `handlerResult !== undefined` replaces `currentPayload`.
- `emitMessageEnd(event)` (runner.ts:714-753): **still rejects a role
  change** — `if (handlerResult.message.role !== currentMessage.role) { ...
  emitError(...); continue; }` — this is the exact mechanism Second Brain's
  `index.ts` docstring references ("the host replaces the message in place
  and rejects role changes").
**Classification: NO_IMPACT.**
Justification: these are the exact 4 dispatch functions backing Second
Brain's `context`, `tool_result`, `before_provider_request`, and
`message_end` handlers; all four are unchanged.

### `packages/coding-agent/src/core/extensions/types.ts`
Diff removes ~15 section-header comment banners
(`// === UI Context ===`, `// === Extension Context ===`,
`// === Tool Types ===`, `// === Resource Events ===`,
`// === Session Events ===`, `// === Agent Events ===`,
`// === Model Events ===`, `// === User Bash Events ===`,
`// === Input Events ===`, `// === Tool Events ===`,
`// === Event Results ===`, `// === Message Rendering ===`,
`// === Command Registration ===`, `// === Extension API ===`,
`// === Event Subscription ===`, `// === Tool Registration ===`,
`// === Provider Registration Types ===`, `// === Loaded Extension Types ===`,
`// === Extension Error ===`) plus one type-guard comment
(`// Type guards for ToolResultEvent`). **Every interface/type declaration
is otherwise identical**, including `ContextEventResult { messages?:
AgentMessage[] }`, `ExtensionAPI.on(...)` overload list (all 15+ event
names, including `session_start`, `before_agent_start` via
`ExtensionHandler<BeforeAgentStartEvent, ...>`, `context`, `tool_call`,
`tool_result`, `session_before_compact`, `session_compact`, `message_end`,
`before_provider_request`, `after_provider_response`), and
`ExtensionContext`.
**Classification: NO_IMPACT.**
Justification: zero type/contract change on the exact surface Second
Brain's `types/prime.d.ts` mirrors.

### `packages/coding-agent/src/core/extensions/index.ts`
Diff removes only re-export-grouping comments
(`// Built-in extensions`, `// Re-exports`, `// Events - Tool`, etc.). The
re-exported type/value list is identical (alphabetized differently by the
formatter but the same set — confirmed by inspection, no name added or
removed).
**Classification: NO_IMPACT.**

### `packages/coding-agent/src/core/extensions/bundled-modules.ts`
`git diff v0.7.3 v0.7.4 -- .../bundled-modules.ts` → **empty. No diff at
all.**
**Classification: NO_IMPACT (confirmed identical, not merely unaffected by
this pass's surface).**

## Event lifecycle / event bus

### `packages/coding-agent/src/core/event-bus.ts`
`git diff v0.7.3 v0.7.4 -- .../event-bus.ts` → **empty. No diff at all.**
**Classification: NO_IMPACT.**

### `packages/coding-agent/src/core/agent-session.ts`
472-line diff header (`39 insertions(+), 433 deletions(-)` via `--stat`) —
by far the largest file in this surface — but isolating every non-comment
`-`/`+` line (blank/`//`/`/* */`/`*`-prefixed lines excluded) reduces it to
exactly these real changes, none touching the 10 hooks Second Brain
depends on:
1. `const THINKING_LEVELS = [...]` moved out to `thinking-levels.ts` (pure
   relocation, re-imported).
2. `_notifyKernelStateAfterCompaction()` renamed to
   `_syncKernelStateAfterCompaction()` and extended to call the new
   `provisioner.pruneOversizedVariables()` (part of #1540, "Keep large
   IPython state from slowing later turns" — adds a `prunedDetail` sentence
   to the post-compaction IPython-state message; unrelated to any extension
   hook).
3. An `unfinishedActions().some(...)` predicate in the queued-action-dedup
   path was expanded to check `action.lifecycle.state` explicitly (part of
   #1316, "preserve goal continuation after compaction" — bug fix,
   internal turn-queueing logic, not an extension-visible event).
4. RLM subagent spawn (`rlm.run`) gained `thinking?: ThinkingLevel` request
   handling: destructures `thinking: rawThinking` from `kwargs`, validates
   it against `getSupportedThinkingLevels(modelSelection.model)`, passes
   `thinkingLevel: requestedThinkingLevel` into the child's runtime config
   (part of #1510, "Let subagents be spawned with their own reasoning
   level" — purely additive, optional parameter; a spawn that never passes
   `thinking` behaves exactly as before).
5. `this.agent.continue().catch(() => {})` — trivial formatting/error-swallow
   change, no semantic difference from the 0.7.3 two-line form.

Directly confirmed **byte-identical** (diff hunks do not touch these line
ranges at all) for the exact dispatch/consumption sites Second Brain's
hooks rely on:
- `session_start` emission (`this._sessionStartEvent = ...`, line ~1311 in
  0.7.3) and the `getAllTools`/`getActiveTools`/`setActiveTools` surface.
- `before_agent_start` dispatch via `this._extensionRunner.emitBeforeAgentStart(...)`
  (line ~5773 in 0.7.3).
- `tool_call`/`tool_result` dispatch (`runner.emitToolCall({...})` line
  ~1436; `runner.emitToolResult({...})` line ~1456 in 0.7.3) — including
  the exact `event.input`/`event.content`/`event.details`/`event.isError`
  shape passed in.
- `session_before_compact` dispatch (`hasHandlers("session_before_compact")`
  / `type: "session_before_compact"`, 0.7.3 line 7256/7258 → 0.7.4 line
  6983/6985 — line-shifted only by the upstream comment-stripping earlier
  in the file; byte-diffed the surrounding 70-line block directly and
  confirmed identical apart from the `_notifyKernelStateAfterCompaction` →
  `_syncKernelStateAfterCompaction` rename noted above).
- `session_compact` dispatch (0.7.3 line 7302 → 0.7.4 line 7028, same
  line-shift-only situation).
- `message_end` emission sites (`this._emit({ type: "message_end", message
  })`, 4 call sites at 0.7.3 lines 1988/5944/6030/7077/8229) and the
  `_replaceMessageInPlace`/`_emitExtensionEvent` consumption of
  `emitMessageEnd`'s return value — all outside every diff hunk.

**Classification: NO_IMPACT** (for the extension-hook surface).
**Classification: BENEFICIAL** (for the file as a whole — items 2-4 above
are net-positive fixes/features Second Brain's sessions inherit for free
with zero extension-side change required: post-compaction IPython state
messaging is more informative, goal continuation after compaction is more
reliable, and RLM subagents gain an optional `thinking` override Second
Brain's Sol contract does not need to use).
Justification: every event Second Brain's `index.ts` wires
(`pi.on("session_start", ...)`, `pi.on("before_agent_start", ...)`,
`pi.on("context", ...)`, `pi.on("tool_call", ...)`, `pi.on("tool_result",
...)`, `wire<...>("session_before_compact"/"session_compact", ...)`,
`pi.on("message_end", ...)`) is dispatched from code this audit directly
inspected and found byte-identical (modulo the one rename above, which
does not change `session_before_compact`'s cancellation contract
`{ cancel: true }` or `session_compact`'s `event.fromExtension` shape).

### `packages/coding-agent/src/core/agent-session-runtime.ts` /
`agent-session-services.ts`
Both diffs are comment-only (docstrings above `CreateAgentSessionRuntimeResult`,
`AgentSessionRuntime`, `createAgentSessionRuntime`, etc. removed). No
method signature or logic change.
**Classification: NO_IMPACT.**

### `packages/coding-agent/src/core/compaction/compaction.ts`,
`compaction/branch-summarization.ts`, `compaction/utils.ts`
All three diffs are comment-only (section banners, step comments) after
isolating non-comment lines; `findCutPoint`, `findValidCutPoints`,
`findTurnStartIndex`, `extractFileOperations`, `shouldCompact`,
`DEFAULT_COMPACTION_SETTINGS` are byte-identical logic.
**Classification: NO_IMPACT.**
Justification: this is the machinery behind `session_before_compact`'s
`branchEntries` payload and the durability-barrier checkpoint Second
Brain's `runLedgerCheckpoint` gates on; unchanged.

## Provider request generation and usage/telemetry

### `packages/coding-agent/src/core/sdk.ts`
Diff is comment-only around `createAgentSession` (`// Use provided or
create AuthStorage...`, `// Check if session has existing data...`, etc.).
Directly confirmed the `Agent(...)` construction's `onPayload`/`onResponse`
callbacks — the actual dispatch points for `before_provider_request` /
`after_provider_response` — are **entirely outside every diff hunk**:
```
onPayload: async (payload, _model) => {
  const runner = extensionRunnerRef.current;
  if (!runner?.hasHandlers("before_provider_request")) return payload;
  return runner.emitBeforeProviderRequest(payload);
},
onResponse: async (response, _model) => {
  const runner = extensionRunnerRef.current;
  if (!runner?.hasHandlers("after_provider_response")) return;
  await runner.emit({ type: "after_provider_response", status: response.status, headers: response.headers });
},
```
**Classification: NO_IMPACT.**
Justification: this is the exact payload Second Brain's
`sensors.providerRequestMeta(session, provider, model, providerRequestSeq,
event.payload)` consumes, and the exact `status`/`headers` shape
`sensors.providerResponseMeta` consumes — unchanged.

### `packages/coding-agent/src/core/model-registry.ts`
Diff is comment-only (schema-section banners, inline step comments).
`applyModelOverride`, `loadModels`, `validateConfig`, cost-merge logic
unchanged.
**Classification: NO_IMPACT.**

### `packages/coding-agent/src/core/session-stats.ts`
One-line diff: removes a single JSDoc comment above `SessionStats`. No
field change.
**Classification: NO_IMPACT.**

### `packages/ai/src/providers/anthropic.ts`
Diff is comment-only. The two `usage` construction sites Second Brain's
cache accounting ultimately traces through (`message_end`'s
`message.usage`) are unchanged:
```
output.usage.output = event.message.usage.output_tokens || 0;
output.usage.cacheRead = event.message.usage.cache_read_input_tokens || 0;
output.usage.cacheWrite = event.message.usage.cache_creation_input_tokens || 0;
output.usage.totalTokens = output.usage.input + output.usage.output + output.usage.cacheRead + output.usage.cacheWrite;
```
only the comment above the `totalTokens` line
(`// Anthropic doesn't provide total_tokens, compute from components`) was
removed; the computation is identical.
**Classification: NO_IMPACT.**

### `packages/ai/src/providers/openai-codex-responses.ts`,
`openai-completions.ts`, `openai-responses.ts`, `openai-responses-shared.ts`
All four diffs are comment-only (section banners, inline explanatory
comments, two comment-text rewordings in `parseSSE`'s `finally` block with
no logic change). Retry logic, SSE/WebSocket parsing, `mapStopReason`,
cache-retention resolution (`getPromptCacheRetention`) unchanged.
**Classification: NO_IMPACT.**
Justification: none of Second Brain's hooks read raw provider-adapter
internals directly (it consumes `message.usage` at `message_end` and
`event.payload`/`event.status`/`event.headers` at the
before/after-provider-request boundary, both already confirmed unchanged
above), so even if these adapters had changed materially, only a change to
`AssistantMessage.usage`'s field *names* would matter — none occurred.

## Tool registry / getAllTools / getActiveTools / setActiveTools

### `packages/coding-agent/src/core/tools/index.ts`
Real (non-comment) diff: removes 4 unused exported functions
(`createToolDefinition`, `createTool`, `createAllTools`, and the
`allToolNames` constant) that had no callers anywhere in the codebase (dead
code per #1505). `createAllToolDefinitions` — the one function actually
used to build the live tool catalog — is unchanged, and
`export type ToolName = "ipython"` is unchanged: **the real Prime tool
catalog in this RLM/IPython-only session shape is still exactly
`["ipython"]`**, confirming the finding already recorded in Second Brain's
own `outputs/reports/rc4/06-tool-working-set-live.md` (cited in
`index.ts`'s own R6 comment) still holds on 0.7.4.
No occurrence of `getAllTools`, `getActiveTools`, or `setActiveTools` in
any diff hunk anywhere in the audited surface (`grep` across all diffed
files for these three identifiers returns nothing beyond the unchanged
`types.ts` declarations already covered above).
**Classification: NO_IMPACT.**
Justification: Second Brain's `session_start` handler calls
`pi.getAllTools()`/`pi.getActiveTools()` read-only for measurement and
explicitly never calls `setActiveTools` (documented reason: the Python Tool
Working Set catalog's names don't match Prime's real single-tool
`["ipython"]` catalog, and `setActiveTools` takes a REPLACEMENT list). That
decision remains correct and unaffected on 0.7.4.

## Subagent/RLM lifecycle (`rlm-runtime.ts`)

Real diff: adds `normalizeRequestedRlmSubagentThinkingLevel(value)` (new
exported function, validates a requested `thinking` string against
`THINKING_LEVELS`) as part of #1510. `normalizeRequestedRlmSubagentModel`,
`normalizeRequestedRlmSubagentSessionName`, `findRlmModelMatches`,
`createRlmRunHostHandler`, `createRlmFindModelsHostHandler`,
`createRlmListSubagentsHostHandler` are otherwise unchanged (comment-only
diffs on the latter three).
**Classification: BENEFICIAL (additive, opt-in).**
Justification: Second Brain's Sol orchestrator contract and the `rlm`
skill/import never pass a `thinking` kwarg to `rlm.run()`/`rlm(...)`
today, so this is a strictly available-but-unused capability — zero
required change, and an unavailable/unsupported requested thinking level
now fails the spawn with a clear error message rather than silently doing
something unexpected (matches the existing "unavailable requested model
fails spawn" contract Second Brain's own docs already describe for
`model`).

Also confirmed relevant: commit `e85a67ac4` ("fix(coding-agent): reset
daemon root depth", #1496) modifies
`packages/coding-agent/src/modes/daemon/daemon-supervisor.ts` to
`delete workerEnvironment.RLM_DEPTH` before spawning a **new root** daemon
worker process (previously a root worker could inherit a stale `RLM_DEPTH`
from whatever environment launched the daemon itself). This does not touch
`rlm-runtime.ts` and is outside `brainstem/prime-extension/`'s read
surface (Second Brain's `index.ts` explicitly notes "the extension context
exposes no rlmDepth"), so it cannot regress anything Second Brain reads.
**Classification: NO_IMPACT (BENEFICIAL as a general correctness fix, not
observable by Second Brain's extension).**

## Session identity/transcript persistence

### `packages/coding-agent/src/core/session-manager.ts`
Largest deletion count in the whole surface after `agent-session.ts`
(`251` lines per `--stat`, `249` real deletions vs `4` insertions per
`--numstat`) but **every single line is a removed comment/docstring**
(confirmed by isolating non-`//`/`/* */`-prefixed `-` lines: none remain
that are not comment text — the file's class/interface/function bodies are
untouched). Specifically confirmed:
- `getSessionFile(): string | undefined` (line 1413 in the current live
  checkout) — the exact method Second Brain's `resolveSessionId()` calls
  (`ctx?.sessionManager?.getSessionFile?.()`) — **does not appear in the
  diff at all**, i.e. is provably byte-identical.
- `SessionEntry`/`SessionContext`/`SessionHeader`/`CompactionEntry`/
  `BranchSummaryEntry`/`CustomMessageEntry`/`SessionStateEntry` type shapes
  unchanged (only their doc comments were stripped).
**Classification: NO_IMPACT.**

### `packages/coding-agent/src/core/session-action-store.ts`,
`session-id.ts`, `session-cwd.ts`, `session-resolver.ts`,
`session-file-actions.ts`, `context-tree.ts`, `messages.ts`
`session-action-store.ts`, `session-id.ts`, `session-cwd.ts`,
`session-resolver.ts`, `session-file-actions.ts`: **all confirmed empty
diffs** (`git diff v0.7.3 v0.7.4 -- <path>` returns nothing for each,
individually verified). `context-tree.ts` and `messages.ts`: comment-only
diffs (JSDoc trimming on `ContextTreeNode`, a declaration-merging comment,
an inline `!! prefix` comment — no type/logic change).
**Classification: NO_IMPACT (all seven files).**

## Session leases (`session-lease.ts`)

`git diff v0.7.3 v0.7.4 -- packages/coding-agent/src/core/session-lease.ts`
→ **empty. No diff at all** (independently reconfirmed here; matches
`02-local-patch-disposition.md`'s finding). Nothing beyond the two known
Windows patches (already fully audited in `02-local-patch-disposition.md`)
touches this file between the tags.
**Classification: NO_IMPACT.**

## Configuration/extension loading & reloading paths

### `packages/coding-agent/src/config.ts`
Real diff: (1) removes 6 dead/unused path-helper exports
(`getReadmePath`, `getExamplesPath`, `getModelsPath`, `getSettingsPath`,
`getToolsDir`, `getPromptsDir` — none had any caller, #1505 dead-code
removal); (2) adds a `normalizeSocketPath()` helper (from #1520,
"Normalize daemon socket paths before deriving identity") used by
`getDaemonLogPath` and `getDaemonUpdateRestartManifestPath` to make socket
identity hashing consistent (this replaces a Windows-only
`socketPath.toLowerCase()` special case with a shared normalizer — the
same category of concern as Second Brain's own Patch B, but for a
completely different code path: daemon log file naming, not session-lease
directory locking).
**Classification: NO_IMPACT.**
Justification: Second Brain's own extension config (`config/*.toml`, read
by `brainstem/prime-extension/src/config.ts`'s `loadConfig()`) is entirely
separate from this file; extension discovery paths (`loader.ts`'s
`discoverAndLoadExtensions`, already confirmed comment-only above) do not
call into `config.ts`'s changed functions.

## Provider/model catalog and Anthropic/OpenAI-Codex request handling

Covered above under "Provider request generation and usage/telemetry" —
`anthropic.ts`, `openai-codex-responses.ts`, `openai-completions.ts`,
`openai-responses.ts`, `openai-responses-shared.ts` are all comment-only
diffs. No provider adapter file in `packages/ai/src/providers/` has a
functional diff in this release (independently confirmed via
`git diff --numstat v0.7.3 v0.7.4 -- packages/ai/src/providers` — every
row shows `0` insertions except `anthropic.ts` (0), `google-shared.ts`
(7 ins, unrelated to Google/tool schemas Second Brain never touches),
`mistral.ts` (4 ins), `openai-codex-responses.ts` (2 ins) — all comment
rewording, no field renames).
**Classification: NO_IMPACT.**

## Cache accounting (`cache_read`/`cache_write`/usage field handling)

Fully covered above (`anthropic.ts`): `cacheRead`/`cacheWrite`/`totalTokens`
computation is byte-identical. `message_end`'s consumption of
`message.usage` in `agent-session.ts` (`this._emit({ type: "message_end",
message })`) is outside every diff hunk. Second Brain's
`sensors.assistantUsage(session, provider, model, message.usage)` call
site therefore receives an identically-shaped `usage` object on 0.7.4.
**Classification: NO_IMPACT.**

## Summary table

| Area | File(s) | Classification | Note |
|---|---|---|---|
| Extension loader | loader.ts | NO_IMPACT | comment-only |
| Extension runner | runner.ts | NO_IMPACT | comment-only; dispatch fns byte-identical |
| Extension types | types.ts | NO_IMPACT | comment-only |
| Extension re-exports | extensions/index.ts | NO_IMPACT | comment-only |
| Bundled modules | bundled-modules.ts | NO_IMPACT | empty diff |
| Event bus | event-bus.ts | NO_IMPACT | empty diff |
| Session/agent core | agent-session.ts | NO_IMPACT (hooks) / BENEFICIAL (file) | all 10 used hooks byte-identical; real changes are #1510/#1540/#1316, none hook-visible |
| Runtime/services | agent-session-runtime.ts, agent-session-services.ts | NO_IMPACT | comment-only |
| Compaction | compaction.ts, branch-summarization.ts, utils.ts | NO_IMPACT | comment-only |
| Provider request/response | sdk.ts | NO_IMPACT | onPayload/onResponse untouched |
| Model registry | model-registry.ts | NO_IMPACT | comment-only |
| Session stats | session-stats.ts | NO_IMPACT | 1-line comment |
| Anthropic adapter | anthropic.ts | NO_IMPACT | usage/cache fields identical |
| OpenAI/Codex adapters | openai-*.ts (4 files) | NO_IMPACT | comment-only |
| Tool registry | tools/index.ts | NO_IMPACT | dead-code removal only; ["ipython"] catalog unchanged |
| RLM runtime | rlm-runtime.ts | BENEFICIAL | additive `thinking` param, opt-in |
| Daemon RLM depth | daemon-supervisor.ts | NO_IMPACT (BENEFICIAL, not observable) | root-worker RLM_DEPTH reset fix |
| Session manager | session-manager.ts | NO_IMPACT | comment-only; getSessionFile untouched |
| Session id/cwd/resolver/file-actions/action-store | (5 files) | NO_IMPACT | empty diffs |
| context-tree / messages | context-tree.ts, messages.ts | NO_IMPACT | comment-only |
| Session lease | session-lease.ts | NO_IMPACT | empty diff (reconfirmed) |
| Config/extension paths | config.ts | NO_IMPACT | dead-code removal + unrelated socket-path normalizer |
| Cache accounting | anthropic.ts (usage fields) | NO_IMPACT | identical |
| RLM system prompt content | prompts/rlm.ts | BENEFICIAL (not a contract) | new nonblocking-work/progress-update/simplified-English guidance text (#1188), additive to `ctx.getSystemPrompt()`'s base — Second Brain treats `base` opaquely and only appends, so a content-only change here is compatible by construction |

## Anomalies

None. No file in this audit's surface shows a diff that removes, renames,
or reshapes any event type, handler signature, or payload field consumed
by `brainstem/prime-extension/src/index.ts`. The one identifier rename
found (`_notifyKernelStateAfterCompaction` → `_syncKernelStateAfterCompaction`)
is a private method on `AgentSession`, not part of the extension contract,
and does not change `session_before_compact`'s awaited-checkpoint/`{cancel:
true}` semantics or `session_compact`'s `event.fromExtension` field.

## Verdict

**No BREAKING_FOR_BRAIN and no UNKNOWN_REQUIRES_RUNTIME_PROOF findings in
this static delta audit.** Every file in the specified surface either has
an empty diff, a comment/dead-code-only diff, or a real diff that is
additive/orthogonal to the exact hooks and fields
`brainstem/prime-extension/src/index.ts` uses. Runtime proof of this
conclusion (actually running RC4 candidate code against a real 0.7.4
daemon) is still required before promotion — this is a static-code
confirmation, not a substitute for the live pilot(s) later sections of the
0.7.4 upgrade qualification plan call for.
