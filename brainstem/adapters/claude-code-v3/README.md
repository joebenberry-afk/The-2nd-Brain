# Second Brain V3 — Claude Code adapter

Two hooks, both answered by `brain hook claude-code` (JSON on stdin, JSON on stdout, fail-open):

| Event | Brain adds | Budget |
|---|---|---|
| `SessionStart` (startup, resume, clear, compact, fork) | the project brief: current decisions, active work, gotchas, locators, tested facts | ≤ 600 tokens; nothing when the project has no current records |
| `PostToolUseFailure` | one tested correction whose error pattern matches the failure | ≤ 80 tokens; nothing otherwise |

Nothing is added to ordinary prompts, and no hook blocks, vetoes or continues host work. Facts
already in Claude Code's own auto memory (`MEMORY.md` next to the transcript) are left out of the
brief. Everything else is pull: `brain q "<question>"`, `brain show <id>`, `brain add …`.

## Install

1. `pip install -e .` in the Brain checkout (provides `brain`), and set `SECOND_BRAIN_HOME`.
2. Replace `<BRAIN_EXE>` in `hooks.json` with the absolute path of `brain`
   (Windows: `<checkout>\.venv\Scripts\brain.exe`) and merge the `hooks` block into
   `~/.claude/settings.json`.
3. Check: `echo '{"hook_event_name":"SessionStart","source":"startup","cwd":"<repo>"}' | brain hook claude-code`.

Before relying on corrections, confirm on the installed Claude Code version that
`PostToolUseFailure` context reaches the model (issue anthropics/claude-code#55889 reports the
channel dropped for Bash in one version). Telemetry: one line per call in
`$SECOND_BRAIN_HOME/telemetry/kb-hooks.jsonl` (event, delivered tokens, latency).
