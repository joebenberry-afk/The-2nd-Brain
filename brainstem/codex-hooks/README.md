# Second Brain P0 Codex hooks — SHADOW (Phase 0C part 2)

Repo-local, reversible Codex hook wiring for the P0 AutoInject pipeline
(plan §6.10, Phase 0C). **SHADOW only**: decisions are computed and recorded;
Codex sessions are never mutated (`{}` is returned — no `additionalContext`).

## What happens on each event

| Codex event        | Brain behavior (SHADOW)                                   |
|--------------------|-----------------------------------------------------------|
| SessionStart       | pipeline call with no task text -> no-op (nothing to retrieve) |
| UserPromptSubmit   | task AutoInject decision (task text via STDIN, never argv) |
| SubagentStart      | worker-specific AutoInject decision                       |
| Stop / SessionEnd  | same launcher; records decision / finalization events     |

Every call runs `brainctl autoinject codex-shadow`: one JSON object on
stdin, one JSON object on stdout, decision + delivery recorded in the
canonical DB and in `<brain>/telemetry/agent-performance/codex-hooks.jsonl`
(privacy-safe: ids/counts/hashes only, SCHEMA.md rules). Fail-open: any
error/timeout/malformed input yields `NO_INJECTION(BRAIN_UNAVAILABLE)` with
exit 0 — the hook never breaks a Codex session.

## Files

- `hooks.toml` — TOML template of the `[hooks]` event keys merged into
  `~/.codex/config.toml` (or `$env:CODEX_HOME/config.toml`).
- `run.ps1` — launcher: env-clean venv python, stdin -> stdout, exit code
  forwarded, decision JSON logged.
- `scripts/install-codex-hooks.ps1` / `scripts/uninstall-codex-hooks.ps1`
  (repo root) — idempotent merge/unmerge of only the `[hooks]` keys; never
  touches `[hooks.state]`/`[agents]`; prints the diff; keeps a timestamped
  backup; `-RestoreBackup` fully reverses to the pre-install state.

## Install / uninstall

```powershell
.\scripts\install-codex-hooks.ps1            # merge into ~/.codex/config.toml
.\scripts\uninstall-codex-hooks.ps1          # remove block (keeps other tables)
.\scripts\uninstall-codex-hooks.ps1 -RestoreBackup   # exact prior state
```

Test safely without touching the real config:

```powershell
$env:CODEX_HOME = "$env:TEMP\codex-test"; .\scripts\install-codex-hooks.ps1
```

## Verified Codex schema (0.147.0)

Tested against the installed `codex-cli 0.147.0` on this machine:

- There is **no `codex hooks` subcommand** in 0.147.0 (`codex --help` lists
  exec/review/plugin/mcp/app-server/... only).
- Hook configuration is event-keyed: the installed plugin manifests that
  0.147.0 executes (`~/.codex/plugins/cache/claude-plugins-official/*/hooks/
  hooks.json`) declare `hooks.<Event> = [{ matcher?, hooks = [{ type =
  "command", command = "...", async = false }] }]`, and
  `~/.codex/config.toml [hooks.state]` holds their trusted hashes. The
  template above uses exactly this shape.
- Event names observed in the installed manifests: `SessionStart`,
  `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `PreToolUse`,
  `PostToolUse`, `Stop`.

## Known limits (honest)

- We do NOT parse `transcript_path` (unstable JSON) — the hook payload is
  the only event source used.
- We do not claim byte-exact replay of Codex sessions; shadow phase only.
- Hooks run through `powershell -File run.ps1` on Windows; a Brain venv must
  exist at `<brain>/.venv/Scripts/python.exe` (missing venv -> `{}`, exit 0).
