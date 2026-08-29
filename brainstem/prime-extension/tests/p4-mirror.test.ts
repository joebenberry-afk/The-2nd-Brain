import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
const execFileSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock, execFileSync: execFileSyncMock }));
const existsSyncMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("node:fs", () => ({ existsSync: existsSyncMock }));

import { runP4Pulse, runP4PulseSync } from "../src/p4-mirror";

beforeEach(() => {
  execFileMock.mockReset();
  execFileSyncMock.mockReset();
  existsSyncMock.mockReset();
  existsSyncMock.mockReturnValue(true);
});

describe("P4 pulse bridge (Task 7)", () => {
  it("runs one bounded synchronous pulse through the canonical CLI with --no-telemetry", () => {
    execFileSyncMock.mockReturnValue(
      JSON.stringify({
        session_id: "omp-1",
        event: "session_shutdown",
        heartbeat: { mode: "shadow", ran: true, model_tokens_used: 0 },
        candidate_count: 1,
        candidates: [{ candidate_id: "candidate-1", lifecycle_state: "candidate" }],
        fingerprints: [{ fingerprint_id: "fp-1", category: "PROMPT_BLOAT" }],
      }),
    );

    const result = runP4PulseSync({
      home: "C:/brain",
      hostSessionId: "omp-1",
      event: "session_shutdown",
      repo: "C:/repo",
      projectId: "project-a",
      force: true,
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(execFileSyncMock).toHaveBeenCalledWith(
      "C:/brain/.venv/Scripts/python.exe",
      [
        "-m", "second_brain", "p4", "pulse",
        "--event", "session_shutdown", "--session", "omp-1",
        "--repo", "C:/repo", "--project-id", "project-a", "--force",
        "--no-telemetry", "--json",
      ],
      expect.objectContaining({ cwd: "C:/brain", timeout: 5000, maxBuffer: 1024 * 1024 }),
    );
    expect(result.ok).toBe(true);
    expect(result.sessionId).toBe("omp-1");
    expect(result.heartbeat).toEqual({ mode: "shadow", ran: true, model_tokens_used: 0 });
    expect(result.fingerprints).toEqual([{ fingerprint_id: "fp-1", category: "PROMPT_BLOAT" }]);
  });

  it("omits --repo/--project-id/--force when unset", () => {
    execFileSyncMock.mockReturnValue(JSON.stringify({ session_id: "omp-1" }));

    runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_start" });

    expect(execFileSyncMock).toHaveBeenCalledWith(
      expect.any(String),
      [
        "-m", "second_brain", "p4", "pulse",
        "--event", "session_start", "--session", "omp-1",
        "--no-telemetry", "--json",
      ],
      expect.anything(),
    );
  });

  it("fails open when the Brain venv is absent (sync)", () => {
    existsSyncMock.mockReturnValue(false);

    const result = runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_shutdown" });

    expect(result).toEqual({ ok: true, sessionId: "omp-1" });
    expect(execFileSyncMock).not.toHaveBeenCalled();
  });

  it("fails open on a non-zero exit / spawn error (sync)", () => {
    execFileSyncMock.mockImplementation(() => {
      throw new Error("boom");
    });

    const result = runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_shutdown" });

    expect(result).toEqual({ ok: false, sessionId: "omp-1", error: "boom" });
  });

  it("fails open on a session id mismatch (sync)", () => {
    execFileSyncMock.mockReturnValue(JSON.stringify({ session_id: "someone-else" }));

    const result = runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_shutdown" });

    expect(result).toEqual({ ok: false, error: "p4 session mismatch" });
  });

  it("fails open on unparsable output (sync)", () => {
    execFileSyncMock.mockReturnValue("not json");

    const result = runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_shutdown" });

    expect(result).toEqual({ ok: false, error: "p4 pulse returned unparsable output" });
  });

  it("strips PYTHONHOME/PYTHONPATH and sets SECOND_BRAIN_HOME (sync)", () => {
    execFileSyncMock.mockReturnValue(JSON.stringify({ session_id: "omp-1" }));
    const savedHome = process.env.PYTHONHOME;
    const savedPath = process.env.PYTHONPATH;
    process.env.PYTHONHOME = "C:/somewhere/python";
    process.env.PYTHONPATH = "C:/somewhere/site-packages";
    try {
      runP4PulseSync({ home: "C:/brain", hostSessionId: "omp-1", event: "session_start" });
      const passedEnv = execFileSyncMock.mock.calls[0][2].env as Record<string, string | undefined>;
      expect(passedEnv.PYTHONHOME).toBeUndefined();
      expect(passedEnv.PYTHONPATH).toBeUndefined();
      expect(passedEnv.SECOND_BRAIN_HOME).toBe("C:/brain");
    } finally {
      if (savedHome === undefined) delete process.env.PYTHONHOME;
      else process.env.PYTHONHOME = savedHome;
      if (savedPath === undefined) delete process.env.PYTHONPATH;
      else process.env.PYTHONPATH = savedPath;
    }
  });

  it("runs one bounded async pulse (session_start/turn_start) with the same --no-telemetry contract", async () => {
    execFileMock.mockImplementation((_python, args, _options, callback) => {
      expect(args).toEqual([
        "-m", "second_brain", "p4", "pulse",
        "--event", "turn_start", "--session", "omp-2",
        "--no-telemetry", "--json",
      ]);
      callback(null, JSON.stringify({ session_id: "omp-2", heartbeat: { mode: "off" } }));
      return { stdin: { write: vi.fn(), end: vi.fn() } };
    });

    const result = await runP4Pulse({
      home: "C:/brain",
      hostSessionId: "omp-2",
      event: "turn_start",
      python: "C:/brain/.venv/Scripts/python.exe",
    });

    expect(result.ok).toBe(true);
    expect(result.heartbeat).toEqual({ mode: "off" });
  });

  it("fails open on a spawn error (async)", async () => {
    execFileMock.mockImplementation((_python, _args, _options, callback) => {
      callback(new Error("spawn failed"), "");
      return { stdin: { write: vi.fn(), end: vi.fn() } };
    });

    const result = await runP4Pulse({ home: "C:/brain", hostSessionId: "omp-2", event: "session_start" });

    expect(result).toEqual({ ok: false, sessionId: "omp-2", error: "spawn failed" });
  });

  it("fails open when the Brain venv is absent (async), never spawning", async () => {
    existsSyncMock.mockReturnValue(false);

    const result = await runP4Pulse({ home: "C:/brain", hostSessionId: "omp-2", event: "session_start" });

    expect(result).toEqual({ ok: true, sessionId: "omp-2" });
    expect(execFileMock).not.toHaveBeenCalled();
  });
});
