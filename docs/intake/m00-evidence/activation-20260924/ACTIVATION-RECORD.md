# M00 production activation record (2026-09-24)

**Result:** `M00_PRODUCTION_ACTIVATED / EXTERNAL_TRUST_ROOT_PENDING`.
The owner authorized activation on 2026-09-24; the agent executed it from the
card [`../activation-prep-20260924/ACTIVATION-CARD.md`](../activation-prep-20260924/ACTIVATION-CARD.md).
Step logs and live-arm summaries are in [`logs/`](logs/). The full host streams
stay in the gitignored
`outputs/reports/m00-activation-20260924/live/`; their digests are recorded in
`logs/LIVE-STREAM-DIGESTS.txt`.

## Production baseline

```text
code baseline      = 749e9cd (release worktree .worktrees/qualified-m00, detached) / code-equivalent 80f3c54
extension          = %USERPROFILE%\.omp\agent\extensions\second-brain: 17 files, manifest ce7fefa8…, index.ts 10a8662f…
runtime            = canonical .venv editable -> .worktrees/qualified-m00/src (Python 3.13.7)
production schema  = 28 (migrations 25-28 applied by `init`)
memories           = 116 (19 stored VERIFIED -> effective TESTED; 10 stored project_rule -> effective advisory)
external issuer    = unavailable (EXTERNAL-TRUST-ROOT-WORK-ITEM.md)
authority features = refused/degraded as documented in the register's capability table
```

## What was executed

| Step | Command (abbreviated) | Result |
|---|---|---|
| 1 Freeze | production runtime `backup --note "pre-M00-activation 2026-09-24"`; extension copy to `%TEMP%\m00-preactivation-extension-second-brain` | backup `backups\backup-20260924-065413-970460`: DB sha256 `cf05045470c853982c1a3136809c27a7f8c2f049619bb85ce8e239c2dd13fb0d` (matches its manifest), schema 24, 116/19/10, integrity ok; extension copy 26 files `6688f073…` |
| 2 Extension | `install-prime-extension.ps1 -SourceRoot .worktrees\qualified-m00` | exit 0; source commit `749e9cd`; 17 files; manifest `ce7fefa8…`; pre-install backup `.worktrees\qualified-m00\backups\20260924-025430-030-prime-extension-pre-install`; no displaced directory left in the discovery path |
| 3 Runtime | `uv pip install -e .worktrees\qualified-m00 --python .venv\Scripts\python.exe` | `qualified-v2` -> `qualified-m00`; import origin `qualified-m00\src`; issuer registries 0/0/0 |
| 4 Database | `init` | `applied migrations [25, 26, 27, 28]`; nothing seeded |
| 5 Verify | `doctor`, read-only DB query, refusal commands | 21 checks, 0 failed, **0 warnings** (the rehearsal's skill-authority warning did not appear on the real home); schema 28, 116 memories, integrity ok |
| 6 Live | fresh `omp -p --mode json --no-session`, real home, normal extension discovery, model `deepseek/deepseek-flash` | see acceptance below |

## Live acceptance

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Installed extension matches the release | PASS | installer post-swap verification `ce7fefa8…`; `index.ts` `10a8662f…`; independent check: 17/17 files byte-equal to `qualified-m00` |
| 2 | Canonical `.venv` imports `qualified-m00` | PASS | `logs/03-repoint.txt` |
| 3 | Schema 28 | PASS | `logs/05-db-state.txt` |
| 4 | All 116 memories present | PASS | same |
| 5 | Former VERIFIED rows display and evaluate as TESTED | PASS | `memory list`: 19 rows `TESTED (claimed VERIFIED)`, 0 bare VERIFIED; `effective_verified 0`, `effective_elevated 0` |
| 6 | `--grade VERIFIED` refused | PASS | `remember … --grade VERIFIED` rc 2 `VERIFIED_REQUIRES_ATTESTATION`; row count unchanged (`logs/05-refusals.txt`) |
| 7 | Policy lane has no authoritative memories | PASS | `_lane_authorized(row, "policy")` true for 0 of 116 rows |
| 8 | An ordinary stored memory reaches the parent agent | PASS | `live_memory_on`: host-recorded `brain.autoinject.packet` containing `mem-a8d221e64549` ("Migration ordering", TESTED), `authority: advisory` |
| 9 | Native child delegation still works | PASS | `live_brain_on`: one native `sonic` spawn (`SonicFixedReply`), child result `CHILD-OK-391` returned via `hub`, 0 interference markers; the matched Brain-off arm behaved the same |
| 10 | The Brain-off control gets no Brain memory | PASS | `live_memory_off` and `live_brain_off`: 0 memory-id hits, no Brain custom records |
| 11 | `doctor` has 0 failures | PASS | 0 failed, 0 warnings |
| 12 | No new HIGH/MEDIUM security finding | PASS | independent `LiveSecurityCheck` (security reviewer; executed read-only on production and in disposable DB copies): "no NEW HIGH/MEDIUM finding introduced by activation". One **pre-existing** MEDIUM recorded below |

## Deviations and observations, stated plainly

- **Not every session was closed (card step 0).** Activation ran from inside
  the one live OMP process (pid 25360), and two Hermes gateway processes were
  also running. The backup uses SQLite's online backup and recorded its own
  hash, and `init` migrated inside a transaction, so neither is at risk. The
  activating OMP process still holds the **pre-activation extension module in
  memory** until it restarts. Its budget and routing bridges fail open against
  the new runtime, and its worker bridges fail closed. The reviewer found no
  new authority sink, but cached pre-activation state may persist in that
  process. **Restart OMP to finish activation for this process.**
- **The first memory prompt returned `NO_RELEVANT_MEMORY`.** That
  instruction-heavy prompt diluted retrieval. An A/B run on disposable copies
  gave the same result on the old (`qualified-v2`) and new runtimes, and both
  produced the identical packet `pkt-e164f810cf059d8e` for the plain question.
  This is prompt design, not a regression. The accepted run used the plain
  question.
- **The Hermes integration was not in the activation card.** The enabled
  integrator-profile plugin (`%LOCALAPPDATA%\hermes\profiles\integrator\plugins\second-brain-hermes`)
  pins the canonical `.venv`, so it now runs the release. Its lifecycle and
  pre-LLM hooks work, and writeback creates only OBSERVED/advisory candidates.
  Its stale worker tools (`second_brain_delegate`, `review`, `correct`) are
  still advertised but refuse with `ORCHESTRATION_REMOVED` and write nothing
  (executed in a disposable home). Replacing the plugin with the release copy
  (`brainstem/adapters/hermes`, which registers only writeback and
  handoff_read) is a separate follow-up that needs a gateway restart.
- **The `lean-code skill has no current matching approval` extension error is
  pre-existing.** It also appears in sessions that started before activation.
  The unapproved lean kernel is omitted, as the approval binding requires.
- **The canonical backup is a second at-rest copy** of the full DB and config.
  It is gitignored, has the same file permissions as the original, and grants
  no authority under the new runtime; only an explicit rollback to the old
  runtime would restore the old authority.

## Pre-existing finding surfaced by the live check (not introduced by activation)

**Antigravity Stop hook: MEDIUM.** `adapters/antigravity.py:202-244`, identical
in `qualified-v2` and the release, reads caller-writable critical/high
requirements (`working_set.check_requirements`) and returns host
`decision: "continue"`. That lets Brain veto a host session's completion. The
reviewer reproduced it in a disposable home: `stop` before the requirement,
`continue` after `requirements add … --importance critical`. The live
Antigravity plugin registers `Stop`. This is host completion control, which the
orchestration-free boundary assigns to the harness. It is the first V3
boundary item (register, "M00 → V3 freeze boundary"). Activation neither
created nor widened it.

## Rollback (unchanged; see the card)

Rollback restores the SEC-AUTH exposure. In order:

1. Run `uninstall-prime-extension.ps1 -BackupDir
   ".worktrees\qualified-m00\backups\20260924-025430-030-prime-extension-pre-install"`,
   or copy back `%TEMP%\m00-preactivation-extension-second-brain`.
2. Run `uv pip install -e .worktrees\qualified-v2 --python .venv\Scripts\python.exe`.
3. Optionally, `restore backups\backup-20260924-065413-970460`.

## Not claimed

No independent approval, protected custody or cryptographic signing exists.
Activation re-enabled none of the fail-closed capabilities.
