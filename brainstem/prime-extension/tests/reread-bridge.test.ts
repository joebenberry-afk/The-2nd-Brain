import { execFile } from "node:child_process";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runRereadHint } from "../src/index";

vi.mock("node:child_process", () => ({ execFile: vi.fn() }));

describe("Prime reread hint bridge", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the Brain home runtime and sanitized environment", async () => {
    const home = "C:/brain-home";
    const mocked = vi.mocked(execFile);
    mocked.mockImplementation((file, args, options, callback) => {
      if (typeof callback === "function") {
        callback(null, JSON.stringify({ unchanged: true, prior_artifact: "sha256:prior", prior_turn: 2 }), "");
      }
      return undefined as never;
    });

    await expect(runRereadHint(home, "session", "file.txt", "SHADOW", "read", "call"))
      .resolves.toMatchObject({ unchanged: true });
    expect(mocked).toHaveBeenCalledWith(
      join(home, ".venv", "Scripts", "python.exe"),
      [
        "-m", "second_brain", "--home", home, "working-set", "reread-hint", "session", "file.txt",
        "--mode", "SHADOW", "--tool", "read", "--tool-call-id", "call",
      ],
      expect.objectContaining({
        cwd: home,
        env: expect.objectContaining({ SECOND_BRAIN_HOME: home }),
      }),
      expect.any(Function),
    );
    const options = mocked.mock.calls[0]?.[2] as { env: Record<string, string | undefined> };
    expect(options.env.PYTHONHOME).toBeUndefined();
    expect(options.env.PYTHONPATH).toBeUndefined();
  });
});
