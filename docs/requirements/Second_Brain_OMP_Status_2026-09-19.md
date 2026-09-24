# Second Brain in OMP — status and usable scope (2026-09-19)

This document states what is installed, what was verified on 2026-09-19, what is
deliberately bounded, and how to use the Brain day to day. It is a status note,
not a release certification.

## Installed and frozen subject

| Component | Identity |
|---|---|
| OMP host | `omp/18.2.6` (`C:/Users/assas/.bun/bin/omp.exe`) |
| Extension | `C:/Users/assas/.omp/agent/extensions/second-brain` (24 modules + `types/prime.d.ts`); byte-snapshot in `outputs/reports/storage-cleanup-20260918/extension-snapshot/` |
| Brain runtime | `C:/Users/assas/Documents/The-Second-Brain/.worktrees/qualified-v2` (editable install used by `.venv`) |
| Commit | `aee82ab` (adds the ledger v1→v2 prefix recovery and the deployed `deepseek-flash` driver classification) |
| Source fingerprint | `92716ec400c806182ddc866f257572ff8ed87bb23504fac59ca93003df12b9fd` |
| Configuration fingerprint | `f5da285e8046fc188c9c26ceccbe7fde19ff4c94ae68abb457d87291eb12b0ac` |
| State | `SECOND_BRAIN_HOME=C:\Users\assas\Documents\The-Second-Brain`, schema v24, `db/brain.sqlite` |

## Verified on this subject (2026-09-19)

- Health: `doctor` 20/20 checks pass (home, layout, config, version, interpreter, sqlite, identity coherence, migrations v24, build identity, tools).
- Static gates: `ruff check src tests` clean, `pyright` 0 errors/0 warnings; extension `eslint` clean, `tsc --noEmit` clean, vitest 730 passed / 32 files; full Python suite 2,134 tests / 0 failures / 0 errors / 1 platform skip (POSIX ACL test on Windows).
- Ledger: live session ledger append/verify (`hash_chain_ok`, `seq_contiguous`, `replay_ok`) and the pre-compaction durability barrier (`ledger segment checkpoint` → `durability: flushed`).
- Memory: `remember` → `recall` round trip with evidence freshness (`[VERIFIED_CURRENT]`); archived memories discoverable via history/explanation while excluded from injection.
- Retrieval: deterministic bounded explanations (`replay_complete=true`, identical `selection_steps` hash across runs); need-cost ROI abstention behaves as specified.
- Injection: AutoInject `mode=active` decisions recorded and `active_state_delivery` confirmed as model-visible.
- Context paging: evicted observation recovered exactly through `vmem resolve` (artifact reference).
- Isolation: a memory scoped to the `brain-pilot-demo` project does not appear in `second-brain` retrieval, and vice versa (`NO_INJECTION WRONG_PROJECT` at the Brain side).
- Workers: read-only native workers are admitted, receive a bounded context packet, and their results are delivered by OMP; mutating workers are refused with a typed reason (see below).
- Gate evidence: `outputs/reports/omp-current-evidence-20260919/` — 23 source-bound refs plus real-host observations; and `outputs/reports/omp-qualification-assembly-20260919/` — manifest + candidate records adjudicated by the project's strict verifier: manifest PASS with zero errors, `proven_count=8`, `coverage_complete_count=8` (8 of 12 canonical requirements, 48 of 74 gates), overall verdict HOLD for the four outstanding requirements.

## Deliberate boundaries

1. **Mutating delegated edits are refused on this host.** Stock OMP 18.2.6 exposes only
   `getAsyncJobSnapshot()`; the private per-attempt lifecycle API the Brain requires for
   writer-ownership settlement (`observeAsyncJobLifecycle`) is not present. The extension
   refuses with `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` rather than assume
   settlement. Do edits inline, or run on a host that exposes that API.

   > Host-version note (2026-09-21): the installed host is now **OMP 18.2.8**, and the
   > settlement surface is still absent there — so this boundary still holds, by measurement
   > rather than by version. The current host's capability set is recorded in
   > `../../outputs/reports/host-bridge-v1-20260921/REHEARSAL.md`, and the retired host patch
   > is documented in the qualified-v2 worktree at
   > `.worktrees/qualified-v2/docs/integrations/omp-host-patch-2026-09-19-production/`,
   > tracked on branch `brain/omp-native-6172a18-20260911` (recovery route in `../README.md`).
2. **Read-only worker accounting is approximate.** A read-only admission that runs longer
   than the 300-second lease is reaped as `FAILED/lease_expired` while the worker keeps
   running; the result is still delivered by OMP, and the extension records
   `omp_worker_admission_bypassed`.

   > Correction (2026-09-21, from an independent read of the code — baseline-suite instance 3).
   > **Confirmed**: the reap lives in the qualified worktree's `worker_protocol.py`
   > (`reap()` at :1950, marking the row `FAILED/lease_expired` at :2075-2083 against a UTC
   > wall-clock comparison), it **cancels nothing** — no process kill, no host notification —
   > and it runs from event-driven callers (`cli.py:3940` heartbeat, `:3983` p4 pulse,
   > `:4708` worker-plane), not from a wall-clock timer. Delivery survival is also confirmed:
   > the late receipt is rejected as `INVALID_TRANSITION` on the already-terminal row
   > (`worker_protocol.py:1557-1571`) while the host has already delivered the result.
   > **UNVERIFIED**: the `omp_worker_admission_bypassed` half. `reportBypassedWorkerJob` is
   > guarded by `admittedWorkerSessions` (`index.ts:1041-1062`), so the admitting process
   > cannot emit that record for its own admitted worker; the causal chain that would produce
   > it needs a live trace. Treat that clause as unproven rather than as an observed outcome.
3. **No economics claim.** The prior verdict stands; no new savings or cost figure follows
   from today's session.
4. **Skill-v2 remains SHADOW.** Governed promotion/refusal trials need renewed bounded
   authority.
5. **Full v1/v2 release remains HOLD** until the remaining gates in
   `outputs/reports/omp-current-evidence-20260919/RECONCILIATION.md` are closed.

   > **SUPERSEDED FOR INSTALLATION STATUS** by the 2026-09-20 conditional-installation
   > record (`docs/requirements/omp-shipping-activation-and-rollback-card.md`, which cites
   > the executed rollback rehearsal in
   > `outputs/reports/omp-activation-20260920/rollback-rehearsal-executed.json`). This HOLD
   > statement was true at 2026-09-19 and is preserved as history; the installation/activation
   > status it measured is now governed by the later record.
   >
   > **Other unresolved gates remain governed by their own latest subject-specific evidence.**
   > Precedence rule: *later, more specific evidence supersedes earlier status only for the
   > exact subject it re-measures.* Decision recorded 2026-09-21 (D-5).

## Day-to-day use

```text
brainctl doctor                     # health
brainctl remember "<claim>" --evidence <path> --grade TESTED
brainctl recall "<question>"        # targeted recall (prints NO_INJECTION <reason> when abstaining)
brainctl memory list / show / history / contradictions
brainctl project list               # registered projects; add with: brainctl project add <path> --id <id>
brainctl ledger verify <host_session_id>
```

Project scoping follows the working directory: run the CLI from the project root, or rely
on the registry attached by `brainctl project add` (which writes `.brain/project.toml` and
an `AGENTS.md` marker into the project). Memory written from a project is retrievable only
from that project (plus intentionally global memories).

Where the evidence lives: `outputs/reports/omp-live-verification-20260919/` (live contracts),
`outputs/reports/omp-current-evidence-20260919/` (gate reconciliation, rebind refs, host
observations), `outputs/reports/storage-cleanup-20260918/` (cleanup receipt, preserved
bundles and extension snapshot). Since 2026-09-19 the whole `outputs/reports/` tree is
gitignored as derived campaign evidence (~8 GB, 65k files): it stays on disk and is
referenced by path; canonical conclusions live in `docs/` and in the small records
committed to `memory/`, `projects/`, `skills/`, `engrams/`, `frontier/`, `immune/`, `config/`.
