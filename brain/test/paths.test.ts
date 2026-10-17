import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import type * as ChildProcess from "node:child_process";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pathHint } from "../src/paths.ts";
import { estimateTokens, PACKAGE_HOME } from "../src/util.ts";
import { FIX_BUDGET } from "../src/capture.ts";

// pathHint gives git and its directory walk one 150 ms wall-clock budget, so a fixture that ran the
// real git and clock would pass or fail on how fast git starts. By default git answers "not a
// repository" at once and the clock stands still; the budget cases move the clock themselves, and
// the smoke case at the end runs the real git and clock.
vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof ChildProcess>();
  return { ...actual, spawnSync: vi.fn(actual.spawnSync) };
});
const realGit = (await vi.importActual<typeof ChildProcess>("node:child_process")).spawnSync;

/** What spawnSync returns for a git that exited with `status` (null: killed at its timeout) after printing `stdout`. */
const gitSays = (status: number | null, stdout = ""): ChildProcess.SpawnSyncReturns<string> => ({ status, signal: null, stdout, stderr: "", output: [null, stdout, ""], pid: 0 });

let now = 0;
let clock: { mockRestore: () => void };
beforeEach(() => {
  now = 1_000;
  clock = vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.mocked(spawnSync).mockClear();
  vi.mocked(spawnSync).mockImplementation(() => gitSays(128));
});
afterEach(() => {
  clock.mockRestore();
  vi.mocked(spawnSync).mockImplementation(realGit);
});

/** A non-git tree (the bounded walk); tmpdir is outside any checkout. */
function tree(files: string[]): string {
  const root = mkdtempSync(join(tmpdir(), "brain-paths-"));
  for (const file of files) {
    mkdirSync(join(root, file, ".."), { recursive: true });
    writeFileSync(join(root, file), "");
  }
  return root;
}

describe("pathHint", () => {
  it("names the same file in the folder where it actually lives, nearest folders first", () => {
    const root = tree(["brain/scripts/agentbench.ts", "old/agentbench.ts", "brain/src/card.ts"]);
    const hint = pathHint("read", "scripts/agentbench.ts:15-47", "Path 'scripts/agentbench.ts:15' not found", root);
    expect(hint).toBe("Brain: scripts/agentbench.ts does not exist; closest: brain/scripts/agentbench.ts, old/agentbench.ts");
  });

  it("catches a typo, another extension, and a missing folder", () => {
    const root = tree(["src/telemetry.ts", "docs/LOOP.md", "brain/scripts/perf.ts"]);
    expect(pathHint("Read", join(root, "src/telemtry.ts"), "File does not exist.", root)).toContain("closest: src/telemetry.ts");
    expect(pathHint("grep", "src/telemetry.js", "Path not found: src/telemetry.js", root)).toContain("closest: src/telemetry.ts");
    expect(pathHint("glob", "scripts", "Path not found: scripts", root)).toContain("closest: brain/scripts/");
  });

  it("lists the deepest existing folder when nothing looks alike", () => {
    const root = tree(["data/test/a.jsonl", "data/test/b.jsonl", "data/train/c.jsonl"]);
    expect(pathHint("read", "data/test/README.md", "Path 'data/test/README.md' not found", root)).toBe("Brain: data/test/README.md does not exist; data/test/ holds: a.jsonl, b.jsonl");
  });

  it("stays silent on other errors, existing paths, URLs, shell commands and unrelated names", () => {
    const root = tree(["src/card.ts"]);
    expect(pathHint("read", "src/card.ts:9999", "Path 'src/card.ts:9999' not found", root)).toBe("");
    expect(pathHint("edit", "src/cards.ts", "String to replace not found in file.", root)).toBe("");
    expect(pathHint("edit", "src/card.ts", "Edit rejected for src/card.ts: file changed between read and edit.", root)).toBe("");
    expect(pathHint("read", "https://example.com/x.md", "Not found", root)).toBe("");
    expect(pathHint("bash", "src/cards.ts", "No such file or directory", root)).toBe("");
    expect(pathHint("read", "quantum.py", "Path 'quantum.py' not found", root)).toBe("");
  });

  it("stays within the fix budget however many files match", () => {
    const root = tree(Array.from({ length: 12 }, (_, i) => `a_rather_long_folder_name_number_${i}/another_long_folder_name/index.ts`));
    const hint = pathHint("read", "index.ts", "Path 'index.ts' not found", root);
    expect(hint).toMatch(/^Brain: index\.ts does not exist; closest: /);
    expect(estimateTokens(hint)).toBeLessThanOrEqual(FIX_BUDGET);
  });
});

/** Runs `body` with these environment variables pointing at `dir` (where os.homedir/tmpdir read them). */
function pointing(vars: string[], dir: string, body: () => void): void {
  const saved = vars.map((name) => [name, process.env[name]] as const);
  for (const name of vars) process.env[name] = dir;
  try { body(); } finally { for (const [name, value] of saved) { if (value === undefined) delete process.env[name]; else process.env[name] = value; } }
}

// A missing path must never hold the host's tool result: a walk of a machine-sized folder took
// 7-25 s in telemetry, and the hint only names files.
describe("pathHint cost", () => {
  const miss = (cwd: string, budget?: number) => pathHint("read", "proj/src/telemtry.ts", "Path 'proj/src/telemtry.ts' not found", cwd, budget);
  const small = () => tree(["proj/src/telemetry.ts", "proj/lib/other.ts"]);
  const holds = "Brain: proj/src/telemtry.ts does not exist; proj/src/ holds: telemetry.ts";
  const closest = "Brain: proj/src/telemtry.ts does not exist; closest: proj/src/telemetry.ts";

  it("does not walk a home or temp folder; it still lists the folder the path should have been in", () => {
    for (const vars of [["HOME", "USERPROFILE"], ["TMPDIR", "TMP", "TEMP"]]) {
      const root = tree(["proj/src/telemetry.ts", "proj/src/card.ts"]);
      pointing(vars, root, () => {
        expect(miss(root)).toBe("Brain: proj/src/telemtry.ts does not exist; proj/src/ holds: card.ts, telemetry.ts");
      });
    }
    expect(spawnSync).not.toHaveBeenCalled();
  });

  it("runs no git and walks nothing on a spent budget; the folder's own entries answer", () => {
    expect(miss(small(), 0)).toBe(holds);
    expect(spawnSync).not.toHaveBeenCalled();
  });

  it("walks the tree when git says it is not a repository", () => {
    expect(miss(small())).toBe(closest);
  });

  it("falls back to the folder's own entries when a non-repository answer from git used up the budget", () => {
    vi.mocked(spawnSync).mockImplementation(() => { now += 160; return gitSays(128); });
    expect(miss(small())).toBe(holds);
  });

  it("lists with git's tracked and untracked files inside the whole budget it is given", () => {
    // The file git names is not on disk, so only git's listing can supply it.
    const root = tree(["proj/src/other.ts"]);
    vi.mocked(spawnSync).mockImplementation(() => gitSays(0, "proj/src/telemetry.ts\0proj/src/other.ts\0"));
    expect(miss(root)).toBe(closest);
    expect(spawnSync).toHaveBeenCalledWith("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], expect.objectContaining({ cwd: root, timeout: 150 }));
  });

  it("keeps the whole paths of a listing git was killed in the middle of", () => {
    vi.mocked(spawnSync).mockImplementation(() => { now += 150; return gitSays(null, "proj/src/telemetry.ts\0proj/sr"); });
    expect(miss(tree(["proj/src/other.ts"]))).toBe(closest);
  });

  it("walks nothing when git was killed before it printed anything", () => {
    vi.mocked(spawnSync).mockImplementation(() => { now += 150; return gitSays(null); });
    expect(miss(small())).toBe(holds);
  });

  it("reuses a listing for a minute instead of running git again", () => {
    const root = small();
    miss(root);
    miss(root);
    expect(spawnSync).toHaveBeenCalledTimes(1);
  });
});

// The real git and clock, once. However loaded the machine, the answer is one of the documented
// ones: git's listing inside its budget, or the folder's own entries when git ran out of it.
describe("pathHint with the real git (smoke)", () => {
  beforeEach(() => {
    clock.mockRestore();
    vi.mocked(spawnSync).mockImplementation(realGit);
  });

  it("answers a missing path in a real repository", () => {
    const root = tree(["proj/src/telemetry.ts", "proj/src/card.ts"]);
    expect(realGit("git", ["init", "-q"], { cwd: root, windowsHide: true }).status).toBe(0);
    const hint = pathHint("read", "proj/src/telemtry.ts", "Path 'proj/src/telemtry.ts' not found", root);
    expect(hint).toMatch(/^Brain: proj\/src\/telemtry\.ts does not exist; (?:closest: proj\/src\/telemetry\.ts|proj\/src\/ holds: card\.ts, telemetry\.ts)$/);
  });
});

// The hook only runs for the tools its matcher names, so a tool the hint answers but the matcher
// leaves out can never get one (Claude Code's Read, Grep and Glob were missing).
describe("path hint reach on Claude Code", () => {
  const settings = JSON.parse(readFileSync(join(PACKAGE_HOME, ".claude", "settings.json"), "utf8"));
  const readme = readFileSync(join(PACKAGE_HOME, "brain", "README.md"), "utf8");
  const matchers: Record<string, string[]> = {
    "the repo settings": settings.hooks.PostToolUseFailure.map((entry: { matcher: string }) => entry.matcher),
    "the README template": [...readme.matchAll(/"PostToolUseFailure": \[\{ "matcher": "([^"]+)"/g)].map((m) => m[1]!),
  };

  it.each(Object.entries(matchers))("%s delivers every failed tool the hint can answer", (_, patterns) => {
    const root = tree(["src/telemetry.ts"]);
    const answered = ["Read", "Grep", "Glob", "LS", "NotebookEdit", "Edit", "MultiEdit", "Write", "Bash"]
      .filter((tool) => pathHint(tool, "src/telemtry.ts", "File does not exist.", root) !== "");
    expect(answered).toEqual(expect.arrayContaining(["Read", "Grep", "Glob", "LS"]));
    expect(patterns.length).toBeGreaterThan(0);
    for (const tool of answered) expect(patterns.some((pattern) => new RegExp(pattern).test(tool)), tool).toBe(true);
  });
});
