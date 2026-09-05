import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT,
  CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES,
  CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET,
  VMEM_DEFAULT_BUDGET_TOKENS,
  contextPagingConfigFromContextToml,
  defaultBrainHome,
  loadConfig,
  loadContextPagingConfig,
  loadVmemConfig,
  observabilityDisabledByEnv,
  resolveBrainHome,
  rtdConfigFromContextToml,
  rtdThresholdFromConfig,
  thresholdCharsFromContextToml,
  vmemAdmissionConfigFromContextToml,
  vmemConfigFromContextToml,
} from "../src/config";

const ENV_KEYS = ["SECOND_BRAIN_OBSERVABILITY", "SECOND_BRAIN_HOME", "USERPROFILE", "HOME"] as const;
const saved: Partial<Record<(typeof ENV_KEYS)[number], string | undefined>> = {};

let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-cfg-"));
  for (const k of ENV_KEYS) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
});

afterEach(async () => {
  for (const k of ENV_KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k] as string;
  }
  await rm(tmp, { recursive: true, force: true });
});

describe("config gate", () => {
  it("env SECOND_BRAIN_OBSERVABILITY in {off,0,false,no} disables (case-insensitive)", () => {
    for (const value of ["off", "OFF", "0", "false", "False", "no", "No", "  off  "]) {
      process.env.SECOND_BRAIN_OBSERVABILITY = value;
      expect(observabilityDisabledByEnv()).toBe(true);
    }
  });

  it("unset or unrecognized SECOND_BRAIN_OBSERVABILITY does not disable", () => {
    delete process.env.SECOND_BRAIN_OBSERVABILITY;
    expect(observabilityDisabledByEnv()).toBe(false);
    for (const value of ["on", "1", "yes", "true", "enabled"]) {
      process.env.SECOND_BRAIN_OBSERVABILITY = value;
      expect(observabilityDisabledByEnv()).toBe(false);
    }
  });

  it("env gate wins even when a valid brain home exists", async () => {
    await mkdir(join(tmp, "home"), { recursive: true });
    process.env.SECOND_BRAIN_HOME = join(tmp, "home");
    process.env.SECOND_BRAIN_OBSERVABILITY = "off";
    expect(loadConfig()).toMatchObject({ enabled: false, home: null, telemetryDir: null });
  });

  it("missing brain home -> silently disabled", () => {
    process.env.SECOND_BRAIN_HOME = join(tmp, "does-not-exist");
    expect(loadConfig()).toMatchObject({ enabled: false, home: null, telemetryDir: null });
  });

  it("existing brain home -> enabled with telemetry dir", async () => {
    await mkdir(join(tmp, "brain"), { recursive: true });
    process.env.SECOND_BRAIN_HOME = join(tmp, "brain");
    expect(loadConfig()).toMatchObject({
      enabled: true,
      home: join(tmp, "brain"),
      telemetryDir: join(tmp, "brain", "telemetry", "agent-performance"),
    });
  });

  it("default brain home is %USERPROFILE%\Documents\The-Second-Brain when SECOND_BRAIN_HOME unset", async () => {
    process.env.USERPROFILE = tmp;
    await mkdir(join(tmp, "Documents", "The-Second-Brain"), { recursive: true });
    expect(defaultBrainHome()).toBe(join(tmp, "Documents", "The-Second-Brain"));
    expect(resolveBrainHome()).toBe(join(tmp, "Documents", "The-Second-Brain"));
  });
});

// ---------------------------------------------------------------------------
// Phase 12: context.toml [rtd] threshold_chars parsing + file read
// ---------------------------------------------------------------------------

describe("thresholdCharsFromContextToml (tiny TOML subset)", () => {
  it("reads threshold_chars inside the [rtd] section", () => {
    expect(
      thresholdCharsFromContextToml("schema_version = 1\n\n[rtd]\nthreshold_chars = 500\n"),
    ).toBe(500);
  });

  it("ignores other sections, other keys, and inline comments", () => {
    const text = [
      "[governor]",
      "threshold_chars = 999",
      "",
      "[rtd]",
      "enabled = false",
      "threshold_chars = 700  # RTD size gate",
      "whitelist_tools = [\"bash\"]",
      "",
      "[reserve]",
      "threshold_chars = 42",
    ].join("\n");
    expect(thresholdCharsFromContextToml(text)).toBe(700);
  });

  it("returns undefined when absent, in another section, or invalid", () => {
    expect(thresholdCharsFromContextToml("[other]\nthreshold_chars = 5")).toBeUndefined();
    expect(thresholdCharsFromContextToml("[rtd]\nenabled = false")).toBeUndefined();
    expect(thresholdCharsFromContextToml("[rtd]\nthreshold_chars = \"abc\"")).toBeUndefined();
    expect(thresholdCharsFromContextToml("[rtd]\nthreshold_chars = -5")).toBeUndefined();
    expect(thresholdCharsFromContextToml("not toml at all")).toBeUndefined();
    expect(thresholdCharsFromContextToml("")).toBeUndefined();
  });

  it("does not mistake a sub-section or prefixed section for [rtd]", () => {
    expect(thresholdCharsFromContextToml("[rtdx]\nthreshold_chars = 1\n[rtd]")).toBeUndefined();
  });
});

describe("rtdThresholdFromConfig (file read, never throws)", () => {
  it("reads <home>/config/context.toml [rtd] threshold_chars", async () => {
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-rtd-"));
    try {
      await mkdir(join(home, "config"), { recursive: true });
      await writeFile(join(home, "config", "context.toml"), "[rtd]\nthreshold_chars = 123\n", "utf8");
      expect(rtdThresholdFromConfig(home)).toBe(123);
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });

  it("returns undefined for null home, missing file, or invalid value", async () => {
    expect(rtdThresholdFromConfig(null)).toBeUndefined();
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-rtd-"));
    try {
      expect(rtdThresholdFromConfig(home)).toBeUndefined(); // no config dir
      await mkdir(join(home, "config"), { recursive: true });
      await writeFile(join(home, "config", "context.toml"), "[rtd]\nthreshold_chars = \"x\"\n", "utf8");
      expect(rtdThresholdFromConfig(home)).toBeUndefined();
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });
});

describe("vmemConfigFromContextToml (Phase R3)", () => {
  it("defaults to disabled with the default budget when [vmem] is absent", () => {
    expect(vmemConfigFromContextToml("")).toEqual({
      enabled: false,
      budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS,
    });
    expect(vmemConfigFromContextToml("[rtd]\nenabled = true\n")).toEqual({
      enabled: false,
      budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS,
    });
  });

  it("reads enabled and budget_tokens inside the [vmem] section", () => {
    expect(
      vmemConfigFromContextToml("[vmem]\nenabled = true\nbudget_tokens = 2500\n"),
    ).toEqual({ enabled: true, budgetTokens: 2500 });
  });

  it("ignores other sections, other keys, and inline comments", () => {
    const text = [
      "[rtd]",
      "enabled = true",
      "budget_tokens = 999",
      "",
      "[vmem]",
      "enabled = true  # live pilot only",
      "budget_tokens = 3000",
      "",
      "[reserve]",
      "budget_tokens = 42",
    ].join("\n");
    expect(vmemConfigFromContextToml(text)).toEqual({ enabled: true, budgetTokens: 3000 });
  });

  it("treats an invalid budget_tokens as absent (keeps the default)", () => {
    expect(vmemConfigFromContextToml("[vmem]\nenabled = true\nbudget_tokens = -5\n")).toEqual({
      enabled: true,
      budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS,
    });
    expect(vmemConfigFromContextToml("[vmem]\nbudget_tokens = \"x\"\n")).toEqual({
      enabled: false,
      budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS,
    });
  });
});

describe("loadVmemConfig (file read, never throws)", () => {
  it("reads <home>/config/context.toml [vmem] enabled/budget_tokens", async () => {
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-vmem-"));
    try {
      await mkdir(join(home, "config"), { recursive: true });
      await writeFile(
        join(home, "config", "context.toml"),
        "[vmem]\nenabled = true\nbudget_tokens = 4096\n",
        "utf8",
      );
      expect(loadVmemConfig(home)).toEqual({ enabled: true, budgetTokens: 4096 });
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });

  it("returns safe defaults for null home or missing file", async () => {
    expect(loadVmemConfig(null)).toEqual({ enabled: false, budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS });
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-vmem-"));
    try {
      expect(loadVmemConfig(home)).toEqual({ enabled: false, budgetTokens: VMEM_DEFAULT_BUDGET_TOKENS });
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });
});

describe("contextPagingConfigFromContextToml (Part B/E — conservative defaults)", () => {
  it("defaults are safe (enabled=false) when the section is absent", () => {
    expect(contextPagingConfigFromContextToml("[vmem]\nenabled = true\n")).toEqual({
      enabled: false,
      pinRecentMessages: CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES,
      residentTokenBudget: CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET,
      maxPagesPerContextEvent: CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT,
    });
  });

  it("parses enabled/pin_recent_messages/resident_token_budget/max_pages_per_context_event", () => {
    const cfg = contextPagingConfigFromContextToml(
      "[context_paging]\nenabled = true\npin_recent_messages = 10\n" +
        "resident_token_budget = 999\nmax_pages_per_context_event = 7\n",
    );
    expect(cfg).toEqual({
      enabled: true,
      pinRecentMessages: 10,
      residentTokenBudget: 999,
      maxPagesPerContextEvent: 7,
    });
  });

  it("invalid values fall back to the documented defaults", () => {
    const cfg = contextPagingConfigFromContextToml(
      "[context_paging]\nenabled = banana\npin_recent_messages = -1\n" +
        'resident_token_budget = "nope"\nmax_pages_per_context_event = -5\n',
    );
    expect(cfg).toEqual({
      enabled: false,
      pinRecentMessages: CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES,
      residentTokenBudget: CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET,
      maxPagesPerContextEvent: CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT,
    });
  });
});

describe("loadContextPagingConfig (file read, never throws)", () => {
  it("reads <home>/config/context.toml [context_paging]", async () => {
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-ctxpaging-"));
    try {
      await mkdir(join(home, "config"), { recursive: true });
      await writeFile(
        join(home, "config", "context.toml"),
        "[context_paging]\nenabled = true\npin_recent_messages = 8\n" +
          "resident_token_budget = 2000\nmax_pages_per_context_event = 2\n",
        "utf8",
      );
      expect(loadContextPagingConfig(home)).toEqual({
        enabled: true,
        pinRecentMessages: 8,
        residentTokenBudget: 2000,
        maxPagesPerContextEvent: 2,
      });
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });

  it("returns safe defaults for null home or missing file", async () => {
    expect(loadContextPagingConfig(null)).toEqual({
      enabled: false,
      pinRecentMessages: CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES,
      residentTokenBudget: CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET,
      maxPagesPerContextEvent: CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT,
    });
    const home = await mkdtemp(join(tmpdir(), "sb-cfg-ctxpaging-"));
    try {
      expect(loadContextPagingConfig(home)).toEqual({
        enabled: false,
        pinRecentMessages: CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES,
        residentTokenBudget: CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET,
        maxPagesPerContextEvent: CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT,
      });
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  });
});

describe("repository P3.3 runtime gates", () => {
  it("enables the existing RTD, VMem admission, and context-paging path", async () => {
    const text = await readFile(join(process.cwd(), "..", "..", "config", "context.toml"), "utf8");
    expect(rtdConfigFromContextToml(text).enabled).toBe(true);
    expect(vmemAdmissionConfigFromContextToml(text).enabled).toBe(true);
    expect(contextPagingConfigFromContextToml(text).enabled).toBe(true);
  });
});
