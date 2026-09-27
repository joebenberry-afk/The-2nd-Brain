# FieldTelemetry — real-use evidence audit

## Top findings

### 1. The current JIT system was effectively silent in the retained pre-audit field window — HIGH

**Claim.** Before this audit, 15,961 V2 tool-result opportunities produced **zero JIT items, zero distinct exposed records, and zero JIT tokens**. This is not a benchmark result: most events came from other actively used projects.

**Evidence.** Computations C2–C4/C6 below, frozen at `2026-09-26T16:44:11.724Z`, the first event from the current audit's writer `a602fcea`. The retained KB event window is `2026-09-25T15:06:24.936Z`–`2026-09-26T16:25:40.805Z`; hooks begin at 15:05. The snapshot contains **21,681 KB rows in 311 files**, including 5,162 older V1 rows and 16,519 V2 rows. Filtering before the current audit is essential: our own Python analysis commands immediately caused PYTHONHOME memory delivery and would otherwise manufacture apparent field success.

| Hook event | Opportunities | Positive deliveries | Estimated tokens |
|---|---:|---:|---:|
| Older brief | 40 | 8 | 3,040 (380 each) |
| Older correction | 184 | 0 | 0 |
| JIT | 15,961 | 0 | 0 |
| JIT session start | 282 | 0 | 0 |
| Recovery | 2 | 0 | 0 |

JIT decisions: **15,373 `no_match`; 490 `no_view`; 97 `unsupported_shape`; 1 `duplicate`**. The V2 hooks represent 271 distinct session IDs, not 271 independent user tasks. Older brief rows have neither record IDs nor session identity; their record counts/follow-through cannot be recovered. Examples: `telemetry/kb-hooks.jsonl:1-6` and `:33-35`.

Token fields are **estimates**, not tokenizer/billing measurements: `brainstem/omp-v3/index.ts:16` uses `ceil(chars/4)`. Summed hook runtime is only 8,281.86 ms, including 7,115.96 ms for JIT; median hook is 0.36 ms (C6). Runtime overhead is not the main failure here; **lack of useful exposure is**.

**Impact.** Within this observed window, JIT delivered no actionable memory at all. A delivery precision proxy has denominator zero; it is **undefined**, not “0% precision.” This does not prove every possible task would get no benefit, nor does it attribute correctness causally.

### 2. Real usage is cross-project, but project registration erases the path evidence needed to help it — HIGH

**Claim.** **97.22% of V2 tool results (15,518/15,961) have `project=null`, and every one of those 15,518 rows has `paths=[]`.** They retain 813 search-term rows and 1,884 shell-command rows, so they are not empty sessions.

**Evidence.** C4/C6; `brainstem/omp-v3/index.ts:209-220` deliberately returns no observation paths when there are no registered roots. Registered manifests are only Second Brain plus P22 gamma/delta fixtures; `projects/second-brain/project.toml:3-6`, `projects/p22-project-gamma/project.toml:3-5`. On-disk counts alone do not infer lack of activity elsewhere:

| Actual cwd family, V2 tool results | Events | Distinct session IDs* | Reads | Searches** | Error rows |
|---|---:|---:|---:|---:|---:|
| Absolute Laya | 12,390 | 232 | 5,208 | 1,285 | 498 |
| Dragon Ball SZ Modding/worktrees | 1,758 | 11 | 695 | 117 | 114 |
| BasicUpscaler/subdirectories | 1,366 | 17 | 639 | 147 | 69 |
| The Second Brain | 443 | 2 | 224 | 47 | 14 |
| CoreCycler | 4 | 1 | 0 | 0 | 0 |

*IDs can occur in more than one cwd family; columns are not additive session counts. **grep/glob/find/ast_grep. All KB hooks identify host `omp`.

The two mapped Second Brain sessions retained 191 pathful rows, 29 search-term rows and 63 commands; even they produced zero JIT deliveries. External session example: `state/kb-events/01f9d8a3db4c7c27.9b0cf0ed.jsonl:2` records BasicUpscaler read success with `project:null`, `paths:[]`.

**Impact.** The Brain is installed in real multi-project work, but its path-trigger/capture mechanisms cannot see most of that work. This also makes a “no matching knowledge” metric ambiguous: **missing registration is being mixed with lack of useful knowledge**. This is a reach/observability problem before it is a ranking problem.

### 3. The most repeated unmet demand is host-operation knowledge, not another repository summary — HIGH counts; MED recoverability

**Claim.** A small set of cross-project operational mistakes recurs far more than the capture pipeline harvests. None of the following errors matches any **current** record's literal `trigger_errors` (C6, using `triggers.error_matches`).

Counts exclude `eval` echoes of failed inner tools, so they do not count both a failed `read` and its propagating eval exception as two underlying mistakes.

| Uncovered failure class | Failed underlying calls | Sessions | Example source |
|---|---:|---:|---|
| Wrong edit/hashline grammar | **118** | **53** | `state/kb-events/048c5fc53427281d.jsonl:145-146`; `07815f6795bb0413.jsonl:48` |
| Missing `tools/edit` documentation hunt | 13 | 13 | `state/kb-events/0bf561789cb26747.2d092c3b.jsonl:55` |
| Invalid service invocation (`async`/`timeout`, or missing service name) | 20 | 16 | `state/kb-events/048c5fc53427281d.jsonl:41-43` |
| Running Git outside a repository | 15 | 15 | `state/kb-events/12fe5ea69effe2cf.ebc9b822.jsonl:6` |
| Wrong `yield` success protocol | 12 | 12 | `state/kb-events/0d39759b0d6c8881.ebc9b822.jsonl:9` |
| Looking for nonexistent `CLAUDE.md` | 16 | 14 | `state/kb-events/0b73a1611bf967e4.22c4f5f9.jsonl:3` |
| Backslashes consumed from `C:\Python314\python.exe` | 5 | 5 | `state/kb-events/4aa62fb0cd8dcd4b.62b23c84.jsonl:18` |
| Searching nonexistent installed `laya` package path | 4 | 4 | `state/kb-events/12fe5ea69effe2cf.ebc9b822.jsonl:20` |
| Grep timeouts | 3 | 3 | `state/kb-events/39b33e8a57de6227.62b23c84.jsonl:59` |

**206 failed calls**, 30,769 logged error characters, are addressable investigation targets. The latter is approximately **7,692 chars/4 tokens in error text alone**, not the full retry cost and not proven avoidable savings. Some wrong-cwd probes are legitimate discovery; don't label every one waste. Three explicit 30-second grep timeouts represent at least **90 seconds of tool timeout budget consumed**, not necessarily 90 seconds on the user's critical path.

Other recurrence: exact `git status --short` appears 23 times across 22 file/session identities, 12 failures; `repowise status` appears 14 times across four, four failures (C4). These are better candidates for reusable environment/host facts than blindly memorizing commands. `Daemon broker request aborted` appears 34 times in four sessions, but there is no demonstrated repair; do not fabricate a memory that purports to fix it.

**Impact.** [INFERENCE] Host-version-scoped executable examples could eliminate a meaningful fraction of 118 edit retries and 20 service errors, while benefiting agents in all four project families. This is a change in the kind of knowledge supplied, not an 80-token budget adjustment.

### 4. There is no retained V3 capture lifecycle; running the real producer on a copy yields only three proposals — HIGH

**Actual state.** `state/kb-inbox`, `state/kb-capture-cursor.json`, `state/kb-outcomes`, `state/kb-scores.json`, and `state/kb-score-cursor.json` are absent (C1). V3 candidate storage is explicitly `state/kb-inbox`: `src/second_brain/kb/capture.py:28-35`. Capture writes candidates and checkpoints only when invoked: `capture.py:491-586`; `brain review` invokes capture/scoring in `commands_capture.py:108-119`.

Thus **zero retained V3 inbox candidates, zero retained capture acceptance evidence, and no retained outcome counters**. This is not proof that files were never deleted in the past. The 121 canonical records contain no `captured_from` metadata at all: 18 current, 35 candidate, 63 superseded, 5 retracted; six have `promoted_at`, but cannot be attributed to V3 event capture (C4). Do not count those six as automated capture promotions.

**Executed smoke/replay, no repository mutations.** C5 copied frozen events plus records/project manifests to `C:/Users/assas/AppData/Local/Temp/field-capture-dngg9zm3`, then called the real `capture.capture_events()` until drained. Passes consumed **128, 128, 55, 0 files**; output **3 gotchas, 0 locators, 1 deduplication**. All three came from **V1** observations. There are not ten real V3 proposals to sample.

| Scratch-produced candidate | Judgment | Reason/evidence |
|---|---|---|
| `got-5c56ea624a40` — backslash venv path fails, slash path succeeds | **Worth curating**, not blindly promoting | The actual invocation change is specific and reusable for Windows shell use. Retain the general rule, not the long one-off hash-calculation command. Replay JSON contains both source event refs. |
| `got-59bc2d5713d5` — relative venv unavailable, explicit SZ toolkit venv succeeds | **Worth curating only with correct project scope** | Current candidate is global (`project:null`); a project-specific absolute interpreter path must not become global advice. |
| `got-47111c0abcd1` — `tsc` export errors, later `vitest; tsc` succeeds | **Reject as a durable fix** | Temporal success does not show adding vitest fixed missing TS exports. Candidate body admits “candidate only, not a verified fix.” Underlying code likely changed [INFERENCE]. |

The failure-pair producer is a temporal association, not a causal diagnosis (`capture.py:310-340`, `:535-550`). Locator capture requires a registered project and observed paths and a successful edit ending a sufficiently long hunt (`:346-374`, `:429-471`). The missing 97% path coverage directly undermines this lane.

**Ten existing canonical candidate samples.** A deliberately stratified sample of the 35 existing candidates follows; these are **older retained candidates, not falsely claimed V3 inbox output**, and judgments are an audit assessment rather than a verified promotion decision.

| Candidate / source | Worth keeping? | Assessment |
|---|---|---|
| `mem-3748f4ba9c43`, `records/mem-3748f4ba9c43.md:3-17` | **Yes, scoped gotcha** | `/proc` recursive mkdir hangs; regular-file parent gives deterministic ENOTDIR. Concrete symptom, alternative and commit evidence. |
| `mem-6863d65a700f`, `records/mem-6863d65a700f.md:3-16` | **Yes, improve evidence** | `pkill -f` can match the invoking shell; explicit-PID alternative is useful. Session-only evidence and platform specificity need care. |
| `mem-e3729ae8669f`, `records/mem-e3729ae8669f.md:3-20` | **Yes, condense** | Cloud and Windows local-source availability differ; useful eval environment boundary, not generic model guidance. |
| `mem-bde4dc4aee9e`, `records/mem-bde4dc4aee9e.md:3-20` | **Yes, condense/revalidate host version** | Stop is per-turn, not session-close. Actionable integration invariant; body contains stale line-number narrative and malformed evidence fragments. |
| `mem-6849e6dc3a1f`, `records/mem-6849e6dc3a1f.md:3-18` | **Yes, correct project first** | Governor snapshot semantics matter to tests/soaks; currently `project: unknown` despite BasicUpscaler source evidence. Prefer semantic invariant + locator over completed-fix story. |
| `mem-b10a5474054e`, `records/mem-b10a5474054e.md:3-17` | **No as evergreen memory** | “Ledger passed through seq 520 on one date” is an audit artifact, not future operational knowledge. Archive with that run. |
| `mem-771d74aaa3fd`, `records/mem-771d74aaa3fd.md:3-16` | **No as evergreen memory** | “P2 recovery proven” is a closure claim with no useful action or narrow trigger; keep in historical report. |
| `mem-5ec9b9283907`, `records/mem-5ec9b9283907.md:3-16` | **Not as a fact** | Unverified threshold hypothesis plus temporary experimental protocol. Keep in experiment state with expiry, not durable push knowledge. |
| `mem-58f449274500`, `records/mem-58f449274500.md:3-16` | **Yes as a caution, if still unresolved** | Don't equate a HUD gauge and telemetry field by name; synchronized cross-validation requirement prevents a real inference error. Needs current-state check. |
| `mem-0fcad79fd46b`, `records/mem-0fcad79fd46b.md:3-14` | **Yes after evidence repair/condensing** | Distinguish circular-arrow Change glyph from numerical Skill Stock. Useful correction; current evidence is an external Downloads document without hash. |

Assessment: **7/10 potentially useful after curation; 3/10 should not be evergreen facts**. This is not random-sample corpus precision. “Worth keeping” does not mean the truth/evidence gates have been satisfied.

Legacy side stores also fail to establish a working learning loop: `state/radar/candidates.json` contains **101 candidates** (74 REPEATED_READ, 22 TOOL_ERROR_LOOP, 5 SEARCH_THRASH), all candidate lifecycle and all `promotion_eligible:false` (C7). Its summed 99,550 “expected benefit tokens” is a heuristic, **not realized savings**: repeated-read estimates are `(count - 1) * 300` (`src/second_brain/radar.py:382-394`). Historical telemetry records just three `writeback_candidate` and one `hermes_writeback_candidate`; these are not V3 capture accepts.

### 5. Agents do not visibly choose the new query/write commands; automatic retrieval is not voluntary usage — HIGH within log coverage

**Claim.** In **2,219 KB logged shell commands**, no executable `brain q`, `brain show`, `brain note`, or actual `brain add` invocation was found. One `python -m second_brain.kb add --help` is help exploration, not a write. The CLI activity that is visible is implementation/maintenance probing: `views`, `jit-match`, `brief`, `doctor`, and help.

**Evidence.** C4 parses shell command segments with the repository's normalizer; C6 also checks preserved raw text so unsupported shell forms are not silently assumed absent. Example help sequence: `state/kb-events/1a74fedd03b2dd75.a9a69ea9.jsonl:14,34,36,38,40`. Regex text mentions in commit messages or grep patterns are explicitly not command invocations. C7 scans the **15,256 historical tool_call command strings** and finds no `brain q/show/note/add` text either. The 114,692 legacy tool calls do not retain read/query arguments; only 15,256 shell commands and 27,627 read-target hashes are available (`brainstem/prime-extension/src/sensors.ts:506-539`). Arbitrary shell wrappers/scripts and truncated command tails remain blind spots.

**What they query / hit rate.** There are **no observed voluntary V3 queries whose contents or hit/abstain results can be analyzed**. It would be false to say “queries abstain 100%”: the observed query count is zero. Legacy `brain_retrieval_attempt` has 3,920 automatic attempts, with task SHA rather than raw query; it is not evidence of an agent deciding to call `brain q`. Legacy `brain_no_injection` reasons include ALREADY_DELIVERED 1,401, NO_RELEVANT_MEMORY 957, WRONG_PROJECT 291 and CONTEXT_PRESSURE 255 (C4). These historical counts include self-development/probes and are not a clean field-only hit rate.

**Impact.** [INFERENCE] A product depending on optional agent-authored `brain note` or exploratory `brain q` has effectively zero distribution in the observed new-command lane. Discoverability, host integration and automatic capture must be evaluated separately from retrieval quality.

### 6. Historical delivery exists across hosts, but telemetry names easily overstate it — HIGH counts; MED attribution

**Claim.** The legacy runtime actually delivered memory, but `brain_packet_delivered` is **preparation**, not authoritative model exposure. All 940 such rows that have a visibility field say false by design (`src/second_brain/autoinject.py:21-26`, `:1763-1769`). The host signal is `autoinject_shadow_decision`. Merely `model_visible:true` is also insufficient: active-mode NO_INJECTION rows can carry that flag. C8/C9 require **decision=INJECT, model_visible=true, and positive packet tokens**.

| Historical lane | Opportunities | Actual-positive memory packets | Sessions | Estimated packet tokens |
|---|---:|---:|---:|---:|
| Prime/OMP host autoinject | 2,611 | **741** | 463 | 436,865 |
| Antigravity preinvocation | 1,118 | **122** | 50 | 70,822 |

These are **mixed historical telemetry, not a clean non-benchmark efficacy estimate**. Of OMP's 741 positives, 619 have cwd exactly this repo; explicit campaign/probe/worktree roots also appear. A stronger external-project slice has **14 memory packets across 11 sessions** (eight at SZ-Agent-Toolkit, six at Dragon Ball SZ Modding), all positive host delivery. No BasicUpscaler memory packet appears in this historical positive slice. There are nevertheless 91 BasicUpscaler active-state capsules (84 root + seven nested), so host integration did run there.

**Distinct records and counts.** Join `(session, packet_sha256)` to prepared packet hash, falling back to packet ID. **476/741 positive OMP packets can be assigned selected IDs; 265 lack recorded IDs.** The identifiable subset contains 33 distinct records and 1,497 item exposures. Full counts (this is historical mixed-scope delivery, not current JIT):

| Record ID | Count | Record ID | Count | Record ID | Count |
|---|---:|---|---:|---|---:|
| mem-99df66e3c8f6 | 212 | mem-bb634354ec69 | 184 | mem-f5ad9ae46d7c | 184 |
| mem-f745bcb2eff2 | 159 | mem-3d8ffbd6538d | 124 | mem-d2f7df353130 | 107 |
| mem-174b3f5abbba | 85 | mem-60c403ed0839 | 78 | mem-b67de5057f76 | 66 |
| mem-29557f93448f | 66 | mem-e0ee543da163 | 42 | mem-fd5c6f1dc8b1 | 36 |
| mem-79d7c4fd9876 | 26 | mem-7ee245204a5e | 25 | mem-a8d221e64549 | 24 |
| mem-b0d6cc3de0ab | 20 | mem-f21a28b715f1 | 18 | mem-812f9bb08444 | 11 |
| mem-5ee4c7712fa3 | 7 | mem-e6a79159acd1 | 4 | mem-3848b16778bd | 3 |
| mem-333cb2aae270 | 2 | mem-ad3d80115ee2 | 2 | mem-42f674862947 | 2 |
| mem-7dda00fb6cdc | 2 | mem-771d74aaa3fd | 1 | mem-eaaccf45995d | 1 |
| mem-a6c1b8123c08 | 1 | mem-5bc2da33777a | 1 | mem-bde4dc4aee9e | 1 |
| mem-17cdb5558c11 | 1 | mem-69e44c5b85a5 | 1 | mem-494903a96872 | 1 |

The external identified subset is only six packets: `mem-7dda00fb6cdc` twice; `mem-eaaccf45995d`, `mem-17cdb5558c11`, `mem-69e44c5b85a5`, `mem-494903a96872` once each. Example actual host receipts: `telemetry/agent-performance/2026-09-16T07-37-43-238Z_01a0a926-6e46-7421-9455-b999853a5c58.jsonl:771`, `2026-09-24T21-25-23-765Z_01a0d54f-10b5-7253-99b8-51b51515e993.jsonl:925`.

Of all 1,497 identifiable historical item exposures, **1,287 are now superseded records**, 206 currently current and four candidate (C10). The top three are completed/blocked Antigravity repair state and a P3.1 “capsule proven” claim. This **does not prove they were stale when delivered**; it demonstrates how much exposure history is transient project status rather than durable operating knowledge.

**Precision/follow-through limits.** V3 has zero exposures. Legacy read targets are hashed, no tool query/path text is retained, and historical packet content/revision is incomplete. Current canonical paths cannot safely reconstruct what historical packets said. Consequently no trustworthy “used delivered path/command” precision rate can be produced from this store. Don't substitute successful delivery for successful use.

**Other hosts.** All current KB hooks are OMP; older telemetry contains Antigravity (1,118 preinvocations), Codex (412 shadow-hook decisions: 301 BRAIN_UNAVAILABLE, 107 NO_RELEVANT_MEMORY, two null, one CONTEXT_PRESSURE, one WRONG_PROJECT), Claude Code (159 explicit host-tagged rows in inventory) and Hermes (101 explicit host-tagged rows). Historical manifest hosts: prime 1,241; worker-protocol 29; omp 5; hermes 2. These are presence/instrumentation evidence, not equal production-quality support. No affirmative Cursor/plain-shell usage evidence was found in the audited stores. Model names include several OpenAI Codex subscription models, Anthropic, DeepSeek and Antigravity models; there is no controlled cross-model comparison here.

### 7. Large logs and state stores do not yet establish token savings or useful retained state — HIGH

**Read repetition.** C8 identifies **69 repeat reads across 41 sessions**, among 27,627 read calls with a target hash. It deduplicates tool IDs and treats any intervening edit/write/ast_edit/bash/eval/ipython/hub/task as invalidating reuse. Joined result volume is **494,072 bytes (~123,518 bytes/4 token proxy)**, including **231,236 bytes (~57,809 proxy tokens) in external DBSZ/BasicUpscaler sessions**. This is a **possible repeated-output surface**, not measured avoidable tokens: hash identity may omit separate offset arguments, result changes/compaction are unobserved, and model context replay/cache behavior is not represented. It is more conservative and auditable than Radar's fixed 300-token multiplier, but cannot justify a claimed savings percentage.

**State quality.** Across 919 `active-state.json` files, all have objective and 913 have next_action; only eight have confirmed_facts, 12 decisions, three files_touched, two brain_refs, nine open_questions (C2). Example `state/sessions/2026-09-25T14-37-22-808Z_01a0d8ff-dff8-71dc-913a-ad06587875b4/active-state.json:2-18` mostly repeats the delegated assignment and marks lifecycle verification. Historical host telemetry reports 1,527 active-state deliveries (728,794 rendered characters), but persistence is not evidence of substantive task-state learning.

**Other caches.** `state/autoinject-emit-cache.json:1` holds one negative result: NO_INJECTION/NO_RELEVANT_MEMORY, zero candidates/selected, one emit. It is not an outcome ledger. `.repowise/sessions/sessions.db` has one injection, a 130-character stale-read warning for `src/second_brain/cli.py`, `evaluated=0`, `acted=0`; this is unevaluated, not evidence of a failed intervention. `.repowise/hook-sessions` tracks three old sessions; numeric per-path values are sequence positions, not demonstrated read counts. RepoWise data provides no reliable extra Brain efficacy estimate.

## Breakthrough candidates

### A. Host-operating memory as a executable, version-scoped capability layer

- **Concretely:** Supply the valid host-specific edit grammar, service invocation contract, output/yield shape and verified doc locator at the relevant tool boundary. Store tested minimal examples and applicability (`host/version/platform`), not a long repository brief. Never silently rewrite destructive commands; warn or provide an exact safe example.
- **Change of kind:** Moves from passive repository facts to reusable knowledge of how the agent's actual tools work. It reaches the same repeated failures across unrelated projects.
- **Expected effect:** Addressable observed surface is 118 edit-grammar failures, 20 service failures, 12 yield errors and 13 failed edit-doc hunts. Actual avoided fraction and token/latency gains are [INFERENCE], not measured.
- **Effort:** M. **Risk:** Host drift; masking genuine tool changes; giving advice after rather than before first failure.
- **Obsoletes:** Treating all useful memory as project-triggered Markdown facts; duplicative host rules hidden in repository-specific records.
- **Cheapest experiment:** Replay the recorded error cases against deterministic host examples with no model call; then, if approved, use `openai-codex/gpt-6-astra` on 20 small authentic tool-operation tasks, memory on/off. Measure first-call validity, total logical tokens and elapsed time, not USD. Kill if instructions already solve the error or new guidance creates wrong-version failures.

### B. Workspace presence should work without manual registration

- **Concretely:** Detect a stable workspace/root identity automatically and preserve normalized observation paths even when no curated manifest exists. Separate `unregistered_workspace` from `no_match`. Maintain strict knowledge scope: discovery of a cwd does not authorize globally distributing its contents. Learn local locators in a private per-workspace lane.
- **Change of kind:** The current product is useful only for registered projects; this makes it available wherever the coding agent works, which is the actual observed deployment pattern.
- **Expected effect:** Restores potential path coverage for **15,518 currently pathless V2 events**. Useful match/capture gains remain [INFERENCE].
- **Effort:** M. **Risk:** Wrong root selection in monorepos/worktrees; privacy; cross-project contamination.
- **Obsoletes:** Manifest registration as a prerequisite for logging useful local path evidence; collapsing missing roots into normal no-match.
- **Cheapest experiment:** Deterministic offline replay of existing events plus real host payload fixtures from the external roots, held entirely in temp, and inspect root/path normalization and cross-project isolation. Then run approved `openai-codex/gpt-6-astra` field tasks on one external repo; demand a real saved hunt before expanding.

### C. Replace the dormant curator ceremony with a completed-action evidence loop

- **Concretely:** Trigger bounded maintenance automatically outside the model loop; capture a compact failure/repair or hunt/target proposal with its actual source diff and verification result, offer a one-action accept/edit/reject surface, and publish only after evidence and routing gates pass. Keep hypotheses and completed-run claims out of evergreen facts.
- **Change of kind:** A memory system that learns during normal work rather than hoping an agent decides to author a record or someone discovers an empty inbox command.
- **Expected effect:** Current retained V3 throughput is zero; existing producer replay gives only three low-level temporal associations. Improved useful learning rate is [INFERENCE]; the proof criterion is later reuse preventing a repeated operation/error, not candidate count.
- **Effort:** M/L. **Risk:** Correlation mistaken for repair, poisoning, background work creep, current ID/grade/publication incompatibilities (see LearningLoop report).
- **Obsoletes:** Relying on voluntary `brain note`/`brain add` as the main acquisition path; storing “passed once” as perpetual facts; Radar's candidate pile as evidence of learning.
- **Cheapest experiment:** Offline human audit of the three produced proposals plus ten real paired fixes before any automated promotion. After fixing reach, run one week of ordinary approved `openai-codex/gpt-6-astra` work with local capture on and count accepted useful proposals and later reuse; stop if the review cost exceeds avoided work.

### D. A single truthful exposure-to-action receipt, not more logging

- **Concretely:** One small receipt linking workspace, host, session, tool call, immutable record revision, actual insertion, and subsequent target access/retry result. Record absence reasons distinctly. Read fingerprints must include range/version if used to claim redundant-read savings. Keep full bodies/private arguments out unless explicitly needed.
- **Change of kind:** Turns “we prepared memory” into “this memory changed the next action.” It is prerequisite measurement, not a standalone usefulness feature.
- **Expected effect:** Eliminates 265/741 unidentified historical positive packets and zero-denominator precision confusion in future data [INFERENCE]. It does not itself save tokens.
- **Effort:** S/M. **Risk:** Instrumentation bloat, privacy, proxy gaming.
- **Obsoletes:** Treating `brain_packet_delivered`, `model_visible:true` alone, or arbitrary Radar estimates as efficacy; duplicate divergent telemetry schemas.
- **Cheapest experiment:** Offline fixture with one INJECT, one NO_INJECTION, one shadow preparation and one actual use; require exact non-overlapping counts. No model required. The later efficacy trial must use `openai-codex`, not DeepSeek or OpenRouter.

## Kill list

1. **Stop claiming delivery from Python preparation or active-mode flags.** Source explicitly disclaims host visibility (`autoinject.py:21-26`); C9 reduces 2,027 active-visible rows to 741 positive memory packets. Preserve only the minimal needed actual receipt.
2. **Stop emitting long-lived completion/repair-status facts as evergreen knowledge.** Top historical exposures are now superseded lifecycle records; the two sampled “proven once” records have no future action. Move such data to run history/state with expiry, not broad push memory.
3. **Stop requiring voluntary `brain q`/`brain note` for baseline value.** Zero visible voluntary use in the retained command coverage. Keep manual commands for intentional retrieval/curation, but do not design the success path around them.
4. **Stop discarding local path observations when a project lacks a manifest.** This loses 97.22% of observed V2 tool-result path coverage; retain scoped local evidence without widening visibility.
5. **Stop equating candidate production with learning.** No persisted V3 lifecycle; 101 legacy Radar candidates all non-promotable; scratch producer's TS candidate demonstrates non-causal association. A useful later intervention is the outcome, not a file in a queue.
6. **Stop presenting Radar's 99,550 expected tokens as saved tokens.** Fixed-count heuristic at `radar.py:394`, no counterfactual proof. Likewise don't turn 494 KB repeated output into a promised 123K-token saving.
7. **Do not build a larger repeated-read cache first.** Only 69 repeat-read opportunities survive the conservative available-data filter; missing workspace reach and repeated host misuse have clearer field demand. Cache priority is [INFERENCE] pending actual context/range-aware measurement.

## Open questions

- Did another brain home or deleted/rotated state hold V3 inbox/outcome data? The audited root contains none; there is no evidence authorizing a claim about every installation.
- Why did the two mapped pre-audit Second Brain sessions miss every trigger? Knowledge applicability, generation contents and the actual call shapes need replay beyond this telemetry slice; the field data establishes absence of delivery, not its single cause.
- How many host-operation errors survive current `openai-codex` models given the exact host tool instructions? Historical telemetry mixes models; no cross-model transfer claim is warranted.
- What fraction of repeat reads were legitimately new ranges, reads after compaction or externally changed files? Existing read-target hashes lack enough context to settle recoverable tokens.
- Did historical memory improve correctness? Actual host insertion is measurable, but selected content/revisions and following raw read/query inputs are not complete enough for trustworthy precision or causal usefulness.
- Was every historical self-repo session organic? Explicit probes/campaigns are present. This report keeps historical totals descriptive and uses external-project slices as stronger field evidence; it does not invent a benchmark-clean self-repo denominator.

### Reproduction commands and artifacts

All scripts and replay writes are **outside the repository** under `C:/Users/assas/AppData/Local/Temp`. Repository access was read-only; no builds, lint/tests, formatter/installers, view rebuilds, paid/model campaigns or source edits were run. Real capture behavior was exercised only against the temporary home. Models were never called for experiments.

Every numbered command used the prefix:

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -B
```

Run from the repository cwd, append:

| ID | Script/arguments | Main output |
|---|---|---|
| C1 | `C:/Users/assas/AppData/Local/Temp/field_telemetry_audit.py inventory` | `field_inventory.json`: schemas, stores, 788,955 historical rows, missing-state proof |
| C2 | `C:/Users/assas/AppData/Local/Temp/field_telemetry_detail.py` | `field_frozen.json`, `field_detail.json`: fixed cutoff snapshot, state content counts |
| C4 | `C:/Users/assas/AppData/Local/Temp/field_metrics.py` | `field_metrics.json`: delivery, commands, errors, canonical metadata |
| C5 | `C:/Users/assas/AppData/Local/Temp/field_capture_replay.py` | `field_capture_replay.json`: drained real producer and three candidate bodies/source refs |
| C6 | `C:/Users/assas/AppData/Local/Temp/field_final_metrics.py` | `field_final_metrics.json`: cwd groups, non-echo failures, missing error coverage, latency |
| C7 | `C:/Users/assas/AppData/Local/Temp/field_legacy_inputs.py` | `field_legacy_inputs.json`: shell-command coverage, Radar counts |
| C8 | `C:/Users/assas/AppData/Local/Temp/field_visible_audit.py` | `field_visible_audit.json`: authoritative-host join, conservative repeated-read proxy |
| C9 | `C:/Users/assas/AppData/Local/Temp/field_delivery_final.py` | `field_delivery_final.json`: positive actual exposures, ID counts, manifests/hosts |

C3 was a schema inspection of `field_inventory.json` and is subsumed by C2/C4; an initial shell-quoting attempt failed before reading data. Initial scratch-script syntax/edit-format mistakes were corrected before the successful computations; they made no repository changes.

C10 was this read-only inline calculation (same environment-clean Python prefix, passed via heredoc):

```python
import json, pathlib, sys, collections
r = pathlib.Path.cwd()
t = pathlib.Path(r'C:/Users/assas/AppData/Local/Temp')
sys.path.insert(0, str(r / 'src'))
from second_brain.kb import records
rs, _ = records.load_all(r)
by = {x.id: x for x in rs}
d = json.loads((t / 'field_delivery_final.json').read_text())
counts = d['autoinject_shadow_decision']['record_counts']
print(sum(n for _, n in counts))
print({s: sum(n for i, n in counts if by[i].status == s)
       for s in ['current', 'candidate', 'superseded', 'retracted']})
f = json.loads((t / 'field_final_metrics.json').read_text())
print(sum(v['calls'] for v in f['errors'].values()),
      sum(v['error_chars'] for v in f['errors'].values()))
```

Outputs: 1,497 identifiable item exposures; current 206/candidate 4/superseded 1,287/retracted 0; 206 categorized underlying failures/30,769 error characters. Temporary JSONs retain source `_file`/`_line` citations for row-level audit. No secret values are reproduced in this report.
