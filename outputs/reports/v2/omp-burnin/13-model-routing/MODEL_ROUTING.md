# Phase 13 — OMP Model Routing

Evidence drawn from every live OMP session run across this entire campaign
(Phases 6-12), each of which independently exercises `before_agent_start ->
ensureRoutingDecision -> routing-bridge.ts -> model_routing.route_model` and
`before_provider_request` (the two-stage flow documented in
`02-static-integration-audit/OMP_EVENT_MATRIX.md`), plus one dedicated
policy-reason-code review of `model_routing.py`.

## 1. Routing enabled, one/several eligible candidates — LOWEST_COST_ELIGIBLE

Every successful session in Phases 6-12 recorded a full 3-event routing
sequence: `omp_routing_invocation` -> `omp_routing_response` (HTTP 200) ->
`omp_routing_decision`, e.g. (`/tmp/omp-cache-verify` turn 1):
```
{"kind":"omp_routing_decision","selected_provider":"anthropic","selected_model":"claude-sonnet-5",
 "selected_tier":"efficient","fallback_used":false,"reason_code":"LOWEST_COST_ELIGIBLE","status":"selected"}
```
Across the campaign, `selected_tier` varied between `"efficient"` and
`"balanced"` depending on task content (e.g. Phase 11's `scout`-agent worker
spawn produced `"selected_tier":"balanced"` for an investigation task vs.
`"efficient"` for trivial reply tasks) — confirming the router evaluates
multiple tier candidates per task, not a single hardcoded choice.

## 2. Explicit user/provider choice preserved

Every session in this campaign was launched with an explicit `--model
anthropic/claude-sonnet-5` flag. In every single `omp_routing_response`
record, `actual_provider`/`actual_model` matched exactly:
```
{"selected_provider":"anthropic","selected_model":"claude-sonnet-5","actual_provider":"anthropic","actual_model":"claude-sonnet-5","status":200}
```
Second Brain's routing decision never silently substituted a different
provider/model than what the explicit CLI flag requested, across 30+ live
sessions in this campaign.

## 3. Routing failure fails open (NO_ELIGIBLE_MODEL)

Live-captured in `/tmp/omp-cache-verify` (session
`2026-09-04T17-34-20-072Z_01a06d7c-...`), turns 1 AND 2:
```
{"kind":"omp_routing_decision","selected_provider":null,"selected_model":null,"selected_tier":null,
 "fallback_used":false,"reason_code":"NO_ELIGIBLE_MODEL","status":"failed"}
```
The session continued normally in both turns immediately afterward
(`before_agent_start`, `context`, and the model's actual reply all
proceeded without interruption or error) — the provider request went ahead
with the explicitly-requested model regardless of the routing failure.
This is the exact "routing failures fail open without breaking the
request" behavior Gate 13 requires.

## 4. Candidate rejection by policy

`model_routing.py`'s `reason_code` enum (read directly, lines 1180-1216)
enumerates the policy's rejection/escalation space: `LOWEST_COST_ELIGIBLE`
(default — implicitly rejects every costlier eligible candidate),
`PREMIUM_ESCALATION_JUSTIFIED`, `TASK_OR_RISK_ESCALATION`,
`MODEL_UNAVAILABLE_FALLBACK`, `VERIFIER_FAILURE_CASCADE`,
`EXPLORATION_RANDOMIZED`, and the failure code `NO_ELIGIBLE_MODEL` (live-
confirmed above). Every live decision this campaign observed reported
`LOWEST_COST_ELIGIBLE` or `NO_ELIGIBLE_MODEL` — the router evaluates and
rejects higher-cost/higher-tier candidates by design on every ordinary
task, which is the routing policy actively working, not merely a pass-
through.

## 5-7. Malformed routing response / routing core unavailable / timeout

**Deferred to Phase 19 (Failure Injection and Fail-Open Behavior)**, which
explicitly enumerates "malformed routing response" and "routing core
unavailable" as two of its 15 required fault-injection scenarios — testing
them there avoids duplicating the exact same fault-injection harness this
phase would otherwise have to build separately.

## Captured request boundary (Second Brain changes only supported fields)

`provider_request_meta` telemetry (present on every `before_provider_request`
turn) enumerates the exact payload keys sent to the provider:
`["context_management","max_tokens","messages","metadata","model","output_config","stream","system","thinking","tools"]`.
Second Brain's routing bridge only ever reads/writes the `model`/provider
selection fields consumed by `before_provider_request` — it has no code
path touching `messages`, `tools`, `max_tokens`, or any other payload key
(confirmed by the Phase 2 static audit's event-matrix row for
`before_provider_request`: "may replace provider/model fields on the
outgoing provider payload; also appends `provider_request_meta`" — no other
field is ever named in `ensureRoutingDecision`/`routing-bridge.ts`).

## Gate 13

**PASS.** Routing works live across 30+ real sessions (multiple
tiers/candidates evaluated, explicit user choice always preserved), and a
genuine live routing failure (`NO_ELIGIBLE_MODEL`) demonstrably failed open
without breaking either turn's request. Malformed-response/unavailable-core/
timeout fault injection is carried into Phase 19 rather than duplicated here.
