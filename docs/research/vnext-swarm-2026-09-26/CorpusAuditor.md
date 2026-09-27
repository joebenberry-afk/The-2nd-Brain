# Corpus audit — The Second Brain

Read-only snapshot, 2026-09-26. Scope: every canonical record; registered project manifests/knowledge files; published JIT generations and frozen views; named configuration/instruction channels; legacy stores. No repository files changed, no rebuild/test suite/installer/live model campaign ran. The actual record parser and JIT compiler were exercised **in memory**, with bytecode writes disabled. Historical DeepSeek results do not establish transfer to OpenAI agents. All proposed model experiments use the subscription provider **openai-codex**, measure tokens/latency, and do not use OpenRouter or USD economics.

## Top findings

1. **The effective product corpus is six deliverable items, not 121 memories—and two discard their most valuable content.** There are 121 parsed records, only 18 current. Published generation and fresh in-memory compilation both contain six IDs / 14 patterns. The Antigravity canonical body contains all 11 checked contract identifiers (conversationId, workspacePaths, transcriptPath, artifactDirectoryPath, stopHookArgs, executionNum, terminationReason, fullyIdle, injectSteps, permissionOverrides, overwrite); its 76.5-token JIT payload contains **zero**. Prime daemon delivery explains the cause but omits **--daemon-socket**, the repair. Evidence: src/second_brain/kb/views.py:433–444; records/mem-79d7c4fd9876.md:26; records/mem-b0d6cc3de0ab.md:28; current-generation second-brain/triggers.json:1 (full prefix below); computations C1/C2. A relevant record can be selected and still fail to deliver the required decision. **Impact:** 4/10 VG-M tasks ask for these omitted fields/repair (M05/M07/M08/M10); correctness uplift from rewriting is unmeasured [INFERENCE]. **Confidence HIGH.**

2. **The missing knowledge is a current orientation/authority map, not more host feature summaries.** There are **zero state, decision, or correction records**, and only one locator (Antigravity). Ten dated OMP 18.1.15 overview records consume **1,687.75 / 2,421.5 current title+body tokens (69.7%)**, with no JIT triggers. AGENTS names v4.2 as authoritative and omits records/ from its canonical list; project current-state calls v1.0.0 current and says V2 has not started; CHANGELOG announces V2; CLAUDE describes V3; the accepted JIT plan is newer than these pointers. Evidence: AGENTS.md:9–26; projects/second-brain/current-state.md:3–18; projects/second-brain/architecture.md:10–29; CHANGELOG.md:3–24; CLAUDE.md:17–31,70–73; docs/requirements/V3x_Just_In_Time_Memory_Plan.md:1–17. **Impact:** wrong entry points can send an agent into the legacy architecture; exact avoided work is unmeasured [INFERENCE]. **Confidence HIGH.**

3. **Scope metadata strands useful knowledge independently of retrieval quality.** All 70 domain-scoped records have neither project nor domain tags; projects.visible cannot expose them to any ordinary project. Twenty-five are candidates containing other-project experimental findings. The valuable current WGC timing correction is project=unknown, deliberately rejected by visibility. The retry-helper fact belongs to brain-pilot-demo, but that project has no manifest. Only second-brain and two P22 isolation fixtures are registered. **Impact:** only 16/18 current records are visible in any registered project; 6/18 are JIT reachable. No global records exist, so an unknown consumer gets no corpus help. Evidence: C1; src/second_brain/kb/projects.py:37,59–79,135–148; records/mem-d8227d4a3e7b.md:5–8; P22 manifests:3–5. **Confidence HIGH.**

4. **Duplication is real, but duplicate does not mean worthless before the moment of need.** Exclusive primary classifications: **a=4, b=10, c=4, d=0** (table below). Four current records repeat AGENTS, CLAUDE, or exact code comments, including important WAL and daemon hazards. They can save a search before the source is opened, but repeat information afterward. Python advisory repeats its title/body and costs 72.75 tokens; cloud advisory costs 66. Frozen brief costs 524.5 tokens, AGENTS 978.25, CLAUDE 1,067.75; these are competing surfaces, not evidence they are always simultaneously injected. Evidence: AGENTS.md:58–68; CLAUDE.md:64–65; src/second_brain/backup.py:619–629; brainstem/prime-extension/tests/integration/run-integration.sh:13–17; C2. Native dedupe is only a normalized-title substring option in the legacy brief renderer, not knowledge of what this agent already read (views.py:47,66–69,116–122). **Confidence HIGH for duplication; MED for usefulness judgment.**

5. **The value catalog no longer aligns with the current corpus.** Four task target IDs (M01/M04/M06/M09) are now superseded. M01's replacement names PYTHONHOME/PYTHONPATH, while its answer check requires **UV_INTERNAL__PYTHONHOME**; the launcher clears all three. M06/M09 ask old Brain orchestration policy although the current release removes Brain orchestration. Do not revive obsolete policy to improve scores. Evidence: outputs/reports/v3-agent-experience/value/tasks.jsonl:1,4,6,9; scripts/brainctl.py:11–12; records/mem-6d592dd0c627.md:24; CHANGELOG.md:28–34; C2. **Impact: 40%** of the ten-task memory catalog names superseded targets. This does not retrospectively prove which corpus historical runs loaded. **Confidence HIGH.**

6. **Legacy stores contain salvageable procedural knowledge, not another healthy semantic corpus.** The 129 legacy semantic files comprise 116 filenames already in records/, eight unmatched synthetic sentinel IDs, and five __v2 files whose bodies exactly match canonical counterparts. But 18 episodic files retain specific failure lessons: byte-exact CRLF restoration, shutdown writes lost to process.exit(), uv venvs without pip, and bounded deterministic result reuse. These are absent from current V3 records. The active SQLite skill contains a verification recipe much better than the current eight-token “numeric order” body. Evidence: C1/C2 and legacy table. **Impact:** preserve about four lesson families plus the migration procedure, then archive inactive channels; do not keep advertising their machinery as current. **Confidence HIGH for inventory; MED for archival boundary until installed-runtime dependencies end.**

### Census

Token estimate is normalized character count / 4, not a model tokenizer. Titles exclude the YAML key; bodies exclude frontmatter/outer whitespace. Appendix A contains every record's token sizes. All 121 files parse with the production loader; records/private/ is absent (zero private records).

| Dimension | All 121 | Current 18 |
|---|---|---|
| Type | fact 113; gotcha 6; procedure 1; locator 1; decision/correction/state 0 | fact 14; gotcha 2; procedure 1; locator 1; decision/correction/state 0 |
| Status | current 18; candidate 35; superseded 63; retracted 5 | current 18 |
| Claimed grade | OBSERVED 78; TESTED 20; VERIFIED 19; HISTORICAL 4; INFERRED 0 | TESTED 6; VERIFIED 12 |
| Effective current grade | — | TESTED 18; none independently attested |
| Scope | domain 70; project 51; global 0 | project 18 |
| Project field | second-brain 44; unset 70; unknown 5; brain-pilot-demo 1; smoke-proj 1 | second-brain 16; unknown 1; brain-pilot-demo 1 |
| Explicit domain tags | 0 | 0 |
| Title tokens | 2,078.75 | 435 |
| Body tokens | 28,092.5 | 1,986.5 |
| Title+body total | 30,171.25 | 2,421.5 |
| Title+body median (min–max) | 194.75 (4–949.25) | 163.75 (12.75–273.75) |

Unattested VERIFIED becomes TESTED by src/second_brain/kb/records.py:141–146. C1 checked current evidence: all 18 have at least one matching cited blob, with no changed cited file detected. **This verifies source identity, not present-day validity of a dated installation claim or independent attestation.**

| Status | Files | Title tokens | Body tokens |
|---|---:|---:|---:|
| current | 18 | 435 | 1,986.5 |
| candidate | 35 | 695 | 11,394 |
| superseded | 63 | 903.25 | 14,572.25 |
| retracted | 5 | 45.5 | 139.75 |

| Trigger coverage (nonempty field) | All | Current | Current coverage |
|---|---:|---:|---:|
| trigger_paths | 4 | 4 | 22.2% |
| trigger_commands | 2 | 2 | 11.1% |
| trigger_errors | 3 | 2 | 11.1% |
| terms | 10 | 6 | 33.3% |
| Any path/command/error | 7 | 6 | 33.3% |
| Published JIT reachability | 6 | 6 | 33.3% |

**Terms are not JIT triggers.** Only path/command/error fields are compiled (views.py:448–483). All six current records with actual triggers survive compilation. Ten second-brain current records are rejected with no_trigger; the other two current records have no registered recipient. Current generation **7419aca05aa3d747e6bd1858308e9dfe** has eight exact-path, one path-glob, three command-prefix, two error patterns (14 total), attached to six records. _none and P22 views are empty. Both retained older generations have five records / 12 patterns, without the replacement Python record. Three generations are derived snapshots, not three corpora.

Published evidence: views/current.json:1 and views/generations/7419aca05aa3d747e6bd1858308e9dfe/second-brain/triggers.json:1. Current pointer brief is 112.75 tokens / four pointers (Antigravity, migration, cloud, Python); legacy brief is 524.5 tokens / 16 titles with two correction entries. WAL and daemon facts are excluded from the pointer brief by type despite being useful (views.py:372,396–405).

### Every CURRENT record: value classification

Classes: **a** saves real work at a specific moment; **b** true but not an actionable delivery unit as written; **c** duplicate of AGENTS/CLAUDE/code comments; **d** stale/wrong. Classification is judgment [INFERENCE], not an experiment result. Category c takes precedence over a when the same remedy is explicit in an existing channel; it is not a deletion verdict. No current record was proved factually false. The worst demonstrated staleness is in competing project/instruction documents and record scoping. OMP records explicitly specify date/version, so they are not labeled wrong merely because the host advanced.

| Record (body evidence) | Class | Title / body tokens | JIT | One-line reason |
|---|---|---:|---|---|
| mem-0d394ab244f3 (records/mem-0d394ab244f3.md:27) | c | 20.75 / 40.5 | yes | Cloud bun/node:sqlite boundary is already in CLAUDE.md:64–65; do not spend another 66 tokens when loaded. |
| mem-29557f93448f (records/mem-29557f93448f.md:35) | c | 17.5 / 60.75 | yes | Important restore hazard duplicates backup.py:58–62,619–629,775–792; worth targeted pre-change delivery, not repeated prose. |
| mem-333cb2aae270 (records/mem-333cb2aae270.md:16) | b | 31.5 / 140.75 | no | Optional collaboration capabilities plus dated profile settings; potentially useful cautions need individual, current triggers. |
| mem-42f674862947 (records/mem-42f674862947.md:16) | a | 24 / 139.75 | no | Count parent and child usage once and retain unknowns: prevents invalid cost claims during delegated-run measurement. |
| mem-5bc2da33777a (records/mem-5bc2da33777a.md:16) | b | 30.25 / 144 | no | Configuration/provider-policy overview supplies no exact precedence rule or task-local action. |
| mem-5ee4c7712fa3 (records/mem-5ee4c7712fa3.md:16) | b | 28.5 / 153 | no | Old release-note digest mixes unrelated fixes; pull-only research, not an active work-saving rule. |
| mem-6d592dd0c627 (records/mem-6d592dd0c627.md:24) | c | 18.25 / 43 | yes | Exact machine-environment advice already in AGENTS.md:58–68; valuable only when that instruction is absent from context. |
| mem-79d7c4fd9876 (records/mem-79d7c4fd9876.md:26) | a | 17.25 / 256.5 | yes | Concrete installed-bundle/protobuf contract locator can replace reverse-engineering; its multi-topic body hides the requested fields from JIT. |
| mem-812f9bb08444 (records/mem-812f9bb08444.md:16) | b | 29.25 / 138.75 | no | Session/compaction taxonomy with a generic instruction to consult docs; no exact contract location or version-matched intervention. |
| mem-a6c1b8123c08 (records/mem-a6c1b8123c08.md:16) | a | 26 / 137.75 | no | RPC acknowledgement is not terminal completion, and typed hooks do not prove emission: actionable when building an adapter; split out of the broad overview. |
| mem-a8d221e64549 (records/mem-a8d221e64549.md:23) | b | 4.5 / 8.25 | yes | Correct generic ordering rule, already enforced by db.py:99–101,218–231; omits the actual helper or verification action an agent needs. |
| mem-b0d6cc3de0ab (records/mem-b0d6cc3de0ab.md:28) | c | 18.5 / 53.75 | yes | Daemon cause and dedicated-socket repair duplicate run-integration.sh:13–17,72–77; useful pre-search, but JIT omits the repair. |
| mem-b389ff7ff08b (records/mem-b389ff7ff08b.md:16) | b | 31.5 / 117 | no | Explicitly dated 18.1.15 provenance is historical evidence, not evidence of the presently running installation. |
| mem-d7311da506a7 (records/mem-d7311da506a7.md:16) | b | 28.75 / 147.75 | no | Tool inventory restates host capabilities; the active tool schema is the authoritative usable surface. |
| mem-d8227d4a3e7b (records/mem-d8227d4a3e7b.md:21) | a | 25.5 / 103.25 | no | Prevents invalid capture-age/latency calculations; external grid-correction note:13–22,38–42 confirms the mechanism; project=unknown makes it unreachable. |
| mem-e0ee543da163 (records/mem-e0ee543da163.md:16) | b | 31 / 142.5 | no | Broad orchestration/safety overview; several good cautions, but no precise entry point or compact decision to apply. |
| mem-e6a79159acd1 (records/mem-e6a79159acd1.md:16) | b | 30.25 / 135.5 | no | Versioned five-backend overview plus an old profile snapshot; no current task-specific action or trigger. |
| mem-f9b4deb601eb (records/mem-f9b4deb601eb.md:21) | b | 21.75 / 23.75 | no | Trivial eight-line retry-helper defaults, not a hidden operational constraint; source retry.py:4–8 confirms them; its project is not registered. |

External cross-checks: C:/Users/assas/Documents/brain-pilot-demo/src/brain_pilot_demo/retry.py:4–8; C:/Users/assas/Documents/BasicUpscaler/The Basic Upscaler/docs/research/BLOCKER-G1A2-grid-correction-2026-09-21.md:13–22,38–42. Ten OMP records share outputs/reports/omp-18.1.15-knowledge-20260911/capability-catalog.json; lines 2–24 bind them to that version/local variant, not today's installation. These are spot-checked source claims, not live requalification.

### What should exist but is missing or non-deliverable

| Needed unit / moment | Existing evidence | Concrete content to retain/generate |
|---|---|---|
| First orientation: V3 versus old runtime | CLAUDE.md:19–31; views.py:1–5; current-state.md:3–18 is stale | V3 core = src/second_brain/kb/; OMP adapter = brainstem/omp-v3/; canonical = records/ + project manifests; derived = db/kb.sqlite + views/; legacy runtime is not the implementation starting point. |
| Current plan/authority | Accepted JIT plan:1–17 versus AGENTS.md:9–12 and CLAUDE.md:70–73 | One current-plan pointer with contracts-over-prose ordering, release-versus-development distinction, and owner-approved status; not another “all phases proven” narrative. |
| Python launch / launcher creation | AGENTS.md:58–68; scripts/brainctl.py:11–12 | Working invocation: env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe …; launcher implementation additionally clears UV_INTERNAL__PYTHONHOME. Distinguish invocation workaround from full launcher sanitation. |
| Correct health/index entry point | CLAUDE.md:19–27 versus AGENTS.md:73 | V3 uses brain doctor/index/views; legacy python -m second_brain doctor is a different surface. Give the appropriate command. These CLI commands were not executed in this audit. |
| Legacy Doctor missing layout | paths.py:43–50,125–128; VG-M04 | ensure_layout(home); skill directories approved/global, domain, project, model and principles. Legacy-scoped locator, not a claim V3 requires those roots. |
| Antigravity integration | antigravity.py:16–35; record mem-79d7c4fd9876:26; VG-M05/M08/M10 | Separate identity fields, Stop arguments/result, and invocation/PreToolUse results into independently useful cards; keep bundle locator separately. |
| Prime integration isolation | run-integration.sh:13–17,68–77; VG-M07 | Shared daemon pins startup env. Dedicated --daemon-socket per run makes a fresh daemon inherit SECOND_BRAIN_HOME. |
| Claude lifecycle | adapters/claude-code/README.md:12–19; candidate mem-bde4dc4aee9e:20 | Stop is per turn; SessionEnd is session close. Candidate exists but OBSERVED/no triggers makes it non-deliverable. Verify before promoting. |
| Byte-exact attach/detach | registry.py:341–352,365–378,449; legacy correction:19–39,51 | newline='' for round-tripping user files; default text reads translate CRLF and break byte-exact restoration. |
| Shutdown persistence | prime-extension/src/index.ts:2575–2579; storage.ts:24–27,112; surprise episode:19–39,51 | Persist terminal telemetry synchronously before worker teardown; awaited/fire-and-forget append can be lost. Host/version-scope this, not a universal async-I/O ban. |
| uv environment install | bootstrap.ps1:86–91; environment episode:51 | uv pip install --python <venv-python>; python -m pip only when pip exists. |
| Linux test hangs/self-kill | candidates mem-3748f4ba9c43:17, mem-6863d65a700f:16 | /proc mkdirSync(recursive) and pkill -f self-matching remedies already exist; evidence is weaker (commit/session strings), so verify before promotion and add precise routing. |
| Delegated economics | mem-42f674862947:16; context-efficiency episode:27,47,51–53 | Parent + children once; distinguish cheap deterministic computation from expensive unrestricted consumption of its result. |

Minimum useful V3 orientation is in **CLAUDE only**, not cross-host AGENTS, and still lacks the accepted JIT plan pointer. This is a portability problem as much as retrieval.

### Legacy parallel stores: salvage versus archive

Counts exclude .gitkeep; recursive counts are C1.

| Store | Files | Useful content / verdict | Evidence |
|---|---:|---|---|
| memory/semantic | 129 | No wholly new production semantic IDs: 116 shared filenames; eight unmatched sentinel IDs; five __v2 bodies exactly preserved in records/. Archive once rollback runtime stops consuming it; never reimport sentinels as facts. | C2; mem-736677e29a1a:3–12, mem-697f82879357:3–12; five version comparisons true. |
| memory/episodic | 18 | Preserve failure provenance; extract CRLF, shutdown, uv-install, bounded reuse. Six entries have literal (none) lessons; most remaining entries repeat current records or generic evidence discipline. | correction-20260814-bcf7ea0b:19–39,51; surprise-20260814-630da729:19–39,51; environment-20260814-3db7d00e:51; context-efficiency-20260908-9bab655f:27,47,51–53. |
| decisions/ | 1 | Obsolete v4.1/Prime build policy, useful historical rationale rather than active instructions. | global/2026-08-14-build-decisions.md:5–14. |
| experiences/ | 0 | Empty hierarchy; nothing to migrate. | C1. |
| skills/ | 11 (5 SKILL.md + 6 binding/eval JSON) | Keep SQLite verification recipe; bounded config reuse as experimental evidence, not active policy. Delivery-integration ritual and Lean/read-reuse scaffolds do not justify parallel authority channels. | active/sqlite-migration-verifier/SKILL.md:30–39,49–64; shadow/verified-config-read-reuse/SKILL.md:29–40,50–58; shadow/delivery-integration/SKILL.md:41–47. |
| engrams/ | 1 | Two read steps over historical config, status candidate; experiment artifact, not general knowledge. | deterministic/policy-config-f34927e18ed4_v1.json:4–40. |
| lexicon/ | 1 | Empty template, not a codebook. | global.md:3–15. |
| frontier/ | 7 | Historical review/activation bindings; preserve audit archive. Config-read-reuse review explicitly permits no ongoing activation. | skill-verified-config-read-reuse-promotion-2.md:3–12; skill-sqlite-migration-verifier-promotion-2.md:3–12. |
| immune/ | 11 | Rollback/proposal evidence and quarantined foreign payloads, not trusted learning. Preserve unexecuted quarantine and rollback chain; do not index as advice. | policies/codex-proposal-guard-63748fbfb27c.json:2–7; triggers/...-failure.json:2–7; metrics.jsonl:1; glob inventory. |
| plasticity/ | 1 | One scout utility anecdote, not current ranking data. Archive. | utility.jsonl:1. |
| sleep/ | 5 | Derived reports repeat episode lessons; archive with legacy. | reports/consolidation-2026-08-14T10-40-19.141863+00-00.md:18–43. |

The config-reuse episode **reports**, but this audit did not independently remeasure, 80,879 → 55,772 complete-workflow tokens (31.0% reduction); unrestricted consuming workers increased to 36,345/36,430 tokens. Lesson: deliver a verified computed answer to a bounded consumer, not “engrams universally save tokens.” Evidence: context-efficiency-20260908-9bab655f:15–27,47–53. Transfer to current subscription OpenAI models is unproved.

## Breakthrough candidates

### 1. Replace prose recall with decision-complete capsules

- **Concrete change:** Treat the delivered unit as the product. Every promoted item contains the action/answer needed at its trigger, a limit, and an exact source pointer. Rewrite daemon advice with --daemon-socket in its first/only sentence. Split Antigravity identity, Stop, result contracts, and reverse-engineering locator. Prefer one canonical compact body over another hand-maintained summary field.
- **Change of kind:** From “knowledge exists” to “the next decision can be made without another broad search.” No embeddings/learned score required.
- **Expected effect:** Required identifier delivery deterministically changes from 0/11 to the relevant subset for Antigravity and 0/1 to 1/1 for daemon repair. Reduced reads/tokens and better answers remain [INFERENCE].
- **Effort:** S corpus surgery; M if source-pointer rendering changes.
- **Risk:** Dropped preconditions; too many sibling cards collide on a broad trigger. Deliver the relevant card, not all fields every time.
- **Obsoletes:** Arbitrary first-sentence policy (views.py:433–444), omnibus “one fact” bodies, ranking experiments on answer-incomplete payloads.
- **Cheapest experiment:** Zero-model rendered-contract coverage and trigger-collision checks first. Then, only when authorized, paired openai-codex/gpt-5.5 existing-versus-complete payload runs for M05/M07/M08/M10 plus unrelated adapter work; compare correctness, reads, logical tokens, latency. Kill automatic delivery if completeness still does not reduce work at equal correctness.

### 2. Make source location/current authority the primary knowledge product

- **Concrete change:** Curate a small map of V3 entry points, current-plan/contract pointer, working commands, and legacy boundary. Deliver path+symbol/range+critical invariant, not host-manual paraphrases. Compute mechanical defaults/enumerations from current source on demand; store surprising constraints and where to verify them.
- **Change of kind:** A maintained map into source instead of a second source copy; useful across hosts, including plain shell without tool-result hooks.
- **Expected effect:** Prevents wrong-tree exploration and duplicate maintenance [INFERENCE]. Proposed targets: 40–80 tokens/relevant locator; about 100 tokens for a portable authority capsule. These budgets are hypotheses, not proof against zero startup context.
- **Effort:** M.
- **Risk:** Moved paths invalidate locators; always-on maps tax unrelated tasks. Bind source identity and measure no-benefit tasks.
- **Obsoletes:** Stale project architecture/current-state as authority; host-feature digests as active work knowledge; historical installation snapshots as current state.
- **Cheapest experiment:** Resolve every locator offline. Authorized follow-up: openai-codex/gpt-5.5 and separately openai-codex/gpt-6-astra, native versus tiny map versus current JIT on held-out implementation-localization tasks. Reject if overhead exceeds saved exploration or correctness falls. Do not optimize only ten fact questions.

### 3. Unify channels and suppress information already known

- **Concrete change:** AGENTS becomes the minimal cross-host local contract; CLAUDE points to it and adds conditional host specifics. One current-authority pointer; old project narratives explicitly historical. Duplicate memory delivered before its source is read, or when a matching error shows the rule was missed—not after an equivalent instruction/source was just read.
- **Change of kind:** Optimize marginal knowledge added to this agent, not record count/keyword relevance; eliminate V1/V3 authority contradictions.
- **Expected effect:** Removes documented contradictions; can avoid the 72.75-token Python and 66-token cloud repetitions when known. Whole-session savings depend on actual loading [INFERENCE].
- **Effort:** S document cutover; M robust exposure-aware suppression.
- **Risk:** A previously exposed constraint may be forgotten after compaction; exposure is not comprehension. Preserve error-time recovery.
- **Obsoletes:** Multiple authoritative narratives, title-substring-only redundancy detection, eager brief as discovery crutch.
- **Cheapest experiment:** Static contradiction/channel check, then authorized paired openai-codex/gpt-5.5 no-benefit tasks plus a real matching failure; require equal recovery and fewer delivered tokens. No broad campaign before this distinction works.

### 4. Require scope and a use moment at admission

- **Concrete change:** Unresolved project/domain captures go into an unresolved-scope inbox. Promotion requires a real recipient and one demonstrated changed decision. Repair BasicUpscaler scope; register real consumers instead of P22 fixtures; triage 25 domain candidates as their own project's knowledge/state.
- **Change of kind:** Addressable reusable interventions instead of an append-only log of whatever agents said. Retrieval cannot fix absent identity.
- **Expected effect:** Correct consumers gain eligibility without disclosure to unrelated projects. Usefulness increase is [INFERENCE]; present zero visibility for unknown/untagged rows is measured.
- **Effort:** M.
- **Risk:** Guessed identities leak knowledge. Require known root/explicit identity, never generic word overlap.
- **Obsoletes:** Current-but-unknown and untagged domain scope as acceptable promoted knowledge; historical provenance remains.
- **Cheapest experiment:** Offline visibility matrix across unrelated temporary/real project manifests; WGC fact appears only for its actual project. Authorized openai-codex/gpt-5.5 consumer task then tests value; no transfer claim from older campaigns.

### Record-value rubric and ideal shape [DESIGN]

**Hard gates:** identified recipient; checkable/current evidence with version limits; named moment at which action/answer changes; no authority escalation; rendered payload contains the action; adds knowledge absent from recipient context. Failing rows remain searchable research/candidates, not auto-pushed.

Score 0–2 each: **decision delta**, **work/search avoided**, **validity/maintainability**, **trigger specificity**, **information per delivered token**. Proposed admission threshold >=8/10 after gates is a hypothesis, not a calibrated truth. A short false/stale item scores zero. Locators win when they avoid broad discovery; facts win for non-obvious invariants not cheap to reconstruct. Mechanical defaults should be computed or located, not paraphrased.

**Canonical shape using existing concepts:** id; type (locator/gotcha/decision/procedure, not every import defaulting to fact); scope; status; evidence path+symbol/range+revision; one bounded trigger family; necessary version/machine precondition; compact body. Lifecycle/history metadata stays out of model-visible payloads. No new ontology, embedding store, grade ladder, or LLM summary cache is necessary.

**Delivered target:** generally **25–60 tokens plus a short source pointer**, hard cap 80 only if the complete decision fits. Otherwise split independently triggered decisions or explicitly provide an exact source locator. Never silently swap a fact for its title and count that as useful delivery. Avoid title/body repetition. Pull-only history can be longer.

Proposed examples, not applied edits:
- Daemon: “Prime print runs reuse daemon startup env. Integration runs need a fresh --daemon-socket so SECOND_BRAIN_HOME is inherited. See brainstem/prime-extension/tests/integration/run-integration.sh:13–17.”
- Restore: “Before restoring brain.sqlite, move its DB/WAL/SHM set aside; remove stale sidecars after copy to prevent replay of old rows. See backup.py::_drop_stale_db_sidecars.”
- Locator: “V3 JIT compilation is second_brain.kb.views.compile_triggers; payload rendering is render_jit_item. Legacy second_brain.jit is a different subsystem.” Evidence: views.py:433,539 versus projects/second-brain/architecture.md:21; delivery value [INFERENCE].

## Kill list

1. **Stop treating title+first sentence as sufficient delivery.** It omits Antigravity fields and daemon repair. Fix the record/rendered-content contract before selector tuning (finding 1).
2. **Stop advertising old project files as current authority.** Archive historical narratives, replace active role with one source map/current-plan pointer. Evidence: current-state.md:3–18; architecture.md:3–6; AGENTS.md:9–26; accepted JIT plan:1–17.
3. **Stop importing release-note/catalog paragraphs as default fact memories.** Keep OMP 18.1.15 research pull-only; extract specific constraints with a use moment. Ten records consume 69.7% of current content tokens, no triggers. Historical facts are not thereby false.
4. **Stop benchmark-driven resurrection of removed orchestration policy.** Replace M06/M09 with current product work, preserving old benchmark as history. Evidence: tasks.jsonl:6,9; CHANGELOG.md:30–31.
5. **Stop test fixtures masquerading as production knowledge.** P22 manifests point at C:/tmp isolation roots; eight unmatched legacy semantic IDs are sentinels. Archive with qualification evidence after installed-runtime review.
6. **Stop maintaining empty knowledge-channel scaffolds as a product surface.** experiences has no content; global lexicon and most project templates contain no entries. Absence is clearer than ceremonial headings.
7. **Stop querying frontier/immune/plasticity/sleep as validated knowledge.** Review, rollback, quarantine, anecdote and derived reports belong in audit archives. Never activate quarantined payloads.
8. **Stop using legacy context/retrieval knobs to explain V3.** config/jit.toml:1–6 controls scored=false. config/context.toml:2–5,22–42,44–105 ties its major knobs to legacy surfaces, mostly disabled/documented-only. config/retrieval.toml:2–20 configures semantic.search_memories, not the V3 compiler. Archive alongside runtime cutover, not independently while installed M00 may use them.
9. **Do not wholesale-delete old episodes/skills before salvage.** Preserve CRLF, terminal-write, uv-install, SQLite verification and bounded-reuse evidence. M00/rollback dependence is explicit in CLAUDE.md:28–31; archival follows runtime cutover, not precedes it.

## Open questions

- What are the real recipient project/domain identities for the 70 untagged domain and five unknown-project records? Evidence roots can inform repair; no registrations were authorized/performed here.
- Which duplicate instruction surfaces does each host load, and what survives compaction? This audit measured content/contradictions, not every prompt assembler. Do not assume all 2,046 estimated AGENTS+CLAUDE tokens are always simultaneously charged.
- Are OMP 18.1.15 RPC/accounting constraints still the right current-host interventions? Matching evidence blobs are not a live host requalification.
- How much do complete capsules/maps help strong OpenAI subscription agents rather than the old cheap-model campaign? Authorized openai-codex comparisons must settle effect size.
- When can installed M00 and rollback dependence end? Semantic inventory supports archival, but runtime ownership is outside this assignment.

### Reproducibility and verification

**C1 — actual command executed, read-only, 0.22 seconds; zero parse errors; six JIT IDs / 14 patterns.** Imports source with -B, runs production loader/compile_triggers in memory, and never calls compile_views/index/rebuild. It verifies blobs/counts, not a test suite.

```bash
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -B - <<'PY'
import sys,json,collections,statistics
from pathlib import Path
sys.path.insert(0,'src')
from second_brain.kb import records,projects,views
h=Path.cwd();rs,errors=records.load_all(h); ps=projects.load_projects(h)
cs=[r for r in rs if r.status=='current']; p=next(p for p in ps if p.id=='second-brain')
v=views.compile_triggers(rs,p,{},False,home=h,source_projects=ps)
def sizes(rr):
 vals=[(len(r.title)+len(r.body))/4 for r in rr]
 return {'count':len(rr),'title_tokens':sum(len(r.title)/4 for r in rr),'body_tokens':sum(len(r.body)/4 for r in rr),'combined_median':statistics.median(vals),'combined_min':min(vals),'combined_max':max(vals)}
print(json.dumps({'parse_errors':errors,'records':sizes(rs),'current':sizes(cs),'private_dir_exists':(h/'records/private').exists(),'private_records':sum(r.private for r in rs),'projects':[p.id for p in ps],'jit_ids':sorted(v['records']),'jit_patterns':len(v['patterns']),'current_visibility':{p.id:sum(projects.visible(r,p) for r in cs) for p in [*ps,projects.Project('brain-pilot-demo'),projects.Project('unknown')]},'current_evidence':{r.id:views._evidence_status(r,p,p,h)[:2] for r in cs},'legacy_counts':{name:sum(1 for f in (h/name).rglob('*') if f.is_file() and f.name!='.gitkeep') for name in ['memory','decisions','experiences','skills','engrams','lexicon','frontier','immune','plasticity','sleep']},'scope_domains':{str(k):n for k,n in collections.Counter(tuple(r.domains) for r in rs).items()}},default=str,indent=2))
PY
```

**C2 — read-tool/Eval computations:** all 121 records read raw to avoid display truncation; CRLF normalized; frontmatter/body split; characters / 4. C1 independently matched aggregate sizes. Current-generation JSON was parsed, required-identifier membership counted, task IDs joined to current status, legacy filenames compared, and five __v2 bodies compared exactly to canonical bodies. Results: Antigravity body 11/11 names, JIT 0/11; daemon remedy present in body, absent in JIT; 129 semantic files minus 116 canonical filenames = eight sentinels + five preserved versions. Current OMP-summary tokens = 1,687.75; rendered six-item sum = 353 tokens.

This is a corpus/contract smoke, not proof of usefulness. No live model run, repository mutation, private-data export or project-wide validation occurred.

### Appendix A — every record's title/body token census

Each row refers to records/<id>.md. All 121 records appear; value classification above intentionally covers only CURRENT records as requested.

| Record | Status | Type | Title tokens | Body tokens |
|---|---|---|---:|---:|
| mem-0d394ab244f3 | current | gotcha | 20.75 | 40.5 |
| mem-0fcad79fd46b | candidate | fact | 20 | 448.25 |
| mem-1222283b65da | candidate | fact | 15 | 476 |
| mem-15170d4924df | candidate | fact | 9.5 | 185.25 |
| mem-16647236fa3c | superseded | fact | 9.75 | 178.75 |
| mem-174b3f5abbba | superseded | fact | 11.25 | 88.5 |
| mem-17919407e022 | superseded | fact | 22.25 | 329.5 |
| mem-17cdb5558c11 | candidate | fact | 26 | 692.75 |
| mem-265240eb1b6b | superseded | fact | 13.25 | 256.5 |
| mem-26a01ba54b6f | superseded | fact | 8.5 | 228.25 |
| mem-27a63457268a | superseded | fact | 16.25 | 284.25 |
| mem-27fc58215bba | candidate | fact | 22.75 | 135.75 |
| mem-28454b0abf5e | superseded | fact | 12.5 | 216 |
| mem-28e9391580bf | superseded | fact | 15.5 | 306.75 |
| mem-29557f93448f | current | fact | 17.5 | 60.75 |
| mem-2af778b663f3 | superseded | fact | 9 | 183 |
| mem-30b06d1e51c1 | retracted | fact | 2.5 | 1.5 |
| mem-333cb2aae270 | current | fact | 31.5 | 140.75 |
| mem-33ea5e925ac9 | superseded | fact | 9 | 171.5 |
| mem-3693230ebaf0 | superseded | fact | 27 | 80 |
| mem-36f8b61546e8 | candidate | fact | 29.25 | 530.25 |
| mem-3748f4ba9c43 | candidate | gotcha | 17.75 | 45.5 |
| mem-3848b16778bd | superseded | fact | 16.5 | 152 |
| mem-389bf41a9601 | superseded | fact | 7.25 | 196.75 |
| mem-3d8ffbd6538d | superseded | fact | 6 | 88.25 |
| mem-4216c4ad856b | superseded | fact | 16.25 | 328.25 |
| mem-42c9700fa242 | superseded | fact | 10.5 | 260 |
| mem-42f674862947 | current | fact | 24 | 139.75 |
| mem-4592f5573486 | retracted | fact | 2.5 | 4 |
| mem-45d2ab7eb2b4 | candidate | fact | 16.25 | 606.25 |
| mem-46205483dd56 | candidate | fact | 12.5 | 322.25 |
| mem-46448b8c4ab7 | superseded | fact | 18.5 | 366.25 |
| mem-478737e47cf9 | superseded | fact | 19.75 | 611.25 |
| mem-494903a96872 | candidate | fact | 26.5 | 493.25 |
| mem-4a796459e7b6 | superseded | fact | 11.75 | 231.25 |
| mem-53393f42418c | candidate | fact | 20.5 | 551.75 |
| mem-54e98fd1c79b | superseded | fact | 17.25 | 342.5 |
| mem-55c71a309022 | candidate | fact | 21.75 | 348 |
| mem-58f449274500 | candidate | fact | 23.5 | 388 |
| mem-5bc2da33777a | current | fact | 30.25 | 144 |
| mem-5ec9b9283907 | candidate | fact | 12 | 200.75 |
| mem-5ee4c7712fa3 | current | fact | 28.5 | 153 |
| mem-60c403ed0839 | superseded | fact | 6.5 | 146.75 |
| mem-621006a63d2d | retracted | fact | 4.5 | 8.25 |
| mem-6557c215d72b | candidate | fact | 20.25 | 480.75 |
| mem-6849e6dc3a1f | candidate | fact | 26.5 | 96.75 |
| mem-6863d65a700f | candidate | gotcha | 16 | 43 |
| mem-69e44c5b85a5 | superseded | fact | 11.75 | 200.25 |
| mem-6b07e0e7d311 | superseded | fact | 22.75 | 250.5 |
| mem-6d592dd0c627 | current | gotcha | 18.25 | 43 |
| mem-6d5ec5875344 | superseded | fact | 6.75 | 110.5 |
| mem-7001b2e04e08 | candidate | fact | 19.75 | 355 |
| mem-75ef9bf9e33f | candidate | fact | 19.25 | 557 |
| mem-7667f0b43eec | superseded | fact | 18.5 | 316.75 |
| mem-771d74aaa3fd | candidate | fact | 9.25 | 24.5 |
| mem-79d7c4fd9876 | current | locator | 17.25 | 256.5 |
| mem-7a29c44e6be5 | candidate | fact | 24.75 | 347 |
| mem-7daaa380f599 | superseded | fact | 7.25 | 168.25 |
| mem-7dda00fb6cdc | superseded | fact | 22.75 | 926.5 |
| mem-7ee245204a5e | superseded | fact | 12.75 | 50 |
| mem-7f11e32b5e6e | superseded | fact | 17.75 | 383 |
| mem-80706130512e | candidate | fact | 17.5 | 428 |
| mem-812f9bb08444 | current | fact | 29.25 | 138.75 |
| mem-89440840b2f9 | superseded | fact | 10 | 153.25 |
| mem-8adbc449f9e0 | superseded | fact | 9 | 135.75 |
| mem-8c8b13bf82b4 | candidate | fact | 23.75 | 522.5 |
| mem-918af823ea7d | candidate | fact | 22.5 | 321.75 |
| mem-93c5c68d979b | superseded | fact | 10.25 | 195.75 |

[Showing lines 1-300 of 354. Use :301 to continue]