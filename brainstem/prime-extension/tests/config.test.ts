import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  VMEM_DEFAULT_BUDGET_TOKENS,
  defaultBrainHome,
  loadConfig,
  loadVmemConfig,
  observabilityDisabledByEnv,
  resolveBrainHome,
  rtdThresholdFromConfig,
  thresholdCharsFromContextToml,
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
    expect(loadConfig()).toEqual({ enabled: false, home: null, telemetryDir: null });
  });

  it("missing brain home -> silently disabled", () => {
    process.env.SECOND_BRAIN_HOME = join(tmp, "does-not-exist");
    expect(loadConfig()).toEqual({ enabled: false, home: null, telemetryDir: null });
  });

  it("existing brain home -> enabled with telemetry dir", async () => {
    await mkdir(join(tmp, "brain"), { recursive: true });
    process.env.SECOND_BRAIN_HOME = join(tmp, "brain");
    expect(loadConfig()).toEqual({
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
