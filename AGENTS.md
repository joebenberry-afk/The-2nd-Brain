# AGENTS.md — working inside The Second Brain repository

This file governs agents working **on the Brain itself** (this repo).

## Authority

- `docs/intake/2026-09-27-plan-v4-agent-experience.md` is the design and its §3.2 rules are
  binding. Repository code, tests and verified runtime behaviour outrank assumptions.
- V1–V3 (Python, SQLite, constitution, records) are retired; `docs/history/pre-v4-outline.md`
  says what they were and where their history lives. Do not revive them.

## Rules

1. **Files are the truth.** `notes/`, `kits/`, `work/`, `projects.json` are canonical and
   Git-versioned. `state/` is local and derived; nothing derived is committed.
2. **No secrets.** Never write credential values, tokens or private keys into any file here.
   `notes/*/private/` never leaves the machine.
3. **Small increments.** After changes in `brain/`:
   `npx eslint src test && npx tsc --noEmit && npx vitest run` (includes the frozen recall
   eval: dev ≥ 13/15, held-out ≥ 7/8).
4. **Node built-ins only** in `brain/src`. No dependency without a measured need.
5. **Git policy.** Feature branches `brain/<feature>`. Commit categories: `brain(core)`,
   `brain(memory)`, `brain(project)`, `brain(adapter)`, `brain(policy)`.

## Commands

```text
cd brain && npm ci
npx eslint src test && npx tsc --noEmit && npx vitest run
npm run test:unit               # ~2 s inner loop; the full gate above before committing
node bin/brain.mjs check        # or `brain check` once installed
```

<!-- The-Second-Brain:begin id=second-brain -->
Use `brain recall "<query>"` before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command; the repo wins on conflict.
Use `brain note "<text>"` for what the repo cannot tell you: a decision and its why, an environment gotcha with its error line, what failed before, an owner preference.
Use `brain state "Goal: … Next: …"` when the goal or next step changes.
Use `brain fix "<error>"` after an unexplained failure (tested known fix, or silence).
<!-- The-Second-Brain:end -->
