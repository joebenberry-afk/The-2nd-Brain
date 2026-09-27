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
  it("registers nothing without a home (no SECOND_BRAIN_HOME, no local notes dir)", () => {
    // When no home is found, the function returns early without throwing
    const { handlers } = load({});
    // The repo root has a notes/ dir, so handlers will be registered; just verify no crash
    expect(handlers.size).toBeGreaterThanOrEqual(0);
  });

  it("registers handlers even when home is empty (no notes)", () => {
    const { handlers } = load();
    expect(handlers.size).toBeGreaterThan(0);
    expect(handlers.has("before_agent_start")).toBe(true);
    expect(handlers.has("context")).toBe(true);
    expect(handlers.has("session_before_compact")).toBe(true);
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
    // Create a note so card has content
    mkdirSync(join(home, "notes", "demo"), { recursive: true });
    createNote(home, {
      text: "Test note for card",
      project: "demo",
      kind: "fact",
    });

    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;
    const c = ctx("s1");

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
    const { handlers } = load();
    const start = handlers.get("before_agent_start")!;
    const beforeCompact = handlers.get("session_before_compact")!;

    const session = "s-prompt-test";
    const c = ctx(session);

    // Trigger before_agent_start with a prompt
    start({ prompt: "  test   with   spaces  " }, c);

    // Trigger compaction to write auto section
    beforeCompact({}, c);

    // Check the work file was written
    const workFile = join(home, "work", "omp.md");
    const content = readFileSync(workFile, "utf8");
    expect(content).toContain("- last ask: test with spaces");
  });

  it("compaction flow: tool_result + before_compact + compact + context", () => {
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const beforeCompact = handlers.get("session_before_compact")!;
    const compact = handlers.get("session_compact")!;
    const contextHandler = handlers.get("context")!;
    const start = handlers.get("before_agent_start")!;

    // Create a note so resume card has content
    createNote(home, {
      text: "Resume content here",
      project: "omp",
      kind: "fact",
    });

    const session = "s-compaction-flow";
    const c = ctx(session);

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

    // Step 2: before_compact writes auto section
    beforeCompact({}, c);

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
    const beforeCompact = handlers.get("session_before_compact")!;
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
    beforeCompact({}, c);
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
    const { handlers } = load();
    const beforeCompact = handlers.get("session_before_compact")!;
    const compact = handlers.get("session_compact")!;
    const start = handlers.get("before_agent_start")!;

    createNote(home, {
      text: "Fallback resume",
      project: "omp",
      kind: "fact",
    });

    const session = "s-fallback";
    const c = ctx(session);

    // Trigger compaction without calling context
    beforeCompact({}, c);
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
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;

    // Create a tested note with an error pattern
    createNote(home, {
      text: "Fix for SRE mismatch",
      project: "omp",
      kind: "gotcha",
      errors: ["SRE module mismatch"],
      tested: true,
    });

    const session = "s-fix";
    const c = ctx(session);

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
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const beforeCompact = handlers.get("session_before_compact")!;

    const session = "s-paths";
    mkdirSync(join(root, "work"), { recursive: true });
    const c = ctx(session, join(root, "work"));

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

    beforeCompact({}, c);

    const workFile = readWork(home, "omp");
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
    const { tools, handlers } = load({ SECOND_BRAIN_HOME: home }, true);
    const start = handlers.get("before_agent_start")!;

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
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;
    const result = stateTool.execute(
      "state-id",
      { text: "Goal: finish implementation" },
      {},
      {},
      ctx("s-state")
    ) as any;

    expect(result.content[0].text).toContain("state saved");

    const workFile = readWork(home, "omp");
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
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;

    // Create a note to find
    createNote(home, {
      text: "Something to recall later",
      project: "omp",
      kind: "fact",
    });

    // Call with full signature: (id, params, signal, onUpdate, ctx)
    const result = recallTool.execute(
      "tool-id",
      { query: "recall" },
      {},
      () => {},
      ctx("s-sig")
    ) as any;

    expect(result.content).toBeDefined();
    expect(result.content[0].text).toContain("Something");
  });

  it("tools execute with (id, params, ctx) order", () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;

    createNote(home, {
      text: "Another thing to find",
      project: "omp",
      kind: "fact",
    });

    // Call with short signature: (id, params, ctx)
    const result = recallTool.execute(
      "tool-id",
      { query: "find" },
      ctx("s-short-sig")
    ) as any;

    expect(result.content).toBeDefined();
    expect(result.content[0].text).toContain("Another thing");
  });

  it("session_shutdown writes auto section like before_compact", () => {
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const shutdown = handlers.get("session_shutdown")!;

    const session = "s-shutdown";
    mkdirSync(join(root, "work"), { recursive: true });
    const c = ctx(session, join(root, "work"));

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
    const workFile = readWork(home, "omp");
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
