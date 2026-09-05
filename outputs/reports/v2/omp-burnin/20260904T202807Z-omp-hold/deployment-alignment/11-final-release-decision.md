# Final Release Decision — Post-Deployment-Fix Phase 22 Qualification

## Candidate identity

- Branch: `brain/v2-omp-qualification`
- Final SHA: `ad1384bf30088c5aa9bb9dec0bb5009c9a63c5d0`
- Remote/local match: confirmed pushed and equal
- OMP: `18.1.10` (`C:\Users\assas\.bun\bin\omp.exe`)
- Brain: `2.0.0-rc.1`, schema `21`
- Adapter build fingerprint: `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68`
  (unchanged — this pass changed deployment target and evidence/documentation
  only, never extension or runtime source)
- Doctor: **19/19 PASS**, `dirty=false`

## Deployment alignment

- Candidate extension source == deployed OMP extension: **PASS**, 0 differing
  files at the corrected auto-discovery path
  (`~/.omp/agent/extensions/second-brain`).
- Root-cause defect found and resolved (deployment-target only, no source
  edit): the canonical installer's documented default
  (`~/.prime/agent/extensions/second-brain`) is not auto-discovered by this
  OMP build; the real auto-discovery root is `~/.omp/agent/extensions/`.
  See `07-auto-discovery-path-defect.md`.
- Rollback proven byte-exact (`08-rollback-proof.md`).
- Provider smoke: **AVAILABLE** — multiple real, successful, non-429 provider
  calls after deployment fix.

## Phase 22 coverage (all ten gates)

| Gate | Result |
|---|---:|
| OMP sessions (50+) | 146 — PASS |
| Normal turns (100+) | 366 — PASS |
| Tool calls (25+) | 321 — PASS |
| Worker launches (20+) | 58 — PASS |
| Gate A terminal worker results (20+) | 26 — PASS |
| Gate B successful completions (20+) | 23 — PASS |
| Session compactions (10+) | 12 matched pairs — PASS |
| Clean restarts (10+) | 149 shutdown records / 140 sessions — PASS |
| Interrupted/recovery cases (3+) | 3 — PASS |
| Project switches (20+) | 24 — PASS |
| Conflicting controlled projects (2+) | 2 pairs (`p10-*` historical, `p22-*` fresh) — PASS |

**All ten Phase 22 minimum-coverage gates PASS on live, real, non-synthetic
telemetry.**

## Critical live regression

- AutoInject reaches OMP context: **PASS** (`active_state_delivery`,
  `brain_retrieval_attempt`, `brain_packet_delivered` observed this pass).
- Project isolation: **PASS** (`p22-project-gamma`/`p22-project-delta`
  alternating sentinels, zero cross-contamination, matching the historical
  `p10-*` proof).
- Worker context capsule: **PASS** (58 real handoffs this campaign).
- Worker result lifecycle: **PASS for the observed path** — see the P1
  caveat below.
- Routing: **PASS** (`omp_routing_decision`/`invocation`/`response` present
  throughout the corpus).
- Compaction continuity: **PASS** (4 fresh canary phrases each survived
  forced native compaction).
- Restart persistence: **PASS** (state persisted correctly across dozens of
  independent fresh `omp` process invocations this pass).
- Fail-open: **PASS** (unchanged from prior campaign evidence).
- Rollback: **PASS** (byte-exact, this pass).
- Provenance (build/project/session/retrieval/packet/worker/routing):
  **PASS** — every record above carries session/task/packet correlation.

## New defect found this pass (unresolved)

`09-worker-result-undercount-defect.md`: `recordAsyncWorkerCompletions` in
`brainstem/prime-extension/src/index.ts` only observes worker completions
delivered through an explicit `hub jobs`/`hub wait` `tool_result`. Real
completions delivered through OMP's auto-delivery `async-result` custom
message (when a job is not explicitly awaited before it settles) are
**silently invisible** to `omp_worker_child_result` telemetry and to the
durable Brain-side worker-result lifecycle record. This was directly
observed and reproduced twice this pass (3/20 and 2/5 real successful
completions captured before a tight-polling workaround was adopted to
reliably capture the rest).

This is a genuine, reproducible **P1 defect** in the extension's own
worker-result observation path. It was not fixed in this pass (the correct
fix requires a new observer hooking `message_end`/custom messages, which is
too invasive to implement and verify safely inside a qualification pass with
existing wiring tests asserting exact event shape/order/count).

## Release rule application

The release rule requires, in addition to numeric coverage:

```text
P0 open = 0
P1 open = 0
```

`P0 open = 0` holds. **`P1 open = 0` does not hold** — the worker-result
undercount defect above is a newly discovered, evidenced, unresolved P1.
Although every Phase 22 numeric gate independently passes using data
collected via a verified workaround, the underlying telemetry-capture defect
means the ordinary (non-workaround) production code path silently drops real
worker-result evidence. Tagging `v2.0.0` while a P1 defect in exactly this
qualification's own measurement path remains open would certify a system
whose self-reporting is known to be unreliable in a specific, reproduced
way.

## Decision

**RELEASE DECISION: HOLD.**

Blocking reason: one open P1 defect
(`09-worker-result-undercount-defect.md`) — worker-result telemetry
undercounts real completions delivered via OMP's auto-delivery path. Not a
capacity/coverage blocker: every Phase 22 numeric gate passes.

No `v2.0.0` tag was created. Qualified release SHA: **NONE**.

## Path to release

1. Implement the recommended fix in `09-worker-result-undercount-defect.md`
   (observe `message_end` custom `async-result` messages alongside the
   existing `hub` `tool_result` path).
2. Add a regression test reproducing the auto-delivery scenario and asserting
   `omp_worker_child_result` is recorded for it.
3. Re-run one bounded worker batch WITHOUT the tight-polling workaround to
   confirm 100% capture through the fixed default code path.
4. Re-evaluate the release gate; if P1 open returns to 0 and Phase 22
   coverage (already proven above) remains intact, `v2.0.0` may be tagged.
