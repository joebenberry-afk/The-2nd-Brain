import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * P3-E1 harness sanity: every eval fixture under
 * tests/fixtures/lean-code-tasks/ MUST ship TASK.md (with the three required
 * sections) and JUDGE.md (with at least one deterministic numbered command),
 * and must NOT contain files that vitest would collect as tests (the fixtures
 * are inert data — an arm session works on a disposable COPY, never here).
 *
 * Plan §18.2 categories T1-T18 minus T10 (RTD-specific, deferred to P3-F).
 */
const ROOT = join(process.cwd(), "tests", "fixtures", "lean-code-tasks");

const EXPECTED = [
  "t01-config-reuse",
  "t02-existing-reuse",
  "t03-tiny-bugfix",
  "t04-duplication-temptation",
  "t05-legit-abstraction",
  "t06-dep-temptation",
  "t07-legit-dep",
  "t08-tool-temptation",
  "t09-legit-tool",
  "t11-high-risk",
  "t12-prep-refactor",
  "t13-cleanup-temptation",
  "t14-trivial",
  "t15-substantial",
  "t16-already-minimal",
  "t17-stale-memory",
  "t18-missing-evidence",
];

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

describe("P3-E1 eval fixtures (plan §18.2)", () => {
  it("has exactly the expected fixture set (T1-T9, T11-T18; T10 deferred to P3-F)", () => {
    expect(existsSync(ROOT)).toBe(true);
    const slugs = readdirSync(ROOT).filter((n) => statSync(join(ROOT, n)).isDirectory()).sort();
    expect(slugs).toEqual([...EXPECTED].sort());
    expect(EXPECTED.some((s) => s.startsWith("t10"))).toBe(false);
  });

  it("every fixture ships TASK.md with the three required sections", () => {
    for (const slug of EXPECTED) {
      const taskPath = join(ROOT, slug, "TASK.md");
      expect(existsSync(taskPath), `${slug}/TASK.md missing`).toBe(true);
      const text = readFileSync(taskPath, "utf8");
      expect(text, `${slug} TASK PROMPT section`).toContain("## TASK PROMPT");
      expect(text, `${slug} ACCEPTANCE section`).toContain("## ACCEPTANCE");
      expect(text, `${slug} BASELINE HINT section`).toContain("## BASELINE HINT");
      expect(text.length).toBeGreaterThan(200);
    }
  });

  it("every fixture ships JUDGE.md with at least one numbered deterministic command", () => {
    for (const slug of EXPECTED) {
      const judgePath = join(ROOT, slug, "JUDGE.md");
      expect(existsSync(judgePath), `${slug}/JUDGE.md missing`).toBe(true);
      const text = readFileSync(judgePath, "utf8");
      const numbered = text.split("\n").filter((l) => /^\s*\d+\.\s+/.test(l));
      expect(numbered.length, `${slug} JUDGE.md has no numbered commands`).toBeGreaterThan(0);
    }
  });

  it("fixtures are inert: no vitest-collectable test files inside", () => {
    for (const slug of EXPECTED) {
      const files = walk(join(ROOT, slug)).map((p) => p.replace(/\\/g, "/"));
      for (const f of files) {
        expect(f, `${slug} contains a test-collectable file`).not.toMatch(/\.(test|spec)\.(c|m)?[jt]s$/);
      }
    }
  });

  it("every JUDGE.md documents the anti-tamper oracle-restore rule", () => {
    for (const slug of EXPECTED) {
      const text = readFileSync(join(ROOT, slug, "JUDGE.md"), "utf8");
      expect(text, `${slug} JUDGE.md missing anti-tamper preamble`).toContain("FIXTURE_SOURCE");
    }
  });
});
