import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFileSync: execFileSyncMock }));
vi.mock("node:fs", () => ({ existsSync: () => true }));

import { runRadarObservationSync } from "../src/radar-mirror";

beforeEach(() => execFileSyncMock.mockReset());

describe("Radar observation bridge", () => {
  it("observes one completed OMP session through the canonical CLI", () => {
    execFileSyncMock.mockReturnValue(
      JSON.stringify({
        session_id: "omp-1",
        candidate_count: 1,
        candidates: [{ candidate_id: "candidate-1", lifecycle_state: "candidate" }],
      }),
    );

    const result = runRadarObservationSync({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      projectId: "project-a",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(execFileSyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      [
        "-m", "second_brain", "radar", "observe", "omp-1",
        "--project-id", "project-a", "--repo", "C:/repo", "--json",
      ],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000 }),
    );
    expect(result.ok).toBe(true);
    expect(result.candidateCount).toBe(1);
  });
});
