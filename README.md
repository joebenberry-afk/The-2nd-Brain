# The Second Brain

**Memory for coding agents that survives compaction, follows you across projects, and costs
almost nothing when it has nothing to say.** Built for Oh My Pi;
usable from any shell or agent through the `brain` command.

> **Status (2026-09-27): V4 in development** on branch `claude/new-session-nro2r6` — see
> [the plan](docs/intake/2026-09-27-plan-v4-agent-experience.md). The V2/V3 runtimes stay in
> the tree, untouched, until V4 has run in daily use; rollback is one command.

## What an agent feels

| Moment | The agent gets | Cost |
|---|---|---|
| **Session start** | a *start card*: where we left off, the 5 notes that matter for this project and the current work, matching MVP kits | ≤ 400 tokens, nothing when there is nothing to say |
| **Compaction** | the same card again, including the working state it would otherwise lose — injected straight after compaction, even mid-run | ≤ 400 tokens, cache-stable |
| **Working** | `brain_recall(query)` · `brain_note(text)` · `brain_state(goal/done/next)` — one argument each; recall a note id to read it in full; a retired answer comes back marked as retired, with its replacement | ≤ 3 lines per recall |
| **A tool fails** | the one known, tested fix for that error, appended to the result | ≤ 80 tokens, or nothing |
| **New project** | *kits*: the proven path from idea to running MVP (stack and why, scaffold steps, gotchas, done-check) | one file, ≤ 600 tokens |
| **Any other prompt** | nothing | 0 |

Measured on this repository: the start card is about 250 tokens and builds in ~9 ms; recall
answers in ~1 ms (warm) over 127 notes and matches the previous SQLite engine exactly (frozen
cases: dev 13/15, held-out 7/8). At 2,000 notes a warm recall takes ~26 ms, at 5,000 ~67 ms.

## How it works

```text
notes/<project>/*.md     one Markdown file per durable fact (decision, gotcha, procedure, fact, note)
notes/global/*.md        cross-project notes; tagged ones reach only projects with that tag
notes/*/private/         never leaves the machine
kits/<name>/SKILL.md     MVP kits (Agent Skills format — OMP and Claude Code can load them natively)
work/<project>.md        working state: goal · done · next · watch out (+ files edited, last failure)
projects.json            optional: extra paths, remotes and tags per project
```

Plain files in git are the only truth; there is no database, no index to rebuild, no service.
Projects need no registration: the id comes from the git remote or the folder, and tags from the
stack at the root (`package.json` → node, `pyproject.toml` → python, …), so notes shared under a
tag and kits find the right projects by themselves. `projects.json` only adds paths, aliases (a
renamed repo) and extra tags. Secrets are masked in everything written. `brain sync` moves notes,
kits and working state between machines through git.

The package is `brain/` — TypeScript, Node built-ins only, no build step (Node ≥ 22.18 or Bun
runs it directly):

| Module | Does |
|---|---|
| `notes.ts` · `project.ts` | note format and storage · which project a directory belongs to |
| `search.ts` | in-memory BM25 (a faithful port of SQLite FTS5's `bm25()`) |
| `card.ts` · `work.ts` | the start card · the working state |
| `capture.ts` | tool-event log, failed→fixed and commit-trailer proposals, known fixes |
| `kits.ts` · `sync.ts` | MVP kits · git sync and sharing |
| `omp.ts` | the Oh My Pi extension (in-process: no subprocess per event) |
| `cli.ts` | the `brain` command and a Claude Code hook |

## Install (Windows + Oh My Pi)

In your Brain checkout:

```powershell
git fetch origin
git switch claude/new-session-nro2r6
.\scripts\install-v4.ps1        # brain command on PATH, SECOND_BRAIN_HOME, OMP extension; parks V2/V3 extensions
brain check                     # notes, projects, kits; exit 0
brain card                      # what a session in this project will see
```

Restart OMP. Details, verification and rollback (`.\scripts\uninstall-v4.ps1 -Restore`):
[brain/README.md](brain/README.md).

## Everyday commands

```text
brain card                          the start card for this directory's project
brain recall "<question>" [--all]   ≤ 3 one-line answers
brain note "<text>" [--kind gotcha --error "<msg>" --tested] [--global]
brain state ["goal … / next …"]     show or replace the working state
brain move <id> --to <project>      re-home a note (share <id> --tag T makes it global for a tag)
brain review · accept · reject      proposals captured from failed→fixed commands and commit trailers
brain kit list · show · new         MVP kits
brain sync                          notes, kits, working state ↔ git remote
brain stats                         what the Brain actually did this week
```

## Development

```bash
cd brain && npm ci
npx eslint src test && npx tsc --noEmit && npx vitest run
```

CI runs the same on Node 22 and 24 plus a Bun smoke run, including the frozen recall eval on the
committed notes. Design: [V4 plan](docs/intake/2026-09-27-plan-v4-agent-experience.md).
