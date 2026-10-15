import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CARD_BUDGET, cardCandidates, LEAN_LINE, rankForCard, renderCard } from "../src/card.ts";
import { createNote, loadNotes, saveNote, type Note } from "../src/notes.ts";
import type { Project } from "../src/project.ts";
import { cutToTokens, estimateTokens } from "../src/util.ts";
import { logUse, rotateTelemetry, saveToolSchemas, stats, telemetryPath, toolSchemaUse } from "../src/telemetry.ts";
import { writeAuto, writeWork } from "../src/work.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-card-"));
const project: Project = { id: "demo", tags: ["web"], root: null };
const NOW = new Date("2026-09-27T12:00:00Z");

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
    const plain = rankForCard(notes, project, "", NOW, home).map((n) => n.body);
    expect(plain[0]).toBe("tested gotcha about builds");
    const focused = rankForCard(notes, project, "fixing token refresh in the auth middleware", NOW, home).map((n) => n.body);
    expect(focused[0]).toBe("token refresh bug lives in auth middleware");
  });

  it("demotes missing-file evidence without hiding notes or treating Brain-home evidence as missing", () => {
    const home = tmp();
    const root = tmp();
    writeFileSync(join(home, "current.md"), "evidence");
    writeFileSync(join(root, "source.ts"), "evidence");
    const stale = createNote(home, { text: "Missing gotcha", kind: "gotcha", project: "demo", evidence: ["missing.ts"] });
    const current = createNote(home, { text: "Current fact", kind: "fact", project: "demo", evidence: ["current.md"] });
    const source = createNote(home, { text: "Source fact", kind: "fact", project: "demo", evidence: ["source.ts"] });
    const card = renderCard(home, [stale, current, source], { ...project, root }, { now: NOW });
    expect(card).toContain(stale.id);
    expect(card).toContain(current.id);
    expect(card).toContain(source.id);
    expect(card.indexOf(current.id)).toBeLessThan(card.indexOf(stale.id));
    expect(card.indexOf(source.id)).toBeLessThan(card.indexOf(stale.id));
  });

  it("does not amplify stale work relevance when recall moves a weaker live hit first", () => {
    const home = tmp();
    const stale = createNote(home, { text: "Authentication cookie token refresh middleware", project: "demo", kind: "fact", evidence: ["missing.ts"] });
    const live = createNote(home, { text: "Authentication configuration", project: "demo", kind: "gotcha", tested: true });
    const ranked = rankForCard([stale, live], { ...project, root: home }, stale.body, NOW, home);
    expect(rankForCard([stale, live], project, stale.body, NOW, home).map(note => note.id)).toEqual([stale.id, live.id]);
    expect(ranked.map(note => note.id)).toEqual([live.id, stale.id]);
  });

  it("keeps an expired note behind a live one even when only the expired one matches the prompt", () => {
    const home = tmp();
    const stale = createNote(home, { text: "Authentication cookie token refresh middleware", project: "demo", kind: "fact", staleAfter: "2000-01-01" });
    const live = createNote(home, { text: "Authentication configuration", project: "demo", kind: "gotcha", tested: true });
    const ranked = rankForCard([stale, live], project, "", NOW, home, "cookie token refresh middleware");
    expect(ranked.map(note => note.id)).toEqual([live.id, stale.id]);
  });

  it("leads with where we left off, stays within budget, and leaves tool guidance to resident tools", () => {
    const home = tmp();
    for (let i = 0; i < 12; i++) {
      createNote(home, { text: `gotcha number ${i} ${"with a long explanation ".repeat(8)}`, project: "demo", kind: "gotcha", tested: true });
    }
    writeWork(home, "demo", "Goal: ship login fix. Next: patch refresh.");
    writeAuto(home, "demo", { edited: ["src/auth.ts"], ask: "fix login" });
    const card = renderCard(home, loadNotes(home).notes, project, { tools: true, now: NOW });
    const lines = card.split("\n");
    expect(lines[0]).toMatch(/^Brain · demo/);
    expect(lines[1]).toMatch(/^Where we left off/);
    expect(card).toContain("- edited: src/auth.ts");
    expect(card).toContain("Known here:");
    expect(card).not.toMatch(/brain_recall\(|brain_note\(|brain_state\(/);
    expect(lines.at(-1)).toBe(LEAN_LINE);
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
    expect(renderCard(home, loadNotes(home).notes, project, { now: NOW })).toContain('brain note "<text>"');
  });

  it("keeps owner-facing proposal counts out of the card", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "inbox"), { recursive: true });
    writeFileSync(
      join(home, "state", "inbox", "p-1.json"),
      JSON.stringify({ id: "p-1", at: "2026-09-27T00:00:00Z", project: "demo", kind: "gotcha", text: "x", errors: [], tested: true, source: "capture", evidence: [] }),
    );
    expect(renderCard(home, [], project, { now: NOW })).toBe("");
    const note = createNote(home, { text: "Shared fact", project: "demo" });
    expect(renderCard(home, [note], project, { now: NOW })).not.toMatch(/proposal|brain review/);
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

  it("renders long facts completely and skips oversized facts without hiding later facts", () => {
    const home = tmp();
    const long = "OMP compaction must retain the active session plan and insert the continuation after the compaction summary; " + "the complete instruction remains useful only when its final clause is visible.";
    createNote(home, { text: "Oversized " + "instruction ".repeat(200), project: "demo", kind: "gotcha", tested: true });
    createNote(home, { text: long, project: "demo", kind: "fact" });
    const card = execFileSync(process.execPath, [join(import.meta.dirname, "..", "bin", "brain.mjs"), "card", "--home", home, "--project", "demo"], {
      encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home },
    }).trimEnd();
    expect(card).toContain(long);
    expect(card).not.toContain("Oversized");
    expect(card).not.toContain("…");
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
  });

  it("keeps parent plans out of subagent cards", () => {
    const home = tmp();
    writeWork(home, "demo", "Goal: parent private plan");
    writeAuto(home, "demo", { edited: ["parent.ts"] });
    const note = createNote(home, { text: "Shared fact", project: "demo" });
    const card = renderCard(home, [note], project, { tools: true, subagent: true });
    expect(card).toContain(note.body);
    expect(card).not.toContain("brain_recall(");
    expect(card).not.toContain("brain_note(");
    expect(card).not.toMatch(/parent|Where we left off|brain_state/);
    expect(renderCard(home, [note], project, { subagent: true })).toContain('brain recall "<query>"');
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

  it("shares only bounded parent warnings with children and ranks notes using them", () => {
    const home = tmp();
    writeWork(home, "demo", "Goal: compiler bundler release. Next: ship compiler. Watch out: authentication cookie expiration. Done: compiler compiled.");
    writeAuto(home, "demo", { ask: "parent request", edited: ["parent.ts"] });
    const unrelated = createNote(home, { text: "Compiler bundler release", project: "demo", kind: "gotcha", tested: true });
    const warning = createNote(home, { text: "Authentication cookie expiration", project: "demo", kind: "fact" });
    const card = renderCard(home, [unrelated, warning], project, { subagent: true, tools: true, now: NOW });
    expect(card).toContain("Watch out: authentication cookie expiration");
    expect(card).not.toMatch(/Goal:|Next:|Done:|parent request|parent.ts|Where we left off/);
    expect(card.indexOf(warning.id)).toBeLessThan(card.indexOf(unrelated.id));
    writeWork(home, "demo", "Watch out: " + "keep authentication isolated ".repeat(15));
    const long = renderCard(home, [], project, { subagent: true, tools: true });
    const line = long.split("\n").find(line => line.startsWith("Watch out:"))!;
    expect(line).toContain("keep authentication isolated");
    expect(estimateTokens(line)).toBeLessThanOrEqual(40);
  });

  it("returns nothing for zero or negative token room", () => {
    expect(cutToTokens("hello", 0)).toBe("");
    expect(cutToTokens("hello", -2)).toBe("");
  });

  it("cuts on a word end, not mid-word, unless that would lose too much", () => {
    const ask = "when these agents are done, I want you to pause development so i can upload the latest 2nd brain build";
    expect(cutToTokens(ask, 24)).toBe("when these agents are done, I want you to pause development so i can upload the latest 2nd…");
    expect(cutToTokens("x".repeat(30) + " " + "y".repeat(60), 10)).toBe("x".repeat(30) + "…");
    expect(cutToTokens("z".repeat(100), 10)).toBe("z".repeat(39) + "…");
  });

  it("prefers fewer complete facts over five clipped facts", () => {
    const home = tmp();
    const notes = Array.from({ length: 5 }, (_, i) => createNote(home, { text: "Fact " + i + ": " + "complete words ".repeat(19).trim(), project: "demo" }));
    const card = renderCard(home, notes, project, { tools: true });
    const shown = card.split("\n").filter((line) => line.startsWith("- [note]"));
    expect(shown.length).toBeGreaterThanOrEqual(3);
    expect(shown.length).toBeLessThan(5);
    expect(card).not.toContain("…");
    expect(card.split("\n").at(-1)).toBe(LEAN_LINE);
    expect(estimateTokens(card)).toBeLessThanOrEqual(CARD_BUDGET);
    for (const line of card.split("\n").filter((line) => line.startsWith("- [note]"))) {
      expect(notes.some((note) => line.includes(note.body))).toBe(true);
    }
  });
});

describe("recurring known fix", () => {
  it("keeps paused fixes out of recurring lines until their note is edited", () => {
    const home = tmp();
    const fix = createNote(home, { text: "Repair the runtime", project: "global", tested: true, errors: ["runtime mismatch"] });
    utimesSync(fix.path, NOW, NOW);
    for (const session of ["a", "b", "c", "d"]) {
      logUse(home, { kind: "fix", id: fix.id, project: "demo", session, tokens: 0, ms: 0 }, NOW);
      logUse(home, { kind: "fixout", id: fix.id, project: "demo", outcome: "missed", tokens: 0, ms: 0 }, NOW);
    }
    const card = () => renderCard(home, loadNotes(home).notes, project, { now: NOW });
    expect(card()).not.toContain("Often hit lately");
    const edited = new Date(NOW.getTime() + 2000);
    utimesSync(fix.path, edited, edited);
    expect(card()).toContain(`4× [note, tested] Repair the runtime (${fix.id})`);
  });

  it("is said up front once it fired in 3 sessions of the same role this week", () => {
    const home = tmp();
    const fix = createNote(home, { text: "OMP edits start with [path#tag] then PUT rows", project: "global", kind: "gotcha", tested: true, errors: ["input must begin with"] });
    const other = createNote(home, { text: "Unrelated tested fact", project: "demo", kind: "fact", tested: true });
    const fire = (session: string, sub: boolean) => logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session, sub, id: fix.id }, NOW);
    fire("a", true);
    fire("a", true);
    fire("b", true);
    fire("m1", false);
    const card = (subagent: boolean) => renderCard(home, loadNotes(home).notes, project, { tools: true, subagent, now: NOW });
    expect(card(true)).not.toContain("Often hit lately");
    fire("c", true);
    const child = card(true);
    expect(child).toContain("Often hit lately (sessions this week):\n- 3× [gotcha, tested]");
    expect(child.split(fix.id)).toHaveLength(2);
    expect(child.indexOf(fix.id)).toBeLessThan(child.indexOf(other.id));
    expect(estimateTokens(child)).toBeLessThanOrEqual(400);
    // Main sessions never made this mistake: their card stays as it was.
    expect(card(false)).not.toContain("Often hit lately");
    // A second recurring fix gets its own line; a third never does.
    for (const [i, text] of ["Second recurring fix", "Third recurring fix"].entries()) {
      const extra = createNote(home, { text, project: "global", kind: "gotcha", tested: true, errors: [`error number ${i}`] });
      for (const s of ["x", "y", "z"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, sub: true, id: extra.id }, NOW);
    }
    const two = card(true);
    expect(two.match(/^- 3× /gm)).toHaveLength(2);
    expect(estimateTokens(two)).toBeLessThanOrEqual(400);
  });

  it("counts only fires from the same host, so an OMP-only mistake stays off Claude Code cards", () => {
    const home = tmp();
    const fix = createNote(home, { text: "OMP edit anchors come from displayed lines", project: "global", kind: "gotcha", tested: true, errors: ["never displayed"] });
    const card = (host?: "omp" | "claude-code") => renderCard(home, loadNotes(home).notes, project, { host, now: NOW });
    // `brain fix` rows (via "cli") belong to neither host.
    for (const s of ["a", "b", "c"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, sub: false, via: "cli", id: fix.id }, NOW);
    expect(card("omp")).not.toContain("Often hit lately");
    expect(card("claude-code")).not.toContain("Often hit lately");
    for (const s of ["a", "b", "c"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, sub: false, id: fix.id }, NOW);
    expect(card("omp")).toContain("Often hit lately");
    expect(card()).toContain("Often hit lately");
    expect(card("claude-code")).not.toContain("Often hit lately");
    for (const s of ["x", "y", "z"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, sub: false, via: "hook", id: fix.id }, NOW);
    expect(card("claude-code")).toContain(`3× [gotcha, tested]`);
    expect(card("omp")).toContain(`3× [gotcha, tested]`);
    // A note scoped to one host is never said up front on the other host's card.
    saveNote(home, { ...fix, host: "omp" });
    expect(card("claude-code")).not.toContain("Often hit lately");
    expect(card("omp")).toContain(`3× [gotcha, tested]`);
  });

  it("keeps a recurring fix too long for its parent slot as an ordinary note", () => {
    const home = tmp();
    const long = createNote(home, { text: "Long project gotcha " + "with detail ".repeat(60), project: "demo", kind: "gotcha", tested: true, errors: ["long failure"] });
    const before = renderCard(home, loadNotes(home).notes, project, { tools: true, now: NOW });
    expect(before).toContain(long.id);
    for (const s of ["a", "b", "c"]) logUse(home, { kind: "fix", project: "demo", tokens: 1, ms: 1, session: s, sub: false, id: long.id }, NOW);
    const after = renderCard(home, loadNotes(home).notes, project, { tools: true, now: NOW });
    expect(after).not.toContain("Often hit lately");
    expect(after).toContain(long.id);
  });
});

describe("local usage telemetry", () => {
  it("counts logged recall queries and fix outcomes across rotation, respecting build and time filters", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const row = (extra: object) => JSON.stringify({ at: NOW.toISOString(), project: "demo", tokens: 0, ms: 0, v: "t00002", ...extra });
    writeFileSync(join(home, "state", "telemetry.1.jsonl"), [
      row({ kind: "recall", query: "logged hit", ids: ["n-fix"] }),
      row({ kind: "fix", id: "n-fix", session: "one" }),
      row({ kind: "fixout", id: "n-fix", outcome: "helped" }),
      row({ kind: "fixout", id: "n-fix", outcome: "missed", v: "t00001" }),
      row({ kind: "recall", query: "old", ids: [], at: "2020-01-01T00:00:00Z" }),
    ].join("\n") + "\n");
    writeFileSync(telemetryPath(home), [
      row({ kind: "recall", query: "silent", ids: [] }),
      row({ kind: "recall", hits: 0 }),
      row({ kind: "recall", query: "malformed", ids: [null] }),
      row({ kind: "fix", id: "n-fix", session: "one" }),
      row({ kind: "fixout", id: "n-fix", outcome: "missed" }),
      row({ kind: "fixout", id: "n-fix", outcome: "invalid" }),
      row({ kind: "fixout", id: "n-fix", outcome: "missed", at: "2020-01-01T00:00:00Z" }),
    ].join("\n") + "\n");
    expect(stats(home, 7, NOW)).toMatchObject({ recallQueries: { logged: 2, silent: 1 }, fixOutcomes: [{ id: "n-fix", firings: 2, helped: 1, missed: 1 }] });
    expect(stats(home, 7, NOW, { allBuilds: true }).fixOutcomes).toEqual([{ id: "n-fix", firings: 2, helped: 1, missed: 2 }]);
  });

  it("an old session appending after a new one never turns stats back to the old build", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const row = (v: string, kind: string) => JSON.stringify({ at: NOW.toISOString(), project: "demo", tokens: 1, ms: 1, session: "s-" + v, v, kind });
    writeFileSync(telemetryPath(home), [row("t00002", "recall"), row("t00001", "card")].join("\n") + "\n");
    expect(stats(home, 7, NOW)).toMatchObject({ olderBuildRows: 1, recalls: { calls: 1 }, cards: { main: 0 } });
  });

  it("reads the newest build by default and counts each fix once per session", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const row = (v: string, extra: object) => JSON.stringify({ at: NOW.toISOString(), project: "demo", tokens: 1, ms: 1, v, ...extra });
    writeFileSync(telemetryPath(home), [
      row("t00001", { kind: "card", session: "old-child" }),
      row("t00002", { kind: "fix", session: "a", id: "n-edit" }),
      row("t00002", { kind: "fix", session: "a", id: "n-edit" }),
      row("t00002", { kind: "fix", session: "b", id: "n-edit" }),
      row("t00002", { kind: "fix", session: "b", id: "n-read" }),
    ].join("\n") + "\n");
    const s = stats(home, 7, NOW);
    expect(s.olderBuildRows).toBe(1);
    expect(s.cards.main).toBe(0);
    expect(s.fixes).toEqual([{ id: "n-edit", sessions: 2 }, { id: "n-read", sessions: 1 }]);
    expect(stats(home, 7, NOW, { allBuilds: true })).toMatchObject({ olderBuildRows: 0, cards: { main: 1, sub: 0 } });
  });

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

  it("counts sessions that used brain tools per role; a subagent is known by any sub row", () => {
    const home = tmp();
    const base = { project: "demo", tokens: 1, ms: 1 };
    logUse(home, { ...base, kind: "card", session: "idle-main" }, NOW);
    logUse(home, { ...base, kind: "card", session: "busy-main" }, NOW);
    logUse(home, { ...base, kind: "state", session: "busy-main" }, NOW);
    logUse(home, { ...base, kind: "fix", session: "fixed-main" }, NOW);
    logUse(home, { ...base, kind: "card", session: "child", sub: true }, NOW);
    logUse(home, { ...base, kind: "note", session: "child" }, NOW);
    // A shell `brain recall` with BRAIN_SESSION set cannot say whether it ran in a child.
    logUse(home, { ...base, kind: "recall", session: "cli-only", via: "cli" }, NOW);
    expect(stats(home, 7, NOW).toolUse).toEqual({ main: { sessions: 3, using: 1 }, sub: { sessions: 1, using: 1 } });
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
    expect(stats(home, 7, NOW, { allBuilds: true }).byKind).toEqual({ card: { count: oldRows, tokens: oldRows }, note: { count: 1, tokens: 1 } });
  });
});


describe("telemetry session roles and rotation", () => {
  const raw = (home: string, rows: object[]) => {
    mkdirSync(join(home, "state"), { recursive: true });
    writeFileSync(telemetryPath(home), rows.map((r) => JSON.stringify({ at: NOW.toISOString(), project: "demo", tokens: 1, ms: 1, ...r })).join("\n") + "\n");
  };

  it("takes a session's role from rows of every build, but counts only newest-build use", () => {
    const home = tmp();
    raw(home, [
      { session: "S", via: "hook", sub: false, kind: "card", v: "t00001" },
      { session: "S", via: "cli", kind: "recall", v: "t00002" },
    ]);
    expect(stats(home, 7, NOW).toolUse.main).toEqual({ sessions: 1, using: 1 });
  });

  it("keeps a session with a main card main when an older build logged its child's fixes under it", () => {
    const home = tmp();
    raw(home, [
      { session: "S", via: "hook", sub: true, kind: "fix", id: "n-a", v: "t00001" },
      { session: "S", via: "hook", sub: false, kind: "card", v: "t00002" },
      { session: "S", via: "cli", kind: "recall", v: "t00002" },
    ]);
    expect(stats(home, 7, NOW).toolUse).toEqual({ main: { sessions: 1, using: 1 }, sub: { sessions: 0, using: 0 } });
  });

  it("does not count a `brain card` preview as a delivered card or a known session", () => {
    const home = tmp();
    const base = { project: "demo", tokens: 1, ms: 1 };
    logUse(home, { ...base, kind: "card", session: "main" }, NOW);
    logUse(home, { ...base, kind: "card", session: "preview", via: "cli" }, NOW);
    const s = stats(home, 7, NOW);
    expect(s.cards.main).toBe(1);
    expect(s.toolUse.main.sessions).toBe(1);
    expect(s.byKind.card).toEqual({ count: 2, tokens: 2 });
  });

  it("leaves Claude Code children, seen only through hook rows, out of the sub rate", () => {
    const home = tmp();
    raw(home, [
      { session: "omp-child", sub: true, kind: "card" },
      { session: "omp-child", sub: true, via: "tool", kind: "recall" },
      { session: "P:agent:x", sub: true, via: "hook", kind: "fix", id: "n-a" },
      { session: "P:agent:x", sub: true, via: "hook", kind: "fix", id: "n-b" },
    ]);
    expect(stats(home, 7, NOW).toolUse.sub).toEqual({ sessions: 1, using: 1 });
  });

  it("a rotation that lost the race hands the fresh file back instead of replacing the full one", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const rotated = join(home, "state", "telemetry.1.jsonl");
    writeFileSync(rotated, "x".repeat(1_100_000) + "\n");
    const row = JSON.stringify({ at: NOW.toISOString(), kind: "note", project: "demo", tokens: 1, ms: 1 }) + "\n";
    writeFileSync(telemetryPath(home), row);
    rotateTelemetry(home, 1_048_576);
    expect(statSync(rotated).size).toBeGreaterThanOrEqual(1_048_576);
    expect(readFileSync(telemetryPath(home), "utf8")).toBe(row);
    expect(readdirSync(join(home, "state")).filter((name) => name.endsWith(".rot"))).toEqual([]);
  });

  it("lists active tool schemas not called inside the window, largest first", () => {
    const home = tmp();
    expect(toolSchemaUse(home, 7, NOW)).toBeNull();
    saveToolSchemas(home, [
      { name: "read", source: "builtin", tokens: 300 },
      { name: "mcp__small", source: "mcp", tokens: 100 },
      { name: "mcp__big", source: "mcp", tokens: 900 },
    ], NOW);
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const event = (tool: string, at: string) => JSON.stringify({ v: 1, at, session: "s", cwd: home, tool, ok: true });
    // mcp__big was last called 8 days ago: outside a 7-day window, inside a 30-day one.
    writeFileSync(join(home, "state", "events", "s.jsonl"), [event("read", "2026-09-27T11:00:00Z"), event("mcp__big", "2026-09-19T12:00:00Z")].join("\n") + "\n");
    expect(toolSchemaUse(home, 7, NOW)).toEqual({ at: NOW.toISOString().replace(/\.\d+Z$/, "Z"), tools: 3, tokens: 1300, system: [], unused: [
      { name: "mcp__big", source: "mcp", tokens: 900 },
      { name: "mcp__small", source: "mcp", tokens: 100 },
    ] });
    expect(toolSchemaUse(home, 30, NOW)?.unused.map(tool => tool.name)).toEqual(["mcp__small"]);
  });

  it("keeps system prompt block sizes beside the tool schemas; older snapshots read as none", () => {
    const home = tmp();
    saveToolSchemas(home, [], NOW, [1200, 40, 3500]);
    expect(toolSchemaUse(home, 7, NOW)?.system).toEqual([1200, 40, 3500]);
    writeFileSync(join(home, "state", "tool-schemas-omp.json"), JSON.stringify({ at: "2026-10-01T00:00:00Z", tools: [] }) + "\n");
    expect(toolSchemaUse(home, 7, NOW)?.system).toEqual([]);
  });

  it("rotates a full file to telemetry.1.jsonl", () => {
    const home = tmp();
    mkdirSync(join(home, "state"), { recursive: true });
    const full = "y".repeat(1_100_000) + "\n";
    writeFileSync(telemetryPath(home), full);
    rotateTelemetry(home, 100);
    expect(readFileSync(join(home, "state", "telemetry.1.jsonl"), "utf8")).toBe(full);
    expect(existsSync(telemetryPath(home)) ? readFileSync(telemetryPath(home), "utf8") : "").toBe("");
    expect(readdirSync(join(home, "state")).filter((name) => name.endsWith(".rot"))).toEqual([]);
  });

  it("keeps the rows readable when telemetry.1.jsonl cannot be replaced", () => {
    const home = tmp();
    // Renaming a file over a directory fails everywhere: EPERM on Windows, EISDIR on Linux.
    mkdirSync(join(home, "state", "telemetry.1.jsonl"), { recursive: true });
    const full = "y".repeat(1_100_000) + "\n";
    writeFileSync(telemetryPath(home), full);
    rotateTelemetry(home, 100);
    expect(readFileSync(telemetryPath(home), "utf8")).toBe(full);
    expect(readdirSync(join(home, "state")).filter((name) => name.endsWith(".rot"))).toEqual([]);
    // Each row tries once: a rotated file that stays held must not stall every card, fix and call.
    const started = performance.now();
    for (let i = 0; i < 3; i++) logUse(home, { kind: "card", project: "demo", tokens: 1, ms: 1 });
    expect(performance.now() - started).toBeLessThan(300);
    expect(readFileSync(telemetryPath(home), "utf8").startsWith(full)).toBe(true);
  });
});
