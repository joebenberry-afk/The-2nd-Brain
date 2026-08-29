# v1.0 P4 Canonical Integration Design

- **Date:** 2026-08-29
- **Status:** Approved design; implementation pending
- **Scope:** Complete and qualify frozen v1 P4, then freeze/tag v1.0.0
- **Authority:** `C:/Users/assas/Downloads/GPTs plans/Second_Brain_v1_to_v2_Luna_Master_Plan.md`

## Problem

The current authoritative status ledger proves P0.1 through P3.17 and marks P4.1 through P4.5 not qualified. The existing P4 modules exercise isolated APIs but do not provide the required end-to-end integration or release evidence:

- `goals.py` and `fingerprints.py` create sidecar SQLite databases outside the primary backup path.
- `heartbeat.py` exposes a direct health probe but has no event-driven scheduling guard, persisted run record, or telemetry integration.
- Prime already observes Radar at shutdown, but Radar candidates do not become P4 fingerprints.
- Existing Frontier, Immune, Plasticity, SkillForge, and counterfactual APIs are not composed into a distinct P4 controlled-optimization lifecycle.
- The Python telemetry registry predates many emitted kinds and reports live historical data as invalid even when the records use documented additive schemas.

The repository must reach a known-good v1 baseline without starting V2-A or creating parallel canonical systems.

## Non-goals and invariants

1. P4 does not implement trusted retrieval, freshness replacement, low-friction memory I/O, earned memory, new vector search, or other V2 behavior.
2. The primary Brain database, existing JSONL telemetry, existing Radar, existing lifecycle gates, and existing Prime adapter remain authoritative.
3. All routine P4 computation is deterministic and local. No model call is used for hashing, ranking, scheduling, bookkeeping, health checks, or evidence validation.
4. No always-on daemon, hosted service, remote telemetry sink, autonomous Constitution edit, or destructive cleanup is introduced.
5. Prompts, message content, tool payloads, and chain-of-thought remain absent from persisted telemetry and P4 state.
6. Existing P0-P3 behavior is preserved unless a verified regression blocks release.
7. Historical root telemetry is not rewritten. Fresh qualification homes must validate clean; preexisting root issues remain explicitly reported.
8. The 72 untracked user memory files are preserved and are not added to the release commit.

## Rejected approaches

### Sidecar-only patch

Keep `state/goals/goals.sqlite` and `state/fingerprints/fingerprints.sqlite`, add tests, and call the existing APIs from Prime. This is smaller but violates the no-parallel-store rule and loses P4 state in the existing backup/restore contract.

### V2-first retrofit

Start with trusted retrieval and retrofit P4 later. The master plan makes P4 the v1 release boundary and forbids V2 implementation before a frozen v1 baseline.

### Chosen approach: canonical P4 integration

Move P4 durable operational records into the primary DB, connect them to existing lifecycle hooks and telemetry, and compose existing governance primitives behind a small optimization coordinator. Qualification and an independent verifier are release artifacts, not self-certification.

## Data and persistence

### Migration 0010

Add one idempotent primary migration under `src/second_brain/migrations/0010_p4_operations.sql`:

- `goals`: existing goal fields plus status constraints and timestamps;
- `goal_events`: append-only lifecycle/milestone audit records with a foreign key to `goals`;
- `bottleneck_fingerprints`: scoped deterministic fingerprints, impact, occurrence count, timestamps, bounded evidence references, and metadata;
- `heartbeat_state`: singleton last-run state used by the atomic due guard;
- `heartbeat_runs`: bounded run outcomes and issue codes for operational read-back; retain the latest 256 runs deterministically.

`GoalStore` and `BottleneckFingerprintStore` call the normal migration/connect path and no longer open private SQLite files. Primary DB backup therefore includes these records automatically. The current repository has no live P4 sidecar to migrate; preflight must refuse silent data loss if a non-empty legacy sidecar is encountered.

### Goal lifecycle

Preserve the current public methods and add validated atomic operations for:

```text
PENDING -> ACTIVE -> BLOCKED -> ACTIVE
                    |          |
                    v          v
                COMPLETED   ABANDONED
```

Rules:

- creation remains deterministic and local;
- transitions and milestone completion are transactional and append `goal_events`;
- milestone completion requires a non-empty evidence reference and is idempotent;
- an empty milestone list never auto-completes a goal;
- completed and abandoned goals are terminal;
- blocker notes are bounded operational text, not prompts or payloads;
- list/get operations expose current state and bounded evidence only.

## P4.2 event-driven heartbeat

There is no daemon or timer thread. `HeartbeatCoordinator.run_if_due(event, session_id, repo_dir)` is called from lifecycle events and uses an atomic primary-DB reservation:

- `off`: do not probe or mutate;
- `shadow`: inspect DB integrity, cache state, and repository state without maintenance mutation;
- `active`: perform the same checks and prune only expired ActionCache entries.

The persisted interval guard prevents duplicate work from repeated hooks or concurrent adapter processes. A reserved run that crashes is suppressed until the next interval rather than retried in a loop. `session_shutdown` may force one final bounded run.

The Prime adapter invokes the coordinator asynchronously at `session_start` and due `turn_start`, and synchronously at final `session_shutdown` so the result survives worker teardown. Other harnesses use the CLI path. The existing subprocess timeout and environment cleanup rules remain in force.

Each run emits one privacy-safe `heartbeat_pulse` record through the existing telemetry store containing only mode, lifecycle event, due/skipped state, health flags, cache count, dirty-tree flag, bounded issue codes, measured local latency, and `model_tokens_used: 0`. That zero is a measured invariant of this coordinator (there is no model-call path), not a fallback for missing provider economics; provider token counters remain nullable. Probe failures are visible; they are never silently discarded.

## P4.3 operational telemetry

### Registry and schema

Update `src/second_brain/telemetry.py` to register all kinds currently emitted by the repository, including the v3 OMP kinds, while retaining strict version checks. Add P4 kinds:

- `heartbeat_pulse`;
- `bottleneck_fingerprint`;
- `optimization_proposal`;
- `optimization_evaluation`;
- `optimization_activation`;
- `optimization_rollback`.

Add the corresponding privacy and field contracts to `brainstem/telemetry/SCHEMA.md` and the Prime sensor builders. P4 records use v2 unless the existing provider-economics/OMP contract requires v3.

### Deterministic report

Extend the existing `telemetry.report()` output, without removing existing keys, with an operational section grouped by available session/role/model/harness identity:

- provider-reported input/output/total/cache tokens, preserving null when absent;
- tool calls and result bytes;
- observable file reads and rereads;
- compactions and context peaks;
- driver/worker/background activity;
- tool/extension/verification errors;
- heartbeat, fingerprint, proposal, activation, rollback counts;
- measured wall time and validation issue counts.

No inferred token zeroes, raw payloads, prompt text, or model judgments are added. The report labels measured values separately from unavailable values.

## P4.4 Radar-backed fingerprints

Extend `ImprovementRadar.observe_session()` rather than adding a second detector:

1. analyze the canonical session stream using existing deterministic Radar rules;
2. preserve Radar candidate evidence hashes and stale-evidence rejection;
3. map alerts to the existing bounded fingerprint categories;
4. record a scoped, deduplicated fingerprint with category, signal hash, impact, counts, mitigation, project scope, and telemetry references;
5. return the fingerprint result to the Prime bridge and append a `bottleneck_fingerprint` telemetry record.

Descriptions are fixed/bounded category summaries. Evidence references carry hashes, line references, counts, and timestamps only. No prompt, command payload, or raw tool output is persisted. Cross-project signals remain scoped unless an explicit existing policy permits transfer.

## P4.5 governed self-optimization

Add a thin `optimization.py` coordinator; it is an orchestration layer over existing authorities, not a new policy engine or database.

Lifecycle:

```text
Radar signal
  -> shadow proposal
  -> real paired evaluation / existing SkillForge evaluation
  -> Frontier review
  -> explicit allowlisted canary or activation
  -> Immune rollback guard
  -> explicit Plasticity utility record from verified evidence
```

Mode semantics:

- `off`: no proposal or mutation;
- `shadow`: record proposal and evaluation only;
- `active`: permit preparation/canary/activation only when current evidence, quality, economics, Frontier approval, and rollback binding all pass.

Activation is an explicit CLI/adapter action. Existing `credit.counterfactual_result()` supplies same-starting-state observed comparisons where applicable; existing `skillforge.record_evaluation()` remains the skill-specific evidence writer; `frontier.gate_check()` is the approval authority; `promotion.promote()` performs skill lifecycle mutation; `immune.register_policy()` and `immune.rollback()` protect the exact allowlisted artifact; `plasticity.utility_update()` records only caller-supplied verified utility evidence.

The coordinator refuses stale Radar evidence, changed intervention hashes, missing verification/regression evidence, unapproved Frontier state, unsafe paths, constitutional targets, and missing rollback guards. It never promotes from one success, never auto-approves, and never jumps from off to active.

## Prime integration

Add one bounded P4 bridge around the existing `ledger-mirror`/Prime adapter conventions rather than a parallel transport:

- clean `PYTHONHOME`/`PYTHONPATH` and set `SECOND_BRAIN_HOME`;
- call one deterministic P4 CLI operation per due lifecycle event;
- use asynchronous fail-open calls for non-final hooks;
- use a synchronous final call at shutdown;
- append returned heartbeat/fingerprint/optimization metadata with the existing `TelemetryStore`;
- append bounded `extension_error` records on bridge failure without blocking the host.

Existing Radar shutdown wiring remains the integration point; it gains fingerprint output instead of a duplicate shutdown observer. Adapter-neutral CLI commands make the same operations available when deep Prime hooks are unavailable.

## Qualification and independent verification

Add a fresh-home qualification runner and a separate read-back verifier. The runner uses the real repository/project registration and actual command/test outputs; it does not hard-code token counts, model identities, or success claims. Synthetic failure injection is labeled as resilience evidence, not dogfood.

The qualification matrix must cover:

1. fresh session;
2. resumed session;
3. compacted session;
4. cross-session continuity;
5. harness isolation;
6. harness switch;
7. driver/worker workflow;
8. failed worker;
9. malformed/corrupt memory or ledger input;
10. stale state;
11. token pressure;
12. cache-sensitive behavior;
13. long-running goal;
14. Brain OFF comparison;
15. Brain ON comparison;
16. recovery/rollback;
17. security/trust boundary;
18. genuine Second Brain repository dogfood.

For each scenario capture observable task result, verification, corrections/rework when present, provider/cache economics when exposed, injection/context/tool/file metrics, compactions, worker/driver/background activity, wall time, errors, and rollback behavior. Missing counters remain null.

The verifier independently recomputes artifact hashes, checks source/Git identity, opens the fresh primary DB, runs integrity and migration idempotency checks, validates telemetry against the current registry, exercises backup/restore, checks stale-evidence refusal and rollback containment, and rejects any manifest with fabricated or inconsistent fields.

## Tests and release gates

Python changes require focused tests, then `ruff check`, `pyright`, and full pytest with the repository's sanitized Python environment. TypeScript changes require focused Vitest coverage, ESLint, and `tsc --noEmit`. Required behavior tests include:

- goal persistence/reopen, all legal/illegal transitions, idempotent milestones, malformed state, and backup/restore;
- atomic heartbeat due suppression, mode semantics, zero model calls, visible failures, and recovery;
- complete telemetry kind/version validation and operational counters;
- Radar-to-fingerprint deduplication, scoping, privacy, and stale evidence;
- optimization shadow/approval/economics/activation/rollback refusal paths;
- Prime bridge async/final behavior and fail-open handling;
- fresh install, reopen, migration idempotency, and clean qualification telemetry.

Release sequence:

1. implement P4 against this design;
2. pass focused and full deterministic checks;
3. run fresh-home qualification;
4. run independent verifier/read-back;
5. fix blockers and rerun affected scenarios;
6. update the authoritative current status ledger and release report with raw evidence links;
7. document migration/backup/restore and v1 economics baseline;
8. commit and tag the known-good `v1.0.0` baseline;
9. do not begin V2-A before the tag.

Any correctness, security, evidence, or economics gate failure blocks the release and all v2 work.
