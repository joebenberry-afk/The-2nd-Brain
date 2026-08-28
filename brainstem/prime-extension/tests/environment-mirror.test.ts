import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFileSync: execFileSyncMock }));
vi.mock("node:fs", () => ({ existsSync: () => true }));

import { runEnvironmentAssessmentSync } from "../src/environment-mirror";

beforeEach(() => execFileSyncMock.mockReset());

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
});
