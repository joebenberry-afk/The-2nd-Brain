# P2.6 Intelligent Model Routing — Independent Validator Re-qualification

**Validator:** Brain-Validator (`bot_role=validator`)  
**Audit timestamp:** 2026-08-23T18:39:16-04:00  
**Repository:** `C:/Users/assas/Documents/The-Second-Brain`  
**Scope:** read-only implementation/runtime audit; no implementation changes made by this audit  
**Prior status:** P2.1–P2.5 treated as PROVEN; P2.6 was unresolved  
**Verdict:** **MISSING** (adjacent routing/statistics/telemetry substrates exist, but the required Brain-owned model decision and host-consumption seam is absent)

## 1. Exact frozen contract

The current frozen roadmap matrix (`outputs/reports/rc2/01-frozen-roadmap-matrix.md`, line 30) defines P2.6 as:

- **Requirement:** Intelligent Model Routing
- **Canonical implementation modules named by the matrix:** `router.py`, `crossmodel.py`
- **Live evidence expected by the matrix:** model tier recommendation
- **Token/economic boundary:** premium model escalation only
- **Historical matrix claim:** PROVEN

The matrix itself labels its later Hermes addendum as an independent read-back boundary and says the historical matrix is superseded where later evidence differs (lines 66–71). Therefore this audit does not accept the historical P2.6 `PROVEN` cell without independently proving model selection and live model consumption.

For this re-qualification, the frozen contract is operationalized by the requested 12 gates: a real Brain model decision; eligible model/provider selection using task/risk/cost/capability signals; live harness consumption; deterministic/policy-bounded behavior; role constraints; deterministic fallback; task/session/project correlation; decision telemetry/ledger; harness neutrality; explicit separation from Hermes-native routing; persistent Hermes proof of actual model effect; and token/cost/risk data sufficient for later optimization without P4 self-optimization.

## 2. Repository state and canonical surfaces

### Exact repository state captured before this evidence file

Commands and read-back:

```text
git rev-parse --show-toplevel
C:/Users/assas/Documents/The-Second-Brain

git branch --show-current
brain/v1-rc4-prime-074-compat

git rev-parse HEAD
0bc2b8d56ceed3c1e17576283f05b4dba6f52d91

git status --short --branch
## brain/v1-rc4-prime-074-compat...origin/brain/v1-rc4-prime-074-compat [ahead 8]
 M brainstem/telemetry/SCHEMA.md
 M outputs/reports/rc2/01-frozen-roadmap-matrix.md
 M src/second_brain/cli.py
 M src/second_brain/contracts.py
 M src/second_brain/vmem.py
 M tests/test_orchestration.py
?? brainstem/adapters/hermes/
?? memory/semantic/mem-7ee245204a5e.md
?? outputs/reports/hermes/
?? outputs/reports/rc2/P0_4_VALIDATOR_RUNTIME_PROOF.md
?? outputs/reports/rc2/P0_6_FINAL_PROJECT_ATTRIBUTION_RUNTIME_PROOF.md
?? outputs/reports/rc2/P0_6_GOVERNOR_ATTRIBUTION_RUNTIME_PROOF.md
?? outputs/reports/rc2/P0_6_INJECTION_TELEMETRY_PROOF.md
?? outputs/reports/rc2/P1_1_FINAL_HERMES_RUNTIME_PROOF.md
?? outputs/reports/rc2/P1_1_HARNESS_NEUTRAL_SEAM_MAP.md
?? outputs/reports/rc2/P1_1_HERMES_DRIVER_WORKER_REQUALIFICATION.md
?? outputs/reports/rc2/P1_1_HERMES_RUNTIME_PROOF.md
?? outputs/reports/rc2/P1_2_FINAL_HERMES_RUNTIME_PROOF.md
?? outputs/reports/rc2/P1_2_HERMES_WORKER_COMMUNICATION_REQUALIFICATION.md
?? outputs/reports/rc2/P1_3_FINAL_HERMES_CACHE_PRESERVATION_PROOF.md
?? outputs/reports/rc2/P1_3_HERMES_CACHE_PRESERVATION_REQUALIFICATION.md
?? outputs/reports/rc2/P2_3_FINAL_HERMES_CONTEXT_OFFLOADING_PROOF.md
?? outputs/reports/rc2/P2_3_VALIDATOR_CONTEXT_OFFLOADING_REQUALIFICATION.md
?? src/second_brain/hermes_adapter.py
?? src/second_brain/worker_protocol.py
?? tests/test_hermes_adapter.py
?? tests/test_worker_protocol.py
```

The worktree was already dirty before this validator evidence file was written. The listed implementation changes are pre-existing baseline state; this audit did not edit them.

### Canonical implementation/runtime surfaces

| Surface | Current responsibility | P2.6 finding |
|---|---|---|
| `src/second_brain/router.py:239-280` | Deterministic sparse **skill** routing (`task -> selected skills`), report-only; output is `selected`, `scores`, `shadow` | Not a model selector |
| `src/second_brain/crossmodel.py:1-8,46-186,189+` | Caller-recorded model profiles and model/skill/task outcomes; task hash, success/noise/F1 aggregates, transfer reports | Post-hoc statistics; no selection decision |
| `src/second_brain/risk.py:171-201` | Deterministic risk score for touched files and user criticality | No model/provider candidate evaluation |
| `src/second_brain/hermes_adapter.py:943-954` | Invokes existing skill router; fail-open returns `([], True)` on router failure | Skill-route fallback only |
| `src/second_brain/hermes_adapter.py:1154-1245` | Hermes `pre_llm_call`: AutoInject/VMem, skill routes, bounded identity/telemetry, packet delivery | No Brain model decision or host model override |
| `brainstem/prime-extension/src/driver-orchestrator.ts:1-12,80-107` | Hermes/Prime-native active-model role classification (`hard_orchestrator`, `driver`, `worker`, `normal`) | Role policy, not Brain model routing |
| `brainstem/prime-extension/src/driver-orchestrator.ts:119-133` | Prompt contract says to prefer a cheap competent worker | Advisory host prompt text; no candidate selection/consumption handoff |
| `brainstem/telemetry/SCHEMA.md:39-50` | Token/cost/provider usage and Hermes lifecycle/pre-LLM records | No selected-model/candidate/fallback decision schema |
| Installed validator plugin | `C:/Users/assas/AppData/Local/hermes/profiles/validator/plugins/second-brain-hermes` | Plugin doctor passed; adapter remains thin |

### CLI and database read-back

`brainctl models --help` exposes only:

```text
{record,transfer,policy,add,report}
```

`brainctl router --help` exposes only:

```text
{route,eval}
route: route a task to skills (report only)
```

A read-only SQLite schema query against `db/brain.sqlite` returned the model-related tables:

```text
model_profiles(model_id, family, capabilities, first_seen_at)
model_skill_outcomes(outcome_id, model_id, skill_name, task_hash, success,
                     noise, f1, session_id, created_at)
```

The database had no `model_decisions`, `model_candidates`, `model_routes`, or equivalent decision table. This confirms that `crossmodel.py` stores outcome statistics rather than an operational routing decision.

## 3. Independent execution evidence

### Focused automated tests

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q -o addopts='' tests/test_crossmodel.py tests/test_router.py
28 passed in 8.66s

env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q -o addopts='' tests/test_hermes_adapter.py
21 passed in 33.96s

npm exec vitest run tests/driver-orchestrator.test.ts tests/wiring.test.ts
exit 0
```

These tests prove skill routing, cross-model outcome/statistics behavior, Hermes adapter lifecycle/injection behavior, and Hermes/Prime wiring tests. They do not prove a model-selection decision or model override.

### Hermes installation/plugin boundary

```text
hermes --version
Hermes Agent v0.20.5 (2026.8.19) · upstream 739bc555
Python: 3.11.16
OpenAI SDK: 2.24.0
Up to date

hermes -p validator plugins doctor C:/Users/assas/AppData/Local/hermes/profiles/validator/plugins/second-brain-hermes --ci
exit 0
```

The configured validator plugin points at the canonical repository/home and identifies `Brain-Validator` / `validator`. No credential values are included in this artifact.

### Controlled real Brain/Hermes-adapter probes

The existing `autoinject hermes-hook` subprocess path was invoked against the canonical Brain twice with the **same** task and different supplied models/providers:

- expensive probe: `hermes:Brain-Validator:p26-validator-probe-expensive`, supplied `openai-codex / gpt-5.6-luna`
- cheap probe: `hermes:Brain-Validator:p26-validator-probe-cheap`, supplied `deepseek / deepseek-v4-flash`
- same task hash: `6ee990b599f6a04dc6c1e277b76ecef0a3790d37e62b650d6f19ce73bfa877a6`
- same packet hash: `0e92dce4a3dd7a73b265acd4bbf88053a114821406fcbaf7036e35cec7919a6d`
- both `hermes_pre_llm_call` records: `decision=INJECT`, `routing_error=false`, `selected_routes=[]`, `packet_tokens=222`
- neither record contains `selected_model`, `eligible_models`, `model_decision`, `routing_decision`, `fallback_model`, or a policy code for model selection

Persistent read-back files:

```text
telemetry/agent-performance/hermes-Brain-Validator-p26-validator-probe-expensive.jsonl
telemetry/agent-performance/hermes-Brain-Validator-p26-validator-probe-cheap.jsonl
```

The session-start records preserve each **supplied** model/provider, while the pre-LLM records preserve the same Brain packet and no model decision. This is direct evidence that the current adapter carries host identity/model metadata and performs Brain AutoInject/skill routing; it does not select a model.

### Current telemetry aggregate read-back

A read-only JSONL aggregation over `telemetry/agent-performance` returned:

```text
HERMES_SESSION_STARTED 90
  model/provider pairs include 81 (unknown, gpt-5.6-luna),
  2 (openai-codex, gpt-5.6-luna), 1 (deepseek, deepseek-v4-flash),
  and 6 (unknown, unknown)
HERMES_PRE_LLM 139
  selected_model_field=0
  selected_routes_nonempty=42
  routing_decision_fields=0
ASSISTANT_USAGE 7001
  with_cost=7001
  with_provider_model=7001
PROVIDER_REQUEST_META 7001
  with_provider_model=7001
```

The usage/request primitives are real and useful, but they are not correlated to a Brain model decision because no such decision field exists in the Hermes pre-LLM event.

A persistent real Hermes session read-back (`telemetry/agent-performance/hermes-Brain-Dev-20260823_085556_11c840.jsonl`) shows `hermes_session_started` with `model=gpt-5.6-luna`, followed by `hermes_pre_llm_call` with `selected_routes=[]`; it does not show a Brain-selected model or provider handoff.

### Bounded real Hermes CLI attempt

The following bounded persistent Hermes invocation was attempted:

```text
hermes -p validator chat -Q --reasoning none --max-turns 1 --run-budget 60 \
  --in C:/Users/assas/Documents/The-Second-Brain \
  -q 'P2.6 validator probe: reply with exactly P2_6_RUNTIME_PROBE_OK and do not use tools.'
```

Observed result: warning `Unknown toolsets: a2a, second_brain`, then command timeout at 180 seconds with exit code 124. No provider completion or Brain-selected-model effect was proven by this attempt. The timeout is recorded as a blocker to claiming gate 11, not replaced with a mock result.

## 4. Twelve-gate verdicts

| # | Required gate | Verdict | Independent evidence / reason |
|---:|---|---|---|
| 1 | Real Second Brain model-selection decision surface, not post-hoc statistics | **MISSING** | `router.py` selects skills; `crossmodel.py` records caller-supplied model outcomes. No model decision function/table/CLI surface. |
| 2 | Select eligible models/providers using task/risk/cost/capability signals | **MISSING** | `risk.py` scores touched-file risk and `crossmodel.py` stores capabilities/outcomes, but no candidate enumeration/scoring/selection consumes these signals. |
| 3 | Selected model consumed by live harness/runtime | **MISSING** | Hermes adapter registers/carries the supplied `model`/`provider`; `_handle_pre_llm` only computes skill routes and AutoInject. No model handoff to provider invocation. |
| 4 | Deterministic or policy-bounded decision | **PARTIAL** | Skill router and Prime role classification are deterministic; no model-selection decision exists to bound. |
| 5 | Role constraints preserved; workers/coordinators cannot silently escape model policy | **PARTIAL** | Prime role classifier and worker/driver prompt contracts exist and are tested, but no Brain-selected model is enforced at worker/provider launch; worker telemetry frequently reports `model=unknown`. |
| 6 | Explicit deterministic selection-failure fallback | **PARTIAL** | Hermes skill routing has deterministic fail-open `selected_routes=[]` / `routing_error=true`; there is no model-selection failure/fallback model semantics. |
| 7 | Decision correlated to task/session/project identity | **PARTIAL** | Hermes events carry `task_sha256`, session, project, bot role, and supplied model; no model decision ID or selected-model correlation exists. |
| 8 | Telemetry/ledger records selected model, eligible candidates, reason/policy code, fallback | **MISSING** | `hermes_pre_llm_call` has candidate/selected memory IDs and skill routes, but aggregate read-back found zero `selected_model` and zero model-decision fields. Usage telemetry has model/provider/cost but no selection envelope. |
| 9 | Harness-neutral mechanism; Hermes merely consumes the decision | **PARTIAL** | Existing risk, cross-model statistics, AutoInject, ledger, and telemetry primitives are Brain-owned; Hermes adapter is thin. The required Brain model decision is absent, so there is nothing for Hermes to consume. |
| 10 | No Hermes-native router/duplicate policy mistaken for Second Brain routing | **PROVEN** | `driver-orchestrator.ts` is explicitly Hermes/Prime-native active-model role policy; `router.py` is explicitly a Brain skill router. The audit keeps these surfaces separate and does not treat the host role prompt as Brain model routing. |
| 11 | Persistent Hermes execution proves Brain model decision changes/constrains actual model | **MISSING** | Existing persistent Hermes records show host-supplied models and Brain AutoInject/skill events, not a Brain-selected model. The bounded live CLI attempt timed out before provider completion. |
| 12 | Token/cost/risk telemetry sufficient for later optimization without P4 self-optimization | **PARTIAL** | `assistant_usage` and `provider_request_meta` have token/cost/model/provider fields (7,001 records each); deterministic `risk.py` exists. They lack model-decision attribution, candidate/fallback, and reason/policy fields, so they are not yet sufficient for P2.6 routing optimization analysis. |

## 5. Overall verdict and smallest missing seam

### Overall: **MISSING**

The current system has substantial adjacent primitives:

- deterministic task-to-skill routing;
- caller-recorded model profiles and model/skill outcome statistics;
- deterministic risk assessment;
- Hermes identity/session/project binding;
- bounded AutoInject/VMem/ledger/telemetry;
- Hermes/Prime-native role classification and worker policy;
- token/cost/provider usage records.

Those primitives do **not** establish P2.6. The controlled same-task/two-model probe is decisive: changing the supplied model/provider changed only the host identity metadata; Brain returned the same packet and no selected model/provider decision.

### Smallest exact missing seam (do not implement in this audit)

A Brain-owned, harness-neutral **model decision envelope and invocation handoff** is missing. The minimum seam must:

1. receive the task plus existing risk/cost/capability and role constraints;
2. deterministically/policy-boundedly enumerate eligible model/provider candidates;
3. return one bounded decision containing at least decision ID, task hash, session/project identity, role, eligible candidates, selected model/provider, reason/policy code, and deterministic fallback (or explicit failure);
4. be consumed by the Hermes/provider invocation rather than merely logged; and
5. persist the same decision envelope in ledger/telemetry so actual usage can be joined to the decision.

This is the smallest P2.6 seam. It is not a request to begin P3 self-optimization, add a Hermes-native router, duplicate memory, or redesign existing Brain primitives.

**STOP:** Evidence persisted and independently read back. No implementation was changed by this validator audit.
