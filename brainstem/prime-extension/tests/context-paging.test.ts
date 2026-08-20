/**
 * Part B/E (RC4 pass) + Defect B (RC4 proactive-paging-repair pass):
 * `pageContext` is synchronous, fail-open, and NEVER throws (Part E).
 * These tests exercise it directly against the REAL captured schema
 * (Pilot 2, outputs/reports/rc4/12-real-prime-pilot-2.md), with fake
 * `listPrePage`/`claimPages` seams so no real subprocess is spawned.
 *
 * Defect B fix under test: `pageContext` now queries PRE-PAGE residency
 * states (RESIDENT, optionally FAULTED_IN — never EVICTED, never PINNED)
 * and performs its OWN claim (RESIDENT/FAULTED_IN -> EVICTED) before any
 * replacement patch is ever constructed — see context-paging.ts's module
 * docstring for the exact 8-step ordering this file verifies.
 */
import { describe, expect, it } from "vitest";
import { pageContext, type PageContextOptions } from "../src/context-paging";
import { AUTOINJECT_CUSTOM_TYPE } from "../src/autoinject";
import type { ContextPagingFileConfig } from "../src/config";
import type {
  VmemClaimPagesResult,
  VmemListPrePageSyncResult,
  VmemPrePageObject,
} from "../src/vmem";

const ENABLED_CFG: ContextPagingFileConfig = {
  enabled: true,
  pinRecentMessages: 2,
  residentTokenBudget: 10, // tiny: real fixtures below easily exceed this
  maxPagesPerContextEvent: 3,
};

function autoinjectMessage(deliveryId: string, content = "x".repeat(200)): unknown {
  return {
    role: "custom",
    customType: AUTOINJECT_CUSTOM_TYPE,
    content,
    display: true,
    details: { delivery_id: deliveryId, packet_tokens: 100 },
    timestamp: "2026-01-01T00:00:00Z",
  };
}

function toolResultMessage(toolCallId: string, isError = false, content = "y".repeat(200)): unknown {
  return {
    role: "toolResult",
    toolCallId,
    toolName: "ipython",
    content: [{ type: "text", text: content }],
    details: { some: "detail" },
    isError,
    timestamp: "2026-01-01T00:00:01Z",
  };
}

function assistantMessage(): unknown {
  return {
    role: "assistant",
    content: [{ type: "text", text: "z".repeat(200) }],
    api: "messages",
    provider: "anthropic",
    model: "claude",
    usage: {},
    stopReason: "end_turn",
    timestamp: "2026-01-01T00:00:02Z",
    responseId: "resp-1",
  };
}

/** Default a pre-page VMem object fixture: RESIDENT, unpinned, unless overridden. */
function prePageObj(
  overrides: Partial<VmemPrePageObject> & Pick<VmemPrePageObject, "objId" | "kind" | "metadata">,
): VmemPrePageObject {
  return { residencyState: "RESIDENT", pinned: false, ...overrides };
}

function fakeListPrePage(objects: VmemPrePageObject[], ok = true, error?: string) {
  return (): VmemListPrePageSyncResult => (ok ? { ok: true, objects } : { ok: false, error });
}

/** Default claim seam: confirms EVERY requested candidate (auto-approve) —
 * most tests only care about the list-side correlation; tests that
 * specifically exercise claim semantics override this. */
function autoClaim() {
  return (opts: { candidates: Array<{ objId: string; kind: string }> }): VmemClaimPagesResult => ({
    ok: true,
    claimedObjIds: opts.candidates.map((c) => c.objId),
  });
}

function fakeClaim(claimedObjIds: string[], ok = true, error?: string) {
  return (): VmemClaimPagesResult => (ok ? { ok: true, claimedObjIds } : { ok: false, error });
}

function baseOptions(overrides: Partial<PageContextOptions> = {}): PageContextOptions {
  return {
    home: "C:/fake-home",
    hostSessionId: "sess-paging-1",
    messages: [],
    cfg: ENABLED_CFG,
    listPrePage: fakeListPrePage([]),
    claimPages: autoClaim(),
    ...overrides,
  };
}

describe("pageContext — disabled / zero-mutation baselines", () => {
  it("disabled config -> always undefined, even with eligible-looking input", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, enabled: false },
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-1",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });

  it("empty messages -> undefined, no crash", () => {
    expect(pageContext(baseOptions({ messages: [] }))).toEqual({ messages: undefined, pagedCount: 0 });
  });

  it("non-array messages -> undefined, no crash", () => {
    expect(pageContext(baseOptions({ messages: "not an array" as unknown as unknown[] }))).toEqual({
      messages: undefined,
      pagedCount: 0,
    });
  });

  it("no eligible elements at all (only assistant turns) -> undefined, vmem list never called", () => {
    let called = false;
    const messages = [assistantMessage(), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: () => {
          called = true;
          return { ok: true, objects: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(called).toBe(false); // budget never exceeded -> vmem list never invoked
  });

  it("eligible elements exist but none correlate to a claimable object -> undefined (zero mutation)", () => {
    const messages = [
      autoinjectMessage("del-unmatched"),
      assistantMessage(),
      assistantMessage(),
      assistantMessage(),
    ];
    const result = pageContext(baseOptions({ messages, listPrePage: fakeListPrePage([]) }));
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });
});

describe("pageContext — Defect B: successful proactive page (the claim, end-to-end)", () => {
  it("pages an AutoInject custom message: RESIDENT + fully artifact-backed object + over budget -> claim invoked, confirmed, replaced", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    let claimCallCount = 0;
    let claimedCandidates: Array<{ objId: string; kind: string }> = [];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            residencyState: "RESIDENT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: (opts) => {
          claimCallCount += 1;
          claimedCandidates = opts.candidates;
          return { ok: true, claimedObjIds: ["obj-research-1"] };
        },
      }),
    );
    expect(claimCallCount).toBe(1); // ONE claim call per context event
    expect(claimedCandidates).toEqual([{ objId: "obj-research-1", kind: "RESEARCH_RESULT" }]);
    expect(result.pagedCount).toBe(1);
    expect(result.claimedPageCount).toBe(1);
    expect(result.requestedPageCount).toBe(1);
    expect(result.messages).toBeDefined();
    const patched = result.messages as Array<Record<string, unknown>>;
    // Identity fields kept EXACTLY as provided.
    expect(patched[0]?.role).toBe("custom");
    expect(patched[0]?.customType).toBe(AUTOINJECT_CUSTOM_TYPE);
    expect(patched[0]?.display).toBe(true);
    expect(patched[0]?.details).toEqual((original as Record<string, unknown>).details);
    expect(patched[0]?.timestamp).toBe((original as Record<string, unknown>).timestamp);
    // ONLY content replaced, as a plain STRING (matches the real schema).
    expect(typeof patched[0]?.content).toBe("string");
    const content = patched[0]?.content as string;
    expect(content).toContain("[SECOND_BRAIN_VMEM]");
    expect(content).toContain("obj-research-1");
    expect(content).toContain("del-1");
    expect(content).not.toContain("x".repeat(200)); // original packet text never leaks
    // Recovery pointer carries the REAL host session id, not a placeholder.
    expect(content).toContain("second_brain vmem resolve sess-paging-1 obj-research-1 --json");
    expect(content).not.toContain("<session_id>");
    // Every other element byte-for-byte identical.
    expect(patched[1]).toBe(messages[1]);
    expect(patched[2]).toBe(messages[2]);
    expect(patched[3]).toBe(messages[3]);
  });

  it("pages a toolResult: FAULTED_IN + artifact-backed object (evict_to_budget's own precedent) -> claimed and replaced", () => {
    const original = toolResultMessage("call-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-tool-1",
            kind: "TOOL_OBSERVATION",
            residencyState: "FAULTED_IN",
            metadata: { toolCallId: "call-1", artifactRef: "art-tool-1" },
          }),
        ]),
      }),
    );
    expect(result.pagedCount).toBe(1);
    const patched = result.messages as Array<Record<string, unknown>>;
    expect(patched[0]?.role).toBe("toolResult");
    expect(patched[0]?.toolCallId).toBe("call-1");
    expect(patched[0]?.toolName).toBe("ipython");
    expect(patched[0]?.isError).toBe(false);
    expect(patched[0]?.details).toEqual((original as Record<string, unknown>).details);
    expect(patched[0]?.timestamp).toBe((original as Record<string, unknown>).timestamp);
    // ONLY content replaced, as an ARRAY of one text block (matches RTD's shape).
    expect(Array.isArray(patched[0]?.content)).toBe(true);
    const blocks = patched[0]?.content as Array<{ type: string; text: string }>;
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.type).toBe("text");
    expect(blocks[0]?.text).toContain("[SECOND_BRAIN_VMEM]");
    expect(blocks[0]?.text).toContain("obj-tool-1");
    expect(blocks[0]?.text).toContain("call-1");
    expect(blocks[0]?.text).not.toContain("y".repeat(200));
    // Recovery pointer carries the REAL host session id, not a placeholder.
    expect(blocks[0]?.text).toContain("second_brain vmem resolve sess-paging-1 obj-tool-1 --json");
    expect(blocks[0]?.text).not.toContain("<session_id>");
  });

  it("recovery pointer threads the ACTUAL hostSessionId end-to-end for both paging classes (distinct fixture value, not the shared default)", () => {
    const distinctSessionId = "sess-recovery-distinct-9f3e";
    const autoinjectOriginal = autoinjectMessage("del-2");
    const toolOriginal = toolResultMessage("call-2");
    const messages = [autoinjectOriginal, toolOriginal, assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        hostSessionId: distinctSessionId,
        messages,
        cfg: { ...ENABLED_CFG, maxPagesPerContextEvent: 3 },
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-2",
            kind: "RESEARCH_RESULT",
            residencyState: "RESIDENT",
            metadata: { deliveryId: "del-2", packetArtifactRef: "art-2", packetSha256: "b".repeat(64) },
          }),
          prePageObj({
            objId: "obj-tool-2",
            kind: "TOOL_OBSERVATION",
            residencyState: "FAULTED_IN",
            metadata: { toolCallId: "call-2", artifactRef: "art-tool-2" },
          }),
        ]),
      }),
    );
    expect(result.pagedCount).toBe(2);
    const patched = result.messages as Array<Record<string, unknown>>;
    const autoinjectContent = patched[0]?.content as string;
    expect(autoinjectContent).toContain(
      `second_brain vmem resolve ${distinctSessionId} obj-research-2 --json`,
    );
    expect(autoinjectContent).not.toContain("<session_id>");
    const toolBlocks = patched[1]?.content as Array<{ type: string; text: string }>;
    expect(toolBlocks[0]?.text).toContain(
      `second_brain vmem resolve ${distinctSessionId} obj-tool-2 --json`,
    );
    expect(toolBlocks[0]?.text).not.toContain("<session_id>");
  });

  it("telemetry fields: candidate/eligible/requested/claimed counts and token before/after are populated correctly", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
      }),
    );
    expect(result.candidateCount).toBe(1);
    expect(result.eligibleCount).toBe(1);
    expect(result.requestedPageCount).toBe(1);
    expect(result.claimedPageCount).toBe(1);
    expect(result.pressureEstimatedTokens).toBeGreaterThan(0);
    expect(result.residentBudget).toBe(ENABLED_CFG.residentTokenBudget);
    expect(result.estimatedTokensBefore).toBeGreaterThan(0);
    expect(result.estimatedTokensAfter).toBeGreaterThan(0);
    expect(result.objectKinds).toEqual(["RESEARCH_RESULT"]);
    expect(result.stateBefore).toEqual(["RESIDENT"]);
    expect(result.stateAfter).toEqual(["EVICTED"]);
  });
});

describe("pageContext — Defect B: claim/state-transition failure -> no replacement", () => {
  it("claim seam reports the object was NOT claimed (lost a race) -> no context replacement, original messages untouched", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: fakeClaim([]), // claim call succeeded but confirmed NOTHING
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(messages[0]).toBe(original); // byte-for-byte untouched
  });

  it("the claim subprocess call itself fails -> fail-open, no replacement, error surfaced", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: fakeClaim([], false, "simulated claim-pages subprocess failure"),
      }),
    );
    expect(result.messages).toBeUndefined();
    expect(result.pagedCount).toBe(0);
    expect(result.error).toBe("simulated claim-pages subprocess failure");
    expect(messages[0]).toBe(original); // byte-for-byte untouched
  });

  it("a throwing claimPages seam is caught: fail-open, no replacement, no throw out of pageContext", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: () => {
          throw new Error("boom");
        },
      }),
    );
    expect(result.messages).toBeUndefined();
    expect(result.pagedCount).toBe(0);
    expect(result.error).toBe("boom");
  });

  it("claim confirms only SOME of the requested candidates: only those are replaced, the rest untouched", () => {
    const msgA = autoinjectMessage("del-a");
    const msgB = autoinjectMessage("del-b");
    const messages = [msgA, msgB, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, pinRecentMessages: 3 },
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-a",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-a", packetArtifactRef: "art-a", packetSha256: "a".repeat(64) },
          }),
          prePageObj({
            objId: "obj-b",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-b", packetArtifactRef: "art-b", packetSha256: "b".repeat(64) },
          }),
        ]),
        claimPages: fakeClaim(["obj-a"]), // obj-b lost the race
      }),
    );
    expect(result.requestedPageCount).toBe(2);
    expect(result.claimedPageCount).toBe(1);
    expect(result.pagedCount).toBe(1);
    const patched = result.messages as Array<Record<string, unknown>>;
    expect(typeof patched[0]?.content).toBe("string");
    expect((patched[0]?.content as string)).toContain("obj-a");
    expect(patched[1]).toBe(msgB); // untouched — its claim was not confirmed
  });
});

describe("pageContext — Defect B: candidate object state gates (only RESIDENT/FAULTED_IN, never PINNED)", () => {
  it("an already-EVICTED candidate object is not correlated (never sent to the claim call, no replacement)", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    let claimCalled = false;
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            residencyState: "EVICTED",
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: () => {
          claimCalled = true;
          return { ok: true, claimedObjIds: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(claimCalled).toBe(false); // no correlated candidate -> claim call never invoked
  });

  it.each(["STORED", "SUPERSEDED", "PURGED"])(
    "a %s candidate object is not correlated -> no replacement",
    (state) => {
      const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
      const result = pageContext(
        baseOptions({
          messages,
          listPrePage: fakeListPrePage([
            prePageObj({
              objId: "obj-research-1",
              kind: "RESEARCH_RESULT",
              residencyState: state,
              metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
            }),
          ]),
        }),
      );
      expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    },
  );

  it("a PINNED candidate object (even if RESIDENT) is never claimable -> no replacement", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    let claimCalled = false;
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-1",
            kind: "RESEARCH_RESULT",
            residencyState: "RESIDENT",
            pinned: true,
            metadata: { deliveryId: "del-1", packetArtifactRef: "art-1", packetSha256: "a".repeat(64) },
          }),
        ]),
        claimPages: () => {
          claimCalled = true;
          return { ok: true, claimedObjIds: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(claimCalled).toBe(false);
  });
});

describe("pageContext — eligibility classes (only the two real captured classes page)", () => {
  it("AutoInject object with deliveryId ONLY (no packetArtifactRef/packetSha256) -> NOT pageable (core regression fix)", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({ objId: "obj-research-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } }),
        ]),
      }),
    );
    expect(result.pagedCount).toBe(0);
    expect(result.messages).toBeUndefined();
    expect(messages[0]).toBe(original); // untouched
  });

  it("AutoInject object with deliveryId + packetArtifactRef but a MALFORMED packetSha256 -> NOT pageable", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const malformedCases = [
      "a".repeat(63), // wrong length (too short)
      "a".repeat(65), // wrong length (too long)
      "z".repeat(64), // non-hex characters
      undefined, // missing entirely
    ];
    for (const packetSha256 of malformedCases) {
      const metadata: Record<string, unknown> = { deliveryId: "del-1", packetArtifactRef: "art-1" };
      if (packetSha256 !== undefined) metadata.packetSha256 = packetSha256;
      const result = pageContext(
        baseOptions({
          messages,
          listPrePage: fakeListPrePage([prePageObj({ objId: "obj-research-1", kind: "RESEARCH_RESULT", metadata })]),
        }),
      );
      expect(result.pagedCount).toBe(0);
      expect(result.messages).toBeUndefined();
    }
    expect(messages[0]).toBe(original); // untouched
  });

  it("Tool observation object with toolCallId ONLY (no artifactRef) -> NOT pageable", () => {
    const original = toolResultMessage("call-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({ objId: "obj-tool-1", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-1" } }),
        ]),
      }),
    );
    expect(result.pagedCount).toBe(0);
    expect(result.messages).toBeUndefined();
    expect(messages[0]).toBe(original); // untouched
  });

  it("mixed proof in one context event: only the fully-backed candidate is ever a claim candidate at all", () => {
    const fullyBackedAutoinject = autoinjectMessage("del-full");
    const underProvenAutoinject = autoinjectMessage("del-partial");
    const messages = [fullyBackedAutoinject, underProvenAutoinject, assistantMessage(), assistantMessage(), assistantMessage()];
    let claimedCandidates: Array<{ objId: string; kind: string }> = [];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, pinRecentMessages: 3 },
        listPrePage: fakeListPrePage([
          prePageObj({
            objId: "obj-research-full",
            kind: "RESEARCH_RESULT",
            metadata: { deliveryId: "del-full", packetArtifactRef: "art-full", packetSha256: "c".repeat(64) },
          }),
          prePageObj({ objId: "obj-research-partial", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-partial" } }),
        ]),
        claimPages: (opts) => {
          claimedCandidates = opts.candidates;
          return { ok: true, claimedObjIds: opts.candidates.map((c) => c.objId) };
        },
      }),
    );
    // Only the fully-backed candidate is EVER sent to the claim call.
    expect(claimedCandidates).toEqual([{ objId: "obj-research-full", kind: "RESEARCH_RESULT" }]);
    expect(result.pagedCount).toBe(1);
    const patched = result.messages as Array<Record<string, unknown>>;
    expect((patched[0]?.content as string)).toContain("obj-research-full");
    expect(patched[1]).toBe(underProvenAutoinject); // untouched
  });

  it("never pages a toolResult with isError === true", () => {
    const messages = [toolResultMessage("call-err", true), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: fakeListPrePage([
          prePageObj({ objId: "obj-tool-err", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-err" } }),
        ]),
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });

  it("never pages assistant/thinking/toolCall/compactionSummary/other custom types", () => {
    const otherCustom = {
      role: "custom",
      customType: "some.other.packet",
      content: "x".repeat(200),
      display: true,
      details: { delivery_id: "del-should-not-match" },
      timestamp: "t",
    };
    const compactionSummary = {
      role: "compactionSummary",
      customInstructions: null,
      retainedMessageCount: 5,
      summary: "y".repeat(200),
      timestamp: "t",
      tokensBefore: 1000,
    };
    const messages = [otherCustom, compactionSummary, assistantMessage(), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, pinRecentMessages: 4 },
        listPrePage: fakeListPrePage([
          prePageObj({ objId: "obj-x", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-should-not-match" } }),
        ]),
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });
});

describe("pageContext — Part E guardrails", () => {
  it("current-turn pin window: the last N elements are never touched even when eligible", () => {
    const pinned = autoinjectMessage("del-pinned");
    const messages = [assistantMessage(), assistantMessage(), pinned, assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, pinRecentMessages: 2 }, // last 2 elements pinned: indices [2,3]
        listPrePage: fakeListPrePage([
          prePageObj({ objId: "obj-pinned", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-pinned" } }),
        ]),
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });

  it("resident_token_budget respected: below budget -> undefined, vmem list AND claim never called", () => {
    let listCalled = false;
    let claimCalled = false;
    const messages = [autoinjectMessage("del-1", "tiny"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, residentTokenBudget: 999999 },
        listPrePage: () => {
          listCalled = true;
          return { ok: true, objects: [] };
        },
        claimPages: () => {
          claimCalled = true;
          return { ok: true, claimedObjIds: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(listCalled).toBe(false);
    expect(claimCalled).toBe(false);
  });

  it("max_pages_per_context_event cap respected: only the capped number are ever requested/claimed/replaced", () => {
    const messages = [
      autoinjectMessage("del-1"),
      autoinjectMessage("del-2"),
      autoinjectMessage("del-3"),
      autoinjectMessage("del-4"),
      assistantMessage(),
      assistantMessage(),
    ];
    const artifactBacked = (deliveryId: string, objId: string) =>
      prePageObj({
        objId,
        kind: "RESEARCH_RESULT",
        metadata: { deliveryId, packetArtifactRef: `art-${deliveryId}`, packetSha256: "b".repeat(64) },
      });
    let claimedCandidates: Array<{ objId: string; kind: string }> = [];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, maxPagesPerContextEvent: 2, pinRecentMessages: 2 },
        listPrePage: fakeListPrePage([
          artifactBacked("del-1", "obj-1"),
          artifactBacked("del-2", "obj-2"),
          artifactBacked("del-3", "obj-3"),
          artifactBacked("del-4", "obj-4"),
        ]),
        claimPages: (opts) => {
          claimedCandidates = opts.candidates;
          return { ok: true, claimedObjIds: opts.candidates.map((c) => c.objId) };
        },
      }),
    );
    expect(claimedCandidates).toHaveLength(2); // never more than the cap requested
    expect(result.requestedPageCount).toBe(2);
    expect(result.pagedCount).toBe(2);
    const patched = result.messages as Array<Record<string, unknown>>;
    expect(typeof patched[0]?.content).toBe("string");
    expect((patched[0]?.content as string)).toContain("obj-1");
    expect(typeof patched[1]?.content).toBe("string");
    expect((patched[1]?.content as string)).toContain("obj-2");
    // Beyond the cap: untouched (still the original object identity).
    expect(patched[2]).toBe(messages[2]);
    expect(patched[3]).toBe(messages[3]);
  });

  it("fail-open on a simulated vmem-list failure: undefined + error, never throws", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({ messages, listPrePage: fakeListPrePage([], false, "simulated vmem list failure") }),
    );
    expect(result.messages).toBeUndefined();
    expect(result.pagedCount).toBe(0);
    expect(result.error).toBe("simulated vmem list failure");
  });

  it("fail-open on a throwing listPrePage seam: undefined + error, never throws out of pageContext", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listPrePage: () => {
          throw new Error("boom");
        },
      }),
    );
    expect(result.messages).toBeUndefined();
    expect(result.pagedCount).toBe(0);
    expect(result.error).toBe("boom");
  });

  it("zero mutation guardrail: never constructs an identical-looking patch when nothing was paged", () => {
    const messages = [assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(baseOptions({ messages, listPrePage: fakeListPrePage([]) }));
    expect(result.messages).toBeUndefined();
  });
});
