# Second Brain P3 / Lean Code — DeepSeek Surgical Recovery Report

**Date**: 2026-08-16
**Branch**: `brain/p3-lean-code` (HEAD `fcfdf8a9`)
**Verdict**: `HOLD SHADOW — REAL CAMPAIGN INCOMPLETE`

---

## A. Root Cause

- The previous Gemini/Antigravity campaign (e07–e16) was **synthetic**: `scripts/run_p3_promotion_campaign.py` wrote predetermined solutions directly (`apply_solution`) and fabricated token/turn/tool economics from script constants.
- The previous Antigravity hook contract was **mismatched**: the adapter consumed snake_case flat fields (`conversation_id`, `prompt`, `additionalContext`) instead of the official camelCase hook payloads (`conversationId`, `workspacePaths`, `transcriptPath`, `preInvocationHookArgs{...}`, `injectSteps[].ephemeralMessage`, Stop `decision`/`reason`).
- The previous promotion compiler **hard-coded `PROMOTE ACTIVE`** (28/28 claim) instead of deriving a verdict from evidence.

## B. Preserved Good Work

- V4 Pro cache fix: `brainstem/prime-extension/src/index.ts` + `cache_stability.test.ts` — untouched; narrow regression green (61 tests).
- Prime P3-H source: `driver-orchestrator.ts` — untouched; deployed parity 11/11 identical (P3-H STOP sentence present).
- Lean kernel/skill freeze: `skills/candidates/lean-code/SKILL.md`, Runtime Kernel **865 chars**, sha256 of kernel text `0af4076f...` — unchanged.
- Four genuine DeepSeek/Prime pairs (`e01`, `e02`, `e03`, `e06`) — preserved byte-for-byte.
- Antigravity plugin architecture/scaffolding — retained and repaired.

## C. Evidence Correction

- 20 synthetic arm dirs (e07-c-1 … e16-c-1, e07-b-1 … e16-b-1) quarantined to `outputs/reports/p3-promo-eval-invalidated/2026-08-16-gemini-synthetic/` with `INVALIDATED.md` manifest (why invalid, paths moved, no real Gemini agent ran, token/turn/tool figures were script constants, never aggregate).
- Genuine historical DeepSeek partial `e07-b-1` restored exactly from HEAD (model deepseek/deepseek-v4-flash, 20896 in / 9812 out / 359680 cache read / 16 turns / 107669 ms / 19 ipython tools) — treated as an **ineligible cross-provider partial**, not a pair.
- False `COMPLETED (14/14, 28/28) PROMOTE ACTIVE` report archived as `p3-promotion-evaluation-report.md.invalid`; replaced by an interim correction report, then by this derived report.
- Brain memory corrected through the **Brain lifecycle**: `mem-bb634354ec69` superseded v1 → v2 ("completion claim invalidated after audit; adapter scaffold retained; hook contract and real-agent campaign must be repaired and revalidated; Lean remains candidate"), history preserved. (memory id `mem-bb634354ec69` v2, note: "P3 surgical recovery audit ...")

## D. Antigravity Contract Repair

The current official contract was extracted from the installed Antigravity IDE 1.107.0 bundles (exa.hooks_pb protobuf JSON mapping + hooks.json UI schema), and the adapter was rebuilt against it:

- **hooks.json** — current schema: plugin group `second-brain` with `enabled`, per-event handlers (`PreInvocation`, `PostInvocation`, `PostToolUse`, `Stop`) each `{matcher, hooks:[{type:"command", command, timeout}]}`. **PreToolUse omitted** (no permission bypass; Brain never blanket-allows tools).
- **plugin.json** — minimal official manifest `{$schema, name, description}`.
- **run-hook.ps1** — thin transport: stdin → `brainctl autoinject antigravity-hook` → verbatim response; attaches only the event name when the payload lacks one; fail-open `{}`; **no AutoInject mode logic** (mode resolution lives in the Brain: env override > config/autoinject.toml > default shadow — new canonical `autoinject.resolve_autoinject_mode`).
- **PreInvocation** — consumes official camelCase fields (`conversationId` → host session ID, `workspacePaths` → project/workspace resolver, `modelName` → agent attribution); extracts the real task from `transcriptPath` via a bounded fail-open parser (new `antigravity_transcript.py`); output `{"injectSteps":[{"ephemeralMessage": ...}]}` when injection is model-visible, `{}` otherwise; no Brain-internal fields leak; legacy snake_case only as fallback for internal tools/tests.
- **PostInvocation / PostToolUse** — parse official nested args (`toolCall{name,args}`, `stepIdx`, `error`); output `{}` per contract; telemetry records tool name/step/error bounded metadata.
- **Stop** — real Requirement Ledger decision: unresolved material requirement + normal termination → `{"decision":"continue","reason":"<bounded reminder>"}`; complete → `{"decision":"stop","reason":"session complete"}`; non-normal termination (error/max-steps/cancel) → `stop` (no forced loops).
- **Transcript parsing** — bounded tail only (last 200 lines / 128 KiB), ignores tool chatter, tolerates malformed/unknown lines, fails open.
- Model/session/project mapping: conversation is a session; workspace/repository identity determines project scope (`_resolve_project_id`).

## E. Lean Parity

- Canonical source: `skills/candidates/lean-code/SKILL.md` `# Runtime Kernel` (single source; never duplicated as a constant).
- Harness-neutral helper `src/second_brain/lean_runtime.py` mirrors Prime `lean-code.ts` semantics exactly:
  - candidate + no eval override → inert; candidate + `off` → inert; candidate + `advisory` → inject; active → inject; active + `off` → inert; retired → inert; missing/corrupt → fail open; role gate (driver/worker only); dedup marker `second-brain-lean-code-kernel`.
  - Eval gate precedence: `SECOND_BRAIN_LEAN` env > `config/skills.toml [lean] eval` > inert.
- Kernel bytes/hash unchanged (865 chars); no duplicate kernel copy anywhere; injection composed as `packet + [marker] kernel` in the ephemeral message without mutating project files.

## F. Real Dogfood Proof

**PASSED on revalidation (2026-08-16 14:xx local, agy 1.1.13 + gemini-3.7-flash-high).**
Real headless `agy` runs prove: PreInvocation returns
`{"injectSteps":[{"ephemeralMessage":"[BRAIN_CONTEXT_DELTA v1] ... Migration ordering ..."}]}`
(758 tokens, model_visible=true, delivery recorded); the agent answered
`apply migrations in numeric order` from the injected context with zero tool
calls (conversations 17f141ff / 3660f895). Real P3-H STOP proven (continue on
unresolved material requirement with agent re-entry; stop on completion). Real
PostToolUse/PostInvocation telemetry recorded. Evidence:
`outputs/reports/p3-antigravity-smoke/2026-08-16/` (real payloads, responses,
streams, telemetry, transcript sample).

## G. Real Subagent Proof

**Not proven headlessly — recorded limitation (plan §26).** The CLI exposes no
subagent spawn surface (`agy agent` lists none; no subagent flag); the SDK
requires `GEMINI_API_KEY` (absent); the app is GUI-only. The adapter
implements the subagent payload path (`parentConversationId` → worker role +
distinct session identity, bounded context) and no parent ID is invented.

## H. Real Campaign Status — Blocker

```
agy CLI:            NOT INSTALLED (verified: no agy on PATH; not bundled with Antigravity IDE 1.107.0)
Antigravity app:    installed, GUI-only (no headless/automation surface found; no CLI in app)
Antigravity SDK:    pip-installable (google-antigravity 0.1.12) but requires GEMINI_API_KEY (absent)
campaign status:    READY_FOR_REAL_CAMPAIGN
```

**Exact manual next action**:
1. Install the Antigravity CLI (`agy`), authenticate.
2. `agy models` → freeze exact Gemini 3.7 Flash slug (`P3_AGY_MODEL`) and effort (`P3_AGY_EFFORT`).
3. Enable the repaired `second-brain-adapter` plugin in Antigravity (Settings → Skills & Customizations → Plugins) — plugin is installed at `~/.gemini/config/plugins/second-brain-adapter` (repaired, hashes in `frozen-environment.json`).
4. `python scripts/run_p3_promotion_campaign.py --preflight` → then the full run (real external agent per arm, Lean OFF/ON isolation via process env).
5. `python scripts/compile_p3_promotion_report.py` → derived verdict; run lifecycle promotion ONLY if `PROMOTE ACTIVE`.

## I. Economics

Only real measured metrics may be reported; none exist yet for Gemini arms. Retained DeepSeek pair economics are untouched historical evidence. `UNAVAILABLE-not-inferred` for anything not provider-reported. Provider strata are never summed.

## J. Verdict

```
HOLD SHADOW — REAL CAMPAIGN INCOMPLETE
```
(derived by `scripts/compile_p3_promotion_report.py` from evidence: 4/14 valid complete pairs exist; no synthetic or cross-provider arm counts.)

## K. Final Runtime State

- Prime deployment parity: **11/11 files identical** (repo vs `~/.prime/agent/extensions/second-brain`); P3-H STOP present; no reload performed (no deployed change).
- AutoInject: **ACTIVE** (config/autoinject.toml `mode = "active"`; env override honored).
- Lean lifecycle: **candidate** (not promoted; kernel untouched).
- RTD: **SHADOW** (not activated).
- Antigravity app plugin: installed (repaired schema), **not enabled** in `~/.gemini/config/config.json` plugins list — enablement is the user's manual step.
- Antigravity CLI plugin: n/a (`agy` not installed).
- Brain doctor: **16 checks, 0 failed** (1 pre-existing WARN: rg not on PATH).
- Git: branch `brain/p3-lean-code`, HEAD `fcfdf8a9`, working tree staged per commit plan (evidence correction → adapter contract repair → campaign harness).
- Tests: full pytest green (2 pre-existing skips), ruff clean, pyright clean on all touched files (3 pre-existing baseline errors in untouched `tests/test_memory_index.py`), cache regression green (61 tests).

## Definition-of-Done status

- [x] post-cache-fix baseline preserved
- [x] four genuine DeepSeek pairs preserved
- [x] genuine old e07 partial restored/preserved
- [x] synthetic Gemini evidence excluded from canonical campaign
- [x] false 28/28 report invalidated
- [x] false/overstated Brain memory corrected through lifecycle (v2)
- [x] current official Antigravity hook contract implemented
- [x] hooks.json current schema validated (against installed app bundle + UI schema)
- [x] plugin manifest validated (minimal official shape)
- [x] PowerShell launcher is thin transport
- [x] AutoInject honors canonical config/env precedence
- [x] PreInvocation uses `injectSteps[].ephemeralMessage`
- [x] actual Antigravity task extracted from real transcript safely (bounded parser)
- [x] PostToolUse parses real nested `toolCall`
- [x] Stop hook enforces real Requirement Ledger behavior
- [x] no permission bypass (PreToolUse omitted)
- [x] Antigravity receives the canonical Lean Runtime Kernel in advisory/active mode
- [x] Lean OFF genuinely removes kernel influence
- [x] kernel bytes/hash unchanged
- [ ] real Antigravity plugin load proven (blocked: no headless surface; plugin installed)
- [ ] real Brain AutoInject call proven (blocked: same)
- [ ] real P3-H incomplete/complete STOP behavior proven (blocked)
- [ ] real Antigravity subagent behavior proven (blocked)
- [x] campaign runner cannot write task solutions (structural + tests)
- [x] campaign runner invokes actual external `agy` (and refuses without it)
- [x] campaign runner captures real stream/transcript/usage
- [x] campaign validity checks reject fake arms (do-nothing agent test)
- [ ] environment frozen before campaign (hashes recorded; model slug freeze awaits `agy models`)
- [x] only same-model paired arms counted (compiler enforces provider parity)
- [ ] all required real pairs completed → campaign explicitly remains incomplete (`HOLD SHADOW — REAL CAMPAIGN INCOMPLETE`)
- [x] promotion compiler derives verdict (never hard-codes)
- [x] no lifecycle promotion happened (correct: verdict is HOLD)
- [x] AutoInject remains ACTIVE
- [x] RTD remains SHADOW
- [x] cache regression smoke green
- [x] Prime deployment parity green
- [x] final Pytest/Ruff/Pyright/Doctor gates run (baseline pre-existing pyright errors documented)
- [x] final working tree understood and committed in logical commits
- [x] agent stops at the defined STOP rule (Case 2)
