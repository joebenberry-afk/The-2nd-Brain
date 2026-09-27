import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CARD_BUDGET, cardCandidates, rankForCard, renderCard } from "../src/card.ts";
import { createNote, loadNotes, saveNote, type Note } from "../src/notes.ts";
import type { Project } from "../src/project.ts";
import { cutToTokens, estimateTokens } from "../src/util.ts";
import { logUse, stats, telemetryPath } from "../src/telemetry.ts";
import { writeAuto, writeWork } from "../src/work.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-card-"));
const project: Project = { id: "demo", tags: ["web"], root: null };
const NOW = new Date("2026-09-27T12:00:00Z");

function kit(home: string, name: string, tags: string[]): void {
  mkdirSync(join(home, "kits", name), { recursive: true });
  const tagLines = tags.length ? `tags:\n${tags.map((t) => `  - ${t}`).join("\n")}\n` : "";
  writeFileSync(join(home, "kits", name, "SKILL.md"), `---\nname: ${name}\ndescription: ${name} kit\n${tagLines}---\n\n# ${name}\n`);
}

describe("card", () => {
  it("is empty when there is nothing to say", () => {
    expect(renderCard(tmp(), [], project, { now: NOW })).toBe("");
  });

  it("pushes only project notes and tag-shared global notes", () => {
    const home = tmp();
    createNote(home, { text: "own fact", project: "demo", kind: "fact" });
    createNote(home, { text: "other project", project: "other" });
    createNote(home, { text: "global untagged", project: "global" });
    createNote(home, { text: "global web", project: "global", tags: ["web"] });
    createNote(home, { text: "global rust", project: "global", tags: ["rust"] });
    const retired = createNote(home, { text: "old", project: "demo" });
    saveNote(home, { ...retired, retired: "2026-09-01T00:00:00Z" });
    const heads = cardCandidates(loadNotes(home).notes, project).map((n) => n.body).sort();
    expect(heads).toEqual(["global web", "own fact"]);
  });

  it("ranks tested gotchas over plain notes and lifts notes relevant to the working state", () => {
    const home = tmp();
    const notes: Note[] = [
      createNote(home, { text: "plain note about lunch", project: "demo" }),
      createNote(home, { text: "tested gotcha about builds", project: "demo", kind: "gotcha", tested: true }),
      createNote(home, { text: "token refresh bug lives in auth middleware", project: "demo", kind: "fact" }),
    ];
    const plain = rankForCard(notes, notes, project, "", NOW).map((n) => n.body);
    expect(plain[0]).toBe("tested gotcha about builds");
    const focused = rankForCard(notes, notes, project, "fixing token refresh in the auth middleware", NOW).map((n) => n.body);
    expect(focused[0]).toBe("token refresh bug lives in auth middleware");
  });

  it("leads with where we left off, stays within budget, and names the tools", () => {
    const home = tmp();
    for (let i = 0; i < 12; i++) {
      createNote(home, { text: `gotcha number ${i} ${"with a long explanation ".repeat(8)}`, project: "demo", kind: "gotcha", tested: true });
    }
    writeWork(home, "demo", "Goal: ship login fix. Next: patch refresh.");
    writeAuto(home, "demo", { edited: ["src/auth.ts"], failure: "`npm test` → TypeError", ask: "fix login" });
    const card = renderCard(home, loadNotes(home).notes, project, { tools: true, now: NOW });
    const lines = card.split("\n");
    expect(lines[0]).toMatch(/^Brain · demo/);
    expect(lines[1]).toMatch(/^Where we left off/);
    expect(card).toContain("- edited: src/auth.ts");
    expect(card).toContain("Known here:");
    expect(card).toContain("brain_state(");
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
    expect(renderCard(home, loadNotes(home).notes, project, { now: NOW })).toContain('brain note "<text>"');
  });

  it("offers every kit on a new project and tag-matched kits otherwise", () => {
    const home = tmp();
    kit(home, "fastapi-mvp", ["python"]);
    kit(home, "vite-react", ["web"]);
    const root = tmp();
    execFileSync("git", ["init", root]);
    for (let i = 0; i < 4; i++) writeFileSync(join(root, "file" + i), "new source");
    const fresh = renderCard(home, [], { ...project, root }, { now: NOW });
    expect(fresh).toContain("fastapi-mvp");
    expect(fresh).toContain("vite-react");
    createNote(home, { text: "we use vite", project: "demo", kind: "decision" });
    const known = renderCard(home, loadNotes(home).notes, project, { now: NOW });
    expect(known).toContain("vite-react");
    expect(known).not.toContain("fastapi-mvp");
  });

  it("mentions waiting proposals", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "inbox"), { recursive: true });
    writeFileSync(
      join(home, "state", "inbox", "p-1.json"),
      JSON.stringify({ id: "p-1", at: "2026-09-27T00:00:00Z", project: "demo", kind: "gotcha", text: "x", errors: [], tested: true, source: "capture", evidence: [] }),
    );
    expect(renderCard(home, [], project, { now: NOW })).toContain("1 proposal waiting");
  });
});


describe("card completeness and scope", () => {
  it("includes the fact after a short title and skips an incomplete combined fact", () => {
    const home = tmp();
    const useful = createNote(home, { text: "Migration ordering\n\nApply migrations in numeric order.", project: "demo" });
    const oversized = createNote(home, { text: "Oversized title\n\n" + "complete instruction ".repeat(120), project: "demo", kind: "gotcha" });
    const card = renderCard(home, [oversized, useful], project);
    expect(card).toContain("Migration ordering — Apply migrations in numeric order.");
    expect(card).not.toContain("Oversized title");
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
  });

  it.each([true, false])("advertises directly callable kits with tools=%s", (tools) => {
    const home = tmp();
    kit(home, "node-ts-cli", ["web"]);
    kit(home, "omp-extension", ["web"]);
    const card = renderCard(home, [], project, { tools });
    const command = tools ? 'brain_recall("kit <name>")' : 'brain recall "kit <name>"';
    expect(card).toContain("Kits: node-ts-cli, omp-extension → " + command);
    expect(card).not.toContain(home);
    expect(card).not.toContain("SKILL.md");
  });

  it("renders long facts completely and skips oversized facts without hiding later facts", () => {
    const home = tmp();
    const long = "OMP compaction must retain the active session plan and insert the continuation after the compaction summary; " + "the complete instruction remains useful only when its final clause is visible.";
    createNote(home, { text: "Oversized " + "instruction ".repeat(200), project: "demo", kind: "gotcha", tested: true });
    createNote(home, { text: long, project: "demo", kind: "fact" });
    const card = execFileSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "card", "--home", home, "--project", "demo"], {
      encoding: "utf8", env: { ...process.env, SECOND_BRAIN_HOME: home },
    }).trimEnd();
    expect(card).toContain(long);
    expect(card).not.toContain("Oversized");
    expect(card).not.toContain("…");
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
  });

  it("bounds pathological kit names without losing useful notes or the footer", () => {
    const home = tmp();
    kit(home, "normal", ["web"]);
    writeFileSync(join(home, "kits", "normal", "SKILL.md"), "---\nname: " + "k".repeat(2000) + "\ndescription: kit\ntags: [web]\n---\nbody");
    const note = createNote(home, { text: "A useful complete fact", project: "demo" });
    const card = renderCard(home, [note], project, { tools: true });
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
    expect(card).toContain(note.body);
    expect(card).toContain("brain_state(");
  });

  it("keeps parent plans and kits out of subagent cards", () => {
    const home = tmp();
    kit(home, "web-kit", ["web"]);
    writeWork(home, "demo", "Goal: parent private plan");
    writeAuto(home, "demo", { edited: ["parent.ts"] });
    const note = createNote(home, { text: "Shared fact", project: "demo" });
    const card = renderCard(home, [note], project, { tools: true, subagent: true });
    expect(card).toContain(note.body);
    expect(card).toContain("brain_recall(");
    expect(card).toContain("brain_note(");
    expect(card).not.toMatch(/parent|Where we left off|brain_state|web-kit/);
  });

  it("ranks the first prompt ahead of unrelated static rank and previous work", () => {
    const home = tmp();
    const unrelated = createNote(home, { text: "Compiler bundler release cache", project: "demo", kind: "gotcha", tested: true });
    const relevant = createNote(home, { text: "Authentication cookie expiration", project: "demo", kind: "fact" });
    writeWork(home, "demo", "Goal: compiler bundler release cache");
    const card = renderCard(home, [unrelated, { ...relevant, at: "2025-01-01T00:00:00Z" }], project, { prompt: "Authentication cookie expiration", now: NOW });
    expect(card.indexOf(relevant.id)).toBeLessThan(card.indexOf(unrelated.id));
    expect(card).toContain(relevant.id);
  });

  it("does not advertise unrelated MVP kits in an established foreign repository", () => {
    const home = tmp();
    const root = tmp();
    execFileSync("git", ["init", root]);
    for (let i = 0; i < 4; i++) writeFileSync(join(root, "file" + i), "existing source");
    execFileSync("git", ["-C", root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "existing project"]);
    kit(home, "python-kit", ["python"]);
    expect(renderCard(home, [], { ...project, root })).toBe("");
    kit(home, "web-kit", ["web"]);
    const card = renderCard(home, [], { ...project, root });
    expect(card).toContain("web-kit");
    expect(card).not.toMatch(/New project|python-kit/);
  });

  it("returns nothing for zero or negative token room", () => {
    expect(cutToTokens("hello", 0)).toBe("");
    expect(cutToTokens("hello", -2)).toBe("");
  });

  it("prefers four complete facts over five clipped facts", () => {
    const home = tmp();
    const notes = Array.from({ length: 5 }, (_, i) => createNote(home, { text: "Fact " + i + ": " + "complete words ".repeat(19).trim(), project: "demo" }));
    const card = renderCard(home, notes, project, { tools: true });
    expect(card.split("\n").filter((line) => line.startsWith("- [note]"))).toHaveLength(4);
    expect(card).not.toContain("…");
    for (const line of card.split("\n").filter((line) => line.startsWith("- [note]"))) {
      expect(notes.some((note) => line.includes(note.body))).toBe(true);
    }
  });

  it("does not mistake packed refs or linked worktrees for unborn repositories", () => {
    const home = tmp();
    const root = tmp();
    execFileSync("git", ["init", root]);
    execFileSync("git", ["-C", root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "existing"]);
    execFileSync("git", ["-C", root, "pack-refs", "--all"]);
    kit(home, "python-kit", ["python"]);
    const linked = join(tmp(), "linked");
    execFileSync("git", ["-C", root, "worktree", "add", "-b", "linked", linked]);
    execFileSync("git", ["-C", root, "pack-refs", "--all"]);
    for (const dir of [root, linked]) {
      for (let i = 0; i < 4; i++) writeFileSync(join(dir, "file" + i), "existing");
      expect(renderCard(home, [], { ...project, root: dir })).toBe("");
    }
  });

});

describe("local usage telemetry", () => {
  it("separates parent and subagent cards and counts measured recall hits", () => {
    const home = tmp();
    const base = { project: "demo", tokens: 12, ms: 1 };
    logUse(home, { ...base, kind: "card" }, NOW);
    logUse(home, { ...base, kind: "card", sub: true }, NOW);
    logUse(home, { ...base, kind: "recall", hits: 2 }, NOW);
    logUse(home, { ...base, kind: "recall", hits: 0 }, NOW);
    logUse(home, { ...base, kind: "recall" }, NOW);
    const s = stats(home, 7, NOW);
    expect(s.cards).toEqual({ main: 1, sub: 1 });
    expect(s.recalls).toEqual({ calls: 3, measured: 2, matched: 1 });
  });

  it("rotates telemetry past 1 MiB by rename, keeping the previous file readable by stats", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const old = JSON.stringify({ at: NOW.toISOString(), kind: "card", project: "old", tokens: 1, ms: 1 }) + "\n";
    const oldRows = Math.ceil(1_100_000 / old.length);
    writeFileSync(telemetryPath(home), old.repeat(oldRows));
    logUse(home, { kind: "note", project: "newest", tokens: 1, ms: 1 }, NOW);
    const rows = readFileSync(telemetryPath(home), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows.map((r) => r.project)).toEqual(["newest"]);
    expect(statSync(join(home, "state", "telemetry.1.jsonl")).size).toBe(old.length * oldRows);
    expect(stats(home, 7, NOW).byKind).toEqual({ card: { count: oldRows, tokens: oldRows }, note: { count: 1, tokens: 1 } });
  });
});

