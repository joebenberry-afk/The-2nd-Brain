# Second Brain V4 — install, verify, roll back

## 1. Install (Windows, in the Brain checkout)

```powershell
git status                                # commit or stash local changes first
.\scripts\install-v4.ps1
```

The installer (every step reversible):
- picks the runtime — Node ≥ 22.18, else Bun — and writes `brain\bin\brain.cmd` (cmd.exe) and
  `brain\bin\brain.ps1` (PowerShell prefers it; through `brain.cmd`, cmd.exe would expand `%VAR%`
  inside note text — it needs an execution policy such as RemoteSigned: under Restricted or
  AllSigned, which refuse it without falling back, the installer keeps `brain.cmd` alone and says
  so) next to the committed `brain\bin\brain` shim (Git Bash, where Claude Code runs
  hooks, needs that one), then adds `brain\bin` to your user PATH, keeping `%VAR%` entries intact
  (`-NoPath` skips that). In PowerShell a bare `--` is dropped: text that starts with `-` and
  contains a space needs none; otherwise quote it (`'--'`);
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
brain check     # notes: N (A active) · projects: P — exit 0
brain card      # the start card a Claude Code session in this checkout will see
```

Restart OMP from that new terminal.

**Other projects' notes.** A project's id comes from its git remote or folder name (a linked
worktree takes its main checkout's name); a folder without git belongs to the nearest folder
above it that `projects.json` names (an id or alias), never your home folder or anything above
it, so `cd scripts` stays in the project. A git repo inside a declared `paths` folder stays the root; the declared folder's
registered docs also resolve from it. If a repo on
this machine resolves to a different id than its notes use (`brain card` in it shows nothing you
expected), add its `remote` or the id as an alias in `projects.json` — e.g. the SZ-tool notes
live under `sztool`, which lists the SZ-Agent-Toolkit remote. `brain move <id> --to <project>`
re-homes one note; `brain check` lists notes still filed under an alias. A recall that finds nothing here but something elsewhere says so:
`no match here; N related in other projects (--all)`. Recall answers with silence rather than a
weak match: two words of a longer query must match, the project's own name ("Absolute Laya …")
does not count inside that project, and file names and versions (`LOOP.md`, `18.4.1`) match
whole, not as "loop" or "update". The matched words must also carry at least a fifth of the
query's information (half for one- or two-word queries), so words common across the notes count
for little. A keyword list (five or more words) must also be about the note's subject: two of its
words in the note's first line, or half of a short one. When no note answers, recall names the best heading of the project's plan docs
instead: `docs/LOOP.md › Goals (line 12)`.

**Recall relevance check.** With `TYPESAFE_API_KEY` set, CLI, OMP and MCP recall use TypeSafe
Jev (`jev-latest`) to check the notes the lexical search would show. Notes scoring below **0.78**
are dropped (0.75 let 1-2 wrong answers through on reruns of the same 54 queries: Jev drifts about
±0.02 between calls; 0.78 gave none in four runs), without promoting unjudged runners-up; the usual doc-heading or no-match fallback
still applies. Only the scrubbed query and note body text (whitespace collapsed, scrubbed, then
cut to 450 characters, so a secret at the cut is masked whole) are sent. Private notes are never sent and remain lexical, unjudged.
A plan-doc heading answer (its heading and best-matching paragraph) is checked the same way; the outline of a doc the query names by file, explicit note-id reads and the start card are not.
When a doc heading could become the fallback answer, it is checked in the same request as the
notes, so a rejected note no longer costs a second sequential call (54-query replay: 44 → 39
requests, 58 → 64 questions); surviving notes still win over the heading.
Set `BRAIN_JUDGE=off` to opt out; without a key, or on timeout, HTTP or parse errors, recall
**fails open** to its unchanged lexical answer. Calls take about 300 ms, with a 5-second
timeout. A small per-process cache avoids repeated calls for the same query, note id and text.
The endpoint defaults to `https://api.typesafe.ai` (`TYPESAFE_BASE_URL` overrides it).
Recall telemetry retains query/ids and adds `judged` (a successful check) and `dropped` (count).

**Isolated subagents.** An OMP isolated child runs in a scratch copy (`~/.omp/wt/<id>/m`) whose folder
names no project; a child whose own folder is undeclared and has no git remote works for its live
parent's project — card, recall, notes, known fixes and logged events — instead of a phantom `m`
(61 child sessions in one week had run with no project notes at all).

**Tora (optional local scorer).** While a Tora session (a local EmbeddingGemma 2 scorer that lives
as long as its agent session) is running, judged recall asks it to score the query against every
visible, non-private, non-retired note (`%LOCALAPPDATA%\tora\sessions\<pid>.json` says where it
listens; a stale file whose process is gone is ignored). The two best notes at or above Tora's own
confidence cut that the lexical search missed join the lexical candidates in the same Jev request;
they appear, after whatever recall would answer without Tora (a plan-doc heading included, still
checked as before), only if Jev keeps them (0.78), within the usual three
lines. Tora only adds: it never removes or replaces that answer, and it is **optional and fails open**:
no session, a refused or slow (0.8 s) call, or a malformed answer leaves recall exactly as it was. `BRAIN_TORA=off` disables it.
Jev still needs `TYPESAFE_API_KEY`; without a judge, Tora is not asked.
When every candidate scores under the floor (0.70), the Jev call could be skipped. That is only
logged (**shadow**) unless `BRAIN_TORA_SKIP=on` enforces it: then no Jev call is made for the
candidates, they are dropped like a rejected batch (`judged` is false unless the doc check still ran), and the doc fallback applies as usual. Recall rows gain `tora` (`ms`, `cut`, `floor`,
`skip`, `enforced`, and `c`: `[id, cosine, Jev probability, "l"exical | "t"ora-added, kept]` per candidate; `kept` is 1 when the
answer kept it by its own rule (0.78, or the phrase floor), 0 when dropped, null when Jev gave no verdict)
only when Tora answered. `brain stats` summarises them: recalls scored, candidates Tora added and
Jev kept, recalls the floor would skip, `lost` (Jev-kept candidates inside those: answers enforcing
would have lost), and kept candidates scoring under the floor. The last line is the verdict:
`skip floor: ready` only when `lost` is 0 and at least 150 Jev-kept candidates carry a Tora score;
otherwise `not ready` with the reason. Set `BRAIN_TORA_SKIP=on` only after it says ready.

**Tidy and note usage.** `brain tidy [--all] [--days N]` is a read-only report of duplicate or
contradictory notes and active notes older than N days (default 30) with no recent use. Without
a judge key it lists lexical similarities, not semantic claims. With `TYPESAFE_API_KEY`, public
pairs are checked in batches of at most 20; private text never leaves the machine, and judge
failures leave lexical suggestions intact. Retire commands are suggestions only, keeping the
newer note. New public CLI/tool notes can append a duplicate/contradiction hint; no hint changes
the normal reply, and subagents skip it. Local per-note telemetry counts recalls, explicit id
opens, rendered card appearances and fix fires across the current and rotated logs. One 1 MiB
telemetry generation holds about two weeks, so `brain tidy` and `brain stats` name the window
the retained rows actually cover (`Unused 17d, telemetry since …; 30d asked`) and judge unused
notes only within it.
`brain stats --days N` reports used/never-used active notes across the Brain home, like its
other usage totals; retained telemetry, not an unlimited lifetime history, defines that window.

**Plan docs and anchors.** `brain project docs add docs/LOOP.md` (and `brain project docs list`,
which marks an entry that does not resolve here `(missing under <root>)`)
lets the Brain read a project's own plan files: only headings and the text under one heading
(YAML front matter is skipped),
never code. A working state line `See: docs/LOOP.md#checkpoint` is shown as that section's current
text wherever the state appears (card, `brain state`), so the state never drifts from the
repo; a missing file or heading shows `anchor missing: …`, never an old copy. Saving a state
whose anchor resolves to nothing already says `anchor missing: …`. An anchor written inside a
sentence (`… Next: patch it. See: docs/LOOP.md#checkpoint.`) is moved onto its own line when the
state is saved, trailing punctuation dropped, so it renders and is checked like one written alone.
A bare section number (`#17`, `#9.1`) names the heading numbered that way (`## 17. Scoreboard`).

Recall searches the whole registered section, preferring more distinct query terms and then heading matches; unnamed queries need at least two distinct matching terms. `brain project docs suggest [-n N]` (default 5) ranks checkout Markdown files by distinct silent or doc-answered queries logged locally in the last 30 days, skips registered docs, and prints explicit `brain project docs add <path>` commands. It never registers files itself or sends scanned docs to a judge. `--project <id>` uses that project's existing declared checkout when run elsewhere. Scanning uses git-tracked Markdown when available, otherwise a bounded walk excluding hidden folders and `node_modules` (at most 2,000 files, 512 KiB each).

## 2. Verify in the first sessions

1. **Start card.** Start OMP in a project: the first turn carries a hidden `brain.card` message
   (≤ 320 tokens: where we left off, up to five complete notes ranked by the first prompt);
   later prompts add nothing, and a session resumed in a new OMP process (restart,
   `/resume`) keeps the card it already holds until a compaction. Child cards on both hosts are
   capped at **200 tokens total**: the parent plan’s Watch out field (≤40 tokens), up to two
   recurring fixes counted over child sessions, standing rules (≤6 lines/80 tokens), up to eight
   parent-session edited paths, and live H2/H3 doc headings with line numbers (≤60 tokens). A
   complete section whose heading best matches the brief is included only when it fits both
   ≤120 tokens and the remaining card budget; ordinary project notes use leftover space. Children
   never inherit Goal/Next/Done or auto observations, and cannot overwrite state through the
   Brain tools (the CLI can: see below).
   Only main-session startup scans capture logs. `brain stats` separates main and sub cards.
   A tested fix that fired in 3+ sessions of the same role (child or main) this week is said on
   the card up front (`Often hit lately …`, at most two, ≤80 tokens per parent fix), before the first attempt; fixes too long for that slot stay ordinary-note candidates. It drops off by itself
   once the mistake stops. Measured on GPT subagents: the OMP edit-grammar mistake fell from
   8/8 first edits to 2/8 with that line in the task; live on OMP 18.4.0, children whose card
   carried it (after 3 had hit the mistake) failed 0/5 first edits vs 3/3 before, for +39 tokens.
   The card holds only what the agent can act on: pending proposal counts stay in `brain review`,
   and where the `brain_*` tools are resident (OMP) their descriptions carry the when-to-act
   guidance, so the card ends with the lean-work line; CLI hosts (Claude Code, `brain card`) also
   get the CLI line. Measured over the 20 projects of the live home (2026-10-14), with the budget
   lowered from 400 to 320 tokens: OMP main cards −19%, CLI main cards −17%, OMP child cards −8%.

   Add a standing child rule with `brain note "Use Node built-ins only" --tag brief`. Active
   project-visible notes tagged `brief` are supplied once in the child rule block, not repeated
   under Known here. `brief` is non-scoping: brief-only globals apply everywhere; other global
   tags still require a project match. The parent card says
   `children get: <n> rules` instead of repeating their bodies. OMP takes paths from the live
   parent session and doc names from the first child prompt. Claude Code takes paths from the
   parent’s captured event log; its documented SubagentStart input has no brief/prompt, so it
   uses registered docs only. All lookups are local and read-only; only card ids/costs are logged.
2. **Working state.** Ask the agent to set the plan (`brain_state`) when the goal or next step
   changes. OMP's own compaction summary carries goal and next: both were recalled in 100% of
   measured short and long sessions, with or without extra Brain context. The long sessions
   included three compactions and a goal change; OMP kept the new goal in every run. The Brain
   adds nothing after compaction. Its working state reaches the next session's start card.
   At compaction, shutdown and session switches, files edited and the last ask are saved locally
   in `state/work/<project>.auto.md`, never synced; the agent-written plan is preserved. The plan
   is marked possibly stale when auto observations are over three days newer, or HEAD has commits
   since the plan was written (a count and up to three short commit subjects are shown; commits
   that touch only the Brain home's own `notes/` and `work/` do not count). A
   `See: path#heading` line is rendered from the checkout at that moment (see *Plan docs and anchors*).
3. **Known fix.** Run something that fails with an error a tested note names — e.g. an OMP edit
   without a `[path#tag]` header (`notes/global/` holds fixes taken from logged OMP failures): the
   failed result ends with `Brain: … [id]` on its own line. The same fix again in the same context
   is a one-line pointer (`Brain: same fix as above [id]`) until a compaction drops the original.
4. **Learning.** After a few sessions, `brain review` lists (this project's and global ones;
   `--all` for every project), with their full bodies, failed
   commands that later succeeded as retries (same program and arguments, flags or a preparatory
   step added — `npm test` → `npm ci && npm test`), plus `Brain-Decision:` / `Brain-Gotcha:`
   commit trailers; `brain accept <id>` makes a note. A pair is `tested` only when the failed
   command itself succeeded afterwards. Exploration (grep, ls, cat …), the Brain's own CLI,
   `--help` probes, inline scripts and heredocs (`python -c`, `node -e`, `<<EOF` before the
   script) and scripts under OS temp roots (including Git Bash `$TEMP`/`$TMP`) or a top-level
   `tmp/`, `temp/`, `cache/`, `.cache/` are never proposed; nor is a success after an edit,
   `sed -i` or a `>` redirect included (the code was repaired, not the command).

   **Tested fixes learn themselves.** A tested pair from a project session (the failed command
   itself succeeded afterwards, as above) with a matchable error is written as a note at once — source
   `capture`, tested by `capture`, with its error pattern and evidence — with no inbox file and
   no `brain review` — but only when its error pattern is specific: a whole diagnostic line of at
   most 120 characters, never a cut prefix (`ModuleNotFoundError: No module named`), a stdout line
   or a bare exit status, and never from an OMP isolated worktree (`~/.omp/wt/`). The note id is
   derived from the proposal, so two scans that overlap write one note, not two. It is skipped
   when its error or headline was rejected or dismissed (a signature printed by `brain review` and
   dismissed also stops it), or a note already covers it, and it is never re-created. Untested
   pairs, global-scope pairs, unspecific patterns, owner rules, commit trailers and Claude memory
   still wait for `brain review`; a fix that helps under half of 4+ runs is still paused.

   **Owner rules and Claude memory.** Main-session owner messages with durable cues (remember,
   always/never, from now on, preferences or agent-model choices) become scrubbed, ≤400-character
   pending `user` decisions, never prompt injections; questions, code/quoted examples, child
   instructions and private-path messages are ignored, and so are pasted material (markdown list
   items, headings and `**Label:**` lines, or any message holding three or more rule cues),
   narrative (`I remember you saying …`) and task requests (`I want you to create …`); pending rule
   proposals the current rules would no longer take are dropped at the next scan (live inbox,
   2026-10-15: 8 of 15). `brain accept` preserves source `user`
   and adds `brief` for agent/model or always/never work rules. `brief` never scopes a global
   note: a brief-only global applies everywhere; additional project tags still constrain it.
   `brain review [--all]` also lists read-only, accept/reject-able `claude-memory` proposals
   from `~/.claude/projects/<encoded path>/memory/*.md` (`CLAUDE_CONFIG_DIR` overrides `~/.claude`; CLI calls use their supplied environment),
   excluding `MEMORY.md`, unreadable files and private paths. Declared project paths
   map worktrees to their owner; undeclared folders use a bounded transcript cwd lookup or match
   their encoding against real directory names (only matching prefixes, no file content scan). An
   active, unexpired visible note covers an import when its headline matches or it contains
   ≥80% of the candidate’s distinct words with matching negation: a conservative lexical check,
   not semantic reconciliation. Accepted imports retain their body and provenance; rejected
   headlines stay suppressed. No judge or network is used and Claude’s files are never changed.

   Review also lists the five most frequent unmatched errors from the last 14 days, for this
   project and global scope (`--all` includes other projects), with the last tool and next
   successful step as context. Save a real repair with the suggested literal `--error` and
   `--tested` to close the loop, or `brain dismiss "<signature>"` to ignore it; dismissal hashes
   sync in `rejected.json`, without the error text. New `brain note`/`brain_note` notes without
   explicit evidence attach up to three existing repo-relative files named in the text, or
   session edits named by basename; private, outside-root and scratch files are excluded.
   Existing-headline upgrades are unchanged, and missing evidence later marks recall as stale.
   Correct a note in one write with `brain_note(text, replaces: "<id>")` or
   `brain note "<correction>" --replaces <id>`: the new note is saved, the old one retired, and both
   linked. Missing or already-retired replacement targets are rejected before saving.
5. **Weekly.** `brain stats --days 7`: moments and token costs, main vs subagent cards, recall
   hit rate, which fixes fired in how many sessions, errors the Brain swallowed to keep the host
   running (latest three), and frequent errors without a fix. Each recall row keeps its query
   (masked, ≤ 200 chars) and the ids it answered with, locally only (`recall: N queries logged,
   S silent`). A fired fix is judged by the first run of the same command that started after the
   model saw the fix — in OMP after its next `context` event, in Claude Code from a later model
   message than the one that got it (a call the transcript cannot place stays pending). Siblings
   in the same parallel batch and calls nested in one eval cell ran before the fix was read and
   decide nothing; outcome rows already logged within a second of their fire do not count either.
   `evaltimeout` and `rawhint` are judged by the next JS eval cell their detector checks, whatever
   its code. `fix outcomes: <id> helped H/missed M` (an aborted or cancelled rerun decides nothing);
   a fix that helped under half the time over 4+ runs since its note last changed is paused (no
   longer fired, not on the card's `Often hit lately` lines) and listed under `Fixes to review` in
   stats and `brain review`. The note file is never changed; editing it gives the fix a new trial.
   Live telemetry, 7 days to 2026-10-15: of 429 outcomes, 80 were such artifacts; attributable
   ones are 336 helped / 13 missed, and the global `Path …:N not found` fix they had paused fires
   again (its own record: 3 helped, 0 missed). A plan-doc answer counts as answered (`doc:<path>`), not silent.
   `tool use by surface:` counts recall/note/state calls separately for OMP tools, CLI and MCP (a
   Claude Code agent's calls count as CLI); old rows lacking attribution are excluded from this
   split, not guessed to be OMP. `brain tools used in: X/Y main sessions · x/y sub` counts, per
   role, sessions that called recall/note/state; sub counts only children whose tool use is
   observable (OMP), since a Claude Code subagent's calls carry its parent's session. `cards:`
   counts delivered cards; a `brain card` preview is not one. Every row carries the build that
   wrote it (newest source mtime); stats count only the newest build unless `--all-builds`: OMP
   and MCP processes keep the build they started with, while hooks and CLI calls stamp the build
   current at each call, so a session's role comes from all its rows in the window.
   `tool schemas (OMP, <date>): N active ≈ T tokens per request · uncalled Nd: U ≈ W tokens`
   sets the schemas the newest OMP main session sent top-level (snapshot at its first prompt;
   tools mounted under `xd://` ship a route line, not a schema, and are left out) against tool
   calls in the event logs; the biggest uncalled ones are listed. Disabling them is host config
   (OMP MCP/tool settings), not a Brain change. Anything never used for a week gets removed
   (plan rule 1).

Tool descriptions say when to act: recall before exploring, choosing or retrying; notes for
repo-invisible learning; state when goal/next changes. Cards repeat it only for CLI hosts. OMP
subagents keep only `brain_recall`: the Brain deactivates `brain_note` and `brain_state` in each
child session at `session_start`, saving ~250 schema tokens per child request. The CLI cannot
tell a child from its parent: a child's project-scoped `brain note --tested` is tested at once
(a global one stays untested until the owner runs `brain tested <id>`), and its `brain state`
replaces the parent's plan. That reaches OMP children through bash and Claude Code subagents, whose instructions carry the managed block (`brain state` when the goal changes).

**Context hand-off.** Main sessions above 150,000 context tokens get one ≤40-token rollover
line per crossing: save `brain_state` with Goal/Next/See: and open a fresh session; its start
card carries the saved state. `projects.json` accepts a project-level numeric `rollover`
threshold (tokens); `0` disables the hint. Unknown usage is silent, subagents never get it,
and the latch survives hook processes and OMP restarts, rearming only when usage drops back
below the threshold. OMP queues the hint for the next model turn without starting an extra
turn. Claude Code reads the latest assistant input/cache usage from a bounded transcript
tail: PostToolUse adds model context, while Stop only shows a nonblocking user warning.
The paid `node scripts/compactbench.ts --scenario rollover --reps 4 --label v5-rollover`
trial compares continued long contexts with state-save plus RPC `new_session`, including
handoff cost and goal retention. Its isolated evidence defaults to an OS temporary directory,
not the real Brain home; `--output` selects another directory.
Same-batch `v5-rollover-20261004` (GPT-6 Astra, 4+4 sessions, ~424k seeded tokens)
finished 16/16 edits and retained goal/next 4/4 in each arm. Recorded total cost, including
seeding and handoff, fell from $40.1323 to $21.0601 ($2.5083 to $1.3163 per finished task,
−47.5%); continuation cost fell from $23.1659 to $4.1466 (−82.1%). The feature is kept.
This trial scripts compliance with the hint; it does not prove agents initiate rollover unprompted.
`--threshold 150000 --seed-rows 4400 --label v5-rollover-150k` (157k seeded, 4+4, 2026-10-05)
also kept 16/16 and 4/4 per arm: $0.928 → $0.525 per finished task (−43.4%), continuation
$8.58 → $2.10 (−75.5%); the $0.32 handoff pays back within one task. The default dropped from
250k to 150k on this result.

## 3. Other harnesses

**Claude Code.** In `~/.claude/settings.json` (or a project’s `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "SubagentStart": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "PostToolUse": [{ "matcher": "^(Bash|PowerShell|Edit|Write|MultiEdit)$", "hooks": [{ "type": "command", "timeout": 30, "async": true, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "PostToolUseFailure": [{ "matcher": "^(Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit|Read|Grep|Glob|LS)$", "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "PreCompact": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }]
  }
}
```

The `[ -f … ]` guard leaves a Brain checkout to its own `.claude/settings.json`, which registers
these hooks with another command: Claude Code de-duplicates only identical handlers, so both would
run (two cards, every fix twice). The handler fails open (`{}`, exit 0; the swallowed error
becomes a `brain stats` row), and `2>/dev/null || echo "{}"` covers a missing `brain` or runtime.
The 30-second timeout also lifts SessionEnd's shared 1.5-second budget. PostToolUse runs
`async` rather than holding every tool result about 300 ms; it may return a rollover hint
for the next model context. The other hooks stay synchronous (card, fix, state, Stop warning). A PreCompact or SessionEnd right after the last
tool call can miss that call's event, and `claude -p` stops a PostToolUse still running at exit.

Successful and failed tools share the capture log (a backgrounded Bash launch is not logged), so
a failed command followed by its successful repair can become a proposal. A failure whose error a
tested note names gets the fix (`Brain: … [id]`) once per context; a repeat gets the one-line
pointer. The capture scan runs at SessionEnd and PreCompact, off the startup path (SessionStart on
a 949-log home: ~820 → ~410 ms). PreCompact and SessionEnd save edited files (outside the project, not those under
`~/.claude`, the session scratchpad or a temp root) and the last user ask available in the last
256 KiB of the transcript
(else Claude Code's `last-prompt` row; task notifications and slash commands are not asks) to
local auto state; the agent-written plan is never replaced.
SessionStart source `compact` or `resume` adds no context; saved state feeds the next session's card.
A failed Read, Grep, Glob, LS or NotebookEdit naming a missing path gets the same "did you mean"
path hint as OMP; listing candidates is best-effort within 150 ms and skipped for a drive, home or
temp root (one OMP tool result had been held 24.7 s by an unbounded walk). The Git Bash shim
starts `node` directly (`command -v`), and `brain.mjs` hands a Node older than 22.18 to Bun.
Hooks with `agent_id`, SubagentStart and SubagentStop never write working state; child tool
logs are separate from their parent’s. `agent_type` alone is also used by main sessions
started with `--agent` and does not imply a child. Tool hooks do not spawn git.
SubagentStart returns the child card as `hookSpecificOutput.additionalContext` and logs a
`sub: true` card row under the child’s session identity; empty cards return `{}`.
This checkout preserves its cloud setup hook and calls `bash brain/bin/brain` (Node or Bun).
Payloads follow the [Claude Code hook reference](https://code.claude.com/docs/en/hooks).

**Codex or any agent.** Run `brain hook agents-md` and copy its six-line managed block into
the project’s AGENTS.md (or the harness’s equivalent instructions file). It explains when
to use the CLI: recall before exploring unfamiliar ground, choosing tools/stacks or retrying;
note what the repo cannot tell you; state when goal or next changes; fix after unexplained
failures. `brain fix "<error>"` returns the same tested, scoped known fix as OMP (≤80 tokens),
or prints nothing and exits 0 when none matches. Set `SECOND_BRAIN_HOME`; optional
`BRAIN_SESSION` (preferred), Claude Code’s `CLAUDE_CODE_SESSION_ID` or `CLAUDE_SESSION_ID`
attributes CLI usage to the session.

**MCP clients.** Launch `brain mcp` as a stdio server to expose the same three tool definitions
as OMP: `brain_recall`, `brain_note` and `brain_state`. Launch in the workspace directory
(or set `BRAIN_PROJECT`) and set `SECOND_BRAIN_HOME`. MCP has no subagent identity: the host
must withhold `brain_state` from child agents to protect the parent’s working state.

## 4. Roll back

```powershell
.\scripts\uninstall-v4.ps1 -Restore      # removes the V4 extension, restores the parked one
```

Restart OMP. `-RemovePath` also takes `brain\bin` off your PATH and deletes the generated
`brain.cmd` and `brain.ps1`. Notes and working state
stay as files. The parked V2/V3 extensions expect the pre-V4 tree (tag `v2-archive`), which
this checkout no longer contains.

## 5. The files (edit them by hand when you like)

A note, `notes/<project>/<id>.md` (scope comes from the folder: a project, `global`, or
`<project>/private/` which never syncs: `brain sync` refuses to push if any outgoing commit holds
a private note; it also refuses a detached HEAD or a rebase, merge, bisect, cherry-pick or revert
in progress, committing nothing). Credentials in notes, working state, events and V3 imports are
masked on every write (`--db-password x` included; prose such as `Unexpected token: identifier`
is left alone), including Hugging Face, Shopify, PyPI, Vault, DigitalOcean, Google OAuth, Telegram
and Discord tokens and Azure SAS signatures; a reference that names a variable and nothing else
(`process.env.X`, `$DB_PASSWORD`, `${{ secrets.X }}`, `os.environ['X']`), booleans, null,
`credentials: 'include'` and settings such as `password_min_length=12` stay readable. An error
pattern that stops compiling once its secret is masked is refused, and `brain check` lists
active notes whose stored pattern is invalid. A
tag that carries a secret is refused:

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
tested_by: owner           # who verified it: owner (brain tested) | capture | agent | convert
tested_at: 2026-09-28T09:00:00Z
host: omp                  # optional: fires only on this host (omp | claude-code), lower case; brain check reports any other value
stale_after: 2027-01-01    # optional: out of date from this date (UTC) or ISO instant on
---

Clear PYTHONHOME before running python        ← the first line is the headline

Why and how, in as much detail as helps.
```

A duplicate headline with a different normalized body is refused without altering the original:
choose a new headline, or retire the original first. Identical bodies can still upgrade metadata.
Headlines are compared after secret masking, and a `--global --tag t` note is compared with the
global notes sharing one of its tags. `brain tested <id>` run outside the note's own checkout keeps
its evidence hashes instead of re-stamping them from the wrong repository.
Within the recall shortlist, notes whose file evidence is entirely missing sort after fresh hits
and carry `(stale evidence)`; notes past `stale_after` (`brain note --stale-after <date>`) do the
same with `(stale since <date>)` and are never pushed as a known fix. Cards apply a -3 ranking
penalty to both without hiding the note, and rank them behind live notes even when the first
prompt matches them, as recall does. A
stat-validated per-process cache reuses unchanged parsed notes; Markdown remains the truth.

**Content-bound trust and keyword recall.** New file evidence (explicit or automatic, including metadata upgrades) stores flat `evidence_sha` entries (`path=12hex`, SHA-256 of file bytes with CRLF normalized); verification refreshes those snapshots and stores `tested_sha` over the whitespace-normalized body plus error patterns. Changed readable evidence shows `(evidence changed)` and gets the same -3 card penalty as missing evidence; a change after `tested_at` prevents a known-fix push. An edited verified body/error pattern loses its +3 tested bonus and fix eligibility, with `(edited since tested)` on an id read; `brain tested <id>` re-stamps both fingerprints. Missing files retain the existing advisory behavior, and absent `tested_sha` is legacy trusted (mi…

`brain export <dir>` writes the public notes as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
0.2 bundle for OKF readers: `kind` becomes `type`, `tested_by` becomes `verified` (`human:owner`
only for the owner), retired notes become `status: deprecated` with links to their replacement.
Private notes are never exported. The folder must be empty or an earlier export (which is
replaced), and outside the Brain home except under `state/`.

Retiring keeps the file (`retired:`, `replaced_by:`); `brain retire <id> [--by <new id>]` writes
both sides. Recall prefers a visible current replacement with a short retired-note reference;
explicit note ids and `--history` still expose retired details. A working state, `work/<project>.md`,
is the agent’s plan as free text under a
one-line frontmatter (`at:`); an `## auto` section left by older versions is shown until the next
`brain_state` drops it. Proven setups live as global `procedure` notes in `notes/global/`.
Recall them normally: `brain recall "node typescript cli scaffold setup"` or
`brain recall "omp extension setup"`; recall a returned note id for its instructions
(≤ 600 tokens). These setup notes are untagged: available from an empty directory,
but pull-only, so they do not occupy unrelated start cards. Projects need nothing;
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
both Vitest projects; `npm run check` adds lint and type checking. Every run puts its throwaway
homes and repos under one `brain-test-run-*` folder in the OS temp directory and removes it at the
end (`TMPDIR`/`TEMP`/`TMP` point there for the tests and their child processes); runs before
2026-10-15 left about 1,000 `brain-*` folders each. The full gate includes
`test/eval.test.ts`, which runs the frozen V3 recall queries against the committed live `notes/`
and grades judged answers on the hand-labelled real queries, plan-doc headings included: the four
registered docs are frozen as fixtures, each doc section carries a majority-of-three blind label,
every candidate the judge would see must have recordings (four runs), and an unexpected or
unlabelled doc answer counts as wrong. Current result on all four runs: frozen 34 right 7–8,
held-out 20 right 4–5, judged wrong 0.
`npm run perf` measures real-home read paths plus isolated synthetic 1,000/5,000-note corpora,
using Node built-ins and recording aggregates in `state/perf.json` with previous-run deltas.

`node scripts/agentbench.ts` runs small coding tasks (rename, fix, find, combo, and a memory
task whose answer lives only in a Brain note) with headless OMP agents, Brain `off` vs `on` vs
experiments (`on+<name>`, read from `BRAIN_EXPERIMENT`) and host settings (`+@<preset>`), scores
each run from its session file and ranks by cost against the same-batch control (batches drift
±5–10 %). It costs real model usage: GPT first, then Grok/Google, Claude last. Results append to
`state/agentbench.jsonl`; session files stay in `state/agentbench/` for turn-by-turn analysis.
Latest (GPT, v3, 20 runs each): Brain on vs off −30 % tokens, −39 % cost, 6.7 vs 9.2 turns,
20/20 vs 16/20 passing.
Rules: [the V4 plan](../docs/intake/2026-09-27-plan-v4-agent-experience.md) §3.2.
