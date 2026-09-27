# Learning loop: capture is cheap; reusable knowledge is not yet a closed loop

Read-only investigation of the assigned V3 write path, promotion/currentness artifacts, and constitutional constraints. No repository files, canonical state, or derived views were changed. Runtime probes used disposable OS-temp homes; Python used `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -B`. No suites, installers, or model campaigns ran. Token figures below are the product's `ceil(characters/4)` estimator, **not provider-billed token measurements** (`src/second_brain/kb/views.py:28-30`). Future agent experiments specified below use **`openai-codex/gpt-6-astra`**, fixed effort, and tokens/latency rather than USD. Existing DeepSeek campaigns are not used to establish transfer to that model.

## Top findings

### 1. The new write path cannot currently deliver its own normal outputs to OMP. **HIGH**

**Claim.** `brain note` already exists and eliminates metadata authoring, but `note → accept → promote` does not produce a JIT-eligible warning. Further, fixing the grade exposes a separate whole-view failure.

**Evidence.**
- `capture.note` infers project/type/evidence/triggers, defaults private, writes an inbox candidate, and **always assigns OBSERVED** (`capture.py:660-823`, especially 799-803).
- `accept` preserves standing/grade while moving the record to canonical storage and rebuilding views (`capture.py:1004-1030`). `promote` changes only status/promotion metadata; it checks nonempty evidence and reason, not the underlying claim (`index.py:499-537`). `brain edit` exposes no grade change (`commands_index.py:266-289`; `index.py:710-758`).
- JIT requires current + effective TESTED (`views.py:583-586`). A temp-home execution of the actual CLI sequence `note`, `review`, `accept`, `promote` returned success for every command, but the compiled diagnostic was **`grade`**, with status current and grade OBSERVED.
- Captured IDs use `note-`, `got-`, `loc-`, and `git-` (`capture.py:329-331,463,800,940`); the record schema accepts those prefixes (`records.py:63`). The OMP loader instead requires **`^mem-...`** for every record, with a thrown error on violation (`brainstem/omp-v3/index.ts:305-314`). The caller invalidates the session and clears its entire view cache (`:509-526`). State/recovery pointers repeat the mem-only assumption (`:327,477`).
- **Actual adapter-runtime probe:** Python compiled temp views; Bun loaded the real adapter, invoked its registered lifecycle/tool-result handlers, flushed actual telemetry. A valid `mem-` record delivered (`no_match`, then `delivered`). The otherwise identical view containing an additional current TESTED `note-` record delivered nothing (`no_view`, `no_view`). This was an offline adapter invocation, not a live OMP model session.

**Impact.** Normal low-friction captures yield **zero JIT warnings** until a curator changes grade through file authoring or a separately authored TESTED record. Once an eligible captured-prefix record is published, **all records in the affected recipient view can disappear**, not just the new one. Fixing this contract mismatch and providing an explicit evidence-backed grade transition are prerequisites, not breakthroughs.

### 2. Currentness checks are disconnected from invalidation, and a missing source can become eligible again. **HIGH**

**Claim.** The Brain has blob checking, but it does not reliably revoke obsolete advice at read/review time.

**Evidence.**
- `capture.stale_evidence` reports changed/missing path@blob handles but does not alter canonical or derived standing (`capture.py:1069-1134`). Unparseable evidence handles are skipped.
- Compiler evidence checking skips missing files; it marks `changed=True` only when an existing file's hash differs (`views.py:486-536`). Only locators require at least one verified blob; non-locators need merely nonempty evidence (`:583-597`).
- `brain review` calculates stale evidence, then fingerprints record serializations, project manifests, score JSON and configuration—**not source evidence state** (`commands_capture.py:121-122,172-188`). Source-only changes therefore need not trigger recompilation.
- Temp reproduction with LF-byte-normalized evidence: initial stale list `[]`; changed source produced `changed`; **review generation remained identical**. The published warning remained present although a direct in-memory recompilation excluded it as `stale_evidence`.
- Deleting that source made the non-locator gotcha **eligible on direct recompilation**, while `capture.stale_evidence` correctly reported `missing`.
- The OMP runtime loads precompiled views and watches the generation/dirty marker, not evidence dependencies (`index.ts:305-328,549-556`). There is no automatic source-read revalidation on this surface.
- No canonical record in the current 121-record corpus has `last_verified_at` (read-only computation C1); the typed schema has only valid/recorded/superseded times (`records.py:116-139`). The Constitution explicitly expects recent verification and labile reconsolidation on contradiction (`constitution/truth-precedence.md:9-11,23-29`). V3's status enum has no labile state (`records.py:51`).

**Impact.** A source modification may remain warned about indefinitely without canonical activity/rebuild; a missing file does not conservatively quarantine non-locators. Whole-file hashing also cannot distinguish an irrelevant edit from a changed claim, nor establish that an unchanged historical report describes the current installation. Those latter limitations are [INFERENCE] from the dependency format, not measured semantic error rates.

### 3. The corpus mostly stored historical observations, not durable reusable operations; decay is not primarily a TTL problem. **HIGH**

**Evidence and counts.**
- Migration inventory: 120 files, **113 facts / 5 gotchas / 1 locator / 1 procedure**; **95 candidates**; 21 resolved blob handles, 2 mismatched, 117 unresolvable; only **2 push-eligible** after enrichment (`outputs/reports/v3-jit/migration/INVENTORY.md:7-24`).
- Promotion review covered 109 active records and recommended **57 retirements**, 35 keep-candidate, 17 promote (`promotion/PROPOSAL.md:7-18`). That is **52.3% of previously active records**, not a measured spontaneous failure rate.
- Computation over its proposal JSON: the 57 retirements were **56 facts + 1 gotcha; 45 unassigned-project domain records + 12 second-brain project records**. Nine reasons literally say “subsumed”; seven literally mention “orchestration.” These two lexical counts are not an exhaustive semantic categorization.
- Examples: individual Trial A subsumed by aggregate proof (`PROPOSAL.md:39`); an in-progress reset step resolved later (`:37`); obsolete orchestration repair (`:110`); a live actor/PID/address invalid after restart (`:111`). Immutable historical evidence can remain byte-perfect while its operational advice ceases to apply.
- Legacy conversion deliberately maps every legacy row to `type="fact"`, preserves created time, and maps labile to candidate (`convert.py:155-203`). Therefore “only one locator” partly reflects migration representation, not necessarily one month with only one useful localization discovery.
- `consolidate.py` only proposes same-visibility-bucket title-Jaccard duplicates at 0.8; it does not synthesize episode conclusions or maintain current claims (`consolidate.py:18-85`).
- Current corpus computation: **121 total; 18 current / 35 candidate / 63 superseded / 5 retracted**. Active types: 46 facts, 5 gotchas, 1 locator, 1 procedure. Of 175 evidence handles, **117 are still not path@blob-shaped**; 51 records have at least one such handle. Records span 2026-08-14 through 2026-09-25. None has `captured_from` metadata (C1).

**Impact.** The largest change of kind is separating **episode history** from **durable operation memory**. Automatically preserving every checkpoint as a “fact” creates later cleanup work. Conversely, blindly deleting history would lose provenance; retain it as evidence, not current advice.

### 4. The deployed learning loop is not merely slow: its maintenance lane has no local execution state. **HIGH for snapshot; MED for causal interpretation**

**Evidence.** Read-only snapshot found inbox size **0**, and all of `state/kb-capture-cursor.json`, `kb-score-cursor.json`, `kb-scores.json`, `kb-outcomes`, and `kb-review.json` absent (C1). The host shutdown callback writes only a session-end observation (`index.ts:601-603`). The plan explicitly moved capture to offline `brain review` and removed shutdown capture (`V3x_Just_In_Time_Memory_Plan.md:24,411-418`). The review code performs capture/scoring/reporting, not automatic curation (`commands_capture.py:100-188`).

**Interpretation.** This is evidence that the current home's retained V3 maintenance path has not produced durable checkpoints, not proof that no user ever ran a command in another home or subsequently removed state. [INFERENCE] The current design turns continuous observations into an unowned offline queue; passive logging alone cannot improve the next agent. The migration's five-gotcha count is not evidence that the new auto-capture algorithm was exercised and rejected all other learnings.

### 5. Outcome scoring is mechanically cautious but not a causal usefulness measure; it is unused by current selection. **HIGH**

**Evidence.**
- Positive labels: same-operation retry exits zero, evidence file touched, or pointer expanded (`outcomes.py:176-198`). Negative labels: same error on retry or three relevant searches after a locator. There is no comparison to what the agent would have done without delivery, no correctness result, and no token saving in the label.
- Windows use the next six tool events; gaps, short windows, ambiguous writers become incomplete (`:205-279,404-411`). Deduplication uses session/project/record/revision, retained aggregation is recomputed rather than blindly incremented, and history is bounded (`:244-247,341-374,443-509`). These are sensible mechanics.
- Utility is `(helpful + 1)/(helpful + harmful + 2)`; suppression is `delivered >= 3 and harmful > helpful` (`:358-360`). Actual pure-function probe: **one harmful + one neutral + one incomplete suppressed the record** with utility 1/3. Three informative trials are not required.
- Current `config/jit.toml:1-6` has `scored=false`; the compiler ignores score entries in this mode and emits 0.5/false (`views.py:568-575,623-624,665-680`). Enabled scoring would affect ranking/suppression in OMP (`index.ts:243-250`), not canonical truth or pull search.
- A read-only, capped `run_scoring(home,dry_run=True)` processed a 161-session retained prefix and produced only **2 trials, both incomplete; 0 helpful/harmful; checkpointed=true**. This is a capped prefix, not a corpus-wide outcome estimate. No score state was persisted.
- Config/plan already require held-out advantage before enabling the selector (`config/jit.toml:4`; plan `:769,783,897-899`).

**Verdict.** Keep raw exposure/revision/outcome observations if needed for evaluation. Do **not** promote these proxies into automatic truth, grade, or learned routing. [INFERENCE] A successful retry may be independent of the advice; reading a suggested file may be redundant; more searching may be good verification. The current selector has no demonstrated local production value, while maintenance currently imports/runs scoring even with selection off (`commands_capture.py:79-116`). Removing it from ordinary review is justified unless an explicit offline measurement owner needs it.

### 6. Agent Skills are the right eventual channel for real procedures, but this corpus has no demonstrated skill-sized procedure yet. **HIGH on inventory; MED on recommendation**

**Evidence.** The only procedure is `mem-a8d221e64549`: current TESTED, title “Migration ordering,” body **“apply migrations in numeric order”** (`records/mem-a8d221e64549.md:1-23`; 33 body characters). This is an invariant, not a reusable multistep workflow.

`export_skill` only gates type=procedure, status=current, effective grade≥TESTED (`skills_export.py:13-46`); it then writes a standalone `SKILL.md` with copied body, textual applicability/evidence and an advisory footer (`:96-164`). It does not check current source hashes, require evidence, reject conflicts, or manage later revocation/update of its copied output. A temp current TESTED procedure **with no evidence** exported successfully. Export location is caller-chosen (`commands_skills.py:34-40`); code does not enforce private/project scope at the host's discovery surface.

**Impact.** Do not multiply one-line facts into skill catalog entries. [INFERENCE] Proven, substantial workflows should use native on-demand skill discovery rather than repeated 80-token fragments—but only with a single canonical source/revision and publication/invalidation rules. Merely copying a record into a skill makes a second stale memory store.

### Lifecycle diagram, step count and latency

```text
agent hits trap / hunts for source
  │ OMP tool_result observations; shutdown writes end marker
  │ 0 additional authoring tokens; no capture/promotion here
  ├── explicit brain note "learning" ────────────────┐
  ├── brain capture / brain review                  │
  │    failure→different successful variant        │
  │    ≥4 read/search ops, ≥2 searches, one edit    │
  └── Brain-Gotcha / Brain-Decision commit trailer  │
       + brain capture/review --git <repo>         │
                                                   ▼
                  state/kb-inbox/<id>.md
                  candidate / OBSERVED
                  notes+event captures private
                                                   │
                review title list + source/body inspection
                curator verifies actual reusable claim
                [missing explicit TESTED-grade transition]
                                                   ▼
                         brain accept <id>
                  records[/private]/<id>.md
                  STILL candidate / OBSERVED
                  index refresh + views compile
                                                   │
                    brain promote <id> --reason ...
                current, SAME grade, actor/time/reason
                index refresh + views compile
                                                   │
       current + TESTED + nonconflicting + evidence + triggers
       + fresh resolvable blobs where checked + item budget
                                                   ▼
                  immutable generation/current.json
                                                   │
              next session loads eligible recipient view
              [captured-prefix IDs currently break loader]
                                                   │
          matching next tool RESULT → ≤80-token advisory
          (not prevention of the first matching command)

contradiction → explicit conflict OR curate replacement
replacement + supersede(old, by=new, reason) → old superseded
no replacement + retire(old, reason)         → invalidates
  ↳ history preserved; index/views rebuilt; active session revokes old view

cross-machine branch: explicit share(scope) / sync(public records+projects)
  ↳ private records excluded; pulled records refresh index/views
procedure branch: explicit export-skill → copied SKILL.md (no update/revoke loop)
```

Lifecycle evidence: `capture.py:310-343,346-379,491-587,827-983,1004-1030`; `index.py:499-707`; `views.py:577-635,659-763`; `sync.py:31-98,101-124,154-175,254-257`; `index.ts:531-556,566-603`. A failure→success pair must share context/tool/operation/prefix and differ in command (`capture.py:535-550`); it explicitly does **not** prove a fix (`:323-325`). Commit trailers create OBSERVED candidates with commit evidence but **no triggers** (`:939-951`), so also need applicability enrichment before JIT.

| Route | Explicit steps after discovery | Measured token/latency floor | Where it stalls |
|---|---|---|---|
| Existing low-friction note path | 4 CLI calls if using note→review→accept→promote; source/body inspection and grade authoring add **at least 2 actions**, possibly trigger/evidence enrichment | Temp CLI run: ~**96.5 ms warm in-process** across 4 calls; **156 estimated output tokens** with note `--json`; excludes commands, source verification, agent reasoning and process startup | Still OBSERVED; after grade repair, captured ID can invalidate OMP view |
| Auto-captured episode | 0 capture-authoring calls during trap; later review/capture + inspect + verify/grade + accept + promote, approximately **5–6 explicit actions** depending on combined inspection/verification | Logging is off-model; no measured end-to-end wait. Source checking has task-dependent token cost | Explicit maintenance never scheduled by the shown host lane; grade/ID gates remain |
| Old explicit `brain add --grade TESTED ...` | **2 CLI calls** add+promote, plus real source/behavior verification before claiming TESTED | Temp fixture: **49.7 ms warm**, **66 estimated command+output tokens**, resulting warning **17 estimated tokens** | Works at compiler and mem-ID contract level, but trusts caller's grade/evidence string; does not supply proof itself |
| Commit trailer | Trailer authoring + later capture/review + curation + trigger/grade authoring + accept/promote | Not timed | No trigger, OBSERVED; commit attribution is not proof of the claim |

There is **no honest fixed “trap → next agent warned” time/token total**: curator waiting is unbounded, no source-verification cost was measured, and the normal note route currently fails eligibility/delivery. The deterministic CLI work is already inexpensive; the meaningful cost is missing proof/curation and missed future reuse. These timings are illustrative single executions, not benchmark medians or cold-shell/end-to-end latency claims.

## Breakthrough candidates

### A. Proof-carrying capture: compile a verified observation into a narrowly scoped memory lease

**Concrete change.** Keep the existing one-line `brain note` entry point. Attach the **specific source/tool event at discovery time**, record a condition and a reusable action, and let the in-session agent explicitly curate it into a publication transaction. That transaction validates privacy/scope, resolves evidence, records what was checked and under which runtime/repo version, sets an honest grade, records actor/reason, accepts/promotes, and publishes once. A locator can have a deterministic proof such as “symbol X exists in file Y at revision Z.” A gotcha needs bounded evidence of the claimed condition and remedy, not merely an adjacent successful command. Never run arbitrary commands embedded in stored memory as validators; validators must be trusted, read-only/explicitly authorized implementations.

**Change of kind.** The durable product becomes a **qualified, actionable dependency-backed claim**, not a note awaiting two more administrative commands. Reuse the source knowledge already in the working agent's context rather than paying for another agent to reconstruct the episode.

**Expected effect.** [INFERENCE] One explicit authoring/curation transaction rather than the measured 4-call note path + separate file-grade repair; potentially one short delta rather than rereading the discovery episode. No numerical downstream saving is established. Unreviewed material remains candidate/private, so no mass auto-promotion.

**Effort:** M. **Risk:** turning existence/hash matching into a false semantic proof; shell/tool-output prompt injection; wrong project/runtime attachment. **Obsoletes:** separate accept-then-promote administration for one curated capture, grade editing by hand, repeated view rebuilds for that workflow. The schema/OMP ID mismatch must be fixed first.

**Constitution.** Explicit human **or agent** curated reconsolidation with provenance/evidence is compatible with `learning-boundaries.md:19-20` and the plan's human/agent review diagram (`plan:49-52`). Fully unattended background promotion of new semantic claims is **not safely authorized**: it needs an explicit constitutional amendment defining allowed proof classes and review responsibility. “Hash matches” must not become automatic TESTED/VERIFIED. Global policy promotion retains owner/version/baseline/rollback requirements (`learning-boundaries.md:21-35`).

**Cheapest confirm/kill experiment.** First replay ten real candidate episodes in temp homes with deterministic validators, including false-adjacency successes, missing evidence, cross-project evidence and changed source. Require zero unsafe promotion and successful delivery in a new actual host session. Then, only if needed, matched `openai-codex/gpt-6-astra` sessions: existing note flow versus in-session curated transaction; report useful delivered memories per discovery, authoring tokens, verification tokens, latency and subsequent-task correctness. Kill if verification cost exceeds avoided rediscovery or if unsupported semantic claims pass.

### B. Memory as a dependency-aware cache, not a timeless database

**Concrete change.** Publish each claim with a **validity lease** over relevant dependencies: repo/symbol hash, tool version, platform/config fingerprint or session/build identity. At the next relevant read, check a cached dependency stamp; hash only changed dependencies. A missing or changed dependency makes the derived item unavailable/pending revalidation; preserve canonical history. Recompile/revoke when validity changes, regardless of record-file edits. Add a read-only check for explicit pull too, so stale memory is labeled rather than silently current. Use trusted semantic predicates where available; an unrelated file edit should request revalidation, not prove the claim false.

**Type-specific policy [DESIGN].** Session state ends with its session/build; operational locators and procedures depend on sources/tool versions; environment gotchas depend on runtime/config; historical facts stay historical; decisions expire only through explicit supersession, not arbitrary age. TTL is a fallback revalidation schedule for evidence without stronger dependencies, not a truth rule.

**Change of kind.** Currentness is computed from live dependencies at use, not inferred from old timestamps or periodic sweeping.

**Expected effect.** Deterministically closes the two reproduced freshness failures. [INFERENCE] Avoids large retirement sweeps for mechanically checkable state, at bounded local I/O cost and zero model tokens for unchanged evidence. **Effort:** M. **Risk:** hashing expensive files, overinvalidating whole-file edits, trusting a historical report for current runtime, accidentally widening foreign roots. **Obsoletes:** manual blob-staleness reports as the only enforcement, source-blind review fingerprint, missing-source permissiveness.

**Constitution.** Derived withholding/labile candidate creation preserves truth precedence and does not silently rewrite canonical knowledge. Automated canonical retirement or replacement still requires the curated path/amendment above. Do not delete contradictions; retain provenance (`truth-precedence.md:23-25`).

**Cheapest experiment.** No model: the exact temp cases exercised here—unchanged file, changed file, deleted file, unrelated edit, different installation version, foreign/missing root—must produce explicit fresh/pending/unavailable decisions both on pull and JIT, while retained history remains readable. Then an `openai-codex/gpt-6-astra` stale-advice task checks whether withholding actually improves correctness without costly repeated validation.

### C. Learn one durable operation from an episode, not one fact per checkpoint

**Concrete change.** At a natural verified completion point, the current agent emits at most one compact **condition → action → proof** delta, or explicitly abstains. Distinguish `episode` evidence, `state` checkpoints, reusable `locator`/`gotcha`, and real multistep `procedure`. Link repeated trials to one conclusion; add an explicit stable subject key for supersession. Do not ingest an end-of-session general narrative wholesale. Commit trailers can carry the same concise delta, but must preserve full provenance, privacy and triggers rather than a clipped title.

**Change of kind.** Memory acquisition optimizes expected future avoided work, not recall of what happened. Episode transcripts/ledgers remain evidence; they do not compete as current operational advice.

**Expected effect.** [INFERENCE] Directly targets the **56 fact retirements**, repeated individual-trial records and runtime-address checkpoints found here. No claim that all 56 could have been prevented automatically. **Effort:** M. **Risk:** omitting rare but useful exceptions, hallucinated causal summaries, replacing true historical facts with overgeneralized advice. **Obsoletes:** indiscriminate checkpoint-as-fact import and title-similarity “consolidation” as the main lifecycle tool; conversion remains preservation-only.

**Constitution.** Automatic summaries may become logged shadow candidates (`learning-boundaries.md:5-12`). In-session curated promotion is allowed; unattended learned rules affecting future behavior require the explicit gate/amendment. Model-specific quirks stay model-scoped (`:34-35`).

**Cheapest experiment.** Use ten already-retired clusters and the surviving source ledger, without live collection. Have `openai-codex/gpt-6-astra` produce deltas in the owner's existing subscription session; independently verify against sources and evaluate unseen task pairs. Include “nothing worth remembering” controls. Kill if it manufactures proof, loses necessary scope, or costs more tokens than the future tasks save.

### D. Make procedures native skills, but publish them as managed revisions

**Concrete change.** Only a procedure with applicability, ordered steps, preconditions, verification and failure boundaries qualifies. Use the host's skill-discovery channel for its compact description and load the full procedure only on need. Brain retains cross-host canonical provenance, source revision, privacy/scope and retirement links. Publish to a dedicated owned target with a manifest mapping skill to record/revision; invalidate/update or remove the **owned** generated copy when its lease expires. Do not overwrite unrelated skills, silently expose private/project records in global catalogs, or keep the same procedure's full text in both Brain pushes and skill bodies. Plain-shell agents retain explicit CLI/file access.

**Change of kind.** Procedural knowledge becomes an executable-on-demand workflow in the agent's existing interface, rather than generic memory prose.

**Expected effect.** [INFERENCE] Better selection and fewer repeated procedure fragments for actual multi-step workflows. **No evidence-backed benefit for the current 33-character “Migration ordering” item**; keep that a fact/invariant, not a skill. **Effort:** M. **Risk:** skill catalog/context bloat, a second stale store, scope leakage, skill text mistaken for authorization. **Obsoletes:** unmanaged one-off `export-skill` copies for production use; procedure prose repeated as JIT warnings.

**Constitution.** Existing reviewed procedure export can remain advisory. Automatically promoting learned skills/global policy to ACTIVE requires lifecycle evidence, baseline, owner/version and rollback (`learning-boundaries.md:10-11,21-35`); publishing unreviewed candidates as actionable native skills is not shadow mode. Change-control explicitly stops on unrelated skill-directory overwrite or failed skill security review (`change-control.md:38-43`).

**Cheapest experiment.** First identify **one real recurring multistep workflow**, not the current one-line invariant. Compare native skill versus Brain pointer/body on matched `openai-codex/gpt-6-astra` tasks, holding content constant; count discovery/body-load tokens, completion correctness and source-staleness behavior. Kill if catalog overhead or double delivery exceeds savings.

### E. Replace online usefulness guessing with sparse, outcome-grounded evaluation

**Concrete change.** Keep exposures and record revisions; move the current six-event scorer outside ordinary review/selection. Evaluate a small set of candidate changes against native behavior and fixed JIT on frozen subsequent tasks with actual correctness/token/latency outcomes. For in-session feedback, accept a precise “wrong/stale because…” correction with evidence, not a popularity vote. A record read or command success is engagement, not truth.

**Change of kind.** Optimize the product from observed task benefit instead of using self-reinforcing interaction proxies.

**Expected effect.** [INFERENCE] Less selector maintenance and fewer unjustified suppressions; no measured cost saving for deleting this scorer. **Effort:** S for decoupling, M for outcome-grounded evaluation. **Risk:** fewer automatic diagnostics; sparse evaluation misses long-tail benefits. **Obsoletes:** default review-time scoring, proxy suppression until a held-out benefit is demonstrated. **Constitution:** compatible; raw statistics may remain shadow data, never canonical authority.

**Cheapest experiment.** No agent run initially: label existing delivered episodes against actual task outcomes and compare the proxy labels, including one-harm/two-uninformative suppression and legitimate follow-up searches. Only then use `openai-codex/gpt-6-astra` fixed-vs-scored held-out tasks. Kill the selector if proxy labels disagree materially or scored mode loses correctness/token neutrality, per the existing plan.

## Kill list

1. **Stop calling note→accept→promote a working learning loop.** The actual path remains OBSERVED; eligible captured IDs then break OMP loading. Fix contract closure before building more capture interfaces (`capture.py:799-823`; `index.py:499-537`; `index.ts:312,522`).
2. **Stop requiring accept and promote as separate administrative publications for an already curated item.** Both rebuild index/views but accept does not make advice usable (`capture.py:1018-1028`; `index.py:532-536`). Retain separate quarantine state, not duplicate agent ceremony.
3. **Stop treating nonempty evidence or an unchanged historical report as current proof.** Promotion checks presence, not validity; compiler misses missing non-locator sources (`index.py:507-510`; `views.py:495-527,589-597`).
4. **Stop representing transient process addresses, trial checkpoints and superseded architecture as durable current facts.** Keep historical evidence; publish durable conclusions or locators instead (`promotion/PROPOSAL.md:37,39,110-111`).
5. **Stop automatic maintenance coupling to outcome scoring while it has no qualified selector benefit.** Move it behind explicit evaluation; keep `scored=false` (`commands_capture.py:79-116`; `config/jit.toml:1-6`).
6. **Do not add another `brain note` or a generic session-summary system.** The former already exists; the latter risks reproducing the historical-checkpoint corpus. Improve proof/publication rather than adding entry points (`capture.py:660-823`; `convert.py:183-203`).
7. **Do not export every procedure-tagged record as a native skill.** The sole current procedure is a 33-character invariant; unmanaged exports can survive source changes and retirement (`records/mem-a8d221e64549.md:23`; `skills_export.py:13-68`).
8. **Stop using cumulative record count as learning success.** The useful metric is verified, applicable future deliveries and avoided work; migration had 120 records but only two eligible pushes (`migration/INVENTORY.md:9-22`).

## Open questions

- What precise deterministic claim classes should be authorized for unattended promotion, if any? The Constitution permits curated reconsolidation, not an unrestricted automatic semantic write path. This is an owner-reviewed policy decision requiring written rationale/reviewer/Git history (`change-control.md:3-9`), not a hidden implementation assumption.
- How many real future tasks recur with the same applicability conditions? The assigned corpus/maintenance artifacts establish storage and publication problems, not a recurring-task distribution or OpenAI-agent benefit estimate.
- Are two-stage accept/promote and missing grade mutation intentional ownership boundaries, or simply an incomplete agent-facing contract? Code and smoke prove behavior; they do not identify an approved TESTED attestation workflow for `brain note` outputs.
- What publication target can enforce native-skill project/private scope for each host? The current exporter can write a directory but provides no host-specific discovery/withdrawal contract.
- Why is retained maintenance state absent: never run in this home, run in another home, or removed later? The observed filesystem cannot settle history. Likewise, the capped dry scorer is not a complete retained-history analysis.

### Reproducible computation/probe notes

**C1 — corpus and state statistics.** Executed with the clean interpreter and `-B`; computations below are the relevant read-only expressions from the executed heredocs:

```python
from pathlib import Path
from collections import Counter
from second_brain.kb import records, capture, outcomes
import json, re
h = Path.cwd()
rs, errors = records.load_all(h)
print(len(rs), Counter(r.type for r in rs), Counter(r.status for r in rs))
print(Counter(r.type for r in rs if r.active))
print(sum(not re.match(r'^[^@\s]+@[0-9a-f]{7,40}', e)
          for r in rs for e in r.evidence), sum(len(r.evidence) for r in rs))
print(sum(any(re.match(r'^[^@\s]+@[0-9a-f]{7,40}', e) for e in r.evidence) for r in rs))
print(sum('last_verified_at' in r.extra for r in rs))
print(Counter(r.extra.get('captured_from', 'none') for r in rs))
print(len(capture.inbox(h)))
print({x: (h/'state'/x).exists() for x in [
 'kb-capture-cursor.json', 'kb-score-cursor.json', 'kb-scores.json',
 'kb-outcomes', 'kb-review.json']})
print(capture.stale_evidence(h))
p = json.loads((h/'outputs/reports/v3-jit/promotion/proposal.json').read_text(encoding='utf-8'))
retired = [r for r in p['records'] if r['verdict'] == 'retire']
print(Counter(r['type'] for r in retired), Counter(r['scope'] for r in retired))
print(Counter(str(r['project']) for r in retired))
print(sum('subsum' in r['reason'].lower() for r in retired))
print(sum('orchestration' in r['reason'].lower() for r in retired))
print(vars(outcomes.run_scoring(h, dry_run=True)))
```

Command form: `env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -B - <<'PY'` followed by the Python and `PY`. Snapshot outputs are reported above; logs can continue to grow while agents are active.

**C2 — actual code paths exercised in temp homes.** The same interpreter command created a `TemporaryDirectory`, a minimal project manifest and a source file; called actual `cli.main(...)` for note/review/accept/promote; inspected `views.compile_triggers`; authored a TESTED grade only inside that temp home; called review before/after a source change; deleted the source and called `compile_triggers` plus `stale_evidence`; exported an evidence-empty TESTED procedure using `skills_export.export_skill`; and called `_aggregate` on the three explicitly described synthetic observations. The source-freshness check was separately run with `write_bytes` to eliminate CRLF/LF fixture ambiguity. Timings used `perf_counter` around `cli.main`, so exclude interpreter startup. These are investigation smoke probes, not permanent tests or benchmark campaigns.

**C3 — actual adapter execution.** A clean-interpreter heredoc created two temp homes with Python `records.save`/`views.compile_views`: one held `mem-abcdef123456`; one held that record plus `note-abcdef123456`, both global current TESTED gotchas with the same error trigger. For each home Python ran `subprocess.run(['bun','-e',js], text=True, capture_output=True)` against the real adapter. Essential executed JavaScript:

```javascript
import extension, { flushObservations } from '<repo>/brainstem/omp-v3/index.ts';
import { readFileSync } from 'node:fs';
const handlers = {};
extension({ on: (n, f) => handlers[n] = f }, { SECOND_BRAIN_HOME: home });
const ctx = { cwd: home, sessionManager: { getSessionId: () => 'fixture-session' } };
handlers.before_agent_start({}, ctx);
const result = handlers.tool_result({
 toolName: 'bash', input: { command: 'python fixture.py' }, isError: true,
 content: [{ type: 'text', text: 'ValueError: trap' }],
 details: { exitCode: 1 }, toolCallId: 'one'
}, ctx);
await flushObservations();
const telemetry = readFileSync(home + '/telemetry/kb-hooks.jsonl', 'utf8')
 .trim().split(String.fromCharCode(10)).map(JSON.parse);
console.log({ delivered: !!result, decisions: telemetry.map(x => x.decision) });
```

Both corrected probe invocations exited 0. The initial scratch JS invocation had a string-escaping parse error and did not exercise the adapter; only the corrected runs support the delivery claim. All temp homes were removed by `TemporaryDirectory` cleanup. No actual host/provider request was made.
