---
id: n-0ec82b28eb
kind: gotcha
at: 2026-11-06T01:18:00Z
source: capture
errors:
  - "1139:26: error[E0422]: cannot find struct, variant or union type `CodeReader` in this scope: not found in this scope"
evidence:
  - events:01a1add4-d41b-7087-a27b-6d4f787d1be9.jsonl#9581-10471
tested: "true"
tested_by: capture
tested_at: 2026-11-06T01:18:00Z
tested_sha: 9cb9ce1cbeb3
---

cargo: CARGO_TARGET_DIR=target-wire-huntmenu cargo build --release  fails (1139:26: error[E0422]: cannot find struct, variant or union); sleep 75; CARGO_TARGET_DIR=target-wire-huntmenu cargo build…

CARGO_TARGET_DIR=target-wire-huntmenu cargo build --release --message-format…

sleep 75; CARGO_TARGET_DIR=target-wire-huntmenu cargo build --release --message-format short 2>&1

Error: src\audio.rs:
  28:60: warning: unnecessary parentheses around closure body
src\battle_scene.rs:
  1139:26: error[E0422]: cannot find struct, variant or union type `CodeReader` in this scope: not found in this scope
  11:24: warning: unused import: `Canvas`
  901:53: error[E0599]: no method named `k
…
score: `_rec`
  4611:33: warning: value assigned to `keys` is never read: this value is reassigned later and neve
