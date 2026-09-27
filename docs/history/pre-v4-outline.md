# What the Brain was before V4 (outline)

V4 (`brain/`, TypeScript, plain Markdown notes) is the baseline. Everything below was removed
from the working tree on 2026-09-27. The code and tracked files still exist in git history:
tag `v2-archive` (local), `origin/main` at `5b35f1c` (V3, PR #1), and the old `brain/*` branches.
Untracked runtime data (databases, telemetry, campaign evidence, the venv) was deleted, not
saved.

## Timeline

| Version | Dates | What it was |
|---|---|---|
| V1 "Brain OS" | from 2026-08-14 | Python CLI (`brainctl`) with a SQLite store, built from the v4.1 / v4.2 "OneShot" implementation plans; a brain metaphor for everything: `constitution/`, `engrams/`, `experiences/`, `plasticity/`, `sleep/` consolidation, `immune/` scanning. |
| V1 → V2 | ~09-05 → 09-23 | Qualification campaigns to make OMP integration provable: native session identity, dispatch fences, capability tiers, fail-closed admission, sealed approvals, ledgers, economics (ON/OFF paired agent runs). Their evidence filled `outputs/reports/`. |
| V2 `2.0.0` | activated 09-24 | The qualified runtime: 68 Python modules (~54k lines), 28 SQLite migrations with FTS5 retrieval, the "Prime" OMP extension (22 modules, ~2.7k lines), and adapters for Claude Code, Codex, Antigravity/Gemini, Hermes and OpenCode. |
| V3 | 09-24 → 09-25 | Agent-native redesign (PR #1). Typed Markdown records in `records/` (`fact`, `decision`, `gotcha`, `procedure`, `locator`, `correction`, `state`) with trust grades and a candidate → promote workflow. Just-in-time advice appended to tool results, and a standalone OMP extension (`second-brain-v3`). About 4.7k lines. |
| V4 | 09-27 → | This tree. See `docs/intake/2026-09-27-plan-v4-agent-experience.md`. |

## Component map (removed)

| Path | Purpose |
|---|---|
| `src/second_brain/` | Python package: CLI, memory store, FTS5 retrieval, autoinject, security, `kb/` (V3 records core), adapters |
| `src/second_brain/migrations/` | 28 SQLite schema migrations |
| `tests/` | ~140 pytest modules |
| `brainstem/` | Host integrations: the Prime OMP extension, `omp-v3`, adapters (Claude, Codex, Antigravity, Hermes), telemetry schemas |
| `constitution/` | Protected rules; changed only through reviewed change control |
| `config/` | Policy defaults (`*.toml`) |
| `memory/`, `records/` | V2 memory corpus and V3 records. Both were converted to `notes/`: 120 records became notes, and on 2026-09-27 the V2 database re-check found 0 unconverted memories |
| `engrams/`, `experiences/`, `decisions/`, `lexicon/`, `frontier/`, `skills/`, `templates/`, `projects/` | Knowledge taxonomies and the skill lifecycle (candidate → shadow → staged → active → quarantine) |
| `immune/`, `plasticity/`, `sleep/` | Content scanning, learning statistics, offline consolidation/replay |
| `proof/` | Proof campaign runner, deterministic checks and manifests |
| `outputs/reports/` | Milestone reports and campaign evidence (raw ON/OFF runs, nested repo checkouts) |
| `docs/` | Plans, requirements, intake campaigns, architecture, integrations |
| `scripts/` | `bootstrap.ps1`, installers for V2/V3, eval runners, cloud corpus seed |
| Root | `The_Second_Brain_OS_V4*_Plan.md` (the V1 authority plans), `CHANGELOG.md`, `INDEX.md`, `VERSION` (2.0.0), `pyproject.toml`, `brainctl.cmd` |

## Why it was replaced

These are the V4 plan's findings, section 1:

- Most of the effort went into proving the system: constitution, sealed approvals, ledgers,
  qualification campaigns. None of it changed what an agent saw in a session.
- The vocabulary (candidate, promote, grade, conflict, supersession kinds) made writing a
  memory a multi-step ceremony, so agents rarely wrote one. 113 of 120 records were `fact`,
  and 95 were still `candidate`.
- Python in a TypeScript host meant a venv, the `PYTHONHOME` breakage, and a process spawn per hook.
- The gap that hurt most was still open. After compaction an agent got the project brief
  back, not what it had been working on.

## Carried into V4

- The records, as `notes/`.
- The BM25 ranking and its frozen dev/held-out recall cases (13/15 and 7/8).
- The capture, scrub and correction logic.
- Commit-trailer proposals and git sync.
