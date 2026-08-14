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
