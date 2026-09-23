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
| `.venv/Scripts/python -m pytest -q -o addopts= -rs` | **2109 passed, 1 skipped, 0 failed** (`rc 0`, 599 s); skip = `tests/test_immune.py:563` "POSIX write bits are not Windows ACLs" |
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

### 2.1 Refusals and retained path, executed directly

| Command (disposable home) | Observed |
| --- | --- |
| `brainctl --home <absent> worker-plane spawn s t --json` | exit 2, `{"status":"failed","failure_code":"ORCHESTRATION_REMOVED"}`; path still absent after |
| `brainctl --home <absent> worker-plane lease-release-settled --attempt old --apply` | exit 2, same refusal; path still absent |
| `brainctl --home <absent> stop decide --session s --task-id t` | exit 2, same refusal; path still absent |
| `brainctl --home <absent> governor check-budget --session s --json` | exit 2, same refusal; path still absent |
| `brainctl --home <absent> governor reserve-budget --session s --task-id t` | exit 2, same refusal; path still absent |
| `brainctl --home <empty dir> governor check-budget --session s --json` | exit 2; the empty home gained **no** entries |
| `init`, then `remember "migration order is numeric" --evidence <repo>/notes.txt:1-1` | exit 0, `mem-e373dc2d650d` |
| `recall "migration order numeric"` with `SECOND_BRAIN_PROJECT=demo` | exit 0, `[VERIFIED_CURRENT] migration order is numeric` |
| `autoinject shadow --task … --session e2e-s1 --agent e2e-agent --cwd <repo> --json` with `SECOND_BRAIN_PROJECT=demo` | exit 0, `decision: INJECT`, `candidate_ids [mem-e373dc2d650d]`, `delivery_id del-40a130ed3c63d76e16757517`, `project_resolution: env` |
| Same `recall` / `autoinject shadow` **without** a project identity | exit 0, `NO_INJECTION WRONG_PROJECT` / `decision: NO_INJECTION`, `delivery_id: null` |

So memory write, retrieval and AutoInject delivery still work end to end with
no Brain task admission anywhere in the path, and the retired command families
refuse before creating state.

The project identity matters and is part of the claim: a project-scoped memory
is only delivered when the session resolves to that project, and with no
explicit identity (or a `default`/`unknown` resolution) the reader abstains
fail-closed (`NO_INJECTION WRONG_PROJECT`) rather than leaking another
project's memory. Both directions were reproduced independently by the
security reviewer in fresh disposable homes (`mem-30b4fd1e617a`,
`del-457a62282219fa256c7da37a`), and the disposable homes were emptied
afterwards in every case.

### 2.2 Independent review of this subject

Two independent read-only reviewers ran against `ce15820` (the test-coverage
addition in `1d7800a` is later and only adds one Hermes usage-honesty test).

- **Security review (independent, with execution)** — *CONFIRMED for the
  exercised surface*: it reproduced, in its own disposable homes with
  `PYTHONHOME`/`PYTHONPATH` sanitized, `ORCHESTRATION_REMOVED` for the five OMP
  operations, six Hermes events and `brainctl worker-plane` (exit 2) with no
  home state created; independently reproduced both retained-path directions
  (default/unresolved project → `NO_INJECTION WRONG_PROJECT`, no delivery id;
  explicit `SECOND_BRAIN_PROJECT` → `recall` VERIFIED_CURRENT and `shadow`
  INJECT with a delivery id); ran
  `pytest -q tests/test_migration_chain.py tests/test_autoinject.py tests/test_ledger.py tests/test_vmem.py tests/test_handoff.py`
  → **205 passed** (`-o addopts=`), exit 0, disposable home empty; and
  independently reproduced the aggregate-usage coercion below. It also
  **read but did not re-run** the author's full-suite counts, and found the
  Hermes observer tests did not cover absent/partial usage — a gap closed in
  `1d7800a` by `test_usage_absent_or_partial_is_never_fabricated`.
- **Implementation verifier (read-only, no execution tool)** — returned
  **UNDEMONSTRATED** because its agent type could not run commands. Its static
  pass nonetheless confirmed the retired Python/extension modules are gone and
  no alternate activation switch remains, and raised the
  `scripts/run_p3_promotion_campaign.py` disposition now recorded in §5.
- **Environment limitation, stated plainly**: further `task`-type child spawns
  from this session are refused by the **installed production extension** with
  `BRAIN_WORKER_SETTLEMENT_CAPABILITY_UNAVAILABLE` (its own documented
  stock-route behaviour — it cannot confirm settlement for a child on this
  host). That is the installed legacy runtime, not this candidate, and it
  prevented spawning a third worker for an independent full-suite re-run; the
  full-suite counts above therefore remain author-executed, while the refusal,
  retained-path and targeted-suite checks have independent execution.

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
- **Passive usage honesty (scoped)**: for the strict accounting reader used by
  limits and admission — `governor._session_total_tokens` — duplicate
  observations of one identified billable response are charged once,
  unidentified ones in full, and absent/mismatched usage raises instead of
  reporting a factual zero; episode correlation excludes another root
  (`tests/test_governor.py`). This claim does **not** cover the aggregate
  display reader; see the `OPEN` finding in §5.
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

## 5. Historical subjects retained as data, and retained evaluation

Migrations `0014`, `0022`–`0028`, worker task/receipt/outbox/reservation rows
and the sealed `docs/integrations/omp-host-patch-2026-09-19*` records are
untouched and unclaimed. Old worker/STOP/budget telemetry remains decodable
vocabulary, not a current producer or execution guarantee. P4 qualification
retains its memory/session/cache/backup scenarios; the two repository
worker-plane scenarios are retired and reported as retired, not passed.

`scripts/run_p3_promotion_campaign.py` is **retained** as an operator-invoked
evaluation harness, not a Brain control sink: it selects no model of its own
(the model slug and effort come from operator-frozen `P3_AGY_MODEL` /
`P3_AGY_EFFORT`), passes no Brain admission, lease or settlement, and the
external vendor CLI owns its own permissions. It does launch an external `agy`
process and can forward `--dangerously-skip-permissions` when the operator sets
`P3_AGY_SKIP_PERMISSIONS`. A scope-boundary header was added at the top of the
file and its "This script is an ORCHESTRATOR" self-description was replaced
with "drives an evaluation campaign"; the executable body is unchanged. Any
future finding that Brain authority is reachable from this script is a defect,
not a feature.

Stale derived bytecode for the five removed modules
(`host_protocol`, `model_routing`, `runtime_lineage`, `worker_protocol`,
`worker_recovery` under `src/second_brain/__pycache__/`) was deleted; those
files are gitignored and rebuildable.

### Open retained finding (pre-existing, not introduced by this removal)

`governor.SessionTokens` declares its core counters as `int | None` with a `0`
default, and `parse_telemetry_session` leaves them at `0` when a record omits
them — so a **completed** invocation whose payload is `usage={}` reads back as
`input_tokens 0 / output_tokens 0 / total_tokens 0 / cache_read_tokens 0`,
even though the module's own HONESTY RULE (`governor.py:1-11`) says an absent
field must be reported absent, never coerced to `0`. Reproduced independently
by the security reviewer and by the author; `git show ce15820 --
src/second_brain/governor.py` touches no such default line and the parent
commit already carried five of them, so the behaviour pre-dates this removal.

Disposition: recorded as an `OPEN` retained accounting-honesty obligation
(unknown usage must stay unknown on the reader surface too). It is **not**
fixed here, because correcting it changes a retained reporting contract used
by economics/ROI readers and their tests, which is outside the removal scope;
it is listed as a blocker rather than waived. The strict
`_session_total_tokens` reader does raise on the same file.


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
- **Aggregate usage reader coerces unknown to zero** (§5) — `OPEN`, retained,
  pre-existing.
- **Independent runtime review is partial**: the read-only implementation
  verifier had no execution tool and returned `UNDEMONSTRATED`; the security
  reviewer's independent smoke is the only non-author runtime check, and the
  installed production extension refused further child spawns (see §2.2). The
  executed refusal/retained-path evidence in §2.1 is author-executed.
- **Retired, not proved**: `M00-CORD-01/02`, `SB-ORCH-001`, worker-only clauses
  of `#3/#4/#5`, `FSLNCH-02`.
- The tracked evidence pack also carries controller-era files
  (`worker-settlement.md`, `admission-issuance.md`, `replay-authority.md`,
  `ten-worker-sequence.json`, `mutation-evidence.json`,
  `vitest-full-transcript.txt`, `ownership-edges.json`). They stay as their
  original subjects' evidence and do not describe this candidate.
