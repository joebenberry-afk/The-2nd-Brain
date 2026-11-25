---
id: n-d0ae544aa4
kind: procedure
at: 2026-11-25T21:00:16Z
source: agent
evidence:
  - "%LOCALAPPDATA%/aria2-rpc/aria2.conf"
replaces: n-12c452f5d1
---

Zen/Helium multi-connection downloads: aria2 1.37.0 RPC daemon on 127.0.0.1:6800 (listening, seen via netstat today), config %LOCALAPPDATA%\aria2-rpc\aria2.conf (16 conns in file; aria2-supervisor.ps1 passes 64 on the command line when running the patched %USERPROFILE%\.local\bin\aria2c.exe). Started at logon by scheduled task 'aria2 download engine' (schtasks /query) -> conhost --headless powershell aria2-supervisor.ps1, which restarts aria2c; no Startup-folder lnk exists. Same daemon serves Zen (zen\) and Helium (helium\). Browser add-on 'Aria2 Integration' (slug aria2-extension): in Firefox it cancels the browser download BEFORE calling aria2, so a down daemon loses the download [add-on behaviour not re-verified today]. Plain aria2c CLI reads %USERPROFILE%\.aria2\aria2.conf (64 conns, patched build; see %LOCALAPPDATA%\aria2-rpc\PATCHED-ARIA2-64-CONNECTIONS.md); it does not read the daemon conf, so it never binds 6800. Measured 2026-10-15 (not re-verified): 1 conn 0.2 Mbps vs 16 conns 2.4 Mbps.
