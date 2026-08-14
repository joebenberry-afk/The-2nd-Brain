import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  defaultBrainHome,
  loadConfig,
  observabilityDisabledByEnv,
  resolveBrainHome,
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
