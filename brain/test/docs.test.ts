import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { projectDocs, readAnchor, docAnswer } from "../src/docs.ts";
import { renderCard } from "../src/card.ts";
import { writeWork } from "../src/work.ts";
import { main } from "../src/cli.ts";
import { estimateTokens } from "../src/util.ts";
import { answerWithHits } from "../src/search.ts";
import { logUse, stats } from "../src/telemetry.ts";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup() {
  const base = mkdtempSync(join(tmpdir(), "brain-docs-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(join(root, "docs"), { recursive: true }); mkdirSync(join(root, ".git"));
  const file = join(root, "docs", "LOOP.md");
  writeFileSync(file, "# Plan\n\n## Goals\nShip anchored memory.\n\n## Resume\nCurrent checkpoint.\n\n## Other\nNot the checkpoint.\n");
  const project = { id: "repo", root, tags: [] };
  return { base, home, root, file, project };
}

it.each(["---", "..."])("skips YAML front matter closed by %s without shifting heading lines", (end) => {
  const { home, root, file, project } = setup();
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md"] } } }));
  writeFileSync(file, '\uFEFF---\r\n# Metadata\r\nstatus: draft\r\n' + end + '\r\n## Goals\r\nShip memory.\r\nResume\r\n---\r\nCheckpoint.\r\n');
  expect(readAnchor(root, "docs/LOOP.md#metadata")).toBeUndefined();
  expect(readAnchor(root, "docs/LOOP.md#status-draft")).toBeUndefined();
  expect(docAnswer(home, project, "LOOP.md")?.text).toBe("docs/LOOP.md: Goals · Resume");
  expect(docAnswer(home, project, "LOOP.md goals")?.text).toBe("docs/LOOP.md › Goals (line 5)");
  expect(readAnchor(root, "docs/LOOP.md#resume")).toBe("Checkpoint.");
  writeFileSync(file, "---\n## Goals\nNo closing delimiter.\n");
  expect(readAnchor(root, "docs/LOOP.md#goals")).toBe("No closing delimiter.");
});

it("counts heading and outline recalls as answered in stats", () => {
  const { home, project } = setup();
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md"] } } }));
  for (const query of ["LOOP.md goals", "LOOP.md"]) {
    const answer = answerWithHits([], query, { home, project });
    logUse(home, { kind: "recall", project: project.id, query, ids: answer.ids, hits: answer.hits, tokens: 1, ms: 0 });
    expect(answer.ids).toEqual(["doc:docs/LOOP.md"]);
  }
  expect(stats(home).recallQueries).toEqual({ logged: 2, silent: 0 });
});

it("reads only explicitly listed Markdown docs, with heading and first-paragraph precision", () => {
  const { home, root, file, project } = setup();
  expect(projectDocs(home, project)).toEqual([]);
  expect(docAnswer(home, project, "LOOP.md goals")?.text).toBeUndefined();
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md", "missing.md", "../outside.md", "code.ts"] } } }));
  expect(projectDocs(home, project)).toEqual([file]);
  expect(docAnswer(home, project, "LOOP.md goals")?.text).toBe("docs/LOOP.md › Goals (line 3)");
  expect(docAnswer(home, project, "goals")?.text).toBe("docs/LOOP.md › Goals (line 3)");
  expect(docAnswer(home, project, "goals unrelated")?.text).toBeUndefined();
  writeFileSync(file, "## Goals\nFirst paragraph.\n\nSecret zebra detail.\n");
  expect(docAnswer(home, project, "secret zebra")?.text).toBeUndefined();
  expect(projectDocs(home, { ...project, root: null })).toEqual([]);
  expect(readAnchor(root, "docs/LOOP.md#absent")).toBeUndefined();
});

it("named registered docs return the best heading or a bounded H2 outline", () => {
  const { home, root, file, project } = setup();
  writeFileSync(file, "# Plan\n## Loop\nCurrent work.\n### Hidden detail\nOther.\n## Current campaign\nShip the checkpoint.\n## Idea ledger\nIdeas.\n## User decisions pending\nOwner choices.\n## Iteration log\nHistory.");
  writeFileSync(join(root, "docs", "OTHER.md"), "## Goals\nGoals for the unrelated project.");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/OTHER.md", "docs/LOOP.md"] } } }));
  const outline = docAnswer(home, project, "lOoP.Md goals")?.text;
  expect(outline).toBe("docs/LOOP.md: Loop · Current campaign · Idea ledger · User decisions pending · Iteration log");
  expect(outline).not.toContain("Hidden detail");
  expect(docAnswer(home, project, "LOOP.md campaign")?.text).toBe("docs/LOOP.md › Current campaign (line 6)");
  expect(docAnswer(home, project, "LOOP.md")?.text).toBe(outline);
  expect(docAnswer(home, project, "MISSING.md goals")?.text).toBeUndefined();
  writeFileSync(file, "## Loop\nCurrent.\n" + Array.from({ length: 20 }, (_, i) => "## Campaign heading number " + i).join("\n"));
  const bounded = docAnswer(home, project, "LOOP.md goals")?.text!;
  expect(bounded).toContain("docs/LOOP.md: Loop · Campaign heading");
  expect(bounded).toContain("…");
  expect(estimateTokens(bounded)).toBeLessThanOrEqual(30);
});

it("outlines a named doc whose file name has '-', '_' or accents, never a look-alike", () => {
  const { home, root, project } = setup();
  writeFileSync(join(root, "docs", "release-plan.md"), "# Plan\n\n## Milestones\nShip.\n\n## Goals\nDash goals.\n");
  writeFileSync(join(root, "docs", "release_plan.md"), "# Plan\n\n## Risks\nNone.\n\n## Goals\nUnderscore goals.\n");
  writeFileSync(join(root, "docs", "Café.md"), "## Menu\nCoffee.\n\n## Hours\nOpen.\n");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/release-plan.md", "docs/release_plan.md", "docs/Café.md", "docs/LOOP.md"] } } }));
  expect(docAnswer(home, project, "release_plan.md")?.text).toBe("docs/release_plan.md: Risks · Goals");
  expect(docAnswer(home, project, "release-plan.md")?.text).toBe("docs/release-plan.md: Milestones · Goals");
  expect(docAnswer(home, project, "docs/release_plan.md goals")?.text).toBe("docs/release_plan.md › Goals (line 6)");
  expect(docAnswer(home, project, "Café.md")?.text).toBe("docs/Café.md: Menu · Hours");
  expect(docAnswer(home, project, "cafe.md")?.text).toBe("docs/Café.md: Menu · Hours");
  expect(docAnswer(home, project, "What is in LOOP.md?")?.text).toBe("docs/LOOP.md: Goals · Resume · Other");
  expect(docAnswer(home, project, "docs/LOOP.md#resume")?.text).toBe("docs/LOOP.md › Resume (line 6)");
});

it("resolves See: anchors written as heading text, in another case, quoted or percent-encoded", () => {
  const { root, file } = setup();
  writeFileSync(file, "# Plan\n\n## Goals\nShip anchored memory.\n\n## Resume\nCurrent checkpoint.\n\n## Current campaign\nShip the checkpoint.\n\n## 6. Kill rules (unchanged from V4, restated)\nKill.\n");
  for (const anchor of ["docs/LOOP.md#Resume", "`docs/LOOP.md#resume`", "\"docs/LOOP.md#resume\""]) expect(readAnchor(root, anchor)).toBe("Current checkpoint.");
  for (const anchor of ["docs/LOOP.md#Current campaign", "docs/LOOP.md#Current%20campaign", "docs/LOOP.md#Current-Campaign"]) expect(readAnchor(root, anchor)).toBe("Ship the checkpoint.");
  for (const anchor of ["docs/LOOP.md#6. Kill rules (unchanged from V4, restated)", "docs/LOOP.md#6-Kill-Rules-unchanged-from-V4-restated", "docs/LOOP.md#6-kill-rules-unchanged-from-v4-restated"]) expect(readAnchor(root, anchor)).toBe("Kill.");
  expect(readAnchor(root, "docs/LOOP.md#absent")).toBeUndefined();
  expect(readAnchor(root, "docs/LOOP.md#%E0%A4%A")).toBeUndefined();
});

it("labels a quoted See: anchor on the card without stray quotes", () => {
  const { home, project } = setup();
  writeWork(home, project.id, "Goal: x\nSee: `docs/LOOP.md#Resume`");
  const card = renderCard(home, [], project);
  expect(card).toContain("docs/LOOP.md › Resume:\nCurrent checkpoint.");
  expect(card).not.toContain("`docs/LOOP.md");
});

it("matches GitHub-style Unicode, punctuation and duplicate heading slugs, ignoring fences", () => {
  const { root, file } = setup();
  writeFileSync(file, "```md\n## Fake\n```\n## Café & Next!\nFirst.\n## Café & Next!\nSecond.\n## End\nOther.\n");
  expect(readAnchor(root, "docs/LOOP.md#café--next")).toBe("First.");
  expect(readAnchor(root, "docs/LOOP.md#café--next-1")).toBe("Second.");
  expect(readAnchor(root, "docs/LOOP.md#fake")).toBeUndefined();
  expect(readAnchor(root, "../outside.md#resume")).toBeUndefined();
  writeFileSync(file, "[Resume](./plan.md) `now`\n---\n\n    keep indentation  \n\n## End\nOther");
  expect(readAnchor(root, "docs/LOOP.md#resume-now")).toBe("    keep indentation  ");
});

it("renders the current anchor and surrounding delta without rewriting stored state", () => {
  const { home, file, project } = setup();
  const saved = writeWork(home, project.id, "Goal: x\nSee: docs/LOOP.md#resume\nNext: verify\nWatch out: approvals");
  const stored = readFileSync(saved.path, "utf8");
  expect(renderCard(home, [], project)).toContain("docs/LOOP.md › Resume:\nCurrent checkpoint.");
  writeFileSync(file, "## Resume\nNew checkpoint.\n");
  const card = renderCard(home, [], project);
  expect(card).toContain("docs/LOOP.md › Resume:\nNew checkpoint.");
  expect(card).toContain("Goal: x"); expect(card).toContain("Next: verify");
  expect(card).not.toContain("Current checkpoint");
  expect(readFileSync(saved.path, "utf8")).toBe(stored);
  const child = renderCard(home, [], project, { subagent: true });
  expect(child).toContain("Watch out: approvals"); expect(child).not.toMatch(/checkpoint|LOOP|Goal:|Next:/);
  writeWork(home, project.id, "Goal: x\nWatch out: approvals\nSee: docs/LOOP.md#resume\nNext: verify");
  expect(renderCard(home, [], project, { subagent: true })).not.toContain("LOOP.md");
  writeFileSync(file, "## Resume\n" + "checkpoint detail ".repeat(300));
  expect(estimateTokens(renderCard(home, [], project))).toBeLessThanOrEqual(400);
  for (const missing of [() => writeFileSync(file, "## Renamed\nNo old text."), () => rmSync(file)]) {
    missing();
    expect(renderCard(home, [], project)).toContain("anchor missing: docs/LOOP.md#resume");
  }
  expect(renderCard(home, [], { ...project, root: null })).toContain("anchor missing: docs/LOOP.md#resume");
});

it("CLI adds and lists docs, deduplicates, preserves config and refuses invalid paths", async () => {
  const { home, root, file } = setup();
  writeFileSync(join(home, "projects.json"), JSON.stringify({ extra: true, projects: { repo: { tags: ["node"], custom: 42 } } }));
  const run = async (...args: string[]) => {
    const out: string[] = [], err: string[] = [];
    const code = await main(args, { cwd: root, env: { SECOND_BRAIN_HOME: home }, stdin: () => "", out: s => out.push(s), err: s => err.push(s) });
    return { code, out: out.join("\n"), err: err.join("\n") };
  };
  expect((await run("project", "docs", "add", "docs/LOOP.md")).code).toBe(0);
  expect((await run("project", "docs", "add", "docs/LOOP.md")).code).toBe(0);
  expect((await run("project", "docs", "list")).out).toBe("docs/LOOP.md");
  expect(JSON.parse(readFileSync(join(home, "projects.json"), "utf8"))).toEqual({ extra: true, projects: { repo: { tags: ["node"], custom: 42, docs: ["docs/LOOP.md"] } } });
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["docs/LOOP.md", "gone.md"] } } }));
  expect((await run("project", "docs", "list")).out).toBe(`docs/LOOP.md\ngone.md (missing under ${root})`);
  writeFileSync(join(root, "code.ts"), "code");
  for (const path of [file, "../outside.md", "code.ts", "missing.md", "C:\\outside.md", "/outside.md"]) {
    expect((await run("project", "docs", "add", path)).code).not.toBe(0);
  }
});

it("refuses symlink escapes and leaves malformed registration data untouched", async () => {
  const { base, home, root, project } = setup();
  const outside = join(base, "outside"); mkdirSync(outside);
  writeFileSync(join(outside, "PLAN.md"), "## Resume\nOutside text.");
  symlinkSync(outside, join(root, "linked"), "junction");
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { repo: { docs: ["linked/PLAN.md"] } } }));
  expect(projectDocs(home, project)).toEqual([]);
  expect(readAnchor(root, "linked/PLAN.md#resume")).toBeUndefined();
  const io = { cwd: root, env: { SECOND_BRAIN_HOME: home }, stdin: () => "", out: () => {}, err: () => {} };
  expect(await main(["project", "docs", "add", "linked/PLAN.md"], io)).not.toBe(0);
  const malformed = '{"projects":{"repo":{"docs":"wrong"}}}';
  writeFileSync(join(home, "projects.json"), malformed);
  expect(await main(["project", "docs", "add", "docs/LOOP.md"], io)).not.toBe(0);
  expect(readFileSync(join(home, "projects.json"), "utf8")).toBe(malformed);
});
