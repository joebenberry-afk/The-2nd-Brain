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
  state without any chain check, unlike `replay`. It now verifies the chain
  before reading a payload and fails closed on non-contiguous seq, orphan
  parents, a broken chain, or failing object digests
  (`src/second_brain/ledger.py`, `rehydrate`).
  `test_rehydrate_refuses_tampered_chain` tampers a stored payload, asserts
  `hash_chain_ok` is false, and asserts rehydrate refuses with "hash chain
  broken"; the intact-ledger control still rehydrates. `[executed]`

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

The managed hook route is **closed**: every installed hook command binds the
absolute `System32` PowerShell plus an absolute runner path, the installers
refuse when that path is missing, and the Pester suite pins exactly that. `[read]`

Residual that remains true (**deferred, reclassified low**): bare
search-path resolution survives in non-hook subprocesses —
`envsteward.py:421` (bare `powershell`), `shutil.which("brainctl")` in the
Hermes adapter, install-time `& agy` / `& git`, and the `SECOND_BRAIN_PYTHON`
override honored by all three runners. Blast radius is the same user's own
`PATH` and environment; it is not a privilege boundary on this host. Named
remediation if wanted later: absolute-path resolution plus env pinning in those
subprocesses, tested the same way the hook route is.

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

Retained sinks that keep this live: a self-asserted green completion verdict
plus its `accuracy_gate` ledger row; an unauthenticated insert of `success=1`
rows into `model_skills_outcomes`/`model_profiles` under a caller-chosen
`model_id` (`verify.py:489-535`), whose consumers are the cross-model policy
display and `scripts/calibrate_risk.py`, which fits weights back into
`config/verification.toml`.

What the removal *did* change: the pre-removal `brainctl stop` consumed
`completion_allowed` from a gate file; in this candidate `stop` is an inert
refusal (`cli.py:4437-4447`). The strongest sink is gone, the finding is not.

Named remediation: an approval/verification channel the agent under governance
cannot author — signed approval, host-provided token, or operator-only
credential — plus a consumer change so unauthenticated verdicts cannot write
outcome or calibration data. That is architecture, not a candidate-local edit.
**Owner decision required: accept at the M00 release boundary or keep blocking.**

## 7. SEC-AUTH-02 — origin, grade and trusted-memory authority

**Reproduced, reachable, OPEN.** `cmd_remember` hard-codes
`origin_class="USER_AUTHORED"` (`cli.py:2145`) and passes `--grade` straight
through (choices `OBSERVED|TESTED|VERIFIED`, `cli.py:643-651`), with
`--evidence` optional. `_validate_origin` (`semantic.py:349-359`) then mints
`authority_ceiling="project_rule"` from unauthenticated input, and
`tests/test_cli.py:99-103` pins that contract as current behavior. `[read]`

Blast radius on a retained path: a model-visible packet can be admitted as
`CURRENT / HIGH` with a `project_rule` ceiling that outranks legitimate advisory
memories and exempts the item from the retrieval holdout
(`src/second_brain/autoinject.py:1214-1218`).

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

Results (raw event streams and the JSON payload are beside this file as
`native-noninterference-20260923.json`):

| Arm | task calls | spawned | refused | interference markers | final |
|---|---|---|---|---|---|
| `brain_off_single` | 1 | `ProbeSonic` | — | 0 | `RESULT ProbeSonic` |
| `brain_on_single` | 1 | `ProbeSonic` | — | 0 | `RESULT ProbeSonic` |
| `brain_off_batch` | 1 (2 tasks) | `ProbeA`, `ProbeB` | — | 0 | `RESULT 0` |
| `brain_on_batch` | 1 (2 tasks) | `ProbeA`, `ProbeB` | — | 0 | `RESULT 2` |
| `installed_build_single` (control) | 1 | — | `Probe` | 13 × `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` | refused |

Machine verdicts recorded by the probe, all true: single spawn succeeds; batch
spawn succeeds; no Brain settlement permission needed; no
`UNAUTHORIZED_COORDINATOR`; no worker-admission requirement; no budget
reservation prerequisite; no coordinator instruction injection; Brain-`on`
spawn semantics equal Brain-`off`; **probe sensitivity demonstrated**.

Sensitivity is the important half: the same prompt, model and probe against the
*pre-removal* build is refused with 13 settlement markers, so "zero markers" in
the candidate arms is a measurement, not an insensitive probe. The extractor is
itself self-tested (`--self-test`) against a known-refusal sample.

Brain activity is also confirmed, not assumed: the disposable home received 29
files during the Brain-`on` arms, including `db/brain.sqlite`, per-session
ledgers and `state/extension-runtime-ready.json`. A silently disabled extension
cannot produce that, so the clean result is not "Brain was off".

Not covered by this probe: `hub`/steering, workpool, cancellation/restart
timing, and model selection. They are native host surfaces that no retained
candidate file touches (the removal deleted the bridges that did), but this
probe did not exercise them, so they stay listed as observations rather than
proven rows.
