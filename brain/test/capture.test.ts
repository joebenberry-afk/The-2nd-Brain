import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import * as capture from "../src/capture.ts";
import {
  appendEvent,
  acceptProposal,
  errorSignature,
  eventsDir,
  findFix,
  listProposals,
  pendingCount,
  program,
  rejectProposal,
  renderFix,
  safeSession,
  scanCommits,
  scanEvents,
  scrub,
  toolEventFrom,
  type Proposal,
  type ToolEvent,
} from "../src/capture.ts";
import {
  createNote,
  formatNote,
  loadNotes,
} from "../src/notes.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-capture-"));

describe("capture.scrub", () => {
  it("replaces GitHub tokens", () => {
    const { text, scrubbed } = scrub("ghp_abc123def456");
    expect(scrubbed).toBe(true);
    expect(text).toBe("***");
  });

  it("replaces OpenAI sk- tokens", () => {
    const { text, scrubbed } = scrub("sk-1234567890abcdefghijk");
    expect(scrubbed).toBe(true);
    expect(text).toBe("***");
  });

  it("replaces password=value patterns (key kept)", () => {
    const { text, scrubbed } = scrub("password=mysecret123");
    expect(scrubbed).toBe(true);
    expect(text).toContain("password");
    expect(text).toContain("***");
    expect(text).not.toContain("mysecret");
  });

  it("replaces long hex sequences", () => {
    const { text, scrubbed } = scrub("abc123" + "a".repeat(40));
    expect(scrubbed).toBe(true);
    expect(text.includes("***")).toBe(true);
  });

  it("returns scrubbed=false when no changes", () => {
    const { text, scrubbed } = scrub("normal command output");
    expect(scrubbed).toBe(false);
    expect(text).toBe("normal command output");
  });
});

describe("capture.program", () => {
  it("extracts basename from path", () => {
    expect(program("/usr/bin/python")).toBe("python");
    expect(program("C:\\Windows\\System32\\cmd.exe")).toBe("cmd");
  });

  it("skips VAR=value assignments", () => {
    expect(program("VAR=value python -c 'print(1)'")).toBe("python");
  });

  it("skips sudo, env, time", () => {
    expect(program("sudo python")).toBe("python");
    expect(program("env VAR=val python")).toBe("python");
    expect(program("time python")).toBe("python");
  });

  it("strips .exe on Windows, and looks through cmd /c", () => {
    expect(program("C:\\Windows\\System32\\where.exe git")).toBe("where");
    expect(program("cmd.exe /c dir")).toBe("dir");
  });

  it("returns empty string for empty command", () => {
    expect(program("")).toBe("");
    expect(program("   ")).toBe("");
  });
});

describe("capture.errorSignature", () => {
  it("finds first line with error keywords", () => {
    const error = "some output\nERROR: failed to parse\nmore output";
    expect(errorSignature(error)).toContain("failed to parse");
  });

  it("strips ANSI escapes", () => {
    const error = "\x1b[31mERROR: something\x1b[0m";
    expect(errorSignature(error)).toBe("ERROR: something");
  });

  it("collapses whitespace", () => {
    const error = "ERROR:  too  much   space";
    expect(errorSignature(error)).toBe("ERROR: too much space");
  });

  it("cuts to 120 characters", () => {
    const error = "ERROR: " + "x".repeat(200);
    const sig = errorSignature(error);
    expect(sig.length).toBeLessThanOrEqual(120);
  });

  it("falls back to first non-empty line when no keywords", () => {
    const error = "some output\nanother line\n";
    expect(errorSignature(error)).toBe("some output");
  });

  it("returns empty string for empty error", () => {
    expect(errorSignature("")).toBe("");
    expect(errorSignature("   ")).toBe("");
  });
});

describe("capture.safeSession", () => {
  it("keeps alphanumeric and [._-]", () => {
    expect(safeSession("session_01j2nv33")).toBe("session_01j2nv33");
    expect(safeSession("session-name.v1")).toBe("session-name.v1");
  });

  it("replaces other characters with underscore", () => {
    expect(safeSession("session/with spaces")).toBe("session_with_spaces");
    expect(safeSession("session@host#tag")).toBe("session_host_tag");
  });

  it("keeps long keys short and distinct: sessions sharing a long prefix never share a log", () => {
    const base = "C:\\Users\\me\\.omp\\agent\\sessions\\--C--Users-me-Documents-Some-Long-Project-Name--\\";
    const a = safeSession(base + "2026-09-27T10-00-00-000Z_aaaa.jsonl");
    const b = safeSession(base + "2026-09-27T11-00-00-000Z_bbbb.jsonl");
    expect(a).not.toBe(b);
    expect(a.length).toBeLessThanOrEqual(100);
    expect(a).toMatch(/aaaa\.jsonl-[0-9a-f]{12}$/);
  });

  it("returns unknown for empty or only-non-alphanumeric", () => {
    expect(safeSession("")).toBe("unknown");
    expect(safeSession("---")).toBe("unknown");
    expect(safeSession("...")).toBe("unknown");
  });
});

describe("capture.toolEventFrom", () => {
  it("extracts fields from input defensively", () => {
    const result = toolEventFrom("bash", { command: "ls -la" }, false, []);
    expect(result.tool).toBe("bash");
    expect(result.command).toBe("ls -la");
    expect(result.ok).toBe(true);
  });

  it("tries multiple keys for command", () => {
    expect(toolEventFrom("bash", { cmd: "echo hi" }, false, []).command).toBe(
      "echo hi"
    );
    expect(toolEventFrom("bash", { code: "print(1)" }, false, []).command).toBe(
      "print(1)"
    );
    expect(toolEventFrom("bash", { script: "run.sh" }, false, []).command).toBe(
      "run.sh"
    );
  });

  it("tries multiple keys for path", () => {
    expect(toolEventFrom("edit", { path: "/a" }, false, {}).path).toBe("/a");
    expect(toolEventFrom("edit", { file_path: "/b" }, false, {}).path).toBe(
      "/b"
    );
    expect(toolEventFrom("edit", { filePath: "/c" }, false, {}).path).toBe("/c");
    expect(toolEventFrom("edit", { file: "/d" }, false, {}).path).toBe("/d");
  });

  it("extracts error text from blocks", () => {
    const content = [
      { type: "text", text: "line 1" },
      { type: "text", text: "line 2" },
    ];
    const result = toolEventFrom("bash", {}, true, content);
    expect(result.error).toContain("line 1");
    expect(result.error).toContain("line 2");
  });

  it("handles error text as plain string", () => {
    const result = toolEventFrom("bash", {}, true, "error message");
    expect(result.error).toBe("error message");
  });

  it("handles garbage input gracefully", () => {
    expect(toolEventFrom("", {}, null, undefined).tool).toBe("unknown");
    expect(toolEventFrom(123 as unknown, null, false, null).tool).toBe(
      "unknown"
    );
  });

  it("cuts tool name to 100 characters", () => {
    const long = "a".repeat(150);
    const result = toolEventFrom(long, {}, false, undefined);
    expect(result.tool.length).toBeLessThanOrEqual(100);
  });
});

describe("capture.appendEvent", () => {
  it("writes event as JSON line", () => {
    const home = tmp();
    appendEvent(
      home,
      "session-123",
      "/some/path",
      {
        tool: "bash",
        command: "echo hi",
        ok: true,
      }
    );
    const dir = eventsDir(home);
    const files = readdirSync(dir);
    expect(files.length).toBe(1);
    const content = readFileSync(join(dir, files[0] as string), "utf8");
    const line = JSON.parse(content.trim()) as ToolEvent;
    expect(line.v).toBe(1);
    expect(line.tool).toBe("bash");
    expect(line.ok).toBe(true);
  });

  it("scrubs command and error", () => {
    const home = tmp();
    appendEvent(
      home,
      "session-123",
      "/some/path",
      {
        tool: "bash",
        command: "password=secret123 echo hi",
        error: "failed",
        ok: false,
      }
    );
    const dir = eventsDir(home);
    const files = readdirSync(dir);
    const content = readFileSync(join(dir, files[0] as string), "utf8");
    const line = JSON.parse(content.trim()) as ToolEvent;
    expect(line.command).not.toContain("secret123");
  });

  it("never throws on unwritable home", () => {
    expect(() => {
      appendEvent(
        "/nonexistent/path/that/is/bad",
        "session",
        "/cwd",
        { tool: "bash", ok: true }
      );
    }).not.toThrow();
  });

  it("respects EVENT_CAP_BYTES", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });
    const file = join(dir, "test.jsonl");

    // Write a file at exactly the cap
    const large = "x".repeat(5 * 1024 * 1024);
    writeFileSync(file, large);

    const sizeBeforeAppend = statSync(file).size;

    // Try to append
    appendEvent(home, "test", "/cwd", { tool: "bash", ok: true });

    // File should not have grown
    const sizeAfterAppend = statSync(file).size;
    expect(sizeAfterAppend).toBe(sizeBeforeAppend);
  });
});

describe("capture.scanEvents", () => {
  it("pairs failure with fix within 6 events", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const events: ToolEvent[] = [
      {
        v: 1,
        at: "2026-09-27T10:00:00Z",
        session: "s1",
        cwd: "/work/demo",
        tool: "bash",
        command: "python app.py --invalid",
        ok: false,
        error: "ERROR: NameError",
      },
      {
        v: 1,
        at: "2026-09-27T10:01:00Z",
        session: "s1",
        cwd: "/work/demo",
        tool: "bash",
        command: "ls",
        ok: true,
      },
      {
        v: 1,
        at: "2026-09-27T10:02:00Z",
        session: "s1",
        cwd: "/work/demo",
        tool: "bash",
        command: "python app.py --fixed",
        ok: true,
      },
    ];

    const logFile = join(dir, "session1.jsonl");
    for (const evt of events) {
      writeFileSync(logFile, `${JSON.stringify(evt)}\n`, {
        flag: "a",
      });
    }

    const proposals = scanEvents(home, []);
    expect(proposals).toHaveLength(1);
    expect(proposals[0]?.kind).toBe("gotcha");
    expect(proposals[0]?.tested).toBe(false);
  });

  it("does not pair beyond 6 events", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const events: ToolEvent[] = [
      {
        v: 1,
        at: "2026-09-27T10:00:00Z",
        session: "s1",
        cwd: "/work",
        tool: "bash",
        command: "python fail",
        ok: false,
        error: "ERROR: failed",
      },
      ...Array.from({ length: 6 }, (_) => ({
        v: 1 as const,
        at: "2026-09-27T10:00:00Z",
        session: "s1",
        cwd: "/work",
        tool: "other",
        command: "cmd",
        ok: true as const,
      })),
      {
        v: 1,
        at: "2026-09-27T10:07:00Z",
        session: "s1",
        cwd: "/work",
        tool: "bash",
        command: "python fail --fix",
        ok: true,
      },
    ];

    const logFile = join(dir, "session1.jsonl");
    for (const evt of events) {
      writeFileSync(logFile, `${JSON.stringify(evt)}\n`, {
        flag: "a",
      });
    }

    const proposals = scanEvents(home, []);
    expect(proposals.length).toBe(0);
  });

  it("dedupes against active notes by headline", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    // Create an existing note - use exact headline that will be generated
    const note = createNote(home, {
      text: "python: python fail fails (ERROR: something); python fail --fix works",
      project: "global",
      kind: "gotcha",
      tested: true,
    });

    const events: ToolEvent[] = [
      {
        v: 1,
        at: "2026-09-27T10:00:00Z",
        session: "s1",
        cwd: "/work",
        tool: "bash",
        command: "python fail",
        ok: false,
        error: "ERROR: something",
      },
      {
        v: 1,
        at: "2026-09-27T10:01:00Z",
        session: "s1",
        cwd: "/work",
        tool: "bash",
        command: "python fail --fix",
        ok: true,
      },
    ];

    const logFile = join(dir, "session1.jsonl");
    for (const evt of events) {
      writeFileSync(logFile, `${JSON.stringify(evt)}\n`, {
        flag: "a",
      });
    }

    const proposals = scanEvents(home, [note]);
    expect(proposals.length).toBe(0);
  });

  it("prunes old files only when fully processed", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const event: ToolEvent = {
      v: 1,
      at: "2026-09-27T10:00:00Z",
      session: "s1",
      cwd: "/work",
      tool: "bash",
      command: "echo",
      ok: true,
    };

    const oldFile = join(dir, "old-session.jsonl");
    writeFileSync(oldFile, `${JSON.stringify(event)}\n`);

    // Set file mtime to old date
    const oldDate = new Date("2000-01-01").getTime();
    utimesSync(oldFile, oldDate / 1000, oldDate / 1000);

    // First scan: should prune when fully processed
    const now = new Date("2026-10-20");
    scanEvents(home, [], { now });

    // File should be deleted
    expect(existsSync(oldFile)).toBe(false);
  });

  it("updates cursor after processing", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const event: ToolEvent = {
      v: 1,
      at: "2026-09-27T10:00:00Z",
      session: "s1",
      cwd: "/work",
      tool: "bash",
      command: "echo",
      ok: true,
    };

    const logFile = join(dir, "session1.jsonl");
    writeFileSync(logFile, `${JSON.stringify(event)}\n`);

    scanEvents(home, []);

    const cursor = JSON.parse(readFileSync(join(home, "state", "capture-cursor.json"), "utf8"));
    expect(cursor["session1.jsonl"]).toBeGreaterThan(0);
  });

  it("second scan returns empty when cursor at file end", () => {
    const home = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });

    const event: ToolEvent = {
      v: 1,
      at: "2026-09-27T10:00:00Z",
      session: "s1",
      cwd: "/work",
      tool: "bash",
      command: "echo",
      ok: true,
    };

    const logFile = join(dir, "session1.jsonl");
    writeFileSync(logFile, `${JSON.stringify(event)}\n`);

    scanEvents(home, []);
    const proposals2 = scanEvents(home, []);

    expect(proposals2.length).toBe(0);
  });
});

describe("capture.scanCommits", () => {
  it("reads Brain-Gotcha trailers from git log", () => {
    const home = tmp();
    const repo = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });
    mkdirSync(join(repo, ".git"));

    // Initialize git repo
    spawnSync("git", ["-C", repo, "init"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.email", "test@test.com"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.name", "Test User"], {
      stdio: "ignore",
    });

    // Create a commit with trailer
    writeFileSync(join(repo, "file.txt"), "content");
    spawnSync("git", ["-C", repo, "add", "file.txt"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "commit", "-m", "Test\n\nBrain-Gotcha: found a bug"], {
      stdio: "ignore",
    });

    const proposals = scanCommits(home, repo, "demo", []);
    expect(proposals.length).toBeGreaterThan(0);
    expect(proposals[0]?.kind).toBe("gotcha");
    expect(proposals[0]?.source).toBe("commit");
  });

  it("reads Brain-Decision trailers too", () => {
    const home = tmp();
    const repo = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });
    mkdirSync(join(repo, ".git"));

    spawnSync("git", ["-C", repo, "init"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.email", "test@test.com"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.name", "Test User"], {
      stdio: "ignore",
    });

    writeFileSync(join(repo, "file.txt"), "content");
    spawnSync("git", ["-C", repo, "add", "file.txt"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "commit", "-m", "Test\n\nBrain-Decision: use async"], {
      stdio: "ignore",
    });

    const proposals = scanCommits(home, repo, "demo", []);
    expect(proposals.length).toBeGreaterThan(0);
    expect(proposals[0]?.kind).toBe("decision");
  });

  it("honors cursor on second call", () => {
    const home = tmp();
    const repo = tmp();
    const dir = eventsDir(home);
    mkdirSync(dir, { recursive: true });
    mkdirSync(join(repo, ".git"));

    spawnSync("git", ["-C", repo, "init"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.email", "test@test.com"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "config", "user.name", "Test User"], {
      stdio: "ignore",
    });

    writeFileSync(join(repo, "file.txt"), "content");
    spawnSync("git", ["-C", repo, "add", "file.txt"], {
      stdio: "ignore",
    });
    spawnSync("git", ["-C", repo, "commit", "-m", "First\n\nBrain-Gotcha: bug1"], {
      stdio: "ignore",
    });

    const props1 = scanCommits(home, repo, "demo", []);
    expect(props1.length).toBe(1);

    const props2 = scanCommits(home, repo, "demo", []);
    expect(props2.length).toBe(0);
  });

  it("returns empty when git fails or not a repo", () => {
    const home = tmp();
    const proposals = scanCommits(home, "/nonexistent", "demo", []);
    expect(proposals.length).toBe(0);
  });
});

describe("capture.listProposals", () => {
  it("lists and sorts proposals by at then id", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    const prop1: Proposal = {
      id: "p-2",
      at: "2026-09-27T10:02:00Z",
      project: "demo",
      kind: "gotcha",
      text: "second",
      errors: [],
      tested: true,
      source: "capture",
      evidence: [],
    };

    const prop2: Proposal = {
      id: "p-1",
      at: "2026-09-27T10:01:00Z",
      project: "demo",
      kind: "gotcha",
      text: "first",
      errors: [],
      tested: true,
      source: "capture",
      evidence: [],
    };

    writeFileSync(join(dir, "p-2.json"), JSON.stringify(prop1));
    writeFileSync(join(dir, "p-1.json"), JSON.stringify(prop2));

    const props = listProposals(home);
    expect(props.length).toBe(2);
    expect(props[0]?.id).toBe("p-1");
    expect(props[1]?.id).toBe("p-2");
  });
});

describe("capture.acceptProposal", () => {
  it("creates a note and deletes inbox file", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    const prop: Proposal = {
      id: "p-1",
      at: "2026-09-27T10:00:00Z",
      project: "demo",
      kind: "gotcha",
      text: "Fix the bug",
      errors: ["error pattern"],
      tested: true,
      source: "capture",
      evidence: ["events:file#0-1"],
    };

    writeFileSync(join(dir, "p-1.json"), JSON.stringify(prop));

    const note = acceptProposal(home, "p-1");

    expect(note.project).toBe("demo");
    expect(note.kind).toBe("gotcha");
    expect(note.source).toBe("capture");
    expect(note.errors).toContain("error pattern");
    expect(!existsSync(join(dir, "p-1.json"))).toBe(true);
  });

  it("throws for unknown proposal", () => {
    const home = tmp();
    expect(() => acceptProposal(home, "p-999")).toThrow();
  });
});

describe("capture.rejectProposal", () => {
  it("records headline and errors, deletes inbox file", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    const prop: Proposal = {
      id: "p-1",
      at: "2026-09-27T10:00:00Z",
      project: "demo",
      kind: "gotcha",
      text: "This is a false alarm",
      errors: ["pattern1", "pattern2"],
      tested: true,
      source: "capture",
      evidence: [],
    };

    writeFileSync(join(dir, "p-1.json"), JSON.stringify(prop));

    rejectProposal(home, "p-1");

    const rejectedFile = join(home, "rejected.json"); // synced with the notes
    expect(existsSync(rejectedFile)).toBe(true);
    // Synced: only hashes, never the declined text (it may show a secret)
    const raw = readFileSync(rejectedFile, "utf8");
    expect(JSON.parse(raw).hashes).toHaveLength(3);
    expect(raw).not.toMatch(/false alarm|pattern1/);
  });

  it("throws for unknown proposal", () => {
    const home = tmp();
    expect(() => rejectProposal(home, "p-999")).toThrow();
  });
});

describe("capture.pendingCount", () => {
  it("counts proposals in inbox", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    for (let i = 0; i < 3; i++) {
      const prop: Proposal = {
        id: `p-${i}`,
        at: "2026-09-27T10:00:00Z",
        project: "demo",
        kind: "gotcha",
        text: `Proposal ${i}`,
        errors: [],
        tested: true,
        source: "capture",
        evidence: [],
      };
      writeFileSync(join(dir, `p-${i}.json`), JSON.stringify(prop));
    }

    expect(pendingCount(home)).toBe(3);
  });

  it("filters by project", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    const prop1: Proposal = {
      id: "p-1",
      at: "2026-09-27T10:00:00Z",
      project: "demo",
      kind: "gotcha",
      text: "Demo proposal",
      errors: [],
      tested: true,
      source: "capture",
      evidence: [],
    };

    const prop2: Proposal = {
      id: "p-2",
      at: "2026-09-27T10:00:00Z",
      project: "other",
      kind: "gotcha",
      text: "Other proposal",
      errors: [],
      tested: true,
      source: "capture",
      evidence: [],
    };

    writeFileSync(join(dir, "p-1.json"), JSON.stringify(prop1));
    writeFileSync(join(dir, "p-2.json"), JSON.stringify(prop2));

    expect(pendingCount(home, "demo")).toBe(1);
    expect(pendingCount(home, "other")).toBe(1);
    expect(pendingCount(home)).toBe(2);
  });

  it("includes global proposals when filtering by project", () => {
    const home = tmp();
    const dir = join(home, "state", "inbox");
    mkdirSync(dir, { recursive: true });

    const prop: Proposal = {
      id: "p-1",
      at: "2026-09-27T10:00:00Z",
      project: "global",
      kind: "gotcha",
      text: "Global",
      errors: [],
      tested: true,
      source: "capture",
      evidence: [],
    };

    writeFileSync(join(dir, "p-1.json"), JSON.stringify(prop));

    expect(pendingCount(home, "demo")).toBe(1);
  });
});

describe("capture.findFix", () => {
  it("finds fix by substring match", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "PYTHONHOME breaks python",
      project: "global",
      kind: "gotcha",
      errors: ["PYTHONHOME"],
      tested: true,
    });

    const fix = findFix([note], "error: PYTHONHOME is corrupt", null);
    expect(fix).toBe(note);
  });

  it("finds fix by regex pattern", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "Module not found",
      project: "global",
      kind: "gotcha",
      errors: ["re:No such module: \\w+"],
      tested: true,
    });

    const fix = findFix([note], "No such module: os", null);
    expect(fix).toBe(note);
  });

  it("skips invalid regexes", () => {
    const home = tmp();
    // createNote refuses it; a hand-edited or synced note may still carry one
    const note = { ...createNote(home, { text: "Fix", project: "global", kind: "gotcha", tested: true }), errors: ["re:[invalid("] };

    const fix = findFix([note], "error", null);
    expect(fix).toBeNull();
  });

  it("returns longest match", () => {
    const home = tmp();
    const note1 = createNote(home, {
      text: "Fix 1",
      project: "global",
      kind: "gotcha",
      errors: ["error"],
      tested: true,
    });

    const note2 = createNote(home, {
      text: "Fix 2",
      project: "global",
      kind: "gotcha",
      errors: ["error: cannot open file"],
      tested: true,
    });

    const fix = findFix([note1, note2], "error: cannot open file /tmp/x", null);
    expect(fix?.id).toBe(note2.id);
  });

  it("returns null for empty error", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "Fix",
      project: "global",
      kind: "gotcha",
      errors: ["error"],
      tested: true,
    });

    expect(findFix([note], "", null)).toBeNull();
    expect(findFix([note], "   ", null)).toBeNull();
  });

  it("ignores untested notes", () => {
    const home = tmp();
    const untested = createNote(home, {
      text: "Untested",
      project: "global",
      kind: "gotcha",
      errors: ["error"],
      tested: false,
    });

    const tested = createNote(home, {
      text: "Tested",
      project: "global",
      kind: "gotcha",
      errors: ["error"],
      tested: true,
    });

    const fix = findFix([untested, tested], "error", null);
    expect(fix?.id).toBe(tested.id);
  });

  it("ignores retired notes", () => {
    const home = tmp();

    // Create a retired note
    const created = createNote(home, {
      text: "Will be retired",
      project: "global",
      kind: "gotcha",
      errors: ["error"],
      tested: true,
    });

    const retiredNote = { ...created, retired: "2026-09-27T10:00:00Z" };
    writeFileSync(created.path, formatNote(retiredNote));

    const { notes: reloadedNotes } = loadNotes(home);
    const fix = findFix(reloadedNotes, "error", null);
    expect(fix).toBeNull();
  });
});

describe("capture.renderFix", () => {
  it("renders advisory message with headline and first sentence", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "Fix the bug\n\nThe bug is in module X. Details follow.",
      project: "global",
      kind: "gotcha",
      tested: true,
    });

    const rendered = renderFix(note);
    expect(rendered).toContain("Fix the bug");
    expect(rendered).toContain("The bug is in module X");
    expect(rendered).toContain(`[${note.id}]`);
  });

  it("fits within FIX_BUDGET tokens", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "Fix\n\n" + "x".repeat(1000),
      project: "global",
      kind: "gotcha",
      tested: true,
    });

    const rendered = renderFix(note);
    const tokens = Math.ceil(rendered.length / 4);
    expect(tokens).toBeLessThanOrEqual(80);
  });

  it("joins a headline that already ends a sentence without doubling punctuation", () => {
    const note = createNote(tmp(), { text: "Use anchored edits.\n\nCopy the read tag first. More later.", project: "global", kind: "gotcha", tested: true });
    expect(renderFix(note)).toBe(`Brain: Use anchored edits. Copy the read tag first [${note.id}]`);
  });

});

describe("review round trip (regressions)", () => {
  it("persists scanned proposals so review can list and accept them", () => {
    const home = mkdtempSync(join(tmpdir(), "brain-rt-"));
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    const rows = [
      { v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "bash", command: "python app.py", ok: false, error: "SRE module mismatch" },
      { v: 1, at: "2026-09-27T10:00:05Z", session: "s", cwd: "", tool: "bash", command: "PYTHONHOME= python app.py", ok: true },
    ];
    writeFileSync(join(events, "s.jsonl"), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const scanned = scanEvents(home, []);
    expect(scanned).toHaveLength(1);
    expect(scanned[0]?.project).toBe("global");
    const listed = listProposals(home);
    expect(listed.map((p) => p.id)).toEqual(scanned.map((p) => p.id));
    expect(scanEvents(home, [])).toEqual([]);
    const note = acceptProposal(home, listed[0]?.id ?? "");
    expect(note.tested).toBe(true);
    expect(note.errors).toEqual(["SRE module mismatch"]);
    expect(listProposals(home)).toEqual([]);
  });

});


describe("capture batch five regressions", () => {
  it.each([
    ["npx vitest run a.test.ts", "npx vitest run b.test.ts"],
    ["npx eslint src test && npx tsc --noEmit", "npx vitest run eval.test.ts"],
    ["node -e 'A'", "node -e 'B'"],
    ["node -p 'A'", "node -p 'B'"],
    ["python -c 'A'", "python -c 'B'"],
    ["node --eval=A", "node --eval=B"],
    ["node -e'A'", "node -e'B'"],
    ["python -cA", "python -cB"],
    ["bash -c 'A'", "bash -c 'B'"],
    ["python - <<'PY'\nprint('A')\nPY", "python - <<'PY'\nprint('B')\nPY"],
    ["node brain/bin/brain.mjs card", "node /absolute/brain/bin/brain.mjs card"],
  ])("drops unrelated command successes: %s → %s", (failed, fixed) => {
    const home = tmp();
    log(home, row({ command: failed, ok: false, error: "Error: original command failed" }) + row({ command: fixed }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it.each([
    ["npm test", "npm ci && npm test", true],
    ["git push", "git push --set-upstream origin main", false],
    ["npm test", "npm test -- --run", true],
    ["git status --invalid", "git status --short", false],
    ["npx vitest run a.test.ts", "npm ci; npx vitest run a.test.ts b.test.ts", false],
    ["node -e 'console.log(1)'", "node --no-warnings -e 'console.log(1)'", false],
    ["python - <<'PY'\nprint('A')\nPY", "python -u - <<'PY'\nprint('A')\nPY", false],
  ])("keeps positional-prefix repairs: %s → %s", (failed, fixed, tested) => {
    const home = tmp();
    log(home, row({ command: failed, ok: false, error: "Error: original command failed" }) + row({ command: fixed }));
    expect(scanEvents(home, []).map((p) => p.tested)).toEqual([tested]);
  });

  it.each(["grep", "rg", "ls", "cat", "find", "head", "tail", "wc", "echo", "which", "where", "type", "pwd", "stat", "file", "tree", "dir", "Get-ChildItem", "Select-String"])("never proposes exploration failures from %s", (program) => {
    const home = tmp();
    log(home, row({ command: `cd A && ${program} missing`, ok: false, error: "Error: not found" }) + row({ command: `cd B; ${program} found` }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it.each(["npx vitest run", "bunx vitest run", "npm exec vitest run", "npm run test --", "pnpm vitest run", "yarn vitest run", "python -m pytest", "uv run pytest", "bun run test"])("requires the launched target to be retried: %s", (launcher) => {
    const home = tmp();
    log(home, row({ command: `${launcher} test/cli.test.ts`, ok: false, error: "Error: test failure" }) + row({ command: `${launcher} test/kits.test.ts` }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it.each([
    ["cd A && npm   test", "cd B; npm ci && npm test"],
    ["npx vitest run test/cli.test.ts", "npm ci; npx vitest run test/cli.test.ts --reporter=verbose"],
    ['node check.js "two words"', "node check.js 'two words' --verbose"],
  ])("recognizes the complete retry of %s", (failed, fixed) => {
    const home = tmp();
    log(home, row({ command: failed, ok: false, error: "Error: repair required" }) + row({ command: fixed }));
    expect(scanEvents(home, []).map((p) => p.tested)).toEqual([true]);
  });

  it("does not treat a quoted shell separator as an executed retry", () => {
    const home = tmp();
    log(home, row({ command: "npm test", ok: false, error: "Error: tests failed" }) + row({ command: 'npm exec echo "preparation; npm test; done"' }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("selects diagnostics over source and aggregates volatile locations", () => {
    const home = tmp();
    const diagnostics = [
      "import { errorSignature, appendEvent } from './capture.ts';\ntest/first.test.ts(94,40): error TS2345: invalid argument at 0xabcdef12",
      "const error = new Error('failure');\ntest/second.test.ts(12,8): error TS2345: invalid argument at 0x12345678",
      "/tmp/third.test.ts:3:9: error TS2345: invalid argument at 0xabababab",
      "C:\\work\\fourth.test.ts(8,2): error TS2345: invalid argument at 0xcdcdcdcd",
    ];
    log(home, diagnostics.map((error) => row({ ok: false, error })).join(""));
    expect(capture.unmatchedErrors(home, [])).toEqual([{ signature: "<path>: error TS2345: invalid argument at <hex>", count: 4 }]);
    expect(errorSignature("import { failure } from 'x';\nConnection refused by server")).toBe("Connection refused by server");
    expect(errorSignature("Error: " + "complete ".repeat(20))).toMatch(/complete$/);
    expect(errorSignature("❯ test/a.test.ts (2 tests | 1 failed)\n→ Cannot read property value")).toBe("→ Cannot read property value");
    expect(errorSignature("file:///C:/work/[eval1]:1\nimport { failure } from 'x';\nWall time: 0.17 seconds")).toBe("");
  });

  it("never reuses a successful retry to claim another failure was fixed", () => {
    const home = tmp();
    log(home, row({ command: "npm run a", ok: false, error: "Error: failure A" }) + row({ command: "npm run b", ok: false, error: "Error: failure B" }) + row({ command: "npm run a --fix" }));
    expect(scanEvents(home, []).map((p) => [p.errors[0], p.tested])).toEqual([["Error: failure A", true]]);
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("does not trust a retry whose failure is hidden by an unconditional tail", () => {
    const home = tmp();
    log(home, row({ command: "python bad.py", ok: false, error: "Error: still broken" }) + row({ command: "echo preparing; python bad.py; echo finished" }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("does not trust a retry skipped by a successful OR branch", () => {
    const home = tmp();
    log(home, row({ command: "npm test", ok: false, error: "Error: tests failed" }) + row({ command: "npm --version || npm test" }));
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("does not mistake a failed multiline command fragment for the fix", () => {
    const home = tmp();
    const failed = "python - <<'PY'\n\nprint('repairable')\nPY";
    const fixed = "python -u - <<'PY'\n\nprint('repairable')\nPY";
    log(home, row({ command: failed, ok: false, error: "Error: environment not ready" }) + row({ command: fixed }));
    const proposal = scanEvents(home, [])[0]!;
    const note = acceptProposal(home, proposal.id);
    expect(renderFix(note)).toContain("python -u - <<'PY' print('repairable') PY works");
    expect(renderFix(note)).not.toContain("Brain: print('repairable') PY works");
    const legacy = { ...note, body: "Legacy repair\n\npython - <<'PY'\n\nraise RuntimeError('bad')\nPY\n\npython repaired.py\n\nError: bad input" };
    expect(renderFix(legacy)).not.toContain("raise RuntimeError('bad') PY works");
  });

  const row = (fields: Partial<ToolEvent> = {}) => JSON.stringify({ v: 1, at: new Date().toISOString(), session: "s", cwd: "", tool: "bash", ok: true, ...fields }) + "\n";
  const log = (home: string, text: string, name = "s") => {
    mkdirSync(eventsDir(home), { recursive: true });
    const path = join(eventsDir(home), name + ".jsonl");
    writeFileSync(path, text);
    return path;
  };
  const pair = (cwd = "", error = "Error: missing dependency") => row({ cwd, command: "npm test", ok: false, error }) + row({ cwd, command: "npm test -- --run", ok: true });

  it("scrubs URL credentials in path and cwd before their display cuts", () => {
    const home = tmp();
    const secret = "SyntheticPassword".repeat(40);
    appendEvent(home, "s", "https://ci:" + secret + "@example.test/work", { tool: "read", path: "https://ci:" + secret + "@example.test/file", ok: true });
    const event = JSON.parse(readFileSync(join(eventsDir(home), "s.jsonl"), "utf8")) as ToolEvent;
    expect(event.cwd).toBe("https://ci:***@example.test/work");
    expect(event.path).toBe("https://ci:***@example.test/file");
  });

  it("redacts PEM material whose BEGIN is outside the retained tail", () => {
    const home = tmp();
    const material = "SyntheticKeyMaterial42";
    appendEvent(home, "s", "", { tool: "bash", ok: false, error: "header\n-----BEGIN RSA PRIVATE KEY-----\n" + (material + "\n").repeat(90) + "-----END RSA PRIVATE KEY-----\nError: bad key" });
    const event = JSON.parse(readFileSync(join(eventsDir(home), "s.jsonl"), "utf8")) as ToolEvent;
    expect(event.error).not.toContain(material);
    expect(event.error).toContain("Error: bad key");
  });

  it("deduplicates only same-project and applicable global notes and proposals", () => {
    const home = tmp();
    const a = join(home, "a"), b = join(home, "b");
    mkdirSync(a); mkdirSync(b);
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { a: { paths: [a], tags: ["node"] }, b: { paths: [b], tags: ["node"] } } }));
    const note = createNote(home, { text: "Other project fix", project: "a", errors: ["Error: missing dependency"] });
    const tagged = createNote(home, { text: "Unrelated global", project: "global", tags: ["rust"], errors: ["Error: missing dependency"] });
    log(home, pair(b));
    expect(scanEvents(home, [note, tagged]).map((p) => p.project)).toEqual(["b"]);
    log(home, pair(a), "other");
    expect(scanEvents(home, []).map((p) => p.project)).toEqual(["a"]);
    log(home, pair(b), "repeat");
    expect(scanEvents(home, [])).toEqual([]);
    const applicable = createNote(home, { text: "Shared fix", project: "global", tags: ["node"], errors: ["Error: a shared failure"] });
    log(home, pair(b, "Error: a shared failure"), "shared");
    expect(scanEvents(home, [applicable])).toEqual([]);
  });

  it("keeps the full successful command in a bounded captured fix", () => {
    const home = tmp();
    const command = "python -m tools.maintenance.verify_production_database_schema";
    log(home, row({ command: command + " --invalid", ok: false, error: "Error: invalid runtime flag" }) + row({ command }));
    const [proposal] = scanEvents(home, []);
    const note = acceptProposal(home, proposal?.id ?? "");
    const fix = renderFix(note);
    expect(fix).toContain(command);
    expect(Math.ceil(fix.length / 4)).toBeLessThanOrEqual(80);
  });


  it("reserves proposal body space for the actionable command after a long failure", () => {
    const home = tmp();
    const fixed = "python -m " + "package.".repeat(22) + "check";
    const failed = "python --configuration=" + "deep_directory/".repeat(28) + " -m " + "package.".repeat(22) + "check";
    log(home, row({ command: failed, ok: false, error: "ModuleNotFoundError: no module named package" }) + row({ command: fixed }));
    const [proposal] = scanEvents(home, []);
    const note = acceptProposal(home, proposal?.id ?? "");
    expect(renderFix(note)).toContain(fixed);
    expect(Math.ceil(renderFix(note).length / 4)).toBeLessThanOrEqual(80);
  });

  it("captures both interleaved failed-to-fixed pairs", () => {
    const home = tmp();
    log(home, row({ command: "git status --invalid", ok: false, error: "error: invalid git option" }) + row({ command: "npm test", ok: false, error: "error: missing npm dependency" }) + row({ command: "git status" }) + row({ command: "npm test -- --run" }));
    expect(scanEvents(home, []).map((p) => p.errors[0]).sort()).toEqual(["error: invalid git option", "error: missing npm dependency"]);
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("skips wrong event field types and continues other logs", () => {
    const home = tmp();
    log(home, row({ command: 42 as unknown as string, ok: false, error: "error: bad row" }), "a");
    log(home, row({ cwd: {} as string, command: "npm test", ok: false, error: "error: bad cwd" }) + row({ error: [] as unknown as string, ok: false }) + "null\n" + pair(), "b");
    expect(scanEvents(home, []).map((p) => p.errors)).toEqual([["Error: missing dependency"]]);
  });

  it("omits unusable generated patterns so short-error proposals can be accepted", () => {
    const home = tmp();
    log(home, pair("", "OOM"));
    const [proposal] = scanEvents(home, []);
    expect(proposal?.errors).toEqual([]);
    expect(acceptProposal(home, proposal?.id ?? "").body).toContain("OOM");
  });

  it("reads only the unprocessed suffix when a large log has a cursor", () => {
    const home = tmp();
    const old = row({ command: "echo old" }).repeat(4000);
    const fresh = pair();
    log(home, old + fresh);
    writeFileSync(join(home, "state", "capture-cursor.json"), JSON.stringify({ "s.jsonl": Buffer.byteLength(old) }));
    const whole = vi.spyOn(fs, "readFileSync");
    const reads = vi.spyOn(fs, "readSync");
    syncBuiltinESMExports();
    try {
      expect(scanEvents(home, []).map((p) => p.errors)).toEqual([["Error: missing dependency"]]);
      expect(whole.mock.calls.filter(([path]) => String(path).endsWith("s.jsonl"))).toEqual([]);
      expect(reads.mock.results.reduce((sum, result) => sum + (typeof result.value === "number" ? result.value : 0), 0)).toBe(Buffer.byteLength(fresh));
    } finally {
      whole.mockRestore(); reads.mockRestore();
      syncBuiltinESMExports();
    }
  });

  it("requires normalized cwd equality and preserves the failed target", () => {
    const home = tmp();
    log(home, row({ cwd: "C:/work/a", command: "npm test", ok: false, error: "Error: wrong cwd" }) + row({ cwd: "C:/work/b", command: "npm test -- --run" }), "different");
    log(home, row({ command: "npm test", ok: false, error: "Error: tests failed" }) + row({ command: "npm --version" }), "weak");
    log(home, row({ cwd: "C:\\work\\demo\\", command: "npm test", ok: false, error: "Error: useful test failure" }) + row({ cwd: "c:/WORK/demo", command: "npm test -- --run" }), "strong");
    expect(scanEvents(home, []).map((p) => [p.errors[0], p.tested])).toEqual([["Error: useful test failure", true]]);
  });

  it("marks an explicit successful retry after preparation as tested", () => {
    const home = tmp();
    log(home, row({ command: "npm   test", ok: false, error: "Error: preparation required" }) + row({ command: "npm ci && npm test -- --run" }));
    expect(scanEvents(home, []).map((p) => [p.errors[0], p.tested])).toEqual([["Error: preparation required", true]]);
  });


  it("never proposes commands or errors touching private note paths", () => {
    const home = tmp();
    log(home, row({ command: "cat notes/demo/private/secret.md", ok: false, error: "Error: confidential prose" }) + row({ command: "cat notes/demo/private/other.md" }), "command");
    log(home, pair("", "Error: notes\\demo\\private\\secret.md contains confidential prose"), "error");
    log(home, row({ command: "cat notes/demo/public.md", ok: false, error: "Error: missing note" }) + row({ command: "cat notes/demo/private/secret.md" }), "fixed");
    expect(scanEvents(home, [])).toEqual([]);
    appendEvent(home, "raw", "", { tool: "bash", command: "cat notes/demo/private/secret.md", ok: false, error: "Error: confidential prose" });
    expect(existsSync(join(eventsDir(home), "raw.jsonl"))).toBe(false);
  });

  it("masks quoted curl credentials and whitespace credential flags, not ports", () => {
    expect(scrub('curl -u "user:pass words" --port 80').text).not.toContain("words");
    expect(scrub("curl --user 'user:pass words' -p 8080").text).toContain("-p 8080");
    for (const flag of ["password", "token", "api-key", "secret", "client-secret", "auth"]) {
      const text = scrub('tool --' + flag + ' "Synthetic secret words" --port 80').text;
      expect(text).not.toContain("Synthetic");
      expect(text).not.toContain("secret words");
      expect(text).toContain("--port 80");
      expect(scrub("tool --" + flag + " synthetic-value").text).not.toContain("synthetic-value");
    }
  });

  it("reports frequent recent scoped errors without a known tested fix", () => {
    const home = tmp();
    const a = join(home, "a"), b = join(home, "b");
    mkdirSync(a); mkdirSync(b);
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { a: { paths: [a] }, b: { paths: [b] } } }));
    const known = createNote(home, { text: "Known repair", project: "a", tested: true, errors: ["Error: known failure"] });
    log(home, row({ cwd: a, ok: false, error: "Error: known failure" }) + row({ cwd: b, ok: false, error: "Error: known failure" }) + row({ cwd: a, ok: false, error: "Error: frequent failure" }).repeat(3) + row({ cwd: a, ok: false, error: "Error: rare failure" }) + row({ cwd: a, ok: false, error: "Error: old failure", at: "2000-01-01T00:00:00Z" }) + row({ cwd: a, ok: true, error: "Error: not a failure" }));
    expect(capture.unmatchedErrors(home, [known], { days: 7, project: "a" })).toEqual([{ signature: "Error: frequent failure", count: 3 }, { signature: "Error: rare failure", count: 1 }]);
    expect(capture.unmatchedErrors(home, [known], { project: "b" })).toEqual([{ signature: "Error: known failure", count: 1 }]);
  });
});

