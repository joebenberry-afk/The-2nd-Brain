---
id: n-ead13ac56d
kind: gotcha
at: 2026-10-23T10:13:53Z
source: agent
tags:
  - concurrency
  - claude-code
---

The concurrent-session quiet check (transcript mtimes under ~/.claude/projects/*BasicUpscaler* and ~/.codex/sessions) is tripped by automatic sdk-py sessions titled 'Review this change for security vulnerabilities' that run after commits (cwd C:/BU-wt/module-architecture). Read the session's first user line before treating it as concurrent work.
