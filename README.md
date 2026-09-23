# The Second Brain

Harness-independent memory, context, knowledge, approved skills and safe
reuse for coding agents. The native harness owns agent creation, model
selection, tool permissions and task lifecycle. Brain does not orchestrate
agents, stop tasks, or reserve worker capacity.

**Candidate status (2026-09-23):** The orchestrator-removal worktree is
candidate-only and not qualified or activated. See
[`docs/intake/Second_Brain_M00_OneShot_Closure_Mandate.md`](docs/intake/Second_Brain_M00_OneShot_Closure_Mandate.md),
[`docs/intake/M00-CAMPAIGN-REGISTER.md`](docs/intake/M00-CAMPAIGN-REGISTER.md)
and the [orchestration-free v3 roadmap](docs/intake/Second_Brain_V3_Orchestration_Free_Roadmap_2026-09-23.md).
The completed v4.2 implementation specification and previous v1/v2 release
reports remain historical subjects. They do not qualify the removed controller
or this candidate's current bytes. The installed production profile and
canonical Brain state have not been changed by this candidate.

## Retained product boundary

- Canonical memory, project-scoped retrieval, source/provenance/freshness,
  authorized writes and approved skill consumption.
- Automatic bounded context, per-recipient delivery, compaction checkpoint,
  memory/context recovery and handoff envelopes.
- Passive model-usage/cost accounting with explicit missing-data coverage;
  bounded Brain-local cache, index, retrieval and storage work.
- Thin OMP, Codex, Claude Code, Antigravity and Hermes adapters for supported
  memory/telemetry hooks. Host-specific labels do not become privileged
  authorization or model-routing rules.

Orchestration-only APIs are removed; still-reachable old CLI/transport calls
refuse without opening execution state. Historical worker leases, receipts,
budget rows, migrations and sealed host-patch records remain intact as
history—not active admission, settlement or refunded capacity.

## Repository and local development

`src/second_brain/` contains the Python memory/storage/CLI core.
`brainstem/prime-extension/` contains the OMP context/telemetry adapter.
`memory/`, `experiences/`, `decisions/`, `projects/`, `skills/` and `engrams/`
are canonical; `db/`, `state/`, `telemetry/` and local reports are derived.
The constitution changes only through explicit reviewed change control.

Use a disposable `--home` and the candidate interpreter for development;
unset inherited `PYTHONHOME`/`PYTHONPATH` before supplying the candidate
`src` import root. Do not run the repository test suite against the canonical
home. The installed extension is not updated by changing source files.

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m second_brain doctor --home <disposable-home>
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m pyright
```

The extension has development-only test dependencies. Install, backup and
rollback paths are described in
[`brainstem/prime-extension/README.md`](brainstem/prime-extension/README.md).
Candidate byte manifests compare sources and installed extension inventories;
they are not protected approval or authorization to activate production.

## Historical release context

The earlier v1.0.0 baseline and later v2 RC reports under `outputs/reports/`
describe their original executed bytes. The old Sol/driver contracts, patched
host launcher, native worker binding campaign and governed test fixtures are
not part of this candidate. Open retained authorization, integrity, skill,
hook and extension-activation findings remain blockers rather than being
silently inherited as passes.

## Paired economics answer review

The general paired runner retains every requested host attempt, including
setup failures and missing arms. Host stdout/stderr stays privately outside
all Git repositories; public raw run records are immutable and contain only
public-safe paths, hashes, sizes, usage, source/catalog identities, and the
actual host executable/argv identity. `classification: observed` and
`qualification_eligible: true` are required for economics evidence.

Set `SECOND_BRAIN_PYTHON` to the selected Brain interpreter for both execution
and collection; otherwise the runner's interpreter is used. Schema-3 records
bind the actually loaded source package in `runtime_identity`, separately from
the producer's `source_identity`. Initialization and host execution use that
same interpreter. Missing or mismatched runtime bindings cannot qualify.
Pin the corresponding host adapter in the preregistered host command; selecting
an interpreter does not automatically replace a host's installed adapter.

After independently checking each answer against its frozen task, collect
reviews without rerunning the host. The reviewer pin is mandatory and comes
from the preregistered collection contract:

```text
python scripts/run_paired_economics.py --collect --runs <cohort>/raw --reviews <reviews.json> --reviewer-identity <expected-id> --out <reviewed.json>
```

Each review supplies `run_id`, `task_id`, `fixture_commit`,
`response_artifact_sha256`, `reviewer_identity`, boolean `accepted`, `evidence`,
and `rationale`. Reviews must match the expected identity, current frozen task
catalog, producer/runtime identities, and immutable response artifact. Any rejected,
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
