# Task 3: `visibility-bridge.ts` + `index.ts` wiring

Tasks 1 and 2 are complete and committed: `src/second_brain/skills.py` and the `omp_adapter.py` `operation == "skill_visibility"` branch both exist. Do not modify any Python file. Do not modify `routing-bridge.ts`, `worker-context-bridge.ts`, or anything under `src/second_brain`. `index.ts` is a large (2000+ line), delicate, currently-live extension file — make ONLY the additive changes specified below; do not reformat, reorder, or "clean up" anything else in it. Do not begin P3.17.

**Files:**
- Create: `brainstem/prime-extension/src/visibility-bridge.ts`
- Create: `brainstem/prime-extension/tests/visibility-bridge.test.ts`
- Modify: `brainstem/prime-extension/src/index.ts` (additive only, exact insertion points given below)
- Modify: `brainstem/prime-extension/tests/wiring.test.ts` — first check its current line count with `read`; if it exceeds ~2500 lines, create `brainstem/prime-extension/tests/visibility-wiring.test.ts` instead and skip editing `wiring.test.ts`

## Step 1: Create `visibility-bridge.ts`

This mirrors `brainstem/prime-extension/src/routing-bridge.ts` exactly (read that file directly first — it is in this repository). Implement:

```typescript
/** Thin OMP -> Second Brain skill-visibility bridge (plan P3.16). */

import { execFile } from "node:child_process";

export const OMP_VISIBILITY_MAX_TASK_CHARS = 2048;
export const OMP_VISIBILITY_MAX_IDENTITY_CHARS = 128;
export const OMP_VISIBILITY_TIMEOUT_MS = 3000;
export const OMP_VISIBILITY_MAX_STDOUT_CHARS = 256 * 1024;
export const OMP_VISIBILITY_MAX_INJECTED_CHARS = 8192;

export interface OmpVisibilityOptions {
  home: string;
  task: string;
  sessionId: string;
  projectId: string;
  python?: string;
  timeoutMs?: number;
}

export interface OmpVisibilityPlan {
  visibility_plan_id: string;
  mode: "shadow" | "enforced";
  selected_skill_ids: string[];
  hydrated_skill_ids: string[];
  rejected_skill_ids: Record<string, string>;
  unavailable_skill_ids: Record<string, string>;
  [key: string]: unknown;
}

export interface OmpVisibilityResult {
  visibility_plan: OmpVisibilityPlan | null;
  hydrated_instructions: Record<string, string>;
  error: string | null;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

/** Parse the omp-routing CLI bridge's skill_visibility JSON response. Every
 * malformed/oversized/non-object shape fails open to a null plan. */
export function parseOmpVisibilityOutput(stdout: string): OmpVisibilityResult {
  if (stdout.length > OMP_VISIBILITY_MAX_STDOUT_CHARS) {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_OUTPUT_TOO_LARGE" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") {
    return { visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_INVALID_RESPONSE" };
  }
  const value = parsed as Record<string, unknown>;
  const plan = value.visibility_plan;
  const hydrated = value.hydrated_instructions;
  const hydratedInstructions: Record<string, string> =
    hydrated != null && typeof hydrated === "object" && !Array.isArray(hydrated)
      ? Object.fromEntries(
          Object.entries(hydrated as Record<string, unknown>).filter(
            ([, text]) => typeof text === "string",
          ) as [string, string][],
        )
      : {};
  if (plan == null || typeof plan !== "object" || Array.isArray(plan)) {
    return {
      visibility_plan: null,
      hydrated_instructions: {},
      error: bounded(value.error, 128) || "BRAIN_VISIBILITY_UNAVAILABLE",
    };
  }
  return { visibility_plan: plan as OmpVisibilityPlan, hydrated_instructions: hydratedInstructions, error: null };
}

export function ompVisibilityRecord(
  kind: string,
  session: string,
  fields: Record<string, unknown>,
): Record<string, unknown> {
  return {
    v: 3,
    ts: new Date().toISOString(),
    kind,
    session,
    ...fields,
  };
}

/** Run one bounded Brain-owned skill-visibility plan; every failure fails open. */
export function runOmpVisibility(options: OmpVisibilityOptions): Promise<OmpVisibilityResult> {
  const python = options.python ?? "python";
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const payload = {
    operation: "skill_visibility",
    task: bounded(options.task, OMP_VISIBILITY_MAX_TASK_CHARS),
    host_session_id: bounded(options.sessionId, OMP_VISIBILITY_MAX_IDENTITY_CHARS),
    project_id: bounded(options.projectId, OMP_VISIBILITY_MAX_IDENTITY_CHARS),
  };
  return new Promise((resolve) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_VISIBILITY_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_VISIBILITY_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolve({ visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_UNAVAILABLE" });
          return;
        }
        resolve(parseOmpVisibilityOutput(stdout));
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}
```

Notes:
- Use `python = options.python ?? join(options.home, ".venv", "Scripts", "python.exe")` (import `join` from `"node:path"`) if `routing-bridge.ts`'s actual `runOmpRouting` (which you must read directly) resolves the python binary that way instead of the plain string `"python"` shown above as a placeholder default — **match `routing-bridge.ts`'s exact python-resolution expression verbatim**, do not deviate.
- The CLI entrypoint is the SAME `["-m", "second_brain", "autoinject", "omp-routing"]` command `routing-bridge.ts`/`worker-context-bridge.ts` already use — this is not a new subcommand; `omp_adapter.handle_request` (Task 2) dispatches on the `operation` field in the JSON payload. Do not add a new CLI subcommand.

## Step 2: Write the failing tests

```typescript
// brainstem/prime-extension/tests/visibility-bridge.test.ts
import { describe, expect, it } from "vitest";
import { parseOmpVisibilityOutput, runOmpVisibility } from "../src/visibility-bridge";

describe("parseOmpVisibilityOutput", () => {
  it("parses a well-formed shadow-mode plan", () => {
    const stdout = JSON.stringify({
      visibility_plan: { mode: "shadow", selected_skill_ids: ["a"], hydrated_skill_ids: [] },
      hydrated_instructions: {},
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.visibility_plan?.mode).toBe("shadow");
    expect(result.error).toBeNull();
  });

  it("parses a well-formed enforced-mode plan with hydrated instructions", () => {
    const stdout = JSON.stringify({
      visibility_plan: {
        visibility_plan_id: "vplan-abc123",
        mode: "enforced",
        selected_skill_ids: ["a"],
        hydrated_skill_ids: ["a"],
        rejected_skill_ids: {},
        unavailable_skill_ids: {},
      },
      hydrated_instructions: { a: "full skill text" },
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.visibility_plan?.mode).toBe("enforced");
    expect(result.hydrated_instructions.a).toBe("full skill text");
  });

  it("fails open on malformed JSON", () => {
    const result = parseOmpVisibilityOutput("not json");
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });

  it("fails open when visibility_plan is missing", () => {
    const result = parseOmpVisibilityOutput(JSON.stringify({ error: "VISIBILITY_UNAVAILABLE" }));
    expect(result.visibility_plan).toBeNull();
    expect(result.error).toBe("VISIBILITY_UNAVAILABLE");
  });

  it("fails open when hydrated_instructions is not an object", () => {
    const stdout = JSON.stringify({
      visibility_plan: { mode: "shadow", selected_skill_ids: [], hydrated_skill_ids: [] },
      hydrated_instructions: "nope",
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.hydrated_instructions).toEqual({});
  });

  it("fails open when stdout exceeds the bound", () => {
    const huge = "x".repeat(300 * 1024);
    const result = parseOmpVisibilityOutput(huge);
    expect(result.visibility_plan).toBeNull();
    expect(result.error).toBe("BRAIN_VISIBILITY_OUTPUT_TOO_LARGE");
  });
});

describe("runOmpVisibility", () => {
  it("fails open when the python process errors", async () => {
    const result = await runOmpVisibility({
      home: "/nonexistent/path/that/does/not/exist",
      task: "test task",
      sessionId: "s1",
      projectId: "p1",
      python: "/nonexistent/python/binary/that/does/not/exist",
    });
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });
});
```

## Step 3: Run tests to verify they fail, then implement, then verify pass

Run (from `brainstem/prime-extension/`): `npm test -- --run visibility-bridge`
Expected FAIL first (module missing), then implement Step 1's code, then re-run expecting PASS.

## Step 4: Wire into `index.ts`

**4a. Add the import.** Immediately after the existing import block:
```typescript
import {
  ompRoutingRecord,
  runOmpRouting,
  type OmpModelCandidate,
  type OmpRoutingDecision,
  type OmpRoutingOptions,
  type OmpRoutingResult,
} from "./routing-bridge";
```
add a new import block:
```typescript
import {
  ompVisibilityRecord,
  runOmpVisibility,
  type OmpVisibilityOptions,
  type OmpVisibilityResult,
} from "./visibility-bridge";
```

**4b. Add the extension options field.** Find the `ExtensionOptions`-like interface that already declares `ompRoutingRunner?: (options: OmpRoutingOptions) => Promise<OmpRoutingResult>;` (search for that exact string) and add immediately after it:
```typescript
  ompVisibilityRunner?: (options: OmpVisibilityOptions) => Promise<OmpVisibilityResult>;
```

**4c. Add the runner binding.** Find the line `const routingRunner = options.ompRoutingRunner ?? runOmpRouting;` and add immediately after it:
```typescript
  const visibilityRunner = options.ompVisibilityRunner ?? runOmpVisibility;
```

**4d. Inject at the pre-model hook.** Inside the `pi.on("before_agent_start", async (event, ctx) => { ... })` handler, find this exact existing block (search for `runShadowAutoInject(autoinjectCall(session, event, ctx));` — it is the `else` branch of an `if (aiCfg.mode === "advisory" || aiCfg.mode === "active") { ... } else { void runShadowAutoInject(autoinjectCall(session, event, ctx)); }` statement). Immediately AFTER that `if/else` statement's closing `}` and BEFORE the following `mirror(session, "user_task", { ... }, { cwd: ctxCwd(ctx) });` call, insert:

```typescript
      if (config.home && taskText.trim().length > 0) {
        try {
          const visibilityResult = await visibilityRunner({
            home: config.home,
            task: taskText,
            sessionId: session,
            projectId: process.env.SECOND_BRAIN_PROJECT ?? ctxCwd(ctx) ?? "",
          });
          if (
            visibilityResult.visibility_plan?.mode === "enforced" &&
            Object.keys(visibilityResult.hydrated_instructions).length > 0
          ) {
            const specialistText = Object.entries(visibilityResult.hydrated_instructions)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([, text]) => text)
              .join("\n\n")
              .slice(0, OMP_VISIBILITY_MAX_INJECTED_CHARS);
            aiMessage = mergeActiveStateMessage(aiMessage, {
              content: specialistText,
              details: { visibility_plan_id: visibilityResult.visibility_plan.visibility_plan_id },
            });
          }
          getStore(session)?.append(
            ompVisibilityRecord("omp_visibility_plan", session, {
              mode: visibilityResult.visibility_plan?.mode ?? null,
              selected_skill_ids: visibilityResult.visibility_plan?.selected_skill_ids ?? [],
              hydrated_skill_ids: visibilityResult.visibility_plan?.hydrated_skill_ids ?? [],
              visibility_plan_id: visibilityResult.visibility_plan?.visibility_plan_id ?? null,
              error: visibilityResult.error,
            }),
          );
        } catch {
          // Visibility is advisory: any failure must not block AutoInject/session start.
        }
      }
```

Also add `OMP_VISIBILITY_MAX_INJECTED_CHARS` to the Step 4a import list (add it to the `visibility-bridge` import block: `OMP_VISIBILITY_MAX_INJECTED_CHARS, ompVisibilityRecord, runOmpVisibility, type OmpVisibilityOptions, type OmpVisibilityResult`).

Confirm before writing this block that `taskText`, `aiMessage` (declared `let aiMessage: unknown = undefined;` near the top of the handler), `mergeActiveStateMessage`, `config.home`, `session`, and `ctxCwd` are all already in scope at this exact point in the function (they are used by the surrounding code you are inserting next to — verify by reading the actual current file content around your insertion point before editing, since line numbers shift once earlier tasks' unrelated diffs are accounted for; anchor on the `runShadowAutoInject` search string, not a line number).

This makes visibility injection purely additive: in shadow mode (the shipped default), `visibilityResult.visibility_plan?.mode` is `"shadow"`, so the `if` body never executes and `aiMessage` is unchanged — zero behavior change from today. Only when `config/skills.toml [visibility] mode = "enforced"` does the injected content change.

## Step 5: Add/extend the wiring test

Read `brainstem/prime-extension/tests/wiring.test.ts` first to see its current line count and how it constructs the extension for testing (`ompRoutingRunner` is almost certainly already injectable as a test seam there — find and copy that exact pattern for `ompVisibilityRunner`). Add (in `wiring.test.ts` if it is under ~2500 lines, else in a new `visibility-wiring.test.ts` using the same setup helpers that file exports/uses) three cases:

1. Shadow-mode plan (`ompVisibilityRunner` resolves `{ visibility_plan: { mode: "shadow", ... }, hydrated_instructions: { x: "text" }, error: null }`) never causes `"text"` to appear in the resulting `message`/`systemPrompt` the handler returns.
2. Enforced-mode plan with one hydrated skill (`ompVisibilityRunner` resolves `{ visibility_plan: { mode: "enforced", visibility_plan_id: "vplan-x", ... }, hydrated_instructions: { skill1: "specialist body text" }, error: null }`) produces a result whose `message`/merged content contains `"specialist body text"`.
3. A rejecting/erroring `ompVisibilityRunner` (throws, or resolves `{ visibility_plan: null, hydrated_instructions: {}, error: "BRAIN_VISIBILITY_UNAVAILABLE" }`) produces no injected specialist content and the handler completes without throwing (matches this file's existing fail-open convention for every other advisory call).

## Step 6: Run full TS suite and commit

Run (from `brainstem/prime-extension/`): `npm test -- --run`
Expected: all tests pass, no regressions in any of the other ~25 existing test files.

```bash
git add -- brainstem/prime-extension/src/visibility-bridge.ts brainstem/prime-extension/tests/visibility-bridge.test.ts brainstem/prime-extension/src/index.ts brainstem/prime-extension/tests/wiring.test.ts brainstem/prime-extension/tests/visibility-wiring.test.ts
git commit -m "feat(prime-extension): wire skill-visibility bridge at pre-model hook"
```
(Adjust the `git add` file list to whichever wiring-test file you actually used.)

## Report

Write your full report to `.superpowers/sdd/2026-08-27-p3-16-modular-skill-visibility-implementation/task-3-report.md` with status/files/tests/commit/concerns. Return the same short summary as your final message. If anything about the exact current `index.ts` insertion context does not match what this brief describes (e.g. `aiMessage`/`mergeActiveStateMessage`/`taskText` not in scope where expected), STOP and report NEEDS_CONTEXT with exactly what you found instead — do not improvise a different injection point.
