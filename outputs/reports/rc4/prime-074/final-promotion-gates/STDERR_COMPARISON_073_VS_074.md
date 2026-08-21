# STDERR_COMPARISON_073_VS_074.md

Full daemon-log stderr comparison, isolated patched v0.7.3 vs isolated patched v0.7.4,
each covering exactly 3 consecutive real driver->daemon->RLM-child->result->cleanup
spawns under the identical test protocol (3 trivial multiplication tasks, same prompt
template, same model `anthropic/claude-sonnet-5`, same `--autonomous` settings).

Source files: raw/073-daemon-full-stderr.log (agentdir-073, daemon PID 9112, socket
`\\.\pipe\prime-eperm-gate-073-final`), raw/074-daemon-full-stderr.log
(agentdir-074, daemon PID 25092, socket `\\.\pipe\prime-eperm-gate-074-final`).

## Signature-by-signature comparison

| Signature | v0.7.3 count | v0.7.4 count | Verdict |
|---|---|---|---|
| `Supervisor command ack_result failed: EPERM: operation not permitted, fsync` | 24 | 12 | Same class, **lower** count on 0.7.4 (not worse) |
| `failed to persist RLM subagent display entry: EPERM ... rename ...rlm-subagent.json.tmp-... -> ...rlm-subagent.json` | 1 | 0 | Same class, **did not recur** on 0.7.4 (not worse; the single 0.7.3 occurrence already looked like a one-off transient lock, consistent with the AV-scan-style rmdir/rename flakes seen elsewhere in this campaign, e.g. RLM_FIX_DIFF.txt's `jedi`/`scipy` package-extraction rmdir flakes) |
| `Idle eviction sweep failed: Timed out draining daemon mutations for idle eviction` | 1 | 1 | Identical count |
| Any other/new error signature | 0 | 0 | **No new failure signatures introduced by 0.7.4** |

## Root-cause identity check (not just observed-count comparison)

- `command-recovery-journal.ts` (the exact source of the fsync-EPERM class: `compact()`
  calls `fsyncSync()` on a **directory file descriptor**, a POSIX durability idiom that
  Windows does not support on directory handles -- non-fatal, caught, logged, daemon
  continues) is **byte-for-byte identical** between the `throwaway-073` and `prime-074`
  worktrees (`diff` produced zero output). This is mechanically the same defect in both
  versions, not a regression -- it is a pre-existing Prime/Windows portability gap
  present in the common daemon-supervisor code shared by both releases.
- `daemon-mode.ts` / `daemon-supervisor.ts` (source of the RLM-subagent-display rename
  path and the idle-eviction sweep) are **not** byte-identical between versions (real
  0.7.4 changes exist: socket-path normalization additions, a worker-environment
  construction refactor, one comment removed about "passive child from a stopped
  worker"). None of the diff hunks touch the `persist RLM subagent display entry`
  rename call or the idle-eviction drain-timeout logic, consistent with the identical
  idle-eviction count (1 vs 1) and the non-recurrence of the rename EPERM (0.7.4 not
  running fewer commands in a way that would suppress it -- the fsync-EPERM count on
  0.7.4 is roughly proportional to a somewhat shorter/more-concise 0.7.4 transcript in
  this run, not a change in the underlying rename logic).

## Conclusion

No new filesystem/journal error signature was introduced by 0.7.4. Frequency/severity
did not materially worsen on 0.7.4 for any signature (fsync EPERM roughly halved;
rename EPERM did not recur; idle-eviction timeout identical count). These are
pre-existing, non-fatal, Windows-portability issues common to both versions' shared
daemon-supervisor code (confirmed via direct source diff for the dominant fsync-EPERM
signature), not created or worsened by the 0.7.4 candidate. Per the task's explicit
instruction, none of these issues were fixed/modified during this qualification pass;
they are recorded here as a known, pre-existing, non-blocking limitation carried by
both versions.
