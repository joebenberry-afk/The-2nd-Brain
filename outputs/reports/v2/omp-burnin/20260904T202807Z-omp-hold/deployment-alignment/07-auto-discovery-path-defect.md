# Deployment Alignment — Critical Finding: Wrong Auto-Discovery Path

## Summary

The canonical installer's default deployment target,
`~/.prime/agent/extensions/second-brain`, is **not auto-discovered** by the
`omp` (oh-my-pi) binary actually present on this machine (`omp/18.1.10`,
`C:\Users\assas\.bun\bin\omp.exe`). A byte-identical deployment there (proven
in `05-post-deploy-verification.md`) produced **zero** Brain instrumentation
on a plain `omp -p` smoke run: no `brain.active-state` custom message, and no
telemetry file for that session anywhere under
`telemetry/agent-performance/`.

## Diagnosis steps

1. `omp -p --cwd <worktree> "Reply with exactly: ok"` (no extension flags) —
   session `01a06ed8-…`. Result: plain assistant reply only, no Brain custom
   message, no telemetry file for that session ID. Extension not active.
2. `~/.omp/agent/extensions/` did not exist at all before this investigation
   (`ls` failed — no such directory). `omp config list` shows
   `internal.extensions = []`.
3. `omp -p ... -e "<...>\.prime\agent\extensions\second-brain\index.ts" "Reply with exactly: ok2"`
   — explicit extension load. Result: `brain.active-state` custom message
   appeared (`[SECOND_BRAIN_ACTIVE_STATE]` / `[SECOND_BRAIN_HOT_CONTEXT]`).
   **The extension code itself is correct** when loaded.
4. Diagnostic copy of the same 24 files to
   `~/.omp/agent/extensions/second-brain-diag/` (no `-e` flag needed) —
   session `01a06edd-…`. Result: `brain.active-state` custom message
   appeared automatically. **Confirms the real auto-discovery root is
   `~/.omp/agent/extensions/`, matching the `PI_CODING_AGENT_DIR` default
   (`~/.omp/agent`) reported by `omp --help`, not `~/.prime/agent/…`.**

## Root cause

`scripts/install-prime-extension.ps1` defaults
`$ExtensionsDir = Join-Path $env:USERPROFILE ".prime\agent\extensions"`. This
matches a different/legacy product path ("Prime Agent") and does not match
this OMP build's real auto-discovery directory. Every deployment through the
documented default command (`powershell ... install-prime-extension.ps1`
with no `-ExtensionsDir`) therefore never loads the Second Brain extension by
default for a freestanding `omp` invocation. This is a genuine, previously
undetected deployment-target defect — the extension code itself, and the
manifest/hash verification the installer performs, are both correct.

## Resolution applied (deployment-only, no source change)

The installer already supports an explicit override
(`-ExtensionsDir`/`-SettingsFile`), so no script or extension source code was
modified. Re-ran the existing installer, pointed at the real auto-discovery
root:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-prime-extension.ps1 \
  -SourceRoot "C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot" \
  -ExtensionsDir "C:\Users\assas\.omp\agent\extensions" \
  -SettingsFile "C:\Users\assas\.omp\agent\settings.json"
```

Output:

```text
Source repository: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot
Source commit: da37094f3114098072610fa9464ec6cca880f23f
Target: C:\Users\assas\.omp\agent\extensions\second-brain
File count: 24
Manifest SHA-256: f16a4e35edbf04550a9b2c164b7d92a65275e6471e72798c6ee101e9d4b29cff
Pre-install backup: C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\backups\20260904-200145-476-prime-extension-pre-install
```

The manifest SHA-256 (`f16a4e35…`) is identical to the earlier `.prime`
deployment, confirming byte-for-byte equivalence of both deployments. The
diagnostic `second-brain-diag` copy was deleted before this installer-managed
deployment, so the final state under `~/.omp/agent/extensions/` is exactly
what the installer produced and verified — not a hand-copy.

## Post-fix verification

Plain `omp -p --cwd <worktree> "Reply with exactly: ok4"` — **no** `-e` flag,
**no** explicit extension path — session `01a06edf-3675-753f-9d2e-d253e5411146`:

- `brain.active-state` custom message present in the session transcript.
- `telemetry/agent-performance/2026-09-05T00-01-57-365Z_01a06edf-3675-753f-9d2e-d253e5411146.jsonl`
  exists.
- `state/extension-runtime-ready.json` refreshed to a new `resolved_at`
  (`2026-09-05T00:01:57.336Z`, previously stale at `2026-09-04T19:49:25.373Z`)
  with `home` correctly resolved to the candidate worktree and
  `runtime_python` correctly resolved to the candidate worktree's venv.

**Candidate source == deployed OMP extension == observed runtime identity is
now proven for a genuinely fresh, flag-free OMP process.**

## Scope note

The pre-existing `~/.prime/agent/extensions/second-brain` deployment (from
step 5) was left in place; it is inert for this OMP binary's auto-discovery
but harmless, and may still serve an actual "Prime Agent" binary elsewhere.
No installer script or extension source file was edited — only an existing,
already-supported `-ExtensionsDir` parameter was used to target the correct
directory. This finding and its resolution should be carried into the
installer's documented defaults as a follow-up (not performed here, to avoid
an unreviewed default-behavior change to a shared script).

## Open long-lived process caveat

One pre-existing, long-lived `omp.exe` process (PID 44248) is present on this
machine, launched well before this campaign step. Its own frozen in-memory
extension state (if any) is unaffected by this deployment-directory
correction and was not touched — it was not safely terminable without
aborting the task using it. This does not affect qualification validity:
every new Phase 22 activity in this campaign is generated by fresh,
independent `omp` process invocations (confirmed above), not by that
pre-existing process.
