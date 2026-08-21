# RLM_ENVIRONMENT_MATRIX.md

All rows below were executed against isolated, disposable worktrees/venvs only, per the
user's isolation directive. No case touched the live shared kernel-venv or live daemon.

| Case | Prime | Venv holder alive? | Identity mutated? | Result |
|---|---|---|---|---|
| 1 | isolated 0.7.3 (`throwaway-073`+patches) | no | no (fresh build) | PASS -- clean bootstrap |
| 2 | isolated 0.7.3 (`throwaway-073`+patches) | **yes** (real running python.exe, held file open) | yes (1-line pyproject.toml change) | **FAIL 3/3** -- `EPERM: operation not permitted, unlink '...venvA\Scripts\python.exe'` |
| 3 | isolated 0.7.3 (`throwaway-073`+patches) | no (holder killed) | yes (same mutation repeated) | PASS -- clean rebuild, same "rebuilding kernel venv" code path |
| 4 | isolated 0.7.4 candidate (`prime-074`+patches) | no | no (fresh build) | PASS -- clean bootstrap |
| 5 | isolated 0.7.4 candidate (`prime-074`+patches) | **yes** (same method) | yes (same method) | **FAIL 3/3** -- byte-identical `EPERM: operation not permitted, unlink '...venvB\Scripts\python.exe'` |

(Live 0.7.3 case from the ORIGINAL prior-review failure is not re-run here per the
isolation directive; its failure signature -- `unlink
'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'`, "exactly one process
[the reviewing session's own kernel] found holding that exact file open" -- is
structurally identical to isolated cases 2 and 5 above: same operation (`rm()` on a
shared venv), same failure mode (`EPERM` unlinking `Scripts\python.exe`), same
precondition (a live process using that venv as its own running interpreter).)

## Interpretation (per the plan's own Phase D rubric)

The plan's rubric for `isolated 0.7.3 fails / isolated 0.7.4 fails` states:

> then suspect common Windows/bootstrap infrastructure

That is exactly what was found: cases 2 and 5 fail identically, with the ONLY
difference being the venv path baked into the error string. `bootstrap.ts` is
byte-for-byte identical between the live/0.7.3-patched tree and the isolated
0.7.4-candidate-patched tree (`diff` produced zero output, see
`RLM_ROOT_CAUSE.md`), so this is mechanically guaranteed to be common code, not a
version-specific behavior difference.

Cases 1, 3, 4 additionally show the DEFECT IS CONDITIONAL, not universal: the exact
same "rebuilding kernel venv" code path (identity mismatch -> destructive `rm()`)
succeeds cleanly whenever no other live process currently holds the venv's
`python.exe` open. This directly explains why ordinary/steady-state RLM child spawns
(no concurrent identity-changing event) are expected to succeed, while a fresh spawn
that happens to race a still-running older-identity kernel is expected to fail --
matching the "3/3 fail" signature actually observed in the live review (a hard,
reproducible failure mode, not intermittent noise), because once the first `rm()`
partially fails it leaves the venv wedged (see RLM_ROOT_CAUSE.md) and every subsequent
attempt re-triggers the same collision until the original holder process exits.

## Conclusion for this row of the gate

`isolated 0.7.3` and `isolated 0.7.4` behave identically under every tested condition.
No 0.7.4-specific regression was found in this defect. This satisfies Phase D's
"common infrastructure, not a 0.7.4 regression" branch.
