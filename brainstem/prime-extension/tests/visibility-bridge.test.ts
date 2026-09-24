import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  loadSkillsVisibilityMode,
  parseOmpVisibilityOutput,
  runOmpVisibility,
  skillsVisibilityModeFromToml,
} from "../src/visibility-bridge";

describe("parseOmpVisibilityOutput", () => {
  it("parses a well-formed shadow-mode plan", () => {
    const stdout = JSON.stringify({
      visibility_plan: {
        visibility_plan_id: "vplan-shadow",
        mode: "shadow",
        selected_skill_ids: ["a"],
        hydrated_skill_ids: [],
        rejected_skill_ids: {},
        unavailable_skill_ids: {},
      },
      hydrated_instructions: {},
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.visibility_plan?.mode).toBe("shadow");
    expect(result.error).toBeNull();
  });

  it("parses a well-formed enforced-mode plan with hydrated instructions", () => {
    const stdout = JSON.stringify({
      visibility_plan: {
        visibility_plan_id: "vplan-abc123",
        mode: "enforced",
        selected_skill_ids: ["a"],
        hydrated_skill_ids: ["a"],
        rejected_skill_ids: {},
        unavailable_skill_ids: {},
      },
      hydrated_instructions: { a: "full skill text" },
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.visibility_plan?.mode).toBe("enforced");
    expect(result.hydrated_instructions.a).toBe("full skill text");
  });

  it("fails open on malformed JSON", () => {
    const result = parseOmpVisibilityOutput("not json");
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });

  it("fails open when visibility_plan is missing required fields", () => {
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          mode: "shadow",
          selected_skill_ids: ["a"],
          hydrated_skill_ids: [],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: {},
      }),
    );
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_INVALID_PLAN");
  });

  it("fails open when visibility_plan has an invalid mode", () => {
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-invalid-mode",
          mode: "advisory",
          selected_skill_ids: ["a"],
          hydrated_skill_ids: [],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: {},
      }),
    );
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_INVALID_PLAN");
  });

  it("fails open when hydrated instructions include an unselected skill", () => {
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-unknown-hydrated",
          mode: "enforced",
          selected_skill_ids: ["a"],
          hydrated_skill_ids: ["a"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { unknown: "must not inject" },
      }),
    );
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_INVALID_PLAN");
  });

  it("fails open when a hydrated body exceeds the injection bound", () => {
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-oversized-body",
          mode: "enforced",
          selected_skill_ids: ["a"],
          hydrated_skill_ids: ["a"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { a: "x".repeat(8193) },
      }),
    );
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_INVALID_PLAN");
  });

  it("fails open (whole plan) when the aggregate injected total exceeds the budget", () => {
    // Two near-limit bodies that individually satisfy the per-body bound
    // (<=8192 each) but together exceed OMP_VISIBILITY_MAX_INJECTED_CHARS
    // once the 2-char "\n\n" separator is counted (P3.16 defect fix).
    const a = "a".repeat(4100);
    const b = "b".repeat(4100); // 4100 + 2 + 4100 = 8202 > 8192
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-aggregate-too-large",
          mode: "enforced",
          selected_skill_ids: ["a", "b"],
          hydrated_skill_ids: ["a", "b"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { a, b },
        error: null,
      }),
    );
    // Fails the WHOLE plan (no injection at all) rather than silently
    // truncating one body to fit -- never a partial inject.
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_AGGREGATE_TOO_LARGE");
  });

  it("accepts three near-limit bodies exactly at the aggregate budget, byte-identical", () => {
    // 2730 + 2730 + 2730 + 2*2 separators = 8194 -- trim to fit exactly 8192.
    const a = "a".repeat(2729);
    const b = "b".repeat(2729);
    const c = "c".repeat(2730);
    const total = a.length + b.length + c.length + 2 * 2;
    expect(total).toBeLessThanOrEqual(8192);
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-aggregate-fits",
          mode: "enforced",
          selected_skill_ids: ["a", "b", "c"],
          hydrated_skill_ids: ["a", "b", "c"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { a, b, c },
        error: null,
      }),
    );
    expect(result.error).toBeNull();
    expect(result.visibility_plan?.hydrated_skill_ids).toEqual(["a", "b", "c"]);
    // Plan/effective-input identity: every recovered body is byte-identical
    // to the input, and OMP's own "\n\n" concatenation of exactly these
    // bodies never exceeds the injection budget.
    expect(result.hydrated_instructions.a).toBe(a);
    expect(result.hydrated_instructions.b).toBe(b);
    expect(result.hydrated_instructions.c).toBe(c);
    const effectiveInput = Object.entries(result.hydrated_instructions)
      .sort(([x], [y]) => x.localeCompare(y))
      .map(([, text]) => text)
      .join("\n\n");
    expect(effectiveInput.length).toBeLessThanOrEqual(8192);
    expect(effectiveInput).toBe(`${a}\n\n${b}\n\n${c}`);
  });

  it("fails open when hydrated_skill_ids claims more bodies than are present", () => {
    // hydrated_skill_ids says two skills hydrated, but only one body is
    // actually attached -- must never be treated as a valid partial plan.
    const result = parseOmpVisibilityOutput(
      JSON.stringify({
        visibility_plan: {
          visibility_plan_id: "vplan-count-mismatch",
          mode: "enforced",
          selected_skill_ids: ["a", "b"],
          hydrated_skill_ids: ["a", "b"],
          rejected_skill_ids: {},
          unavailable_skill_ids: {},
        },
        hydrated_instructions: { a: "full skill text" },
        error: null,
      }),
    );
    expect(result.visibility_plan).toBeNull();
    expect(result.hydrated_instructions).toEqual({});
    expect(result.error).toBe("BRAIN_VISIBILITY_INVALID_PLAN");
  });

  it("fails open when visibility_plan is missing", () => {
    const result = parseOmpVisibilityOutput(JSON.stringify({ error: "VISIBILITY_UNAVAILABLE" }));
    expect(result.visibility_plan).toBeNull();
    expect(result.error).toBe("VISIBILITY_UNAVAILABLE");
  });

  it("fails open when hydrated_instructions is not an object", () => {
    const stdout = JSON.stringify({
      visibility_plan: { mode: "shadow", selected_skill_ids: [], hydrated_skill_ids: [] },
      hydrated_instructions: "nope",
      error: null,
    });
    const result = parseOmpVisibilityOutput(stdout);
    expect(result.hydrated_instructions).toEqual({});
  });

  it("fails open when stdout exceeds the bound", () => {
    const huge = "x".repeat(300 * 1024);
    const result = parseOmpVisibilityOutput(huge);
    expect(result.visibility_plan).toBeNull();
    expect(result.error).toBe("BRAIN_VISIBILITY_OUTPUT_TOO_LARGE");
  });
});

describe("runOmpVisibility", () => {
  it("fails open when the python process errors", async () => {
    const result = await runOmpVisibility({
      home: "/nonexistent/path/that/does/not/exist",
      task: "test task",
      sessionId: "s1",
      projectId: "p1",
      python: "/nonexistent/python/binary/that/does/not/exist",
    });
    expect(result.visibility_plan).toBeNull();
    expect(result.error).not.toBeNull();
  });
});

/**
 * The quiet fast path suppresses the visibility spawn only when this in-host read
 * proves `skills.resolve_visibility_mode` cannot be `enforced`. The reader must
 * therefore agree with Python on every decodable shape and answer "enforced"
 * (i.e. plan) whenever it cannot be sure — a wrong "shadow" costs the injected
 * specialist instructions.
 */
describe("skillsVisibilityModeFromToml", () => {
  const shipped = [
    "# skills.toml — skill lifecycle defaults",
    "schema_version = 1",
    "",
    "[router]",
    "max_active = 3      # ENFORCED",
    "",
    "[visibility]",
    'mode = "shadow"     # SHADOW/REPORT-ONLY default',
    "",
    "[lean]",
    'eval = "off"',
  ].join("\n");

  it("reads the exact enforced value Python compares against", () => {
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = "enforced"\n')).toBe("enforced");
    expect(skillsVisibilityModeFromToml("[visibility]\nmode='enforced'\n")).toBe("enforced");
    expect(skillsVisibilityModeFromToml('[ visibility ]\nmode = "enforced" # why\n')).toBe("enforced");
    expect(skillsVisibilityModeFromToml('visibility.mode = "enforced"\n')).toBe("enforced");
    expect(skillsVisibilityModeFromToml('["visibility"]\nmode = "enforced"\n')).toBe("enforced");
  });

  it("answers shadow for the shipped config and every other decoded value", () => {
    expect(skillsVisibilityModeFromToml(shipped)).toBe("shadow");
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = "ENFORCED"\n')).toBe("shadow");
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = "shadow"\n')).toBe("shadow");
    expect(skillsVisibilityModeFromToml("[visibility]\nmode = 3\n")).toBe("enforced");
    expect(skillsVisibilityModeFromToml("")).toBe("shadow");
    expect(skillsVisibilityModeFromToml('[router]\nmax_active = 3\n')).toBe("shadow");
  });

  it("never answers shadow when the value cannot be decoded here", () => {
    // Escaped/duplicate/odd shapes could still resolve to `enforced` in Python:
    // the safe direction is to plan visibility (one spawn) instead of dropping it.
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = """enforced"""\n')).toBe("enforced");
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = "enf\\u006frced"\n')).toBe("enforced");
    expect(skillsVisibilityModeFromToml('[visibility]\nmode = "shadow"\nmode = "shadow"\n')).toBe(
      "enforced",
    );
  });

  it("reads the file fail-safe and resolves a missing home to shadow", () => {
    expect(loadSkillsVisibilityMode(null)).toBe("shadow");
    expect(loadSkillsVisibilityMode(join(tmpdir(), "sb-visibility-missing"))).toBe("shadow");
  });

  it("reads a home's own skills.toml", () => {
    const home = mkdtempSync(join(tmpdir(), "sb-visibility-"));
    try {
      mkdirSync(join(home, "config"), { recursive: true });
      expect(loadSkillsVisibilityMode(home)).toBe("shadow");
      writeFileSync(join(home, "config", "skills.toml"), '[visibility]\nmode = "enforced"\n', "utf8");
      expect(loadSkillsVisibilityMode(home)).toBe("enforced");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
