# P0–P2 Upstream Reference Map (plan §26)

Every reference cited in plan sections 1–4, mapped to: upstream project, exact
path/URL, the feature we adapted, our local file(s), what was copied
conceptually, and what was deliberately NOT copied.

**Statement:** no verbatim upstream code was copied into this repository —
all adaptations are invariants/concepts reimplemented to our conventions
(see "copied conceptually" vs "not copied" per row). Licenses therefore
impose no verbatim-copy obligations; attribution lives in this map.

## DeepSeek Harness (github.com/deepseek-ai/deepseek-harness)

| Upstream path (exact) | Feature adapted | Our local file(s) | Copied conceptually | NOT copied |
|---|---|---|---|---|
| `blob/47f9438…/.agents/notes/implemented/architecture/2026-07-05-reconstructable-requests.md` | reconstructable request framing (stable prefix vs changing tail) | `src/second_brain/contracts.py` (RequestEpoch/RequestFingerprint), `p1-orchestration-cache-gate.md` §4 | the invariant: keep the model-visible prefix stable; detect first divergence | their exact request schema / adapter code |
| `packages/compaction/compaction/README.md` | compaction-as-summary + kept-tail semantics | `ledger.py` segments + `ledger-mirror.ts` compaction events; T-G4 barrier | compaction boundaries are ledger events; never compact-unprotected | their summarization implementation |
| `packages/context/tmux-context/src/index.ts` | out-of-band context carriers (kernel/files for bulky state) | policy `driver-orchestration.md` §3 Tier 0/1; artifacts.py blobs | large intermediates live outside model context | tmux protocol code |
| `packages/core/session/README.md` | session persistence semantics (append, reload, lineage) | `ledger.py` (append-only events, parent pointers), `p2-session-continuity-gate.md` | append-only truth + derived projections | their storage engine |
| `packages/preset/agent-presets/README.md` | role presets (orchestrator/worker) | `driver-orchestrator.ts` resolveAgentRole + policies | deterministic role classification by model | their preset format |
| `packages/subagent/subagent/README.md` | child lifecycle (named spawn, reuse, registry) | campaign orchestration (retained child reuse, `rlm.list_subagents()`), Phase D2 report | reuse retained children; follow-up protocol | their spawn plumbing |
| `packages/subagent/tool-subagent-control/README.md` | tool surface control for orchestrators | `orchestrator-guard.ts` (Sol tool block) | driver tool minimization | their guard implementation |
| `packages/subagent/tool-subagent-report/README.md` | concise worker report contract | policy §5 worker result contract | structured evidence, no giant transcripts | their report schema |
| `blob/master/.agents/notes/implemented/architecture/2026-08-10-session-log-version-mechanism.md` | session-log schema versioning | `ledger.py` LEDGER_SCHEMA_VERSION + §14 rules | versioned headers, refuse-newer, ordered upgraders | their log format |
| `packages/attachment/attachment-local/src/store.ts` | content-addressed local attachment store | `ledger.py` object_refs + `state/sessions/<id>/objects/<sha256>` | content addressing + digest-verified reads | their store API |
| `packages/compaction/compaction-tool-result-pruner/README.md` | pruned tool results with artifact recovery | `artifacts.py` (RTD blobs + distilled preview) | keep raw bytes recoverable, context small | their pruning logic |
| `packages/core/agent-loop/tests/invariant.spec.ts` | deterministic invariant testing of agent loops | `tests/test_ledger.py` replay rejection suite | fault-injection test matrix (gap/orphan/tamper) | their test harness |
| `packages/core/session/src/repair.ts` | session repair/recovery on resume | `ledger.py` recover_report() + `classify_tool_outcome` | recoverability must be explicit and verifiable | their repair algorithm |
| `packages/session/session-persistence-sqlite/README.md` | SQLite-backed session persistence (WAL) | `ledger.py` (WAL, synchronous=FULL, foreign_keys=ON) | durability pragmas + atomic migration framework | their schema |

## Pi mono (github.com/badlogic/pi-mono)

| Upstream path | Feature adapted | Our local files | Copied conceptually | NOT copied |
|---|---|---|---|---|
| repo root (concept) | Pi/Pi Agent extension mechanism: custom state vs custom_message | `prime-extension/src/index.ts` + `ledger-mirror.ts` (mirror events), amendment §2.5 mapping | custom (non-model-visible) state vs custom_message (model-visible) split | pi-mono runtime code |

## Prime Agent / Codex (OpenAI developer docs)

| URL | Feature adapted | Our local files | Copied conceptually | NOT copied |
|---|---|---|---|---|
| developers.openai.com/codex/hooks | hook event model (SessionStart/UserPromptSubmit/SubagentStart/Stop/SessionEnd) | `brainstem/codex-hooks/*`, `cli.py codex-shadow` | event names + stdin/stdout JSON contract; verified against installed 0.147.0 plugin manifests | their hook examples |
| developers.openai.com/codex/app-server | app-server item tier (thread/inject_items) | (documented as P3+ option in `p1-orchestration-cache-gate.md` §4) | existence of a persistent injection tier | their API — NOT implemented |
| developers.openai.com/codex/subagents | subagent invocation model | campaign delegation (policy Tier 4/5) | subagent as a first-class unit | their CLI plumbing |

## Provider cache documentation

| URL | Feature adapted | Our local files | Copied conceptually | NOT copied |
|---|---|---|---|---|
| api-docs.deepseek.com/guides/kv_cache | KV-cache hit semantics (prefix-sensitive) | `contracts.py` RequestFingerprint + `p1-orchestration-cache-gate.md` §4 | prefix stability drives cache hits | their API fields (UNAVAILABLE on this runtime) |
| developers.openai.com/api/docs/guides/latest-model | caching field semantics (cached_tokens) | economics report §UNAVAILABLE-not-inferred | awareness that fields exist | their API |
| platform.claude.com/docs/en/build-with-claude/prompt-caching + cache-diagnostics + tool-use-with-prompt-caching | prompt caching + diagnostics concepts | same (documented as unavailable on Prime 0.7.2) | diagnostics-driven verification | their API |

**Not copied anywhere:** verbatim source; all adaptations are invariants
(append-only truth, stable prefixes, content addressing, fail-open,
recovery-first) reimplemented to Second Brain conventions.
