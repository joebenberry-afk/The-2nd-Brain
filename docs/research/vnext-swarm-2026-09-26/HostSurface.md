## Top findings

### 1. The most valuable missing surface already exists: **prompt-time, task-specific memory before the first model request**

**Claim.** OMP can deliver a bounded answer or locator without waiting for a tool call, without adding a tool schema, and without rewriting the system prompt. `before_agent_start` exposes the transformed user `prompt`; return a hidden custom `message`, not a changing `systemPrompt`. Current Brain deliberately ignores that input (`_event`) and returns only after compaction. This is a coverage error, not a token-budget tuning problem.

**Evidence.** Installed `CA/src/extensibility/extensions/types.ts:782-790,1194-1198`; `runner.ts:1874-1925`; bundled `omp://extensions.md`, “Agent lifecycle” (returned messages appended once after the user batch). Brain `brainstem/omp-v3/index.ts:549-565` versus `:566-593`. `outputs/reports/v3-agent-experience/value/tasks.jsonl:1,3` asks remembered launcher/SQLite facts directly, without requiring tools. Claude Code and Codex have `UserPromptSubmit`; Gemini CLI has `BeforeAgent` (official sources below).

**Impact.** Current JIT has exactly zero opportunity to help a zero-tool answer. Prompt-time matching changes that to an opportunity on every user prompt; an abstention can still inject zero tokens. [INFERENCE] A high-confidence 40–100-token fact with evidence can eliminate the *entire* model-decides-to-search → tool → second-model-request cycle. Accuracy lift is unmeasured on OpenAI; old DeepSeek campaigns are weak-model evidence and must not be generalized.

**Confidence: HIGH** on surface availability and current gap; **MED** on value, pending an OpenAI subscription experiment.

### 2. **Cheap discovery is real; free pull is not**

**Claim.** A native rule/skill/tool advertisement can be 16–51 visible tokens, but any model-initiated pull usually causes another model request with its surrounding history. The optimization target is *avoided model requests/search output*, not merely a shorter tool description.

**Evidence.** Actual installed native o200k token counter measurements below: 18-token skill description; 21-token OMP skill row; 31-token minimal JSON schema, 51-token explicit strict function envelope; 39-token MCP tool definition; 16-token OMP device catalog row. OMP defaults extension tools to `loadMode: "discoverable"` (`CA/src/extensibility/extensions/types.ts:636-658`); `tools.xdev=true`, `tools.xdevDocs="catalog"` defaults (`CA/src/tools/settings.ts:866-899`). Full docs can be inlined by settings: discoverable does **not** guarantee a small prompt on every installation. MCP initialization instructions/catalog names also cost context. Claude Code now defaults to lazy MCP ToolSearch; Codex/Gemini/Cursor schema residency must be checked on the actual installed host/provider, not assumed.

**Impact.** [INFERENCE] Replacing a 600-token every-request brief with one 21-token skill row cuts *resident advertisement* 96.5%, but says nothing by itself about end-to-end tokens or whether the agent ever pulls. A 31-token tool used once can still be more expensive than a 70-token prompt-time hit if it adds a model request. Cache hits improve processing latency, not logical context size.

**Confidence: HIGH** for measurements and OMP defaults; **MED** for other hosts' wire cost.

### 3. **Use native path rules where they genuinely match, but OMP rulebook globs are not Cursor auto-attach**

**Claim.** Cursor auto-attaches `.mdc` rules for matching files; Claude Code has `paths:` rules; Gemini CLI discovers nested `GEMINI.md` on file access. OMP's ordinary rulebook `globs` are advisory metadata: they do not cause host-side `rule://` selection. OMP's genuinely host-matched surface is TTSR.

**Evidence.** `omp://rulebook-matching-pipeline.md`, §§5–6: rulebook name/description residency; `globs` “Not used to automatically select rulebook rules”; source `CA/src/capability/rule-buckets.ts:68-84`; `CA/src/prompts/system/system-prompt.md:28-50`. `omp://ttsr-injection-lifecycle.md`, §§2–5: regex/AST match assistant text/tool-argument streams, not incoming user prompts or arbitrary tool-result error text; default scope excludes thinking. Native noninterrupting tool matches prepend advice to the matching tool result; interrupting matches abort/retry generation with a 50ms scheduler delay **plus an extra model continuation**. Official Claude memory/Cursor rules/Gemini context docs establish their different attachment semantics.

**Impact.** [INFERENCE] Compile only highly precise path/command invariants to native matchers: zero Brain body tokens until matched, with no separate retrieval tool. This cannot replace prompt-time recall or general error-result matching. TTSR `question:` adds judge-model work; it is not free matching.

**Confidence: HIGH.**

### 4. **One universal core is feasible; current adapters do not implement one uniform product**

**Claim.** The universal baseline should be canonical Markdown + one bounded evidence-bearing CLI read + a tiny host-discovery instruction/skill. Hook/MCP adapters should translate events and output envelopes only. Current OMP uses compiled JIT; Claude V3 uses an eager brief and failure correction; Codex and Antigravity remain on legacy lifecycle/autoinject machinery.

**Evidence.** OMP README `brainstem/omp-v3/README.md:6-16,52-53`; Claude V3 README `brainstem/adapters/claude-code-v3/README.md:3-12`, implementation `src/second_brain/kb/hooks.py:49-93`; Codex `brainstem/codex-hooks/run.ps1:36,66-72`, `src/second_brain/adapters/codex.py:23,94-138`; Antigravity `src/second_brain/adapters/antigravity.py:24-43,168-200`. Existing `brain q` renders *titles/evidence*, not record bodies (`src/second_brain/kb/index.py:424-445`); its JSON output likewise excludes body (`commands_index.py:44-58`). `brain show` is a second lookup (`:66-103`).

**Impact.** [INFERENCE] A one-hop bounded “answer/locator + provenance” read avoids two-step q→show and lets all hosts consume exactly the same selection. Adapter divergence and legacy engines stop being prerequisites for usefulness. Pure files remain usable when Python/MCP/hooks are unavailable; that fallback is discoverable, not magically automatic.

**Confidence: HIGH** on current architecture; **MED** on proposed value.

### 5. **Version/contract drift is already concrete, not theoretical**

- **OMP is now 18.3.2**, not the README/campaign's 18.3.1. `where.exe omp` → `C:\Users\assas\.bun\bin\omp.exe`; `omp --version` → `omp/18.3.2`. Installed source and native package inspected under `C:/Users/assas/.bun/install/global/node_modules/@oh-my-pi/`; native package `package.json:3` agrees. Brain README `:18-42` records 18.3.1. The prompt-time contract inspected is the *current installed* one, not an old Pi example.
- **Codex output contract mismatch risk.** Current official Codex docs require `hookSpecificOutput: {hookEventName, additionalContext}` for `UserPromptSubmit`/`SessionStart`/`PostToolUse`. Repo legacy adapter emits top-level `additionalContext`, and its launcher forwards it unchanged (`codex.py:118-128`; `run.ps1:66-69`). README's “verified 0.147.0” checked installed plugin manifest/config shape, not proof that Brain context reached a model (`README.md:72-86`). **[INFERENCE] Treat current Brain Codex injection as unqualified until installed-host payload delivery is checked; do not claim it certainly fails on 0.147.0.**
- **Record-ID contract is outright incompatible across Brain paths.** OMP `loadView` requires every record ID to start `mem-` (`index.ts:305-314`) and invalidates the session's whole view on a load exception (`:522`). `state_pointers` and recovery are also mem-only (`:327,477`). LearningLoop's separate scratch actual-adapter proof: a valid mem-only view delivered; adding an eligible `note-` record made both callbacks `no_view`. See its report for capture producer evidence and runnable proof. Host selection cannot compensate for a rejected view.

**Confidence: HIGH** on version/source differences; **MED** on Codex runtime consequence. These are reasons to have tiny contract probes per host, not to build another orchestration layer.

### Host × surface matrix

**Definitions / accounting.** `R` = resident text/schema counted on each model request while present; `D` = body loaded on demand then normally remains in conversation until compaction; `T` = event-time appended context/tool result, then normally remains until compaction; `E` = ephemeral request transform. “Added once” is **not** “paid once”: a 70-token appended fact retained for 20 requests contributes approximately 1,400 logical input tokens. Cache-prefix impacts below are [INFERENCE] from exact-prefix caching semantics unless source states placement. Stable resident prefixes are reusable; appending preserves prior prefix; changing system instructions/tools or deleting old injected messages can invalidate reuse from that point. Provider serialization/compaction can change this. No live cache-latency measurement was run.

Latency codes: `L0` local file/memory work, no extra inference; `LP` process startup + local work; `LR` selected pull introduces model tool-call/result continuation; `LN` MCP connection/network/approval in addition; `LX` abort/continuation or another model/judge call. None implies a guaranteed number. Isolated current CLI warm-process-launch median below was 118.63ms; host process wrappers, matching and model latency are not included.

**Verified Y** means this installed OMP version's source/types/bundled documentation inspected, not a paid end-to-end model test. **N** means official current documentation or repository adapter only; no installed runtime delivery claim.

| Host × surface | Cost / cache-prefix impact | Triggerability / latency | Installed verified + evidence |
|---|---|---|---|
| OMP `AGENTS.md`, supported context files, `RULES.md`, always-apply rules | R full body; stable prefix; edits/rebuilds can change it | Startup/native discovery, no agent pull; L0 | **Y**; `omp://context-files.md`; `CA/src/prompts/system/system-prompt.md:37-42` |
| OMP `APPEND_SYSTEM.md`, `--append-system-prompt`, custom system prompt/template | R full body; avoid task-varying content in early prefix | Static setup/programmatic options; L0 | **Y**; `omp://system-prompt-customization.md` |
| OMP `before_agent_start` returned custom message | T only on hit; appended after user batch preserves older prefix | Incoming user prompt, including dequeued user-containing batches; not tool-only iteration; L0 or LP | **Y**; `types.ts:782-790,1194-1198`; `runner.ts:1874-1925`; `omp://extensions.md` |
| OMP `before_agent_start` returned `systemPrompt` | R replacement for this request/continuations; task-varying replacement risks large prefix churn | Same prompt-time event; L0 | **Y**; same types; full replacement, not an append primitive |
| OMP `input` event; direct `sendMessage` / `sendUserMessage` | Rewritten/appended input T; not a free hidden cache | Input transformation or explicit extension message; L0; message may trigger turn/LX | **Y**; `types.ts:1170-1178,1467-1485`; `omp://extensions.md` |
| OMP `tool_result` | T result patch; prior transcript prefix preserved; retained result still costs later requests | Actual tool result, including error; L0 | **Y**; Brain `index.ts:566-593`; `omp://extensions.md` “Tool lifecycle” |
| OMP `tool_call.additionalContext` | T after batch results, not before first execution | Tool args; passive advice cannot prevent first execution; L0 | **Y**; `CA/src/extensibility/shared-events.ts:313-342` |
| OMP `context` hook | E before each model call; original session unchanged; append is cheap now, removing/replacing earlier E content can lose cross-call suffix cache | Arbitrary message inspection; L0 each request; must dedupe/bound | **Y**; `shared-events.ts:172-183`; `types.ts:1162-1164` |
| OMP `before_provider_request` | E can replace raw provider payload; maximal power and serialization/cache risk | Every supported provider request except documented Devin exception; L0 | **Y**; `types.ts:771-780,1166`; `omp://extensions.md` |
| OMP compaction hooks | `session.compacting.context` feeds summary; `preserveData` is metadata, not automatically model knowledge. Post-compact next-turn T possible | Before/customize/after compaction; L0; native compaction already has its own inference cost | **Y**; `shared-events.ts:64-90,422-437`; Brain `index.ts:549-565,595-600` |
| OMP skill | R name+description (~21 measured tokens); D body on `read skill://`; stable catalog prefix | Semantic agent choice, explicit `/skill:name`, subagent autoload; LR for model read; user slash no retrieval inference | **Y**; `omp://skills.md`; `system-prompt.md:28-34` |
| OMP ordinary rulebook rule | R name/globs/description (~21-row example); D body via `rule://` | Agent-selected, **globs not host auto-attach**; LR | **Y**; `omp://rulebook-matching-pipeline.md` §§5–6; `rule-buckets.ts:68-84` |
| OMP TTSR regex / AST rule | No rule body in startup rulebook; T on match; appended reminder preserves earlier prefix; aborted output is not free | Assistant output/tool args; `interruptMode: never` tool result reminder, or abort/retry LX; AST edit/write only; not user-prompt/error-result matcher | **Y**; `omp://ttsr-injection-lifecycle.md` §§2–5; `rule-buckets.ts:68-74` |
| OMP TTSR judged `question` rule | No body until yes, **judge workload** on completed in-scope output | Semantic output check, warning not stream interrupt; LX; not recommended for cheap Brain recall | **Y**; bundled rulebook §6, lifecycle §10 |
| OMP custom tool, extension tool, MCP tool | Essential: R schema. Discoverable default: R catalog entry + D schema via xd; Code Mode can expose typed declaration. `inline` setting can inline full docs anyway | Model pull; LR, plus LN for MCP; schema/catalog choice must be measured on actual settings | **Y**; `types.ts:636-658`; `tools/settings.ts:866-911`; `tools/xdev.ts:319-371`; `omp://mcp-runtime-lifecycle.md` |
| OMP slash commands / prompt templates / file mentions / shell-generated attachments | D selected prompt/file body; normal conversation residency thereafter | Explicit user command, optional shell expansion; L0/LP, no autonomous recall guarantee | **Y**; `omp://slash-command-internals.md`, `omp://skills.md` |
| OMP native memory backends | Backend-specific: local system memory or recalled context + recall tools | Native local/Hindsight backends; may perform network/model work; not Brain-required | **Y**; installed package `README.md:16-35`, `omp://memory.md` |
| Claude Code `CLAUDE.md` / supported `AGENTS.md` / imports | R full loaded content; stable initial context; imports do **not** save tokens | Startup; nested files on relevant reads; L0 | **N**; C-Memory |
| Claude Code `.claude/rules` `paths:` | D scoped bodies; unscoped rules R. Attachment placement may affect prefix | Host path activation on matching file use; L0 | **N**; C-Memory “Path-specific rules” |
| Claude Code auto-memory | R first 200 lines or 25KB of MEMORY.md; D topic files | Startup index, model file reads for details; L0/LR | **N**; C-Memory “How it works” |
| Claude Code skills / slash skills / dynamic shell context | R name+description; D SKILL.md; disabled model invocation can omit advertisement | Model relevance or explicit slash; dynamic `!command` on selected skill; LR/LP | **N**; C-Skills; a one-skill library is preferable to one skill per fact |
| Claude Code `UserPromptSubmit` / `UserPromptExpansion` | T system reminder beside current prompt, transcript-persisted | Deterministic local prompt match before model; LP | **N**; C-Hooks “Add context for Claude”, “UserPromptSubmit” |
| Claude Code `SessionStart` / `SubagentStart` | T initial context; repeated on resume/compact as documented | Startup/resume/clear/compact/fork; LP | **N**; C-Hooks; V3 `kb/hooks.py:84-93` |
| Claude Code `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` | T reminder next to tool result; MCP/tool output replacement also possible | Args/output/error; passive pretool context still arrives by next model request; LP | **N**; C-Hooks “Add context for Claude”; Brain README explicitly requests installed failure-channel validation |
| Claude Code compaction | Root CLAUDE.md re-read after compact; nested files/path rules re-trigger. SessionStart compact can restore tiny pointer set | Native reloading + hook; LP for hook. Do not assume PreCompact stdout becomes model context | **N**; C-Memory compaction FAQ; C-Hooks |
| Claude Code MCP tools/resources/prompts/channels | Current default R names+server instructions, D schemas via ToolSearch, then results T; channels push opted-in events | Model/user pull or explicit channel opt-in; LR/LN; channel not a universal baseline | **N**; C-MCP “Scale with MCP tool search”, “Push messages with channels” |
| Claude Code system-prompt append / user attachments / file reads / subagent return | R static append or D/T selected content; subagents isolate working history but return tokens | CLI/user/model-directed; L0/LP/LR; subagent invocation adds model work | **N**; C-Skills/C-Memory/C-Hooks; don't use subagents merely to fetch one memory |
| Codex `AGENTS.md` / overrides / developer instructions | R discovered chain, stable per-run; root→cwd, 32KiB default cap | Once per launched run/session; L0 | **N**; O-Agents |
| Codex skills | R name+description+path, D body; initial list capped at 2% context or 8,000 chars if unknown | Explicit `$skill` or implicit description match; LR | **N**; O-Skills |
| Codex `UserPromptSubmit`, `SessionStart`, `SubagentStart` | T extra developer context via event-specific nested envelope | Prompt/startup/user work; `SessionStart source=compact` before immediate postcompact continuation; LP; trusted hook required | **N**; O-Hooks “Review and trust hooks” / event sections |
| Codex `PreToolUse` / `PostToolUse` | T developer context; PostToolUse includes failing Bash exits | Tool args/result/error; LP; cannot undo already-run command | **N**; O-Hooks; don't invent separate Claude-shaped PostToolUseFailure |
| Codex `PreCompact` / `PostCompact` | Observation/persistence boundaries, not a substitute for documented SessionStart compact injection | Auto/manual compact; LP | **N**; O-Hooks |
| Codex MCP tools / resources / server instructions, plugin bundles | Schemas/catalog + initialization instructions have resident cost; selected result D/T. Exact lazy wire representation not established here | Model pull; connected MCP tools can also be lifecycle hook handlers; LR/LN or local hook dispatch | **N**; O-MCP; O-Hooks “MCP tool hooks” |
| Codex CLI shell/read/user attachments | No extra Brain tool schema if existing shell used; only line/skill advertisement R plus selected result D | Agent chooses `brain q`; LR+LP | **N** host delivery; **Y** core CLI scratch smoke below |
| Gemini CLI GEMINI.md / configurable AGENTS.md / imports | R concatenated instructions sent with every prompt; nested JIT files D | Startup hierarchy and host file/directory access; L0 | **N**; G-Memory; `context.fileName` supports AGENTS.md |
| Gemini CLI skills | R name+description; D body+folder structure in history | `activate_skill`, approval consent, model relevance; LR (+human latency) | **N**; G-Skills |
| Gemini CLI `BeforeAgent` | Per-turn prompt additionalContext; no startup body on miss | Incoming user prompt; LP; no extra model call for hook itself | **N**; G-Hooks “BeforeAgent” |
| Gemini CLI `AfterTool` | T appended directly to tool result | Result/error observations; LP | **N**; G-Hooks “AfterTool” |
| Gemini CLI `BeforeModel`, `BeforeToolSelection` | E request replacement/filtering; changing earlier system/tools can invalidate prefix | Each model request; L0/LP; tool selection can force tools but doing so adds work | **N**; G-Hooks |
| Gemini CLI SessionStart / PreCompress | Startup T (interactive first history turn, noninteractive prompt prepend). PreCompress only asynchronous observational state-save, **not injection** | Startup/resume/clear; compression event; LP | **N**; G-Hooks lifecycle sections |
| Gemini CLI extensions / custom slash commands / MCP | Packaging, not a new token-free channel. Context R, skill catalog R, MCP schemas/catalog R or host-specific, selected resource/body D | Extension bundles context/skills/commands/MCP/hooks; `@server://resource/path` invokes resources/read; LR/LN or explicit command LP | **N**; G-Extensions, G-MCP |
| Cursor user/team/project Always rules / AGENTS.md | R system-level instructions; current docs say rule bodies included at start of context | Static always scope; L0 | **N**; U-Rules |
| Cursor Auto Attached / Apply to Specific Files | D matching `.mdc` body; early context placement can change prefix when activated | Host file glob match; no autonomous tool-retrieval decision; L0 | **N**; U-Rules metadata truth table |
| Cursor Agent Requested / Apply Intelligently | R description, D body when agent selects; Manual rules no automatic body | Semantic choice or `@rule`; LR or explicit mention | **N**; U-Rules |
| Cursor skills / slash commands / file mentions | R skill advertisement, D selected body/resources; nested/path skills can limit advertisement | Agent relevance, slash, file scope; LR/user-driven | **N**; U-Skills |
| Cursor `sessionStart` | T initial system context `additional_context`; startup prefix only if stable | Session start, LP | **N**; U-Hooks “sessionStart” |
| Cursor `postToolUse` / `postToolUseFailure` | T `additional_context` after result; MCP result replacement supported | Actual result/failure; LP | **N**; U-Hooks corresponding output tables |
| Cursor `beforeSubmitPrompt` / `preCompact` | **No documented knowledge-injection output** on these events; output is allow/block/user_message or observational notification | Cannot assume Claude/Gemini prompt push maps here | **N**; U-Hooks explicit schemas |
| Cursor MCP tools/resources/prompts / subagent results | Available tools/catalog and selected output; exact residency/lazy cost not established from docs | Model/user pulls, approvals; LR/LN | **N**; U-MCP feature table/Available Tools |
| Antigravity current repository transport | SessionStart code emits prefix in systemPrompt + ephemeral step; PreInvocation ephemeral steps; PostToolUse telemetry only | Host-specific camelCase protobuf-based hook envelope; LP; not interchangeable with Gemini CLI | **N** installed runtime; repo `adapters/antigravity.py:13-43,168-200`, hook config has PreInvocation/PostInvocation/PostToolUse/Stop, **not SessionStart** (`brainstem/adapters/antigravity/hooks.json:1-38`) |
| Hermes existing repository plugin (ancillary target) | Stable system PREFIX + ephemeral pre_llm_call TAIL, writeback tool; model routing is extra unrelated machinery | Plugin-specific callbacks; process/network cost not measured | **N**; `brainstem/adapters/hermes/README.md:7-39`; no recommendation to retain model routing |
| Plain shell / any other agent | Files + existing shell: zero new schema, optional 29-token instruction; D result | Only launcher/user/agent-directed; AGENTS.md is a convention, not universally auto-read | **Y** core smoke only; no host-specific automatic trigger claim |

### Which surface wins for the four jobs?

| Job | Preferred route | Why / limits |
|---|---|---|
| (a) Prompt-time memory questions, e.g. M01/M03 | **Deterministic bounded prompt-time match → answer-bearing tail context**: OMP before_agent_start message, Claude/Codex UserPromptSubmit, Gemini BeforeAgent. On Cursor/unsupported hosts: tiny instruction + one semantic skill or tiny tool, then one-hop pull. | No tools need to be emitted first. Return actual fact plus evidence, not “maybe run brain.” Abstain on ambiguous/stale/scope-unsafe matches. OMP TTSR watches generated output, not incoming questions. Cursor beforeSubmitPrompt isn't documented to inject context. |
| (b) Path/command/error gotchas | Host-native path rules when equivalent; post-result append for error corrections and general observation; OMP regex TTSR tool-only/no-interrupt for precise command/path hints if desirable | Error facts exist only after the failure. Noninterrupting advice cannot prevent the first command. Truly preventive requirements belong in trusted static/path policy or an explicit validated pre-exec control, not claimed as passive “advice.” Do not force arbitrary memory into permission gates. |
| (c) Orientation at start | **Tiny capability advertisement and only genuinely invariant environment facts**; task-specific orientation after user prompt; `brain brief` explicit when requested | Avoid a generic 600-token catalog carried through every request. A one-line “where to recall” plus “how to run safely” is different from dumping all memories. Native files are cheaper and simpler than a subprocess for an invariant. |
| (d) After compaction | Reuse native static reload; preserve only active-task state + IDs/evidence paths, then reselect on next prompt/tool. OMP completion-aware recovery T; Claude/Codex SessionStart compact | Never replay every historical memory. Gemini PreCompress/Cursor preCompact do not provide general postcompact injection; rely on persistent tiny instructions plus next appropriate read/hook or explicit recovery command. OMP preserveData is not itself visible context. |

### Minimal universal contract and maximum necessary adapter

**Core, one source of truth.**

1. Canonical `records/*.md` remain readable without any host. Each answer must preserve scope, status, evidence and record identity; derived native rules/skills are disposable materializations, not independent memory databases.
2. Existing `brain q` / `brain show` are the compatibility baseline. Add **one bounded context-rendering mode in the core**, e.g. `brain q "question" --context`, returning the selected answer/locator body with ID+evidence or nothing. This is proposed, **not an existing flag**. The current q→title→show ceremony should not be wrapped into every adapter independently. Same core selection must serve prompt hook, custom tool and optional MCP. Keep `brain note` as the write entrance; do not require every host to understand record YAML or lifecycle ledgers.
3. One project or user instruction, measured at 29 o200k tokens: `For prior decisions, gotchas, or code locations, run \`brain q "<question>"\`; use \`brain show <id>\` for evidence.` Once the one-hop mode exists, update the instruction rather than keep aliases/duplicate paths. If CLI is unavailable, the installed skill points to the canonical file location using existing file tools.
4. **One Agent Skill**, not one skill per fact. Short intent description; body teaches bounded recall, provenance and when not to use memory. Shared `.agents/skills/brain/SKILL.md` where supported; copy/link into host-native discovery directory where necessary. Don't duplicate both rich AGENTS instructions and rich skill text in startup context.
5. Optional one-tool MCP server only for hosts that need a tool interface/remote access: `brain({q:string})` → bounded answer+evidence. A local stdio wrapper suffices; no daemon, auth service, embeddings service or orchestration policy is necessary for local read-only use. A future capture tool is a separately justified capability, not a prerequisite for recall.

| Host | Adapter should be at most |
|---|---|
| OMP | One extension normalizing prompt, tool result and compaction events to the same core; existing compiled local view can make hooks process-free. Optional one discoverable read-only `brain` tool. No changing system prompt. |
| Claude Code | One JSON command entrypoint shared by UserPromptSubmit, optional PostToolUse/Failure and SessionStart compact; settings entries + one skill/file locator. No eager brief by default. |
| Codex | Same normalized core; current nested hook output envelope, trusted hook registration, correct PostToolUse failure semantics; SessionStart compact for recovery. Optional one MCP tool, not a legacy autoinject pipeline. |
| Gemini CLI | Small extension manifest bundles same skill/CLI pointer and BeforeAgent/AfterTool handlers. Use configured context.fileName=AGENTS.md or a tiny GEMINI.md import/pointer. No claim that PreCompress injects. |
| Cursor | Tiny AGENTS rule + skill; generated narrowly scoped `.mdc` only for path facts; optional sessionStart/postTool hooks. Prompt-time zero-call recall cannot be guaranteed by currently documented beforeSubmitPrompt output. |
| Antigravity | Native skill/rule/CLI pointer plus one verified PreInvocation transport translating to core; keep distinct from Gemini's event protocol. Installed contract probe required. |
| Plain-shell agent | No adapter: accessible canonical files and `brain` executable, plus a launcher/user instruction when that agent doesn't discover AGENTS.md. |

### Candidate schema/description measurements (local, no model calls)

Command run: `bun C:/Users/assas/AppData/Local/Temp/brain-host-surface-measure.ts`.

Counter: installed `@oh-my-pi/pi-natives/native/index.js` `countTokens(text)` default o200k. Installed `pi-agent-core/src/tokenizer.ts:28-35,70-86` documents this default; direct call succeeded. These are **exact o200k counts of the shown strings**, not exact provider-wire/API counts for GPT-5.5/GPT-6 or Claude/Gemini. Host wrappers, path names, injected intent fields and tool-serialization framing add tokens. `tiktoken` was absent; no package installed.

| Candidate | Bytes | o200k tokens | char/4 estimate |
|---|---:|---:|---:|
| Universal instruction above | 112 | **29** | 28 |
| Description: `Recall project decisions, gotchas, and code locations before guessing or repeating a failed approach.` | 101 | **18** | 26 |
| OMP `- brain: <description>` | 110 | **21** | 28 |
| OMP `- brain (): <description>` rule row | 113 | **21** | 29 |
| `- xd://brain — Recall project decisions, gotchas, and code locations.` | 71 | **16** | 18 |
| Code Mode declaration `brain(args: { q: string }): Promise<unknown>;` | 45 | **12** | 12 |
| Minimal compact schema below | 139 | **31** | 35 |
| Explicit function schema with useful description, `additionalProperties:false`, `strict:true` | 233 | **51** | 59 |
| MCP tool definition with useful description / `inputSchema` | 173 | **39** | 44 |

```json
{"name":"brain","description":"Recall project facts.","parameters":{"type":"object","properties":{"q":{"type":"string"}},"required":["q"]}}
```

A ~30-token schema is therefore plausible as a local string, not a 30-token *all-in* tool. The 12-token declaration is not enough alone to explain when to use it. Most importantly, reducing tool schema residency doesn't make an agent decide to invoke it. For a single tool, a short essential schema can even be cheaper than an extra discovery read; measure rather than presuming lazy always wins.

**Read-path smoke and latency.** Ran actual CLI only against a temporary copy of all 121 canonical record files and projects (not the repo DB):

`env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B C:/Users/assas/AppData/Local/Temp/brain-host-surface-smoke.py`

Script invoked `python -B -m second_brain.kb.cli q PYTHONHOME --home <temp-copy> --all-projects --limit 1` five times. Exit 0, returned `mem-6d592dd0c627` current/TESTED launcher gotcha and its evidence pointer. Durations **285.14, 118.36, 113.85, 118.63, 120.58ms; median 118.63ms**. First run builds only the temp index. `index.search` calls `refresh(home)` each query (`src/second_brain/kb/index.py:344-345`), so this is process+imports+refresh+query, not pure SQLite latency. The title/evidence-only output confirms the two-hop limitation; this smoke does not prove natural-language relevance or host delivery. Temp home removed by script. No repo writes, suites, installations, live model calls or campaign reruns.

### Evidence key / primary sources

`CA` = `C:/Users/assas/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent`. `omp://...` references are the bundled documentation exposed by this running installed host; source/type references are from the installed package. Host binary version measured independently as 18.3.2.

- **C-Hooks:** https://code.claude.com/docs/en/hooks.md — “Add context for Claude”, UserPromptSubmit, SessionStart, tool/compaction event contracts.
- **C-Memory:** https://code.claude.com/docs/en/memory.md — AGENTS/CLAUDE loading, path rules, MEMORY.md cap, compaction behavior.
- **C-Skills:** https://code.claude.com/docs/en/skills.md — metadata/body split, invocation controls, dynamic shell injection.
- **C-MCP:** https://code.claude.com/docs/en/mcp.md — default ToolSearch, resources/prompts/channels and server instructions.
- **O-Hooks:** https://developers.openai.com/codex/hooks.md (redirects to https://learn.chatgpt.com/docs/hooks.md) — official current event/JSON/trust contracts.
- **O-Agents:** https://developers.openai.com/codex/guides/agents-md.md (redirects to https://learn.chatgpt.com/docs/agent-configuration/agents-md.md).
- **O-Skills:** https://developers.openai.com/codex/skills.md (redirects to https://learn.chatgpt.com/docs/build-skills.md).
- **O-MCP:** https://developers.openai.com/codex/mcp.md (redirects to https://learn.chatgpt.com/docs/extend/mcp.md?surface=cli).
- **G-Hooks:** https://geminicli.com/docs/hooks/reference/ — BeforeAgent/AfterTool/BeforeModel and lifecycle sections.
- **G-Memory:** https://geminicli.com/docs/cli/gemini-md/ — hierarchical/JIT context; configurable filenames.
- **G-Skills:** https://geminicli.com/docs/cli/skills/ — name/description system prompt, activate_skill, consent/body history.
- **G-Extensions:** https://geminicli.com/docs/extensions/ — extension bundle components.
- **G-MCP:** https://geminicli.com/docs/tools/mcp-server/ — discovered tools/schemas/resources and resource mentions.
- **U-Rules:** https://cursor.com/docs/rules.md — four rule modes and metadata truth table.
- **U-Hooks:** https://cursor.com/docs/hooks.md — sessionStart/postToolUse/postToolUseFailure injection; beforeSubmitPrompt/preCompact limits.
- **U-Skills:** https://cursor.com/docs/skills.md — skill discovery, paths, manual invocation and body loading.
- **U-MCP:** https://cursor.com/docs/mcp.md — tools/resources/prompts and invocation/approval.
- **Cache semantics:** https://developers.openai.com/api/docs/guides/prompt-caching.md — exact rendered-prefix matching includes tools/developer/history; append-only updates; changed tools/early context affect cache. This supports cache reasoning, **not a measured guarantee for the `openai-codex` subscription transport**.

Official web pages are current-documentation evidence, not proof of the versions installed on this machine. Gemini's docs additionally announce transition of unpaid/Google One CLI users to Antigravity CLI; that does not make their hook protocols interchangeable.

## Breakthrough candidates

### A. Prompt-time evidence lane, not an eager brief

- **Concrete change:** Reuse existing project/scope/eligibility selection to match incoming prompt terms and attach at most one small answer-bearing fact or locator plus evidence through the native before-model prompt event. Keep zero-token abstention. Do not modify static system prompt. Keep tool-result gotchas as a separate lane.
- **Change of kind:** Brain can inform an answer that would otherwise finish without any tool use; tool-result JIT structurally cannot.
- **Expected effect:** Zero-tool memory coverage 0 → eligible prompt matches. [INFERENCE] One successful hit can save one or more full agent requests. No justified percentage accuracy forecast.
- **Effort:** M. **Risk:** false-positive memories, outdated facts, scope leakage; existing relative FTS relevance is not calibrated confidence. Do not send full user prompt to another model just to decide whether to recall.
- **Obsoletes:** “startup and ordinary prompts must always add nothing” as universal policy; broad eager brief; mandatory tool-call gate.
- **Cheapest confirm/kill:** First zero-model replay on current/revalidated M01/M03 and no-benefit prompts: inspect exact selected record, scope, bytes, evidence and abstentions. Then parent-authorized paired OMP sessions using **`openai-codex/gpt-5.5`**, fixed settings, baseline versus prompt-tail plus current tool JIT. Measure correctness, total logical tokens, model-request count, p50/p95 wall latency; separate cache-read from noncached tokens. Kill if no-tool correctness doesn't improve or no-benefit false injections dominate. No DeepSeek/OpenRouter; no run performed here.

### B. Compile facts to native triggers, keep retrieval for questions

- **Concrete change:** A materializer exports only selected precise path gotchas to Claude `paths:` / Cursor `globs` rules and exact OMP command/path TTSR rules with `interruptMode: never`; preserve canonical ID/evidence. Gemini uses scoped context files where scope semantics fit. Keep error-result hook and prompt matching for cases native rules cannot cover.
- **Change of kind:** Host performs activation; agent no longer spends a reasoning/tool turn deciding to fetch that class of memory.
- **Expected effect:** No Brain rule body before match, no separate recall request. [INFERENCE] Removes some 604-line-adapter trigger-decoding responsibility, but cannot remove all adapter work.
- **Effort:** M. **Risk:** host scope differences; instructions may have higher authority than advisory evidence; false match; generated-file churn; OMP TTSR prose matching may add continuations. Use no natural-language judged rules for basic recall.
- **Obsoletes:** Custom matching for the *covered subset only*, duplicated host-owned rule truth; not all of index.ts.
- **Cheapest confirm/kill:** Scratch native rule and `omp ttsr test` against positive/negative command/path snippets, no model calls. On other hosts inspect effective rule context using supported diagnostics. Then a tiny authorized `openai-codex/gpt-5.5` A/B for command/path tasks; kill if native activation overmatches or costs extra continuation requests versus direct append.

### C. One-hop recall result, portable across shell/skill/tool/MCP

- **Concrete change:** Core bounded renderer returns selected body/locator+evidence in one call; one optional tool delegates to it. One 18-token skill description; avoid host-specific memory APIs and duplicated retrieval engines.
- **Change of kind:** Memory becomes an evidence-producing primitive usable by any coding agent, rather than a host-injected catalog that encourages a hunt.
- **Expected effect:** Existing q→show can become one retrieval; [INFERENCE] saves one request boundary when the first output otherwise lacks the answer. CLI median measured 118.63ms shows local work is not the likely dominant expense compared with a model continuation, but inference latency was not measured.
- **Effort:** S–M. **Risk:** truncation removing qualifiers/evidence; a tiny schema without a precise description can lower invocation rate. Don't claim this alone fixes the no-tool blind spot.
- **Obsoletes:** Wrapper-specific rendering, mandatory two-step q/show for simple questions; legacy “prefix/tail” retrieval stacks for hosts migrating to this contract.
- **Cheapest confirm/kill:** Zero-model record/CLI smoke covering answer+evidence budgets and no-match; authorized `openai-codex/gpt-5.5` sessions with 29-token line versus 21-token skill row versus 51-token direct function versus 16-token discoverable row. Count actual invocations and total requests, not just advertisement tokens. Kill variants that remain unused.

### D. Demand-shaped recovery instead of replaying memory exposure history

- **Concrete change:** Postcompaction recovery carries active state/evidence pointers only; when a new prompt/tool demands a prior fact, reselect it. Exploit native root-instruction reload. Keep completed compaction versus requested-only distinction.
- **Change of kind:** Recovery restores the *ability to retrieve and continue* rather than rebuilding a mini memory dump.
- **Expected effect:** Bound current 160-token recovery independently of historical exposure count; [INFERENCE] less irrelevant postcompact context, especially on long sessions. Existing OMP already partly follows this; improvement is cross-host consistency and demand selection, not a new subsystem.
- **Effort:** S–M. **Risk:** active state absent from recorded data; native hooks differ and some are observation-only.
- **Obsoletes:** Broad SessionStart brief after every compact; replay-all exposed records.
- **Cheapest confirm/kill:** Scratch lifecycle tests using existing host payload fixtures plus actual installed no-model hook plumbing. Parent-authorized `openai-codex/gpt-5.5` forced-compaction task only after the payload checks; verify continuation correctness and tokens. Don't build a generic replay engine.

## Kill list

1. **Kill tool-result-only delivery as the definition of JIT.** It forbids helping an answer that never calls a tool. Evidence `index.ts:549-593`; tasks M01/M03.
2. **Kill eager generic briefs as the default for every host.** Claude V3 still injects ≤600 tokens (`README.md:7`), while OMP injects zero at start. Keep explicit brief and tiny invariant orientation; task-time selection is the useful boundary. No OpenAI efficacy claim from old DeepSeek runs.
3. **Kill “hidden means free” and “injected once means only one token charge.”** Hidden custom messages still enter model context; exact-prefix caching doesn't remove logical tokens. Evidence installed event/message types and official cache docs.
4. **Kill plans treating OMP ordinary rule globs as automatic matching.** They are advisory; only TTSR or an extension matches host-side (`omp://rulebook-matching-pipeline.md` §6).
5. **Kill semantic/judge-driven TTSR as the default memory router.** It adds model work per completed candidate, while cheap matching should decide ordinary recall. Reserve it for separately justified quality gates, not this project goal.
6. **Kill a tool/skill per record.** [INFERENCE] At the measured 21-token row, 121 rows are ~2,541 resident tokens before any bodies (not measured on the actual heterogeneous catalog). One capability advertisement and host-side index suffice.
7. **Kill legacy adapter autonomy/model-routing policy on the recall path.** `src/second_brain/adapters/codex.py:23,94-138`, Antigravity imports and Hermes README show extra engines/prefix policy. Replace adapters only when their equivalent core transport is qualified; canonical data preservation is separate.
8. **Kill claims that config registration equals model-visible delivery.** Codex envelope mismatch risk; Claude adapter itself documents a dropped Bash correction channel (`brainstem/adapters/claude-code-v3/README.md:22-24`). Require a tiny per-version delivery probe.
9. **Kill the `mem-`-only consumer restriction once canonical capture emits other IDs.** It invalidates an entire view rather than one record (`index.ts:312,522`). LearningLoop has the isolated runtime proof.
10. **Kill compulsory MCP/daemon installation for local CLI-capable agents.** Optional interoperability transport is useful; forcing another long-running layer is not required by any observed local need. Files/CLI+skill is the universal baseline.
11. **Kill provider-dollar optimization in this evaluation.** Owner uses the `openai-codex` subscription. Optimize tokens, latency, correctness and useful actions; ignore OpenRouter. Historical monetary comparisons are not this decision criterion.

## Open questions

1. What does the intended OMP `openai-codex/gpt-5.5` or GPT-6 request actually serialize for one added discoverable tool under this user's Code Mode/xdev settings? Counts above are local string counts; no provider request/cached-token proof was collected.
2. What selection threshold/record wording gives high precision on real incoming prompts, especially non-memory tasks? Existing FTS title/term ranking is not calibrated for unsolicited advice.
3. Which current canonical records still answer the old M01/M03 prompts correctly after retirement and plan changes? Revalidate records/ground truth before any new campaign; don't optimize toward stale facts.
4. Does the installed Codex 0.147.0 accept the legacy top-level `additionalContext` despite the current official nested contract? Does installed Claude deliver PostToolUseFailure Bash context? This assignment inspected docs and repository wiring, not those host runtimes.
5. Can Cursor offer a newer documented prompt-time injection route beyond its currently documented beforeSubmitPrompt schema? Without one, native semantic discovery remains agent-dependent.
6. For Gemini/Antigravity users, which actual CLI/product/version is the target? Current Gemini documentation announces a transition, while the repository's Antigravity protocol is different. Do not consolidate by naming alone.
7. How much active-task state must survive compaction beyond native summaries? Current OMP pointer recovery has a 160-token cap, but choosing which state matters requires real continuation tasks rather than expanding the budget.
