/**
 * Environment fingerprint (V3 S2 cadence): the assessment runs once per session,
 * then only when this cheap in-host value changes — so it must react to every
 * manifest/HEAD change the assessment's evidence depends on, and to nothing else.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { environmentFingerprint, ENVIRONMENT_FINGERPRINT_FILES } from "../src/environment-mirror";

let repo: string;

beforeEach(() => {
  repo = mkdtempSync(join(tmpdir(), "sb-fingerprint-"));
});

afterEach(() => {
  rmSync(repo, { recursive: true, force: true });
});

describe("environment fingerprint", () => {
  it("is stable for an unchanged repo and reacts to every manifest it names", () => {
    const empty = environmentFingerprint(repo);
    expect(environmentFingerprint(repo)).toBe(empty);
    expect(environmentFingerprint(repo, { SECOND_BRAIN_PROJECT: "project-a" })).not.toBe(empty);

    for (const name of ["package.json", "package-lock.json", "uv.lock", "Cargo.lock", "go.sum"]) {
      writeFileSync(join(repo, name), `{"n":1}`, "utf8");
      const stamped = environmentFingerprint(repo);
      expect(stamped).not.toBe(empty);
      writeFileSync(join(repo, name), `{"n":2,"bigger":true}`, "utf8");
      expect(environmentFingerprint(repo)).not.toBe(stamped);
    }
    expect(ENVIRONMENT_FINGERPRINT_FILES).toContain("package.json");
  });

  it("reacts to version-stamped requirement manifests and to .git/HEAD content", () => {
    const empty = environmentFingerprint(repo);
    writeFileSync(join(repo, "requirements-dev.txt"), "pytest\n", "utf8");
    const withRequirements = environmentFingerprint(repo);
    expect(withRequirements).not.toBe(empty);

    mkdirSync(join(repo, ".git"), { recursive: true });
    writeFileSync(join(repo, ".git", "HEAD"), "ref: refs/heads/main\n", "utf8");
    const onMain = environmentFingerprint(repo);
    expect(onMain).not.toBe(withRequirements);
    writeFileSync(join(repo, ".git", "HEAD"), "ref: refs/heads/other\n", "utf8");
    expect(environmentFingerprint(repo)).not.toBe(onMain);
    // Whitespace-only differences are the same repository state.
    writeFileSync(join(repo, ".git", "HEAD"), "ref: refs/heads/other", "utf8");
    expect(environmentFingerprint(repo)).toBe(environmentFingerprint(repo));
  });

  it("separates different repositories with identical contents", () => {
    const other = mkdtempSync(join(tmpdir(), "sb-fingerprint-other-"));
    try {
      writeFileSync(join(repo, "package.json"), "{}", "utf8");
      writeFileSync(join(other, "package.json"), "{}", "utf8");
      expect(environmentFingerprint(repo)).not.toBe(environmentFingerprint(other));
    } finally {
      rmSync(other, { recursive: true, force: true });
    }
  });

  /**
   * Review counterexample: a linked worktree (this repository's own checkout
   * shape) has a `.git` FILE pointing at the main repository's git directory, so
   * reading `<repo>/.git/HEAD` finds nothing and every branch fingerprints the
   * same. The fingerprint must resolve the real git directory, follow
   * `commondir` to the shared refs, and include the ref VALUE — a symbolic HEAD
   * keeps its content while the branch advances.
   */
  it("fingerprints a linked worktree's git directory and its ref value", () => {
    const mainGit = join(repo, "main-git");
    const gitDir = join(mainGit, "worktrees", "reviewed");
    mkdirSync(gitDir, { recursive: true });
    writeFileSync(join(gitDir, "commondir"), "../..\n", "utf8");
    writeFileSync(join(gitDir, "HEAD"), "ref: refs/heads/main\n", "utf8");
    mkdirSync(join(mainGit, "refs", "heads"), { recursive: true });
    const refFile = join(mainGit, "refs", "heads", "main");
    writeFileSync(refFile, `${"a".repeat(40)}\n`, "utf8");
    writeFileSync(join(repo, ".git"), `gitdir: ${gitDir}\n`, "utf8");

    const first = environmentFingerprint(repo);
    expect(environmentFingerprint(repo)).toBe(first);

    // The branch advances: HEAD content and every manifest stay identical.
    writeFileSync(refFile, `${"b".repeat(40)}\n`, "utf8");
    const advanced = environmentFingerprint(repo);
    expect(advanced).not.toBe(first);

    // A packed ref (no loose file) resolves to the same value once more.
    rmSync(refFile);
    writeFileSync(join(mainGit, "packed-refs"), `# pack-refs with: peeled\n${"b".repeat(40)} refs/heads/main\n`, "utf8");
    expect(environmentFingerprint(repo)).toBe(advanced);

    // A branch switch in the worktree is visible through HEAD content.
    writeFileSync(join(gitDir, "HEAD"), "ref: refs/heads/other\n", "utf8");
    const switched = environmentFingerprint(repo);
    expect(switched).not.toBe(advanced);

    // A detached HEAD carries the commit itself, and a broken pointer is stable.
    writeFileSync(join(gitDir, "HEAD"), `${"c".repeat(40)}\n`, "utf8");
    expect(environmentFingerprint(repo)).not.toBe(switched);
    writeFileSync(join(repo, ".git"), "not a gitdir pointer\n", "utf8");
    const broken = environmentFingerprint(repo);
    expect(environmentFingerprint(repo)).toBe(broken);
    expect(broken).not.toBe(switched);
  });

  it("reacts to a plain checkout's branch value as well as its HEAD content", () => {
    mkdirSync(join(repo, ".git", "refs", "heads"), { recursive: true });
    const refFile = join(repo, ".git", "refs", "heads", "main");
    writeFileSync(join(repo, ".git", "HEAD"), "ref: refs/heads/main\n", "utf8");
    writeFileSync(refFile, `${"a".repeat(40)}\n`, "utf8");
    const onMain = environmentFingerprint(repo);
    writeFileSync(refFile, `${"b".repeat(40)}\n`, "utf8");
    expect(environmentFingerprint(repo)).not.toBe(onMain);
  });
});
