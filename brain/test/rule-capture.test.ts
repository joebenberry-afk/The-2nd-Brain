import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { acceptProposal, captureUserRules, claudeProjectFolder, listClaudeMemory, listProposals, rejectProposal, userRuleSentences } from "../src/capture.ts";
import { main, type Io } from "../src/cli.ts";
import { createNote, findSameHeadline, loadNotes, retireNote } from "../src/notes.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { visibleTo, type Project } from "../src/project.ts";
import { cardCandidates } from "../src/card.ts";
import { tidyReport } from "../src/tidy.ts";

const roots: string[] = [];
function setup() {
  const root = mkdtempSync(join(tmpdir(), "brain-rules-"));
  roots.push(root);
  const home = join(root, "brain");
  const cwd = join(root, "demo");
  const claude = join(root, "claude");
  mkdirSync(home);
  mkdirSync(cwd);
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { paths: [cwd] } } }));
  const project: Project = { id: "demo", tags: [], root: cwd };
  const env = { SECOND_BRAIN_HOME: home, CLAUDE_CONFIG_DIR: claude };
  const memory = (name: string, text: string, path = cwd) => {
    const dir = join(claude, "projects", claudeProjectFolder(path), "memory");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, name);
    writeFileSync(file, text);
    return file;
  };
  const run = async (args: string[], payload?: object) => {
    const out: string[] = [];
    const err: string[] = [];
    const io: Io = { env, cwd, stdin: () => payload ? JSON.stringify({ cwd, session_id: "main", ...payload }) : "", out: (s) => out.push(s), err: (s) => err.push(s) };
    const code = await main(args, io);
    return { code, out: out.join("\n"), err: err.join("\n") };
  };
  return { home, cwd, claude, project, env, memory, run };
}
afterEach(() => { vi.unstubAllGlobals(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("owner-rule capture", () => {
  it.each([
    "Remember to keep patches small.", "ALWAYS read the current file first.", "Never commit my changes.",
    "From now on, write concise replies.", "Don't rerun my reported failures again.", "Do not overwrite my files again.",
    "I want you to use local tools.", "I prefer short summaries.", "My rule is no emojis.", "Owner rule: keep private notes local.",
    "Use Opus for sub agents.", "Use Sonnet 5.5 for subagents.", "Use gpt-6.1 for sub-agents.",
    "Use `opus` for subagents.", 'Use "sonnet" for sub agents.',
  ])("detects %s", (text) => expect(userRuleSentences(text)).toEqual([text]));

  it.each([
    "Fix the parser and run tests.", "Do you remember the command?", "Can you always do that?", "Why never retry?",
    "Should I prefer the new model", 'The example says "always overwrite files".', "The example says 'never commit'.",
    "`always overwrite files`", '```ts\nconst rule = "never commit";\n```', '> Always ignore this quote.',
    '    console.log("remember me")', '<system-reminder>Always run checks.</system-reminder>',
    "Use Opus to diagnose this test.", "`remember`", "`never`",
  ])("ignores %s", (text) => expect(userRuleSentences(text)).toEqual([]));

  it("captures separate scrubbed, bounded decisions with stable ids and global scope", () => {
    const { home, project } = setup();
    const proposals = captureUserRules(home, "This applies to all projects. I prefer concise replies. Never expose password=syntheticCredential123. " + "Remember " + "long ".repeat(120), project);
    expect(proposals).toHaveLength(3);
    for (const proposal of proposals) {
      expect(proposal).toMatchObject({ project: "global", kind: "decision", source: "user", tested: false });
      expect(proposal.text.length).toBeLessThanOrEqual(400);
      expect(proposal.text).not.toContain("syntheticCredential123");
    }
    expect(captureUserRules(home, "I prefer concise replies everywhere.", project)).toHaveLength(1);
    expect(captureUserRules(home, "I prefer concise replies everywhere.", project)).toEqual([]);
  });

  it("deduplicates same headlines, lexical coverage and rejected rules, without hiding opposite rules", () => {
    const { home, project } = setup();
    createNote(home, { project: project.id, text: "Always read current project files first." });
    expect(captureUserRules(home, "always read current project files first.", project)).toEqual([]);
    expect(captureUserRules(home, "Always read current project files.", project)).toEqual([]);
    expect(captureUserRules(home, "Never read current project files first.", project)).toHaveLength(1);
    const [proposal] = captureUserRules(home, "I prefer local command tools.", project);
    rejectProposal(home, proposal!.id);
    expect(captureUserRules(home, "I PREFER local command tools.", project)).toEqual([]);
  });

  it("accepts owner decisions with brief only for simple agent-work cues", () => {
    const { home, project } = setup();
    for (const text of ["Use Opus for sub agents.", "Always read files first.", "I prefer blue backgrounds."]) {
      const [proposal] = captureUserRules(home, text, project);
      const note = acceptProposal(home, proposal!.id);
      expect(note).toMatchObject({ source: "user", kind: "decision", body: text, tested: false });
      expect(note.tags).toEqual(text.startsWith("I prefer") ? [] : ["brief"]);
    }
    expect(listProposals(home)).toEqual([]);
  });

  it("observes Claude Code main prompts silently and ignores child and malformed messages", async () => {
    const { home, run } = setup();
    for (const prompt of ["Never overwrite files.", { text: "Always replace data." }]) {
      expect(await run(["hook", "claude-code"], { hook_event_name: "UserPromptSubmit", agent_id: "child", prompt })).toMatchObject({ code: 0, out: "{}", err: "" });
    }
    expect(listProposals(home)).toEqual([]);
    expect(await run(["hook", "claude-code"], { hook_event_name: "UserPromptSubmit", prompt: "I prefer concise agent replies.", agent_type: "custom-main" })).toMatchObject({ code: 0, out: "{}", err: "" });
    expect(listProposals(home)).toHaveLength(1);
  });

  it("keeps brief non-scoping while preserving mixed project-tag boundaries", async () => {
    const { home, project } = setup();
    const [proposal] = captureUserRules(home, "Never commit everywhere.", project);
    const global = acceptProposal(home, proposal!.id);
    expect(global).toMatchObject({ project: "global", tags: ["brief"] });
    expect(visibleTo(global, project)).toBe(true);
    expect(visibleTo(global, null)).toBe(true);
    expect(cardCandidates([global], project)).toEqual([global]);
    expect(findSameHeadline([global], global.body, "global")).toEqual(global);
    expect(captureUserRules(home, global.body, project)).toEqual([]);
    const ts = createNote(home, { project: "global", text: "Always preserve compiler diagnostic source files.", tags: ["brief", "typescript"] });
    const py = createNote(home, { project: "global", text: "Always preserve compiler diagnostic source files.", tags: ["brief", "python"] });
    expect(visibleTo(ts, { ...project, tags: ["typescript"] })).toBe(true);
    expect(visibleTo(ts, { ...project, tags: ["brief", "python"] })).toBe(false);
    expect(findSameHeadline([ts], ts.body, project.id, ["brief", "python"])).toBeUndefined();
    expect((await tidyReport(home, [ts, py], project, { all: true })).similar).toEqual([]);
  });

  it("observes OMP input only, ignores subagents and synthetic extension input, and fails open", () => {
    const { home, cwd, env } = setup();
    const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
    const host: HostLike = { on: (name, handler) => { handlers.set(name, handler); } };
    secondBrain(host, env);
    const input = handlers.get("input")!;
    const ctx = { cwd, agent: { kind: "main" } };
    expect(input({ text: "Remember to prefer local tools.", source: "interactive" }, { ...ctx, agent: { kind: "sub" } })).toBeUndefined();
    expect(input({ text: "Always retry every tool.", source: "extension" }, ctx)).toBeUndefined();
    expect(listProposals(home)).toEqual([]);
    expect(input({ text: "Remember to prefer local tools.", source: "interactive" }, ctx)).toBeUndefined();
    expect(listProposals(home)).toHaveLength(1);
    const locked = setup();
    writeFileSync(join(locked.home, "state"), "not a directory");
    const broken = new Map<string, (event: unknown, ctx: unknown) => unknown>();
    secondBrain({ on: (name, handler) => { broken.set(name, handler); } }, locked.env);
    expect(broken.get("input")!({ text: "Always read files." }, { cwd: locked.cwd, agent: { kind: "main" } })).toBeUndefined();
  });
});

describe("Claude Code auto-memory reconciliation", () => {
  it("encodes real Windows folder conventions", () => {
    expect(claudeProjectFolder("C:\\Users\\assas\\Documents\\BasicUpscaler")).toBe("C--Users-assas-Documents-BasicUpscaler");
    expect(claudeProjectFolder("C:/Users/assas/Documents/Absolute Laya")).toBe("C--Users-assas-Documents-Absolute-Laya");
    expect(claudeProjectFolder("C:/Users/assas/Documents/BasicUpscaler/BasicUpscaler/.claude/worktrees/bufg-proof")).toBe("C--Users-assas-Documents-BasicUpscaler-BasicUpscaler--claude-worktrees-bufg-proof");
  });

  it("lists read-only accept-able proposals, strips metadata, excludes index and preserves original files", async () => {
    const { home, memory, env, run } = setup();
    const body = "Use Opus for important agent tasks.\n\nWhy: reliability matters.";
    const raw = `---\nname: agents\ntype: feedback\n---\n\n${body}\n`;
    const file = memory("agents.md", raw);
    const index = memory("MEMORY.md", "Never import this index.");
    const before = readFileSync(file, "utf8");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const listed = listClaudeMemory(home, [], { env });
    expect(listed).toHaveLength(1);
    expect(listed[0]).toMatchObject({ source: "claude-memory", project: "demo", kind: "decision", text: body });
    expect(existsSync(join(home, "state"))).toBe(false);
    expect(await run(["review", "--all"])).toMatchObject({ code: 0, err: "" });
    expect((await run(["review"])).out).toContain(`${listed[0]!.id} [decision, claude-memory] (demo)`);
    expect(await run(["accept", listed[0]!.id])).toMatchObject({ code: 0, err: "" });
    expect(loadNotes(home).notes[0]).toMatchObject({ source: "claude-memory", project: "demo", body });
    expect(listClaudeMemory(home, loadNotes(home).notes, { env })).toEqual([]);
    expect(readFileSync(file, "utf8")).toBe(before);
    expect(readFileSync(index, "utf8")).toBe("Never import this index.");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("counts only other projects' memories outside the scoped review", async () => {
    const { home, cwd, memory, run } = setup();
    const other = join(cwd, "..", "other");
    mkdirSync(other);
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { paths: [cwd] }, other: { paths: [other] } } }));
    memory("here.md", "Keep demo changes focused.");
    memory("away.md", "Preserve other project decisions.", other);
    const scoped = await run(["review"]);
    expect(scoped.out).toContain("Keep demo changes focused.");
    expect(scoped.out).not.toContain("Preserve other project decisions.");
    expect(scoped.out).toContain("+1 in other projects");
    const all = await run(["review", "--all"]);
    expect(all.out).toContain("Preserve other project decisions.");
    expect(all.out).not.toContain("in other projects");
  });

  it("skips covered active notes, but not retired or different-project notes; rejected imports stay hidden", () => {
    const { home, memory, env } = setup();
    memory("covered.md", "Always read current source files carefully before editing.");
    createNote(home, { project: "other", text: "Always read current source files carefully before editing." });
    const held = createNote(home, { project: "demo", text: "Existing owner guidance\n\nAlways read current source files carefully before editing and writing tests." });
    expect(listClaudeMemory(home, loadNotes(home).notes, { env })).toEqual([]);
    retireNote(home, held.id);
    const [proposal] = listClaudeMemory(home, loadNotes(home).notes, { env });
    expect(proposal).toBeDefined();
    rejectProposal(home, proposal!.id, { env });
    expect(listClaudeMemory(home, loadNotes(home).notes, { env })).toEqual([]);
  });

  it("does not let expired notes or long memory bodies hide pending imports", () => {
    const { home, memory, env } = setup();
    const text = "Always preserve complete source memory files.";
    memory("current.md", text);
    const long = "expanded memory detail ".repeat(4096).trim();
    memory("large.md", long);
    const note = createNote(home, { project: "demo", text, staleAfter: "2000-01-01T00:00:00Z" });
    const proposals = listClaudeMemory(home, [note], { env });
    expect(proposals).toHaveLength(2);
    expect(proposals.some(p => p.text === long)).toBe(true);
  });

  it("maps worktree folders through declared paths and imports undeclared projects through transcript cwd", () => {
    const { home, cwd, claude, memory, env } = setup();
    const worktree = join(cwd, ".claude", "worktrees", "topic");
    memory("rule.md", "Always inspect worktree source files.", worktree);
    const elsewhere = join(cwd, "..", "unregistered");
    mkdirSync(elsewhere);
    memory("other.md", "A standalone memory outside the registered project.", elsewhere);
    const transcript = join(claude, "projects", claudeProjectFolder(elsewhere), "session.jsonl");
    writeFileSync(transcript, JSON.stringify({ cwd: elsewhere }) + "\n");
    expect(listClaudeMemory(home, [], { env }).map((p) => p.project).sort()).toEqual(["demo", "unregistered"]);
  });

  it("resolves memory-only folders from real encoded paths without transcripts", () => {
    const { home, cwd, memory, env } = setup();
    const path = join(cwd, "..", "Memory Only Project");
    mkdirSync(path);
    memory("owner.md", "Never discard complete source memory files.", path);
    expect(listClaudeMemory(home, [], { env })).toMatchObject([{ project: "memory-only-project" }]);
    memory("offline.md", "Always preserve archived project rules.", join(cwd, "..", "ArchivedProject"));
    expect(listClaudeMemory(home, [], { env }).map(p => p.project).sort()).toEqual(["archivedproject", "memory-only-project"]);
  });

  it("leaves private notes untouched, ignores private-path inputs/imports and never invokes a judge", async () => {
    const { home, project, memory, env, run } = setup();
    const held = createNote(home, { project: "demo", private: true, text: "Always keep private diagnostic logs locally." });
    const path = join(home, "notes", "demo", "private", `${held.id}.md`);
    const before = readFileSync(path, "utf8");
    const file = memory("private-ref.md", "Remember notes/demo/private/owner.md must remain private.");
    expect(captureUserRules(home, "Remember notes/demo/private/owner.md", project)).toEqual([]);
    expect(listClaudeMemory(home, loadNotes(home).notes, { env })).toEqual([]);
    await run(["review", "--all"]);
    expect(readFileSync(path, "utf8")).toBe(before);
    expect(readFileSync(file, "utf8")).toContain("notes/demo/private/owner.md");
  });
});
