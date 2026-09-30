import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { sync, shareNote, SyncError } from "../src/sync.ts";
import { createNote, loadNotes, saveNote } from "../src/notes.ts";
import { addProjectTag } from "../src/project.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-sync-"));

function gitCmd(cwd: string, ...args: string[]): string {
  const result = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${result.stderr}`);
  }
  return result.stdout;
}

function setupRepo(cwd: string, upstream?: string): void {
  gitCmd(cwd, "init");
  gitCmd(cwd, "config", "user.name", "Test");
  gitCmd(cwd, "config", "user.email", "test@example.com");
  writeFileSync(join(cwd, ".gitkeep"), "");
  gitCmd(cwd, "add", ".gitkeep");
  gitCmd(cwd, "commit", "-m", "init");
  if (upstream) {
    gitCmd(cwd, "remote", "add", "origin", upstream);
    gitCmd(cwd, "push", "-u", "origin", "HEAD:main");
  }
}

function pairRepos(): { bare: string; a: string; b: string } {
  const root = tmp();
  const bare = join(root, "remote.git");
  const a = join(root, "a");
  const b = join(root, "b");

  // Initialize bare repo
  mkdirSync(bare);
  gitCmd(bare, "init", "--bare");
  gitCmd(bare, "symbolic-ref", "HEAD", "refs/heads/main");

  // Initialize and push from A
  mkdirSync(a);
  gitCmd(a, "init");
  gitCmd(a, "config", "user.name", "TestA");
  gitCmd(a, "config", "user.email", "testa@example.com");
  writeFileSync(join(a, ".gitkeep"), "");
  gitCmd(a, "add", ".gitkeep");
  gitCmd(a, "commit", "-m", "init");
  gitCmd(a, "remote", "add", "origin", bare);
  gitCmd(a, "push", "-u", "origin", "HEAD:main");

  // Clone to B
  gitCmd(root, "clone", bare, b);
  gitCmd(b, "config", "user.name", "TestB");
  gitCmd(b, "config", "user.email", "testb@example.com");

  return { bare, a, b };
}

describe("sync", () => {
  it("refuses credential share tags without moving or changing the note", () => {
    const home = tmp();
    const note = createNote(home, { text: "Safe note", project: "global" });
    const before = readFileSync(note.path, "utf8");
    expect(() => shareNote(home, note.id, "ghp_" + "x".repeat(30))).toThrow(/tag.*credential/i);
    expect(readFileSync(note.path, "utf8")).toBe(before);
  });

  it.each(["", "brain-home"])("refuses private-note history before pushing from %s", (subdir) => {
    const { a, bare } = pairRepos();
    const home = join(a, subdir);
    const remoteHead = gitCmd(bare, "rev-parse", "refs/heads/main");
    const privateDir = join(home, "notes", "demo", "private");
    mkdirSync(privateDir, { recursive: true });
    writeFileSync(join(privateDir, "local.md"), "local-only content");
    gitCmd(a, "add", "-f", ".");
    gitCmd(a, "commit", "-m", "manual private commit");
    gitCmd(a, "rm", "--", (subdir ? subdir + "/" : "") + "notes/demo/private/local.md");
    gitCmd(a, "commit", "-m", "remove private file from tip");
    mkdirSync(home, { recursive: true });
    expect(() => sync(home)).toThrow(/refus.*push.*notes\/demo\/private\/local\.md/i);
    expect(gitCmd(bare, "rev-parse", "refs/heads/main")).toBe(remoteHead);
  });

  it("refuses to push after an autostash conflict outside a nested Brain home", () => {
    const { a, b, bare } = pairRepos();
    writeFileSync(join(a, "outside.txt"), "original\n");
    gitCmd(a, "add", "outside.txt");
    gitCmd(a, "commit", "-m", "outside base");
    gitCmd(a, "push", "origin", "HEAD:main");
    gitCmd(b, "pull", "--rebase");
    writeFileSync(join(a, "outside.txt"), "upstream\n");
    gitCmd(a, "commit", "-am", "outside upstream");
    gitCmd(a, "push", "origin", "HEAD:main");
    const remoteHead = gitCmd(bare, "rev-parse", "refs/heads/main");
    writeFileSync(join(b, "outside.txt"), "local uncommitted\n");
    const home = join(b, "brain-home");
    createNote(home, { text: "Local durable note", project: "demo" });
    expect(() => sync(home)).toThrow(/uncommitted changes to .*outside\.txt conflict/);
    expect(gitCmd(bare, "rev-parse", "refs/heads/main")).toBe(remoteHead);
    expect(gitCmd(b, "diff", "--name-only", "--diff-filter=U")).toContain("outside.txt");
    expect(gitCmd(b, "stash", "list")).toContain("autostash");
  });

  it("raises when not a git repository", () => {
    const home = tmp();
    expect(() => sync(home)).toThrow(SyncError);
  });

  it("commits only sync paths when other files are staged", () => {
    const { a } = pairRepos();
    const notesDir = join(a, "notes");
    mkdirSync(notesDir, { recursive: true });
    const note = createNote(a, { text: "test", project: "demo" });
    expect(note.path).toBeTruthy();

    // Stage an unrelated file
    const otherFile = join(a, "other.txt");
    writeFileSync(otherFile, "content");
    gitCmd(a, "add", "other.txt");

    const result = sync(a);
    expect(result.committed).toBe(true);
    expect(result.pushed).toBe(true);

    // Check that other.txt is still staged
    const staged = gitCmd(a, "diff", "--cached", "--name-only");
    expect(staged).toContain("other.txt");

    // Check that only notes were committed
    const committed = gitCmd(a, "show", "--name-only", "HEAD");
    expect(committed).toContain("notes");
    expect(committed).not.toContain("other.txt");
  });

  it("never commits private notes even without .gitignore", () => {
    const { a } = pairRepos();
    const note = createNote(a, { text: "secret", project: "demo", private: true });
    expect(note.private).toBe(true);

    const result = sync(a);
    expect(result.committed).toBe(false);
    // Private notes should not be committed, so nothing to push
    // The message reflects that nothing was synced
    expect(result.message).not.toContain("committed");
  });

  it("returns correct messages for different sync states", () => {
    const home = tmp();
    setupRepo(home);

    // No upstream branch
    let result = sync(home);
    expect(result.message).toBe("nothing to sync; no upstream branch");

    const notesDir = join(home, "notes");
    mkdirSync(notesDir, { recursive: true });
    createNote(home, { text: "test", project: "demo" });

    result = sync(home);
    expect(result.committed).toBe(true);
    expect(result.message).toContain("committed");
    expect(result.message).toContain("no upstream branch");
  });

  it("syncs notes between two repos (pull/push)", () => {
    const { a, b } = pairRepos();

    // A: create and sync
    const note = createNote(a, { text: "shared note", project: "demo" });
    const resultA = sync(a);
    expect(resultA.committed).toBe(true);
    expect(resultA.pushed).toBe(true);

    // B: pull and see the note
    const resultB = sync(b);
    expect(resultB.pulled).toBe(true);
    const { notes } = loadNotes(b);
    expect(notes.some((n) => n.id === note.id)).toBe(true);
  });

  it("handles rebase conflicts by aborting", () => {
    const { a, b } = pairRepos();

    // Both create a note with same id (conflict setup)
    const note = createNote(a, { text: "from a", project: "demo" });
    sync(a);

    const notesB = join(b, "notes", "demo");
    mkdirSync(notesB, { recursive: true });
    writeFileSync(join(notesB, `${note.id}.md`), "---\nid: " + note.id + "\nkind: note\nat: 2026-09-27T00:00:00Z\nsource: user\n---\nfrom b");
    gitCmd(b, "add", "-A");
    gitCmd(b, "commit", "-m", "conflict");

    // A modifies the note
    saveNote(a, { ...note, body: "modified in a" });
    sync(a);

    // B tries to sync - should encounter conflict
    expect(() => sync(b)).toThrow(SyncError);
    expect(() => sync(b)).toThrow(/notes\/demo\/.+\.md.*brain sync/s);

    // Check that rebase was aborted (working tree clean)
    const status = gitCmd(b, "status", "--short");
    expect(status).toBe("");
  });

  it("shareNote moves project note to global with tag", () => {
    const home = tmp();
    const note = createNote(home, { text: "tip", project: "demo" });

    const shared = shareNote(home, note.id, "learning");
    expect(shared.project).toBe("global");
    expect(shared.tags).toContain("learning");

    const { notes } = loadNotes(home);
    const found = notes.find((n) => n.id === note.id);
    expect(found?.project).toBe("global");
  });

  it("shareNote adds tag to global note", () => {
    const home = tmp();
    const note = createNote(home, { text: "tip", project: "global", tags: ["existing"] });

    const shared = shareNote(home, note.id, "new-tag");
    expect(shared.project).toBe("global");
    expect(shared.tags).toContain("existing");
    expect(shared.tags).toContain("new-tag");
  });

  it("shareNote refuses private notes", () => {
    const home = tmp();
    const note = createNote(home, { text: "secret", project: "demo", private: true });

    expect(() => shareNote(home, note.id, "tag")).toThrow(SyncError);
    expect(() => shareNote(home, note.id, "tag")).toThrowError(/private/);
  });

  it("shareNote refuses retired notes", () => {
    const home = tmp();
    const note = createNote(home, { text: "old", project: "demo" });
    saveNote(home, { ...note, retired: "2026-09-27T00:00:00Z" });

    expect(() => shareNote(home, note.id, "tag")).toThrow(SyncError);
    expect(() => shareNote(home, note.id, "tag")).toThrowError(/retired/);
  });

  it("shareNote raises when note not found", () => {
    const home = tmp();

    expect(() => shareNote(home, "nonexistent", "tag")).toThrow(SyncError);
    expect(() => shareNote(home, "nonexistent", "tag")).toThrowError(/unknown/);
  });

  it("shareNote names the owner it tagged when the note is filed under an alias", () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { alpha: { aliases: ["old"] } } }));
    const note = createNote(home, { text: "tip", project: "old" });
    expect(shareNote(home, note.id, "uploads").taggedProject).toBe("alpha");
  });

  it("shareNote deduplicates tags", () => {
    const home = tmp();
    const note = createNote(home, { text: "tip", project: "demo", tags: ["learning"] });

    const shared = shareNote(home, note.id, "learning");
    expect(shared.tags).toEqual(["learning"]);
  });
});

describe("sync to a branch whose name contains a slash (regression)", () => {
  it("pushes to the full upstream branch name", () => {
    const { bare, a } = pairRepos();
    gitCmd(a, "checkout", "-b", "claude/topic-x");
    gitCmd(a, "push", "-u", "origin", "HEAD:claude/topic-x");
    createNote(a, { text: "note on a slashed branch", project: "demo" });
    const result = sync(a);
    expect(result.pushed).toBe(true);
    const log = gitCmd(bare, "log", "--format=%s", "-1", "claude/topic-x");
    expect(log).toMatch(/^brain: sync /);
    expect(spawnSync("git", ["-C", bare, "rev-parse", "--verify", "refs/heads/claude"]).status).not.toBe(0);
  });
});

describe("sync resolves working-state conflicts by recency (regression)", () => {
  const work = (at: string, text: string) => `---\nat: ${at}\n---\n\n${text}\n`;

  it("keeps the newer working state when both machines changed it", () => {
    const { a, b } = pairRepos();
    mkdirSync(join(a, "work"), { recursive: true });
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T10:00:00Z", "base"));
    sync(a);
    sync(b);
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T11:00:00Z", "from A, older"));
    sync(a);
    writeFileSync(join(b, "work", "demo.md"), work("2026-09-27T12:00:00Z", "from B, newer"));
    createNote(b, { text: "a note written on B", project: "demo" });
    const result = sync(b);
    expect(result).toMatchObject({ pulled: true, pushed: true });
    expect(readFileSync(join(b, "work", "demo.md"), "utf8")).toContain("from B, newer");
    expect(loadNotes(b).notes).toHaveLength(1);
    expect(gitCmd(b, "status", "--porcelain")).toBe("");
    sync(a);
    expect(readFileSync(join(a, "work", "demo.md"), "utf8")).toContain("from B, newer");
  });

  it("keeps the upstream state when it is the newer one", () => {
    const { a, b } = pairRepos();
    mkdirSync(join(a, "work"), { recursive: true });
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T10:00:00Z", "base"));
    sync(a);
    sync(b);
    writeFileSync(join(b, "work", "demo.md"), work("2026-09-27T11:00:00Z", "from B, older"));
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T12:00:00Z", "from A, newer"));
    sync(a);
    sync(b);
    expect(readFileSync(join(b, "work", "demo.md"), "utf8")).toContain("from A, newer");
  });
});

describe("sync failure modes (review regressions)", () => {
  it("a pull that fails without stopping a rebase is an error, not a success", () => {
    const { a } = pairRepos();
    createNote(a, { text: "local note", project: "demo" });
    gitCmd(a, "remote", "set-url", "origin", join(tmp(), "gone.git"));
    expect(() => sync(a, { push: false })).toThrow(SyncError);
  });

  it("never stages anything outside the Brain paths, even when none of them exists yet", () => {
    const { a } = pairRepos();
    writeFileSync(join(a, "unrelated.txt"), "not brain data\n");
    const result = sync(a, { push: false });
    expect(result.committed).toBe(false);
    expect(gitCmd(a, "status", "--porcelain")).toBe("?? unrelated.txt\n");
  });
});

describe("sync: the newer plan beats a newer auto refresh (review regression)", () => {
  it("keeps machine A's newer plan over machine B's later session-end stamp", () => {
    const { a, b } = pairRepos();
    const work = (at: string, autoAt: string | null, text: string) =>
      `---\nat: ${at}\n${autoAt ? `auto_at: ${autoAt}\n` : ""}---\n\n${text}\n${autoAt ? "\n## auto\n- last ask: bye\n" : ""}`;
    mkdirSync(join(a, "work"), { recursive: true });
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T09:00:00Z", null, "old plan"));
    sync(a);
    sync(b);
    writeFileSync(join(a, "work", "demo.md"), work("2026-09-27T10:00:00Z", null, "new plan from A"));
    sync(a);
    writeFileSync(join(b, "work", "demo.md"), work("2026-09-27T09:00:00Z", "2026-09-27T10:05:00Z", "old plan"));
    sync(b);
    expect(readFileSync(join(b, "work", "demo.md"), "utf8")).toContain("new plan from A");
  });
});

describe("sync stopped by a conflict outside work/ (review regression)", () => {
  it("names the file and says the same thing on every retry", () => {
    const { a, b } = pairRepos();
    addProjectTag(a, "alpha", "web");
    sync(a);
    addProjectTag(b, "beta", "cli");
    let first = "";
    try {
      sync(b);
    } catch (error) {
      first = error instanceof SyncError ? error.message : "";
    }
    expect(first).toMatch(/^sync stopped: projects\.json changed on both machines/);
    expect(first).not.toContain("git rebase --continue\"");
    expect(first).toContain("git pull --rebase --autostash");
    expect(() => sync(b)).toThrow(first);
    expect(gitCmd(b, "status", "--short")).toBe("");
  });
});
