/** Regressions for the issue swarm's findings (each reproduced before its fix). */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { acceptProposal, errorSignature, findFix, program, rejectProposal, scanEvents } from "../src/capture.ts";
import { main, type Io } from "../src/cli.ts";
import { convertV3 } from "../src/convert.ts";
import { createNote, formatNote, loadNotes, parseNote, retireNote, saveNote } from "../src/notes.ts";
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
    // notes/Demo → notes/demo: a real case-insensitive filesystem (Windows, macOS) already
    // resolves it; elsewhere a symlink stands in for one.
    if (!existsSync(join(home, "notes", "Demo"))) symlinkSync(join(home, "notes", "demo"), join(home, "notes", "Demo"));
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
    const merged = readFileSync(join(b, "rejected.json"), "utf8");
    expect(JSON.parse(merged).hashes).toHaveLength(3);
    expect(merged).not.toContain("from-");
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

async function cli(argv: string[], io: Partial<Io>): Promise<{ code: number; out: string; err: string }> {
  const out: string[] = [];
  const err: string[] = [];
  const code = await main(argv, { stdin: () => "", ...io, out: (t) => out.push(t), err: (t) => err.push(t) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

/** A home and a cwd whose project resolves to "demo". */
function cliSetup(): { home: string; cwd: string; io: Partial<Io> } {
  const home = tmp();
  const cwd = join(tmp(), "demo");
  mkdirSync(join(cwd, ".git"), { recursive: true });
  return { home, cwd, io: { env: { SECOND_BRAIN_HOME: home }, cwd } };
}

describe("batch 3: CLI", () => {
  it("share keeps the note visible to the project it came from", async () => {
    const { home, io } = cliSetup();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { Demo: { aliases: ["x"], note: "kept" } } }));
    const id = (await cli(["note", "Vite dev server needs --host for LAN testing"], io)).out.replace("saved ", "");
    await cli(["share", id, "--tag", "frontend"], io);
    expect((await cli(["recall", "vite dev server"], io)).out).toContain(id);
    expect(JSON.parse(readFileSync(join(home, "projects.json"), "utf8")).projects).toEqual({ Demo: { aliases: ["x"], note: "kept", tags: ["frontend"] } });
  });

  it("share refuses, moving nothing, when projects.json cannot be edited", async () => {
    const { home, io } = cliSetup();
    writeFileSync(join(home, "projects.json"), "{ broken");
    const id = (await cli(["note", "Vite dev server needs --host"], io)).out.replace("saved ", "");
    expect((await cli(["share", id, "--tag", "frontend"], io)).code).toBe(1);
    expect(loadNotes(home).notes[0]?.project).toBe("demo");
  });

  it("noting a headline again with an error and --tested upgrades the note", async () => {
    const { home, io } = cliSetup();
    const id = (await cli(["note", "Clear PYTHONHOME before running python"], io)).out.replace("saved ", "");
    expect((await cli(["note", "Clear PYTHONHOME before running python", "--kind", "gotcha", "--error", "SRE module mismatch", "--tested"], io)).out).toBe(`updated ${id}`);
    expect(loadNotes(home).notes[0]).toMatchObject({ id, kind: "gotcha", errors: ["SRE module mismatch"], tested: true });
    expect((await cli(["note", "Clear PYTHONHOME before running python"], io)).out).toBe(`already noted ${id}`);
    expect(loadNotes(home).notes[0]).toMatchObject({ kind: "gotcha", tested: true });
  });

  it("reads the README's commented note example as written", () => {
    const text = [
      "---",
      "id: n-3f9a2c1b7d",
      "kind: gotcha               # note | fact | decision | gotcha | procedure",
      "at: 2026-09-27T10:00:00Z",
      "source: agent              # agent | user | capture | commit | convert",
      "tags:                      # on global notes: only projects with one of these tags see it",
      "  - python",
      "errors:                    # error text this note fixes",
      "  - \"SRE module mismatch\"  # quoted",
      "tested: true               # only tested notes are appended",
      "---",
      "",
      "Clear PYTHONHOME",
    ].join("\n");
    expect(parseNote(text, "x.md", "demo", false)).toMatchObject({ kind: "gotcha", source: "agent", tags: ["python"], errors: ["SRE module mismatch"], tested: true });
  });

  it("--help and -h print the usage", async () => {
    const { io } = cliSetup();
    for (const flag of ["--help", "-h"]) expect(await cli([flag], io)).toMatchObject({ code: 0, out: expect.stringContaining("brain recall") });
  });

  it("check fails on a broken home and names files the loader never reads", async () => {
    const { home, io } = cliSetup();
    expect((await cli(["check", "--home", join(home, "nope")], io)).code).toBe(1);
    createNote(home, { text: "fine", project: "demo" });
    mkdirSync(join(home, "notes", "SZ Tool"), { recursive: true });
    mkdirSync(join(home, "notes", "demo", "sub"), { recursive: true });
    writeFileSync(join(home, "notes", "n-top.md"), "x");
    writeFileSync(join(home, "notes", "demo", "n-z.MD"), "x");
    mkdirSync(join(home, "work"), { recursive: true });
    writeFileSync(join(home, "work", "demo.md"), "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> theirs\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { a: "x", b: { paths: "C:/work/b" } } }));
    const result = await cli(["check"], io);
    expect(result.code).toBe(1);
    for (const bad of ["SZ Tool", join("demo", "sub"), "n-top.md", "n-z.MD", "conflict markers", "a is not an object", "b.paths"]) expect(result.err).toContain(bad);
  });

  it("the Claude Code hook counts its sessions", async () => {
    const { home, cwd, io } = cliSetup();
    createNote(home, { text: "something to show", project: "demo" });
    await cli(["hook", "claude-code"], { ...io, stdin: () => JSON.stringify({ hook_event_name: "SessionStart", source: "startup", session_id: "abc-123", cwd }) });
    expect((await cli(["stats"], io)).out).toContain("1 sessions");
  });
});

describe("batch 3: resume card", () => {
  it("keeps the last ask and the failure however many files were edited", async () => {
    const { formatAuto, AUTO_BUDGET } = await import("../src/work.ts");
    const edited = ["brain/src/search.ts", "brain/src/card.ts", "brain/src/omp.ts", "brain/src/work.ts", "brain/test/eval.test.ts", "brain/README.md", "README.md", "docs/intake/2026-09-27-plan-v4-agent-experience.md"];
    const auto = formatAuto({ edited, failure: `npx vitest run: ${"expected 412 to be less than or equal to 400 ".repeat(5)}`, ask: `Fix the flaky login test ${"and keep the card small ".repeat(10)}` });
    expect(auto).toContain("- last ask: Fix the flaky login test");
    expect(auto).toContain("- last failure: npx vitest run");
    expect(auto).toMatch(/- edited: .*docs\/intake\/2026-09-27-plan-v4-agent-experience\.md.* \+\d+ more/);
    expect(auto.length).toBeLessThanOrEqual(AUTO_BUDGET * 4);
  });
});

describe("batch 3: OMP lifecycle", async () => {
  const { default: secondBrain, CARD_TYPE } = await import("../src/omp.ts");
  const { readWork } = await import("../src/work.ts");
  type H = (e: unknown, c: unknown) => unknown;

  function omp(home: string) {
    const handlers = new Map<string, H>();
    secondBrain({ on: (e, h) => void handlers.set(e, h) }, { SECOND_BRAIN_HOME: home });
    return { handlers, fire: (e: string, event: unknown, ctx: unknown) => handlers.get(e)?.(event, ctx) };
  }
  /** A project dir "demo" and a ctx for session `id` with an optional transcript. */
  function session(id: string, cwd: string, extra: { branch?: unknown[]; hasUI?: boolean; header?: object; file?: string | null } = {}) {
    return {
      cwd,
      hasUI: extra.hasUI ?? true,
      sessionManager: {
        getSessionId: () => id,
        getSessionFile: () => (extra.file === undefined ? `/sessions/${id}.jsonl` : extra.file),
        getHeader: () => extra.header ?? {},
        getBranch: () => extra.branch ?? [],
      },
    };
  }
  function setup() {
    const home = tmp();
    const cwd = join(tmp(), "demo");
    mkdirSync(join(cwd, ".git"), { recursive: true });
    createNote(home, { text: "Demo uses pnpm, not npm", project: "demo", kind: "decision" });
    return { home, cwd, ...omp(home) };
  }

  it("puts the resume card after the compaction summary, where native compaction keeps it", () => {
    const { cwd, fire } = setup();
    const s = session("s", cwd);
    fire("before_agent_start", { prompt: "go" }, s);
    fire("context", { messages: [] }, s);
    fire("session_compact", {}, s);
    const out = fire("context", { messages: [{ role: "assistant", content: "old" }, { role: "compactionSummary", summary: "…" }, { role: "user", content: "go on" }] }, s) as { messages: { role?: string; customType?: string }[] };
    expect(out.messages.map((m) => m.customType ?? m.role)).toEqual(["assistant", "compactionSummary", CARD_TYPE, "user"]);
  });

  it("leaves OMP's background compaction on: no session_before_compact handler", () => {
    expect(setup().handlers.has("session_before_compact")).toBe(false);
  });

  it("saves the outgoing session on /new, and a fork carries its state without a second card", () => {
    const { home, cwd, fire } = setup();
    const s1 = session("s1", cwd);
    fire("before_agent_start", { prompt: "fix billing" }, s1);
    fire("tool_result", { toolName: "edit", input: { path: join(cwd, "src", "billing", "invoice.ts") }, isError: false, content: [] }, s1);
    fire("session_before_switch", { reason: "new" }, s1);
    fire("session_switch", { reason: "new" }, session("s2", cwd));
    expect(readWork(home, "demo")?.auto).toContain("src/billing/invoice.ts");

    fire("session_before_switch", { reason: "fork" }, s1);
    const forked = session("s3", cwd);
    fire("session_switch", { reason: "fork" }, forked);
    expect(fire("before_agent_start", { prompt: "continue" }, forked)).toBeUndefined();
    fire("tool_result", { toolName: "edit", input: { path: join(cwd, "src", "csv.ts") }, isError: false, content: [] }, forked);
    fire("session_compact", {}, forked);
    expect(readWork(home, "demo")?.auto).toMatch(/- edited: src\/billing\/invoice\.ts, src\/csv\.ts/);
  });

  it("does not record tool URIs as edits, and records every file of a multi-file edit", () => {
    const { home, cwd, fire } = setup();
    const s = session("s", cwd);
    fire("tool_result", { toolName: "write", input: { path: "xd://brain_note" }, isError: false, content: [] }, s);
    fire("tool_result", { toolName: "write", input: { path: "local://PLAN.md" }, isError: false, content: [] }, s);
    fire("tool_result", { toolName: "edit", input: { paths: ["src/b.ts", "src/c.ts"] }, isError: false, content: [] }, s);
    fire("session_shutdown", {}, s);
    const auto = readWork(home, "demo")?.auto ?? "";
    expect(auto).toContain("- edited: src/b.ts, src/c.ts");
    expect(auto).not.toContain("xd:");
    expect(auto).not.toContain("PLAN.md");
  });

  it("keeps the user's last ask, not OMP's synthetic continue prompt", () => {
    const { home, cwd, fire } = setup();
    const branch = [
      { type: "message", message: { role: "user", content: [{ type: "text", text: "Fix the flaky login test" }] } },
      { type: "message", message: { role: "developer", content: [{ type: "text", text: "Resume the user's latest intent." }] } },
    ];
    const s = session("s", cwd, { branch });
    fire("before_agent_start", { prompt: "Fix the flaky login test" }, s);
    fire("before_agent_start", { prompt: "Resume the user's latest intent. Re-read kept recent messages." }, s);
    fire("session_compact", {}, s);
    expect(readWork(home, "demo")?.auto).toContain("- last ask: Fix the flaky login test");
  });

  it("refreshes the working state on /handoff, which compacts without session_before_compact", () => {
    const { cwd, fire } = setup();
    const s = session("s", cwd);
    fire("before_agent_start", { prompt: "Migrate the auth middleware" }, s);
    fire("context", { messages: [] }, s);
    fire("tool_result", { toolName: "edit", input: { path: "middleware.ts" }, isError: false, content: [] }, s);
    fire("session_compact", {}, s);
    const out = fire("context", { messages: [{ role: "compactionSummary", summary: "…" }] }, s) as { messages: { content?: string }[] };
    expect(out.messages[1]?.content).toContain("- edited: middleware.ts");
    expect(out.messages[1]?.content).toContain("Migrate the auth middleware");
  });

  it("a subagent gets the card but never writes the parent's working state", () => {
    const { home, cwd, fire } = setup();
    const parent = session("p", cwd);
    fire("before_agent_start", { prompt: "Ship CSV export" }, parent);
    fire("session_shutdown", {}, parent);
    const sub = session("sub", cwd, { hasUI: false, header: { parentSession: "/sessions/p.jsonl" } });
    expect(fire("before_agent_start", { prompt: "Write unit tests for parse.ts" }, sub)).toBeDefined();
    fire("tool_result", { toolName: "edit", input: { path: "test/parse.test.ts" }, isError: false, content: [] }, sub);
    fire("session_shutdown", {}, sub);
    expect(readWork(home, "demo")?.auto).toContain("Ship CSV export");
    expect(readWork(home, "demo")?.auto).not.toContain("parse");
  });

  it("sends one card when compaction runs before the session's first prompt", () => {
    const { cwd, fire } = setup();
    const s = session("s", cwd);
    const start = fire("before_agent_start", { prompt: "go" }, s) as { message: object };
    fire("session_compact", {}, s);
    const messages = [{ role: "compactionSummary", summary: "…" }, { role: "custom", ...start.message }, { role: "user", content: "go" }];
    expect(fire("context", { messages }, s)).toBeUndefined();
  });

  it("failures fixed in earlier sessions become proposals after the first card, off its critical path", () => {
    const { home, cwd, fire } = setup();
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const line = (o: object) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "old", cwd, tool: "bash", ...o }) + "\n";
    writeFileSync(join(home, "state", "events", "old.jsonl"), line({ command: "npm test", ok: false, error: "Error: missing dependency" }) + line({ command: "npm ci && npm test", ok: true }));
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    try {
      fire("before_agent_start", { prompt: "go" }, session("new", cwd));
      vi.runOnlyPendingTimers();
    } finally {
      vi.useRealTimers();
    }
    const next = fire("before_agent_start", { prompt: "go" }, session("next", cwd)) as { message: { content: string } };
    expect(next.message.content).toMatch(/1 proposal/);
  });
});

describe("batch 3: privacy and security", () => {
  it("a rejection syncs as a hash, never as the declined text", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const line = (o: object) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "bash", ...o }) + "\n";
    writeFileSync(join(home, "state", "rejected.json"), JSON.stringify({ texts: ["ssh: ssh deploy@10.20.0.5 -i ~/.ssh/acme_prod fails"], signatures: [] }));
    writeFileSync(join(home, "state", "events", "s.jsonl"), line({ command: "deploy --token-file ./prod.tok", ok: false, error: "deploy: 401 unauthorized for acme-prod" }) + line({ command: "deploy --token-file ./prod.tok --refresh", ok: true }));
    const [p] = scanEvents(home, []);
    rejectProposal(home, p?.id ?? "");
    const synced = readFileSync(join(home, "rejected.json"), "utf8");
    expect(synced).not.toMatch(/acme|deploy|10\.20/);
    expect(JSON.parse(synced).hashes).toHaveLength(3);
    writeFileSync(join(home, "state", "events", "t.jsonl"), line({ command: "deploy --token-file ./prod.tok", ok: false, error: "deploy: 401 unauthorized for acme-prod" }) + line({ command: "deploy --token-file ./prod.tok --refresh", ok: true }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("a global fix the agent writes through the tool is not tested until the owner says so", async () => {
    const { default: secondBrain } = await import("../src/omp.ts");
    const home = tmp();
    const tools: { name: string; execute: (...a: unknown[]) => { content: { text: string }[] } }[] = [];
    secondBrain({ on: () => undefined, registerTool: (t) => void tools.push(t as never) }, { SECOND_BRAIN_HOME: home });
    const note = tools.find((t) => t.name === "brain_note");
    const ctx = { cwd: home, sessionManager: { getSessionId: () => "s" } };
    const out = note?.execute("id", { text: "Toolchain repair: run the fix script", kind: "gotcha", error: "npm ERR! code E401", tested: true, global: true }, undefined, undefined, ctx);
    expect(out?.content[0]?.text).toContain("untested");
    expect(loadNotes(home).notes[0]).toMatchObject({ project: "global", tested: false });
    expect(note?.execute("id", { text: "Catch-all fix", error: "re:.", tested: true }, undefined, undefined, ctx).content[0]?.text).toMatch(/^brain: error pattern matches almost anything/);
  });

  it("masks Stripe, GitLab, npm and SendGrid tokens, private key blocks and vendor keys", () => {
    const light = (t: string) => scrub(t, { longRuns: false }).text;
    expect(light("curl -u sk_live_4eC39HqLyjWDarjtT1zdp7dc: https://api.stripe.com")).not.toContain("4eC39H");
    expect(light("token glpat-abcdefghijklmnopqrst12 ok")).toBe("token *** ok");
    expect(light("//registry.npmjs.org/:_authToken npm_abcdefghijklmnopqrstuvwxyz0123456789")).not.toContain("npm_abc");
    expect(light("SG.abcdefghijklmnop12.qrstuvwxyzabcdef34")).toBe("***");
    const pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n-----END OPENSSH PRIVATE KEY-----";
    expect(light(`key:\n${pem}\nnext`)).toBe("key:\n-----BEGIN OPENSSH PRIVATE KEY----- *** -----END PRIVATE KEY-----\nnext");
    expect(light("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA")).not.toContain("MIIE");
    expect(light("MAILGUN_KEY=key-3ax6xnjp29jd6fds4gc373sgvjxteol0")).toBe("MAILGUN_KEY=***");
    expect(light("cache_key=homepage sort_key=name")).toBe("cache_key=homepage sort_key=name");
  });

  it("masks a credential the log's cut goes through", async () => {
    const { appendEvent } = await import("../src/capture.ts");
    const home = tmp();
    const error = `${"x".repeat(250)}fatal: unable to access 'https://ci-deploy:Zq8vR2mK9pL4xW7nQ3tY@git.example.com/r.git'\n${"y".repeat(700)}`;
    appendEvent(home, "s", home, { tool: "bash", command: "git submodule update", ok: false, error });
    expect(readFileSync(join(home, "state", "events", "s.jsonl"), "utf8")).not.toMatch(/Zq8v/);
  });

  it("skips a catastrophically backtracking pattern instead of hanging", () => {
    const home = tmp();
    const note = { ...createNote(home, { text: "x fix", project: "global", tested: true }), errors: ["re:(\\w+\\s?)+: command not found"] };
    const started = performance.now();
    expect(findFix([note], `${"word ".repeat(20)}failed`, null)).toBeNull();
    expect(performance.now() - started).toBeLessThan(200);
    expect(() => createNote(home, { text: "y", project: "global", errors: ["re:(\\w+\\s?)+: command not found"] })).toThrow(/backtrack/);
  });

  it("scrubs a long dotted line in linear time", () => {
    const started = performance.now();
    scrub(`Brain-Decision: ${"a.".repeat(150_000)}`);
    expect(performance.now() - started).toBeLessThan(1000);
  });

  it("never lets a projects.json key make a project global", async () => {
    const { resolveProject } = await import("../src/project.ts");
    const home = tmp();
    const dir = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { Global: { paths: [dir] } } }));
    expect(resolveProject(home, dir, {}).id).toBe("global-project");
  });
});

describe("batch 4: Windows command shapes", () => {
  it("pairs by the program that ran, however Windows or a notebook spells it", () => {
    expect(program('"C:/Program Files/Git/cmd/git.exe" push origin main')).toBe("git");
    expect(program('"C:/Program Files/nodejs/npm.cmd" test')).toBe("npm");
    expect(program("$env:PYTHONHOME = $null; python -m second_brain doctor")).toBe("python");
    expect(program('& "C:\\Python311\\python.exe" -m pytest')).toBe("python");
    expect(program("cmd /c npm test")).toBe("npm");
    expect(program("%%bash\ngit push origin main")).toBe("git");
    expect(program("!pip install pandas")).toBe("pip");
  });

  it("never pairs two Python cells as a failed command and its fix", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const line = (o: object) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "ipython", ...o }) + "\n";
    writeFileSync(
      join(home, "state", "events", "s.jsonl"),
      line({ command: "import pandas as pd", ok: false, error: "ModuleNotFoundError: No module named 'pandas'" }) +
        line({ command: "import os", ok: true }) +
        line({ command: "%%bash\ngit push origin main", ok: false, error: "error: failed to push some refs" }) +
        line({ command: "%%bash\ngit push --set-upstream origin main", ok: true }),
    );
    expect(scanEvents(home, []).map((p) => p.text.split("\n")[0])).toEqual([expect.stringMatching(/^git: /)]);
  });
});
