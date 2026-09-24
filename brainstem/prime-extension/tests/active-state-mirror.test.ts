import { EventEmitter } from "node:events";
import { vi, beforeEach, describe, expect, it, type Mock } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
const spawnMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock, spawn: spawnMock }));
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
  startDetachedActiveStateUpdate,
} from "../src/active-state-mirror";

function fakeChild() {
  return { stdin: { write: vi.fn(), end: vi.fn() } };
}

function fakeDetachedChild(): EventEmitter & { unref: Mock } {
  return Object.assign(new EventEmitter(), { unref: vi.fn() });
}

beforeEach(() => {
  execFileMock.mockReset();
  spawnMock.mockReset();
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

  it("hands the shutdown capsule update to a detached child instead of waiting for it", () => {
    const child = fakeDetachedChild();
    spawnMock.mockReturnValue(child);

    const started = startDetachedActiveStateUpdate({
      home: "C:/brain",
      hostSessionId: "omp-1",
      verification: { session_shutdown: "normal" },
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(started).toBe(true);
    expect(spawnMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      [
        "-m", "second_brain", "capsule", "update", "omp-1",
        "--verification-json", JSON.stringify({ session_shutdown: "normal" }),
        "--json",
      ],
      expect.objectContaining({
        cwd: "C:/brain",
        detached: true,
        stdio: "ignore",
        windowsHide: true,
        env: expect.objectContaining({ SECOND_BRAIN_HOME: "C:/brain" }),
      }),
    );
    expect(child.unref).toHaveBeenCalledTimes(1);
    // Without a listener, a later spawn failure would be an uncaught exception.
    expect(child.listenerCount("error")).toBe(1);
  });

  it("fails open when the detached capsule update cannot be started", () => {
    spawnMock.mockImplementation(() => {
      throw new Error("spawn EINVAL");
    });

    expect(
      startDetachedActiveStateUpdate({
        home: "C:/brain",
        hostSessionId: "omp-1",
        verification: { session_shutdown: "normal" },
        python: "C:/brain/.venv/Scripts/python.exe",
      }),
    ).toBe(false);
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

  it("adds no message when the render only echoes the current prompt (PERF-01)", () => {
    const prompt = "  Explain the migration order\nfor schema 28  ";
    const message = activeStateMessage(
      {
        ok: true,
        sessionId: "omp-1",
        renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Explain the migration order\nfor schema 28",
      },
      prompt,
    );
    expect(message).toBeUndefined();
  });

  it("recognizes the echo when the 512-char cut ends on whitespace", () => {
    const prompt = `${"a".repeat(511)} tail words beyond the bound`;
    const stored = "a".repeat(511);
    const message = activeStateMessage(
      {
        ok: true,
        sessionId: "omp-1",
        renderedText: `[SECOND_BRAIN_HOT_CONTEXT]\nObjective: ${stored}`,
      },
      prompt,
    );
    expect(message).toBeUndefined();
  });

  it("drops only the prompt echo and keeps real session state", () => {
    const message = activeStateMessage(
      {
        ok: true,
        sessionId: "omp-1",
        renderedText:
          "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Fix the parser\nActive Decisions: keep FTS5",
      },
      "Fix the parser",
    );
    expect(message?.content).toBe("[SECOND_BRAIN_ACTIVE_STATE]\n[SECOND_BRAIN_HOT_CONTEXT]\nActive Decisions: keep FTS5");
  });

  it("keeps an objective that differs from the current prompt", () => {
    const message = activeStateMessage(
      {
        ok: true,
        sessionId: "omp-1",
        renderedText: "[SECOND_BRAIN_HOT_CONTEXT]\nObjective: Fix the parser everywhere",
      },
      "Fix the parser",
    );
    expect(message?.content).toContain("Objective: Fix the parser everywhere");
  });
});
