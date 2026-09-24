# The Second Brain

**Persistent project knowledge. Relevant context. Less repeated work.**

Second Brain keeps what a project decided, what failed, and where work left off, then brings the
relevant part back when an agent starts a task or resumes after a compaction. It runs locally
(Python and SQLite, no services, `dependencies = []`), keeps knowledge in Git-versioned readable
files, and leaves execution alone: your harness still owns agents, models, tools, and stopping.

[Quick start](#quick-start) · [Capabilities](#capabilities) · [Adapters](#host-adapters) · [Release notes](CHANGELOG.md) · [Roadmap](#v3-direction)

## What you get

- **Fewer repeated explanations.** Durable project memory — decisions, constraints, gotchas — with sources, evidence grade, contradiction candidates, and version history, so the same context is not re-derived every session.
- **Continuity across compaction and restarts.** Pre-compaction checkpoints, bounded resume packets, and handoff envelopes keep the thread of work intact.
- **Context that stays relevant.** Retrieval is relevance-gated and project-scoped: when nothing matches well, the Brain injects nothing instead of padding the prompt.
- **Knowledge you can audit.** Memory records carry provenance fields, evidence grades and version history. Missing evidence stays visible; a claimed grade is not proof.
- **Reusable know-how.** Recurring procedures become candidate skills with validation, evals, and guarded promotion.
- **Honest accounting.** Usage and cost are observed passively, and unknown values stay unknown.

## Status: V2 (`2.0.0`)

| Axis | State |
|---|---|
| Code qualification | **Qualified** at code subject `80f3c54` — 2156 passed / 1 skipped / 0 failed, independently reproduced; no blocking HIGH/MEDIUM authorization finding |
| Live qualification scope | **Oh My Pi only.** The other adapters below are implemented and exercised locally, but are not live-qualified |
| Authority-dependent features | **Fail-closed / unavailable** — see [Trust and security](#trust-and-security) |
| Production activation | **Activated 2026-09-24** on baseline `749e9cd` (code-equivalent `80f3c54`), schema 28, 116 memories, live acceptance 12/12 |

Independent issuer, protected custody, and ledger signing are unavailable
([work item](docs/intake/EXTERNAL-TRUST-ROOT-WORK-ITEM.md)); see the
[V2 release notes](CHANGELOG.md) for the release boundary. The `v2.0.0` publication
adds stable version metadata and repository/documentation cleanup; it does not
silently replace the installed `749e9cd` runtime.

## Architecture

```
harness session              ── owns agents, models, tools, permissions, STOP
  └─ adapter                 ── OMP extension or local hooks
       └─ Python core        ── canonical memory, retrieval, context, ledger, reports
            ├─ canonical     memory/ experiences/ decisions/ projects/ skills/ engrams/ constitution/ config/
            └─ derived       db/ state/ telemetry/             (rebuildable, ignored)
```

The Python core owns canonical memory and context state; the OMP extension additionally
writes its own telemetry and active-state artifacts. Adapters are thin and replaceable —
host APIs are adapted, not baked into core policy, and a host label never becomes
authorization ([architecture](docs/architecture/index.md), [components](docs/components)).
Backups are recovery copies, not disposable indexes. The retained Antigravity
completion-control exception is documented under [Trust and security](#trust-and-security).

## Capabilities

- **Project memory and retrieval** — semantic memories, episode capture, project registry with `.brain/project.toml`, source provenance, evidence grades, supersession, contradiction candidates, relevance-gated injection, delta deduplication, recovery ([retrieval](docs/components/retrieval-isolation-and-lean-activation.md)).
- **Context and continuity** — active-state capsule, requirement and read ledgers, JIT context compilation, checkpoint-before-compaction, ledger replay and rehydration, paged session objects, handoff envelopes ([working set](docs/components/working-set.md), [JIT context](docs/components/jit-context.md)).
- **Skills** — candidate → shadow → staged → active lifecycle with forging from episodes, structural validation, evals, and guarded promotion.
- **Operations** — `doctor` health checks, sha256-manifested backup and restore, ordered idempotent migrations, environment snapshots ([doctor](docs/components/doctor.md), [backup](docs/components/backup-restore.md)).
- **Accounting** — passive provider usage and cost observation with explicit missing-data coverage ([telemetry](docs/components/telemetry-observability.md)).

## Quick start

Requires **Python 3.11+ and Git**. The hook/install examples below target Windows.

The Brain home is a directory holding canonical knowledge plus its SQLite index. Clone
into a **dedicated checkout used as its own home**, and set `SECOND_BRAIN_HOME` first so
no existing home is touched.
This Windows quick start uses the complete repository, including host installers.
The wheel and source distribution contain the Python core; host adapters are
available in the repository and GitHub's full source archive.

```powershell
$dev = Join-Path $HOME "second-brain-dev"
git clone --branch v2.0.0 https://github.com/joebenberry-afk/The-2nd-Brain $dev
Set-Location $dev
$env:SECOND_BRAIN_HOME = $dev

# creates .venv, installs the package editable, runs `init`, then `doctor`
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

Register an existing project, then capture and retrieve knowledge from its directory:

```powershell
.\brainctl.cmd project add ..\my-project        # registers a repo: .brain/project.toml + AGENTS.md marker
Set-Location ..\my-project                      # the project is resolved from the cwd
& "$dev\brainctl.cmd" remember "Write-path changes need BEGIN IMMEDIATE; smoke tests require a real database"
& "$dev\brainctl.cmd" recall "why does the write path need immediate transactions?"
```

Add `--evidence <path-inside-your-project>` when the claim has a real file behind it.
Without evidence, this example remains a caller-reported `OBSERVED` memory.

- **Pick the home deliberately.** `SECOND_BRAIN_HOME` decides which home every command uses, and `init` migrates that home's database; for a throwaway home, run `init --home <dir>` first, then `doctor --home <dir>`.
- `brainctl.cmd` clears `PYTHONHOME`/`PYTHONPATH`: an inherited bad pair breaks Python startup (`SRE module mismatch`) on some Windows setups.
- `remember` defaults to grade `OBSERVED`, and `--grade VERIFIED` is refused today. Editing `src/` does not update an installed host extension.
- The test suite uses its own homes; do not run it against a home holding real memory.

## Host adapters

| Host | Integration | Live qualification |
|---|---|---|
| **Oh My Pi (OMP)** | Extension ([source](brainstem/prime-extension/README.md)): retrieval and injection, session and project correlation, context and compaction continuity, approved-skill visibility, passive telemetry | **Qualified.** Installed and activated 2026-09-24; `scripts\install-prime-extension.ps1`, rollback `scripts\uninstall-prime-extension.ps1 -BackupDir <backup>`; restart OMP to pick up a new build |
| **Claude Code** | Local hooks ([source](brainstem/adapters/claude-code/README.md)) — `SessionStart`, `PreCompact`, `Stop`; documented fail-open (`{}`, exit 0) | Implemented locally; not live-qualified |
| **Codex** | Repo-local hooks ([source](brainstem/codex-hooks/README.md)); `SECOND_BRAIN_AUTOINJECT_MODE` defaults to `shadow` (decides and records, injects nothing) | Implemented locally, shadow stage; not live-qualified |
| **Hermes** | Plugin ([source](brainstem/adapters/hermes/README.md)); the release copy registers writeback and handoff read only | Implemented locally; not live-qualified |
| **Antigravity** | Adapter plugin and hooks ([source](brainstem/adapters/antigravity)) | Implemented locally; not live-qualified, with the known finding below |

Adapter installers back up every file they replace and report what changed. Hosted and
cloud agent surfaces are **not packaged or qualified**: no adapter ships for them and no
qualification record covers them.

## Trust and security

Unavailable until an independent issuer exists — the Brain refuses rather than trusting a
caller's claim: `VERIFIED` memory issuance, approval-bearing or critical completion,
authoritative model-success records, and policy-authority promotion (the ceiling stays
`advisory`); stored `VERIFIED` rows read as at most `TESTED`.

- **Skill approval is not protected.** Skill delivery works, but it is driven by an unprotected same-user review record bound to the exact approved bytes.
- **The ledger is tamper-evident, not signed.** Replay and rehydration reject a broken chain; there is no signature.
- **The security boundary is the OS user.** A same-user process can read and write the Brain home; the Brain does not defend against that.
- **One host control remains.** The Antigravity `Stop` hook can return `decision: "continue"` from caller-writable requirements — a pre-existing MEDIUM finding, and the first item V3 removes.
- **No guaranteed savings.** Relevant reuse may reduce repeated explanation and investigation, but token, cost, latency and quality benefits depend on the workload.

## V3 direction

V3 develops against `qualified-m00` as its parent and keeps the boundary: no Brain
component may admit, block, route, veto, continue, or settle host agent work. **The
Antigravity `Stop` path is the known exception today and is scheduled for removal first.**
After that: measurement and a cheaper runtime, evidence-aware memory and invalidation,
source discovery and precise retrieval, durable context continuity, skills, memory-only
learning, and bounded resources with portable adapters. See the
[V3 roadmap](docs/intake/Second_Brain_V3_Orchestration_Free_Roadmap_2026-09-23.md) and the
[removal mandate](docs/intake/Second_Brain_Orchestrator_Removal_Mandate_2026-09-23.md).

## Documentation

| Where | What |
|---|---|
| [M00 campaign register](docs/intake/M00-CAMPAIGN-REGISTER.md) | Current status, boundary decisions, fail-closed capability table |
| [Activation record](docs/intake/m00-evidence/activation-20260924/ACTIVATION-RECORD.md) | What was activated, live acceptance, deviations, rollback |
| [Release contract](docs/integrations/Second_Brain_v2_OMP_Only_Release_Contract_2026-09-19.md) | V2 release scope and its limits |
| [External trust-root work item](docs/intake/EXTERNAL-TRUST-ROOT-WORK-ITEM.md) | What is blocked on an independent issuer |
| [CHANGELOG](CHANGELOG.md) | V2 release notes and dated history |
| [constitution](constitution/constitution.md) | Protected rules and change control |

<details>
<summary>Advanced: paired economics evidence collection</summary>

The paired harness compares Brain-off and Brain-on runs against real hosts. Run records are
immutable and public-safe (paths, hashes, sizes, usage, identities); host output stays
outside Git. Evidence requires `classification: observed` and `qualification_eligible: true`,
and `SECOND_BRAIN_PYTHON` should pin one runtime for execution and collection. Reviews are
collected afterwards without rerunning a host, under a mandatory preregistered reviewer
identity:

```text
python scripts/run_paired_economics.py --collect --runs <cohort>/raw --reviews <reviews.json> --reviewer-identity <expected-id> --out <reviewed.json>
```

Each review supplies `run_id`, `task_id`, `fixture_commit`, `response_artifact_sha256`,
`reviewer_identity`, boolean `accepted`, `evidence`, and `rationale`; rejected, unknown,
extra, or missing reviews fail qualification. See
[`scripts/run_paired_economics.py`](scripts/run_paired_economics.py).

</details>

## Development

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
$env:SECOND_BRAIN_HOME = Join-Path $env:TEMP ("brain-tests-" + [guid]::NewGuid())
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m pyright
```

TypeScript work is confined to `brainstem/prime-extension/` (`bunx tsc --noEmit`, `bunx eslint src tests`,
`bunx vitest run`); working rules for agents are in [`AGENTS.md`](AGENTS.md). No license file is present.
