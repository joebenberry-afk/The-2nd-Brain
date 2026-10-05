---
id: n-e33f5ee17a
kind: note
at: 2026-10-01T02:20:28Z
source: agent
---

Windows: IsHungAppWindow reports a hang only after 5 s; a synchronous cross-thread SetWindowPos to a window whose thread just froze blocks the caller. Probe with SendMessageTimeoutW(WM_NULL, SMTO_ABORTIFHUNG, timeout) or post with SWP_ASYNCWINDOWPOS (BU L1, fixes-1 a7e3f46).
