# Fresh Verifier Plumbing

Phase R9. Implements the mechanism needed to capture a genuinely fresh
verifier session's evidence — never generates a PASS/FAIL itself. No real
model was invoked this pass (explicitly out of scope per the session's
stop instruction); this is the capture/parse mechanism only.

## 1. The "prepare" half already existed — reused, not rebuilt

`brainstem/policies/verifier-role.md` states the fresh-verifier contract
but flags itself "no hard enforcement yet — Phase D2 will wire a
fresh-verifier delegation path." Before writing anything new, checked
whether that wiring already existed: `src/second_brain/verify.py`'s
`build_verifier_brief()` (Phase 7, already shipped, already tested —
`tests/test_verify.py`, 22 tests, all passing) already does real,
deterministic prompt construction: reads the session's requirements
ledger, capsule constraints, and git diff of touched files; deliberately
excludes solver reasoning (hypotheses, decisions, next_action, open
questions); and places the diff **before** the requirements so the
verifier must perform backward reconstruction before reading the task
(`BACKWARD_MANDATE`, `VERIFIER_QUESTIONS`). Exposed via `second_brain
verify build-brief <session_id> <repo>`.

An early draft of this phase's work duplicated this into a new
`VerifierRequestPacket`/`build_verifier_prompt()` — caught before
committing (`ruff`/`pyright` flagged a genuine `cmd_verify` name collision
with the existing command, which forced re-reading `verify.py` and
finding the duplication). Deleted; `second_brain verify build-brief`
remains the "prepare" step, unmodified.

## 2. What was actually missing: the "record" half

Nothing in the codebase captured what a fresh session *returned*, with
real provenance, and parsed a verdict from it. New:
`src/second_brain/fresh_verifier.py` + `second_brain fresh-verifier
record`.

- `VerifierProvenance` — provider/model/host/session_id/usage, all
  caller-supplied. A missing `session_id` is recorded as `{"available":
  false, "reason": "host does not expose provider run ID"}` (plan Rule B)
  — never invented. Missing usage token counts are recorded as `null`
  (plan Rule A), never zero or estimated.
- `parse_verdict(raw_response)` — regex-matches a `Result:` or `Verdict:`
  line for `PASS|FAIL|PARTIAL`; anything else (no line, ambiguous prose
  like "this will pass eventually") returns `UNPARSEABLE`. Never guesses.
- `record_verifier_response(prompt, raw_response, provenance)` — `raw_
  response` is a required argument, not something the function can
  produce itself; the verdict is parsed strictly after it exists. This is
  what makes "The parsed JSON must be created AFTER the raw response"
  (plan §15) structurally true rather than just a rule to remember.
- CLI: `second_brain fresh-verifier record --out DIR --prompt-file FILE
  --raw-response FILE --provider --model --host [--session-id]
  [--input-tokens] [--output-tokens] [--json]`. Both `--prompt-file` and
  `--raw-response` must already exist on disk — the command errors (exit
  2) if either is missing, rather than proceeding with a placeholder.
  Writes `raw-response.txt` (verbatim copy), `metadata.json`,
  `usage.json`, `verdict.json` to `--out`.

## 3. Verified real behavior, not asserted from code presence

Manually ran the full flow end to end (temp brain home, real subprocess
CLI invocation): a crafted raw response containing `Result: PASS` and
`Confidence: 0.9` produced the correct parsed verdict and written evidence
files; a raw response with no result line produced `UNPARSEABLE`, not a
guessed default; a missing `--raw-response` file produced exit code 2 with
a clear error, not a fabricated result.

## 4. Verification

```
.venv\Scripts\python -m ruff check src/second_brain/fresh_verifier.py src/second_brain/cli.py \
  tests/test_fresh_verifier.py tests/test_cli.py
  → All checks passed
.venv\Scripts\python -m pyright src/second_brain/fresh_verifier.py src/second_brain/cli.py \
  tests/test_fresh_verifier.py tests/test_cli.py
  → 0 errors, 0 warnings, 0 informations
.venv\Scripts\python -m pytest tests/test_fresh_verifier.py tests/test_cli.py tests/test_verify.py -v
  → 50 passed
.venv\Scripts\python -m pytest -q   (full suite)
  → all passed, exit 0 (the R5-report's previously-flaky concurrency test
    passed clean this run, confirming it was transient, not caused by any
    change in this branch)
```

New tests: `tests/test_fresh_verifier.py` (12 — verdict parsing for
PASS/FAIL/PARTIAL/UNPARSEABLE including a case that must NOT match "pass"
inside ordinary prose, provenance null-vs-available handling,
end-to-end bundling), `tests/test_cli.py` (+3 — real verdict parsed via
CLI subprocess, UNPARSEABLE response never guessed, missing raw-response
file errors cleanly).

## 5. What a real live pilot still needs to do

This mechanism has never been exercised against an actual fresh model
session. A live pilot must: run `second_brain verify build-brief` for a
real session, send the resulting brief to a genuinely fresh session (no
implementation transcript) on whatever harness/model is chosen, capture
its raw output verbatim, and run `second_brain fresh-verifier record`
with the real provider/model/host/session-id/usage the host actually
reports. No verdict from that pass may be written by hand.
