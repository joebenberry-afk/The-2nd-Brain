import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  assemblePrefix,
  assembleTail,
  checkPrefixDrift,
  appendTailAfterUserMessage,
} from "../src/injection-slots";

describe("T2.4 Injection placement", () => {
  let homeDir: string;

  beforeEach(async () => {
    homeDir = await mkdtemp(join(tmpdir(), "sb-inj-test-"));
    process.env.SECOND_BRAIN_HOME = homeDir;
    mkdirSync(join(homeDir, "skills", "active", "skill-test"), { recursive: true });
    writeFileSync(
      join(homeDir, "skills", "active", "skill-test", "SKILL.md"),
      `---\nname: skill-test\nversion: 1.0.0\n---\n\n# Purpose\nTest purpose.\n\n# Instructions\nTest body.\n`,
      "utf8",
    );
  });

  afterEach(async () => {
    delete process.env.SECOND_BRAIN_HOME;
    if (homeDir) {
      await rm(homeDir, { recursive: true, force: true }).catch(() => {});
    }
  });

  it("test_prefix_is_byte_identical_across_turns: sha256(PREFIX) identical across turns and no drift", () => {
    const p1 = assemblePrefix({
      projectId: "test-proj",
      leanKernel: "[second-brain-lean-code-kernel]\nWrite minimal code.",
      skillDescriptors: "skill-test v1.0.0: Test purpose.",
    });
    const hash1 = createHash("sha256").update(p1).digest("hex");

    const drift1 = checkPrefixDrift("session-1", p1);
    expect(drift1.drift).toBe(false);
    expect(drift1.hash).toBe(hash1);

    // Turn 2
    const p2 = assemblePrefix({
      projectId: "test-proj",
      leanKernel: "[second-brain-lean-code-kernel]\nWrite minimal code.",
      skillDescriptors: "skill-test v1.0.0: Test purpose.",
    });
    const hash2 = createHash("sha256").update(p2).digest("hex");

    expect(hash1).toBe(hash2);
    const drift2 = checkPrefixDrift("session-1", p2);
    expect(drift2.drift).toBe(false);

    // If drifted on turn 3
    const pDrift = p2 + "\nUnexpected addition";
    const drift3 = checkPrefixDrift("session-1", pDrift);
    expect(drift3.drift).toBe(true);
  });

  it("test_delta_goes_to_tail: dynamic delta, freshness, and hydrated skills go to TAIL, not PREFIX", () => {
    const prefix = assemblePrefix({
      projectId: "test-proj",
      leanKernel: "[second-brain-lean-code-kernel]\nKernel code.",
      skillDescriptors: "skill-test v1.0.0: Test purpose.",
    });

    expect(prefix).toContain("[second-brain-lean-code-kernel]");
    expect(prefix).toContain("skill-test v1.0.0: Test purpose.");
    // An OMP session mounts no `brainctl` device, so the prefix must not
    // instruct it (2026-09-21).
    expect(prefix).not.toContain("brainctl");
    expect(prefix).toContain("Project: test-proj");

    // Dynamic items must NOT be in prefix
    expect(prefix).not.toContain("[BRAIN_CONTEXT_DELTA");
    expect(prefix).not.toContain("freshness:");
    expect(prefix).not.toContain("Hydrated full instructions");

    const tail = assembleTail({
      deltaContext: "[BRAIN_CONTEXT_DELTA v1]\npacket_id: pkt-123\nfreshness: VERIFIED_CURRENT\n",
      hotContextRefs: "hot-ref-vmem",
      freshnessLines: "freshness: VERIFIED_CURRENT",
      hydratedSkills: "Hydrated full instructions for skill-test",
    });

    expect(tail).toContain("[BRAIN_CONTEXT_DELTA");
    expect(tail).toContain("hot-ref-vmem");
    expect(tail).toContain("freshness: VERIFIED_CURRENT");
    expect(tail).toContain("Hydrated full instructions for skill-test");

    // Prefix items must not be in tail
    expect(tail).not.toContain("Project: test-proj");
    expect(tail).not.toContain("To remember: run `brainctl remember");

    // Append tail after user message in turn messages
    const messages = [
      { role: "system", content: prefix },
      { role: "user", content: "Do the task" },
      { role: "assistant", content: "Working..." },
    ];
    const placed = appendTailAfterUserMessage(messages, tail);
    const userIdx = placed.findIndex(
      (m) => (m as Record<string, unknown>).role === "user",
    );
    expect(userIdx).toBeGreaterThanOrEqual(0);
    const placedAfter = placed.slice(userIdx);
    const hasTail = placedAfter.some((m) => {
      const content = (m as Record<string, unknown>).content;
      return typeof content === "string" && content.includes(tail);
    });
    expect(hasTail).toBe(true);
  });
});
