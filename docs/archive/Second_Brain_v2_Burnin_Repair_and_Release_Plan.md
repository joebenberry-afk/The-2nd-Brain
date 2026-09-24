# Second Brain v2 — Burn-In Repair, Hardening, and Release Plan

**Target baseline:** `4af64af` — `brain(release): complete v2 qualification gates and evidence`  
**Qualified branch:** `brain/v2-one-shot`  
**Current release status:** **V2-READY, NOT RELEASED**  
**Release tag:** **DO NOT create `v2.0.0` until burn-in gates pass**  
**Primary live harness:** Prime Agent 0.9.1  
**Secondary live harness:** Claude Code  
**Goal:** preserve the qualified v2 architecture while fixing integration, state/runtime identity, recovery, and usability defects discovered during real burn-in.

---

## 0. Mission / Agent Goal Prompt

> You are repairing and hardening the qualified Second Brain v2 implementation at commit `4af64af`.
>
> Preserve the existing v2 architecture and all proven v2 behavior unless a defect requires a narrowly scoped change. Do not redesign features that are already qualified. Treat the current repository, tests, qualification evidence, and actual runtime behavior as higher authority than stale documentation.
>
> The objective is to make Second Brain v2 safe and usable in real Prime Agent 0.9.1 and Claude Code sessions, with correct runtime/state identity, deterministic project attribution, complete backup/recovery, reliable AutoInject behavior, and observable version provenance.
>
> Every fix must be evidence-driven, test-first where practical, fail-open where the existing architecture requires it, token-efficient, reversible, and independently verifiable.
>
> Do not tag `v2.0.0` until the final production burn-in gate passes.

---

# 1. Non-Negotiable Invariants

1. **Freeze `4af64af` as the qualified pre-burn-in authority.**
   - Never rewrite or amend it.
   - All repairs land in new commits on a dedicated repair branch.
   - Preserve a direct rollback path to `4af64af`.

2. **Do not weaken existing v2 trust gates.**
   - Canonical source and verified current repo state outrank memory.
   - Contradictions must not silently strengthen memory.
   - Earned-memory gates, trust failure precedence, delivery state, and retrieval integrity remain intact.

3. **Do not collapse code identity and state identity.**
   - Second Brain runtime/code version and Brain state/home must become independently observable.
   - A state path must never silently select an unintended executable version.

4. **Do not tag `v2.0.0` during implementation.**
   - Release happens only after Prime + Claude burn-in and final requalification.

5. **Preserve token-efficiency as a hard cross-cutting requirement.**
   - Measure before/after token overhead.
   - Avoid broad preload.
   - Prefer targeted recall and compact context deltas.
   - Reject fixes that materially increase cost without demonstrated benefit.

6. **Every production-facing repair requires:**
   - regression test,
   - rollback method,
   - evidence artifact,
   - explicit acceptance criteria.

---

# 2. Phase 0 — Publish and Freeze the Exact Qualified v2 Baseline

## Goal

Make the exact qualified v2 implementation auditable and reproducible remotely before changing it.

## Tasks

### 0.1 Push the qualified branch

From:

`C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`

push:

```powershell
git push -u origin brain/v2-one-shot
```

### 0.2 Verify remote identity

Confirm:

- local HEAD = `4af64af`
- remote `origin/brain/v2-one-shot` = `4af64af`
- worktree is clean
- no release tag is created

### 0.3 Record baseline manifest

Create a pre-repair evidence record containing:

- commit SHA
- branch
- Python version
- package version
- DB schema version
- Prime Agent version
- installed Prime extension source SHA/fingerprint
- doctor result
- qualification verifier result
- test suite result
- existing v2 release report hash

Suggested artifact:

`outputs/reports/v2/burnin/00-qualified-baseline.json`

## Acceptance

- Exact commit `4af64af` is visible on GitHub.
- Remote and local SHAs match.
- Existing qualification still passes before repair work starts.
- `v2.0.0` does not exist.

---

# 3. Phase 1 — Audit the Exact v2 Code Before Modifying It

## Goal

Determine which GitHub-audit findings still exist at `4af64af` and avoid fixing defects that v2 already resolved.

## Audit Targets

### 1.1 Prime installer behavior

Inspect:

- `scripts/install-prime-extension.ps1`
- uninstall/rollback script
- deployment tests

Determine whether the installer derives extension source from:

- `$env:SECOND_BRAIN_HOME` — problematic
- `$PSScriptRoot` / repository source path — desired

### 1.2 Doctor identity checks

Inspect:

- `src/second_brain/doctor.py`
- path resolution
- version reporting
- runtime environment diagnostics

Confirm whether explicit `--home` can disagree with `SECOND_BRAIN_HOME` while doctor still passes.

### 1.3 Backup and restore coverage

Inspect:

- `src/second_brain/backup.py`
- canonical path definitions
- semantic memory storage
- skills, decisions, engrams, constitution, projects, and other durable stores

Classify every top-level Second Brain root as:

- canonical
- derived/rebuildable
- runtime/ephemeral
- external reference

### 1.4 Runtime vs state identity

Inspect every adapter/process-spawn path for assumptions of:

`<SECOND_BRAIN_HOME>\.venv\Scripts\python.exe`

Map whether runtime and state are independently configurable.

### 1.5 Project-ID resolution

Find all project attribution logic across:

- Python AutoInject
- Brainstem
- Prime extension
- worker-context bridge
- routing
- visibility
- telemetry mirror
- Claude adapter

Identify all places that derive project ID from path basename or other local heuristics rather than the canonical registry resolver.

### 1.6 AutoInject cache behavior

Inspect:

- cache key
- prompt/task identity
- TTL
- cross-process persistence
- concurrent reads/writes
- atomicity
- worker recovery behavior
- session reuse behavior

### 1.7 Extension lifecycle home resolution

Determine whether `SECOND_BRAIN_HOME` is:

- frozen at extension startup,
- resolved per event,
- partially dynamic.

### 1.8 Version/build identity

Inspect:

- `VERSION`
- `pyproject.toml`
- `src/second_brain/__init__.py`
- doctor output
- extension metadata
- qualification reports

### 1.9 Retrieval Intelligence 2.0 live wiring

Trace the exact path:

`Prime before_agent_start -> v2 AutoInject -> Retrieval Intelligence 2.0 -> trust gate -> packet -> Prime custom message`

Confirm:

- v2 scoring is actually used in Prime live path
- project ID passed to retrieval is canonical
- v2 memory corpus is available in the qualified state
- no legacy Phase-14-only gate is mistakenly treated as the active retrieval switch
- NO_INJECTION decisions expose enough bounded diagnostic evidence to explain why retrieval did not occur

## Output

Create:

`outputs/reports/v2/burnin/01-exact-v2-audit.md`

Every finding must be one of:

- CONFIRMED DEFECT
- ALREADY FIXED IN V2
- EXPECTED BEHAVIOR
- NEEDS LIVE PROOF

## Acceptance

No repair code begins until each previous audit finding has been classified against exact `4af64af`.

---

# 4. Phase 2 — Fix Installer Source / Runtime-State Coupling

## Priority

**P0**

## Problem

The installer must not use runtime state selection to decide which source tree to deploy.

## Target Behavior

The extension installer should:

- derive canonical source from the installer/repository location,
- use `SECOND_BRAIN_HOME` only as runtime state configuration,
- allow an explicit source override only through a dedicated parameter,
- back up the previous installed extension,
- verify the installed file set after copy.

## Likely Files

- `scripts/install-prime-extension.ps1`
- `scripts/uninstall-prime-extension.ps1`
- installer tests
- Prime extension README

## Implementation

1. Resolve repository root from `$PSScriptRoot`.
2. Add optional explicit `-SourceRoot` only for tests/controlled deployment.
3. Never use `SECOND_BRAIN_HOME` to locate `brainstem/prime-extension/src`.
4. Build a deterministic source manifest:
   - relative filename
   - SHA-256
5. Copy source.
6. Re-hash installed copy.
7. Fail installation if source and target manifests differ.
8. Preserve pre-install backup.
9. Print:
   - source repo path
   - source commit
   - target path
   - file count
   - manifest hash

## Tests

- Installer launched from another working directory.
- `SECOND_BRAIN_HOME` points to legacy state.
- Installer still installs v2 source.
- Missing source fails before deleting target.
- Partial copy does not report success.
- Rollback restores previous extension byte-for-byte.

## Acceptance

It becomes impossible to reproduce the burn-in mistake where a v2 installer command silently deploys the legacy extension.

---

# 5. Phase 3 — Make Doctor Detect Runtime/Home Identity Mismatch

## Priority

**P0**

## Problem

Doctor can validate one explicit `--home` while reporting a different `SECOND_BRAIN_HOME` as OK.

## Target Behavior

Doctor must make runtime identity ambiguity impossible to miss.

## Implementation

Add explicit checks for:

- resolved requested home
- environment home
- Python executable
- package source path
- Git repository root
- Git SHA
- DB path
- DB schema version
- adapter/runtime build identity where available

If explicit `--home` and `SECOND_BRAIN_HOME` differ:

- default doctor: **FAIL**
- optional diagnostic override may downgrade to WARN only if intentionally requested

Also verify:

`second_brain.__file__` belongs to the intended runtime source.

## Suggested Doctor Output

```text
Brain state home: ...
Env Brain home: ...
Runtime package: ...
Runtime repo SHA: ...
Database: ...
Schema: 21
Prime adapter build: ...
Identity coherence: PASS/FAIL
```

## Tests

- explicit home == env home -> PASS
- explicit home != env home -> FAIL
- Python imports Second Brain from another checkout -> FAIL
- DB belongs to selected home but Python runtime comes from another checkout -> FAIL
- clean coherent qualified state -> PASS

## Acceptance

A doctor PASS means the operator is actually testing the runtime/state combination they think they are testing.

---

# 6. Phase 4 — Make Backups Complete for Canonical Brain State

## Priority

**P0/P1**

## Problem

The existing backup format captures DB/config/constitution/projects but can omit canonical Markdown memory bodies and other durable knowledge.

## Goal

A backup must be capable of reconstructing all canonical Second Brain knowledge required for correct retrieval and operation.

## 6.1 Canonicality inventory

Create a checked-in canonicality manifest, for example:

`config/storage-classes.toml`

For every major root specify:

- `canonical`
- `derived`
- `runtime`
- `external_reference`

Example categories to audit carefully:

- `memory/semantic`
- `memory/episodic`
- `memory/procedural`
- `decisions`
- `skills/approved`
- `skills/principles`
- `engrams/active`
- `constitution`
- `projects`

## 6.2 Backup format v2

Introduce manifest format 2.

Manifest must include:

- backup format
- created time
- runtime version
- runtime Git SHA
- DB schema
- canonical path list
- per-file SHA-256
- DB snapshot SHA-256
- excluded derived/runtime categories with reason

## 6.3 Restore verification

Restore must verify:

- all expected canonical files exist
- hashes match
- DB references do not point to missing canonical files
- migrations are current
- trusted retrieval verifier passes against restored state

## Tests

- memory Markdown present after roundtrip
- versioned semantic memories preserved
- decisions preserved
- approved skills preserved if canonical
- restore rejects missing canonical body
- restore detects modified file/hash mismatch
- stale WAL/SHM cannot resurrect state
- restore remains transactional/reversible

## Acceptance

A backup/restore roundtrip produces a Brain with semantically equivalent canonical knowledge and passes trusted retrieval verification.

---

# 7. Phase 5 — Separate Runtime Identity from Brain State Identity

## Priority

**P1**

## Problem

Using `<SECOND_BRAIN_HOME>\.venv` couples state location to executable/code version.

## Goal

Support an explicit runtime executable independent of state home.

## Proposed Contract

- `SECOND_BRAIN_HOME` -> state/canonical Brain root
- `SECOND_BRAIN_PYTHON` -> Python executable
- optional `SECOND_BRAIN_RUNTIME_ROOT` -> source/runtime checkout for provenance

Precedence:

1. explicit adapter option
2. `SECOND_BRAIN_PYTHON`
3. compatibility fallback `<home>\.venv\Scripts\python.exe`

## Requirements

- preserve backward compatibility
- doctor reports which rung was used
- extension telemetry records runtime identity hash, not secrets/paths beyond allowed metadata
- all adapters use the same resolution helper

## Likely Files

- Prime extension spawn helpers
- Claude adapter scripts
- Python bootstrap
- doctor
- config documentation
- integration tests

## Tests

- state in directory A, runtime in directory B
- legacy layout still works
- invalid runtime executable fails open in adapters
- doctor identifies selected runtime
- Prime and Claude both use the same configured v2 runtime

## Acceptance

Changing state home can no longer silently downgrade/upgrade the Second Brain code version.

---

# 8. Phase 6 — Unify Canonical Project Resolution

## Priority

**P1**

## Problem

Different components may derive different project IDs from the same working directory.

## Goal

There must be exactly one project-resolution authority.

## Canonical Resolution Ladder

Reuse the v2 Python/Brainstem resolver:

1. explicit project
2. `.brain/project.toml`
3. registered repository containment
4. registered git remote match
5. environment override
6. unresolved/default safe fallback

## Implementation

Create one reusable Brainstem command/API returning:

```json
{
  "project_id": "...",
  "resolution": "manifest|registry_path|git_remote|env|default",
  "repo_root": "...",
  "confidence": "..."
}
```

All Prime bridges must call or consume that canonical result.

Remove basename-derived project ID behavior from production decisions.

## Surfaces to Update

- AutoInject
- routing
- visibility
- worker-context packet
- worker-result bridge
- telemetry/ledger attribution
- handoff envelopes
- Claude Code adapter
- future harness adapters

## Tests

Include:

- main repo
- Git worktree
- nested subdirectory
- two repos with same folder basename
- renamed worktree
- registered remote
- missing manifest
- unresolved project
- wrong project memory exclusion

## Acceptance

For one working directory, every Second Brain subsystem reports the same project ID.

---

# 9. Phase 7 — Harden AutoInject Cache Correctness and Concurrency

## Priority

**P1**

## 7.1 Correct cache identity

Replace session-only + prompt-prefix correctness with a canonical task hash.

Recommended key:

`session_id + normalized_task_sha256 + project_id + mode + relevant retrieval-config fingerprint`

Normalization must remove only known host-added volatile fields. Do not fuzzy-normalize semantic user text.

## 7.2 Cross-process safety

Replace the shared whole-file rewrite design.

Preferred order:

1. SQLite-backed bounded cache, or
2. per-session cache files with locking and atomic replace.

Avoid one global `.tmp` file.

## 7.3 Cache provenance

Cache entry should store:

- task SHA
- project ID
- retrieval config fingerprint
- packet hash
- delivery ID
- created time
- expiry
- runtime build identity

## 7.4 Invalidation

Invalidate on:

- different task hash
- project change
- config/retrieval-policy change
- memory corpus generation change if available
- TTL expiry
- incompatible runtime build

## Tests

- same task repeated by Prime -> one retrieval, stable packet
- different task with same first 128 chars -> no stale packet
- concurrent Prime workers -> no lost/corrupt cache
- recovered worker -> deterministic cache hit
- project changes inside same session -> no cross-project reuse
- expired entry -> recompute
- corrupted cache -> fail open

## Acceptance

The cache can never return a packet merely because two tasks share a prefix or because concurrent workers raced on one JSON file.

---

# 10. Phase 8 — Define Extension Home Lifecycle Semantics

## Priority

**P2**

## Problem

Configuration helpers may read environment dynamically while the extension factory caches home at startup.

## Choose and Document One Model

### Recommended: frozen-per-extension-lifecycle

At extension startup:

- resolve Brain home once
- resolve runtime once
- compute identity fingerprint
- emit one `SECOND_BRAIN_RUNTIME_READY` record

If environment changes later:

- do not silently retarget
- require `/reload` or restart
- doctor/status should say extension runtime is frozen to X

This is safer than partially dynamic retargeting.

## Tests

- env changes mid-session do not silently switch DB
- reload picks up new home
- daemon worker recovery preserves intended home
- runtime-ready identity emitted exactly once per lifecycle

## Acceptance

Operators always know which Brain instance the active Prime extension is using.

---

# 11. Phase 9 — Fix Runtime Version and Build Identity

## Priority

**P2**

## Goal

Stop reporting `0.1.0` for qualified v2.

## Implement a Build Identity

At minimum expose:

- semantic version
- Git SHA
- dirty/clean status
- DB schema version
- adapter build fingerprint
- qualification baseline SHA

Before final release use a prerelease value such as:

`2.0.0-rc.1+<sha>`

Do not use the final `2.0.0` tag until burn-in passes.

## Surfaces

- `VERSION`
- `pyproject.toml`
- `__version__`
- `brainctl --version`
- doctor
- status
- Prime runtime-ready telemetry
- qualification report

## Tests

- all version surfaces agree
- dirty runtime is visible
- wrong adapter build is detectable
- DB schema mismatch is visible

## Acceptance

A single doctor/status output can prove exactly which Second Brain build, adapter, and schema are running.

---

# 12. Phase 10 — Refresh Stale Documentation and Deployment Status

## Priority

**P2**

## Goal

Remove historical statements that can be mistaken for current runtime behavior.

## Tasks

- Update Prime extension README.
- Separate:
  - architecture documentation
  - current deployment state
  - historical notes
- Generate deployment status from runtime evidence where practical.
- Clearly distinguish:
  - legacy Phase-14 recall gate
  - v2 AutoInject active path
  - Retrieval Intelligence 2.0
- Document process-local vs persistent environment variables.
- Document `/reload` requirements.
- Document state/runtime separation.

## Acceptance

A future operator cannot infer an obsolete "recall default off" behavior when v2 AutoInject is active.

---

# 13. Phase 11 — Retrieval Intelligence 2.0 Live-Path Audit and Repair

## Priority

**P1 — execute after identity/project fixes**

## Goal

Prove that the v2 retrieval engine actually delivers useful project-specific memory during real Prime sessions.

## 11.1 Trace one request end-to-end

For a controlled prompt, record:

- task SHA
- resolved project ID
- candidate IDs
- refusal counts
- ranking components
- selected IDs
- packet hash
- delivery ID
- Prime model-visible confirmation

No raw private prompt text should be added to telemetry beyond existing policy.

## 11.2 Test known durable-memory query

Use a question whose expected durable answer is already known to exist in the canonical corpus.

Examples should include:

- token-efficiency priority
- harness-independent memory
- project-specific implementation decision

## 11.3 Diagnose NO_INJECTION

A NO_INJECTION event must be explainable with bounded reason codes such as:

- no candidates
- project mismatch
- trust failure
- delivery dedupe
- token budget
- contradiction
- stale/invalid manifest

## 11.4 Verify Retrieval Intelligence 2.0 scoring

Confirm the live path uses the v2 components:

- relevance
- authority
- scope
- freshness
- contradiction
- activation need
- diversity
- final score
- MMR selection

## Acceptance

A substantive query that should benefit from durable memory causes the correct trusted memory to become model-visible, while irrelevant prompts remain quiet.

---

# 14. Phase 12 — Regression and Qualification Test Campaign

## Required Test Layers

### A. Unit

Every repaired component.

### B. Integration

- installer
- doctor identity
- backup/restore
- runtime/state separation
- project resolver
- AutoInject cache
- Prime extension
- Claude hook
- retrieval delivery

### C. Migration

Fresh v1 -> v2 migrations 1–21 and restored backup migration paths.

### D. Trust

Re-run all existing TrustFailureCode coverage and precedence tests.

### E. Performance / Token

Measure:

- cold retrieval
- warm retrieval
- AutoInject latency
- packet tokens
- total added context
- cache-hit savings
- Prime turn overhead

Do not invent new performance thresholds just to pass the release. Compare against qualified baseline and document regressions.

### F. Full qualification

Run the existing independent verifier and all P8 gates again.

## Acceptance

No existing qualified v2 invariant regresses.

---

# 15. Phase 13 — Prime Agent 0.9.1 Production Burn-In

## Environment

Use:

- Prime Agent 0.9.1
- exact repaired v2 runtime
- qualified/migrated v2 state
- exact repaired v2 Prime extension
- explicit coherent runtime/home identity

## Burn-In Scenarios

1. Fresh-session AutoInject.
2. Quiet prompt where no memory is needed.
3. Substantive prompt where durable memory should be recalled.
4. Natural user correction.
5. Verify correction retention.
6. Worker delegation.
7. Worker result return.
8. Compaction.
9. Resume after compaction.
10. Process/worker recovery.
11. Restart Prime.
12. Cross-turn cache reuse.
13. Different task with similar prefix.
14. Worktree project attribution.
15. Wrong-project memory isolation.
16. Ordinary real development work.

## Metrics

Track:

- re-explanation required
- useful retrieval rate
- bad retrieval
- missed retrieval
- cross-project leakage
- correction retention
- repeated reasoning
- token overhead
- retrieval latency
- cache hit correctness
- recovery correctness
- false automation
- unexplained/annoying Brain behavior

## Pass Condition

No release-blocking correctness defect across multiple real sessions.

---

# 16. Phase 14 — Claude Code Cross-Harness Burn-In

## Goal

Prove the same canonical Brain can continue work across Prime and Claude without hidden state divergence.

## Scenarios

1. Prime session establishes current task state.
2. Create bounded handoff.
3. Claude resumes.
4. Claude performs work.
5. PreCompact/compaction durability.
6. Claude correction/learning event.
7. Return to Prime.
8. Verify continuity.
9. Verify project ID and memory authority remain identical.

## Acceptance

- no duplicate canonical memory
- no harness-specific conflicting truth
- no stale handoff dominating current repo state
- bounded context transfer
- continuity survives restart

---

# 17. Phase 15 — Final Release Gate

## Required Evidence

Before tagging:

- exact repaired commit SHA
- clean Git state
- doctor PASS with coherent identities
- all migrations current
- full test suite PASS
- independent verifier PASS
- backup/restore roundtrip PASS
- Prime 0.9.1 burn-in PASS
- Claude Code burn-in PASS
- cross-harness continuity PASS
- retrieval usability PASS
- token/runtime comparison recorded
- no unresolved P0/P1 defect
- rollback tested

## Release Decision

### PASS

Create annotated tag:

`v2.0.0`

only after all gates pass.

### HOLD

Do not tag if:

- identity ambiguity remains
- project attribution differs across components
- backup is incomplete
- trusted retrieval fails expected live cases
- cross-process cache can serve stale packets
- Prime/Claude state diverges
- token overhead materially regresses without justification
- any trust invariant regresses

---

# 18. Recommended Commit Sequence

Keep repairs reviewable and reversible.

1. `chore(v2): publish qualified burn-in baseline evidence`
2. `fix(installer): decouple extension source from brain state home`
3. `fix(doctor): fail on runtime and state identity mismatch`
4. `fix(backup): snapshot complete canonical brain state`
5. `feat(runtime): separate brain state home from python runtime`
6. `fix(project): centralize canonical project resolution`
7. `fix(autoinject): use strong task identity for emit cache`
8. `fix(autoinject): make cross-process cache concurrency safe`
9. `fix(extension): freeze and expose brain home per lifecycle`
10. `chore(version): expose v2 build and schema identity`
11. `docs(v2): refresh live retrieval and deployment documentation`
12. `fix(retrieval): repair any exact-v2 live-path defects found`
13. `test(v2): add Prime 0.9.1 and Claude burn-in regressions`
14. `brain(release): requalify v2 after production burn-in`

Do not squash away evidence-bearing repair boundaries until after release review.

---

# 19. Rollback Strategy

At every phase retain:

- `4af64af` qualified baseline
- pre-install Prime extension backup
- pre-repair Brain-state backup
- repair-branch commit boundary
- documented revert command/path

If a live burn-in repair causes instability:

1. stop the harness,
2. restore previous global adapter,
3. reset `SECOND_BRAIN_HOME` / runtime configuration,
4. return to known-good state,
5. record incident evidence,
6. reproduce in isolated test state before retrying.

Never repair the production Brain by manually editing SQLite or canonical memory files during burn-in.

---

# 20. Definition of Done

Second Brain v2 is ready to tag only when:

- the exact runtime is identifiable,
- the exact state is identifiable,
- the exact adapter is identifiable,
- project scope is deterministic,
- backups preserve all canonical knowledge,
- AutoInject never serves stale cross-task packets,
- retrieval is quiet when unnecessary and useful when needed,
- Prime 0.9.1 works across multiple real sessions,
- Claude Code can continue the same work safely,
- compaction/restart/recovery preserve continuity,
- token overhead remains controlled,
- all existing v2 trust and qualification gates remain green,
- and there are no unresolved release-blocking usability defects.

Until then, the correct status remains:

**V2-READY — PRODUCTION BURN-IN / REPAIR IN PROGRESS — NOT YET v2.0.0**
