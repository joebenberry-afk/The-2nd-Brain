/**
 * Phase R3: VMem <-> Prime bridge subprocess contract (spawn args, JSON
 * parsing, fail-open on missing venv / spawn error / unparsable stdout).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock }));

import { runVmemCompactPrep, runVmemHotContext, runVmemStore } from "../src/vmem";

beforeEach(() => {
  execFileMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fakeHome(): Promise<{ home: string; python: string }> {
  const home = await mkdtemp(join(tmpdir(), "sb-vmem-"));
  const bin = join(home, ".venv", "Scripts");
  mkdirSync(bin, { recursive: true });
  writeFileSync(join(bin, "python.exe"), "");
  return { home, python: join(bin, "python.exe") };
}

function fakeSpawn(result: { error?: Error; stdout?: string }) {
  execFileMock.mockImplementation((_py, _args, _opts, cb) => {
    cb(result.error ?? null, result.stdout ?? "");
  });
}

describe("runVmemCompactPrep", () => {
  it("spawns env-clean `vmem compact-prep <session> --json` and parses the result", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    let capturedEnv: Record<string, string | undefined> = {};
    execFileMock.mockImplementation((_py, args, opts, cb) => {
      capturedArgs = args as string[];
      capturedEnv = (opts as { env: Record<string, string | undefined> }).env;
      cb(null, JSON.stringify({ evicted_at_compaction: 3, pinned_preserved: 1 }));
    });

    const result = await runVmemCompactPrep({ home, hostSessionId: "sess-1" });

    expect(capturedArgs).toEqual(["-m", "second_brain", "vmem", "compact-prep", "sess-1", "--json"]);
    expect(capturedEnv.SECOND_BRAIN_HOME).toBe(home);
    expect(capturedEnv.PYTHONHOME).toBeUndefined();
    expect(capturedEnv.PYTHONPATH).toBeUndefined();
    expect(result).toEqual({ ok: true, evictedAtCompaction: 3, pinnedPreserved: 1 });
  });

  it("fails open (ok:false) when no venv exists", async () => {
    const result = await runVmemCompactPrep({
      home: "H:/no-such-home",
      hostSessionId: "sess-1",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error", async () => {
    const { home } = await fakeHome();
    fakeSpawn({ error: new Error("boom") });
    const result = await runVmemCompactPrep({ home, hostSessionId: "sess-1" });
    expect(result).toEqual({ ok: false, error: "boom" });
  });

  it("fails open on unparsable stdout", async () => {
    const { home } = await fakeHome();
    fakeSpawn({ stdout: "not json" });
    const result = await runVmemCompactPrep({ home, hostSessionId: "sess-1" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/unparsable/);
  });
});

describe("runVmemStore", () => {
  it("spawns env-clean `vmem store <session> <kind> <title> --json`, writes content to stdin, and parses obj_id", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    let capturedEnv: Record<string, string | undefined> = {};
    let capturedStdin = "";
    execFileMock.mockImplementation((_py, args, opts, cb) => {
      capturedArgs = args as string[];
      capturedEnv = (opts as { env: Record<string, string | undefined> }).env;
      cb(null, JSON.stringify({ obj_id: "obj-abc123" }));
      return {
        stdin: {
          write: (text: string) => {
            capturedStdin += text;
          },
          end: () => {},
        },
      };
    });

    const result = await runVmemStore({
      home,
      hostSessionId: "sess-3",
      kind: "RESEARCH_RESULT",
      title: "autoinject_delivery",
      content: JSON.stringify({ delivery_id: "pkt-1", packet_tokens: 42 }),
    });

    expect(capturedArgs).toEqual([
      "-m", "second_brain", "vmem", "store", "sess-3", "RESEARCH_RESULT", "autoinject_delivery", "--json",
    ]);
    expect(capturedEnv.SECOND_BRAIN_HOME).toBe(home);
    expect(capturedEnv.PYTHONHOME).toBeUndefined();
    expect(capturedEnv.PYTHONPATH).toBeUndefined();
    expect(capturedStdin).toBe(JSON.stringify({ delivery_id: "pkt-1", packet_tokens: 42 }));
    expect(result).toEqual({ ok: true, objId: "obj-abc123" });
  });

  it("passes --summary and --pinned when provided", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      capturedArgs = args as string[];
      cb(null, JSON.stringify({ obj_id: "obj-xyz" }));
      return { stdin: { write: () => {}, end: () => {} } };
    });

    await runVmemStore({
      home,
      hostSessionId: "sess-4",
      kind: "DECISION",
      title: "pre_compaction_checkpoint",
      content: "{}",
      summary: "short summary",
      pinned: true,
    });

    expect(capturedArgs).toEqual([
      "-m", "second_brain", "vmem", "store", "sess-4", "DECISION", "pre_compaction_checkpoint",
      "--json", "--summary", "short summary", "--pinned",
    ]);
  });

  it("fails open (ok:false) when no venv exists", async () => {
    const result = await runVmemStore({
      home: "H:/no-such-home",
      hostSessionId: "sess-3",
      kind: "GENERIC",
      title: "t",
      content: "c",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error", async () => {
    const { home } = await fakeHome();
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(new Error("boom"), "");
      return { stdin: { write: () => {}, end: () => {} } };
    });
    const result = await runVmemStore({
      home,
      hostSessionId: "sess-3",
      kind: "GENERIC",
      title: "t",
      content: "c",
    });
    expect(result).toEqual({ ok: false, error: "boom" });
  });

  it("fails open on unparsable stdout", async () => {
    const { home } = await fakeHome();
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(null, "not json");
      return { stdin: { write: () => {}, end: () => {} } };
    });
    const result = await runVmemStore({
      home,
      hostSessionId: "sess-3",
      kind: "GENERIC",
      title: "t",
      content: "c",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/unparsable/);
  });

  it("fails open on a non-zero exit (execFile error path, same as compact-prep/hot-context)", async () => {
    const { home } = await fakeHome();
    const exitError = Object.assign(new Error("Command failed"), { code: 2 });
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(exitError, "");
      return { stdin: { write: () => {}, end: () => {} } };
    });
    const result = await runVmemStore({
      home,
      hostSessionId: "sess-3",
      kind: "GENERIC",
      title: "t",
      content: "c",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Command failed");
  });
});

describe("runVmemHotContext", () => {
  it("spawns env-clean `vmem hot-context <session> --budget <n> --json` and parses the result", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      capturedArgs = args as string[];
      cb(null, JSON.stringify({ resident_count: 2, evicted_count: 5, resident_tokens: 900 }));
    });

    const result = await runVmemHotContext({ home, hostSessionId: "sess-2", budgetTokens: 1500 });

    expect(capturedArgs).toEqual([
      "-m", "second_brain", "vmem", "hot-context", "sess-2", "--budget", "1500", "--json",
    ]);
    expect(result).toEqual({ ok: true, residentCount: 2, evictedCount: 5, residentTokens: 900 });
  });

  it("fails open (ok:false) when no venv exists", async () => {
    const result = await runVmemHotContext({
      home: "H:/no-such-home",
      hostSessionId: "sess-2",
      budgetTokens: 1500,
    });
    expect(result.ok).toBe(false);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error", async () => {
    const { home } = await fakeHome();
    fakeSpawn({ error: new Error("boom") });
    const result = await runVmemHotContext({ home, hostSessionId: "sess-2", budgetTokens: 1500 });
    expect(result).toEqual({ ok: false, error: "boom" });
  });
});
