---
id: n-ff6fb1254c
kind: gotcha
at: 2026-10-18T00:52:59Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-18T00:52:59Z
tested_sha: 52c8bb43014b
---

aria2 engine outage after reboot (2026-10-17): the Startup-folder shortcut "aria2 download engine.lnk" was switched off in Startup apps at 04:56:46 (StartupApproved\StartupFolder byte0=03), along with GoogleUpdater and Gemini, just before a restart. The user habitually disables startup apps. The Aria2 Integration add-on cancels and erases Zen's download BEFORE the RPC call, so with aria2 down every download was lost.
Fix: scheduled task "aria2 download engine" (sign-in + every 5 min, IgnoreNew, priority 5; install-engine-task.ps1, -Uninstall), which is not listed in Startup apps. zen-aria2.js turns off the add-on's captureDownloads via ExtensionStorageSync.set({id}, {options}) at startup. Its own handoff (aria2 accepts the download paused, then Zen's copy is cancelled) is the only capture path. When RPC is unreachable it runs `schtasks /run /tn "aria2 download engine"` through nsIProcess.
Test gotcha: a headless Zen run (`zen.exe --headless -profile X URL`) does not forward the URL to an already-running headless instance; it starts a second instance that hangs. To delay a download, serve a local page that sets location.href after a delay; a data: URL with meta refresh did not start the download.
