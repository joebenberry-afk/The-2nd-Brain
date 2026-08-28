import { vi, beforeEach, describe, expect, it } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock, execFileSync: execFileSyncMock }));
const hotContextMock = vi.hoisted(() => vi.fn());
vi.mock("../src/vmem", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/vmem")>();
  return { ...actual, runVmemHotContext: hotContextMock };
});
vi.mock("node:fs", () => ({ existsSync: () => true }));

import {
  activeStateMessage,
  renderActiveState,
  runActiveStateEnsure,
  runActiveStateUpdate,
  runActiveStateUpdateSync,
} from "../src/active-state-mirror";

function fakeChild() {
  return { stdin: { write: vi.fn(), end: vi.fn() } };
}

beforeEach(() => {
  execFileMock.mockReset();
  execFileSyncMock.mockReset();
  hotContextMock.mockReset();
});
describe("active-state lifecycle bridge", () => {
  it("ensures a bounded capsule through the Brain CLI", async () => {
    const child = fakeChild();
    execFileMock.mockImplementation((_python, args, _options, callback) => {
      expect(args).toEqual([
        "-m", "second_brain", "capsule", "ensure", "omp-1",
        "A".repeat(512), "--next-action", "next", "--json",
      ]);
      callback(null, JSON.stringify({ session_id: "omp-1", changed: true, capsule_bytes: 200 }));
      return child;
    });

    const result = await runActiveStateEnsure({
      home: "C:/brain",
      hostSessionId: "omp-1",
      objective: "A".repeat(900),
      nextAction: "next",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result.ok).toBe(true);
    expect(result.sessionId).toBe("omp-1");
  });

  it("updates only bounded meaningful state", async () => {
    execFileMock.mockImplementation((_python, args, _options, callback) => {
      expect(args).toEqual([
        "-m", "second_brain", "capsule", "update", "omp-1",
        "--add-decision", "reuse VMem",
        "--add-question", "resume point",
        "--json",
      ]);
      callback(null, JSON.stringify({ session_id: "omp-1", changed: true }));
      return fakeChild();
    });

    const result = await runActiveStateUpdate({
      home: "C:/brain",
      hostSessionId: "omp-1",
      decisions: ["reuse VMem"],
      openQuestions: ["resume point"],
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result.ok).toBe(true);
  });

  it("persists shutdown state synchronously", () => {
    execFileSyncMock.mockReturnValue(JSON.stringify({ session_id: "omp-1", changed: true }));
    const result = runActiveStateUpdateSync({
      home: "C:/brain",
      hostSessionId: "omp-1",
      verification: { session_shutdown: "normal" },
      python: "C:/brain/.venv/Scripts/python.exe",
    });
    expect(result.ok).toBe(true);
    expect(execFileSyncMock).toHaveBeenCalled();
  });

  it("rejects rendered state from a different session", async () => {
    hotContextMock.mockResolvedValue({
      ok: true,
      sessionId: "other",
      renderedText: "stale",
    });

    const result = await renderActiveState({
      home: "C:/brain",
      hostSessionId: "omp-1",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result.ok).toBe(false);
    expect(result.error).toContain("session mismatch");
  });

  it("builds a bounded model-visible message from existing VMem output", () => {
    const message = activeStateMessage({
      ok: true,
      sessionId: "omp-1",
      renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Resume task",
    });
    expect(message?.customType).toBe("brain.active-state");
    expect(message?.content).toContain("Objective: Resume task");
    expect(message?.display).toBe(false);
  });
});
