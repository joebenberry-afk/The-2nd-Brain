import { describe, expect, it } from "vitest";
import {
  commandFromInput,
  parseThreshold,
  rtdShadowRecord,
  serializedSize,
  shouldDistill,
} from "../src/rtd";

const BIG = "x".repeat(9000); // > 8000 default threshold
const SMALL = "small output"; // < 8000 default threshold

function bashEvent(content: unknown, command = "pytest -q"): {
  toolName: string;
  content: unknown;
  input: { command: string };
} {
  return { toolName: "bash", content, input: { command } };
}

describe("shouldDistill", () => {
  it("triggers when size > threshold, tool is bash, command starts with a distill prefix", () => {
    expect(shouldDistill(bashEvent(BIG, "pytest -q tests/"), 8000)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent(BIG, "git status"), 8000)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent(BIG, "rg pattern src/"), 8000)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent(BIG, "grep -rn foo"), 8000)).toEqual({ trigger: true, reason: "ok" });
  });

  it("does not trigger below or at the threshold (reason size)", () => {
    expect(shouldDistill(bashEvent(SMALL, "pytest -q"), 8000)).toEqual({ trigger: false, reason: "size" });
    // serialized size is JSON.stringify length: 7998 chars -> 8000 exactly, not > threshold
    expect(shouldDistill(bashEvent("y".repeat(7998), "pytest -q"), 8000)).toEqual({
      trigger: false,
      reason: "size",
    });
  });

  it("does not trigger for non-bash tools (reason tool)", () => {
    expect(
      shouldDistill({ toolName: "ipython", content: BIG, input: { code: "print(1)" } }, 8000),
    ).toEqual({ trigger: false, reason: "tool" });
    expect(
      shouldDistill({ toolName: "edit", content: BIG, input: { path: "x.ts" } }, 8000),
    ).toEqual({ trigger: false, reason: "tool" });
  });

  it("does not trigger for bash commands outside the prefix list (reason command)", () => {
    expect(shouldDistill(bashEvent(BIG, "ls -la"), 8000)).toEqual({ trigger: false, reason: "command" });
    expect(shouldDistill(bashEvent(BIG, "node script.js"), 8000)).toEqual({
      trigger: false,
      reason: "command",
    });
  });

  it("command match is case-insensitive", () => {
    for (const command of ["Pytest -q", "GIT log", "RG foo", "GREP -r x", "pYtEsT", "Git status"]) {
      expect(shouldDistill(bashEvent(BIG, command), 8000), command).toEqual({ trigger: true, reason: "ok" });
    }
  });

  it("handles content shape variants: string content and block arrays", () => {
    // string content above threshold
    expect(shouldDistill(bashEvent(BIG, "pytest -q"), 8000)).toEqual({ trigger: true, reason: "ok" });
    // small block array -> size reason
    const blocks = [{ type: "text", text: "line1" }, { type: "text", text: "line2" }];
    expect(shouldDistill(bashEvent(blocks, "pytest"), 8000)).toEqual({ trigger: false, reason: "size" });
    // large block array -> triggers
    const bigBlocks = Array.from({ length: 2000 }, (_, i) => ({ type: "text", text: `block ${i} content` }));
    expect(shouldDistill(bashEvent(bigBlocks, "pytest -q"), 8000)).toEqual({ trigger: true, reason: "ok" });
  });

  it("unserializable content never triggers (size 0)", () => {
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;
    expect(shouldDistill(bashEvent(circular, "pytest"), 8000)).toEqual({ trigger: false, reason: "size" });
  });
});

describe("parseThreshold", () => {
  it("parses ints; defaults on missing/invalid/negative", () => {
    expect(parseThreshold("8000")).toBe(8000);
    expect(parseThreshold("123")).toBe(123);
    expect(parseThreshold("12abc")).toBe(12);
    expect(parseThreshold(undefined)).toBe(8000);
    expect(parseThreshold("abc")).toBe(8000);
    expect(parseThreshold("-5")).toBe(8000);
  });
});

describe("helpers", () => {
  it("commandFromInput extracts only non-empty string commands", () => {
    expect(commandFromInput({ command: "pytest" })).toBe("pytest");
    expect(commandFromInput({ command: 42 })).toBeUndefined();
    expect(commandFromInput({ command: "" })).toBeUndefined();
    expect(commandFromInput(null)).toBeUndefined();
    expect(commandFromInput(undefined)).toBeUndefined();
    expect(commandFromInput("nope")).toBeUndefined();
    expect(commandFromInput({})).toBeUndefined();
  });

  it("serializedSize measures JSON length and survives garbage", () => {
    expect(serializedSize("hello")).toBe(7); // JSON.stringify("hello") === '"hello"' (7 chars)
    expect(serializedSize([1, 2])).toBe(5); // "[1,2]"
    expect(serializedSize(undefined)).toBe(0);
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(serializedSize(circular)).toBe(0);
  });
});

describe("rtdShadowRecord", () => {
  const base = { session: "s1", id: "call-1", threshold: 8000 };

  it("returns null when not triggered (small size / wrong tool)", () => {
    expect(
      rtdShadowRecord({ ...base, tool: "bash", content: SMALL, input: { command: "pytest" }, active: false }),
    ).toBeNull();
    expect(
      rtdShadowRecord({ ...base, tool: "ipython", content: BIG, input: { command: "pytest" }, active: false }),
    ).toBeNull();
    expect(
      rtdShadowRecord({ ...base, tool: "bash", content: BIG, input: { command: "ls -la" }, active: false }),
    ).toBeNull();
  });

  it("builds a shadow record when triggered (reason ok, no substitution)", () => {
    const rec = rtdShadowRecord({
      ...base,
      tool: "bash",
      content: BIG,
      input: { command: "pytest -q" },
      active: false,
    });
    expect(rec).toMatchObject({
      v: 2,
      kind: "rtd_shadow",
      session: "s1",
      tool: "bash",
      id: "call-1",
      size: serializedSize(BIG),
      threshold: 8000,
      would_trigger: true,
      reason: "ok",
    });
    expect(typeof rec?.ts).toBe("string");
    expect(rec).not.toHaveProperty("substitution");
  });

  it("active mode records intent without substituting", () => {
    const rec = rtdShadowRecord({
      ...base,
      tool: "bash",
      content: BIG,
      input: { command: "git status" },
      active: true,
    });
    expect(rec).toMatchObject({
      reason: "would-substitute",
      substitution: "enabled-not-implemented",
      would_trigger: true,
    });
  });
});


describe("shouldDistill command-token semantics", () => {
  const big = { content: [{ type: "text", text: "x".repeat(100) }] };
  it("matches first token exactly", () => {
    expect(shouldDistill({ ...big, toolName: "bash", input: { command: "git status --short" } }, 50)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill({ ...big, toolName: "bash", input: { command: "gitx status" } }, 50)).toEqual({ trigger: false, reason: "command" });
    expect(shouldDistill({ ...big, toolName: "bash", input: { command: "  rg -n foo ." } }, 50)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill({ ...big, toolName: "bash", input: { command: "pytestx -q" } }, 50)).toEqual({ trigger: false, reason: "command" });
  });
});
