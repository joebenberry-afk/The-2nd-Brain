# The Second Brain

**Memory for coding agents that survives compaction, follows you across projects, and costs
almost nothing when it has nothing to say.**

One Git-backed Markdown store (`notes/`, `work/`, `projects.json`) shared across **Oh My Pi (OMP)**,
**Claude Code**, **DeepSeek Harness (DSH)**, **Codex**, any **MCP** client, and the `brain` CLI.
Zero runtime dependencies and no `npm install` or build step — Node ≥ 22.18 or Bun runs the TypeScript source directly.

> **Full guide:** [brain/README.md](brain/README.md) · **DSH plugin:** [dsh/README.md](dsh/README.md)

**Contents:** [Requirements](#requirements) · [Supported harnesses](#supported-harnesses) ·
[What an agent feels](#what-an-agent-feels) · [Quick start](#quick-start-on-a-new-machine) ·
[How it works](#how-it-works) · [Everyday commands](#everyday-commands)

---

## Requirements

The Brain has **no npm packages to install**: `brain/package.json` declares no dependencies and
`brain/src` uses Node built-ins only.

| Needed | Version | Used for |
|---|---|---|
| [Node.js](https://nodejs.org/) **or** [Bun](https://bun.sh/) | Node ≥ 22.18 (runs `.ts` natively) · any current Bun | Runs `brain` (`brain/bin/brain.mjs` hands an older Node to Bun) |
| [Git](https://git-scm.com/) | any recent | Cloning, project detection from the remote, `brain sync`, commit-trailer capture |
| PowerShell | Windows PowerShell 5.1 or PowerShell 7 | `scripts/install-v4.ps1` / `uninstall-v4.ps1` (Windows only) |
| Git Bash (Windows) or any POSIX shell | — | The `brain/bin/brain` shim that Claude Code and Codex hooks call |

Optional, only for the integration you use:

| Optional | Enables |
|---|---|
| Oh My Pi (`@oh-my-pi/pi-coding-agent`, verified on 18.3.5) | In-process extension via `install-v4.ps1` |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Lifecycle hooks (`brain hook claude-code`) |
| DeepSeek Harness Host | The `dsh/` plugin bundle |
| [Codex CLI](https://github.com/openai/codex) | `.codex/hooks.json` + `AGENTS.md` block |
| Any MCP client | `brain mcp` stdio server |
| Tora (local reranker) — **not publicly available yet**; without it recall uses lexical BM25 | Precision filter for recall when a Tora session is running; turn off with `BRAIN_TORA=off` |
| TypeSafe Jev + `TYPESAFE_API_KEY` (paid) | Fallback recall judge when Tora gives no verdict; `BRAIN_JUDGE=off` disables judging |

Environment: `SECOND_BRAIN_HOME` points at this checkout (the Windows installer sets it).

---

## Supported Harnesses

Every harness reads and writes the same checkout, shares notes and working state across tools, and logs into the same local telemetry:

| Harness | Adapter | Start Card & Subagent Card | `brain_recall` · `brain_note` · `brain_state` | Tested Known Fix on Error | Capture & Learning | Context Rollover & Layer 4 Elision |
|---|---|---|---|---|---|---|
| **Oh My Pi (OMP)** | In-process extension (`brain/src/omp.ts`) | Main (≤ 320 tok) + child (≤ 200 tok) + post-compaction restore | Native tools (deferred non-blocking write hints; child keeps `brain_recall`) | Appended to failed tool results + missing-path hints | Live tool events, retry outcomes, owner rules, session auto-state | 150k rollover hint + in-process Layer 4 reversible elision |
| **Claude Code** | Lifecycle hooks (`brain hook claude-code`) | `SessionStart` (startup + `compact`) & `SubagentStart` | `brain` CLI + managed `CLAUDE.md` / `AGENTS.md` block (or `brain mcp`) | `PostToolUseFailure` hook + missing-path hints | Async `PostToolUse` & `UserPromptSubmit`, `PreCompact`/`SessionEnd` scan + `~/.claude` memory import | 150k rollover hint (`PostToolUse` / `Stop`) + optional `brain proxy` |
| **DeepSeek Harness (DSH)** | Host plugin bundle (`dsh/` → warm `brain serve`) | Main + subagent card + post-compaction restore (~35 ms warm) | Native tools via warm `brain serve` (~32 ms recall) | Appended on failed tool call (~31 ms warm) | `brain event`, `brain prompt`, `brain scan` at compaction/end | 150k rollover hint (`brain rollover`) |
| **Codex CLI** | `.codex/hooks.json` + `AGENTS.md` block | `SessionStart`, `PreCompact`, `SubagentStart` hooks | `brain` CLI (`brain hook agents-md`) or `brain mcp` | `brain fix "<error>"` | `Stop` & `SessionEnd` hooks + commit-trailer scan | Optional `brain proxy` (`/chatgpt/backend-api/codex` or `/openai/v1`) |
| **MCP Clients** | Stdio server (`brain mcp`) | Via `brain card` or host startup hook | Native MCP tools (`brain_recall`, `brain_note`, `brain_state`) | Via `brain fix` CLI | Note writes & recall telemetry | — |
| **Any Shell / Agent** | `brain` CLI (`brain/bin/brain[.cmd/.ps1]`) | `brain card [--subagent]` | Direct CLI commands | `brain fix "<error>"` | `brain event` · `brain prompt` · `brain scan` · `Brain-*:` git trailers | `brain rollover <tokens>` |

---

## What an agent feels

| Moment | The agent gets | Cost |
|---|---|---|
| **Session start** | a *start card*: where we left off, recurring fixes (`Often hit lately …`), and up to 5 complete notes ranked for the prompt | ≤ 320 tokens (≤ 200 for subagents), 0 when empty |
| **Compaction** | the start card again: compaction summaries keep goal/next, while the card restores notes, recurring fixes, and `See: path#heading` plan anchors | ≤ 320 tokens per compaction |
| **Working** | `brain_recall(query)` · `brain_note(text)` · `brain_state(goal/done/next)` — one argument each; recall a note id to read it in full; retired notes point to their replacement | ≤ 3 lines per recall |
| **A tool fails** | the one known, tested fix for that error (plus a "did you mean" path hint on missing files), appended to the result | ≤ 80 tokens, or 0 |
| **150k context** | a hand-off hint to save `brain_state` (`Goal/Next/See:`) and open a fresh session | ≤ 40 tokens at threshold multiples |
| **New project** | recall global procedure notes for proven setups (stack and why, scaffold steps, gotchas, done-check) | ordinary note recall |
| **Any other prompt** | nothing | 0 |

Measured on this repository (at 127 notes): the start card is ~250 tokens and builds in ~9 ms; lexical recall answers in ~1 ms warm (~26 ms at 2,000 notes, ~67 ms at 5,000) and matches the previous SQLite FTS5 engine on the frozen eval (dev 13/15, held-out 7/8). When a local **Tora** reranker or **TypeSafe Jev** judge is available, recall filters candidates and plan-doc headings for precision and fails open to lexical BM25 on timeout or offline use.

---

## Quick Start on a New Machine

Clone the repository and run the installer for your platform and harnesses.

### 1. Core CLI + Oh My Pi (Windows PowerShell)
```powershell
git clone https://github.com/joebenberry-afk/The-2nd-Brain.git
cd The-2nd-Brain
.\scripts\install-v4.ps1        # puts brain on PATH (.cmd + .ps1 + bash shim), sets SECOND_BRAIN_HOME, installs OMP extension
brain check                     # verifies notes and projects; exit 0
brain card                      # previews the start card for this directory
```

Open a new terminal and restart OMP. The OMP extension (`~/.omp/agent/extensions/second-brain-v4/index.ts`) is a one-line loader pointing at `brain/src/omp.ts` in this checkout, so `git pull` + restarting OMP updates everything (`.\scripts\install-v4.ps1 -Copy` installs a standalone copy if needed; `.\scripts\uninstall-v4.ps1 -Restore` rolls back).

**macOS / Linux / Git Bash:** ensure Node ≥ 22.18 (or Bun) is on `PATH`, set `SECOND_BRAIN_HOME` to the checkout path, and add `$SECOND_BRAIN_HOME/brain/bin` to `PATH`.

### 2. Claude Code

Add the hooks to `~/.claude/settings.json` (global; skips the Brain checkout itself because `.claude/settings.json` in this repo already runs them locally):

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

Then add the managed instruction block to `~/.claude/CLAUDE.md` (or a repo's `CLAUDE.md` / `AGENTS.md`):

```bash
brain hook agents-md
```

### 3. DeepSeek Harness (DSH)

`dsh/` is a DSH Host plugin bundle (`@local/dsh-second-brain`) backed by a single warm `brain serve` process per Host (~30–35 ms per card, recall, or fix). Install it once per DSH profile via the Plugin Manager or `plugin_manager` tool:

```text
plugin_manager(action: "install_bundle", target: "<this checkout>/dsh")
```

Full configuration (`cordis.patch.yml`), tests, and limits: [dsh/README.md](dsh/README.md).

### 4. Codex & Other CLI Agents

1. Paste `brain hook agents-md` into your global or repository `AGENTS.md`.
2. Optional hooks: copy `.codex/hooks.json` for `SessionStart`, `PreCompact`, `SubagentStart`, `Stop`, and `SessionEnd` lifecycle integration.
3. Optional Layer 4 reversible tool-output elision proxy (`brain proxy`, default `127.0.0.1:47830`): see [brain/README.md §3](brain/README.md#3-other-harnesses).

### 5. MCP Clients

Run `brain mcp` as a stdio server with `SECOND_BRAIN_HOME` set to expose `brain_recall`, `brain_note`, and `brain_state` over the Model Context Protocol.

---

## How it works

```text
notes/<project>/*.md     one Markdown file per durable fact (decision, gotcha, procedure, fact, note)
notes/global/*.md        cross-project notes; tagged ones reach only projects with that tag
notes/*/private/         never leaves the machine (git-ignored and refused by brain sync)
work/<project>.md        working state: goal · done · next · watch out · See: path#heading
projects.json            optional: extra paths, git remotes, aliases, tags, plan docs, rollover threshold
state/                   machine-local only (git-ignored): event logs, auto work state, elided outputs, caches
```

Plain files in git are the only truth — no database, no vector index to rebuild, no required daemon.
Projects need no registration: the id comes from `projects.json`, the git remote, or the folder name (linked worktrees and isolated OMP subagents inherit their parent project), and tags come from stack files at the root (`package.json` → `node`, `pyproject.toml` → `python`, `Cargo.toml` → `rust`, …). Secrets are scrubbed before anything touches disk or a judge. `brain sync` pulls, auto-merges working states and dismissals, commits `notes/`, `work/`, `projects.json`, and `rejected.json`, and pushes to git.

### Package architecture (`brain/src/`)

| Module | Responsibility |
|---|---|
| `notes.ts` · `project.ts` · `docs.ts` | Note model, content-bound SHA trust, project/worktree resolution, live `See: path#heading` plan anchors |
| `search.ts` · `judge.ts` · `tora.ts` | In-memory BM25 (SQLite FTS5 port) + optional local Tora reranker / TypeSafe Jev relevance and duplicate judging |
| `card.ts` · `work.ts` · `rollover.ts` | Main & subagent start cards, working state with staleness detection, 150k context hand-off hints |
| `capture.ts` · `outcome.ts` · `paths.ts` | Tool-event log, self-learning tested fixes, failed→fixed & commit-trailer proposals, owner-rule & Claude memory capture, missing-path hints |
| `render.ts` · `proxy.ts` | Layer 4 epoch-based reversible tool-output elision (in-process for OMP, HTTP proxy for Claude Code & Codex) |
| `omp.ts` · `cli.ts` · `serve.ts` · `mcp.ts` | Harness adapters: OMP extension, CLI + Claude Code hooks, warm JSON-lines service for DSH, stdio MCP server |
| `sync.ts` · `tidy.ts` · `telemetry.ts` · `scrub.ts` | Git sync, duplicate/contradiction/unused audit, per-surface stats & schema cost tracking, secret masking |

---

## Everyday commands

```text
brain card                          the start card for this directory's project
brain recall "<question>" [--all]   ≤ 3 one-line answers (or pass a note/stub id to read in full)
brain note "<text>" [--kind gotcha --error "<msg>" --tested] [--replaces <id>] [--global|--private]
brain fix "<error>"                 the one tested known fix for an error, or silence
brain state ["Goal: … Next: …"]     show or replace the working state (supports See: path#heading)
brain project docs add <path>       register a plan doc for live anchors and heading recall
brain move <id> --to <project>      re-home a note (share <id> --tag T makes it global for a tag)
brain review · accept · reject      review captured command fixes, owner rules, Claude memory & unmatched errors
brain tidy [--all]                  audit duplicate, contradictory, or unused notes
brain sync                          pull, merge working states, commit and push notes/work ↔ git remote
brain stats [--days 7]              cards, recall hit rate, fix outcomes, judge usage & schema token cost
```

Full reference: [brain/README.md](brain/README.md).
