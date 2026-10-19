# Layer 4: reversible rendering. Owner decision and design

Date: 2026-10-17. Status: **approved by the owner** ("you can do layer 4 test it and continue to
improve 2nd brain"). On by default in OMP since it passed E6 there; opt-in through `brain proxy`
for Claude Code and Codex, which have not passed (§6).

Research behind it: `Documents/Context Solution/report.md` (context-compaction research pack),
RQ5 layer table, the layer-4 row (claims C25, C28, C56, C60, C63, C64) and experiment E6.

## 1. What the decision changes

- **V4 §3.2 rule 4** ("adds context or nothing") gets one exception, written at the rule itself.
  Layer 4 may replace old, large tool output **in the request a model receives** with a stub that
  carries a recall id. Three things stay as they were:
  - Host history and transcripts are never edited.
  - Nothing else in a request changes.
  - The Brain still never blocks, vetoes, steers or continues host work.
- **V5 §4** ("no new resident tools", "no second harness adapter beyond the Claude Code hook and
  MCP"):
  - Restore reuses `brain_recall` and `brain recall`, so the Brain still has three tools.
  - Claude Code and Codex have no hook that can rewrite a request. The only layer-4 seam they have
    is a local proxy, so the proxy counts as covered by this approval. It is opt-in: it runs only
    when the user starts `brain proxy` and points the host at it.
  - This doc is the record. The V5 text is unchanged.
- **V4 rule 1** (a feature must show up in telemetry as used). Each epoch that elides output writes
  a `kind: "elide"` telemetry row. A restore shows up as a `recall` row whose id starts with `t-`.

## 2. Design

**Core: `brain/src/render.ts`.** It is host-neutral and uses Node built-ins only. Adapters map the
host's messages to `ToolOutput { key, text, tool? }[]` in conversation order, where `key` is the
host's call id. They then write back each `Elision { index, id, stub, tokens, fresh }`.

- **Policy.** Budgets are counted by `outputTokens` (next bullet), not by the brain's chars/4.
  - `keep` = 30 000 tokens: the newest tool output always stays verbatim.
  - `step` = 50 000 tokens: the epoch size.
  - `min` = 500 tokens: smaller outputs are never elided.
  - Interpretation: an epoch re-sends everything after its first new stub uncached (Anthropic
    1.25x the base input price, 2x with 1-hour caching; OpenAI 1x), while each elided token then
    saves one cache read (0.1x) per later request. So `step` is above `keep`: an epoch pays back
    in about 7 requests, 11 with 1-hour caching.
  - keep + step caps live tool output near 80k of this estimate. In E6 (§5) Claude Code's
    requests peaked at 124k Claude tokens with layer 4 and 224k without; Claude counts logs about
    1.4x heavier than o200k.
  - Amended 2026-10-17, before any elision was measured, from keep 40k / step 20k (OMP's pruning
    defaults). A cache-economics simulation over six session shapes (warm cache, two requests per
    tool output) gave, against no layer 4: 40k/20k input -50%, Anthropic cost -24% on average and
    +20% on 15 log reads; 30k/50k input -47%, cost -35% on average and -6% at worst. This is a
    model, not a measurement; E6 measures.
- **Token count.** `outputTokens` weights each UTF-16 unit (letters 0.2, digits 0.8, space or tab
  0.1, newline 1, other ASCII 0.6, other 1), fitted against tiktoken o200k on tool output.
  - Fact: mean absolute error 6.0% on the fitting set and 5.1% held out. chars/4 ran 33-39% low on
    logs, JSON and listings, so with it a log-heavy history stayed mostly verbatim.
  - Each output is counted once per conversation (cached by key and length): about 1.6 ms per MB.
- **Epoch watermark.** It is stateless and deterministic.
  - A boundary sits where the running total of tool-output tokens first reaches each multiple of
    `step`.
  - The watermark is the last boundary that has at least `keep` tokens of output after it.
    Eligible outputs at or before the watermark are elided.
  - Appending output only adds later boundaries. So the watermark never moves back, and it jumps
    about `step` tokens at a time. Between jumps every stub, and so the request prefix, is
    byte-identical.
  - Why this matters: per-turn masking cut cache hits to 23% from 84% (C28). Providers cache exact
    prefixes (C63).
  - Cost: one cache miss per epoch, on the elided span and everything after it.
- **Sticky per conversation.** A `Renderer` keeps the keys it has elided.
  - If the host later shrinks or rewrites an elided output in place (OMP pruning), the same stub
    goes out again, byte for byte, so the prefix and the recall id do not change. Amended
    2026-10-17 after E6: the first version re-elided a shrunk output under a new id and sent a
    host placeholder under `min` as is, so either changed the prefix.
  - A fresh re-read has a new call id, so it is judged on its own position. A stub is never
    re-elided.
  - If a request carries fewer tool outputs than the last one (compaction, `/clear`, a branch
    switch), the sticky set resets.
- **Stub.** It is factual, deterministic and 60-90 tokens:
  `[Second Brain elided this <tool> output to save context: <lines> lines, ~<tokens> tokens. Recall id t-<10 hex> returns it in full; re-running the tool also shows it. It began: <first 100 chars>]`.
  - Amended 2026-10-17 after E6, where every stub had it: the re-run clause appears only for
    read-only tools (read, read_file, grep, glob, find, ls, list_dir), because re-running anything
    else repeats its side effects. The head never ends in half a surrogate pair.
  - Images and other non-text output are never touched.
- **Restore.** The id is `t-` plus the first 10 hex characters of the original's SHA-256.
  - The original is written once, atomically, to `state/elided/<id>.txt`. It is local and
    gitignored like all of `state/`. Copies older than 14 days are dropped at most once a day.
  - `judgedAnswer` (both `brain_recall` and `brain recall`) answers a `t-…` query with that file,
    verbatim.
  - Unknown or expired ids get a short "re-run the tool if that has no side effects" answer.
  - Privacy: the copy holds raw tool output, with the same exposure as the host's own transcript
    files.

**Adapters.**

| Host | Seam | Switch |
|---|---|---|
| OMP | extension `context` event: return `{ messages }` built from shallow copies; never mutate | on by default except on the Anthropic Messages API (§7); `BRAIN_RENDER=off` disables, `BRAIN_RENDER=on` forces |
| Claude Code | `brain proxy`; `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>/anthropic` plus `ENABLE_TOOL_SEARCH=true` (§3) | running the proxy |
| Codex | `brain proxy`; custom provider in `config.toml` (below) | running the proxy |

The proxy:
- **Routes.** `/anthropic/*` → `https://api.anthropic.com`, `/chatgpt/*` → `https://chatgpt.com`,
  `/openai/*` → `https://api.openai.com`.
- **What it rewrites.**
  - Anthropic `POST …/v1/messages`: `tool_result` blocks.
  - Responses `POST …/responses` and `…/responses/compact`: `*_output` items.
  - Everything else, every response, and auth pass through untouched.
- **Request bodies.** Compressed bodies (zstd, gzip, br, deflate) are decoded, and the rewritten
  body is forwarded uncompressed.
- **Failure.** It fails open: on any error the original bytes go upstream.
- **Binding.** It binds 127.0.0.1 only.

Codex `config.toml` (ChatGPT login; API-key users point `base_url` at `…/openai/v1`):

```toml
model_provider = "brain"
[model_providers.brain]
name = "Brain proxy"
base_url = "http://127.0.0.1:<port>/chatgpt/backend-api/codex"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = false
```

## 3. Facts the design rests on (observed 2026-10-17)

- **OMP already prunes tool output.** Fact: OMP prunes on its own and persists the result.
  - Where: `pi-coding-agent/src/session/session-maintenance.ts:715` (`#pruneToolOutputs`) and
    `pi-agent-core/src/compaction/pruning.ts:77`.
  - Defaults: protect 40k, minimum saving 20k, `skill` results protected. It is guarded by
    cache warmth.
  - Placeholders: `[Output truncated - N tokens]` and `[Superseded by a newer read of this file]`.
    These placeholders cannot be restored.
  - E6 ran with OMP's compaction off, which also skips `#pruneToolOutputs`
    (`session-maintenance.ts:3312-3317`); `#pruneStaleToolResults` still ran. Interpretation: the
    E6 OMP baseline kept more tool output than a default OMP session, so layer 4's OMP input cut
    there is an upper bound.
- **OMP's pruning is cache-aware.** Fact: `session-maintenance.ts:303-318`.
  - Per-turn pruning only rewrites the last 8 000 tokens (`PRUNE_CACHE_WARM_SUFFIX_TOKENS`):
    rewriting the warm prefix "costs the cacheWrite premium on the whole suffix".
  - A full flush waits for 90 minutes idle (`PRUNE_IDLE_FLUSH_MS`), past Anthropic's 1-hour
    OAuth cache TTL.
  - Interpretation: the same economics set layer 4's `step` (§2).
- **Claude Code turns tool search off behind a base URL.** Fact: 2.1.296 disables tool search
  for a non-first-party `ANTHROPIC_BASE_URL`. Input tokens of one `claude -p` request: direct
  23 416; through the proxy 38 221; through the proxy with `ENABLE_TOOL_SEARCH=true` 23 118.
- **chars/4 under-counts tool output.** Fact: an E6 log of 18 725 characters is 7 617 o200k
  tokens; chars/4 gives 4 681. Claude counts about 1.8 characters per token on such logs and
  OpenAI about 2.5.
- **In OMP, layer 4 cannot reduce compactions.** Fact: OMP floors its compaction trigger by its
  estimate of the stored conversation.
  - Where: `pi-agent-core/src/compaction/compaction.ts:357-374`. The source comment says on-wire
    transforms must not deflate the trigger.
  - So in OMP, layer 4 cuts per-request tokens and cost (and possibly context rot), but not
    compactions.
  - Inference, untested: Claude Code and Codex probably trigger autocompaction on provider-reported
    usage, so behind the proxy they may compact less.
- **Claude Code 2.1.296 behind a base-URL proxy.** Fact, from a throwaway probe proxy:
  - It works with a subscription login; the OAuth bearer passes through.
  - Request bodies are uncompressed JSON. Responses are SSE.
  - `context_management` holds only `clear_thinking_20251015`, so Claude Code does not clear tool
    uses server-side.
- **Codex 0.162.1 behind the proxy.** Fact:
  - `OPENAI_BASE_URL` is ignored under a ChatGPT login.
  - `-c openai_base_url=…` first retries a WebSocket for about 8 s, then sends zstd bodies.
  - The custom provider above sends plain JSON, with no WebSocket and with ChatGPT auth plus
    `chatgpt-account-id` passed through.
  - Every request carries the full `input`; there is no `previous_response_id`.

## 4. Invariants (tests)

- The same outputs give the same stubs, byte for byte, across calls and processes.
- Between epochs, adding output changes no earlier stub.
- User text, assistant text and small outputs are never touched.
- Sticky: shrinking or replacing an elided output's text re-sends the same stub, byte for byte,
  and a re-read with a new key in the keep window stays verbatim.
- A stub never holds half a surrogate pair; only read-only tools' stubs suggest a re-run.
- Restore round trip: `brain recall <id>` returns the original exactly.
- OMP: the messages the host passed in are never mutated, and `{ messages }` is returned only when
  something changed.
- Proxy: fail-open, zstd bodies, and untouched streaming responses.

## 5. E6 gate

Bench: `brain/scripts/probebench.ts --scenario e6`.
- **Arms.** Each harness's baseline against the same harness with layer 4. For OMP the baseline is
  the `brain` arm: same extension, `BRAIN_RENDER=off`.
- **Scenario.**
  - Many large log reads with no forced compaction.
  - The plant and probes from E2.
  - Two detail probes whose answers exist only inside early tool output, which layer 4 elides.
- **Pass criteria.**
  - At least 30% fewer input tokens per finished run.
  - An equal probe score, detail probes included.
  - Cache-weighted input below baseline: uncached ×1, cache writes ×2, cache reads at the model's
    list-price ratio (2026-10-19): ×0.05 Opus and Sonnet 5.5, ×0.025 Fable 5.1, ×0.1 Haiku 5.5 and
    OpenAI models. Until 2026-10-19 reads were ×0.1 for every model; the E6 models (Haiku 5.5,
    gpt-6-astra) are ×0.1 in both versions, so the §6 verdicts stand.
- The cache hit rate and compaction counts are measured, not gated (§3, §6).
- Owner decision, 2026-10-17: the cache-weighted criterion replaced "a cache hit rate no lower than
  baseline", which layer 4 fails by arithmetic (§6).

Layer 4 stays off by default until E6 passes on a harness. It then turns on for that harness only,
and in OMP only for providers without a cache-write premium (§7).

## 6. E6 results (2026-10-17)

Runs: `--depth 18`. No harness compacted on its own (0 compactions in every run). Models: Claude Code
`haiku` (claude-haiku-5-5); Codex and OMP gpt-6-astra.

| Harness | Baseline | Runs (layer 4 / baseline) | Input tokens | Cache hit | Cost | Wall | Probes, detail |
|---|---|---|---|---|---|---|---|
| Claude Code (proxy) | default | 1 / 1 | −32.8% | −4.9 pp | −40.0% (list-price estimate) | +3.9% | 11/11, 2/2 in both arms |
| OMP (`BRAIN_RENDER=on`) | brain | 3 / 3 | −39.3% | −4.5 pp | −20.5% | +6.1% (2 uncontended runs) | 11/11, 2/2 in both arms |
| Codex (proxy) | default | 2 / 1 valid | −29.2% | −3.7 pp | not reported | −32.5% | 11/11, 2/2 in both arms |

- **Elisions and restores.** Fact: 12 elisions per run on Claude Code and OMP, 13–14 on Codex.
  - The model re-read an elided output with `brain recall t-…` twice per run on Claude Code and
    once on OMP and Codex. Every detail probe was still answered.
  - A restore returns the original verbatim in 148 ms through the CLI and 8 ms through MCP.
- **Validity rule.** A run counts only when every batch log reached the context in full
  (`logsRead` equals the depth).
  - Fact: Codex's first default run printed only the tails of all 18 logs and is excluded.
  - Fact: an earlier Codex pair, run before the rule existed, is excluded too. Its layer-4 arm
    printed only tails, so there was nothing to elide (0 elisions).
- **Speed.** Fact: rendering adds a median 0.06 ms per OMP request. The proxy adds about 2 ms to a
  1 MB request it has seen before (5.5 ms the first time).
  - One OMP layer-4 run took 395 s while another bench shared the machine. Its two reruns took
    190 s and 218 s, against 188 s and 196 s for the baseline.
  - Fact: the first build made every Claude Code hook process load undici. `cli.ts` imports
    `proxy.ts`, which imported `node:http`, and Node's ESM facade for `node:http` loads undici.
    `proxy.ts` now fetches `node:http` and `node:https` with `process.getBuiltinModule` when the
    proxy starts.
  - Effect, measured: the marginal import cost of `proxy.ts` fell from 16.0 ms to 3.3 ms, and the
    median hook process from 133–137 ms to 118–123 ms (`node -e 0` takes 51 ms; the hook work
    itself is 6–8 ms). A `cli.test.ts` case fails if the hook path loads `node:http` again.
- **Gate, as first printed.** Claude Code and OMP: "FAIL (cache hit lower)". Codex: "FAIL (input
  reduction below 30%; cache hit lower)".
- **Why criterion 3 fails.** Interpretation: the tokens layer 4 removes were mostly cache reads, so
  the hit rate falls arithmetically even when the bill falls.
  - Cache-weighted input (uncached ×1, cache reads ×0.1, Claude Code's cache writes ×2, the 1-hour
    write price that all of them used) fell on OMP −20.7% (its cost fell 20.5%) and Codex −12.2%,
    and rose 2.6% on Claude Code. At the 5-minute write price (×1.25) Claude Code's fell 7.0%.
- **Claude Code's cost.** Fact: its billed cost per token rises fivefold once a call's context
  passes roughly 90–100 k tokens; a bench turn makes about two calls, so per turn the blended rate
  roughly quadruples between 177 k and 192 k. Layer 4 kept 10 of the 18 filler turns below the step
  (the baseline kept 6), so its cost fell 40.0% at list price; at a flat per-token price it rose
  2.5%. Explained 2026-10-19: Haiku 5.5 bills prompts over 100k tokens at 5x every rate ($0.10 →
  $0.50/M input).
- **Decision (owner, 2026-10-17).** Criterion 3 is now "cache-weighted input below baseline"; the
  hit rate is still reported.
  - On these runs OMP passes (−20.7%), so layer 4 is on by default in OMP (`BRAIN_RENDER=off`
    disables it). Codex still fails criterion 1 (29.2% < 30%, against one valid baseline run), and
    Claude Code (one run per arm) the new criterion (+2.6%); both stay opt-in through the proxy.
- **Bench correction.** Fact: Claude Code's `total_cost_usd` is the session's running total, so a
  resumed call reports every earlier call too. Until 2026-10-17 the bench summed it; it now records
  each call's difference. The costs above use the last running total.

## 7. Provider pricing (2026-10-19)

E6 gated OMP on gpt-6-astra only. Anthropic prices changed the arithmetic for Claude models in OMP:
cache reads cost 0.05× input on Opus and Sonnet 5.5 (0.025× Fable 5.1, 0.1× Haiku 5.5) while 1-hour
cache writes, which OMP uses, cost 2×. An epoch re-writes the whole suffix after its first new stub,
and each elided token then saves one read per request, so it pays back only after about 40 × suffix ÷
elided requests.

- **Replay.** 14 days of OMP sessions (694 sessions, 51,373 requests), excluding the 17 that had
  elisions, re-priced per request with `RENDER_POLICY` replayed over the recorded tool outputs. The
  modeled baseline input cost was within 4% of the billed one. Input cost with layer 4:

  | Model | Change | Sessions dearer |
  |---|---|---|
  | claude-opus-5-5 | −3.1% | 26 / 73 (worst +27%) |
  | claude-sonnet-5-5 | +3.0% | 66 / 162 (worst +39%) |
  | gpt-6-astra | −15.8% | — |
  | gpt-6.1-sol | −19.0% | — |

  Both known biases favour layer 4: restores are not modeled, and OMP's own tool-output pruning
  already removes part of what layer 4 would elide.
- **Variants tried.** Larger steps stay near break-even on Anthropic with the same tails. Eliding
  only on requests that miss the cache anyway saves 6.9% on Opus with a perfect miss signal, but
  1.8% with time- or shrink-based detection and 0.6% on history rewrites alone; OMP's cache warmer
  (`providers.cacheWarming`, default `idle`) makes a time gap an unreliable miss signal.
- **Decision.** OMP skips layer 4 for models on the Anthropic Messages API (`BRAIN_RENDER=on` still
  forces it). OMP's catalog `cost.cacheWrite` cannot make this call: it lists 1.25× input for OpenAI
  models too, which bill no writes. `RENDER_POLICY` stays 30k/50k: `keep` 20k would save a further
  6 points on OpenAI models in the replay, but no E6 run has checked the detail probes there.
- **Cache TTL, measured, unchanged.** OMP's 1-hour writes beat 5-minute ones: 997 requests came 5
  minutes to 1 hour after the previous one, and at 5 minutes Opus input cost would rise 77% and
  Sonnet 20%.
