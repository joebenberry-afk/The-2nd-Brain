---
date: 2026-09-28
type: plan
authority: owner-approved 2026-09-28 ("I support all your recommendation")
status: accepted 2026-09-28; P1 in progress (P0 sign-off runs in parallel)
scope: v5
supersedes: none (extends 2026-09-27-plan-v4-agent-experience.md; V4 §3.2 rules stay binding)
superseded-by: none
---

# Second Brain V5 — anchored memory that proves it helps

## 0. The one-paragraph version

V4 made the Brain small, fast and felt: a start card, a working state that survives compaction,
one known fix on a failure, recall and note in one call. The first live week says which of those
earn their tokens. The start card (the plan carried across sessions and restarts) and known fixes
do; the post-compaction resume repeated what OMP's own summary already kept; recall mostly
answers the wrong question; the learning loop has not produced one accepted note. V5 changes
three things and puts two more on trial. First, **anchors instead of copies**: the working state
and recall point into the repo's own plan documents (`docs/LOOP.md › Resume`) and render their
current text, so the Brain can never drift from the repo it summarises. Second, **recall judged
on real agent queries**: a second frozen eval built from logged `brain_recall` calls, where a
wrong answer costs more than silence. Third, **learning that lands**: every fired fix is scored
by whether the next attempt succeeded, and pair mining is replaced by one measured end-of-task
prompt. On trial: kits and the post-compaction resume, each kept only if a longer benchmark shows
a benefit. Anything that still produces nothing after two weeks is deleted.

## 1. Evidence from V4 (2026-09-27 → 2026-09-28)

| Signal | Number | Source |
|---|---|---|
| Brain on vs off, fixed GPT tasks incl. a memory task | −30 % tokens, −39 % cost, 6.7 vs 9.2 turns, 20/20 vs 16/20 | `brain/scripts/agentbench.ts`, fixture v3 |
| Compaction resume, scripted on Windows | 10/10 goal and next recalled; 57-token resume | `brain/scripts/compactbench.ts` |
| Resume causality (resume removed from context, 10 + 10) | also 10/10: OMP's own summary kept goal and next in every run | compactbench `ablate`, `p2-ablation-head-28f537a` |
| Card delivery, 7 days | 177 cards (48 main, 129 sub); ≤ 400 tokens | `brain stats --days 7` |
| Brain tools used in main sessions (stamped builds) | 4 of 9 (stop-loss is < 20 %) | telemetry |
| Known fixes fired | 49 times; the edit-grammar fix in 7 sessions | telemetry |
| Real `brain_recall` queries, hand-labelled (37) | before `28f537a`: 6 right, ~5 partial, ~19 wrong, 7 silent; after: 6 right, 6 partial, 10 wrong, 15 silent | session files; `28f537a` |
| Frozen V3 recall eval | dev 13/15, held-out 7/8 (unchanged by the precision fix) | `test/eval.test.ts` |
| Notes | 160: 120 converted from V3, 40 agent-written, **0 from capture**; 43 tested, 28 retired | `notes/` |
| Capture proposals reviewed live | every one was noise (17 on 09-27, then `p-e8f18b11d5`, `p-bb20ed2433`) | `brain review` |
| Kits (P4) | without the body: +8.8 % tokens to first pass (body read 1/6); with the body: −2.2 % tokens, −3.3 % calls, −25 % cost (6 + 6) | agentbench `scaffold`, `p4-kit-body` |
| Where agent money goes | 611 M cache-read vs 2.6 M output tokens / 24 h; cost is turns × context | `omp stats`, plan V4 §6.1 |

Owner-relayed agent review (Absolute Laya, 2026-09-28): *useful, mostly because of the resume
state; on-demand recall rarely hit; the auto "last failure" steered it wrong; the card repeated;
the state note is a short copy of `docs/LOOP.md`'s tail and can drift.* The repeat, the stale
failure and the mid-word cut are fixed in `28f537a`. The drift and recall points are what V5 is
for.

## 2. Diagnosis

1. **Compaction continuity is not where the resume earns its tokens yet.** In a short scripted
   session, OMP's own summary carried goal and next every time; removing the 57-token resume
   changed nothing. The card is what carries the plan across sessions, restarts and machines.
   Whether the resume matters in long sessions (several compactions, a summary crowded with other
   work) is unmeasured.
2. **Recall answers questions the Brain cannot know.** Agents query in keyword bags about project
   knowledge ("LOOP.md goals", "jobq commands", "sealed.py rewrite …"). That knowledge lives in
   the repo's documents, not in 160 notes, so BM25 over notes either stays silent or matches one
   shared word. The frozen eval did not see this: its prompts are V3-era natural-language
   questions whose answers *are* notes.
3. **The working state duplicates the repo's plan.** Projects with a living plan file
   (`docs/LOOP.md`, this repo's plan §6.1) get a second, shorter copy in `work/<project>.md`.
   "The repo wins on conflict" is a rule the agent must apply by hand, every session.
4. **The learning loop does not close.** Pair mining finds command retries, but real repairs are
   edits; every proposal so far was noise. Agents write notes when asked (40), rarely unprompted.
   Nothing measures whether a note or fix, once shown, helped.

## 3. What changes

### 3.1 Anchors, not copies

- `projects.json` gains `docs`: plan files the Brain may read (default: none; `brain project docs
  add docs/LOOP.md`). Only Markdown headings and the text under one heading are ever read; code is
  never indexed.
- `brain_state` accepts an anchor line, `See: docs/LOOP.md#resume`. The card renders that section's
  **current** text from the checkout (cut to the state's budget, ≤ 150 tokens after compaction)
  instead of a stored copy; the stored text is only the delta the file does not hold. A missing
  file or heading shows `anchor missing: docs/LOOP.md#resume` once, never a stale copy.
- Recall that finds no note answers with at most one heading line from the project's `docs`:
  `docs/LOOP.md › Goals (line 12)`. Budget unchanged: ≤ 3 lines.

Done when: in this repo and Absolute Laya, the card's "where we left off" equals the anchored
section byte-for-byte after an edit to the file, with no `brain_state` call; `LOOP.md goals`
answers with the heading line.

### 3.2 Recall judged on real queries

- Telemetry keeps each recall's query (scrubbed, local `state/` only) and the ids it returned.
- A second frozen eval, `test/fixtures/recall-real.jsonl`, from the logged queries (the 37 above
  plus two weeks of new ones), each labelled with its right note, heading, or "silence".
- Gate: wrong answers ≤ 10 % of queries; right answers never fewer than the day the set is frozen;
  the V3 eval keeps its thresholds.

Done when: both evals run in the gate and `brain stats` shows the weekly wrong-answer rate from a
labelled sample.

### 3.3 Learning that lands

- **Fix efficacy.** When a known fix fires, the next run of the same command (or tool) within the
  session decides it: success → `helped`, failure → `missed`. `brain stats` shows helped/missed per
  fix; a fix below 50 % over ≥ 4 firings loses `tested` and says so on `brain review`.
- **One end-of-task prompt, measured.** `BRAIN_STOP_NUDGE` (built in V4, off) runs in agentbench
  on vs off; it ships only if it raises notes that are later recalled or fired without costing
  more than 5 % tokens.
- **Pair mining gets two weeks.** If no capture proposal is accepted by then, capture proposals
  (not the event log, which feeds fixes and stats) are deleted.

Done when: every fired fix has an outcome in telemetry; the nudge has a shipped/rejected verdict
with numbers; capture proposals are either producing accepted notes or gone.

### 3.4 Kits: confirm or fold

With the kit body in the recall answer, the kit beat native narrowly (6 + 6 runs: −2 % tokens,
−3 % calls, −25 % cost to first pass). One more task shape and 12 + 12 runs decide it: if the
advantage does not hold, a kit becomes a `procedure` note (recall already returns bodies) and
`kits/`, `brain kit …` and the card's kit line are deleted.

### 3.5 Resume: prove it or trim it

compactbench gains a long-session scenario: three compactions, each turn crowded with unrelated
reads and edits, the goal changed once midway. `resume` vs `ablate`, 10 + 10. If removing the
resume still changes nothing, the post-compaction resume carries only what the host summary
dropped (edited files, the last failure) or is removed; the start card is untouched.

### 3.6 Sign-off and host parity (carried from V4)

A week of daily use; P6 cleanup; the `v2-archive` tag pushed on the owner's go; Claude Code
verified end to end once the owner's Claude login is renewed (the hook already delivers the card).

## 4. What V5 does not do

No embeddings, no database, no code indexing, no new resident tools (still three), no per-prompt
injection, no second harness adapter beyond the Claude Code hook and MCP. The card stays ≤ 400
tokens and appears once per session and once after each compaction.

## 5. Phases

| Phase | Build | Done when |
|---|---|---|
| **P0 V4 sign-off** | Daily use; P6 cleanup; `v2-archive` tag on owner's go | V4 §6 criteria all met or explicitly waived by the owner |
| **P1 Measure first** | Recall query logging; fix-efficacy outcomes; `recall-real.jsonl` frozen; long-session compactbench | Baselines recorded in this plan: wrong-answer rate, helped/missed per fix, resume vs ablate on long sessions |
| **P2 Anchors** | `docs` in projects.json; anchored state; heading fallback in recall | §3.1 criteria on two real projects |
| **P3 Learning** | Nudge A/B; efficacy demotion; capture verdict | §3.3 criteria |
| **P4 Trim** | Kits confirm-or-fold (§3.4); resume prove-or-trim (§3.5) | Each has a shipped verdict with numbers; the losing path is deleted |

P1 must land before P2: anchors are judged by the real-query eval, not by feel.

## 6. Kill rules (unchanged from V4, restated)

Anything unused for a week is deleted. A change ships only with a same-batch control in
agentbench or compactbench, judged by cost, not tokens.

## 7. Owner decisions needed

| # | Question | Recommendation |
|---|---|---|
| **D5-1** | Anchor docs explicitly (`projects.json docs`) or auto-detect plan files? | Explicit. Auto-detect guesses wrong silently. |
| **D5-2** | Keep recall queries in local telemetry (scrubbed, never synced)? | Yes; they are the only way to judge recall. |
| **D5-3** | Delete capture proposals if none is accepted in two weeks? | Yes. |
| **D5-4** | Fold kits into procedure notes if the 12 + 12 confirmation fails? | Yes. |
| **D5-5** | Trim the post-compaction resume if long sessions show no benefit either? | Yes; the start card stays. |

**Answered 2026-09-28:** the owner accepted every recommendation (D5-1 to D5-5).
