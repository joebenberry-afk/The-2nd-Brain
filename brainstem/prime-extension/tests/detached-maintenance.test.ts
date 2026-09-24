import { EventEmitter } from "node:events";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const spawnMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ spawn: spawnMock }));
const existsSyncMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("node:fs", () => ({ existsSync: existsSyncMock }));

import { startDetachedShutdownMaintenance } from "../src/detached-maintenance";

/** Detached children: the module only ever unrefs them and forgets them. */
class FakeChild extends EventEmitter {
  unref = vi.fn();
}

let children: FakeChild[];

beforeEach(() => {
  children = [];
  spawnMock.mockReset();
  spawnMock.mockImplementation(() => {
    const child = new FakeChild();
    children.push(child);
    return child;
  });
  existsSyncMock.mockReset();
  existsSyncMock.mockReturnValue(true);
});

describe("detached shutdown maintenance", () => {
  it("starts the assessment and the P4 pulse as detached, unref'd, silenced children", () => {
    const result = startDetachedShutdownMaintenance({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      projectId: "project-a",
      assessEnvironment: true,
    });

    // Synchronous return: neither command's runtime is observed, so the host
    // shutdown path never waits for Brain's Python work.
    expect(result).toEqual({ environment: true, p4: true });
    expect(spawnMock).toHaveBeenCalledTimes(2);
    expect(spawnMock.mock.calls[0]![1]).toEqual([
      "-m", "second_brain", "env", "assess", "C:/repo", "--session", "omp-1", "--phase", "shutdown", "--json",
    ]);
    expect(spawnMock.mock.calls[1]![1]).toEqual([
      "-m", "second_brain", "p4", "pulse", "--event", "session_shutdown", "--session", "omp-1",
      "--repo", "C:/repo", "--project-id", "project-a", "--json",
    ]);
    // Python owns the heartbeat/fingerprint telemetry of a detached pulse.
    expect(spawnMock.mock.calls[1]![1]).not.toContain("--no-telemetry");
    for (const call of spawnMock.mock.calls) {
      expect(call[0]).toBe(join("C:/brain", ".venv", "Scripts", "python.exe"));
      expect(call[2]).toEqual(
        expect.objectContaining({ cwd: "C:/brain", detached: true, stdio: "ignore", windowsHide: true }),
      );
    }
    expect(children).toHaveLength(2);
    for (const child of children) {
      expect(child.unref).toHaveBeenCalledTimes(1);
      // Without a listener a later spawn failure is an uncaught exception.
      expect(child.listenerCount("error")).toBe(1);
    }
  });

  it("strips PYTHONHOME/PYTHONPATH and sets SECOND_BRAIN_HOME for both children", () => {
    const savedHome = process.env.PYTHONHOME;
    const savedPath = process.env.PYTHONPATH;
    process.env.PYTHONHOME = "C:/foreign/home";
    process.env.PYTHONPATH = "C:/foreign/path";
    try {
      startDetachedShutdownMaintenance({
        home: "C:/brain",
        hostSessionId: "omp-1",
        repo: "C:/repo",
        assessEnvironment: true,
      });
      for (const call of spawnMock.mock.calls) {
        const env = (call[2] as { env: Record<string, string | undefined> }).env;
        expect(env.PYTHONHOME).toBeUndefined();
        expect(env.PYTHONPATH).toBeUndefined();
        expect(env.SECOND_BRAIN_HOME).toBe("C:/brain");
      }
    } finally {
      if (savedHome === undefined) delete process.env.PYTHONHOME;
      else process.env.PYTHONHOME = savedHome;
      if (savedPath === undefined) delete process.env.PYTHONPATH;
      else process.env.PYTHONPATH = savedPath;
    }
  });

  it("skips the assessment when it would add nothing, and omits unknown repo/project flags", () => {
    const result = startDetachedShutdownMaintenance({
      home: "C:/brain",
      hostSessionId: "omp-1",
      assessEnvironment: false,
    });

    expect(result).toEqual({ environment: false, p4: true });
    expect(spawnMock).toHaveBeenCalledTimes(1);
    expect(spawnMock.mock.calls[0]![1]).toEqual([
      "-m", "second_brain", "p4", "pulse", "--event", "session_shutdown", "--session", "omp-1", "--json",
    ]);
  });

  it("resolves the interpreter from SECOND_BRAIN_PYTHON when no explicit path is given", () => {
    const saved = process.env.SECOND_BRAIN_PYTHON;
    process.env.SECOND_BRAIN_PYTHON = "C:/venv/python.exe";
    try {
      startDetachedShutdownMaintenance({
        home: "C:/brain",
        hostSessionId: "omp-1",
        assessEnvironment: false,
      });
      expect(spawnMock.mock.calls[0]![0]).toBe("C:/venv/python.exe");
    } finally {
      if (saved === undefined) delete process.env.SECOND_BRAIN_PYTHON;
      else process.env.SECOND_BRAIN_PYTHON = saved;
    }
  });

  it("fails open when the Brain venv is absent: no child, nothing started", () => {
    existsSyncMock.mockReturnValue(false);

    expect(
      startDetachedShutdownMaintenance({
        home: "C:/brain",
        hostSessionId: "omp-1",
        repo: "C:/repo",
        assessEnvironment: true,
      }),
    ).toEqual({ environment: false, p4: false });
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("fails open when spawn itself throws, and never raises a later child error", () => {
    spawnMock.mockImplementation(() => {
      throw new Error("EINVAL");
    });
    expect(
      startDetachedShutdownMaintenance({
        home: "C:/brain",
        hostSessionId: "omp-1",
        repo: "C:/repo",
        assessEnvironment: true,
      }),
    ).toEqual({ environment: false, p4: false });

    // A startable child that fails later (missing executable/EACCES) must not
    // turn the host's shutdown path into an uncaught exception.
    spawnMock.mockImplementation(() => {
      const child = new FakeChild();
      children.push(child);
      return child;
    });
    startDetachedShutdownMaintenance({
      home: "C:/brain",
      hostSessionId: "omp-1",
      repo: "C:/repo",
      assessEnvironment: true,
    });
    expect(children).toHaveLength(2);
    for (const child of children) {
      expect(() => child.emit("error", new Error("ENOENT"))).not.toThrow();
    }
  });
});
