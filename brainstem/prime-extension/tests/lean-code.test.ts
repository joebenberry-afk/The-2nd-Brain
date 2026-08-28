import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import factory from "../src/index";
import { resetAutoInjectEmitCache } from "../src/autoinject";
import {
  appendLeanKernel,
  decideLeanRuntime,
  extractRuntimeKernel,
  LEAN_KERNEL_MARKER,
  leanEvalFromSkillsToml,
  leanKernelCacheSize,
  loadLeanKernel,
  resetLeanKernelCache,
  resolveLeanSkillFile,
} from "../src/lean-code";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";
import fs from "node:fs";

/**
 * P3-D lean runtime adapter tests (plan §8, §24.5 "kernel lifecycle",
 * "kernel dedup", "missing/corrupt skill fail-open", "role handling",
 * "Sol hard-orchestrator contract unchanged").
 *
 * Unit tests exercise the pure decision/parse/cache logic of
 * src/lean-code.ts against per-test temp homes; wiring tests run the REAL
 * factory from src/index.ts through a fake ExtensionAPI/ExtensionContext so
 * the before_agent_start integration (ordering, patch return, telemetry
 * records) is proven end-to-end.
 */

/** Exact canonical kernel body (byte-stable, plan §7.4) — copied verbatim from
 * skills/candidates/lean-code/SKILL.md "# Runtime Kernel" section (865 chars). */
const CANONICAL_KERNEL =
  "LEAN CODE: deliver the smallest complete, correct, maintainable change that proves the requested value. Reuse order: config/no-code -> existing behavior -> extend/compose -> stdlib/platform -> installed dependency -> small local code -> new abstraction/tool -> new dependency/service. New abstractions/tools require current need, a stable contract, and net complexity/token reduction; duplication may remain until the pattern is proven. Protect correctness, security, integrity, compatibility, readability, required tests/observability. Search/locate first; read exact evidence; expand only to resolve material uncertainty. Effort and verification scale with risk/reversibility. A small preparatory refactor is allowed only when it directly simplifies the current change. When material requirements are proven, STOP; record unrelated cleanup as simplification debt.";

const SKILL_TEMPLATE = (status: string, kernel: string = CANONICAL_KERNEL): string =>
  `---
name: lean-code
status: ${status}
---

# Purpose

Lean Code minimizes total engineering + agent cost subject to correctness.

# Runtime Kernel

${kernel}
`;

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

const ENV_KEYS = [
  "SECOND_BRAIN_HOME",
  "SECOND_BRAIN_OBSERVABILITY",
  "SECOND_BRAIN_LEAN",
  "SECOND_BRAIN_AUTOINJECT_MODE",
  "ORCHESTRATOR_MODELS",
  "DRIVER_MODELS",
  "WORKER_MODELS",
] as const;
const SAVED_ENV: Record<string, string | undefined> = {};
let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-lean-"));
  for (const key of ENV_KEYS) {
    SAVED_ENV[key] = process.env[key];
    delete process.env[key];
  }
  process.env.SECOND_BRAIN_HOME = tmp;
  resetLeanKernelCache();
  resetAutoInjectEmitCache();
});

afterEach(async () => {
  for (const key of ENV_KEYS) {
    if (SAVED_ENV[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED_ENV[key] as string;
  }
  await rm(tmp, { recursive: true, force: true });
});

function writeSkillsToml(evalValue?: string): string {
  const dir = join(tmp, "config");
  mkdirSync(dir, { recursive: true });
  const file = join(dir, "skills.toml");
  const body =
    evalValue === undefined
      ? "# skills.toml — no [lean] section\nschema_version = 1\n\n[router]\nmax_active = 3\n"
      : `schema_version = 1\n\n[router]\nmax_active = 3\n\n[lean]\neval = "${evalValue}"\n`;
  writeFileSync(file, body);
  return file;
}

function writeSkill(level: "active" | "shadow" | "candidates" | "retired", text: string): string {
  const dir = join(tmp, "skills", level, "lean-code");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), text);
  return join(dir, "SKILL.md");
}
function writeCandidate(kernel: string = CANONICAL_KERNEL): string {
  return writeSkill("candidates", SKILL_TEMPLATE("candidate", kernel));
}

/** Load the factory with a recording fake ExtensionAPI. */
function loadFactory(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => {
      handlers.set(name, handler);
    },
  } as unknown as ExtensionAPI;
  factory(pi);
  return handlers;
}

/** Fake ExtensionContext; session file lives inside the temp dir. */
function makeCtx(overrides: Partial<ExtensionContext> = {}): ExtensionContext {
  return {
    cwd: "C:/work",
    model: { id: "deepseek-v4-flash", provider: "deepseek" },
    sessionManager: {
      getSessionFile: () => join(tmp, "sessions", "lean-test.jsonl"),
    },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE SYSTEM PROMPT",
    signal: undefined,
    hasUI: false,
    ui: undefined,
    ...overrides,
  };
}

function telemetryFile(): string {
  return join(tmp, "telemetry", "agent-performance", "lean-test.jsonl");
}

/** Poll-read the telemetry file until it has at least `minLines` JSONL lines. */
async function waitForLines(minLines: number, timeoutMs = 3000): Promise<Record<string, unknown>[]> {
  const file = telemetryFile();
  const deadline = Date.now() + timeoutMs;
  let last: string[] = [];
  while (Date.now() < deadline) {
    try {
      last = (await readFile(file, "utf8")).split("\n").filter((l) => l.trim().length > 0);
      if (last.length >= minLines) return last.map((l) => JSON.parse(l));
    } catch {
      // file not created yet
    }
    await new Promise((r) => setTimeout(r, 15));
  }
  throw new Error(`timed out waiting for ${minLines} lines in ${file}; got ${last.length}`);
}

async function fireBeforeAgentStart(handlers: Map<string, Handler>, ctx: ExtensionContext, prompt = "hello world") {
  const handler = handlers.get("before_agent_start");
  if (!handler) throw new Error("before_agent_start handler not registered");
  return await handler({ type: "before_agent_start", prompt, systemPrompt: undefined }, ctx);
}

/** Narrow the handler result to the optional systemPrompt patch (wiring asserts). */
function promptOf(result: unknown): string | undefined {
  return (result as { systemPrompt?: string } | undefined)?.systemPrompt;
}

describe("extractRuntimeKernel (canonical single source, plan §7.1)", () => {
  it("parses the canonical # Runtime Kernel section from the real candidate skill (865 chars)", () => {
    const canonicalPath = join(process.cwd(), "..", "..", "skills", "candidates", "lean-code", "SKILL.md");
    expect(existsSync(canonicalPath)).toBe(true);
    const text = fs.readFileSync(canonicalPath, "utf8");
    const kernel = extractRuntimeKernel(text);
    expect(kernel).toBeDefined();
    expect(kernel?.length).toBe(865);
    expect(kernel).toBe(CANONICAL_KERNEL);
  });

  it("returns the section body trimmed and stops at the next markdown heading", () => {
    const text = `# Other

x

# Runtime Kernel

${CANONICAL_KERNEL}

# Next Section

trailing
`;
    expect(extractRuntimeKernel(text)).toBe(CANONICAL_KERNEL);
  });

  it("returns undefined when the heading is absent (corrupt -> fail open)", () => {
    expect(extractRuntimeKernel("# Purpose\nno kernel here")).toBeUndefined();
  });

  it("returns undefined when the section body is empty", () => {
    expect(extractRuntimeKernel("# Runtime Kernel\n\n# Next")).toBeUndefined();
  });
});

describe("resolveLeanSkillFile / loadLeanKernel (lifecycle dirs + in-process cache, plan §8.2/§8.6)", () => {
  it("resolves candidate under skills/candidates", () => {
    writeCandidate();
    const resolved = resolveLeanSkillFile(tmp);
    expect(resolved?.status).toBe("candidate");
    expect(resolved?.path).toBe(join(tmp, "skills", "candidates", "lean-code", "SKILL.md"));
  });

  it("active takes precedence over shadow/candidate", () => {
    writeCandidate();
    writeSkill("shadow", SKILL_TEMPLATE("shadow"));
    writeSkill("active", SKILL_TEMPLATE("active"));
    expect(resolveLeanSkillFile(tmp)?.status).toBe("active");
  });

  it("retired resolves only when no other level exists", () => {
    writeSkill("retired", SKILL_TEMPLATE("retired"));
    expect(resolveLeanSkillFile(tmp)?.status).toBe("retired");
  });

  it("missing skill -> status missing + bounded error (fail open, §8.5)", () => {
    const loaded = loadLeanKernel(tmp);
    expect(loaded.status).toBe("missing");
    expect(loaded.kernel).toBeUndefined();
    expect(loaded.error).toContain("not found");
  });

  it("corrupt skill (no kernel section) -> bounded error, no kernel (fail open, §8.5)", () => {
    writeSkill("candidates", "# Purpose\nno kernel here");
    const loaded = loadLeanKernel(tmp);
    expect(loaded.status).toBe("candidate");
    expect(loaded.kernel).toBeUndefined();
    expect(loaded.error).toContain("Runtime Kernel");
  });

  it("loads the canonical kernel from the candidate file", () => {
    writeCandidate();
    const loaded = loadLeanKernel(tmp);
    expect(loaded.kernel).toBe(CANONICAL_KERNEL);
    expect(loaded.kernel?.length).toBe(865);
  });

  it("serves repeated calls from the in-process cache entry (one entry per resolved path)", () => {
    writeCandidate();
    const first = loadLeanKernel(tmp);
    const second = loadLeanKernel(tmp);
    expect(first.kernel).toBe(CANONICAL_KERNEL);
    expect(second.kernel).toBe(first.kernel);
    expect(leanKernelCacheSize()).toBe(1);
  });

  it("invalidates the cache when the file content changes (size change)", () => {
    writeCandidate();
    loadLeanKernel(tmp);
    writeCandidate("shorter kernel");
    const loaded = loadLeanKernel(tmp);
    expect(loaded.kernel).toBe("shorter kernel");
  });
});

describe("decideLeanRuntime (lifecycle behavior matrix, plan §8.2/§8.3)", () => {
  it("candidate + no env + driver -> omit/off (no runtime influence by default)", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.kernel).toBeUndefined();
  });

  it("candidate + advisory env + driver -> inject/advisory (P3-E eval mode)", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("advisory");
    expect(out.kernel).toBe(CANONICAL_KERNEL);
    expect(out.kernelChars).toBe(865);
  });

  it("candidate + advisory env + worker -> inject/advisory", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("advisory");
  });

  it("candidate + advisory env + normal -> omit/role (kernel inert for non-code roles)", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "normal", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("role");
  });

  it("Sol hard-orchestrator -> omit/role even under advisory (NEVER injected, §8.3)", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "hard_orchestrator", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("role");
  });

  it("active + no env + worker -> inject/active", () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("active");
    expect(out.skillStatus).toBe("active");
  });

  it("active + env off -> omit/off (forces inert)", () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE", env: { SECOND_BRAIN_LEAN: "off" } });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
  });

  it("retired + advisory -> omit/off (retirement disables runtime behavior, §26.1)", () => {
    writeSkill("retired", SKILL_TEMPLATE("retired"));
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
  });

  it("missing skill -> omit/skill-missing + bounded error (fail open, no invented text)", () => {
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("skill-missing");
    expect(out.error).toBeDefined();
    expect(out.kernel).toBeUndefined();
  });

  it("corrupt skill -> omit/skill-missing + bounded error", () => {
    writeSkill("candidates", "# Purpose\nno kernel");
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("skill-missing");
    expect(out.error).toBeDefined();
  });

  it("dedup: base already carries the marker -> omit + dedup_hit, no kernel (plan §8.4)", () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: `BASE\n\n[${LEAN_KERNEL_MARKER}]\n${CANONICAL_KERNEL}` });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("active");
    expect(out.dedupHit).toBe(true);
    expect(out.kernel).toBeUndefined();
  });

  it("inject requires a base prompt (never invent a prompt)", () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: undefined });
    expect(out.decision).toBe("omit");
    expect(out.kernel).toBeUndefined();
  });
});

describe("decideLeanRuntime — FILE-BASED eval gate (config/skills.toml [lean] eval, P3-E fix)", () => {
  it("file advisory (env unset) -> inject/advisory for driver, eval_source=file", () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE" });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("advisory");
    expect(out.mode).toBe("advisory");
    expect(out.evalSource).toBe("file");
    expect(out.kernel).toBe(CANONICAL_KERNEL);
  });

  it("file advisory (env unset) -> inject/advisory for worker, eval_source=file", () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("advisory");
    expect(out.evalSource).toBe("file");
  });

  it("env off OVERRIDES file advisory -> omit/off, eval_source=env", () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE", env: { SECOND_BRAIN_LEAN: "off" } });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.mode).toBe("off");
    expect(out.evalSource).toBe("env");
  });

  it("env advisory OVERRIDES file off -> inject/advisory, eval_source=env", () => {
    writeCandidate();
    writeSkillsToml("off");
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE", env: { SECOND_BRAIN_LEAN: "advisory" } });
    expect(out.decision).toBe("inject");
    expect(out.reason).toBe("advisory");
    expect(out.evalSource).toBe("env");
  });

  it("file off -> omit/off even for an ACTIVE skill", () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    writeSkillsToml("off");
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.mode).toBe("off");
    expect(out.evalSource).toBe("file");
  });

  it("absent [lean] key -> inert (omit/off, no error)", () => {
    writeCandidate();
    writeSkillsToml(undefined); // file exists but has no [lean] section
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.mode).toBeNull();
    expect(out.evalSource).toBeNull();
    expect(out.error).toBeUndefined();
  });

  it("absent file -> inert (omit/off, no error)", () => {
    writeCandidate();
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.mode).toBeNull();
    expect(out.error).toBeUndefined();
  });

  it("invalid file value -> treated as absent -> inert", () => {
    writeCandidate();
    writeSkillsToml("banana");
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.mode).toBeNull();
    expect(out.error).toBeUndefined();
  });

  it("unreadable config file -> fail-open: inert + bounded error (no crash)", () => {
    writeCandidate();
    mkdirSync(join(tmp, "config", "skills.toml"), { recursive: true }); // dir as file -> read error
    const out = decideLeanRuntime({ home: tmp, role: "worker", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
    expect(out.error).toBeDefined();
    expect(out.kernel).toBeUndefined();
  });

  it("file advisory + normal role -> omit/role (role beats file)", () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "normal", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("role");
  });

  it("file advisory + Sol hard-orchestrator -> omit/role (NEVER injected)", () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "hard_orchestrator", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("role");
  });

  it("retired + file advisory -> omit/off (retirement beats advisory)", () => {
    writeSkill("retired", SKILL_TEMPLATE("retired"));
    writeSkillsToml("advisory");
    const out = decideLeanRuntime({ home: tmp, role: "driver", base: "BASE" });
    expect(out.decision).toBe("omit");
    expect(out.reason).toBe("off");
  });

  it("leanEvalFromSkillsToml: parses [lean] eval advisory/off; ignores other sections", () => {
    expect(leanEvalFromSkillsToml('[router]\nmax_active = 3\n\n[lean]\neval = "advisory"\n')).toBe("advisory");
    expect(leanEvalFromSkillsToml('[lean]\neval = "off"\n')).toBe("off");
    expect(leanEvalFromSkillsToml('[lean]\neval = OFF\n')).toBe("off"); // case-insensitive, unquoted
    expect(leanEvalFromSkillsToml('[router]\nmax_active = 3\n')).toBeUndefined();
    expect(leanEvalFromSkillsToml('[lean]\nmax_active = 3\n')).toBeUndefined();
    expect(leanEvalFromSkillsToml("[lean]\neval = 'banana'\n")).toBeUndefined();
  });
});

describe("appendLeanKernel (dedup marker, plan §8.4)", () => {
  it("appends the marker block + canonical kernel verbatim", () => {
    const out = appendLeanKernel("BASE", CANONICAL_KERNEL);
    expect(out).toBe(`BASE

[${LEAN_KERNEL_MARKER}]
${CANONICAL_KERNEL}`);
    expect(out?.includes(LEAN_KERNEL_MARKER)).toBe(true);
    expect(out?.includes(CANONICAL_KERNEL)).toBe(true);
  });

  it("returns the base unchanged when the marker is already present (no double injection)", () => {
    const base = `BASE\n\n[${LEAN_KERNEL_MARKER}]\n${CANONICAL_KERNEL}`;
    expect(appendLeanKernel(base, CANONICAL_KERNEL)).toBe(base);
  });

  it("returns undefined for an undefined/empty base", () => {
    expect(appendLeanKernel(undefined, CANONICAL_KERNEL)).toBeUndefined();
    expect(appendLeanKernel("   ", CANONICAL_KERNEL)).toBeUndefined();
  });
});

describe("wiring: before_agent_start integration (real factory)", () => {
  it("candidate + no env -> no patch and lean_kernel omit/off record", async () => {
    writeCandidate();
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(result).toBeUndefined();
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.reason).toBe("off");
    expect(lean?.skill_status).toBe("candidate");
    expect(lean?.mode).toBeNull();
  });

  it("SECOND_BRAIN_LEAN=advisory + worker -> systemPrompt patch carries the kernel", async () => {
    writeCandidate();
    process.env.SECOND_BRAIN_LEAN = "advisory";
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(promptOf(result)).toContain(LEAN_KERNEL_MARKER);
    expect(promptOf(result)).toContain(CANONICAL_KERNEL);
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("inject");
    expect(lean?.reason).toBe("advisory");
    expect(lean?.role).toBe("worker");
    expect(lean?.kernel_chars).toBe(865);
    expect(lean?.dedup_hit).toBe(false);
  });


  it("uses OMP's effective system-prompt sections for candidate injection", async () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(
      handlers,
      makeCtx({ getSystemPrompt: () => ["BASE SYSTEM PROMPT", "TOOLS"] }),
    );
    expect(promptOf(result)).toContain(LEAN_KERNEL_MARKER);
    expect(promptOf(result)).toContain(CANONICAL_KERNEL);
    const lines = await waitForLines(2);
    const lean = lines.find((line) => line.kind === "lean_kernel");
    expect(lean?.decision).toBe("inject");
    expect(lean?.mode).toBe("advisory");
    expect(lean?.eval_source).toBe("file");
  });
  it("FILE gate: skills.toml [lean] eval=advisory (env unset) -> kernel injected, eval_source=file", async () => {
    writeCandidate();
    writeSkillsToml("advisory");
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(promptOf(result)).toContain(LEAN_KERNEL_MARKER);
    expect(promptOf(result)).toContain(CANONICAL_KERNEL);
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("inject");
    expect(lean?.reason).toBe("advisory");
    expect(lean?.mode).toBe("advisory");
    expect(lean?.eval_source).toBe("file");
  });

  it("FILE gate: env off overrides file advisory at wiring level", async () => {
    writeCandidate();
    writeSkillsToml("advisory");
    process.env.SECOND_BRAIN_LEAN = "off";
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(result).toBeUndefined();
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.reason).toBe("off");
    expect(lean?.eval_source).toBe("env");
  });

  it("advisory + driver -> contract and kernel merged once, kernel AFTER contract (plan §7.4 ordering)", async () => {
    writeCandidate();
    process.env.SECOND_BRAIN_LEAN = "advisory";
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx({ model: { id: "deepseek-v4-pro", provider: "deepseek" } }));
    const prompt = promptOf(result) as string;
    expect(prompt).toContain("second-brain-driver-orchestration-contract");
    expect(prompt.indexOf("second-brain-driver-orchestration-contract")).toBeLessThan(prompt.indexOf(LEAN_KERNEL_MARKER));
    expect(prompt.includes(LEAN_KERNEL_MARKER)).toBe(true);
  });

  it("Sol hard-orchestrator -> Sol contract only, kernel NEVER injected (contract unchanged)", async () => {
    writeCandidate();
    process.env.SECOND_BRAIN_LEAN = "advisory";
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx({ model: { id: "gpt-5.6-sol", provider: "openai" } }));
    expect(promptOf(result)).toContain("You are Sol");
    expect(promptOf(result)).not.toContain(LEAN_KERNEL_MARKER);
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.reason).toBe("role");
  });

  it("missing skill -> fail open: no patch + lean_kernel skill-missing + extension_error", async () => {
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(result).toBeUndefined();
    const lines = await waitForLines(3);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.reason).toBe("skill-missing");
    expect(lines.some((l) => l.kind === "extension_error")).toBe(true);
  });

  it("dedup: base already carries the marker -> exactly one marker in the returned prompt", async () => {
    writeSkill("active", SKILL_TEMPLATE("active"));
    const baseWithKernel = `BASE SYSTEM PROMPT\n\n[${LEAN_KERNEL_MARKER}]\n${CANONICAL_KERNEL}`;
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(
      handlers,
      makeCtx({ getSystemPrompt: () => baseWithKernel, model: { id: "deepseek-v4-pro", provider: "deepseek" } }),
    );
    const prompt = promptOf(result) as string;
    expect(prompt.split(LEAN_KERNEL_MARKER).length - 1).toBe(1);
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.dedup_hit).toBe(true);
  });

  it("no skill + env off -> omit/off, no patch", async () => {
    process.env.SECOND_BRAIN_LEAN = "off";
    const handlers = loadFactory();
    const result = await fireBeforeAgentStart(handlers, makeCtx());
    expect(result).toBeUndefined();
    const lines = await waitForLines(2);
    const lean = lines.find((l) => l.kind === "lean_kernel");
    expect(lean?.decision).toBe("omit");
    expect(lean?.reason).toBe("off");
    expect(lines.some((l) => l.kind === "extension_error")).toBe(false);
  });
});
