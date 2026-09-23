# Orchestrator-removal gate — exact-candidate evidence (2026-09-23)

Subject, commands, results and limits for the 2026-09-23 removal candidate.
The register (`docs/intake/M00-CAMPAIGN-REGISTER.md`) owns the disposition
table and the test-retirement mapping; this file owns the executed evidence.

**No production activation, canonical-state migration, host/extension install,
push or tag is claimed or performed.**

## 1. Identity

| Item | Value | How established |
| --- | --- | --- |
| Candidate worktree | `.worktrees/m00.3-producer-guard` | branch `brain/m00.3-producer-guard` |
| Removal commit | `ce15820bc00b8eadc78adf7e94116f7ebd36739b` | `git rev-parse HEAD` at freeze |
| Parent | `dacebb6` (`brain(policy): define M00 native profile`) | `git log` |
| Subject digest (code/docs under `src/`, `tests/`, `scripts/`, `config/`, extension `src`+`tests`, adapters, telemetry) | `c2013aae12f72a4601fd76b0ebe74c232bb18a1aa84a4e6579948afc532dd9cd` | sha256 over sorted `path + git blob sha` for the 519 tracked files (`git ls-files -s`) |
| Working tree at freeze | clean except untracked `tmp_t03_probe.txt` (pre-existing stray, deliberately not staged) | `git status --porcelain=v1` |
| Python | candidate venv, `3.13.7` | `sys.version` |
| Tooling | ruff `0.16.8`, pyright `1.1.414`, bun `1.4.0`, tsc `5.9.3`, vitest (declared `^3.0.0`, installed `3.2.7`) | version commands |
| Host observed for the native smoke probe | `omp v18.2.11` (installed CLI, read-only `--help`) | `omp --help` |

`git` stores these paths with LF blobs (`core.autocrlf` checkout conversion);
digests above are therefore line-ending independent, exactly as the sealed
successor records are.

## 2. Gate commands and results

All Python runs used a fresh disposable `SECOND_BRAIN_HOME` plus
`PYTHONPATH=<candidate>/src`, with inherited `PYTHONHOME`/`PYTHONPATH`/
`SECOND_BRAIN_PYTHON` removed. Extension runs used a fresh disposable
`SECOND_BRAIN_HOME`.

| Command | Result |
| --- | --- |
| `.venv/Scripts/python -m ruff check <changed files>` / `ruff format` | clean (`All checks passed!`; format: unchanged after normalization) |
| `.venv/Scripts/python -m pyright` | `0 errors, 0 warnings, 0 informations` |
| `.venv/Scripts/python -m pytest -q -rs` | **2108 passed, 1 skipped, 0 failed** (`rc 0`); skip = `tests/test_immune.py:563` "POSIX write bits are not Windows ACLs" |
| `bunx tsc --noEmit` (extension) | exit 0 |
| `bunx eslint src tests` (extension) | exit 0 |
| `bunx vitest run --config vitest.candidate.config.ts` | **26 files passed, 600 tests passed**, 21.11 s |
| Decoy home after every run | empty (no Brain state written outside the disposable home) |

Adverse note, recorded rather than hidden: one earlier run of the extension
suite **concurrently** with the Python suite reported `11 failed files / 15
errors / 685 s transform`. The same command run alone on the same bytes is
green (21 s). The failure is host CPU starvation under a concurrent heavy
tree, not a candidate behavior; the qualifying evidence is the serial run.
Only one heavy process tree was run at a time for every final gate above.

Native smoke probe: the candidate working tree was inspected against the
installed `omp v18.2.11` CLI read-only (`--help`). The full native
`task → worker → completion` / `batch → workers` differential control required
by `M00-NATIVE-ORCH-01` was **not** executed here; it remains `OPEN`.

## 3. What was removed (active surface)

- **Python**: `worker_protocol`, `worker_recovery`, `runtime_lineage`,
  `host_protocol`, `model_routing`; worker task/result/correction contracts and
  lifecycle in `contracts`; the `worker-plane`, `stop`, `orchestration` and
  governor budget/reservation CLI families (now inert refusals); worker
  reaping from heartbeat/P4; repository `WorkerPlaneManager` and its
  `worker_plane` schema; Brainstem route/agent-pressure/scout policy and the
  model/provider/worker signals; capability tiers for execution control;
  gateway routing decisions, budget-soft retrieval gating, `scout` agent
  launch.
- **Hermes**: worker prepare/request/review/correction handlers, model-switch
  preflight and model decisions, budget warning; plugin worker tools and the
  `llm_request` model middleware. Retained: native model/usage observation,
  memory, skills, raw-result transport, handback.
- **Extension**: `driver-orchestrator`, `orchestrator-guard`, `budget-bridge`,
  `stop-boundary`, `native-settlement`, `routing-bridge`,
  `worker-context-bridge`, `worker-lifecycle-bridge`, `worker-result-bridge`;
  controller env/config keys, controller tests and their probes.
- **Release scripts**: host-patch stage/activate/record/export/rehearse
  entry points, the patched-host launcher, the settlement test runner, the
  `omp-canary` observers, campaign/smoke drivers, the host-protocol bridge and
  its conformance harness, the Brainstem experiment and the eight-gate probe.
  The extension install/uninstall path and an explicit-path, extension-only
  candidate snapshot/verify tool remain.

## 4. Retained behavior proven in this gate

- **Inert legacy entry points**: `worker-plane`, `stop decide`,
  `governor check-budget/reserve-budget/consume|cancel-budget-reservation/
  budget-reservations` return `ORCHESTRATION_REMOVED` and create no home
  (`tests/test_cli.py`); OMP `worker_*` operations and unknown model requests
  return `ORCHESTRATION_REMOVED` / `MODEL_ROUTING_REMOVED` without opening
  state (`tests/test_omp_adapter.py`); Hermes retired events refuse before
  home access (`tests/test_hermes_adapter.py`).
- **Inert legacy config**: a v2 policy still containing `worker_slots` /
  `premium_model_turns` loads while unknown keys elsewhere still fail
  (`tests/test_v2_policy.py`).
- **Memory, context and skills**: AutoInject decision/delivery/dedupe and the
  retrieval-holdout classifier, Hermes memory/skill/attribution/VMem
  behavior, handoff, ledger, VMem, JIT and delta sync suites all pass; idle
  spend no longer suppresses useful retrieval
  (`tests/test_autoinject.py::test_native_agent_spend_does_not_block_useful_memory`).
- **Cross-home isolation**: a native session id reused against a different
  Brain home cannot render another home's VMem context
  (`tests/test_cache_breakpoints.py::test_same_native_session_id_cannot_reuse_another_home_context`).
- **Passive usage honesty**: duplicate observations of one identified billable
  response are charged once, unidentified ones in full, missing usage raises
  instead of reporting zero, and episode correlation excludes another root
  (`tests/test_governor.py`).
- **Historical data preservation**: an unresolved pre-24 writer holder blocks
  the upgrade without mutating rows or schema and repeats deterministically; a
  terminal writer row keeps its original identity through the physical-lease
  upgrade; migration 0028 rows survive reopen and an idempotent re-run
  (`tests/test_migration_chain.py`).
- **Release identity**: the retired `budget-bridge.ts` is still recoverable
  byte-exact from its sealed subject commit and the sealed approval records
  still bind their own bytes (`tests/test_release_history.py`); the extension
  install/rollback path and candidate byte-drift detection are covered by
  `tests/test_prime_installer.py`.

## 5. Historical subjects retained as data

Migrations `0014`, `0022`–`0028`, worker task/receipt/outbox/reservation rows
and the sealed `docs/integrations/omp-host-patch-2026-09-19*` records are
untouched and unclaimed. Old worker/STOP/budget telemetry remains decodable
vocabulary, not a current producer or execution guarantee. P4 qualification
retains its memory/session/cache/backup scenarios; the two repository
worker-plane scenarios are retired and reported as retired, not passed.

## 6. Honest limits

- **Real-home preservation is not proved.** An earlier session telemetry
  contact with the canonical home was observed read-only; no before-state
  exists, so retrospective write preservation is unproven and no restore,
  migration or mutation was attempted to disguise that.
- **Native non-interference is not proved** (`M00-NATIVE-ORCH-01`
  `OPEN`): no real OMP session invoked native `task`/`batch`/`hub` against this
  candidate under a matched control.
- **Applicable HIGH findings remain open**: `SEC-AUTH-01`, `SEC-AUTH-02`,
  `SEC-INTEGRITY-01`, `SEC-SKILL-01`/`SB-PROMOTION-004`, `FSUPD-01`/`FSPATH-03`,
  `SEC-HOOK-02`, `SEC-DEP-01` (current lockfile advisories), project-ID
  prompt sinks. Removal of the worker route is not a fix verdict for them.
- **Retired, not proved**: `M00-CORD-01/02`, `SB-ORCH-001`, worker-only clauses
  of `#3/#4/#5`, `FSLNCH-02`.
- The tracked evidence pack also carries controller-era files
  (`worker-settlement.md`, `admission-issuance.md`, `replay-authority.md`,
  `ten-worker-sequence.json`, `mutation-evidence.json`,
  `vitest-full-transcript.txt`, `ownership-edges.json`). They stay as their
  original subjects' evidence and do not describe this candidate.
