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
   kits); later prompts add nothing. Subagents inherit only the parent plan’s Watch out field
   (≤40 tokens), never Goal/Next/Done, auto observations or kits, and cannot overwrite state.
   Only main-session startup scans capture logs. `brain stats` separates main and sub cards.
   A tested fix that fired in 3+ sessions of the same role (child or main) this week is said on
   the card up front (`Often hit lately …`), before the first attempt; it drops off by itself
   once the mistake stops. Measured on GPT subagents: the OMP edit-grammar mistake fell from
   8/8 first edits to 2/8 with that line in the task; live on OMP 18.4.0, children whose card
   carried it (after 3 had hit the mistake) failed 0/5 first edits vs 3/3 before, for +39 tokens.
2. **Working state.** Ask the agent to set the plan (`brain_state`). Then force a compaction
   (`/compact`) and ask "where are we?": the answer should give goal and next step without
   re-reading files. Compaction re-injects only the working state (≤ 150 tokens: Goal and Next
   first). Files edited, the last failure and the last ask are kept locally in
   `state/work/<project>.auto.md`, never synced.
3. **Known fix.** Run something that fails with an error a tested note names — e.g. an OMP edit
   without a `[path#tag]` header (`notes/global/` holds fixes taken from logged OMP failures): the
   failed result ends with `Brain: … [id]` on its own line. The same fix again in the same context
   is a one-line pointer (`Brain: same fix as above [id]`) until a compaction drops the original.
4. **Learning.** After a few sessions, `brain review` lists, with their full bodies, failed
   commands that later succeeded as retries (same program and arguments, flags or a preparatory
   step added — `npm test` → `npm ci && npm test`), plus `Brain-Decision:` / `Brain-Gotcha:`
   commit trailers; `brain accept <id>` makes a note. A pair is `tested` only when the failed
   command itself succeeded afterwards. Exploration (grep, ls, cat …), inline scripts and
   heredocs (`python -c`, `node -e`, `<<EOF` before the script) and scripts under OS temp roots or
   a top-level `tmp/`, `temp/`, `cache/`, `.cache/` are never proposed.
5. **Weekly.** `brain stats --days 7`: moments and token costs, main vs subagent cards, recall
   hit rate, which fixes fired in how many sessions, and frequent errors without a fix.
   `tool use by surface:` counts recall/note/state calls separately for OMP tools, CLI, hooks and
   MCP; old rows lacking attribution are excluded from this split, not guessed to be OMP. Every
   row carries the build that wrote it (newest source mtime); stats read only the newest build
   unless `--all-builds`, because a running session keeps the code it started with. Anything
   never used for a week gets removed (plan rule 1).

Tool descriptions and card footers say when to act: recall before exploring, choosing or retrying;
notes for repo-invisible learning; state when goal/next changes. OMP subagents keep only
`brain_recall` (their card says so): the Brain deactivates `brain_note` and `brain_state` in each
child session at `session_start`, saving ~250 schema tokens per child request. A child note
written another way (CLI) stays untested until a parent confirms it or runs `brain tested <id>`.

**Opt-in: end-of-turn learning nudge.** With `BRAIN_STOP_NUDGE=on` in OMP's environment
(`[Environment]::SetEnvironmentVariable("BRAIN_STOP_NUDGE", "on", "User")`, then restart OMP),
a main session that ran 30 tool calls since its last `brain_note`/`brain_state` gets one hidden
continuation turn when it is about to stop: save the working state or a learning, or reply
"nothing to save". At most once per session, never for subagents; `brain stats` counts `nudge`.
This amends plan rule 4 ("never continues host work") for this one moment, by owner decision.

## 3. Other harnesses

**Claude Code.** In `~/.claude/settings.json` (or a project’s `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }],
    "PostToolUse": [{ "matcher": "^(Bash|PowerShell|Edit|Write|MultiEdit)$", "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }],
    "PostToolUseFailure": [{ "matcher": "^(Bash|PowerShell|Edit|Write|MultiEdit)$", "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }],
    "PreCompact": [{ "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "brain hook claude-code" }] }]
  }
}
```

The hook fails open (`{}`, exit 0). Successful and failed tools share the capture log, so a
failed command followed by its successful repair can become a proposal. PreCompact and
SessionEnd save edited files, the last failure, and the last user ask available in the last
256 KiB of the transcript to local auto state; the agent-written plan is never replaced.
After compaction, SessionStart source `compact` returns only the ≤150-token resume.
Hooks with `agent_id`, SubagentStart and SubagentStop never write working state; child tool
logs are separate from their parent’s. `agent_type` alone is also used by main sessions
started with `--agent` and does not imply a child. Tool hooks do not spawn git.
This checkout preserves its cloud setup hook and calls `bash brain/bin/brain` (Node or Bun).
Payloads follow the [Claude Code hook reference](https://code.claude.com/docs/en/hooks).

**Codex or any agent.** Run `brain hook agents-md` and copy its six-line managed block into
the project’s AGENTS.md (or the harness’s equivalent instructions file). It explains when
to use the CLI: recall before exploring unfamiliar ground, choosing tools/stacks or retrying;
note what the repo cannot tell you; state when goal or next changes; fix after unexplained
failures. `brain fix "<error>"` returns the same tested, scoped known fix as OMP (≤80 tokens),
or prints nothing and exits 0 when none matches. Set `SECOND_BRAIN_HOME`; optional
`BRAIN_SESSION` (preferred) or `CLAUDE_SESSION_ID` attributes CLI usage to the session.

**MCP clients.** Launch `brain mcp` as a stdio server to expose the same three tool definitions
as OMP: `brain_recall`, `brain_note` and `brain_state`. Launch in the workspace directory
(or set `BRAIN_PROJECT`) and set `SECOND_BRAIN_HOME`. MCP has no subagent identity: the host
must withhold `brain_state` from child agents to protect the parent’s working state.

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

A duplicate headline with a different normalized body is refused without altering the original:
choose a new headline, or retire the original first. Identical bodies can still upgrade metadata.
Within the recall shortlist, notes whose file evidence is entirely missing sort after fresh hits
and carry `(stale evidence)`; cards apply a -3 ranking penalty without hiding the note. A
stat-validated per-process cache reuses unchanged parsed notes; Markdown remains the truth.

Retiring keeps the file (`retired:`, `replaced_by:`); `brain retire <id> [--by <new id>]` writes
both sides. Recall prefers a visible current replacement with a short retired-note reference;
explicit note ids and `--history` still expose retired details. A working state, `work/<project>.md`,
is the agent’s plan as free text under a
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
`npm run test:unit` runs the no-subprocess test files for a fast inner loop. `npm test` runs
both Vitest projects; `npm run check` adds lint and type checking. The full gate includes
`test/eval.test.ts`, which runs the frozen V3 recall queries against the committed live `notes/`.
`npm run perf` measures real-home read paths plus isolated synthetic 1,000/5,000-note corpora,
using Node built-ins and recording aggregates in `state/perf.json` with previous-run deltas.
Rules: [the V4 plan](../docs/intake/2026-09-27-plan-v4-agent-experience.md) §3.2.
