import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock }));
const existsSyncMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("node:fs", () => ({ existsSync: existsSyncMock }));

import { runP4Pulse } from "../src/p4-mirror";

/** Answer the bridge's execFile call immediately with `stdout`. */
function answerWith(stdout: string): void {
  execFileMock.mockImplementation((_python, _args, _options, callback) => {
    callback(null, stdout);
    return { stdin: { write: vi.fn(), end: vi.fn() } };
  });
}

beforeEach(() => {
  execFileMock.mockReset();
  existsSyncMock.mockReset();
  existsSyncMock.mockReturnValue(true);
});

describe("P4 pulse bridge (Task 7)", () => {
  it("runs one bounded async pulse (session_start/turn_start) with the --no-telemetry contract", async () => {
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

  it("strips PYTHONHOME/PYTHONPATH and sets SECOND_BRAIN_HOME (async)", async () => {
    answerWith(JSON.stringify({ session_id: "omp-2" }));
    const savedHome = process.env.PYTHONHOME;
    const savedPath = process.env.PYTHONPATH;
    process.env.PYTHONHOME = "C:/somewhere/python";
    process.env.PYTHONPATH = "C:/somewhere/site-packages";
    try {
      await runP4Pulse({ home: "C:/brain", hostSessionId: "omp-2", event: "session_start" });
      const passedEnv = execFileMock.mock.calls[0][2].env as Record<string, string | undefined>;
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

  it("reports a session id mismatch as a failure (async)", async () => {
    answerWith(JSON.stringify({ session_id: "someone-else" }));

    const result = await runP4Pulse({ home: "C:/brain", hostSessionId: "omp-2", event: "session_start" });

    expect(result).toEqual({ ok: false, error: "p4 session mismatch" });
  });

  it("reports unparsable output as a failure (async)", async () => {
    answerWith("not json");

    const result = await runP4Pulse({ home: "C:/brain", hostSessionId: "omp-2", event: "session_start" });

    expect(result).toEqual({ ok: false, error: "p4 pulse returned unparsable output" });
  });
});
