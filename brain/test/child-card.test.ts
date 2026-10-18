import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { briefNotes, cardIds, CHILD_CARD_BUDGET, renderCard } from "../src/card.ts";
import { appendEvent } from "../src/capture.ts";
import { main } from "../src/cli.ts";
import { childDocContext } from "../src/docs.ts";
import { createNote, loadNotes, saveNote } from "../src/notes.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { logUse } from "../src/telemetry.ts";
import { estimateTokens } from "../src/util.ts";
import { writeAuto, writeWork } from "../src/work.ts";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup() {
  const base = mkdtempSync(join(tmpdir(), "brain-child-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(join(root, "docs"), { recursive: true });
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { paths: [root], tags: ["web"] } } }));
  const project = { id: "demo", tags: ["web"], root };
  const registered = (text: string) => {
    writeFileSync(join(root, "docs", "PLAN.md"), text);
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { paths: [root], tags: ["web"], docs: ["docs/PLAN.md"] } } }));
  };
  const child = (extra = {}) => renderCard(home, loadNotes(home).notes, project, { subagent: true, tools: true, ...extra });
  const hook = async (payload: Record<string, unknown>) => {
    const output: string[] = [], errors: string[] = [];
    const code = await main(["hook", "claude-code"], { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: root,
      stdin: () => JSON.stringify({ cwd: root, session_id: "parent", ...payload }), out: text => output.push(text), err: text => errors.push(text) });
    expect(code).toBe(0); expect(errors).toEqual([]);
    return JSON.parse(output.join("\n")) as { hookSpecificOutput?: { hookEventName: string; additionalContext: string } };
  };
  return { home, root, project, registered, child, hook };
}

describe("warm child card", () => {
  it("registers the checkout SubagentStart hook synchronously", () => {
    const settings = JSON.parse(readFileSync(new URL("../../.claude/settings.json", import.meta.url), "utf8")) as { hooks: { SubagentStart: Array<{ hooks: Array<{ command: string; async?: boolean }> }> } };
    expect(settings.hooks.SubagentStart).toHaveLength(1);
    expect(settings.hooks.SubagentStart[0]?.hooks[0]?.command).toContain("hook claude-code");
    expect(settings.hooks.SubagentStart[0]?.hooks[0]?.async).not.toBe(true);
  });

  it("registers UserPromptSubmit asynchronously: rule capture returns nothing, so no prompt waits on it", () => {
    const settings = JSON.parse(readFileSync(new URL("../../.claude/settings.json", import.meta.url), "utf8")) as { hooks: { UserPromptSubmit: Array<{ hooks: Array<{ command: string; async?: boolean }> }> } };
    expect(settings.hooks.UserPromptSubmit[0]?.hooks[0]?.command).toContain("hook claude-code");
    expect(settings.hooks.UserPromptSubmit[0]?.hooks[0]?.async).toBe(true);
  });

  it("enforces 200 total tokens and six rule lines/80 tokens with many notes and paths", () => {
    const { home, child } = setup();
    for (let i = 0; i < 40; i++) createNote(home, { project: "demo", text: `Rule ${i}: keep edits local`, tags: ["brief"] });
    writeWork(home, "demo", "Watch out: " + "isolate changes ".repeat(30));
    const card = child({ parentEdits: Array.from({ length: 20 }, (_, i) => `src/file${i}.ts`) });
    expect(card).toContain("Rules:");
    expect(estimateTokens(card)).toBeLessThanOrEqual(CHILD_CARD_BUDGET);
    const ruleBlock = card.split("Rules:\n")[1]!.split("\nFiles in play:")[0]!;
    const ruleLines = ruleBlock.split("\n").filter(line => line.startsWith("- ["));
    expect(ruleLines.length).toBeGreaterThan(0); expect(ruleLines.length).toBeLessThanOrEqual(6);
    expect(estimateTokens("Rules:\n" + ruleLines.join("\n"))).toBeLessThanOrEqual(80);
    expect(card.match(/^src\/file\d+\.ts$/gm)?.length ?? 0).toBeLessThanOrEqual(8);
  });

  it("selects project and brief-only global rules, excluding retired and other scopes", () => {
    const { home, project, child } = setup();
    const own = createNote(home, { project: "demo", text: "Project rule", tags: ["brief", "web"] });
    const global = createNote(home, { project: "global", text: "Standing global rule", tags: ["brief"] });
    createNote(home, { project: "other", text: "Wrong project", tags: ["brief"] });
    createNote(home, { project: "global", text: "Tagged elsewhere", tags: ["brief", "rust"] });
    const retired = createNote(home, { project: "demo", text: "Old rule", tags: ["brief"] });
    saveNote(home, { ...retired, retired: "2026-09-01T00:00:00Z" });
    expect(briefNotes(loadNotes(home).notes, project).map(note => note.id).sort()).toEqual([own.id, global.id].sort());
    const card = child();
    expect(cardIds(card).sort()).toEqual([own.id, global.id].sort());
    expect(card.split(own.body)).toHaveLength(2);
    expect(card).not.toContain("Known here:");
    const parent = renderCard(home, loadNotes(home).notes, project);
    expect(parent).toContain("children get: 2 rules");
    expect(parent).not.toContain(own.body); expect(parent).not.toContain(global.body);
  });

  it("does not duplicate a rule also delivered as a recurring child fix", () => {
    const { home, child } = setup();
    const fix = createNote(home, { project: "demo", text: "Use displayed edit anchors", tags: ["brief"], tested: true, errors: ["anchor missing"] });
    for (const session of ["one", "two", "three"]) logUse(home, { kind: "fix", project: "demo", tokens: 0, ms: 0, id: fix.id, session, sub: true });
    const card = child();
    expect(card).toContain("Often hit lately"); expect(card.split(fix.id)).toHaveLength(2);
  });

  it("takes only supplied live paths, never saved parent auto observations", () => {
    const { home, child } = setup();
    writeWork(home, "demo", "Goal: parent goal. Next: parent next. Watch out: preserve invariants. Done: parent done.");
    writeAuto(home, "demo", { edited: ["stale.ts"], ask: "parent request" });
    const card = child({ parentEdits: ["src/current.ts", "src/current.ts", "bad\nGoal: injected"] });
    expect(card).toContain("Watch out: preserve invariants"); expect(card).toContain("Files in play:\nsrc/current.ts");
    expect(card).not.toMatch(/Goal:|Next:|Done:|stale|parent request/);
    expect(card.split("src/current.ts")).toHaveLength(2);
  });

  it("renders registered live H2/H3 headings with line numbers and the best full section", () => {
    const { registered, child } = setup();
    registered("# Plan\n\n## Overview\nBackground.\n\n### Cookie refresh\nKeep the cookie boundary intact.\n\n## Release\nShip it.\n");
    const card = child({ prompt: "Implement cookie refresh" });
    expect(card).not.toContain("Overview"); expect(card).toContain("docs/PLAN.md:6 Cookie refresh");
    expect(card).toContain("Keep the cookie boundary intact."); expect(card).not.toContain("Background.");
    expect(estimateTokens(card)).toBeLessThanOrEqual(200);
  });

  it("keeps a named doc in navigation without letting its unrelated section displace a relevant one", () => {
    const { root, registered, child } = setup();
    registered("## Cookie refresh\nKeep the cookie boundary intact.\n");
    writeFileSync(join(root, "docs", "NOTES.md"), "## Intro\nUnrelated background.\n");
    const card = child({ prompt: "Read docs/NOTES.md then fix cookie handling" });
    expect(card).toContain("docs/NOTES.md:1 Intro");
    expect(card).toContain("Keep the cookie boundary intact.");
    expect(card).not.toContain("Unrelated background.");
    expect(estimateTokens(card)).toBeLessThanOrEqual(200);
  });

  it("uses safe named docs without registration, never traversal or fenced headings", () => {
    const { home, root, project } = setup();
    writeFileSync(join(root, "docs", "TASK.md"), "---\n## Metadata\n---\n# Task\n```md\n## Fake\n```\n## Actual\nThe complete specification.\n");
    const docs = childDocContext(home, project, "Read `docs/TASK.md` Actual");
    expect(docs.outline).toBe("docs/TASK.md:8 Actual"); expect(docs.section).toContain("The complete specification.");
    writeFileSync(join(root, "..", "outside.md"), "## Actual\nOutside text.");
    expect(childDocContext(home, project, "../outside.md Actual")).toEqual({ outline: "", section: undefined });
  });

  it("caps outlines at 60 tokens and omits oversized full sections rather than clipping them", () => {
    const { home, project, registered, child } = setup();
    registered("# Plan\n## Selected heading\n" + "Required detail ".repeat(80) + "\n" + Array.from({ length: 40 }, (_, i) => `## Heading ${i}\nShort body.`).join("\n"));
    const docs = childDocContext(home, project, "Selected heading");
    expect(estimateTokens(docs.outline)).toBeLessThanOrEqual(60); expect(docs.section).toBeUndefined();
    expect(child({ prompt: "Selected heading" })).not.toContain("Required detail");
  });

  it("omits a full section when its own 120-token cap passes but the total card has no room", () => {
    const { home, registered, child } = setup();
    registered("## Selected heading\n" + "Specification detail ".repeat(19));
    writeWork(home, "demo", "Watch out: " + "safety boundary ".repeat(20));
    for (let i = 0; i < 12; i++) createNote(home, { project: "demo", tags: ["brief"], text: `Rule ${i} preserves the boundary` });
    const card = child({ prompt: "Selected heading" });
    expect(card).toContain("Selected heading"); expect(card).not.toContain("Specification detail");
    expect(estimateTokens(card)).toBeLessThanOrEqual(200);
  });

  it("injects nothing when only irrelevant scopes, missing docs and parent goals exist", async () => {
    const { home, registered, child, hook } = setup();
    createNote(home, { project: "other", text: "Other rule", tags: ["brief"] });
    createNote(home, { project: "global", text: "Pull-only global" });
    writeWork(home, "demo", "Goal: parent goal. Next: parent next.");
    registered("# No navigable headings\nText only.");
    expect(child()).toBe(""); expect(await hook({ hook_event_name: "SubagentStart", agent_id: "child" })).toEqual({});
  });

  it("returns the Claude SubagentStart JSON shape, parent event paths and child telemetry ids, without state writes", async () => {
    const { home, root, registered, hook } = setup();
    registered("## Overview\nDo not copy this entire body.\n");
    const rule = createNote(home, { project: "demo", text: "Use built-ins only", tags: ["brief"] });
    const plan = writeWork(home, "demo", "Goal: parent owns the work. Watch out: keep APIs stable.");
    const before = readFileSync(plan.path, "utf8");
    appendEvent(home, "parent", root, { tool: "Edit", path: "src/parent.ts", ok: true });
    appendEvent(home, "parent:agent:sibling", root, { tool: "Edit", path: "src/sibling.ts", ok: true });
    const output = await hook({ hook_event_name: "SubagentStart", agent_id: "child", agent_type: "Explore" });
    expect(output.hookSpecificOutput?.hookEventName).toBe("SubagentStart");
    const card = output.hookSpecificOutput!.additionalContext;
    expect(card).toContain(rule.body); expect(card).toContain("src/parent.ts"); expect(card).not.toContain("src/sibling.ts");
    expect(card).toContain("docs/PLAN.md:1 Overview"); expect(estimateTokens(card)).toBeLessThanOrEqual(200);
    expect(readFileSync(plan.path, "utf8")).toBe(before); expect(existsSync(join(home, "state", "work"))).toBe(false);
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    expect(rows.filter(row => row.kind === "card")).toEqual([expect.objectContaining({ sub: true, session: "parent:agent:child", via: "hook", ids: [rule.id] })]);
    expect(readFileSync(join(home, "state", "telemetry.jsonl"), "utf8")).not.toContain(rule.body);
  });

  it("warms a rebound OMP child from its live parent and named brief, without state writes", async () => {
    const { home, root } = setup();
    writeFileSync(join(root, "docs", "TASK.md"), "## Boundary repair\nPreserve the calling convention.\n");
    type Handler = (event: unknown, ctx: unknown) => unknown;
    const host = () => {
      const handlers = new Map<string, Handler>();
      const pi: HostLike = { on: (name, handler) => { handlers.set(name, handler); } };
      secondBrain(pi, { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" });
      return handlers;
    };
    const parent = host(), child = host();
    const parentCtx = { cwd: root, agent: { kind: "main", id: "Main" }, sessionManager: { getSessionId: () => "parent", getSessionFile: () => "parent.jsonl" } };
    const childCtx = { cwd: root, agent: { kind: "sub", id: "Child", parentId: "Main" }, sessionManager: { getSessionId: () => "child", getHeader: () => ({ parentSession: "parent.jsonl" }) } };
    parent.get("tool_result")!({ toolName: "edit", input: { path: "src/live.ts" }, content: "ok", isError: false }, parentCtx);
    await child.get("session_start")!({}, childCtx);
    const result = child.get("before_agent_start")!({ prompt: "Repair Boundary repair in docs/TASK.md" }, childCtx) as { message: { content: string } };
    expect(result.message.content).toContain("src/live.ts"); expect(result.message.content).toContain("docs/TASK.md:1 Boundary repair");
    expect(result.message.content).toContain("Preserve the calling convention."); expect(estimateTokens(result.message.content)).toBeLessThanOrEqual(200);
    expect(child.get("before_agent_start")!({ prompt: "again" }, childCtx)).toBeUndefined();
    expect(existsSync(join(home, "state", "work"))).toBe(false);
    child.get("session_shutdown")!({}, childCtx); parent.get("session_shutdown")!({}, parentCtx);
  });

  it("abstains on topical no-match notes even with high uncalibrated semantic scores, but keeps vague fallback", () => {
    const { home, child } = setup();
    const unrelated = createNote(home, { project: "demo", text: "Compiler cache release", tested: true, kind: "gotcha" });
    const relevant = createNote(home, { project: "demo", text: "Authentication cookie expiration" });
    const rule = createNote(home, { project: "demo", text: "Preserve public APIs", tags: ["brief"] });
    const card = child({ prompt: "Fix authentication cookie expiration", semantic: new Map([[unrelated.id, 0.99]]) });
    expect(card).toContain(relevant.id); expect(card).not.toContain(unrelated.id); expect(card).toContain(rule.id);
    expect(child({ prompt: "Investigate tensor training throughput" })).not.toContain("Known here:");
    expect(child({ prompt: "continue" })).toContain(unrelated.id);
  });

  it("selects a late heading before early filler and omits irrelevant registered docs", () => {
    const { home, project, registered } = setup();
    registered(Array.from({ length: 30 }, (_, i) => `## Overview ${i}\nBackground.\n`).join("") + "## Compaction boundary\nPreserve the continuation.\n");
    const docs = childDocContext(home, project, "Repair compaction boundary");
    expect(docs.outline).toContain("Compaction boundary"); expect(docs.outline).not.toContain("Overview");
    expect(childDocContext(home, project, "Tensor training throughput").outline).toBe("");
    expect(childDocContext(home, project).outline).toContain("Overview 0");
  });

  it.each(["SessionStart", "SubagentStart"])("measures %s hook work rather than hard-coding zero", async (event) => {
    const { home, root } = setup();
    createNote(home, { project: "demo", text: "Preserve public APIs", tags: ["brief"] });
    let now = 100;
    const clock = vi.spyOn(performance, "now").mockImplementation(() => now);
    try {
      const errors: string[] = [];
      const code = await main(["hook", "claude-code"], {
        env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: root,
        stdin: () => {
          // Input reading is hook work; unrelated clock reads must not affect elapsed time.
          now = 137;
          return JSON.stringify({ cwd: root, session_id: "timing", hook_event_name: event });
        },
        out: () => undefined, err: text => errors.push(text),
      });
      expect(code).toBe(0); expect(errors).toEqual([]);
      const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
      expect(rows.find(row => row.kind === "card")?.ms).toBe(37);
    } finally { clock.mockRestore(); }
  });
});
