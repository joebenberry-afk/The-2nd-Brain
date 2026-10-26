---
id: n-f4b00bbe7b
kind: gotcha
at: 2026-10-24T20:40:57Z
source: agent
errors:
  - "M1 instrument exited early: name=game_presentmon, code=6 / failed to start trace session: access denied / ETW 0xC0000022"
tested: "true"
tested_by: agent
tested_at: 2026-10-24T20:40:57Z
tested_sha: 9e1a43f0bc73
---

PresentMon exit 6 'access denied' (ETW 0xC0000022) in M1 sessions = exe under the Low-IL-labelled BasicUpscaler folder runs at Low integrity.
Fix (owner 24 Oct, FG-467): icacls tools\presentmon\PresentMon-2.6.0-x64.exe /setintegritylevel M (unelevated; same path+sha so freezes stay valid). Folder label untouched. Any NEW exe the M1 path runs from inside the repo needs the same, or must live outside (C:/BU-wt, D:). Check: icacls <exe> | findstr Mandatory.
