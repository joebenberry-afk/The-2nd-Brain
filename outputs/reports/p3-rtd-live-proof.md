# P3-F — RTD Live Mechanism Proof

Plan §11 (RTD), §30 (deferred activation when the tool surface does not exist).
Branch `brain/p3-lean-code`. The Prime harness has ZERO `tool=bash` events
(verified: 542 telemetry files scanned, every `tool_call` is `ipython` — the
21,269-event observation holds), so RTD activation is DEFERRED per plan §30
and the mechanism is proven LIVE through the extension's exact code path on
REAL captured bash output. Final state: `[rtd] enabled = false` (shadow).

## 1. Live mechanism roundtrip (extension's exact path: src/rtd.ts runRtd +
cliRtdPreserver -> `second_brain artifact store` + `expand`, repo venv python,
env-sanitized, driven via vite-node against the vitest-tested exports)

Real captures (bash output captured via the harness's %%bash into files):

| capture | real command | raw chars | threshold |
|---|---|---|---|
| pytest_fail.txt | `python -m pytest <demo> -v --tb=long` (12 failing tests, long diffs; exit 1) | 11,252 | 8000 (default) |
| git_log.txt | `git log -p -n 60` on the repo | 4,056,541 | 8000 (default) |

Results per case (all through `cliRtdPreserver` -> real CLI, temp brain home):

| check | pytest-fail | git-log-p | pytest-fail-error (isError=true) |
|---|---|---|---|
| eligibility (rtdEligibility bash+pytest/git) | ok | ok | ok |
| artifact handle sha256 == TS sha256 of raw bytes | TRUE | TRUE | TRUE |
| `artifact expand` byte-identical (preserver verify) | TRUE | TRUE | TRUE |
| CLI-level recovery: `artifact expand <sha> > rec; cmp -s orig rec` | CMP=0 (byte-identical) | CMP=0 | (same artifact) |
| distilled record | true | true | true |
| original/visible/saved chars | 11252 / 2608 / 8644 | 4056541 / 2612 / 4053929 | 11252 / 2607 / 8645 |
| visible % of original | 23% | 0.06% | 23% |
| reduction >= 50% | YES | YES | YES |
| patch returned ({content:[text]}) | YES | YES | YES |
| command_class / error_status | pytest / false | git / false | pytest / true |

Block determinism + failure evidence (pytest case): the distilled block
contains the `=== FAILURES ===` section, `FAILING TESTS (12)` with names
(e.g. test_failing_7), the `12 failed, 1 passed in 2.22s` summary, the
omitted-chars marker, and the exact reopen instructions; two consecutive
distillations are byte-identical (deterministic, no LLM).

Block metadata (pytest case): `[SECOND_BRAIN_RTD] original_chars=11252
visible_chars=2000 saved_chars=9252 lines=278 sha256=ce3e0484…
artifact=[brain-artifact:sha256:ce3e0484…] command=pytest error_status=false
truncated=true` + head/tail + reopen pointer.

Error-conservative path: the failing-command capture (exit 1) driven with
isError=true records error_status=true, keeps the longer tail (15%/85% split),
and the artifact is equally recoverable.

## 2. Zero false triggers (live)

- My session telemetry (01a0094d…): 395 tool_call events, 100% `ipython`;
  0 rtd_shadow records; no `[SECOND_BRAIN_RTD]` content anywhere.
- Global scan: 542 telemetry files, 0 non-ipython tool_calls, 0 rtd_shadow
  records, 0 substitution blocks — no false trigger has ever fired.
- Code path proof: `rtdEligibility("ipython", {code}) === "tool"` and
  `runRtd` with an ipython event returns record=null, patch=undefined even
  with enabled=true (eligibility short-circuits before any preservation).

## 3. Rollback proof (per-event config read)

- `config/context.toml [rtd] enabled = true` (temp home) -> loadRtdConfig
  enabled=true -> runRtd produces the distilled record
  (distilled=true, artifact_ref set) and the patch.
- Flip the SAME file to `enabled = false` -> loadRtdConfig enabled=false ->
  the next runRtd is SHADOW-ONLY: rtd_shadow record (reason ok, NO distilled
  fields, NO artifact_ref), no patch. No redeploy needed for the flip.
- FINAL STATE: repo config/context.toml `[rtd] enabled = false` (deferred).

## 4. Incident found + fixed during the proof (byte-exact preservation)

The first roundtrip FAILED the sha cross-check for multi-line Windows
captures: Python's text-mode `sys.stdin.read()` applies universal-newline
translation (CRLF -> LF), so the stored bytes differed from the node-side
hash of the exact string the host sent — preservation failed (fail-open
worked: original content returned, distilled=false) but distillation could
NEVER trigger on this machine (bash output is CRLF). Fix (smallest correct):
`src/second_brain/artifacts.py` gained `store_bytes(home, data, …)` and
`cli.py cmd_artifact store` now reads `sys.stdin.buffer.read()` (exact bytes)
instead of text. `tests/test_artifacts.py` 25/25 pass. After the fix the
roundtrip is byte-identical (sha match + cmp 0 on both captures).

## 5. Verdict

- **Mechanism proven LIVE**: the extension's exact RTD path preserves raw
  results byte-exactly (sha256 content-addressed, expand-verified, cmp 0),
  replaces only after recoverability is proven, distills deterministically
  with visible <= 50% of original on triggered cases, keeps failure evidence,
  handles error results conservatively, never touches ipython/binary content,
  and rolls back via the config flip.
- **ACTIVATION DEFERRED (plan §30)**: the bash-tool surface does not exist in
  this Prime harness (100% ipython tool surface). RTD stays SHADOW
  (`enabled = false`). Eligibility is NOT generalized to ipython (interactive
  session evidence must not be distilled; plan §11.2 stays bash-only).
- **Lean Code promotion does not require active RTD** (§20.3 lists RTD's
  visible-byte criterion as one of several P3 levers; the Lean candidate
  gate already passed on kernel behavior + economics without RTD).

## 6. Changed files (uncommitted; parent commits)

- src/second_brain/artifacts.py (+store_bytes, byte-exact preservation)
- src/second_brain/cli.py (artifact store reads stdin as exact bytes)
- (rtd.ts/config.ts/index.ts/SCHEMA.md/tests + context.toml docs from the
  P3-F implementation job — unchanged by this proof)
- outputs/reports/p3-rtd-live-proof.md (this report)
