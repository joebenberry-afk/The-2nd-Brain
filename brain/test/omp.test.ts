/**
 * Tests for the OMP extension (brain/src/omp.ts).
 * Fake host collecting handlers and tools, with temp directories for Brain home.
 */
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import secondBrain, { CARD_TYPE, type HostLike } from "../src/omp.ts";
import { createNote } from "../src/notes.ts";
import { readWork } from "../src/work.ts";

type Handler = (event: unknown, ctx: unknown) => unknown;

let root = "";
let home = "";

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "omp-"));
  home = join(root, "brain");
  mkdirSync(home, { recursive: true });
});

afterEach(() => {
  // cleanup in real sessions; here we just leave temp dirs
});

function load(
  env: NodeJS.ProcessEnv = { SECOND_BRAIN_HOME: home },
  captureTools = false
): {
  handlers: Map<string, Handler>;
  tools: unknown[];
} {
  const handlers = new Map<string, Handler>();
  const tools: unknown[] = [];

  const pi: HostLike = {
    on: (name, handler) => void handlers.set(name, handler),
    ...(captureTools ? { registerTool: (tool) => void tools.push(tool) } : {}),
  };

  secondBrain(pi, env);
  return { handlers, tools };
}

const ctx = (session: string, cwd = join(root, "work")) => ({
  cwd,
  sessionManager: { getSessionId: () => session },
});

describe("OMP extension", () => {
  it("falls back to its own checkout as the home when SECOND_BRAIN_HOME is unset", () => {
    const { handlers } = load({}, false);
    expect([...handlers.keys()].sort()).toEqual(["before_agent_start", "context", "session_before_branch", "session_before_switch", "session_branch", "session_compact", "session_shutdown", "session_switch", "tool_result"]);
  });

  it("registers handlers even when home is empty (no notes)", () => {
    const { handlers } = load();
    expect(handlers.size).toBeGreaterThan(0);
    expect(handlers.has("before_agent_start")).toBe(true);
    expect(handlers.has("context")).toBe(true);
    expect(handlers.has("session_compact")).toBe(true);
    expect(handlers.has("tool_result")).toBe(true);
    expect(handlers.has("session_shutdown")).toBe(true);
  });

  it("never throws when host field throws", () => {
    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;
    // ctx with throwing sessionManager getter
    const badCtx = {
      get sessionManager() {
        throw new Error("boom");
      },
    };
    expect(() => start({ prompt: "test" }, badCtx)).not.toThrow();
    expect(start({ prompt: "test" }, badCtx)).toBeUndefined();
  });

  it("sends card on first before_agent_start, nothing on later calls", () => {
    // Create a work directory and git repo so project resolves predictably
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    // Create a note in the "work" project (the resolved project)
    mkdirSync(join(home, "notes", "work"), { recursive: true });
    createNote(home, {
      text: "Test note for card",
      project: "work",
      kind: "fact",
    });

    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;
    const c = ctx("s1", workDir);

    // First call: should have card
    const first = start({ prompt: "initial" }, c) as any;
    expect(first).toBeDefined();
    expect(first.message).toBeDefined();
    expect(first.message.customType).toBe(CARD_TYPE);
    expect(first.message.content).toContain("Test note");

    // Second call: no card
    const second = start({ prompt: "again" }, c);
    expect(second).toBeUndefined();
  });

  it("empty home → no card message", () => {
    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;

    const result = start({ prompt: "test" }, ctx("s1"));
    expect(result).toBeUndefined();
  });

  it("captures prompt in ask field", () => {
    // Set up project
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;
    const compact = handlers.get("session_compact")!;

    const session = "s-prompt-test";
    const c = ctx(session, workDir);

    // Trigger before_agent_start with a prompt
    start({ prompt: "  test   with   spaces  " }, c);

    // Compaction writes the auto section
    compact({}, c);

    // Check the work file was written - project resolves to folder name
    const workFile = readWork(home, "work");
    expect(workFile?.auto).toContain("test with spaces");
  });

  it("compaction flow: tool_result + before_compact + compact + context", () => {
    // Set up project
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    // Create a note that will be visible in the work project
    mkdirSync(join(home, "notes", "work"), { recursive: true });
    createNote(home, {
      text: "Resume content here",
      project: "work",
      kind: "fact",
    });

    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const compact = handlers.get("session_compact")!;
    const contextHandler = handlers.get("context")!;
    const start = handlers.get("before_agent_start")!;

    const session = "s-compaction-flow";
    const c = ctx(session, workDir);

    // Step 1: tool result with ok=true and path (edit tracking)
    toolResult(
      {
        toolName: "bash",
        input: { command: "touch file.txt", path: "file.txt" },
        isError: false,
        content: [],
      },
      c
    );

    // Step 3: compact builds resume
    compact({}, c);

    // Step 4: context returns messages with resume card at index 0
    const contextResult = contextHandler(
      { messages: [{ role: "user", content: "hello" }] },
      c
    ) as any;
    expect(contextResult).toBeDefined();
    expect(contextResult.messages).toBeDefined();
    expect(contextResult.messages.length).toBe(2);
    const resumeMsg = contextResult.messages[0];
    expect(resumeMsg.customType).toBe(CARD_TYPE);
    expect(resumeMsg.details.resume).toBe(true);
    expect(resumeMsg.content).toContain("Resume content");

    // Step 5: second context call should have identical timestamp
    const contextResult2 = contextHandler(
      { messages: [{ role: "user", content: "hello again" }] },
      c
    ) as any;
    expect(contextResult2.messages[0].timestamp).toBe(resumeMsg.timestamp);

    // Step 6: before_agent_start after compaction adds nothing
    const afterCompact = start({ prompt: "new turn" }, c);
    expect(afterCompact).toBeUndefined();
  });

  it("does not duplicate resume card if already in messages", () => {
    const { handlers } = load();
    const compact = handlers.get("session_compact")!;
    const contextHandler = handlers.get("context")!;

    createNote(home, {
      text: "Test resume",
      project: "omp",
      kind: "fact",
    });

    const session = "s-dedup";
    const c = ctx(session);

    // Trigger compaction
    compact({}, c);

    // Context with resume card already present
    const resumeCard = {
      role: "custom",
      customType: CARD_TYPE,
      details: { resume: true },
      content: "Already here",
    };
    const result = contextHandler(
      { messages: [resumeCard, { role: "user", content: "hello" }] },
      c
    ) as any;

    // Should return undefined (don't add)
    expect(result).toBeUndefined();
  });

  it("fallback: resume card delivered via before_agent_start if never seen by context", () => {
    // Set up project
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    mkdirSync(join(home, "notes", "work"), { recursive: true });
    createNote(home, {
      text: "Fallback resume",
      project: "work",
      kind: "fact",
    });

    const { handlers } = load();
    const compact = handlers.get("session_compact")!;
    const start = handlers.get("before_agent_start")!;

    const session = "s-fallback";
    const c = ctx(session, workDir);

    // Trigger compaction without calling context
    compact({}, c);

    // Now call before_agent_start: should deliver the card
    const result = start({ prompt: "after compact" }, c) as any;
    expect(result).toBeDefined();
    expect(result.message.customType).toBe(CARD_TYPE);
    expect(result.message.content).toContain("Fallback resume");

    // Resume should be cleared after fallback
    const result2 = start({ prompt: "again" }, c);
    expect(result2).toBeUndefined();
  });

  it("failed tool result with tested fix → appends fix to content", () => {
    // Set up project
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;

    // Create a tested note with an error pattern (global so it's visible)
    mkdirSync(join(home, "notes", "global"), { recursive: true });
    createNote(home, {
      text: "Fix for SRE mismatch",
      project: "global",
      kind: "gotcha",
      errors: ["SRE module mismatch"],
      tested: true,
    });

    const session = "s-fix";
    const c = ctx(session, workDir);

    // Failed tool with matching error
    const result = toolResult(
      {
        toolName: "bash",
        input: { command: "python test.py" },
        isError: true,
        content: [{ type: "text", text: "AssertionError: SRE module mismatch" }],
      },
      c
    ) as any;

    expect(result).toBeDefined();
    expect(result.content).toBeDefined();
    expect(result.content.length).toBe(2);
    expect(result.content[1].text).toContain("Fix for SRE mismatch");
  });

  it("untested note → no fix appended", () => {
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;

    // Create untested note
    createNote(home, {
      text: "Untested fix",
      project: "omp",
      kind: "gotcha",
      errors: ["pattern"],
      tested: false,
    });

    const session = "s-untested";
    const c = ctx(session);

    const result = toolResult(
      {
        toolName: "bash",
        input: { command: "test" },
        isError: true,
        content: [{ type: "text", text: "pattern here" }],
      },
      c
    );

    expect(result).toBeUndefined();
  });

  it("events file written under state/events/", () => {
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;

    const session = "s-events";
    const c = ctx(session);

    toolResult(
      {
        toolName: "bash",
        input: { command: "ls" },
        isError: false,
        content: [],
      },
      c
    );

    const eventsDir = join(home, "state", "events");
    const files = readdirSync(eventsDir);
    expect(files.length).toBeGreaterThan(0);
    expect(files[0]).toMatch(/\.jsonl$/);

    const content = readFileSync(join(eventsDir, files[0]!), "utf8");
    expect(content).toContain('"tool":"bash"');
    expect(content).toContain('"ok":true');
  });

  it("tracks edited paths (last 20 unique)", () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;

    const session = "s-paths";
    const c = ctx(session, workDir);

    // Simulate editing multiple files
    for (let i = 1; i <= 5; i++) {
      toolResult(
        {
          toolName: "write",
          input: { path: `file${i}.ts` },
          isError: false,
          content: [],
        },
        c
      );
    }
    handlers.get("session_compact")!({}, c);

    const workFile = readWork(home, "work");
    expect(workFile?.auto).toContain("file1.ts");
    expect(workFile?.auto).toContain("file5.ts");
  });

  it("tools not registered when BRAIN_TOOLS=off", () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_TOOLS: "off" }, true);
    expect(tools.length).toBe(0);
  });

  it("tools registered with no typebox", () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);
    expect(tools.length).toBe(3);
    const names = tools.map((t: any) => t.name);
    expect(names).toEqual(["brain_recall", "brain_note", "brain_state"]);
  });

  it("brain_recall tool: recall finds a note written by brain_note", () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    // Prepare: write a note first
    const noteTool = tools.find((t: any) => t.name === "brain_note") as any;
    expect(noteTool).toBeDefined();

    // Execute brain_note to create a note
    const noteResult = noteTool.execute(
      "n-id",
      { text: "Important pattern to remember" },
      {},
      {},
      ctx("s-tools")
    ) as any;
    expect(noteResult.content[0].text).toContain("saved");

    // Now execute brain_recall to find it
    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;
    const recallResult = recallTool.execute(
      "r-id",
      { query: "pattern" },
      {},
      {},
      ctx("s-tools")
    ) as any;
    expect(recallResult.content[0].text).toContain("Important pattern");
  });

  it("brain_state tool: writes the work file", () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;
    const result = stateTool.execute(
      "state-id",
      { text: "Goal: finish implementation" },
      {},
      {},
      ctx("s-state", workDir)
    ) as any;

    expect(result.content[0].text).toContain("state saved");

    const workFile = readWork(home, "work");
    expect(workFile?.text).toContain("Goal: finish");
  });

  it("tool errors come back as text, not exceptions", () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;

    // Call without required text
    const result = stateTool.execute("id", {}, {}, {}, ctx("s-error")) as any;
    expect(result.content[0].text).toContain("brain:");
    expect(result.content[0].text).not.toContain("throw");
  });

  it("tools execute with (id, params, signal, onUpdate, ctx) order", () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;

    // Create a note to find - use global so it's visible to all projects
    mkdirSync(join(home, "notes", "global"), { recursive: true });
    createNote(home, {
      text: "Something to recall later",
      project: "global",
      kind: "fact",
    });

    // Call with full signature: (id, params, signal, onUpdate, ctx)
    const result = recallTool.execute(
      "tool-id",
      { query: "recall" },
      {},
      () => {},
      ctx("s-sig", workDir)
    ) as any;

    expect(result.content).toBeDefined();
    expect(result.content[0].text).toContain("Something");
  });

  it("tools execute with (id, params, ctx) order", () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;

    mkdirSync(join(home, "notes", "global"), { recursive: true });
    createNote(home, {
      text: "Another thing to find",
      project: "global",
      kind: "fact",
    });

    // Call with short signature: (id, params, ctx)
    const result = recallTool.execute(
      "tool-id",
      { query: "find" },
      ctx("s-short-sig", workDir)
    ) as any;

    expect(result.content).toBeDefined();
    expect(result.content[0].text).toContain("Another thing");
  });

  it("session_shutdown writes auto section like before_compact", () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const shutdown = handlers.get("session_shutdown")!;

    const session = "s-shutdown";
    const c = ctx(session, workDir);

    // Track a failure
    toolResult(
      {
        toolName: "bash",
        input: { command: "test" },
        isError: true,
        content: [{ type: "text", text: "Error: failed" }],
      },
      c
    );

    // Trigger shutdown
    shutdown({}, c);

    // Check work file was written
    const workFile = readWork(home, "work");
    expect(workFile?.auto).toContain("last failure");
  });

  it("context returns undefined when no event.messages or no resume", () => {
    const { handlers } = load();
    const contextHandler = handlers.get("context")!;

    const c = ctx("s-context-edge");

    // Call with no messages property
    const result1 = contextHandler({ other: "data" }, c);
    expect(result1).toBeUndefined();

    // Call with non-array messages
    const result2 = contextHandler({ messages: "not-an-array" }, c);
    expect(result2).toBeUndefined();
  });
});

describe("tool plumbing", () => {
  it("builds parameters with the host's TypeBox shim, marking optional fields", async () => {
    const { schema } = await import("../src/omp.ts");
    const Type = {
      Object: (f: unknown) => ({ kind: "Object", f }),
      String: (o: unknown) => ({ kind: "String", o }),
      Boolean: (o: unknown) => ({ kind: "Boolean", o }),
      Optional: (s: unknown) => ({ kind: "Optional", s }),
    };
    const props = { q: { type: "string" as const, description: "query" }, all: { type: "boolean" as const, description: "every project", optional: true } };
    expect(schema({ Type }, props)).toEqual({
      kind: "Object",
      f: { q: { kind: "String", o: { description: "query" } }, all: { kind: "Optional", s: { kind: "Boolean", o: { description: "every project" } } } },
    });
    expect(schema(undefined, props)).toEqual({
      type: "object",
      properties: { q: { type: "string", description: "query" }, all: { type: "boolean", description: "every project" } },
      required: ["q"],
      additionalProperties: false,
    });
  });

  it("finds params and ctx whatever the argument order", async () => {
    const { toolArgs } = await import("../src/omp.ts");
    const ctx = { cwd: "/work/x" };
    expect(toolArgs(["id", { text: "a" }, undefined, undefined, ctx], "text")).toMatchObject({ params: { text: "a" }, cwd: "/work/x", ctx });
    expect(toolArgs(["id", { signal: 1 }, { text: "b" }, ctx], "text").params).toEqual({ text: "b" });
    expect(toolArgs([{ text: "c" }], "text").cwd).toBe(process.cwd());
  });
});

describe("OMP extension under a hostile or limited host", () => {
  function host(opts: { rejectTools?: boolean; unknownEvents?: string[] }) {
    const handlers = new Map<string, Handler>();
    const pi: HostLike = {
      on: (name, handler) => {
        if (opts.unknownEvents?.includes(name)) throw new Error(`unknown event ${name}`);
        handlers.set(name, handler);
      },
      registerTool: () => {
        if (opts.rejectTools) throw new Error("schema rejected");
      },
    };
    return { pi, handlers };
  }

  it("keeps working when the host rejects the tools, and the card then names the CLI", () => {
    const h = mkdtempSync(join(tmpdir(), "omp-h-"));
    createNote(h, { text: "A decision", project: "work", kind: "decision" });
    const { pi, handlers } = host({ rejectTools: true });
    expect(() => secondBrain(pi, { SECOND_BRAIN_HOME: h })).not.toThrow();
    const card = handlers.get("before_agent_start")?.({ prompt: "x" }, ctx("s")) as { message: { content: string } };
    expect(card.message.content).toContain('brain recall "<query>"');
    expect(card.message.content).not.toContain("brain_recall(");
  });

  it("names the CLI when tools are switched off", () => {
    const h = mkdtempSync(join(tmpdir(), "omp-h-"));
    createNote(h, { text: "A decision", project: "work", kind: "decision" });
    const { pi, handlers } = host({});
    secondBrain(pi, { SECOND_BRAIN_HOME: h, BRAIN_TOOLS: "off" });
    const card = handlers.get("before_agent_start")?.({ prompt: "x" }, ctx("s")) as { message: { content: string } };
    expect(card.message.content).toContain('brain recall "<query>"');
  });

  it("survives a host that does not know some events", () => {
    const { pi, handlers } = host({ unknownEvents: ["context", "session_compact"] });
    expect(() => secondBrain(pi, { SECOND_BRAIN_HOME: home })).not.toThrow();
    expect([...handlers.keys()].sort()).toEqual(["before_agent_start", "session_before_branch", "session_before_compact", "session_before_switch", "session_branch", "session_shutdown", "session_switch", "tool_result"]);
  });
});
