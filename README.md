# The Second Brain

A portable, current-state memory for coding agents: **plain Markdown files plus a small
`brain` command**, that tells an agent what is true now about a project and otherwise stays
out of the way. The host (focus: **Oh My Pi**) owns agents, tools and lifecycle; the Brain only
remembers, finds and — at two well-defined moments — reminds.

> **Status (2026-09-24):** V3 is complete in code and continuously tested (CI on every push).
> The live qualification in OMP on the owner's machine has not been run yet — see
> [the status report](docs/intake/2026-09-24-report-v3-status.md). The previous (M00/v2)
> runtime is kept unchanged for one-command rollback.

## What V3 does

| | |
|---|---|
| **Remembers what is currently true** | One Markdown record per fact, typed (`fact`, `decision`, `gotcha`, `procedure`, `locator`, `correction`, `state`), with evidence and an effective trust grade. A fact changes only by explicit `supersede` / `retire` / `conflict`, never because something is newer; history stays queryable (`--history`, `--as-of`). |
| **Speaks only when it helps** | In OMP it adds exactly two things: a **project brief** on a session's first turn and after compaction (≤ 600 tokens, nothing when the project has no current records), and **one tested correction** when a tool call fails with a known error (≤ 80 tokens). Ordinary prompts get nothing. |
| **Answers when asked** | `brain q "<question>"` returns at most three one-line answers, or nothing. |
| **Learns from real work** | A failed command followed by a working variant, and `Brain-Decision:` / `Brain-Gotcha:` commit trailers, become *proposals* in a local inbox (secrets scrubbed). Nothing is trusted until you `accept` and `promote` it with evidence. |
| **Works across projects and machines** | Records are scoped to a project, shared to tagged groups of projects (`brain share`), or global. `brain sync` moves them between machines through git; `records/private/` never leaves the machine. |
| **Stays honest** | Everything pushed is labelled advisory. Nothing retrieved grants permission; a claimed VERIFIED grade counts as TESTED without an independent issuer; promotions record who promoted. |

It does **not** depend on a harness or on an OMP version: the records and the CLI work from any
shell or agent, and the OMP extension reads host fields defensively (a host change degrades it
to "adds nothing"). Antigravity, Hermes and Codex adapters are out of focus and frozen.

## Put it on your machine (Windows + OMP)

In your Brain checkout (the canonical home, e.g. `C:\Users\<you>\Documents\The-Second-Brain`):

```powershell
git status                                   # commit or stash local changes first
git fetch origin
git switch claude/new-session-nro2r6         # the V3 branch (or the branch it was merged into)

$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pip install -e .                 # installs .venv\Scripts\brain.exe
[Environment]::SetEnvironmentVariable("SECOND_BRAIN_HOME", (Get-Location).Path, "User")
$env:SECOND_BRAIN_HOME = (Get-Location).Path

# Bring in memories added on this machine since the V3 snapshot (existing records are skipped):
.venv\Scripts\brain.exe convert --from-db db\brain.sqlite --legacy-home .
.venv\Scripts\brain.exe doctor                               # expect: errors (0)
.venv\Scripts\brain.exe views                                # compile briefs and correction tables
.\scripts\install-omp-v3.ps1 -DisableLegacy                  # parks the old extension (reversible)
```

Restart OMP. Checks for the first sessions, the live native-vs-V3 comparison and rollback
(`.\scripts\uninstall-omp-v3.ps1 -RestoreLegacy`) are in the
[OMP runbook](brainstem/omp-v3/README.md).

## Everyday commands

| Command | Does |
|---|---|
| `brain q "<question>" [--all-projects] [--history] [--as-of DATE]` | search (≤ 3 lines) |
| `brain show <id>` · `brain brief` | one record · this project's brief |
| `brain add "<claim>" --type gotcha --evidence … [--trigger-error …]` | record a learning (always a candidate) |
| `brain promote <id> --reason …` | make a candidate current (needs evidence) |
| `brain supersede <old> --by <new> --reason …` · `brain retire <id> --reason …` | change what is current |
| `brain conflict <a> <b> --reason …` | keep a disagreement visible (neither is pushed) |
| `brain edit <id> --type …` | change a record's description, never its standing |
| `brain review` · `brain accept <id>` · `brain reject <id> --reason …` | proposals, stale evidence, duplicates, recent promotions |
| `brain share <id> --domain <tag> --reason …` · `brain sync` | share across projects · sync machines |
| `brain doctor` | integrity, views, privacy, storage, runtime identity |
| `brain export-skill <id> --dir <skills dir>` | a proven procedure as an Agent Skills `SKILL.md` |

## How it is built

```text
records/*.md (canonical, git)  ──►  db/kb.sqlite (FTS5 index, derived)  ◄── brain q
            │                  └─►  views/<project>/brief.md, corrections.json (derived)
            │                                   │
            ▼                                   ▼
      brain CLI (Python, stdlib)        OMP extension (one TypeScript file, reads views only)
```

- `src/second_brain/kb/` — the V3 core (records, projects, index, views, capture, sync, doctor,
  CLI). Standard library only; nothing on its import path loads the legacy modules.
- `brainstem/omp-v3/` — the standalone OMP extension and its runbook.
- `records/` and `projects/` are canonical and versioned; `db/`, `views/`, `state/`,
  `telemetry/` are derived or local and rebuildable.
- Everything else under `src/second_brain/` and `brainstem/prime-extension/` is the legacy
  (M00/v2) runtime, kept untouched for rollback until V3 passes its live qualification.

Measured choices: Python was kept (the old hook's cost was its import graph, not the language —
same index workload: Python 28 ms, Go 23 ms); SQLite FTS5 is the index (no server, no vector DB
until a paraphrase class fails keyword search); git is the sync.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_kb_*.py          # V3 core
python -m ruff check src tests && python -m pyright src/second_brain/kb
cd brainstem/prime-extension && npm ci && npx vitest run tests/omp-v3.test.ts
```

On Windows use `.venv\Scripts\python.exe` with `PYTHONHOME`/`PYTHONPATH` cleared (see
`AGENTS.md`). CI (`.github/workflows/ci.yml`) runs lint, types, the V3 tests on Python 3.11 and
3.13, the OMP extension tests, and the frozen retrieval case sets on every push. Some legacy
tests are Windows-only; `CLAUDE.md` lists them.

## Design and decisions

- [V3 agent-native redesign](docs/intake/2026-09-24-plan-v3-agent-native-redesign.md) — the
  design, owner decisions O1–O7 and the binding rules (host focus, no harness dependence).
- [V3 status against every requirement](docs/intake/2026-09-24-report-v3-status.md)
- [Currentness sweep](docs/intake/2026-09-24-report-v3-currentness-sweep.md) — what was retired
  when the corpus was converted.
- [V3 requirements baseline](docs/intake/Second_Brain_V3_Requirements_2026-09-24/START_V3.md)

The protected rules live in `constitution/` and change only through reviewed change control.
