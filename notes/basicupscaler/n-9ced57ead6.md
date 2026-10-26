---
id: n-9ced57ead6
kind: note
at: 2026-10-23T09:44:40Z
source: agent
evidence:
  - runs/architecture/2026-10-23-p1/settings/claude-settings-changes.txt
evidence_sha:
  - runs/architecture/2026-10-23-p1/settings/claude-settings-changes.txt=9894374bef37
---

P1 Task 15 (23 Oct 2026): Claude memory for sessions in FG's new path (C:/Users/assas/Documents/BasicUpscaler/BasicUpscaler) is ~/.claude/projects/C--Users-assas-Documents-BasicUpscaler-BasicUpscaler/memory/, copied from the collection-root folder plus Frame-Gen's feedback-haiku-agents.md; the collection-root copies remain, so edit both. The basicupscaler git remote is removed (its 85 refs live on as refs/archive/bu/heads/*). The auto-mode classifier denies Edit of ~/.claude/settings.json autoMode.environment as [Self-Modification]; lines 307 and 326 wait for the owner (text in runs/architecture/2026-10-23-p1/settings/claude-settings-changes.txt). Codex keeps projects in a third store, ~/.codex/state_5.sqlite (projects, project_roots, project_idempotency_keys), beside config.toml and .codex-global-state.json.
