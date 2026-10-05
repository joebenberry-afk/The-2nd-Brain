---
id: n-cb7dd26f8c
kind: note
at: 2026-10-02T15:49:49Z
source: agent
---

Slint 1.18.1 focus ring (BU Task 8, 4832eb4): focus() on the already-focused item sends no focus event, so a by-pointer flag around focus() leaves a Tab ring after a click; set kb-focus=false right after focus() in the click handler (tests/pressable.rs). A bare Pressable element fails to compile (lower_accessibility: accessible-enabled needs accessible-role), use inherits + role. Built-in Tooltip follows Fluent Palette.color-scheme, not Tone.
