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
node bin/brain.mjs check        # or `brain check` once installed
```

<!-- The-Second-Brain:begin id=second-brain -->
## The Second Brain

Canonical Brain: `%SECOND_BRAIN_HOME%`.

For substantive work:
- current repo/tests outrank memory;
- use targeted Brain recall;
- do not preload the Brain;
- use Brainstem signals where available;
- preserve durable validated learning.
<!-- The-Second-Brain:end -->
