# provider-probe — P3 capability probe (installed Prime Agent v0.7.2)

Minimal, removable probe that proves, live, which provider/turn hooks the
**installed** runtime actually fires and what they expose. Hashes/counts/keys
only — never logs prompt text, secrets, or tool output.

Proves:
- `resources_discover` fires on startup/reload (reason logged);
- `context` fires before each LLM call (message count + role histogram);
- `before_provider_request` fires before each request (payload keys + sha256, message count);
- `after_provider_response` fires after each HTTP response (status + header keys + header-value sha256);
- `message_end` exposes assistant `usage` (input/output/cacheRead/cacheWrite/totalTokens/cost numbers);
- `tool_result` content is modifiable and the patch is observed by the model:
  the handler appends a hash-only marker text block; the model can quote the
  marker in its next turn (hash only, never tool output).

## Files

- `index.ts` — the probe extension (single file, ~3.8 KB).
- `probe.log.jsonl` — created at runtime next to `index.ts` (delete with the probe).

## Install (live run — parent-coordinated; do NOT leave installed)

1. Copy the probe into the Prime extensions dir (one level, index.ts is
   auto-discovered — no package.json needed):

   ```powershell
   Copy-Item -Recurse brainstem\p3-probes\provider-probe `
     $env:USERPROFILE\.prime\agent\extensions\provider-probe
   ```

2. Restart the Prime Agent daemon (new extension dirs are only discovered at
   daemon start). If the daemon is already running:

   ```powershell
   prime-agent daemon stop
   prime-agent daemon start
   ```

3. Open a session and send one ordinary prompt (any prompt; the probe logs
   hashes/counts only). Then ask the model: "quote the probe-marker text you
   saw appended to the last tool result" — a correct quote proves the
   `tool_result` patch flowed back into model context.

## Observe

```powershell
Get-Content $env:USERPROFILE\.prime\agent\extensions\provider-probe\probe.log.jsonl
```

Expect one line per event: `before_provider_request` (payloadKeys/payloadSha/
messageCount), `after_provider_response` (status/headerKeys/headerValuesSha),
`message_end` (role + assistant usage numbers + firstTextSha),
`tool_result` (toolName/contentSha/probe-marker), `context`, `resources_discover`.

## Remove (always after the live run)

```powershell
Remove-Item -Recurse $env:USERPROFILE\.prime\agent\extensions\provider-probe
```

Then delete this repo directory and restart the daemon once more:

```powershell
Remove-Item -Recurse brainstem\p3-probes
prime-agent daemon stop; prime-agent daemon start
```

The probe never installs anything else: no npm dependencies, no config
changes, no loader/extension modifications.
