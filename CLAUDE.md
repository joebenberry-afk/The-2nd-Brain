# Claude Project Bootstrap

@AGENTS.md

This repository **is** Second Brain — not a project consuming it.

## What the Brain is

Plan and binding rules: `docs/intake/2026-09-27-plan-v4-agent-experience.md` (§3.2).
The product is `brain/` (TypeScript, Node built-ins only, no build step; Node ≥ 22.18 or Bun
runs `.ts` directly). Truth is plain files: `notes/<project>/*.md` (one fact each; scope comes
from the path), `notes/global/`, `kits/<name>/SKILL.md`, `work/<project>.md` (working state),
`projects.json`. No database; nothing derived is committed.

Use it while working here (`node brain/bin/brain.mjs …` in the cloud, `brain …` once installed):
`brain recall "<question>"` before re-discovering a project fact; `brain note "<text>"` for a
durable learning (`--kind gotcha --error "<msg>" --tested` when you verified a fix);
`brain state "goal … / next …"` when the plan changes. After TypeScript changes in `brain/`:
`npx eslint src test && npx tsc --noEmit && npx vitest run` (includes the frozen recall eval —
it must stay at dev ≥ 13/15, held-out ≥ 7/8).

## Cloud sessions (Claude Code on the web)

`.claude/settings.json` runs `scripts/cloud-session-setup.sh` at session start. In the cloud it
installs `brain/`'s test dependencies, puts a `brain` shim on PATH and sets
`SECOND_BRAIN_HOME` to this checkout; locally it does nothing. The cloud VM has no OMP host, so
live `omp` runs and installed-runtime checks must run on the Windows machine.
