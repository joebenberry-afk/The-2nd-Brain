## Top findings

1. **The breakthrough-sized cut is the searchable/deployed repository, not a language rewrite: only 6,789 of 56,616 Python lines belong to V3, and the OMP adapter is 604 lines.** The retained legacy Python is 49,827 lines (88.0% of Python source). `brainstem/prime-extension/` adds 28,832 code lines, of which its actual `src/*.ts` runtime is 12,670 lines; the rest includes tests/reference material. V3 already meets the design's ≤10K-Python/≤1.5K-per-adapter budgets in isolation. The package still ships the entire `src/second_brain` tree and exposes two different runtimes (`pyproject.toml:12–24`). Evidence: inventory command M1 below; size target `docs/intake/2026-09-24-plan-v3-agent-native-redesign.md:57–58`. **Impact:** a clean package/source cutover removes approximately 49.8K Python lines without redesigning V3; moving the one current adapter test out permits archiving 28,523 of 28,832 Prime code lines. Token/correctness improvement from smaller navigation scope is **[INFERENCE]**, not proportional to LOC. **Confidence: HIGH.**

2. **The advertised legacy-free import boundary is almost, but not actually, true; every CLI operation also eagerly imports almost the entire V3 product.** `second_brain/__init__.py:5` imports legacy `paths.py` (136 lines), including the old directory taxonomy; none of the V3 functional modules imports another legacy subsystem. A real `import second_brain.kb.cli` loaded 23 project modules and 6,819 source lines: 21 of the 23 KB modules plus the package initializer and `paths`. `consolidate.py` is review-only/lazy; `kb/__main__.py` adds another five lines for `python -m second_brain.kb`. CLI registration eagerly loads capture, doctor, outcomes, skills, sync, conversion and hooks even for a query (`kb/cli.py:17–26,36–51`). One import-time run measured 66.062 ms cumulative import time, including 37.466 ms through `commands_capture` (nested/shared costs, not additive). **Impact:** remove the accidental `paths` import before deleting it; command-specific loading can reduce cold overhead, but this is a latency optimization, not a demonstrated task-token breakthrough. **Confidence: HIGH.**

3. **Measured cold-process CLI latency is approximately 100–150 ms on this Windows machine, not the redesign document's 28 ms synthetic Linux workload.** Eleven fresh processes per operation, with inherited `PYTHONHOME`/`PYTHONPATH` removed and all Brain writes redirected to a disposable OS-temp home:

   | Command | Median ms | Min–max ms | First process ms | Observed behavior |
   |---|---:|---:|---:|---|
   | Python `-c pass` | 27.95 | 25.87–33.11 | 33.11 | exit 0 |
   | `brain q PYTHONHOME --project second-brain --json` | 111.69 | 109.50–404.59 | 404.59 | exit 0; returned `mem-6d592dd0c627` |
   | `brain jit-match --tool bash --command "python -m pytest" --project second-brain --cwd <repo> --json` | 99.43 | 96.04–122.94 | 122.94 | exit 0; `delivered`, command route, same record |
   | `brain views` | 148.45 | 144.82–185.87 | 185.87 | exit 0; four project/_none summaries |

   Here `brain` was invoked through its equivalent `python -m second_brain.kb` entry point, not the Windows console-script executable. These are **fresh-process / mostly warm-filesystem-cache** measurements, not cold-OS-cache claims; the first query includes copied-home initialization/freshness effects. `q` is not read-only internally: `index.search` calls `refresh` on every query, reparsing every record and serializing each twice (`index.py:207–279,344–365`). `views` writes both modern and frozen legacy outputs (`views.py:754`). **Impact:** no evidence supports rewriting Python to solve a presumed >second-scale CLI problem; the OMP delivery path never spawns this CLI. **Confidence: HIGH.**

4. **Legacy retention is a build/test/distribution dependency, not a V3 runtime dependency; deleting directories alone would break real retained workflows.** CI's so-called retrieval gates run the legacy `second_brain` entry point and `autoinject.BrainLifecycle`, not V3 KB search (`.github/workflows/ci.yml:29–47`; `scripts/v3_retrieval_eval.py:164–193`). OMP V3 tests live under Prime and inherit its entire typecheck (`ci.yml:67–82`; `prime-extension/tsconfig.json:24–28`). `tests/conftest.py:8,25–37` imports legacy DB/paths and builds a legacy home; V3 conversion tests use `semantic` and `db` (`test_kb_views.py:463–539`). The current value suite dynamically loads the 1,524-line older matched-arms runner (`v3_value_suite.py:114–121`), including repeated `_arms()` loading for helpers, and still offers historical M00/candidate arms (`:50–58`). **Impact:** archive old validation with its old runtime; extract the retained test/support boundary first. The suite is 2,232 lines, all `v3*` scripts total 6,530 lines, and all scripts total 19,947 lines—none on the production KB import path. **Confidence: HIGH.**

5. **Agent navigation is materially polluted by multiple contradictory “current” authorities.** Eight root Markdown documents contain 299,310 Unicode characters: a **74,828-token characters/4 proxy**, not a model-token measurement. The three root V4 plans alone account for 14,956 lines / 240,172 characters / **60,043 proxy tokens**. The ordinary `AGENTS`+`CLAUDE`+`README`+`INDEX` set is 4,305 proxy tokens; Claude's explicit `CLAUDE`+`AGENTS`+Lean-kernel import chain is approximately 2,360. `docs/` adds 78 Markdown files / 23,256 lines / 1,547,347 bytes. Five filenames within `docs/` contain “plan”; together with three root V4 plans, that is eight plan-named documents, plus requirements/contracts/status documents. The V3.x plan alone is 1,099 lines / 23,988 proxy tokens. Historical observed orientation cost was 30–50K tokens (`agent-native-redesign.md:29–37`), consistent with but not independently reproduced by these proxies. **Actual audit observation:** a broad descriptive `find` returned six hits, five outside current V3, and reported processing 119,408 input tokens over 20 files / 327.7 KB. That is one tool's reported internal search work, not a typical end-to-end coding-agent cost. **Confidence: HIGH on sizes/contradictions; MED on expected savings.**

6. **The largest V3 hotspots are policy commitments, not obviously necessary implementation overhead.** Capture (1,134), views (815), index (803), outcomes (509), and triggers (506) total 3,767 lines, 55.5% of the KB. Their weight purchases: heuristic episode mining and evidence inference; two parallel view formats; explicit temporal/current-state semantics; a copied Python/TypeScript shell/path matcher; and an offline causal-proxy scoring machine. Some is essential safety, some is backward compatibility, some is an unproven experiment. `config/jit.toml:2–6` disables scored selection, but `commands_capture.py:116` still runs scoring on review. Scoring awards “helpful” for a successful retry or touching a locator target and “harmful” after three relevant searches (`outcomes.py:176–197`); these measure subsequent actions, not correctness or saved tokens. **Impact:** do not let proxy instrumentation remain a mandatory dependency of basic capture. There is no evidence in this audit that deleting safety/state semantics improves task performance. **Confidence: HIGH on structure; MED on simplification value.**

7. **Distribution simplification is worthwhile; a core language rewrite is not yet justified.** Current installation requires a checkout, manually sanitized environment, existing `.venv`, editable install, conversion, doctor, view compilation and a PowerShell host installer (`README.md:29–53`). §3.7 measured Python 27–28 ms vs Go 22–29 ms on the same 2,000-row Linux FTS workload, with a 6.3 MB Go artifact, 99 MB Bun artifact, and no Rust FTS implementation (`agent-native-redesign.md:159–180`). Python has no runtime package dependencies (`pyproject.toml:6–7`), so distribution can be separated from a rewrite. `uv tool install` removes **user-managed** venv ceremony but still creates an isolated environment; zipapp is one application file but still needs a compatible Python interpreter. Primary sources: https://docs.astral.sh/uv/concepts/tools/ and https://docs.python.org/3/library/zipapp.html. **Impact [INFERENCE]:** fewer failed environment/setup actions and more usable shell/Codex/Cursor/Gemini access; no measured task-token savings yet. **Confidence: HIGH on options; MED on product effect.**

### Actual V3 runtime graph

```text
pyproject: brain = second_brain.kb.cli:main
  second_brain/__init__.py -> paths.py [accidental legacy import]
  kb/__main__.py -> kb/cli.py
  cli -> commands_{index,views,capture,doctor,outcomes,skills,sync}, hooks
  commands_index -> index -> records, projects, triggers
  commands_views -> views, convert, records, projects, triggers
  commands_capture -> capture -> index, projects, records, triggers
                    -> outcomes (review/maintenance)
                    -> consolidate (lazy review only)
  commands_doctor -> doctor -> capture,index,projects,records,views
  commands_outcomes -> outcomes -> records,triggers
  commands_skills -> skills_export -> records
  commands_sync -> sync -> index,records,views
  hooks -> projects,records,views
```

All KB imports outside this graph are Python standard library. AST import inspection plus `sys.modules` observation establish this; the `import_module` in `commands_capture.py:85` explicitly names `second_brain.kb.outcomes`, not a legacy plugin. Conversion reads legacy SQLite data directly without importing its runtime (`kb/convert.py:7–13,26–39`).

**OMP live read path, not README's old diagram:** Node built-ins only (`omp-v3/index.ts:2–5`), no Prime or Python import. It reads `views/dirty`, `views/current.json`, `views/generations/<generation>/projects.json`, and `views/generations/<generation>/<project-or-_none>/triggers.json` (`:273–288,305–328`). It resolves real project/file paths for disclosure boundaries (`:285,290–297,331–350`). On the safe turn boundary it rechecks the small current/dirty marker (`:549–556`). It does **not** read SQLite, canonical Markdown, `brief.md`, or `corrections.json` for JIT delivery. Pointer recovery is embedded in trigger data (`:474–483`). It asynchronously writes `state/kb-events/*` and `telemetry/kb-hooks.jsonl`, with bounded queues/rotation (`:361–455,580–590`); these are outputs, not retrieval inputs. The stale README diagram describes the pre-JIT view boundary (`README.md:75–80`).

### Authority and navigation contradictions

| Surface | Conflicting instructions/state | Evidence |
|---|---|---|
| `AGENTS.md` / `INDEX.md` vs README/CLAUDE | V4.2 implementation and a campaign-specific V4.3 proof plan are authoritative vs current V3 KB | `AGENTS:7–15`; `INDEX:5–12`; `README:14–27,83–89`; `CLAUDE:17–31` |
| Canonical knowledge | AGENTS lists `memory/experiences/decisions/skills/engrams/...` but omits `records/`; V3 says `records/` is canonical | `AGENTS:22–26`; `README:83–89` |
| Default health command | AGENTS directs `python -m second_brain doctor` into the old runtime; V3 uses `brain doctor` | `AGENTS:63–76`; `pyproject:13–14`; `README:70` |
| Accepted vs proposed redesign | Header says draft/proposed/nothing authorized; later binding rules say owner accepted O1 | `agent-native-redesign:1–17,274–288` |
| CLI alias | O6 says keep `brainctl` as an alias; packaging binds it to a different implementation | `agent-native-redesign:283`; `pyproject:13–14` |
| Cloud knowledge transport | O4 replaces the cloud seed with private git home; bootstrap still creates legacy DB and loads the old seed before KB indexing | `agent-native-redesign:281`; `CLAUDE:35–40`; `cloud-session-setup.sh:24–30` |
| Retrieval qualification | CI comments/name suggest V3 memory/retrieval but gate imports `autoinject` and uses `brain.sqlite` | `ci:1–3,31–47`; `v3_retrieval_eval:71–72,164–193` |
| View contract | README diagram shows `brief.md/corrections.json`; current OMP consumes generation-scoped `triggers.json` | `README:75–80`; `omp-v3/index.ts:273–307` |
| Completion language | README says V3 complete in code and live qualification not run; V3.x plan says in-progress, and later profiles have their own qualification contract | `README:8–12`; `V3x_Just_In_Time_Memory_Plan:1–7,56,1084–1099` |

The startup-brief/JIT difference is **not an unresolved contract contradiction**: O9 explicitly reconciles it and freezes the eager arm (`V3x_Just_In_Time_Memory_Plan.md:19–30`). The issue is that agents must traverse multiple long documents to find that precedence. Likewise retaining old correction views is deliberate compatibility, not unreachable dead code (`V3x_JIT_Contracts.md:42–49`).

## Breakthrough candidates

### 1. Ship a product-only tree; archive the research/runtime museum outside ordinary checkout/search

- **Concrete change:** retain KB, current host adapter(s), canonical records/projects, small active config, current tests and one evaluation runner. Move legacy runtime, historical runners, old requirements/plans and frozen evaluation arms into a separately retrievable archive/release artifact. A source checkout must not require reading that archive to find the current product contract. Separate personal knowledge home from distributable application code.
- **Change of kind:** from an accumulated personal research OS to a small installable memory product with an unambiguous search surface—not an ignore-rule optimization over the same confusing default tree.
- **Expected effect:** approximately 49.8K Python lines and 28.5K Prime code lines leave the ordinary product; 60K proxy tokens of root V4 plans leave root authority. Token/correctness gains **[INFERENCE]**; no claim these are injected on every session.
- **Effort:** M. **Risk:** losing recoverable local work/history if archive is treated as garbage collection. The 132 backup directories and 25 worktree directories observed here are **not** authorized deletions; branch/worktree ownership and uncommitted work need preservation checks. Their excluded-dependency code inventories are 1,506,412 and 3,568,500 lines respectively.
- **Obsoletes:** in-tree rollback requirement (`README:88–89`), legacy CI/bootstrap coupling and V4 root authority. Keep rollback as a pinned external artifact, not an ambient alternative implementation.
- **Cheapest confirmation:** in a disposable copy, prove the retained CLI/host adapter, conversion fixture, privacy/currentness tests and packaging do not import legacy modules; then compare identical orientation+implementation tasks on current vs product-only trees with **`openai-codex/gpt-5.5`**, same effort and frozen corpus. Measure agent tokens, latency, files opened and correctness; no USD criterion. Kill the navigation claim if the smaller tree does not reduce exploration without correctness loss. No model run was performed here.

**Removal order:** (a) make one short current authority/bootstrap contract; (b) remove initializer's accidental `paths` import and retire/redirect legacy console entry point by explicit cutover; (c) move the 309-line OMP test plus shared JSON fixtures to the current adapter's own dev package; (d) replace the global legacy conftest dependency and move conversion proofs to a frozen-schema fixture/migration archive while preserving tested conversion behavior; (e) replace old S2 retrieval gate with retained KB retrieval cases and decouple cloud setup; (f) extract the retained evaluation helper boundary, archive historical arms with exact pinned artifacts; (g) archive legacy source/data roots only after record/migration preservation is established. Do not infer records are disposable from runtime reachability.

### 2. One current authority, with a tiny task router instead of chronological documentation traversal

- **Concrete change:** `AGENTS.md` gives current runtime boundary, exact commands, one current contract, and a compact map for query/capture/adapter/evaluation changes. README/CLAUDE/INDEX link that authority rather than assert competing versions. Historical plans cease claiming current precedence. Status distinguishes implemented/locally exercised/qualified/rejected.
- **Change of kind:** agents consume a current state interface, not a timeline they must reconcile. This is the Brain solving its own largest documented use case.
- **Expected effect:** source material for ordinary orientation can be hundreds rather than tens of thousands of tokens **[INFERENCE]**. Current four-file root bundle is 4,305 proxy tokens; avoidable root-plan detour is 60,043 proxy tokens; documented observed orientation was 30–50K.
- **Effort:** S. **Risk:** over-compression hiding critical trust/privacy invariants. Preserve exact references for rare operations.
- **Obsoletes:** V4 authority entries and duplicated active implementation narratives; does not delete historical evidence.
- **Cheapest confirmation:** deterministic authority-link check plus a small blinded current-state/location task comparison on **`openai-codex/gpt-5.5`**. Score correct current command/module/contract and token/latency totals. This can be tested before changing retrieval.

### 3. Make the core a knowledge compiler; make automated learning an optional experiment

- **Concrete change:** keep canonical records, scope/privacy/grade/currentness, explicit note/review/promotion, one deterministic retrieval path and one compiled delivery format. Move outcome scoring/episode mining out of the mandatory CLI product; do not run it merely to review notes. Migrate frozen Claude hooks onto the chosen view contract before deleting their old format, or explicitly ship them as a separately versioned adapter. Keep atomic generation publication and path/privacy checks.
- **Change of kind:** the product supplies compact evidence to agents; it no longer contains a mandatory shadow evaluator attempting to infer whether its own suggestions caused success.
- **Expected effect:** outcomes + command handler are 558 Python lines; capture has 164-line `note`, 157-line git capture and 96-line incremental event-consumption functions plus substantial matching/cursor support. Frozen views occupy `views.py:33–369` (~337 lines). Removing whole features can materially shrink the core; exact net savings depend on retained contracts **[INFERENCE]**. Existing scored-selection switch is off, so deleting scorer-dependent selection cannot remove a demonstrated enabled production benefit based on this audit alone; diagnostic/capture consumers still require migration.
- **Effort:** M. **Risk:** explicit-only learning may again fail to capture useful lessons. Preserve `brain note` ergonomics; do not replace it with a ceremony-heavy schema editor. Do not delete automatic capture without checking real accepted-candidate yield from the learning-loop audit.
- **Obsoletes:** mandatory scoring inside review, score snapshot requirements for the base product, duplicate frozen view compiler, perhaps six-event causal-proxy machinery. Does not obsolete evidence/trust semantics.
- **Cheapest confirmation:** replay already retained events offline, enumerate accepted/useful records attributable uniquely to each capture feature, and compare scorer judgments against task outcomes. Only if useful yield exists should an **`openai-codex/gpt-5.5`** capture-vs-explicit-note experiment follow. No paid/live run performed here.

**What a 2K-line core would actually mean (design budget, not measured achievable implementation):**

| Responsibility | Proposed Python LOC budget |
|---|---:|
| Canonical record parser/validation, safe atomic writes and explicit state transitions | 400 |
| Project resolution, sharing/privacy visibility | 150 |
| FTS index/search/currentness | 300 |
| Single compiled generation and trigger entries | 350 |
| Direct note + inbox review/promote | 250 |
| CLI dispatch/formatting | 200 |
| Integrity/rebuild | 150 |
| Explicit git transport | 200 |
| **Total** | **2,000** |

This cannot honestly preserve every current command and temporal/capture policy by “refactoring.” It entails removing from the base product: heuristic event mining/outcome scoring, old correction/eager-brief renderers, migration tooling after cutover, skill export, near-duplicate review, and likely a general `--as-of` interface (keep explicit current/superseded history and git evidence, or revise the budget). OMP's 604-line adapter remains separately counted. The command normalization/privacy invariants still need implementation, not omission. **Recommendation:** ship the safe ~6.8K cutover first; authorize a smaller feature contract only after evidence shows which capabilities are unused. Never claim 2K by merely moving required runtime files elsewhere.

### 4. Distribute a hermetic command, not a checkout setup ritual

- **Concrete change:** initially publish a small wheel/current-source package and a pinned `uv tool install --python 3.13 <trusted Brain artifact>` path; distinguish managed-environment installation from true zero-interpreter installation. Bind Brain home independently through `SECOND_BRAIN_HOME`. Provide a launcher with controlled Python environment behavior; inspect/run artifact in a clean Windows profile and a clean POSIX environment. A stdlib zipapp is a cheap alternate artifact for hosts already guaranteed Python. Only after install failures persist, compare a bundled-interpreter executable with a small Go port.
- **Change of kind:** any coding agent invokes a stable tool on PATH without inheriting this repository's venv, legacy package, current branch or corrupted user-level Python setup.
- **Expected effect:** setup-success and portability improvement **[INFERENCE]**; the strongest existing evidence is the machine's documented Python environment trap (`AGENTS:58–68`) and current install sequence. No claim `uv` alone neutralizes inherited `PYTHONHOME` or that zipapp includes Python. OMP hot-path latency is unchanged.
- **Effort:** S/M for packaging/launcher; L for Go rewrite and requalification. **Risk:** install supply chain, signed artifact/update mechanics, cross-platform SQLite FTS5 availability; deployment must preserve canonical records/private scope.
- **Obsoletes:** editable checkout/venv as the user install contract; not Python source or file-based memory. A rewrite would obsolete all KB implementation and require re-proving safety, so it is not the first experiment.
- **Cheapest confirmation:** no-model clean-profile install + `q`/`note`/`views`/host read smoke, environment contamination case, offline startup and uninstall-with-records-preserved; compare install actions, failures, artifact bytes and cold latency. Do not spend model tokens to decide this packaging question.

### 5. Collapse the evaluation product without weakening the evidence

- **Concrete change:** one small current-arm runner consumes frozen tasks/artifacts and emits request/child usage, outputs, correctness and paired comparisons. Historical M00/eager/scored arms remain external reproducible artifacts, not permanent branches throughout the runner. Load reusable helpers once instead of dynamically executing the older 1,524-line script for utility calls. Retain actual request capture, unknown-metric handling, corpus isolation, failures and strong native-memory control.
- **Change of kind:** evaluation becomes a simple reusable measurement interface, not another backward-compatible product.
- **Expected effect:** reduce the current 2,232+1,524-line coupled runner surface **[INFERENCE]**, with no promised token improvement until campaign setup/navigation is measured. Counting lines is not a reason to remove scientific controls.
- **Effort:** M. **Risk:** accidentally losing child-token accounting or control isolation. **Obsoletes:** historical runtime preparation paths in the shipping runner; obsolete campaign generators.
- **Cheapest confirmation:** replay already captured raw sessions through old/new accounting and compare all metrics/failures exactly; then one no-model preparation probe. Any later agent experiment uses **`openai-codex`**, e.g. `gpt-5.5`; **no DeepSeek or OpenRouter**. Existing DeepSeek campaigns can motivate hypotheses, not establish transfer to the owner's subscription models.

## Kill list

**Interpretation:** recommendations only; no repository file was edited/deleted. “n” means not on the production V3 KB/OMP import/read path, **not** unused by historical tools, tests, installers or live rollback. Archive is a pinned external artifact/branch with preserved local data, not another default-searchable in-repo duplicate. Counts are physical lines including comments/blanks; code totals exclude dependency/cache/build directories.

### Deletion/archive table — complete non-KB Python module inventory

All rows below are under `src/second_brain/`; every `n` is supported by AST import inventory and the runtime module census. Actions follow the cutover prerequisites above.

| Path | Lines | On V3 path? y/n | Action |
|---|---:|:---:|---|
| `kb/` | 6,789 | y | Retain; simplify only under revised feature contract |
| `__init__.py` | 5 | y | Retain package initializer; remove legacy paths import |
| `paths.py` | 136 | y | Accidental parent import only; archive after initializer cutover |
| `__main__.py` | 4 | n | Replace legacy entry contract or archive with `brainctl` |
| `action_cache.py` | 1,321 | n | Archive |
| `adapters/` | 902 | n | Archive legacy Python adapters |
| `antigravity_transcript.py` | 301 | n | Archive |
| `artifacts.py` | 465 | n | Archive |
| `autoinject.py` | 2,008 | n | Archive after replacing old retrieval CI |
| `backup.py` | 819 | n | Archive; preserve actual user backups |
| `brain_schema.py` | 734 | n | Archive |
| `brainstem.py` | 304 | n | Archive |
| `build_identity.py` | 140 | n | Archive |
| `capabilities.py` | 489 | n | Archive |
| `capsule_runtime.py` | 204 | n | Archive |
| `cerebellum.py` | 312 | n | Archive |
| `cli.py` | 4,931 | n | Archive legacy `brainctl` runtime |
| `contracts.py` | 1,060 | n | Archive implementation; retain applicable invariants in current contract |
| `credit.py` | 1,078 | n | Archive |
| `crossmodel.py` | 339 | n | Archive |
| `db.py` | 300 | n | Archive after conftest/conversion-test decoupling |
| `decisions.py` | 362 | n | Archive code, not unconverted knowledge |
| `delta_sync.py` | 457 | n | Archive |
| `doctor.py` | 396 | n | Archive; keep KB doctor |
| `economics.py` | 451 | n | Archive |
| `engram.py` | 868 | n | Archive |
| `envsteward.py` | 557 | n | Archive |
| `episodes.py` | 398 | n | Archive |
| `errors.py` | 17 | n | Archive |
| `fingerprints.py` | 390 | n | Archive |
| `firewall.py` | 596 | n | Archive code; do not remove KB disclosure protections |
| `fresh_verifier.py` | 182 | n | Archive |
| `freshness.py` | 261 | n | Archive |
| `frontier.py` | 648 | n | Archive |
| `gardener.py` | 2,143 | n | Archive |
| `goals.py` | 553 | n | Archive |
| `governor.py` | 914 | n | Archive |
| `handoff.py` | 467 | n | Archive |
| `heartbeat.py` | 372 | n | Archive |
| `hermes_adapter.py` | 1,299 | n | Archive frozen legacy host integration |
| `hybrid_retrieval.py` | 1,165 | n | Archive; reintroduce only against measured KB retrieval need |
| `immune.py` | 629 | n | Archive |
| `injection_slots.py` | 236 | n | Archive |
| `jit.py` | 288 | n | Archive; this is not `kb/triggers.py` |
| `lean_runtime.py` | 946 | n | Archive |
| `ledger.py` | 2,438 | n | Archive |
| `monitor.py` | 323 | n | Archive |
| `omp_adapter.py` | 129 | n | Archive |
| `optimization.py` | 501 | n | Archive |
| `p4.py` | 127 | n | Archive |
| `plasticity.py` | 379 | n | Archive |
| `promotion.py` | 1,852 | n | Archive; retain KB candidate/evidence transitions |
| `radar.py` | 481 | n | Archive |
| `reconsolidation.py` | 1,202 | n | Archive |
| `registry.py` | 512 | n | Archive |
| `repository_intelligence.py` | 185 | n | Archive |
| `risk.py` | 269 | n | Archive |
| `router.py` | 330 | n | Archive |
| `scout.py` | 304 | n | Archive |
| `security/` | 318 | n | Archive legacy helpers only; KB has its own validation |
| `semantic.py` | 3,540 | n | Archive after conversion-fixture extraction |
| `simplification.py` | 216 | n | Archive |
| `skillforge.py` | 974 | n | Archive |
| `skills.py` | 361 | n | Archive |
| `sleep.py` | 298 | n | Archive |
| `telemetry.py` | 795 | n | Archive; not current adapter telemetry writer |
| `turn_bridge.py` | 676 | n | Archive |
| `v2_policy.py` | 317 | n | Archive |
| `verify.py` | 608 | n | Archive |
| `vmem.py` | 1,729 | n | Archive |
| `working_set.py` | 516 | n | Archive |
| `migrations/` | 658 SQL | n | Archive 29 legacy migrations with converter fixture/schema evidence |
| `defaults/` | 416 text | n | Archive 23 old config/template text files after removing legacy bootstrap |

**Result:** retain ~6.8K Python, approximately 3.2K below the ≤10K target, without a core rewrite. There are 49,686 Python lines outside KB **and** outside the parent initializer/accidental paths import; `paths.py` becomes removable after that one import is eliminated. A final initializer/entrypoint choice changes the total by single digits.

### Other directories, tests, scripts and documentation

| Path | Lines | On V3 path? y/n | Action |
|---|---:|:---:|---|
| `brainstem/omp-v3/index.ts` | 604 TS | y | Retain; 896 below adapter ceiling |
| `brainstem/prime-extension/` | 28,832 code | n | Move current 309-line OMP test/dev config out; archive remaining 28,523 code lines |
| `brainstem/adapters/antigravity/` | 130 code / 225 text | n | Archive frozen legacy adapter |
| `brainstem/adapters/claude-code/` | 56 code / 168 text | n | Archive old adapter, not V3 consumer |
| `brainstem/adapters/claude-code-v3/` | 45 text | y, alternate host config | Retain/revise hooks config and README; calls current `kb/hooks.py` |
| `brainstem/adapters/hermes/` | 580 code / 708 text | n | Archive frozen adapter |
| `brainstem/codex-hooks/` | 74 PS / 190 text | n | Archive legacy adapter; later portable CLI is shared replacement |
| `brainstem/policies/` | 0 | n | Remove empty placeholder when obsolete |
| `brainstem/tests/` | 595 PS | n | Archive legacy installer tests; retain any installer behavior still shipped |
| `tests/test_kb_*.py` | 7,021 (12 files) | n, verification | Retain behavior proofs; replace legacy converter fixture dependency |
| `tests/test_v3_*.py` | 1,322 (3 files) | n, mixed verification | Keep value-suite/current request accounting; audit legacy shipping-default test separately |
| All other `tests/*.py`, including conftest | 50,528 | n | Archive legacy suite after extracting required current fixtures; not an immediate wholesale delete |
| `scripts/v3_value_suite.py` | 2,232 | n | Retain/streamline current evidence runner |
| `scripts/v3_matched_arms.py` | 1,524 | n | Extract necessary helper API first, archive old M00/Lean runner |
| `scripts/v3_e01_latency.py` | 754 | n | Archive historical campaign; preserve evidence |
| `scripts/v3_e02_semantic.py` | 1,435 | n | Archive historical campaign; preserve evidence |
| `scripts/v3_retrieval_eval.py` | 389 | n | Replace legacy retrieval gate, archive old eval |
| `scripts/v3_request_capture_extension.ts` | 122 | n | Retain current request accounting |
| `scripts/v3_inert_extension.ts` | 36 | n | Retain only if current inert control needs it |
| `scripts/v3_capture_order_probe.ts` | 38 | n | Archive one-off after preserving contract result |
| `scripts/install-omp-v3.ps1`, `uninstall-omp-v3.ps1` | 46 + 29 | n, deployment | Retain until packaging replacement; remove legacy cutover dependence deliberately |
| Remaining scripts | 13,342 code | n | Archive historical campaigns/legacy installers; replace bootstrap and preserve needed cross-host install actions |
| Root three V4 plans | 14,956 Markdown | n | External historical archive; remove current authority links |
| `docs/` | 23,256 Markdown | n | Keep one active contract/current runbook; historical research/evidence separately browsable |
| `backups/` | 1,506,412 code; 4,361 files; 132 directories | n | Preserve ownership/data, then move out of ordinary checkout/search; do not blindly delete |
| `.worktrees/` | 3,568,500 code; 9,857 files; 25 directories | n | Check branch/local changes/active ownership before external archiving/removal; never recursive-delete on this audit |
| `pyproject.toml` | 45 | n, packaging | Ship only current package/entrypoint; preserve stdlib-only runtime |
| `.github/workflows/ci.yml` | 82 | n, validation | Replace legacy retrieval/bootstrap/typecheck coupling, not safety gates |

The reported directory counts (132/25) are this audit's observations, superseding the task's earlier 131/24 inventory, without assuming why they changed. Backup/worktree line counts exclude dependencies/caches/build outputs and nested runtime-data roots; they are navigation-weight bounds, not safe deletable-code totals. Other tests total is 58,871 − 7,021 − 1,322 = 50,528; scripts remainder is 19,947 − 6,530 − 75 = 13,342. All brainstem code is 30,871 lines; the 604-line live OMP adapter is 2.0% of that code inventory.

**Stop doing:**
- Treating `v3_` names or “V3 core and memory tests” labels as evidence that a check exercises KB; inspect its runtime entry point.
- Keeping every historical comparison arm installed/typechecked to validate one 604-line current adapter.
- Claiming no legacy imports while the parent package imports `paths`; trivial to fix, not evidence of an entire legacy hot path.
- Describing outcome signals as task correctness or causal token savings.
- Spending rewrite effort to gain the synthetic §3.7 ~5 ms before removing setup and navigation failure modes.
- Attempting to reach 2K lines by compressing safety checks, hiding required modules in another package, or dropping tests that catch actual behavior.

## Open questions

1. Which backup/worktree directories contain unique uncommitted user work, active branches, unreleased private knowledge, or a currently installed rollback artifact? Counts do not establish disposal safety; no content-preservation/ownership audit was performed.
2. How many accepted, still-useful canonical records were produced uniquely by automatic episode mining, git trailers, explicit note, or outcome scoring? This architecture audit establishes cost/structure, not learning yield; the learning-loop/corpus audits should decide which optional features earn retention.
3. Is the frozen V3 Claude Code hook actually installed/used now? Its functioning contract makes old views non-dead code; removal requires host migration, not merely OMP focus.
4. Does a clean product-only checkout reduce tokens and improve current-authority accuracy on the owner's **openai-codex** models? Historical DeepSeek results do not settle transfer. No live model campaign was run.
5. Is the desired portability bar “no user-created venv” or “no Python/interpreter installation at all”? The former has a low-risk packaging solution; the latter requires a bundled interpreter or a rewrite. No clean-machine artifact was built or installed here.
6. Can a 2K-line product preserve the owner-selected minimal feature/safety contract without moving complexity into adapters or manual agent work? The proposed budget is a design hypothesis, not a measured implementation.

### Methods and exercised evidence

Repository work was read-only. No formatters, installers, lint/test suite, derived-state rebuild in the real home, or paid/live model campaign was run. The exercised runtime was `q`, `jit-match`, `views` in a disposable copied home plus import probes. The OMP source/read boundary was inspected, not launched by this worker. Python children used `PYTHONDONTWRITEBYTECODE=1` and sanitized environment variables. Temp homes were removed by `TemporaryDirectory`.

**M1 — physical lines and import inventory.** Reproduction command for the executed counting/import computations:

```bash
env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe - <<'PY'
import pathlib, ast
r = pathlib.Path('.')
skip = {'node_modules','__pycache__','.git','.venv','dist','build'}
code = {'.py','.ts','.tsx','.js','.ps1','.sh','.cmd'}
for base in ['src/second_brain','brainstem','scripts','tests']:
    ps = [p for p in (r/base).rglob('*') if p.is_file()
          and p.suffix in code and not set(p.parts) & skip]
    print(base, len(ps), sum(len(p.read_bytes().splitlines()) for p in ps))
for p in sorted((r/'src/second_brain/kb').glob('*.py')):
    t = ast.parse(p.read_text(encoding='utf-8-sig'))
    print(p, len(p.read_bytes().splitlines()))
    for n in ast.walk(t):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            print(n.lineno, ast.unparse(n))
for p in sorted(r.glob('*.md')):
    text = p.read_text(encoding='utf-8-sig')
    print(p, len(text.splitlines()), len(text), round(len(text)/4))
PY
```

The actual inventory also grouped those same file lists by immediate child, counted Markdown under `docs/`, and printed function/class AST start/end spans. Backup/worktree counting used `os.walk(..., followlinks=False)`, pruned dependency/cache/build/data subtrees and symlink/junction directories, counted the same code suffixes plus `.sql/.mjs`, and reported zero file-read errors. It excluded 86 backup and 305 worktree subtrees. This explains why those archive counts must not be conflated with unfiltered disk size.

**M2 — dynamic import proof.** Executed:

```bash
env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe - <<'PY'

[Showing lines 1-300 of 347. Use :301 to continue]