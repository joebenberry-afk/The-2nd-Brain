import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildRtdBlock,
  cliRtdPreserver,
  commandFromInput,
  distillText,
  parseThreshold,
  pytestEvidence,
  resolveToolClass,
  rtdEligibility,
  rtdShadowRecord,
  runRtd,
  serializedSize,
  shouldDistill,
  textFromContent,
  type RtdPreserver,
} from "../src/rtd";
import { rtdConfigFromContextToml } from "../src/config";
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

  it("rejects tool names that map to no known canonical class (reason tool) without reading any content", () => {
    expect(rtdEligibility("edit", { path: "x.ts" })).toBe("tool");
    expect(rtdEligibility("websearch", { query: "x" })).toBe("tool");
  });

  it("Phase C: a plain-Python ipython call (no %%bash header) is NOT eligible — reason command, not tool", () => {
    // ipython DOES map to the canonical "bash" class (resolveToolClass), so
    // this is a "command" rejection (no command found), never "tool".
    expect(rtdEligibility("ipython", { code: "print(1)" })).toBe("command");
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

describe("resolveToolClass (Phase C: real host-tool normalization)", () => {
  it("real bash tool: unchanged behavior, canonical class bash", () => {
    expect(resolveToolClass("bash", { command: "pytest -q" })).toEqual({
      toolClass: "bash",
      command: "pytest -q",
    });
    expect(resolveToolClass("bash", {})).toEqual({ toolClass: "bash", command: undefined });
  });

  it("ipython with a %%bash header: extracts the next non-empty line as the command", () => {
    expect(resolveToolClass("ipython", { code: "%%bash\npytest -q tests/" })).toEqual({
      toolClass: "bash",
      command: "pytest -q tests/",
    });
    // leading/trailing blank lines around the header and the command are tolerated
    expect(resolveToolClass("ipython", { code: "\n  %%bash  \n\n  git status\n" })).toEqual({
      toolClass: "bash",
      command: "git status",
    });
  });

  it("ipython plain Python (no %%bash header): tool class bash, no command", () => {
    expect(resolveToolClass("ipython", { code: "print(1)\nx = 2" })).toEqual({ toolClass: "bash" });
    expect(resolveToolClass("ipython", { code: "" })).toEqual({ toolClass: "bash" });
    expect(resolveToolClass("ipython", {})).toEqual({ toolClass: "bash" });
  });

  it("unknown/unmapped tool names resolve to no canonical class", () => {
    expect(resolveToolClass("edit", { path: "x.ts" })).toEqual({ toolClass: null });
    expect(resolveToolClass(42, undefined)).toEqual({ toolClass: null });
  });

  it("rtdEligibility: ipython %%bash pytest at eligible size -> ok", () => {
    const ev = { toolName: "ipython", input: { code: "%%bash\npytest -q tests/" } };
    expect(rtdEligibility(ev.toolName, ev.input)).toBe("ok");
    expect(shouldDistill(ev, 8000, M_BIG)).toEqual({ trigger: true, reason: "ok" });
  });

  it("rtdEligibility: ipython %%bash pytest BELOW threshold -> size", () => {
    const ev = { toolName: "ipython", input: { code: "%%bash\npytest -q tests/" } };
    expect(shouldDistill(ev, 8000, M_SMALL)).toEqual({ trigger: false, reason: "size" });
  });

  it("rtdEligibility: ipython %%bash curl (not a whitelisted command) -> command", () => {
    expect(rtdEligibility("ipython", { code: "%%bash\ncurl https://example.com" })).toBe("command");
  });

  it("rtdEligibility: plain-Python ipython call (no %%bash header) -> command, not tool", () => {
    expect(rtdEligibility("ipython", { code: "import os\nprint(os.getcwd())" })).toBe("command");
  });

  it("regression: the real bash tool path is unchanged end-to-end", () => {
    expect(rtdEligibility("bash", { command: "pytest -q tests/" })).toBe("ok");
    expect(shouldDistill(bashEvent("pytest -q tests/"), 8000, M_BIG)).toEqual({
      trigger: true,
      reason: "ok",
    });
    expect(shouldDistill(bashEvent("pytest -q tests/"), 8000, M_SMALL)).toEqual({
      trigger: false,
      reason: "size",
    });
  });
});

describe("shouldDistill", () => {
  it("eligibility is checked BEFORE the measurement is used: ineligible tool/command short-circuit even with a huge size", () => {
    const huge: ContentMeasurement = { serializedChars: 999_999, outputBytes: 999_999 };
    // ipython maps to class "bash" but "x" has no %%bash header -> "command".
    expect(shouldDistill({ toolName: "ipython", input: { code: "x" } }, 8000, huge)).toEqual({
      trigger: false,
      reason: "command",
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

describe("parseThreshold (Phase 12 ladder: env -> context.toml -> default)", () => {
  // Hermetic brain home: env is isolated per test, so parseThreshold's file
  // lookup never touches a real brain.
  const ENV_KEYS = ["SECOND_BRAIN_HOME", "SECOND_BRAIN_RTD_THRESHOLD"] as const;
  const saved: Record<string, string | undefined> = {};
  let home: string;

  beforeEach(async () => {
    home = await mkdtemp(join(tmpdir(), "sb-rtd-thr-"));
    for (const key of ENV_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
    process.env.SECOND_BRAIN_HOME = home;
  });

  afterEach(async () => {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key] as string;
    }
    await rm(home, { recursive: true, force: true });
  });

  async function writeContextToml(rtdBody: string): Promise<void> {
    await mkdir(join(home, "config"), { recursive: true });
    await writeFile(
      join(home, "config", "context.toml"),
      `schema_version = 1\n\n[rtd]\n${rtdBody}\n`,
      "utf8",
    );
  }

  it("parses ints from env; defaults on missing/invalid/negative env without a file", () => {
    expect(parseThreshold("8000")).toBe(8000);
    expect(parseThreshold("123")).toBe(123);
    expect(parseThreshold("12abc")).toBe(12);
    expect(parseThreshold(undefined)).toBe(8000); // no context.toml -> default
    expect(parseThreshold("abc")).toBe(8000);
    expect(parseThreshold("-5")).toBe(8000);
  });

  it("context.toml [rtd] threshold_chars drives the threshold when env is unset", async () => {
    await writeContextToml("threshold_chars = 500");
    expect(parseThreshold(undefined)).toBe(500);
  });

  it("env SECOND_BRAIN_RTD_THRESHOLD beats the file value", async () => {
    await writeContextToml("threshold_chars = 500");
    process.env.SECOND_BRAIN_RTD_THRESHOLD = "100";
    expect(parseThreshold(process.env.SECOND_BRAIN_RTD_THRESHOLD)).toBe(100);
    expect(parseThreshold("100")).toBe(100);
  });

  it("invalid env value falls through to the file value", async () => {
    await writeContextToml("threshold_chars = 500");
    expect(parseThreshold("abc")).toBe(500);
    expect(parseThreshold("-5")).toBe(500);
  });

  it("invalid or absent file value falls back to the default", async () => {
    await writeContextToml("threshold_chars = -5");
    expect(parseThreshold(undefined)).toBe(8000);
    await writeContextToml("threshold_chars = \"nope\"");
    expect(parseThreshold(undefined)).toBe(8000);
    await writeContextToml("whitelist_tools = [\"bash\"]"); // other keys only
    expect(parseThreshold(undefined)).toBe(8000);
  });

  it("missing context.toml falls back to the default", async () => {
    expect(parseThreshold(undefined)).toBe(8000);
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

// ---------------------------------------------------------------------------
// P3-F substitution surface (plan §11)
// ---------------------------------------------------------------------------

const RTD_CFG_ON = rtdConfigFromContextToml(
  '[rtd]\nenabled = true\nthreshold_chars = 8000\nmax_distill_chars = 2000\n' +
    'whitelist_tools = ["bash"]\nwhitelist_commands = ["pytest", "git", "rg", "grep"]\n',
);

function fakePreserver(ok: boolean): RtdPreserver {
  return {
    preserve: async (_raw) =>
      ok
        ? {
            sha256: "a".repeat(64),
            handle: "[brain-artifact:sha256:" + "a".repeat(64) + "]",
          }
        : null,
    verify: async () => ok,
  };
}

const baseRtdOptions = {
  session: "s-rtd",
  tool: "bash",
  id: "rtd-1",
  input: { command: "pytest -q tests/" },
  content: [{ type: "text", text: BIG }],
  isError: false,
  measurement: M_BIG,
  threshold: 8000,
  cfg: RTD_CFG_ON,
};

describe("rtdConfigFromContextToml (plan §11.3 — documented fields become real)", () => {
  it("parses enabled/threshold/max/whitelists from [rtd]", () => {
    const cfg = rtdConfigFromContextToml(
      "[rtd]\nenabled = true\nthreshold_chars = 12345\nmax_distill_chars = 999\n" +
        'whitelist_tools = ["bash", "ipython"]\nwhitelist_commands = ["pytest", "git"]\n',
    );
    expect(cfg.enabled).toBe(true);
    expect(cfg.thresholdChars).toBe(12345);
    expect(cfg.maxDistillChars).toBe(999);
    expect(cfg.whitelistTools).toEqual(["bash", "ipython"]);
    expect(cfg.whitelistCommands).toEqual(["pytest", "git"]);
  });

  it("defaults are safe (enabled=false) when absent/invalid", () => {
    const absent = rtdConfigFromContextToml("[router]\nmax_active = 3\n");
    expect(absent.enabled).toBe(false);
    expect(absent.thresholdChars).toBe(8000);
    expect(absent.maxDistillChars).toBe(2000);
    expect(absent.whitelistTools).toEqual(["bash"]);
    expect(absent.whitelistCommands).toEqual(["pytest", "git", "rg", "grep"]);
    const invalid = rtdConfigFromContextToml("[rtd]\nenabled = banana\nmax_distill_chars = -5\n");
    expect(invalid.enabled).toBe(false);
    expect(invalid.maxDistillChars).toBe(2000);
  });

  it("whitelists drive eligibility (config wins over fixed defaults) — canonical classes only (Phase C)", () => {
    // whitelist_tools stays about the canonical CLASS name ("bash"), not the
    // real host tool name — resolveToolClass maps BOTH the real "bash" tool
    // and "ipython" %%bash cells onto that same class.
    const cfg = rtdConfigFromContextToml(
      '[rtd]\nwhitelist_tools = ["bash"]\nwhitelist_commands = ["pytest"]\n',
    );
    expect(rtdEligibility("bash", { command: "pytest -q" }, cfg)).toBe("ok");
    expect(rtdEligibility("bash", { command: "git status" }, cfg)).toBe("command");
    expect(rtdEligibility("ipython", { code: "%%bash\npytest -q" }, cfg)).toBe("ok");
    expect(rtdEligibility("ipython", { code: "%%bash\ngit status" }, cfg)).toBe("command");
    // A whitelist that excludes the "bash" class rejects BOTH real names.
    const noBash = rtdConfigFromContextToml('[rtd]\nwhitelist_tools = ["nothing"]\n');
    expect(rtdEligibility("bash", { command: "pytest -q" }, noBash)).toBe("tool");
    expect(rtdEligibility("ipython", { code: "%%bash\npytest -q" }, noBash)).toBe("tool");
  });
});

describe("textFromContent (plan §11.8 — binary/non-text never distilled)", () => {
  it("extracts concatenated text blocks", () => {
    expect(textFromContent([{ type: "text", text: "a" }, { type: "text", text: "b" }])).toBe("ab");
  });
  it("returns undefined for image blocks / mixed / empty / non-arrays", () => {
    expect(textFromContent([{ type: "image", image: "x" }])).toBeUndefined();
    expect(textFromContent([{ type: "text", text: "a" }, { type: "image", image: "x" }])).toBeUndefined();
    expect(textFromContent([])).toBeUndefined();
    expect(textFromContent([{ type: "text" }])).toBeUndefined();
    expect(textFromContent([42])).toBeUndefined();
  });
});

describe("distillText + pytestEvidence (deterministic, plan §11.5/§11.6)", () => {
  it("head/tail with omitted marker, bounded to maxChars", () => {
    const out = distillText(BIG + "TAILMARKER", { commandClass: "git", maxChars: 2000, isError: false });
    expect(out.visibleChars).toBeLessThanOrEqual(2000);
    expect(out.text).toContain("… [");
    expect(out.text).toContain(" chars omitted] …");
    expect(out.text.endsWith("TAILMARKER")).toBe(true);
    expect(out.text.startsWith("x".repeat(700))).toBe(true); // 40% head budget (marker reserved)
  });

  it("error results keep a longer tail (conservative, §11.7)", () => {
    const ok = distillText(BIG, { commandClass: "git", maxChars: 2000, isError: false });
    const err = distillText(BIG, { commandClass: "git", maxChars: 2000, isError: true });
    const tailOf = (s: { text: string }) => s.text.slice(s.text.indexOf("… ["));
    expect(tailOf(err).length).toBeGreaterThan(tailOf(ok).length);
  });

  it("small text is returned unchanged (no truncation)", () => {
    const out = distillText("tiny", { commandClass: "git", maxChars: 2000, isError: false });
    expect(out).toEqual({ text: "tiny", visibleChars: 4 });
  });

  it("pytest evidence: failures section + failing test names + summary", () => {
    const raw = [
      "collected 5 items",
      "tests/test_a.py F",
      "",
      "=== FAILURES ===",
      "____ test_broken ____",
      "    assert 1 == 2",
      "    AssertionError",
      "=== short test summary info ===",
      "FAILED tests/test_a.py::test_broken",
      "=== 1 failed, 4 passed in 0.5s ===",
    ].join("\n");
    const extra = pytestEvidence(raw);
    expect(extra).toContain("=== FAILURES ===");
    expect(extra).toContain("FAILING TESTS (1):");
    expect(extra).toContain("test_broken");
    expect(extra).toContain("1 failed, 4 passed");
    expect(pytestEvidence("no failures here")).toBeUndefined();
  });

  it("buildRtdBlock carries the full metadata + reopen pointer", () => {
    const block = buildRtdBlock({
      rawChars: 9000, visibleChars: 1900, sha256: "ab".repeat(32), artifactRef: "[brain-artifact:sha256:ab]",
      commandClass: "git", isError: false, evidence: "head\n...\ntail", lineCount: 12,
    });
    expect(block).toContain("[SECOND_BRAIN_RTD]");
    expect(block).toContain("original_chars=9000");
    expect(block).toContain("visible_chars=1900");
    expect(block).toContain("saved_chars=7100");
    expect(block).toContain("lines=12");
    expect(block).toContain("artifact=[brain-artifact:sha256:ab]");
    expect(block).toContain("truncated=true");
    expect(block).toContain("Full exact result preserved at");
    expect(block).toContain("artifact expand");
  });
});

describe("runRtd (substitution orchestrator, plan §11)", () => {
  it("shadow path (enabled=false): record only, no patch", async () => {
    const cfgOff = { ...RTD_CFG_ON, enabled: false };
    const out = await runRtd({ ...baseRtdOptions, cfg: cfgOff, preserver: fakePreserver(true) });
    expect(out.patch).toBeUndefined();
    expect(out.record?.would_trigger).toBe(true);
    expect(out.record?.distilled).toBeUndefined();
  });

  it("below threshold: no record, no patch", async () => {
    const out = await runRtd({
      ...baseRtdOptions,
      content: [{ type: "text", text: SMALL }],
      measurement: M_SMALL,
      preserver: fakePreserver(true),
    });
    expect(out.record).toBeNull();
    expect(out.patch).toBeUndefined();
  });

  it("ineligible tool/command: no record, no patch", async () => {
    const out = await runRtd({
      ...baseRtdOptions,
      tool: "ipython",
      input: { code: "print(1)" },
      preserver: fakePreserver(true),
    });
    expect(out.record).toBeNull();
    expect(out.patch).toBeUndefined();
  });

  it("preservation FAILURE -> original content unchanged, distilled=false record (plan §11.4)", async () => {
    const out = await runRtd({ ...baseRtdOptions, preserver: fakePreserver(false) });
    expect(out.patch).toBeUndefined();
    expect(out.record?.distilled).toBe(false);
    expect(out.record?.original_chars).toBe(9000);
    expect(out.record?.command_class).toBe("pytest");
  });

  it("verify FAILURE after store -> original content unchanged", async () => {
    const preserver: RtdPreserver = {
      preserve: async () => ({ sha256: "a".repeat(64), handle: "[brain-artifact:sha256:" + "a".repeat(64) + "]" }),
      verify: async () => false,
    };
    const out = await runRtd({ ...baseRtdOptions, preserver });
    expect(out.patch).toBeUndefined();
    expect(out.record?.distilled).toBe(false);
  });

  it("success: patch carries the deterministic block; record carries sizes/ref/class (no raw content)", async () => {
    const out = await runRtd({ ...baseRtdOptions, preserver: fakePreserver(true) });
    expect(out.patch).toBeDefined();
    const text = out.patch!.content[0]!.text;
    expect(text).toContain("[SECOND_BRAIN_RTD]");
    expect(text).toContain("original_chars=9000");
    expect(text).toContain("command=pytest");
    expect(text).toContain("error_status=false");
    expect(text).not.toContain(BIG); // raw content never leaks into the block
    expect(out.record?.distilled).toBe(true);
    expect(out.record?.original_chars).toBe(9000);
    expect(out.record!.visible_chars!).toBeLessThan(3000);
    expect(out.record!.saved_chars!).toBeGreaterThan(6000);
    expect(out.record?.artifact_ref).toContain("brain-artifact:sha256:");
    expect(out.record?.command_class).toBe("pytest");
    expect(out.record?.error_status).toBe(false);
  });

  it("binary content (image block) is NEVER distilled even when enabled", async () => {
    const out = await runRtd({
      ...baseRtdOptions,
      content: [{ type: "image", image: "x".repeat(9000) }],
      preserver: fakePreserver(true),
    });
    expect(out.patch).toBeUndefined();
  });
});

describe("cliRtdPreserver spawn contract (fail-open)", () => {
  it("no venv -> preservation fails (null/false), never throws", async () => {
    const preserver = cliRtdPreserver({ home: tmpdir(), session: "s" });
    const preserved = await preserver.preserve("raw");
    expect(preserved).toBeNull();
    expect(await preserver.verify("a".repeat(64), "raw")).toBe(false);
  });
});
