---
id: n-bb69d5b9fc
kind: gotcha
at: 2026-11-07T03:21:19Z
source: agent
errors:
  - "FAIL in-app title matches : title persistence: rtc: pinned 12:00:00"
tested: "true"
tested_by: agent
tested_at: 2026-11-07T03:21:19Z
tested_sha: 3d1a4c2ec4e9
---

DWC port suite and agent CLI runs share dwc-rs/target/release/port_save.bin + config.txt, so running the gate suite while subagents run --play produces phantom FAILs (e.g. 'in-app title matches : title persistence'). Isolate a probe: copy target/release/dwc-rs.exe into build/probe/ with its own config.txt (save path is next to the exe) and run scenarios there.
