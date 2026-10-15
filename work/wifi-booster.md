---
at: 2026-10-15T05:28:34Z
---

Goal: guarantee Zen downloads go to aria2. Finding: add-on fails to capture even when awake (pre-test 2 MB __down stayed in Zen; WebSocket from bg alive) so cold-start race was not the whole cause. User approved admin install + Zen restart. Plan: Program Files loader cfg -> %LOCALAPPDATA%\aria2-rpc\zen\zen-aria2.js (privileged: wake add-on, log add-on console errors, fallback handoff to aria2 after 2.5 s with pause/finalize/unpause). Test in headless temp-profile Zen first, then main Zen.
