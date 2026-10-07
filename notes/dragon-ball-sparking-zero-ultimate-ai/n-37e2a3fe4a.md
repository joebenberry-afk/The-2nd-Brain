---
id: n-37e2a3fe4a
kind: decision
at: 2026-10-06T10:45:00Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-Dragon-Ball-Sparking-Zero-Ultimate-AI\memory\aes-key-is-available.md
---

The game AES key for `AIplus_AES_KEY` is available. Joseph has supplied it
before and will supply it on request. Do not conclude that retoc/repak
extraction is blocked, and do not tell him a task needs the key as if it were
unobtainable — ask for it, or check whether the artifact is already extracted
under `Temp Mapping/`.

The Bash tool starts a fresh shell per call, so `$env:AIplus_AES_KEY` never
persists between calls. Export it inside the same command that uses it.

`--aes-key` is a **global** retoc flag and must come before the subcommand:
`retoc.exe --aes-key <key> unpack <utoc> <out>`.

**Why:** Joseph pushed back with "I already exposed the AES Key to you, just use
it, don't act like it doesn't exist" after I reported the learning curves and
mod-loader assets as AES-blocked. Both were in fact already extracted under
`Temp Mapping/`, so the blocker was doubly wrong.

**How to apply:** Before saying anything is AES-gated, (1) look for an existing
extraction under `Temp Mapping/`, (2) if genuinely missing, ask for the key in
one line and continue with everything else meanwhile. Related:
[[check-existing-video-evidence-first]], [[telemetry-repo-ownership]].
