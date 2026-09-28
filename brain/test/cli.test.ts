import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { main, type Io } from "../src/cli.ts";
import { createNote, loadNotes } from "../src/notes.ts";
import { appendEvent, renderFix, scanEvents } from "../src/capture.ts";
import { estimateTokens } from "../src/util.ts";
import { readWork } from "../src/work.ts";
import { logUse } from "../src/telemetry.ts";

const tmp = (p = "brain-cli-") => mkdtempSync(join(tmpdir(), p));

/** A temp git repo whose project id resolves to `name`. */
function repo(name: string): string {
  const dir = join(tmp(), name);
  mkdirSync(join(dir, ".git"), { recursive: true });
  writeFileSync(join(dir, ".git", "config"), "[core]\n\tbare = false\n");
  return dir;
}

async function run(argv: string[], io: Partial<Io> = {}): Promise<{ code: number; out: string; err: string }> {
  const out: string[] = [];
  const err: string[] = [];
  const code = await main(argv, { stdin: () => "", ...io, out: (s) => out.push(s), err: (s) => err.push(s) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

function setup(): { home: string; cwd: string; io: Partial<Io> } {
  const home = tmp();
  const cwd = repo("demo");
  return { home, cwd, io: { env: { SECOND_BRAIN_HOME: home }, cwd } };
}

describe("brain cli", () => {
  it("delivers cards, fixes and auto-save even when pending cleanup is locked", async () => {
    const { home, cwd, io } = setup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const hook = (payload: object) => run(["hook", "claude-code"], { ...io, stdin: () => JSON.stringify({ cwd, session_id: "locked", ...payload }) });
    const remove = fs.rmSync;
    const locked = vi.spyOn(fs, "rmSync").mockImplementation((path, options) => {
      if (String(path).includes("pending-fixes")) throw Object.assign(new Error("locked"), { code: "EPERM" });
      return remove(path, options);
    });
    syncBuiltinESMExports();
    try {
      expect((await hook({ hook_event_name: "SessionStart" })).out).toContain(note.id);
      const failure = { hook_event_name: "PostToolUseFailure", tool_name: "Bash", tool_input: { command: "npm test" }, error: "runtime mismatch" };
      expect((await hook(failure)).out).toContain(note.id);
      expect((await hook(failure)).out).toContain(note.id);
      for (const event of ["SessionEnd", "PreCompact"]) {
        await hook({ hook_event_name: "PostToolUse", tool_name: "Edit", tool_input: { file_path: event + ".ts" } });
        await hook({ hook_event_name: event });
        expect(readWork(home, "demo")?.auto).toContain(event + ".ts");
      }
      await hook({ hook_event_name: "SubagentStop", agent_id: "child" });
    } finally {
      locked.mockRestore();
      syncBuiltinESMExports();
    }
  });

  it("logs CLI recall ids, silence and scrubbed queries without private answer text", async () => {
    const { home, io } = setup();
    const note = createNote(home, { project: "demo", text: "Private deployment detail", private: true });
    await run(["recall", note.id], io);
    await run(["recall", "password=" + "syntheticCredential123" + " " + "missing ".repeat(40)], io);
    const text = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8");
    const rows = text.trim().split("\n").map(line => JSON.parse(line));
    expect(rows[0]).toMatchObject({ via: "cli", query: note.id, ids: [note.id] });
    expect(rows[1]).toMatchObject({ query: ("password=*** " + "missing ".repeat(40)).slice(0, 200), ids: [] });
    expect(text).not.toContain(note.body);
    expect(text).not.toContain("syntheticCredential123");
  });

  it("pauses a fix that helped under half of 4+ runs until its note is edited", async () => {
    const { home, io } = setup();
    const note = createNote(home, { project: "demo", text: "Review this repair", tested: true, errors: ["Error: widget registry locked"] });
    const before = readFileSync(note.path, "utf8");
    expect((await run(["fix", "Error: widget registry locked"], io)).out).toContain(note.id);
    const base = { project: "demo", tokens: 0, ms: 0 };
    for (const [id, outcomes] of [[note.id, ["helped", "missed", "missed", "missed"]], ["half", ["helped", "helped", "missed", "missed"]], ["few", ["missed", "missed", "missed"]]] as const) {
      for (const outcome of outcomes) {
        logUse(home, { ...base, kind: "fix", id });
        logUse(home, { ...base, kind: "fixout", id, outcome });
      }
    }
    await run(["recall", "missing"], io);
    await run(["recall", note.id], io);
    const measured = await run(["stats"], io);
    expect(measured.code).toBe(0);
    expect(measured.out).toContain(`fix outcomes: ${note.id} helped 1/missed 3`);
    expect(measured.out).toContain("recall: 2 queries logged, 1 silent");
    for (const output of [measured.out, (await run(["review"], io)).out]) {
      const listed = (output.split("Fixes to review")[1] ?? "").split("\n").slice(1).filter((line) => line.startsWith("  ")).map((line) => line.trim());
      expect(listed).toEqual([note.id]);
      expect(output).not.toContain("nothing to review");
    }
    // Paused: the failing fix no longer fires, and its note file is untouched.
    expect((await run(["fix", "Error: widget registry locked"], io)).out).toBe("");
    expect(readFileSync(note.path, "utf8")).toBe(before);
    // Editing the note starts a new trial.
    const later = new Date(Date.now() + 5000);
    utimesSync(note.path, later, later);
    expect((await run(["fix", "Error: widget registry locked"], io)).out).toContain(note.id);
  });

  it("ranks outcome lines by total firings, not session counts, and limits them to five", async () => {
    const { home, io } = setup();
    const base = { project: "demo", tokens: 0, ms: 0, session: "same" };
    for (let i = 0; i < 6; i++) {
      for (let n = 0; n <= i; n++) logUse(home, { ...base, kind: "fix", id: `fix-${i}` });
      logUse(home, { ...base, kind: "fixout", id: `fix-${i}`, outcome: "helped" });
    }
    const measured = await run(["stats"], io);
    expect(measured.out.split("\n").filter(line => line.startsWith("fix outcomes:"))).toEqual([5, 4, 3, 2, 1].map(i => `fix outcomes: fix-${i} helped 1/missed 0`));
  });

  it("Claude hooks score retries across processes and clear pending fixes at session boundaries", () => {
    const { home, cwd } = setup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const hook = (hook_event_name: string, session_id: string, tool_input: object = {}, tool_name = "Bash", extra = {}) => {
      const child = spawnSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "hook", "claude-code", "--home", home], { cwd, encoding: "utf8", env: { ...process.env, BRAIN_PROJECT: "demo" }, input: JSON.stringify({ hook_event_name, session_id, cwd, tool_name, tool_input, error: "runtime mismatch", ...extra }) });
      expect(child.status).toBe(0);
      return child.stdout;
    };
    expect(hook("PostToolUseFailure", "help", { command: "build" })).toContain(note.id);
    hook("PostToolUse", "other", { command: "build" });
    hook("PostToolUse", "help", { command: "test" });
    hook("Stop", "help");
    hook("PostToolUse", "help", { command: "build" });
    hook("PostToolUse", "help", { command: "build" });
    hook("PostToolUseFailure", "miss", {}, "Edit");
    hook("PostToolUseFailure", "miss", {}, "Edit");
    hook("PostToolUse", "miss", {}, "Edit");
    hook("PostToolUseFailure", "empty-error", { command: "build" });
    hook("PostToolUseFailure", "empty-error", { command: "build" }, "Bash", { error: "" });
    for (const boundary of ["SessionEnd", "PreCompact"]) {
      hook("PostToolUseFailure", boundary, { command: "build" });
      hook(boundary, boundary);
      hook("PostToolUse", boundary, { command: "build" });
    }
    const outcomes = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line)).filter(row => row.kind === "fixout");
    expect(outcomes.map(row => [row.session, row.id, row.outcome, row.via])).toEqual([["help", note.id, "helped", "hook"], ["miss", note.id, "missed", "hook"], ["miss", note.id, "helped", "hook"], ["empty-error", note.id, "missed", "hook"]]);
  });
  it("prints usage for help and no command; rejects unknown commands and options", async () => {
    const { io } = setup();
    expect((await run([], io)).out).toContain("brain recall");
    expect((await run(["help"], io)).code).toBe(0);
    expect(await run(["frobnicate"], io)).toMatchObject({ code: 1 });
    const bad = await run(["recall", "x", "--nope"], io);
    expect(bad.code).toBe(1);
    expect(bad.err).toMatch(/^brain: /);
  });

  it("--home picks the Brain home explicitly", async () => {
    const home = tmp();
    await run(["note", "explicit home note", "--home", home], { env: {}, cwd: repo("demo") });
    expect(loadNotes(home).notes).toHaveLength(1);
  });

  it("offers an executable CLI widening flag", async () => {
    const { home, io } = setup();
    createNote(home, { text: "Foreign zebras", project: "other" });
    const result = await run(["recall", "zebras"], io);
    expect(result.out).toContain("(--all)");
    expect(result.out).not.toContain("all: true");
    expect((await run(["recall", "zebras", "--all"], io)).out).toContain("Foreign zebras");
  });

  it("note → recall → show → tested → retire", async () => {
    const { io } = setup();
    const saved = await run(["note", "Migrations", "apply", "in", "numeric", "order", "--kind", "procedure", "--tag", "db"], io);
    expect(saved.code).toBe(0);
    const id = saved.out.replace("saved ", "");
    expect(id).toMatch(/^n-[0-9a-f]{10}$/);
    const found = await run(["recall", "migration", "order"], io);
    expect(found.out).toContain(id);
    expect(found.out).toContain("[procedure]");
    expect((await run(["recall", "nothing-like-this"], io)).out.split("\n")).toHaveLength(1);
    expect((await run(["show", id], io)).out).toContain("kind: procedure");
    expect((await run(["tested", id], io)).out).toBe(`tested ${id}`);
    expect((await run(["recall", "migration", "order"], io)).out).toContain("[procedure, tested]");
    expect((await run(["retire", id], io)).out).toBe(`retired ${id}`);
    // nothing current answers any more, so the retired note shows as history
    expect((await run(["recall", "migration", "order"], io)).out).toMatch(new RegExp(`^${id} \\[procedure, tested\\] Migrations apply in numeric order \\(retired \\d{4}-\\d{2}-\\d{2}\\)`));
    expect((await run(["recall", "migration", "order", "--history"], io)).out).toContain("retired");
  });

  it("validates note options", async () => {
    const { io } = setup();
    expect((await run(["note"], io)).code).toBe(1);
    expect((await run(["note", "x", "--kind", "essay"], io)).err).toContain("unknown kind");
    expect((await run(["note", "x", "--global", "--private"], io)).code).toBe(1);
    expect((await run(["show", "n-missing"], io)).code).toBe(1);
    expect((await run(["recall"], io)).code).toBe(1);
    expect((await run(["recall", "x", "-n", "0"], io)).code).toBe(1);
  });

  it("scopes notes: --global is visible elsewhere, --project overrides resolution", async () => {
    const { home, io } = setup();
    await run(["note", "shared", "fact", "about", "zebras", "--global"], io);
    await run(["note", "private", "fact", "about", "zebras", "--private"], io);
    const other = { env: { SECOND_BRAIN_HOME: home }, cwd: repo("other") };
    const seen = await run(["recall", "zebras"], other);
    expect(seen.out).toContain("shared fact");
    expect(seen.out).not.toContain("private fact");
    expect((await run(["recall", "zebras", "--project", "demo"], other)).out).toContain("private fact");
    expect(loadNotes(home).notes.find((n) => n.body.startsWith("private"))?.private).toBe(true);
  });

  it("recalls global procedures from an empty project without pushing them onto cards", async () => {
    const { home, io } = setup();
    const text = "Node TypeScript CLI scaffold setup\n\nRun TypeScript directly with Node type stripping.\nUse node:util parseArgs for the command interface.";
    expect((await run(["note", text, "--kind", "procedure", "--global"], io)).code).toBe(0);
    const note = loadNotes(home).notes[0]!;
    const other = { env: { SECOND_BRAIN_HOME: home }, cwd: tmp("brain-empty-") };
    const recalled = await run(["recall", "node typescript cli scaffold setup"], other);
    expect(recalled.code).toBe(0);
    expect(recalled.out).toContain(note.id + " [procedure]");
    expect((await run(["recall", note.id], other)).out).toContain(text);
    expect((await run(["card"], other)).out).toBe("");
    expect((await run(["card"], io)).out).toBe("");
  });

  it("card is empty on a fresh project, and shows notes and state otherwise", async () => {
    const { io } = setup();
    expect((await run(["card"], io)).out).toBe("");
    await run(["note", "We ship with vite", "--kind", "decision"], io);
    await run(["state", "Goal: login fix. Next: refresh tokens."], io);
    const card = (await run(["card"], io)).out;
    expect(card).toContain("Brain · demo");
    expect(card).toContain("Where we left off");
    expect(card).toContain("We ship with vite");
    expect(card).toContain('brain note "<text>"');
  });

  it("state shows and replaces the working state", async () => {
    const { io } = setup();
    expect((await run(["state"], io)).out).toBe("no working state");
    expect((await run(["state", "Goal: x"], io)).out).toMatch(/^state saved \(\d+ tokens\)$/);
    expect((await run(["state"], io)).out).toContain("Goal: x");
  });

  it("share moves a note to global with a tag", async () => {
    const { home, io } = setup();
    const id = (await run(["note", "Use node 22"], io)).out.replace("saved ", "");
    expect((await run(["share", id], io)).code).toBe(1);
    expect((await run(["share", id, "--tag", "Node"], io)).out).toBe(`shared ${id} with tag node; project demo now has tag node, so it still sees it`);
    expect(loadNotes(home).notes[0]).toMatchObject({ project: "global", tags: ["node"] });
    expect((await run(["recall", "use node"], io)).out).toContain(id);
  });

  it("review lists captured proposals, accept makes a note, reject forgets", async () => {
    const { home, cwd, io } = setup();
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    const rows = [
      { v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd, tool: "bash", command: "npm test", ok: false, error: "Error: Cannot find module x" },
      { v: 1, at: "2026-09-27T10:00:05Z", session: "s", cwd, tool: "bash", command: "npm test extra-target", ok: true },
      { v: 1, at: "2026-09-27T10:01:00Z", session: "s", cwd, tool: "bash", command: "tsc --noEmit", ok: false, error: "error TS2307: cannot resolve" },
      { v: 1, at: "2026-09-27T10:01:05Z", session: "s", cwd, tool: "bash", command: "tsc --version", ok: true },
    ];
    writeFileSync(join(events, "s.jsonl"), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const review = await run(["review"], io);
    const ids = [...review.out.matchAll(/^(p-[0-9a-f]+) \[gotcha\]/gm)].map((m) => m[1] as string);
    expect(ids).toHaveLength(2);
    expect(review.out).toContain("(demo)");
    const accepted = await run(["accept", ids[0] as string], io);
    expect(accepted.out).toMatch(/^accepted p-[0-9a-f]+ → n-[0-9a-f]{10}$/);
    expect((await run(["reject", ids[1] as string], io)).out).toBe(`rejected ${ids[1]}`);
    expect((await run(["review"], io)).out).toBe("nothing to review");
    expect(loadNotes(home).notes).toHaveLength(1);
    expect(loadNotes(home).notes[0]?.tested).toBe(false);
    expect((await run(["accept", "p-nope"], io)).code).toBe(1);
  });

  it("check reports load errors with exit 1; stats summarises telemetry", async () => {
    const { home, io } = setup();
    await run(["note", "fine note"], io);
    expect((await run(["check"], io)).out).toBe("notes: 1 (1 active) · projects: 0");
    writeFileSync(join(home, "notes", "demo", "broken.md"), "no frontmatter");
    const check = await run(["check"], io);
    expect(check.code).toBe(1);
    expect(check.err).toContain("broken.md");
    await run(["recall", "fine"], io);
    const stats = await run(["stats"], io);
    expect(stats.out).toContain("last 7 days");
    expect(stats.out).toMatch(/note: 1 \(\d+ tokens\)/);
    expect(stats.out).toMatch(/recall: 1 \(\d+ tokens\)/);
  });

  it("convert --dry-run on a tiny V3 home writes nothing", async () => {
    const { home, io } = setup();
    const v3 = tmp();
    mkdirSync(join(v3, "records"));
    writeFileSync(join(v3, "records", "mem-1.md"), "---\nid: mem-1\ntitle: A fact\ntype: fact\nscope: project\nproject: demo\nstatus: current\ngrade: TESTED\nrecorded_at: 2026-01-01T00:00:00+00:00\n---\n\nBody.\n");
    const dry = await run(["convert", "--from", v3, "--dry-run"], io);
    expect(dry.out).toBe("written 1, skipped 0, projects 0 (dry run)");
    expect(loadNotes(home).notes).toHaveLength(0);
    expect((await run(["convert", "--from", v3], io)).out).toBe("written 1, skipped 0, projects 0");
    expect(loadNotes(home).notes[0]).toMatchObject({ id: "mem-1", tested: true, body: "A fact\n\nBody." });
    expect((await run(["convert"], io)).code).toBe(1);
  });

  it("sync fails cleanly outside a git repository", async () => {
    const { io } = setup();
    const r = await run(["sync"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain("not a git repository");
  });
});

describe("brain hook claude-code", () => {
  async function hook(stdin: string, env: NodeJS.ProcessEnv): Promise<{ code: number; json: any }> {
    const r = await run(["hook", "claude-code"], { env, cwd: tmp(), stdin: () => stdin });
    return { code: r.code, json: JSON.parse(r.out) };
  }

  it("SessionStart returns the card for the payload's cwd", async () => {
    const home = tmp();
    const cwd = repo("demo");
    createNote(home, { text: "Demo decision", project: "demo", kind: "decision" });
    const r = await hook(JSON.stringify({ hook_event_name: "SessionStart", source: "startup", cwd }), { SECOND_BRAIN_HOME: home });
    expect(r.code).toBe(0);
    expect(r.json.hookSpecificOutput.hookEventName).toBe("SessionStart");
    expect(r.json.hookSpecificOutput.additionalContext).toContain("Demo decision");
    const other = await hook(JSON.stringify({ hook_event_name: "SessionStart", cwd: repo("elsewhere") }), { SECOND_BRAIN_HOME: home });
    expect(other.json).toEqual({});
  });

  it("PostToolUseFailure returns a tested fix and logs the event", async () => {
    const home = tmp();
    const cwd = repo("demo");
    createNote(home, { text: "Clear PYTHONHOME first\n\nThe uv tree is corrupt.", project: "demo", kind: "gotcha", errors: ["SRE module mismatch"], tested: true });
    const payload = { hook_event_name: "PostToolUseFailure", cwd, session_id: "abc", tool_name: "Bash", tool_input: { command: "python x.py" }, error: "AssertionError: SRE module mismatch" };
    const r = await hook(JSON.stringify(payload), { SECOND_BRAIN_HOME: home });
    expect(r.json.hookSpecificOutput.additionalContext).toContain("Clear PYTHONHOME first");
    expect(readFileSync(join(home, "state", "events", "abc.jsonl"), "utf8")).toContain('"command":"python x.py"');
    const interrupted = await hook(JSON.stringify({ ...payload, is_interrupt: true }), { SECOND_BRAIN_HOME: home });
    expect(interrupted.json).toEqual({});
  });

  it("fails open: garbage, other events and no home all give {} and exit 0", async () => {
    const home = tmp();
    for (const stdin of ["not json", "null", "[]", JSON.stringify({ hook_event_name: "Stop" })]) {
      expect(await hook(stdin, { SECOND_BRAIN_HOME: home })).toEqual({ code: 0, json: {} });
    }
    expect(await hook(JSON.stringify({ hook_event_name: "SessionStart" }), { SECOND_BRAIN_HOME: join(home, "missing") })).toEqual({ code: 0, json: {} });
  });
});

describe("bin/brain.mjs", () => {
  it("exits quietly when the stdout consumer closes its pipe", async () => {
    const child = spawn(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "help"], { stdio: ["ignore", "pipe", "pipe"] });
    let error = "";
    child.stderr.on("data", (chunk: Buffer) => { error += chunk.toString(); });
    child.stdout.destroy();
    const code = await new Promise<number | null>((resolve, reject) => {
      child.on("error", reject);
      child.on("close", resolve);
    });
    expect({ code, error }).toEqual({ code: 0, error: "" });
  });

  it("runs under node from the package", () => {
    const r = spawnSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "help"], { encoding: "utf8" });
    expect(r.status).toBe(0);
    expect(r.stdout).toContain("brain recall");
  });
});

describe("brain move", () => {
  it("re-homes a note to another project or to global", async () => {
    const home = mkdtempSync(join(tmpdir(), "brain-move-"));
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home };
    const id = (await run(["note", "Telemetry resets per launch"], io)).out.replace("saved ", "");
    expect((await run(["move", id, "--to", "SZ Tool"], io)).out).toBe(`moved ${id} to sz-tool`);
    expect(loadNotes(home).notes[0]).toMatchObject({ id, project: "sz-tool" });
    expect((await run(["move", id], io)).code).toBe(1);
    expect((await run(["move", "n-nope", "--to", "x"], io)).code).toBe(1);
  });
});

describe("brain check reports silent failures", () => {
  it("flags an unreadable projects.json", async () => {
    const home = mkdtempSync(join(tmpdir(), "brain-check-"));
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home };
    expect((await run(["check"], io)).code).toBe(0);
    writeFileSync(join(home, "projects.json"), '{ "projects": { "x": { "aliases": ["y"], } } }');
    const r = await run(["check"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain("projects.json");
  });
});


describe("note privacy", () => {
  it.each(["demo", "global"])("private notes never upgrade a public %s duplicate", async (scope) => {
    const { home, io } = setup();
    const publicNote = createNote(home, { text: "Deployment needs approval", project: scope });
    const before = readFileSync(publicNote.path, "utf8");
    const saved = await run(["note", publicNote.body, "--private", "--evidence", "internal/deploy.ts"], io);
    expect(saved.code).toBe(0);
    expect(saved.out).toMatch(/^saved /);
    const privateNote = loadNotes(home).notes.find((n) => n.private);
    expect(privateNote?.project).toBe("demo");
    expect(privateNote?.evidence).toEqual(["internal/deploy.ts"]);
    expect(readFileSync(publicNote.path, "utf8")).toBe(before);
    const again = await run(["note", publicNote.body, "--private", "--evidence", "internal/check.ts"], io);
    expect(again.out).toBe('updated ' + privateNote?.id);
    expect(loadNotes(home).notes).toHaveLength(2);
    expect(readFileSync(publicNote.path, "utf8")).toBe(before);
  });

  it("scrubs tags and evidence on creation and duplicate upgrade", async () => {
    const { home, io } = setup();
    const secret = "ghp_" + "syntheticCredential123";
    const saved = await run(["note", "Check deployment", "--tag", secret, "--evidence", "https://example.test/?token=" + secret], io);
    expect(saved.code).toBe(0);
    const created = loadNotes(home).notes[0]!;
    expect(created.tags).toEqual(["***"]);
    expect(created.evidence).toEqual(["https://example.test/?token=***"]);
    expect(readFileSync(created.path, "utf8")).not.toContain(secret);
    const upgraded = await run(["note", "Check deployment", "--tag", "password=" + secret, "--evidence", "password=" + secret], io);
    expect(upgraded.code).toBe(0);
    const updated = loadNotes(home).notes[0]!;
    expect(updated.tags).toContain("password=***");
    expect(updated.evidence).toContain("password=***");
    expect(readFileSync(updated.path, "utf8")).not.toContain(secret);
  });
});


describe("brain stats measurements", () => {
  it("reports parent/sub cards, recall hit rate and the five most frequent unmatched errors", () => {
    const { home, cwd } = setup();
    const base = { project: "demo", tokens: 10, ms: 1 };
    logUse(home, { ...base, kind: "card" });
    logUse(home, { ...base, kind: "card", sub: true });
    logUse(home, { ...base, kind: "recall", hits: 1 });
    logUse(home, { ...base, kind: "recall", hits: 0 });
    logUse(home, { ...base, kind: "recall" });
    createNote(home, { text: "Known fix", project: "demo", tested: true, errors: ["known failure"] });
    appendEvent(home, "stats", cwd, { tool: "bash", ok: false, error: "known failure" });
    const failures = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"];
    for (const [i, failure] of failures.entries()) {
      for (let n = 0; n <= i; n++) appendEvent(home, "stats", cwd, { tool: "bash", ok: false, error: failure + " failure" });
    }
    const child = spawnSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "stats", "--home", home], {
      cwd, encoding: "utf8", env: { ...process.env, SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" },
    });
    const result = { code: child.status, out: child.stdout };
    expect(result.code).toBe(0);
    expect(result.out).toContain("cards: 1 main · 1 sub");
    expect(result.out).toContain("recall calls: 3 · hit rate: 50% (1/2 measured)");
    expect(result.out).toContain("Unmatched errors:");
    expect(result.out).toContain("6 × foxtrot failure");
    expect(result.out).toContain("2 × bravo failure");
    expect(result.out).not.toMatch(/alpha failure|known failure/);
    expect(result.out.indexOf("foxtrot failure")).toBeLessThan(result.out.indexOf("bravo failure"));
  });
});

describe("host-independent memory", () => {
  it("fix returns only tested visible active repairs within budget, or silence", async () => {
    const { home, io } = setup();
    const note = createNote(home, { project: "demo", text: "Install the correct runtime\n\n" + "Detailed repair. ".repeat(80), tested: true, errors: ["runtime mismatch"] });
    const found = await run(["fix", "Error: runtime mismatch"], io);
    expect(found).toEqual({ code: 0, out: renderFix(note), err: "" });
    expect(estimateTokens(found.out)).toBeLessThanOrEqual(80);
    createNote(home, { project: "demo", text: "Unverified", errors: ["unverified failure"] });
    createNote(home, { project: "other", text: "Foreign repair", tested: true, errors: ["foreign failure"] });
    await run(["retire", note.id], io);
    for (const error of ["runtime mismatch", "unverified failure", "foreign failure", "unknown error"]) {
      expect(await run(["fix", error], io)).toEqual({ code: 0, out: "", err: "" });
    }
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows.map((r) => [r.kind, r.via, r.tokens > 0])).toEqual([["fix", "cli", true], ...Array.from({ length: 4 }, () => ["fix", "cli", false])]);
  });

  it("rejects a changed body without upgrading the original note", async () => {
    const { home, io } = setup();
    const note = createNote(home, { project: "demo", text: "Runtime choice\n\nUse Node because it ships here." });
    const before = readFileSync(note.path, "utf8");
    const result = await run(["note", "Runtime choice\n\nUse Bun instead.", "--tested"], io);
    expect(result.out).toContain("not saved: " + note.id);
    expect(result.out).toContain("different body");
    expect(readFileSync(note.path, "utf8")).toBe(before);
    await run(["note", "Runtime choice\nUse Node because it ships here.", "--tested"], io);
    expect(loadNotes(home).notes[0]?.tested).toBe(true);
  });

  it("attributes CLI calls with session precedence and does not mislabel old rows", async () => {
    const { home, io } = setup();
    await run(["note", "A durable decision"], { ...io, env: { ...io.env, BRAIN_SESSION: "parent", CLAUDE_SESSION_ID: "fallback" } });
    await run(["recall", "durable"], { ...io, env: { ...io.env, CLAUDE_SESSION_ID: "fallback" } });
    logUse(home, { kind: "state", project: "demo", ms: 0, tokens: 1, via: "tool" });
    logUse(home, { kind: "recall", project: "demo", ms: 0, tokens: 1, via: "hook" });
    logUse(home, { kind: "note", project: "demo", ms: 0, tokens: 1, via: "mcp" });
    logUse(home, { kind: "recall", project: "demo", ms: 0, tokens: 1 });
    logUse(home, { kind: "card", project: "demo", ms: 0, tokens: 1, via: "hook" });
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows.slice(0, 2).map((r) => [r.via, r.session])).toEqual([["cli", "parent"], ["cli", "fallback"]]);
    expect((await run(["stats"], io)).out).toContain("tool use by surface: 1 tool · 2 cli · 1 hook · 1 mcp calls");
  });

  it("emits an agent block without needing an installed home", async () => {
    const result = await run(["hook", "agents-md"], { env: {}, cwd: tmp() });
    expect(result.code).toBe(0);
    expect(result.out.split("\n").length).toBeLessThanOrEqual(6);
    expect(result.out.split("\n").filter((line) => line.startsWith("Use ")).length).toBe(4);
  });

  it("Claude success after edits avoids a command-fix proposal and checkpoints without replacing the plan", async () => {
    const { home, cwd, io } = setup();
    const transcript = join(home, "transcript.jsonl");
    writeFileSync(transcript, JSON.stringify({ type: "user", message: { content: "Please repair startup" } }) + "\n" + JSON.stringify({ type: "user", message: { content: [{ type: "tool_result", content: "ignore output" }] } }) + "\n");
    await run(["state", "Goal: ship. Next: verify."], io);
    const planPath = join(home, "work", "demo.md");
    const plan = readFileSync(planPath, "utf8");
    const send = (p: Record<string, unknown>) => run(["hook", "claude-code"], { ...io, stdin: () => JSON.stringify({ cwd, session_id: "main", transcript_path: transcript, ...p }) });
    await send({ hook_event_name: "PostToolUseFailure", tool_name: "Bash", tool_input: { command: "npm test" }, error: "Error: dependency missing" });
    expect(scanEvents(home, [])).toEqual([]);
    for (const tool_name of ["Edit", "Write", "MultiEdit"]) await send({ hook_event_name: "PostToolUse", tool_name, tool_input: { file_path: join(cwd, tool_name + ".ts") } });
    await send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "npm ci && npm test" }, tool_response: { stdout: "passed" } });
    expect(scanEvents(home, [])).toEqual([]);
    await send({ hook_event_name: "PreCompact", trigger: "auto" });
    const auto = readWork(home, "demo")?.auto;
    expect(auto).toContain("Edit.ts");
    expect(auto).toContain("Write.ts");
    expect(auto).toContain("MultiEdit.ts");
    expect(auto).toContain("npm test → Error: dependency missing");
    expect(auto).toContain("Please repair startup");
    expect(readFileSync(planPath, "utf8")).toBe(plan);
    await send({ hook_event_name: "PostToolUse", tool_name: "Edit", tool_input: { file_path: join(cwd, "final.ts") } });
    await send({ hook_event_name: "SessionEnd", agent_type: "custom-main-agent" });
    expect(readWork(home, "demo")?.auto).toContain("final.ts");
  });

  it("subagent hooks never create or overwrite project working state or contaminate parent observations", async () => {
    const { home, cwd, io } = setup();
    const send = (p: Record<string, unknown>) => run(["hook", "claude-code"], { ...io, stdin: () => JSON.stringify({ cwd, session_id: "parent", ...p }) });
    await send({ hook_event_name: "PostToolUse", agent_id: "child", tool_name: "Edit", tool_input: { file_path: join(cwd, "child.ts") } });
    for (const hook_event_name of ["SubagentStart", "SubagentStop", "SessionEnd", "PreCompact"]) {
      expect(await send({ hook_event_name, agent_id: "child", agent_type: "Explore" })).toEqual({ code: 0, out: "{}", err: "" });
    }
    expect(readWork(home, "demo")).toBeNull();
    await send({ hook_event_name: "SessionEnd" });
    expect(readWork(home, "demo")).toBeNull();
    await run(["state", "Goal: parent plan"], io);
    const before = readWork(home, "demo");
    await send({ hook_event_name: "PreCompact", agent_id: "child" });
    expect(readWork(home, "demo")).toEqual(before);
  });
});
it.each(["constructor", "toString"])("rejects inherited command %s with a usage error", async (command) => {
  const home = tmp();
  const result = await run([command], { env: { SECOND_BRAIN_HOME: home }, cwd: home });
  expect(result).toEqual({ code: 1, out: "", err: `brain: unknown command ${command} (brain help)` });
});
