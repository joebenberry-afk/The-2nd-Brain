# Live Rollout Baseline — Prime extension + restart mechanics
Timestamp (UTC ISO): 2026-08-15T10:40:41.161452+00:00
Branch: brain/optimization-sol-orchestrator (campaign commits 1f2c843 … a8c6acb, 2026-08-15)
Collected by: worker-b (read-only Phase 1; the ONLY mutation is this report file, intentionally UNCOMMITTED — the driver decides).
## 1. Live extension directory vs repo build
Installed dir: `~/.prime/agent/extensions/second-brain/` (files + mtimes UTC + SHA-256):
| file | mtime (UTC) | sha256 |
|---|---|---|
| config.ts | 2026-08-14T04:47:35.390601+00:00 | 833a42d84c776d7fc5895d830fe9c6d6009eaff791e8aa0976d54764bdb2861e |
| index.ts | 2026-08-14T04:58:32.695997+00:00 | b0108ac90a9621c4b370fa78fc8b1e164c06c6c6793ac8a0be20bc13e289716a |
| sensors.ts | 2026-08-14T04:52:53.746401+00:00 | ee2b707ab44e9be3b67febff037b3b1c494009128740a6759dc6f2b092ba067a |
| storage.ts | 2026-08-14T04:58:25.848409+00:00 | 2005be8b0b3e1cd1e80a432ef0242fff4b513973a528208ab07ccebb54dae1e8 |

Repo build dir: `brainstem/prime-extension/src/` (committed state):
| file | mtime (UTC) | sha256 |
|---|---|---|
| config.ts | 2026-08-15T09:28:29.710044+00:00 | 3ceb6dc5850f08b0c5c3178b42427adfacaef64ed7e4e666711501e271ccd64e |
| index.ts | 2026-08-15T10:09:33.646641+00:00 | 4405af2ea6ac66d04ee5f57c43d9a212654145dbc11b41f81826bf7e1064973e |
| orchestrator-guard.ts | 2026-08-15T08:24:16.171704+00:00 | c2950b86422132261cb8257270379cd79060eafdba4bf760b312d703d95b48fe |
| recall-gate.ts | 2026-08-15T10:13:32.746933+00:00 | 4b8253aea584f279febcc905ecedc63943cb1792af879ac081fa2605389fa77f |
| rtd.ts | 2026-08-15T09:28:36.527441+00:00 | ac7820ee67a08ecc3e076f79061d6f3b11649531f1380fc3eb8dafb55b8ba49c |
| sensors.ts | 2026-08-15T01:12:03.677134+00:00 | e70f288ed36dee48116eede1123e4c27a4e12be2c64b2b1898e44db678a13663 |
| storage.ts | 2026-08-15T01:08:28.895668+00:00 | 3dad5234d3b7fe4495a2534531dda213ff8c5d3d376ee506ec38d0e71e8ee4e7 |

**Diff conclusion:** the installed copy predates the campaign. Installed mtimes are
2026-08-14T04:47–04:58Z (pre-campaign; the installed copy predates even the
telemetry cluster 1f2c843, which added `rtd.ts`). MISSING from installed:
`orchestrator-guard.ts, recall-gate.ts, rtd.ts`. No stale/extra files in the installed dir. All hashes
differ from repo (installed = older sources). No version/commit metadata exists
in either copy (plain TS mirror).
## 2. settings.json + installer surface

- `~/.prime/agent/settings.json` structure (KEY NAMES ONLY — values redacted,
  no credentials printed): `telemetry.noticeShown` (bool),
  `hideThinkingBlock` (bool), `enabledModels` (list[str]),
  `defaultThinkingLevel` (str), `defaultProvider` (str), `defaultModel` (str),
  `recentModels` (list[str]).
- Installer surface (`scripts/install-prime-extension.ps1`): touches ONLY
  `~/.prime/agent/extensions/second-brain/**` — pre-install backup of the
  existing target (lines 37-39) and of settings.json into `backups/<stamp>-prime-extension-pre-install/` (lines 40-43), then removes the target and copies `src/*.ts` + `types/*.d.ts` (lines 48-54). It NEVER edits settings.json (header line 3: "Never edits settings.json"). No other user config is overwritten.

## 3. Restart mechanics (facts for the deployment driver)

### a. Current process topology (tasklist + Win32_Process command lines, 2026-08-15 ~10:2x UTC)

- PID 26652 — MAIN daemon/supervisor: `node cli.ts --mode daemon --daemon-socket \\.\pipe\prime-agent-daemon` (log component `coding-agent.daemon-supervisor`; supervisor id f2d0bd67-… listening on that pipe per `~/.prime/agent/logs/agent.jsonl` @ 2026-08-15T08:26:44Z).
- PID 26952 — SESSION WORKER daemon for the current session tree: `--mode daemon --daemon-socket \\.\pipe\prime-agent-worker-2245fa1c0e38-14a413cfbaf5` (this session's host; log @ 08:13:29Z).
- PID 26244, 29156 — node `cli.ts` (client-side processes, no --mode daemon).
- PID 31668 — transient `cli.ts --version`.
- 6 × python.exe — `ipykernel_launcher` kernels (3 kernels × 2 pythons each: `kernel-venv/Scripts/python.exe` + uv cpython-3.11), one per live RLM session (connection files ZeF9G3, NU2Wmk, vCy8YM).
- agent.jsonl last-20-lines observations: idle-eviction sweep timeouts; a supervisor replacement cycle at 08:26 (EPERM launch failure → new supervisor f2d0bd67 up at 08:26:44); graceful shutdown sequence at 09:56:45–46 ("shutdown command received over socket; 1 active session(s) will be closed" → "shutting down (exit 0)" → worker evicted, idleMinutes=90).

### b. When do sessions load extensions? (per-session from disk — NO daemon restart needed for new sessions)

- Each session's services construct a fresh `DefaultResourceLoader` and call `reload()`: `core/agent-session-services.ts:207-215` (`new DefaultResourceLoader({...})`; `await resourceLoader.reload()`).
- `reload()` → `loadExtensions(extensionPaths, cwd, eventBus)` (`core/resource-loader.ts:413`) → `discoverAndLoadExtensions` (`core/extensions/loader.ts:559-604`) → `discoverExtensionsInDir` (`loader.ts:522-554`) reads the extension directories from disk, including global `agentDir/extensions` (`loader.ts:582-584`).
- Subagent runtimes are new session runtimes too (`modes/daemon/daemon-mode.ts createRlmSubagentRuntime → createAgentSessionRuntime`), so they also load extensions at creation.
- **Conclusion: any NEW session (main or subagent) picks up newly installed extension files without a daemon restart.**

### c. Extension reload mechanism for EXISTING sessions

- Slash command: `core/slash-commands.ts:189` — name "reload", description "Reload keybindings, extensions, skills, prompts, and themes".
- Implementation: `core/agent-session.ts:8865-8895` `async reload()` — re-reads settings, `await this._resourceLoader.reload()` (disk re-discovery incl. extensions), `extendResourcesFromExtensions("reload")`, session_start reason "reload".
- Programmatic: `ExtensionContext.reload` (`core/extensions/runner.ts:663-665` → `reloadHandler`; `types.ts:355-356` "Reload extensions, skills, prompts, and themes").
- **Conclusion: an existing session can activate newly installed extension files via `/reload` (after the current turn), without a daemon restart.**

### d. Daemon kill semantics + auto-respawn

- Graceful shutdown: `modes/daemon/daemon-supervisor.ts` `shutdown()` (~5088-5171) requests each worker to shut down (`requestWorker({type:"worker_archive_and_shutdown"})` at 4720-4723; fallback SIGTERM/SIGKILL with 5s grace at 4857-4875) and then `process.exit(exitCode)` (5096/5171). Log evidence 09:56:45: "shutdown command received over socket; 1 active session(s) will be closed" → "shutting down (exit 0)".
- Auto-respawn: `modes/daemon/daemon-mode.ts:654-668` `checkSupervisorAvailability` — when the supervisor socket is unreachable and no authenticated supervisor connection exists, `launchReplacementSupervisor` (754-841) spawns a detached `cli.ts --mode daemon --daemon-socket <pipe>` (809-825) and probes connectivity up to 10 s (827-834). Log evidence: 08:26:20 launch failure (EPERM) then 08:26:44 new supervisor up; workers survive via descriptor recovery ("Recovered worker 56e5e65937b0 without replaying uncertain operations", 08:26:41; descriptors under `~/.prime/agent/daemon-workers/<id>/*.json`).
- Clients also relaunch a cold daemon on attach (`cli-main.ts:28`; `cli/daemon-launch.ts` probe).
- **Conclusion: killing the daemon supervisor closes (gracefully) or orphans/re-adopts (hard kill) ALL its session workers — including the orchestrator session. A replacement supervisor is relaunched automatically when the socket is gone, and surviving workers are re-adopted; but a graceful shutdown is the safe path for a rollout restart. Killing a SESSION worker daemon kills only that session tree.**

## 4. Redaction note

No credential/token/API-key values were read or printed. settings.json was
inspected for KEY NAMES only. Process inventories show command lines only
(no secrets). This report contains no secrets.


---

# Post-deployment re-census (2026-08-15T~12:00Z)

Appended by worker-b, Phase 8 (read-only census; this section is the only mutation).

Deployment: 2026-08-15T06:45:44Z (8 files, SHA-identical to repo).
Pre-deployment baseline numbers (above + `outputs/reports/optimization-phase0-baseline.md`):
files 360, anon 304, files<=2 records 310, records 13,032, non-anon files 56.

## 1. Filesystem census (telemetry/agent-performance)

| metric | pre-deploy | post-deploy | delta |
|---|---|---|---|
| total files | 360 | 387 | +27 |
| anon-* files | 304 | 304 | **+0 (KEY CHECK PASS)** |
| files with <=2 records | 310 | 308 | -2 |
| total records | 13,032 | 22,615 | +9,583 |
| non-anon (session) files | 56 | 83 | +27 |

- Anon histogram: 304 files × exactly 1 record (unchanged). Newest anon mtime:
  2026-08-14T20:05:49Z — **no anon-* file created since deployment**; all new
  sessions use UUID stems.
- Files <=2 records now: 304 anon (1 record) + 4 non-anon (2 records:
  019ffef4-…, 01a0011f-…, 01a00129-…, 01a0014e-… — all pre-deploy stems).
- Session files created after 06:45:44Z: **20**, stems:
  01a002df, 01a003db, 01a0045c, 01a0045e, 01a0047b, 01a0047e-2d9b,
  01a0047e-3473, 01a00510, 01a00511, 01a00512, 01a00513, 01a00514, 01a0051c,
  01a00520, 01a0052a, 01a0052b, 01a00535, 01a0053b-0398, 01a0053b-84a5,
  01a0053e. The headless deepseek-v4-flash test sessions are 01a00510/11/12/13
  (7-12 records each), 01a00514 (146), 01a0051c (106), 01a00520 (171),
  01a0052a (7), 01a0052b (117), 01a00535 (164), 01a0053b ×2 (12, 76),
  01a0053e (7); 01a0047b/01a0047e are the campaign's own orchestrator/worker
  sessions.

## 2. Kind census (ALL files)

| kind | count |
|---|---|
| turn_start | 4,640 |
| context | 4,640 |
| turn_end | 4,622 |
| tool_call | 4,008 |
| tool_result | 4,003 |
| agent_end | 295 |
| before_agent_start | 229 |
| session_start | 99 |
| session_shutdown | 76 |
| session_before_compact | 7 |
| session_compact | 4 |
| **orchestrator_policy_violation** | **0 (expected: no Sol model+blocked-tool combo ran)** |
| **rtd_shadow** | **0 (expected: live sessions expose only ipython; no bash)** |
| **extension_error** | **0 (expected)** |

session_start model distribution (99): deepseek/deepseek-v4-flash 45,
deepseek/deepseek-v4-pro 20, openai-codex/gpt-5.6-sol 13,
openai-codex/gpt-5.6-luna 11, lemonade/Qwen3.5-9B-GGUF-Q6_K 6,
anthropic/claude-sonnet-5 3, openai-codex/gpt-5.6-terra 1.

## 3. Schema health

- Sampled 5 records from 3 post-deploy files (01a00510, 01a00511, 01a00512):
  all parse as valid JSON, `v=2`, bounded schema fields only (session_start:
  cwd/model/reason; before_agent_start: prompt_chars; turn_start: turn;
  context: messages; tool_call: id/input_bytes/tool; turn_end:
  context_usage/tool_results) — no free-text fields beyond schema.
- Malformed lines: **1 total**, in `01a003e2-c6e4-71a8-8a36-53d88ffc786a.jsonl`
  line 34 (a NUL-byte line; file mtime 2026-08-15T05:29:37Z) —
  **pre-deployment artifact**, not produced by the deployed extension.
  Zero malformed lines in any post-deployment file.

## 4. Conclusion

Deployed extension is behaviorally clean in production: zero new anon files,
zero extension errors, zero RTD shadows, zero guard violations, schema-clean
records, and every new session wrote a UUID-stem telemetry file. The only
anomaly (one NUL line) predates deployment.
