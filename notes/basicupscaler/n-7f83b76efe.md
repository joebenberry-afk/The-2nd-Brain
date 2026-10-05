---
id: n-7f83b76efe
kind: note
at: 2026-10-04T18:16:56Z
source: agent
---

Codex computer use (ChatGPT.exe foreground + cua-driver.exe Cua.AgentCursorOverlay covering the monitor) flips Windows' SHQueryUserNotificationState to BUSY for ~1 s per action (seen 14:16:14, 4 Oct). runctl.stop_reason reports it as 'full-screen app', so GPU captures/evals stop when Codex drives the desktop. Debounce proposed to owner, not applied.
