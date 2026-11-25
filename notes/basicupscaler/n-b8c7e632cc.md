---
id: n-b8c7e632cc
kind: gotcha
at: 2026-11-11T14:09:05Z
source: agent
errors:
  - "Error: freeze:provenance_not_a_sha256:headers_commit"
tested: "true"
tested_by: agent
tested_at: 2026-11-11T14:09:05Z
tested_sha: c3fe87042ba0
checked: holds
checked_at: 2026-11-25T17:59:56Z
checked_why: The inject command and flags, the injector-first then engine-record sequence in the kit (engine_record and cmd_engine_record contain no injection code), once-per-process attach, the shell-window dry check, the two Rust-versus-Python freeze drift fixes and the kit copy in the receipt all match the fi
checked_sha: c3fe87042ba0
---

B2 engine probe: `bu engine-record` does not load the hook; load it first with `bu_hook_inject.exe --pid N --allow Cyberpunk2077.exe --hwnd H --engine-recorder --epoch <nonzero>`.
The hook attaches once per game launch, so check everything offline before injecting: run `bu engine-record` against the shell window (GetShellWindow) to prove the Rust reader accepts the freeze (expected error: freeze:executable_sha256 only), and take a screen grab to confirm the game is in the world, not the main menu ("in-game" from the owner may still mean the menu). Rust and Python freeze validators had drifted (headers_commit length, static receipt file vs directory); Python check-freeze passing does not prove the Rust reader loads the freeze. Kit: C:/BU-scratch/b2-probe-kit/run_probe.py (copy in the receipt's kit/ folder on velocity/b2-engine-recorder).
