# Candidate identity and deployment — not qualified

- REPAIR_START_SHA: `f5089ac1b6e27f0b3329196cec7e74f402cd0636`
- FINAL_RUNTIME_CANDIDATE_SHA: `75b80d2aab33929923d4d9323bcaf639bc69591b`
- QUALIFIED_RUNTIME_SOURCE_SHA: **NONE**. This is an auditable RC candidate, not a qualified release.
- Version: **2.0.0-rc.1**; schema **22**.
- Runtime/state home: `C:/Users/assas/Documents/The-Second-Brain/.worktrees/v2-one-shot`.
- Python: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\.venv\Scripts\python.exe`, **3.11.15**, SQLite **3.50.4**. The verification environment removes PYTHONHOME/PYTHONPATH pollution.
- OMP: **18.1.10**, `C:/Users/assas/.bun/bin/omp.exe`; upstream source reference `f241301c83726afe75a847e919b89977a54dafbe`. Exact installed executable/bundle hashes are recorded, not inferred from the version string.

Runtime implementation commit: `64694bb32f02cd6a736ec65a24660bd8acd6a3f6`.
The final candidate adds only two verification-file corrections; runtime,
adapter, dependency and configuration manifest bytes remain unchanged.
The doctor checkpoint below therefore identifies the implementation commit.

## Independent fingerprint scopes

| Scope | SHA-256 |
|---|---|
| Runtime source manifest (126 files) | `62e9397efc6a171fc896d5f941c8252a7f53d5c661062d5722611e6b961d8ae4` |
| Adapter source manifest (24 files) | `8eef1a6716c2050a559f336c25179d8b8a2de1679a53c2b9981aca61734715be` |
| Configuration/profile snapshot | `65ec1298da95db9282aee4b19864a26f850af5122399a37325341661f25337a5` |
| Actual default installed extension | `cbcc46d28cd0b1b82c979bef66940f519beb33d3d92f0bb73aeaccc23a67875d` |
| Expected candidate installed layout | `da9b55bf6f150a41b546fa126f8a452717ec47a01729730b400c94ed9515a47b` |

`artifacts/frozen-identity.json` contains every path, size and SHA. Manifest digests hash compact UTF-8 JSON arrays of `{path,bytes,sha256}`, sorted by case-sensitive path, with slash-normalized relative paths. Runtime and adapter domains are intentionally different. The config/profile hash covers canonical config files, the observed native `config.yml` hash, and the explicitly listed nonsecret environment keys. It is **not** a verified loaded-candidate profile; qualified profile hash remains null. No credentials or account database were read into this manifest.

The extension package lock is hashed there. No tracked Python lock was found in the inspected scope; installed distribution versions and platform are in `artifacts/runtime-environment.json`. Dependencies and canonical configuration were not changed by the source commit.

## Deployment reality

The default extension directory contains the expected 24-file layout, but it does **not** match this candidate. Different files: `budget-bridge.ts`, `index.ts`, `ledger-mirror.ts`, `worker-result-bridge.ts`, `types/prime.d.ts`. No candidate installation or new native loaded-process proof was performed. Scratch installer tests are not deployment evidence; an existing process cannot prove newly loaded bytes.

The sealed doctor reports **19 checks, zero failures/warnings**, candidate SHA prefix `64694bb32f02`, schema 22 and adapter fingerprint prefix `870dce1c1687` (`artifacts/doctor-sealed-source.txt`). Its dirty marker reflects uncommitted evidence at that checkpoint, not a clean-qualified native session. Its historical `qualified_baseline` field does not qualify this candidate.

A pre-schema-22 backup was created at `backups/backup-20260905-042829-573966`; applying migration 22 and immediate reapplication produced `[22]` then `[]`. No historical receipts or telemetry were rewritten. Final default restore/redeploy remains open.

Source commit and later evidence HEAD are deliberately separate. The evidence commit does not embed its own SHA; the final response and remote verification identify it externally. **No v2.0.0 tag is created.**


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
