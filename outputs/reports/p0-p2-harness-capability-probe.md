# P0–P2 Harness Capability Probe Report (T-PhaseB)

- Session: `harness-probe` (rlm child `sub-a56a9d2f`, active session `40402c67bdcc`, session `01a007f9-c1dd-77ee-9ded-63088b447bf5`)
- Prime build: `v0.7.2` (`C:/Tools/prime-agent/package.json` version) / `PRIME_AGENT_BUILD_ID=v0.7.2-dirty`
- Model in this session: `deepseek/deepseek-v4-flash` (from session journal `model_change` record)
- Runtime env: `RLM_DEPTH=1`, `RLM_MAX_DEPTH=1`, daemon worker mode (`PRIME_AGENT_INTERNAL_DAEMON_WORKER=1`, recovery journal `C:\Users\assas\.prime\agent\daemon-workers\2245fa1c0e38\6d708b4c4041.recovery.jsonl`, supervisor pipe `\\.\pipe\prime-agent-daemon`)
- Report generated: 2026-08-16T00:32Z (local 2026-08-15 20:32)
- Scope: read-only probes in my own session; single repo write = this file. No repo code touched, no sibling touched, no global harness entries, test memory deleted.

## Harness capability matrix

| # | Capability | Classification | Evidence (one line) |
|---|---|---|---|
| 1 | persistent kernel | SUPPORTED + PROVEN | Structured dict `probe_state` stored turn 1, read back turn 3: deep equality True, same object id 1935902235776; backup JSON written to session_dir and re-read equal. |
| 2 | kernel across turns / compaction survival | PARTIAL: across-turns PROVEN; compaction survival NOT TESTED | State survived across multiple tool calls/turns in-session; no real compaction executed (`compact.status() -> scheduled=False`), so compaction survival not proven (see row 14). |
| 3 | named child spawn (recursion depth 1) | UNSUPPORTED CURRENT VERSION (config-limited) | `await rlm('probe grandchild', name='probe-grandchild')` raised `RuntimeError: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`; API surface exists (RLMSpawnHandle with rlm_child_id/name/session_dir/model) but daemon enforces depth limit. |
| 4 | child registry | SUPPORTED + PROVEN (empty registry + daemon-level registry) | `rlm.list_subagents()` returns `[]` on self before and after spawn attempt (no zombie entries); daemon registry proven indirectly: sibling `phase0a-audit2` visible in `agent_observe.list_agents()` with `rlmChildId=sub-e6ee62a6` under root. |
| 5 | retained child follow-up / child reuse | NOT TESTED (blocked) | No child could be created (depth limit), so no retained follow-up; contract verified in API (`agent_message.send(receiver_role='child', receiver_name=...)`, `rlm.list_subagents()`, `rlm.delete_subagent()`). |
| 6 | active steer | SUPPORTED + NOT YET PROVEN | A2A receive channel exists (`queuedCount=0` on my session at report time; no steer received during run); parent->child steer not exercised this run. |
| 7 | sibling visibility | SUPPORTED + PROVEN | `agent_observe.list_agents()` shows sibling `phase0a-audit2` (status model/streaming, busy, 487 messages); not messaged per instruction. |
| 8 | A2A child->parent | SUPPORTED + PROVEN | This report's `agent_message.send(..., receiver_role='parent')` is the live proof (probe 7); grandchild->parent variant NOT TESTED (no grandchild possible). |
| 9 | A2A parent->child | SUPPORTED + NOT YET PROVEN | `agent_message.send` signature supports `receiver_role='child'` + `receiver_name`; no child existed to receive, so unexecuted. |
| 10 | recursion depth-1 | UNSUPPORTED CURRENT VERSION (config-limited) | Daemon rejected depth-2 spawn with explicit `RLM_DEPTH=1, RLM_MAX_DEPTH=1` error; recursion is not configured in this install/runtime. |
| 11 | harness CRUD (child-local) | SUPPORTED + PROVEN | `rlm.harness.create_memory(..., global_=False)` -> HarnessEntry(scope=local); visible in `rlm.harness.overview()` (`memory: 1 [local:probe_local_memory]`); `delete_memory` -> True; absent from overview after. |
| 12 | refine availability | SUPPORTED + PROVEN (surface only) | `refine.run(instructions=None, global_=False)` -> `{"scheduled": True}` contract; `refine.status()` exists; NOT executed per task instruction (no real refinement run). |
| 13 | skills import | SUPPORTED + PROVEN | `agent_message`, `agent_observe`, `compact`, `goal`, `rlm_heartbeat` all importable and callable in kernel; signatures verified (`send`, `list_agents`, `status`, `get/create/complete`, `list/create/delete`). |
| 14 | compact API | SUPPORTED + PROVEN | `compact.status()` -> `{'tokens': 19991, 'context_window': 1000000, 'percent': 1.999, 'scheduled': False}`; actual compaction not invoked. |
| 15 | detach/reattach | NOT TESTED | Cannot detach self safely; indirect: session is daemon-supervised (worker env vars, recovery journal, supervisor named pipe, session leases `PRIME_AGENT_INTERNAL_SESSION_LEASES=1`), but I never detached/reattached in this run. |
| 16 | recovery | SUPPORTED + NOT YET PROVEN (indirect) | Daemon recovery journal exists at `daemon-workers/2245fa1c0e38/6d708b4c4041.recovery.jsonl` and daemon supervisor pipe is live; no forced daemon restart/recovery exercised, so honest status is indirect-only. |
| 17 | usage/context-tree attribution | UNAVAILABLE (root-vs-child); self-level SUPPORTED + PROVEN | No API exposed root-vs-child token attribution: `agent_observe.get_agent` keys have no token/usage/cost fields (messageCount only), `compact.status()` reports self totals, `goal.get()` budget fields all None (no goal set). |
| 18 | parallel fan-out = 2 | SUPPORTED + PROVEN (weak) | Root has two concurrent active children this run: `phase0a-audit2` (sub-e6ee62a6) and `harness-probe` (sub-a56a9d2f), both streaming, no fan-out error observed. |
| 19 | A2A grandchild->me | NOT TESTED (blocked) | Requires depth-2 child which the daemon refuses (row 3); child->parent A2A itself proven via row 8. |
| 20 | named child handle fields | SUPPORTED + PROVEN (surface) | RLMSpawnHandle dataclass exposes `rlm_child_id`, `name`, `session_dir`, `model`; RLMSubagent exposes registry fields incl. `status` in {running, completed, error} — verified from module source, spawn itself blocked. |

## Additional findings

- Amendment file read: `C:/Users/assas/Downloads/Second_Brain_P0-P2_Maximum_Prime_Agent_Harness_Amendment.md` — sec 2 (research refs), sec 28 Phase B (probe list), sec 35 capability matrix (classifications) confirmed the probe scope; the installed API matches the amendment's assumed primitives except recursion depth.
- Probe 1 cross-restart backup: `probe_state_backup.json` written to `C:\Users\assas\.prime\agent\session-artifacts\01a007b1-e5a2-77ab-98b9-8db15261aae4\sub-a56a9d2f\probe_state_backup.json`; kernel-restart survival not testable from inside the session (NOT TESTED).
- Active steer: none received during the run (checked `queuedCount=0` at report time). If a steer arrives later, that is additional evidence for row 6.

## Honest limitations

1. Recursion probes (3/5/8/9/10/19) are limited by `RLM_MAX_DEPTH=1`: the primitive exists (spawn + registry + delete + follow-up contract) but the current runtime configuration forbids depth-2 children, so those rows are config-limited UNSUPPORTED or NOT TESTED — not evidence that v0.7.2 lacks the feature entirely.
2. Detach/reattach, recovery-after-restart, compaction survival, and grandchild A2A cannot be safely self-probed from a child session; only indirect daemon artifacts were inspected.
3. Root-vs-child token attribution is not exposed by any API I could reach (`agent_observe`, `goal`, `compact`, harness state); only self-level totals (`compact.status()`) are available.
4. No BROKEN capability was found: every API that the runtime allowed me to exercise worked as documented. The only hard block is the recursion depth configuration.
