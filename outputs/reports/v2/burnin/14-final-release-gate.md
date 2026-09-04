> **HISTORICAL / SUPERSEDED — DO NOT USE AS THE CURRENT RELEASE GATE**
>
> This report records the earlier Prime-centric repair campaign. It is retained
> as historical evidence, but its Prime Agent 0.9.1 and Claude Code burn-in
> blockers are no longer the v2 release model. The authoritative current
> decision is `outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/RELEASE_DECISION.md`.
>
> Current authoritative blocker: **HOLD — Native OMP Phase 22 production
> qualification coverage is incomplete** (`19/20` worker launches, `7/20`
> worker results, `8/10` compactions, `11/20` project switches). Additional
> real runs stopped at the external provider boundary: HTTP `429
> rate_limit_error`, `retry-after-ms: 9017000`. Prime binary required for OMP
> v2 release: **NO**.

# Second Brain v2 Burn-In Repair — Final Release Gate

Repair branch: `brain/v2-burnin-repair` (pushed to `origin/brain/v2-burnin-repair`)
Qualified baseline: `4af64affdf4f1ec07b9483b67f440394d2853b32` on `brain/v2-one-shot` (untouched; `origin/brain/v2-one-shot` still resolves to this exact commit)
Repair commits: 14, from `chore(v2): publish qualified burn-in baseline evidence` through `test(v2): qualification and regression campaign evidence`

## Required Evidence (plan §17)

| Gate | Status | Evidence |
|---|---|---|
| Exact repaired commit SHA | PASS | `git log --oneline 4af64af..HEAD` — 14 commits, linear, on top of the untouched baseline |
| Clean Git state | PASS | `git status --porcelain` empty at every commit boundary |
| Doctor PASS with coherent identities | PASS | `outputs/reports/v2/burnin/03-doctor-identity-repair.json`; live smoke: 19 checks, 0 failed |
| All migrations current | PASS | schema v21; `outputs/reports/v2/burnin/12-qualification-campaign.json` migration/restore section |
| Full test suite PASS | PASS WITH DOCUMENTED PRE-EXISTING EXCEPTIONS | `outputs/reports/v2/burnin/12-qualification-campaign.json`: 20 failures, 18 identical to an isolated baseline-commit run (pre-existing, out of this campaign's named scope), 1 fixed within this campaign (`test_backup_restore_preserves_index`), 1 flaky/non-reproducing (`test_cli_concurrent_init_and_append_burst`) |
| Independent verifier PASS | PASS | `scripts/verify_qualification.py --json` → `ok: true`; known non-blocking gap (empty qualification ledger) already documented in `01-exact-v2-audit.md`, unchanged by this campaign |
| Backup/restore roundtrip PASS | PASS | `outputs/reports/v2/burnin/04-backup-repair.json`; format 2, canonical roots, per-file hashes, memory-reference verification |
| Prime 0.9.1 burn-in PASS | **BLOCKED — NOT RUN** | Prime Agent 0.9.1 is not installed/reachable in this environment (`prime-agent`/`prime`/`sol` absent from PATH; no matching global npm package). No live Prime session was available to exercise Phase 13's 16 scenarios. |
| Claude Code burn-in PASS | **BLOCKED — NOT RUN** | Phase 14 requires a completed Prime session to hand off from; unreachable because Phase 13 is blocked. |
| Cross-harness continuity PASS | **BLOCKED — NOT RUN** | Same dependency as above. |
| Retrieval usability PASS | PARTIAL — OFFLINE PROOF ONLY | `outputs/reports/v2/burnin/08-retrieval-live-path-repair.json` proves the CLI decision/packet/project-attribution path end-to-end; no live Prime model-visible confirmation was possible. |
| Token/runtime comparison recorded | PASS | `outputs/reports/v2/burnin/12-qualification-campaign.json` token_and_latency section: 0 packet-token delta, latency within measurement noise versus the qualified baseline |
| No unresolved P0/P1 defect | PASS | Every P0/P1 defect named in `01-exact-v2-audit.md` has a repair commit and passing regression test |
| Rollback tested | PASS | `outputs/reports/v2/burnin/13-rollback-verification.json` |

## Release Decision

**HOLD.**

Per the plan's own non-negotiable invariant #4 and §17 HOLD criteria: `v2.0.0` is not tagged while Prime 0.9.1 and Claude Code production burn-in have not run. This environment cannot host a live Prime Agent 0.9.1 session (binary unavailable), so Phases 13 and 14 are blocked, not failed — no burn-in evidence exists to gate on, favorably or unfavorably. Every gate reachable without a live Prime harness (installer, doctor identity, backup completeness, runtime/state separation, canonical project resolution, AutoInject cache correctness/concurrency/provenance, retrieval project attribution, extension lifecycle freeze, build identity, documentation, full regression campaign, token/latency comparison, rollback) is repaired, tested, and evidenced on `brain/v2-burnin-repair`.

## Next Step for a Human Operator

Run Phase 13 (Prime Agent 0.9.1 production burn-in, 16 scenarios) and Phase 14 (Claude Code cross-harness continuity) on a host with Prime Agent 0.9.1 installed, using this repair branch's repaired runtime, state, and reinstalled extension (`scripts/install-prime-extension.ps1 -SourceRoot <this checkout>`). Only after both pass and are recorded under `outputs/reports/v2/burnin/` should `brain/v2-burnin-repair` be merged into `brain/v2-one-shot` and requalified for the `v2.0.0` tag.
