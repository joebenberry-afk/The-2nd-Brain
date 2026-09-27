import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { AUTO_BUDGET, WORK_BUDGET, formatAuto, readWork, renderResume, resumeText, workPath, writeAuto, writeWork } from "../src/work.ts";
import * as util from "../src/util.ts";
import { estimateTokens } from "../src/util.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-work-"));

describe("work", () => {
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

  it("formatAuto: failure collapsed and cut to 200 chars", () => {
    const failure = "error:  line1\n  line2\n  line3";
    const formatted = formatAuto({ failure });
    expect(formatted).toContain("- last failure:");
    expect(estimateTokens(formatted)).toBeLessThanOrEqual(AUTO_BUDGET);
  });

  it("formatAuto: ask collapsed and cut to 160 chars", () => {
    const ask = "what  is\n  the  issue?";
    const formatted = formatAuto({ ask });
    expect(formatted).toContain("- last ask:");
    expect(estimateTokens(formatted)).toBeLessThanOrEqual(AUTO_BUDGET);
  });

  it("formatAuto: empty when all fields empty", () => {
    const formatted = formatAuto({});
    expect(formatted).toBe("");
  });

  it("formatAuto: cuts total to AUTO_BUDGET tokens", () => {
    const formatted = formatAuto({
      edited: Array.from({ length: 20 }, (_, i) => `file${i}.ts`),
      failure: "x".repeat(500),
      ask: "y".repeat(500),
    });
    expect(estimateTokens(formatted)).toBeLessThanOrEqual(AUTO_BUDGET);
  });

  it("resumeText: empty when work is null", () => {
    expect(resumeText(null)).toBe("");
  });

  it("resumeText: empty when both text and auto are empty", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "", auto: "", path: "" };
    expect(resumeText(work)).toBe("");
  });

  it("resumeText: includes timestamp and text/auto", () => {
    const work = {
      project: "p",
      at: "2026-09-27T10:30:45Z", autoAt: "",
      text: "Goal: xyz",
      auto: "- edited: a.ts",
      path: "",
    };
    const result = resumeText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("2026-09-27 10:30");
    expect(result).toContain("UTC");
    expect(result).toContain("Goal: xyz");
    expect(result).toContain("- edited: a.ts");
  });

  it("resumeText: format with text only", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "Goal", auto: "", path: "" };
    const result = resumeText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("Goal");
  });

  it("resumeText: format with auto only", () => {
    const work = { project: "p", at: "2026-09-27T10:00:00Z", autoAt: "", text: "", auto: "- edited: x", path: "" };
    const result = resumeText(work);
    expect(result).toContain("Where we left off");
    expect(result).toContain("- edited: x");
  });

  it("round trip: write work, update auto, read both", () => {
    const home = tmp();
    const originalText = "Goal: test something\nDetails: more info";

    writeWork(home, "proj", originalText);
    const work1 = readWork(home, "proj");
    expect(work1?.text).toContain("Goal: test");

    writeAuto(home, "proj", { edited: ["src/a.ts", "src/b.ts"], failure: "timeout" });
    const work2 = readWork(home, "proj");

    expect(work2?.text).toContain("Goal: test");
    expect(work2?.auto).toContain("edited");
    expect(work2?.auto).toContain("src/a.ts");
    expect(work2?.auto).toContain("timeout");
  });

  it("auto observations remain local and leave the synced plan byte-identical", () => {
    const home = tmp();
    const plan = writeWork(home, "p", "Goal: ship safely");
    const before = readFileSync(plan.path, "utf8");
    writeAuto(home, "p", { edited: ["a.ts"], failure: "npm test failed" });
    expect(readFileSync(plan.path, "utf8")).toBe(before);
    expect(readFileSync(join(home, "state", "work", "p.auto.md"), "utf8")).toContain("npm test failed");
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

  it("resume preserves a late Next after a long Done within the complete budget", () => {
    const home = tmp();
    writeWork(home, "p", `Goal: ship migration. Done: ${"completed step ".repeat(100)} Next: run integration. Watch out: preserve data.`);
    writeAuto(home, "p", { edited: ["db.ts"], failure: "test failed", ask: "ship it" });
    const text = renderResume(readWork(home, "p"));
    expect(estimateTokens(text)).toBeLessThanOrEqual(150);
    expect(text).toContain("Goal: ship migration");
    expect(text).toContain("Next: run integration");
    expect(text.indexOf("Next:")).toBeLessThan(text.indexOf("Done:"));
  });

  it("stale plan and current auto context display their own timestamps", () => {
    const work = { project: "p", path: "", at: "2026-09-20T12:00:00Z", autoAt: "2026-09-27T15:00:00Z", text: "Goal: migrate DB", auto: "- last ask: export CSV" };
    for (const text of [resumeText(work), renderResume(work)]) {
      expect(text).toContain("plan may be stale");
      expect(text).toContain("2026-09-20 12:00");
      expect(text).toContain("2026-09-27 15:00");
    }
    expect(resumeText({ ...work, autoAt: "2026-09-23T12:00:00Z" })).not.toContain("plan may be stale");
  });

  it("legacy auto is readable, overridden locally, and dropped on the next plan write", () => {
    const home = tmp();
    mkdirSync(join(home, "work"));
    writeFileSync(workPath(home, "p"), "---\nat: 2026-09-20T12:00:00Z\nauto_at: 2026-09-21T12:00:00Z\n---\n\nGoal: old\n\n## auto\n- last ask: legacy\n");
    expect(readWork(home, "p")?.auto).toContain("legacy");
    writeAuto(home, "p", { ask: "local" });
    expect(readWork(home, "p")?.auto).toContain("local");
    writeWork(home, "p", "Goal: new");
    expect(readFileSync(workPath(home, "p"), "utf8")).not.toContain("legacy");
    expect(readWork(home, "p")?.auto).toContain("local");
  });

  it("resume handles slash-separated labels and bounds unlabeled fallback text", () => {
    const work = { project: "p", path: "", at: "", autoAt: "", text: "Goal ship / Done " + "completed ".repeat(100) + "/ Next verify / Watch out data", auto: "" };
    const labeled = renderResume(work);
    expect(labeled).toContain("Next: verify");
    expect(labeled.indexOf("Next:")).toBeLessThan(labeled.indexOf("Done:"));
    const fallback = renderResume({ ...work, text: "Continue from checkpoint. " + "detail ".repeat(200) });
    expect(fallback).toContain("Continue from checkpoint.");
    expect(estimateTokens(fallback)).toBeLessThanOrEqual(150);
    expect(renderResume(null)).toBe("");
  });

});
