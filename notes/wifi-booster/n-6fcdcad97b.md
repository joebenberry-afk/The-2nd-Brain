---
id: n-6fcdcad97b
kind: gotcha
at: 2026-10-15T04:43:09Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-15T04:43:09Z
tested_sha: 7e8d44217127
---

Aria2 Integration add-on (baptistecdr 4.15.6, MV3 event page) misses the FIRST download after Zen starts: alarms don't persist across browser sessions, so the background is asleep; the downloads.onCreated wake runs handleDownload while extensionOptions is still the default (captureDownloads=false) because ExtensionOptions.fromStorage() hasn't resolved -> Zen downloads it itself on 1 connection. Evidence 2026-10-15: Zen started 00:17:30, download 00:17:44, storage-sync-v2.sqlite-wal mtime 00:17:44, aria2 received nothing. Once awake, its 5 s alarm keeps it awake (MDN: 30 s minimum is Chrome-only). Zen "Retry" never reaches the add-on (no onCreated). GitHub release-asset links expire (se= param). Workaround: cancel and re-click. Same Obsidian 1.14.4 file (341,331,008 B) via aria2 RPC: 14.6 min, 3.1 Mbps avg, 16 conns, sha256 matched GitHub's digest; Zen got 0.24 Mbps.
