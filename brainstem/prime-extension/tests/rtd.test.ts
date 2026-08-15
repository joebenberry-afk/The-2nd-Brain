import { describe, expect, it } from "vitest";
import {
  commandFromInput,
  parseThreshold,
  rtdEligibility,
  rtdShadowRecord,
  serializedSize,
  shouldDistill,
} from "../src/rtd";
import { measureContent, type ContentMeasurement } from "../src/sensors";

const BIG = "x".repeat(9000); // > 8000 default threshold
const SMALL = "small output"; // < 8000 default threshold

const M_BIG = measureContent(BIG);
const M_SMALL = measureContent(SMALL);

function bashEvent(command: string): { toolName: string; input: { command: string } } {
  return { toolName: "bash", input: { command } };
}

describe("rtdEligibility (decided without touching content)", () => {
  it("accepts bash commands starting with a distill prefix (case-insensitive)", () => {
    expect(rtdEligibility("bash", { command: "pytest -q tests/" })).toBe("ok");
    expect(rtdEligibility("bash", { command: "git status" })).toBe("ok");
    expect(rtdEligibility("bash", { command: "rg pattern src/" })).toBe("ok");
    expect(rtdEligibility("bash", { command: "grep -rn foo" })).toBe("ok");
    expect(rtdEligibility("bash", { command: "Pytest -q" })).toBe("ok");
    expect(rtdEligibility("bash", { command: "  rg -n foo ." })).toBe("ok");
  });

  it("rejects non-bash tools (reason tool) without reading any content", () => {
    expect(rtdEligibility("ipython", { code: "print(1)" })).toBe("tool");
    expect(rtdEligibility("edit", { path: "x.ts" })).toBe("tool");
  });

  it("rejects commands outside the prefix list and exact first-token matches only", () => {
    expect(rtdEligibility("bash", { command: "ls -la" })).toBe("command");
    expect(rtdEligibility("bash", { command: "node script.js" })).toBe("command");
    expect(rtdEligibility("bash", { command: "gitx status" })).toBe("command");
    expect(rtdEligibility("bash", { command: "pytestx -q" })).toBe("command");
    expect(rtdEligibility("bash", { command: "" })).toBe("command");
    expect(rtdEligibility("bash", {})).toBe("command");
    expect(rtdEligibility("bash", undefined)).toBe("command");
  });
});

describe("shouldDistill", () => {
  it("eligibility is checked BEFORE the measurement is used: ineligible tool/command short-circuit even with a huge size", () => {
    const huge: ContentMeasurement = { serializedChars: 999_999, outputBytes: 999_999 };
    expect(shouldDistill({ toolName: "ipython", input: { code: "x" } }, 8000, huge)).toEqual({
      trigger: false,
      reason: "tool",
    });
    expect(shouldDistill({ toolName: "edit", input: { path: "x" } }, 8000, huge)).toEqual({
      trigger: false,
      reason: "tool",
    });
    expect(shouldDistill(bashEvent("ls -la"), 8000, huge)).toEqual({
      trigger: false,
      reason: "command",
    });
    expect(shouldDistill(bashEvent("node script.js"), 8000, huge)).toEqual({
      trigger: false,
      reason: "command",
    });
  });

  it("triggers when serializedChars > threshold and eligibility passes", () => {
    expect(shouldDistill(bashEvent("pytest -q tests/"), 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent("git status"), 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent("rg pattern src/"), 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
    expect(shouldDistill(bashEvent("grep -rn foo"), 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
  });

  it("does not trigger below or at the threshold (reason size) — legacy char-length boundary", () => {
    expect(shouldDistill(bashEvent("pytest -q"), 8000, M_SMALL)).toEqual({ trigger: false, reason: "size" });
    // serialized size is JSON.stringify length: 7998 chars -> 8000 exactly, not > threshold
    expect(shouldDistill(bashEvent("pytest -q"), 8000, measureContent("y".repeat(7998)))).toEqual({
      trigger: false,
      reason: "size",
    });
    // 8000 chars -> JSON length 8002 -> triggers (legacy metric, quotes count)
    expect(shouldDistill(bashEvent("pytest -q"), 8000, measureContent("y".repeat(8000)))).toEqual({
      trigger: true,
      reason: "ok",
    });
  });

  it("size semantics stay the legacy JSON character length for Unicode/escaping", () => {
    // "héllo" -> JSON '"héllo"' = 7 chars, UTF-8 bytes = 6. Decision uses chars.
    expect(shouldDistill(bashEvent("pytest"), 6, measureContent("héllo"))).toEqual({
      trigger: true,
      reason: "ok",
    });
    expect(shouldDistill(bashEvent("pytest"), 7, measureContent("héllo"))).toEqual({
      trigger: false,
      reason: "size",
    });
    // quote/backslash escaping: JSON '"a\"b"' = 6 chars vs 3 raw bytes
    expect(shouldDistill(bashEvent("pytest"), 3, measureContent('a"b'))).toEqual({
      trigger: true,
      reason: "ok",
    });
    expect(shouldDistill(bashEvent("pytest"), 6, measureContent('a"b'))).toEqual({
      trigger: false,
      reason: "size",
    });
  });

  it("handles content shape variants: string content and block arrays", () => {
    // small block array -> size reason
    const blocks = [{ type: "text", text: "line1" }, { type: "text", text: "line2" }];
    expect(shouldDistill(bashEvent("pytest"), 8000, measureContent(blocks))).toEqual({ trigger: false, reason: "size" });
    // large block array -> triggers
    const bigBlocks = Array.from({ length: 2000 }, (_, i) => ({ type: "text", text: `block ${i} content` }));
    expect(shouldDistill(bashEvent("pytest -q"), 8000, measureContent(bigBlocks))).toEqual({ trigger: true, reason: "ok" });
  });

  it("unserializable content never triggers (serializedChars 0)", () => {
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;
    const m = measureContent(circular);
    expect(m.serializedChars).toBe(0);
    expect(shouldDistill(bashEvent("pytest"), 8000, m)).toEqual({ trigger: false, reason: "size" });
    // even a tiny threshold cannot trigger: legacy metric is 0, not the fallback text
    expect(shouldDistill(bashEvent("pytest"), 0, m)).toEqual({ trigger: false, reason: "size" });
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

  it("serializedSize measures JSON length and survives garbage (legacy helper)", () => {
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

  it("returns null when not triggered (ineligible before measurement: wrong tool/command, small size)", () => {
    expect(
      rtdShadowRecord({ ...base, tool: "bash", input: { command: "pytest" }, measurement: M_SMALL, active: false }),
    ).toBeNull();
    // Ineligible cases return null even with a huge measurement: eligibility
    // is decided first, so content is never even measured for RTD.
    const huge: ContentMeasurement = { serializedChars: 999_999, outputBytes: 999_999 };
    expect(
      rtdShadowRecord({ ...base, tool: "ipython", input: { command: "pytest" }, measurement: huge, active: false }),
    ).toBeNull();
    expect(
      rtdShadowRecord({ ...base, tool: "bash", input: { command: "ls -la" }, measurement: huge, active: false }),
    ).toBeNull();
  });

  it("builds a shadow record when triggered (size = legacy serialized chars, no substitution)", () => {
    const rec = rtdShadowRecord({
      ...base,
      tool: "bash",
      input: { command: "pytest -q" },
      measurement: M_BIG,
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
      input: { command: "git status" },
      measurement: M_BIG,
      active: true,
    });
    expect(rec).toMatchObject({
      reason: "would-substitute",
      substitution: "enabled-not-implemented",
      would_trigger: true,
    });
  });
});

describe("single eligibility decision (no re-read, no divergence)", () => {
  it("rtdShadowRecord with precomputed eligibility never re-reads the input command", () => {
    let reads = 0;
    const input = {
      get command() {
        reads += 1;
        return "pytest -q";
      },
    };
    const rec = rtdShadowRecord({
      session: "s1",
      id: "call-1",
      tool: "bash",
      input,
      eligibility: "ok", // precomputed by the real handler BEFORE measurement
      measurement: M_BIG,
      threshold: 8000,
      active: false,
    });
    expect(rec).not.toBeNull();
    expect(rec!.would_trigger).toBe(true);
    expect(reads).toBe(0); // decision came from the passed value; input untouched
  });

  it("rtdShadowRecord compat path (no precomputed eligibility) reads the input EXACTLY once", () => {
    let reads = 0;
    const input = {
      get command() {
        reads += 1;
        return "pytest -q";
      },
    };
    const rec = rtdShadowRecord({
      session: "s1",
      id: "call-1",
      tool: "bash",
      input,
      measurement: M_BIG,
      threshold: 8000,
      active: false,
    });
    expect(rec).not.toBeNull();
    expect(reads).toBe(1); // derived once and passed through — never a second read
  });

  it("precomputed eligibility is authoritative: cannot diverge even if the getter would now say ok", () => {
    let reads = 0;
    const input = {
      get command() {
        reads += 1;
        return "pytest -q";
      },
    };
    const rec = rtdShadowRecord({
      session: "s1",
      id: "call-1",
      tool: "bash",
      input,
      eligibility: "tool", // stale precomputed decision must win
      measurement: M_BIG,
      threshold: 8000,
      active: false,
    });
    expect(rec).toBeNull();
    expect(reads).toBe(0); // input never re-read, decision cannot flip
  });

  it("shouldDistill: eligibility default derives once; passed eligibility reads nothing", () => {
    let reads = 0;
    const input = {
      get command() {
        reads += 1;
        return "pytest";
      },
    };
    expect(shouldDistill({ toolName: "bash", input }, 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
    expect(reads).toBe(1); // derived exactly once (default)

    reads = 0;
    expect(shouldDistill({ toolName: "bash", input }, 8000, M_BIG, "ok")).toEqual({ trigger: true, reason: "ok" });
    expect(reads).toBe(0); // precomputed: no input read at all
  });
});
