# P2.6 Intelligent Model Routing — Final Qualification

**Verdict:** `P2.6_PROVEN`
**Primary live harness:** Oh My Pi (OMP)
**Secondary harness:** Hermes (focused regression/plugin validation retained; live model-routing qualification paused per harness-priority change)
**Independent authority:** Brain-Validator

## Qualification summary

A Second Brain-owned, harness-neutral model-routing decision surface now controls the primary OMP provider request through OMP's supported `before_provider_request` replacement seam.

```text
real OMP task
  -> Second Brain ModelDecision
  -> OMP before_provider_request replacement
  -> effective OMP provider request
  -> provider response/usage
```

The Brain selector remains authoritative. OMP only transports the bounded decision and records effective request/response metadata. No OMP-native routing, memory, VMem, artifact, ledger, worker-plane, or policy subsystem was created.

## Independent Validator verdict

Brain-Validator independently inspected the changed implementation, OMP readiness proof, focused tests, and all four real OMP telemetry artifacts. Final verdict:

```text
P2.6_PROVEN
```

Confidence: 0.91. Findings: none.

## Decision and policy gates

Verified in `src/second_brain/model_routing.py`, `src/second_brain/omp_adapter.py`, and `brainstem/prime-extension/src/routing-bridge.ts`:

- bounded, task-text-free `ModelDecision` serialization;
- deterministic candidate ordering and stable decision IDs;
- lowest-cost eligible selection;
- role minimum-tier constraints;
- capability and risk constraints;
- provider/model availability and explicit fallback;
- premium escalation only with explicit objective/policy reason;
- worker premium-forcing knobs rejected/ignored by trusted-policy gating;
- malformed candidate/decision booleans rejected;
- ambiguous provider/model quality statistics not cross-applied;
- explicit selected/original/fallback identities;
- no silent profile-default, coordinator-model, arbitrary-provider, or premium fallback.

## OMP live probes

All sessions returned the requested bounded sentinel and exited successfully.

### Probe A — routine/default eligible route

Telemetry:

```text
telemetry/agent-performance/2026-08-24T03-55-41-757Z_01a031e8-e53d-7314-8592-67fcda2de3ec.jsonl
```

Observed:

- decision `model-decision-c943b1528e948377059f330a9`;
- selected `openai-codex / gpt-5.6-luna`, tier `balanced`, reason `LOWEST_COST_ELIGIBLE`;
- effective request `openai-codex / gpt-5.6-luna`;
- assistant usage `openai-codex / gpt-5.6-luna`;
- `handoff_failure=null`;
- real token/cost usage recorded.

### Probe B — legitimate premium escalation

Telemetry:

```text
telemetry/agent-performance/2026-08-24T04-04-03-448Z_01a031f0-8cf8-763d-8f1e-3440222c8878.jsonl
```

Observed:

- architecture/security/production task;
- selected `openai-codex / gpt-5.6-sol`, tier `premium`;
- reason `PREMIUM_ESCALATION_JUSTIFIED`;
- effective request `openai-codex / gpt-5.6-sol`;
- provider request metadata `openai-codex / gpt-5.6-sol`;
- assistant usage `openai-codex / gpt-5.6-sol`;
- no fallback or handoff failure.

### Probe C — controlled fallback

Telemetry:

```text
telemetry/agent-performance/2026-08-24T04-04-27-511Z_01a031f0-eaf7-739d-82d8-2fa6d6f1c34a.jsonl
```

Controlled metadata marked the selected premium Sol candidate unavailable while declaring Terra eligible.

Observed:

```text
original selected: openai-codex / gpt-5.6-sol (premium, unavailable)
fallback reason:   MODEL_UNAVAILABLE_FALLBACK
fallback/effective: openai-codex / gpt-5.6-terra (balanced)
actual usage:      openai-codex / gpt-5.6-terra
```

No silent fallback occurred.

### Probe D — worker premium guard

Telemetry:

```text
telemetry/agent-performance/2026-08-24T04-05-10-742Z_01a031f1-93d6-7750-9b00-75908c5b5b96.jsonl
```

Observed worker role:

```text
selected/effective/actual: deepseek / deepseek-v4-flash
selected tier:             efficient
reason:                    LOWEST_COST_ELIGIBLE
provider response:         deepseek / deepseek-v4-flash, status 200
```

The worker did not force the premium candidate.

## OMP readiness and preservation

`outputs/reports/rc2/OMP_SECOND_BRAIN_READY_PROOF.md` records the independent OMP readiness verdict and the first successful OMP selected==effective proof.

Existing OMP/Brain behavior remains covered:

- AutoInject packet delivery and bounded custom context;
- VMem and context paging;
- artifact preservation;
- canonical ledger mirror;
- worker-plane/context reuse;
- provider request/response telemetry;
- P1.3 cache/context regression behavior.

## Automated verification

- Python P2.6/P0-P2 regression matrix: **118 passed**.
- OMP routing/readiness + lifecycle/AutoInject/VMem/ledger/context matrix: **232 passed**.
- OMP TypeScript typecheck: passed.
- Ruff on changed Python surfaces: clean.
- Pyright on changed Python surfaces: `0 errors, 0 warnings, 0 informations`.
- Hermes adapter/plugin focused suite: **28 passed**.
- Hermes plugin doctor: passed.

## Hermes boundary

The Hermes implementation remains present and validated by focused tests. Its initial live probe is preserved at:

```text
telemetry/agent-performance/hermes-Brain-Validator-20260823_233345_36fdd0.jsonl
```

That probe recorded `NO_ELIGIBLE_MODEL` because Hermes pre-LLM lacked provider metadata and no candidate metadata was configured. Per the user's priority change, no further Hermes live runtime work was performed; Hermes remains a secondary cross-harness validation target. This does not invalidate the OMP-primary P2.6 proof.

## P0-P2 and stop boundary

The frozen roadmap and existing qualification artifacts establish P0, P1, and P2 as fully proven for this worktree. P2.6 is now independently proven on the primary OMP runtime.

The first post-P2 roadmap requirement is **P3.1 — Active State Capsule**. No P3 implementation was started by this qualification.

**STOP.**
