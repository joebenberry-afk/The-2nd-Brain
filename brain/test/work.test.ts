import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AUTO_BUDGET, WORK_BUDGET, formatAuto, readWork, resumeText, workPath, writeAuto, writeWork } from "../src/work.ts";
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

  it("auto at section exactly", () => {
    const home = tmp();
    writeWork(home, "p", "text content");
    writeAuto(home, "p", { edited: ["a.ts"] });

    const content = readFileSync(join(home, "work", "p.md"), "utf8");
    expect(content).toContain("## auto");
    // The exact line "## auto" should be on its own line
    expect(content).toMatch(/\n## auto\n/);
  });
});
