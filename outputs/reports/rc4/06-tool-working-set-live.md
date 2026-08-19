# Prime Tool Working Set Integration

Phase R6. Confirms the host control surface is real (not a limitation, per
R1), wires the read side, and explicitly declines to wire the write side
this pass — for an evidence-based reason, not a missing feature.

## 1. The API is real and unused

`ExtensionAPI` declares `getActiveTools?(): string[]`, `getAllTools?():
ToolInfo[]`, and `setActiveTools?(toolNames: string[]): void`
(`prime.d.ts:306-309`), annotated "modeled for Phase J measurement, not
consumed today." Confirmed in R1
([02-prime-live-callgraph.md](02-prime-live-callgraph.md)) that `index.ts`
never called any of the three before this pass.

## 2. Wired this pass: read side only

`session_start` now calls `pi.getAllTools?.()` and `pi.getActiveTools?.()`
(when the host provides them) and records a new `prime_tool_surface`
telemetry line — the real tool names and counts Prime exposes for that
session. Read-only, additive, cannot affect the session even if wrong.

## 3. Deliberately not wired: `setActiveTools`

`src/second_brain/tool_working_set.py`'s `ToolWorkingSetManager` — the
"shared Tool Working Set" the plan asks to wire — manages a **fictional**
tool catalog: `view_file`, `run_command`, `replace_file_content`,
`write_to_file` (core), `git_commit_and_sync`, `database_migrate_query`,
`memory_curate_insight` (domain). These are not Prime's real tool names
(Prime's own guard code elsewhere blocks/allows `bash`/`edit`/`websearch` —
confirmed by grepping `orchestrator-guard.ts`). `setActiveTools(names)`
takes a **replacement** list, not an additive one. Calling it with this
Python module's invented names would not "activate a Python-Brain domain
tool" — it would tell Prime to replace its active tool set with a list of
names that likely don't exist in Prime's real catalog at all, which could
strip every real tool the session actually has access to (`view_file`,
`run_command` etc. are not synonyms for Prime's `bash`/`edit`).

This is the same category of gap as R3's VMem message-shape problem, not
a host limitation: the mechanism works, but nothing in this codebase has
ever captured what Prime's real tool names actually are, so there is
nothing correct to pass `setActiveTools` yet. The new `prime_tool_surface`
telemetry (§2) is what will finally answer that question, from a real
Prime session. Wiring `setActiveTools` against a guessed name mapping
before that data exists would be exactly the kind of fabrication the
plan's evidence rules forbid.

## 4. Verification

```
cd brainstem/prime-extension
npx tsc --noEmit   → clean
npx eslint .       → clean
npx vitest run     → 16 files, 397 passed (was 395; +2 new)
```

New tests (`tests/wiring.test.ts`): tool surface captured and recorded
correctly when the host provides `getAllTools`/`getActiveTools` (verifies
`all_tools_count`, `active_tools_count`, real tool-name arrays, and record
ordering — `prime_tool_surface` before `session_start` in the telemetry
stream); no record written when the host does not expose either method
(the default fake host used by every other wiring test — confirms zero
behavior change for hosts/tests that predate this capability).

## 5. What live pilot must produce before `setActiveTools` can be wired

A real Prime session's `prime_tool_surface` record, giving the actual tool
names Prime exposes. Only then can `ToolWorkingSetManager`'s catalog (or a
new one) be built against real names, and `setActiveTools` calls proven
safe in a real session before being claimed live.
