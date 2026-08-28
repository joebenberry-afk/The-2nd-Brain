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
const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({
  execFile: execFileMock,
  execFileSync: execFileSyncMock,
}));

import {
  runVmemClaimPagesSync,
  runVmemCompactPrep,
  runVmemHotContext,
  runVmemListPrePageSync,
  runVmemListSync,
  runVmemResolve,
  runVmemStore,
} from "../src/vmem";

beforeEach(() => {
  execFileMock.mockReset();
  execFileSyncMock.mockReset();
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

  it("Part C: passes --metadata <json> when provided (correlation keys only)", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      capturedArgs = args as string[];
      cb(null, JSON.stringify({ obj_id: "obj-meta" }));
      return { stdin: { write: () => {}, end: () => {} } };
    });

    await runVmemStore({
      home,
      hostSessionId: "sess-5",
      kind: "TOOL_OBSERVATION",
      title: "rtd_artifact",
      content: "{}",
      metadata: { toolCallId: "call-abc" },
    });

    expect(capturedArgs).toEqual([
      "-m", "second_brain", "vmem", "store", "sess-5", "TOOL_OBSERVATION", "rtd_artifact",
      "--json", "--metadata", JSON.stringify({ toolCallId: "call-abc" }),
    ]);
  });

  it("Part C: omits --metadata entirely when not provided (absent flag, unchanged default)", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      capturedArgs = args as string[];
      cb(null, JSON.stringify({ obj_id: "obj-nometa" }));
      return { stdin: { write: () => {}, end: () => {} } };
    });

    await runVmemStore({ home, hostSessionId: "sess-6", kind: "GENERIC", title: "t", content: "c" });

    expect(capturedArgs).not.toContain("--metadata");
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
  it("returns the bounded rendered active state with session identity", async () => {
    const { home } = await fakeHome();
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(null, JSON.stringify({
        session_id: "sess-2",
        rendered_text: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Resume",
        resident_count: 0,
        evicted_count: 0,
        resident_tokens: 12,
      }));
    });

    const result = await runVmemHotContext({ home, hostSessionId: "sess-2", budgetTokens: 256 });

    expect(result.sessionId).toBe("sess-2");
    expect(result.renderedText).toContain("Objective: Resume");
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

describe("runVmemListSync (Part B/C — the only synchronous subprocess call)", () => {
  it("spawns env-clean `vmem list <session> --state <state> --json` (sync) and parses objects", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    let capturedEnv: Record<string, string | undefined> = {};
    execFileSyncMock.mockImplementation((_py, args, opts) => {
      capturedArgs = args as string[];
      capturedEnv = (opts as { env: Record<string, string | undefined> }).env;
      return JSON.stringify([
        { obj_id: "obj-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } },
        { obj_id: "obj-2", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-1" } },
      ]);
    });

    const result = runVmemListSync({ home, hostSessionId: "sess-1", state: "EVICTED" });

    expect(capturedArgs).toEqual([
      "-m", "second_brain", "vmem", "list", "sess-1", "--json", "--state", "EVICTED",
    ]);
    expect(capturedEnv.SECOND_BRAIN_HOME).toBe(home);
    expect(capturedEnv.PYTHONHOME).toBeUndefined();
    expect(capturedEnv.PYTHONPATH).toBeUndefined();
    expect(result).toEqual({
      ok: true,
      objects: [
        { objId: "obj-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } },
        { objId: "obj-2", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-1" } },
      ],
    });
  });

  it("omits --state when not provided", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileSyncMock.mockImplementation((_py, args) => {
      capturedArgs = args as string[];
      return "[]";
    });
    runVmemListSync({ home, hostSessionId: "sess-2" });
    expect(capturedArgs).toEqual(["-m", "second_brain", "vmem", "list", "sess-2", "--json"]);
  });

  it("objects missing obj_id/kind are dropped; missing/non-object metadata defaults to {}", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() =>
      JSON.stringify([
        { obj_id: "obj-1", kind: "RESEARCH_RESULT" }, // no metadata -> {}
        { obj_id: "obj-2", kind: "GENERIC", metadata: ["not", "an", "object"] }, // -> {}
        { kind: "GENERIC", metadata: {} }, // missing obj_id -> dropped
        { obj_id: "obj-4" }, // missing kind -> dropped
        "not even an object", // dropped
      ]),
    );
    const result = runVmemListSync({ home, hostSessionId: "sess-3" });
    expect(result.ok).toBe(true);
    expect(result.objects).toEqual([
      { objId: "obj-1", kind: "RESEARCH_RESULT", metadata: {} },
      { objId: "obj-2", kind: "GENERIC", metadata: {} },
    ]);
  });

  it("fails open (ok:false) when no venv exists, never throws", async () => {
    const result = runVmemListSync({ home: "H:/no-such-home", hostSessionId: "sess-1" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileSyncMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error (e.g. timeout), never throws", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() => {
      throw new Error("Command timed out");
    });
    const result = runVmemListSync({ home, hostSessionId: "sess-1" });
    expect(result).toEqual({ ok: false, error: "Command timed out" });
  });

  it("fails open on unparsable/non-array stdout, never throws", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() => "not json");
    const bad1 = runVmemListSync({ home, hostSessionId: "sess-1" });
    expect(bad1.ok).toBe(false);

    execFileSyncMock.mockImplementation(() => JSON.stringify({ not: "an array" }));
    const bad2 = runVmemListSync({ home, hostSessionId: "sess-1" });
    expect(bad2).toEqual({ ok: false, error: "list returned non-array output" });
  });
});

describe("runVmemListPrePageSync (Defect B — RC4 proactive-paging-repair pass)", () => {
  it("spawns env-clean `vmem list <session> --json` (sync, NO --state filter) and parses residency_state/pinned", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    let capturedEnv: Record<string, string | undefined> = {};
    execFileSyncMock.mockImplementation((_py, args, opts) => {
      capturedArgs = args as string[];
      capturedEnv = (opts as { env: Record<string, string | undefined> }).env;
      return JSON.stringify([
        {
          obj_id: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1" },
          residency_state: "RESIDENT",
          pinned: false,
        },
        {
          obj_id: "obj-2",
          kind: "TOOL_OBSERVATION",
          metadata: { toolCallId: "call-1" },
          residency_state: "FAULTED_IN",
          pinned: true,
        },
      ]);
    });

    const result = runVmemListPrePageSync({ home, hostSessionId: "sess-1" });

    expect(capturedArgs).toEqual(["-m", "second_brain", "vmem", "list", "sess-1", "--json"]);
    expect(capturedEnv.SECOND_BRAIN_HOME).toBe(home);
    expect(capturedEnv.PYTHONHOME).toBeUndefined();
    expect(capturedEnv.PYTHONPATH).toBeUndefined();
    expect(result).toEqual({
      ok: true,
      objects: [
        {
          objId: "obj-1",
          kind: "RESEARCH_RESULT",
          metadata: { deliveryId: "del-1" },
          residencyState: "RESIDENT",
          pinned: false,
        },
        {
          objId: "obj-2",
          kind: "TOOL_OBSERVATION",
          metadata: { toolCallId: "call-1" },
          residencyState: "FAULTED_IN",
          pinned: true,
        },
      ],
    });
  });

  it("missing residency_state/pinned default to empty-string/false, never crash", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() =>
      JSON.stringify([{ obj_id: "obj-1", kind: "RESEARCH_RESULT", metadata: {} }]),
    );
    const result = runVmemListPrePageSync({ home, hostSessionId: "sess-1" });
    expect(result.ok).toBe(true);
    expect(result.objects).toEqual([
      { objId: "obj-1", kind: "RESEARCH_RESULT", metadata: {}, residencyState: "", pinned: false },
    ]);
  });

  it("fails open (ok:false) when no venv exists, never throws", async () => {
    const result = runVmemListPrePageSync({ home: "H:/no-such-home", hostSessionId: "sess-1" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileSyncMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error and on unparsable/non-array stdout, never throws", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() => {
      throw new Error("Command timed out");
    });
    expect(runVmemListPrePageSync({ home, hostSessionId: "sess-1" })).toEqual({
      ok: false,
      error: "Command timed out",
    });

    execFileSyncMock.mockImplementation(() => "not json");
    expect(runVmemListPrePageSync({ home, hostSessionId: "sess-1" }).ok).toBe(false);

    execFileSyncMock.mockImplementation(() => JSON.stringify({ not: "an array" }));
    expect(runVmemListPrePageSync({ home, hostSessionId: "sess-1" })).toEqual({
      ok: false,
      error: "list returned non-array output",
    });
  });
});

describe("runVmemClaimPagesSync (Defect B — the ONE claim call per context event)", () => {
  it("spawns env-clean `vmem claim-pages <session> --json`, sends candidates via stdin JSON, and parses the claimed obj_id list", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    let capturedEnv: Record<string, string | undefined> = {};
    let capturedInput: string | undefined;
    execFileSyncMock.mockImplementation((_py, args, opts) => {
      capturedArgs = args as string[];
      capturedEnv = (opts as { env: Record<string, string | undefined> }).env;
      capturedInput = (opts as { input?: string }).input;
      return JSON.stringify(["obj-1"]);
    });

    const result = runVmemClaimPagesSync({
      home,
      hostSessionId: "sess-1",
      candidates: [
        { objId: "obj-1", kind: "RESEARCH_RESULT" },
        { objId: "obj-2", kind: "TOOL_OBSERVATION" },
      ],
    });

    expect(capturedArgs).toEqual(["-m", "second_brain", "vmem", "claim-pages", "sess-1", "--json"]);
    expect(capturedEnv.SECOND_BRAIN_HOME).toBe(home);
    expect(capturedEnv.PYTHONHOME).toBeUndefined();
    expect(capturedEnv.PYTHONPATH).toBeUndefined();
    expect(JSON.parse(capturedInput ?? "{}")).toEqual({
      candidates: [
        { obj_id: "obj-1", kind: "RESEARCH_RESULT" },
        { obj_id: "obj-2", kind: "TOOL_OBSERVATION" },
      ],
    });
    expect(result).toEqual({ ok: true, claimedObjIds: ["obj-1"] });
  });

  it("empty claimedObjIds (claim confirmed nothing) is a valid, non-error result", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() => JSON.stringify([]));
    const result = runVmemClaimPagesSync({ home, hostSessionId: "sess-1", candidates: [{ objId: "obj-1", kind: "RESEARCH_RESULT" }] });
    expect(result).toEqual({ ok: true, claimedObjIds: [] });
  });

  it("fails open (ok:false) when no venv exists, never throws", async () => {
    const result = runVmemClaimPagesSync({ home: "H:/no-such-home", hostSessionId: "sess-1", candidates: [] });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileSyncMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error and on unparsable/non-array stdout, never throws", async () => {
    const { home } = await fakeHome();
    execFileSyncMock.mockImplementation(() => {
      throw new Error("Command timed out");
    });
    expect(
      runVmemClaimPagesSync({ home, hostSessionId: "sess-1", candidates: [{ objId: "obj-1", kind: "RESEARCH_RESULT" }] }),
    ).toEqual({ ok: false, error: "Command timed out" });

    execFileSyncMock.mockImplementation(() => "not json");
    expect(
      runVmemClaimPagesSync({ home, hostSessionId: "sess-1", candidates: [{ objId: "obj-1", kind: "RESEARCH_RESULT" }] }).ok,
    ).toBe(false);

    execFileSyncMock.mockImplementation(() => JSON.stringify({ not: "an array" }));
    expect(
      runVmemClaimPagesSync({ home, hostSessionId: "sess-1", candidates: [{ objId: "obj-1", kind: "RESEARCH_RESULT" }] }),
    ).toEqual({ ok: false, error: "claim-pages returned non-array output" });
  });
});

describe("runVmemResolve (Part D — explicit fault-in bridge, exported/tested, not auto-wired)", () => {
  it("spawns env-clean `vmem resolve <session> <obj_id> --json` and parses a success result", async () => {
    const { home } = await fakeHome();
    let capturedArgs: string[] = [];
    execFileMock.mockImplementation((_py, args, _opts, cb) => {
      capturedArgs = args as string[];
      cb(null, JSON.stringify({ ok: true, content: "resolved text", resolution: "artifact" }));
    });

    const result = await runVmemResolve({ home, hostSessionId: "sess-1", objId: "obj-1" });

    expect(capturedArgs).toEqual(["-m", "second_brain", "vmem", "resolve", "sess-1", "obj-1", "--json"]);
    expect(result).toEqual({ ok: true, content: "resolved text", resolution: "artifact", error: undefined });
  });

  it("parses a structured {ok:false} result even when the CLI exits non-zero", async () => {
    const { home } = await fakeHome();
    const exitError = Object.assign(new Error("Command failed"), { code: 1 });
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(exitError, JSON.stringify({ ok: false, error: "delivery not found: del-x" }));
    });

    const result = await runVmemResolve({ home, hostSessionId: "sess-1", objId: "obj-1" });
    expect(result).toEqual({ ok: false, content: undefined, resolution: undefined, error: "delivery not found: del-x" });
  });

  it("fails open (ok:false) when no venv exists, never throws", async () => {
    const result = await runVmemResolve({ home: "H:/no-such-home", hostSessionId: "sess-1", objId: "obj-1" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/no brain venv/);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("fails open on subprocess error with unparsable stdout, never throws", async () => {
    const { home } = await fakeHome();
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(new Error("spawn failed"), "");
    });
    const result = await runVmemResolve({ home, hostSessionId: "sess-1", objId: "obj-1" });
    expect(result).toEqual({ ok: false, error: "spawn failed" });
  });

  it("fails open on completely unparsable stdout with no spawn error, never throws", async () => {
    const { home } = await fakeHome();
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(null, "not json at all");
    });
    const result = await runVmemResolve({ home, hostSessionId: "sess-1", objId: "obj-1" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/unparsable/);
  });
});
