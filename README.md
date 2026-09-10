# The Second Brain

> A model-independent continual-learning control layer that surrounds coding
> agents, remembers verified experience, actively manages context, chooses
> tools and skills adaptively, learns from success/failure, transfers validated
> experience across projects, and improves future agent performance without
> retraining the underlying LLM.

**Specification:** `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
is the authoritative implementation plan. The v4.3 proof plan supplied for
this campaign governs validation; v4.1 and the Definitive plan are retained
as research history. Verified repository reality wins over stale narrative
text.

**Canonical location:** `%USERPROFILE%\Documents\The-Second-Brain`
(resolvable via the `SECOND_BRAIN_HOME` environment variable).

## v1.0.0 release status

Second Brain **v1.0.0** is released. The authoritative source of truth for
what is qualified is `outputs/reports/rc2/00-AUTHORITATIVE-CURRENT-STATUS-LEDGER.md`
(all 37 roadmap items, P0.1 through P4.5, `PROVEN`) plus the P4/P4.5 release
gate in `outputs/reports/v1-p4/qualification-report.md` and
`outputs/reports/v1-release-baseline.md`. P4.5 (Controlled Self-Optimization)
qualified the governed optimization *mechanism* — real fingerprint → real
candidate binding → real counterfactual evidence → propose → evaluate →
activate — using a genuine Antigravity/Gemini paired session; the evaluated
Lean-code candidate showed measured negative ROI and activation was
correctly refused. That refusal is the qualifying evidence, not a promotion
of the candidate.

**V2 boundary:** `v1.0.0` remains the released baseline. The v2 RC is
unqualified and remains **HOLD**. Native worker correlation requires both
OMP [#10928](https://github.com/can1357/oh-my-pi/pull/10928) (delivered
`jobId`, `status`, `agentId`) and
[#10948](https://github.com/can1357/oh-my-pi/pull/10948) (dispatch progress
`id` = child agent ID, `jobId` = exact manager-returned ID).
Brain binds and journals each native job ID to its packet and expected
child identity. Missing bindings, mismatched agents, and legacy unbound
journals are not guessed from names or rendered output. Neither draft PR
is a released host capability. No deployment, provider qualification,
Gate 22/23, or v2 release tag is authorized by the
[offline proof](outputs/reports/v2/omp-burnin/20260905-dispatch-binding/).

The status table and campaign notes below this section describe the earlier
Phase 0-23 / "v4.3 optimization campaign" build history and are retained as
historical record; they predate the rc2 37-item roadmap ledger and are not
the current v1 status source.

## Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Project creation | done |
| 1 | Foundation | done |
| 2 | Observability | done |
| 3 | Project integration | done |
| 4 | Working set / JIT context | done |
| 5 | Sensory gateway / RTD | done (shadow-only) |
| 6..23 | (gated) | done; see `outputs/reports/` |

Each phase is gated by its acceptance criteria in the plan. Milestone reports
live in `outputs/reports/<milestone>.md`.

### Optimization campaign status (2026-08-15)

- Telemetry hot-path fixes (Phases 2-4) committed: stable per-lifecycle
  anonymous session id; RTD eligibility decided before serialization with one
  shared measurement; telemetry dir mkdir-once. RTD remains **shadow mode**
  (no substitution); `context.toml [rtd] threshold_chars` is now wired into
  the threshold ladder (env override still highest); other `[rtd]` keys stay
  informational (see `proof/reports/config-consumption.md`).
- Sol minimal-orchestrator guard committed and deployed: the Prime extension
  blocks `bash`/`edit`/`websearch` for orchestrator-model sessions and
  injects the Sol contract via `before_agent_start`. Live rollout
  2026-08-15T06:45:44Z: 8 files SHA-identical to repo; post-deploy census
  clean (0 `orchestrator_policy_violation` in 22,615 records, 0
  `extension_error`, 0 new anon files). Contract:
  `brainstem/policies/sol-minimal-orchestrator.md`.
- Skill router: `skills.toml [router] max_active` is ENFORCED (fallback 3,
  CLI `--max-active` overrides); SKILL.md metadata cached with mtime
  invalidation.
- Retrieval (FTS5 + filters + dedupe + ranking) committed and live: FTS5
  engine, hard filters, dedupe, ranking; live DB reindexed to schema v7,
  `memory_fts` 6/6 (FTS branch ~5 ms).
- Live rollout result (2026-08-15): final status **PARTIALLY VALIDATED** —
  deployment, per-session loading, recall hook, telemetry health, FTS5 and
  campaign delegation are live-proven; Sol-specific acceptance is blocked
  only by model availability (proof: `outputs/reports/optimization-proof.md`).

## Layout

- `constitution/` — protected rules (never auto-rewritten by the Brain)
- `config/` — TOML policy defaults (context, learning, retrieval, ...)
- `src/second_brain/` — Python control layer (`brainctl`)
- `scripts/` — bootstrap, adapters, doctor (PowerShell) + `brainctl.py`
- `db/brain.sqlite` — local control/index database (derived, rebuildable)
- `memory/`, `experiences/`, `decisions/`, `projects/`, `skills/`, `engrams/` — canonical knowledge stores
- `state/`, `telemetry/`, `plasticity/`, `sleep/` — runtime/derived data
- `outputs/reports/` — milestone reports
- `tests/` — pytest suite

## Quick start (Windows)

```powershell
cd $env:USERPROFILE\Documents\The-Second-Brain
powershell -ExecutionPolicy Bypass -File scripts\\bootstrap.ps1
.venv\Scripts\python -m second_brain doctor
```

or manually:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
brainctl init
brainctl doctor
```

`brainctl` commands implemented so far: `init`, `doctor`, `status`,
`project add|list|status|detach|remove`, `backup`, `restore`,
`telemetry report|validate`, `capsule init|update|show`,
`requirements add|evidence|status|show|check`, `read-ledger record|show`,
`context compile`.

## Paired economics answer review

The general paired runner retains every requested host attempt, including
setup failures and missing arms. Host stdout/stderr stays privately outside
all Git repositories; public raw run records are immutable and contain only
public-safe paths, hashes, sizes, usage, source/catalog identities, and the
actual host executable/argv identity. `classification: observed` and
`qualification_eligible: true` are required for economics evidence.

After independently checking each answer against its frozen task, collect
reviews without rerunning the host. The reviewer pin is mandatory and comes
from the preregistered collection contract:

```text
python scripts/run_paired_economics.py --collect --runs <cohort>/raw --reviews <reviews.json> --reviewer-identity <expected-id> --out <reviewed.json>
```

Each review supplies `run_id`, `task_id`, `fixture_commit`,
`response_artifact_sha256`, `reviewer_identity`, boolean `accepted`, `evidence`,
and `rationale`. Reviews must match the expected identity, current frozen task
catalog/source identity, and immutable response artifact. Any rejected,
unknown, extra, duplicate, or missing review fails answer qualification.

Every attempt remains in the cohort records. `token_statistic.n` counts only
pairs with measurable token totals; missing or corrupt usage prevents economic
qualification. `quality_qualified_economics` is null unless the answer gate and
complete paired-usage checks pass. Dollar values are catalog estimates, not
observed charges; unknown prices remain null and do not block token-only evidence.
`host_execution` records command start and finish times; paired `wall_ms` uses
that interval, not the narrower telemetry-event span.
This workflow does not replace native provenance, preregistration, or the other
release gates. The separate three-pair read-reuse study is unchanged.

## Tooling policy

- **Python (stdlib-first)** for `brainctl`, SQLite control DB, curation,
  retrieval, reports.
- **TypeScript** only for the Prime Agent extension (`brainstem/prime-extension/`).
- **PowerShell** for Windows bootstrap/adapters.
- **Markdown** for canonical human-readable knowledge; **TOML** for policy;
  **JSON/JSONL** for runtime records; **SQLite** for searchable metadata only.
- No Rust, no services, no vector DB until a measured requirement justifies them.

## Doctrine (abbreviated)

Repository reality outranks Brain memory. Experience is written quickly;
general rules change slowly. Raw evidence is preserved outside active context.
Skills must earn activation and continued existence. High-risk work receives
independent verification. Automatic policy changes start in shadow mode.

See `constitution/` for the protected rules and the plan for the full doctrine.
# The-2nd-Brain
