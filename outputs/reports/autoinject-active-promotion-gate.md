# AutoInject ACTIVE Promotion Gate — Evidence

Date: 2026-08-16. Mode promoted SHADOW -> ACTIVE via live flip switch
(`config/autoinject.toml [autoinject] mode = "active"`), existing configuration
only — no rollout subsystem. Rollback point: commit `dca051e` (repaired shadow
baseline). Rollback action: set `mode = "shadow"` (proven live, see gate 13).

Canary session: `01a0091a-c6d8-72c4-907f-8321e6dddfd5` (deepseek-v4-flash,
fresh Prime session under ACTIVE). Telemetry:
`telemetry/agent-performance/01a0091a-...jsonl`. Ledger:
`state/sessions/9db47e25.../ledger.sqlite`.

## Gates (13/13 PASS)

1. **Auto-load, no manual brainctl** — session_start == exactly 1
   (05:45:45.530Z); first brain_packet_delivered 05:45:45.871Z; no Brain CLI
   run by the agent before the first injected packet.
2. **Project = second-brain throughout** — all retrieval records
   project_id="second-brain"; ledger sessions.project_id="second-brain".
3. **First relevant prompt triggers AutoInject** — task_sha256 of the canary
   prompt reproduced (sha256 of prompt[:4000]; AUTOINJECT_MAX_TASK_ARG_CHARS).
4. **[BRAIN_CONTEXT_DELTA v1] in model context** — custom messages
   (customType brain.autoinject.packet) received: pkt-09140130cdcf638b
   (2 items), pkt-179431e983f87b26 (5 items); packet text sha256-matches
   telemetry canonical_packet_hash. Item quoted verbatim by the canary
   (mem-b67de5057f76@2, PYTHONHOME pollution) and cross-checked.
5. **model_visible=true only for real injection** — active-mode shadow_decision
   records: model_visible=true + handler_returned_message=true; shadow-run
   record: model_visible=false + handler_returned_message=false. Python-side
   brain_packet_delivered records carry model_visible=false (documented
   conservative: host-side visibility is recorded by the extension records).
6. **No pizza memory** — mem-cd1f9e0cdac4 (archived) absent from both packets
   and deliveries; deliveries rows = exactly the 7 quoted items.
7. **No duplicate injection** — 2 delivered rows, 2 distinct packet_ids, 1:1;
   one custom message per wave (cross-run re-emit = cache_hit, emit_index=2).
8. **Token cost recorded** — packet_tokens 362 / 633.
9. **Budget** — 362, 633 <= target 800 <= hard cap 2000.
10. **Specific item reported** — quoted item title/version matches deliveries
    row (del-a47ab809849c7b3975dbb1ab) and memories table.
11. **Ledger contiguous, error-free** — extension_error == 0; seq contiguous.
12. **Replay/integrity** — `ledger verify`: rc=0, replay_ok=true,
    seq_contiguous=true, orphan_parents=0, object_bad=[].
13. **SHADOW rollback proven** — live flip active->shadow: next run received no
    brain message, decision record mode=shadow/model_visible=false; flipped
    back to active (final dogfood state).

## Known conservative semantics (no action taken)

- Python `brain_packet_delivered` telemetry carries `model_visible: false`
  unconditionally (the Python pipeline prepares deliveries; host-side
  visibility is recorded on the extension's shadow_decision records). A
  future pass may make the Python record mode-aware.
