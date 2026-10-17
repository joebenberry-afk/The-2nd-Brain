import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { AUTO_BUDGET, WORK_BUDGET, formatAuto, readWork, stateSaved, workText, workPath, writeAuto, writeWork } from "../src/work.ts";
import * as util from "../src/util.ts";
import { estimateTokens } from "../src/util.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-work-"));

describe("work", () => {
  it.each([
    ["2026-10-16T00:00:00Z", false], ["2026-10-17T00:00:00Z", true],
    ["2026-10-18T00:00:00Z", true], ["", true], ["invalid", true],
  ])("suppresses only older automatic observations (%s)", (autoAt, shown) => {
    const text = workText({ project: "p", path: "", at: "2026-10-17T00:00:00Z", text: "Goal: current", autoAt, auto: "- last ask: old ask" });
    expect(text.includes("old ask")).toBe(shown);
  });

  it("a new saved plan supersedes old local asks, while auto-only and unknown plans remain readable", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "work"), { recursive: true });
    writeFileSync(join(home, "state", "work", "p.auto.md"), "---\nat: 2000-01-01T00:00:00Z\n---\n\n- last ask: old ask\n");
    expect(workText(readWork(home, "p"))).toContain("old ask");
    expect(workText(writeWork(home, "p", "Goal: current"))).not.toContain("old ask");
    expect(workText({ ...readWork(home, "p")!, at: "invalid" })).toContain("old ask");
  });
  it("workPath: <home>/work/<project>.md", () => {
    const path = workPath("/tmp/brain", "myproject");
    expect(path).toBe(join("/tmp/brain", "work", "myproject.md"));
  });

  it("readWork: null when missing", () => {
    const home = tmp();
    const work = readWork(home, "missing");
    expect(work).toBeNull();
  });

  it("readWork: a file without frontmatter is the plan, and an auto refresh keeps it", () => {
    const home = tmp();
    mkdirSync(join(home, "work"), { recursive: true });
    writeFileSync(join(home, "work", "p.md"), "Goal: ship the sync fix\nNext: run the installer test");
    expect(readWork(home, "p")).toMatchObject({ text: "Goal: ship the sync fix\nNext: run the installer test", auto: "", at: "" });
    writeAuto(home, "p", { ask: "continue" });
    expect(readWork(home, "p")).toMatchObject({ text: "Goal: ship the sync fix\nNext: run the installer test", auto: "- last ask: continue" });
    expect(readWork(home, "nothing-here")).toBeNull();
  });

  it("readWork: a plan line that is exactly '## auto' stays in the plan", () => {
    const home = tmp();
    writeWork(home, "p", "Goal: fix the parser\n## auto\nNext: tests");
    expect(readWork(home, "p")?.text).toBe("Goal: fix the parser\n## auto\nNext: tests");
    writeAuto(home, "p", { ask: "go on" });
    expect(readWork(home, "p")).toMatchObject({ text: "Goal: fix the parser\n## auto\nNext: tests", auto: "- last ask: go on" });
  });

  it("writeWork: creates file with trimmed text, cuts to WORK_BUDGET", () => {
    const home = tmp();
    const text = "  Goal: foo\n\nDetails: bar  ";
    const work = writeWork(home, "p1", text);

    expect(work.project).toBe("p1");
    expect(work.text).toBe("Goal: foo\n\nDetails: bar");
    expect(estimateTokens(work.text)).toBeLessThanOrEqual(WORK_BUDGET);

    // File exists and has the content
    const content = readFileSync(work.path, "utf8");
    expect(content).toContain("Goal: foo");
  });

  it("writeWork: cuts to token budget", () => {
    const home = tmp();
    const longText = "x".repeat(WORK_BUDGET * 5);
    const work = writeWork(home, "p1", longText);
    expect(estimateTokens(work.text)).toBeLessThanOrEqual(WORK_BUDGET);
  });

  it("writeWork: a long plan keeps its See: line whole, and the reply says it was cut", () => {
    const home = tmp();
    const see = "See: docs/intake/2026-09-28-plan-v5-anchored-memory.md#83-question-phrased-recall-queries-rejected-2026-09-28";
    const text = `Goal: ${"ship the anchored memory work ".repeat(6)}\nNext: ${"run the gate and the agentbench control ".repeat(4)}\nDone: ${"landed the judge threshold change ".repeat(7)}\n${see}`;
    expect(text.length).toBeGreaterThan(700);
    const work = writeWork(home, "p", text);
    expect(work.text.split("\n")).toContain(see);
    expect(work.text).toMatch(/^Goal: ship/);
    expect(estimateTokens(work.text)).toBeLessThanOrEqual(WORK_BUDGET);
    expect(stateSaved(work)).toMatch(new RegExp(`^state saved \\(\\d+ tokens\\); cut from ${text.length} chars to fit ${WORK_BUDGET} tokens`));
    expect(stateSaved(writeWork(home, "p", "Goal: short\n" + see))).toMatch(/^state saved \(\d+ tokens\)$/);
  });

  it("stateSaved: a section named without its file asks for a See: anchor; a path or See: line does not", () => {
    const home = tmp();
    // The 2026-10-05 state that cost the next session two turns hunting for the right plan.
    expect(stateSaved(writeWork(home, "p", "Goal: token efficiency. Done: rollover default 150k; plan §8.8. Next: watch the hint."))).toContain('"§8.8" names no file');
    expect(stateSaved(writeWork(home, "p", "Goal: finish section 4.2 of the plan"))).toContain('"section 4.2" names no file');
    expect(stateSaved(writeWork(home, "p", "Goal: x. Next: plan §8.8\nSee: docs/plan.md#88-token-efficiency"))).toMatch(/^state saved \(\d+ tokens\)$/);
    expect(stateSaved(writeWork(home, "p", "Next: docs/intake/plan-v5.md §8.8"))).toMatch(/^state saved \(\d+ tokens\)$/);
    expect(stateSaved(writeWork(home, "p", "Goal: bump to 8.8 and ship"))).toMatch(/^state saved \(\d+ tokens\)$/);
  });

  it("stateSaved: a See: anchor naming no heading is reported at save; a section number resolves", () => {
    const home = tmp(), root = tmp();
    // The 2026-10-07 BasicUpscaler state: "See: Frame Gen.md#17" rendered "anchor missing" next session.
    writeFileSync(join(root, "Frame Gen.md"), "# Frame gen\n\n## 9. Research\n\n### 9.1 Public material\n\nnine-one text\n\n## 17. Lossless Scaling scoreboard (FG-86)\n\nW/L/D table\n");
    const project = { id: "p", tags: [], root };
    for (const see of ["Frame Gen.md#17", "Frame Gen.md#§17", "Frame Gen.md#9.1", "Frame Gen.md#17-lossless-scaling-scoreboard-fg-86"]) {
      const work = writeWork(home, "p", `Goal: beat LSFG\nSee: ${see}`);
      expect(stateSaved(work, home, project)).toMatch(/^state saved \(\d+ tokens\)$/);
      expect(workText(work, root)).not.toContain("anchor missing");
    }
    expect(workText(writeWork(home, "p", "Goal: x\nSee: Frame Gen.md#9.1"), root)).toContain("nine-one text");
    // "#1" is no prefix of "17" or "9.1": no heading is numbered 1 here.
    for (const see of ["Frame Gen.md#1", "Frame Gen.md#scoreboard", "Missing.md#17"]) {
      expect(stateSaved(writeWork(home, "p", `Goal: x\nSee: ${see}`), home, project)).toContain(`anchor missing: ${see}`);
    }
  });

  it("an anchor written inside a sentence is moved onto its own line, rendered and checked", () => {
    const home = tmp(), root = tmp();
    writeFileSync(join(root, "Frame Gen.md"), "# Frame gen\n\n## 17. Lossless Scaling scoreboard\n\nW/L/D table\n");
    const project = { id: "p", tags: [], root };
    const work = writeWork(home, "p", "Goal: x. Next: y. See: Frame Gen.md#17. Watch out: z");
    expect(work.text).toContain("\nSee: Frame Gen.md#17\n");
    expect(workText(work, root)).toContain("W/L/D table");
    expect(stateSaved(work, home, project)).toMatch(/^state saved/);
    expect(stateSaved(writeWork(home, "p", "Goal: x. See: Frame Gen.md#nope."), home, project)).toContain("anchor missing: Frame Gen.md#nope");
  });

  it("workText: commits of the Brain's own work/ and notes/ folders do not mark the plan stale", () => {
    const home = tmp();
    const git = (...args: string[]) => execFileSync("git", ["-C", home, "-c", "user.name=t", "-c", "user.email=t@t", ...args], { stdio: "ignore" });
    git("init", "-q");
    execFileSync("git", ["-C", home, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], { stdio: "ignore", env: { ...process.env, GIT_AUTHOR_DATE: "2000-01-01T00:00:00Z", GIT_COMMITTER_DATE: "2000-01-01T00:00:00Z" } });
    const work = writeWork(home, "p", "Goal: x");
    const later = new Date(Date.parse(work.at) + 3600_000).toISOString();
    const commit = (file: string, message: string) => {
      mkdirSync(join(home, file, ".."), { recursive: true });
      writeFileSync(join(home, file), message);
      git("add", "-A");
      execFileSync("git", ["-C", home, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message], { stdio: "ignore", env: { ...process.env, GIT_AUTHOR_DATE: later, GIT_COMMITTER_DATE: later } });
    };
    commit("work/p.md", "plan");
    commit("notes/p/a.md", "note");
    expect(workText(work, home)).not.toContain("commit");
    commit("src/x.ts", "code");
    expect(workText(work, home)).toContain("1 commit since");
  });

  it("writeWork: a See: block over half the budget is cut, never Goal and Next", () => {
    const home = tmp();
    const see = "See: " + Array.from({ length: 30 }, (_, i) => `brain/src/module${i}.ts:${i * 10}`).join("; ");
    expect(see.length).toBeGreaterThan(600);
    const work = writeWork(home, "p", `Goal: finish the privacy audit\nNext: rerun the gate\n${see}`);
    expect(work.text).toMatch(/^Goal: finish the privacy audit\nNext: rerun the gate\nSee: brain\/src\/module0\.ts:0;/);
    expect(estimateTokens(work.text)).toBeLessThanOrEqual(WORK_BUDGET);
  });

  it("writeWork: See: lines over half the budget are kept whole while they fit, never cut mid-anchor", () => {
    const home = tmp();
    const see = ["phase-three-recall-question-phrasing-experiment", "83-question-phrased-recall-queries-rejected-2026-09-28", "6-kill-rules-unchanged-from-v4-restated-and-extended"]
      .map((slug) => `See: docs/intake/2026-09-28-plan-v5-anchored-memory.md#${slug}`.padEnd(110, "x"));
    const text = `Goal: ${"ship the anchored memory work ".repeat(5)}\nNext: ${"run the gate and the agentbench control ".repeat(3)}\nWatch out: approvals\n${see.join("\n")}`;
    expect(text.length).toBeGreaterThan(600);
    const work = writeWork(home, "p", text);
    const lines = work.text.split("\n");
    expect(lines.filter((line) => line.startsWith("See:") && line.endsWith("…"))).toEqual([]);
    expect(lines).toContain(see[0]);
    expect(lines).toContain(see[1]);
    expect(work.text).toMatch(/^Goal: ship/);
    expect(estimateTokens(work.text)).toBeLessThanOrEqual(WORK_BUDGET);
  });

  it("writeWork: throws on empty text", () => {
    const home = tmp();
    expect(() => writeWork(home, "p1", "  ")).toThrow(/empty/);
    expect(() => writeWork(home, "p1", "")).toThrow(/empty/);
  });

  it("readWork: parses frontmatter and body, extracts auto section", () => {
    const home = tmp();
    const text = "Goal: test\n\nDetails here\n## auto\n- edited: a, b";
    writeWork(home, "p1", text);
    writeAuto(home, "p1", { edited: ["a", "b"] });

    const work = readWork(home, "p1");
    expect(work?.text).toContain("Goal: test");
    expect(work?.auto).toContain("edited");
  });

  it("writeAuto: keeps existing text, replaces auto section", () => {
    const home = tmp();
    writeWork(home, "p1", "Goal: original");
    writeAuto(home, "p1", { edited: ["src/a.ts"] });

    const work = readWork(home, "p1");
    expect(work?.text).toContain("Goal: original");
    expect(work?.auto).toContain("src/a.ts");
  });

  it("writeAuto with nothing to say leaves file untouched", () => {
    const home = tmp();
    writeWork(home, "p1", "Goal: original");
    const before = readWork(home, "p1");

    const after = writeAuto(home, "p1", {});
    expect(after?.text).toBe(before?.text);
  });

  it("writeAuto with nothing to say returns null when no existing file", () => {
    const home = tmp();
    const result = writeAuto(home, "p1", {});
    expect(result).toBeNull();
  });

  it("formatAuto: edited keeps last 8 unique in last-occurrence order", () => {
    const formatted = formatAuto({
      edited: ["a", "b", "c", "a", "d", "e", "a", "f", "g", "h", "i", "j"],
    });
    expect(formatted.split("\n")[0]).toBe("- edited: d, e, a, f, g, h, i, j +2 more");
  });

  it("formatAuto: ask collapsed and cut to 160 chars", () => {
    const ask = "what  is\n  the  issue?";
    const formatted = formatAuto({ ask });
    expect(formatted).toContain("- last ask:");
    expect(estimateTokens(formatted)).toBeLessThanOrEqual(AUTO_BUDGET);
  });

  it("formatAuto: attachment placeholders are not an ask", () => {
    expect(formatAuto({ ask: "[Image #1, 1568x421]" })).toBe("");
    expect(formatAuto({ ask: "[Pasted text #2 +40 lines] [Image #3]", edited: ["a.ts"] })).toBe("- edited: a.ts");
    expect(formatAuto({ ask: "why does this crash? [Image #1, 1568x421]" })).toBe("- last ask: why does this crash?");
  });

  it("formatAuto: empty when all fields empty", () => {
    const formatted = formatAuto({});
    expect(formatted).toBe("");
  });

  it("formatAuto: cuts total to AUTO_BUDGET tokens", () => {
    const formatted = formatAuto({
      edited: Array.from({ length: 20 }, (_, i) => `file${i}.ts`),
      ask: "y".repeat(500),
    });
    expect(estimateTokens(formatted)).toBeLessThanOrEqual(AUTO_BUDGET);
  });

  it("workText: empty when work is null", () => {
    expect(workText(null)).toBe("");
  });

  it("workText: empty when both text and auto are empty", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "", auto: "", path: "" };
    expect(workText(work)).toBe("");
  });

  it("workText: includes timestamp and text/auto", () => {
    const work = {
      project: "p",
      at: "2026-09-27T10:30:45Z", autoAt: "",
      text: "Goal: xyz",
      auto: "- edited: a.ts",
      path: "",
    };
    const result = workText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("2026-09-27 10:30");
    expect(result).toContain("UTC");
    expect(result).toContain("Goal: xyz");
    expect(result).toContain("- edited: a.ts");
  });

  it("workText: format with text only", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "Goal", auto: "", path: "" };
    const result = workText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("Goal");
  });

  it("workText: format with auto only", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "", auto: "- edited: x", path: "" };
    const result = workText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("- edited: x");
  });

  it("round trip: write work, update auto, read both", () => {
    const home = tmp();
    const originalText = "Goal: test something\nDetails: more info";

    writeWork(home, "proj", originalText);
    const work1 = readWork(home, "proj");
    expect(work1?.text).toContain("Goal: test");

    writeAuto(home, "proj", { edited: ["src/a.ts", "src/b.ts"] });
    const work2 = readWork(home, "proj");

    expect(work2?.text).toContain("Goal: test");
    expect(work2?.auto).toContain("edited");
    expect(work2?.auto).toContain("src/a.ts");
  });

  it("auto observations remain local and leave the synced plan byte-identical", () => {
    const home = tmp();
    const plan = writeWork(home, "p", "Goal: ship safely");
    const before = readFileSync(plan.path, "utf8");
    writeAuto(home, "p", { edited: ["a.ts"] });
    expect(readFileSync(plan.path, "utf8")).toBe(before);
    expect(readFileSync(join(home, "state", "work", "p.auto.md"), "utf8")).toContain("- edited: a.ts");
  });

  it("warns when HEAD has commits newer than the plan and caps the subjects", () => {
    const root = tmp();
    const work = { project: "p", path: "", at: "2026-09-20T12:00:00Z", autoAt: "", text: "Goal: ship", auto: "" };
    const git = (...args: string[]) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    const commit = (subject: string, date: string) => execFileSync("git", ["-C", root, "-c", "user.name=Brain Test", "-c", "user.email=brain@example.test", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", subject], { env: { ...process.env, GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date }, stdio: "pipe" });
    try {
      git("init");
      commit("before plan", "2026-09-19T12:00:00Z");
      expect(workText(work, root)).not.toContain("plan may be stale");
      for (let i = 1; i <= 4; i++) commit(`change ${i}`, `2026-09-2${i}T12:00:00Z`);
      const latest = git("log", "-3", "--format=%h %s").trim().split("\n");
      const text = workText(work, root);
      expect(text).toContain(`plan may be stale — 4 commits since: ${latest.join("; ")}; …`);
      expect(text).not.toMatch(/change 1|before plan/);
      expect(text).toContain("Where we left off (2026-09-20 12:00 UTC):\nGoal: ship");
      expect(workText({ ...work, at: "2026-09-23T12:00:01Z" }, root)).toContain("1 commit since:");
      expect(workText({ ...work, at: "" }, root)).not.toContain("plan may be stale");
      expect(workText(work, join(root, "missing"))).not.toContain("commits since:");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("an explicit plan written during an auto write cannot be lost", () => {
    const home = tmp();
    writeWork(home, "p", "Goal: old plan");
    const atomic = util.writeAtomic;
    const hook = vi.spyOn(util, "writeAtomic").mockImplementationOnce((path, text) => {
      hook.mockRestore();
      writeWork(home, "p", "Goal: concurrent new plan");
      atomic(path, text);
    });
    try {
      writeAuto(home, "p", { ask: "continue" });
    } finally {
      hook.mockRestore();
    }
    expect(readWork(home, "p")).toMatchObject({ text: "Goal: concurrent new plan", auto: "- last ask: continue" });
  });

  it("stale plan and current auto context display their own timestamps", () => {
    const work = { project: "p", path: "", at: "2026-09-20T12:00:00Z", autoAt: "2026-09-27T15:00:00Z", text: "Goal: migrate DB", auto: "- last ask: export CSV" };
    const text = workText(work);
    expect(text).toContain("plan may be stale");
    expect(text).toContain("2026-09-20 12:00");
    expect(text).toContain("2026-09-27 15:00");
    expect(workText({ ...work, autoAt: "2026-09-23T12:00:00Z" })).not.toContain("plan may be stale");
  });

  it("legacy auto is readable, overridden locally, and dropped on the next plan write", () => {
    const home = tmp();
    mkdirSync(join(home, "work"));
    writeFileSync(workPath(home, "p"), "---\nat: 2026-09-20T12:00:00Z\nauto_at: 2026-09-21T12:00:00Z\n---\n\nGoal: old\n\n## auto\n- last failure: obsolete inline snippet\n- last ask: legacy\n");
    expect(readWork(home, "p")?.auto).toBe("- last ask: legacy");
    mkdirSync(join(home, "state", "work"), { recursive: true });
    writeFileSync(join(home, "state", "work", "p.auto.md"), "---\nat: 2026-09-22T12:00:00Z\n---\n\n- last ask: local\n- last failure: obsolete local snippet\n");
    expect(readWork(home, "p")?.auto).toBe("- last ask: local");
    writeAuto(home, "p", { ask: "local" });
    writeWork(home, "p", "Goal: new");
    expect(readFileSync(workPath(home, "p"), "utf8")).not.toContain("legacy");
    expect(readWork(home, "p")?.auto).toContain("local");
  });
});
