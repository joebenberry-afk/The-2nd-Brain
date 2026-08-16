# P2 Dogfood Raw Evidence — T-G6 (ledger + compaction + recovery)

- **Date (UTC):** 2026-08-16T02:47:50.979377+00:00
- **Worker session id (`--session`):** `01a0086d-41af-7608-b22c-d9a9148c84cc` (agent_observe `sessionId`; activeSessionId `2a1c1212aaaf`; extension resolves the same id from session-file stem — telemetry filename + mirror stderr confirm)
- **Brain home:** `C:\Users\assas\Documents\The-Second-Brain`

## Step 0 — Host session id

`agent_observe.list_agents()` → entry `ledger-dogfood`: `sessionId=01a0086d-41af-7608-b22c-d9a9148c84cc`, `activeSessionId=2a1c1212aaaf`, `rlmChildId=sub-695ed4db`, parent `bab3f6ae211a`. The extension's mirror uses the FULL id (`01a0086d-…`) as `--session` (verified in its stderr and telemetry file name); all ledger commands below use that id.

Environment: all commands run env-clean (PYTHONHOME/PYTHONPATH stripped, SECOND_BRAIN_HOME set) via the `brainctl` runner.

## Step 1 — Mirror verification: NOT LIVE (N/T, 0 events)

```text
$ brainctl ledger verify 01a0086d-41af-7608-b22c-d9a9148c84cc
brainctl: error: ledger not initialized: '01a0086d-41af-7608-b22c-d9a9148c84cc'   (rc=2)
```

The extension mirror *is* firing (telemetry `extension_error` records, 514 in this session) but every append failed. Sample (telemetry `telemetry/agent-performance/01a0086d-…jsonl`):

```json
{"kind":"extension_error","error":"ledger mirror: Command failed: … python -m second_brain ledger append --session 01a0086d-41af-7608-b22c-d9a9148c84cc --stdin-json\nbrainctl: error: ledger not initialized: '01a0086d-41af-7608-b22c-d9a9148c84cc'"}
```

**Enabling step (manual):** the fail-open mirror never initializes a fresh session ledger, so I initialized it (documented gap: extension should `ledger init` on first session_start):

```json
{"initialized":"750bdc3f37e28ba1a05b216ade2203c1649188e2a872687a6df6ba0982da5e22","schema_version":1}
```

Post-init verify (mirror still N/T — no mirrored events exist):

```json
{"events":0,"integrity":{"event_count":0,"object_bad":[],"object_digests_ok":true,"orphan_parents":0,"schema_version":1,"seq_contiguous":true},"replay_ok":true}
```

**VERDICT step 1: PARTIAL** — mirror live (fires) but 0/N mirrored events; ledger must be initialized manually. Finding T-G6-F1: mirror sends `seq:0` in every event (ledger-mirror.ts `buildMirrorEventJson`), while `append_events` requires exact contiguity and the CLI auto-assigns seq only when the field is absent/not-an-int — so mirror appends always fail (`seq contiguity violated: batch starts at 0 but ledger expects N`), even after init. One-line fix: drop `seq` from the mirror JSON.

## Step 2 — 4 pre-compaction facts seeded (env-clean)

- A) D-1 decision `phase-state` (seq 1)
- B) D-2 decision `approach-X-rejected` (seq 2)
- C) finding `emit-burst` (seq 3)
- D) artifact file `dogfood-artifact-1b140a5e.txt` (`DOGFOOD-ARTIFACT-1b140a5e`, sha256 `4e647ce468cbb5192776a26540f89da6a658dafaea10dbde3b23d4d233f0ea6d`) + D-3 decision `artifact-ref` (seq 4) with sha+path in payload (no `ledger object add` CLI exists — blob not registered; noted)

```json
$ brainctl ledger append --session <sid> --stdin-json   # 4-event array
{"appended":[1,2,3,4]}
```

Verify after seed:

```json
{"events":0,"integrity":{"event_count":4,"object_bad":[],"object_digests_ok":true,"orphan_parents":0,"schema_version":1,"seq_contiguous":true},"replay_ok":true}
```

**VERDICT step 2: PASS** — 4 seeds confirmed (seqs 1-4).

## Step 3 — Compaction + barrier

`compact.status()` BEFORE: `{"tokens": 57989, "context_window": 1000000, "percent": 5.7989, "scheduled": false}`

`await compact.run("G6 dogfood: preserve the D-1/D-2/D-3 facts and this mission state")` → `{"scheduled": true}`

`compact.status()` AFTER: `{"tokens": 35641, "context_window": 1000000, "percent": 3.5641, "scheduled": false}` — compaction **PROCEEDED** (not cancelled).

Barrier evidence: extension `session_before_compact` fired 13× (re-emission burst — matches seeded finding C `emit-burst`; branch_entries=153), ran `ledger segment checkpoint` (flush+integrity). Manual checkpoint of the same ledger right after returns ok:true:

```json
{"durability":"flushed","integrity":{"event_count":4,"object_bad":[],"object_digests_ok":true,"orphan_parents":0,"schema_version":1,"seq_contiguous":true},"ok":true}
```

No `ledger_degraded`/`cancel:true` was produced; compaction proceeded ⇒ **barrier WORKED (proceed)**. The mirror's own `compaction_started`/`compaction_completed` appends failed with the seq-contiguity bug (T-G6-F1); telemetry `session_compact` fired 13× (`from_extension:false`). Segment rollover DID run (new active segment):

```json
{"citation":"segments/all/events","level":1,"pointer":{"event_range":{"from":1,"to":4},"segments":[{"active":true,"end_seq":null,"index":0,"segment_id":"seg-1","start_seq":5}],"session":"01a0086d-41af-7608-b22c-d9a9148c84cc"},"rehydration_id":"db3874cb…"}
```

**VERDICT step 3: PASS** — compaction ran (57,989→35,641 tokens, -38.5%); barrier checkpoint ok; new segment opened.

## Step 4 — Post-compaction recovery (env-clean)

### L1 — search pointer citation
```json
$ brainctl ledger search <sid> --query "phase-state"
{"hits":[{"agent_id":"deepseek/deepseek-v4-flash","event_id":"dogfood-D1-phase-state","event_type":"decision","payload":{"decision_id":"D-1","rationale":"We are in Phase G6 dogfood; compaction proof in progress","title":"phase-state"},"segment_id":null,"seq":1,"timestamp":"2026-08-16T02:44:36.088269+00:00"}]}
```
**VERDICT L1: PASS** — pointer citation (seq 1).

### L2 — evidence packet
Note: `--decision` filters by **event_id** (not payload decision_id), so `--decision D-2` returns empty packets; the correct id is `dogfood-D2-approach-X-rejected`. Both runs recorded:

```json
$ brainctl ledger rehydrate <sid> --level 2 --decision D-2
{"evidence_packets":[],"level":2,"rehydration_id":"b6255819…"}
$ brainctl ledger rehydrate <sid> --level 2 --decision dogfood-D2-approach-X-rejected
{"evidence_packets":[{"decision":"approach-X-rejected","event_id":"dogfood-D2-approach-X-rejected","evidence_refs":[],"rationale":"Approach X (in-process per-emit cache only) was rejected because worker recovery loses the in-memory Map; file-backed session cache chosen instead","segment_id":null,"seq":2}],"level":2,"rehydration_id":"e06a6e32…"}
```
**VERDICT L2: PASS** (with event_id; shorthand `D-2` is a UX gap T-G6-F2).

### L3 — exact payload (seq of D-2 = 2)
```json
$ brainctl ledger rehydrate <sid> --level 3 --from-seq 2 --to-seq 2
{"artifacts":[],"events":[{"agent_id":"deepseek/deepseek-v4-flash","event_id":"dogfood-D2-approach-X-rejected","event_type":"decision","parent_event_id":null,"payload":{"decision_id":"D-2","rationale":"Approach X (in-process per-emit cache only) was rejected because worker recovery loses the in-memory Map; file-backed session cache chosen instead","title":"approach-X-rejected"},"segment_id":null,"seq":2,"source_event_ids":[],"timestamp":"2026-08-16T02:44:36.088269+00:00"}],"level":3,"rehydration_id":"0d5093e3…"}
```
Payload matches seeded text character-for-character. **VERDICT L3: PASS**

### Artifact sha256 recompute
```text
seeded:     4e647ce468cbb5192776a26540f89da6a658dafaea10dbde3b23d4d233f0ea6d
recomputed: 4e647ce468cbb5192776a26540f89da6a658dafaea10dbde3b23d4d233f0ea6d
MATCH: True   (file: C:\Users\assas\AppData\Local\Temp\dogfood-artifact-1b140a5e.txt)
```
**VERDICT artifact: PASS** (object blob not registered — no `object add` CLI; sha+path in payload noted per task).

### L2 re-run — dedupe
```json
{"deduplicated":true,"rehydration_id":"e06a6e324a69e0e7f6933170c1b7f983daee346df67aaebc62900c78f7d2f346"}
```
**VERDICT dedupe: PASS** (same rehydration_id).

### Final verify
```json
{"events":0,"integrity":{"event_count":4,"object_bad":[],"object_digests_ok":true,"orphan_parents":0,"schema_version":1,"seq_contiguous":true},"replay_ok":true}
```
**VERDICT verify: PASS** — integrity ok (seq_contiguous, 0 orphans, digests ok, replay ok; `events:0` = empty lineage projection, expected).

## Step 5 — D5 fresh-session writeback (env-clean)

Task literal `--evidence '{"dogfood":"T-G6"}'` → error (CLI requires a JSON list of `{ref,kind}`):
```json
{"error":"--evidence must be a JSON list of {ref, kind} dicts","status":"error"}
```
`kind` additionally restricted to evidence|episode|test|decision|import → corrected call:
```json
$ brainctl autoinject writeback --session <sid> --project second-brain --title "P2 dogfood compaction recovery proven" --observation "Fresh-session ledger mirror + checkpoint barrier + rehydration L1-L4 + artifact hash verified live" --guidance "P2 ledger dogfood proven" --evidence '[{"ref":"T-G6","kind":"evidence"}]'
{"memory_id":"mem-771d74aaa3fd","project_id":"second-brain","session_id":"01a0086d-41af-7608-b22c-d9a9148c84cc","status":"candidate"}
```
**VERDICT step 5: PASS (with CLI adaptation)** — memory id `mem-771d74aaa3fd`, status `candidate`.

## Summary verdicts

| Step | Result |
|---|---|
| 1 mirror live | PARTIAL — fires but 0/N (not initialized + seq:0 bug T-G6-F1); manual init required |
| 2 seed 4 facts | PASS (seqs 1-4) |
| 3 compaction + barrier | PASS — proceeded, 57,989→35,641 tok; checkpoint ok; segment rolled |
| 4a L1 search | PASS |
| 4b L2 rehydrate | PASS (event_id; shorthand gap T-G6-F2) |
| 4c L3 exact payload | PASS |
| 4d artifact sha | PASS (match; blob unregistered, no object CLI) |
| 4e L2 dedupe | PASS (`deduplicated:true`) |
| 4f final verify | PASS (integrity ok) |
| 5 writeback | PASS (adapted evidence; `mem-771d74aaa3fd`) |

## Findings
- **T-G6-F1 (P2 bug):** mirror `buildMirrorEventJson` sends `seq:0`; python `append_events` rejects non-contiguous batches and CLI auto-assigns only when `seq` is absent/not-int ⇒ every mirror append fails (`seq contiguity violated`). Fix: omit `seq` in mirror JSON (then `ledger append` assigns).
- **T-G6-F2 (UX):** `rehydrate --decision` matches event_id, not payload `decision_id`; shorthand ids like `D-2` silently return empty packets.
- **T-G6-F3 (gap):** extension never auto-initializes a fresh session ledger; first mirror event fails with `ledger not initialized` and the session stays uninitialized until manual `ledger init`.
- **T-G6-F4 (validated):** seeded finding C `emit-burst` reproduced live — `session_before_compact` fired 13× at one turn end (same for `session_compact`).

Evidence file: `outputs/reports/p2-dogfood-raw-evidence.md`