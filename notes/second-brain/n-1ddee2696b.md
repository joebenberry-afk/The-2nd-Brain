---
id: n-1ddee2696b
kind: decision
at: 2026-09-29T09:31:42Z
source: agent
---

Claude Code is wired globally (2026-09-29): ~/.claude/settings.json runs brain hook claude-code on SessionStart/PostToolUse/PostToolUseFailure/PreCompact/SessionEnd, skipped when $CLAUDE_PROJECT_DIR/brain/bin/brain exists so Brain checkouts (whose project hooks also serve the cloud) don't fire twice; global CLAUDE.md carries the agents-md block. Old V2 hooks backed up in settings.json.bak-v2hooks.
