# Retained HIGH finding dispositions (2026-09-23)

**Subject:** the orchestration-free M00 candidate, branch
`brain/m00.3-producer-guard`, evidence base `4d74719`, plus the code changes
recorded in "Packet changes" below. **Not** a qualification verdict and **not**
a production claim: this file dispositions the findings the removal campaign
left open, so the register can say for each one whether it is fixed,
dispositioned, or still blocking.

## Method and evidence limits

Three read-only workers (`AuthzEvidenceScout`, `IntegrityEvidenceScout`,
`InstallHookEvidenceScout`) each audited one finding group against this tree
and returned `path:line` evidence, reachability, blast radius and a proposed
disposition. The driver re-read every load-bearing line itself and executed the
runnable parts (`npm audit`, the rehydrate tamper test, the installer Pester
suite, the native non-interference probe).

Evidence limits, stated rather than hidden:

- The workers had **no shell device**, so their claims are source readings, not
  executions. Claims that matter here were re-executed or re-read by the driver
  and are marked `[executed]` or `[read]` accordingly.
- "Not reachable on a retained path" means: no retained caller, route, test or
  documented operator command reaches it in this candidate. It is a statement
  about this tree, not a proof about future code.
- No arm of the native probe ran against live Brain state; every Brain-touching
  arm used a disposable `SECOND_BRAIN_HOME`.

## Disposition summary

| Finding | Disposition | Basis |
|---|---|---|
| Aggregate usage reader | `FIXED + regression-tested` (`4d74719`) | `M00-FINAL` §1 |
| SEC-INTEGRITY-01 | `NARROWED — clauses refuted, one residual fixed, one deferred` | §1 below |
| SEC-SKILL-01 / SB-PROMOTION-004 | `NARROWED — consumption-time clause refuted, approval-record authority deferred` | §2 |
| FSUPD-01 / FSPATH-03 | `NARROWED — literal defect retired with removal, install-route residuals fixed/deferred` | §3 |
| SEC-HOOK-02 | `NARROWED — hook route closed, non-hook resolution deferred as low-severity` | §4 |
| SEC-DEP-01 | `HIGH FIXED (dev-only); 2 dev-only moderates deferred with named remediation` | §5 |
| SEC-AUTH-01 | `OPEN — reproduced on retained paths; owner accept/defer decision required` | §6 |
| SEC-AUTH-02 | `OPEN — reproduced on retained paths; owner accept/defer decision required` | §7 |
| M00-NATIVE-ORCH-01 | `EXECUTED — 8/8 live verdicts true, probe sensitivity demonstrated` | §8 |

`SEC-AUTH-01` and `SEC-AUTH-02` remain blocking-until-decided. Nothing in this
packet converts them into passes.

## 1. SEC-INTEGRITY-01 — ledger chain, replay and migration integrity

Claim under test: the v3 chain hashes only payload JSON; `integrity()` trusts a
persisted watermark; `LedgerStore.replay` accepts `hash_chain_ok=false`.

All three clauses are **refuted** on this tree:

- The digest covers the full 16-column event envelope, not payload alone:
  `_ENVELOPE_COLUMNS` (`src/second_brain/ledger.py:92-97`) and
  `_envelope_digest` over `canonical_json(fields)` with the previous digest
  (`:101-106`); append-time hashing stores the same value (`:1104-1112`).
  `[read]`
- `integrity()` recomputes from genesis via `_envelope_seed(origin)` and never
  reads `last_verified_seq` — the docstring states the watermark is
  caller-writable data, not a trusted checkpoint (`:1190-1243`). `[read]`
- `replay` rejects a broken chain: `raise BrainError("replay rejected: hash
  chain broken")` (`:1470-1471`), alongside seq-contiguity, orphan-parent and
  object-digest refusals (`:1466-1474`). `[read]`

Residuals that remain true:

- **Unkeyed, self-anchored chain (deferred).** There is no key: a writer who can
  rewrite both the events and `ledger_meta` can recompute a consistent chain.
  Detection is therefore tamper-*evidence*, not tamper-*proof*. Closing this
  needs key custody — the same missing non-agent-controlled channel as
  SEC-AUTH-01 — and is **not** a candidate-local change.
- **Rehydration projection was unverified (fixed in this packet).**
  `LedgerRehydrator.rehydrate` projected durable event payloads into recovered
  state without any chain check, unlike `replay`. It now verifies inside a
  single snapshot — the same `BEGIN`/release pattern `replay` uses — and fails
  closed before projecting on non-contiguous seq, orphan parents, a broken
  chain, or failing object digests (`src/second_brain/ledger.py`, `rehydrate`).
  The snapshot matters: verification and projection must not be able to read
  different rows, because a concurrent writer committing between the check and
  the read would otherwise be projected as verified.
  `test_rehydrate_refuses_tampered_chain` tampers a stored payload, asserts
  `hash_chain_ok` is false, and asserts rehydrate refuses with "hash chain
  broken"; the intact-ledger control still rehydrates. `[executed]`
- **Independent reproduction of that fix** `[executed]`: the read-only verifier
  wrote its own scratch check (no test helpers, its own ledger, its own
  two-connection tamper) but had no execution device; the driver ran it with the
  candidate interpreter and the result was `intact: recovered original payload`
  and `tampered: rehydrate rejected: hash chain broken`, exit 0. The verifier's
  snippet as written left its writer connection open, which fails only on
  Windows temp cleanup — a defect in the snippet, not the product. The
  verify-then-project *interleaving* itself is not integration-tested; the code
  closes the window structurally rather than by test.

A legacy test shortcut was corrected as part of this: `test_rehydrate_levels_and_dedupe`
attached an artifact by rewriting the stored `artifact_sha256` column after
append, which contradicts the envelope digest. It now binds the artifact at
append time (`_ev(..., artifact_sha256=digest)`), which is what the tool flow
does, so the fixture stops describing a ledger the product cannot produce.
`[executed]`

## 2. SEC-SKILL-01 / SB-PROMOTION-004 — approved skill consumption

Claim under test: approved content is not bound to the delivered bytes at
consumption time.

**Refuted on every retained route.** `skills.approved_content`
(`src/second_brain/skills.py:82-108`) binds the body-text hash, lifecycle level
and all `artifact_binding` fields to `frontier.latest_review`; descriptors are
gated (`:126-127`) and `hydrate_plan` requires the exact body (`:301-309`). The
extension's own consumer path (`omp_adapter.build_plan` → gated `hydrate_plan`)
and the Hermes path use the same gate (`hermes_adapter.py:468-473`), and the TS
side binds with `approvedLeanText`. `[read]`

Residual that remains true (**deferred**): the approval *record* is an ordinary
same-user file written by `frontier_review` (`frontier.py:128-201`) with a
caller-supplied `reviewer` string, and the evaluation binding is
consistency-only (it does not require a passing evaluation to exist). So the
consumption gate is exact about *which bytes*, but the authority behind
"approved" is caller-authored — the SEC-AUTH-01 class. Named remediation: an
approval record that requires an evaluation result and is not writable by the
agent under governance; explicitly **not** attempted here.

## 3. FSUPD-01 / FSPATH-03 — extension install, copy and rollback

Literal defect (self-hashing a predictable mutable `%TEMP%` staging tree and
then using that same tree as the sealing source) is verified in sibling-worktree
copies of the retired `scripts/activate_omp_successor.py` and **absent from this
candidate** — retired with the file. `[read]`

Surviving route `scripts/install-prime-extension.ps1` +
`scripts/uninstall-prime-extension.ps1` (reachable, operator-invoked):

- Already defended: pre-install backup is byte-verified against the manifest it
  recorded (`install:66-76`); the stage is verified against the source manifest
  before the swap (`:97-100`); a failed replacement move restores the displaced
  extension (`:106-114`); rollback rejects missing, wrong-destination and
  tampered backups (`uninstall:63-123`).
- **Fixed in this packet:** the swap is now re-verified in the discovery path.
  The verified stage only describes staged bytes; after the move the installer
  re-manifests `$Target` and, on mismatch, removes the unverified install and
  restores the displaced previous extension before failing
  (`install:115-128`). The manifest SHA-256 it prints is now the hash of the
  verified *installed* tree. Two Pester cases cover the branch: a fresh install
  that must not be left in the discovery path, and a previous extension that
  must come back byte-identically.
- **Deferred (low):** `-SourceRoot`/`-ExtensionsDir` are caller-chosen with no
  containment check. The caller is the operator running the installer; a
  containment rule constrains the operator, not an attacker, so this is
  recorded rather than changed.
- **Deferred (blocked):** no protected approval binding. The deployment manifest
  tool refuses overwrite and says "not an approval" in its own output, which is
  the correct boundary; real approval needs the SEC-AUTH-01 channel.

## 4. SEC-HOOK-02 — hook and process executable trust

**Partly closed, and the residual is inside the hook route — corrected after
independent review.** Every installed hook command binds the absolute `System32`
PowerShell plus an absolute runner path, the installers refuse when that path is
missing, and the Pester suite pins exactly that. What that closes is the
`PATH`/cwd hijack of the *outer* command. `[read]`

It does **not** close the interpreter the hook executes: both retained hook
runners resolve Python from the environment —
`brainstem/adapters/claude-code/scripts/run-hook.ps1:21` (`SECOND_BRAIN_PYTHON`,
else `<brain home>\.venv\Scripts\python.exe`) invoked at `:46`, and
`brainstem/codex-hooks/run.ps1:25,36` the same way. So the residual is a
hook-execution path, not a non-hook one; an earlier draft of this record
classified it as non-hook and that was wrong. Both runners already clear
`PYTHONHOME`/`PYTHONPATH` before invoking, so the repo's interpreter-pollution
class is handled. `[read]`

Blast radius stays same-user: whoever can set that variable can already run code
as that user, and no privilege boundary is crossed on this host. Bounded
mitigation if wanted later: require an absolute, existing interpreter path and
prefer the home venv, tested the same way the outer command is pinned. Not
applied now because it does not close the channel and the runners are live
integration. The remaining bare-name resolutions (`envsteward.py:421` bare
`powershell`, `shutil.which("brainctl")`, install-time `& agy` / `& git`) are
separate, also same-user, and also deferred.

## 5. SEC-DEP-01 — dev dependency advisories

`[executed]` `npm audit --package-lock-only` in `brainstem/prime-extension`
before this packet: 3 advisories — `js-yaml` (HIGH, `>=4.0.0 <4.3.2`, locked
4.3.1), and `vitest` / `@vitest/mocker` (moderate, `>=2.1.0 <4.1.11`, locked
3.2.7). The extension declares **no runtime dependencies**; all three are
development-only (the lock marks them `dev`).

- **HIGH fixed:** `js-yaml` is a transitive dev dependency of
  `@eslint/eslintrc` (`^4.3.0`), so `npm update js-yaml` resolves it inside the
  existing range. Lock diff is 3 lines: 4.3.1 → 4.3.2. `[executed]` Audit after:
  `high: 0`.
- **Deferred with named remediation:** the two moderates are
  `@vitest/mocker` reachable only through `vitest@3.2.7`, a direct devDependency
  declared `^3.0.0`. The advisory fix is `vitest@5.0.1`, a semver-major
  toolchain jump that would invalidate the extension's recorded test evidence
  at freeze time. Remediation: upgrade `vitest` to `^5`, re-run
  `tsc`/`eslint`/`vitest`, and re-freeze. Dev-only exposure: a hostile import
  inside the test run, not a production path.

## 6. SEC-AUTH-01 — caller-authored verification and approval

**Reproduced, reachable, OPEN.** `brainctl verify gate`
(`src/second_brain/cli.py:1858-1948`) accepts `--action ACTION=passed`,
`--approval-state approved`, a caller-written `--verification-file`,
`--environment-file`, and caller-supplied hashes, and turns them into
`completion_allowed` (`src/second_brain/verify.py:445-465`). Freshness is
string inequality between two caller-supplied session ids plus caller hashes
compared against caller hashes (`fresh_verifier.py:91-140`). `[read]`

Retained sinks that keep this live, as independently reproduced: a
self-asserted green completion verdict plus its `accuracy_gate` ledger row, and
an unauthenticated insert of `success=1` rows into
`model_skills_outcomes`/`model_profiles` under a caller-chosen `model_id`
(`verify.py:489-539`). Exercised consumers after a self-authored green gate:
`models report` (outcomes=3, successes=2) and `models policy`, whose verification
list then included the caller's own `self-claimed-model` with success_rate 0.667.

**Correction (independent review refuted an earlier draft of this record).** That
draft also claimed `scripts/calibrate_risk.py` fits weights from these verdicts
back into `config/verification.toml`. That is wrong twice over, and the reviewer
showed it by execution: the calibrator returns `sample_count=0` and writes
default `[risk_weights] 1.0` because its collector samples session capsules and
agent-performance telemetry, not the gate ledger or model outcomes; and the
gate's own risk assessment reads `repo/config/verification.toml` ahead of
`$SECOND_BRAIN_HOME` (`risk.py:53-76`), while the calibrator writes the
disposable home's config. The calibration amplification is withdrawn; the
verdict-to-outcome sinks above are the retained blast radius.

What the removal *did* change: the pre-removal `brainctl stop` consumed
`completion_allowed` from a gate file; in this candidate `stop` exits 2 with
`ORCHESTRATION_REMOVED` (`cli.py:4435-4450`), reproduced. The strongest sink is
gone, the finding is not.

Named remediation: an approval/verification channel the agent under governance
cannot author — signed approval, host-provided token, or operator-only
credential — plus a consumer change so unauthenticated verdicts cannot write
outcome data. That is architecture, not a candidate-local edit.
**Owner decision required: accept at the M00 release boundary or keep blocking.**

## 7. SEC-AUTH-02 — origin, grade and trusted-memory authority

**Reproduced, reachable, OPEN.** `cmd_remember` hard-codes
`origin_class="USER_AUTHORED"` (`cli.py:2145`) and passes `--grade` straight
through (choices `OBSERVED|TESTED|VERIFIED`, `cli.py:643-651`), with
`--evidence` optional. `_validate_origin` (`semantic.py:349-359`) then mints
`authority_ceiling="project_rule"` from unauthenticated input, and
`tests/test_cli.py:99-103` pins that contract as current behavior. `[read]`

Blast radius on a retained path, independently reproduced: a `remember --grade
VERIFIED` with no evidence yields origin `USER_AUTHORED`, ceiling `project_rule`
and zero sources; its model-visible semantic and policy packets are admitted
`CURRENT / HIGH` with score 1.035 against an advisory comparator's 0.828, and the
forged item escapes the retrieval holdout (`autoinject.py:1214-1218`; the
reviewer's holdout probe reported the canary bypassed at epsilon=1 while an
isolated advisory still landed in `HOLDOUT`). Supplying `--evidence` captures a
git path and source SHA but does **not** change the grade, origin or ceiling —
so evidence is optional and decorative for authority purposes. `[executed]`

Named remediation: record the *claimed* grade separately from any authenticated
grade, and stop a caller-declared ceiling from both outranking and bypassing the
holdout. That ranking change is product behavior, so it is reported rather than
applied at freeze. **Owner decision required: accept or keep blocking.**

## 8. M00-NATIVE-ORCH-01 — executed native non-interference differential

`[executed]` `scripts/native_noninterference_probe.py` (new, explicitly
invoked, read-only toward live state) runs the real host CLI in print/JSON mode
over five arms: Brain-`off`/Brain-`on` × single spawn/batch spawn, plus a
sensitivity control that loads the **pre-removal build installed on this host**.
Every arm used `--no-session`, an empty temp project directory, and a disposable
`SECOND_BRAIN_HOME`; no arm could read or write live Brain state.

Results (each arm's full raw event stream is archived beside this file in
`native-noninterference-20260923/`, and the summary payload is
`native-noninterference-20260923.json`):

| Arm | task calls | spawned | refused | markers | brain-home files | final |
|---|---|---|---|---|---|---|
| `brain_off_single` | 1 | `ProbeSonic` | — | 0 | 0 | `RESULT ProbeSonic` |
| `brain_on_single` | 1 | `ProbeSonic` | — | 0 | 14 | `RESULT ProbeSonic` |
| `brain_off_batch` | 1 (2 tasks) | `ProbeA`, `ProbeB` | — | 0 | 0 | `RESULT 0` |
| `brain_on_batch` | 1 (2 tasks) | `ProbeA`, `ProbeB` | — | 0 | 18 | `RESULT 2` |
| `installed_build_single` (control) | 1 | — | `ProbeSonic` | 13 × `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` | 9 | `RESULT BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` |

Eight acceptance verdicts are recorded true (single spawn, batch spawn, no
settlement permission, no `UNAUTHORIZED_COORDINATOR`, no worker admission, no
budget reservation prerequisite, no coordinator instruction injection, Brain-on
spawn semantics equal Brain-off), and a **ninth recorded value**, the sensitivity
control, is true as well. Count them as eight plus sensitivity, not "9/9".

Sensitivity is the important half: the same prompt, model and probe against the
*pre-removal* build is refused with 13 settlement markers, so "zero markers" in
the candidate arms is a measurement, not an insensitive probe. The extractor is
itself self-tested (`--self-test`) against a known-refusal sample. `[executed]`

Brain activity is confirmed **per arm**, not in aggregate: each extension-enabled
arm now runs against its own disposable home and the payload records that arm's
inventory. The candidate arms wrote 14 and 18 files (including `db/brain.sqlite`,
per-session ledgers and `state/extension-runtime-ready.json`) while both
Brain-off arms wrote **0**, and the installed control wrote 9 into its own home.
An earlier draft measured one shared home after the whole loop, which could not
attribute activity to a candidate arm; the verifier caught that insufficiency and
it is now fixed in both the harness and this record. `[executed]`

Read the per-arm `final` column as the host's reply text, **not** as child
completion evidence: in these runs the task-tool end records carry
`results: []` with the subagents still `running` asynchronously, which is why the
batch arms report `RESULT 0` and `RESULT 2` differently. The probe proves spawn
acceptance and absence of interference markers; it does not prove child
completion, timing or cancellation.

Not covered by this probe: `hub`/steering, workpool, cancellation/restart
timing, and model selection. They are native host surfaces that no retained
candidate file touches (the removal deleted the bridges that did), but this
probe did not exercise them, so they stay listed as observations rather than
proven rows.

## 9. Independent review record

Two read-only workers ran against the packet after it was written.

**`AuthzReproducer` (security reviewer, executed).** Independently reproduced
both authorization findings in disposable homes and confirmed the subject bytes
(`git diff --name-status 968862a HEAD -- <authorization paths>` empty, the
candidate interpreter importing the candidate source). It reproduced a green
CRITICAL gate from entirely self-authored inputs (including
`human_approval_for_irreversible`) with ledger and outcome writes, exercised
`models report`/`models policy` afterwards, confirmed `stop` exits 2
`ORCHESTRATION_REMOVED`, and reproduced SEC-AUTH-02's optional evidence, forged
authority, ranking advantage and holdout bypass. It also **refuted** this
record's calibration claim, which §6 now withdraws with its reasoning. It agreed
both findings stay OPEN pending a non-agent-controlled channel.

**`PacketVerifier` (implementation verifier, read-only, no execution device).**
Its per-claim execution verdicts are `UNDEMONSTRATED` and must not be read as
confirmation — it could not run pytest, Pester, git or the probe. What it did
deliver: an independent reconciliation of the five archived raw streams against
the JSON summaries (one task call per arm, the reported names, four spawn
acknowledgements, one refusal, zero selected markers in candidate arms, 13
control-marker occurrences; all eight verdicts recomputed true); a judgement
that the corrected level-3 fixture still defends its artifact assertions
(`digest_verified`, exact excerpt, real object bytes) rather than having been
weakened to pass a new gate; a source-level judgement that the new Pester cases
would fail if the post-swap verification were removed, so they discriminate;
and three wording defects, all corrected here: the hook-route misclassification
(§4), the aggregate brain-activity attribution (§8, now per arm), and raw
streams living only in temp files (§8, now archived).

**What the driver changed because of review:** the rehydration snapshot (§1),
per-arm homes and stream archiving in the probe (§8), the hook-route
classification (§4), the calibration withdrawal (§6), the reproduced
SEC-AUTH-02 numbers (§7), and the wording of the verdict count (§8).

**Still not done, and why:** the verifier asked for a mutant/pre-change Pester
comparison to rule out an unrelated early failure satisfying its two new cases —
not run, because it needs the pre-packet installer materialised in scratch; the
source-level discriminator argument above is the current basis. And no second
party has executed the full suites: both reviewers lacked execution devices, so
every count in this record remains author-executed. That is an environment
limitation, reported rather than smoothed over.
