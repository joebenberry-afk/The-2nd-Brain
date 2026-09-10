## 2026-09-10 — Native OMP session identity (unreleased)

- Use native session identity for fresh roots and named workers, eliminating
  basename collisions while preserving verified existing ledger assignments.
- Record identity before Brain operations and preserve bindings across
  extension restart, session reopen, and transcript rename.
- Read ancestor identity metadata consistently, including title-prefixed
  transcripts and bindings outside a tail window; retain filesystem ancestry.
- Refuse unproven legacy state without opening a replacement ledger. Avoid
  shutdown capsule updates when no capsule was touched in that extension run.

## 2026-09-10 — Selected-runtime economics (unreleased)

- Honor `SECOND_BRAIN_PYTHON` for fresh Brain initialization and host execution,
  independently of the evidence producer's interpreter.
- Bind schema-3 records and collection to the package actually loaded by that
  runtime. Refuse unavailable runtimes and packages outside the bound source
  checkout before accepting evidence; preserve interpreter paths across venvs.
- Keep frozen tasks, OFF/ON profiles, and the separate native three-pair
  read-reuse study unchanged.

## 2026-09-10 — Host-bound capability tiers (unreleased)

- Derive CLI and matrix governance tiers from the same host-bound capability
  snapshot. Stale, declared, and unbound support no longer advertises safe
  governance; current observed support and explicit denial retain their tiers.
- Accept explicit per-harness matrix bindings and show declaration/unavailable
  statuses instead of presenting them as verified support.

## 2026-09-10 — Answer-grounded economics (unreleased)

- Retain host answer/error streams outside Git repositories with immutable
  capture files and hashed public references. Preserve failed attempts.
- Separate repository regression checks from answer acceptance. Collect
  independent, output-bound reviews without running the host again; reject
  stale, tampered, duplicate, and mismatched evidence.
- Keep whole-cohort token statistics separate from the quality gate. Missing
  arms or failed host, regression, or answer checks cannot qualify economics.


## 2026-09-10 — Economics evidence-integrity repair (unreleased)

- Retain immutable raw records for every paired attempt, including setup
  failures, missing arms, and appended telemetry accounting failures.
- Pin collection to the current observed runner source and frozen task catalog,
  require the preregistered `--reviewer-identity`, and reject all extra or
  invalid reviews.
- Keep answer quality separate from economics usage eligibility; unknown
  prices remain null while token evidence follows existing statistical gates.
- Add the primary OMP host explicitly with its supported `--print --no-title`
  launch mode and public-safe executable/argv identity.
- Mark malformed or missing usage unavailable rather than reporting partial
  totals as complete. Retain host execution timestamps for end-to-end timing.

## 2026-09-10 — Hermes backend isolation (unreleased)

- Resolve the Brain backend only from its configured interpreter or command,
  never from the consumer repository's `src` directory or working directory.
  Preserve consumer project context in the existing request payload.
- Use Python safe-path startup and the trusted Brain home for backend execution;
  a missing Brain home fails open instead of falling back to consumer code.
- Deliver PREFIX through Hermes's native frozen system-prompt section API and
  TAIL through supported ephemeral context. Preserve native read behavior;
  remove the unsupported Brain read-replacement path, not Hermes's own dedup.

## 2026-09-10 — Completion candidate diagnostics (unreleased)

- Explain cascade selection with bounded candidate identities, scores, MMR
  steps, omission reasons, and explicit truncation. Keep archived history out
  of active ranking and budgets while retaining diagnostics on repeated queries.
  Admit at most 256 ranked candidates per cascade so even wide provider results
  retain a complete, bounded replay record; report candidates outside that pool.
- Preserve normalized relevance separately from raw BM25, reuse activation
  evidence, honor configured decision utility, and refuse malformed vector
  results and invalid token-penalty denominator settings safely.
- Gate optional Brainstem work on current capability evidence and provider
  quota without lowering risk-required model or verification floors. Retain
  the capability snapshot in decision inputs for reproducible replay.
- `brainctl v2 harness capabilities <id> --host-version <version>
  --config-binding <binding> --json` distinguishes declared, observed,
  unavailable, denied, and unknown support. An unversioned event or a static
  declaration is not current observed support; replay cannot change host scope.
- Candidate only: full v1/v2 remains HOLD and skill-v2 remains SHADOW.
  Local diagnostics do not establish native qualification or runtime adoption.

## 2026-09-09 — Bounded closure regression repair (unreleased)

- Share policy-lane admission without excluding canonical `project_rule` memory
  or trusting absent authority metadata. Preserve contradiction annotations.
- Keep exact and vector retrieval bodies free of document frontmatter; preserve
  lexical body semantics and the existing query-observation cadence.
- Refuse stale FTS versions/file hashes and invalidate negative misses when an
  index is repaired. Vector rows require canonical version/file-hash identity;
  reject unsafe projections, retain retryability, and enforce bounded selection.
- Preserve finite scoring defaults for malformed normalization configuration and
  exact project-ID scope across retrieval and injection.
- This successor is not automatically adopted. Full v1/v2 remains HOLD and
  skill-v2 remains SHADOW; native and release campaigns remain unstarted.

## 2026-09-09 — Bounded retrieval repair (unreleased)

- Correct FTS5 BM25 normalization to use the most-negative score as the best
  match. Strong lexical matches no longer lose relevance before candidate
  limits and MMR selection. Existing filters, weights, and budgets are unchanged.
- Add real Hybrid retrieval regression protection with a neighboring-query
  positive control. Full v1/v2 qualification remains HOLD; skill-v2 stays SHADOW.

## 2026-09-09 — Bounded qualification closure (unreleased)

- Restore explicit `leave_unresolved` reconsolidation plans. Applying or
  reverting a deferral preserves memory bodies, versions, sources and lineage;
  stale-plan checks and decision-history records remain active.
- Add source/config-bound observations to the existing qualification producers.
  Only explicitly permitted Gate clauses can receive test evidence; failures,
  skipped cases, unknown nodes and stale identities remain unresolved.
- Capture current native read-reuse studies with complete controller/worker
  accounting and session-bound acceptance. Reject extra commands and incomplete
  runs; answer sidecars cannot authorize success. Local retrieval profiling never
  invents provider usage, task success or savings.

## 2026-09-08 — Recovery and native dispatch repairs (unreleased)

- Validate session-ledger layouts on every open, including resumed `create=True`
  calls. Transactionally backfill supported pre-chain ledgers while preserving
  original event bytes and a consistent snapshot; label the chain origin as
  derived, never as proof of pre-migration authenticity. Refuse partial chains
  and preserve manifest timestamps and host-artifact references.
- Export finite mSPRT likelihood overflow in log space and distinguish it from
  the zero-variance infinity limit and unavailable evidence. Paired-economics
  JSON rejects nonstandard numeric constants instead of overwriting malformed
  historical exports.
- Require public recovery to succeed before VMem coverage permits reclamation,
  including previously covered objects whose backing artifacts disappear.
- Preserve UTF-8 input bytes and mixed line endings through VMem and firewall
  CLI round trips; reject invalid UTF-8 rather than replacing it.
- Stop project discovery at an independent Git boundary and share the same
  ownership resolver between CLI memory writes and automatic retrieval.
- Reject backups with missing canonical memory bodies before publishing them;
  validate restores before mutation and recreate the complete runtime layout.
- Close native preflight-rejected tasks with durable failure receipts. Allow
  context-free workers when OFF/SHADOW injection has not created a capsule;
  retain fail-closed behavior for corrupt or unreadable capsules.
- Recognize the Astra driver and reject qualification runs that resolve Python
  from a different source checkout.
- Initialize isolated economics homes before host launch, sanitize Python
  environments, and retain raw usage telemetry without retaining host output.
  Keep each executed checkout beside its telemetry instead of deleting it while
  the native host may still hold operating-system handles.
- Decode harness configuration as UTF-8 on Windows PowerShell, preserving
  unrelated Unicode settings. Emit Codex callbacks under the actual `[hooks]`
  table with TOML-safe, Windows-callable command quoting.
- Preserve UTF-8 across native hook process boundaries, recognize Codex's
  `hook_event_name`, and leave unavailable hook counters null.
- Accept historical version-2 heartbeats without the additive GC counter while
  still validating supplied measurements.
- Keep retrieval outcomes pending when acceptance is unknown. Use the canonical
  identity-checked usage reader; unavailable or unattributable token totals stay
  null rather than becoming fabricated zero-cost failures.
- Seed the safe v2 policy into initialized Brain homes without overwriting
  operator configuration.
- Refuse empty transfer acceptance contracts before executing a student, and
  require an explicit successful acceptance result for transfer verification.
- Preserve canonical memory bodies in lexical cascade results and MMR input.
- Profile retrieval against the current corpus using measured latency and
  explicitly estimated context sizes; never fabricate provider costs, turns,
  task success, or a positive economics verdict. Preserve existing reports.
- Add read-only candidate qualification and atomic, independently verified
  ledger recording. Candidate reports cannot authorize ACTIVE; conflicting,
  partial, stale, tampered, or simulated evidence remains ineligible.
- Read RepoWise freshness from its machine-readable commit state rather than
  hashing rendered table borders; unchanged Windows environments no longer
  fail qualification solely because UTF-8 and legacy decoding differ.

## 2026-09-07 — Fail-closed admission policy (unreleased, HOLD)

- Reject an invalid existing v2 admission policy instead of silently falling back
  to SHADOW and recording candidates. Only an absent legacy policy retains the
  SHADOW default; valid OFF policy still records neither candidates nor decisions.

## 2026-09-05 — Local budget and qualification closure (unreleased, HOLD)

- Bound every Brainstem injection decision by remaining total allowance,
  operation cap, and available context. Preserve explicit zero; reject invalid
  token counts; abstain when the useful minimum cannot fit.
- Make qualification fail closed on missing or incomplete manifests, canonical
  Gate coverage, source/configuration mismatch, unsupported provenance, and
  unresolved or tampered evidence. Bind SQL/package data as well as Python.
- Keep simulated self-improvement reports as mechanism evidence, ineligible
  for production activation, economics, or release qualification.
- Replace rollout caller booleans with persisted `credit_observation_id` and
  `qualification_manifest`. Recompute authenticated causal credit and require
  the actual verifier process to bind the exact observation artifact.
- Adopt cancellation accounting in place of automatic cancelled delivery;
  preserve OMP suppression. Cancellation remains unqualified: lost host
  authority and per-job physical-cleanup authority are not closed.
- Fresh proof: 1,914 Python tests, 697 extension tests, Pyright, changed-file
  Ruff, disposable Doctor, backup/restore, and native host-to-Brain smoke.
  Full ESLint retains four inherited unused-import errors in unchanged tests.
- No deployment, provider calls, active rollout, Gate 22/23 closure, or tag.
  [Evidence and contract](outputs/reports/v2/omp-burnin/20260905-local-contract-closure/).

## 2026-09-05 — Exact native dispatch binding (unreleased, HOLD)

- Bind pending workers by the manager-returned `progress.jobId`; retain
  `progress.id` as the expected child agent identity. Preserve the exact
  pair across restart; reject unknown jobs and conflicting delivered agents.
- Keep explicit hub and structured async delivery on one durable acceptance
  path. Do not infer missing bindings from agent names, task text, or legacy
  journals.
- OMP dispatch draft [#10948](https://github.com/can1357/oh-my-pi/pull/10948)
  remains separate from delivery metadata draft
  [#10928](https://github.com/can1357/oh-my-pi/pull/10928).
- Prove collision, batch, replay, and restart against native host components
  and durable Python receipts offline. No deployment or provider calls.
  [Evidence](outputs/reports/v2/omp-burnin/20260905-dispatch-binding/).

## 2026-09-05 — Structured async authority (unreleased, HOLD)

- Replace rendered-result status/identity parsing with native OMP delivery
  metadata. Stock hosts remain pending with one capability diagnostic;
  patched hosts preserve immutable receipts across replay and restart.
- Prove the six-line upstream OMP patch against current main and pinned
  18.1.10, including delivery reconstructed after live-row eviction.
- Resolve all 85 Pyright errors without blanket suppression; regress
  non-iterable corroboration and malformed worker-event identity boundaries.
- Reduce measured populated-home budget checks from 934 ms to 141 ms using
  eight bounded read-only ledger readers. Preserve root scoping, deduplication,
  unavailable-accounting semantics, and real caps.
- No deployment, provider qualification, Gate 22/23, or release tag.
  [Offline evidence](outputs/reports/v2/omp-burnin/20260905-host-contract-offline/).

## 2026-09-05 — Audited OMP closeout (unreleased, HOLD)

- Preserve native task options and distinct dispatch identities; acknowledge
  results only after packet/owner-bound durable acceptance. Schema 22 adds
  atomic result receipts to the existing worker database.
- Preserve current messages when no paging breakpoint exists. Deduplicate
  root-owned ledger usage and report unavailable accounting explicitly.
- Validate destination-bound installer backups before mutation; retain
  unrelated settings. Retry bounded transient Windows manifest contention
  without suppressing permanent errors.
- RC remains unqualified: native result framing, populated-home latency,
  type checking and final live/economics gates remain open. No release tag.
- Evidence and exact remaining work:
  [audited closeout](outputs/reports/v2/omp-burnin/20260905T030605Z-audited-closeout/14-release-readiness.md).

## 2026-08-15 — Driver Orchestration Contract (Prime extension)

- `brainstem/prime-extension/src/driver-orchestrator.ts` (new): pure role
  resolution + driver contract. Roles `hard_orchestrator` > `driver` >
  `worker` > `normal` by lowercased substring containment; defaults
  `DRIVER_MODELS=deepseek-v4-pro,gpt-5.6-luna`, `WORKER_MODELS=deepseek-v4-
  flash,qwen3.5` (env CSV override, call-time reads, orchestrator-guard
  style); `DRIVER_ORCHESTRATOR_CONTRACT` (170 words, marker
  `second-brain-driver-orchestration-contract`, trivial-direct /
  substantial-delegate / max-2 concurrency / never-wait-for-user / cheapest-
  competent-worker / workers-do-not-orchestrate); `appendDriverContract`
  appends with marker dedup, never replaces, never invents a prompt.
- `brainstem/prime-extension/src/index.ts` (before_agent_start only): role
  resolved before the unchanged Sol branch; driver sessions get the contract
  APPENDED to the full system prompt (dedup -> no patch when marker already
  present); default-off recall brief composes AFTER the contract in ONE
  patch; non-driver sessions behave exactly as before (zero spawns when
  recall disabled).
- `brainstem/prime-extension/src/sensors.ts`: `before_agent_start` record
  gains additive optional `role` + `driver_contract_injected` (schema v2,
  additive per SCHEMA.md; absent for non-driver roles; Python validator
  unaffected — extra fields ignored).
- `brainstem/prime-extension/tests/driver-orchestrator.test.ts` (new, 16
  tests) + 6 wiring tests + 2 sensors tests; suite 177 -> 201 passed, tsc
  clean, eslint clean.
- Docs: `brainstem/telemetry/SCHEMA.md` (additive note), `README.md` (env
  rows + Agent roles section), `brainstem/policies/driver-orchestration.md`
  (canonical policy). `orchestrator-guard.ts` / `recall-gate.ts` /
  `config.ts` / `rtd.ts` / `storage.ts` / `types/*` byte-identical to HEAD.
- NOT deployed: installed copy at `~/.prime/agent/extensions/second-brain/`
  still predates the campaign (deployment is a separate step).

## 2026-08-15 — Live validation evidence (deployment + recall + census)

- `a2be626` "docs: record live rollout baseline": pre-deployment baseline
  (installed extension predates campaign; restart mechanics: per-session
  extension loading, `/reload`, supervisor auto-respawn; headless launchEnv
  propagation for client-owned sessions).
- `42bf8a3` "brain(core): fix transient Hypothesis deadline flake in
  migration property tests": `tests/test_migrations_property.py` was the only
  Hypothesis file without `deadline=None`; git-init subprocess + 200 ms
  deadline under two-worker contention → minimal test-only fix; full suite
  655 passed / 2 skipped pre and post.
- This commit "live validation evidence": `outputs/reports/optimization-proof.md`
  gains the "Live Rollout Addendum — 2026-08-15" (deployment 06:45:44Z exit 0,
  8 files SHA-identical; recall hook spawn observed live at +6.11 s with the
  exact query; relevant/irrelevant recall tests with 0 extension_error;
  recall bounds (1 spawn, 3 rows/1000 words); guard live status — ipython-only
  toolset, 0 violations in 22,615 records, Pass Condition B, Sol-specific
  acceptance blocked by model availability; Test D allowed path live (campaign
  ran ≤2 concurrent, 0 violations); FTS5 live (schema v7, 6/6, FTS branch);
  telemetry re-census 387/304/308/22,615 with 0/0/0 violations/shadows/errors;
  realistic-task flake root cause; final status PARTIALLY VALIDATED; graceful
  daemon shutdown command `shutdown --force` with citations).
- `proof/reports/live-rollout-baseline.md`: post-deployment re-census section
  appended (before/after table, kind census, schema-health sample).

## 2026-08-15 — Phase 14 recall hook + proof package update

- `a8c6acb` "brain(adapter): default-off controlled Prime recall hook
  (Phase 14)": `brainstem/prime-extension/src/recall-gate.ts` + `index.ts`
  wiring. Default OFF (`SECOND_BRAIN_RECALL` unset/not in {1,true,yes});
  env knobs `SECOND_BRAIN_RECALL_MAX_ROWS` (3), `MIN_CHARS` (40),
  `TIMEOUT_MS` (5000). One bounded out-of-process `memory search` per
  before_agent_start for substantial non-Sol prompts (non-blank, >=8 words,
  >=minChars, not greeting/continuation); brief capped at 3 rows / 1000
  words, appended to the full system prompt; every failure fails silent.
  23 recall-gate + 6 wiring vitest tests. NOT deployed yet.
- `outputs/reports/optimization-proof.md`: Prime Recall section rewritten
  from NOT PROVEN to implemented-default-off (cited above); added Phases
  15-17 conservative no-op section; risks/recommendation updated (recall
  implemented-not-deployed; limited rollout stands).

## 2026-08-15 — Optimization Proof package + live reindex

- Live Brain reindexed (derived data only, `memory reindex`): schema v6 -> v7,
  `memory_fts` created and populated 6/6 (was absent — live path was the
  linear Markdown scan); `memory_index` 6/6; real `memory search` now takes
  the FTS5 branch (~5 ms). Canonical `memory/` files untouched.
- `outputs/reports/optimization-proof.md` added: plan §24 required proof
  package (Sol orchestration, telemetry, RTD, retrieval, configuration,
  router, Prime recall, risks, recommendation) with commit/test/artifact
  citations; Prime Recall section explicitly marked NOT PROVEN — gap.

# Changelog

> **Status note (2026-08-15 documentation truth pass):** the retrieval
> entries below (Phases 6-8) describe work that lives in the WORKTREE only —
> `semantic.py`, `cli.py`, migration `0007_memory_index.sql` and
> `tests/test_retrieval_*.py` are NOT committed yet; a ranking fix and
> benchmark are in final validation. Treat them as **in final validation**,
> not shipped. Committed campaign state: telemetry hot-path fixes (Phase 2-4),
> Sol minimal-orchestrator guard (Phase 1 wiring), skill router cache +
> `router.max_active` (Phase 13).

## 2026-08-15 — Optimization pass Phase 8: retrieval deduplication

- `semantic.py` `search_memories(..., include_duplicates=False)` (new
  keyword-only, backward compatible): post-filter, pre-budget dedupe shared by
  the FTS and linear-fallback paths (`_dedupe_rows` / `_dedupe_family`).
  * Families: normalized-title equality (primary) + body-token Jaccard >= 0.8
    with a 6-token body minimum (secondary); features precomputed once;
    pairwise body scan bounded by a deterministic 200-row work guard (broad
    queries stay fast; title families always apply).
  * Representative: highest current_version, then status (current > labile >
    candidate > archived > superseded), then newest updated_at, then evidence
    grade, then memory_id. Content is never merged — one row is selected.
  * Scope rule: under a project context, global/domain-scope rows form a
    DISTINCT bucket (comparison may be required); otherwise families dedupe.
  * `include_duplicates=True` returns everything (comparison exception); it
    does NOT bypass Phase 7 filters (history audits need include_history too).
  * FTS path carries the body from the index (`f.body AS _body`) so similarity
    detection needs no file reads.
- Review N1 applied: ALL status='superseded' rows are now excluded by default
  (carve-out removed — memory_versions preserves history); include_history
  re-includes them; REJECTED stays always excluded. Docstrings/CHANGELOG/
  tests updated.
- Review N4 applied: the FTS5 availability check is now a single
  process-global module flag (`_FTS_MODULE_CHECKED/_FTS_MODULE_OK`) instead of
  a per-db-path cache (removes any temp-dir path-reuse hazard); the per-DB
  `CREATE VIRTUAL TABLE IF NOT EXISTS` still runs for every new database.
- CLI: `brainctl memory search --duplicates`.
- Tests: `tests/test_retrieval_dedupe.py` (+7): superseded family keeps
  current; near-identical pair keeps canonical (deterministic); project+global
  distinct under project context / deduped globally; include_duplicates
  returns all (with history); archived family member never representative;
  fallback parity; distinct memories not merged.
- Benchmark: dup rate 0.0000 with dedupe, stale 0.0000, recall/MRR no
  regression, 10k p95 21 ms (see `proof/reports/retrieval-bench.md` Phase 8).

## 2026-08-15 — Optimization pass Phase 7: retrieval hard filters

- `semantic.py` `search_memories(home, term, *, project_id=None, include_history=False)`:
  hard filters applied BEFORE ranking as SQL WHERE on the FTS path and via a
  shared predicate (`_row_passes_filters`) on the linear fallback (fallback
  cannot regress filter semantics):
  * evidence grade REJECTED: always excluded (rejected != historical);
  * status archived: excluded unless `include_history`;
  * status superseded: excluded unless `include_history` (review N1: ALL
    superseded rows excluded by default — memory_versions already preserves
    version history, so no carve-out);
  * project_id: restrict to one project (global/None = everything).
  Deterministic tie-break: ORDER BY bm25(memory_fts), memory_id.
- Review fixes from Phase 6 (F1/F2/F4): reindex_all purges gate `memory_fts`
  DELETEs on `_fts_available` (derived once) so FTS5-less builds never crash
  on missing-file purge; `_fts_query` returns None for non-ASCII or
  token-less terms and search falls back to linear (never a fragment MATCH
  like `"d"* "j"*` from "déjà"); `_safe_index` logs one warning
  (`second_brain.semantic` logger) on index failure, still fail-open.
- CLI: `brainctl memory search <term> [--project P] [--history]`.
- Tests: `tests/test_retrieval_filters.py` (+10: archived/rejected/superseded
  exclusion, unique-evidence exception, project filter, linear-fallback
  parity, deterministic ordering, F1/F2/F4 regressions).
- Benchmark (same harness/seed): stale activation rate 0.0000 at 100/1k/10k
  with filters on (was 0.027-0.093 raw); 10k p95 20.7 ms (target <=200 ms);
  see `proof/reports/retrieval-bench.md` Phase 7 section. No ranking tuning
  (Phase 9).

## 2026-08-15 — Optimization pass Phase 6: SQLite FTS5 retrieval (replaces linear scan)

- Migration `0007_memory_index.sql`: derived `memory_index` metadata table
  (title/summary/project/scope/status/grade/version/timestamps/body_path/
  tags/file_hash/indexed_at). The `memory_fts` FTS5 virtual table is created
  lazily in code behind an availability check so migrations never fail on
  FTS5-less builds. Markdown stays canonical; the index is rebuildable via
  `brainctl memory reindex` (never hand-edited).
- `semantic.py`: indexer (`index_memory`, `reindex_all` incremental with
  sha256 change detection + purge of missing files) hooked into
  add/curate/supersede (fail-open via `_safe_index`); `search_memories` now
  uses FTS5 (quoted prefix tokens, bm25 rank) with a documented linear-scan
  FALLBACK when FTS5 is unavailable or the index is empty-but-memories-exist;
  Phase 7-11 TODO anchors left at the filter/rank/dedupe/budget points.
- Known divergence (tested + documented): FTS5 matches word prefixes, so a
  middle-of-word substring (e.g. "arc" in "sidecar") matches only the linear
  scan.
- Benchmark harness `proof/runner/retrieval_bench.py` (v4.3 §14 labeled
  corpus; Recall@1/3/5, Precision@5, MRR, dup/stale/contradiction rates,
  tokens, p50/p95 at 100/1k/10k): FTS 10k p95 = 17.9 ms vs linear 1,440 ms
  (~80x); see `proof/reports/retrieval-bench.md` (quality gates from Phase 7+).
- Tests (`tests/test_memory_index.py`, +13): migration fresh create /
  idempotent / reopen, backup-restore preserves the FTS index, auto-index on
  add/curate/supersede, incremental reindex + purge, search parity vs linear,
  linear fallback (fts unavailable / empty index), documented divergence.
- CLI: `brainctl memory reindex`.

## 2026-08-15 — Optimization pass Phase 4: telemetry filesystem churn reduced

- `brainstem/prime-extension/src/storage.ts`: removed mkdir-per-append. New
  factory-scoped `createTelemetryDirEnsurer()` seam: the shared destination's
  mkdir is ATTEMPTED AT MOST ONCE per extension factory (plan: "at extension
  startup, ensure the telemetry directory once"), shared by every
  TelemetryStore in that factory regardless of session count; standalone
  store construction keeps a one-shot per-store default. A failed first
  attempt is deliberately permanent (never retried; reported once through the
  first constructing store's one-time error handler, fail-open). The factory
  accepts an optional `ensureTelemetryDir` test seam (`ExtensionOptions`,
  factory-scoped, never module-global). Construction/append/appendFinal
  remain non-fatal; append ordering, path sanitization, per-session files,
  JSONL format, privacy, and Phase 2 anonymous identity are unchanged.
- **Buffering NOT implemented** (documented in storage.ts): Prime's daemon
  tears the worker down immediately after `session_shutdown`; the only
  shutdown flush is the synchronous `appendFinal()` write, and there is no
  awaited session-end flush that could drain a buffer — buffering could lose
  the final records, so immediate append semantics are kept.
- Tests (`tests/storage.test.ts`, +9; `tests/wiring.test.ts`, +2): ensurer
  attempts mkdir exactly once across any call count and across two stores
  sharing one ensurer; failed first attempt permanently marked (throws once,
  never re-attempted); separate ensurers independent; two distinct session
  stores from ONE factory share exactly one mkdir attempt (wiring-level with
  injected seam); failing shared ensurer keeps construction non-fatal and
  never re-attempts; concurrent/interleaved appends ordered and complete;
  independent destinations no cross-talk; constructor/ensure failure
  fail-open (construction + append + appendFinal never throw); appendFinal
  reuses readiness (no re-mkdir).

## 2026-08-15 — Optimization pass Phase 3: RTD hot-path serialization waste removed

- `brainstem/prime-extension/src/rtd.ts`: eligibility (tool/command) decided
  first via `rtdEligibility` — ineligible results short-circuit with zero
  RTD-specific serialization (base telemetry's mandatory measurement is
  unaffected; see the three-path clarification below).
  `shouldDistill`/`rtdShadowRecord` consume a precomputed `ContentMeasurement`
  (no content field in the RTD API), and the precomputed eligibility is passed
  through so the input is read exactly once and the decision cannot diverge.
- `brainstem/prime-extension/src/sensors.ts`: `measureContent` = ONE
  serialization attempt producing both legacy RTD `serializedChars`
  (JSON.stringify length; 0 when non-string/throws) and existing telemetry
  `outputBytes` (raw string bytes; serialized JSON bytes; `<unserializable>`
  fallback; Node-verified for undefined/function/symbol/circular/bigint).
  `toolResult` now takes the precomputed byte count.
- `brainstem/prime-extension/src/index.ts`: tool_result handler decides RTD
  eligibility FIRST (`rtdEligibility`), then measures once and shares the
  measurement with telemetry and RTD shadow; RTD threshold semantics (JSON
  char length, Unicode/escaping/boundaries) unchanged.
- **Correction (same day)**: eligibility is now computed BEFORE any content
  measurement, and ineligible results perform ZERO RTD-specific serialization
  — ineligible primitive strings get only the raw UTF-8 byte count base
  telemetry already required (no JSON.stringify); ineligible non-strings keep
  exactly the single serialization/fallback base telemetry already required
  (`measureContent(content, includeSerializedChars=false)`); eligible results
  keep exactly one JSON.stringify attempt plus one byte count. The precomputed
  eligibility is passed into `rtdShadowRecord` so RTD never re-measures.
- Tests: eligibility-before-measurement proofs, computed-once proof (toJSON
  counter), JSON.stringify spy regressions (ineligible string: 0 stringifies;
  eligible string: exactly 1; ineligible object: exactly 1 for base
  telemetry), measurement-mode unit tests, Unicode/escaping/boundary
  regressions, legacy-metric divergence (string: 500 bytes vs 502 chars).

## 2026-08-15 — Optimization pass Phase 2: stable anonymous telemetry identity

- `brainstem/prime-extension/src/index.ts`: anonymous fallback session id is
  now created once per extension lifecycle (closure state, not a global) and
  reused for every event without an explicit Prime session file — one
  telemetry JSONL per anonymous lifecycle instead of one file per event.
  Explicit Prime session file stems unchanged (always override the fallback).
- Deterministic wiring tests for the four acceptance cases (stable id, single
  file, distinct per-lifecycle ids, explicit override).
- Baseline remains `outputs/reports/optimization-phase0-baseline.md` (pre-fix
  snapshot: 304 single-record anon files); post-fix file-count evidence will
  be recorded in a later milestone, not by rewriting the baseline.

## 2026-08-15 — Optimization pass P0/P1: Sol minimal-orchestrator (Phase 0-1)

- Baseline recorded: `outputs/reports/optimization-phase0-baseline.md` (telemetry
  fragmentation 304 single-record anon files; retrieval p95 1426 ms @ 10k vs 200 ms
  gate; router milestone numbers; config NOT WIRED findings).
- Canonical Sol minimal-orchestrator policy added:
  `brainstem/policies/sol-minimal-orchestrator.md` (ADVISORY; enforcement status
  documented; not in constitution/).
- `orchestrator_policy_violation` telemetry kind (schema v2) added: bounded
  enumerated fields only (violation, model, detected_by, blocked); Python
  aggregation in `telemetry.report`; pure report-only TS sensor (NOT WIRED).
- Prime per-model tool restrictions: NOT CONFIGURED / UNVERIFIED — no global
  Prime config changed.
- See `outputs/reports/optimization-phase0-baseline.md` and
  `brainstem/policies/sol-minimal-orchestrator.md`.

## 2026-08-15 — Optimization pass Phase 1 wiring: Sol guard enforced (commit 61c536a)

- `brainstem/prime-extension/src/orchestrator-guard.ts` (NEW): pure decision
  module — `orchestratorPolicyFor(modelId, toolName, cfg)` blocks
  `bash`/`edit`/`websearch` for orchestrator models (default substring
  `gpt-5.6-sol`; env `ORCHESTRATOR_MODELS` / `ORCHESTRATOR_BLOCKED_TOOLS`
  overrides; `ipython` deliberately NOT blocked — RLM delegation runs through
  the IPython kernel); `buildPolicyBlockRecord` emits
  `orchestrator_policy_violation` (bounded enumerated fields per SCHEMA.md).
- `src/index.ts` wiring: `tool_call` handler appends the normal record, then
  for orchestrator-model sessions returns `{block:true, reason}` and appends a
  violation record (`detected_by=runtime_guard`, `blocked=true`, session stem
  filled); `before_agent_start` injects the condensed Sol contract as a
  `systemPrompt` patch for orchestrator-model sessions only. All other
  sessions remain measurement-only. Fail-open: guard errors are recorded as
  `extension_error` and never block.
- `types/prime.d.ts`: added `ToolCallEventResult` / `BeforeAgentStartEventResult`
  and typed `on` overloads (type-only; matches Prime runtime v0.7.2).
- `docs/orchestration/SOL_MINIMAL_ORCHESTRATOR.md` (NEW): condensed Sol
  contract (canonical: `brainstem/policies/sol-minimal-orchestrator.md`).
- Tests: `tests/orchestrator-guard.test.ts` (14) + 7 wiring tests; suite 137.
- **Deployment status: NOT deployed to `~/.prime` yet** — the installed
  extension copy predates the guard; deployment is a separate step pending
  campaign end.

## 2026-08-15 — Optimization pass Phase 13: skill router cache + config (commit b4f0a47)

- `src/second_brain/router.py`: SKILL.md section cache (path -> mtime_ns +
  sections, lock-guarded) — each unchanged skill is read AT MOST ONCE per
  `route()` call (was twice: triggers + procedure) and zero times on later
  calls; mtime change invalidates. Scoring/thresholds unchanged (threshold
  1.0, conservative).
- `router.max_active` ENFORCED: `route()` resolves it from
  `<home>/config/skills.toml [router] max_active` per call (tomllib pattern of
  `working_set._material_gate_blocks`); invalid/absent -> 3; explicit arg
  (CLI `--max-active`) overrides config.
- `config/skills.toml` + defaults copy: `[router] max_active` comments now
  ENFORCED.
- Tests: `tests/test_router.py` +6 (read-once, zero-reads cache hit, mtime
  invalidation, config honored/fallbacks, explicit override, conservative
  routing unchanged); 16 in file, full suite green.

## 2026-08-14 — v4.2 complete, v4.3 proof campaign begins

- v4.2 implementation and self-hosting milestones are complete.
- v4.3 validation is a separate falsifiable campaign; shadow-only RTD and
  report-only Prime routing remain explicit limitations until proven otherwise.

Format: Keep a Changelog-ish. Entries reference milestone reports under
`outputs/reports/`.

## [0.4.0] — Working Set / JIT Context (Phase 4)

- Active State Capsule, Requirement-to-Evidence Ledger (material-unverified
  completion gate), Read Ledger.
- Deterministic JIT Context Compiler -> Task Context Capsules.
- First dogfooding: the build manages its own Phase 5 task via capsule +
  requirements + read ledger + compiled capsule.
- See `outputs/reports/milestone-04-working-set-jit.md`.

## [0.3.0] — Project Integration (Phase 3)

- `brainctl project add` = full attach: `.brain/project.toml` (never overwrites
  user manifests), fenced AGENTS.md marker block (byte-exact preservation),
  RepoWise detection.
- `project detach` (rollback) + `project remove [--purge]`.
- See `outputs/reports/milestone-03-project-integration.md`.

## [0.2.0] — Observability (Phase 2)

- Prime Agent measurement extension (`brainstem/prime-extension/`): 11
  lifecycle events -> schema v2 JSONL telemetry, privacy-preserving,
  config-gated, fire-and-forget writes. Installed globally.
- `brainctl telemetry report|validate`.
- Install/uninstall PowerShell scripts + Pester suite.
- See `outputs/reports/milestone-02-observability.md`.

## [0.1.0] — Foundation (Phase 0–1)

- Initial repository: canonical layout, constitution, config defaults.
- Python package `second_brain` (stdlib-only) with `brainctl`:
  `init`, `doctor`, `status`, `project add|list|status`, `backup`, `restore`.
- SQLite migration framework (WAL, foreign keys, idempotent migrations).
- Project registry + backup/restore with verified roundtrip.
- See `outputs/reports/milestone-01-foundation.md`.
