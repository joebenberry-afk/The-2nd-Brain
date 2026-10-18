import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";
import { describe, expect, it, vi } from "vitest";
import { LEAN_LINE } from "../src/card.ts";
import { main, type Io } from "../src/cli.ts";
import { createNote, loadNotes, saveNote } from "../src/notes.ts";
import { appendEvent, findFix, renderFix, scanEvents, unmatchedErrors } from "../src/capture.ts";
import { estimateTokens } from "../src/util.ts";
import { readWork } from "../src/work.ts";
import { fixFires, logUse } from "../src/telemetry.ts";

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
  const code = await main(argv, { stdin: () => "", ...io, env: { CLAUDE_CONFIG_DIR: process.env.CLAUDE_CONFIG_DIR, ...io.env }, out: (s) => out.push(s), err: (s) => err.push(s) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

function setup(): { home: string; cwd: string; io: Partial<Io> } {
  const home = tmp();
  const cwd = repo("demo");
  return { home, cwd, io: { env: { SECOND_BRAIN_HOME: home }, cwd } };
}

describe("brain cli", () => {
  it("awaits the judge, logs dropped answers, and leaves the card lexical", async () => {
    const { home, io } = setup();
    const note = createNote(home, { project: "demo", text: "Obsidian deployment guidance" });
    const fetch = vi.fn(async () => new Response(JSON.stringify({ answers: { rel_0: { noul: 0.1 } } })));
    vi.stubGlobal("fetch", fetch);
    try {
      const judgedIo = { ...io, env: { ...io.env, TYPESAFE_API_KEY: "synthetic-cli" } };
      expect((await run(["card"], judgedIo)).out).toContain(note.id);
      expect(fetch).not.toHaveBeenCalled();
      expect(await run(["recall", "obsidian deployment"], judgedIo)).toMatchObject({ code: 0, out: "no match; note it once you learn it", err: "" });
      const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
      expect(rows.find(row => row.kind === "recall")).toMatchObject({ query: "obsidian deployment", ids: [], hits: 0, judged: true, dropped: 1, via: "cli" });
    } finally { vi.unstubAllGlobals(); }
  });

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
    const fired = new Date(Date.now() - 30 * 60_000);
    // A minute later: the model had read the fix (an outcome in its fire's second is no evidence).
    const scored = new Date(fired.getTime() + 60_000);
    for (let i = 0; i < 6; i++) {
      for (let n = 0; n <= i; n++) logUse(home, { ...base, kind: "fix", id: `fix-${i}` }, fired);
      logUse(home, { ...base, kind: "fixout", id: `fix-${i}`, outcome: "helped" }, scored);
    }
    const measured = await run(["stats"], io);
    expect(measured.out.split("\n").filter(line => line.startsWith("fix outcomes:"))).toEqual([5, 4, 3, 2, 1].map(i => `fix outcomes: fix-${i} helped 1/missed 0`));
  });

  it("Claude hooks score retries across processes and clear pending fixes at session boundaries", () => {
    const { home, cwd } = setup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const hook = (hook_event_name: string, session_id: string, tool_input: object = {}, tool_name = "Bash", extra = {}) => {
      const child = spawnSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "hook", "claude-code", "--home", home], { cwd, encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, BRAIN_PROJECT: "demo" }, input: JSON.stringify({ hook_event_name, session_id, cwd, tool_name, tool_input, error: "runtime mismatch", ...extra }) });
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
    expect(outcomes.map(row => [row.session, row.id, row.outcome, row.via])).toEqual([["help", note.id, "helped", "hook"], ["miss", note.id, "missed", "hook"], ["miss", note.id, "helped", "hook"]]);
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

  it("note --replaces saves a correction and validates the target before writing", async () => {
    const { home, io } = setup();
    const old = createNote(home, { project: "demo", text: "Migration order\nApply backwards." });
    const missing = await run(["note", "Missing correction", "--replaces", "n-missing"], io);
    expect(missing.code).not.toBe(0);
    expect(missing.err).toContain("no note n-missing");
    expect(loadNotes(home).notes).toHaveLength(1);
    const saved = await run(["note", "Migration order\nApply forwards.", "--replaces", old.id], io);
    expect(saved.code).toBe(0);
    const notes = loadNotes(home).notes;
    const replacement = notes.find(note => note.id !== old.id)!;
    expect(saved.out).toBe(`saved ${replacement.id} (retired ${old.id})`);
    expect(replacement.replaces).toBe(old.id);
    expect(notes.find(note => note.id === old.id)).toMatchObject({ retired: expect.any(String), replacedBy: replacement.id });
    const retired = await run(["note", "Another correction", "--replaces", old.id], io);
    expect(retired.code).not.toBe(0);
    expect(retired.err).toContain(`${old.id} is already retired`);
    expect(loadNotes(home).notes).toHaveLength(2);
  });

  it("accepts ids as pasted: brackets, trailing punctuation, upper case", async () => {
    const { home, io } = setup();
    const id = createNote(home, { project: "demo", text: "Pasted id one" }).id;
    const id2 = createNote(home, { project: "demo", text: "Pasted id two" }).id;
    const shown = await run(["show", `[${id.toUpperCase()}].`], io);
    expect(shown.code).toBe(0);
    expect(shown.out).toContain("Pasted id one");
    expect((await run(["tested", id.toUpperCase()], io)).out).toBe(`tested ${id}`);
    expect((await run(["retire", `(${id2})`, "--by", id.toUpperCase()], io)).out).toBe(`retired ${id2} (replaced by ${id})`);
    const notes = loadNotes(home).notes;
    expect(notes.find((n) => n.id === id2)?.replacedBy).toBe(id);
    expect(notes.find((n) => n.id === id)?.replaces).toBe(id2);
    expect((await run(["retire", id, "--by", `[${id}]`], io)).err).toContain("cannot replace itself");
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

  it("tells the writer when a fix's remedy falls past the fix line", async () => {
    const { io } = setup();
    const long = `The nightly export fails because ${"the staging bucket rotates its credentials every hour and ".repeat(6)}the fix is to run export-refresh first`;
    const cut = await run(["note", long, "--error", "export: credentials expired", "--tested"], io);
    expect(cut.out).toMatch(/^saved (n-[0-9a-f]{10}); its fix line is cut at ".*…": fixes show 80 tokens, so lead the first line with the remedy in a note that replaces \1$/);
    expect((await run(["fix", "export: credentials expired"], io)).out).not.toContain("export-refresh");
    // A remedy-first headline fits, and a note without an error pattern is not a fix at all.
    expect((await run(["note", "Run export-refresh before the nightly export", "--error", "export: token expired", "--tested"], io)).out).toMatch(/^saved n-[0-9a-f]{10}$/);
    const weekly = long.replace("nightly", "weekly");
    const id = (await run(["note", weekly], io)).out.replace("saved ", "");
    expect(id).toMatch(/^n-[0-9a-f]{10}$/);
    // Adding an error pattern to that note makes it a fix: the update says so too.
    expect((await run(["note", weekly, "--error", "export: weekly credentials expired"], io)).out).toMatch(new RegExp(`^updated ${id}; its fix line is cut at ".*…": .* in a note that replaces ${id}$`));
  });

  it("never marks a global fix tested from an agent's note", async () => {
    const { home, io } = setup();
    const args = ["note", "Clear the widget cache after a schema bump", "--global", "--kind", "gotcha", "--error", "schema version mismatch in widget cache", "--tested"];
    const saved = await run(args, io);
    expect(saved.out).toMatch(/^saved n-[0-9a-f]{10} \(untested: the owner confirms a global fix with `brain tested <id>`\)$/);
    expect(loadNotes(home).notes[0]).toMatchObject({ project: "global", tested: false });
    expect((await run(args, io)).out).toMatch(/^already noted n-[0-9a-f]{10} \(untested: /);
    expect(loadNotes(home).notes[0]?.tested).toBe(false);
    expect((await run(["fix", "Error: schema version mismatch in widget cache (v3 != v4)"], { ...io, cwd: repo("other") })).out).toBe("");
    // Once the owner confirmed it, noting it again (here or from a project) does not call it untested.
    const id = saved.out.split(" ")[1] as string;
    await run(["tested", id], io);
    expect((await run(args, io)).out).toBe(`already noted ${id}`);
    expect((await run(["note", "Clear the widget cache after a schema bump", "--kind", "gotcha", "--tested"], io)).out).toBe(`already noted ${id}`);
  });

  it("review lists captured proposals, accept makes a note, reject forgets", async () => {
    const { home, cwd, io } = setup();
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    // Relative to now: the unmatched-error window (14 days) must still hold the failures later.
    const at = (seconds: number) => new Date(Date.now() - 3_600_000 + seconds * 1000).toISOString();
    const rows = [
      { v: 1, at: at(0), session: "s", cwd, tool: "bash", command: "npm test", ok: false, error: "Error: Cannot find module x" },
      { v: 1, at: at(5), session: "s", cwd, tool: "bash", command: "npm test extra-target", ok: true },
      { v: 1, at: at(60), session: "s", cwd, tool: "bash", command: "tsc --noEmit", ok: false, error: "error TS2307: cannot resolve" },
      { v: 1, at: at(65), session: "s", cwd, tool: "bash", command: "tsc --version", ok: true },
    ];
    writeFileSync(join(events, "s.jsonl"), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const review = await run(["review"], io);
    const ids = [...review.out.matchAll(/^(p-[0-9a-f]+) \[gotcha\]/gm)].map((m) => m[1] as string);
    expect(ids).toHaveLength(2);
    expect(review.out).toContain("(demo)");
    const accepted = await run(["accept", ids[0] as string], io);
    expect(accepted.out).toMatch(/^accepted p-[0-9a-f]+ → n-[0-9a-f]{10}$/);
    expect((await run(["reject", ids[1] as string], io)).out).toBe(`rejected ${ids[1]}`);
    const remaining = await run(["review"], io);
    expect(remaining.out).toContain("Unmatched errors");
    expect(remaining.out).not.toMatch(/^p-[0-9a-f]+/m);
    for (const error of unmatchedErrors(home, loadNotes(home).notes)) await run(["dismiss", error.signature], io);
    expect((await run(["review"], io)).out).toBe("nothing to review");
    expect(loadNotes(home).notes).toHaveLength(1);
    expect(loadNotes(home).notes[0]?.tested).toBe(false);
    expect((await run(["accept", "p-nope"], io)).code).toBe(1);
  });

  it("review turns a tested captured fix into a note by itself, without a proposal to accept", async () => {
    const { home, cwd, io } = setup();
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    const at = (seconds: number) => new Date(Date.now() - 3_600_000 + seconds * 1000).toISOString();
    const rows = [
      { v: 1, at: at(0), session: "s", cwd, tool: "bash", command: "npm test", ok: false, error: "Error: Cannot find module x" },
      { v: 1, at: at(5), session: "s", cwd, tool: "bash", command: "npm test --run", ok: true },
    ];
    writeFileSync(join(events, "s.jsonl"), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const review = await run(["review"], io);
    expect(review.out).not.toMatch(/^p-[0-9a-f]+/m);
    expect(loadNotes(home).notes).toHaveLength(1);
    expect(loadNotes(home).notes[0]).toMatchObject({ project: "demo", source: "capture", tested: true, testedBy: "capture" });
    expect(existsSync(join(home, "state", "inbox")) ? readdirSync(join(home, "state", "inbox")) : []).toEqual([]);
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

  it("drops the card's when-to-act footer when CLAUDE.md already loads the agents block", async () => {
    const home = tmp();
    const cwd = repo("demo");
    const claude = tmp();
    createNote(home, { text: "Demo decision", project: "demo", kind: "decision" });
    const card = async (event: string) => (await hook(JSON.stringify({ hook_event_name: event, source: "startup", cwd, agent_id: "a1" }), { SECOND_BRAIN_HOME: home, CLAUDE_CONFIG_DIR: claude })).json.hookSpecificOutput.additionalContext as string;
    expect(await card("SessionStart")).toContain("brain recall");
    expect(await card("SubagentStart")).toContain("brain recall");
    const block = (await run(["hook", "agents-md"])).out;
    // Through the project's CLAUDE.md importing AGENTS.md, as in this repository.
    writeFileSync(join(cwd, "AGENTS.md"), block);
    expect(await card("SessionStart")).toContain("brain recall");
    writeFileSync(join(cwd, "CLAUDE.md"), "# Demo\n\n@AGENTS.md\n");
    expect(await card("SessionStart")).not.toContain("brain recall");
    rmSync(join(cwd, "CLAUDE.md"));
    // Through the global CLAUDE.md, as the installer writes it.
    writeFileSync(join(claude, "CLAUDE.md"), `# Mine\n\n${block}\n`);
    for (const event of ["SessionStart", "SubagentStart"]) {
      const text = await card(event);
      expect(text).toContain("Demo decision");
      expect(text).not.toContain("brain recall");
    }
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
    // An OMP-only fix can only match echoed text in Claude Code.
    const omp = createNote(home, { text: "OMP hashline edits need a fresh tag", project: "global", kind: "gotcha", errors: ["is not from this session."], tested: true });
    saveNote(home, { ...omp, host: "omp" });
    const echoed = await hook(JSON.stringify({ ...payload, error: "Exit code 1\nValueError: token abc123 is not from this session." }), { SECOND_BRAIN_HOME: home });
    expect(echoed.json).toEqual({});
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
    const child = spawn(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "help"], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TYPESAFE_API_KEY: undefined } });
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
    const r = spawnSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "help"], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } });
    expect(r.status).toBe(0);
    expect(r.stdout).toContain("brain recall");
  });

  it("keeps node:http off the hook path, where its ESM import would cost every hook about 16 ms (undici)", () => {
    const cli = pathToFileURL(join(import.meta.dirname, "..", "src", "cli.ts")).href;
    const r = spawnSync(process.execPath, ["--no-warnings", "--input-type=module", "-e", `await import(${JSON.stringify(cli)}); process.stdout.write(String(process.moduleLoadList.includes("NativeModule http")))`], { encoding: "utf8" });
    expect(r.stdout).toBe("false");
  });

  it("keeps a detached proxy running and stops a piped one when its host closes stdin", async () => {
    const args = [join(import.meta.dirname, "..", "bin", "brain.mjs"), "proxy", "--port", "0", "--home", tmp()];
    const env = { ...process.env, TYPESAFE_API_KEY: undefined };
    const detached = spawn(process.execPath, args, { stdio: ["ignore", "pipe", "ignore"], env });
    const detachedExit = once(detached, "exit");
    try {
      expect(String((await once(detached.stdout, "data"))[0])).toContain("brain proxy listening on http://127.0.0.1:");
      // NUL ends at once, so a proxy that stopped at end of input would be gone long before this.
      expect(await Promise.race([detachedExit.then(() => "exited"), sleep(500, "running")])).toBe("running");
    } finally {
      detached.kill();
    }
    const piped = spawn(process.execPath, args, { stdio: ["pipe", "pipe", "ignore"], env });
    const pipedExit = once(piped, "exit");
    await once(piped.stdout, "data");
    piped.stdin.end();
    expect((await pipedExit)[0]).toBe(0);
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

describe("text that starts with a dash", () => {
  // PowerShell drops a bare `--` before brain.ps1 sees it; such text must still arrive as text.
  it("is text when it has a space before any '=', and still works after `--`", async () => {
    const { home, io } = setup();
    expect((await run(["note", "--force deletes the cache"], io)).code).toBe(0);
    expect(loadNotes(home).notes[0]?.body.startsWith("--force deletes the cache")).toBe(true);
    expect(await run(["fix", "-bash: foo: command not found"], io)).toMatchObject({ code: 0, err: "" });
    expect((await run(["note", "Bash missing", "--error", "-bash: x: command not found", "--tested"], io)).code).toBe(0);
    expect(loadNotes(home).notes.find((n) => n.body === "Bash missing")).toMatchObject({ errors: ["-bash: x: command not found"], tested: true });
    expect((await run(["note", "--", "--dry-run first"], io)).code).toBe(0);
    expect(loadNotes(home).notes.some((n) => n.body === "--dry-run first")).toBe(true);
    expect((await run(["note", "x", "--nope"], io)).code).toBe(1);
  });

  it.skipIf(process.platform !== "win32")("maps an MSYS drive path given to --home or --from", async () => {
    const home = tmp();
    const msys = (p: string) => p.replace(/\\/g, "/").replace(/^([A-Za-z]):/, (_, d: string) => "/" + d.toLowerCase());
    expect(await run(["--home", msys(home), "check"], { env: {}, cwd: home })).toMatchObject({ code: 0, err: "" });
    const v3 = tmp();
    mkdirSync(join(v3, "records"));
    expect(await run(["--home", home, "convert", "--from", msys(v3), "--dry-run"], { env: {}, cwd: home })).toMatchObject({ code: 0, err: "" });
  });
});

describe("brain check reports silent failures", () => {
  it("flags notes filed under an id that is now an alias", async () => {
    const home = mkdtempSync(join(tmpdir(), "brain-check-"));
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { owner: { aliases: ["old"] } } }));
    const note = createNote(home, { project: "old", text: "Filed before the rename" });
    const io = { env: { SECOND_BRAIN_HOME: home }, cwd: home };
    const r = await run(["check"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain("alias of owner");
    // Once the notes moved, the emptied folder left on disk hides nothing.
    expect((await run(["move", note.id, "--to", "owner"], io)).code).toBe(0);
    mkdirSync(join(home, "notes", "old", "private"), { recursive: true });
    expect(await run(["check"], io)).toMatchObject({ code: 0, err: "" });
    createNote(home, { project: "old", text: "Private, filed under the alias", private: true });
    expect((await run(["check"], io)).err).toContain("alias of owner");
  });

  it("project docs list --project finds the docs of a declared folder from a subfolder", async () => {
    const home = tmp();
    const dir = tmp();
    mkdirSync(join(dir, "docs"));
    mkdirSync(join(dir, "sub"));
    writeFileSync(join(dir, "docs", "X.md"), "# X\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { p: { paths: [dir], docs: ["docs/X.md"] } } }));
    expect(await run(["project", "docs", "list", "--project", "p"], { env: { SECOND_BRAIN_HOME: home }, cwd: join(dir, "sub") })).toMatchObject({ code: 0, out: "docs/X.md" });
  });

  it("flags an unreadable projects.json", async () => {
    const home = mkdtempSync(join(tmpdir(), "brain-check-"));
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home };
    expect((await run(["check"], io)).code).toBe(0);
    writeFileSync(join(home, "projects.json"), '{ "projects": { "x": { "aliases": ["y"], } } }');
    const r = await run(["check"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain("projects.json");
  });

  it("reads host case-insensitively and flags a host that fires nowhere", async () => {
    const home = mkdtempSync(join(tmpdir(), "brain-check-"));
    const file = (id: string, host: string) => {
      mkdirSync(join(home, "notes", "global"), { recursive: true });
      writeFileSync(join(home, "notes", "global", `${id}.md`), `---\nid: ${id}\nkind: gotcha\nerrors:\n  - "hashline tag is stale"\ntested: true\nhost: ${host}\n---\n\nRe-read the file first\n`);
    };
    file("n-upper", "OMP");
    const notes = loadNotes(home).notes;
    expect(findFix(notes, "error: hashline tag is stale", null, undefined, "omp")?.id).toBe("n-upper");
    expect(findFix(notes, "error: hashline tag is stale", null, undefined, "claude-code")).toBeNull();
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home };
    expect((await run(["check"], io)).code).toBe(0);
    file("n-list", "[omp, claude-code]");
    const r = await run(["check"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain(join(home, "notes", "global", "n-list.md"));
    expect(r.err).not.toContain("n-upper");
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
      cwd, encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" },
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
    await run(["note", "A durable decision"], { ...io, env: { ...io.env, BRAIN_SESSION: "parent", CLAUDE_CODE_SESSION_ID: "claude", CLAUDE_SESSION_ID: "fallback" } });
    await run(["recall", "durable"], { ...io, env: { ...io.env, CLAUDE_CODE_SESSION_ID: "claude", CLAUDE_SESSION_ID: "fallback" } });
    await run(["recall", "durable"], { ...io, env: { ...io.env, CLAUDE_SESSION_ID: "fallback" } });
    logUse(home, { kind: "state", project: "demo", ms: 0, tokens: 1, via: "tool" });
    logUse(home, { kind: "note", project: "demo", ms: 0, tokens: 1, via: "mcp" });
    logUse(home, { kind: "recall", project: "demo", ms: 0, tokens: 1 });
    logUse(home, { kind: "card", project: "demo", ms: 0, tokens: 1, via: "hook" });
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows.slice(0, 3).map((r) => [r.via, r.session])).toEqual([["cli", "parent"], ["cli", "claude"], ["cli", "fallback"]]);
    expect((await run(["stats"], io)).out).toContain("tool use by surface: 1 tool · 3 cli · 1 mcp calls");
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

describe("claude-code hook lifecycle", () => {
  const hookSetup = () => {
    const { home, cwd, io } = setup();
    const send = async (p: Record<string, unknown>) => {
      const r = await run(["hook", "claude-code"], { ...io, stdin: () => JSON.stringify({ cwd, session_id: "s", ...p }) });
      return { ...r, json: JSON.parse(r.out) };
    };
    const telemetry = () => readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    return { home, cwd, io, send, telemetry };
  };
  const failure = (command: string, error: string, extra = {}) => ({ hook_event_name: "PostToolUseFailure", tool_name: "Bash", tool_input: { command }, error, ...extra });

  it("resolves an unregistered folder after `cd sub` the same in the hook as in the agent's CLI calls", async () => {
    const { io } = hookSetup();
    const root = join(tmp(), "plain");
    const sub = join(root, "sub");
    mkdirSync(sub, { recursive: true });
    // The Bash tool's env has no CLAUDE_PROJECT_DIR; only the hook's does.
    expect(await run(["note", "Pin the numpy wheel", "--kind", "gotcha", "--error", "numpy.core.multiarray failed to import", "--tested"], { ...io, cwd: sub })).toMatchObject({ code: 0 });
    const r = await run(["hook", "claude-code"], { ...io, env: { ...io.env, CLAUDE_PROJECT_DIR: root }, stdin: () => JSON.stringify({ cwd: sub, session_id: "s", ...failure("python x.py", "ImportError: numpy.core.multiarray failed to import") }) });
    expect(JSON.parse(r.out).hookSpecificOutput.additionalContext).toContain("Pin the numpy wheel");
  });

  it("saves edited files regardless of command failures and host noise", async () => {
    const { home, cwd, send } = hookSetup();
    await send(failure("npm test", "Error: dependency missing"));
    await send({ hook_event_name: "PostToolUse", tool_name: "Edit", tool_input: { file_path: join(cwd, "a.ts") } });
    await send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "npm test" } });
    await send(failure("sleep 60", "Error: operation aborted"));
    await send({ hook_event_name: "PreCompact" });
    const auto = readWork(home, "demo")?.auto;
    expect(auto).toContain("a.ts");
  });

  it("takes the human ask, not harness rows, and falls back to the last-prompt row", async () => {
    const { home, send } = hookSetup();
    const transcript = join(home, "t.jsonl");
    const rows = [
      { type: "user", origin: { kind: "human" }, message: { content: "<system-reminder>\nnoise\n</system-reminder>\nPlease fix the upload retry" } },
      { type: "user", origin: { kind: "task-notification" }, message: { content: "<task-notification>\n<task-id>a1</task-id>\n</task-notification>" } },
      { type: "user", message: { content: "<command-message>ponytail:ponytail</command-message>\n<command-name>/ponytail:ponytail</command-name>\n<command-args>ultra</command-args>" } },
      { type: "user", message: { content: "<local-command-stdout>Set model to x</local-command-stdout>" } },
      { type: "user", message: { content: [{ type: "text", text: "[Request interrupted by user for tool use]" }] } },
      { type: "user", origin: { kind: "human" }, message: { content: "<create-pr-command> ## Overview" } },
      { type: "user", isCompactSummary: true, message: { content: "This session is being continued from a previous conversation" } },
    ];
    writeFileSync(transcript, rows.map((r) => JSON.stringify(r) + "\n").join(""));
    await send({ hook_event_name: "SessionEnd", transcript_path: transcript });
    expect(readWork(home, "demo")?.auto).toContain("- last ask: Please fix the upload retry");

    // The prompt row is beyond the 256 KiB tail; Claude Code's own last-prompt rows are not.
    const long = join(home, "long.jsonl");
    const output = { type: "user", message: { content: [{ type: "tool_result", content: "x".repeat(10_000) }] } };
    const tail = [{ type: "last-prompt", lastPrompt: "Ship the CSV export" }, { type: "last-prompt", lastPrompt: "/ponytail:ponytail ultra" }, { type: "last-prompt", leafUuid: "u" }];
    writeFileSync(long, [rows[0], ...Array.from({ length: 30 }, () => output), ...tail].map((r) => JSON.stringify(r) + "\n").join(""));
    for (const hook_event_name of ["PreCompact", "SessionEnd"]) {
      await send({ hook_event_name, transcript_path: long });
      expect(readWork(home, "demo")?.auto).toContain("- last ask: Ship the CSV export");
    }

    // A prompt that starts with a one-segment path or route is a real ask, not a slash command.
    const route = join(home, "route.jsonl");
    const ask = "/health returns 503 behind the proxy; find why";
    writeFileSync(route, [rows[0], { type: "user", origin: { kind: "human" }, message: { content: ask } }, { type: "last-prompt", lastPrompt: ask }].map((r) => JSON.stringify(r) + "\n").join(""));
    await send({ hook_event_name: "SessionEnd", transcript_path: route });
    expect(readWork(home, "demo")?.auto).toContain("- last ask: /health returns 503");
    // …also when its row is beyond the tail: only a <command-name> wrapper makes slash text a command.
    const far = "/status page shows 500 after the deploy; find why";
    writeFileSync(route, [rows[0], { type: "user", origin: { kind: "human" }, message: { content: far } }, ...Array.from({ length: 30 }, () => output), { type: "last-prompt", lastPrompt: far }].map((r) => JSON.stringify(r) + "\n").join(""));
    await send({ hook_event_name: "SessionEnd", transcript_path: route });
    expect(readWork(home, "demo")?.auto).toContain("- last ask: /status page shows 500");
    // A typed command's prompt row is beyond the tail too, but its wrapper (or a plugin's ":") is not.
    const bare = { type: "user", message: { content: "<command-name>/review</command-name>\n<command-args>high</command-args>" } };
    for (const [wrapper, typed] of [[bare, "/review high"], [output, "/ponytail:ponytail ultra"]] as const) {
      writeFileSync(route, [rows[0], ...Array.from({ length: 30 }, () => output), wrapper, { type: "last-prompt", lastPrompt: typed }].map((r) => JSON.stringify(r) + "\n").join(""));
      await send({ hook_event_name: "SessionEnd", transcript_path: route });
      expect(readWork(home, "demo")?.auto).toContain("- last ask: /status page shows 500");
    }
  });

  it("does not log a backgrounded launch as a success", async () => {
    const { home, send, telemetry } = hookSetup();
    await send(failure("cargo build --release", "error: linker `link.exe` not found"));
    await send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "vcvars64.bat && cargo build --release", run_in_background: true } });
    expect(scanEvents(home, [])).toEqual([]);
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    await send(failure("npm test", "runtime mismatch"));
    await send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "npm test" }, tool_response: { backgroundTaskId: "b1" } });
    expect(telemetry().filter((row) => row.kind === "fixout")).toEqual([]);
    // The pending fix waits for the next foreground run.
    await send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "npm test" } });
    expect(telemetry().filter((row) => row.kind === "fixout").map((row) => [row.id, row.outcome])).toEqual([[note.id, "helped"]]);
  });

  it("keeps Claude Code's own files off the edited line", async () => {
    const { home, cwd, send } = hookSetup();
    const scratchpad = join(homedir(), "brain-test-scratchpad");
    await send({ hook_event_name: "PostToolUse", tool_name: "Edit", tool_input: { file_path: join(cwd, "src.ts") } });
    for (const file_path of [join(scratchpad, "x.py"), join(homedir(), ".claude", "projects", "p", "memory", "m.md"), join(homedir(), "AppData", "Local", "Temp", "t.py")]) {
      await send({ hook_event_name: "PostToolUse", tool_name: "Write", tool_input: { file_path } });
    }
    await send({ hook_event_name: "PostToolUse", tool_name: "Write", tool_input: { file_path: join(homedir(), "elsewhere", "kept.ts") } });
    await send({ hook_event_name: "SessionEnd", scratchpad_dir: scratchpad });
    expect(readWork(home, "demo")?.auto).toBe(`- edited: src.ts, ${join(homedir(), "elsewhere", "kept.ts").replace(/\\/g, "/")}`);
  });

  it("keeps Claude Code's scratchpad off the edited line when the project root contains it", async () => {
    const { home, cwd, send } = hookSetup();
    const scratchpad = join(cwd, "AppData", "Local", "Temp", "claude", "x", "scratchpad");
    await send({ hook_event_name: "PostToolUse", tool_name: "Write", tool_input: { file_path: join(cwd, "a.ts") } });
    await send({ hook_event_name: "PostToolUse", tool_name: "Write", tool_input: { file_path: join(scratchpad, "x.py") } });
    await send({ hook_event_name: "SessionEnd", scratchpad_dir: scratchpad });
    expect(readWork(home, "demo")?.auto).toBe("- edited: a.ts");
  });

  it("reads a hook payload that starts with a byte order mark", async () => {
    const { home, cwd, io, telemetry } = hookSetup();
    createNote(home, { project: "demo", text: "Demo decision", kind: "decision" });
    const r = await run(["hook", "claude-code"], { ...io, stdin: () => "﻿" + JSON.stringify({ cwd, session_id: "s", hook_event_name: "SessionStart" }) });
    expect(JSON.parse(r.out).hookSpecificOutput.additionalContext).toContain("Demo decision");
    expect(telemetry().filter((row) => row.kind === "error")).toEqual([]);
  });

  it("clears a subagent's pending fixes with its parent session", async () => {
    const { home, send } = hookSetup();
    createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    await send(failure("npm test", "runtime mismatch", { agent_id: "a1" }));
    await send({ hook_event_name: "SessionEnd" });
    expect(readdirSync(join(home, "state", "pending-fixes"))).toEqual([]);
  });

  it("cards startup, clear and compact, nothing on resume or an unknown source", async () => {
    const { home, send, telemetry } = hookSetup();
    createNote(home, { project: "demo", text: "Demo decision", kind: "decision" });
    for (const source of ["startup", "clear"]) expect((await send({ hook_event_name: "SessionStart", source })).json.hookSpecificOutput.additionalContext).toContain("Demo decision");
    await send({ hook_event_name: "SessionEnd" });
    // The compaction summary keeps goal and next, not the notes: the whole card comes back.
    expect((await send({ hook_event_name: "SessionStart", source: "compact" })).json.hookSpecificOutput.additionalContext).toContain("Demo decision");
    for (const source of ["resume", "other"]) expect((await send({ hook_event_name: "SessionStart", source })).json).toEqual({});
    expect(telemetry().filter((row) => row.kind === "card")).toHaveLength(3);
  });

  it("leaves the lean rule after a compaction when the card has nothing to say", async () => {
    const { send } = hookSetup();
    expect((await send({ hook_event_name: "SessionStart", source: "compact" })).json.hookSpecificOutput.additionalContext).toBe(LEAN_LINE);
  });

  it("logs a swallowed hook error to telemetry", async () => {
    const { home, cwd, send, telemetry } = hookSetup();
    await send({ hook_event_name: "PostToolUse", tool_name: "Edit", tool_input: { file_path: join(cwd, "a.ts") } });
    writeFileSync(join(home, "state", "work"), "not a directory");
    expect(await send({ hook_event_name: "PreCompact" })).toMatchObject({ code: 0, json: {} });
    const errors = telemetry().filter((row) => row.kind === "error");
    expect(errors).toHaveLength(1);
    expect(errors[0].error).toMatch(/^claude-code PreCompact: /);
  });

  it("sends the full fix once per context, then a pointer", async () => {
    const { home, send } = hookSetup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const fix = async () => (await send(failure("npm test", "runtime mismatch"))).json.hookSpecificOutput.additionalContext;
    expect(await fix()).toBe(renderFix(note));
    expect(await fix()).toBe(`Brain: same fix as above [${note.id}]`);
    await send({ hook_event_name: "PreCompact" });
    expect(await fix()).toBe(renderFix(note));
  });

  it("counts only Claude Code hook fires on the hook card and on brain card", async () => {
    const { home, io, send } = hookSetup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const hit = (card: string) => card.includes("Often hit lately");
    const card = async () => (await send({ hook_event_name: "SessionStart" })).json.hookSpecificOutput.additionalContext;
    for (const s of ["a", "b", "c"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, id: note.id });
    for (const s of ["d", "e", "f"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, via: "cli", id: note.id });
    expect(hit(await card())).toBe(false);
    expect(hit((await run(["card"], io)).out)).toBe(false);
    for (const s of ["g", "h", "i"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, via: "hook", id: note.id });
    expect(hit(await card())).toBe(true);
    expect(hit((await run(["card"], io)).out)).toBe(true);
  });

  it("logs subagent fixes under their own session, and ties CLI calls to the Claude Code session", async () => {
    const { home, io, send, telemetry } = hookSetup();
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    await send({ hook_event_name: "SessionStart" });
    for (const agent_id of ["a1", "a2"]) expect((await send(failure("npm test", "runtime mismatch", { agent_id }))).json.hookSpecificOutput.additionalContext).toBe(renderFix(note));
    expect(telemetry().filter((row) => row.kind === "fix").map((row) => [row.session, row.sub, row.via])).toEqual([["s:agent:a1", true, "hook"], ["s:agent:a2", true, "hook"]]);
    expect(fixFires(home, true, 7, new Date(), "claude-code").get(note.id)).toBe(2);
    await run(["recall", "runtime"], { ...io, env: { ...io.env, CLAUDE_CODE_SESSION_ID: "s" } });
    expect((await run(["stats"], io)).out).toContain("brain tools used in: 1/1 main sessions · 0/0 sub");
  });
});
it.each(["constructor", "toString"])("rejects inherited command %s with a usage error", async (command) => {
  const home = tmp();
  const result = await run([command], { env: { SECOND_BRAIN_HOME: home }, cwd: home });
  expect(result).toEqual({ code: 1, out: "", err: `brain: unknown command ${command} (brain help)` });
});
