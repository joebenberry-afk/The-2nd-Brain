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
  (verified live on OMP 18.3.5; a running session keeps the code it started with). An install
  made with `.\scripts\install-v4.ps1 -Copy` runs its own copy of `brain/src`: re-run that
  command after the pull, before restarting.
  If OMP does not load it (check 1 below shows no card), run `.\scripts\install-v4.ps1 -Copy`:
  a self-contained copy of `brain/src` (re-run it after each `git pull`);
- ends with `brain check` as a self-test.

No `npm install` is needed to run it (zero runtime dependencies).

Open a **new terminal** (it picks up PATH and `SECOND_BRAIN_HOME`), then:

```powershell
brain check     # notes: N (A active) · projects: P — exit 0
brain card      # the start card a Claude Code session in this checkout will see
```

Restart OMP from that new terminal.

**Other projects' notes.** A project's id comes from its registered path, git remote or folder name.
Linked worktrees inherit their main checkout's registration before remote/name fallback; a folder without git belongs to the nearest folder
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

**Recall relevance check.** CLI, OMP and MCP recall check the notes the lexical search would show
with a judge: TypeSafe Jev (`jev-latest`, paid) when `TYPESAFE_API_KEY` is set;
`BRAIN_JUDGE=off` judges nothing. Notes scoring below **0.78** are dropped
(0.75 let 1-2 wrong answers through on reruns of the same 54 queries: Jev drifts about ±0.02
between calls; 0.78 gave none in four runs), without promoting unjudged runners-up; the usual
doc-heading or no-match fallback still applies. Only the scrubbed query and note body text (whitespace collapsed, scrubbed,
then cut to 2,000 characters, so a secret at the cut is masked whole; Jev reads the first 450) are
sent. Private notes are never sent and remain lexical, unjudged.
A lone project-local **fact** that is the only visible lexical hit and scores at least twice the next
candidate is answered without a judge call: there is no competing note to choose between and no
addition slot to spend. This skipped 6 of the 100 frozen eval queries (3 dev, 1 held-out, 2 real)
with no eval precision or recall change; a dominant gotcha or a close pair of facts is still judged.
A plan-doc heading answer (its heading and best-matching paragraph) is checked the same way; the outline of a doc the query names by file, explicit note-id reads and the start card are not.
When a doc heading could become the fallback answer, it is checked in the same request as the
notes, so a rejected note no longer costs a second sequential call (54-query replay: 44 → 39
requests, 58 → 64 questions); surviving notes still win over the heading.
Without a judge, or on timeout, HTTP or parse errors, recall **fails open** to its
unchanged lexical answer. Jev answers in about 300 ms and has a 5-second timeout.
A small per-process cache avoids
repeated work for the same query and text. Jev's endpoint defaults to `https://api.typesafe.ai`
(`TYPESAFE_BASE_URL` overrides it). Recall telemetry retains query/ids and adds `judged` (a
successful check), `judge` and `dropped` (count); `brain stats` counts judged
recalls by judge, so Jev spend shows up. Compact `recall` diagnostics retain effective `all`, a hash
of project id/tags, a public-note corpus content hash, bounded public candidate IDs/stage codes,
and judge route outcome/duration (including failures). Document hits retain `doc:path#heading-anchor`,
not heading content. Queries remain scrubbed and capped at 200 characters; private note content/IDs
and endpoint credentials are not included in these diagnostics. A corpus mismatch means today's
notes cannot establish a historical retrieval miss.

**Isolated subagents.** An OMP isolated child runs in a scratch copy (`~/.omp/wt/<id>/m`) whose folder
names no project; a child whose own folder is undeclared and has no git remote works for its live
parent's project — card, recall, notes, known fixes and logged events — instead of a phantom `m`
(61 child sessions in one week had run with no project notes at all).

**The write-time hint.** `brain note` asks Jev about the three lexical neighbours in one pair
request. In OMP `brain_note` returns without waiting for that judge
  (0.8-3.9 s in OMP telemetry before, ~0.1 s after); a hint it raises (`Brain: note <id> (same as …)`)
  rides the session's next tool result, else its next prompt. The CLI, MCP and DSH still wait for it.

**Tidy and note usage.** `brain tidy [--all] [--days N] [--pair-budget N]` is a read-only report of
duplicate or contradictory notes, active notes older than N days (default 30) with no recent use,
and active global notes whose tags match no registered or inferred project tag (so no scoped
recall sees them; scope is never widened automatically). Candidates are whole-body lexical
overlap (Jaccard ≥ 0.2), plus at most 50 low-overlap extras: notes naming another note's id, and
same-project notes sharing two rare terms (held by at most three notes). Without a judge key it
lists them as unjudged similarities, not semantic claims. With `TYPESAFE_API_KEY`, public pairs
are ranked by recall/card/fix exposure and the first 20 (`--pair-budget N` for more) are judged
in batches of at most 20; the rest stay listed as unreviewed with a count. Private text never
leaves the machine, and judge failures leave lexical suggestions intact. Retire commands are suggestions only, keeping the
newer note. New public CLI/tool notes can append a duplicate/contradiction hint; no hint changes
the normal reply, and subagents skip it. Local per-note telemetry counts recalls, explicit id
opens, rendered card appearances and fix fires across the current and rotated logs. One 1 MiB
telemetry generation holds about two weeks, so `brain tidy` and `brain stats` name the window
the retained rows actually cover (`Unused 17d, telemetry since …; 30d asked`) and judge unused
notes only within it.
`brain stats --days N` reports used/never-used active notes across the Brain home, like its
other usage totals; retained telemetry, not an unlimited lifetime history, defines that window.
Its asks-by-week section reads the hosts' session files once per change: parsed per-transcript
summaries (cwd, asks; no transcript text) are cached in the derived `state/asks-cache.json`, and
which project a session belongs to is decided afresh on every run.

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
   `/resume`) keeps the card it already holds until a compaction. After a compaction the card
   comes back in full: inside a run (OMP compacts mid-loop) appended to the next tool result, else
   with the next prompt; with nothing to say, only the lean line. It never arrives as a message of
   its own: OMP starts a turn to deliver a message queued after a run's last step, and the Brain
   never continues host work. Child cards on both hosts are
   capped at **200 tokens total**: the parent plan’s Watch out field (≤40 tokens), up to two
   recurring fixes counted over child sessions, standing rules (≤6 lines/80 tokens), up to eight
   parent-session edited paths, and live H2/H3 doc headings with line numbers (≤60 tokens). A
   complete section whose heading best matches the brief is included only when it fits both
   ≤120 tokens and the remaining card budget. Naming a doc boosts its navigation entries, not
   full-section selection. Topical briefs rank navigation before its cap and omit unrelated
   headings unless their doc is named; without a brief a small source-order outline remains. Ordinary child
   notes must pass lexical recall eligibility for topical briefs;
   vague/no-brief children retain static fallback. Labels and duplicated clipped headlines are
   never substituted for complete facts.
   Children never inherit Goal/Next/Done or auto observations, and cannot overwrite state through the
   Brain tools (the CLI can: see below).
   Only main-session startup scans capture logs. `brain stats` separates main and sub cards.
   A tested fix that fired in 3+ sessions of the same role (child or main) this week is said on
   the card up front (`Often hit lately …`, at most two, ≤80 tokens per parent fix), before the first attempt; fixes too long for that slot stay ordinary-note candidates. It drops off by itself
   once the mistake stops. Measured on GPT subagents: the OMP edit-grammar mistake fell from
   8/8 first edits to 2/8 with that line in the task; live on OMP 18.4.0, children whose card
   carried it (after 3 had hit the mistake) failed 0/5 first edits vs 3/3 before, for +39 tokens.
   Expired or changed-verification fixes are not promoted as current recurring advice; missing
   historical evidence remains advisory. Card notes show recall's stale/evidence-changed markers.
   The card holds only what the agent can act on: pending proposal counts stay in `brain review`,
   and where the `brain_*` tools are resident (OMP) their descriptions carry the when-to-act
   guidance, so the card ends with the lean-work line; CLI hosts (Claude Code, `brain card`) also
   get the CLI line, unless Claude Code already loads the `brain hook agents-md` block from the
   global CLAUDE.md (or a project CLAUDE.md, directly or through `@AGENTS.md`). Measured over the 20 projects of the live home (2026-10-14), with the budget
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
   included three compactions and a goal change; OMP kept the new goal in every run. The card
   still comes back after each compaction (see *Start card*), for the notes, fixes and plan anchor
   the summary drops. The working state also reaches the next session's start card.
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
   Captured command repairs compare scrubbed, retained command tokens to compatible operations.
   Captured error patterns match through runner prefixes but not longer identifiers; numeric
   diagnostic endings never match longer numbers. Failed hooks load only global and current-project note directories.
   Outcomes follow compatible prepared retries and target paths, not exact shell strings; a different
   diagnostic is unknown rather than evidence that the same error persisted.
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
   pairs, host/shell-parser diagnostics, global-scope pairs, unspecific patterns, owner rules, commit trailers and Claude memory
   still wait for `brain review`; a fix that helps under half of 4+ runs is still paused.
   Invalid capture/git cursor shapes rebuild from the event/commit source; deterministic IDs prevent duplicates.
   Unmatched-error review validates each note body once per invocation, never across edits.
   Event and note persistence masks Cookie/Set-Cookie values, curl cookie arguments, structured session
   credentials and AWS temporary access-key identifiers. Other tools' `-b`/`-bench` flags stay intact.

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
   successful step as context. When an untested or stale note already names the error, review
   shows its id and `brain tested <id>` instead of suggesting a duplicate note. Otherwise save a
   real repair with the suggested literal `--error` and `--tested` to close the loop, or
   `brain dismiss "<signature>"` to ignore it; dismissal hashes
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
   Callable ArkType schemas are converted with draft-2020-12/fallback options before estimating.
   Brain tools fall back to their declared JSON schema if conversion fails; other unconvertible
   tools retain a name-and-description-only estimate without dropping the snapshot. The chars/4
   estimates exclude provider framing and provider-specific normalization.

Tool descriptions say when to act: recall before exploring, choosing or retrying; notes for
repo-invisible learning; state when goal/next changes. Cards repeat it only for CLI hosts. OMP
subagents keep only `brain_recall`: the Brain deactivates `brain_note` and `brain_state` in each
child session at `session_start`, saving ~250 schema tokens per child request. The CLI cannot
tell a child from its parent: a child's project-scoped `brain note --tested` is tested at once
(a global one stays untested until the owner runs `brain tested <id>`), and its `brain state`
replaces the parent's plan. That reaches OMP children through bash and Claude Code subagents, whose instructions carry the managed block (`brain state` when the goal changes).

**Context hand-off.** Main sessions above 150,000 context tokens get a ≤40-token rollover
line at the threshold and again at each further multiple of it (300k, 450k, …): save
`brain_state` with Goal/Next/See: and open a fresh session; its start card carries the saved
state. `projects.json` accepts a project-level numeric `rollover` threshold (tokens); `0`
disables the hint. Unknown usage is silent, subagents never get it, and the latch survives hook
processes and OMP restarts, rearming only when usage drops back below the threshold. OMP queues
the hint for the next model turn without starting an extra turn and shows it to the owner as a
warning notification: in 14 days to 2026-10-19, 47 sessions got the agent-only hint, then ran a
median 104 more requests and spent 17% of all OMP cost. Claude Code reads the latest assistant
input/cache usage from a bounded transcript tail: PostToolUse adds model context, while Stop
only shows a nonblocking user warning.
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
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "timeout": 30, "async": true, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "SubagentStart": [{ "hooks": [{ "type": "command", "timeout": 30, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
    "PostToolUse": [{ "matcher": "^(Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit)$", "hooks": [{ "type": "command", "timeout": 30, "async": true, "command": "[ -f \"$CLAUDE_PROJECT_DIR/brain/bin/brain\" ] && echo \"{}\" || brain hook claude-code 2>/dev/null || echo \"{}\"" }] }],
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
The installed global hooks include UserPromptSubmit, SubagentStart and Stop; this checkout owns
the same events locally. Stop stays advisory and never requests continuation.
The 30-second timeout also lifts SessionEnd's shared 1.5-second budget. PostToolUse runs
`async` rather than holding every tool result about 300 ms; it may return a rollover hint
for the next model context. UserPromptSubmit runs `async` too: rule capture returns nothing
(no per-prompt injection, D7), so no prompt waits ~180 ms on it. The other hooks stay synchronous (card, fix, state, Stop warning): an async hook's
`systemMessage` reaches the model on the next turn and is never shown to the user
(code.claude.com/docs/en/hooks, "Run hooks in the background"), so an async Stop would hide
the rollover warning from the owner it is for. A PreCompact or SessionEnd right after the last
tool call can miss that call's event, and `claude -p` stops a PostToolUse still running at exit.

Successful and failed tools share the capture log (a backgrounded Bash launch is not logged), so
a failed command followed by its successful repair can become a proposal. A failure whose error a
tested note names gets the fix (`Brain: … [id]`) once per context; a repeat gets the one-line
pointer. A fix is the note's first line, plus the next sentence when it fits, cut at 80 tokens;
saving a note with an error whose fix line is cut there says so, so the writer leads with the
remedy. The capture scan runs at SessionEnd and PreCompact, off the startup path (SessionStart on
a 949-log home: ~820 → ~410 ms). PreCompact and SessionEnd save edited files (outside the project, not those under
`~/.claude`, the session scratchpad or a temp root) and the last user ask available in the last
256 KiB of the transcript
(else Claude Code's `last-prompt` row; task notifications and slash commands are not asks) to
local auto state; the agent-written plan is never replaced. Auto observations demonstrably older
than the saved plan are omitted from its display; equal/newer or unknown timestamps remain visible.
SessionStart source `compact` gets the card again (or the lean line when it has nothing to say);
`resume` adds no context; saved state feeds the next session's card.
A failed Read, Grep, Glob, LS or NotebookEdit naming a missing path gets the same "did you mean"
path hint as OMP; listing candidates is best-effort within 150 ms and skipped for a drive, home or
temp root (one OMP tool result had been held 24.7 s by an unbounded walk). The Git Bash shim
starts `node` directly (`command -v`), and `brain.mjs` hands a Node older than 22.18 to Bun.
Hooks with `agent_id`, SubagentStart and SubagentStop never write working state; child tool
logs are separate from their parent’s. `agent_type` alone is also used by main sessions
started with `--agent` and does not imply a child. Tool hooks do not spawn git.
SubagentStart returns the child card as `hookSpecificOutput.additionalContext` and logs a
`sub: true` card row under the child’s session identity; empty cards return `{}`.
Card latency for both startup and child hooks measures in-process input/loading/rendering work,
not Node or module startup; measure process wall time separately.
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

**DeepSeek Harness.** `dsh/` is a Host plugin (bundle `@local/dsh-second-brain`): the start
card, the child card, `brain_recall`/`brain_note`/`brain_state`, the tested known fix, capture
of every tool outcome (`brain event`), owner-rule capture (`brain prompt`), a scan at compaction
and session end (`brain scan`), and the context hand-off hint (`brain rollover`), all in one
Host. It keeps one warm `brain serve` process per Host instead of one CLI process per call:
a warm recall or fix is ~30 ms against ~400 ms fresh, so every failed tool result and every
tool call stays cheap. A checkout older than the plugin is detected once and falls back to one
process per call with the older feature set. Install, configuration and limits: `dsh/README.md`.

**MCP clients.** Launch `brain mcp` as a stdio server to expose the same three tool definitions
as OMP: `brain_recall`, `brain_note` and `brain_state`. Launch in the workspace directory
(or set `BRAIN_PROJECT`) and set `SECOND_BRAIN_HOME`. MCP has no subagent identity: the host
must withhold `brain_state` from child agents to protect the parent’s working state.

**Reversible rendering (layer 4; on by default in OMP except on Anthropic models, opt-in elsewhere).** Old, large tool
output is swapped for a 60–90-token stub on its way to the model; the history the harness stores
is never changed. The stub names a recall id (`t-` and 10 hex): `brain_recall t-…` or
`brain recall t-…` returns the original verbatim; stubs of read-only tools (read, grep, glob,
find, ls) add that re-running the tool shows it too. Originals stay in `state/elided/` for 14
days after being saved or reused for a new elision (raw tool output, with the same exposure as
the harness’s own transcripts).
OMP and the proxy persist each original before committing its stub; a failed write keeps that
output full. Equal-length replacements are recounted by content, not by character count.
Budgets count tokens with `outputTokens` (about 5% from o200k; chars/4 runs 33–39% low on logs
and JSON). The newest 20 000 tokens of tool output stay verbatim; older output is elided in
epochs of 50 000 tokens, so the request prefix, and with it the provider’s prompt cache, stays
byte-identical between epochs; output under 500 tokens is never touched. `brain stats` counts
epochs, elided outputs, tokens saved per later request and restores; the same output counts as
fresh once per conversation, even if a shrunken history clears the sticky set, while a second copy
under a new call id counts again.
- OMP: on by default, except for models on the Anthropic Messages API; `BRAIN_RENDER=off` turns it
  off, `BRAIN_RENDER=on` forces it. Anthropic bills cache writes at 1.25x input (2x for 1-hour
  caching) and reads at 0.05x (Opus, Sonnet 5.5) or 0.025x (Fable 5.1), so an epoch rarely pays
  back: a replay of 14 days of OMP sessions put it at −3.1% input cost on Opus and +3.0% on
  Sonnet, a third of sessions dearer, against −16% and −19% on OpenAI models. OMP floors its
  compaction trigger by the stored history, so here layer 4 saves request tokens and cost, not
  compactions.
- Claude Code and Codex: run `brain proxy` (127.0.0.1:47830, `--port N`; needs
  `SECOND_BRAIN_HOME`). It fails open per request (any error forwards the original bytes), but a
  harness pointed at a proxy that is not running cannot connect: start the proxy first, or drop
  the setting below. Started on a pipe, it stops when its host closes stdin; otherwise on Ctrl+C
  or SIGTERM.
  - Claude Code: `ANTHROPIC_BASE_URL=http://127.0.0.1:47830/anthropic` and
    `ENABLE_TOOL_SEARCH=true`. Behind a base URL Claude Code turns tool search off: a probe
    request took 38 221 input tokens without the variable and 23 118 with it.
  - Codex with a ChatGPT login, in `~/.codex/config.toml` (API-key users point `base_url` at
    `http://127.0.0.1:47830/openai/v1`):

    ```toml
    model_provider = "brain"
    [model_providers.brain]
    name = "Brain proxy"
    base_url = "http://127.0.0.1:47830/chatgpt/backend-api/codex"
    wire_api = "responses"
    requires_openai_auth = true
    supports_websockets = false
    ```
- Overhead, measured: counting 1 MB of output takes about 1.6 ms; the OMP hook adds a median
  0.06 ms per request. Proxy rewriting synchronously persists each new original before forwarding;
  its previous overhead timings excluded that work and have been removed. Hook processes never load
  `node:http`; the proxy fetches it when it starts. Importing it would add about 16 ms to every
  Claude Code hook.
- Measured in E6 (18 reads of 19 000-character logs, no compaction): input tokens fell 33% on
  Claude Code through the proxy (1 run; Claude Code's own list-price estimate fell 40%; the
  largest request peaked at 124 k tokens instead of 224 k), 39% on OMP (3 runs; cost −21%) and
  29% on Codex (2 runs against 1 valid baseline), with every probe still answered. Wall time did
  not rise consistently (OMP +6% over two uncontended runs, Codex −33%, Claude Code +4%). The
  prompt-cache hit rate fell 3.7–4.9 points, because each epoch rewrites the prefix once, so the
  E6 gate judges cache-weighted input instead (cache reads ×0.1, writes ×2): −20.7% on OMP,
  −12.2% on Codex, +2.6% on Claude Code. Layer 4 is therefore on by default in OMP only; Codex
  misses the 30% input criterion and Claude Code the cache-weighted one (intake doc §6).

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
0.2 bundle for OKF readers: `kind` becomes `type`, currently verified content gets `verified`
(`human:owner` only for the owner; edited bodies/error patterns omit it), and retired notes become `status: deprecated` with replacement links.
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

Changes that read a file and write it back are serialized, not just the final replacement. Moving,
upgrading, retiring, sharing or marking a note tested, tagging a project or registering its docs,
rejecting a proposal and a `brain convert` merge each take a claim file in `state/locks/` (local,
never synced), reload what they are changing once they hold it, and release it when done. Two
processes tagging one project keep both tags, and two moves of one note never leave two copies. A
move or upgrade built from a stale snapshot (the note was moved or retired, or its body changed,
since it was read) fails with an explicit message and writes nothing. Claims cover synchronous
read-modify-writes of milliseconds. A dead owner's claim is reclaimed immediately, as is a leftover
claim from the current process that it no longer holds. Every claim and reclaim gate expires after
15 seconds, even with a live pid, so pid reuse or failed cleanup cannot permanently wedge writes.
A writer that cannot get a fresh claim within about 3 seconds fails with a `ClaimError` naming the
holder pid and full claim path; hooks skip the contended write after that bounded wait. Retry, or,
if no Brain command is running, delete the claim file named in the error.

`brain check` reports any file it cannot read.

