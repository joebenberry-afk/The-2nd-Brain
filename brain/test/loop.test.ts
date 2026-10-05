import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { appendEvent, autoEvidence, dismissError, eventsDir, rejectProposal, sessionEdits, unmatchedErrors, type Proposal } from "../src/capture.ts";
import { main, type Io } from "../src/cli.ts";
import { errorPatternProblem, loadNotes } from "../src/notes.ts";
import secondBrain from "../src/omp.ts";
import { brainTools } from "../src/tools.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-loop-"));

function setup() {
  const home = tmp();
  const cwd = join(tmp(), "demo");
  mkdirSync(join(cwd, ".git"), { recursive: true });
  writeFileSync(join(cwd, ".git", "config"), "[core]\n\tbare = false\n");
  const io: Partial<Io> = { cwd, env: { SECOND_BRAIN_HOME: home, BRAIN_JUDGE: "off", CLAUDE_CONFIG_DIR: process.env.CLAUDE_CONFIG_DIR } };
  return { home, cwd, io };
}

function file(root: string, path: string): string {
  const absolute = join(root, path);
  mkdirSync(join(absolute, ".."), { recursive: true });
  writeFileSync(absolute, "fixture\n");
  return absolute;
}

async function run(argv: string[], io: Partial<Io>) {
  const out: string[] = [], err: string[] = [];
  const code = await main(argv, { stdin: () => "", ...io, out: text => out.push(text), err: text => err.push(text) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

describe("unmatched errors close the learning loop", () => {
  it("returns a literal pattern and the next success of the latest occurrence, then syncs dismissal hashes", () => {
    const { home, cwd } = setup();
    const now = Date.now();
    appendEvent(home, "z-old", cwd, { tool: "Bash", ok: false, error: "/checkout/src/old.ts: error TS2345: invalid argument" }, new Date(now - 4000));
    appendEvent(home, "z-old", cwd, { tool: "Read", ok: true, path: "src/old.ts" }, new Date(now - 3000));
    appendEvent(home, "a-latest", cwd, { tool: "find", ok: false, error: "/checkout/src/new.ts: error TS2345: invalid argument" }, new Date(now - 2000));
    appendEvent(home, "a-latest", cwd, { tool: "Write", ok: true, path: "src/repair.py" }, new Date(now - 1000));
    appendEvent(home, "a-latest", cwd, { tool: "Bash", ok: true, command: "python src/repair.py" });
    const [error] = unmatchedErrors(home, [], { project: "demo" });
    expect(error).toEqual({ signature: "<path>: error TS2345: invalid argument", count: 2, pattern: "error TS2345: invalid argument", tool: "find", then: "Write src/repair.py" });
    expect(errorPatternProblem(error!.pattern!)).toBeNull();

    const proposal: Proposal = { id: "p-0123456789", at: new Date().toISOString(), project: "demo", kind: "gotcha", text: "A different repair", errors: ["different failure"], tested: false, source: "capture", evidence: [] };
    mkdirSync(join(home, "state", "inbox"), { recursive: true });
    writeFileSync(join(home, "state", "inbox", proposal.id + ".json"), JSON.stringify(proposal));
    rejectProposal(home, proposal.id);
    const prior = JSON.parse(readFileSync(join(home, "rejected.json"), "utf8")) as { hashes: string[] };
    dismissError(home, error!.signature);
    expect(unmatchedErrors(home, [])).toEqual([]);
    const rejectedText = readFileSync(join(home, "rejected.json"), "utf8");
    const rejected = JSON.parse(rejectedText) as { hashes: string[] };
    expect(rejected.hashes).toEqual(expect.arrayContaining(prior.hashes));
    expect(rejected.hashes).toHaveLength(prior.hashes.length + 1);
    expect(rejectedText).not.toContain(error!.signature);
  });

  it("never borrows success context from another session and omits unsafe or absent patterns", () => {
    const { home, cwd } = setup();
    appendEvent(home, "failed", cwd, { tool: "find", ok: false, error: "find timed out after 20.0s" });
    appendEvent(home, "other", cwd, { tool: "Bash", ok: true, command: "echo recovered" });
    appendEvent(home, "path-only", cwd, { tool: "Read", ok: false, error: "/checkout/src/missing.ts" });
    const rows = unmatchedErrors(home, []);
    const timed = rows.find(row => row.signature.startsWith("find timed"));
    expect(timed).toMatchObject({ pattern: "find timed out after 20.0s", tool: "find" });
    expect(timed).not.toHaveProperty("then");
    expect(rows.find(row => row.signature === "<path>")).not.toHaveProperty("pattern");
  });

  it("scrubs and bounds the next successful command without showing private file paths", () => {
    const { home, cwd } = setup();
    appendEvent(home, "scrub", cwd, { tool: "Bash", ok: false, error: "Error: credential transport failed" });
    appendEvent(home, "scrub", cwd, { tool: "Bash", ok: true, command: "retry --password=syntheticCredential123 " + "argument ".repeat(40) });
    const row = unmatchedErrors(home, [])[0]!;
    expect(row.then).toContain("Bash retry");
    expect(row.then).not.toContain("syntheticCredential123");
    expect(row.then!.length).toBeLessThanOrEqual(120);
    // Raw legacy logs may contain private paths even though appendEvent now excludes them.
    writeFileSync(join(eventsDir(home), "private.jsonl"), [
      { v: 1, at: new Date().toISOString(), session: "private", cwd, tool: "Bash", ok: false, error: "Error: private recovery required" },
      { v: 1, at: new Date().toISOString(), session: "private", cwd, tool: "Write", ok: true, path: "notes/demo/private/secret.md" },
    ].map(row => JSON.stringify(row) + "\n").join(""));
    expect(unmatchedErrors(home, []).find(row => row.signature === "Error: private recovery required")).not.toHaveProperty("then");
  });

  it("turns a reviewed error into a tested project fix and removes it from review", async () => {
    const { home, cwd, io } = setup();
    const raw = "/checkout/src/config.ts: line 19: unexpected EOF while looking for matching `'' $HOME";
    appendEvent(home, "review", cwd, { tool: "Bash", ok: false, error: raw });
    appendEvent(home, "review", cwd, { tool: "Write", path: "repair.py", ok: true });
    const row = unmatchedErrors(home, [])[0]!;
    const review = await run(["review"], io);
    expect(review.code).toBe(0);
    expect(review.out).toContain(`1 × ${row.signature}`);
    expect(review.out).toContain("  last: Bash · then: Write repair.py");
    const patternArg = JSON.stringify(row.pattern).replace(/[$`]/g, "\\$&");
    expect(review.out).toContain(`--error ${patternArg}`);
    expect(review.out).not.toContain("nothing to review");
    expect((await run(["note", "Write a script file instead of nesting heredoc quotes", "--kind", "gotcha", "--error", row.pattern!, "--tested"], io)).code).toBe(0);
    const note = loadNotes(home).notes[0]!;
    expect(note).toMatchObject({ project: "demo", tested: true, errors: [row.pattern] });
    expect((await run(["fix", raw], io)).out).toContain(note.id);
    expect((await run(["review"], io)).out).toBe("nothing to review");
  });

  it("scopes review, caps it at five errors, and dismiss joins the signature arguments", async () => {
    const { home, cwd, io } = setup();
    const other = join(tmp(), "other");
    mkdirSync(join(other, ".git"), { recursive: true });
    writeFileSync(join(other, ".git", "config"), "[core]\n\tbare = false\n");
    for (let i = 0; i < 6; i++) {
      for (let n = 0; n <= i; n++) appendEvent(home, "ranked", cwd, { tool: "find", ok: false, error: `Error: ranked failure ${i}` });
    }
    appendEvent(home, "foreign", other, { tool: "find", ok: false, error: "Error: foreign project failure" });
    appendEvent(home, "global", "", { tool: "find", ok: false, error: "Error: global failure" });
    const output = (await run(["review"], io)).out;
    expect(output.match(/^\d+ × /gm)).toHaveLength(5);
    expect(output).toContain("6 × Error: ranked failure 5");
    expect(output).not.toContain("foreign project failure");
    // Leave only global and foreign errors to prove the scope isn't masked by the top-five cap.
    for (const row of unmatchedErrors(home, [], { project: "demo" })) dismissError(home, row.signature);
    expect((await run(["review"], io)).out).toContain("Error: global failure");
    expect((await run(["review"], io)).out).not.toContain("foreign project failure");
    expect((await run(["review", "--all"], io)).out).toContain("foreign project failure");
    expect(await run(["dismiss", "Error:", "global", "failure"], io)).toMatchObject({ code: 0, out: "dismissed Error: global failure" });
    expect((await run(["review"], io)).out).toBe("nothing to review");
  });

  it("preserves malformed rejection files instead of losing existing dismissals", () => {
    const { home, cwd } = setup();
    appendEvent(home, "failure", cwd, { tool: "find", ok: false, error: "Error: unclassified failure" });
    writeFileSync(join(home, "rejected.json"), "{broken");
    expect(() => dismissError(home, "Error: unclassified failure")).toThrow("not valid JSON");
    expect(readFileSync(join(home, "rejected.json"), "utf8")).toBe("{broken");
    expect(unmatchedErrors(home, [])).toHaveLength(1);
  });
});

describe("automatic file evidence", () => {
  it("selects existing mentioned paths and word-bounded edited basenames, not missing, outside, private or scratch files", () => {
    const { cwd } = setup();
    for (const path of ["src/config.ts", "docs/design.md", "src/parser.ts", "src/unmentioned.ts", "tmp/scratch.py", "cache/copy.ts", "notes/demo/private/secret.md", ".claude/memory/host.md"]) file(cwd, path);
    file(join(cwd, ".."), "outside.ts");
    const text = "Use `src/config.ts:12` and docs\\design.md; PARSER.TS owns parsing. Ignore missing.ts ../outside.ts tmp/scratch.py cache/copy.ts notes/demo/private/secret.md .claude/memory/host.md.";
    expect(autoEvidence(text, cwd, ["src/parser.ts", "src/unmentioned.ts"])).toEqual(["src/config.ts", "docs/design.md", "src/parser.ts"]);
    expect(autoEvidence("prefixparser.tsSuffix", cwd, ["src/parser.ts"])).toEqual([]);
    expect(autoEvidence("missing.ts ../outside.ts tmp/scratch.py cache/copy.ts notes/demo/private/secret.md .claude/memory/host.md", cwd, ["src/unmentioned.ts"])).toEqual([]);
    expect(autoEvidence("src/config.ts", null, ["src/config.ts"])).toEqual([]);
  });

  it("deduplicates and caps evidence at three files, including backslash paths", () => {
    const { cwd } = setup();
    for (const path of ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"]) file(cwd, path);
    expect(autoEvidence("src/a.ts src\\a.ts src/b.ts src/c.ts src/d.ts", cwd, [])).toEqual(["src/a.ts", "src/b.ts", "src/c.ts"]);
  });

  it("rejects a file that escapes the root through a symlink", () => {
    const { cwd } = setup();
    const outside = tmp();
    file(outside, "escape.ts");
    symlinkSync(outside, join(cwd, "linked"), "junction");
    expect(autoEvidence("linked/escape.ts", cwd, ["linked/escape.ts"])).toEqual([]);
    file(cwd, "tmp/scratch.ts");
    symlinkSync(join(cwd, "tmp"), join(cwd, "aliased"), "junction");
    expect(autoEvidence("aliased/scratch.ts", cwd, ["aliased/scratch.ts"])).toEqual([]);
  });

  it("replays only successful session edits, keeps recent ordering, and excludes host scratchpads", () => {
    const { home, cwd } = setup();
    appendEvent(home, "edits", cwd, { tool: "Write", ok: true, path: "src/one.ts" });
    appendEvent(home, "edits", cwd, { tool: "Read", ok: true, path: "src/read.ts" });
    appendEvent(home, "edits", cwd, { tool: "Edit", ok: false, path: "src/failed.ts", error: "Error: edit refused" });
    appendEvent(home, "edits", cwd, { tool: "MultiEdit", ok: true, path: "src/two.ts" });
    appendEvent(home, "edits", cwd, { tool: "Edit", ok: true, path: "src/one.ts" });
    appendEvent(home, "edits", cwd, { tool: "Write", ok: true, path: join(tmp(), "scratch.py") });
    appendEvent(home, "edits", cwd, { tool: "Write", ok: true, path: "host-scratch/scratch.py" });
    expect(sessionEdits(home, "edits", cwd, [join(cwd, "host-scratch")])).toEqual(["src/two.ts", "src/one.ts"]);
    expect(sessionEdits(home, "absent", cwd)).toEqual([]);
    for (let i = 0; i < 21; i++) appendEvent(home, "cap", cwd, { tool: "Write", ok: true, path: `src/${i}.ts` });
    expect(sessionEdits(home, "cap", cwd)).toEqual(Array.from({ length: 20 }, (_, i) => `src/${i + 1}.ts`));
  });

  it("saves evidence from CLI session basenames and flags later missing files in recall", async () => {
    const { home, cwd, io } = setup();
    const path = file(cwd, "src/config.ts");
    appendEvent(home, "note-session", cwd, { tool: "Edit", ok: true, path: "src/config.ts" });
    const sessionIo = { ...io, env: { ...io.env, CLAUDE_CODE_SESSION_ID: "note-session" } };
    expect((await run(["note", "Bootstrap cache decision: src/config.ts defines the root"], sessionIo)).code).toBe(0);
    expect((await run(["note", "Configuration basename lesson: CONFIG.TS defines the root"], sessionIo)).code).toBe(0);
    expect(loadNotes(home).notes.every(note => note.evidence.includes("src/config.ts"))).toBe(true);
    expect((await run(["recall", "bootstrap cache decision"], io)).out).not.toContain("(stale evidence)");
    rmSync(path);
    const clock = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 10_001);
    try {
      const recalled = await run(["recall", "bootstrap cache decision"], io);
      expect(recalled.code).toBe(0);
      expect(recalled.out).toContain("(stale evidence)");
    } finally { clock.mockRestore(); }
  });

  it("honors explicit CLI evidence and never adds auto-evidence on existing-headline upgrades", async () => {
    const { home, cwd, io } = setup();
    file(cwd, "src/config.ts");
    expect((await run(["note", "Explicit evidence: src/config.ts", "--evidence", "commit:abc1234"], io)).code).toBe(0);
    expect(loadNotes(home).notes[0]!.evidence).toEqual(["commit:abc1234"]);
    const text = "Future evidence: src/later.ts";
    await run(["note", text], io);
    file(cwd, "src/later.ts");
    await run(["note", text, "--tested"], io);
    expect(loadNotes(home).notes.find(note => note.body === text)?.evidence).toEqual([]);
  });

  it("attaches brain_note evidence from in-memory edits or the session log without changing upgrades", async () => {
    const { home, cwd, io } = setup();
    file(cwd, "src/config.ts");
    file(cwd, "src/parser.ts");
    appendEvent(home, "mcp", cwd, { tool: "Edit", ok: true, path: "src/parser.ts" });
    const noteTool = brainTools.find(tool => tool.name === "brain_note")!;
    const context = { home, cwd, env: io.env!, sub: false, session: "mcp" };
    await noteTool.run({ text: "Parser session lesson: PARSER.TS guards the input" }, context);
    await noteTool.run({ text: "Configuration session lesson: CONFIG.TS chooses the root" }, { ...context, edited: ["src/config.ts"] });
    const notes = loadNotes(home).notes;
    expect(notes.find(note => note.body.startsWith("Parser session"))?.evidence).toEqual(["src/parser.ts"]);
    expect(notes.find(note => note.body.startsWith("Configuration session"))?.evidence).toEqual(["src/config.ts"]);
    const text = "Later tool evidence: src/later.ts";
    await noteTool.run({ text }, context);
    file(cwd, "src/later.ts");
    await noteTool.run({ text, tested: true }, context);
    expect(loadNotes(home).notes.find(note => note.body === text)?.evidence).toEqual([]);
  });

  it("carries OMP hashline edits into note evidence even when the event log has no path", async () => {
    const { home, cwd, io } = setup();
    file(cwd, "src/config.ts");
    const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
    const tools: unknown[] = [];
    secondBrain({ on: (event, handler) => void handlers.set(event, handler), registerTool: tool => void tools.push(tool) }, io.env!);
    const ctx = { cwd, sessionManager: { getSessionId: () => "omp-evidence" } };
    handlers.get("tool_result")!({ toolName: "edit", input: { input: "[src/config.ts#1234]\nPUT 1:\n+changed" }, isError: false, content: [{ type: "text", text: "edited" }] }, ctx);
    // Our in-process fake host receives the registered Brain tool; execute is opaque to HostLike.
    const noteTool = tools.find(tool => !!tool && typeof tool === "object" && "name" in tool && tool.name === "brain_note") as { execute: (...args: unknown[]) => Promise<{ content: { text: string }[] }> };
    expect((await noteTool.execute("note", { text: "Hashline session lesson: CONFIG.TS defines the root" }, ctx)).content[0]!.text).toMatch(/^saved /);
    expect(loadNotes(home).notes[0]!.evidence).toEqual(["src/config.ts"]);
  });
});
