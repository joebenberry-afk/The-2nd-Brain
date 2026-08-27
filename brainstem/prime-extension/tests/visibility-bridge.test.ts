import { describe, expect, it } from "vitest";
import { parseOmpVisibilityOutput, runOmpVisibility } from "../src/visibility-bridge";

describe("parseOmpVisibilityOutput", () => {
  it("parses a well-formed shadow-mode plan", () => {
    const stdout = JSON.stringify({
      visibility_plan: { mode: "shadow", selected_skill_ids: ["a"], hydrated_skill_ids: [] },
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
