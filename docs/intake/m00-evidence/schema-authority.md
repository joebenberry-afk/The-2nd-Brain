# M00.3 #2b schema-authority increment — reserved names, registration, one version source

**Subject:** candidate worktree `.worktrees/m00.3-producer-guard`.
**Production activation: NOT PERFORMED.** Every case runs on disposable homes under the OS temp dir.

This increment closes four of the open items the independent review of the earlier `#2b` work left
(`outputs/reports/schema-bootstrap-20260921/QUALIFICATION.md`, "Open — architectural debt"). It does
**not** close `#2b`: the store-as-second-transition-authority item and the test-strength items remain
open, and they are listed at the end rather than glossed.

## 1. Reserved names do not establish ownership

The hole, restated: a *name* was treated as ownership. `events_fts` and its five shadow tables were
ignored by name, so a database containing only such an object was classified `empty`, the ledger then
created its own tables, and `reindex()` — which begins with `DROP TABLE IF EXISTS events_fts` — could
remove somebody else's table.

The rule now:

- `brain_schema.reserved_objects(conn, source)` treats a reserved name as ours only when the object
  matches the definition the authority derives from the **registered** DDL, materialised in an
  in-memory reference database: the index itself must be a real fts5 virtual table whose columns equal
  the registered ones, and its shadow names count only beside such a verified index (SQLite refuses to
  create the index while a shadow name is taken, so a shadow name next to a verified index is that
  index's own object).
- Anything else keeps the name, is reported in `identity.unknown_tables` (surfaced as a new
  `DatabaseIdentity.reserved` field for the verified set), and `ensure()` refuses it by name. Nothing
  is adopted, renamed or deleted.
- `LedgerStore._schema_state` no longer carries its own `events_fts` string test; it asks the authority.

## 2. Registration is import-time, not open-time

`ledger` and `vmem` now call `brain_schema.register(...)` at module import, immediately after the DDL
they own, instead of during `_prepare_schema` / `_init_db`. This was not cosmetic: the authority's
derived-shape caches are filled on first use, so a process that opened only one store first could
compute a canonical shape set that omitted the other component — which is exactly how an adopted
predecessor database came to be refused. The import-time registration removes the dependence on open
order, and the adoption cases pass again for that reason, not by loosening a rule.

## 3. VMem's additive columns moved inside the authority's transaction

The four additive columns were applied *after* `ensure()` committed, unversioned and outside the write
reservation. They are now applied inside the same `BEGIN IMMEDIATE` as the adoption decision, so an
interrupted open rolls back to the shape it started from instead of leaving a half-migrated table. The
registered canonical shape for `vmem` is already the post-migration shape, so the authority still
recognises the genuine 19-column header-less predecessor.

## 4. One version source per namespace

- Database schema version: `ledger.LEDGER_SCHEMA_VERSION` is now an alias of
  `brain_schema.SCHEMA_VERSION` (the authority that owns the number and writes it into
  `ledger_meta`), instead of a second literal.
- `contracts.LEDGER_SCHEMA_VERSION` is a **different namespace** — the header *envelope* protocol
  version (1), validated by `read_ledger_header` — and is now documented as such, with the
  compatibility statement that the two numbers describe different things and are not required to
  agree. Its behaviour and its tests are unchanged.

## 5. `schema_dump` compares what actually defines a schema

The equivalence fingerprints now include each table's stored SQL, primary-key flags, foreign keys and
triggers, plus a `reserved` section for the verified reserved objects. Previously the dump omitted
foreign keys, triggers, table SQL, primary-key flags and all FTS objects, so "the two orders converge"
was weaker than it read. The existing convergence, idempotency and case-4 assertions get the stronger
comparison automatically.

## 5b. The authority decides whether a component may migrate

`LedgerStore._schema_state` used to decide for itself whether an unfamiliar layout was a predecessor
it could migrate or a shape it had to refuse — including the version-2 header whose `events` table
lacks `prev_hash`, a database the authority called `canonical` while the store migrated it. The
decision now comes from the authority:

- `brain_schema.component_shape(conn, component)` compares the live tables against shapes derived
  from the **registered** DDL (`table_info` plus `foreign_key_list`, not a second hand-written
  expectation) and returns `current` / `additive` / `unsupported`, naming the absent tables, the
  missing registered columns, the unregistered columns and the tables altered in any other way.
- `LedgerStore` asks for that shape and carries out only the transition it was told to make: the
  hash-chain transition runs when the authority reports exactly the registered column the chain
  added as missing (or when a version-1 header already carries the current shape), and every
  other difference is refused as an unsupported layout to preserve.

New cases (`tests/test_brain_schema.py`):

- `test_component_shape_names_the_chain_transition_the_authority_allows` — a current database with
  `prev_hash` removed is reported `additive` with exactly `{"events": ("prev_hash",)}` missing, and
  opening performs the transition and ends at the canonical state.
- `test_component_shape_refuses_a_shape_the_authority_cannot_name` — an extra column is reported
  `unsupported` with that column named, and opening refuses it rather than repairing it.

## 6. Inherited gate failures repaired

`ruff check src tests` and `pyright` were **not** clean on the candidate before this work, in files this
change does not otherwise touch: four `E501` line-length errors (`src/second_brain/jit.py:251,261`,
`src/second_brain/worker_recovery.py:800,919`) and four `object`-vs-`str` argument errors in
`tests/test_writer_admission.py` (the typed `_response_text` helper the file already provides is now
used at those sites). Both gates are clean on the current bytes. These are recorded as gate repairs,
not as behavioural changes.

## 7. Evidence

| Artifact | Command | Result |
| --- | --- | --- |
| `pytest-schema-neighborhood.txt` | `pytest tests/test_brain_schema.py tests/test_ledger.py tests/test_vmem.py tests/test_vmem_coverage.py tests/test_vmem_live_integration.py tests/test_governor.py tests/test_backup.py tests/test_migrations_property.py tests/test_db.py tests/test_writer_admission.py tests/test_cleanup_t61.py tests/test_contracts.py tests/test_worker_recovery.py -v` | **398 passed** (the 284-test set named in the earlier qualification plus the new cases and the adjacent worker suites) |
| the same set before the transition work | as above, without the last four files | **288 passed** |
| `ruff check src tests` | candidate venv | `All checks passed!` |
| `pyright` | candidate venv | `0 errors, 0 warnings, 0 informations` |
| `used == 65` witness | `tests/test_governor.py` inside the runs above | untouched and passing (not duplicated here) |

New cases in `tests/test_brain_schema.py`:

- `test_case_6b_a_reserved_name_does_not_establish_ownership` — a foreign `events_fts` with its own row
  is refused by name (`unidentified existing tables`), the row survives, the ledger's tables are not
  created behind the refusal, and the state is `unknown-tables` rather than `empty`.
- `test_case_6c_a_shadow_table_name_does_not_establish_ownership` — a shadow name without a verified
  parent is refused, and its row survives.
- `test_case_6d_the_ledgers_own_index_is_recognised_and_reindexed` — the positive control: the object
  the ledger itself created stays ours, `reindex()` is idempotent, and the index appears in the dump.

### Mutation sensitivity

Reverting the ownership rule to the old name-only ignore in `brain_schema.classify` (byte-verified
restore afterwards, `sha256` `f76ae5d4…` before and after):

```
FAILED tests/test_brain_schema.py::test_case_6b_... - Failed: DID NOT RAISE BrainError
FAILED tests/test_brain_schema.py::test_case_6c_... - sqlite3.OperationalError: fts5: error creating
    shadow table events_fts_data: table 'events_fts_data' already exists
2 failed, 13 passed
```

The two new cases are sensitive to exactly the rule they qualify; the other thirteen are unaffected.

## 8. Still open in #2b (narrowed debt, not closed)

1. **Test strength still short of the claims** (`schema_dump` is stronger now, and the authority
   decides the transition, but): case 4's fixture supplies the complete base DDL rather than a strict
   prefix; case 5 never reads the object through VMem's public reader; case 7 uses two threads rather
   than genuinely competing first opens in separate *processes*; and idempotency is proven
   structurally without a write witness distinguishing a one-time adoption write from a subsequent
   no-op reopen.
2. **`vmem`'s additive columns are inside the transaction but still applied by the component**, not
   chosen by the authority. The authority's registered shape includes them and now reports the
   difference via `component_shape`, so the two agree; the store is still the one that applies them.
