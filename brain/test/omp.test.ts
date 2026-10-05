/**
 * Tests for the OMP extension (brain/src/omp.ts).
 * Fake host collecting handlers and tools, with temp directories for Brain home.
 */
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { LEAN_LINE } from "../src/card.ts";
import secondBrain, { CARD_TYPE, editedPaths, hasBackspaceEscape, type HostLike } from "../src/omp.ts";
import { createNote, loadNotes, saveNote } from "../src/notes.ts";
import { appendEvent, listProposals } from "../src/capture.ts";
import { readWork, writeWork } from "../src/work.ts";
import { stats } from "../src/telemetry.ts";

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
  it("awaits judged recall and logs the final shown ids", async () => {
    createNote(home, { project: "work", text: "Topaz migration guidance" });
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work", TYPESAFE_API_KEY: "synthetic-omp" }, true);
    const fetch = vi.fn(async () => new Response(JSON.stringify({ answers: { rel_0: { noul: 0.1 } } })));
    vi.stubGlobal("fetch", fetch);
    try {
      const recall = tools.find((t: any) => t.name === "brain_recall") as any;
      const result = await recall.execute("judged", { query: "topaz migration" }, ctx("judged"));
      expect(result.content[0].text).toBe("no match; note it once you learn it");
      const row = JSON.parse(readFileSync(join(home, "state", "telemetry.jsonl"), "utf8"));
      expect(row).toMatchObject({ query: "topaz migration", ids: [], hits: 0, judged: true, dropped: 1, via: "tool" });
    } finally { vi.unstubAllGlobals(); }
  });

  it("logs scrubbed recall queries and private note ids, never returned text", async () => {
    const note = createNote(home, { project: "work", text: "Private deployment detail", private: true });
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" }, true);
    const recall = tools.find((t: any) => t.name === "brain_recall") as any;
    (await recall.execute("a", { query: note.id }, ctx("queries")));
    const query = "password=" + "syntheticCredential123" + " " + "missing ".repeat(40);
    (await recall.execute("b", { query }, ctx("queries")));
    const text = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8");
    const rows = text.trim().split("\n").map(line => JSON.parse(line));
    expect(rows[0]).toMatchObject({ via: "tool", query: note.id, ids: [note.id] });
    expect(rows[1]).toMatchObject({ query: ("password=*** " + "missing ".repeat(40)).slice(0, 200), ids: [] });
    expect(text).not.toContain(note.body);
    expect(text).not.toContain("syntheticCredential123");
  });

  it("records only ids actually shown, in the displayed order", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" }, true);
    for (const suffix of ["primary", "backup", "fallback", "emergency"]) createNote(home, { project: "work", text: `Quartz deployment ${suffix}` });
    const recall = tools.find((t: any) => t.name === "brain_recall") as any;
    const shown = (await recall.execute("ordered", { query: "quartz deployment" }, ctx("queries"))).content[0].text as string;
    const row = JSON.parse(readFileSync(join(home, "state", "telemetry.jsonl"), "utf8"));
    expect(row.ids).toEqual(shown.split("\n").map(line => line.split(" ")[0]));
    expect(row.ids).toHaveLength(3);
  });

  it.each(["aborted by user", "cancelled by host"])("leaves pending fixes unjudged after %s until a real rerun", (noise) => {
    const note = createNote(home, { project: "global", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const { handlers } = load();
    const result = (session: string, content: string, isError: boolean) => handlers.get("tool_result")!({ toolName: "bash", input: { command: "npm test" }, isError, content }, ctx(session));
    const outcomes = () => readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line)).filter(row => row.kind === "fixout").map(row => [row.session, row.id, row.outcome]);
    for (const session of ["help", "miss"]) {
      result(session, "runtime mismatch", true);
      result(session, noise, true);
    }
    expect(outcomes()).toEqual([]);
    result("help", "ok", false);
    result("miss", "real failure", true);
    expect(outcomes()).toEqual([["help", note.id, "helped"], ["miss", note.id, "missed"]]);
  });

  it("scores only the next same-key result in the same session and drops untried fixes", () => {
    const note = createNote(home, { project: "global", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    const { handlers } = load();
    const result = (session: string, command: string | undefined, failed: boolean, toolName = "bash") => handlers.get("tool_result")!({ toolName, input: command ? { command } : {}, isError: failed, content: failed ? "runtime mismatch" : "ok" }, ctx(session));
    result("help", "build", true);
    result("other", "build", false);
    result("help", "test", false);
    result("help", "build", false);
    result("help", "build", false);
    result("miss", undefined, true, "edit");
    result("miss", undefined, true, "edit");
    result("miss", undefined, false, "edit");
    for (const event of ["session_compact", "session_shutdown", "session_before_switch"]) {
      result(event, "build", true);
      handlers.get(event)!({}, ctx(event));
      result(event, "build", false);
    }
    const outcomes = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line)).filter(row => row.kind === "fixout");
    expect(outcomes.map(row => [row.session, row.id, row.outcome])).toEqual([["help", note.id, "helped"], ["miss", note.id, "missed"], ["miss", note.id, "helped"]]);
  });
  it("falls back to its own checkout as the home when SECOND_BRAIN_HOME is unset", () => {
    const { handlers } = load({}, false);
    expect([...handlers.keys()].sort()).toEqual(["before_agent_start", "context", "input", "session_before_branch", "session_before_switch", "session_branch", "session_compact", "session_shutdown", "session_start", "session_switch", "tool_result", "turn_end"]);
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

    // Compaction dropped the card: the next prompt carries only the lean line, once.
    handlers.get("session_compact")!({}, c);
    const lean = start({ prompt: "after compaction" }, c) as any;
    expect(lean.message.content).toBe(LEAN_LINE);
    expect(lean.message.customType).not.toBe(CARD_TYPE);
    expect(start({ prompt: "later" }, c)).toBeUndefined();
  });

  it("a session resumed in a new process keeps its card: none again until a compaction", () => {
    createNote(home, { text: "Test note for card", project: "work", kind: "fact" });
    const branch: unknown[] = [
      { type: "message", message: { role: "user", content: "first" } },
      { type: "custom_message", customType: CARD_TYPE, content: "Brain · work", details: { v: 4 } },
    ];
    const resumed = { cwd: join(root, "work"), sessionManager: { getSessionId: () => "s-resumed", getBranch: () => branch } };
    // A fresh process (new handlers, empty memory) resumes the persisted session.
    expect(load().handlers.get("before_agent_start")!({ prompt: "continue" }, resumed)).toBeUndefined();

    // After a compaction the old card is gone from the context: the next process cards again.
    branch.push({ type: "compaction", summary: "…" });
    const after = load().handlers.get("before_agent_start")!({ prompt: "continue" }, resumed) as { message?: { customType?: string } } | undefined;
    expect(after?.message?.customType).toBe(CARD_TYPE);
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

  it("a repeated error gets a pointer, the full fix again only after compaction drops it", () => {
    const workDir = join(root, "work");
    mkdirSync(workDir, { recursive: true });
    const { handlers } = load();
    const note = createNote(home, { text: "Fix for SRE mismatch", project: "global", kind: "gotcha", errors: ["SRE module mismatch"], tested: true });
    const c = ctx("s-repeat", workDir);
    const fail = { toolName: "bash", input: { command: "python test.py" }, isError: true, content: [{ type: "text", text: "SRE module mismatch" }] };
    const fixText = () => (handlers.get("tool_result")!(fail, c) as any).content[1].text as string;
    expect(fixText()).toContain("Fix for SRE mismatch");
    expect(fixText()).toBe(`\nBrain: same fix as above [${note.id}]`);
    expect((handlers.get("tool_result")!(fail, ctx("other-session", workDir)) as any).content[1].text).toContain("Fix for SRE mismatch");
    handlers.get("session_compact")!({}, c);
    expect(fixText()).toContain("Fix for SRE mismatch");
    // /clear keeps the session id and fires no compaction: a shrinking context is the signal.
    handlers.get("context")!({ messages: [{}, {}, {}] }, c);
    expect(fixText()).toBe(`\nBrain: same fix as above [${note.id}]`);
    handlers.get("context")!({ messages: [{}] }, c);
    expect(fixText()).toContain("Fix for SRE mismatch");
  });

  it("fires only fixes scoped to OMP or to no host", () => {
    const workDir = join(root, "work");
    mkdirSync(workDir, { recursive: true });
    const { handlers } = load();
    const cc = createNote(home, { text: "Claude Code only fix", project: "global", kind: "gotcha", errors: ["String to replace not found"], tested: true });
    saveNote(home, { ...cc, host: "claude-code" });
    const omp = createNote(home, { text: "OMP only fix", project: "global", kind: "gotcha", errors: ["is not from this session."], tested: true });
    saveNote(home, { ...omp, host: "omp" });
    const result = (text: string) => (handlers.get("tool_result")!({ toolName: "edit", input: { path: "a.ts" }, isError: true, content: [{ type: "text", text }] }, ctx("s-host", workDir)) as any)?.content;
    expect(result("String to replace not found in file.")).toBeUndefined();
    expect(result("Hash abc is not from this session.")?.[1]?.text).toContain("OMP only fix");
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
          toolName: "edit",
          input: { input: `*** Begin Patch\n[file${i}.ts#ABCD]\nPUT 1.=1:\n+updated\n*** End Patch` },
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

  it("brain_recall tool: recall finds a note written by brain_note", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    // Prepare: write a note first
    const noteTool = tools.find((t: any) => t.name === "brain_note") as any;
    expect(noteTool).toBeDefined();

    // Execute brain_note to create a note
    const noteResult = (await noteTool.execute(
      "n-id",
      { text: "Important pattern to remember" },
      {},
      {},
      ctx("s-tools")
    )) as any;
    expect(noteResult.content[0].text).toContain("saved");

    // Now execute brain_recall to find it
    const recallTool = tools.find((t: any) => t.name === "brain_recall") as any;
    const recallResult = (await recallTool.execute(
      "r-id",
      { query: "pattern" },
      {},
      {},
      ctx("s-tools")
    )) as any;
    expect(recallResult.content[0].text).toContain("Important pattern");
  });

  it("brain_state tool: writes the work file", async () => {
    const workDir = join(root, "work");
    mkdirSync(join(workDir, ".git"), { recursive: true });
    writeFileSync(join(workDir, ".git", "config"), '[core]\nbare = false\n');

    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;
    const result = (await stateTool.execute(
      "state-id",
      { text: "Goal: finish implementation" },
      {},
      {},
      ctx("s-state", workDir)
    )) as any;

    expect(result.content[0].text).toContain("state saved");

    const workFile = readWork(home, "work");
    expect(workFile?.text).toContain("Goal: finish");
  });

  it("tool errors come back as text, not exceptions", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);

    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;

    // Call without required text
    const result = (await stateTool.execute("id", {}, {}, {}, ctx("s-error"))) as any;
    expect(result.content[0].text).toContain("brain:");
    expect(result.content[0].text).not.toContain("throw");
  });

  it("tools execute with (id, params, signal, onUpdate, ctx) order", async () => {
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
    const result = (await recallTool.execute(
      "tool-id",
      { query: "recall" },
      {},
      () => {},
      ctx("s-sig", workDir)
    )) as any;

    expect(result.content).toBeDefined();
    expect(result.content[0].text).toContain("Something");
  });

  it("tools execute with (id, params, ctx) order", async () => {
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
    const result = (await recallTool.execute(
      "tool-id",
      { query: "find" },
      ctx("s-short-sig", workDir)
    )) as any;

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

  it("keeps host plumbing and resolved failures out of the working state", () => {
    const { handlers } = load();
    const toolResult = handlers.get("tool_result")!;
    const c = ctx("s-failures");
    const fail = (toolName: string, command: string | undefined, text: string) => toolResult({ toolName, input: command ? { command } : {}, isError: true, content: [{ type: "text", text }] }, c);

    fail("wait", undefined, "Daemon broker request aborted");
    fail("bash", "sleep 100", "Command aborted by user");
    handlers.get("session_shutdown")!({}, c);
    expect(readWork(home, "work")?.auto ?? "").not.toContain("last failure");

    fail("bash", "npm test", "Error: 3 tests failed");
    toolResult({ toolName: "bash", input: { command: "npm test" }, isError: false, content: [{ type: "text", text: "ok" }] }, c);
    handlers.get("session_shutdown")!({}, c);
    expect(readWork(home, "work")?.auto ?? "").not.toContain("last failure");

    fail("bash", "npm run build", "Error: tsc exited");
    handlers.get("session_shutdown")!({}, c);
    expect(readWork(home, "work")?.auto).toContain("last failure: npm run build → Error: tsc exited");
  });

  it("context ignores missing or non-array messages", () => {
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

  it("refuses same-headline conflicting bodies without upgrading their errors or tested status", async () => {
    const existing = createNote(home, { project: "work", text: "Plugin setup\nUse the project plugin" });
    const before = readFileSync(existing.path, "utf8");
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" }, true);
    const noteTool = tools.find((t: any) => t.name === "brain_note") as any;
    const result = (await noteTool.execute("conflict", { text: "Plugin setup\nUse the global plugin", tested: true, error: "plugin missing" }, ctx("parent")));
    expect(result.content[0].text).toBe("not saved: " + existing.id + " has this headline with a different body; use a new headline, or `brain retire " + existing.id + "` first");
    expect(readFileSync(existing.path, "utf8")).toBe(before);
    const identical = (await noteTool.execute("same", { text: "Plugin setup\n\nUse the project plugin", tested: true }, ctx("parent")));
    expect(identical.content[0].text).toBe("updated " + existing.id);
    expect(loadNotes(home).notes[0]?.tested).toBe(true);
  });

  it("brain_note: null optional fields mean unset; an unknown kind is refused", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" }, true);
    const noteTool = tools.find((t: any) => t.name === "brain_note") as any;
    const refused = (await noteTool.execute("bug", { text: "Kind probe", kind: "bug" }, ctx("parent"))).content[0].text;
    expect(refused).toBe("brain: unknown kind bug (note, fact, decision, gotcha, procedure)");
    const saved = (await noteTool.execute("nulls", { text: "Kind probe", kind: null, error: null, tested: null, global: null }, ctx("parent"))).content[0].text;
    expect(saved).toMatch(/^saved n-/);
    expect(loadNotes(home).notes.map((note) => note.kind)).toEqual(["note"]);
  });

  it("subagent notes cannot claim verification or upgrade an existing note to tested", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" }, true);
    const noteTool = tools.find((t: any) => t.name === "brain_note") as any;
    const child = { ...ctx("child"), agent: { kind: "sub" } };
    const text = "Compiler needs the project-local plugin";
    const saved = (await noteTool.execute("new", { text, tested: true }, child)).content[0].text;
    const note = loadNotes(home).notes[0]!;
    expect(note.tested).toBe(false);
    expect(saved).toBe("saved " + note.id + " (untested: the parent or `brain tested <id>` confirms)");
    (await noteTool.execute("duplicate", { text, tested: true, error: "plugin missing" }, child));
    expect(loadNotes(home).notes[0]?.tested).toBe(false);
    const { handlers } = load();
    expect(handlers.get("tool_result")!({ toolName: "bash", input: { command: "npm test" }, isError: true, content: [{ type: "text", text: "plugin missing" }] }, child)).toBeUndefined();
    (await noteTool.execute("parent", { text, tested: true }, { ...ctx("parent"), agent: { kind: "main" } }));
    expect(loadNotes(home).notes[0]?.tested).toBe(true);
  });

  it("child startup leaves capture proposals to the parent", () => {
    const cwd = join(root, "work");
    mkdirSync(cwd);
    appendEvent(home, "previous", cwd, { tool: "bash", command: "npm test", ok: false, error: "Cannot find module left-pad" });
    appendEvent(home, "previous", cwd, { tool: "bash", command: "npm ci && npm test", ok: true });
    const { handlers } = load({ SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "work" });
    const start = handlers.get("before_agent_start")!;
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    const tick = () => vi.runOnlyPendingTimers();
    start({ prompt: "run tests" }, { ...ctx("child", cwd), agent: { kind: "sub" } });
    tick();
    expect(listProposals(home)).toEqual([]);
    start({ prompt: "run tests" }, { ...ctx("parent", cwd), agent: { kind: "main" } });
    tick();
    vi.useRealTimers();
    expect(listProposals(home).map(p => p.text)).toEqual([expect.stringContaining("npm ci && npm test works")]);
  });

  it("subagent brain_state cannot overwrite the parent's plan", async () => {
    const plan = writeWork(home, "work", "Goal: parent owns this plan");
    const before = readFileSync(plan.path, "utf8");
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);
    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;
    const child = { ...ctx("child"), hasUI: false, sessionManager: { getSessionId: () => "child", getSessionFile: () => "child.jsonl", getHeader: () => ({ parentSession: "parent.jsonl" }) } };
    const result = (await stateTool.execute("id", { text: "Goal: child task" }, undefined, undefined, child));
    expect(result.content[0].text).toBe("not saved: working state belongs to the parent session");
    expect(readFileSync(plan.path, "utf8")).toBe(before);
    expect(existsSync(join(home, "state"))).toBe(false);
  });

  it("host agent identity decides: a headless top-level run saves, a sub with UI does not", async () => {
    const { tools } = load({ SECOND_BRAIN_HOME: home }, true);
    const stateTool = tools.find((t: any) => t.name === "brain_state") as any;
    const headlessMain = { ...ctx("print"), hasUI: false, agent: { kind: "main" }, sessionManager: { getSessionId: () => "print", getSessionFile: () => undefined } };
    expect((await stateTool.execute("id", { text: "Goal: headless plan" }, undefined, undefined, headlessMain)).content[0].text).toMatch(/^state saved/);
    const tanClone = { ...ctx("tan"), agent: { kind: "sub" } };
    expect((await stateTool.execute("id", { text: "Goal: clone plan" }, undefined, undefined, tanClone)).content[0].text).toBe("not saved: working state belongs to the parent session");
    expect(readWork(home, "work")?.text).toBe("Goal: headless plan");
  });

  it("bash cwd attributes the event and known fix to the command's project", () => {
    const a = join(root, "a");
    const b = join(root, "b");
    mkdirSync(a); mkdirSync(b);
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { a: { paths: [a] }, b: { paths: [b] } } }));
    createNote(home, { project: "b", text: "Use the project B compiler", errors: ["compiler missing"], tested: true });
    const { handlers } = load();
    const result = handlers.get("tool_result")!({ toolName: "bash", input: { command: "build", cwd: "../b" }, isError: true, content: [{ type: "text", text: "compiler missing" }] }, ctx("cwd", a)) as any;
    expect(result?.content[1].text).toContain("Use the project B compiler");
    const eventsDir = join(home, "state", "events");
    const rows = readdirSync(eventsDir).flatMap(f => readFileSync(join(eventsDir, f), "utf8").trim().split("\n").map(row => JSON.parse(row)));
    expect(rows[0].cwd).toBe(b);
  });

  it("hashline edits track source and move destination but not patch body headers", () => {
    expect(editedPaths({ input: "*** Begin Patch\n[src/a.ts#1A2B]\nPUT 1.=1:\n+[fake.ts#ABCD]\nMV src/b.ts\n[src/c.ts#ABCD]\nREM\n*** End Patch" })).toEqual(["src/a.ts", "src/b.ts", "src/c.ts"]);
  });

  it("child startup omits the parent plan and measures child cards and recall hits", async () => {
    writeWork(home, "work", "Goal: private parent plan");
    createNote(home, { project: "work", text: "Compiler wiring uses the plugin registry" });
    const { tools, handlers } = load({ SECOND_BRAIN_HOME: home }, true);
    const child = { ...ctx("child-card"), hasUI: false };
    const result = handlers.get("before_agent_start")!({ prompt: "compiler wiring" }, child) as any;
    expect(result.message.content).not.toContain("private parent plan");
    expect(result.message.content).not.toContain("brain_state(");
    const recall = tools.find((t: any) => t.name === "brain_recall") as any;
    (await recall.execute("hit", { query: "compiler wiring" }, undefined, undefined, child));
    (await recall.execute("miss", { query: "zzzyyyxxx" }, undefined, undefined, child));
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(row => JSON.parse(row));
    expect(rows.find(row => row.kind === "card")).toMatchObject({ sub: true });
    expect(rows.find(row => row.kind === "card").via).toBeUndefined();
    expect(rows.filter(row => row.kind === "recall").map(row => ({ hits: row.hits, via: row.via }))).toEqual([{ hits: 1, via: "tool" }, { hits: 0, via: "tool" }]);
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
    expect([...handlers.keys()].sort()).toEqual(["before_agent_start", "input", "session_before_branch", "session_before_compact", "session_before_switch", "session_branch", "session_shutdown", "session_start", "session_switch", "tool_result", "turn_end"]);
  });

  it("a child session keeps brain_recall and drops brain_note and brain_state; the parent keeps all", async () => {
    const handlers = new Map<string, Handler>();
    let active = ["read", "brain_recall", "brain_note", "brain_state"];
    const pi: HostLike = {
      on: (name, handler) => void handlers.set(name, handler),
      registerTool: () => undefined,
      getActiveTools: () => [...active],
      setActiveTools: async (names) => { active = names; },
    };
    secondBrain(pi, { SECOND_BRAIN_HOME: home });
    await handlers.get("session_start")!({}, { ...ctx("parent"), agent: { kind: "main" } });
    expect(active).toEqual(["read", "brain_recall", "brain_note", "brain_state"]);
    await handlers.get("session_start")!({}, { ...ctx("child"), agent: { kind: "sub" } });
    expect(active).toEqual(["read", "brain_recall"]);
  });



  it("spots a quoted \\b (a backspace at runtime) in eval code, never a regex literal or String.raw", () => {
    expect(hasBackspaceEscape(String.raw`await tool.grep({ pattern: "\badd\b", path: "src" })`)).toBe(true);
    expect(hasBackspaceEscape(String.raw`await tool.grep({ pattern: '\badd\(' })`)).toBe(true);
    expect(hasBackspaceEscape(String.raw`await tool.grep({ pattern: "\\badd\\b" })`)).toBe(false);
    expect(hasBackspaceEscape("await tool.grep({ pattern: String.raw`\\badd\\b` })")).toBe(false);
    expect(hasBackspaceEscape(String.raw`const found = /\badd\b/.test(text)`)).toBe(false);
    expect(hasBackspaceEscape(String.raw`print("tab\tnewline\n")`)).toBe(false);
    // Review reproductions: comments, regex literals holding quotes, raw templates; cooked templates.
    expect(hasBackspaceEscape(String.raw`print(/'\bword\b'/.test("'word'"))`)).toBe(false);
    expect(hasBackspaceEscape("print(String.raw`'\\bword\\b'`)")).toBe(false);
    expect(hasBackspaceEscape(String.raw`// avoid '\bword\b'` + "\nprint(\"ok\")")).toBe(false);
    expect(hasBackspaceEscape("const p = `\\b${word}\\b`")).toBe(true);
    expect(hasBackspaceEscape("const p = String.raw`\\b${word}\\b`")).toBe(false);
    expect(hasBackspaceEscape("const n = a / b; const s = '\\b'")).toBe(true);
  });

  it("appends the backspace hint to an eval whose quoted pattern holds \\b, then only a pointer", () => {
    const { handlers } = load();
    const c = ctx("raw");
    const run = (code: string, language = "js") => handlers.get("tool_result")!({ toolName: "eval", toolCallId: "e", input: { language, code }, isError: false, content: [{ type: "text", text: "(no matches)" }] }, c) as { content: { text: string }[] } | undefined;
    expect(run(String.raw`await tool.grep({ pattern: String.raw` + "`\\badd\\b`" + " })")).toBeUndefined();
    // Python raw strings are correct as written; the JavaScript advice would be wrong there.
    expect(run(String.raw`import re; print(re.search(r'\bword\b', 'word'))`, "py")).toBeUndefined();
    expect(run(String.raw`await tool.grep({ pattern: '\badd\b' })`)?.content.at(-1)?.text).toContain("is a backspace, not a word boundary");
    expect(run(String.raw`await tool.grep({ pattern: '\bsum\b' })`)?.content.at(-1)?.text).toBe("\nBrain: quoted '\\b' is a backspace again (see above).");
  });

  it("fails open but records a swallowed handler error for brain stats", () => {
    const { handlers } = load();
    const bad = { get cwd(): string { throw new Error("host ctx broke"); }, sessionManager: { getSessionId: () => "s-err" } };
    expect(handlers.get("before_agent_start")!({ prompt: "x" }, bad)).toBeUndefined();
    expect(stats(home).errors.map((e) => e.error)).toEqual(["before_agent_start: Error: host ctx broke"]);
  });


});
