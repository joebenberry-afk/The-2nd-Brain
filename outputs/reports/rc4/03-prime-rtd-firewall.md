# Prime RTD / Observation Firewall Unification Decision

Phase R2. No code changed — investigation confirmed reuse is already correct
and no defect exists. Documented per plan §8 "Prefer reuse."

## The two implementations

- **RTD** (`brainstem/prime-extension/src/rtd.ts`, wired live at
  `index.ts:741-792` inside `pi.on("tool_result", ...)`). TypeScript-native,
  runs inside the Prime process, no subprocess in the hot path except the
  preserve/verify artifact-store round trip
  (`cliRtdPreserver` → `python -m second_brain artifact store/expand`).
- **Observation Firewall** (`src/second_brain/firewall.py`,
  `reduce_observation`). Python-native, kind-specific reducers for pytest,
  compiler/typecheck, git (diff/status/log-aware), search, JSON, process
  logs, build output, and doctor checks. Reachable only via
  `second_brain firewall reduce|expand|kinds`
  (`src/second_brain/cli.py:3409-3447`) — confirmed by grepping every
  caller of `reduce_observation` (`cli.py`, its own tests,
  `tests/test_dogfood_token_economics.py`). **Not imported anywhere in
  `brainstem/prime-extension/`.**

## Verifying the live handler performs the required semantics

Plan §8 requires: `real tool_result → deterministic eligibility → preserve
full output → verify recovery → reduce → replace model-visible result →
record artifact ref + metrics`. Read end to end against
`runRtd()` (`rtd.ts:507-602`), called from the real `tool_result` handler
(`index.ts:741-792`):

1. **Eligibility** — `rtdEligibility()` decided first, before any content
   measurement (bash + pytest/git/rg/grep prefix, size threshold).
2. **Preserve full output** — `options.preserver.preserve(raw)` writes the
   exact raw text through the artifact store *before* anything is replaced
   (`rtd.ts:541`).
3. **Verify recovery** — `options.preserver.verify(preserved.sha256, raw)`
   byte-compares the stored artifact back against the raw text
   (`rtd.ts:557`); on failure or missing preservation, the function returns
   `patch: undefined` — **original content unchanged** (`rtd.ts:542-556,
   558-571`). Recoverability is never traded for savings.
4. **Reduce** — `distillText()` (head/tail + pytest-specific evidence
   extraction, error-aware tail ratio).
5. **Replace model-visible result** — `{ content: [{type:"text", text:
   block}] }` returned as the `tool_result` patch (`rtd.ts:600`), which the
   real handler passes straight through: `return rtd.patch;`
   (`index.ts:783`).
6. **Record artifact ref + metrics** — `buildRtdBlock()` embeds
   `sha256`/`artifact`/`original_chars`/`visible_chars`/`saved_chars` in the
   model-visible block itself (`rtd.ts:456-475`), and the `rtd_shadow`
   telemetry record carries the same fields (`rtd.ts:591-599`) into the
   session's telemetry store (`index.ts:773`).

This is the intended lossless reduction path, genuinely wired to the
production `tool_result` handler — not a claim, verified against source
line by line. This report is a **component-level confirmation**, not a live
Prime session proof; that remains part of the still-open R9–R11 real-pilot
work.

## Verification run (this pass)

```
cd brainstem/prime-extension && npx vitest run
```
→ 15 files, **378 passed**, including
`tests/wiring.test.ts > Phase 3 RTD hot path (src/index.ts)`, which exercises
`src/index.ts`'s real `tool_result` wiring end to end (not just `rtd.ts` in
isolation).

```
npx eslint .    → clean, no output
npx tsc --noEmit → clean, no output
```

## Decision: B — RTD is the production reducer; Firewall stays a separate library

Per plan §8's own framing:

> A. the new Observation Firewall should become the shared reducer behind
> Prime RTD, or B. RTD already fulfills the production reducer requirement
> and Firewall should be a reusable reducer library for other hosts.

**B.** RTD already satisfies every safety invariant the plan requires for
the live Prime path (preserve-first, verify-before-replace, fail-open on any
preservation/verification failure, deterministic reduction, artifact
reference recorded). Routing it through `firewall.py` instead would mean:
calling a Python subprocess synchronously inside the `tool_result` hot path
(latency + a second failure surface beyond the existing preserve/verify
round trip), and replacing a tested, live-wired TypeScript reducer with an
untested-in-this-context one — the opposite of "reuse/unify rather than
build a parallel reducer." `firewall.py` remains what it already is: a
Brain-owned CLI reducer (`second_brain firewall reduce`) other hosts
(Codex, AGY, or any harness without a TS extension layer) can call directly
without needing Prime's extension surface at all.

## Known, unfixed gap (recorded as debt, not blocking)

RTD's `distillText()` only specializes evidence extraction for the
`pytest` command class (`rtd.ts:423-429`); `git`/`rg`/`grep` results get
generic head/tail truncation. `firewall.py`'s `reduce_git()` and
`reduce_search()` produce materially better summaries for those same
eligible commands (diff-file lists, git-status-aware entries, per-file match
counts). Porting that specialization into `rtd.ts` is a legitimate future
improvement, but it is not required to satisfy R2 and was not attempted
here (no defect — just a lower-fidelity reduction for two of the four
eligible command classes).
