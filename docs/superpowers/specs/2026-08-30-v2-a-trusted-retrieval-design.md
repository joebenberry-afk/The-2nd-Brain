# V2-A Trusted Retrieval — Design Specification

**Status:** Architecture approved; implementation not started
**Date:** 2026-08-30
**Baseline:** `v1.0.0` at commit `7735033a939cda08739193378116bb908a5fd983`
**Design branch:** `brain/v1-rc4-prime-074-compat`
**Planned implementation branch:** `brain/v2-a-trusted-retrieval`

## 1. Problem and scope

The v1 retrieval path has the required building blocks—canonical Markdown
memories, SQLite metadata, a derived FTS5 index, project isolation,
contradiction handling, version history, and a delivery ledger—but its stages
are not yet a strict trust boundary. Discovery/index data can be stale, trust
filters can run after ranking, and ranking can therefore be influenced by a
candidate that should have been removed entirely.

V2-A makes trusted retrieval a fail-closed read path without creating a second
retrieval architecture:

```text
untrusted discovery sources
        |
        v
bounded deterministic candidate pages
        |
        v
unique candidate consolidation
        |
        v
trust / eligibility gate
        |
        +-- refusal code + bounded telemetry
        |
        v
EligibleCandidate: immutable verified canonical snapshot
        |
        v
ranking of eligible snapshots only
        |
        v
canonical packet-item materialization
        |
        v
delivery-lineage deduplication
        |
        v
budget and diversity packing
        |
        v
serialization and delivery lifecycle
```

### Goals

1. A refused candidate must not enter ranking, packet construction, or the
delivery ledger.
2. Every semantic field reaching ranking or the model must come from one
integrity-verified canonical snapshot.
3. Canonical content identity and version identity must be deterministic,
explicit, and recoverable.
4. Filesystem/SQLite disagreement must fail closed without pretending the two
stores share an atomic transaction.
5. Discovery must refill around rejected candidates while remaining bounded.
6. Provenance must explain origin without becoming a universal eligibility
requirement.
7. V2-A must remain local, deterministic, shadow/advisory, and compatible with
the v1 canonical stores.

### Non-goals

V2-A does not introduce:

- a hosted retrieval service;
- a vector database, embedding model, or vector-specific trust path;
- automatic curation or automatic promotion;
- repository rewriting;
- active model-context substitution;
- trusted summaries;
- a universal external-source requirement;
- autonomous repair of canonical files;
- domain-scope semantics without a domain identity contract;
- a background daemon or remote telemetry sink.

An existing or future caller-supplied vector adapter may remain compatible, but
it is only another untrusted candidate-discovery producer. Its scores and
payloads cannot bypass or weaken the common gate.

## 2. Authority and invariants

Authority order remains:

```text
current repository/runtime evidence
    > current verified canonical memory
    > derived index/cache metadata
    > historical memory
    > model recollection
```

The following are hard invariants:

- Markdown is the canonical semantic content.
- `memory_versions` is an immutable version/integrity manifest, not a second
body store.
- `memory_index` and FTS5 are derived discovery state and may be stale.
- filesystem signatures are cache invalidation hints, never integrity evidence.
- `summary` is retained metadata only in V2-A and is never trusted, ranked, or
injected.
- `memory_sources` is optional provenance, not a universal trust prerequisite.
- ranking accepts `EligibleCandidate` values only.
- refused candidates cease to be retrieval candidates.
- reindexing cannot bless an unversioned semantic edit.
- delivery planning and serialization attempts do not independently mark an
item delivered.

## 3. Canonical semantic payload and hash

### 3.1 Hash definition

`file_hash` means:

> The lowercase hexadecimal SHA-256 digest of the UTF-8 bytes of the
> canonical JSON serialization of the normalized semantic payload extracted
> from the canonical Markdown file.

The algorithm identifier is:

```text
semantic-payload-v1
```

The existing `contracts.canonical_json` rules are used: recursively sorted
object keys, compact separators, deterministic escaping, `ensure_ascii=True`,
and UTF-8 bytes before hashing.

Raw Markdown bytes are not hashed. A normalized whole-document hash is not
used because frontmatter layout and harmless encoding/line-ending changes are
not semantic identity.

### 3.2 Logical payload

The payload has exactly these logical fields:

```json
{
  "body": "...",
  "canonical_created_at": "...",
  "grade": "...",
  "id": "...",
  "project": null,
  "scope": "...",
  "status": "...",
  "tags": [],
  "title": "...",
  "version": 1
}
```

`version` is the semantic memory version. `canonical_created_at` is the
memory's original canonical creation value. `version_created_at` is a separate
manifest-only operational timestamp and is not part of this payload.

V2-A has no separate `schema_version` field. `semantic-payload-v1` is the sole
hash-contract identifier. A `schema_version` declaration is an unknown
unprefixed field and therefore produces `MALFORMED_CANONICAL`; future schema
changes require a new hash algorithm identifier and an explicit contract.

`summary`, `updated_at`, `last_verified_at`, `strength`, `stability`, and
filesystem signature values are not part of the payload.

### 3.3 Markdown normalization

The canonical parser performs these steps in order:

1. Decode strict UTF-8 while accepting and removing one optional UTF-8 BOM.
2. Normalize all Unicode text to NFC.
3. Convert CRLF and CR line endings to LF.
4. Require a leading `---` frontmatter fence and a closing fence on its own
line.
5. Parse recognized frontmatter as logical key/value fields. Surrounding
syntactic whitespace is ignored; value-internal whitespace is preserved.
6. Map legacy V1 `created_at` to logical `canonical_created_at`. A file may
not contain both names.
7. Require `id`, `title`, `scope`, `project`, `status`, `grade`, `version`, and
one of the canonical-created-at spellings.
8. Remove exactly one separator LF after the closing fence and remove terminal
LF padding from the body. Internal blank lines, indentation, and meaningful
trailing spaces remain unchanged.
9. Convert an empty `project` value to logical `null`.
10. Normalize tags as defined below.
11. Serialize the logical payload with canonical JSON and hash it.

Duplicate required keys, missing required keys, invalid types, invalid enum
values, unterminated frontmatter, invalid UTF-8, or malformed body structure
produce `MALFORMED_CANONICAL`.

Unknown unprefixed frontmatter fields are malformed. Future extension fields
must use the reserved `x-<namespace>-<field>` form. V2-A ignores such fields
for trust, ranking, and packets; they cannot affect eligibility until a future
hash algorithm and schema explicitly recognize them. This prevents harmless
future metadata from silently changing V2-A semantics while preventing
unrecognized metadata from becoming hidden authority.

### 3.4 Tag normalization

The optional `tags` field defaults to an empty list when absent and otherwise
is a scalar string in V2-A. Normalization is:

1. NFC normalize, then Unicode casefold.
2. Split on commas or Unicode whitespace.
3. Empty tokens caused by separators are ignored; no non-empty token is
discarded silently. A non-empty invalid token rejects the canonical file.
4. Require each token to match:

```text
[a-z0-9][a-z0-9._/-]{0,63}
```

5. Deduplicate and sort tokens by ASCII code-point order.

Tags are therefore case-insensitive, ASCII-bounded, deterministic, and safe
for role matching. Existing `worker`/`orchestrator` tags remain valid. Tags
are hash-covered because they can affect role eligibility.

## 4. Immutable version manifest

### 4.1 Manifest fields

`memory_versions` is changed from a retired-version-only history table into a
complete immutable manifest. Each V2 version row contains:

```text
memory_id
version

title
scope
project_id
status
evidence_grade
tags

canonical_created_at
body_path
file_hash
hash_algorithm

version_created_at
change_note
```

The body is not duplicated into SQLite. `body_path` identifies the canonical
Markdown file and `file_hash` proves its semantic payload identity.

`version_created_at` means the time version N was committed through the
Brain lifecycle. It must not be confused with `canonical_created_at`, which is
the hash-covered creation value carried by the memory itself.

`change_note` describes the creation of that version. Version rows are never
updated after insertion; the new version carries the note explaining how it
supersedes or changes the prior version.

For legacy historical rows whose original version-commit time was never
recorded, `version_created_at` remains explicitly unknown during migration;
no timestamp is invented. Such rows are historical-only and cannot be the
current trusted manifest. All V2-created rows have a non-null
`version_created_at`.

### 4.2 Current consistency invariant

For a candidate to be eligible, all of these must agree:

```text
memory_index.memory_id
    = memories.memory_id
    = memory_versions.memory_id

memory_index.current_version
    = memories.current_version
    = memory_versions.version

memory_index.title/scope/project/status/grade/tags
    = memories current metadata
    = memory_versions current metadata

memory_index.body_path
    = memories.body_path
    = memory_versions.body_path

memory_index.file_hash
    = memory_versions.file_hash
    = semantic-payload-v1(canonical Markdown)

memory_index.hash_algorithm
    = memory_versions.hash_algorithm
    = "semantic-payload-v1"
```

The canonical Markdown must also declare matching `id`, `version`, `title`,
`scope`, `project`, `status`, `grade`, and canonical-created-at values
(`created_at` is accepted as the legacy spelling and normalized to
`canonical_created_at`), plus normalized `tags`. Tag agreement is exact after
V2-A tag normalization:

```text
normalize_tags(canonical Markdown)
    = memory_versions.tags
    = memories.tags
    = memory_index.tags
```

Any disagreement in these canonical fields, including tags, produces
`CANONICAL_IDENTITY_MISMATCH`.

Additional invariants:

- version rows are contiguous from `1` through `current_version`;
- the current canonical file exists and is the manifest path;
- historical paths remain distinct and recoverable;
- a missing current manifest is a hard refusal;
- no current candidate may rely on a legacy raw-byte hash;
- a current `memory_versions` row is mandatory even for version 1.

### 4.3 Migration

The next schema migration is `0011_trusted_retrieval.sql`. It rebuilds the
affected SQLite tables where necessary to use explicit timestamp and manifest
fields, preserving existing values without rewriting canonical bodies.

The SQL migration is transactional under the existing migration framework.
Canonical backfill is a separate deterministic operation because SQLite SQL
cannot calculate the Markdown semantic hash:

```text
apply schema migration
→ inspect each canonical memory
→ parse and calculate semantic-payload-v1
→ create missing current manifest rows
→ rebuild memory_index/FTS derived state
→ emit a migration report
```

Backfill rules:

- malformed/missing files remain stored but non-retrievable;
- legacy raw-byte hashes are not accepted as V2 evidence;
- canonical Markdown is never changed by backfill;
- a changed file is not accepted merely because reindex was requested;
- unrelated valid memories remain usable when one memory fails backfill;
- migration and backfill are idempotent.

## 5. Pipeline and component ownership

### 5.1 Candidate discovery

`hybrid_retrieval.py` provides discovery only:

- exact-ID lookup;
- lexical/FTS5 pages;
- linear fallback pages;
- optional caller-supplied vector candidate IDs;
- deterministic tier ordering and cursors.

Discovery may use derived title/body indexes to locate candidates. It may not
use raw index content as trusted packet or ranking content. Discovery scores
are hints for page order only and are not final ranking scores.

The trusted path queries title/body columns, not the DB-derived `summary`
column. A stale summary cannot create a trusted retrieval result.

### 5.2 Unique consolidation and stable read snapshot

Discovery sources are consolidated by:

```text
unique key = memory_id
```

The fixed source precedence is:

```text
exact ID → FTS/lexical → linear fallback → vector adapter
```

The first occurrence establishes the candidate's discovery order and tier.
Later occurrences only add bounded source-tier metadata. They do not consume a
scan slot or rerun trust assessment.

A retrieval operation opens one SQLite read transaction for its complete page
and refill sequence. Candidate ordering and DB metadata therefore come from a
consistent SQLite snapshot even if another process writes between pages.

`scanned` counts unique candidate identities that receive one trust
assessment, not raw rows returned by discovery producers.

### 5.3 Refill and scan bounds

The operation has independent limits:

```text
page_size              bounded backend page size
ranking_target         desired number of eligible candidates
max_scan               absolute unique-candidate scan ceiling
```

It repeatedly discovers pages, consolidates duplicates, gates new identities,
and continues until `ranking_target` eligible snapshots exist, the source is
exhausted, or `max_scan` unique candidates have been assessed.

A page containing only refused candidates therefore does not consume final
ranking capacity. If the ceiling is reached first, the result is bounded and
reports `scan_limit_hit` plus refusal counts. Fewer than `top_k` results is a
valid outcome when the trust gate leaves insufficient candidates.

### 5.4 Trust gate

The gate returns either:

```text
EligibleCandidate
```

or:

```text
TrustRefusal {
    code: TrustFailureCode
    explanation: bounded string
}
```

The first-failure precedence is fixed. The eight stages remain the major
ordering:

```text
1. request identity and scope policy
2. DB/index/version-manifest structural consistency
3. hash-algorithm support
4. canonical file existence/readability/parse
5. canonical identity and version fields
6. canonical semantic hash
7. lifecycle status and evidence policy
8. contradiction eligibility
```

Within those stages, the following total order over every
`TrustFailureCode` is authoritative; the earliest applicable condition wins:

```text
 1. PROJECT_IDENTITY_UNRESOLVED
 2. PROJECT_SCOPE_MISMATCH
 3. DOMAIN_IDENTITY_UNSUPPORTED
 4. VERSION_MANIFEST_MISSING
 5. VERSION_MANIFEST_MISMATCH
 6. INDEX_VERSION_STALE
 7. INDEX_METADATA_MISMATCH
 8. HASH_ALGORITHM_UNSUPPORTED
 9. CANONICAL_MISSING
10. CANONICAL_UNREADABLE
11. MALFORMED_CANONICAL
12. CANONICAL_IDENTITY_MISMATCH
13. CANONICAL_HASH_MISMATCH
14. STATUS_INELIGIBLE
15. EVIDENCE_INSUFFICIENT
16. CONTRADICTION_UNRESOLVED
```

An implementation evaluates all applicable conditions in this order and
returns exactly one first code. It must not select a code from discovery tier,
iteration order, or incidental branch order. A candidate that fails one check
is not evaluated by later checks.

Stable refusal codes are:

```text
CANONICAL_MISSING
CANONICAL_UNREADABLE
MALFORMED_CANONICAL
CANONICAL_IDENTITY_MISMATCH
CANONICAL_HASH_MISMATCH
HASH_ALGORITHM_UNSUPPORTED
VERSION_MANIFEST_MISSING
VERSION_MANIFEST_MISMATCH
INDEX_VERSION_STALE
INDEX_METADATA_MISMATCH
STATUS_INELIGIBLE
EVIDENCE_INSUFFICIENT
PROJECT_SCOPE_MISMATCH
PROJECT_IDENTITY_UNRESOLVED
DOMAIN_IDENTITY_UNSUPPORTED
CONTRADICTION_UNRESOLVED
```

### 5.5 Verified immutable snapshot

`EligibleCandidate` is a frozen snapshot, not a reference to mutable DB/index
state:

```text
EligibleCandidate {
    memory_id
    version
    canonical_hash
    hash_algorithm
    canonical_payload {
        id
        title
        scope
        project
        status
        grade
        canonical_created_at
        version
        tags
        body
    }
    provenance_envelope
    verification_stamp
    discovery_metadata
}
```

`discovery_metadata` contains only bounded mechanical facts such as tier,
first-seen order, and source count. It cannot supply title, body, summary, or
ranking semantics.

On full verification, the operation performs:

```text
read → parse → normalize → hash → retain parsed payload snapshot
```

Ranking and packet construction use that exact snapshot. They never reread
`memory_index.body`, `memory_index.title`, or other raw discovery values after
the gate.

A process-local verification cache may reuse a verified snapshot only after
every trust assessment reads the bounded canonical file and calculates a
process-local raw-byte SHA-256 digest. The cache key is:

```text
home
memory_id
version
canonical_hash
raw_byte_hash
```

If the raw-byte digest matches the cache entry, the previously parsed and
semantic-hash-verified snapshot may be reused. If it differs, the operation
must parse, normalize, and recalculate `semantic-payload-v1` before any
snapshot can be trusted. The raw-byte digest is a cache-freshness key only; it
is never canonical identity evidence and is never persisted.

The cache is empty after process restart. Governed writes invalidate all cache
entries for the affected memory. A cache hit reuses a snapshot whose raw bytes
were read during the current trust assessment; it never converts a filesystem
signature into integrity evidence.

### 5.6 Filesystem signatures

`file_size`, `mtime_ns`, and optional platform-specific `file_identity` are
cache invalidation and diagnostic signals only. A changed signature may
eagerly discard a cache entry, but it does not establish corruption or
freshness. An unchanged signature never authorizes cache reuse; the raw-byte
digest is still required.

```text
signature changed
    = optionally discard cache → read bytes and calculate raw-byte digest

signature unchanged
    = no trust or cache inference → read bytes and calculate raw-byte digest
```

A signature mismatch is not corruption and does not itself generate a trust
refusal. Only canonical/manifest disagreement generates an integrity refusal.
A missing or platform-unreliable identity field is allowed. Cold-cache and
warm-cache behavior are measured separately.

### 5.7 Ranking

Ranking receives only verified snapshots. It recalculates semantic relevance
from canonical title/body content; it does not reuse FTS/BM25 body scores as
trusted ranking signals.

V2-A ranking signals are limited to:

```text
canonical lexical relevance
recency / temporal utility
measured decision value
bounded token cost
canonical-content diversity
```

These are not ranking inputs:

```text
trust grade
status
scope
project eligibility
unresolved contradiction
raw FTS/vector score
summary text
```

Grade, status, scope, project identity, canonical integrity, and contradiction
state are boolean gate decisions. No refused candidate can receive a low score
and remain in contention.

### 5.8 Provenance and summary

`memory_sources` is read as optional provenance after trust approval. It can
explain whether a memory came from an episode, test, decision, evidence item,
or import. It does not establish canonical integrity and is not required for
internally authored/project-authored memories.

V2-A summaries remain retained derived metadata but are completely excluded
from trusted retrieval:

- no summary-based discovery;
- no summary-based ranking;
- no summary in trusted packet guidance.

The trusted packet uses canonical title/body fields from the verified snapshot.
A future V2-B may define a proper summary artifact with source hash, generation
algorithm/version, and artifact identity.

## 6. Packet assembly and delivery persistence

### 6.1 Item materialization and budget order

The post-ranking stages are:

```text
rank verified snapshots
→ materialize canonical packet items
→ delivery-lineage dedup
→ budget/diversity packing
→ final serialization
```

Materialization uses only the verified snapshot. Delivery dedup happens before
budget packing so already-delivered high-ranked items do not consume packet
capacity that could be filled by later ranked items.

A ranked or materialized item is not delivered. Delivery rows are written only
for items that survive deduplication and budget selection and reach the
successful delivery commit point.

### 6.2 Delivery state invariant

The existing delivery ledger is extended to distinguish preparation from
successful delivery:

```text
prepared
 delivered
 failed/retryable
```

Only `delivered` rows suppress a future retry. A prepared row is not enough to
claim the model received anything.

The delivery lifecycle is:

```text
prepare final packet item
→ record prepared intent idempotently
→ serialize/send through host surface
→ commit delivery only after that surface reports success
```

Serialization failure or host-delivery failure leaves no suppressing delivered
row. A retry with the same canonical item identity and lineage is idempotent;
a successful retry produces one effective delivered identity. Existing host
adapters that cannot observe model visibility may still commit their own
successful insertion/return boundary, but must not claim model visibility.

The existing `brain_packet_delivered` event is retained unchanged as a legacy
compatibility event. V2-A does not reinterpret it as preparation, committed
delivery, or model visibility. V2-A lifecycle telemetry uses unambiguous event
names:

```text
brain_packet_prepared
brain_packet_delivery_committed
brain_packet_delivery_failed   # includes explicit retryable state
```

`brain_packet_prepared` records the prepared-intent commit. The committed event
records the successful delivery/insertion return boundary, without claiming
model visibility unless a host-side visibility event independently proves it.
The failed event records serialization or host-delivery failure and whether a
retry remains possible.

## 7. Filesystem/SQLite staged commit and recovery

Filesystem and SQLite cannot participate in one atomic transaction. V2-A uses
an explicit staged protocol:

```text
render next version
        ↓
write temporary file in canonical memory directory
        ↓
flush/fsync file where supported
        ↓
parse and calculate expected semantic hash
        ↓
atomically publish version file with same-directory rename
        ↓
BEGIN SQLite transaction
        ↓
insert immutable manifest row
update memories current pointer/metadata
update required DB state
        ↓
COMMIT
        ↓
refresh derived index outside the transaction
        ↓
invalidate process verification cache
```

Failure semantics:

- Before DB commit: the previous DB version remains current. A newly published
file without a manifest is an orphan and is not trusted.
- After DB commit but before index refresh: the canonical file and manifest are
authoritative; stale/missing index state makes retrieval temporarily
undiscoverable or fail closed until derived state is rebuilt.
- Signature changes after commit force a fresh verification; they do not by
themselves indicate corruption.
- A file is never adopted because it merely exists at a plausible path.
- Orphan scanning reports unreferenced files. Recovery may reconcile an orphan
only when it proves correspondence to an already governed manifest/lifecycle
operation or when an operator explicitly creates a governed version. It never
automatically blesses file presence.

Hash-covered metadata changes use the same new-version protocol. Operational
metadata excluded from the semantic payload may update without changing the
semantic version only when it cannot affect eligibility or model-visible packet
content.

## 8. Telemetry and diagnostics

Retrieval telemetry is additive and privacy-preserving. It records bounded
counts and stable codes, never memory bodies, summaries, prompts, or arbitrary
frontmatter:

```text
discovered_count
unique_candidate_count
scanned_count
eligible_count
ranked_count
stat_checks
raw_byte_hash_checks
semantic_hash_checks
canonical_cache_hits
canonical_parses
scan_limit_hit
trust_refusals: {code: count}
query_mode
project_id
is_delta
```

V2-A lifecycle telemetry names are `brain_packet_prepared`,
`brain_packet_delivery_committed`, and `brain_packet_delivery_failed`. The
legacy `brain_packet_delivered` event remains compatibility-only and cannot be
used to infer preparation, committed delivery, or model visibility.

When candidates were discovered but none passed the gate, the compatibility
facing decision uses a distinct `TRUST_GATE_REJECTED` outcome and includes the
refusal-code counts. A true zero-match query remains
`NO_RELEVANT_MEMORY`. Existing adapter consumers continue to receive the
sparse decision shape; detailed diagnostics are additive.

## 9. Verification plan and rollout

V2-A starts in shadow/advisory mode. No host context mutation is enabled by
this design.

### 9.1 Unit and contract tests

- canonical payload normalization for LF/CRLF/CR, BOM, NFC, frontmatter key
ordering, syntactic spacing, body padding, and preserved meaningful spaces;
- tag casefolding, Unicode normalization, separators, grammar, duplicate
removal, and invalid-token rejection;
- unknown-field rejection and `x-*` extension handling;
- exact hash repeatability, rejection of unprefixed `schema_version`, and
  algorithm identifier handling;
- every refusal code and exact precedence when several faults coexist;
- immutable version creation for body, title, scope, project, status, grade,
and tag changes;
- current manifest/index/memory agreement, including normalized tags, and
  contiguous version rows;
- legacy backfill refusal for malformed files and raw-byte hashes;
- summary exclusion from discovery, ranking, and packet content;
- optional provenance without an external-source requirement;
- snapshot immutability and no post-gate index-body reads.

### 9.2 Pipeline/adversarial tests

- twenty refused candidates followed by valid candidates still refill and rank
valid candidates;
- scan ceiling counts unique candidates only;
- exact + FTS + fallback discovery of one memory consumes one scan slot and one
trust evaluation;
- page refill uses one consistent SQLite read snapshot;
- wrong-project and unresolved-project candidates never rank;
- exact-ID lookup cannot bypass the gate;
- stale/corrupt index content cannot become packet content when its canonical
snapshot differs;
- an external canonical edit preserving size, mtime, and identity is detected
  by the raw-byte digest on the next trust assessment;
- an equal raw-byte digest permits snapshot reuse only with the exact
  process-local cache identity;
- process restart empties the verification cache;
- governed writes invalidate the verification cache;
- linear and FTS discovery use identical gate/rank behavior;
- optional vector candidates enter only through the common gate.

### 9.3 Persistence/recovery tests

- fresh create, reopen, migration idempotency, and backup/restore;
- file publication failure before DB commit;
- DB failure after file publication;
- index refresh failure after DB commit;
- missing, unreadable, malformed, and orphan canonical files;
- unversioned semantic edit remains refused after reindex;
- partial migration leaves no trusted partial state;
- prepared delivery with serialization failure is retryable;
- prepared delivery with host failure is retryable;
- successful retry becomes exactly one effective delivered identity;
- only successfully committed delivery rows suppress future retries.

### 9.4 Benchmark

Run the existing labeled retrieval benchmark at corpus sizes 100, 1,000, and
10,000. Compare V1 and V2-A with separate cold-cache and warm-cache runs.
Record:

```text
candidate pages
unique scans
hash checks
cache hits
canonical parses
refusal counts
eligible/ranked counts
Recall@1/3/5
Precision@5
MRR
duplicate/stale/contradiction rates
retrieval tokens
packet tokens
p50 latency
p95 latency
task completion
verification result
```

Correctness gates are absolute. No performance threshold is invented before
these measurements; any activation decision must use the measured V1 baseline
and the existing completion-reserve rule.

### 9.5 Activation boundary

V2-A remains shadow/advisory until all of the following are true:

- no refused candidate reaches ranking in independent trace evidence;
- all version/hash/refusal precedence tests pass;
- migration and recovery tests pass;
- delivery failure tests show no false deduplication;
- valid-memory recall does not regress without an explained, accepted tradeoff;
- cold and warm performance are reported separately;
- no summary or raw index payload reaches trusted packet content;
- an independent verifier confirms the evidence against the current commit.

Negative performance or quality results remain valid evidence and block
activation; they are not optimized away by changing the metric.

## 10. Implementation boundary

The implementation plan must modify only the trusted retrieval path and its
required schema/tests/telemetry contracts:

```text
src/second_brain/semantic.py
src/second_brain/hybrid_retrieval.py
src/second_brain/autoinject.py
src/second_brain/contracts.py
src/second_brain/migrations/0011_trusted_retrieval.sql
src/second_brain/retrieval_pipeline.py
config/retrieval.toml
brainstem/telemetry/SCHEMA.md
focused retrieval/migration/recovery tests
```

No RTD activation, skill promotion, vector dependency, domain-scope expansion,
or unrelated cleanup is part of V2-A.
