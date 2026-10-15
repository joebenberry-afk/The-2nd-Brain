---
id: n-2dbae1df44
kind: procedure
at: 2026-10-15T06:41:14Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-15T06:41:14Z
tested_sha: 0b8dce732a03
---

Patched aria2 (2026-10-15): %USERPROFILE%\.local\bin\aria2c.exe = official aria2-1.37.0-win-64bit-build1 aria2c.exe (zip sha256 67d01530..., matches winget manifest) with ONE byte changed at file offset 0xdfa1f (imm of `mov qword [rsp+0x28],0x10`, max of --max-connection-per-server NumberOptionHandler, next to `mov dword [rsp+0x30],0x78`) 0x10 -> 0x40 => accepts 1-64. Patched sha256 681a8a9b16410ca2... .local\bin precedes WinGet Links on PATH. Probe: `aria2c --no-conf=true --max-connection-per-server=64 --version` exits 0 only on patched (stock exits 28). Daemon conf keeps 16; aria2-supervisor.ps1 probes and passes --max-connection-per-server=64 --split=64 on the command line (cmdline overrides conf; conf values are still validated, so conf must stay <=16). ~/.aria2/aria2.conf = 64; fast.ts DEFAULTS.connections=64 (clamps to 16 for stock builds); hup uses DEFAULTS. Measured at ~02:30 via temp RPC instance: GitHub release asset 16/32/64 conn = 4.6/7.6/15.6 Mbps; VS Code CDN 16/32/64 = 22.6/35.6/45.1 Mbps. Gotcha: Get-CimInstance Win32_Process filter by CommandLine matches the querying powershell itself; killing its ParentProcessId killed the eval kernel.
