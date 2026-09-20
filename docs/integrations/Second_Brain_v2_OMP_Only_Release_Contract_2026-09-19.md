# Second Brain v2 — OMP-only release contract (successor, version 2026-09-19)

**Status:** active release scope for the v2 release. Supersedes the release scope of the
original 74-clause contract; it does **not** rewrite that contract or its records.

**Authority:** user authorization, 2026-09-19 — "Second Brain's current v2 release will
support and qualify Oh My Pi only." This document authorizes a scope/documentation/verifier
revision only; it does not authorize patched-host installation, live skill promotion, guard
bypass, release tagging, or publishing.

**Machine-readable scope:** `docs/superpowers/plans/2026-09-19-second-brain-v2-omp-only-scope.json`
(consumed by `scripts/verify_qualification.py --scope <path>`).

## 1. Historical record (preserved, not superseded in place)

| Item | Where | State |
|---|---|---|
| Original contract | `docs/superpowers/plans/2026-09-02-second-brain-v2-implementation.md` (unchanged, still the canonical Gate-text authority) | 12 requirements, 74 Gate clauses |
| Last universal-scope verdict | `outputs/reports/omp-qualification-assembly-20260919/strict-verdict.json` | HOLD, 67/74 covered, 10/12 requirements complete |

Those files stay exactly as produced. The OMP-only contract lives beside them; nothing is
rewritten, deleted, or retroactively marked as passing.

## 2. Change record

**Retired (6 clauses, all in `control-plane/universal_control_plane`).** Each is satisfied
only by exercising a second, differently-capable harness:

| Retired clause | Why it cannot be satisfied in an OMP-only scope |
|---|---|
| `rich_to_limited_preserves_decisions` | Requires a real rich→limited harness handoff |
| `rich_to_limited_preserves_evidence` | Same handoff, evidence leg |
| `rich_to_limited_preserves_unresolved_work` | Same handoff, unresolved-work leg |
| `limited_to_rich_preserves_decisions` | Requires the reverse harness direction |
| `limited_to_rich_preserves_evidence` | Same reverse handoff, evidence leg |
| `limited_to_rich_preserves_unresolved_work` | Same reverse handoff, unresolved-work leg |

**Retained (4 clauses of the same requirement).** These are installed-host obligations that
never required a second harness, and they stay required: `adapter_owns_no_canonical_state`,
`false_capabilities_rejected`, `no_mock_host_substitution`,
`unavailable_hosts_reported_unavailable`. All four are already covered by accepted OMP
installed-host evidence.

**Mixed-requirement mapping.** `control-plane/universal_control_plane` is the only mixed
requirement: 6 clauses retired, 4 retained. No other requirement mixed cross-harness
qualification with OMP-relevant behavior, so no other requirement changes.

**Within-OMP handoff stays required.** Cross-harness handoff is retired; handoff *inside*
OMP is not. It remains qualified through the retained `v2-i` clauses —
`complete_event_count_burn_in` (compaction, session handoff and worker context handoff
events), `every_phase_has_current_evidence`, and the terminal release gate — plus the
retained `v2-b`/`v2-a` and canonical-state obligations.

## 3. Recalculated contract

| | Universal scope | OMP-only scope |
|---|---|---|
| Canonical requirements | 12 | 12 (unchanged) |
| Required Gate clauses | 74 | **68** (74 − 6 retired) |
| Covered at revision time | 67/74 | 67/68 |
| Release verdict at revision time | HOLD | HOLD until the terminal clause is covered |

The six retired clauses are **not** counted as passed: the verifier subtracts them from the
required set and reports `retired_gates_counted_as_passed: false`. Any artifact that still
claims a retired clause is accepted as recorded work but contributes nothing to scoped
completeness.

## 4. Verifier behaviour

`scripts/verify_qualification.py` gains an optional, versioned release-scope overlay:

- `--scope <overlay.json>` — loads and validates the overlay (schema version, non-empty
  identity fields, canonical authority retained, only known requirements and Gate clauses
  retired, at least one clause retained per requirement).
- Scoped completeness: a requirement is complete when every **retained** clause is covered
  by accepted evidence; coverage of retired clauses is ignored for completeness.
- The verdict reports `release_scope` (path, sha256, scope id, superseded scope, retired
  clauses) plus `scoped_gate_count` / `scoped_gate_covered` counts.
- Malformed, unknown or over-broad overlays fail closed as their own `release_scope` check.
- Without `--scope` the verifier behaves exactly as before: the universal 74-clause contract
  and its historical verdict remain reproducible.

## 5. Supported capabilities and operational limitations of the OMP-only release

Supported (evidence-backed, current subject `0aab1d9`): Brain retrieval/memory and telemetry
inside OMP; read-only worker dispatch; session restart/resume, compaction and within-OMP
handoff; canonical-state ownership at the adapter boundary; guarded promotion machinery
(refusal on a failing guard); recovery and security checks; burn-in across 543,050 events /
1,595 sessions / 36 days.

Limitations that remain operational, not qualification clauses:

1. **Stock-host mutating worker dispatch does not settle or release.** On stock
   OMP runtimes that publish native lifecycle frames (including the v18.2.6
   source and binary), mutating isolated dispatch is admitted on the extension's
   documented degraded `native_lifecycle` path: cleanup can never be proven, the
   receipt records `cleanupComplete:false`, and the durable writer lease stays
   held/quarantined — never a release. Hosts with none of the three settlement
   sources refuse with `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE`.
   Read-only workers and controller-side edits are unaffected. The qualified
   release path is the accepted patched host. (Corrected 2026-09-20 per the
   executed rollback rehearsal; the prior wording claimed universal stock
   refusal and is false for stock v18.2.6. See
   `outputs/reports/omp-activation-20260920/rollback-rehearsal-executed.json`
   and the corrected activation card.)
2. **Economics stays INSUFFICIENT at n=2** (paired `r_bar = -0.119`, `success_delta = 0.0`).
   No savings verdict is claimed, and no dollar attribution exists for a subscription route.
3. **No cross-harness claim** of any kind is made by this release.
4. The `governed_improvement_promotes_only_with_all_guards` evidence retains its recorded
   limitation: the promoting events ran 2026-09-08/09; today's live evaluation reproduced the
   same eight-guard set refusing when one guard fails.
