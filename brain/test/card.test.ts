import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CARD_BUDGET, cardCandidates, rankForCard, renderCard } from "../src/card.ts";
import { createNote, loadNotes, saveNote, type Note } from "../src/notes.ts";
import type { Project } from "../src/project.ts";
import { estimateTokens } from "../src/util.ts";
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
    const fresh = renderCard(home, [], project, { now: NOW });
    expect(fresh).toContain("New project? MVP kits: fastapi-mvp, vite-react");
    createNote(home, { text: "we use vite", project: "demo", kind: "decision" });
    const known = renderCard(home, loadNotes(home).notes, project, { now: NOW });
    expect(known).toContain("Kits for this kind of project: vite-react");
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
