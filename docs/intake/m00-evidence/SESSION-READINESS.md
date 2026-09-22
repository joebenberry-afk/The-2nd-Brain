# Session readiness — the facts a new session should not have to rediscover

The most expensive friction reported this session was **discovering environmental facts by attempting
an operation and being refused**: the runnable interpreter, whether delegation is available, whether a
required reference exists, and whether the gates for the current subject already pass. Those facts were
all knowable before the first edit. This file states them, and — because a statement decays — the exact
command that reproduces each one.

Read this before planning work in this candidate. It is a *fast readiness* layer, deliberately separate
from implementation gates (scoped lint/type/tests after an edit) and from qualification gates (full
applicable suites + independent review on a frozen candidate).

## Facts, with how to recheck each

| Fact | Value observed | Recheck |
| --- | --- | --- |
| Candidate | `.worktrees/m00.3-producer-guard`, branch `brain/m00.3-producer-guard`, HEAD `b5f809f` | `git rev-parse HEAD` |
| Runnable interpreter | `.worktrees/m00.3-producer-guard/.venv/Scripts/python.exe` | `ls .venv/Scripts/python.exe` |
| Interpreter trap | the user-level `PYTHONHOME` points at a corrupted tree; every Python call needs `PYTHONHOME`/`PYTHONPATH` removed | run anything without stripping them and observe the `SRE module mismatch` |
| Import identity | `second_brain` resolves to `<candidate>/src/second_brain/__init__.py` (editable install), so any cwd may be used | `.venv/Scripts/python.exe tests/fixtures/omp_replay_state.py setup …` echoes `python` and `second_brain_file` |
| Extension test runner | `npx vitest run --config vitest.candidate.config.ts` from `brainstem/prime-extension` (candidate-local cache; never writes through the node_modules junction) | the run itself prints the config path |
| Extension suite | 771 passed / 771 | same command |
| Applicable Python suite | 398 passed (the 13 files listed in `pytest-schema-neighborhood.txt`) | `.venv/Scripts/python.exe -m pytest <those files> --no-header -v` |
| Lint / type gates | `ruff check src tests` clean; `pyright` 0 errors — **this was not true on arrival**: four `E501`s (`jit.py`, `worker_recovery.py`) and four `object`-vs-`str` errors in `test_writer_admission.py` were inherited and are now repaired, classified as gate repairs, not behaviour changes | `ruff check src tests`; `pyright` |
| Mutating delegation | **UNAVAILABLE** — the loaded extension refuses mutating worker dispatch: `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` (this host advertises no settlement capability). This is the *admission capability gate* being exercised, nothing else | attempt a task-tool spawn that implies edits |
| Read-only delegation | read-only agents were accepted in this session (`evidence-auditor` ran a read-only audit). Availability is a separate question from *enforcement*: a declared read-only lane may not bypass the settlement gate, and its restrictions must be demonstrated, not declared | attempt a read-only agent spawn |
| Permitted fallback | direct candidate work + artifact review in this session (that is how the campaign proceeded) | — |
| Runtime verification | driver-executed (tests and fixtures run by this session); **independent execution was unavailable**, and one read-only independent audit was obtained | — |
| Production state | runtime worktree `.worktrees/qualified-v2` extension `index.ts` = `42b57b41…410b75a41` (unchanged all campaign); candidate `index.ts` = `f2c95300…12749e6e`; production activation **NOT PERFORMED** | `sha256sum ../qualified-v2/brainstem/prime-extension/src/index.ts brainstem/prime-extension/src/index.ts` |
| Required references | brought forward in `docs/intake/m00-evidence/` with digests; the four that remain outside this candidate are named in `MANIFEST.md` | read `MANIFEST.md` |

## Two distinctions that must not be flattened

- **Spawn refused ≠ completion guard.** The spawn refusal above exercises the *admission capability
  gate*. The unauthenticated-replay refusal exercises the *completion-authority consumer*. Neither one
  proves the other, and neither alone proves that issuance is restricted, that cleanup was observed, or
  that writer release is safe. Keep them as separate evidence lines.
- **Refusal ≠ early fact.** Every environmental fact above was reported to the agent *as a refusal* at
  the moment of use. The purpose of this file is to move them to the moment of planning. Where a future
  session finds itself discovering a new one by refusal, the repair is to add the fact here with its
  recheck command — not to weaken the guard that produced the refusal.

## Status vocabulary for replay-style results

A replay result is not "completion" or "extension error". Report it as separate facts:

```
completion message received:          yes
authentication:                      refused (UNAUTHORIZED_CALLBACK)
authoritative completion recorded:   no
worker outcome established by it:    no
ownership:                            unchanged
recovery:                             not completed
```

That is the shape `docs/intake/m00-evidence/replay-authority.md` §3 asserts per case, and the shape any
later report should use instead of an internal event name.
