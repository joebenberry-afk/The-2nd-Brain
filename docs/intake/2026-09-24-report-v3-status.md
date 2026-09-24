---
date: 2026-09-24
type: report
authority: evidence
status: V3 core complete in code and cloud-verified; live OMP qualification NOT_RUN
scope: v3-status
supersedes: none-additive
superseded-by: none
promoted:
---

# Second Brain V3 — status against the requirements (VAL-05 matrix)

Branch `claude/new-session-nro2r6`, built from `brain/v3-s2`. Design:
`2026-09-24-plan-v3-agent-native-redesign.md` (owner decisions O1–O7, D8 and the harness-focus
rule). Evidence is cloud-only (Linux container, no OMP): **everything that needs a live OMP host
is NOT_RUN**, and nothing here claims it.

## What exists

| Part | Where | Verified by |
|---|---|---|
| Canonical records (one Markdown file per fact; private ones in ignored `records/private/`) | `src/second_brain/kb/records.py`, `records/` (116 converted + 4 new) | `tests/test_kb_records.py` |
| Project identity and scope (manifest paths, git remote) | `kb/projects.py` | `test_kb_records.py`, `test_kb_security.py` |
| Derived index, pull search with relevance floor, guarded writes (add/edit/promote/supersede/retire/conflict) | `kb/index.py`, `kb/commands_index.py` | `tests/test_kb_index.py` |
| Views: session brief (≤600 tokens) and correction table (≤80 tokens) | `kb/views.py` | `tests/test_kb_views.py` |
| Legacy conversion and native-memory import | `kb/convert.py` | `test_kb_views.py` (real legacy schema) |
| Capture → inbox → accept/reject; stale evidence | `kb/capture.py`, `kb/commands_capture.py` | `tests/test_kb_capture.py` |
| Sync (git) and share (domain tags) | `kb/sync.py` | `tests/test_kb_sync.py` (real repositories) |
| Doctor (integrity, views, privacy, sizes, runtime) | `kb/doctor.py` | `tests/test_kb_doctor.py` |
| OMP adapter (standalone, version-tolerant) + installer/rollback | `brainstem/omp-v3/`, `scripts/*omp-v3.ps1` | `brainstem/prime-extension/tests/omp-v3.test.ts` |
| Claude Code adapter (frozen, not extended) | `kb/hooks.py`, `brainstem/adapters/claude-code-v3/` | `tests/test_kb_hooks.py` |
| Security fixtures | — | `tests/test_kb_security.py` |
| Fault fixtures | — | `tests/test_kb_faults.py` |
| Skill export, duplicate review | `kb/skills_export.py`, `kb/consolidate.py` | `tests/test_kb_skills.py` |
| Live comparison harness (`--arms native,v3`) | `scripts/v3_value_suite.py` | `tests/test_v3_value_suite.py` (home preparation only) |
| CI | `.github/workflows/ci.yml` | green on every completed run of this branch |

Test counts at the end of this work: V3 core and value-suite unit tests 324 passed; OMP
extension suite 714 passed earlier in the session (the V3 extension's own tests since then: 9
passed). Legacy full suite on this branch (MEM-03a state): 2273 passed; the failures are the
documented Windows-only/cloud-only cases (see `CLAUDE.md`).

## Measured (cloud)

| Measure | Result |
|---|---|
| Legacy → V3 conversion | 116 records, 0 errors (91 candidate, 20 current, 5 retracted) |
| Owner-approved currentness sweep | 6 retired with history kept, 3 retyped; brief 483 → 380 tokens, sectioned |
| `brain q` on the frozen S2 memory cases | dev 13/15, held-out 7/8 in the top 3; 2 of the 3 misses ask for the retired 2-worker-cap policy (correct current-state behaviour); ~1.5 lines per query |
| Per-prompt Brain additions in V3 | 0 by construction (push only at session start, compaction and tool failure) |
| Claude Code hook, fresh process | 62–67 ms (legacy hook 148–165 ms; the difference was the legacy import graph, not Python) |
| Runtime choice (same FTS workload) | Python 27–28 ms, Go 22–29 ms, Bun compiled 54–60 ms → Python kept (O7) |
| `brain doctor` on the real home | 0 errors; 1 warning: 23 evidence files that exist only on the Windows machine |

## Requirement matrix

MET = implemented and verified by the named tests; PARTIAL = implemented in part (gap named);
DEFERRED = held behind a measured trigger by owner decision; NOT_RUN = needs the live host.

| Req | Status | Evidence / gap |
|---|---|---|
| ARCH-01 no host control | MET (code) · live NOT_RUN | adapters only add context; other events add nothing (`test_kb_hooks`, `omp-v3.test.ts`) |
| ARCH-02 stable contracts | MET (code) | harness-neutral core; OMP adapter degrades on host shape changes (`omp-v3.test.ts`) |
| ARCH-03 bounded failure | MET (fixtures) | corrupt/deleted index rebuilds, locked index → explicit error (exit 2), corrupt views fall back, adapters fail open (`test_kb_faults`) |
| ARCH-04 no new infrastructure | MET | stdlib + SQLite + git; no daemon, server, GPU or model call |
| PERF-01 no-benefit neutrality | MET by design · live NOT_RUN | zero per-prompt additions; one bounded brief per session (O2) |
| PERF-02 latency | PARTIAL · live NOT_RUN | 62–67 ms per hook process (cloud); OMP adapter reads files in-process (not timed live) |
| PERF-03 all-in accounting | PARTIAL | per-push telemetry (tokens, ms); V3 arm in the value suite; campaign NOT_RUN |
| PERF-04 measured bottlenecks | MET | E01 + import profiling + runtime benchmark |
| MEM-01 canonical vs derived | MET | files canonical; index/views rebuild (`test_kb_index` derived-index test) |
| MEM-02 typed records | MET | 7 types, evidence, bi-temporal fields, claimed vs effective grade |
| MEM-03 current state / as-of | MET | explicit supersession, as-of search, orchestration-removal fixture; applied to the live corpus |
| MEM-04 contradictions visible | MET | `brain conflict`: both visible, marked, never pushed; weaker replacement refused |
| MEM-05 durability | MET (fixtures) | interrupted atomic write keeps the old record; crash between supersede writes detected by doctor (`test_kb_faults`) |
| RET-01 scope before disclosure | MET | `test_kb_security` (views never cross projects; pull scope) |
| RET-02 dilution | MET (legacy push path) | V3 has no per-prompt query; pull queries are agent-written |
| RET-03 semantic | DEFERRED (D2) | E02: lexical at the ceiling; add sqlite-vec when a paraphrase class fails |
| RET-04 embedding versions | DEFERRED | only with an encoder |
| RET-05 ranking/packing | MET | BM25 field weights, relative floor, top-3 pull, budgeted brief |
| RET-06 source catalogue | PARTIAL · NOT_RUN | `locator` records + brief section; held-out SZ-tools/BasicUpscaler tasks need those projects live |
| CTX-01 fidelity classes | PARTIAL | brief/correction formats; no multi-round compaction fixture |
| CTX-02 recipient/epoch | MET (code) | per-session brief, re-brief after compaction; child sessions get their own |
| CTX-03 recovery without control | MET (code) · live NOT_RUN | re-brief after `session_before_compact`; never vetoes |
| CTX-04 minimal, cache-conscious | MET | append-only, stable brief text, hard budgets |
| REU-01 dependency graph | DEFERRED (D6) | |
| REU-02 freshness | MET | `path@blob` stale-evidence check (`review`, `doctor`) |
| REU-03 no side-effect reuse | MET | nothing is cached or replayed |
| REU-04 versioned caches | DEFERRED (D6) | |
| SKL-01..03 portable skills | MET (code) · native discovery live NOT_RUN | `brain export-skill`: current TESTED procedures → Agent Skills `SKILL.md` with applicability, evidence and an advisory footer (`test_kb_skills`) |
| SKL-04 corrections | MET · live NOT_RUN | failure→fix capture, tested corrections pushed on matching errors |
| LRN-01 consolidation | MET | inbox, dedupe, supersede/retire/conflict; `review` lists near-duplicates (live corpus: 2 genuine pairs) |
| LRN-02 evidence checking | MET | promote needs evidence; stale evidence reported |
| LRN-03 learned selectors | DEFERRED | |
| LRN-04 bounded maintenance | MET | 5 MB event cap, 14-day retention, no background work |
| RES-01 budgets by category | MET | doctor sizes per category |
| RES-02 retention/deletion | PARTIAL | event retention; record deletion keeps history by design |
| RES-03 worktree cleanup | DEFERRED | not a memory job |
| RES-04 16 GB envelope | NOT_RUN | footprint is small (records 157 KB, index 516 KB) but unmeasured on the laptop |
| SEC-01 no authority laundering | MET | no VERIFIED minting, edits cannot change standing, promotions carry `promoted_by` |
| SEC-02 injection/metadata | MET (fixtures) | hostile titles, advisory framing, scrubbed capture (`test_kb_security`, `test_kb_capture`) |
| SEC-03 explicit sharing | MET | `share` is the only widening; private records excluded by pathspec and ignore rule |
| SEC-04 integrity ≠ authentication | MET (labelled) | promotion is not authentication; documented |
| PORT-01 real hosts | NOT_RUN | OMP only in focus (owner); adapters exist |
| PORT-02 runtime identity | MET | `brain doctor` runtime section |
| PORT-03 no protocol overreach | MET | CLI + host events; no resident tool schemas |
| PORT-04 upgrade/recovery | PARTIAL | converter idempotent, legacy untouched, one-command rollback; rehearsal on Windows NOT_RUN |
| VAL-01..04 | PARTIAL | CI gates, frozen case sets, V3 arm ready; live campaign NOT_RUN |
| VAL-05 this matrix | MET | |

## What remains (owner machine)

1. Install and verify per `brainstem/omp-v3/README.md` §1–2.
2. Run the live comparison (§3) — this is the qualification for PERF-01/02/03, SKL-04, CTX-03,
   PORT-01 and VAL-01..04.
3. After it passes and daily use shows no rollback: retire the legacy runtime (§5).

Remaining PARTIAL items (PERF-02/03, RET-06, CTX-01, RES-02, PORT-04, VAL-01..04) close with the
live run on the owner machine; nothing further is buildable without it.
