/**
 * Trace-safety gate: a throwing diagnostic thunk must never escape the guarded
 * trace helper (the reviewed I1 counterexample), an unwritable target must not
 * escape either, and an absent target must leave the thunk unevaluated.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { __testTraceRoute } from "../../src/task/worktree";

const original = process.env.OM_CANARY_BOOT;

beforeEach(() => {
  delete process.env.OM_CANARY_BOOT;
});

afterEach(() => {
  if (original === undefined) delete process.env.OM_CANARY_BOOT;
  else process.env.OM_CANARY_BOOT = original;
});

describe("canary trace safety", () => {
  test("a throwing diagnostic thunk cannot escape the guarded helper", () => {
    const dir = mkdtempSync(join(tmpdir(), "canary-trace-"));
    process.env.OM_CANARY_BOOT = join(dir, "boot.txt");
    let evaluated = false;
    expect(() =>
      __testTraceRoute(() => {
        evaluated = true;
        throw new Error("diagnostic blew up");
      }),
    ).not.toThrow();
    expect(evaluated).toBe(true);
  });

  test("an unwritable trace target cannot escape", () => {
    const dir = mkdtempSync(join(tmpdir(), "canary-trace-"));
    process.env.OM_CANARY_BOOT = join(dir, "missing-dir", "boot.txt");
    expect(() => __testTraceRoute("cleanup:stop:error:probe")).not.toThrow();
  });

  test("no trace target leaves the thunk unevaluated", () => {
    let evaluated = false;
    __testTraceRoute(() => {
      evaluated = true;
      return "probe";
    });
    expect(evaluated).toBe(false);
  });
});
