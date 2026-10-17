import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { appendEvent, findFix, listProposals, scanCommits, scanEvents, unmatchedErrors } from "../src/capture.ts";
import { createNote, loadNotes } from "../src/notes.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-capture-recovery-"));

describe("capture recovery and matching", () => {
  it.each([null, 42, "bad", [], { invalid: 4 }])("rebuilds invalid git cursor %j", (cursor) => {
    const home = tmp();
    const repo = tmp();
    expect(spawnSync("git", ["-C", repo, "init", "-q"]).status).toBe(0);
    expect(spawnSync("git", ["-C", repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "Brain-Gotcha: Keep durable evidence"]).status).toBe(0);
    mkdirSync(join(home, "state"), { recursive: true });
    const path = join(home, "state", "git-cursor.json");
    writeFileSync(path, JSON.stringify(cursor));
    expect(scanCommits(home, repo, "global", [])).toHaveLength(1);
    expect(JSON.parse(readFileSync(path, "utf8"))[repo]).toMatch(/^[a-f0-9]{40}$/);
    expect(scanCommits(home, repo, "global", [])).toEqual([]);
  });

  it.each([null, 42, "bad", [], { "s.jsonl": -1 }, { "s.jsonl": 1.5 }, { "s.jsonl": "20" }])("rebuilds invalid cursor %j", (cursor) => {
    const home = tmp();
    appendEvent(home, "s", home, { tool: "bash", command: "python app.py", ok: false, error: "ModuleNotFoundError: No module named 'demo'" });
    appendEvent(home, "s", home, { tool: "bash", command: "PYTHONPATH=. python app.py", ok: true });
    const path = join(home, "state", "capture-cursor.json");
    writeFileSync(path, JSON.stringify(cursor));
    expect(scanEvents(home, [])).toHaveLength(1);
    expect(Object.values(JSON.parse(readFileSync(path, "utf8"))).every((n) => typeof n === "number" && n >= 0)).toBe(true);
    expect(scanEvents(home, loadNotes(home).notes)).toEqual([]);
  });

  it("keeps shell parser repairs in review", () => {
    const home = tmp();
    appendEvent(home, "s", home, { tool: "bash", command: "python app.py", ok: false, error: "error: pi-natives:command: syntax error at line 1 col 1" });
    appendEvent(home, "s", home, { tool: "bash", command: "PYTHONPATH=. python app.py", ok: true });
    expect(scanEvents(home, [])).toHaveLength(1);
    expect(loadNotes(home).notes).toHaveLength(0);
    expect(listProposals(home)).toHaveLength(1);
  });

  it("does not match numeric diagnostic prefixes or unrelated captured operations", () => {
    const home = tmp();
    const note = createNote(home, { text: "Repair\n\npython app.py\n\nPYTHONPATH=. python app.py\n\nError: diagnostic at col 1", project: "global", kind: "gotcha", tested: true, errors: ["diagnostic at col 1"] });
    note.source = "capture";
    expect(findFix([note], "diagnostic at col 190", null)).toBeNull();
    expect(findFix([note], "diagnostic at col 1", null, undefined, undefined, "cargo build")).toBeNull();
    expect(findFix([note], "diagnostic at col 1", null, undefined, undefined, "python app.py")).toBe(note);
  });

  it.each(["E   ModuleNotFoundError: No module named 'arena'", "❯ ModuleNotFoundError: No module named 'arena'"])("recovers captured runner diagnostic %s", (error) => {
    const home = tmp();
    const command = "python -m pytest tests";
    appendEvent(home, "s", home, { tool: "bash", command, ok: false, error });
    appendEvent(home, "s", home, { tool: "bash", command: `PYTHONPATH=. ${command}`, ok: true });
    scanEvents(home, []);
    const notes = loadNotes(home).notes;
    expect(notes).toHaveLength(1);
    const project = { id: notes[0]!.project, tags: [], root: null };
    expect(findFix(notes, error, project, undefined, "omp", command)).toBe(notes[0]);
  });

  it.each([
    `python scripts/${"application_entrypoint_".repeat(6)}.py`,
    "python app.py --api-token sample-credential-123",
  ])("recovers a captured shortened or masked command: %s", (command) => {
    const home = tmp();
    const error = "ModuleNotFoundError: No module named 'arena'";
    appendEvent(home, "s", home, { tool: "bash", command, ok: false, error });
    appendEvent(home, "s", home, { tool: "bash", command: `PYTHONPATH=. ${command}`, ok: true });
    scanEvents(home, []);
    const notes = loadNotes(home).notes;
    expect(notes).toHaveLength(1);
    const project = { id: notes[0]!.project, tags: [], root: null };
    for (const host of ["omp", "claude-code"] as const) {
      expect(findFix(notes, error, project, undefined, host, command)).toBe(notes[0]);
      expect(findFix(notes, error, project, undefined, host, "cargo build")).toBeNull();
    }
  });

  it("matches captured prefixes only at Unicode word boundaries, including later occurrences", () => {
    const home = tmp();
    const pattern = "Error: unresolved symbol 名";
    const note = createNote(home, { text: "Repair missing symbol", project: "global", kind: "gotcha", tested: true, errors: [pattern] });
    note.source = "capture";
    for (const suffix of ["称", "𐐀", "_other", "1"]) {
      expect(findFix([note], `❯ ${pattern}${suffix}`, null)).toBeNull();
    }
    expect(findFix([note], `❯ ${pattern}: details follow`, null)).toBe(note);
    expect(findFix([note], `${pattern}称\n❯ ${pattern}`, null)).toBe(note);
  });

  it("matches the per-error matcher across a batch", () => {
    const home = tmp();
    const notes = [
      createNote(home, { text: "Install demo", project: "global", kind: "gotcha", tested: true, errors: ["ModuleNotFoundError: No module named 'demo'"] }),
      createNote(home, { text: "Unverified repair", project: "global", kind: "gotcha", errors: ["Error: disk quota exceeded"] }),
    ];
    const errors = ["ModuleNotFoundError: No module named 'demo'", "ModuleNotFoundError: No module named 'other'", "Error: disk quota exceeded"];
    for (const error of errors) appendEvent(home, "s", home, { tool: "bash", command: "python app.py", ok: false, error });
    expect(unmatchedErrors(home, notes).reduce((sum, row) => sum + row.count, 0))
      .toBe(errors.filter((error) => !findFix(notes, error, null)).length);
  });

  it("revalidates edited note content on the next unmatched batch", () => {
    const home = tmp();
    const error = "ModuleNotFoundError: No module named 'demo'";
    const note = createNote(home, { text: "Set PYTHONPATH", project: "global", kind: "gotcha", tested: true, errors: [error] });
    appendEvent(home, "s", home, { tool: "bash", command: "python app.py", ok: false, error });
    expect(unmatchedErrors(home, [note])).toEqual([]);
    note.body += " changed";
    expect(unmatchedErrors(home, [note])).toHaveLength(1);
  });
});
