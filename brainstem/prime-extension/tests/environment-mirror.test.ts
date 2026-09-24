import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileAsyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => {
  // Real execFile resolves {stdout, stderr} through its util.promisify.custom
  // hook, which Node defines as this registered symbol.
  const execFile = Object.assign(vi.fn(), {
    [Symbol.for("nodejs.util.promisify.custom")]: execFileAsyncMock,
  });
  return { execFile };
});
vi.mock("node:fs", () => ({ existsSync: () => true }));

import { runEnvironmentAssessment } from "../src/environment-mirror";

beforeEach(() => {
  execFileAsyncMock.mockReset();
});

describe("Environment Steward lifecycle bridge", () => {
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

    expect(execFileAsyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      ["-m", "second_brain", "env", "assess", "C:/repo", "--session", "omp-1",
        "--task-id", "task-2", "--phase", "task_boundary", "--json"],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000 }),
    );
    expect(result).toMatchObject({ ok: true, environmentHash: "b".repeat(64) });
  });

  it("passes optional expected fields through to the CLI", async () => {
    execFileAsyncMock.mockResolvedValue({
      stdout: JSON.stringify({ session_id: "omp-1", completion_eligible: true }),
      stderr: "",
    });

    const result = await runEnvironmentAssessment({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      phase: "session_start",
      expectedFields: ["lockfiles"],
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(execFileAsyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      [
        "-m", "second_brain", "env", "assess", "C:/repo",
        "--session", "omp-1", "--phase", "session_start", "--expected-field", "lockfiles", "--json",
      ],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000 }),
    );
    expect(result).toMatchObject({ ok: true, completionEligible: true });
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

  it("reports a session mismatch as a failure, not evidence for another session", async () => {
    execFileAsyncMock.mockResolvedValue({
      stdout: JSON.stringify({ session_id: "someone-else", environment_hash: "a".repeat(64) }),
      stderr: "",
    });

    const result = await runEnvironmentAssessment({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      phase: "task_boundary",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result).toEqual({ ok: false, error: "environment session mismatch" });
  });
});
