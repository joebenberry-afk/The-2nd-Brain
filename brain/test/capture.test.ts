import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
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

  it("strips .exe on Windows", () => {
    expect(program("cmd.exe /c dir")).toBe("cmd");
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
        command: "python -c 'print(x)'",
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
        command: "python -c 'x=1; print(x)'",
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
    expect(proposals.length).toBeGreaterThan(0);
    expect(proposals[0]?.kind).toBe("gotcha");
    expect(proposals[0]?.tested).toBe(true);
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
        command: "python fix",
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
      text: "python: python fail fails (ERROR: something); python fix works",
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
        command: "python fix",
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

    const rejectedFile = join(home, "state", "rejected.json");
    expect(existsSync(rejectedFile)).toBe(true);
    const rejected = JSON.parse(readFileSync(rejectedFile, "utf8"));
    expect(rejected.texts).toContain("this is a false alarm");
    expect(rejected.signatures).toContain("pattern1");
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
    const note = createNote(home, {
      text: "Fix",
      project: "global",
      kind: "gotcha",
      errors: ["re:[invalid("],
      tested: true,
    });

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
    expect(rendered).toContain("Brain (advisory):");
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

  it("omits body when full text won't fit", () => {
    const home = tmp();
    const note = createNote(home, {
      text: "A".repeat(200) + "\n\n" + "B".repeat(200),
      project: "global",
      kind: "gotcha",
      tested: true,
    });

    const rendered = renderFix(note);
    expect(rendered).toContain("Brain (advisory):");
    expect(rendered).toContain(`[${note.id}]`);
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

  it("renders a fix from the headline and the next sentence, never the headline twice", () => {
    const note = {
      id: "n-1", kind: "gotcha" as const, project: "p", private: false, at: "2026-01-01T00:00:00Z", source: "user",
      tags: [], errors: ["x"], evidence: [], tested: true, path: "",
      body: "Clear PYTHONHOME before python\n\nThe uv tree it points at is corrupt. More detail here.",
    };
    expect(renderFix(note)).toBe("Brain (advisory): Clear PYTHONHOME before python: The uv tree it points at is corrupt [n-1]");
  });
});
