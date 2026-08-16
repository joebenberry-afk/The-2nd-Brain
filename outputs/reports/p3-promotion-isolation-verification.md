# P3 Promotion-Evidence — Isolation + Economics Verification (Worker B)

- Campaign: P3 Promotion-Evidence (ACTIVE vs SHADOW decision for the Lean Code runtime adapter)
- Plan: `Second_Brain_P3_Lean_Code_Promotion_Evidence_Plan.md` §8 (isolation), §9 (cache control), §10 (metrics), §15 (fresh independent evaluation)
- Repo: `C:\Users\assas\Documents\The-Second-Brain`, branch `brain/p3-lean-code` @ `7008da2` (FROZEN — no code changes, no commits, no arm runs)
- Worker B session: `01a00b1f-e668-765f-b67f-f0554642b87b` (deepseek-v4-flash, worker role)
- Freeze inputs: kernel sha256 `0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122`; Brain snapshot `backups/backup-20260816-150945-667622` (manifest format 1, note "P3 promotion-evidence campaign freeze")

## 1. Brain restore isolation — proven clean and repeatable

Procedure: `brainctl restore backups/backup-20260816-150945-667622 --force` (venv python `-m second_brain restore`, env sanitized).

| step | result |
|---|---|
| baseline doctor (pre-test) | 16 checks, 0 failed, 1 warn (rg not on PATH) — PASS |
| restore #1 | rc=0; db sha `5730d0a7…` == manifest; doctor PASS |
| restore #2 (repeat) | rc=0; db sha identical; doctor PASS |
| restore #3 (with `[lean]` present in live config) | rc=0; wipes `[lean]` (see §3); doctor PASS |

**Restore surface (what restore reverts):** exactly the manifest `copied` list — `config/`, `constitution/`, `projects/`, `VERSION` — plus `db/brain.sqlite` (the full DB file set). Implementation: `src/second_brain/backup.py` `restore_backup()`:
- preflights every manifest entry (containment + symlink checks) BEFORE any mutation;
- with `--force` moves the current `db/brain.sqlite(+wal/shm)`, `config`, `constitution`, `projects`, `VERSION` aside to `backups/pre-restore-<ts>/` (never deletes);
- copies the snapshot DB, **drops stale `-wal`/`-shm` sidecars** (verified: absent after restore — prevents WAL replay resurrecting moved-aside rows);
- copies the manifest `copied` entries; verifies restored-DB byte-identity against manifest sha; runs idempotent `db.migrate`.

**What survives (NOT reverted):** `telemetry/` and `outputs/` — verified byte-identical before/after restore #2 (telemetry/agent-performance: 543 files, outputs/reports/p3-eval: 136 files, mtimes unchanged). Also `skills/`, `memory/`, `experiences/`, `decisions/`, `engrams/`, `state/`, `sleep/`, `db` sidecars recreated on demand.

**Repeatability:** 3 consecutive restores from the same snapshot all rc=0 with identical post-restore db sha (`5730d0a7a5aa9235e085d607335729a497d01098207401bc12c19d659759b439`) and clean doctor. Restore is idempotent at the file level (restore over a restored state = no-op content change; each run still creates one pre-restore aside).

**Per-arm isolation verdict:** sound. Baseline writeback cannot become candidate input because each arm starts from this same snapshot, and the arm worktree is a disposable copy (plan §8.2; see §4). The one caveat: `backups/` itself is NOT reverted, so the pre-restore asides accumulate (68 → 71 during this verification); harmless, but the campaign should keep the snapshot dir out of any arm's disposable copy.

## 2. Lean-OFF/ON file gate — verified at parser + live-record level

Mechanism (P3-E fix, `brainstem/prime-extension/src/lean-code.ts`): env `SECOND_BRAIN_LEAN` (advisory/off) OVERRIDES; else `config/skills.toml [lean] eval = "advisory" | "off"` is read per event; absent ⇒ inert. Precedence: role (hard_orchestrator/normal → never) > env off > skill missing/corrupt > retired > lifecycle active > env advisory.

### 2a. Adapter's own parser (vitest-verified)

- Full extension suite: **369/369 tests pass** (13 files), including `lean-code.test.ts` (49), `lean-cache.test.ts` (4), `lean-fixtures.test.ts` (5). Covers: absent `[lean]` ⇒ inert; file advisory ⇒ inject (driver AND worker, `eval_source=file`); file off ⇒ omit even for ACTIVE skill; env overrides file both directions; invalid value ⇒ inert; unreadable config ⇒ fail-open inert + bounded error; Sol hard-orchestrator never injected.
- Direct cold-read through the compiled adapter (`esbuild` bundle of the adapter's own `leanEvalFromSkillsToml`/`resolveLeanEvalFromFile`/`decideLeanRuntime`, no repo changes):

| state | parser result |
|---|---|
| no `[lean]` section | `undefined` (inert) |
| `[lean] eval = "advisory"` | `advisory` |
| `[lean] eval = "off"` | `off` |
| invalid value (`banana`) | `undefined` (inert) |
| `[lean]` without `eval` key | `undefined` (inert) |
| live file (this session's config, advisory) | `{mode: "advisory", source: "file"}` |
| live decide, worker role | `{decision: inject, reason: advisory, mode: advisory, evalSource: file, skillStatus: candidate, kernelChars: 865}` |
| env `SECOND_BRAIN_LEAN=off` override | `{decision: omit, reason: off, mode: off, evalSource: env}` |
| hard_orchestrator role | `{decision: omit, reason: role}` (never injected) |

### 2b. Live lean_kernel record check (this session)

The extension emits one `lean_kernel` record per `before_agent_start` (once per agent epoch, i.e. per queued/injected input — verified against host `agent-session.ts` TurnExecutionPolicy: continuation turns after tool results do not re-run before_agent_start).

- Pre-flip baseline (gate inert): 3 records, all `{decision: omit, reason: off, mode: null, eval_source: null, kernel_chars: 865, skill_status: candidate, role: worker, v: 2}`.
- Gate flipped to `[lean] eval = "advisory"` (config hash `6ed2631e…` → `15437055…`); next epoch's record expected `{decision: inject, reason: advisory, mode: advisory, eval_source: file}` — **PENDING: this session's next before_agent_start** (the daemon fires it on the next parent message; the record will be appended to this session's telemetry and confirmed in a follow-up).
- **Already proven at arm scale**: all 34 window-2 arm sessions carry gate-confirming records — candidate arms: `{mode: advisory, eval_source: file, decision: inject, reason: advisory}` (51 records); baseline arms: `{mode: off, eval_source: file, decision: omit, reason: off}` (51 records); zero exceptions; zero extension errors. Window-1 arms (pre-file-gate wiring) are all `mode: null` — consistent with the gate's fix history.

### 2c. Restore wipes `[lean]` — proven

Restore #3 was executed WITH `[lean] eval = "advisory"` present in the live `config/skills.toml`. After restore: `[lean]` absent, hash back to the backup/committed value (`6ed2631e…`), doctor PASS. ⇒ **per-arm procedure is: restore snapshot → flip `[lean]` in the arm's config → run arm → restore again** (or flip back); restore alone is sufficient to reset the gate.

## 3. Economics telemetry — fields available per arm session

Source of truth: `brainstem/telemetry/SCHEMA.md` + sensors (`brainstem/prime-extension/src/sensors.ts`) + 68 arm telemetry files (`outputs/reports/p3-eval/*/telemetry.jsonl`). Field presence measured across ALL arm sessions:

| record kind | fields | presence |
|---|---|---|
| `assistant_usage` (v=3) | `provider`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `cost_total` | 1050/1050 records carry ALL counters (zero preserved, absent omitted) |
| `provider_request_meta` (v=3) | `provider`, `model`, `request_seq`, `request_bytes`, `message_count`, `payload_keys`, `system_prefix_sha`, `tool_surface_sha` | 1051/1051 all present |
| `provider_response_meta` (v=3) | `status`, `headers[{key, value_sha256}]` (cache/rate-limit allowlist only) | 1050/1050 |
| `autoinject_shadow_decision` | `decision`, `reason`, `packet_tokens`, `latency_ms`, `candidate_count`, `selected_count`, `delivery_id`, `packet_sha256`, `mode`, `model_visible`, `result_patch`, `emit_index`, `cache_hit`, `handler_returned_message`, `cli_packet_chars`, `cli_stdout_chars` | 204/204; `packet_tokens` 202/204 (null on NO_INJECTION) |
| `brain_packet_delivered` | `packet_id`, `item_count`, `packet_tokens`, `delivery_count`, `canonical_packet_hash`, `model_visible`, `delivery_prepared` | 136/136 (Python pipeline ledger — PREPARED state, not host insertion) |
| `lean_kernel` (v=2) | `decision`, `reason`, `role`, `skill_status`, `mode`, `eval_source`, `kernel_chars`, `dedup_hit` | 204/204 for decision/reason/kernel_chars/dedup_hit; `mode`+`eval_source` only in window-2 arms (102/204); `skill_status` null when mode=off (kernel never loaded) |

**What evidence.json collectors can rely on** (template snippet §4 of `p3-eval-arm-template.md` + 68/68 existing evidence.json):
- `assistant_usage` → `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `cost_total` — always available; `cache_write_tokens` is 0 across all arms (provider reports none) — record but do not interpret.
- `autoinject_shadow_decision` → packet COUNT + `packet_tokens` sum — reliable (guard for the 2 null NO_INJECTION rows).
- `tool_call` counts, `turn_start` count, first/last `ts` for wall_ms — reliable.
- `lean_kernel.kernel_chars` — reliable; `mode`/`eval_source` — only for window-2 arms (the valid window); use `decision`+`reason` for treatment verification.
- Per plan §9: cache_read is reported separately (provider cache-warmth/order effects) and NOT attributed to Lean; `assistant_usage` is logical/model-visible input, `cost_total` is billed cost.

## 4. Arm-label blinding — VERDICT: template is NOT label-free; artifacts leak arm identity; stripping procedure below

The task asked to confirm the P3-E arm template contains no Lean/baseline/candidate mentions. **It does NOT pass that bar:**

1. Template header (lines 4-5): "sets the env gate (`SECOND_BRAIN_LEAN=advisory` for CANDIDATE arms only; unset for BASELINE)" — names the experiment AND the arm-discriminating env var.
2. Body line 17: `tests/fixtures/lean-code-tasks/<SLUG>` — the fixture path contains "lean-code".
3. Body line 13/19: "`## BASELINE HINT`" and "a baseline commit".
4. Return contract line 71: "## Lean decisions — LC_* codes".

Because the template is identical for both arms, the header alone does not reveal WHICH arm a session is — but it does reveal the campaign's goal (evaluating a Lean kernel), which a fresh evaluator could reward/correct for. Worse: the template tells the child the env var name, and the child has shell access (`echo $SECOND_BRAIN_LEAN`) — a motivated arm session could trivially self-identify.

**Artifact leaks (matter for §15 blind review):**
- `evidence.json` carries `"arm": "baseline" | "candidate"` (68/68 files) — must be stripped.
- `telemetry.jsonl` `lean_kernel` records carry the arm identity directly: candidate = `{mode: advisory, decision: inject}`, baseline = `{mode: off, decision: omit}` (window 2). Must be stripped or redacted before review.
- Candidate sessions' system prompts contain the injected kernel (`[second-brain-lean-code-kernel]` marker + 865-char kernel) — session transcripts are not blindable without removing that block.
- AutoInject packet content (`pkt-*`) is identical across arms — measured: `brain_packet_delivered` packet_tokens = 995 per arm run in ALL 34 task/arm pairs (0 mismatches; candidate == baseline), so packet cost/content cannot confound the comparison.

**Proposed blinding procedure for §15 (fresh evaluator):**
1. Deliver arm outputs WITHOUT the template header: use only template body sections 1-6, and neutralize the fixture path (refer to the fixture by `<SLUG>` only), "BASELINE HINT" → "HINT", "baseline commit" → "initial commit", "Lean decisions" → "Decisions".
2. Strip `arm` (and `run_id`'s arm token) from every evidence.json; present `economics` + `diff` + `judge` only.
3. Strip all `lean_kernel` records from telemetry before review (or drop `mode`/`eval_source`/`decision`/`reason` if counts are needed).
4. Never show candidate session logs raw — excerpt only post-kernel reasoning, or remove the `[second-brain-lean-code-kernel]` block and its text.
5. Remove `SECOND_BRAIN_LEAN` from any env snapshot given to the evaluator.
6. Reveal arm identity ONLY after scoring (plan §10.6/§15).
7. Re-verify: run a grep for `lean|Lean|LEAN|baseline|candidate|SECOND_BRAIN_LEAN|arm` over the assembled verifier brief before sending (this report's own scan found all leaks above).

## 5. Orchestration economics — this Worker B session (campaign overhead)

From this session's telemetry (`telemetry/agent-performance/01a00b1f-e668-765f-b67f-f0554642b87b.jsonl`):

- assistant_usage: rows 65; input 65,869 / output 41,804 / cache_read 3,529,760 / cache_write 0 / total 3,636,633 tokens; cost $0.030808 (deepseek-v4-flash).
- tool_calls: ipython 65; tool_result rows 64; turns 65; wall ~439 s (at capture).
- AutoInject: 2 packets delivered (995 packet-tokens) + 3 shadow decisions — recorded separately from assistant_usage, never double-counted.
- lean_kernel records: 3 (all inert pre-flip) + pending advisory record (§2b).
- No compaction; no sub-spawns (RLM_MAX_DEPTH=1 respected); restore/gate-flip mutations were config/derived only — zero source changes (`git status` clean apart from the intentional `config/skills.toml` flip, reverted by restore at the end of this verification).

## 6. Findings summary

1. Restore roundtrip: clean, repeatable, byte-identical db, doctor PASS ×3, sidecars dropped, telemetry/outputs survive; restore surface = db/config/constitution/projects/VERSION. AutoInject packets identical across arms (995 packet-tokens/run, 34/34 pairs) — no packet confound.
2. File gate: parser-level proven (369/369 vitest incl. 58 lean tests + direct cold-read); arm-scale proven (34 window-2 arms: advisory/file/inject vs off/file/omit); restore wipes `[lean]` (restore #3).
3. Economics fields: all six assistant_usage counters + provider/model present in 100% of arm records; provider_request_meta complete; lean_kernel mode/eval_source only in window-2 arms; cache_write always 0.
4. Blinding: template NOT label-free (header + fixture path + "Lean decisions"); evidence.json `arm` field + lean_kernel records + candidate system prompts leak arm identity; stripping procedure defined (§4).
5. Overhead: Worker B cost $0.031, 65 turns, 65 tool calls, AutoInject 995 packet-tokens.

## 7. Pending / open items

- Live advisory record for THIS session lands on the next before_agent_start (next parent message); expected `inject/advisory/file` (verified at arm scale already, 51 records).
- `backups/` accumulates pre-restore asides (expected behavior — never deleted by design).
