# Real Antigravity Smoke Evidence — 2026-08-16

Environment: `agy` 1.1.13 (C:\Users\assas\AppData\Local\agy\bin\agy.exe), model
`gemini-3.7-flash-high`, Antigravity IDE 1.107.0, Second Brain repo
`brain/p3-lean-code` HEAD fcfdf8a9 + repair commits. All runs were REAL external
Antigravity agent executions (headless `agy -p`). Nothing here was simulated.

## Adapter installation state

- Plugin source: `brainstem/adapters/antigravity/` (repo).
- Installed at `~/.gemini/config/plugins/second-brain-adapter/` — every file
  byte-identical to the repo source (hash-verified by the installer).
- `agy plugin validate <installed>` -> `[ok] skills: 1 processed, hooks: 1 processed`.
- `agy plugin list` -> second-brain-adapter with components `["skills", "hooks"]`.
- Root cause of the earlier 0-byte manifests: `agy plugin import` truncates the
  app plugin directory (files mtime == import timestamp). Repair: reinstall from
  the repo source with hash verification; register via `agy plugin install`
  (never `agy plugin import`).

## Hook contract corrections discovered against the real CLI

1. hooks.json plugin schema: `PreInvocation`/`PostInvocation`/`Stop` are FLAT
   handler lists; `PostToolUse`/`PreToolUse` are GROUPED (`matcher` + `hooks`).
   The previous grouped form for PreInvocation was rejected at runtime:
   `invalid hook "second-brain": command hook must specify 'command'`.
2. Hook commands run via `cmd /c` with cwd = hooks.json dir; embedded quotes in
   `-File "scripts/run-hook.ps1"` break execution (`Illegal characters in path`).
   Use the unquoted relative form.
3. CLI hook payloads are FLAT (protojson): `invocationNum`, `initialNumSteps`,
   `stepIdx`, `toolCall{name,args}`, `error`, `executionNum`, `terminationReason`,
   `fullyIdle` at the payload ROOT (not nested under `preInvocationHookArgs`
   etc.). The handler now merges nested + root.
4. Real transcript schema (`transcript_full.jsonl`): lines are
   `{"step_index":N,"source":"USER_EXPLICIT|SYSTEM|MODEL","type":"USER_INPUT|...",
   "content":"<USER_REQUEST>...</USER_REQUEST><ADDITIONAL_METADATA>..."}`.
   The parser extracts the `<USER_REQUEST>` body; tool chatter is ignored.

## Gate §24 — real AutoInject smoke: PASS

Run: `agy -p "<task>" --output-format stream-json --model gemini-3.7-flash-high`
(conversation `17f141ff-311f-41d4-b46d-02540dc285b1`, see smoke-13-stream.jsonl).

- Real PreInvocation payload captured (`real-preinvocation-payload.json`):
  conversationId, workspacePaths[], transcriptPath, artifactDirectoryPath,
  modelName=gemini-3.7-flash-high, invocationNum=0.
- Real PreInvocation response captured (`real-preinvocation-response.json`):
  `{"injectSteps":[{"ephemeralMessage":"[BRAIN_CONTEXT_DELTA v1] ... ITEM ...
  Migration ordering ..."}]}` — the canonical bounded packet (758 tokens), with
  the seeded "Migration ordering / apply migrations in numeric order" memory as
  the top-ranked item.
- Brain telemetry recorded: kind=preinvocation, decision=INJECT,
  packet_tokens=758, candidate_count=10, selected_count=6, harness=antigravity,
  model_visible=true, delivery_id recorded.
- Agent response (1 turn, ZERO tool calls): `apply migrations in numeric order`
  — the exact memory body; no full memory dump.

## Gate §25 — real P3-H STOP smoke: PASS

Conversation `0ddd4691-...` (see hook-telemetry-excerpt.jsonl).

- Fixture A (incomplete material requirement): a critical requirement was
  seeded in the Brain Requirement Ledger for the real conversation; the resumed
  real run's Stop hook returned
  `{"decision":"continue","reason":"incomplete material requirement: The
  migration smoke requirement must be reported as verified"}` (captured
  `real-stop-response-continue.json`), telemetry kind=stop_continue
  material_unverified=1; the agent RE-ENTERED execution (extra invocations and
  tool steps observed) and the run ended safely with a final response.
- Fixture B (complete task): runs without ledger requirements stop with
  `{"decision":"stop","reason":"session complete"}`, telemetry kind=stop_allowed
  material_unverified=0.

## PostToolUse / PostInvocation — real telemetry: PASS

- PostToolUse payload captured (`real-posttooluse-payload.json`): flat
  `stepIdx`/`toolCall{name:view_file,args}`/`error`; handler returns `{}` and
  records tool=view_file, step_idx, success (see telemetry excerpt).
- PostInvocation: telemetry kind=turn_end recorded per turn.

## Gate §26 — real subagent smoke: NOT PROVEN (recorded limitation)

The headless CLI exposes no subagent spawn surface (`agy agent` lists no
configured agents; no subagent flag in `agy --help`). The Antigravity Python SDK
supports subagents but requires `GEMINI_API_KEY` (absent on this machine), and
the Antigravity app (GUI) was not driven. The adapter implements the subagent
payload path (`parentConversationId` -> distinct session identity + worker role,
bounded context) and will handle it when the surface becomes available; per
plan §26 this limitation is recorded honestly and no parent ID is invented.

## Required permissions (headless CLI, scoped)

`agy` headless mode auto-denies tools without exact allow-rules; rules are
exact command strings (`command(<cmd>)`, no wildcards) in
`~/.gemini/config/config.json` -> userSettings.globalPermissionGrants.allow and
`~/.gemini/antigravity-cli/settings.json` -> permissions.allow. Granted for the
smoke: `brainctl memory search/show/...` variants, the repo venv python
`-m second_brain` variants, node/git/npm. A disposable workspace plus scoped
rules were used instead of `--dangerously-skip-permissions`.

## Files

- smoke-12-stream.jsonl / smoke-13-stream.jsonl — real agy stream-json output
- real-preinvocation-payload.json / real-preinvocation-response.json
- real-posttooluse-payload.json
- real-stop-response-continue.json
- real-transcript-sample.jsonl (sanitized sample of the real transcript)
- hook-telemetry-excerpt.jsonl (Brain hook telemetry for the proof runs)


## Post-cleanup confirmation run

After removing temporary diagnostics and reinstalling the clean launcher, a
final real run (conversation `3660f895-0219-4b6e-81a9-ffa0d1e92d72`,
gemini-3.7-flash-high) produced: preinvocation INJECT (758 tokens, 6 selected,
model_visible=true), PostInvocation turn_end, Stop stop_allowed; agent
response `apply migrations in numeric order` with zero tool calls. The direct
live PreInvocation response with the Migration-ordering packet was captured in
real-preinvocation-response.json (smoke-13, conversation 17f141ff).
