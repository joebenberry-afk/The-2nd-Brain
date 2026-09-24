import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileSyncMock = vi.hoisted(() => vi.fn());
const execFileAsyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => {
  // Real execFile resolves {stdout, stderr} through its util.promisify.custom
  // hook, which Node defines as this registered symbol.
  const execFile = Object.assign(vi.fn(), {
    [Symbol.for("nodejs.util.promisify.custom")]: execFileAsyncMock,
  });
  return { execFileSync: execFileSyncMock, execFile };
});
vi.mock("node:fs", () => ({ existsSync: () => true }));

import { runEnvironmentAssessment, runEnvironmentAssessmentSync } from "../src/environment-mirror";

beforeEach(() => {
  execFileSyncMock.mockReset();
  execFileAsyncMock.mockReset();
});

describe("Environment Steward lifecycle bridge", () => {
  it("requests a bounded session-start assessment through the Brain CLI", () => {
    execFileSyncMock.mockReturnValue(
      JSON.stringify({
        environment_steward_id: "envsteward-1234",
        session_id: "omp-1",
        environment_hash: "a".repeat(64),
        completion_eligible: true,
      }),
    );

    const result = runEnvironmentAssessmentSync({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      taskId: "task-1",
      phase: "session_start",
      expectedFields: ["lockfiles"],
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(execFileSyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      [
        "-m", "second_brain", "env", "assess", "C:/repo",
        "--session", "omp-1", "--task-id", "task-1",
        "--phase", "session_start", "--expected-field", "lockfiles", "--json",
      ],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000 }),
    );
    expect(result.ok).toBe(true);
    expect(result.sessionId).toBe("omp-1");
    expect(result.environmentHash).toBe("a".repeat(64));
  });

  it("runs the task-boundary assessment without blocking and parses its evidence", async () => {
    execFileAsyncMock.mockResolvedValue({
      stdout: JSON.stringify({ session_id: "omp-1", environment_hash: "b".repeat(64) }),
      stderr: "",
    });

    const result = await runEnvironmentAssessment({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      taskId: "task-2",
      phase: "task_boundary",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(execFileSyncMock).not.toHaveBeenCalled();
    expect(execFileAsyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      ["-m", "second_brain", "env", "assess", "C:/repo", "--session", "omp-1",
        "--task-id", "task-2", "--phase", "task_boundary", "--json"],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000 }),
    );
    expect(result).toMatchObject({ ok: true, environmentHash: "b".repeat(64) });
  });

  it("reports a failed background assessment as an error, not an empty success", async () => {
    execFileAsyncMock.mockRejectedValue(new Error("spawn timeout"));

    const result = await runEnvironmentAssessment({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      phase: "session_start",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result).toEqual({ ok: false, sessionId: "omp-1", error: "spawn timeout" });
  });
});
