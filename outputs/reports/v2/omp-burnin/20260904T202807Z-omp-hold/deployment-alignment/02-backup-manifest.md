# Deployment Alignment — Pre-Deployment Extension Backup

Backup created at `20260904T235135Z` before any replacement of the deployed extension.

## Backup location

```text
C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\outputs\reports\v2\omp-burnin\20260904T202807Z-omp-hold\deployment-alignment\pre-deploy-backup-20260904T235135
```

## Source (original deployed extension)

```text
C:\Users\assas\.prime\agent\extensions\second-brain
```

## File count: 24

## File manifest (path, sha256, bytes)

| Path | SHA-256 | Bytes |
|---|---|---:|
| `active-state-mirror.ts` | `a844b0786c326e5efbab3d1da501e1a52c9d72e5ed13830ce7acc58e919f3909` | 7161 |
| `autoinject.ts` | `a3979844c464abaa0e1776aeabc54e4b7183feb59290b5442edc9a388ace9a60` | 23206 |
| `budget-bridge.ts` | `84bf063694e3bdac53f0f6f92ea48611b1e86fc88b04a50ad18280ad0a4458c3` | 3203 |
| `config.ts` | `ff0c6bcaf058729b69ed1799c58669bfbd3749b0063681a48c535d007535f844` | 22087 |
| `context-paging.ts` | `133de0baacdc8219260e2cad0df046612c6b4fa3468c28b1a6a57ffe762d0d94` | 36235 |
| `driver-orchestrator.ts` | `a2971d525f763996661c0bd18c3dec7abbd680c1e2716429200a2e1fb0ce3272` | 7354 |
| `environment-mirror.ts` | `3662208f5d6f0856fed04c6d57344d102447ab292e49318d1038d1d4a342b0db` | 3277 |
| `index.ts` | `6fb9951dddca45563e054e9d3fe4e6174d34f848391958ce79f441658e66d3f5` | 118671 |
| `injection-slots.ts` | `d9e45ceb467a7a26142055035709bab13cb2c2f8e9c2fb9de9d982c9627ebe35` | 6410 |
| `lean-code.ts` | `ae91d081d014d77fb4d678cc4b0f175a3bf21d367dde72b1652387bcf6679a74` | 25359 |
| `ledger-mirror.ts` | `b56cc8e91984d6b232ba03ce6577d7cb7c7a24d576c984ec3cfd2d086c5b35c7` | 15142 |
| `orchestrator-guard.ts` | `98f2166215541074f9571c171c345e99aca51a80915c744cbf56889114fc0d13` | 6027 |
| `p4-mirror.ts` | `ccce8cd0d797573a4373b38f4d11deb990f2f1f75228916ddc84931c3bb90a87` | 5058 |
| `recall-gate.ts` | `c76012695687127f67bccad87161515643f4dc06e0d322a11d3623871fb9c57e` | 10886 |
| `routing-bridge.ts` | `fa9592f65ddc3828a44a30ea8bf88b418b51a11d1268ada8dc75351da32badda` | 8552 |
| `rtd.ts` | `e291404383862a6ad1aa8ff23318568bdbafb0fe91baa9ca263872f55fc1be34` | 33805 |
| `sensors.ts` | `875e77052425ef1eb26bd271dcbe9dbb64ba0db459f5f2b5712de7895bd6ffd9` | 57365 |
| `stop-boundary.ts` | `1ee1ba9b0d26ef9bd092ff6323f6a258478225d369d3d5361b6fcc2b9b3d36d3` | 4409 |
| `storage.ts` | `6b6afb91dc7869772281f2523169caa03058a5b30ffe5d66a143fd5dccc1cc18` | 5843 |
| `types/prime.d.ts` | `5337f269578dc7736f54065b2aaa0672b542c267816a6aafd05b8d7480cb8bb7` | 10153 |
| `visibility-bridge.ts` | `c89de1588d6083537699d8e3ce7f92134c732a9cd33639f15c30fc6cfe15af6b` | 7919 |
| `vmem.ts` | `bc22cdb38f7a5d598f499593d0a1bcd3e3abf22db32a625f1bfead1a5a5e8e27` | 23672 |
| `worker-context-bridge.ts` | `35c5896c631a44e57e3249550a42863e386f58e5ae067b83df251982d9ac5655` | 6686 |
| `worker-result-bridge.ts` | `aad4fede60ddc4215f83aefbacc277be0d293b8f8a6bcc7caad29b5fdab076f0` | 4468 |

## Rollback guarantee

This backup is an exact byte-for-byte copy of the deployed extension directory
taken before any modification in this deployment-alignment pass. Restoring it
(copying `second-brain/` back over the live deployment path) reproduces the
original file set, hashes, and byte content exactly. This is independent of Git
history: it captures the actual deployed bytes at the auto-discovery path, not a
reconstruction from any source tree.
