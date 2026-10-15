import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  appendEvent,
  captureUserRules,
  dismissError,
  errorSignature,
  eventsDir,
  findFix,
  listProposals,
  scanEvents,
  unmatchedErrors,
  unmatchedSignature,
} from "../src/capture.ts";
import { loadNotes } from "../src/notes.ts";
import type { Project } from "../src/project.ts";

const roots: string[] = [];
const tmp = () => {
  const root = mkdtempSync(join(tmpdir(), "brain-capture-quality-"));
  roots.push(root);
  return root;
};
afterEach(() => { vi.restoreAllMocks(); syncBuiltinESMExports(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

const pair = (home: string, error: string, cwd = home, command = "py app.py") => {
  appendEvent(home, "s", cwd, { tool: "bash", command, ok: false, error });
  appendEvent(home, "s", cwd, { tool: "bash", command: `${command} --no-cache`, ok: true });
};

describe("auto-accepted capture notes need a specific error pattern", () => {
  const module = (name: string) => `ModuleNotFoundError: No module named '${name}' (from C:\\Users\\x\\proj\\app.py)`;

  it("writes a note whose pattern is the whole diagnostic line, so other errors of that class do not match it", () => {
    const home = tmp();
    pair(home, module("alpha_pkg"));
    scanEvents(home, []);
    const { notes } = loadNotes(home);
    expect(notes).toHaveLength(1);
    expect(notes[0]!.errors).toEqual([module("alpha_pkg")]);
    const project = { id: notes[0]!.project, tags: [], root: null };
    expect(findFix(notes, module("alpha_pkg"), project)).not.toBeNull();
    expect(findFix(notes, module("beta_pkg"), project)).toBeNull();
  });

  it("sends a pair whose diagnostic line would be cut to the inbox, not to a note", () => {
    const home = tmp();
    pair(home, module("x".repeat(120)));
    scanEvents(home, []);
    expect(loadNotes(home).notes).toEqual([]);
    expect(listProposals(home)).toHaveLength(1);
  });

  it("sends a pair whose output has no diagnostic line (stdout plus an exit status) to the inbox", () => {
    const home = tmp();
    pair(home, '{"status":"degraded","checked":42}\nCommand exited with code 1');
    scanEvents(home, []);
    expect(loadNotes(home).notes).toEqual([]);
    expect(listProposals(home)[0]!.errors).not.toContain('{"status":"degraded","checked":42}');
  });

  it("signs stdout followed by an exit status by the status, never by the first stdout line", () => {
    expect(errorSignature("usage: tool [options]\nversion 1.2.3\nCommand exited with code 2")).toBe("Command exited with code 2");
    expect(errorSignature("usage: tool\nboom: error here\nCommand exited with code 2")).toBe("boom: error here");
    const home = tmp();
    appendEvent(home, "s", home, { tool: "bash", command: "tool --help", ok: false, error: "v1.2.3 banner line\nCommand exited with code 1" });
    expect(unmatchedErrors(home, [])).toEqual([]);
  });
});

describe("dismissing a printed unmatched signature", () => {
  it("stops capture and auto-accept of the same error", () => {
    const home = tmp();
    const error = "ModuleNotFoundError: No module named 'gamma' (from C:\\Users\\x\\proj\\app.py)";
    appendEvent(home, "s", home, { tool: "bash", command: "py app.py", ok: false, error });
    const [row] = unmatchedErrors(home, []);
    expect(row!.signature).toBe(unmatchedSignature(error));
    expect(row!.signature).toContain("<path>");
    dismissError(home, row!.signature);
    expect(unmatchedErrors(home, [])).toEqual([]);
    appendEvent(home, "s", home, { tool: "bash", command: "py app.py --no-cache", ok: true });
    expect(scanEvents(home, [])).toEqual([]);
    expect(loadNotes(home).notes).toEqual([]);
    expect(listProposals(home)).toEqual([]);
  });
});

describe("overlapping scans", () => {
  it("write one note with a stable id for one failure and its retry", () => {
    const home = tmp();
    pair(home, "Error: cannot find module 'left-pad'");
    scanEvents(home, []);
    const first = loadNotes(home).notes;
    expect(first).toHaveLength(1);
    // A second scan that read its notes and cursor before the first wrote them.
    rmSyncCursor(home);
    scanEvents(home, []);
    const after = loadNotes(home).notes;
    expect(after.map((note) => note.id)).toEqual(first.map((note) => note.id));
  });

  it("never re-creates a note that was retired meanwhile", () => {
    const home = tmp();
    pair(home, "Error: cannot find module 'left-pad'");
    scanEvents(home, []);
    const [note] = loadNotes(home).notes;
    writeFileSync(note!.path, fs.readFileSync(note!.path, "utf8").replace(/^---\n/, "---\nretired: 2026-01-01T00:00:00.000Z\n"));
    rmSyncCursor(home);
    scanEvents(home, []);
    expect(loadNotes(home).notes).toHaveLength(1);
  });
});

function rmSyncCursor(home: string): void {
  rmSync(join(home, "state", "capture-cursor.json"), { force: true });
}

describe("OMP isolated worktrees", () => {
  it("never auto-accept a tested pair into the folder-name project", () => {
    const root = tmp();
    const home = join(root, "brain");
    const cwd = join(root, ".omp", "wt", "abc", "m");
    mkdirSync(home);
    mkdirSync(cwd, { recursive: true });
    pair(home, "Error: cannot find module 'left-pad'", cwd);
    scanEvents(home, []);
    expect(loadNotes(home).notes).toEqual([]);
    expect(listProposals(home)).toHaveLength(1);
  });
});

describe("owner-rule inbox", () => {
  const project: Project = { id: "demo", tags: [], root: null };

  it("drops waiting rule proposals the current rules reject at the next scan, keeping real ones", () => {
    const home = tmp();
    const inbox = join(home, "state", "inbox");
    mkdirSync(inbox, { recursive: true });
    const write = (id: string, text: string, source = "user") => writeFileSync(join(inbox, `${id}.json`), JSON.stringify({
      id, at: "2026-10-01T00:00:00.000Z", project: "demo", kind: "decision", text, errors: [], tested: false, source, evidence: [],
    }));
    write("p-0000000001", "- X never becomes Y.");
    write("p-0000000002", "I remember you saying we never mock the database.");
    write("p-0000000003", "I prefer concise replies.");
    write("p-0000000004", "- X always becomes Z.", "capture");
    scanEvents(home, []);
    expect(listProposals(home).map((p) => p.id)).toEqual(["p-0000000003", "p-0000000004"]);
  });

  it("reads no notes, proposals or rejections for a prompt without a rule cue", () => {
    const home = tmp();
    mkdirSync(join(home, "notes", "demo"), { recursive: true });
    const read = vi.spyOn(fs, "readdirSync");
    syncBuiltinESMExports();
    expect(captureUserRules(home, "Please look at the parser and run the tests.", project)).toEqual([]);
    expect(read).not.toHaveBeenCalled();
    expect(captureUserRules(home, "I prefer concise replies.", project)).toHaveLength(1);
    expect(read).toHaveBeenCalled();
  });
});

describe("unmatchedErrors window", () => {
  it("does not read event logs last written before the window", () => {
    const home = tmp();
    appendEvent(home, "s", home, { tool: "bash", command: "npm test", ok: false, error: "Error: cannot find module 'left-pad'" });
    expect(unmatchedErrors(home, [], { days: 7 })).toHaveLength(1);
    const dir = eventsDir(home);
    const old = new Date(Date.now() - 30 * 86_400_000);
    for (const name of readdirSync(dir)) utimesSync(join(dir, name), old, old);
    expect(existsSync(dir)).toBe(true);
    expect(unmatchedErrors(home, [], { days: 7 })).toEqual([]);
    expect(unmatchedErrors(home, [], { days: 60 })).toHaveLength(1);
  });
});
