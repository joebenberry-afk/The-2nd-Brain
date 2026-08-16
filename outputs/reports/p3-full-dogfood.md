# P3-Full Campaign Dogfood (P3-I gate) — Real Maintenance Task

Plan §21 (dogfooding) + §23 P3-I gate. Branch `brain/p3-lean-code` @ c65a980.
AutoInject ACTIVE (untouched); Lean skill stays candidate (inert — this run
had zero Lean kernel influence, matching the baseline arm of the paired eval).

## 1. Task + source

**Task**: fix the single pre-existing `ruff` finding in `src/second_brain/ledger.py`
(SIM105 at ledger.py:929: `try/except OSError: pass` -> `contextlib.suppress`).

**Source**: genuine hygiene task in a touched area — the pattern was introduced
by THIS campaign's P3-E narrow fix (`_write_manifest` unique-temp rewrite), and
`ruff check src` reported exactly one finding. `projects/second-brain/
known-issues.md` is empty (no items); `simplification-debt.md` holds only the
RTD deferral (not a task). Chosen because it has a crisp acceptance condition
and is the campaign's own lint debt.

**Acceptance condition (observable)**: `ruff check src` exits 0 with the
SIM105 finding gone; `pytest tests/test_ledger.py` stays green (37/37);
behavior unchanged (`contextlib.suppress(OSError)` is exactly equivalent to
`try/except OSError: pass`); diff touches ONLY ledger.py (2+/3-).

## 2. Risk evidence (captured BEFORE editing)

```
$ brainctl risk assess <repo> --file src/second_brain/ledger.py --verification-ladder
Risk: MEDIUM (score 4)
  centrality  2  central paths (... src/second_brain): src/second_brain/ledger.py
  hotspot     2  src/second_brain/ledger.py has 6 commits in last 20
Verification ladder (MEDIUM): ...
  independent verifier: not required
  human approval: not required
```

MEDIUM -> no fresh independent verifier required (that is the HIGH tier).

## 3. Ladder actions performed (MEDIUM)

| ladder item | performed | evidence |
|---|---|---|
| targeted test/check | `ruff check src` | exit 0, zero findings (SIM105 gone) |
| typecheck/compile | `pyright src/second_brain/ledger.py` + `py_compile` | both exit 0 |
| diff sanity | `git diff` reviewed | 1 file, 2+/3- (import + suppress swap) |
| relevant tests | `pytest tests/test_ledger.py` (37/37) + FULL suite | all green |
| requirement-ledger check | disposable capsule + 2 material reqs with evidence, marked verified | `0/2 material requirements unverified (gate on)` exit 0 |
| affected-file review | ledger.py only in diff | yes |
| no unrelated simplification | diff contains ONLY the suppress change | yes |

(HIGH-only items — fresh verifier brief, adversarial tests, rollback check —
were NOT required at MEDIUM and were not performed.)

## 4. Quality / acceptance evidence

```
ruff check src              -> exit 0 (was: SIM105 ledger.py:929)
pyright ledger.py           -> clean; py_compile -> clean
pytest tests/test_ledger.py -> 37 passed
pytest (full suite)         -> all green
git diff --stat             -> src/second_brain/ledger.py | 5 ++---
                             1 file changed, 2 insertions(+), 3 deletions(-)
requirements check          -> 0/2 material requirements unverified (gate on), exit 0
```

## 5. Dogfood economics (session telemetry 01a0094d, this retained worker)

The session is the full P3 campaign (P3-D .. P3-I) — the dogfood subject per
the gate. Task-marginal share is a small slice (risk assess + edit + 3
checks + evidence + report).

| metric | session total (P3-D..P3-I) | window-2 median/run (comparison) |
|---|---|---|
| assistant_usage rows | 454 | ~10 turns |
| input_tokens | 743,679 | 17,234 |
| output_tokens | 392,287 | 6,233 |
| cache_read_tokens | 154,454,784 | 164,992 |
| cache_write_tokens | 0 | 0 |
| cost_total | $0.646 | $0.0043 |
| turns | 454 | 10 |
| tool_calls | 475 (100% ipython) | ~12 |
| AutoInject packets / packet_tokens | 3 / 1,628 (SEPARATE) | 3 / 2,623 |
| wall time | ~7.9 h | ~66 s |
| compactions | 0 | 0 |
| files touched (task) | 1 (ledger.py) | 1 |

Honest framing: the TASK is tiny (1 file / 2 lines) — comparable to the
eval's already-minimal class (T3/T14/T16) and its marginal cost is a few
turns well inside the window-2 distribution; the session totals above are
the campaign aggregate, reported for completeness.

## 6. Orchestration evidence

- **0 fresh workers spawned** for this task: I am the retained worker
  (reused across P3-D..P3-I per the child-pool hygiene directive); no `rlm()`
  spawn calls in this session; no children (agent roster shows none).
- Risk-adaptive verification was performed by MYSELF per the MEDIUM ladder —
  no independent verifier needed, none spawned (plan §15.4 stop rule honored:
  no "one more" worker).

## 7. P3-I gate verdict

**PASS — real-world behavior matches the controlled eval.** The dogfood run
behaved exactly like a window-2 baseline arm: risk captured before editing
(MEDIUM via the new P3-G ladder), ladder actions performed proportionally,
minimal diff (1 file/2 lines, no scope creep — T16-style), relevant tests +
full suite green, Requirement Ledger gate used for completion evidence
(0/2 unverified -> stop permitted), zero fresh workers, AutoInject cost kept
separate. No Lean kernel was active (candidate skill inert) — this is the
Lean-OFF control arm behavior, consistent with the eval's baseline.

## 8. Changed files (uncommitted)

- `src/second_brain/ledger.py` (this task: SIM105 fix)
- (plus the P3-G / P3-H files from the prior jobs, already reported)
