# V2-A Trusted Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrofit the existing local semantic-memory retrieval path so only integrity-verified immutable canonical snapshots can be ranked, packetized, and delivered, while preserving the current SQLite/Markdown architecture and shadow/advisory rollout.

**Architecture:** Keep Markdown files as the canonical source, extend the existing SQLite schema with complete per-version manifests and normalized tag state, and add one in-process trusted pipeline between the existing hybrid discovery and AutoInject packet assembly. `hybrid_retrieval.py` returns bounded ID-only discovery pages; `retrieval_pipeline.py` owns consolidation, the fixed trust gate, raw-byte freshness checks, verified snapshots, ranking, and diagnostics; `autoinject.py` owns packet and delivery state. No daemon, remote service, vector package, or second retrieval stack is introduced.

**Tech Stack:** Python 3.11 standard library (`sqlite3`, `hashlib`, `json`, `unicodedata`, `tempfile`, `os`), SQLite migrations, Markdown canonical files, pytest/Hypothesis, Ruff, Pyright, and the existing labeled retrieval benchmark.

## Global Constraints

- `9a9eeff916efbe0ff68cd8c0355820fdfbbb6a59` is the frozen semantic and architectural authority; do not redesign, weaken, or broaden V2-A.
- `8427dea` is a docs-only descendant containing the approved Section 8 opening Markdown fence; it has no semantic design delta.
- Markdown remains the canonical source; SQLite manifests and indexes are governed/derived state, never a second canonical source.
- Retrofit the current `semantic.py` → `hybrid_retrieval.py` → `autoinject.py` path; do not add a parallel retrieval service, daemon, remote sink, vector dependency, or domain-scope contract.
- The only semantic payload fields are `body`, `canonical_created_at`, `grade`, `id`, `project`, `scope`, `status`, `tags`, `title`, and `version`; `schema_version` is not a payload field.
- Canonical tags normalize with NFC, casefolding, comma/Unicode-whitespace separators, invalid-token rejection, deduplication, and lexical sorting; SQLite stores the normalized tuple as one deterministic comma-separated string in `memories.tags`, `memory_versions.tags`, and `memory_index.tags`.
- A current `memory_versions` row is mandatory, including version 1; legacy unknown `version_created_at` values remain NULL rather than receiving invented timestamps.
- Filesystem size, mtime, and optional file identity are cache signals only. Every trust assessment reads bounded canonical bytes and computes a process-local raw-byte SHA-256 before any verification-cache lookup.
- The semantic identity hash is `semantic-payload-v1(canonical payload)`; raw-byte hashes are never persisted as identity evidence.
- The exact first-failure order is `PROJECT_IDENTITY_UNRESOLVED`, `PROJECT_SCOPE_MISMATCH`, `DOMAIN_IDENTITY_UNSUPPORTED`, `VERSION_MANIFEST_MISSING`, `VERSION_MANIFEST_MISMATCH`, `INDEX_VERSION_STALE`, `INDEX_METADATA_MISMATCH`, `HASH_ALGORITHM_UNSUPPORTED`, `CANONICAL_MISSING`, `CANONICAL_UNREADABLE`, `MALFORMED_CANONICAL`, `CANONICAL_IDENTITY_MISMATCH`, `CANONICAL_HASH_MISMATCH`, `STATUS_INELIGIBLE`, `EVIDENCE_INSUFFICIENT`, `CONTRADICTION_UNRESOLVED`.
- Discovery scores, raw index values, summaries, vector payloads, and raw rows are never trusted ranking or packet content.
- Ranking and packet construction receive only frozen verified snapshots; no post-gate SQLite or filesystem reread may supply model-visible fields.
- Delivery rows distinguish `prepared`, `delivered`, and `failed`/retryable; only `delivered` suppresses a future retry.
- The legacy `brain_packet_delivered` event remains compatibility-only and unchanged; V2 lifecycle telemetry uses `brain_packet_prepared`, `brain_packet_delivery_committed`, and `brain_packet_delivery_failed`.
- V2-A starts and remains in shadow/advisory mode. No host context mutation or activation switch is part of this implementation.
- Correctness gates are absolute. Cold/warm measurements are reported without inventing performance thresholds or changing metrics to hide negative results.
- No Constitution files, unrelated cleanup, skill promotion, RTD activation, or `.superpowers/sdd/.gitignore` changes are in scope.
- Optional Brain dogfooding is allowed only after evidence capture and only as an observation of the committed shadow/advisory path; Brain-derived retrieval, labels, thresholds, or telemetry must never become evidence for the independent verifier or promotion gate.
- Implementation follows TDD: write each observable contract test, run it red for the intended missing behavior, implement the smallest passing change, rerun focused tests, then commit.
- On this Windows workstation, run Python with `PYTHONHOME` and `PYTHONPATH` unset:

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q <focused-tests>
```

---

## File and ownership map

| Path | Ownership in V2-A |
|---|---|
| `src/second_brain/semantic.py` | Strict canonical Markdown codec; normalized tags; semantic/raw hashing; immutable staged version writes; manifest backfill; verified derived-index refresh; compatibility wrappers for legacy search/read APIs. |
| `src/second_brain/migrations/0011_trusted_retrieval.sql` | Transactional schema extension: `memories.tags`, complete `memory_versions` manifest columns, `memory_index.hash_algorithm`, and explicit delivery state columns. |
| `src/second_brain/hybrid_retrieval.py` | ID-only exact, FTS title/body, linear, and optional vector discovery pages with deterministic cursors; no trusted content or final scores. |
| `src/second_brain/retrieval_pipeline.py` | New trusted orchestration: request identity, unique consolidation, refill bounds, all 16 refusal codes, verification cache, immutable snapshots, contradiction gate, ranking, and diagnostics. |
| `src/second_brain/autoinject.py` | Routes model-facing retrieval through the trusted pipeline; role filtering from snapshot tags; canonical packet materialization; dedup-before-budget; prepared/commit/fail delivery calls and compatibility telemetry. |
| `src/second_brain/contracts.py` | `TRUST_GATE_REJECTED`, delivery-state contract, V2 lifecycle event names, and backward-compatible delivery record parsing. |
| `src/second_brain/telemetry.py` | Known-kind allowlist for the three V2 delivery events and trusted retrieval telemetry validation. |
| `config/retrieval.toml` | Bounded trusted page/refill/read settings; existing legacy scoring settings remain available to legacy search only. |
| `brainstem/telemetry/SCHEMA.md` | Privacy-safe fields, lifecycle meanings, and explicit legacy-event compatibility semantics. |
| `tests/test_trusted_retrieval.py` | Canonical codec, tag normalization, trust-gate matrix, snapshot/cache, discovery/refill, ranking, and packet isolation tests. |
| `tests/test_trusted_retrieval_recovery.py` | Migration, backfill, staged filesystem/SQLite/index failure, orphan, reindex, backup/restore, and interruption tests. |
| `tests/test_trusted_retrieval_independent.py` | Fresh-process/read-only verifier that re-derives canonical hashes, manifest/index agreement, packet exclusion, and telemetry privacy without importing the trusted pipeline. |
| `tests/test_semantic.py` | Existing semantic API expectations updated for immutable hash-covered metadata versions and explicit timestamp fields; legacy search tests retained. |
| `tests/test_memory_index.py` | Derived-index rebuild tests updated to reject unversioned edits and use semantic hashes/algorithms. |
| `tests/test_hybrid_retrieval.py` | Existing cascade compatibility tests plus ID-only discovery-page contracts. |
| `tests/test_autoinject.py` | Trusted packet, refusal reason, snapshot-only materialization, dedup-before-budget, and delivery-state integration tests. |
| `tests/test_contracts.py` | New reason/state/event serialization and delivered-only dedup tests. |
| `tests/test_telemetry.py` | New lifecycle kind validation and privacy-safe diagnostics tests. |
| `tests/test_retrieval_isolation.py` | Wrong-project, unresolved-project, exact-ID, and scope behavior updated for the trusted gate. |
| `tests/test_migrations_property.py` | Migration prefix/remainder, rollback, idempotency, and partial-backfill properties. |
| `tests/test_backup.py` | V2 schema backup/restore and post-restore backfill verification. |
| `proof/runner/retrieval_bench.py` | Existing labeled 100/1,000/10,000 corpus benchmark extended with legacy/trusted cold/warm runs and V2 diagnostics. |
| `tests/test_reconsolidation.py` | Legacy lazy-migration pending-list assertion updated to include schema 11; reconsolidation behavior remains unchanged. |

The current CLI and Hermes adapter files are not modified. Their existing shadow/advisory response boundaries remain outside the frozen implementation boundary; callers that can acknowledge a successful return may call the new `BrainLifecycle` commit method, while no Python path claims model visibility without that explicit acknowledgement.

## Cross-task interfaces

These names and types are fixed before implementation begins:

```python
# semantic.py
@dataclass(frozen=True)
class CanonicalPayload:
    id: str
    title: str
    scope: str
    project: str | None
    status: str
    grade: str
    canonical_created_at: str
    version: int
    tags: tuple[str, ...]
    body: str

@dataclass(frozen=True)
class CanonicalRead:
    payload: CanonicalPayload
    semantic_hash: str
    raw_byte_hash: str
    raw_size: int


def parse_canonical_bytes(data: bytes) -> CanonicalPayload: ...
def canonical_payload_bytes(payload: CanonicalPayload) -> bytes: ...
def semantic_payload_hash(payload: CanonicalPayload) -> str: ...
def normalize_tags(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]: ...
def read_canonical_bytes(path: Path, max_bytes: int) -> tuple[bytes, str]: ...

# hybrid_retrieval.py
@dataclass(frozen=True)
class DiscoveryCandidate:
    memory_id: str
    tier: RetrievalTier
    score_hint: float

@dataclass(frozen=True)
class DiscoveryCursor:
    tier: int
    offset: int

@dataclass(frozen=True)
class DiscoveryPage:
    candidates: tuple[DiscoveryCandidate, ...]
    next_cursor: DiscoveryCursor | None
    exhausted: bool
    vector_invoked: bool


def discover_page(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None,
    cursor: DiscoveryCursor | None,
    page_size: int,
    vector_searcher: Callable[[str, str | None], list[str]] | None = None,
) -> DiscoveryPage: ...

# retrieval_pipeline.py
class TrustFailureCode(StrEnum):
    PROJECT_IDENTITY_UNRESOLVED = "PROJECT_IDENTITY_UNRESOLVED"
    PROJECT_SCOPE_MISMATCH = "PROJECT_SCOPE_MISMATCH"
    DOMAIN_IDENTITY_UNSUPPORTED = "DOMAIN_IDENTITY_UNSUPPORTED"
    VERSION_MANIFEST_MISSING = "VERSION_MANIFEST_MISSING"
    VERSION_MANIFEST_MISMATCH = "VERSION_MANIFEST_MISMATCH"
    INDEX_VERSION_STALE = "INDEX_VERSION_STALE"
    INDEX_METADATA_MISMATCH = "INDEX_METADATA_MISMATCH"
    HASH_ALGORITHM_UNSUPPORTED = "HASH_ALGORITHM_UNSUPPORTED"
    CANONICAL_MISSING = "CANONICAL_MISSING"
    CANONICAL_UNREADABLE = "CANONICAL_UNREADABLE"
    MALFORMED_CANONICAL = "MALFORMED_CANONICAL"
    CANONICAL_IDENTITY_MISMATCH = "CANONICAL_IDENTITY_MISMATCH"
    CANONICAL_HASH_MISMATCH = "CANONICAL_HASH_MISMATCH"
    STATUS_INELIGIBLE = "STATUS_INELIGIBLE"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    CONTRADICTION_UNRESOLVED = "CONTRADICTION_UNRESOLVED"

@dataclass(frozen=True)
class TrustedRetrievalRequest:
    query: str
    project_id: str | None
    is_delta: bool = False

@dataclass(frozen=True)
class TrustRefusal:
    memory_id: str
    code: TrustFailureCode
    explanation: str

@dataclass(frozen=True)
class EligibleCandidate:
    memory_id: str
    version: int
    canonical_hash: str
    hash_algorithm: str
    canonical_payload: CanonicalPayload
    provenance_envelope: tuple[str, ...]
    verification_stamp: tuple[str, str, str]
    discovery_metadata: tuple[int, int, int]
    decision_value: int

@dataclass(frozen=True)
class RetrievalDiagnostics:
    discovered_count: int
    unique_candidate_count: int
    scanned_count: int
    eligible_count: int
    ranked_count: int
    stat_checks: int
    raw_byte_hash_checks: int
    semantic_hash_checks: int
    canonical_cache_hits: int
    canonical_parses: int
    scan_limit_hit: bool
    query_mode: str
    refusal_counts: dict[str, int]

@dataclass(frozen=True)
class TrustedRetrievalResult:
    eligible: tuple[EligibleCandidate, ...]
    refusals: tuple[TrustRefusal, ...]
    diagnostics: RetrievalDiagnostics


def retrieve_trusted(
    home: Path | str,
    request: TrustedRetrievalRequest,
    *,
    vector_searcher: Callable[[str, str | None], list[str]] | None = None,
) -> TrustedRetrievalResult: ...
```

`decision_value` is a bounded count captured from the same verified SQLite read snapshot. It is not discovery metadata, canonical payload, or packet content; it exists only so an already-measured `successful_retrieval_count` can be used without a post-gate read. No synthetic decision value is created when the field is absent.

### Shared test-fixture contracts

`tests/test_trusted_retrieval.py` defines `_canonical_text(extra="")` as a
literal valid V1-compatible Markdown document with every required field and a
non-empty body; it never calls the parser or writer under test. Its
`_seed_current(home, title, body, **kwargs)` helper calls the existing semantic
add path and the existing one-step curate path, while `_inject(home, task,
**kwargs)` constructs `BrainLifecycle(home)` and passes explicit project,
agent, role, session, branch, and delta values to `prepare_injection`.
`_delivery_states(home, delivery_ids)` reads only the delivery `state` column
through a fresh read-only SQLite connection. Delivery tests keep the lifecycle
object that prepared a packet so the explicit commit/fail methods operate on
its `last_delivery_ids`; no helper silently commits a delivery.

The refusal tests define `build_fault_case(home, fault_name)` beside the
`TRUST_FAILURE_CASES` table. It returns
`(TrustedRetrievalRequest, candidate_id)` after creating one valid governed
candidate and applying only the named fault mutation.

---

## Dependency-safe implementation phases

### Task 1: Add strict canonical payload and tag codec

**Dependencies:** None.

**Files:**
- Modify: `src/second_brain/semantic.py` near `FRONTMATTER_FIELDS`, `_render_file`, `_body_text`, and `_file_hash`.
- Create: `tests/test_trusted_retrieval.py` canonical codec section.
- Modify: `tests/test_semantic.py` only where the existing writer helper must accept optional tags.

**Interfaces:**
- Consumes: Existing `SCOPES`, `STATUSES`, `GRADES`, `canonical_json`, and V1 writer format.
- Produces: `CanonicalPayload`, `CanonicalRead`, `normalize_tags`, `parse_canonical_bytes`, `canonical_payload_bytes`, `semantic_payload_hash`, and bounded raw-byte reading for Tasks 2–6.

- [ ] **Step 1: Write failing canonical and tag tests.** Use real bytes, not parser mocks. The fixture must prove syntactic variants map to one payload/hash and that forbidden fields fail before any hash is returned.

```python

def test_semantic_hash_ignores_syntax_but_preserves_body_spaces():
    lf = (
        "---\n"
        "title:  T\n"
        "id: mem-000000000001\n"
        "scope: project\n"
        "project: p\n"
        "status: current\n"
        "grade: TESTED\n"
        "version: 1\n"
        "created_at: 2026-08-30T00:00:00+00:00\n"
        "---\n"
        "body  with  spaces\n\n"
    ).encode()
    crlf_bom = ("\ufeff" + lf.decode().replace("\n", "\r\n")).encode()

    first = semantic.parse_canonical_bytes(lf)
    second = semantic.parse_canonical_bytes(crlf_bom)

    assert first == second
    assert semantic.semantic_payload_hash(first) == semantic.semantic_payload_hash(second)
    assert first.body == "body  with  spaces"


def test_tags_normalize_casefold_separators_and_duplicates():
    assert semantic.normalize_tags(" Worker,  wOrKeR\u00a0VERIFIER ") == (
        "verifier",
        "worker",
    )

    # NFC happens before the ASCII grammar check; composed non-ASCII tags
    # remain invalid rather than being silently discarded.
    with pytest.raises(BrainError, match="tag"):
        semantic.normalize_tags("e\u0301")


def test_unprefixed_unknown_and_schema_version_are_malformed():
    raw = _canonical_text(extra="schema_version: 1")
    with pytest.raises(BrainError, match="schema_version"):
        semantic.parse_canonical_bytes(raw.encode())

    raw = _canonical_text(extra="future_field: value")
    with pytest.raises(BrainError, match="future_field"):
        semantic.parse_canonical_bytes(raw.encode())


def test_x_extensions_are_ignored_and_invalid_tags_refuse():
    payload = semantic.parse_canonical_bytes(_canonical_text(extra="x-source: import").encode())
    assert payload.tags == ()
    with pytest.raises(BrainError, match="tag"):
        semantic.normalize_tags("worker+bad")
```

The helper `_canonical_text` must emit all required fields and a non-empty body; it must not call the implementation under test.

- [ ] **Step 2: Run the focused tests and confirm the intended red failure.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "semantic_hash or tags_normalize or unprefixed_unknown"
```

Expected: FAIL because the new codec symbols do not exist; no unrelated fixture or collection error is acceptable.

- [ ] **Step 3: Implement the smallest strict codec.** Normalize one optional BOM, CRLF/CR to LF, NFC-normalize text, parse a single frontmatter block with unique `key: value` lines, reject unknown unprefixed keys, ignore only `x-*`, require the ten approved semantic fields after `created_at` normalization, and remove only terminal LF padding from the body. Parse `version` as a positive integer and validate existing scopes/statuses/grades. Normalize tags by NFC + casefold, split on comma or Unicode whitespace, accept only `[a-z0-9][a-z0-9._/-]{0,63}` tokens after normalization, deduplicate, and sort. Encode the payload with existing canonical JSON and hash the UTF-8 bytes with SHA-256. Reject files over exactly `1_048_576` bytes from `read_canonical_bytes` as unreadable-bound input; this is a safety bound, not a performance gate.

- [ ] **Step 4: Run codec tests and the existing semantic round-trip tests.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "semantic_hash or tags_normalize or unprefixed_unknown"
.venv\Scripts\python.exe -m pytest -q tests/test_semantic.py::test_add_read_roundtrip tests/test_semantic.py::test_add_validation
```

Expected: PASS; the V1 writer remains byte-compatible when tags are empty.

- [ ] **Step 5: Commit the codec boundary.**

```powershell
git add src/second_brain/semantic.py tests/test_trusted_retrieval.py tests/test_semantic.py
git commit -m "feat(v2): add canonical payload codec"
```

### Task 2: Add schema migration and deterministic manifest backfill

**Dependencies:** Task 1.

**Files:**
- Create: `src/second_brain/migrations/0011_trusted_retrieval.sql`.
- Create: `tests/test_trusted_retrieval_recovery.py` migration/backfill section.
- Modify: `tests/test_migrations_property.py` and `tests/test_backup.py`.
- Modify: `tests/test_autoinject.py`, `tests/test_crossmodel.py`, `tests/test_episodes.py`, `tests/test_memory_index.py`, `tests/test_p4_persistence.py`, `tests/test_plasticity.py`, and `tests/test_reconsolidation.py` for schema-version expectations and migration-prefix assertions.

**Interfaces:**
- Consumes: Task 1 parser/hash/tag storage helpers and existing transactional `db.apply_migration`.
- Produces: complete manifest columns, `memories.tags`, `memory_index.hash_algorithm`, delivery state columns, `backfill_trusted_manifests(home) -> dict`, and `manifest_row(conn, memory_id, version)` for Tasks 3–7.

- [ ] **Step 1: Write failing schema/backfill tests.** Assert the physical schema and semantic behavior, not only migration version numbers.

```python

def test_v11_adds_tags_manifest_hash_and_delivery_state(brain_home):
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        memories = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        versions = {row[1] for row in conn.execute("PRAGMA table_info(memory_versions)")}
        index = {row[1] for row in conn.execute("PRAGMA table_info(memory_index)")}
        deliveries = {row[1] for row in conn.execute("PRAGMA table_info(deliveries)")}
    finally:
        conn.close()

    assert "tags" in memories
    assert {"scope", "project_id", "status", "evidence_grade", "tags",
            "canonical_created_at", "body_path", "file_hash", "hash_algorithm",
            "version_created_at"} <= versions
    assert "hash_algorithm" in index
    assert {"state", "prepared_at", "committed_at", "failure_code", "retryable"} <= deliveries


def test_backfill_uses_canonical_hash_and_is_idempotent(brain_home):
    mid = semantic.add_memory(brain_home, "T", "body", project_id="p", tags="Worker,worker")
    first = semantic.backfill_trusted_manifests(brain_home)
    second = semantic.backfill_trusted_manifests(brain_home)
    assert first["valid"] >= 1
    assert second["changed"] == 0

    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute(
            "SELECT tags, file_hash, hash_algorithm FROM memory_versions "
            "WHERE memory_id = ? AND version = 1", (mid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["tags"] == "worker"
    assert row["hash_algorithm"] == "semantic-payload-v1"
    assert row["file_hash"] == semantic.semantic_payload_hash(
        semantic.parse_canonical_bytes((brain_home / "memory/semantic" / f"{mid}.md").read_bytes())
    )


def test_backfill_skips_malformed_memory_and_keeps_valid_memory(brain_home):
    good = semantic.add_memory(brain_home, "good", "good body")
    bad = semantic.add_memory(brain_home, "bad", "bad body")
    (brain_home / "memory/semantic" / f"{bad}.md").write_text("broken", encoding="utf-8")

    report = semantic.backfill_trusted_manifests(brain_home)

    assert report["refusal_counts"]["MALFORMED_CANONICAL"] == 1
    assert semantic.show_memory(brain_home, good)["row"]["memory_id"] == good
```

Add a migration interruption test that injects an exception during the SQL migration and asserts no `schema_version=11` row, no replacement table, and a successful clean retry. Add a property test that any applied migration prefix followed by 0011 either fully commits or leaves that prefix unchanged.

- [ ] **Step 2: Run the migration tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval_recovery.py -k "v11 or backfill" tests/test_migrations_property.py -k "prefix or migration"
```

Expected: FAIL on missing columns/helper; existing V1 migration tests must still collect.

- [ ] **Step 3: Implement `0011_trusted_retrieval.sql` transactionally.** Add `memories.tags TEXT NOT NULL DEFAULT ''`; rebuild `memory_versions` from the old table into a table with `memory_id`, `version`, `title`, `scope`, `project_id`, `status`, `evidence_grade`, `tags`, `canonical_created_at`, `body_path`, `file_hash`, `hash_algorithm`, `version_created_at`, and `change_note`; map old `created_at` to `canonical_created_at`, leave `version_created_at`, `file_hash`, and `hash_algorithm` unknown until backfill, and preserve old title/path/note values. Add `memory_index.hash_algorithm TEXT NOT NULL DEFAULT ''`. Add delivery `state`, `prepared_at`, `committed_at`, `failure_code`, and `retryable`; reclassify pre-V2 rows with non-null `delivered_at` as `prepared` with that timestamp in `prepared_at`, clear the suppressing delivery timestamp, and preserve all lineage fields. Keep SQL compatible with the existing one-migration transaction wrapper; do not add a down migration.

- [ ] **Step 4: Implement deterministic `backfill_trusted_manifests`.** Inspect only governed `memories.body_path` and existing `memory_versions` paths; never scan arbitrary Markdown files to adopt them. For each path, read bounded bytes, parse, normalize, calculate semantic hash, and atomically populate a complete manifest row. For current version 1, create the mandatory row with unknown legacy `version_created_at`; for legacy historical rows, preserve NULL version-commit time. Update `memories.tags` and rebuild `memory_index`/FTS only from verified snapshots. Leave malformed/missing rows stored but refused, leave unrelated valid memories usable, retain stale derived rows rather than blessing bad files, and return a deterministic report with `scanned`, `valid`, `changed`, `refusal_counts`, and `orphans`. A per-memory transaction prevents interruption from leaving half-populated manifests.

- [ ] **Step 5: Run focused migration, backup, and property tests green.** Update every existing schema-version expectation from 10 to 11 in `tests/test_autoinject.py`, `tests/test_crossmodel.py`, `tests/test_episodes.py`, `tests/test_memory_index.py`, `tests/test_p4_persistence.py`, `tests/test_plasticity.py`, and `tests/test_reconsolidation.py`; preserve migration-prefix ordering and test fresh create, reopen, migration idempotency, rollback/retry, malformed-file continuation, and backup/restore.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval_recovery.py -k "v11 or backfill or interruption" tests/test_migrations_property.py tests/test_backup.py
```

Expected: PASS, including fresh create, reopen, migration idempotency, rollback/retry, malformed-file continuation, and backup/restore.

- [ ] **Step 6: Commit schema and backfill.**

```powershell
git add src/second_brain/migrations/0011_trusted_retrieval.sql src/second_brain/semantic.py tests/test_trusted_retrieval_recovery.py tests/test_migrations_property.py tests/test_memory_index.py tests/test_backup.py tests/test_autoinject.py tests/test_crossmodel.py tests/test_episodes.py tests/test_p4_persistence.py tests/test_plasticity.py tests/test_reconsolidation.py
git commit -m "feat(v2): add trusted manifest migration"
```

### Task 3: Route every hash-covered write through immutable staged versioning

**Dependencies:** Tasks 1–2.

**Files:**
- Modify: `src/second_brain/semantic.py` in `add_memory`, `curate`, `supersede`, `_write_file_atomic`, `_sync_file_metadata`, `index_memory`, and `reindex_all`.
- Modify: `tests/test_semantic.py`, `tests/test_memory_index.py`.
- Add staged failure cases to `tests/test_trusted_retrieval_recovery.py`.

**Interfaces:**
- Consumes: `CanonicalPayload`, manifest schema, `normalize_tags`, and backfill report.
- Produces: one internal `_commit_version(...)` path used by new-memory, curate, and supersede; immutable `memory_versions` inserts; governed index refresh; orphan reporting.

- [ ] **Step 1: Write failing immutable-write tests.** Cover every hash-covered field explicitly and preserve V1 bytes.

```python
@pytest.mark.parametrize("change", ["title", "body", "scope", "project", "status", "grade", "tags"])
def test_hash_covered_change_creates_new_immutable_version(brain_home, change):
    mid = semantic.add_memory(brain_home, "title", "body", project_id="p", tags="worker")
    before = (brain_home / "memory/semantic" / f"{mid}.md").read_bytes()

    if change == "body":
        semantic.supersede(brain_home, mid, new_body="body changed", change_note="body")
    elif change == "title":
        semantic.supersede(brain_home, mid, new_title="title changed", change_note="title")
    elif change == "scope":
        semantic.supersede(brain_home, mid, new_scope="global", change_note="scope")
    elif change == "project":
        semantic.supersede(brain_home, mid, new_project_id="other", change_note="project")
    elif change == "status":
        semantic.curate(brain_home, mid, status="current")
    elif change == "grade":
        semantic.curate(brain_home, mid, grade="TESTED")
    else:
        semantic.supersede(brain_home, mid, new_tags="verifier", change_note="tags")

    assert semantic.show_memory(brain_home, mid)["row"]["current_version"] == 2
    assert (brain_home / "memory/semantic" / f"{mid}__v2.md").is_file()
    assert (brain_home / "memory/semantic" / f"{mid}.md").read_bytes() == before


def test_reindex_does_not_bless_unversioned_edit(brain_home):
    mid = semantic.add_memory(brain_home, "T", "original", project_id="p")
    path = brain_home / "memory/semantic" / f"{mid}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("original", "tampered"), encoding="utf-8")

    report = semantic.reindex_all(brain_home)

    assert report["refused"] >= 1
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        row = conn.execute("SELECT file_hash FROM memory_versions WHERE memory_id = ?", (mid,)).fetchone()
    finally:
        conn.close()
    assert row["file_hash"] != ""
    assert "tampered" not in semantic.show_memory(brain_home, mid)["row"].get("summary", "")
```

Add fault tests for publication failure before DB commit, DB failure after publication, and index-refresh failure after DB commit. The assertions must distinguish previous current version, unreferenced orphan, and authoritative committed version with stale derived index.

- [ ] **Step 2: Run the immutable-write tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_semantic.py -k "version or curate or supersede" tests/test_trusted_retrieval_recovery.py -k "publication or index or unversioned"
```

Expected: FAIL because curate still rewrites the current file and the manifest lacks complete version snapshots.

- [ ] **Step 3: Implement one `_commit_version` protocol.** Render the next complete canonical document, write a same-directory temporary file, flush and `os.fsync` it, parse/hash the temporary bytes, atomically rename it to the unique version path, then begin SQLite `IMMEDIATE`, verify the expected current version, insert the immutable manifest row, update current `memories` metadata including normalized `tags`/`body_path`, append sources, and commit. Before commit, keep the previous current pointer; after commit, refresh derived index from the verified snapshot outside the transaction and invalidate affected verification-cache entries. On pre-commit failure, remove the temporary/published file only when safe; if cleanup fails, report an orphan. On post-commit index failure, preserve the canonical file and manifest and mark retrieval undiscoverable/fail closed until rebuild. Never update a manifest row or adopt a plausible orphan during reindex.

- [ ] **Step 4: Update public write behavior without changing unrelated APIs.** `add_memory(..., tags=None)` writes normalized tags and version-1 manifest before derived indexing. `supersede` carries old metadata when omitted and accepts explicit new title/body/scope/project/tags; each call creates the next version. `curate` retains one-step grade validation and source/verification behavior, but any changed hash-covered status/grade/tag value creates a new version; `last_verified_at`, `strength`, and retrieval counters remain operational-only updates. Remove direct `_sync_file_metadata` mutation. Update `_version_created_at`/`history` to expose `canonical_created_at` and `version_created_at`; do not retain a fake legacy version timestamp.

- [ ] **Step 5: Make `index_memory` and `reindex_all` trust-aware.** They may write `memory_index`/FTS only from a parsed snapshot whose manifest identity and semantic hash already match. Store semantic hash in `file_hash`, `semantic-payload-v1` in `hash_algorithm`, and the normalized tag CSV in `tags`. A refusal increments the report and leaves the previous derived row untouched; it never replaces the manifest hash with the current file hash. Orphan scanning reports unreferenced `*.md` files only.

- [ ] **Step 6: Update existing semantic tests and run them green.** Replace in-place-curation assertions with version-file/current-version assertions, preserve old V1 bytes, assert contiguous manifest rows, and change timestamp assertions to `canonical_created_at`/nullable legacy `version_created_at`. Keep legacy `search_memories` summary behavior tested separately; only the trusted path excludes summaries.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_semantic.py tests/test_memory_index.py tests/test_trusted_retrieval_recovery.py -k "version or curate or supersede or index or reindex or publication"
```

- [ ] **Step 7: Commit immutable versioning.**

```powershell
git add src/second_brain/semantic.py tests/test_semantic.py tests/test_memory_index.py tests/test_trusted_retrieval_recovery.py
git commit -m "feat(v2): govern immutable semantic versions"
```

### Task 4: Add ID-only paged hybrid discovery

**Dependencies:** Task 1; Task 2 schema is required for current-version/project filters.

**Files:**
- Modify: `src/second_brain/hybrid_retrieval.py` beside `RetrievalTier` and `HybridCascadeRetriever`.
- Modify: `tests/test_hybrid_retrieval.py`.
- Add discovery tests to `tests/test_trusted_retrieval.py`.

**Interfaces:**
- Consumes: one caller-owned SQLite read connection, existing exact-ID pattern, FTS availability helper, and optional caller-supplied vector callback.
- Produces: `DiscoveryCandidate`, `DiscoveryCursor`, `DiscoveryPage`, and `discover_page`; legacy `HybridCascadeRetriever.retrieve` remains available to existing callers but is not used by trusted AutoInject.

- [ ] **Step 1: Write failing discovery-page tests.** Assert the returned objects cannot carry body/title/summary/raw rows and that all sources have fixed precedence.

```python

def test_discovery_page_is_id_only_and_excludes_summary_only_matches(brain_home):
    mid = semantic.add_memory(
        brain_home,
        "Canonical title",
        "canonical body",
        project_id="p",
        summary="secret summary phrase",
    )
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        conn.execute("BEGIN")
        page = hybrid_retrieval.discover_page(
            conn, "secret summary phrase", project_id="p", cursor=None, page_size=10
        )
    finally:
        conn.close()

    assert all(not hasattr(item, "body") for item in page.candidates)
    assert all(not hasattr(item, "summary") for item in page.candidates)
    assert mid not in {item.memory_id for item in page.candidates}
    assert page.candidates == ()


def test_duplicate_sources_keep_exact_then_lexical_precedence(brain_home):
    mid = semantic.add_memory(brain_home, "Exact and lexical", "body", project_id="p")
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        conn.execute("BEGIN")
        exact = hybrid_retrieval.discover_page(
            conn, mid, project_id="p", cursor=None, page_size=10
        )
    finally:
        conn.close()
    candidate = next(item for item in exact.candidates if item.memory_id == mid)
    assert candidate.tier is hybrid_retrieval.RetrievalTier.TIER_0_EXACT_REF
```

Add a vector callback test that returns only IDs and a test that a missing/empty FTS index falls back to ID-only linear pages without returning canonical text.

- [ ] **Step 2: Run discovery tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "discovery" tests/test_hybrid_retrieval.py
```

Expected: FAIL because `discover_page` and the new dataclasses do not exist; pre-existing cascade tests must remain runnable.

- [ ] **Step 3: Implement deterministic page producers.** Add exact-ID lookup against governed memory IDs, FTS pages over title/body columns only, linear fallback that uses title/body only for matching and discards text before returning, and optional vector IDs. Use `DiscoveryCursor(tier, offset)` to exhaust sources in `exact → FTS/lexical → linear → vector` order. The page size is validated and bounded. Do not call `semantic.search_memories` from this path because its legacy query includes summary and returns raw rows. Do not consult the process negative cache for trusted pages; a prior empty legacy result cannot suppress required refill.

- [ ] **Step 4: Preserve legacy cascade behavior and run tests green.** Existing `RetrievalMatch.raw_row` and `HybridCascadeRetriever.retrieve` remain only for legacy/discovery consumers. The trusted pipeline imports only `DiscoveryCandidate`/`DiscoveryPage`; no raw row crosses that boundary.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_hybrid_retrieval.py tests/test_trusted_retrieval.py -k "discovery or cascade or exact or vector"
```

- [ ] **Step 5: Commit paged discovery.**

```powershell
git add src/second_brain/hybrid_retrieval.py tests/test_hybrid_retrieval.py tests/test_trusted_retrieval.py
git commit -m "feat(v2): add id-only retrieval pages"
```

### Task 5: Implement the fixed trust gate, refill pipeline, and raw-byte verification cache

**Dependencies:** Tasks 1–4.

**Files:**
- Create: `src/second_brain/retrieval_pipeline.py`.
- Modify: `src/second_brain/semantic.py` only for bounded read/cache invalidation hooks and trusted config fields.
- Modify: `tests/test_trusted_retrieval.py` and `tests/test_retrieval_isolation.py`.

**Interfaces:**
- Consumes: `DiscoveryPage`, manifest/index schema, strict parser/hash functions, and existing project-resolution intent values.
- Produces: `TrustFailureCode`, `TrustRefusal`, `EligibleCandidate`, `RetrievalDiagnostics`, `TrustedRetrievalResult`, `VerificationCache`, and `retrieve_trusted`.

- [ ] **Step 1: Write the complete refusal matrix before production code.** Use one parametrized test per code plus combined-fault tests. The fixture mutates only the named layer and recomputes dependent fields when the case is intended to reach a later code.

| Code | Red-test fault |
|---|---|
| `PROJECT_IDENTITY_UNRESOLVED` | Request uses unresolved `default`/`unknown` identity for a project-scoped candidate. |
| `PROJECT_SCOPE_MISMATCH` | Current governed candidate belongs to another project. |
| `DOMAIN_IDENTITY_UNSUPPORTED` | Candidate scope is `domain`; no domain identity contract exists. |
| `VERSION_MANIFEST_MISSING` | Delete the current `(memory_id, version)` manifest row. |
| `VERSION_MANIFEST_MISMATCH` | Alter manifest path/version/required metadata against `memories`. |
| `INDEX_VERSION_STALE` | Change only `memory_index.current_version` from the current pointer. |
| `INDEX_METADATA_MISMATCH` | Change only index title/tags/path/project metadata with version unchanged. |
| `HASH_ALGORITHM_UNSUPPORTED` | Set manifest algorithm to `raw-sha256` or empty after structural fields are present. |
| `CANONICAL_MISSING` | Remove the governed canonical path. |
| `CANONICAL_UNREADABLE` | Make the path a directory or inject a bounded read `OSError`. |
| `MALFORMED_CANONICAL` | Write invalid UTF-8, duplicate keys, missing fence, or invalid value syntax. |
| `CANONICAL_IDENTITY_MISMATCH` | Write a valid document whose title/id/version/tags differ from the manifest without updating its hash. |
| `CANONICAL_HASH_MISMATCH` | Write a valid document with identical identity fields but changed body and unchanged manifest hash. |
| `STATUS_INELIGIBLE` | Govern an `archived`/`superseded` current version with otherwise valid identity/hash. |
| `EVIDENCE_INSUFFICIENT` | Use `REJECTED`, or an unverified candidate/delta grade outside the existing tested/verified policy. |
| `CONTRADICTION_UNRESOLVED` | Two eligible current snapshots share a normalized title but have different canonical bodies. |

```python

TRUST_FAILURE_CASES = (
    ("unresolved_project", TrustFailureCode.PROJECT_IDENTITY_UNRESOLVED),
    ("wrong_project", TrustFailureCode.PROJECT_SCOPE_MISMATCH),
    ("domain_scope", TrustFailureCode.DOMAIN_IDENTITY_UNSUPPORTED),
    ("missing_manifest", TrustFailureCode.VERSION_MANIFEST_MISSING),
    ("manifest_mismatch", TrustFailureCode.VERSION_MANIFEST_MISMATCH),
    ("stale_index_version", TrustFailureCode.INDEX_VERSION_STALE),
    ("index_metadata_mismatch", TrustFailureCode.INDEX_METADATA_MISMATCH),
    ("unsupported_algorithm", TrustFailureCode.HASH_ALGORITHM_UNSUPPORTED),
    ("missing_file", TrustFailureCode.CANONICAL_MISSING),
    ("unreadable_file", TrustFailureCode.CANONICAL_UNREADABLE),
    ("malformed_file", TrustFailureCode.MALFORMED_CANONICAL),
    ("canonical_identity_mismatch", TrustFailureCode.CANONICAL_IDENTITY_MISMATCH),
    ("canonical_hash_mismatch", TrustFailureCode.CANONICAL_HASH_MISMATCH),
    ("ineligible_status", TrustFailureCode.STATUS_INELIGIBLE),
    ("insufficient_evidence", TrustFailureCode.EVIDENCE_INSUFFICIENT),
    ("unresolved_contradiction", TrustFailureCode.CONTRADICTION_UNRESOLVED),
)


@pytest.mark.parametrize("fault_name, expected", TRUST_FAILURE_CASES)
def test_each_fault_returns_exactly_one_first_failure(
    brain_home, fault_name, expected
):
    request, candidate_id = build_fault_case(brain_home, fault_name)
    result = retrieval_pipeline.retrieve_trusted(brain_home, request)
    refusals = [r for r in result.refusals if r.memory_id == candidate_id]
    assert len(refusals) == 1
    assert refusals[0].code is expected
```

`build_fault_case` is a test-only factory implementing the adjacent fault table. It creates a governed valid memory, mutates only the named layer, and recomputes dependent fields only when the case is intended to reach a later precedence position. Add pairwise/triple precedence cases, such as malformed + hash mismatch (malformed wins), identity + hash mismatch (identity wins), stale index + missing canonical (stale index wins), and wrong project + unsupported domain (project scope wins). Assert the code does not change with discovery tier or candidate iteration order.


- [ ] **Step 2: Run the gate matrix red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "trust_failure or precedence or refusal" tests/test_retrieval_isolation.py
```

Expected: FAIL because the pipeline module and total precedence implementation do not exist.

- [ ] **Step 3: Implement the gate in the specified order.** Open one SQLite read connection, execute one read transaction for all pages/refills, and pass that connection through discovery and gate code. Resolve request identity before candidate-specific checks; treat `default`/`unknown`/empty as unresolved for project-scoped candidates but allow global candidates. Reject domain-scoped candidates with `DOMAIN_IDENTITY_UNSUPPORTED` because V2-A adds no domain identity contract. Check DB/index/manifest structure, algorithm, canonical read/parse, identity, semantic hash, status/evidence, then contradictions. Return exactly one refusal and never continue later checks after the first applicable condition. Explanations are bounded stable strings and contain no bodies, summaries, prompts, or arbitrary frontmatter.

- [ ] **Step 4: Implement unique consolidation and refill.** Maintain an ordered `dict[memory_id, DiscoveryMetadata]`; the first occurrence fixes `first_seen` and tier, later sources increment bounded source count without another scan or gate. Continue pages until `ranking_target` eligible snapshots exist, source exhaustion, or `max_scan` unique assessments. Count `discovered_count` as raw page candidates, `unique_candidate_count` and `scanned_count` as unique IDs, and set `scan_limit_hit` only when the unique ceiling stops the loop. A refused page does not consume ranking capacity. Keep optional vector IDs behind the same gate.

- [ ] **Step 5: Implement raw-byte verification and cache rules.** For every assessment, read at most `1_048_576` bytes and compute raw SHA-256 before looking up `VerificationCache(home, memory_id, version, canonical_hash, raw_byte_hash)`. A matching key may reuse the parsed payload; a changed key reparses, normalizes, and recalculates the semantic hash. Do not persist raw hashes or use unchanged `stat()` values as authorization. Clear cache on process restart naturally, expose `invalidate(memory_id)`, and call invalidation from governed writes. Record stat checks, raw-byte checks, semantic checks, cache hits, and parses in diagnostics.

- [ ] **Step 6: Add contradiction pass and immutable snapshots.** After structural/hash/status/evidence checks, group verified candidates by normalized title; differing canonical bodies in an unresolved group become `CONTRADICTION_UNRESOLVED`. Build each eligible object from copied canonical payload, bounded provenance source-kind data, verification hashes/algorithm, discovery metadata, and same-snapshot decision count. No raw SQLite row, summary, FTS score, or vector payload is stored on the object.

- [ ] **Step 7: Add pipeline adversarial tests and run them green.** Cover twenty refused candidates followed by valid candidates, unique scan ceiling, duplicate exact/FTS/linear discovery, one read transaction across refill, wrong project, unresolved project, exact-ID gate bypass prevention, stale index content, optional vector, summary-only exclusion, and no post-gate index-body read. For the stat attack, edit a body with the same byte length, restore the original `st_mtime_ns` with `os.utime`, and assert `CANONICAL_HASH_MISMATCH` on the next trust assessment. Restart/clear the cache and assert a cold parse; an unchanged raw hash with the exact key is the only warm hit.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py tests/test_retrieval_isolation.py
```

- [ ] **Step 8: Commit the trusted gate and pipeline.**

```powershell
git add src/second_brain/retrieval_pipeline.py src/second_brain/semantic.py tests/test_trusted_retrieval.py tests/test_retrieval_isolation.py
git commit -m "feat(v2): add trusted retrieval gate"
```

### Task 6: Rank verified snapshots and route AutoInject through them

**Dependencies:** Task 5.

**Files:**
- Modify: `src/second_brain/retrieval_pipeline.py` ranking/materialization helpers.
- Modify: `src/second_brain/autoinject.py` in `_valid_candidates`, `_role_filter`, `_build_items`, `prepare_injection`, telemetry, and budget flow.
- Modify: `tests/test_trusted_retrieval.py`, `tests/test_autoinject.py`, `tests/test_retrieval_ranking.py`, `tests/test_retrieval_budget.py`, and `tests/test_retrieval_dedupe.py`.

**Interfaces:**
- Consumes: `TrustedRetrievalResult.eligible`, `TrustRefusal`, and `RetrievalDiagnostics` only.
- Produces: trusted rank order, snapshot-only `PacketItem` materialization, compatibility-facing `TRUST_GATE_REJECTED`, and legacy-search isolation.

- [ ] **Step 1: Write failing ranking and packet-isolation tests.**

```python

def test_trusted_packet_uses_canonical_body_and_no_summary_guidance(brain_home):
    mid = semantic.add_memory(
        brain_home,
        "Canonical title",
        "canonical observation",
        project_id="p",
        summary="derived summary must never appear",
    )
    decision = _inject(brain_home, "canonical observation", project_id="p")
    packet = autoinject.render_packet(decision)

    assert decision.decision is InjectionDecision.INJECT
    assert "canonical observation" in packet
    assert "derived summary must never appear" not in packet
    assert "guidance: " in packet
    assert mid in decision.selected_ids


def test_trust_refusals_become_distinct_compatibility_reason(brain_home):
    mid = _seed_current(brain_home, "wrong project", "body", project_id="other")
    decision = _inject(brain_home, "wrong project", project_id="p")
    assert mid in decision.candidate_ids
    assert decision.reason is NoInjectionReason.TRUST_GATE_REJECTED
    assert decision.selected_ids == []


def test_already_delivered_high_ranked_item_does_not_consume_budget(brain_home):
    first = _seed_current(brain_home, "same topic first", "short body", project_id="p")
    second = _seed_current(brain_home, "same topic second", "replacement body", project_id="p")
    lifecycle = autoinject.BrainLifecycle(brain_home)
    first_decision = lifecycle.prepare_injection(
        "same topic", project_id="p", role_profile="worker",
        session_id="s1", branch_id="b1",
    )
    lifecycle.commit_prepared_delivery(host_acknowledged=True, model_visible=False)
    second_decision = lifecycle.prepare_injection(
        "same topic", project_id="p", role_profile="worker",
        session_id="s1", branch_id="b1",
    )
    assert first not in second_decision.selected_ids
    assert second in second_decision.selected_ids
```

Add a test that monkeypatches legacy `semantic.search_memories`, `_body_text`, and `_row` to raise if the trusted AutoInject path calls them; legacy search tests continue to call those functions directly. Add ranking tests proving grade/status/scope/project/raw FTS score/summary do not change order after eligibility, while lexical canonical content, recency, bounded token cost, measured decision count, and canonical-content diversity do.

- [ ] **Step 2: Run ranking/packet tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "rank or packet or summary" tests/test_autoinject.py tests/test_retrieval_ranking.py tests/test_retrieval_budget.py tests/test_retrieval_dedupe.py
```

Expected: FAIL because AutoInject still consumes raw cascade rows, rereads bodies, and uses summaries.

- [ ] **Step 3: Implement ranking only over `EligibleCandidate`.** Recalculate lexical relevance from canonical title/body tokens; use canonical-created recency, the captured existing successful-retrieval count when present, the existing bounded token estimator, and canonical title/body diversity. Do not use grade, status, scope, project eligibility, unresolved contradiction, raw FTS/vector score, or summary as rank inputs. Apply deterministic order `score descending → discovery first-seen → memory_id`. Do not make a refused candidate a low-score candidate.

- [ ] **Step 4: Replace the trusted branch of `prepare_injection`.** Build `TrustedRetrievalRequest` from the existing `RetrievalIntent`, call `retrieve_trusted`, apply role filtering from `candidate.canonical_payload.tags` without opening another connection, rank eligible snapshots, materialize `PacketItem` from the same payload, deduplicate delivered identities, then budget/diversity-pack and serialize. Set `guidance` to the empty string; use canonical title/body only. Preserve the sparse `BrainInjectionDecision` shape. Return `TRUST_GATE_REJECTED` whenever candidates were discovered but none passed the gate, with `candidate_ids` and refusal counts in additive telemetry; keep `NO_RELEVANT_MEMORY` for true zero-match discovery.

- [ ] **Step 5: Preserve packet order and existing budget semantics.** The exact order is rank → canonical materialization → delivery-lineage dedup → existing budget/diversity packing → final serialization. Do not write delivery rows for refused, merely ranked, or materialized-but-dropped items. Keep delta strictness and existing token cap behavior, but source all fields from snapshots.

- [ ] **Step 6: Run focused trusted and legacy tests green.** Update existing tests that expected `WRONG_PROJECT` for the trusted AutoInject path to `TRUST_GATE_REJECTED`; retain direct legacy `semantic.search_memories` summary tests and packet wire-format tests.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py tests/test_autoinject.py tests/test_retrieval_ranking.py tests/test_retrieval_budget.py tests/test_retrieval_dedupe.py tests/test_retrieval_isolation.py
```

- [ ] **Step 7: Commit trusted AutoInject integration.**

```powershell
git add src/second_brain/retrieval_pipeline.py src/second_brain/autoinject.py tests/test_trusted_retrieval.py tests/test_autoinject.py tests/test_retrieval_ranking.py tests/test_retrieval_budget.py tests/test_retrieval_dedupe.py tests/test_retrieval_isolation.py
git commit -m "feat(v2): route autoinject through trusted snapshots"
```

### Task 7: Add explicit prepared/committed/failed delivery state

**Dependencies:** Task 6.

**Files:**
- Modify: `src/second_brain/contracts.py` (`NoInjectionReason`, `LifecycleEventType`, `BrainDeliveryRecord`, delivered-only helper).
- Modify: `src/second_brain/autoinject.py` (`insert_deliveries`, new commit/fail helpers, `BrainLifecycle`).
- Modify: `tests/test_contracts.py`, `tests/test_autoinject.py`, and create the delivery section in `tests/test_trusted_retrieval.py`.

**Interfaces:**
- Consumes: final selected packet items and existing lineage key.
- Produces: `insert_deliveries(...)` with prepared semantics, `commit_deliveries(...)`, `fail_deliveries(...)`, `BrainLifecycle.commit_prepared_delivery(...)`, `BrainLifecycle.fail_prepared_delivery(...)`, and delivered-only `_delivered_keys`.

- [ ] **Step 1: Write failing delivery-state tests.**

```python

def test_prepared_failure_does_not_suppress_retry_and_commit_does(brain_home):
    _seed_current(brain_home, "retry policy", "retry body", project_id="p")
    lifecycle = autoinject.BrainLifecycle(brain_home)
    first = lifecycle.prepare_injection(
        "retry policy", project_id="p", role_profile="worker",
        session_id="s", branch_id="b",
    )
    assert first.selected_ids
    prepared_ids = lifecycle.last_delivery_ids
    assert prepared_ids
    assert _delivery_states(brain_home, prepared_ids) == {"prepared"}

    lifecycle.fail_prepared_delivery("serialization_error", retryable=True)
    assert _delivery_states(brain_home, prepared_ids) == {"failed"}

    retry = lifecycle.prepare_injection(
        "retry policy", project_id="p", role_profile="worker",
        session_id="s", branch_id="b",
    )
    assert retry.selected_ids
    lifecycle.commit_prepared_delivery(host_acknowledged=True, model_visible=False)
    assert _delivery_states(brain_home, prepared_ids) == {"delivered"}

    final = lifecycle.prepare_injection(
        "retry policy", project_id="p", role_profile="worker",
        session_id="s", branch_id="b",
    )
    assert final.reason is NoInjectionReason.ALREADY_DELIVERED


def test_model_visibility_requires_host_acknowledgement(brain_home):
    _seed_current(brain_home, "task", "body", project_id="p")
    lifecycle = autoinject.BrainLifecycle(brain_home)
    lifecycle.prepare_injection(
        "task", project_id="p", role_profile="worker",
        session_id="s2", branch_id="b",
    )
    with pytest.raises(ValueError, match="acknowledgement"):
        lifecycle.commit_prepared_delivery(host_acknowledged=False, model_visible=True)
```

Assert the legacy `brain_packet_delivered` record remains present with its old fields/values and is not consulted for deduplication. Assert a retry reuses one logical lineage and a successful commit yields exactly one delivered identity.

- [ ] **Step 2: Run delivery tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_contracts.py -k "delivery or delivered" tests/test_autoinject.py -k "delivery or ledger" tests/test_trusted_retrieval.py -k "prepared or commit"
```

Expected: FAIL because all current rows are written as delivered and no commit/fail transition exists.

- [ ] **Step 3: Implement the state machine.** Add `DeliveryState(PREPARED, DELIVERED, FAILED)` and `TRUST_GATE_REJECTED`. Add V2 lifecycle enum values while retaining `BRAIN_PACKET_DELIVERED`. Extend `BrainDeliveryRecord` with nullable timestamps/state/failure/retryable fields while parsing old records. Change `is_already_delivered` and `_delivered_keys` to inspect only `state == delivered`.

- [ ] **Step 4: Split preparation from commitment.** Keep `insert_deliveries` as the existing callable name but make it insert or transition a stable lineage row to `prepared`, set `prepared_at`, and never set suppressing `delivered_at`. `commit_deliveries` changes prepared/failed rows to delivered idempotently, sets `committed_at` and compatibility `delivered_at`, and updates supersession pointers only on successful commitment. `fail_deliveries` records bounded failure code and retryable state while clearing suppressing timestamps. Only selected, serialized packet items enter preparation.

- [ ] **Step 5: Wire `BrainLifecycle` without claiming host visibility.** `prepare_injection` emits the existing compatibility `brain_packet_delivered` event with its pre-V2 payload unchanged and emits `brain_packet_prepared` only after prepared rows commit. Add explicit `commit_prepared_delivery(host_acknowledged: bool, model_visible: bool = False)` and `fail_prepared_delivery(failure_code: str, retryable: bool = True)`. Reject `model_visible=True` without host acknowledgement; a committed return boundary may set `model_visible=False`. Emit V2 committed/failed events with delivery IDs, packet hash, counts, and explicit retryability, never bodies or summaries. Current CLI/Hermes adapters remain unmodified and therefore do not gain an implicit model-visible claim.

- [ ] **Step 6: Run delivery and existing adapter tests green.** Update only assertions that relied on the old false-delivered ledger; preserve sparse CLI output and legacy event parsing.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_contracts.py tests/test_autoinject.py tests/test_trusted_retrieval.py -k "delivery or ledger or prepared or commit"
```

- [ ] **Step 7: Commit delivery state.**

```powershell
git add src/second_brain/contracts.py src/second_brain/autoinject.py tests/test_contracts.py tests/test_autoinject.py tests/test_trusted_retrieval.py
git commit -m "feat(v2): separate delivery preparation and commit"
```

### Task 8: Wire bounded trusted config and privacy-safe telemetry

**Dependencies:** Tasks 5–7.

**Files:**
- Modify: `src/second_brain/semantic.py` `RetrievalConfig`/loader.
- Modify: `config/retrieval.toml`.
- Modify: `src/second_brain/autoinject.py` telemetry payloads.
- Modify: `src/second_brain/telemetry.py` known kinds/schema validation.
- Modify: `brainstem/telemetry/SCHEMA.md`.
- Modify: `tests/test_telemetry.py`, `tests/test_autoinject.py`, and `tests/test_trusted_retrieval.py` diagnostics tests.

**Interfaces:**
- Consumes: `RetrievalDiagnostics`, `TrustFailureCode`, and delivery-state events.
- Produces: bounded `trusted_page_size=10`, `trusted_ranking_target=10`, `trusted_max_scan=100`, and `trusted_canonical_max_bytes=1048576` defaults with invalid-value fallback; additive telemetry fields exactly matching the approved list.

- [ ] **Step 1: Write failing config and telemetry tests.**

```python

def test_trusted_config_has_independent_safety_bounds(brain_home):
    cfg = semantic.load_retrieval_config(brain_home)
    assert cfg.trusted_page_size == 10
    assert cfg.trusted_ranking_target == 10
    assert cfg.trusted_max_scan == 100
    assert cfg.trusted_canonical_max_bytes == 1_048_576


def test_retrieval_telemetry_contains_counts_not_content(brain_home):
    _inject(brain_home, "canonical body", project_id="p", session_id="s")
    records = telemetry.iter_records(brain_home)
    retrieval = [record for _file, _line, record in records if record.get("kind") == "brain_retrieval_attempt"][-1]
    assert {"discovered_count", "unique_candidate_count", "scanned_count", "eligible_count",
            "ranked_count", "stat_checks", "raw_byte_hash_checks", "semantic_hash_checks",
            "canonical_cache_hits", "canonical_parses", "scan_limit_hit", "trust_refusals",
            "query_mode", "project_id", "is_delta"} <= retrieval
    assert "body" not in retrieval and "summary" not in retrieval and "prompt" not in retrieval


def test_v2_delivery_kinds_are_known_and_legacy_kind_remains_known():
    assert {"brain_packet_prepared", "brain_packet_delivery_committed",
            "brain_packet_delivery_failed", "brain_packet_delivered"} <= telemetry.KNOWN_KINDS
```

- [ ] **Step 2: Run telemetry/config tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_telemetry.py tests/test_autoinject.py -k "telemetry or config" tests/test_trusted_retrieval.py -k "diagnostic"
```

Expected: FAIL on missing config fields, event kinds, or diagnostics.

- [ ] **Step 3: Implement only bounded safety configuration.** Extend `RetrievalConfig` and `load_retrieval_config` to read a `[trusted]` table, accept positive integer bounds, and fall back to the exact defaults above. Keep existing `[scoring]` settings for legacy `search_memories`; the trusted ranker does not consume legacy trust/status/scope/summary terms. These are resource/scan bounds, not measured activation thresholds.

- [ ] **Step 4: Emit and validate additive telemetry.** Add all approved retrieval fields, stable refusal-code counts, query mode, project ID, delta flag, and no content fields. Add V2 delivery kind names to `KNOWN_KINDS` and lifecycle enum handling. Update `SCHEMA.md` to define prepared/committed/failed semantics, explicit host-ack boundary, and legacy-event non-authority. Keep the already-approved opening ` ```text ` fence in Section 8; make no other spec change.

- [ ] **Step 5: Run telemetry tests and inspect a real JSONL record.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_telemetry.py tests/test_autoinject.py tests/test_trusted_retrieval.py -k "telemetry or config or diagnostic"
```

Expected: PASS; the record contains counts/codes/hashes only and the three V2 event kinds validate at schema version 2.

- [ ] **Step 6: Commit telemetry/config contracts.**

```powershell
git add src/second_brain/semantic.py src/second_brain/autoinject.py src/second_brain/telemetry.py config/retrieval.toml brainstem/telemetry/SCHEMA.md tests/test_telemetry.py tests/test_autoinject.py tests/test_trusted_retrieval.py
git commit -m "feat(v2): add trusted telemetry and bounds"
```

### Task 9: Extend cold/warm labeled benchmarks and independent verification

**Dependencies:** Tasks 1–8.

**Files:**
- Modify: `proof/runner/retrieval_bench.py`.
- Create: `tests/test_trusted_retrieval_independent.py`.
- Add benchmark schema assertions to `tests/test_trusted_retrieval.py`.

**Interfaces:**
- Consumes: existing `build_corpus`, `build_labels`, `evaluate`, and trusted pipeline diagnostics.
- Produces: legacy/trusted cold/trusted warm benchmark rows for corpus sizes 100, 1,000, and 10,000, plus a fresh-process read-only verifier.

- [ ] **Step 1: Write failing benchmark/verifier tests.**

```python

def test_benchmark_reports_cold_and_warm_trusted_metrics(tmp_path):
    rows = retrieval_bench.bench(corpus_size=100, queries=4, engine="trusted", root=tmp_path)
    assert {"cold", "warm"} <= set(rows["cache_modes"])
    for mode in rows["cache_modes"]:
        metrics = rows["trusted"][mode]
        assert {"candidate_pages", "unique_scans", "hash_checks", "cache_hits",
                "canonical_parses", "refusal_counts", "eligible_count", "ranked_count",
                "recall_at_1", "recall_at_3", "recall_at_5", "precision_at_5", "mrr",
                "duplicate_rate", "stale_activation_rate", "contradiction_surface_rate",
                "retrieval_tokens", "packet_tokens", "latency_p50_ms", "latency_p95_ms",
                "task_completion", "verification_result"} <= metrics


def test_independent_verifier_does_not_import_trusted_pipeline(brain_home):
    mid = semantic.add_memory(brain_home, "T", "body", project_id="p")
    result = _run_independent_verifier(brain_home, mid)
    assert result["ok"] is True
    assert result["implementation_imported"] is False
    assert result["canonical_hash_match"] is True
    assert result["manifest_index_agree"] is True
```

The verifier must use a fresh Python subprocess and only stdlib plus direct SQLite/file reads. It re-derives frontmatter identity, normalized tags, semantic payload JSON/hash, manifest/index equality, delivery-state suppression, packet absence of summary/raw index values, and telemetry forbidden-field absence. It must never call `retrieve_trusted`, `semantic.search_memories`, or the packet builder.
`tests/test_trusted_retrieval.py` defines `_run_independent_verifier` with `subprocess.run([sys.executable, str(Path(__file__).with_name("test_trusted_retrieval_independent.py")), "--verify", str(home), memory_id], check=True, capture_output=True, text=True)` and returns `json.loads(completed.stdout)`. The independent test module exposes that `--verify <home> <memory_id>` CLI, imports only standard-library modules, prints one JSON object, and exits nonzero on any failed check.

- [ ] **Step 2: Run benchmark/verifier tests red.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py -k "benchmark" tests/test_trusted_retrieval_independent.py
```

Expected: FAIL on the new benchmark mode and verifier entry point.

- [ ] **Step 3: Add the trusted benchmark mode without changing the baseline.** Keep existing `fts`/`linear` results and labels. Add a trusted runner that opens a fresh verification cache for cold mode and reuses one cache across a repeated label pass for warm mode. Run each query through the trusted pipeline, record page/scan/hash/cache/parse/refusal/eligible/ranked diagnostics, render the final packet to measure packet tokens, estimate query/retrieval tokens with the existing deterministic estimator, and feed returned IDs through existing Recall@1/3/5, Precision@5, MRR, duplicate, stale, contradiction, and latency calculations. Define `task_completion` as all `must_retrieve` IDs present in top five with no `must_not_retrieve` ID present. Define `verification_result` as a structured pass/fail/count object derived from independent eligibility and packet checks, not as a quality threshold.

- [ ] **Step 4: Keep corpus semantics and measurement honest.** Continue using the existing real 100/1,000/10,000 corpus builder and seed. Its governed writes will create manifests; do not mutate metrics, remove refused candidates, or choose thresholds after observing results. Report legacy, trusted-cold, and trusted-warm separately, including negative quality/performance results.

- [ ] **Step 5: Implement the independent verifier test harness.** The child process reads the database and canonical files directly with `sqlite3`, `hashlib`, `json`, `pathlib`, and `unicodedata`; it checks the current commit’s generated evidence and returns JSON. It rechecks the raw file bytes and semantic hash independently, verifies tags across all four stores, confirms no current manifest depends on a raw-byte hash, and scans telemetry/packet artifacts for summaries, bodies, prompts, and raw index payloads. It records the repository commit SHA and refuses to pass if the evidence is from a different working tree state.

- [ ] **Step 6: Run the focused benchmark and verifier tests green.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py tests/test_trusted_retrieval_independent.py
```

- [ ] **Step 7: Commit benchmark/verifier work.**

```powershell
git add proof/runner/retrieval_bench.py tests/test_trusted_retrieval.py tests/test_trusted_retrieval_independent.py
git commit -m "test(v2): measure trusted retrieval cold and warm"
```

### Task 10: Run promotion gates and stop before activation

**Dependencies:** Tasks 1–9.

**Files:**
- Verify only: all V2-A implementation, test, benchmark, and telemetry files above.
- Do not modify activation configuration or host adapters.

**Interfaces:**
- Consumes: committed implementation, benchmark output, independent verifier output, and existing V1 baseline.
- Produces: reviewable gate evidence; no active-mode rollout change.

- [ ] **Step 1: Run the complete focused behavioral gate.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest -q tests/test_trusted_retrieval.py tests/test_trusted_retrieval_recovery.py tests/test_trusted_retrieval_independent.py tests/test_semantic.py tests/test_memory_index.py tests/test_hybrid_retrieval.py tests/test_autoinject.py tests/test_contracts.py tests/test_telemetry.py tests/test_retrieval_isolation.py tests/test_retrieval_filters.py tests/test_retrieval_dedupe.py tests/test_retrieval_ranking.py tests/test_retrieval_budget.py tests/test_migrations_property.py tests/test_backup.py
```

Required evidence: every refusal code and combined precedence case passes; 20 refused candidates refill; duplicate sources scan/gate once; exact ID cannot bypass; same-size/same-mtime edit is detected; only verified canonical body/title reaches packet; summaries/raw rows do not; prepared/failed rows retry; only committed rows suppress; migration/recovery/backup are clean.

- [ ] **Step 2: Run static checks once after all Python changes.**

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m ruff check src tests proof
.venv\Scripts\python.exe -m pyright
```

- [ ] **Step 3: Run the existing labeled benchmark at all required sizes.** Keep outputs separate by engine and cache mode.

```powershell
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
.venv\Scripts\python.exe proof\runner\retrieval_bench.py --corpus 100 1000 10000 --queries 25 --engine trusted --seed 20260815 > trusted-retrieval-v2a.json
.venv\Scripts\python.exe proof\runner\retrieval_bench.py --corpus 100 1000 10000 --queries 25 --engine fts --seed 20260815 > legacy-retrieval-v1.json
```

Record candidate pages, unique scans, hash checks, cache hits, canonical parses, refusal counts, eligible/ranked counts, Recall@1/3/5, Precision@5, MRR, duplicate/stale/contradiction rates, retrieval tokens, packet tokens, p50/p95 latency, task completion, and verification result. Do not discard or reinterpret negative results.

- [ ] **Step 4: Run the independent verifier in a fresh process against the benchmark/current commit evidence.** Require all verifier checks to pass and require its recorded SHA to match the reviewed implementation commit. A verifier failure blocks activation.

- [ ] **Step 5: If dogfooding is useful, run it only after the benchmark and independent evidence are captured.** Consume the committed shadow/advisory path as an observation; label its captures as dogfood; never use Brain-derived retrieval, labels, thresholds, telemetry, or generated memories to define benchmark expectations, verifier checks, or pass/fail evidence. Discard any dogfood working-tree changes before the independent verifier reruns against the reviewed commit.

- [ ] **Step 6: Apply the activation boundary as a review gate, not code.** Keep shadow/advisory until every condition is evidenced: no refused candidate reaches ranking in independent trace evidence; refusal/version/hash tests pass; migration/recovery pass; delivery failure shows no false deduplication; valid-memory recall has no unexplained regression; cold and warm reports are separate; no summary/raw index payload reaches a trusted packet; and the independent verifier confirms current-commit evidence. Negative performance or quality results remain blockers. No active-mode config or host mutation is changed in this task.

- [ ] **Step 7: Commit only if the gate artifacts themselves require a repository commit.** Do not stage generated benchmark output, `.superpowers/sdd/.gitignore`, databases, telemetry captures, or unrelated files. If no source/test/schema change is needed, leave no extra commit.

---

## Self-review against the frozen design

- **Sections 1–3, canonical contract:** Task 1 covers exact payload fields, no `schema_version`, strict unknown-field handling, tag normalization, syntactic hash equivalence, and semantic hash naming. Task 3 makes all hash-covered metadata changes versioned.
- **Section 4, manifests/migration:** Task 2 adds `memories.tags`, rebuilds `memory_versions`, preserves unknown legacy version times, backfills only governed paths, refuses malformed/missing files, rebuilds derived state only from verified snapshots, and tests interruption/idempotency/backup recovery.
- **Section 5.1–5.3, discovery/consolidation/refill:** Task 4 provides exact/FTS/linear/vector ID-only pages, fixed source precedence, one read transaction, unique scan accounting, and independent page/refill bounds.
- **Section 5.4, all refusal codes:** Task 5 defines all 16 codes in exact total order, gives a fault for each, and tests pairwise/triple precedence. Domain scope is explicitly refused because the frozen design adds no domain identity contract.
- **Section 5.5–5.6, snapshots/cache/signatures:** Task 5 reads raw bytes before cache lookup, uses the exact five-part cache key, invalidates on governed writes, treats stat as diagnostic only, and verifies same-size/same-mtime edits.
- **Section 5.7–5.8, ranking/provenance/summary:** Task 6 ranks only verified canonical snapshots, uses only whitelisted signals, keeps provenance optional/bounded, and excludes summaries from discovery/ranking/guidance.
- **Section 6, packet/delivery:** Task 6 preserves rank → materialize → dedup → budget → serialize. Task 7 makes prepared/failed rows retryable, commits only at explicit acknowledgement, preserves the legacy event, and adds all three V2 event names.
- **Section 7, filesystem/SQLite recovery:** Task 3 implements render → temp → fsync → parse/hash → rename → SQLite manifest/current commit → derived refresh → cache invalidation, with tests for every failure boundary and orphan non-adoption.
- **Section 8, telemetry:** Task 8 emits every approved diagnostic field without content and retains the corrected Markdown fence.
- **Section 9, verification/rollout:** Tasks 9–10 cover unit, adversarial, persistence, delivery, benchmark, independent-verifier, shadow/advisory, and negative-result gates.
- **Dogfood independence:** Optional Brain dogfooding occurs only after independent evidence capture and cannot define labels, thresholds, verifier expectations, or promotion evidence.
- **Section 10, boundary:** The plan changes only the listed trusted path/schema/tests/config/telemetry contracts plus the explicitly required benchmark/verifier tests. It does not add a service, dependency, vector implementation, domain contract, activation, or unrelated cleanup.

## Placeholder and type-consistency review

- No step depends on an unspecified value, later design decision, or unbounded behavior.
- `CanonicalPayload`, `CanonicalRead`, `DiscoveryPage`, `TrustedRetrievalRequest`, `EligibleCandidate`, `TrustRefusal`, `RetrievalDiagnostics`, and `TrustedRetrievalResult` are named once and used consistently.
- `insert_deliveries` retains its existing name with prepared semantics; `commit_deliveries`/`fail_deliveries` and the two `BrainLifecycle` methods are the only new delivery transitions.
- `memories.tags`, `memory_versions.tags`, and `memory_index.tags` use one storage encoding, while the canonical payload uses a sorted tuple.
- Legacy search APIs remain available but are never called by trusted AutoInject; no compatibility alias is used as a trusted path.
- The current planning session has made no implementation-code changes. The only repository change beyond this plan is the one-line Section 8 fence repair in docs-only commit `8427dea`.

**Stop condition:** Present this plan for user review now. Do not start Task 1 or any implementation phase until the user explicitly approves the plan.
