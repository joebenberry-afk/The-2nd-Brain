---
date: 2026-09-24
type: plan
authority: proposed
status: draft
scope: v3-implementation-strategy
supersedes: none-additive
superseded-by: none
promoted:
---

# V3 implementation revision — build the goals the cheapest way that works

**What this is.** A proposed revision of *how* V3 is built, measured against the V3 goals in
`Second_Brain_V3_Requirements_2026-09-24/` and the evidence gathered since. The requirement
register (ARCH/PERF/MEM/RET/CTX/REU/SKL/LRN/RES/SEC/PORT/VAL) stays the outcome contract. Items
marked **Owner decision** would change that contract and need the owner's call; everything else
is implementation choice. Nothing here is promoted, deployed or authorised.

**The V3 goal, restated.** Correct work with less avoidable effort: fewer repeated source hunts,
fewer repeated known errors, correct current-state recall, dependable continuity — and on a turn
where memory cannot help, the Brain costs nothing and is not noticed (§17, PERF-01/02).

## 1. What the evidence says

### Measured in this repository

| Finding | Evidence | Consequence |
|---|---|---|
| Hooks block for work that is never shown to the model | Claude Code adapter `brainstem/adapters/claude-code/hooks.json`: SessionStart, UserPromptSubmit, PostToolUse, Stop run synchronously and only write telemetry (`adapters/claude_code.py`); 148–165 ms per call on Linux, 15 ms of it interpreter start, 88 ms importing `second_brain.cli`; Windows adds a PowerShell start | Every prompt and every tool call pays ~0.15–0.6 s for no model-visible value |
| Process start dominates the OMP turn | E01: Python start + import 162–175 ms vs 0.5–29 ms of actual memory work; `once` hook 485 ms; cold p95 budget FAIL by 5.6–15.6× | No design that spawns Python per prompt can meet PERF-02 |
| Memory helps correctness; token savings unproven | Value campaign 1: correct 20/30 native → 28/30 Brain, tool calls −1.5 median; tokens −564 median, 95% CI [−4857, +3640]. VG-M08 injected 2 memories / 2,670 chars and used 20 tool calls vs 10 native | Precision and compact packets matter more than recall volume |
| Lexical wins at this scale | E02: lexical 10/10 recall, 11/11 abstention; every dense/hybrid arm 0/10 at equal abstention | Semantic retrieval is not the bottleneck today |
| Corpus currentness is weak | 116 indexed memories; 80 of 129 memory files are OBSERVED; orchestration-era records (e.g. `mem-174b3f5abbba`) are still `current` after the 2026-09-23 removal | Stale "current" facts are the likeliest wrong injection |
| Most code is off the memory path | 49.8K Python lines: 27 modules / 21.1K lines reachable from `turn_bridge`/`autoinject`/Claude Code adapter; 48 modules / 28.7K lines are not; TS extension 12.7K lines; full suite 2109 tests / 599 s (orchestrator-removal gate) | Import cost on the hot path, slow test cycles, and a large surface every agent session must navigate |
| Cloud evals undercount | Cloud run: dev 13/15, held-out 6/8, 0 false injections; D09, D11, H07 are `SOURCE_MISSING` (sources exist only on Windows); H06 is a real ranking miss | Cloud baselines must be compared cloud-to-cloud |

### External research (September 2026 state)

| Finding | Source | Consequence for V3 |
|---|---|---|
| Reused experience helps only when compact **and** correctly selected; unfiltered or wrong selection gives little or negative benefit | SWE-ContextBench | Precision first; top-1 compact packets; abstain when unsure |
| Mutating earlier context breaks prompt caching; prefix stabilisation cut cache-miss tokens 5.94M → 1.59M and cost 56–87% | TokenPilot | Append-only delivery; keep context paging / tool-output rewriting off |
| A plain filesystem agent scored 74.0% on LoCoMo vs 68.5% for a specialised memory library | Letta | Files the native agent can read are a strong baseline; the Brain's value is curation, currentness and selection, not a retrieval engine |
| Claude Code natively loads auto memory (first 200 lines/25 KB), path-scoped `.claude/rules/` and subdirectory `CLAUDE.md` on demand, Agent Skills with progressive disclosure; hooks can be `async` or HTTP; `PostToolUseFailure` fires on tool errors | Claude Code docs | Use native lazy surfaces instead of per-turn hooks where possible; async every non-injecting hook; error-triggered help has a native trigger |
| Memory as a Skill: resident description = hot cues, SKILL.md = index, references = detail; most effect in the ≤1,024-char description | Memory-Skill Isomorphism | Resident metadata costs every turn — conflicts with strict PERF-01 unless measured |
| Bi-temporal facts: valid-time (`valid_at`/`invalid_at`) plus system-time (`created_at`/`expired_at`), invalidate instead of delete | Graphiti/Zep | The MEM-03 data model |
| Heavy consolidation belongs off the response path; it trades tokens for later savings | Letta sleep-time compute | Deterministic, triggered, budgeted consolidation first; LLM passes are an experiment |
| Memory poisoning succeeds often (≈98% injection in GhostWriter); self-evolving coding agents self-poison (EVOMAL) | GhostWriter, EVOMAL | Keep evidence gates on writes; retrieved text stays untrusted data |

## 2. Revised architecture — three delivery channels, cheapest first

1. **Compiled native context — no per-turn cost.** At write/consolidation time, the Brain compiles
   current, in-scope, TESTED-or-better facts and source locators into host-native lazy surfaces:
   path-scoped rule files (Claude Code `.claude/rules/brain/*.md` with `paths:`; the OMP
   equivalent). The harness loads them only when matching files are touched. Regenerated when
   memory changes, never per prompt. Carries the same scope, framing and effective-grade labels as
   packets (RET-01, SEC-02).
2. **Gated push without a process spawn.** One read-only decision core (the D-6 deterministic
   kernel: scope → admission → contribution → currentness → budget) runs *in the host process*:
   inside the OMP extension, and as a fast command hook for Claude Code. It reads the SQLite index
   directly. It returns nothing on no-benefit turns and a top-1 compact packet otherwise;
   delivery is append-only and deduplicated.
3. **Pull on demand.** `brainctl recall` / a skill for explicit questions and exact-evidence
   expansion. Explicit queries skip the contribution gate, never the validity gates.

Everything that writes — telemetry, ledger, capture, consolidation — runs off the critical path
(async hooks, detached processes, or batched at session end). Python stays the only writer and the
reference implementation; the in-host core is parity-tested against it
(`tests/test_quiet_precheck_parity.py` is the template).

## 3. Goal-by-goal: best approach and change

K = keep, C = change, O = overhaul, D = defer (with trigger), X = remove/freeze.

| Goal | Today | Best approach | |
|---|---|---|---|
| ARCH-01 no host control | Orchestrator removed 2026-09-23; Antigravity Stop / Hermes residuals open | Finish the two residuals with changed-path tests | K |
| ARCH-02 stable contracts | Decision logic duplicated Python + partial TS mirror | One decision core, thin adapters; host names only in adapters | C |
| ARCH-03 bounded failure | Fail-open everywhere | Add the fault fixtures (missing interpreter, locked DB, broken index, malformed payload) to CI | K |
| ARCH-04 no new infra | Helper daemon was an E01 option | In-host core instead of a daemon | K |
| PERF-01 no-benefit neutrality | Contribution gate + uncertain-record gate; campaign 2 PASS | Keep; run the S2 dev/held-out evals in CI | K |
| PERF-02 latency | Cold FAIL 5.6–15.6×; telemetry hooks block | Async all non-injecting hooks; lazy-import hook entry; in-host decision core | **O** |
| PERF-03/04 accounting, bottlenecks | E01 profile done; provider usage read from transcripts | Close PERF-04 with the in-host core; keep accounting | K |
| MEM-01 canonical vs derived | `memories` rows are not rebuildable from files (the cloud seed exists because of this) | Decide per field: move retrieval-critical fields into frontmatter, or declare the DB canonical for them and back it up as such | C |
| MEM-02 typed records | Grade/status/scope only | Add only `record_type` (observation/decision/correction/procedure/locator) and `valid_from`; no broad schema up front | C |
| MEM-03 current state | MEM-03a in progress: explicit retire/supersede links, as-of search | Bi-temporal: record `valid_from` + link `effective_at` + `recorded_at`; never order by timestamp alone; then a one-time **currentness sweep** of the live corpus (owner reviews the retire list) | C |
| MEM-04/05 conflicts, durability | Contradiction markers; ledger durability | A weaker replacement becomes a visible conflict, not a silent supersession | K |
| RET-01 scope | `_valid_candidates` is the boundary | Same boundary for compiled rule files: per-project output only | K |
| RET-02 dilution | Focus/narrow retries shipped | Keep | K |
| RET-03 multi-operator | Lexical + exact-ref + structured | Keep lexical default. Semantic ships only when a measured paraphrase class fails lexical (**Owner decision D2**) | C |
| RET-04 embedding versions | — | Only needed if an encoder ships | D (encoder ships) |
| RET-05 ranking/packing | Up to budget, multi-item packets | Top-1 by default, a second item only above a margin; title + guidance + evidence handle, body on expansion | C |
| RET-06 source catalogue | — | Locator records compiled into per-project rule files, not a DB catalogue injected per turn | C |
| CTX-01..03 continuity | PreCompact resume packet, delivery ledger | Keep; fidelity classes only for the resume packet | K |
| CTX-04 minimal, cache-conscious | Paging/rewriting shipped off | Append-only; stable prefix; keep paging/rewriting off by default | K |
| REU-01..04 reuse | `action_cache`, `delta_sync`, `firewall`, `vmem` exist, mostly off | V3 reuse = memory freshness + source revalidation (`freshness.py`). Artifact caching waits for telemetry showing repeated read-only derivations (**Owner decision D6**) | D (≥ N repeats/week) |
| SKL-01..03 skills | `skills/`, skillforge, gardener, promotion | Plain Agent Skills packages discovered natively; review metadata stays unprotected and labelled | C |
| SKL-04 corrections | Candidate write via Stop marker | **Error-triggered correction:** `PostToolUseFailure` (Claude Code) / OMP tool-error event → deterministic match of error signature against correction records → inject one short correction | **O** (highest-value new feature) |
| LRN-01/02 consolidation, evidence check | `sleep`, `reconsolidation`, `gardener` (manual/shadow) | One deterministic, budgeted consolidation job: dedupe, retire via MEM-03 links, re-check sources, grade changes only with evidence; run manually or async at session end | C |
| LRN-03 learned selectors | plasticity/credit (shadow) | Record "deferred: insufficient labelled decisions"; revisit at ≥1k labelled decisions | D |
| LRN-04 bounded maintenance | — | Every maintenance run has a budget and a receipt | K |
| RES-01..04 resources | Frozen S1 profile | Per-category bytes in `doctor`; keep frozen profile | K |
| SEC-01..04 | M00 refusals | Unchanged; add poisoning fixtures for compiled rule files | K |
| PORT-01 two hosts | OMP + four adapters (Antigravity, Hermes, Codex, Claude Code) | Second qualified host = **Claude Code** (daily use; cloud sessions give real Linux runs) (**Owner decision D4**) | C |
| PORT-02..04 | Runtime identity census | Keep | K |
| VAL-01..05 | Long markdown reports; manual runs; no CI | CI gates on every push (retrieval evals, fault fixtures, parity, fast tests); native auto-memory as a strong control arm; markdown reports only at slice gates (**Owner decision D7**) | **O** |

## 4. What to remove or freeze

Rule: a module stays on the default import path only if a V3 goal needs it. "Freeze" means move
under `second_brain/legacy/`, drop it from default CLI registration, keep its tests runnable on
demand, delete after one release with zero consumers. First step for every item: confirm zero live
consumers (grep adapters/extension, telemetry for invocations) — the dispositions below are
proposals, not audit results.

| Disposition | Modules (lines) | Why |
|---|---|---|
| Freeze — V3 excludes or never consumes | `router` (330), `credit` (1078), `crossmodel` (339), `plasticity` (379), `cerebellum` (312), `monitor` (323), `goals` (553), `heartbeat` (372), `risk` (269), `verify` + `fresh_verifier` (790), `optimization` (501), `p4` (127), `fingerprints` (390), `radar` (481) | Routing, credit assignment, metacognition, goal state machines, verifier briefs and optimisation loops are outside V3's memory scope or excluded (ARCH-01, LRN-03) |
| Freeze until a trigger | `action_cache` (1321), `delta_sync` (457), `firewall` (596), `vmem` (1729), `engram` (868), `gardener` (2143), `skillforge` (974), `promotion` (1852) | Reuse caches and self-evolving skill machinery wait for measured need (REU/LRN triggers); promotion guards must first be checked for M00 refusals that SEC-01 still needs |
| Fold into one job | `sleep` (298), `reconsolidation` (1202) | Become the single consolidation job (LRN-01) |
| Keep, shrink the hot path | `cli` (4931) | Lazy subcommand imports; a dedicated hook entry that imports only adapter + decision core |
| Keep | `semantic`, `autoinject`, `hybrid_retrieval`, `freshness`, `contracts`, `db`, `backup`, `ledger`, `telemetry`, `registry`, `paths`, adapters, `doctor`, `episodes`, `skills` | Directly serve memory, retrieval, continuity, safety or operations |

Also turn off by default: the synchronous PostToolUse hook (make async or drop), the Lean advisory
(already off), context paging and tool-output rewriting (already off).

## 5. Revised sequence

| Slice | Content | Exit check |
|---|---|---|
| **R0 — Get out of the way** (days) | Async non-injecting hooks; lazy hook entry; module census + freeze; CI workflow with the cloud seed running the S2 evals, fault fixtures, parity and a fast test tier (<60 s) | Hook blocking time per prompt/tool call measured before/after; CI green |
| **R1 — In-host decision core** | Port the read-only decision to one TS core used by the OMP extension and a Claude Code command hook (node/bun, reading SQLite); Python remains writer and reference | PERF-02 cold p95 ≤ 100 ms and warm ≤ 10/50 ms measured; parity 100% on dev/held-out/fuzz |
| **R2 — Currentness** | Finish MEM-03a; add `valid_from`/`record_type`; currentness sweep (owner approves retirements); consolidation job | MEM-03 fixtures incl. orchestration removal; no stale record injected on the S2 sets |
| **R3 — Delivery A/B** | Compiled rule files vs gated push vs pull-only, against native + native-auto-memory controls in the value suite | Adopt the winning channel per host by tokens, tool calls, correctness and latency |
| **R4 — Corrections and skills** | Error-triggered corrections (SKL-04); skills as native Agent Skills packages | Repeat-error workload shows fewer repeated mistakes |
| **R5 — Qualification** | Two real hosts, resources, migration/recovery, all-in economics | §17 definition of done |

Deferred with explicit triggers: local encoder (a held-out paraphrase class fails lexical), ANN
(≥10k chunks and measured latency), learned selectors (≥1k labelled decisions), artifact reuse
caches (repeated read-only derivations in telemetry), multimodal (owner request).

## 6. Owner decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Meet E01/PERF-02 with an in-host read-only decision core instead of a helper process or a per-prompt Python spawn | Accept |
| D2 | Replace E02's "V3 still needs a demonstrated useful local semantic capability" with "semantic ships when a measured paraphrase class fails lexical; otherwise rejected with evidence" | Accept |
| D3 | Freeze the modules in §4 after the consumer census | Accept |
| D4 | Claude Code is the second qualified host (PORT-01) | Accept |
| D5 | The delivery channel per host is chosen by the R3 A/B, which may remove the per-prompt hook on a host entirely | Accept |
| D6 | V3 reuse (REU) is memory freshness + source revalidation; artifact caching is deferred behind a telemetry trigger | Accept |
| D7 | Routine evidence is CI gates + JSON; markdown reports only at slice gates | Accept |
| D8 | Approve the currentness sweep list (records to retire) before any canonical memory changes | Review the list when produced |

## 7. Why this makes agent work faster

- Per turn: no blocking hooks on turns that inject nothing; no Python start on the hot path.
- Per task: smaller, current, top-1 packets; corrections delivered at the moment of error.
- Per development session: ~28.7K fewer lines on the default path to read and import; a fast test
  tier and CI gates instead of manual evaluation ceremony; cloud sessions run the same gates.

## Sources

- Claude Code hooks reference — https://code.claude.com/docs/en/hooks
- Claude Code memory — https://code.claude.com/docs/en/memory
- SWE-ContextBench — https://arxiv.org/abs/2602.08316
- TokenPilot — https://arxiv.org/abs/2606.17016
- Letta, "Is a Filesystem All You Need?" — https://www.letta.com/blog/benchmarking-ai-agent-memory/
- Letta, Sleep-time Compute — https://www.letta.com/blog/sleep-time-compute/
- Memory-Skill Isomorphism — https://arxiv.org/abs/2609.16669
- Graphiti temporal knowledge graph — https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/
- GhostWriter memory poisoning — https://pith.science/paper/2607.06595
- EVOMAL — https://arxiv.org/pdf/2608.25776
- In-repo: `outputs/reports/v3-s2/e01/E01_REPORT.md`, `outputs/reports/v3-s2/e02/VERDICT.md`,
  `outputs/reports/v3-agent-experience/value/campaign/REPORT.md`,
  `docs/intake/m00-evidence/orchestrator-removal-gate-20260923.md`
