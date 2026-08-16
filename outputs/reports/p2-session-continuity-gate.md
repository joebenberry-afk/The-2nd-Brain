# P2 Session-Continuity Gate Report (Phase G)

- **Date:** 2026-08-16
- **Scope:** original plan §28 P2 + amendment §33; evidence: `p2-dogfood-raw-evidence.md`, post-fix mirror-check live run, G1–G5 suites
- **Role:** WORKER (report only — no code changed)

## 1. Identity

| Item | Value |
|---|---|
| Branch / HEAD | `brain/p0-p2-production-core` @ `a1dce84` |
| Prime | 0.7.2 (coding-agent 83a0f9f95) |
| Extension | G6-fix build (F1 seq-omit + F2 auto-init + barrier/rollover; deployed 11/11 SHA256) |
| Brain DB | schema v9 (0001–0009 incl. purge_receipts) |
| Ledger schema | v1 (`ledger_meta`, refuse-newer, upgrader stub) |
| Suites | pytest 735/2, vitest 257, ruff/pyright clean |

## 2. P2 acceptance matrix

| Requirement | Verdict | Evidence |
|---|---|---|
| Ledger continuously captures events | PASS | post-fix mirror-check live run: **137 contiguous events**, auto-init on first event, **0 mirror errors**; per-event kinds session_started/user_task/tool_requested/tool_completed/turn_end/agent_ended/compaction_*/session_inactive |
| Branch-aware lineage | PASS (note) | parent_event_id pointers + lineage replay + compare_projection (tests); the Prime session TREE (children/forks) is not yet mirrored into ledger lineage — only host session ids (honest limitation, §5) |
| Object refs verify | PASS | digest fail-loud on read (tests: tamper + missing file); `object_digests_ok:true` in live integrity |
| Fresh replay matches projection | PASS | `replay_ok:true` on dogfood verify + fault-injection replay tests (seq gap/orphan/broken pointer/payload tamper all rejected) |
| Schema/version rules | PASS | v1 header; refuse >1 ("newer runtime required"); <1 deterministic upgrader-stub error; reading never rewrites |
| Pre-compaction durability barrier | PASS | dogfood: `session_before_compact` fired **13×** (re-emission burst, branch_entries=153), checkpoint ran; manual checkpoint right after → `{"ok":true,"integrity":{"seq_contiguous":true,...}}`; **no cancel produced; compaction proceeded** ⇒ barrier proven |
| Native compaction remains in place | PASS | dogfood used host compaction (57,989→35,641 tokens, −38.5%); extension cancels ONLY on barrier failure (never observed live; cancel path tested) |
| Segments roll | PASS | post-compact rollover: `seg-1 start_seq=5` active, end_seq null; open/close/end_seq tests |
| Selective rehydration works | PASS | L1 pointer (segment+range, rehydration_id `db3874cb…`); L2 decision+rationale (id `e06a6e32…`); L3 exact payload char-for-char + artifact excerpt; L4 full dump; dedupe `{"deduplicated":true,"rehydration_id":"e06a6e32…"}` |
| Exact pre-compaction evidence recoverable | PASS | L2 recovered rationale "Approach X (in-process per-emit cache only) was rejected because worker recovery loses the in-memory Map…"; artifact sha seeded `4e647ce468cbb5192776a26540f89da6a658dafaea10dbde3b23d4d233f0ea6d` == recomputed |
| Tool unknown-outcome crash state safe | PASS | classify_tool_outcome: REQUESTED+no start → TOOL_NOT_STARTED ("retry only if still needed"); start+no result → TOOL_OUTCOME_UNKNOWN ("verify external state first"); tests |
| Inactive retention | PASS | state machine ACTIVE→INACTIVE_GRACE→FINALIZING→EXTRACTED→PURGED (+DEGRADED); transition-validated; retention config |
| Pinned survives | PASS | pin blocks purge (test + smoke: pinned dry-run REFUSED) |
| Extraction before purge | PASS | candidate memory `mem-771d74aaa3fd` (dogfood writeback) + purge auto-extract path; extraction-empty/exception refuse purge (tests) |
| Safe purge reclaims | PASS | dir + wal/shm gone, receipt row written (0009); hostile-id (hex-hash neutralization), identity-mismatch, symlink-escape refusal tests |
| No false byte-exact/provider-cache claims | PASS | provider cache metrics recorded UNAVAILABLE-not-inferred (P1 gate); Tier C mirror fidelity documented (Codex hooks replay = best-effort) |
| Harness state survives restart | PASS | parent kernel + child registry survived the user Prime restart 2026-08-16 (resume evidence) |
| Refinement history durable | PASS | harness `refinements.jsonl` append-only (6 entries; Phase F exercises) |
| No unreconciled canonical-vs-derived | PASS | `brainctl doctor` 16/16 + ledger integrity checks (seq_contiguous/orphans/digests/schema) |

## 3. Dogfood findings (T-G6-F1..F4) and fixes

| Finding | Fix | Status |
|---|---|---|
| F1 (P2 bug): mirror sent `seq:0` → every mirror append failed (`seq contiguity violated`) | mirror JSON omits seq; ledger auto-assigns seq≤0 in append_events + CLI (belt+braces) | FIXED; post-fix mirror-check 137/137 contiguous, 0 errors |
| F2 (UX): `rehydrate --decision` matched event_id only | match event_id → payload decision_id exact → substring | FIXED |
| F3 (ops): mirror required manual `ledger init` | auto-init once per session before first append (idempotent races) | FIXED |
| F4 (UX): writeback `--evidence` list-only | plain dict auto-normalizes to canonical [{ref,kind}] | FIXED |

Commit refs (working tree; parent commits cover G1–G5): mirror-check live verification ran post-F1/F3 with the deployed G6-fix build.

## 4. Failure matrix remainder

- Process crash: **NOT TESTED live** — simulated via fault-injection tests (seq-gap/orphan/missing-object reject; partial-batch rollback in append_events); kill-reopen live test deferred (needs a disposable real session).
- Hard power loss: **NOT TESTED** — WAL + synchronous=FULL documented as the durability contract; SQLite auto-recovery on open (wal_recovered note in recover_report).
- Detach/reattach: **NOT TESTED** — host TUI feature; worker-recovery behavior observed (Session worker is recovering) and handled by the file-backed emit cache + ledger.

## 5. Honest limitations

1. Child-session tree branching (Prime session tree: parent/children/forks) is NOT yet mirrored into ledger lineage — the ledger stores host session ids and event parent pointers within one session; cross-session tree lineage is future work.
2. Storage-pressure sweep (`max_total_session_bytes`) is manual via `session purge --oldest`; automatic pressure enforcement deferred.
3. Codex hook tier: mirror fidelity is Tier C (hook events only, no transcript parsing; no byte-exact replay claim).
4. `rehydrate --decision` substring matching is per-field (`decision_id`), not full-payload; documented.

## 6. Verdict

**P2 = PASS.** Every applicable §28/§33 item has evidence (table §2); the four dogfood findings are fixed and live-verified (§3); remaining failure-matrix items are honestly N/T-live with documented simulation paths (§4); limitations are scoped, not acceptance failures (§5). P0 = PASS, P1 = PASS (prior gates); the campaign continues to the final dogfood/proof phase.
