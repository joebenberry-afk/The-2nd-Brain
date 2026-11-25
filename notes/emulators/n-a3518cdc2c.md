---
id: n-a3518cdc2c
kind: decision
at: 2026-11-17T05:03:25Z
source: agent
checked: uncheckable
checked_at: 2026-11-25T17:59:36Z
checked_why: It is an owner rule from a conversation on 2026-11-17 and leaves no trace in the emulators repo; the LEAN_RULE kernel string was not inspected.
checked_sha: 13f880ba7b72
replaces: n-0f450a8b25
---

Owner rule (2026-11-17): token-efficiency applies to ALL current and future sub-agents, not only Main
Put this in every brief/message: batch independent tool calls; read only needed line ranges; never re-read; never print whole files/logs; no narration; terse notes; final digest ≤15 lines. Kernel string LEAN_RULE holds the text.
