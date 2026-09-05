# Deployment Alignment — Pre-Deployment Candidate vs Deployed Comparison

Deterministic file-by-file SHA-256 comparison, run before any replacement.

- Candidate source: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\brainstem\prime-extension`
- Deployed extension: `C:\Users\assas\.prime\agent\extensions\second-brain`

- Candidate file count: 24
- Deployed file count: 24
- Files only in candidate: none
- Files only in deployed: none
- Identical files: 9
- **Differing files: 15**

## Differing files

- `active-state-mirror.ts`
- `autoinject.ts`
- `config.ts`
- `environment-mirror.ts`
- `index.ts`
- `ledger-mirror.ts`
- `p4-mirror.ts`
- `recall-gate.ts`
- `routing-bridge.ts`
- `rtd.ts`
- `sensors.ts`
- `visibility-bridge.ts`
- `vmem.ts`
- `worker-context-bridge.ts`
- `worker-result-bridge.ts`

## Identical files

- `budget-bridge.ts`
- `context-paging.ts`
- `driver-orchestrator.ts`
- `injection-slots.ts`
- `lean-code.ts`
- `orchestrator-guard.ts`
- `stop-boundary.ts`
- `storage.ts`
- `types/prime.d.ts`

## Verdict

Independently reproduces the previously reported count: **15 differing files**,
9 identical, 0 missing, 0 extra. The old count is confirmed correct — not stale.
Deployment (step 5) is required.
