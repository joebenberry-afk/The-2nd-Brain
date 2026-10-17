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
injection, no second harness adapter beyond the Claude Code hook and MCP. The card stays ≤ 320 (§8.9)
tokens and appears once per session and again after each compaction (until 2026-10-15 only its
lean line came back, ~35 tokens: §8 P4 showed goal and next survive without the state; §8.11).

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

### 8.5 Borrowed from OKF: expiry, verifier, export (2026-10-04)

Owner asked for the best parts of Google's Open Knowledge Format v0.2 (markdown + YAML
frontmatter bundles; github.com/GoogleCloudPlatform/open-knowledge-format). OKF stays an export
format, not the canonical one: its data-catalog fields (attested computations, usage counts) have
no use here, and v0.2 is young. D4 gains three optional keys; nothing else changes.

- **`stale_after`** (OKF §5.5): a date (start of day, UTC) or ISO instant with an offset. Past
  it, a note is stale everywhere: recall sorts it last and marks `(stale since <date>)`, the card
  applies the stale-evidence −3, and it is never pushed as a known fix (an author-stated expiry,
  unlike missing evidence, is not a guess). Set with `brain note --stale-after`; not a
  `brain_note` parameter: tried as agentbench arm `v5-staleafter` (learn, 6 + 6, same batch):
  +18 % A+B tokens, +12 % cost, landed 4 → 3, and no agent ever set it (0/6). Arm deleted.
- **`tested_by` / `tested_at`** (OKF `verified`, §5.2–5.3): who verified a tested note and when:
  `agent` (`brain_note`/`brain note --tested`), `capture` (an accepted fail→pass proposal),
  `owner` (`brain tested <id>`, which re-stamps), `convert` (V3 grade). The first verifier sticks
  on re-notes. Shown on explicit id reads; gating and ranking unchanged. Older tested notes stay
  unrecorded.
- **`brain export <dir>`**: public notes as an OKF 0.2 bundle (concept per note, `index.md` per
  folder, `okf_version` at the root). `kind` → `type`, `source` → `generated.by`, `tested_by` →
  `verified.by` (`human:owner` only for `owner`), `retired` → `status: deprecated` plus lineage
  links, file evidence → a "<path> in the <project> checkout" source. Private notes never
  exported; the target must be empty or an earlier export, outside the home except `state/`.
  Live home (2026-10-04): 319 notes, all frontmatter valid YAML.

### 8.6 Closing the loops (2026-10-04)

Evidence (14 days): 388 recalls since 09-28, 216 silent; 180 new agent notes, 0 with evidence;
0 capture notes ever; 133 basicupscaler notes in a week; top unmatched errors 74 × Claude Code
heredoc quoting, 48 × `ls: cannot access`, 20 × OMP `find` timeouts. Owner: "do all of them".

- **Unmatched errors in `brain review`**: the top 5 (14 days, this project + global) with the
  latest tool, the next successful step in that session, a literal `--error` pattern (the
  leading text when ≥ 12 chars, so a fix cannot fire on a generic tail like "No such file or
  directory") and `brain dismiss "<signature>"` (hashes synced in `rejected.json`). Two global
  gotchas written from the logs, untested until the owner confirms: n-f382485a63 (heredoc
  quoting, `host: claude-code`), n-5ec31fc4ff (`find` timeouts, `host: omp`).
- **Automatic evidence**: a new note without `--evidence` gets up to 3 existing repo files it
  names (path, or basename of a file edited this session: OMP in memory, Claude Code from the
  event log). Stale-evidence detection now has inputs.
- **`brain tidy`**: read-only report of duplicate and contradictory pairs (Jev, two `noul`
  questions per pair, batches of 20, fail open; lexical similars without a key) and notes unused
  for 30 days. A new note's reply names a contradicted or duplicated note (top 3 similar,
  judged); never for subagents or private notes.
- **Note usage**: card rows now log the ids shown; `noteUsage` counts recalled / opened / carded /
  fired; `brain stats` prints `notes used`. Live: 85 of 293 active notes used in 14 days.
  Card ranking unchanged (needs a control).
- **Doc recall**: registered docs are searched by whole section, the judge sees the best
  paragraph; `brain project docs suggest` ranks checkout Markdown by silent queries it would
  answer and prints `brain project docs add` commands (D5-1: never auto-registers). Frozen
  real-query eval unchanged (right 7/34, wrong 0 judged on every run): the gain needs docs
  registered. `--project <id>` now resolves that project's declared checkout from another repo.

### 8.7 Time sinks from the transcripts (2026-10-04)

Mined 392 OMP and 1,693 Claude Code transcripts (agent://omp-sinks, agent://cc-sinks) and ~20
external memory systems (agent://ext-survey). Built:

- **Child card** (≤ 200 tokens, both hosts; Claude Code via SubagentStart): parent Watch out,
  recurring fixes, `brief`-tagged standing rules (≤ 80 tokens), the parent's files in play, a
  registered-doc outline plus the best-matching section. `brief` is a non-scoping tag. The parent
  card says `children get: <n> rules`. **Benchmarked 2026-10-05** (agentbench `delegate`, `on` vs
  `on+nochild`, two batches 6+6, 12/12 pass both arms, every run 3 sessions; nochild children
  verified card-less): with the card −9.2 % tokens and −2.1 turns in both batches, but cost
  +9 % then 0 %, pooled +4.9 % ($0.694 vs $0.662, sd ≈ $0.11; inside noise). No cost win; owner
  kept it (2026-10-05): the token and turn gain held in both batches, the cost gap is noise.
- **Owner rules captured on first statement** (UserPromptSubmit / OMP input, main sessions,
  deterministic cues) as `brain review` proposals; Claude Code auto-memory listed read-only for
  `brain accept` (35 live entries; never written).
- **Content trust**: `evidence_sha` (file hashes, `(evidence changed)`), `tested_sha` (an edited
  fix stops counting as tested); absent hashes = legacy trusted. Identifier/suffix aliases rescue
  only corpus-absent terms; docs keep exact-term matching. Eval unchanged, 9 ms/query.
- **Rollover hint** at 250k context (`projects.json` `rollover`, 0 = off), once per crossing,
  never for subagents. compactbench `v5-rollover` 4 + 4: −47.5 % cost per finished task, goal kept
  4/4 both arms; the trial scripted compliance with the hint.

### 8.8 Token-efficiency pass (2026-10-05)

- **Rollover default 250k → 150k.** compactbench `--threshold` (seed sized to land just past it):
  `v5-rollover-150k` 4+4 at 157k seeded, 16/16 and goal 4/4 per arm, $0.928 → $0.525 per
  finished task (−43.4 %); the handoff turn ($0.32) pays back within one task. Real main
  sessions, 14 days: 45 of 68 crossed 150k, 34 crossed 250k, and $910 of $1,542 main spend came
  after the 150k crossing. First live hint 2026-10-06 (OMP main session, 152k): the agent had
  already saved state with a See: line and relayed the hint to the owner in its reply.
- **Silent-recall chains: no change.** Of 86 recalls that followed a silent one within 3 min,
  60 were a different topic, 9 a rephrasing, 17 the identical query: about one wasted turn a
  day, below what agentbench resolves.
- **Tool-schema audit** in `brain stats` (OMP snapshot of top-level schemas vs event-log calls).
  First live reading: 15 top-level tools ≈ 3.7k tokens, none uncalled in 14 days. OMP 18.6
  mounts MCP tools under `xd://`, so the old "11 unused jev schemas ≈ 4.8k" no longer applies.
- **Notes:** three global gotchas confirmed tested (112 failures in 14 days); one ESM duplicate
  retired. The V3 `mem-*` notes `brain tidy` lists as unused stay: the frozen eval expects them.
- **Recall batched with the first search (2026-10-06).** Card footer, `brain_recall` description
  and the AGENTS.md block now say a recall alone costs a turn. Recall hit rate was 17 % (5 of 6
  silent in 7 days). agentbench `speed-pass-recall-batching`, same batch, 3 reps, control arm
  `on+oldrecall` (removed after the run): rename/fix/find 6.8 vs 7.1 turns, though the control
  used 6 % fewer tokens and 13 % less cost; `find` 3 turns in 3/3 vs 4 in 3/3; recallq 8.3 vs 10.3
  turns, −20 % tokens. Kept for the turn count; tokens are mixed and n = 3 is not robust.
- **`brain state` warns on a file-less section** ("plan §8.8" with no path or See: line): that
  state cost the next session two turns searching the wrong plan.
- **Error fixes:** `n-8145fedb93` (BasicUpscaler git root is the inner folder), `n-64be719a88`
  (scratch .mts via unquoted heredoc gets corrupted), global `n-d118aff0ec` (JS eval 30 s kill;
  owner-tested). `triggerUncaughtException(` dismissed: any node crash.
- **Recall by section number (2026-10-06).** `recall "… plan 8.8"` was silent because docs match
  words only. A query naming `§8.8` / `section 6` / a bare two-part `8.8` now matches headings
  starting with that number and beats word overlap; several docs: remaining words, then path
  words (`v5`, `plan`) pick. `26.7.0`, `1.5x`, `v1.5` never match. Smoke: the original query now
  returns plan-v5 `8.8 Token-efficiency pass (line 329)`; `§3.2 rules` returns plan-v4 `3.2 Rules`.
- **Closest path on a missing-path failure (2026-10-06)** (`brain/src/paths.ts`, OMP tool_result
  and Claude Code PostToolUseFailure, after a matching fix note, ≤ 80 tokens, telemetry id
  `pathhint`). 132 read/edit/grep/glob "not found" failures in 14 days took a median 2 more calls
  to recover. Up to three paths with the same name, extension-swapped stem or a 1–2-letter typo,
  at most three folders off the missing path's; else the deepest existing folder's entries.
  Replay on those 132: a hint for 67, e.g. `collector/src/SparkingZeroAdapter.cpp` →
  `runtime/sparking_zero/SparkingZeroAdapter.cpp`; ~0.2 s when the file list is not cached (60 s
  cache in OMP). Live verdict: `fix outcomes: pathhint` in `brain stats`.
- **`docs/intake/2026-09-27-plan-v4-agent-experience.md` registered** (22 recall queries, 9 full
  reads in 14 days unregistered).
- **Asks by week in `brain stats` (2026-10-06)** (`brain/src/asks.ts`): per owner prompt in a main
  session, model turns until the next prompt and wall time, weekly medians from the hosts' own
  files (OMP `~/.omp/agent/sessions/<dir>/*.jsonl`, Claude Code `~/.claude/projects/<dir>/*.jsonl`;
  subagent folders, `isSidechain`, SDK runs, injected and task-notification messages left out; the
  project is the one `resolveProject` gives the session's cwd, `--all` for every project). The
  baseline exists retrospectively, nothing new is logged; ≥ 4 UTC weeks, `--days` widens it (max
  12); stats +0.6 s (2.6 → 3.2 s). First readings, second-brain, turns median (p75) · wall median:
  w09-14 12 (34) · 3.0 min; w09-21 11.5 (38) · 2.8 min; w09-28 5.5 (17) · 0.9 min; w10-05 (to
  date, 14 asks) 11 (33) · 1.7 min. Judge a change by weeks after it against the weeks before.
  Scan cache (2026-10-17, `brain/src/asks.ts`, `state/asks-cache.json`, derived, never committed): the cwd
  and parsed asks of each transcript are kept by path with its size/mtime/ctime (no transcript text;
  deleted files and anything past 12 weeks dropped; a project's files parsed only once a scan accepts
  them), so only new or changed transcripts are read; which project a cwd belongs to is asked afresh
  on every run, never stored. Measured on this machine (4 weeks, second-brain, 447 transcripts, 91 cwds, 345
  asks, identical output): 1369 ms uncached → 703 ms first cached run → 158 ms warm, of which ~127 ms
  is `resolveProject`.
- **agentbench mixes recallq with other tasks (2026-10-06)** (`brain/scripts/agentbench.ts`):
  `planPasses` runs the other tasks as one pass and recallq (Brain-enabled conditions only) as a
  second, same invocation and label, one summary each; recallq never shares a home. Checked with
  `--plan` (no model calls): `--conditions off,on,on+x --tasks rename,fix,find,recallq` → passes
  `[rename,fix,find · off,on,on+x]` and `[recallq · on,on+x]`.
- **Asks end at the first idle gap (2026-10-06)** (`brain/src/asks.ts`): an ask's span stops at the
  last assistant entry before a >5 min gap between consecutive assistant/tool-result entries; later
  turns (background wake-ups) count for nothing. Smoke `stats --days 30` wall median before → after:
  w09-07 41.6 → 7.9 min (turns 30 → 9.5); w09-14 3.0 → 2.5; w09-21 2.8 → 2.0; w09-28 0.9 → 0.9;
  w10-05 1.2 → 1.1. Earlier weeks' readings above used the old definition.
- **Eval-timeout hint before the kill (2026-10-06)** (`slowEvalCell`, OMP tool_result, id `evaltimeout`,
  once per session): a JS eval with `tool.task/wait/find/web_search`, an http(s) `tool.read`,
  `agent(`/`workpool(` or `tool.bash` timeout > 30 and no eval `timeout` gets one line. Replay, 14
  days (events hold no language/timeout, so every cell counts as JS, none as timed): 692 of 5,386
  eval cells flagged; 31 of 40 force-kills flagged, 38 of 40 after an earlier flagged cell in-session.
- **Silent recalls mined in `brain review` (2026-10-06)** (`brain/src/silent.ts`): for each silent recall
  in 14 days, the next ≤10 events/10 min of its session name the file read (selectors/URLs/AGENTS.md/
  CLAUDE.md/registered docs dropped); one file answering ≥2 queries in ≥2 sessions, or a query silent ≥2×,
  prints ≤4 lines `→ brain project docs add <md>` or `→ brain note "<what answered it>"`. Smoke (this
  project, 14 examined): 2 queries, 2 sessions, then read `brain/src/notes.ts` → `brain note`; `--all`: 204 examined.

### 8.9 Lean card and a self-closing fix loop (2026-10-14)

Owner: retrieve quickly, work optimally, lean card; no interest in reviewing what the Brain holds.

- **Lean card.** Only lines the agent can act on: `N proposals waiting` left the card (`brain review`
  still lists them); the when-to-act footer is dropped where the `brain_*` tools are resident (OMP main
  and child), since their descriptions carry it; attachment placeholders (`[Image #1, …]`) are no
  longer an auto "last ask"; main budget 400 → 320. Live home, 20 projects: OMP main −19 %, CLI main
  −17 %, OMP child −8 % tokens; no project lost its card.
- **Tested capture pairs become notes** without `brain review` (project scope, specific error pattern — tightened in §8.10;
  rejected, dismissed or covered pairs skipped; the paused-fix rule unchanged). Live events: 2
  proposals, 0 tested, so no new fixes today. A "setup command, then identical rerun" pairing was
  measured first: 0 strict candidates in 563 failed commands, so it was not built.
- **CLI startup:** Node compile cache in `bin/brain.mjs`: recall 343 → 296 ms, fix 325 → 278 ms, card
  357 → 341 ms (median of 7, judge off). Loading 472 note files (~180 ms) is now the largest CLI cost.
- **Measured, left alone:** judged recall is bound by the Jev round trip (median 460–840 ms vs 80–190 ms
  unjudged); exact repeat queries were 4.8 % of a week's recalls, too few for a persistent verdict
  cache; the Tora skip floor is still `not ready` (3 lost).

### 8.10 Foundation hardening pass (2026-10-15)

Five read-only audits (agent://Audit-CardState, -Recall, -NotesModel, -Learning, -Hosts) reported 31
findings with evidence (29 distinct); six owners fixed 28 of them with regression tests
(agent://HostLatency, FixOutcomes, CaptureQuality, NotesModel, CardState, RecallGate) and one was
declined (below). Full gate after integration: 943 tests, recall eval gates held.

- **Never block the host.** The missing-path hint walked whole trees synchronously inside OMP's
  `tool_result` (one result held 24.7 s; 33 of 145 hint rows over 300 ms): listing now shares a 150 ms
  budget and never walks a drive, home or temp root. Claude Code hooks: the shim no longer spawns
  `node --version` (−45 ms per hook), `captureUserRules` checks for a rule cue before loading notes
  (−50 ms per prompt), the capture scan left SessionStart (~820 → ~410 ms on a 949-log home), and the
  failure hook now covers Read/Grep/Glob/LS/NotebookEdit, which the path hint was built for.
- **Fix outcomes were mis-scored.** Siblings in the same parallel batch and calls nested in one eval
  cell scored a fix before the model saw it: 80 of 429 outcomes in 7 days (47 of 60 "missed"), which
  paused the working global `Path …:N not found` fix (true record 3/0). Outcomes now count only after
  the model saw the fix (OMP `context` event; Claude Code transcript message order), old rows within
  1 s of their fire are discounted, and `evaltimeout`/`rawhint` (19 % of fires, never scorable) are
  judged by the next JS cell their detector checks. Attributable 7-day record: 336 helped / 13 missed.
- **Capture.** Unreviewed notes need a whole diagnostic pattern (a cut prefix would have fired on
  every missing-module error), get proposal-derived ids (overlapping scans wrote duplicates), honour
  `brain dismiss` of printed signatures, and never come from OMP isolated worktrees. Signatures no
  longer fall back to a stdout line (3 of the top 5 unmatched errors were a JSON line, a banner and a
  usage text). Owner-rule capture drops pasted markdown, ≥3-cue messages, narrative and task
  requests: 8 of the 15 pending rule proposals were such noise.
- **Isolated subagents** (`~/.omp/wt/<id>/m`, 61 sessions a week) resolved to a phantom project `m`
  with no notes; they now work for the live parent's project.
- **Notes and secrets.** V3 import scrubs; a regex error pattern broken by masking is refused and
  `brain check` lists invalid ones; headline dedupe compares masked headlines and tagged globals;
  `brain tested` outside the checkout keeps evidence hashes; `brain sync` refuses a detached HEAD or a
  rebase/merge/bisect in progress (it had committed notes that vanished on checkout); the scrubber
  masks eight more token formats and keeps env references, booleans and settings readable (a
  reference followed by a literal stays masked).
- **Card and state.** Inline `See:` anchors (9 of 22 real anchors) are moved onto their own line so they
  render and are checked; the Brain's own notes/work commits no longer mark its plan stale; stale
  notes rank behind live ones under a prompt match.
- **Recall gate.** The eval never graded plan-doc answers (15 counted as silence). Four docs are frozen,
  30 doc sections carry majority-of-three blind labels with four recorded runs, and unexpected doc
  answers count wrong: frozen right 7–8, held-out right 4–5, judged wrong 0 on every run (two lexical
  held-out doc headings now count as the wrong answers they were). A conditional doc fallback joins the
  notes' judge request (44 → 39 requests on the 54-query replay). The narrow headline-gate rescue (+1
  held-out case) was not shipped: it would add a judge call to silent recalls.
- **Judge prompt: rejected (agent://JudgePrompt).** Both remaining miss kinds end at the judge
  (labelled-right notes score 0.34–0.75 under the 0.78 bar). Three rewordings of the relevance
  question were screened live, two runs each over all 92 candidates the eval sends (552 questions):
  "would it help the agent act" and "direct answer" lost right answers and let H17 through (wrong 1
  per run); "lookup" recovered R01, R02 and R17 but admitted four wrong answers per run (R10, R15,
  H07, H17). None met wrong 0 with ≥ 2 more right, so the prompt, recordings and thresholds stay:
  at this judge, recall is on its precision frontier. Each variant also cost 44–79 more tokens per
  question.
- **Measured, left alone:** a persistent parsed-note cache (CLI and hooks are 13 of 348 brain tool
  calls in 30 days; OMP holds notes in process); a custom judge connection pool (no reliable gain
  between recalls minutes apart). On a copy of the live home `brain stats` fell ~3.2 → 2.4 s and
  `brain review` ~3.1 → 1.9 s: the unmatched-error scan fell 1.84 → 1.19 s (successes are described
  only when a failure needs them); the rest is asks-by-week reading host session files, owner-facing
  and off every agent path. `brain stats` fix-outcome lines now apply the pause rule's 1 s artifact
  discount in every build view (7 days: edit-anchor fix 145/8 → 130/3, path hint 91/23 → 73/2).
- **Test hygiene.** Each full vitest run left ~1,000 `brain-*` folders in the OS temp directory
  (26,488 folders by 2026-10-15). The suite now points `TMPDIR`/`TEMP`/`TMP` at one per-run folder
  that a global teardown removes: a full run leaves zero folders. The old folders were deleted at
  the owner's request; Git Bash `du` had estimated 17.4 GB, but deleting them freed only ~10 MB
  (almost all were tiny files that NTFS keeps inside the MFT).

### 8.11 The card after compaction (owner decision, 2026-10-15)

Owner: re-send the full card after every compaction. §8 P4 measured goal and next surviving OMP's
summary in every run, so the benefit claimed here is the rest of the card the summary drops:
Known-here notes, `Often hit lately` fixes and the rendered `See:` plan section. Unmeasured;
cost ≤ 320 tokens per compaction (live home: OMP main cards 121–319 tokens, mean ~232).

- **OMP:** `session_compact` marks the card due. The first tool result after it carries the card
  (appended after the result's own text, after any known fix); a compaction that no tool result
  follows hands it to the next prompt, ranked by that prompt. Not `sendMessage`: OMP's source shows
  a `nextTurn` message waits for the next user prompt, and an `aside` queued after a run's last step
  makes OMP start a turn to deliver it (`#resumeStrandedIrcAsides`) — that would continue host work
  (V4 §3.2 rule 4). A card inside a tool result is no `brain.card` entry, so a process restarted
  before the next compaction cards once more.
- **Claude Code:** `SessionStart` with source `compact` returns the card; `resume` stays silent.
- Nothing to say still returns the lean line, as before.

### 8.12 Obsidian MCP, measured head-to-head (2026-10-15)

Test vault `Documents/Obsidian Brain Test`: a copy of the 167 notes the real-query labels were made on
(Obsidian 1.14.4), with MCP Connector 3.0.2 (istefox, 64 tools, on-device embeddings) and Local REST
API 5.4.0 (built-in MCP, 20 tools), release files checked against GitHub's SHA-256 digests. The same
54 labelled queries (34 frozen + 20 held-out), searches limited to the project and global folders.

| | Brain judged | Brain lexical | Obsidian semantic, top 1 | Obsidian semantic, top 3 | Obsidian simple search |
|---|---|---|---|---|---|
| Labelled note found (27 answerable) | 8 | 16 | 16 | 20 | 0 |
| Answers showing an irrelevant note (of 54) | 0 | 14 | 38 | 54 | 0 |

- Obsidian's simple search (both servers) is literal: no result for any of the 54 questions.
- Semantic search never abstains. A score threshold tuned on this same set reaches 0 wrong only at 2
  right (0.45: 8 right, 5 wrong). Brain judged also answered 4 cases from plan docs the vault lacked.
- Cost: tool definitions 65 KB for 64 tools (~16k tokens) and 32 KB for 20 tools (~8k), against the
  Brain's 1.7 KB for 3; ~458 tokens per semantic answer (3 results with excerpts) against ~78 for a
  judged Brain answer; building the embedding index took ~10 min for 167 notes, reporting 0 % until
  done; searches then take 10 ms (median).
- Lesson: embeddings put the labelled note in the top 3 for 20 of 27 answerable questions, where the
  Brain's judged answer finds 8; the judge is what keeps answers free of wrong notes. Semantic
  candidates in front of the judge is the lever: Tora does this, but adds at most 2 candidates and
  only while a Tora session runs. Not built here.

### 8.13 Tora where Obsidian was ahead, measured on real traffic (2026-10-15)

Owner: improve the Brain where it lacks against Obsidian MCP, and Tora's part in it; drop what is
worse. The labelled sets proved too small to decide: a candidate rule with 0 wrong on all four recorded
runs there gave 11 wrong in 58 new answers on real traffic. Every rule was therefore replayed on the
566 distinct queries logged 1–15 Oct, with a Jev verdict for every candidate and three blind judges
(majority, §8.1: query, project and up to 8 candidates in id order, never the answer) for every
answer a rule changed. For scale, today's judged lexical answers had 78 of 81 shown notes relevant
(60 sampled answers).

| Notes Tora added to real answers (566 queries) | right | wrong |
|---|---|---|
| Before: Tora's best two the lexical search missed, at Tora's cut 0.7605 | 22 | 6 |
| BM25's top 3 that the lexical gate left out, at cosine ≥ 0.70 | 26 | 5 |
| **Built:** the same at cosine ≥ 0.74 | **15** | **0** |

- **Recall.** Tora now re-checks only notes BM25 ranked in its top three but the lexical gate dropped;
  the best two at 0.74 or more join the same Jev request (0.78 unchanged). Notes only Tora finds were
  right 19 of 31 when Jev kept them, and no Jev bar separated them (wrong ones reached 0.88), so they
  are never sent. The 0.74 floor was fitted on the first half of the queries (highest wrong 0.736) and
  held 6 of 6 on the second; under 0.70 Jev kept 1 of 150 sampled candidates. Dropped after measuring:
  Tora's best missed note at 0.70, and a lower Jev bar (0.65) when Tora's and BM25's first notes agree
  (together 47 right, 11 wrong). Frozen eval, cosines frozen in `test/fixtures/recall-tora.json`:
  judged held-out 4–5 → 5–6 right (H04), frozen 7–8, V3 13/15 and 8/8, 0 wrong on every run; the
  held-out gate rises to 5.
- **Start card (OMP).** 45 real first prompts, the union of each ranker's top five labelled blind:
  Tora's cosine ranking had precision@3 0.36 against BM25's 0.18 (prompts with 3+ content words 0.45
  against 0.20; a relevant note in the top three for 23 against 13 of 32); vague prompts tied. Built
  for such prompts with a 0.3 s wait, BM25 otherwise; the card shows as many notes as before.
- **Write-time hint.** On the 10 notes that replaced an older one Jev's pair judge flags 5 pairs; the
  lexical shortlist held 3, Tora's three nearest added a contradiction (0.91). 40 ordinary writes: 116
  Tora-only pairs, no hint. Built for `brain note`; `brain tidy` is unchanged.
- **Availability.** 74 of 246 recalls (11–15 Oct) carried Tora data. Of the 164 without it after Tora's
  first answer, 120 were silent recalls, which the old code logged without Tora's data even when Tora
  had answered, and 41 had waited out the 0.8 s timeout: a session's first call loads llama-server
  (1.1–1.3 s). Tora now loads at session start (Tora IDEAS TS-09), and a query over its 512-token
  context, an HTTP 500 before, is cut to fit with llama-server's own tokenizer (TM-22).
- **Dropped:** the shadow skip floor (`BRAIN_TORA_SKIP`, the `skip floor` verdict in `brain stats`).
  At 0.70 it would skip 24% of judged recalls and lose 2 Jev-kept answers; at 0.66 it loses none but
  skips 8%.
- Where Obsidian still leads: raw coverage. Its semantic top three held the labelled note for 20 of
  27 questions, but candidates only embeddings find are right 61% of the time even after Jev, so the
  Brain keeps them out. Owner follow-up, embedding-only search behind a stricter check: two stricter
  Jev questions ("the same specific thing?", "gives what the query seeks?") did not separate them
  (wrong notes reached 0.82; any zero-wrong bar kept 3 or fewer of 19 right), and on silent recalls
  Tora's nearest note passing Jev was right 7 of 12. Not built: under 1% more answers, below the
  lexical answers' precision. Tora's ledger (TI-11 to TI-16) holds the per-rule numbers.
- **Local judge in place of Jev (owner: cost; built, owner's choice).** Tora runs Qwen3-Reranker-0.6B
  (0.64 GB) beside its embedder and judges recall at `/judge`; Jev is called only when Tora gives no
  verdict and a key is set (`BRAIN_JUDGE=tora`: never). Its scores are mapped onto Jev's scale (0.999
  → 0.78, 0.5 → the phrase floor 0.55). On the 276 blind-labelled October candidates it keeps 116
  right / 3 wrong against Jev's 113 / 5; on the frozen hand-labelled eval it is weaker (real 2 right /
  2 wrong against 7-8 / 0, held-out 6 / 1 against 5-6 / 0, V3 dev 10/15 against 13): its mistakes
  are on-topic notes that do not answer, and no bar fixes both sets. The owner chose it over Jev's
  quality on that set; the eval gates Tora's GPU and CPU recordings at what they measured, listing its
  known wrong answers, and Jev's runs keep 0 wrong. Qwen3-Reranker-4B, bge-reranker-v2-m3 and a
  Qwen3-4B-Instruct yes/no judge did worse. `brain stats` counts judged recalls by judge (Tora TJ-02).
- **Local recall candidate cutover (RECALL-02, 2026-10-17).** For the local Tora judge only, BM25's
  top-three visible, public, non-retired candidates gated out lexically now join `/judge` directly,
  capped at two; no `/score` prefilter. The 0.999 reranker bar, privacy and scope stay unchanged.
  The Jev path retains the cosine ≥0.74 prefilter described above. A temp-home replay of 788
  deduplicated real queries from 14 days changed eight answers: eight notes added, none removed.
  A blind TypeSafe Jev judge rated all eight relevant (p=0.77–0.97). `/score` requests: 487 → 0;
  `/judge`: +0.26/query. Observed latency p50 77 → 88 ms, p95 194 → 201 ms; both arms shared the
  old failure-cooldown state, so this does not isolate latency impact. Caller-budget exhaustion
  no longer cools down a healthy server; genuine full-budget timeouts and server failures still do.
