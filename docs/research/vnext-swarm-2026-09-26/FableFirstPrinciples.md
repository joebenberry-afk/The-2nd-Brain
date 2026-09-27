# Fable — first-principles review of The Second Brain (read-only, 2026-09-26)

Verdict: this is a genuine blocker, but not the one described. None of the four architectures could have produced a qualified win because (1) the instrument cannot see wins of the size a memory layer can produce, (2) the corpus holds almost nothing an agent cannot already read from `AGENTS.md`/source, and (3) every V3-era delivery channel was either mute on question-shaped needs or pointed at a CLI that did not exist in the sandbox. The one channel that delivered 100% at zero tool calls in every arm — the host's own context file — is the one the design forbade itself from using.

Everything below is verified from repo artefacts unless marked [INFERENCE]. Commands I ran are shown; nothing was written to the repository.

## Top findings

1. **The g3-live-2 "FAIL" is a gate artefact, not a Brain result.** `summary.json:2293-2314`: `memory.pass=true`, `no_benefit.pass=true`, `families_non_inferior=true`, verdict FAIL only because `no_benefit_zero_additions=false` — one 291-byte push on VG-N05 rep (REPORT.md:86; trigger `python` on `mem-6d592dd0c627`, records/mem-6d592dd0c627.md:12-13). Correctness native 17/30 → jit 22/30 (`summary.json:239-251`). Impact: a 70-token push on one no-benefit rep flips the campaign. Confidence HIGH.

2. **86% of "incorrect" verdicts in g3-live-2 are grader/answer-key defects, not agent errors.** I dumped all 60 memory answers with their `missing_groups` (runs.json):
   - VG-M01: 11/12 answers name PYTHONHOME+PYTHONPATH+"SRE module mismatch" from AGENTS.md; graded wrong for lacking `UV_INTERNAL__PYTHONHOME` (tasks.jsonl:1). That token lives only in records/mem-b67de5057f76.md:25,29 — `status: superseded` at 2026-09-25T22:33:21Z (line 12), 48 s before the campaign's first run (raw timestamp 1790375649750 = 22:34:09Z). The task's `memory_ids` still points at the retired record. Unwinnable by any Brain.
   - VG-M07: 6/6 answers correct ("daemon pins env at its own startup; use a dedicated --daemon-socket per run"); 6/6 graded wrong because none used the exact phrases in check group 4 (tasks.jsonl:7).
   - VG-M10: 6/6 answers say PreToolUse/Stop return `{}` — that is what `src/second_brain/adapters/antigravity.py` implements; the key wants the record's official-contract fields. The agent obeyed `constitution/truth-precedence.md:23-27` (repo beats memory) and was graded wrong for it.
   - VG-M09 native R2: answer says "the driver **MAY** execute" — markdown bold defeats regex `may execute`.
   Net: 18 of 21 "incorrect" verdicts are artefacts; semantic correctness ≈ native 27/30 vs jit 30/30, and the three native misses (M06×2, M09×1) are on tasks where JIT delivered 0 bytes. Confidence HIGH.

3. **The suite has no statistical power for the effect sizes at stake.** Pooled within-task SD of ln(logical tokens) = 0.46 (native) / 0.50 (jit) in g3-live-2 and 0.62 in g3-live-full (computed from runs.json; run-to-run factor 1.6–1.9×; extremes: VG-M06 native 53K/981K/376K, VG-M08 native 43K/338K/128K). With n=3 and a paired-median-of-medians bootstrap on 10 points, the CI crosses zero for any plausible effect; the legacy campaign's "token CI crossed zero" (campaign2/REPORT.md:28, CI [-7907, +7172] on a −2032 median) is the same instrument failing, not the legacy losing. Confidence HIGH.

4. **Every large "win" attributed to JIT occurred with zero Brain bytes delivered.** VG-M06 (351K→156K), VG-M09, VG-M04, VG-M07 deltas: `request_capture.brain_bytes=0` in 8 of 9 JIT runs on M06/M09/M04 (runs.json). Brain content reached the model on only M02/M05/M08/M10 (+the N05 leak), and on M05/M08/M10 the 306-byte item was the *provenance preamble* of the locator ("…out/main.js and out/jetskiAgent/main.js contain the exa/hooks_pb protobuf descriptor…") because `render_jit_item` sends title + first sentence (src/second_brain/kb/views.py:433-445) and the record's first sentence is not the fact (records/mem-79d7c4fd9876.md:26). The only informative delivery was M02's 97-byte "Migration ordering", on a task both arms answer correctly in 2–6 calls. Confidence HIGH.

5. **The v3-brief arm was measured with its pull channel broken.** The brief says "Ask: brain q" (views/second-brain/brief.md:2); the suite launches `omp --no-extensions --no-skills --no-rules` without the venv on PATH (scripts/v3_value_suite.py:1265-1276; `brain` is a venv console script, pyproject.toml:14). Result: 9/9 `brain q`/`brain show` calls in the brief arm exited 127 "command not found" (g3-live-full raw, e.g. VG-M10-v3-brief-R0.jsonl). After the dead end the agent hunted 19 more calls for "installed app bundles" (M10 brief 21/7/11 calls vs native 3/3/4). "Brief is worse than native" is confounded by a missing binary. Confidence HIGH.

6. **The corpus is effectively empty of deliverable value.** records/: 121 files; 18 `current` (63 superseded, 35 candidate, 5 retracted); of the 18 current, 10 are "OMP 18.1.15 documented …" release-note summaries (host is 18.3.1), only 6 carry any trigger, and only `current` records compile (views.py:583). The three gotchas that would actually save a session ("pkill -f kills the calling shell", "mkdirSync under /proc hangs", "cloud bun lacks node:sqlite") are `candidate` and never delivered. Real-session telemetry: 17,060 JIT observations across 281 OMP sessions → 13 deliveries (0.08%), 7 of them the PYTHONHOME gotcha that AGENTS.md:58-65 already states (`telemetry/kb-hooks.jsonl`, counted). Confidence HIGH.

7. **The host's context file is the only channel with observed 100% delivery at 0 tool calls — and the design banned it.** VG-M01 was answered from AGENTS.md in 12/12 runs across all arms with 0 tool calls (runs.json); OMP injects AGENTS.md verbatim into every request (raw provider-request JSON, message[1] `<repo-rules>`). The V3 plan's binding rule 1 ("The Brain never writes files into a user's project repositories", plan §11.1) and rule 4 ("Per-prompt push: 0 tokens") exclude exactly this channel, while the legacy Brain already owns a fenced, byte-restorable AGENTS.md block (src/second_brain/registry.py:288-380; visible at AGENTS.md:79-90) whose body is five lines of policy prose. Confidence HIGH.

8. **Token cost is turn-dominated; injected bytes were never the problem.** A no-tool prompt costs ~8.8K logical tokens (VG-N01, summary.json:280-283) — the system prompt alone. Every extra request costs ≥ 9K logical tokens; the 600-token brief or an 80-token item is 1–7% of one request. The only lever that moves logical tokens is fewer requests (hunt length). Brain content wins only when it ends a hunt; it loses when it starts one (brief M10: pointer to "installed app bundles" → +18 calls). Confidence HIGH.

9. **"Advisory — verify before relying" framing induces hunts; context-file framing does not.** Same kind of fact: PYTHONHOME via AGENTS.md → 0 calls (12/12). Facts via Brain message in the legacy arm still took 11–16 calls (campaign2/REPORT.md:47-48) and in the brief arm 7–21 calls, because the agent verifies memory against the repo — which `constitution/truth-precedence.md:26` and the marker text "current repo/tests outrank memory" tell it to do. Pushed facts therefore must carry a precise anchor (file:line/§) so verification is one read, or be placed where the host treats them as repo reality. Confidence MED (behavioural inference from 30+ runs, not an ablation).

10. **JIT's trigger vocabulary cannot represent question-shaped needs.** Triggers are path/command/error in *tool results* (brainstem/omp-v3/index.ts:223-258); the need in M06/M07/M09 is visible only in the user prompt ("worker cap", "SECOND_BRAIN_HOME…daemon"). Result: 0/9 deliveries on those tasks in both campaigns. The legacy per-prompt matcher delivered the expected record on 10/10 tasks (campaign2/REPORT.md:17). Confidence HIGH.

## Root-cause diagnosis (why none of the four won)

- **Measurement (primary, ~60% of the story):** regex graders and stale/contradicted keys (findings 2), an underpowered statistic (3), a verdict that a single 70-token leak flips (1), a sandbox missing the CLI the brief advertises (5), and a wandering low-effort model whose run-to-run spread is 1.6–1.9× (3). No architecture can pass this instrument; a perfect Brain fails M01/M07/M10 by construction.
- **Knowledge (co-primary):** 4–6 useful current records; the rest are host release notes or superseded incidents; the potentially decisive gotchas are locked at `candidate`; the one locator leads with provenance instead of the fact (4, 6).
- **Delivery:** V3 brief = titles + dead CLI pointer; V3.x JIT = tool-result-only triggers + first-sentence truncation; the legacy channel that reached 10/10 tasks was switched off by assumption (O3, rule 4), not by measurement (7, 10).
- **Host:** cost is per-request context replay; the host already ships AGENTS.md to every request for free; the Brain competed with that channel instead of compiling into it (7, 8).

## Breakthrough candidates

### A. Compiled context block — "the Brain writes AGENTS.md, not prompts" (RECOMMENDED)
- **What changes:** `brain compile <project>` renders a hard-capped block (≤ 30 lines / ≤ 500 tokens) into the fenced marker region the Brain already owns in the project's `AGENTS.md` (registry.py:288-380). Content, in priority order: gotchas (OS/machine/tooling, TESTED+), active `state`, current decisions, locators — every line is *fact + anchor* (`path:line` or `doc §`), never a title or a "run brain q" pointer. Claude Code reads it via the existing `@AGENTS.md` import (CLAUDE.md:3); Codex, Cursor, Gemini CLI and OMP read AGENTS.md natively (https://agents.md/ ; https://cursor.com/docs/cli/using ; https://developers.openai.com/codex/guides/agents-md.md ; OMP verified in captured requests). The block is committed with the project → cross-machine by the project's own git; the Brain home's git sync carries the source records. Records, `brain q`, `brain note`, FTS stay as source + pull; `brain doctor` verifies every anchor resolves.
- **Why a change of kind:** no runtime, no hook, no adapter, no daemon, no per-host code; the host's authoritative channel carries facts the agent consumes without hunting (finding 7, 9). Replaces "push at moments" with "compile at write time".
- **Expected effect:** delivery 100% on every host (measured for the channel: M01 12/12 at 0 calls). Token model per session: +B tokens per request, cache-prefixed after request 1 (B ≤ 500; ≤ 6% of the 8.8K baseline request); break-even when the block removes ≥ 1 request per ~20 (each request ≥ 9K logical). Correctness: [INFERENCE] the 3 native misses in g3-live-2 (M06/M09 hunts in a 20-tool-call narrative doc) are the locator case the legacy channel already fixed (94K→36K, campaign2:48,70).
- **Effort:** S (≈300 lines: renderer + `brain compile` + doctor anchor check; attach/detach exist). **Risk:** block bloat (cap + priority + "empty when nothing current"); staleness (anchor check in CI); §11.1 owner rule; multi-project domains duplicate lines per project (fine).
- **Obsoletes:** brainstem/omp-v3 (604 lines), views/generations + triggers.json, kb outcome scoring, JIT plan + contracts, eager brief renderer, kb/hooks.py Claude consumer, and — after E1 — all of the legacy prime-extension and 49.8K-line Python runtime (rollback = `brainctl project detach`, byte-for-byte, satisfies constitution rollback).
- **Cheapest kill experiment:** E1 below.

### B. Prompt-matched push (the legacy channel, V3-lean)
- **What changes:** at prompt submit (OMP `before_agent_start`; Claude Code `UserPromptSubmit`), match record `terms`/paths against the *user prompt* (not tool results); push ≤ 2 full records with anchors, 0 when no match; compiled JSON table, ≤150-line adapter per host.
- **Change of kind vs JIT:** matches the need where it is stated. Legacy delivered 10/10 vs JIT 5/10 (finding 10).
- **Expected effect:** 0 tokens on unmatched prompts; ~200–400 tokens × remaining requests when matched. [INFERENCE] correctness like campaign2 (20/30→27/30) if the CLI and grading are fixed.
- **Effort:** M. **Risk:** matcher precision (N05-type leaks), per-host hook drift, hosts without a prompt hook (Cursor; Codex/Gemini uncertain [INFERENCE]) get nothing → needs A as fallback anyway; prompt text must never persist (security-boundaries).
- **Obsoletes:** JIT tool-result matching, epochs, recovery. **Kill experiment:** E3.

### C. Skills-shaped Brain (host-native progressive disclosure)
- **What changes:** compile gotcha/procedure/locator clusters into skill directories (`SKILL.md` with a one-line description); hosts list descriptions every request and load bodies on the model's judgement (OMP skills verified in this session's prompt; Claude Code skills; Cursor "Agent Requested" rules; Codex skills [INFERENCE]).
- **Change of kind:** the model is the matcher, the host is the loader; the Brain only compiles.
- **Expected effect:** ~20–30 tokens/skill/request + ≤300-token body on load; same order as A but bodies on demand. Unmeasured whether models load fact-skills reliably [INFERENCE].
- **Effort:** M. **Risk:** skill-list caps, format drift across hosts, facts dressed as instructions. **Obsoletes:** same as A. **Kill experiment:** E3 variant (skills arm).

### Recommendation
A, with B/C only if E1 shows the block cap binds (many relevant records per project). A is the only candidate whose channel has *observed* 100% delivery at zero tool calls, needs no per-host runtime, and whose failure mode (bloat) is bounded by a cap. Scrap outright: omp-v3 JIT adapter and plan, views generations/triggers, outcome scoring, the eager brief, the "advisory/verify" framing, the OMP-only host focus, and — after E1 passes — the legacy runtime.

## Decisive experiments (cheapest first; agent under test = `openai-codex` gpt-5.5, effort medium; no deepseek)

**E0 — Re-grade, no model calls (free, ~1 h).** Re-score the 120 existing g3-live-2 runs with (a) semantic grading (jev_verify or human) and (b) corrected keys: M01 → current record (`mem-6d592dd0c627`: PYTHONHOME/PYTHONPATH/SRE), M10 → repo-reconciled key. Pass/kill: if ≥ 15 of the 21 "incorrect" verdicts flip, the correctness signal is confirmed broken and every prior FAIL is void on correctness. Also switch the statistic to a paired t on ln(tokens) pooled over tasks×reps (task fixed effect) and report per-task CV; keep median deltas as descriptive only.

**E1 — Context-block channel (decisive for A; ~40 live runs).** Arms: `native` vs `native+block`, where the block is compiled from the same snapshot corpus into the sandbox copy's `AGENTS.md` marker region (no extension, no CLI). Tasks: the 10 memory tasks with corrected keys + 10 no-benefit; reps 5 (with SD 0.5 on ln-tokens, 50 paired points detect a 25–30% reduction at α=0.05, 80% power). Pass: memory correctness non-inferior (semantic), pooled tool-call median delta ≤ −2 or ln-token delta ≤ −0.3; no-benefit correctness equal and per-request overhead ≤ block tokens (report it, do not require 0). Kill: block delivered in every request (verify via request capture) but tool calls do not drop → the hunt-ending hypothesis is false; then the problem is content, go to E2 before any architecture.

**E2 — Anchor ablation (what to store; ~30 runs).** Arms: `block-facts` (fact lines, no anchors) vs `block-anchored` (fact + `path:line`/§) on M04/M06/M08/M09/M10 only (the hunt tasks). Pass: anchored arm ≤ 2 tool calls median where facts-only ≥ 4. Kill: no difference → verification hunting is not anchor-driven; revisit framing (finding 9).

**E3 — Only if A's cap binds:** `native+block` vs `native+block+prompt-push` (B) vs `native+skills` (C) on a corpus with ≥ 40 relevant records per project. Pass: candidate beats A on tokens at equal correctness with ≤ 1 leak on no-benefit.

Harness fixes required before E1 (all inside `scripts/v3_value_suite.py`): put `.venv/Scripts` on PATH in every arm (or drop every "brain q" pointer from delivered text); load the block from the sandbox copy, not `$SECOND_BRAIN_HOME`; make the M01/M10 keys current; semantic grader; pooled statistic; record `request_capture` for the block bytes so overhead is reported, not gated to zero.

## Kill list

- `brainstem/omp-v3/index.ts` tool-result JIT (finding 4, 6, 10): 13 deliveries in 17,060 live observations; 0/9 on question tasks; first-sentence truncation ships provenance.
- `docs/requirements/V3x_Just_In_Time_Memory_Plan.md` + `V3x_JIT_Contracts.md` (1,099 lines) and O8–O11: built on "no per-prompt push" and "tool results are the moment of need", both contradicted by the data.
- Eager brief renderer and the "Ask: brain q / verify before relying" text (finding 5, 9).
- Outcome scoring (`kb/outcomes`, `config/jit.toml`): shipped off; unmeasurable with this instrument.
- Value-suite pass rule "zero Brain additions in every no-benefit request" (finding 1); regex graders on M01/M07/M09; M01/M10 answer keys; median-of-3 paired bootstrap as the verdict statistic (finding 3).
- The 10 "OMP 18.1.15 documented …" fact records (views/second-brain/brief.md:15-24): host is 18.3.1; the first live session rated 11/14 such lines noise (docs/research/v3-just-in-time-memory-proposal.md:111-113).
- V3 binding rules §11.1 (never write into project repos), §11.4 (0 per-prompt tokens), §11.7 (OMP-only) — owner rules, not constitution; they exclude the only working channel and the stated goal (all hosts).
- deepseek-flash as agent under test (owner directive; also the 1.6–1.9× wander factor).
- After E1 passes: `brainstem/prime-extension` (28.9K TS) and the legacy `src/second_brain/*` runtime (49.8K Py) except records/kb/CLI/registry attach-detach.

## Owner decisions required

1. Permit the Brain to own one fenced, byte-restorable block in a managed project's `AGENTS.md` (revokes V3 §11.1; precedent registry.py:288-380). Not a constitution change: truth-precedence and rollback are preserved (`brainctl project detach`).
2. Replace PERF-01/§11.4 "zero per-prompt additions" with "≤ 500 cache-stable tokens per request, empty when nothing is current, reported per campaign".
3. Retire §11.7 OMP-only focus in favour of the host-agnostic context-file channel (matches the new goal).
4. Adopt the corrected value-suite contract: semantic grading, repo-reconciled keys, pooled log-ratio statistic, no-benefit overhead reported not zero-gated, `openai-codex` model, ≥ 5 reps.
5. Corpus policy: retire the OMP 18.1.15 fact records; require new records to lead with the fact sentence and carry an anchor; re-type the Sparking "T1 step N complete" candidates as `state` or archive them.
6. Whether labelled `candidate` gotchas may appear in the block. Recommendation: no (learning-boundaries.md:14-20); instead make `brain promote --evidence <tool-result>` a one-command path so the three high-value gotchas get promoted with evidence.

## Open questions (not settled by the data)

- Do gpt-5.x-class agents show the same "AGENTS.md = trusted, Brain message = verify" asymmetry as deepseek-flash? E1/E2 settle it.
- Does Codex/Gemini CLI expose a prompt-submit hook (needed only for B)? Not needed for A.
- How many relevant current records will a real project accumulate once capture is frictionless — i.e., does A's 30-line cap bind within months? (Today: 4–6.) Determines whether B/C are ever needed.
- Should logical tokens (cache reads counted) or uncached tokens be the reported cost now that the provider is subscription-based? The recommendation is robust under both, but the break-even arithmetic differs by ~10×.
