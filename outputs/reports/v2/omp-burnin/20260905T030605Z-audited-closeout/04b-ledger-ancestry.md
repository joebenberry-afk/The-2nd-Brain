# Stage D / B6 — OMP Ledger Ancestry

## Scope and execution status

This change is offline-only and modifies the existing OMP mirror and canonical per-session ledger path. It does not add a database, ancestry store, provider call, account change, deployment, or production derived-state edit. Existing historical rows were not backfilled.

Per the closeout concurrency contract, no test, lint, formatter, build, provider, or live validation command was run in this worker. Main owns converged validation and the `index.ts` caller wiring. No PASS/FAIL result is claimed here.

Final integration status: Main subsequently ran the converged suites (`07-regression-delta.md`): Python 1823 passed and extension 684 passed. The direct ledger/CLI and mirror tests prove their respective boundaries, not the native marker-to-index-to-ledger chain. That integration proof remains Gate 23; no live ancestry claim is made.

Before the exported Python behavior was edited, Pyright LSP `textDocument/references` was run with each file opened in the workspace. It found the `LedgerStore.create_session` declaration plus its CLI, Hermes, Claude Code, and test references, and the `cmd_ledger` declaration plus its dispatcher reference. The implementation retains the existing signatures for those two APIs.

## Exact modified APIs

- `brainstem/prime-extension/src/ledger-mirror.ts` — exported `MirrorOptions` now accepts optional `parentSessionId?: string`, a HOST session identity. Both `mirrorEventSync(options)` and `mirrorEvent(options)` append `--parent-session <HOST id>` to `ledger init` only when it is a non-empty string. Existing callers that omit it retain the old argv.
- `brainstem/prime-extension/src/ledger-mirror.ts` — the async init cache now remembers the parent used for each session. A parent supplied after a parentless init re-runs init; a different later parent also re-runs init so the CLI can reject the conflict; omission after an established parent does not re-init or erase ancestry.
- `src/second_brain/cli.py` — `brainctl ledger init` adds optional `--parent-session`, explicitly defined as a HOST session id. The handler rejects direct self-parenting and ancestry that resolves back to the child.
- `src/second_brain/ledger.py` — new `resolve_root_parent_session_id(home, parent_host_session_id) -> str` opens only the deterministic parent ledger in SQLite `mode=ro`, selects only the canonical row keyed by `sha256(HOST parent id)`, verifies that row is owned by the supplied HOST id, returns its established `root_parent_session_id`, or returns the parent's internal hash when that owned row has no root. A missing, unreadable, unowned, or non-canonical parent is rejected rather than guessed from project/global history.
- `src/second_brain/ledger.py` — `LedgerStore.create_session(identity)` keeps its existing signature but is now atomic and idempotent. It verifies that the identity owns the ledger, rejects non-canonical or self-referential roots, inserts once, preserves the established identity on repeats, fills a previously-null root, never replaces an established root with null, and rejects a different non-null root. Only `last_active_at` and a previously-null root can change on repeat registration.

`BrainSessionIdentity.root_parent_session_id` remains the sole INTERNAL canonical root field. `--parent-session` and `MirrorOptions.parentSessionId` remain HOST-facing inputs; raw HOST ids are not stored in the root column.

## Deterministic regression coverage authored

`tests/test_ledger.py`:

- `test_cli_ledger_init_persists_canonical_ancestry_and_resume` creates root A, child B, and grandchild C in a scratch `tmp_path` home. It asserts B and C both store `sha256(A)`; reading B to initialize C leaves B's ledger bytes unchanged; resuming B without a parent and repeating with A preserve B's durable identity; resolving A through descendant C is rejected as a cycle; and reparenting B to independent root D is rejected without changing B.
- `test_cli_ledger_parent_resolution_rejects_unowned_parent_without_writes` asserts that an absent parent and a parent ledger whose canonical row is not owned by the supplied HOST id are rejected before a child ledger is created. It byte-compares the deliberately malformed scratch parent before and after resolution to pin read-only behavior.

`brainstem/prime-extension/tests/ledger-mirror.test.ts`:

- `sync and async init forward the HOST parent session identity` pins exact sync and async `ledger init` argv, including compatibility with `--cwd`.
- `a parent arriving after parentless init is validated once; later omission does not re-init` pins cache behavior for late ancestry, resume without ancestry, and conflicting ancestry validation.
- Existing no-parent argv tests remain unchanged and continue to specify omission of `--parent-session`.

All fixture mutations are under test scratch homes. No production ledger, telemetry, or provider state is touched.

## Compatibility and rollback

- Existing no-parent TypeScript and CLI callers are source- and argv-compatible.
- Existing session identity, project, creation time, lifecycle status, pin, schema version, segment, and established ancestry survive repeated init.
- Rollback is code-only: remove the optional mirror/CLI argument and restore the prior session registration statement. No schema rollback or data migration is required because the existing `root_parent_session_id` column is reused.
- Historical null ancestry remains null; this change deliberately does not rewrite the 164 audited production-derived rows.

## Unresolved risk / Main-owned proof

1. `index.ts` now supplies `workerParentSessions.get(session)` as `parentSessionId` at its mirror callsites. The marker-to-index-to-ledger path still needs native integration proof; direct mirror tests do not prove the entire chain.
2. Converged Python/Vitest, TypeScript and changed-file ESLint pass. Pyright remains 85 errors; exact baseline comparisons and exceptions are in `07-regression-delta.md`.
3. A child init now rejects a parent whose canonical ledger row does not yet exist. This prevents false cross-root attribution during out-of-order initialization; the existing mirror's single bounded retry may recover a normal first-init race, but live OMP ordering still requires Main's integration proof.
4. Historical 164/164 null roots cannot be credited as descendant-accounting evidence. Any backfill would require separate provenance and authorization and is intentionally absent here.
5. No live provider, account, deployment, or paired host smoke was performed.
6. The legacy comment in `src/second_brain/adapters/claude_code.py` still says `INSERT OR REPLACE`; it is intentionally unchanged documentation debt outside this frozen source patch, not a description of the new transaction. Runtime now preserves established ancestry and rejects conflicts.


## Final reviewed C2 supersession

Final source: `c106865d9ae620e531b64fdaaf448a1b76e160fb`; qualified source: **NONE**. This supersedes C1 source/count claims above, not their historical observations. Native ancestry now comes only from bounded native transcript ancestry; prompt markers cannot redirect root attribution. The generated dispatch marker precedes verbatim user task text. Usage without required session identity is unknown, not factual cap usage.

Final full Python **1825 passed**; Vitest **688 passed**; TypeScript and changed-file ESLint pass. Pyright remains **85 errors**, Ruff **434 findings**. Doctor **19/0/0**. C2 artifacts: `pytest-reviewed-c2.xml`, `vitest-reviewed-c2.json`, `pyright-reviewed-c2.json`, `ruff-reviewed-c2.json`, `doctor-reviewed-c2.txt`, and `frozen-c2-identity.json`. The real CLI/SQLite ancestry smoke changes the forged unrelated root to the expected native root; missing/null identity smoke returns ACCOUNTING_UNAVAILABLE while valid 400001-token usage remains HARD. These local harnesses are not provider-backed native qualification.

No final default deployment or live qualification arm. Eligible natural successes remain **0/20**. Native result framing, populated-governor latency, mandatory type checking, final deployment/Gate23 and paired economics remain HOLD. Earlier latency/telemetry measurements are C1 historical measurements, not newly measured C2 live performance/schema proof.
