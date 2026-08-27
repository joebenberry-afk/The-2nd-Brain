# P3.16 Modular Skill Visibility — Design Specification

Close the frozen P3.16 seam identified by qualification: `router.py`'s
sparse top-K shadow router (plan §56/§113) is proven, but no harness
consumes its selection to restrict which skills' full instructions are
exposed. This spec adds exactly the missing visibility-gate boundary.
Preserve P3.1–P3.15 (including P3.15's evidence-provenance hardening) and
Lean `candidate / HOLD_SHADOW`. Do not begin P3.17. Do not redesign
`router.py`'s scoring/shadow-comparison algorithm.

## Frozen invariants (verbatim from the accepted instruction)

- sparse top-K = 0–3 specialist skills
- do not load/expose all specialist skills
- descriptor-first
- JIT full instructions
- shadow route first
- compare model-natural routing vs Brainstem routing
- acceptance = lower trigger noise + no success regression
- universal/local harness-neutral core

## Scope boundary (stated explicitly, not silently assumed)

The omp/Claude host's own native skill catalog (name+description list with
on-demand `read(skill://name)`) is a host platform feature this repository
does not own and cannot suppress or override. This spec's provable claim is
therefore scoped to **Brain-owned injected content**: the same channel
AutoInject already uses to prove bounded memory-packet exposure (P0.4).
"Effective model input" in every acceptance test below means the content
the Brain itself injects via that channel, not the totality of everything a
host's own independent tool-use could theoretically retrieve. This mirrors
requirement 6's own framing ("OMP should only be a thin transport/injection
consumer... preserve existing system-prompt/cache structure where
practical") and requirement 11 ("OMP should only be a thin transport/
injection consumer").

## Architecture

One new harness-neutral core module plus two thin adapter extensions,
reusing every existing primitive named in the accepted instruction.

```
task ──► skills.py: descriptors()        (discover eligible + bounded descriptors)
              │
              ▼
        router.route()                   (existing, UNCHANGED — proven shadow router)
              │
              ▼
task ──► skills.py: build_plan()         (revalidate eligibility, cap ≤3, build VisibilityPlan)
              │
              ├──► skills.py: hydrate()  (JIT-read full SKILL.md for selected+eligible only)
              │
              ▼
        VisibilityPlan (bounded, ledger/telemetry-safe — no raw bodies)
              │
      ┌───────┴────────┐
      ▼                ▼
omp_adapter.py    hermes_adapter.py
(operation:       (_visibility_task, alongside
 "skill_visibility")   existing _route_task)
      │                │
      ▼                ▼
visibility-bridge.ts   (existing Hermes host consumes
(new, mirrors          the returned hydrated text same
worker-context-bridge  as it already consumes vmem_context)
 .ts pattern)
      │
      ▼
index.ts: inject hydrated specialist text as a bounded
custom_message at the existing pre-model hook, same
pattern as the AutoInject packet injection
```

### `src/second_brain/skills.py` (new, harness-neutral)

Single responsibility: turn one proven router decision into a bounded,
lifecycle-revalidated visibility plan, and JIT-hydrate only the skills that
plan names. **Not a registry** — it reads the same
`skills/{active,candidate,shadow}` directories and the same
`skillforge.read_metadata`/`skillforge.lifecycle_content_hash` primitives
`router.py` already uses; it stores no independent skill state.

Public functions:

- `eligible_skills(home) -> list[EligibleSkill]` — one entry per skill
  under `paths.SKILL_LEVEL_DIRS` (`active`, `candidate`, `shadow` — same
  pool `router.py` scores), each with `name`, `lifecycle_state`,
  `content_hash` (via `skillforge.lifecycle_content_hash`, `None` if
  unreadable), and `path`.
- `descriptors(home) -> list[Descriptor]` — one bounded descriptor per
  eligible skill: `skill_id`, `lifecycle_state`, `content_hash`,
  `descriptor_text` (frontmatter `name`/`version` from
  `skillforge.read_metadata` plus the first `_DESCRIPTOR_TEXT_MAX_CHARS`
  (240) characters of the skill's own `# Purpose` section body — a small
  local section-slice helper, not a reimplementation of `router.py`'s
  scoring section parser), and `descriptor_ref` (`sha256` of
  `descriptor_text`, truncated to 16 hex chars). Descriptors never include
  any other section's content.
- `build_plan(home, task, *, session_id, project_id, max_active=None, mode=None) -> VisibilityPlan`
  — calls `router.route(home, task, max_active=max_active)` **unchanged**
  (when `max_active` is `None`, `router.route` resolves its own
  `config/skills.toml [router].max_active` default exactly as it does
  today — `skills.py` never re-reads that key); builds the canonical
  result (fields below); independently re-caps `selected_skill_ids` at the
  fixed frozen-invariant constant `_MAX_SPECIALIST_SKILLS = 3` (defense in
  depth against any out-of-contract caller, per requirement 3's literal
  "0–3" bound — deliberately not re-deriving `router`'s own config-driven
  cap, to avoid coupling `skills.py` to `router.py`'s private
  `_router_max_active` helper); revalidates each selected skill's current
  lifecycle/content hash against `eligible_skills(home)` computed in the
  same call (closes the TOCTOU window described in requirement 8's
  stale-selection control); skills failing revalidation go to
  `rejected_skill_ids` with a reason and are excluded from hydration.
- `hydrate_plan(home, plan) -> HydratedPlan` — for each id in
  `plan.selected_skill_ids` that passed revalidation, JIT-read the full
  `SKILL.md` text once (dedup on repeat ids), computing
  `hydrated_skill_ids` (only ids that both selected and hydrated
  successfully) and returning `{skill_id: full_text}` **kept only in the
  return value — never passed to any ledger/telemetry writer**. A read
  failure moves that id from selected to `unavailable_skill_ids`, never
  raises.
- `plan_to_evidence(plan) -> dict` — the bounded, JSON-safe, ledger/
  telemetry-safe projection (below); contains no raw skill body text.

### Canonical `VisibilityPlan` fields (per accepted instruction)

```
visibility_plan_id        sha256("{task}|{session_id}|{project_id}|{sorted(selected)}")[:16], prefixed "vplan-"
task_hash                 sha256(task) — task text itself never stored
session_id / project_id   as given
router_decision_hash      sha256(canonical_json({"selected": selected, "scores": scores}))
eligible_skill_ids        sorted names from eligible_skills(home)
descriptor_refs           {skill_id: descriptor_ref} for every eligible skill
selected_skill_ids        router's selected list, re-capped at max_active (0–3)
hydrated_skill_ids        subset of selected_skill_ids that passed revalidation + hydration
rejected_skill_ids        {skill_id: reason} — stale / retired / hidden / unknown / duplicate-collapsed
unavailable_skill_ids     {skill_id: reason} — selected + eligible but hydration read failed
mode                      "shadow" | "enforced"
descriptor_chars / descriptor_tokens     summed over ALL eligible descriptors
hydrated_chars / hydrated_tokens         summed over hydrated bodies only
avoided_full_chars / avoided_full_tokens summed over eligible-but-NOT-hydrated full bodies
created_at                 UTC ISO-8601
```

`descriptor_tokens`/`hydrated_tokens`/`avoided_full_tokens` reuse
`autoinject.token_estimate` (existing 4-chars/token estimator) — no new
estimator.

### Mode and config

`config/skills.toml [visibility] mode = "shadow"` (new key, same
`tomllib`-read-with-fallback pattern as `_router_max_active`; invalid/
absent → `"shadow"`, fail-safe). `build_plan`'s `mode` parameter, when
`None`, resolves from this config; an explicit `mode` argument (used only
by the controlled current-OMP-primary evaluation harness, requirement 5)
overrides it. This is the two-phase shadow → enforcement switch: shadow
mode computes and records the full plan but callers must not use
`hydrated_skill_ids` to withhold anything (existing exposure unchanged);
enforced mode is the actual gate — callers use `hydrate_plan`'s output as
the sole specialist-instruction content and do not also expose unselected
bodies through the Brain-owned channel.

### Fail-closed / negative-control behavior (requirement 8)

- **Unselected skill**: appears in `descriptor_refs` (routing-visible), not
  hydrated. No code path adds it to `hydrated_skill_ids`.
- **Stale selection** (skill's content hash or lifecycle state changed
  between `build_plan` and `hydrate_plan`): `build_plan` computes
  `eligible_skills` fresh on every call; `hydrate_plan` re-reads the file
  and compares the hash it hydrates against the hash recorded in the plan
  — mismatch moves the id to `unavailable_skill_ids` with reason
  `"stale_content_hash"`, never hydrates the changed body.
- **Retired/hidden/ineligible skill**: not present in `eligible_skills`
  (only `active`/`candidate`/`shadow` directories are scanned, matching
  `router.py`'s own pool) — a router selection naming it (should not
  happen since the router only selects from the same pool, but defensive)
  is rejected with reason `"not_eligible"`. No lifecycle mutation ever
  occurs from this module.
- **Unknown skill ID**: same `"not_eligible"` fail-closed path.
- **Duplicate selection**: `build_plan` de-duplicates
  `selected_skill_ids` before capping; `hydrate_plan` hydrates each unique
  id once.
- **Router failure**: `build_plan` lets `router.route`'s existing
  exceptions propagate to the caller (`omp_adapter`/`hermes_adapter`
  already catch broadly and fail open on `selected_routes = []`/plan
  omitted) — the safety fallback is **zero specialist skills**, never
  "load every skill." This matches `hermes_adapter._route_task`'s existing
  fail-open contract; `skills.py` does not invent a different one.
- **`>3` impossible**: `build_plan` truncates `selected_skill_ids` to
  `max_active` unconditionally, regardless of what the router or caller
  handed it, and records the truncated ids as `rejected_skill_ids` with
  reason `"over_cap"`.

No raw skill body content, and no full task text, is ever passed to
`autoinject._append_telemetry` or any ledger writer — only
`plan_to_evidence(plan)` (bounded refs/hashes/counts) and, in the OMP/
Hermes adapters, the bounded response fields already used for
`selected_routes` today.

### `omp_adapter.py` extension

Add one branch to `handle_request`, parallel to the existing
`operation == "worker_context"` branch:

```python
if payload.get("operation") == "skill_visibility":
    try:
        return _prepare_skill_visibility(Path(home), payload)
    except Exception:
        return {"visibility_plan": None, "error": "VISIBILITY_UNAVAILABLE"}
```

`_prepare_skill_visibility` builds and hydrates the plan, returns
`{"visibility_plan": plan_to_evidence(plan), "hydrated_instructions": {skill_id: full_text}}`
over the same bounded stdout transport `omp-routing` already uses (fail
open to `{"visibility_plan": None, ...}` on any error — same shape family
callers already branch on for `decision: None`).

### `visibility-bridge.ts` (new, mirrors `worker-context-bridge.ts`)

Same `execFile("python", ["-m", "second_brain", "autoinject", "omp-routing"], ...)`
transport (existing CLI entrypoint — no new subcommand), JSON on stdin
with `operation: "skill_visibility"`, bounded/timeout/fail-open exactly
like `runOmpRouting`. Exports `runOmpVisibility(options) -> Promise<OmpVisibilityResult>`.

### `index.ts` wiring

At the same pre-model hook the AutoInject packet already uses
(`before_agent_start`/existing `autoinjectCall` site), call
`runOmpVisibility` alongside the existing routing call, and when
`hydrated_instructions` is non-empty, inject it as one additional bounded
`custom_message` block (same delivery mechanism as the memory packet),
labeled distinctly so it is attributable in telemetry. In shadow mode the
call still runs (for shadow-vs-natural comparison evidence) but its result
is never injected — existing behavior is unchanged, matching requirement 5.

### `hermes_adapter.py` extension

Alongside the existing `_route_task` call in `_handle_pre_llm`, add
`_visibility_task(home, task, session_id, project_id, mode)` that calls
`skills.build_plan`/`hydrate_plan` the same way, folds
`plan_to_evidence(plan)` into `event_payload`/`selected_routes`'s sibling
fields (bounded, no bodies), and — only when `mode == "enforced"` — extends
the returned `packet` the same way `vmem_context` extends it today, so the
Hermes host's own effective-input assembly includes the hydrated
specialist text. Shadow mode leaves `packet` untouched (existing Hermes
behavior fully preserved, matching requirement 5's "keep current
production exposure behavior unchanged" for the shadow phase).

## Two-phase shadow → enforcement proof (requirement 5)

1. **Shadow phase** (default `config/skills.toml [visibility] mode`):
   run the existing `router.eval_router` fixture-based comparison
   (already proven — reused unchanged) plus a fresh current-OMP-primary
   shadow run recording natural vs Brain selection, expected visibility
   plan, and trigger/noise metrics, with zero change to what's exposed.
2. **Controlled enforced phase**: only after (1)'s acceptance
   (`router f1 >= natural f1`, no success regression) holds on the fresh
   run, flip `mode="enforced"` for one bounded current-OMP-primary
   evaluation session and prove exposure restriction directly (below).
   This does not globally change `config/skills.toml`'s default — the
   shipped default stays `"shadow"` unless a later, separate promotion
   decision changes it (out of this spec's scope; matches "do not
   globally promote a poorly performing router merely to close P3.16").

## Proving provider/model-visible restriction (requirement 7)

For the controlled enforced-mode OMP-primary session, capture the actual
`custom_message`/packet text the extension injects (already observable —
`index.ts`'s injected content is deterministic and visible in the
extension's own telemetry mirror) and independently verify, using bounded
`descriptor_ref`/content-hash markers (never full bodies) already present
in `plan_to_evidence`:
- selected skill A's `content_hash` marker is present in the injected text
- unselected skill B's `content_hash` marker is absent from the injected
  text
- run four probes: 0, 1, 2, 3 selected, confirming `hydrated_skill_ids`
  count matches exactly, and one probe forcing `>3` router-adjacent input
  to confirm the cap rejects the excess.

## Economics (requirement 9)

`plan_to_evidence` already carries `descriptor_tokens`, `hydrated_tokens`,
`avoided_full_tokens`. The dogfood step aggregates these across the probe
session alongside existing telemetry counters (`model_calls`, `tool_calls`,
wall time — already captured by existing sensors) and reports
`avoided_full_tokens` as the primary savings metric, distinct from
provider prompt-cache hit rate (a separate, already-measured concern).

## Testing

- `tests/test_skills.py` (new — the frozen matrix's named, previously
  missing file): `eligible_skills`/`descriptors` discovery and bounding;
  `build_plan` re-cap/dedup/revalidation and every negative control in
  requirement 8; `hydrate_plan` stale-hash and unavailable-read paths;
  `plan_to_evidence` never contains raw body text or full task text;
  config `[visibility] mode` fallback.
- `tests/test_omp_adapter.py` (existing file, if present — else add
  focused cases there) for the new `skill_visibility` operation branch.
- `tests/test_hermes_adapter.py` (existing) for `_visibility_task`
  shadow-vs-enforced packet behavior.
- `brainstem/prime-extension/tests/visibility-bridge.test.ts` (new,
  mirrors `worker-context-bridge.test.ts`) and an `index.ts` wiring test
  asserting shadow mode never injects, enforced mode injects exactly the
  hydrated text.

## Out of scope for this spec

- Changing `router.py`'s algorithm, `max_active` default, or its existing
  advisory consumers (`credit.py`, `model_routing.py`, `cli.py`).
- Flipping the shipped default `[visibility] mode` to `"enforced"` — that
  is a separate promotion decision gated on the two-phase proof above.
- Any change to Lean's `candidate/HOLD_SHADOW` state or P3.1–P3.15
  behavior.
- P3.17.
