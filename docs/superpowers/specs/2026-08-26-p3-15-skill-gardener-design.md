# P3.15 Skill Gardener — Evidence-Composing Maintenance Design

## Scope

Close only the frozen P3.15 Skill Gardener gap. Preserve P3.1–P3.14 and
Lean `candidate / HOLD_SHADOW`. Do not begin P3.16.

The implementation extends `src/second_brain/gardener.py` and reuses the
existing P3.10–P3.14 evidence and lifecycle primitives. It does not create a
second skill registry, economics engine, promotion system, or OMP-specific
Gardener.

## Frozen contract

The Gardener periodically identifies:

- dead skills;
- overlap;
- false triggers;
- never-used skills;
- negative ROI;
- duplicate skills;
- skills too broad or too narrow;
- model-specific quirks.

It supports the maintenance vocabulary:

- merge;
- narrow;
- demote;
- hide;
- retire.

The skill bank remains bounded. The existing §88 lifecycle is:

```text
IDEA -> SHADOW -> MEASURED -> ADVISORY -> ACTIVE -> MONITORED -> REVISE / RETIRE
```

P3.15 must not turn an observation into automatic mutation. Review and
maintenance are separate authorities. ROI is a review signal, not promotion
or retirement authority.

## Architecture

### 1. Portfolio observation

`SkillGardener.observe_portfolio()` inventories `candidate`, `shadow`, and
`active` skills using the existing lifecycle directories. It composes bounded
references to:

- P3.10 Radar candidate and signal evidence;
- P3.11 Skill Forge candidate binding/evaluation evidence;
- P3.12 owner, version, rollback, and promotion records;
- P3.13 counterfactual observed-effect records;
- P3.14 measured-only ROI and `SkillHealth` summaries;
- usage telemetry;
- `skillforge.audit_lifecycle()` findings.

It does not copy raw transcripts, tool output, or reports.

### 2. Issue classification

Each issue is a separate bounded record with:

```text
issue_id
issue_type
skill_name
skill_version/content_hash
lifecycle_state
reason_codes
evidence_refs
measurement_state
replacement_ref (when applicable)
```

The high-level `issue_type` remains exactly six values. Every finding also
carries a deterministic `condition_code`; semantically distinct frozen
conditions are never silently collapsed:

| Frozen condition | `issue_type` | `condition_code` | Detection evidence |
|---|---|---|---|
| stale | `stale` | `evidence_stale` | Current skill content/version/environment identity does not match bound evidence, or an existing freshness check fails. |
| dead skill | `broken` | `dead_skill` | Lifecycle artifact is missing/invalid or concrete current runtime evidence shows the skill cannot execute. |
| overlap | `duplicate` | `capability_overlap` | Verified required-capability/behavior overlap exists; names or descriptions alone never qualify. |
| false triggers | `broken` | `false_trigger` | Current trigger evaluation evidence shows a trigger fires for a task outside the skill capability. |
| never-used | `unused` | `measured_zero_use` | Actual usage telemetry proves zero invocations in the evaluated window. Missing telemetry uses `usage_unavailable`, never this code. |
| negative ROI | `negative_roi` | `measured_negative` | P3.14 measured ROI is negative; estimated-only/unavailable/inconclusive values cannot qualify. |
| duplicate skill | `duplicate` | `exact_duplicate` | Exact normalized capability/content identity is shared by distinct skill IDs, with survivor verification still required before action. |
| too broad | `broken` | `scope_too_broad` | Trigger/selection evidence shows the skill activates beyond its declared capability scope. |
| too narrow | `broken` | `scope_too_narrow` | Required-capability evidence shows the skill fails to activate for an in-scope task. |
| model-specific quirks | `broken` | `model_specific_quirk` | Model-scoped runtime/evaluation evidence shows materially divergent behavior tied to a model identity. |

`dead_skill`, `false_trigger`, `scope_too_broad`, `scope_too_narrow`, and
`model_specific_quirk` use `issue_type=broken` only as the mechanical
high-level bucket; their condition codes remain independently queryable and
testable. `overlap` uses `capability_overlap`, while `duplicate skill` uses
`exact_duplicate`; they are not equivalent. `never-used` maps to
`measured_zero_use`, while absent usage remains `usage_unavailable`.

- `stale`: current content/version/evidence identity mismatch or an existing
  deterministic freshness failure. Stale alone does not imply uselessness.
- `unused`: only when measured invocation evidence proves zero use. Missing
  telemetry is `usage_unavailable`, never zero use.
- `duplicate`: only when material capability overlap is proven, using an
  exact normalized capability/content identity or equivalent existing
  evidence. Similar names alone are insufficient.
- `broken`: only when current verification/runtime/lifecycle evidence records
  a concrete failure.
- `superseded`: only with an explicit surviving replacement skill/version and
  capability evidence showing the replacement covers the old capability.
- `negative_roi`: only from P3.14 measured ROI with negative measured value.
  `estimated_only`, `unavailable`, and inconclusive results cannot become
  `negative_roi`.

Each condition code has dedicated focused verification coverage. A test must
prove both the source evidence and the code/action classification; a generic
`DEGRADED` assertion is insufficient.

Multiple issue types may coexist on one skill; they are never collapsed into
`DEGRADED`.

### 3. Maintenance recommendation

Each observation produces one of:

```text
keep
repair
merge
narrow
demote
hide
supersede
archive_retire
no_action
```

A recommendation contains the issue IDs and evidence references supporting
it. The audit remains read-only and records:

```text
evidence_detected
recommendation
authorization: absent
execution: absent
```

A negative-ROI observation defaults to `repair` or `no_action`, not retire.

### 3a. Action authority

Gardener observes, classifies, recommends, and authorizes. It does not become
a second skill editor or promotion engine. The authority table is:

| Recommendation | Authority / behavior |
|---|---|
| `keep` | Gardener records evidence and disposition only; no mutation. |
| `no_action` | Gardener records evidence and disposition only; no mutation. |
| `repair` | Gardener emits an authorized maintenance task; the existing skill-development/evaluation path performs content changes. |
| `narrow` | Gardener emits an authorized maintenance task; the existing skill-development/evaluation path edits and re-evaluates the skill. |
| `merge` | Gardener requires a verified survivor; the existing skill lifecycle/content path performs the merge and subsequent evaluation. No silent deletion. |
| `demote` | Existing `promotion.demote()` authority performs the lower-level lifecycle move after Gardener authorization and P3.12 evidence checks. |
| `hide` | Existing lifecycle visibility/routing primitive performs the visibility change after explicit authorization; Gardener does not invent a second hidden registry. |
| `supersede` | Existing lifecycle/promotion primitive records the verified replacement identity/version and deactivates the old capability only after replacement verification. |
| `archive_retire` | Gardener's archive-first retirement path performs the reversible artifact/archive mutation after all retirement gates pass. |

The table is normative for implementation and tests: only
`archive_retire` owns the archive/retirement mutation; content-editing actions
delegate to the existing development/evaluation path; `demote` delegates to
`promotion.demote()`; observations and recommendations never mutate.

### 4. Maintenance authorization

`SkillGardener.authorize_maintenance()` accepts one explicit recommendation
and an explicit actor/owner. It revalidates the current skill content hash
and evidence references, then creates a bounded authorization record:

```text
authorization_id
skill identity/version/hash
issue IDs and evidence refs
recommended action
actor/owner
replacement identity/version/hash (if required)
non_regression evidence
rollback readiness
created_at
```

Authorization fails closed when required evidence is absent, stale, or
unavailable. Requirements by action:

- negative ROI: measured P3.14 evidence; review only;
- demote: P3.12 owner/version/rollback evidence and explicit approval;
- merge/supersede: verified survivor identity/version plus equivalent
  capability evidence and rollback reference;
- repair/narrow/hide: concrete issue evidence and an explicit reversible
  target;
- retire: all identity/owner/evidence/non-regression/approval/rollback
  requirements plus archive destination.

No audit or recommendation authorizes itself.

### 5. Archive-first lifecycle action

`SkillGardener.execute_maintenance()` accepts only a current authorization
record. Retirement is strictly archive-first and ordered:

```text
copy the complete skill artifact to archive staging/final destination
→ verify archived bytes and content hash
→ persist the retirement record
→ only then disable/remove the source lifecycle entry
```

Any failure before source mutation leaves the original skill unchanged. A
failed copy, archive verification, or retirement-record write must clean up
only incomplete archive staging and must not alter the source.

The retirement record contains:

```text
retirement_record_id
skill identity
skill version/content hash
owner
retirement reason
issue/evidence references
replacement identity/version (if applicable)
previous lifecycle state
archive location/reference
rollback/restore reference
timestamp
```

The archived `SKILL.md` is hash-verified before the source lifecycle entry is
removed or disabled. The operation never permanently deletes the only copy.

`restore_retirement()` verifies the archive hash and retirement record, then
restores the skill to its previous lifecycle location without overwriting an
existing artifact. Active skills cannot be removed automatically; any active
retirement requires an explicit authorization and a separate explicit
production-safety approval, with isolated dogfood preferred.

Existing `promotion.demote()` remains the authority for manual lower-level
moves. P3.15 does not replace it or add a second promotion engine.

## Evidence and safety invariants

- `read-reuse`'s P3.14 `DEGRADED` result is observed but never acted on during
  qualification or ordinary audit.
- Missing usage is `usage_unavailable`, not `unused`.
- Missing/estimated ROI is not measured-negative.
- Stale evidence cannot authorize a current action.
- Suspected duplicates without a verified survivor cannot mutate anything.
- Missing owner, rollback, approval, or action-specific evidence blocks
  lifecycle mutation.
- `audit_portfolio()` and `observe_portfolio()` do not mutate skill state.
- Positive ROI never auto-promotes; negative ROI never auto-retires.
- P3.12 promotion records remain historical governance evidence; P3.15 does
  not rewrite them.
- P3.15 does not alter Lean or begin P3.16.

## Economics

The audit and authorization path is deterministic local composition. It
records:

```text
model_calls
tool_calls
tokens
records_inspected
local_processing_time_ms
maintenance_work_performed
```

It makes no model calls and does not claim hypothetical savings. Any avoided
redundant-skill cost is reported only when directly measured by existing
telemetry/evidence.

## Verification plan

Focused tests must prove:

1. all six issue types are independently classified;
2. unknown usage is distinct from measured zero use;
3. estimated-only/unavailable ROI cannot become negative ROI;
4. stale identity blocks authorization;
5. duplicate/superseded actions require a verified survivor;
6. broken actions require concrete current failure evidence;
7. missing owner/rollback/approval/non-regression evidence blocks mutation;
8. negative ROI alone produces review/no-action, never retirement;
9. audit is read-only and no positive ROI auto-promotes;
10. archive-first retirement preserves identity/evidence/owner/version and
    restore returns the original bytes/hash;
11. active production removal is not automatic;
12. P3.14 `SkillHealth` arithmetic is consumed, not recomputed;
13. Gardener overhead is bounded and measured.

Dogfood must use current real evidence:

- real `read-reuse` as a negative-ROI review signal, without retiring it;
- a current skill with no issue to prove `keep`/`no_action`;
- an isolated real-current artifact copy for archive/restore only if all
  retirement gates are satisfied.

Final proof requires the full Python suite, focused checks, current OMP
runtime evidence where required, and an independent validator reconstructing
observation -> classification -> evidence -> recommendation -> authorization
-> action/no_action -> resulting lifecycle/archive/rollback state.
