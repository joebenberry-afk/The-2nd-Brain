/** NotesModel hardening: secret scrubbing coverage, convert masking, error patterns, dedupe, tested evidence, sync refusals. */
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { main, type Io } from "../src/cli.ts";
import { convertV3 } from "../src/convert.ts";
import { createNote, findSameHeadline, loadNotes, NoteError, saveNote, upgradeNote } from "../src/notes.ts";
import { scrub } from "../src/scrub.ts";
import { sync, SyncError } from "../src/sync.ts";

const tmp = (p = "brain-nm-") => mkdtempSync(join(tmpdir(), p));

async function run(argv: string[], io: Partial<Io> = {}): Promise<{ code: number; out: string; err: string }> {
  const out: string[] = [];
  const err: string[] = [];
  const code = await main(argv, { stdin: () => "", ...io, env: { CLAUDE_CONFIG_DIR: process.env.CLAUDE_CONFIG_DIR, ...io.env }, out: (s) => out.push(s), err: (s) => err.push(s) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

function repo(name: string): string {
  const dir = join(tmp(), name);
  mkdirSync(join(dir, ".git"), { recursive: true });
  writeFileSync(join(dir, ".git", "config"), "[core]\n\tbare = false\n");
  return dir;
}

const git = (cwd: string, ...args: string[]): string => {
  const r = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout;
};

describe("scrub: references and settings are not secrets", () => {
  it.each([
    "apiKey: process.env.OPENAI_API_KEY",
    "password=$DB_PASSWORD",
    "client_secret = os.environ['CLIENT_SECRET']",
    "auth_token=${{ secrets.NPM_TOKEN }}",
    "DB_PASSWORD=%DB_PASSWORD%",
    "fetch(url, { credentials: 'include' })",
    "credentials: omit",
    "secret: true",
    "privateKey: undefined",
    "password_min_length=12",
    "encryption_key_size=256",
    "PWD=/home/me/app",
    "password=${{secrets.DB_PASSWORD}}",
  ])("keeps %s", (text) => {
    expect(scrub(text, { longRuns: false })).toEqual({ text, scrubbed: false });
  });

  it.each([
    ["password=hunter2", "hunter2"],
    ["password=$Hunter2", "Hunter2"],
    ["password=12345678", "12345678"],
    ["credentials: 'hunter2'", "hunter2"],
    ["secret: 'literal-value'", "literal-value"],
    ["password_min_length=ghp_" + "a".repeat(30), "ghp_"],
    ["PWD=hunter2", "hunter2"],
    ['password="os.environ.get(\'DB_PASSWORD\', \'hunter2\')"', "hunter2"],
    ['apiKey=process.env["OPENAI_API_KEY"]||"hunter2"', "hunter2"],
    ['password="${{ secrets.DB_PASSWORD }}hunter2"', "hunter2"],
  ])("still masks %s", (text, secret) => {
    const out = scrub(text, { longRuns: false }).text;
    expect(out).toContain("***");
    expect(out).not.toContain(secret);
  });
});

describe("scrub: well-known token formats", () => {
  const tokens: Record<string, string> = {
    huggingface: "hf_" + "aB3".repeat(11),
    shopify: "shpat_" + "a1".repeat(16),
    pypi: "pypi-AgE" + "aB3".repeat(20),
    vault: "hvs." + "aB3".repeat(10),
    digitalocean: "dop_v1_" + "a1".repeat(32),
    googleOauth: "ya29." + "aB3".repeat(10),
    telegram: "123456789:AA" + "aB3".repeat(11),
    discord: "M" + "aB3".repeat(8) + "." + "abc123" + "." + "xY9".repeat(9),
  };
  for (const [name, token] of Object.entries(tokens)) {
    for (const longRuns of [false, true]) {
      it(`masks ${name} (longRuns ${longRuns})`, () => {
        const out = scrub(`the value is ${token} here`, { longRuns }).text;
        expect(out).not.toContain(token.slice(4));
        expect(out).toContain("***");
      });
    }
  }

  it("masks an Azure SAS signature but keeps the other query parts", () => {
    const out = scrub("https://acct.blob.core.windows.net/c/f?sv=2022&sig=abCD12%2Bef34gh%3D&se=2030", { longRuns: false }).text;
    expect(out).not.toContain("abCD12");
    expect(out).toContain("sv=2022");
    expect(out).toContain("se=2030");
  });

  it("leaves look-alike prose and short identifiers alone", () => {
    for (const text of ["use hf_cache_dir and shpat_ prefix docs", "set pypi-AgE short", "version ya29.1 and hvs.x", "12345:AAshort", "Foo.Bar.Baz and a.b.c", "see ?sig=ok"]) {
      expect(scrub(text, { longRuns: false })).toEqual({ text, scrubbed: false });
    }
  });
});

describe("convertV3 masks like createNote", () => {
  it("masks the title, body, tags, evidence and trigger errors it writes", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });
    const token = "ghp_" + "a1B2".repeat(9);
    writeFileSync(
      join(from, "records", "mem-1.md"),
      [
        "---",
        "id: mem-1",
        `title: "Deploy with ${token}"`,
        "type: fact",
        "scope: project",
        "project: demo",
        "evidence:",
        "  - https://user:hunter2pw@host.example/path",
        "trigger_errors:",
        "  - \"re:password=(\\\\d+) refused\"",
        "  - login failed for the service account",
        "---",
        "",
        "Body with password=hunter2pw inside",
      ].join("\n"),
    );
    const report = convertV3(from, to);
    expect(report.written).toBe(1);
    const dir = join(to, "notes", "demo");
    const text = readFileSync(join(dir, readdirSync(dir).find((f) => f.endsWith(".md"))!), "utf8");
    expect(text).not.toContain(token);
    expect(text).not.toContain("hunter2pw");
    expect(text).toContain("***");
    // The masked pattern no longer compiles as intended: reported, not stored as a dead fix.
    expect(report.errors.join("\n")).toMatch(/secret masking/);
    expect(loadNotes(to).notes[0]?.errors).toEqual(["login failed for the service account"]);
  });
});

describe("error patterns are validated after masking", () => {
  it.each(["re:password=(\\d+) refused", "re:secret=[a-z]+ not accepted", "re:Authorization: Bearer \\S+ rejected"])("refuses %s", (pattern) => {
    const home = tmp();
    expect(() => createNote(home, { project: "demo", text: "Login fails", errors: [pattern] })).toThrow(NoteError);
    expect(loadNotes(home).notes).toEqual([]);
    const note = createNote(home, { project: "demo", text: "Login fails" });
    expect(() => upgradeNote(home, note, { errors: [pattern] })).toThrow(/secret masking/);
    expect(loadNotes(home).notes[0]?.errors).toEqual([]);
  });

  it("keeps a valid pattern that has no credential", () => {
    const home = tmp();
    expect(createNote(home, { project: "demo", text: "Port busy", errors: ["re:EADDRINUSE .*:\\d+"] }).errors).toEqual(["re:EADDRINUSE .*:\\d+"]);
  });

  it("brain check reports an active note whose stored pattern is invalid, not a retired one", async () => {
    const home = tmp();
    const live = createNote(home, { project: "demo", text: "Live fix" });
    const old = createNote(home, { project: "demo", text: "Old fix" });
    saveNote(home, { ...live, errors: ["re:password=*** refused"] });
    saveNote(home, { ...old, errors: ["re:(("], retired: "2026-01-01T00:00:00Z" });
    const result = await run(["check"], { env: { SECOND_BRAIN_HOME: home }, cwd: repo("demo") });
    expect(result.code).toBe(1);
    expect(result.err).toContain(live.id);
    expect(result.err).not.toContain(old.id);
  });
});

describe("same-headline dedupe", () => {
  const io = (home: string, cwd: string): Partial<Io> => ({ env: { SECOND_BRAIN_HOME: home }, cwd });

  it("matches a headline that was masked on write", async () => {
    const home = tmp();
    const cwd = repo("demo");
    const text = "Deploy key ghp_" + "a1B2".repeat(9) + " rotates monthly";
    expect((await run(["note", text], io(home, cwd))).out).toMatch(/^saved /);
    expect((await run(["note", text], io(home, cwd))).out).toMatch(/^already noted /);
    expect(loadNotes(home).notes).toHaveLength(1);
    expect(findSameHeadline(loadNotes(home).notes, text, "demo")).toBeDefined();
  });

  it("recognizes a tagged global note written again with --global --tag", async () => {
    const home = tmp();
    const cwd = repo("demo");
    const args = ["note", "--global", "--tag", "python", "Pin the interpreter in CI"];
    expect((await run(args, io(home, cwd))).out).toMatch(/^saved /);
    expect((await run(args, io(home, cwd))).out).toMatch(/^already noted /);
    expect(loadNotes(home).notes).toHaveLength(1);
  });

  it("does not match a global note tagged for other projects", () => {
    const home = tmp();
    createNote(home, { project: "global", text: "Pin the interpreter in CI", tags: ["python"] });
    const notes = loadNotes(home).notes;
    expect(findSameHeadline(notes, "Pin the interpreter in CI", "global", ["rust"])).toBeUndefined();
    expect(findSameHeadline(notes, "Pin the interpreter in CI", "demo", ["rust"])).toBeUndefined();
    expect(findSameHeadline(notes, "Pin the interpreter in CI", "demo", ["python"])).toBeDefined();
  });
});

describe("brain tested outside the note's checkout", () => {
  it("keeps the evidence hashes taken in the note's own project", async () => {
    const home = tmp();
    const y = repo("yrepo");
    const x = repo("xrepo");
    writeFileSync(join(y, "README.md"), "y readme\n");
    writeFileSync(join(x, "README.md"), "x readme, different\n");
    const note = createNote(home, { project: "yrepo", text: "Read the README first", evidence: ["README.md"], evidenceRoots: [y] });
    expect(note.evidenceSha).toHaveLength(1);
    const result = await run(["tested", note.id], { env: { SECOND_BRAIN_HOME: home }, cwd: x });
    expect(result.out).toBe(`tested ${note.id}`);
    const after = loadNotes(home).notes[0]!;
    expect(after.tested).toBe(true);
    expect(after.testedBy).toBe("owner");
    expect(after.evidenceSha).toEqual(note.evidenceSha);
  });

  it("re-hashes from the note's own checkout", async () => {
    const home = tmp();
    const y = repo("yrepo");
    writeFileSync(join(y, "README.md"), "first\n");
    const note = createNote(home, { project: "yrepo", text: "Read the README first", evidence: ["README.md"], evidenceRoots: [y] });
    writeFileSync(join(y, "README.md"), "second, verified now\n");
    await run(["tested", note.id], { env: { SECOND_BRAIN_HOME: home }, cwd: y });
    const after = loadNotes(home).notes[0]!;
    expect(after.evidenceSha).toHaveLength(1);
    expect(after.evidenceSha).not.toEqual(note.evidenceSha);
  });
});

describe("sync refuses a state that would lose the commit", () => {
  function homeRepo(): string {
    const home = tmp("brain-nm-sync-");
    git(home, "init", "-b", "main");
    git(home, "config", "user.name", "T");
    git(home, "config", "user.email", "t@example.com");
    writeFileSync(join(home, ".gitkeep"), "");
    git(home, "add", ".gitkeep");
    git(home, "commit", "-m", "init");
    return home;
  }

  it("on a detached HEAD, committing nothing", () => {
    const home = homeRepo();
    git(home, "checkout", "--detach");
    createNote(home, { project: "demo", text: "A note written while detached" });
    const before = git(home, "rev-parse", "HEAD");
    expect(() => sync(home)).toThrow(SyncError);
    expect(git(home, "rev-parse", "HEAD")).toBe(before);
  });

  it("while a merge is in progress, committing nothing", () => {
    const home = homeRepo();
    git(home, "checkout", "-b", "side");
    writeFileSync(join(home, "f.txt"), "side\n");
    git(home, "add", "f.txt");
    git(home, "commit", "-m", "side");
    git(home, "checkout", "main");
    writeFileSync(join(home, "f.txt"), "main\n");
    git(home, "add", "f.txt");
    git(home, "commit", "-m", "main");
    spawnSync("git", ["merge", "side"], { cwd: home, encoding: "utf8" });
    createNote(home, { project: "demo", text: "A note written mid-merge" });
    const before = git(home, "rev-parse", "HEAD");
    expect(() => sync(home)).toThrow(SyncError);
    expect(git(home, "rev-parse", "HEAD")).toBe(before);
  });

  it("still commits on a branch", () => {
    const home = homeRepo();
    createNote(home, { project: "demo", text: "A note on the branch" });
    expect(sync(home).committed).toBe(true);
  });
});
