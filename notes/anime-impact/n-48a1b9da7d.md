---
id: n-48a1b9da7d
kind: gotcha
at: 2026-11-09T21:29:23Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-09T21:29:23Z
tested_sha: 399ecef7e247
---

OMP orchestration gotchas: `task` per-call `model` is disabled (choose the agent type instead); the eval kernel `write()` helper rejects agent:// paths ("Protocol paths are not supported by this helper") so message agents with the write tool; a user interjection can kill the eval kernel and kernel-dispatched agents, so dispatch long agents via `task`; a script error in a headless Godot `_initialize` hangs unless --quit-after is set; hero anim GLBs are .gdignore'd and load only through GLTFDocument.
