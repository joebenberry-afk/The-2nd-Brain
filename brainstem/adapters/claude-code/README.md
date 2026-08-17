# Second Brain P3a Claude Code hooks

Native Claude Code lifecycle wiring for SessionStart, PreCompact, and Stop
only (P3a scope). Every call runs `brainctl autoinject claude-code-hook`:
one JSON object on stdin, one on stdout, fail-open (`{}`, exit 0) on any
error -- the hook never breaks a Claude Code session.

## What happens on each event

| Event       | Brain behavior |
|-------------|----------------|
| SessionStart | Registers host=`claude-code` in the existing telemetry-based session lifecycle (`autoinject.BrainLifecycle.start_session`). No memory retrieval, no context injection -- always returns `{}`. |
| PreCompact   | Extracts a bounded resume packet (goal from the transcript's last user message, `custom_instructions` if the user ran `/compact <text>`, git branch/commit/changed-files) and writes it as one `compaction_started` ledger event, then runs `ledger.checkpoint_ledger` (the existing pre-compaction durability barrier). Deduplicated by content hash. Never blocks compaction. |
| Stop         | Fires once per assistant turn (not once per session -- `SessionEnd` is Claude Code's real session-close event and is out of scope here). Records a lightweight `turn_end` telemetry record every time. Writes a `candidate` memory only when the assistant's last message contains the opt-in `<!--second-brain-candidate ...-->` marker (see `rules/second-brain-core.md`) with non-empty evidence. |

## Known limits (honest)

- A hook is a shell script with no model access. It cannot semantically judge "is this a validated decision" or "is this a blocker" from free text. The PreCompact resume packet therefore leaves `decisions`/`blockers`/`open_questions`/`evidence_refs`/`tests_run` as empty -- populating them with guessed text would violate the Brain's no-fabrication rule. The only semantically rich field (`goal`) comes from a literal, bounded read of the transcript's last user message plus, when present, the user's own `/compact` instructions -- not from summarization.
- `Stop` firing once per turn (not once per session) means "session completion" in the literal P3a spec sense doesn't have a clean hook in this three-event slice; `SessionEnd` would be the correct hook for that and is explicitly deferred.
- No circuit breaker: repeated Brain failures do not back off; each hook call is an independent single-shot try/except that fails open, matching every other adapter in this repo.

## Install / uninstall / rollback

```powershell
.\scripts\install-claude-code-hooks.ps1     # merge into ~/.claude/settings.json
.\scripts\uninstall-claude-code-hooks.ps1   # remove the hooks block
.\scripts\uninstall-claude-code-hooks.ps1 -RestoreBackup   # exact prior state
```

Test safely without touching the real config:

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:TEMP\claude-test"; .\scripts\install-claude-code-hooks.ps1
```
