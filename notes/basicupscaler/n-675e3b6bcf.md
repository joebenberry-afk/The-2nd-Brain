---
id: n-675e3b6bcf
kind: note
at: 2026-10-23T15:38:40Z
source: agent
retired: 2026-10-23T15:38:51Z
---

BU cargo gotcha (23 Oct, cargo 1.97): one build folder shared by two checkouts, via build-dir or CARGO_TARGET_DIR, runs one checkout's compiled crates in the other with no error. Workspace units are keyed by workspace-relative path and freshness is mtime, so an older checkout reuses the newer build (probe: copy b printed m::v = 1). Safe form: build-dir = "{cargo-cache-home}/build/<name>/{workspace-path-hash}", one folder per checkout, no sharing. Receipt runs/architecture/2026-10-23-p2/ in the BU main checkout.
