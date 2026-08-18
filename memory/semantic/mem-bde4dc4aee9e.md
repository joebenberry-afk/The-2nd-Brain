---
id: mem-bde4dc4aee9e
title: Claude Code Stop hook fires per-turn, not per-session
scope: project
project: second-brain
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-17T22:28:01.848754+00:00
---

Claude Code's Stop hook fires once per assistant turn, not once per session; SessionEnd is Claude Code's real session-close event and is explicitly out of scope for the P3a adapter. Evidence: brainstem/adapters/claude-code/README.md line 19 states this directly. Confirmed by implementation: the Stop branch of _cmd_claude_code_hook (src/second_brain/cli.py, handler at line 2325) emits telemetry kind claude_code_stop_turn (line 2481), which commit 9b7c3f8 deliberately renamed from turn_end specifically to avoid collision with the pre-existing Prime-extension turn_end kind (a different, also per-turn, field shape) -- the rename itself is evidence the per-turn (not per-session) semantics are load-bearing. Do not treat Stop as a session-completion signal.
