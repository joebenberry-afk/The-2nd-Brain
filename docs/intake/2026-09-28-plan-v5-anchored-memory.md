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
tokens and appears once per session (nothing after compaction: §8 P4).

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

## 8. Status (2026-09-28)

| Phase | State | Evidence |
|---|---|---|
| P0 | running | a week of daily use from 2026-09-27; `v2-archive` push waits for the owner's go |
| P1 | **done** | recall rows keep the masked query and the ids answered (local); fix outcomes helped/missed from the next run of the same command, OMP and Claude Code hook (`74f4c3d`); `recall-real.jsonl` frozen from 34 logged agent queries; long-session compactbench |
| P2 | **done** | `brain project docs add/list`; `See: path#heading` rendered live in card and state; recall falls back to one plan-doc heading or the named doc's outline (`bf68c06`, `b176d1a`). Real-query eval: wrong 16 → 11 (IDF coverage) → 5 (a keyword list must be about the note's headline), right 9 throughout, 0 silent misses; V3 eval unchanged (`c91ef2c`). Wrong rate 15 %, target ≤ 10 % not yet met |
| P3 | **mostly done** | fix efficacy: a fix that helped under half of 4+ runs since its note changed is paused and listed in `brain review` (note untouched; `c91ef2c`). Nudge **rejected and deleted**: two-session learn pairs 6+6 (`v5-nudge`), +11.9 % tokens, +4.2 % cost; control agents wrote the note unprompted 6/6 and session B saw it 6/6 (`421beaa`). Capture verdict due 2026-10-12 (D5-3) |
| P4 | **done** | kits **folded**: 12+12 over two task shapes (`v5-kits`), to first pass +8.1 % tokens, −2.5 % calls, −5.4 % cost; two global procedure notes replace them (`1b152d6`). Post-compaction resume **removed**: long sessions (three compactions, goal changed midway) 7/7 with vs 6/6 without, OMP's summary kept goal B every time (`v5-long-1842`) |

Open: real-query wrong rate to ≤ 10 % on a set grown with two weeks of new logged queries (used as
held-out, since the 34 frozen ones shaped the rules); capture verdict on 2026-10-12.

### 8.1 Recall precision (2026-09-28, owner: "as close to 0% wrong as possible")

Labels were redone blind: three independent judges saw each logged query, what the agent did next,
and the top-10 candidates in id order (never the tool's answer); the majority label is ground
truth (`recall-real.jsonl`, 34 frozen; `recall-real-heldout.jsonl`, 20 logged after the freeze).
A wrong answer now counts any irrelevant note shown, including one beside a relevant note.
Word matching alone could not separate relevant from irrelevant hits (they overlap on every lexical
signal), so recall now checks its lexical answer with TypeSafe Jev and drops notes and plan-doc
headings below 0.75 (owner decision; fail open to the lexical answer; private notes never sent).

| Set | Lexical right / wrong / missed | Judged right / wrong / missed |
|---|---|---|
| Frozen 34 | 6 / 8 / 7 | 7 / **0** / 12 |
| Held-out 20 | 2 / 4 / 4 | 3 / **0** / 5 |
| V3 dev / held-out | 13/15, 7/8 | 13/15, 8/8 (gate lowered to 12/15 for D27 at 0.45) |

Live calls: ~300 ms (5 s timeout). The price is more silence: some useful notes score just
under 0.75 and are dropped. Next: keep logging real queries; re-label and re-measure held-out
monthly so 0 wrong is checked on queries the threshold never saw.

### 8.2 Judge robustness and call-time context (2026-09-28)

**Drift.** The same 54 real queries re-scored three more times: Jev moves about ±0.02 per pair
(mean |Δ| 0.016), enough to flip borderline notes. At 0.75 the reruns showed 1, 2 and 1 wrong
answers (the first recording, 0, was lucky). At **0.78** all four runs had 0 wrong; right answers
fall from 6–7 to 5–6 (frozen) and 2–3 to 2–3 (held-out); V3 dev 12/15 (D28 "migration" sits at
0.75–0.78). Threshold raised to 0.78; the eval now requires 0 wrong on every recorded run
(`recall-judge-reruns.json`).

**Agent context in the judge: rejected.** Hypothesis: misses happen because the judge sees only the
keyword query, while the labellers saw what the agent was doing. On the 40 queries with a logged
call-time intent (`i`) and user task, one batch: AUC query-only 0.904, + intent 0.900, + intent
and task 0.915. The differences are one case each way, inside run-to-run noise, and sending the
user's task text adds exposure for no measured gain. Not shipped.

**What limits recall now** is not the judge but coverage: of 13 frozen misses, most have their
relevant note scoring 0.4–0.7 on a keyword query. Next lever to test: ask agents (tool
description) for a one-sentence question instead of a keyword list, measured by agentbench.

Miss breakdown at 0.78 (first rerun): 18 labelled-relevant misses; 11 never reach the lexical
answer and 7 are shown but judged below 0.78. Of the 11, only one (H04, 0.84) would pass the judge
if the whole top-10 were judged; the rest score 0.14–0.74 on their keyword query. Widening the
shortlist therefore buys one answer; the query text itself is the ceiling.

### 8.3 Question-phrased recall queries: rejected (2026-09-28)

agentbench `recallq` (the fact needed is only in a note the start card does not show, among 8
decoys; the fixture cannot reveal it): `on` vs `on+question` (a tool description asking for one
plain-English question), 8 + 8 interleaved, label `v5-question`. Agents ignored the wording: 0% of
queries ended with "?" in either arm, often identical keyword lists. The needed note came back in
8/8 runs in both arms. Pass 4/8 vs 7/8 is agent judgement, not recall: every failure found "amber"
and then chose to block the deploy because the fixture's `npm test` fails. +20% tokens, +4% cost.
Rejected; the switch was removed, the `recallq` task kept.

Observed on the way: the first query in almost every run was the task itself ("Deploy this app to
staging"); recall answered with three decoys that passed the judge and not the needed note, which
the lexical top-3 had not reached, so agents needed a second recall. **Next lever when development
resumes:** judge a wider lexical shortlist (top 6-8) and show the three best by judge score;
measure with `recallq` (needed note on the first recall) and the real-query eval (0 wrong must hold
on every recorded run).

### 8.4 Bare-name recall: phrase floor (2026-09-30)

Live BasicUpscaler lookups by name ("Witcher 3", "Terraria") came back silent although notes held
the name: Jev scores a bare name against a note about it at 0.57-0.91, often under 0.78. Notes
using the word in another sense scored 0.12-0.48 (20 real short queries). A note holding the whole
query as a phrase (case and accents folded, word-bounded) is now kept at Jev ≥ 0.55
(`PHRASE_FLOOR`, brain/src/judge.ts); every other note still needs 0.78. Real-query eval: 0 wrong
on every recorded run, right unchanged; V3 dev 12 → 13/15 (D28 "Migration?" recovered). Known
miss: "Palworld" (0.37). The floor was set on 20 queries, so held-out rows must keep checking it.
