# LEDGER_EVIDENCE.md (freshly queried this review pass, direct read-only SQLite)

## Target session (prior qualification's compat session)

Internal session id: 479be484141e0eebe92e2b23734a86c5f01c601e14552cda503a973cd4f5477a
  (= sha256("01a02107-1a9d-73ef-8dfb-e8239b63dada"), independently
  recomputed this pass)
Ledger path: state/sessions/479be484.../ledger.sqlite

Query: `SELECT internal_session_id, obj_id, kind, residency_state,
access_count FROM session_vmem`

Real result (4 rows):
```
479be484... | obj-35c2cf10dbed | RESEARCH_RESULT   | EVICTED  | 2
479be484... | obj-03f92f636bee | RESEARCH_RESULT   | EVICTED  | 1
479be484... | obj-8bfd8a13efa8 | RESEARCH_RESULT   | EVICTED  | 1
479be484... | obj-802437fb8987 | TOOL_OBSERVATION  | RESIDENT | 1
```

`obj-802437fb8987` (TOOL_OBSERVATION) metadata confirmed non-empty with
real toolCallId/artifactRef in a prior independent check this same
campaign; not re-queried field-by-field in this specific pass (row
presence/kind/state/access_count were the focus here).

`obj-35c2cf10dbed`'s `access_count = 2` is consistent with the prior
report's claim of one real HOST_INTEGRATION `vmem resolve` access beyond
its initial admission (admission = access_count 1; one resolve call =
access_count 2).

## Cross-session isolation check (Phase G requirement)

Queried a SECOND, entirely different real session's ledger for
comparison: Pilot 5's session (01a02028-9f7c-758b-b275-fe8805cc22a6,
internal id 2740f197f26e7306d80e7d9567c0cb0b1e0cc2073cbf73783b9bdda151fdffdb).

Real result (2 rows):
```
2740f197... | obj-f6c3977ff500 | RESEARCH_RESULT
2740f197... | obj-1f9d8f6f6086 | TOOL_OBSERVATION
```

**Confirmed**: the two sessions' `internal_session_id` values are
different (`479be484...` vs `2740f197...`), and there is **zero overlap**
in `obj_id` values between the two sessions' rows. No cross-session
contamination observed.

## Note

This pass queried the ledger directly via sqlite3 (read-only connections
only; no INSERT/UPDATE/DELETE was ever issued). No ledger file was
mutated by this review.
