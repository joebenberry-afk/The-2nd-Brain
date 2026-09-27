# Second Brain V4 — install, verify, roll back

## 1. Install (Windows, in the Brain checkout)

```powershell
git status                                # commit or stash local changes first
.\scripts\install-v4.ps1
```

The installer (every step reversible):
- picks the runtime — Node ≥ 22.18, else Bun — and writes `brain\bin\brain.cmd` next to the
  committed `brain\bin\brain` shim (Git Bash, where Claude Code runs hooks, needs that one), then
  adds `brain\bin` to your user PATH, keeping `%VAR%` entries intact (`-NoPath` skips that);
- sets `SECOND_BRAIN_HOME` to the checkout when it is unset;
- parks the V2 (`second-brain`) and V3 (`second-brain-v3`) OMP extensions in
  `~/.omp/agent/extensions-disabled/` so memory is not pushed twice;
- writes `~/.omp/agent/extensions/second-brain-v4/index.ts`, a one-line loader that imports
  `brain/src/omp.ts` from the checkout — `git pull` plus an OMP restart is the whole update
  (verified live on OMP 18.3.5; a running session keeps the code it started with).
  If OMP does not load it (check 1 below shows no card), run `.\scripts\install-v4.ps1 -Copy`:
  a self-contained copy of `brain/src` (re-run it after each `git pull`);
- ends with `brain check` as a self-test.

The installer and uninstaller are exercised by `test/install.test.ts` (PowerShell 7, and Bun
loading the installed extension) wherever `pwsh` is available — including CI.

No `npm install` is needed to run it (no runtime dependencies); `npm ci` in `brain/` is only for
tests.

Open a **new terminal** (it picks up PATH and `SECOND_BRAIN_HOME`), then:

```powershell
brain check     # notes: N (A active) · projects: P · kits: K — exit 0
brain card      # what a session in this checkout will see
```

Restart OMP from that new terminal.

**Other projects' notes.** A project's id comes from its git remote or folder name. If a repo on
this machine resolves to a different id than its notes use (`brain card` in it shows nothing you
expected), add its `remote` or the id as an alias in `projects.json` — e.g. the SZ-tool notes
live under `sztool`, which lists the SZ-Agent-Toolkit remote. `brain move <id> --to <project>`
re-homes one note. A recall that finds nothing here but something elsewhere says so:
`no match here; N related in other projects (--all)`.

## 2. Verify in the first sessions

1. **Start card.** Start OMP in a project: the first turn carries a hidden `brain.card` message
   (≤ 400 tokens: where we left off, up to five complete notes ranked by the first prompt, matching
   kits); later prompts add nothing. Subagents get a card without the working state and cannot
   overwrite it with `brain_state`. `brain stats` shows one `card` per session, main and sub apart.
2. **Working state.** Ask the agent to set the plan (`brain_state`). Then force a compaction
   (`/compact`) and ask "where are we?": the answer should give goal and next step without
   re-reading files. Compaction re-injects only the working state (≤ 150 tokens: Goal and Next
   first). Files edited, the last failure and the last ask are kept locally in
   `state/work/<project>.auto.md`, never synced.
3. **Known fix.** Run something that fails with an error a tested note names — e.g. an OMP edit
   without a `[path#tag]` header (`notes/global/` holds fixes taken from logged OMP failures): the
   failed result ends with `Brain: … [id]`.
4. **Learning.** After a few sessions, `brain review` lists, with their full bodies, failed
   commands that later succeeded as retries (same program and arguments, flags or a preparatory
   step added — `npm test` → `npm ci && npm test`), plus `Brain-Decision:` / `Brain-Gotcha:`
   commit trailers; `brain accept <id>` makes a note. A pair is `tested` only when the failed
   command itself succeeded afterwards. Exploration (grep, ls, cat …) is never proposed.
5. **Weekly.** `brain stats --days 7`: which moments fired and what they cost, main vs subagent
   cards, recall hit rate, and the five most frequent errors no note fixes yet — write notes for
   those. Anything never used for a week gets removed (plan rule 1).

## 3. Claude Code (optional)

In `~/.claude/settings.json` (or a project's `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }],
    "PostToolUseFailure": [{ "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }]
  }
}
```

The hook fails open (`{}`, exit 0). After compaction Claude Code fires `SessionStart` with
source `compact`; the hook then returns only the bounded working state. This checkout's own
`.claude/settings.json` calls `bash brain/bin/brain`, which picks Node or Bun.

## 4. Roll back

```powershell
.\scripts\uninstall-v4.ps1 -Restore      # removes the V4 extension, restores the parked one
```

Restart OMP. `-RemovePath` also takes `brain\bin` off your PATH. Notes, kits and working state
stay as files. The parked V2/V3 extensions expect the pre-V4 tree (tag `v2-archive`), which
this checkout no longer contains.

## 5. The files (edit them by hand when you like)

A note, `notes/<project>/<id>.md` (scope comes from the folder: a project, `global`, or
`<project>/private/` which never syncs):

```markdown
---
id: n-3f9a2c1b7d
kind: gotcha               # note | fact | decision | gotcha | procedure
at: 2026-09-27T10:00:00Z
source: agent              # agent | user | capture | commit | convert
tags:                      # on global notes: only projects with one of these tags see it
  - python
errors:                    # error text this note fixes; "re:<regex>" for a pattern
  - "SRE module mismatch"
evidence:
  - scripts/bootstrap.ps1
tested: true               # only tested notes are appended to failed tool results
---

Clear PYTHONHOME before running python        ← the first line is the headline

Why and how, in as much detail as helps.
```

Retiring keeps the file (`retired:`, `replaced_by:`); `brain retire <id> [--by <new id>]` writes
both sides. A working state, `work/<project>.md`, is the agent's plan as free text under a
one-line frontmatter (`at:`); an `## auto` section left by older versions is shown until the next
`brain_state` drops it. A kit, `kits/<name>/SKILL.md`, is an Agent Skill (`name`, `description`,
optional `tags`); `brain recall "kit <name>"` returns its path. Projects need nothing;
`projects.json` adds `paths`, `remote`, `aliases` and `tags`:

```json
{ "projects": { "sztool": { "aliases": ["sz-tool", "sz-tools"], "tags": ["sparking-zero"] } } }
```

`brain check` reports any file it cannot read.

## 6. Develop

```bash
npm ci
npx eslint src test && npx tsc --noEmit && npx vitest run
```

`test/eval.test.ts` runs the frozen V3 recall cases against the committed `notes/`. Rules for
changes: [the V4 plan](../docs/intake/2026-09-27-plan-v4-agent-experience.md) §3.2.
