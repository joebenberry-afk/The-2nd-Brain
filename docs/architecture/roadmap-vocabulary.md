# Roadmap Vocabulary Reconciliation (T6.4)

This is a one-time reconciliation of the 37-item Second Brain roadmap vocabulary,
performed per plan task T6.4. Two documents have independently named the same 37
`P0.1`-`P4.5` items over the life of this campaign:

- The canonical **Scout Spec** (`2nd Brain — Canonical R&D Scout Spec (v1.0 + v2.0).docx`),
  which is the authoritative naming source going forward.
- The repo's **status ledger**
  (`outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`), whose
  `Requirement` column was populated independently across many qualification passes.

For 34 of the 37 items the two names match exactly (or are trivial capitalization/
punctuation variants treated as the same name). Three items diverge — `P3.3`,
`P3.13`, `P3.16` — and are called out explicitly below. Per the plan, **the Scout
Spec name is canonical** for all future documentation and new work; this table does
not rename any historical status-ledger row text except where the ledger itself is
updated in the same commit as this file (see the ledger's `Requirement` column for
`P3.13` and `P3.16`, and the annotated `P3.3` entry).

The `Owning Module(s)` column identifies the primary current Python/TypeScript
module(s) implementing each item, determined by cross-referencing the status
ledger's evidence citations against the qualification reports and reading the
cited source modules directly (not guessed from naming alone).

| Item | Scout Spec Name | Repo Status-Ledger Name | Owning Module(s) | Notes |
|---|---|---|---|---|
| P0.1 | Automatic Brain initialization | Automatic Brain Initialization | `src/second_brain/autoinject.py`, `src/second_brain/doctor.py` | |
| P0.2 | Automatic recall | Automatic Recall | `src/second_brain/hybrid_retrieval.py`, `src/second_brain/semantic.py` | |
| P0.3 | Automatic routing | Automatic Routing | `src/second_brain/autoinject.py`, `src/second_brain/decisions.py`, `src/second_brain/router.py` | |
| P0.4 | Automatic context injection | Automatic Context Injection | `src/second_brain/autoinject.py`, `src/second_brain/injection_slots.py` | |
| P0.5 | Automatic activity capture | Automatic Activity Capture | `src/second_brain/ledger.py`, `src/second_brain/decisions.py` | |
| P0.6 | Injection telemetry | Injection Telemetry | `src/second_brain/telemetry.py`, `src/second_brain/autoinject.py` | |
| P1.1 | Strict Driver/Worker Control Plane | Strict Driver/Worker Plane | `src/second_brain/repository_intelligence.py` (`WorkerPlaneManager`) | |
| P1.2 | Worker Communication | Worker Communication | `src/second_brain/worker_protocol.py`, `src/second_brain/repository_intelligence.py` (packet contracts) | |
| P1.3 | Cache-Preserving Context Architecture | Cache-Preserving Context | `src/second_brain/working_set.py`, `src/second_brain/jit.py`, `src/second_brain/capsule_runtime.py` | |
| P2.1 | Deterministic Projections | Deterministic Projections | `src/second_brain/doctor.py`, `src/second_brain/ledger.py` | |
| P2.2 | Lossless Session/Event Ledger + Compaction Recovery | Lossless Event Ledger & Compaction | `src/second_brain/ledger.py` (`checkpoint_ledger`, `recover_report`), `src/second_brain/vmem.py` (`prepare_compaction`, `resume_after_compaction`) | |
| P2.3 | Context Offloading | Context Offloading | `src/second_brain/artifacts.py`, `src/second_brain/vmem.py` | |
| P2.4 | Repository Intelligence | Repository Intelligence | `src/second_brain/repository_intelligence.py` | |
| P2.5 | Risk-Adaptive Verification | Risk-Adaptive Verification | `src/second_brain/risk.py`, `src/second_brain/verify.py` | |
| P2.6 | Intelligent Model Routing | Intelligent Model Routing | `src/second_brain/model_routing.py` | |
| P3.1 | Active State Capsule | Active State Capsule | `src/second_brain/capsule_runtime.py`, `src/second_brain/working_set.py` | |
| P3.2 | Context Capsule | Context Capsule | `src/second_brain/worker_protocol.py`, `brainstem/prime-extension/src/index.ts` (`P3.2 worker context`) | |
| P3.3 | Reversible Tool Distillation (RTD) | Reversible Tool Distillation | `src/second_brain/artifacts.py`, `src/second_brain/firewall.py`, `brainstem/prime-extension/src/rtd.ts` | Name string is identical, but this is a **semantic** drift, not a lexical one: the Scout Spec's P3.3 envisions repeated *agent workflows* becoming reversible/testable/attributable scripts/tools/skills (a workflow-to-macro concept), while the actual repo implementation is *tool-output* distillation/compression — byte-exact preservation plus deterministic summarization of large tool results. Per the plan's explicit instruction, this drift is recorded here and the ledger's `Requirement` cell is annotated; spec meaning is canonical for future work. |
| P3.4 | Lean Code / Lean Build | Lean Code / Lean Build | `src/second_brain/lean_runtime.py` | |
| P3.5 | Simplification Review | Simplification Review | `src/second_brain/simplification.py` | |
| P3.6 | STOP Discipline | STOP Discipline | `src/second_brain/cli.py` (`cmd_stop`), `src/second_brain/working_set.py` (`check_requirements`) | |
| P3.7 | Risk-Adaptive Accuracy Gate | Risk-Adaptive Accuracy Gate | `src/second_brain/verify.py` (`evaluate_accuracy_gate`), `src/second_brain/risk.py` | |
| P3.8 | Independent Intent Verification | Independent Intent Verification | `src/second_brain/verify.py` (`build_verifier_brief`), `src/second_brain/fresh_verifier.py` | |
| P3.9 | Environment Steward | Environment Steward | `src/second_brain/envsteward.py` | |
| P3.10 | Improvement Radar | Improvement Radar | `src/second_brain/radar.py` | |
| P3.11 | Skill Forge | Skill Forge | `src/second_brain/skillforge.py` | |
| P3.12 | Skill Verifier | Skill Verifier | `src/second_brain/skillforge.py` (`trigger_eval`, `workflow_eval`, `regression_eval`, `security_review`) | |
| P3.13 | Skill Promotion / Rollback Governance | Counterfactual Skill Evaluation | Spec concept (candidate/shadow/canary/active lifecycle + rollback): `src/second_brain/promotion.py`, `src/second_brain/immune.py`, `src/second_brain/optimization.py` (`rollback`). Repo-labeled implementation at this ledger slot: `src/second_brain/credit.py` (`counterfactual_result`), `src/second_brain/gardener.py` | Genuine spec-vs-repo numbering/labeling drift, not a rename: the Scout Spec's P3.13 is lifecycle governance (candidate → shadow → canary → active, with rollback, evidence, and provenance), which the repo actually implements in `promotion.py`/`immune.py`/`optimization.py`. The repo ledger's P3.13 row instead names and evidences "Counterfactual Skill Evaluation" — the observed with/without comparison mechanism in `credit.py`/`gardener.py` — which the Scout Spec catalog does not list as its own numbered item. Spec name is canonical; ledger `Requirement` cell is updated to reflect both. |
| P3.14 | Skill ROI / Credit Layer | Skill ROI | `src/second_brain/credit.py`, `src/second_brain/gardener.py` | |
| P3.15 | Skill Gardener | Skill Gardener | `src/second_brain/gardener.py` (`SkillGardener`) | |
| P3.16 | Brain Immune / Policy Safety | Modular Skill Visibility | Spec concept (quarantine/inspect foreign skills-tools-policies, provenance, permissions, secrets, rollback): `src/second_brain/immune.py`, `src/second_brain/skillforge.py` (`security_review`), `src/second_brain/paths.py` (`immune/quarantine`, `skills/quarantine`). Repo-labeled implementation at this ledger slot: `src/second_brain/skills.py`, `brainstem/prime-extension/src/visibility-bridge.ts` | Genuine spec-vs-repo drift: the repo ledger's P3.16 row names and evidences "Modular Skill Visibility" — the OMP injection-budget/hydration-plan concern in `skills.py`/`visibility-bridge.ts` — a materially different concern from the Scout Spec's P3.16 (immune/quarantine/policy safety for foreign skills, tools, and policies). Spec name is canonical; ledger `Requirement` cell is updated to reflect both. |
| P3.17 | Brain Handoff | Brain Handoff | `src/second_brain/handoff.py`, `src/second_brain/hermes_adapter.py`, `src/second_brain/omp_adapter.py` | |
| P4.1 | Long-Running Goals | Long-Running Goals | `src/second_brain/goals.py` | |
| P4.2 | Event-Driven Heartbeats / Schedules | Schedules / Heartbeats | `src/second_brain/heartbeat.py` | |
| P4.3 | Operational Telemetry | Operational Telemetry | `src/second_brain/telemetry.py`, `src/second_brain/monitor.py` | |
| P4.4 | Bottleneck Fingerprinting | Bottleneck Fingerprinting | `src/second_brain/fingerprints.py`, `src/second_brain/radar.py` | |
| P4.5 | Governed Self-Optimization | Controlled Self-Optimization | `src/second_brain/optimization.py`, `src/second_brain/frontier.py` | |

## Method

- Scout Spec names were transcribed verbatim (short name only, before the em-dash
  description) from the canonical spec document, already extracted in full for this
  task.
- Repo status-ledger names were read directly from
  `outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`'s `Requirement`
  column.
- Owning modules were determined by following each ledger row's `Evidence` citation
  to its qualification report/capsule artifact, then reading the module(s) that
  report cites or that implement the described mechanism directly (docstring plan
  references such as `plan §3 P3.17` or `(plan §119, Phase 23)` were used to confirm
  the match), rather than guessed from filenames.
- All 34 non-drifted items were individually compared name-for-name against the
  Scout Spec catalog; no drift beyond `P3.3`, `P3.13`, and `P3.16` was found.
