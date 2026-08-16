import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * P3 promotion campaign: every opportunity fixture under
 * tests/fixtures/lean-opportunity-tasks/ MUST ship TASK.md (user-style
 * request only — no encoded answer), JUDGE.md (deterministic commands +
 * anti-tamper preamble), and CARD.md (the internal evaluation card with all
 * plan §7 fields — NEVER shown to arms). Fixtures are inert data: no
 * vitest-collectable test files inside.
 */
const ROOT = join(process.cwd(), "tests", "fixtures", "lean-opportunity-tasks");

const EXPECTED = [
  "e01-deploy-profiles",
  "e02-price-formatting",
  "e03-log-pipeline",
  "e06-customer-sort",
  "e07-jsonc-config",
  "e08-call-count-analysis",
  "e09-release-table",
  "e10-net-amount",
  "e11-greet-trim",
  "e12-math-double",
  "e13-crash-safe-store",
  "e14-debug-toggle",
  "e15-order-validation",
  "e16-title-config",
];

const CARD_FIELDS = [
  "task_id",
  "user-style request",
  "repository/fixture baseline",
  "acceptance criteria",
  "current reusable capabilities",
  "risk level",
  "known legitimate solution classes",
  "known unjustified expansion classes",
  "metrics to collect",
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

describe("P3 promotion-eval opportunity fixtures (plan §5/§6/§7)", () => {
  it("has exactly the 14 expected fixtures (E1-E16 minus E4/E5 — covered by skill-eval cases)", () => {
    expect(existsSync(ROOT)).toBe(true);
    const slugs = readdirSync(ROOT).filter((n) => statSync(join(ROOT, n)).isDirectory()).sort();
    expect(slugs).toEqual([...EXPECTED].sort());
  });

  it("TASK.md is the user-style request only — no encoded answer/constraint language", () => {
    const forbidden = ["do not", "no new files", "the answer is", "lines only", "baseline hint", "expected solution"];
    for (const slug of EXPECTED) {
      const text = readFileSync(join(ROOT, slug, "TASK.md"), "utf8");
      for (const phrase of forbidden) {
        expect(text.toLowerCase(), `${slug} TASK.md contains encoded constraint '${phrase}'`).not.toContain(phrase);
      }
      expect(text.length).toBeGreaterThan(40); // a one-line user request is legitimate (e16)
    }
  });

  it("every fixture ships JUDGE.md with numbered commands and the anti-tamper preamble", () => {
    for (const slug of EXPECTED) {
      const text = readFileSync(join(ROOT, slug, "JUDGE.md"), "utf8");
      expect(text).toContain("FIXTURE_SOURCE");
      const numbered = text.split("\n").filter((l) => /^\s*\d+\.\s+/.test(l));
      expect(numbered.length, `${slug} JUDGE.md has no numbered commands`).toBeGreaterThan(0);
    }
  });

  it("every fixture ships the internal CARD.md with all plan §7 fields", () => {
    for (const slug of EXPECTED) {
      const text = readFileSync(join(ROOT, slug, "CARD.md"), "utf8");
      for (const field of CARD_FIELDS) {
        expect(text, `${slug} CARD.md missing field '${field}'`).toContain(field);
      }
      expect(text, `${slug} CARD.md must be marked evaluator-only`).toContain("EVALUATOR-ONLY");
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
});
