# Phase 11-16 — Pre-Deploy Backup Manifest (P1 repair candidate)

Backup taken before deploying the P1-repaired candidate, of the extension
currently live at OMP's real auto-discovery path (the deployment-alignment
pass's prior candidate, `da37094`/`0ec276e`-era bytes — pre-dates this
repair's `a9ff745`/`2d39016` fixes).

## Backup location

```text
outputs/reports/v2/omp-burnin/20260904T202807Z-omp-hold/final-p1-repair/pre-deploy-backup-2026-09-05T013858046Z/second-brain/
```

## Source (original deployed extension)

```text
C:\Users\assas\.omp\agent\extensions\second-brain
```

## File count: 24

## File manifest (path, sha256, bytes)

| Path | SHA-256 | Bytes |
|---|---|---:|
| `active-state-mirror.ts` | `ca7d479587f70c20382c02f57c32398d59d084b2726992c13594ea5b73101b08` | 7196 |
| `autoinject.ts` | `d2591ccc25ed2dfc847c9a23ca0cd7fadf66af71cae1509e95d6ee66165fe85b` | 27904 |
| `budget-bridge.ts` | `84bf063694e3bdac53f0f6f92ea48611b1e86fc88b04a50ad18280ad0a4458c3` | 3203 |
| `config.ts` | `a46c7540e824a8c179cea88b70bfb55274e9e898aad4ef06aa9441ebd133002d` | 22613 |
| `context-paging.ts` | `133de0baacdc8219260e2cad0df046612c6b4fa3468c28b1a6a57ffe762d0d94` | 36235 |
| `driver-orchestrator.ts` | `a2971d525f763996661c0bd18c3dec7abbd680c1e2716429200a2e1fb0ce3272` | 7354 |
| `environment-mirror.ts` | `8f236a113d9c73deccbcbf04d82b288c2d6e89ac71e34d8e4e417316ca8d3bda` | 3312 |
| `index.ts` | `7129831de5fde5c5036078b7fef13b79b80273e722c0afa2f958ceeba320686a` | 125590 |
| `injection-slots.ts` | `d9e45ceb467a7a26142055035709bab13cb2c2f8e9c2fb9de9d982c9627ebe35` | 6410 |
| `lean-code.ts` | `ae91d081d014d77fb4d678cc4b0f175a3bf21d367dde72b1652387bcf6679a74` | 25359 |
| `ledger-mirror.ts` | `7c83d36d050fd94e0128f571e4020902cbc8020512de5d0ee39c45bab2a317d2` | 16385 |
| `orchestrator-guard.ts` | `98f2166215541074f9571c171c345e99aca51a80915c744cbf56889114fc0d13` | 6027 |
| `p4-mirror.ts` | `788ef620d79fad4910958a330f6b0fa8bccedb8d952d7b33e4e70a6e79fa55ff` | 5128 |
| `recall-gate.ts` | `bc0c9ca3745a1af789fc1aa77303dc5f830f4c070fd112252b7326173de5edd6` | 10921 |
| `routing-bridge.ts` | `0df72d0ebc73a10ded6e28bc43cb562ff95c9fa63f6a2354fcf572b582627fbe` | 8587 |
| `rtd.ts` | `c60cfb89e9633d88447964362b4026a477f313454c0470c8efc3a05ef64269ab` | 33840 |
| `sensors.ts` | `b4a96ad63f921207f32798d18ca2f26d7e68566d93605e733710e6696d4a9cb7` | 57265 |
| `stop-boundary.ts` | `1ee1ba9b0d26ef9bd092ff6323f6a258478225d369d3d5361b6fcc2b9b3d36d3` | 4409 |
| `storage.ts` | `6b6afb91dc7869772281f2523169caa03058a5b30ffe5d66a143fd5dccc1cc18` | 5843 |
| `types/prime.d.ts` | `5337f269578dc7736f54065b2aaa0672b542c267816a6aafd05b8d7480cb8bb7` | 10153 |
| `visibility-bridge.ts` | `d44b9bd791eb4d07cddaff0e49795be8a7575941ff0877a96b180df0b58784c0` | 7954 |
| `vmem.ts` | `d5cadb25abc69c5f3a367314c5365b4bb039ca0371a7d9e4f545d11e7dcdd1b7` | 23707 |
| `worker-context-bridge.ts` | `27619bc9927fed934e931dfa11288f356f1f5fca292f320aea4610d63143c116` | 6721 |
| `worker-result-bridge.ts` | `04b4190a7128f15e80edd95a839e6c02db5674150fde432f9720c4443fedaea9` | 4518 |

## Rollback guarantee

Exact byte-for-byte copy of the deployed extension directory taken before
this repair's deployment. Restoring it (copying `second-brain/` back over
`~/.omp/agent/extensions/second-brain`) reproduces the pre-repair deployed
bytes exactly, independent of Git history. Confirmed via the installer's
own additional pre-install backup mechanism (`scripts/backups/` under this
worktree), which will be a second, independent copy created during the
deploy step.
