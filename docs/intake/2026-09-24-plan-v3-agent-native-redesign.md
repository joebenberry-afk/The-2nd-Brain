---
date: 2026-09-24
type: plan
authority: proposed
status: draft
scope: v3-product-design
supersedes: none-additive
superseded-by: none
promoted:
---

# Second Brain V3 — agent-native redesign

**Status.** Proposal for owner decision. If accepted it replaces the incremental approach in
`2026-09-24-plan-v3-implementation-revision.md` (whose R0 items — async hooks, lean entry, CI —
still apply). It keeps the V3 product goal and the M00 trust invariants; it changes the product
shape. Nothing here is promoted, deployed or authorised.

**The product in one sentence.** A portable, current-state memory that agents read and write
through the surfaces they already use — files, a CLI, session start, tool errors and compaction —
and that is silent the rest of the time.

## 1. Design inputs: what agents today are good at, and what they lack

**Good at:** reading files, grep, running CLIs, following `AGENTS.md`/`CLAUDE.md`, loading Agent
Skills on demand, long contexts with prompt caching. A plain filesystem agent scored 74.0% on
LoCoMo against 68.5% for a specialised memory library (Letta).

**Lack (observed in this repository's own sessions):**

| Gap | Example | Native coverage |
|---|---|---|
| Orientation | Learning where V3 stood took ~30–50K tokens of reading contracts, reports and git log | `CLAUDE.md` is static and drifts |
| Environment gotchas across machines | `PYTHONHOME` trap, bun lacking `node:sqlite`, Windows-only sources in cloud | Claude Code auto memory is per-repo and machine-local; not in cloud sessions |
| Cross-project knowledge | SZ-tools mapping source from another repo; a fix made in BasicUpscaler | None |
| Which decision is current | Dozens of plans; orchestration-era facts still marked current | None |
| Trust | Which fact is tested vs guessed | None |
| Continuity after compaction on hosts without it | OMP native memory defaults to off | Partial |

**What agents do not need:** per-prompt injection of loosely related memories, extra resident tool
schemas, host lifecycle control, large packets. SWE-ContextBench: reused experience helps only
when compact and correctly selected; wrong selection gives little or negative benefit.

## 2. Principles

1. **Files are the product.** Records are Markdown files; indexes and briefs are derived views,
   rebuildable from the files alone.
2. **Pull by default; push only at four moments:** session start/resume, a tool error with a
   known correction, compaction, and an explicit request. No per-prompt push by default.
3. **One current answer per subject.** History on request; supersession is explicit, never
   inferred from timestamps.
4. **Precision over recall.** Abstain unless the match is specific.
5. **Nothing blocks a turn the Brain does not speak on.** All writes and telemetry are async.
6. **Trust travels with every fact.** Effective grade, evidence handle, scope. Nothing retrieved
   mints permission (M00 invariants unchanged).
7. **One store across projects, hosts and machines,** private by default, sharing explicit.
8. **Small.** Target ≤10K lines of Python and ≤1.5K lines per host adapter (today: 49.8K Python,
   12.7K TypeScript).

## 3. Architecture

```text
Brain home (private git repo)                          derived, rebuildable
├─ records/<scope>/<id>.md   ─────────────────────►  index.sqlite  (FTS5 + fields)
├─ projects/<id>.toml  (paths, remotes, domains)      views/<project>/brief.md
└─ config/                                            views/<project>/corrections.json
          ▲ write: CLI, async capture                         │ read
          │                                                   ▼
   brain CLI:  q · show · add · supersede · brief · review · sync · doctor
          ▲                                                   │
   thin host adapters:
     session start/resume → brief      tool error → one correction
     compaction           → brief + active state      session end → async capture
   hosts: Claude Code (hooks) · OMP (extension) · Codex (hooks) · any agent (CLI + one AGENTS.md line)
```

### 3.1 Record — the canonical unit

One Markdown file per record; every retrieval-relevant field lives in the file, so the index is
fully rebuildable (today the `memories` table is not, which is why a cloud seed exists).

| Field | Values |
|---|---|
| `id`, `title` | stable id; one-line claim |
| `type` | `fact` · `decision` · `gotcha` · `procedure` · `locator` · `correction` · `state` |
| `scope` | `project:<id>` · `domain:<tag>` · `global` |
| `status` | `candidate` · `current` · `superseded` · `retracted` |
| `grade` | `OBSERVED` · `TESTED` · `VERIFIED` (claimed VERIFIED is effective TESTED without attestation) |
| `valid_from`, `recorded_at` | when it became true; when the Brain learned it (bi-temporal) |
| `supersedes`, `superseded_by`, `reason` | explicit links; a weaker record cannot silently replace a stronger one |
| `evidence` | `path@blob`, commit, `command → exit code`, URL |
| `triggers` | `paths` globs, `errors` signatures, key terms |
| `private` | excluded from every export |

Body ≤ ~120 words. Longer material stays where it lives; the record is a locator to it.

### 3.2 Views — compiled when records change, never per turn

- **Project brief** (≤ 600 tokens, empty when the project has no current records): current
  decisions, active work (`state` records), top gotchas for this OS/machine, where things live,
  last session's handoff. Deterministic ordering and stable text, so hosts can cache it.
- **Correction table**: error signature → correction id, for a constant-time match in adapters.

### 3.3 CLI — the pull surface, zero resident schema cost

| Command | Does |
|---|---|
| `brain q "<question>" [--all-projects] [--as-of DATE]` | top ≤3 compact lines: id, type, status/grade, claim, evidence handle; abstains when nothing is specific |
| `brain show <id>` | full record + evidence |
| `brain add --type gotcha --evidence … "<claim>"` | write a candidate |
| `brain supersede <old> --by <new> --reason …` | explicit currentness change |
| `brain brief` | render the project brief |
| `brain review` | candidate queue: dedupe, promote, retire stale |
| `brain sync` | commit + pull + push the private Brain repo |
| `brain doctor --stale` | records whose evidence changed |

Discovery costs one line in the brief or `AGENTS.md` (~25 tokens): *"Project memory:
`brain q "…"`; record durable learnings with `brain add`."* An MCP wrapper is optional and off by
default, because resident tool schemas cost every turn.

### 3.4 Push moments

| Moment | Claude Code | OMP | Budget |
|---|---|---|---|
| Session start / resume / clear | `SessionStart` → `additionalContext` | first `before_agent_start` | brief ≤ 600 tokens, or nothing |
| Tool error | `PostToolUseFailure` (verify the Bash-context issue #55889 on the installed version) | `tool_result` with `isError` | ≤ 1 correction, ≤ 80 tokens, exact signature match, current + TESTED only |
| Compaction | `SessionStart` after compact | `session_before_compact` → next turn | brief + active state |
| Session end | `SessionEnd` / `Stop`, async | `session_shutdown`, detached | 0 tokens (write only) |

Per-prompt push (today's AutoInject) becomes an optional mode, off by default, kept only if the
evaluation shows it pays.

### 3.5 Write path — where the value is created

1. **Explicit:** agents run `brain add` when they learn something durable (the brief says when).
2. **Deterministic capture at session end (async):** failure→fix pairs (a command failed, a
   variant succeeded) become gotcha candidates; `Brain-Decision:` commit trailers become
   decision candidates; the existing `<!--second-brain-candidate-->` marker keeps working.
3. **Import:** Claude Code auto memory (`MEMORY.md`) and existing `CLAUDE.md` learnings become
   deduplicated candidates, so the two systems do not double-pay.
4. **Gate:** candidates are visible to pull (labelled) but never pushed until reviewed or
   evidence-tested (command re-run, blob check). This is the poisoning defence (GhostWriter,
   EVOMAL).
5. **Consolidation:** `brain review` — deterministic, budgeted; an optional model-assisted pass
   runs as a skill inside the user's own agent session (native execution, no Brain agent).

### 3.6 Cross-project, cross-host, cross-machine

- **Scope:** project records are visible only in that project; `domain:<tag>` records are shared
  by projects that declare the tag (e.g. `domain:ue4ss`); `global` holds OS/tooling gotchas.
  Scope is enforced before ranking.
- **Locators:** `locator` records point to canonical sources in other repositories with revision
  (RET-06).
- **Sync:** the Brain home is a private git repository. `brain sync` is explicit; `private: true`
  records never leave the machine. Cloud sessions clone it — the seed file goes away.
- **Hosts:** OMP and Claude Code read and write the same store, so a lesson learned in one is
  available in the other.

### 3.7 Technology choices (measured, not assumed)

Measured on the cloud Linux container, warm OS cache, 5 runs each (ms, wall clock per process):

| Runtime | Empty process | 2,000-row in-memory FTS5 build + BM25 query | Artifact |
|---|---|---|---|
| Python 3 (`sqlite3`, stdlib only) | 12–18 | 27–28 | needs a venv |
| Go (`modernc.org/sqlite`, pure Go) | 3–7 | 22–29 | 6.3 MB static binary |
| Bun (`bun build --compile`, `bun:sqlite`) | 12–13 | 54–60 | 99 MB binary |
| Node 22 (`node:sqlite`) | 30–35 | — | needs Node |
| Rust | 3–5 | not built | static binary |
| **Today's Brain hook** (Python, full package) | **148–165** | — | 88 ms is importing `second_brain.cli` |

FTS5 is available in Python `sqlite3`, `node:sqlite`, `bun:sqlite` and `modernc.org/sqlite`.

**Language: keep Python for the core.** The 155 ms hook cost is the Brain's import graph, not the
language — plain Python runs the same index workload in 28 ms, within 5 ms of Go. A lean entry
point that imports only `sqlite3` and the record/view modules reaches that range without a
rewrite. A Go rewrite would buy ~5 ms and a single-binary install (no venv, no `PYTHONHOME` trap)
at the cost of re-implementing and re-qualifying the core; revisit only if Windows Python
distribution keeps breaking. Bun's compiled binary is slower and 99 MB. Rust is overkill for
thousands of records.

**Hot paths do no retrieval at all.** Push moments read precompiled views: the session hook reads
`views/<project>/brief.md`; the error hook looks up `corrections.json`. The OMP extension reads the
same files in-process (≈100 lines of TypeScript, zero spawn), so the TypeScript mirror of the
retrieval rules (`quiet-precheck.ts` and its parity machinery) is no longer needed. Only
`brain q` queries the index.

**Database: SQLite FTS5 as a derived index over Markdown files in git.** At thousands of records
a BM25 query is a few milliseconds; column weights boost `title` and `triggers`. Rejected for the
product: Postgres/pgvector and Neo4j/FalkorDB (servers, ARCH-04), LanceDB (vector-first, not
needed), Tantivy (Rust-only, no gain at this scale). If a paraphrase class ever fails lexical
(E02 trigger), add `sqlite-vec` with a static embedding model (model2vec, ~30 MB, CPU) in the same
file, one versioned vector space per encoder (RET-04). DuckDB is fine for evaluation analysis
over telemetry JSONL, not in the product.

**Sync: git, one file per record, sortable unique ids.** Merge conflicts are rare because records
are small and mostly append-only; the index and views are never synced, only rebuilt. CRDT sync
(Automerge etc.) is unnecessary for one user across a few machines.

## 4. Mapping to the V3 requirements

| Area | How the redesign meets it | Contract change |
|---|---|---|
| ARCH-01..04 | No host control; no daemon; CLI + files; fail-open adapters | — |
| PERF-01 | Zero per-prompt additions; one bounded, cacheable session brief | **O2** — allow a ≤600-token brief when current records exist, measured |
| PERF-02 | No per-prompt process; session-start path ≤150 ms once | met by construction |
| MEM-01..05 | Files canonical, index derived; bi-temporal supersession; conflicts visible | — |
| RET-01..06 | Scope before ranking; lexical + exact; locators; abstention | semantic deferred until a paraphrase class fails lexical |
| CTX-01..04 | Brief + active state after compaction; append-only; small | — |
| REU | Evidence freshness (`path@blob`, `doctor --stale`) | artifact caching out of V3 |
| SKL | Procedures as records and plain Agent Skills; corrections on error | — |
| LRN | Capture + review + deterministic consolidation | learned selectors out of V3 |
| RES, SEC | Byte budgets per category; M00 invariants; private flag; injection fixtures | — |
| PORT | Claude Code + OMP qualified; Codex via the same hooks | second host = Claude Code |
| VAL | CI gates + value suite with a native-auto-memory control | — |

## 5. Keep, extract, remove

- **Extract and keep (D-6 extraction, not a rewrite):** the FTS query plan and contribution rules
  from `semantic.py` (used by `brain q` to rank and abstain), `freshness.py`, scope resolution
  (`registry`, `_valid_candidates`), grade/authority invariants, `backup`, adapter payload parsing,
  MEM-03a supersession semantics (links, as-of, weaker-replacement refusal).
- **Remove from the product** (archive under `legacy/`, delete after parity): the per-prompt
  AutoInject pipeline and its TypeScript mirror (turn bridge, quiet precheck, sensors, RTD,
  context paging, VMem, Lean runtime, injection slots), the hash-chained ledger (replaced by
  append-only JSONL telemetry), and the modules no V3 goal uses (router, credit, crossmodel,
  plasticity, cerebellum, monitor, goals, heartbeat, risk, verifier, optimisation, fingerprints,
  radar, gardener, skillforge, engram, promotion, action cache, delta sync, firewall). Governor and
  economics move into evaluation scripts.

## 6. Migration

1. Convert the 116 memories to records (frontmatter mostly exists; move DB-only fields and
   `memory_sources` into the files; infer `type`; leave unknown fields unknown).
2. Currentness sweep: produce a retire/supersede list; the owner approves before any change.
3. Run side by side on OMP and Claude Code for a week: new brief + error push on, old per-prompt
   push off; compare telemetry.
4. The installed M00 runtime stays the rollback until the new one qualifies.

## 7. How we will know it is better

Value-suite arms: native · native + auto memory (strong control) · redesign brief only · brief +
pull · brief + pull + error push · current candidate. Task families: orientation ("what is the
next step on X?"), environment gotcha, cross-project lookup, repeat error, current-vs-superseded
decision, no-benefit.

Promotion rule (frozen before held-out runs): correctness ≥ the native + auto-memory control on
every family; median tokens (input + output, cached reported separately) and tool calls lower on
memory families; per-prompt no-benefit delta 0; session-start cost reported, not hidden.

Deterministic CI on every push: retrieval dev/held-out sets, brief size and stability, correction
matching, scope isolation, poisoning fixtures, index rebuild from files.

## 8. Build plan (rough)

| Step | Content |
|---|---|
| 1 | Record format, converter, index rebuild, `brain q/show/add/supersede/brief`, CI |
| 2 | Adapters: Claude Code (SessionStart brief, PostToolUseFailure correction, async SessionEnd capture), OMP (same via a thin extension); value-suite arms |
| 3 | Capture (failure→fix, commit trailers, auto-memory import), review/consolidation, sync |
| 4 | Evaluation campaign, owner decisions, archive legacy |

## 9. Risks

| Risk | Mitigation |
|---|---|
| The brief costs tokens when irrelevant | Hard budget; empty when nothing current; per-project off switch; A/B |
| Agents under-use pull | Measure `brain q` calls; the brief lists the top locators; error push covers the highest-value case |
| Write-path poisoning / self-poisoning | Candidates never pushed until reviewed or tested |
| Losing qualified M00 behaviour in the move | Extraction with parity tests on the S2 sets; M00 runtime stays the rollback |
| Host hook bugs | Verify per installed version; adapters fail open |
| Private memory in git | Private repository, `private: true`, export manifest (SEC-03) |

## 10. Owner decisions

| ID | Decision |
|---|---|
| O1 | Adopt the agent-native redesign instead of the incremental revision |
| O2 | PERF-01: allow one bounded session brief; keep zero per-prompt additions |
| O3 | Per-prompt push off by default; kept only if the evaluation shows it pays |
| O4 | A private git-synced Brain home replaces the cloud seed |
| O5 | Archive, then delete, the modules in §5 after parity |
| O6 | CLI name `brain` (keep `brainctl` as an alias) |
| O7 | Keep Python for the core with a lean entry point; no language rewrite now (§3.7) |

## 11. Binding rules from the owner's follow-up review (2026-09-24)

The owner accepted O1 and asked that the follow-up questions shape the build. These rules bind
the implementation:

1. **No conflict with the native harness.** The Brain never writes files into a user's project
   repositories. Views live in the Brain home (`views/`, derived, gitignored) and reach the agent
   only through hooks or `brain` commands. Adapters fail open. The Claude Code
   `PostToolUseFailure` context channel is verified on the installed version before error push is
   enabled there (issue #55889).
2. **Not redundant with native memory.** Claude Code auto memory keeps per-repo, machine-local
   notes; the Brain holds what native memory cannot: cross-project, cross-host, cross-machine,
   evidence-graded, current-state records. `brain import-native` turns `MEMORY.md` entries into
   deduplicated candidates, and the brief omits anything already present in the project's
   `MEMORY.md`, so the same fact is never paid for twice. OMP native memory stays off unless the
   owner enables a backend; then only one system is active per host.
3. **Cross-project by design.** Projects declare `domains` in `projects/<id>/project.toml`;
   `domain:<tag>` records are visible to every project that declares the tag. `brain q
   --all-projects` searches everything the caller may see; `locator` records form the
   cross-project source catalogue (RET-06); `brain share <id> --domain <tag>` is the only way a
   project record widens its scope, and it is recorded. `private: true` records never leave the
   machine.
4. **Token budgets are hard limits.** Per-prompt push: 0 tokens by default. Session brief: ≤600
   tokens, empty when nothing is current, stable text. Error correction: ≤80 tokens, one item.
   Pull (`brain q`): ≤3 one-line results. Every limit is enforced in code and reported in
   telemetry.
5. **Technology (O7).** Python core with a stdlib-only lean path (`second_brain.kb` imports no
   other Brain module on the hot path); SQLite FTS5 as a derived index; Markdown records in git;
   hooks read precompiled views.
6. **Original V3 features.** Kept: ARCH, SEC, MEM-01..05, RET-01/02/05/06, CTX-01..04, REU-02/03,
   SKL-01..04, LRN-01/02/04, RES-01/02/04, PORT-01..04, VAL-01..05, E06. Deferred behind a
   measured trigger: RET-03 semantic, RET-04, E03 ANN, E04 reranking, REU-01, REU-04, LRN-03/E05,
   RES-03. E01 and E02 are answered.

7. **Host focus and independence (owner, 2026-09-24).** OMP is the only host developed for now;
   Antigravity, Hermes, Codex and further Claude Code work are out of focus (existing adapters are
   frozen, not extended). The Brain must not depend on a harness, or on an OMP version, to work:
   records, search and views are files plus the `brain` CLI, usable from any shell or agent. The
   OMP adapter is a standalone single-file extension (`brainstem/omp-v3/`) that imports nothing
   from the legacy extension or OMP's type package and reads host fields defensively, so a host
   change degrades it to "adds nothing".

## Sources

- Letta, "Is a Filesystem All You Need?" — https://www.letta.com/blog/benchmarking-ai-agent-memory/
- SWE-ContextBench — https://arxiv.org/abs/2602.08316
- TokenPilot — https://arxiv.org/abs/2606.17016
- Claude Code hooks — https://code.claude.com/docs/en/hooks
- Claude Code memory — https://code.claude.com/docs/en/memory
- Claude Code hook-context issue — https://github.com/anthropics/claude-code/issues/55889
- Graphiti bi-temporal model — https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/
- Memory-Skill Isomorphism — https://arxiv.org/abs/2609.16669
- GhostWriter — https://pith.science/paper/2607.06595 · EVOMAL — https://arxiv.org/pdf/2608.25776
- OMP native memory backends: Brain record `mem-e6a79159acd1`
