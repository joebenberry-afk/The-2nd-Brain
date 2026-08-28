# P2.6 Intelligent Model Routing — Stage 0 Seam Map

**Validator:** Brain-Validator (`bot_role=validator`)  
**Read-back date:** 2026-08-23  
**Scope:** Stage 0 architecture/runtime read-back only.  
**Implementation changes:** none by this audit.  
**Evidence authority:** current repository/runtime read-back outranks prior reports and chat claims.

## 1. Plan and frozen contract read-back

The supplied plan was read from:

```text
C:/Users/assas/Downloads/GPTs plans/P2_6_INTELLIGENT_MODEL_ROUTING_PLAN.md
```

Its frozen contract requires all of the following before `P2.6_PROVEN`:

1. A real Brain model-selection decision surface.
2. Eligibility from task, risk, cost, capability, and role signals.
3. Selected model consumed by the live runtime.
4. Deterministic or policy-bounded selection.
5. Role constraints enforced through model routing.
6. Deterministic explicit fallback.
7. Task/session/project correlation.
8. Decision and outcome telemetry/ledger correlation.
9. Harness-neutral Brain decision; Hermes is a consumer.
10. Hermes-native routing remains distinct.
11. Persistent Hermes proof that Brain changes the actual model used.
12. Token/cost/risk telemetry sufficient for later optimization.

Economic boundary: premium escalation only when justified. The Brain must choose
among allowed models and must not rewrite its own routing policy.

The plan’s Stage 0 hard-stop rule is also binding for this audit: if a supported
runtime handoff cannot consume a per-task Brain decision, report
`P2_6_RUNTIME_HANDOFF_BLOCKED` rather than simulate live proof.

## 2. Repository identity at Stage 0

Read-only command used:

```text
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --stat
git diff --name-only
```

Observed state before this seam-map write:

```text
root   = C:/Users/assas/Documents/The-Second-Brain
branch = brain/v1-rc4-prime-074-compat
HEAD   = 0bc2b8d56ceed3c1e17576283f05b4dba6f52d91
status = branch ahead 8; existing tracked and untracked changes present
```

Existing tracked modifications at read-back:

```text
brainstem/telemetry/SCHEMA.md
outputs/reports/rc2/01-frozen-roadmap-matrix.md
src/second_brain/cli.py
src/second_brain/contracts.py
src/second_brain/vmem.py
tests/test_orchestration.py
```

Existing untracked surfaces included the Hermes adapter, prior Hermes/P0-P2
reports, `src/second_brain/hermes_adapter.py`, `src/second_brain/worker_protocol.py`,
and their tests. These pre-existing changes are not attributed to this Stage 0
read-back. This report itself is the only evidence file added by this action.

## 3. Canonical implementation surface map

| Concern | Canonical surface | Read-back finding | P2.6 relevance |
|---|---|---|---|
| Task/skill routing | `src/second_brain/router.py:239` (`route`) | Deterministic skill scoring and bounded selected skill names; no provider/model candidate selection. | Adjacent primitive only; not a model selector. |
| Model profiles/outcomes | `src/second_brain/crossmodel.py:46`, `:82`, `:159`, `:241` | `record_model` upserts free-text model profile/family/capabilities; `record_skill_outcome` is caller-recorded; reports aggregate outcomes and transfer/policy stats. | Post-hoc statistics; no selection decision, availability, price, provider, or fallback semantics. |
| Risk | `src/second_brain/risk.py:171` (`assess_risk`) | Explainable file-touch risk score with LOW/MEDIUM/HIGH/CRITICAL levels and nine signals. | Reusable input signal; no model-tier mapping or selection. |
| Identity binding | `src/second_brain/hermes_adapter.py:148` (`resolve_binding`) | Maps bot, role, Hermes session, Brain session, project, repo, branch, provider, and model. Provider/model are observed from host payload. | Strong correlation substrate; not a model decision. |
| Brain pre-LLM adapter | `src/second_brain/hermes_adapter.py:943` (`_route_task`), `:1154` (`_handle_pre_llm`) | Calls `router.route`; prepares AutoInject/VMem context; returns `selected_routes` (skills), packet, and identity metadata. | Current routing is skill/context routing, not model routing. |
| Hermes plugin | `brainstem/adapters/hermes/hermes_plugin.py:419` (`pre_llm_call`) | Calls `autoinject hermes-hook`; returns only `{"context": ...}` assembled from Brain packet/VMem text. | Current plugin does not return or apply a model/provider decision. |
| Plugin manifest | `brainstem/adapters/hermes/plugin.yaml:9` | Declares lifecycle hooks and tools; no model-routing decision or middleware registration. | Confirms current installed adapter contract is context/lifecycle only. |
| Canonical session ledger | `src/second_brain/ledger.py:93-168`, `:256` | SQLite ledger has `agents`, `request_epochs`, and `request_fingerprints` with provider/model fields, role, hashes, and identity. | Reusable persistence/correlation path; no `model_routing_decision` event/contract exists. |
| Brain telemetry | `src/second_brain/telemetry.py:14-43`; `brainstem/telemetry/SCHEMA.md:39-53` | Generic usage/request/response metadata and Hermes pre-LLM identity records exist. | Reusable token/cost/provider/model telemetry; no selected candidates, decision ID, reason/policy code, or fallback lifecycle. |
| Role policy | `brainstem/policies/driver-orchestration.md:12-23`; `brainstem/prime-extension/src/driver-orchestrator.ts:29-107` | Role is resolved from the already-active model; driver/worker/hard-orchestrator are classification and prompt-contract behavior. | Role signal/constraint source; not model selection. |
| Skill config | `config/skills.toml:25-28` | `[router].max_active` is enforced for skill selection only. | No model-tier/provider policy. |
| Orchestration policy | `brainstem/policies/driver-orchestration.md:40-57`, `:63-84` | Advisory cheapest-competent-worker ladder and documented model substrings; no provider invocation control. | Documentation/policy input only; must not be mistaken for live model routing. |

## 4. Live Hermes provider/runtime surface map

The installed Hermes runtime was inspected under:

```text
C:/Users/assas/AppData/Local/hermes/hermes-agent
```

### 4.1 Current per-turn route

`hermes_cli/cli_agent_setup_mixin.py:291-337` (`_resolve_turn_agent_config`)
constructs the effective turn route from the session’s primary `self.model` and
provider. Its own docstring says each turn uses the session primary model; its
only request override today is the `/fast` service-tier override.

`hermes_cli/cli_agent_setup_mixin.py:339-544` (`_init_agent`) accepts
`model_override`, `runtime_override`, and `request_overrides`, then constructs
`AIAgent(effective_model, provider, ...)`. This is a supported route-construction
seam, but the current Second Brain plugin does not call it.

### 4.2 Actual provider request

`agent/chat_completion_helpers.py:1825-2111` (`build_api_kwargs`) builds the
request from `agent.model` and `agent.provider`. The transport receives
`model=agent.model`; `agent/transports/chat_completions.py:451-703` builds the
provider kwargs and permits a final `request_overrides` merge. The request is
then dispatched by `agent/chat_completion_helpers.py:926-999`; the default path
calls `request_client.chat.completions.create(**api_kwargs)`.

Therefore the invariant that must be proven later is:

```text
Brain selected provider/model
  == effective Hermes request provider/model
  == provider/runtime metadata provider/model
```

unless an explicit, recorded fallback changes the pair.

### 4.3 Existing observer hooks are insufficient

Hermes’ local plugin documentation and source define:

- `pre_llm_call` as context injection; its returned context is appended to the
  user message.
- `pre_api_request` as an observer around the raw request; its return value is
  ignored.

`agent/conversation_loop.py:3020-3084` invokes `pre_api_request` after request
kwargs are already built and does not assign callback results back to the
request. `hermes_cli/plugins.py:5215-5258` documents `pre_llm_call` return values
as `{"context": ...}` (or a string), not a model/provider route.

The current Second Brain plugin therefore cannot achieve P2.6 by changing only
its existing `pre_llm_call` return value.

### 4.4 Supported generic behavior-changing handoff

Hermes does expose a generic, harness-level middleware seam:

- `hermes_cli/middleware.py:20-34`: `LLM_REQUEST_MIDDLEWARE = "llm_request"`.
- `hermes_cli/middleware.py:77-117`: `apply_llm_request_middleware` accepts
  `{"request": {...}}` and replaces effective provider kwargs before dispatch.
- `hermes_cli/plugins.py:3308-3332`: `PluginContext.register_middleware` registers
  behavior-changing middleware.
- Local Hermes plugin documentation states `llm_request` receives
  `request/original_request` and may return `{"request": {...}}` before the
  provider sends it.

This is a supported generic handoff, not a Hermes-native model policy engine.
It can carry a Brain-owned selected `model` and `provider` in the already-built
request, subject to adapter-local deterministic provider/model translation and
credential/runtime validation. The current Second Brain plugin does **not**
register this middleware, so the handoff is feasible but presently unwired.

## 5. Answers to the plan’s ten Stage 0 questions

1. **Existing model quality/statistics:**
   `crossmodel.py` stores model profiles and caller-recorded model/skill/task
   outcomes, then reports aggregates and transfer/policy statistics. It is not a
   selector and has no provider/cost/availability semantics.

2. **Existing task/risk/capability signals:**
   `router.route` supplies deterministic task-to-skill signals; `risk.assess_risk`
   supplies explainable file-touch risk; `crossmodel.record_model` stores a free
   text capabilities field. No existing composition converts these into a model
   candidate set.

3. **Canonical role-policy source:**
   `brainstem/policies/driver-orchestration.md` plus the pure resolver in
   `brainstem/prime-extension/src/driver-orchestrator.ts`. They classify the
   active model and constrain orchestration behavior; they do not select it.

4. **Where provider/model availability and identity are known:**
   Hermes knows the active provider/model in `AIAgent`, runtime provider
   resolution, provider registry/profile, and the built request kwargs. The Brain
   adapter records the host-supplied pair in `HermesBinding`, ledger agents,
   request epochs/fingerprints, and telemetry. The Brain model profile table is
   not an authoritative availability/cost registry.

5. **Where real Hermes provider invocation is selected:**
   The CLI turn route (`_resolve_turn_agent_config`), agent construction
   (`_init_agent`), request construction (`build_api_kwargs`/transport), and
   dispatch (`_dispatch_nonstreaming_api_request`) own actual invocation.

6. **Can live Hermes accept a per-request provider/model override?**
   Yes, through the generic `llm_request` middleware rewrite of provider kwargs,
   or through the route/agent `model_override` path when the caller controls
   agent initialization. The Second Brain pre-LLM hook currently uses neither.

7. **Narrowest supported handoff:**
   A thin adapter registration of Hermes `llm_request` middleware that obtains a
   bounded Brain `ModelDecision` by task/session/project/role identity and
   rewrites only the effective request’s provider/model fields. It must preserve
   the original request for correlation and use explicit failure/fallback rules.

8. **Existing telemetry/ledger path:**
   Use existing Brain `LedgerStore` lifecycle/request tables and
   `autoinject._append_telemetry`/`telemetry.py` JSONL. Additive routing lifecycle
   records should reuse those paths rather than create a subsystem.

9. **What stays harness-neutral:**
   Candidate modeling, eligibility, risk/cost/capability/role policy, deterministic
   ordering, decision/fallback envelope, identity correlation, and decision
   telemetry belong to Second Brain. Hermes should only consume the selected
   provider/model via generic middleware and expose actual request/result metadata.

10. **Boundary against P4 and Hermes-native routing:**
    Hermes’ OpenRouter/provider-routing configuration ranks underlying providers
    for an already-selected model and Hermes runtime fallback chains handle host
    mechanics. Those are not the Brain decision. P2.6 must not duplicate them or
    autonomously learn/rewrite policy; later optimization is out of scope.

## 6. Stage 0 result

```text
P2_6_STAGE0_SEAM_MAP_COMPLETE
```

The runtime handoff is **not** currently wired, but it is supported by Hermes’
generic `llm_request` middleware. Therefore the correct Stage 0 disposition is:

```text
P2.6 implementation seam: FEASIBLE_BUT_UNWIRED
P2_6_RUNTIME_HANDOFF_BLOCKED: NO
```

This is not P2.6 qualification. No Brain model decision, candidate selector,
explicit fallback, decision telemetry, or selected==actual persistent proof has
been established by Stage 0.

## 7. Exact next gate (no implementation by Validator)

Brain-Integrator/Brain-Dev must, under the supplied plan and without starting P3:

1. define the bounded, deterministic, harness-neutral `ModelDecision` contract;
2. compose existing task/risk/capability/role/statistics primitives into eligibility
   and policy-bounded selection;
3. add deterministic explicit fallback semantics;
4. wire the decision through the generic Hermes `llm_request` middleware seam;
5. persist decision/invocation/fallback lifecycle through existing ledger/telemetry;
6. add focused tests, then perform real persistent Hermes probes;
7. hand the changed surfaces and canonical evidence to Brain-Validator.

Validator will not implement or silently repair this seam. The next validator gate
is independent verification of changed code plus persistent Probe A/B/C/D and
selected-provider/model == actual-provider/model read-back.
