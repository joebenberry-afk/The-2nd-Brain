---
date: 2026-09-27
type: plan
authority: owner-approved
status: accepted 2026-09-27 ("I support all your decisions"); P0–P5 in progress
scope: v4-overhaul
supersedes: 2026-09-24-plan-v3-agent-native-redesign.md (direction), all earlier plans (history)
superseded-by: none
promoted:
---

# Second Brain V4 — the agent-experience overhaul

## 0. The one-paragraph version

Second Brain becomes a small TypeScript library with two faces: an **Oh My Pi extension** that runs
it in-process, and a **`brain` CLI** for any other shell or harness. It stores plain Markdown files
in a git repo. It does exactly five things an agent can feel: a **start card** at session start,
**continuity** across compaction (the agent's own working state survives and comes back), **recall**
and **note** in one call each, **one known fix** when a tool fails, and **kits** — proven paths from
earlier projects that get a new MVP up with the least exploration. Everything that does not show up
in a session is deleted: no grades, no promotion ceremony, no constitution, no ledgers, no
qualification campaigns, no SQLite, no Python, no migrations.

## 1. Diagnosis — where it went wrong

| What the repo optimised for | What an agent actually feels |
|---|---|
| Provability: constitution, sealed approvals, ledger chains, evidence manifests, "authority laundering" rules, qualification campaigns (116 MB of `outputs/`) | Nothing. None of it changes a single token an agent sees. |
| Vocabulary: candidate → current, promote, grade (claimed vs effective), conflict, supersession kinds, doctor | Friction: `brain add "…" --type gotcha --evidence …` then `brain promote --reason …` before it is even pushed. The agent writes nothing. |
| 68 Python modules (54k lines), 28 migrations, a 22-module OMP extension (2.7k lines), five harness adapters | A venv, `PYTHONHOME` breakage, process spawns per hook, four adapters nobody uses. |
| V3 (4.7k lines) fixed the *per-prompt noise* and the *import graph*, but kept the governance vocabulary | The real gap stayed open: after compaction the agent gets the **project brief** back, not **what it was doing**. Working state is still lost. |

The corpus itself is the tell: **113 of 120 records are `fact`**, 95 are still `candidate`. The
machinery for grades and promotion has almost nothing to grade. Meanwhile the moment that hurts
most — compaction mid-task — has no record type at all.

## 2. What "good" feels like (the design target)

Every feature below is defined as an agent moment with a token budget. If a feature has no
moment, it is not built.

| Moment | The agent gets | Budget |
|---|---|---|
| **Session start** | One *card*: what this project is (3 lines), where we left off (goal · done · next · watch out), the 5 most relevant truths, pending proposals count, matching kits | ≤ 400 tokens |
| **Working** | `brain_note("…")` and `brain_recall("…")`, one argument each. `brain_state("…")` to rewrite where-we-are. No output unless asked. | recall ≤ 3 lines; writes return one line |
| **Compaction** | Nothing lost that matters: the working state (agent-written, auto-completed with files touched and the last failing command) is snapshotted before compaction and re-injected right after | ≤ 150 tokens re-injected |
| **Tool failure** | One known fix if a *tested* note matches the error; otherwise nothing | ≤ 80 tokens |
| **New project / MVP** | A *kit*: stack decision with the why, scaffold commands, gotchas, "MVP done" checklist — from projects that already did it | one file, ≤ 600 tokens |
| **Ordinary prompt** | Nothing | 0 |

Two numbers we hold ourselves to on the owner's machine, in OMP, measured not argued:
1. **Continuity:** after a forced compaction mid-task, the agent states goal and next step
   correctly without re-reading files — 10 of 10 scripted runs.
2. **Neutrality + value:** on the slim task suite, tasks that need memory cost fewer tokens and tool
   calls than native; tasks that do not need it cost the same (±2 %).

> **Assumption A1 ("ponytail").** I read *"act like ponytail in which we could design MVPs for
> projects in least amount of tokens"* as: a fast, reusable path from idea to running MVP. That is
> the **kits** feature (§4.5). If ponytail is a specific tool or pattern you have in mind, name it
> and §4.5 changes; nothing else in the plan depends on it.

## 3. Architecture

```text
~/.omp/agent/extensions/second-brain/   (thin: hooks + 3 tools, imports the library)
                       │ in-process, 0 spawn
                       ▼
             brain/  (TypeScript library, Node built-ins only)
               ├─ store    read/write Markdown notes, working state, kits
               ├─ search   in-memory BM25 over title · tags · body (corpus ≈ 150 KB → < 5 ms)
               ├─ card     start card / resume card, hard budgets
               ├─ capture  failed → fixed pairs → proposals; error → known fix
               └─ sync     git add/commit/pull --rebase/push of the Brain home
                       ▲
             brain CLI (same functions; any shell, any harness; Claude Code hook = 40 lines)

Brain home (a git repo)
  notes/<project>/*.md      durable notes, one per file          synced
  notes/global/*.md         cross-project notes and gotchas      synced
  kits/<name>/SKILL.md      MVP kits, Agent-Skills format        synced
  state/<project>/working.md  goal · done · next · watch out      synced (tiny)
  state/events/*.jsonl      tool-result log for capture          local only
  projects.toml             id → paths / git remote / tags       synced
```

### 3.1 Decisions (and what they kill)

| # | Decision | Why | Kills |
|---|---|---|---|
| **D1** | **TypeScript, drop Python** | OMP is TypeScript: the extension calls the library in-process — no spawn, no venv, no `PYTHONHOME`. One language, one test runner. Harness independence is kept by the `brain` CLI (Node is already required by OMP). | 54k lines of Python, the venv, `bootstrap.ps1`, `brainctl.cmd`, pyright/ruff/pytest |
| **D2** | **No database** | 120–2 000 notes is ≈ 0.15–3 MB. Load all and score in memory in single-digit ms. No index to rebuild, no lock, no corruption, no `node:sqlite` availability question. Re-evaluate only above ~5 000 notes (measured, not assumed). | SQLite, FTS5, 28 migrations, `brain index`, `brain views`, the derived-views problem class |
| **D3** | **Three resident tools in OMP** (`brain_recall`, `brain_note`, `brain_state`) | V3 refused resident schemas to save tokens per turn. With prompt caching the schema (~250 tokens total) is paid once per context, while a bash round-trip to `brain q` costs more *per call* and is easy for the agent to skip. One-argument tools get used; CLIs get forgotten. Configurable off for hook-only mode. | the "discovery line in AGENTS.md" workaround |
| **D4** | **Notes, not records.** Frontmatter: `id, kind, project|global, tags, at, source, tested?, evidence?, replaces?, retired?` | Everything an agent or the capture path can fill in one call. `tested` gates what gets pushed on errors; `evidence` (optional paths) gates staleness; `replaces` keeps history. | status ladder, grades, promote, conflict, supersession kinds, doctor's integrity suite |
| **D5** | **Working state is a first-class file** the agent owns | The compaction gap. The harness's summary is lossy and not ours; `working.md` is deterministic, budgeted and re-injected. Also the resume card next session and the cross-machine handoff. | handoff envelopes, capsules, ledgers, active-state mirrors |
| **D6** | **Kits are Agent Skills** (`SKILL.md`) | Loadable natively by OMP and Claude Code; no new format; cross-project by nature. Drafted from a project's notes by `brain kit new`, finished by hand. | the skills lifecycle (candidate/shadow/staged/active/quarantine), skill evals, skillforge |
| **D7** | **Silence and budgets are code, not policy** | Every push path truncates to its budget and refuses to add on ordinary prompts. Telemetry line per session: tokens injected, brain tool calls, ms. | per-prompt autoinject, injection slots, recall gates |
| **D8** | **OMP is the host in focus; independence through the CLI**, not through adapters | One extension, one CLI, one optional 40-line Claude Code hook. | Antigravity, Hermes, Codex adapters, the legacy Claude Code adapter |

### 3.2 Rules (binding for V4 work)

1. A feature exists only if it has a moment in §2 and shows up in telemetry as used within a
   week of daily use. Otherwise it is deleted, not deprecated.
2. Writes take one argument. Anything that needs a flag to be useful is designed wrong.
3. Budgets are enforced in code (truncate, then refuse), never in a document.
4. The Brain never blocks, vetoes, steers or continues host work. It adds context or nothing.
5. Files are the truth. Anything derived is rebuilt from files on start; nothing derived is
   committed.
6. Node built-ins only in the library and the extension. No dependency is added without a
   measured need.
7. Nothing the Brain stores grants permission or authority; every injected line is advisory.
8. Private notes (`notes/**/private/`) never leave the machine; the sync path excludes them by
   pathspec, not by convention.

## 4. Features

### 4.1 Start card (`brain card`, `before_agent_start`)

Assembled from: project summary (first 3 lines of `notes/<project>/README.md` or projects.toml
description) · `state/<project>/working.md` · top-5 notes by a fixed ranking (tested gotchas for
this project, then recent decisions, then facts touched in the last 30 days) · `N proposals
pending` · `kits: a, b` when the project's tags match a kit. Hidden custom message
(`brain.card`), once per session and once after each compaction. Under 400 tokens by
construction: sections are filled greedily and cut.

### 4.2 Continuity (`brain_state`, `session_before_compact`, `session_compact`)

- The agent rewrites `working.md` with `brain_state("Goal … / Done … / Next … / Watch out …")`
  whenever the plan changes. Free Markdown, truncated to 150 tokens.
- Before compaction the extension auto-completes the state from the tool log: files edited, the
  last failing command, the last user prompt — only the fields the agent left empty, ≤ 80 tokens.
- After compaction the state is delivered as the next turn's hidden context
  (`sendMessage(…, { deliverAs: "nextTurn" })`), together with the card if the session is new.
- Session end writes a one-line `last session:` into the state, which becomes tomorrow's resume.

### 4.3 Recall and note (`brain_recall`, `brain_note`, CLI `brain recall|note`)

- Recall: BM25 over title (×5), tags (×3), body (×1); project first, then global and shared tags;
  relative floor 0.5 of the best hit; ≤ 3 lines, or nothing. `--all` widens to every project.
  The V3 ranking already gets 13/15 dev and 7/8 held-out on the frozen cases; V4 must not regress.
- Note: `brain_note("text")` → `notes/<project>/<id>.md` with `kind: note`, `source: agent`,
  `at: now`. Optional `kind: decision|gotcha|fact|procedure`, optional `tags`. Returns the id.
  A gotcha with an error line becomes a candidate correction; it is pushed on matching errors only
  after `tested: true` (set by `brain note --tested <id>` or automatically when capture sees the
  fix work).

### 4.4 Capture and known fixes (`tool_result`, `brain review`)

- The extension appends every tool result to `state/events/<session>.jsonl` (Brain-owned format,
  5 MB cap, 14-day retention). Port of the V3 logger.
- `brain review` turns failed → fixed pairs (same program, later success) and `Brain-Decision:` /
  `Brain-Gotcha:` commit trailers into proposals; secrets scrubbed; accept/reject in one command.
  The card shows the pending count and nothing more.
- On `tool_result` with `isError`, one tested note whose error pattern matches is appended to
  the result (≤ 80 tokens). Port of the V3 correction path.

### 4.5 Kits — MVPs in the fewest tokens (`brain kit`)

A kit is `kits/<name>/SKILL.md`: **when to use**, **stack decision and why**, **scaffold steps**
(exact commands, in order), **gotchas** (each with the failing symptom), **MVP-done checklist**.
≤ 600 tokens.

- `brain kit new <name> --from <project>` drafts a kit from that project's decisions, procedures
  and tested gotchas; you finish it by hand. `brain kit list`, `brain kit show`.
- The card names matching kits (by project tags); `brain_recall("kit fastapi")` returns one.
- Kits are cross-project by definition and load natively as skills in OMP and Claude Code.
- Value is measured, not assumed: scaffolding a fresh project with the kit versus native, tokens
  and tool calls to first passing run.

### 4.6 Cross-project and sync (`brain sync`)

`notes/global/` and shared tags (`projects.toml`) give cross-project visibility without moving
files. `brain sync` = commit the Brain paths (excluding private), pull `--rebase --autostash`,
push. Port of V3 sync. Working state syncs too, so a laptop can resume a desktop's task.

### 4.7 Other harnesses

`brain card` and `brain recall` are the whole contract. A Claude Code adapter is one hook script
(`SessionStart` → card, `PostToolUseFailure` → known fix) of ~40 lines, shipped but not in focus.

## 5. Kill list (from `main`, after P2 is live — see D-owner-5)

Everything is preserved in history under the tag `v2-archive`; `main` is rebuilt as the V4 tree.

- `src/second_brain/` (all 68 modules incl. `kb/` once ported), `pyproject.toml`, `.venv` scripts,
  `brainctl.*`, `scripts/*.ps1` except the new installer, all `tests/test_*.py`.
- `brainstem/prime-extension/` (legacy extension), `brainstem/adapters/*`, `brainstem/codex-hooks`.
- `constitution/`, `engrams/`, `experiences/`, `decisions/`, `plasticity/`, `sleep/`, `skills/*`
  lifecycle dirs, `memory/` (legacy store — converted to notes first), `db/`.
- `outputs/` (116 MB), `docs/intake/*` campaigns, mandates, registers and evidence; `docs/superpowers`,
  `docs/components`, `docs/architecture` (rewritten from scratch as one page).
- CI becomes: eslint · `tsc --noEmit` · vitest · a 2-minute eval smoke.

What is carried over (ported, not rewritten): the 120 records → notes (frontmatter trimmed by a
one-shot converter), the search ranking and its frozen case sets, the capture/scrub/correction
logic, the git sync, the event logger, the slim value suite (runner + tasks only), the two
frozen S2 case sets.

## 6. Phases

Each phase ends with something felt in a session on the owner's machine, not with a report.

| Phase | Build | Done when |
|---|---|---|
| **P0 Freeze** (½ day) | Tag `v2-archive` on current `main`. Branch `brain/v4`. This plan promoted. Owner decisions recorded. | Decisions D1–D6 (§7) answered. |
| **P1 Library + CLI** (2–3 days) | `brain/` package: store, search, card, state, notes; converter for the 120 records; vitest suite; `brain` CLI. | `brain card` in this repo ≤ 400 tokens in < 20 ms; recall on the frozen cases ≥ V3 (13/15, 7/8); `brain note` round-trips. |
| **P2 OMP extension** (2 days) | Hooks (card, compaction snapshot/re-inject, tool log) + 3 tools; installer parks the V3/V2 extension. | On Windows: card on turn 1; after a forced compaction the agent states goal and next correctly (10/10 scripted); ordinary prompts add 0 tokens (telemetry). |
| **P3 Capture + fixes** (1–2 days) | Port capture, review, corrections; `tested` gating. | A known error yields its fix ≤ 80 tokens; a failed → fixed pair shows up in `brain review`. |
| **P4 Kits** (2 days) | Kit format, `brain kit new/list/show`, card integration; first two kits drafted from real projects. | A fresh project scaffolded with a kit beats native on tokens and tool calls to first passing run (slim suite). |
| **P5 Sync + CC hook** (1 day) | Port sync; 40-line Claude Code hook. | Two machines exchange notes and working state; a Claude Code session gets the card. |
| **P6 Cleanup** (1 day, after ≥ 1 week of daily P2–P4 use) | Kill list executed on `main`; README, CLAUDE.md, one architecture page; CI. | `main` is the V4 tree; clone → `npm ci` → `brain card` works in under a minute. |
| **Ongoing** | Weekly telemetry read: which moments fired, tokens per session, tools called. | Anything unused for a week is deleted (rule 1). |

Order is fixed for P0–P2; P3–P5 can interleave with daily use. Nothing in P1–P5 touches the
installed V3/V2 runtime until the installer runs in P2, and that installer is reversible.

### 6.1 Status (2026-09-27, cloud-verified; live OMP runs are the owner's)

| Phase | State | Evidence |
|---|---|---|
| P0 | done, except the `v2-archive` tag (moved to P6) | plan accepted; decisions in §7 |
| P1 | done | 120 notes converted, 0 errors; recall = V3 exactly (dev 13/15, held-out 7/8, `test/eval.test.ts`), 4 ms/query; card 169 tokens in ~6 ms |
| P2 | **live on OMP 18.3.5** (2026-09-27: card delivered, tools mounted, telemetry rows) | `omp.ts`: card on turn 1, bounded resume after the last `compactionSummary` of every call after compaction, tools with the host's TypeBox shim and read/write approval tiers; simulated session in `test/omp.test.ts`. A live `/compact` producing a `resume` row is still to be observed |
| P3 | built | capture → review → accept round trip; known fix ≤ 80 tokens on a failed tool result |
| P4 | built, first kits written | `kits/omp-extension`, `kits/node-ts-cli`; card lists kits (all of them on a new project) |
| P5 | built | git sync (private excluded by pathspec; slashed branches); `brain hook claude-code` |
| P6 | kill list executed early on owner's call (2026-09-27, branch `brain/v4-baseline`); `v2-archive` tagged locally | tree is V4 only; `docs/history/pre-v4-outline.md` records what was removed |

Hardening pass (2026-09-27, "perfect it without a live test"): secrets masked on every write;
recall by note id and a retired-answer history line; duplicate notes refused; tools registered
first and guarded (a host that rejects them keeps the card and fixes); stack tags inferred from
root manifests; project aliases; the 70 SZ-tool notes re-homed out of global; token cache and a
single scoring pass (5,000 notes: warm recall 67 ms); installer `-Copy` fallback and a real
PowerShell + Bun round-trip test. Index trigger: build an inverted index only when a real corpus
passes ~2,000 notes or warm recall exceeds 50 ms.

Swarm rounds 5–6 (2026-09-27, live evidence): compaction re-injected 399 tokens → now only the
working state, ≤ 150; subagents no longer overwrite the parent's plan (host `ctx.agent.kind`);
auto observations moved to local `state/work/` (no race, failed commands off git); card lines
complete or skipped, ranked by the first prompt, "verify" framing dropped; proposals only for
real retries of the failed command (today's 17 live proposals were all noise); seeded
`notes/global` known fixes from logged OMP failures; privacy scrubs for URL paths, PEM tails,
credential flags and evidence; sync conflicts outside a nested home; `brain stats` reports
sub/main cards, recall hit rate and unmatched errors.

Compaction resume verified live (2026-09-28): one `resume` row, 150 tokens, 7 ms.

Round 3 (2026-09-28). Evidence: 0 `brain_recall` tool calls in OMP all week (the 8 recall rows
were CLI); brain tools used in 2/21 main sessions; ~20 of 47 active second-brain notes described
V1–V3. Landed: trigger-phrased tool descriptions and card footer (say *when*, not *what*); the
`brain_state` reply names what compaction will cut; resume keeps whole fields and lines;
subagents cannot mark notes tested, see only the parent's `Watch out:`, skip the capture scan;
stale evidence (D4) demotes and marks, never hides, and is judged only for this project and
global notes; recall answers with an active replacement before a retired note; a same-headline
write with a different body is refused, not silently dropped; stat-validated note cache (warm
load 7.8 → 2.8 ms); capture ignores inline scripts and scratch paths; telemetry attributes
`via` tool/cli/hook/mcp. Host independence: **owner approved `brain mcp`** (stdio MCP, same
three tools from `src/tools.ts`; amends D8), `brain fix "<error>"`, a complete Claude Code hook
(PostToolUse success capture, PreCompact/SessionEnd auto state, child sessions never write
state), and `brain hook agents-md` (the managed AGENTS.md block). Gate split: `npm run test:unit`
≈ 2 s, full ≈ 26 s; `npm run perf` measures real and synthetic 1000/5000-note corpora. Owner
retired 17 V1–V3-era and OMP 18.1.15 research notes; the 4 frozen-eval targets stay active.

Owner decisions: a resident ~40-token system-prompt line only if fewer than 20% of main sessions
use the tools after ~10 sessions (stop-loss). Prompt-time push and seeding the plan from OMP's
compaction summary stay deferred; the round-3 review recommends against both.

## 7. Owner decisions needed before P1

| # | Question | Recommendation |
|---|---|---|
| **D-1** | Drop Python for TypeScript (D1)? | Yes. One language; in-process in OMP; no venv. |
| **D-2** | No database, in-memory search over files (D2)? | Yes; revisit at 5 000 notes. |
| **D-3** | Three resident tools in OMP, or hook-only with the CLI (D3)? | Tools, configurable off. |
| **D-4** | Is "ponytail" the kits feature (§4.5), or something specific? | Confirm or name it. |
| **D-5** | Rebuild `main` as the V4 tree after P2 is live, with `v2-archive` keeping everything? | Yes, in P6, after a week of use. Outward-facing: needs your explicit go. |
| **D-6** | Which two projects supply the first kits? (Held-out cases mention SZ-tools and BasicUpscaler.) | Name them; the plan does not depend on which. |

**Answered 2026-09-27:** the owner accepted every recommendation ("I support all your
decisions"). D-4: kits are the "ponytail" feature. D-6: no projects named, so the first two kits
come from what this repository proved (`omp-extension`, `node-ts-cli`); kits from SZ-tools /
BasicUpscaler follow when those projects are worked on. D-5: the `v2-archive` tag and the
rebuild of `main` wait for P6, after a week of daily use, and still get a final go before the
tag is pushed.
