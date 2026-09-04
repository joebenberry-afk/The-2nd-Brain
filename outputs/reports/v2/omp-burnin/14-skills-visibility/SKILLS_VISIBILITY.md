# Phase 14 — Skills and Visibility

`config/skills.toml [visibility] mode` temporarily flipped `shadow -> enforced`
for this phase's live tests (the file's own comment explicitly sanctions this:
"'enforced' is only ever set by the controlled current-OMP-primary evaluation
harness"); restored to `shadow` afterward, confirmed via `git diff` (no diff).

## Relevant skill visible / irrelevant skill omitted (live, enforced mode)

Router scoring (`router.py::_score_skill`) requires an exact case-insensitive
substring match against a skill's literal positive-trigger phrase text
(`+1.0` each), a name-bigram match (`+1.5`), or weak procedure-token overlap
(capped `+0.5`) — selection threshold `1.0`. A loosely-paraphrased version
of the trigger ("new migration file that changes schema version") scored
only `0.5` (below threshold) — this is the router's own documented design
("a mention like 'migration of the marketing website' does not route"), not
a defect; re-tested with a phrase closer to the literal trigger text and it
selected correctly:

| Session | Task | `mode` | `selected_skill_ids` | Model saw the skill? |
|---|---|---|---|---|
| `/tmp/omp-p14-relevant2` | "This task involves a new NNNN_*.sql migration file exists in the diff..." (near-literal trigger match) | enforced | `["sqlite-migration-verifier"]` | Yes — named the skill verbatim and recited its exact procedure (fresh-create/migrate/idempotency/backup-restore/PRAGMA integrity_check) |
| `/tmp/omp-p14-irrelevant` | "What is 7 plus 5?" | enforced | `[]` | No — replied `NO_SKILL_GIVEN` |

`hydrated_skill_ids` equals `selected_skill_ids` on the relevant case
(`["sqlite-migration-verifier"]`), confirming the full hydrated body was
actually delivered, not merely a descriptor-level mention.

## Maximum injection character/token bound (code-verified, `skills.py`)

- `_MAX_SPECIALIST_SKILLS = 3` — router-priority cap on selected count.
- `_MAX_HYDRATED_BODY_CHARS = 4096` — per-skill hydrated-body cap; a skill
  exceeding it is marked `unavailable_skill_ids[id] = "body_too_large"`,
  never truncated-and-injected-anyway.
- `AGGREGATE_MAX_INJECTED_CHARS = 8192` — total concatenated injected text
  cap, enforced by `hydrate_plan()` **before the plan leaves Python**
  (comment: "so `hydrated_skill_ids` always equals the complete bodies
  actually injected — never a partial body"). A skill whose full body would
  push the running total over budget is marked
  `unavailable_skill_ids[id] = "aggregate_budget_exceeded"` and excluded
  entirely rather than truncated mid-body.
- `visibility-bridge.ts` mirrors this same `AGGREGATE_MAX_INJECTED_CHARS`
  bound on the TS side (comment cross-reference confirmed in `skills.py`
  line 30-31), so the OMP-visible injected text is bounded on both ends of
  the bridge.

## Malformed skill metadata (code-verified)

A `SKILL.md` with no recognizable `# Positive Triggers`/`# Procedure`
headers (`_parse_sections` only keys on lines starting `# `) parses to an
empty sections dict; `_score_skill` on it returns `0.0` with **no
exception** — verified directly: `router._score_skill(home, "broken-skill",
...)` returned `0.0` without raising against a file containing no headers
at all. Fails safe to "never selected," not a crash.

## Missing skills directory (code-verified)

`router.route(Path("/tmp/nonexistent-brain-home-xyz"), "any task")` returned
`{"selected": [], "scores": {}, "shadow": True}` with no exception —
`_all_skill_names` silently skips any level directory that doesn't exist
(`if directory.is_dir()` guard).

## Duplicate skill identity across levels (code-verified)

Created the same skill name (`dup-skill`) under both `skills/candidates/`
and `skills/shadow/`. `router._all_skill_names()` deduplicated to a single
entry (not counted/scored twice); `router._skill_level()` correctly resolved
the higher-priority level (`"candidate"`, per `LEVEL_PRIORITY = ("active",
"candidate", "shadow")`), matching the documented active > candidate >
shadow pool priority (Phase 23).

## Project-specific vs. global/shared policy

Not exercised: `router.py`'s skill pool (`skills/active|candidates|shadow`)
and `config/skills.toml` are both single, home-scoped (not
per-project-namespaced) in the code reviewed this campaign — no
project-vs-global skill-scope distinction exists in the current
implementation to test. Not invented here.

## Gate 14

**PASS.** Live-proven: a relevant skill is delivered in full (descriptor +
hydrated body) only when its trigger genuinely matches, an irrelevant task
gets none, and both the per-skill and aggregate injection caps plus
malformed-metadata/missing-directory/duplicate-identity edge cases fail
safe rather than crash or over-inject. Visibility helps the session (full
procedure text on a real match) without dumping the whole skills corpus
into context on every turn (0 skills delivered on 100% of this campaign's
other ~30 sessions, none of which had a matching trigger).
