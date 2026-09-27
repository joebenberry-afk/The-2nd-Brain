/** Regressions for the issue swarm's findings (each reproduced before its fix). */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { acceptProposal, errorSignature, findFix, program, rejectProposal, scanEvents } from "../src/capture.ts";
import { convertV3 } from "../src/convert.ts";
import { createNote, formatNote, loadNotes, retireNote, saveNote } from "../src/notes.ts";
import { scrub } from "../src/scrub.ts";
import { loadProjects, normalizeRemote } from "../src/project.ts";
import { answer, recall } from "../src/search.ts";
import { sync, SyncError } from "../src/sync.ts";
import { writeAtomic } from "../src/util.ts";

const tmp = (p = "brain-swarm-") => mkdtempSync(join(tmpdir(), p));
const demo = { id: "demo", tags: [], root: null };
const v3Record = (id: string, extra = "") =>
  `---\nid: ${id}\ntitle: A fact\ntype: fact\nscope: project\nproject: demo\nstatus: current\ngrade: TESTED\nrecorded_at: 2026-01-01T00:00:00+00:00\n${extra}---\n\nBody.\n`;

describe("convert", () => {
  it("leaves an unparseable projects.json alone and says so", () => {
    const from = tmp();
    mkdirSync(join(from, "projects", "p1"), { recursive: true });
    writeFileSync(join(from, "projects", "p1", "project.toml"), 'id = "p1"\nrepo_path = "C:/p1"\n');
    const to = tmp();
    const broken = '{"projects":{"sztool":{"aliases":["sz-tool"]},}}';
    writeFileSync(join(to, "projects.json"), broken);
    const report = convertV3(from, to);
    expect(readFileSync(join(to, "projects.json"), "utf8")).toBe(broken);
    expect(report.errors.join("\n")).toContain("left untouched");
  });

  it("merges into projects.json as written, keeping keys it does not know", () => {
    const from = tmp();
    mkdirSync(join(from, "projects", "p1"), { recursive: true });
    writeFileSync(join(from, "projects", "p1", "project.toml"), 'id = "p1"\n');
    const to = tmp();
    writeFileSync(join(to, "projects.json"), JSON.stringify({ projects: { "SZ_Tool": { aliases: ["x"], note: "hand-written" } } }));
    convertV3(from, to);
    expect(JSON.parse(readFileSync(join(to, "projects.json"), "utf8")).projects).toEqual({ SZ_Tool: { aliases: ["x"], note: "hand-written" }, p1: {} });
  });

  it("never overwrites a note file that no longer parses", () => {
    const from = tmp();
    mkdirSync(join(from, "records"), { recursive: true });
    writeFileSync(join(from, "records", "mem-abcdef123456.md"), v3Record("mem-abcdef123456"));
    const to = tmp();
    mkdirSync(join(to, "notes", "demo"), { recursive: true });
    writeFileSync(join(to, "notes", "demo", "mem-abcdef123456.md"), "hand edited, frontmatter broken");
    expect(convertV3(from, to)).toMatchObject({ written: 0, skipped: 1 });
    expect(readFileSync(join(to, "notes", "demo", "mem-abcdef123456.md"), "utf8")).toBe("hand edited, frontmatter broken");
  });

  it("reports a source without V3 data instead of claiming success", () => {
    expect(convertV3(join(tmp(), "nope"), tmp()).errors[0]).toContain("no V3 records/ or projects/");
  });

  it("never writes outside the home for hostile ids or projects", () => {
    const from = tmp();
    mkdirSync(join(from, "records"), { recursive: true });
    writeFileSync(join(from, "records", "a.md"), v3Record("../../../escaped"));
    writeFileSync(join(from, "records", "b.md"), v3Record("mem-bbbbbb", "").replace("project: demo", "project: ../../../outside"));
    const to = join(tmp(), "home");
    mkdirSync(to);
    const report = convertV3(from, to);
    expect(report.errors.some((e) => e.includes("not a V3 record id"))).toBe(true);
    expect(existsSync(join(to, "..", "escaped.md"))).toBe(false);
    expect(loadNotes(to).notes.map((n) => n.project)).toEqual(["outside"]);
  });

  it("saveNote refuses unsafe ids and project names", () => {
    const home = tmp();
    const base = createNote(home, { text: "x", project: "demo" });
    expect(() => saveNote(home, { ...base, id: "../evil" })).toThrow(/unsafe note id/);
    expect(() => saveNote(home, { ...base, project: "../up" })).toThrow(/not a project id/);
  });
});

describe("recall", () => {
  it("searches and shows the whole first line of a one-line note", () => {
    const home = tmp();
    const long = "Vitest in this repo runs with the forks pool because the threads pool deadlocks on Windows when tests spawn child processes; the fix is to set pool: 'forks' in vitest.config.ts and keep testTimeout at 30000 for the installer tests that call pwsh";
    createNote(home, { text: long, project: "demo", kind: "gotcha" });
    const { notes } = loadNotes(home);
    expect(recall(notes, "testTimeout", { project: demo })).toHaveLength(1);
    expect(answer(notes, "vitest forks pool", { project: demo })).toContain("testTimeout at 30000");
  });

  it("renders every hit on one line", () => {
    const home = tmp();
    createNote(home, { text: "Release checklist for widget\n\n1. bump version\n2. run npm test\n3. tag and push", project: "demo", kind: "procedure" });
    expect(answer(loadNotes(home).notes, "widget release checklist", { project: demo }).split("\n")).toHaveLength(1);
  });

  it("puts a better retired answer first and keeps the limit", () => {
    const home = tmp();
    for (const text of ["Staging cluster deploy on Fridays is slow", "Staging cluster deploy on Fridays needs approval", "Staging cluster deploy on Fridays pages oncall"]) createNote(home, { text, project: "demo" });
    const old = createNote(home, { text: "Deploy target is the staging cluster on Fridays", project: "demo", kind: "decision" });
    retireNote(home, old.id);
    const lines = answer(loadNotes(home).notes, "deploy target staging cluster fridays", { project: demo }).split("\n");
    expect(lines.length).toBeLessThanOrEqual(3);
    expect(lines[0]).toContain(old.id);
    expect(answer(loadNotes(home).notes, "deploy target staging cluster fridays", { project: demo, limit: 1 }).split("\n")).toHaveLength(1);
  });

  it("finds a project's own note however many other projects match first", () => {
    const home = tmp();
    for (let i = 0; i < 210; i++) createNote(home, { text: `deploy note ${i} deploy deploy`, project: "big" });
    createNote(home, { text: "Run the deploy only after the smoke test passes", project: "small" });
    expect(answer(loadNotes(home).notes, "deploy", { project: { id: "small", tags: [], root: null } })).toContain("smoke test");
  });

  it("names the replacement when a retired note is read by id", () => {
    const home = tmp();
    const old = createNote(home, { text: "old rule", project: "demo" });
    const next = createNote(home, { text: "new rule", project: "demo" });
    retireNote(home, old.id, next.id);
    expect(answer(loadNotes(home).notes, old.id, { project: demo }).split("\n")[0]).toContain(`replaced by ${next.id}`);
  });

  it("recalls non-Latin text", () => {
    const home = tmp();
    createNote(home, { text: "Сервер падает при старте без переменной PORT", project: "demo" });
    expect(recall(loadNotes(home).notes, "сервер падает", { project: demo })).toHaveLength(1);
  });
});

describe("capture", () => {
  it("pairs the program that actually ran, not cd or env options", () => {
    expect(program("cd brain && npx tsc --noEmit")).toBe("npx");
    expect(program("cd brain && git status --short")).toBe("git");
    expect(program("env -u PYTHONHOME python app.py")).toBe("python");
    expect(program("PYTHONHOME= python app.py")).toBe("python");
    expect(program("sudo -E env -i FOO=1 make")).toBe("make");
  });

  it("signs a traceback or a pytest run by its specific error line", () => {
    const traceback = 'Traceback (most recent call last):\n  File "src/app/main.py", line 3, in <module>\n    import redis\nModuleNotFoundError: No module named \'redis\'';
    expect(errorSignature(traceback)).toBe("ModuleNotFoundError: No module named 'redis'");
    const pytest = "============================= test session starts ==============================\ncollected 2 items\n\ntests/test_a.py F.\n\n=================================== FAILURES ===================================\n___________________________________ test_x ___________________________________\n>       assert add(1, 1) == 3\nE       AssertionError: assert 2 == 3";
    expect(errorSignature(pytest)).toBe("AssertionError: assert 2 == 3");
    expect(errorSignature("src/a.ts(12,5): error TS2322: Type 'x' is not assignable\nsrc/b.ts(1,1): error TS2304")).toBe("src/a.ts(12,5): error TS2322: Type 'x' is not assignable");
  });

  it("keeps a long traceback's last line in the event log", async () => {
    const { appendEvent } = await import("../src/capture.ts");
    const home = tmp();
    const frames = Array.from({ length: 40 }, (_, i) => `  File "/srv/app/module_${i}.py", line ${i}, in handler_${i}`).join("\n");
    appendEvent(home, "s", home, { tool: "bash", command: "python app.py", ok: false, error: `Traceback (most recent call last):\n${frames}\nKeyError: 'DATABASE_URL'` });
    const logged = JSON.parse(readFileSync(join(home, "state", "events", "s.jsonl"), "utf8"));
    expect(errorSignature(logged.error)).toBe("KeyError: 'DATABASE_URL'");
  });

  it("does not propose again what was accepted and later retired, or rejected on another machine", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const line = (o: object) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "bash", ...o }) + "\n";
    const pair = (fail: string, fix: string, error: string) => line({ command: fail, ok: false, error }) + line({ command: fix, ok: true });
    writeFileSync(join(home, "state", "events", "a.jsonl"), pair("make", "make -C src", "make: *** No rule to make target 'all'"));
    const [first] = scanEvents(home, []);
    const note = acceptProposal(home, first?.id ?? "");
    retireNote(home, note.id);
    writeFileSync(join(home, "state", "events", "b.jsonl"), pair("make", "make -C src", "make: *** No rule to make target 'all'"));
    expect(scanEvents(home, loadNotes(home).notes)).toEqual([]);

    writeFileSync(join(home, "state", "events", "c.jsonl"), pair("tsc", "tsc -p .", "error TS5058: The specified path does not exist"));
    const [second] = scanEvents(home, loadNotes(home).notes);
    rejectProposal(home, second?.id ?? "");
    expect(existsSync(join(home, "rejected.json"))).toBe(true);
    const other = tmp();
    mkdirSync(join(other, "state", "events"), { recursive: true });
    writeFileSync(join(other, "rejected.json"), readFileSync(join(home, "rejected.json")));
    writeFileSync(join(other, "state", "events", "c.jsonl"), pair("tsc", "tsc -p .", "error TS5058: The specified path does not exist"));
    expect(scanEvents(other, [])).toEqual([]);
  });

  it("scrubs and matches a huge error line in bounded time", () => {
    const dots = ".".repeat(50_000);
    const started = performance.now();
    scrub(`Ran 50000 tests\n${dots}\nFAILED (failures=1)`);
    const note = { ...createNote(tmp(), { text: "x", project: "global", errors: ["FAILED (failures=1)"], tested: true }) };
    findFix([note], `${dots}\nFAILED (failures=1)`, null);
    expect(performance.now() - started).toBeLessThan(500);
  });
});

it("formatNote still writes what parseNote reads after all of this", () => {
  const home = tmp();
  const note = createNote(home, { text: "headline\n\nbody", project: "demo", errors: ["a: b # c"], tags: ["C++", "Type Script"] });
  expect(readFileSync(note.path, "utf8")).toBe(formatNote({ ...note }));
  expect(spawnSync("git", ["--version"]).status).toBe(0);
});

const git = (cwd: string, ...args: string[]) => {
  const r = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout;
};

/** A bare remote with two clones, a and b, both on main. */
function twoClones(): { a: string; b: string } {
  const root = tmp();
  const [bare, a, b] = [join(root, "remote.git"), join(root, "a"), join(root, "b")];
  git(root, "init", "--bare", "-b", "main", bare);
  for (const dir of [a, b]) {
    git(root, "clone", "-q", bare, dir);
    git(dir, "config", "user.name", "T");
    git(dir, "config", "user.email", "t@example.com");
    git(dir, "checkout", "-q", "-B", "main");
  }
  writeFileSync(join(a, ".gitkeep"), "");
  git(a, "add", ".gitkeep");
  git(a, "commit", "-qm", "init");
  git(a, "push", "-q", "-u", "origin", "main");
  git(b, "pull", "-q", "origin", "main");
  git(b, "branch", "-q", "--set-upstream-to=origin/main");
  return { a, b };
}

describe("batch 2: Windows and sync", () => {
  it("reads a projects.json saved with a BOM (Windows PowerShell 5 Set-Content)", () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), "\uFEFF" + JSON.stringify({ projects: { app: { aliases: ["the-app"] } } }));
    expect(Object.keys(loadProjects(home))).toEqual(["app"]);
  });

  it("matches local-path remotes however the slashes and drive are written", () => {
    expect(normalizeRemote("C:\\repos\\App.git")).toBe("repos/app");
    expect(normalizeRemote("C:/repos/app")).toBe("repos/app");
    expect(normalizeRemote("\\\\nas\\git\\app.git")).toBe("nas/git/app");
    expect(normalizeRemote("git@github.com:o/r.git")).toBe("github.com/o/r");
  });

  it("masks credentials set with setx or SetEnvironmentVariable", () => {
    expect(scrub("setx DB_PASSWORD hunter2hunter2").text).toBe("setx DB_PASSWORD ***");
    expect(scrub('setx GITHUB_TOKEN "abcdefgh12345"').text).toBe("setx GITHUB_TOKEN ***");
    expect(scrub('[Environment]::SetEnvironmentVariable("API_KEY", "abc def 123", "User")').text).toBe(
      '[Environment]::SetEnvironmentVariable("API_KEY", "***", "User")',
    );
    expect(scrub("setx PATH C:\\tools").text).toBe("setx PATH C:\\tools");
  });

  it("never leaves a temp file behind when the rename fails", () => {
    const dir = tmp();
    mkdirSync(join(dir, "target"));
    expect(() => writeAtomic(join(dir, "target"), "x")).toThrow();
    expect(readdirSync(dir)).toEqual(["target"]);
  });

  it("does not delete a re-saved note when its old path is the same file under another name", () => {
    const home = tmp();
    const note = createNote(home, { text: "keep me", project: "demo" });
    // notes/Demo → notes/demo stands in for a case-insensitive filesystem.
    symlinkSync(join(home, "notes", "demo"), join(home, "notes", "Demo"));
    saveNote(home, { ...note, path: join(home, "notes", "Demo", `${note.id}.md`) });
    expect(existsSync(join(home, "notes", "demo", `${note.id}.md`))).toBe(true);
  });

  it("never syncs a Private folder in another case, or a leftover temp file", () => {
    const { a } = twoClones();
    createNote(a, { text: "shared", project: "demo" });
    mkdirSync(join(a, "notes", "demo", "Private"), { recursive: true });
    writeFileSync(join(a, "notes", "demo", "Private", "n-secret.md"), "---\nid: n-secret\n---\n\nmine\n");
    writeFileSync(join(a, "notes", "demo", "n-x.md.123.abc.tmp"), "partial");
    sync(a, { push: false });
    expect(git(a, "ls-files", "notes")).not.toMatch(/Private|\.tmp/);
  });

  it("merges rejections from two machines instead of failing the sync", () => {
    const { a, b } = twoClones();
    const rejected = (signatures: string[]) => JSON.stringify({ signatures, texts: [] }, null, 2) + "\n";
    writeFileSync(join(a, "rejected.json"), rejected(["base"]));
    sync(a);
    sync(b);
    writeFileSync(join(a, "rejected.json"), rejected(["base", "from-a"]));
    sync(a);
    writeFileSync(join(b, "rejected.json"), rejected(["base", "from-b"]));
    expect(sync(b)).toMatchObject({ pulled: true, pushed: true });
    expect(JSON.parse(readFileSync(join(b, "rejected.json"), "utf8")).signatures.sort()).toEqual(["base", "from-a", "from-b"]);
    expect(git(b, "status", "--porcelain")).toBe("");
  });

  it("reports a conflict between pulled changes and uncommitted non-Brain edits instead of success", () => {
    const { a, b } = twoClones();
    writeFileSync(join(a, "README.md"), "one\n");
    git(a, "add", "README.md");
    git(a, "commit", "-qm", "readme");
    git(a, "push", "-q");
    git(b, "pull", "-q");
    writeFileSync(join(a, "README.md"), "two from a\n");
    git(a, "commit", "-qam", "readme a");
    git(a, "push", "-q");
    writeFileSync(join(b, "README.md"), "two from b, not committed\n");
    createNote(b, { text: "a note on b", project: "demo" });
    expect(() => sync(b)).toThrow(SyncError);
    expect(git(b, "stash", "list")).toContain("autostash");
  });

  it("gives the same captured pair the same proposal id on every machine and scan", () => {
    const events = [
      { command: "make", ok: false, error: "make: *** No rule to make target 'all'" },
      { command: "make -C src", ok: true },
    ].map((o) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "bash", ...o }) + "\n").join("");
    const ids = [tmp(), tmp()].map((home) => {
      mkdirSync(join(home, "state", "events"), { recursive: true });
      writeFileSync(join(home, "state", "events", "s.jsonl"), events);
      return scanEvents(home, []).map((p) => p.id);
    });
    expect(ids[0]).toHaveLength(1);
    expect(ids[1]).toEqual(ids[0]);
  });
});
