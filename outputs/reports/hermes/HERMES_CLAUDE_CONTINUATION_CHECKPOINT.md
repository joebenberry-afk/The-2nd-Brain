# Hermes / Claude Continuation Checkpoint

**Checkpoint purpose:** restore the evidenced stopping point before any future
Hermes or project continuation work. This document separates Claude's
committed repository state from the Hermes bootstrap changes made afterward.

## Repository State

Captured from the repository:

```text
repo root: C:/Users/assas/Documents/The-Second-Brain
branch:    brain/v1-rc4-prime-074-compat
HEAD:      0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
```

At task start, `git status --short` was empty. After the Hermes bootstrap
implementation, the working tree contains only the intended Hermes work:

```text
 M brainstem/telemetry/SCHEMA.md
 M src/second_brain/cli.py
?? brainstem/adapters/hermes/
?? memory/semantic/mem-7ee245204a5e.md
?? outputs/reports/hermes/
?? src/second_brain/hermes_adapter.py
?? tests/test_hermes_adapter.py
```

The persistent Hermes team profile installations are outside this Git
repository at:

```text
C:\Users\assas\AppData\Local\hermes\profiles\integrator\plugins\second-brain-hermes
C:\Users\assas\AppData\Local\hermes\profiles\dev\plugins\second-brain-hermes
C:\Users\assas\AppData\Local\hermes\profiles\validator\plugins\second-brain-hermes
```

All three are enabled, pass Hermes Plugin Doctor, use the same canonical
`brain_home`, `brain_python`, and `repo_root`, and have distinct profile-local
identities: `Brain-Integrator/integrator`, `Brain-Dev/dev`, and
`Brain-Validator/validator`. The legacy `aa` profile is not part of the
persistent three-bot acceptance gate.

## Corrected Second Brain Development Continuation

The previous version of this checkpoint incorrectly used the latest Claude
activity (Prime 0.7.4 qualification/promotion preparation) as the next Second
Brain development milestone. The tracks are now separated below. Current
repository/source evidence and the independent Brain-Validator audit outrank
closure summaries that claim release completion without matching live proof.
This continuation correction changed only this checkpoint; the pre-existing
Hermes adapter files listed in Repository State were not modified, and no
Second Brain source or test implementation was started.

### Second Brain core / v1.0 feature development

| State | Evidence-backed classification |
|---|---|
| **Completed at implementation/component level** | The v4.2 self-hosting build and its Phase 0–23 milestone sequence are historical completed implementation work (`outputs/reports/milestone-01..24-*`). The repository contains tested core primitives for AutoInject/retrieval, ledger/session state, working-set/JIT context, FTS5 memory, risk/verification, promotion/immune controls, and related subsystems. |
| **Not fully release-qualified** | RC1 closure commit `611f65f` was explicitly invalidated by `outputs/reports/rc2/00-qualification-status.md` (F1–F6). The RC2 repair batch (`5b10cfd` through `4accaf5`) implemented additional primitives and tests, but `outputs/reports/rc2/24-independent-verifier-handoff.md` says `INDEPENDENT QUALIFICATION REQUIRED`; `outputs/reports/rc2/02-token-fabric-live-wiring-audit.md` records several live-wiring fields as PARTIAL/NO. No v1.0.0 release claim is valid from the closure summary alone. |
| **Partially implemented / unproven** | Remaining v1.0 evidence includes live token-fabric qualification, cross-harness qualification, full regression/production evidence, burn-in/failure-injection depth, and several P3/P4 live-use or integration gates. The field-level audits (`v1-roadmap-baseline-reaudit.md`, `v1-roadmap-matrix-p3.md`, and `v1-roadmap-matrix-crosscut.md`) distinguish implementation from real-use proof. |

The established priority order remains the frozen 37-item sequence:
`P0 -> P1 -> P2 -> P3 -> P4`. It is not replaced by the later Prime
qualification taxonomy.

### Lean Code work

- **Implemented and tested:** provider/cache instrumentation, the 865-character
  canonical Runtime Kernel, the harness-neutral Python runtime mirror, Lean
  lifecycle gates, paired-evaluation harness, RTD/risk/STOP plumbing, and
  associated unit/evaluation tests (`26f9d45` through `bd7fc4a`,
  `outputs/reports/p3-lean-code-gate.md`).
- **Not promoted:** the Lean skill remains under `skills/candidates/lean-code/`;
  the promotion evidence remains `HOLD SHADOW`, not active. Economics do not
  establish pure Lean savings, and the final valid real campaign count is
  corrected to 4/14 after synthetic Antigravity evidence was invalidated.
- **Incomplete/blocked:** the real Antigravity campaign and active promotion
  require `agy` installation/authentication, a frozen model slug, and a
  derived campaign verdict. Brain memories `mem-bb634354ec69` v2 and
  `mem-99df66e3c8f6` are the canonical correction: the earlier completion
  claim was invalidated; Lean remains candidate and the real campaign is
  incomplete.

### Harness integration work

- **Latest fully evidenced milestone:** RC4 CVM closure repair and genuine
  Pilot 5 targeted proof at commit `98f147f`, documented in
  `outputs/reports/rc4/15-real-prime-pilot-5.md`. It genuinely proved RTD
  metadata correlation, byte-exact artifact recovery, RTD-backed paging,
  already-EVICTED reprojection, and model-triggered fault-in for that pilot.
- **Component-level work that must not be repeated:** RC4 R0–R9 implementation
  and test work in `outputs/reports/rc4/00-qualification-status.md` and
  `10-runtime-implementation-checkpoint.md`, including RTD/firewall reuse,
  VMem compaction bookkeeping, action-cache validation, tool-surface capture,
  worker-plane plumbing, hybrid-retrieval wiring, and fresh-verifier record
  plumbing.
- **Still incomplete:** the full cross-harness/paid-model qualification, a
  real fresh-model verifier response, burn-in, and other release-level proof
  gates were not completed. `09-fresh-verifier.md` explicitly says no real
  model was invoked for that mechanism.

### Prime-specific maintenance / upgrade work

Prime 0.7.4 qualification/promotion is **Frozen / Deferred Harness
Maintenance**. The commits `13e892d`, `4de4321`, `7d237c1`, `daecf5d`,
`e5df1cf`, `0c31666`, `b85b7b6`, and `0bc2b8d`, plus the reports under
`outputs/reports/rc4/prime-074/final-promotion-gates/`, are maintenance-track
evidence only. The pre-promotion gate was prepared, but the live-mutating
promotion and Phase N smoke were not performed and must not be resumed here.

### Hermes integration work completed after the prior gate

The persistent three-profile Hermes proof remains valid and is not a substitute
for v1.0 qualification: `mem-7ee245204a5e` was written by Integrator,
retrieved by fresh Dev, and independently verified by Validator. The Hermes
adapter remains a thin boundary over existing Brain primitives.

## Latest boundary and active unfinished work

The latest fully evidenced Second Brain milestone before the Prime 0.7.4
qualification detour was **RC4 CVM closure repair / genuine Pilot 5 targeted
proof** (`98f147f`, `15-real-prime-pilot-5.md`). It was harness integration,
not a v1.0 release declaration.

At that boundary, unfinished work was:

1. **Core/v1.0:** independent qualification/read-back of the frozen 37-item
   roadmap and its remaining live-use/release evidence gaps.
2. **Lean:** complete the real valid-pair campaign and keep the skill at
   candidate/shadow until a derived promotion verdict passes.
3. **Harness:** complete the remaining genuine cross-harness, fresh-verifier,
   token, burn-in, and failure-injection proof gates.
4. **Prime maintenance:** 0.7.4 promotion/Phase N, now explicitly frozen and
   deferred.

## Next Approved Second Brain Milestone (do not start implementation here)

Perform the already-established **RC2 independent qualification/read-back of
the frozen v1.0 37-item roadmap**, beginning with the first unresolved live
evidence gate and preserving the exact `P0 -> P1 -> P2 -> P3 -> P4` order.
This is a proof/reconciliation milestone, not permission to invent a new
feature or to resume Prime. Do not promote Lean, start a paid campaign, or
modify code during this continuation correction.

## Completed work that must not be repeated

- v4.2 Phase 0–23 implementation gates and self-hosting experiments already
  recorded in milestone-01..24 reports.
- RC2 implementation batch and its existing tests/evidence; qualification is
  the remaining gate, not a rewrite.
- Lean Code kernel/runtime/evaluation plumbing and the valid evidence
  correction; do not count synthetic pairs or re-promote from candidate.
- RC4 R0–R9 component wiring and Pilot 5 targeted CVM/RTD proof.
- Hermes three-profile installation and cross-bot runtime proof.
- Prime 0.7.4 qualification work already recorded; do not resume Phase M/N.

## Partially completed or merely planned work

- RC2/v1.0 release qualification and remaining live-wiring/release gates:
  incomplete.
- Lean active promotion and complete genuine campaign: incomplete/blocked.
- Fresh-model verifier execution, full cross-harness/paid qualification,
  burn-in, and remaining failure-injection proof: not completed.
- Dense-vector Tier 3/4 retrieval fallback: designed extension seam, no
  implementation in the current repository (`rc4/08-hybrid-retrieval-validation.md`).
- Prime Phase N/live 0.7.4 promotion: frozen/deferred, not an active milestone.

## Evidence Sources

- `outputs/reports/rc2/00-qualification-status.md`
- `outputs/reports/rc2/01-frozen-roadmap-matrix.md`
- `outputs/reports/rc2/02-token-fabric-live-wiring-audit.md`
- `outputs/reports/rc2/03-cross-harness-qualification.md`
- `outputs/reports/rc2/04-token-economics-paired-campaign.md`
- `outputs/reports/rc2/05-feature-ablations.md`
- `outputs/reports/rc2/06-production-qualification.md`
- `outputs/reports/rc2/24-independent-verifier-handoff.md`
- `outputs/reports/v1-roadmap-baseline-reaudit.md`
- `outputs/reports/v1-roadmap-matrix-p0p1p2p4.md`
- `outputs/reports/v1-roadmap-matrix-p3.md`
- `outputs/reports/v1-roadmap-matrix-crosscut.md`
- `projects/second-brain/current-state.md`
- `projects/second-brain/architecture.md`
- `outputs/reports/p3-lean-code-gate.md`
- `outputs/reports/p3-promotion-evaluation-report.md`
- `outputs/reports/p3-surgical-recovery-report.md`
- `outputs/reports/rc4/00-qualification-status.md`
- `outputs/reports/rc4/03-prime-rtd-firewall.md`
- `outputs/reports/rc4/04-prime-vmem.md`
- `outputs/reports/rc4/08-hybrid-retrieval-validation.md`
- `outputs/reports/rc4/09-fresh-verifier.md`
- `outputs/reports/rc4/10-runtime-implementation-checkpoint.md`
- `outputs/reports/rc4/15-real-prime-pilot-5.md`
- Brain memories `mem-99df66e3c8f6`, `mem-bb634354ec69`,
  `mem-771d74aaa3fd`, and `mem-d2f7df353130`
- `outputs/reports/hermes/HERMES_BRAIN_ACCESS_MAP.md`
- `outputs/reports/hermes/HERMES_RUNTIME_PROOF.md`
- `outputs/reports/hermes/HERMES_CROSS_BOT_PROOF.md`
- `outputs/reports/hermes/HERMES_TOKEN_CONTEXT_EVIDENCE.md`
- `outputs/reports/rc4/prime-074/final-promotion-gates/LIVE_PROMOTION_CHECKPOINT.md`
- `outputs/reports/rc4/prime-074/final-promotion-gates/LIVE_UPGRADE_PREFLIGHT.md`
- `outputs/reports/rc4/prime-074/final-promotion-gates/PRE_PROMOTION_GATE.md`
- `outputs/reports/rc4/prime-074/final-promotion-gates/PHASE_I_J_BLOCKER.md`
- `tests/test_hermes_adapter.py`
- `tests/test_claude_code_adapter.py`
- `brainstem/telemetry/SCHEMA.md`

## Checkpoint Status

```text
CLAUDE_CONTINUATION_POINT_RECOVERED
HERMES_BOOTSTRAP_IMPLEMENTED
HERMES_PERSISTENT_THREE_BOT_RUNTIME_PROOF
HERMES_CONTINUATION_READY
SECOND_BRAIN_DEVELOPMENT_CONTINUATION_CORRECTED
SECOND_BRAIN_DEVELOPMENT_CONTINUATION_READY
```
