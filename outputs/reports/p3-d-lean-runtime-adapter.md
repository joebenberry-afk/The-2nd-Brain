# P3-D — Lean Runtime Adapter (SHADOW) — Implementation Report

Branch `brain/p3-lean-code` @ d21bf87. Plan: Second_Brain_P3_Lean_Code_One_Shot_Plan_v2_ACTIVE.md §7-§8, §24.5, §26. AutoInject untouched (still ACTIVE). No commits, no deployment to ~/.prime (parent coordinates deploy + daemon restart).

## 1. Changed files

| file | change |
|---|---|
| `brainstem/prime-extension/src/lean-code.ts` | NEW — P3-D adapter: canonical kernel parser, lifecycle dir resolution (active > shadow > candidates > retired, mirroring `src/second_brain/paths.py` SKILL_LEVEL_DIRS), in-process mtime/size cache, `decideLeanRuntime` matrix, `appendLeanKernel` dedup append, stable marker `second-brain-lean-code-kernel` |
| `brainstem/prime-extension/src/index.ts` | wired: decide+record `lean_kernel` on every `before_agent_start` (before branch points, incl. Sol path); kernel appended after driver contract, before recall brief; patch-return condition widened to any patched change (worker+lean now delivers) |
| `brainstem/prime-extension/src/sensors.ts` | new pure sensor `leanKernel` (kind `lean_kernel`, v=2, privacy-safe enumerated fields) |
| `brainstem/telemetry/SCHEMA.md` | `lean_kernel` kind row + full P3-D section (semantics, reasons, real ordering) |
| `brainstem/prime-extension/tests/lean-code.test.ts` | NEW — 34 tests: parse, lifecycle matrix, fail-open, dedup, wiring integration |
| `brainstem/prime-extension/tests/lean-cache.test.ts` | NEW — 4 tests: in-process cache contract with node:fs mocked (read-count observable) |
| `brainstem/prime-extension/tests/wiring.test.ts` | updated exact-kind assertions for the additive `lean_kernel` (+fail-open `extension_error`) records; added `recordOf` helper |

## 2. Adapter behavior matrix (plan §8.2)

| skill status | env `SECOND_BRAIN_LEAN` | role driver/worker | role normal | Sol hard-orchestrator |
|---|---|---|---|---|
| candidate | unset | omit (reason `off`) — measurement only | omit (`role`) | omit (`role`) — NEVER |
| shadow | unset | omit (`off`) | omit (`role`) | omit (`role`) |
| active | unset | INJECT (`active`) | omit (`role`) | omit (`role`) |
| candidate/shadow | `advisory` | INJECT (`advisory`) — P3-E eval mode | omit (`role`) | omit (`role`) |
| retired | any | omit (`off`) — retirement disables (§26.1) | omit (`role`) | omit (`role`) |
| any | `off` | omit (`off`) — forced inert | omit (`role`) | omit (`role`) |
| missing/corrupt | any | omit (`skill-missing`) + bounded `extension_error`; no patch, no invented text | omit (`role`) | omit (`role`) |

Dedup (plan §8.4): if the assembled base already contains `second-brain-lean-code-kernel`, no injection; `lean_kernel.dedup_hit=true` (recorded with the lifecycle reason). Injection only ever APPENDS `[second-brain-lean-code-kernel]\n<canonical kernel>` — never replaces the base, never invents a prompt.

## 3. Kernel source + cache (plan §7.1/§8.6)

- Kernel text: parsed at runtime from the canonical skill's `# Runtime Kernel` section only (skills/candidates/lean-code/SKILL.md today; resolves by lifecycle dir when promoted). NOT duplicated as a TS constant.
- Cache: in-process `Map` keyed by resolved path, invalidated on mtimeMs/size change; unchanged file read AT MOST ONCE per extension lifecycle; fail-open error entries cached too. Test seams: `resetLeanKernelCache()`, `leanKernelCacheSize()`.
- Measured canonical kernel: **865 chars** (byte-stable, plan §7.4); injected block incl. marker line: 897 chars.

## 4. Marginal overhead estimate (plan §7.2; real number comes from P3-E)

- kernel 865 chars → `865 // 4` = **216 input tokens** (same chars/4 convention AutoInject uses for packet_tokens);
- injected block (marker + kernel) 897 chars → **224 tokens**;
- the REAL per-turn marginal cost must be measured from live `assistant_usage` deltas in P3-E paired runs (candidate arm via `SECOND_BRAIN_LEAN=advisory`).

## 5. Real patch ordering (documented, not faked — verified against Prime v0.7.2 SDK)

- `runner.ts` emitBeforeAgentStart: handler `systemPrompt` results chain; `message` results collected separately.
- `agent-session.ts` `_applyPreparedSystemPrompt`: the extension's patched prompt becomes the session system prompt.
- `agent-session.ts` `_appendBeforeAgentStartMessages` (line ~72074): AutoInject custom messages are PUSHED TO THE END of `preparedMessages` — i.e., AFTER the current user task; `messages.ts` `convertToLlm` maps `custom` → `user`.
- REAL model-facing order: `system [base → driver contract → lean kernel → recall brief*] → ...history... → user: task → user: AutoInject packet` (*only when recall fires). The kernel sits in the system prompt before ALL messages (plan §7.4 satisfied for the kernel); the dynamic AutoInject packet's position after the task is host-determined and reported honestly.

## 6. Tests (baseline 285 → 323)

- `npm test`: **323 passed / 323** (12 files; +34 lean-code, +4 lean-cache; wiring updated for additive records) — run 3× green.
- `tsc --noEmit`: clean. `eslint .`: clean.
- Coverage of §24.5 kernel items: kernel lifecycle (status×env matrix), kernel dedup (unit + wiring single-marker), missing/corrupt skill fail-open (+extension_error, no patch), role handling (driver/worker/normal/Sol), Sol hard-orchestrator contract unchanged, canonical-file-only parse (real repo file, 865 chars), in-process cache (hit/mtime/size invalidation), patch ordering (contract before kernel, merged once, kernel before recall brief).

## 7. Baseline sample 2 — this session (01a0094d, P3-D worker, Lean-OFF)

Snapshot at report time (session still live; AutoInject mode=active per config):

```
assistant_usage rows=117 | input=104,789 | output=79,273 | cache_read=12,306,816 |
cache_write=0 | cost_total=$0.071326 | AutoInject packets=2 distinct /
packet_tokens=362+633 (pkt-09140130cdcf638b 362 tok/2 items;
pkt-374a5df37e07f4c2 633 tok/5 items; 3rd record = re-emit cache_hit)
tool_call=133 (all ipython), tool_result=132 | files touched=7
validation ok=True
```

- files touched = 7 written: `src/lean-code.ts` (new), `tests/lean-code.test.ts` (new), `tests/lean-cache.test.ts` (new), `src/index.ts`, `src/sensors.ts`, `tests/wiring.test.ts`, `telemetry/SCHEMA.md`.
- This run is Lean-OFF by construction: the session runs the deployed pre-P3-D extension copy (no adapter), the skill is candidate, and no `SECOND_BRAIN_LEAN` env — zero kernel injection, zero lean records in this session's telemetry (correct experimental control for P3-E).
- cache_write=0 recorded exactly as exposed (zero-vs-missing preserved, plan §0A.8).

## 8. Rollback (plan §26)

- Skill demotion/retirement disables injection (§26.1); env `SECOND_BRAIN_LEAN=off` forces inert; adapter is additive and fail-open (§26.4 — missing skill/telemetry never breaks Prime); uninstall = delete `src/lean-code.ts` + revert `index.ts` wiring (no other subsystem touched).
