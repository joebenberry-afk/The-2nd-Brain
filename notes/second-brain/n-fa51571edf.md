---
id: n-fa51571edf
kind: decision
at: 2026-10-21T08:47:40Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-21T08:47:40Z
tested_sha: a1b69ea8bfab
---

brain-view cost pass measured 2026-10-21: fresh desktop session first request 42.1k tokens (18.2k cache write + 23.9k cache read), down from 51.1k (-18%). Headless is 29.3k, so desktop adds ~12.8k (desktop system prompt, ccd tools, SessionStart hooks: superpowers, ponytail, caveman).
