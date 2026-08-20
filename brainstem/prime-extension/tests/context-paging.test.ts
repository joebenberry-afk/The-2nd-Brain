/**
 * Part B/E (RC4 pass): the first conservative Context Virtual Memory pager.
 * `pageContext` is synchronous, fail-open, and NEVER throws (Part E). These
 * tests exercise it directly against the REAL captured schema (Pilot 2,
 * outputs/reports/rc4/12-real-prime-pilot-2.md), with a fake `listEvicted`
 * seam so no real subprocess is spawned.
 */
import { describe, expect, it } from "vitest";
import { pageContext, type PageContextOptions } from "../src/context-paging";
import { AUTOINJECT_CUSTOM_TYPE } from "../src/autoinject";
import type { ContextPagingFileConfig } from "../src/config";
import type { VmemListedObject, VmemListSyncResult } from "../src/vmem";

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

function fakeList(objects: VmemListedObject[], ok = true, error?: string) {
  return (): VmemListSyncResult => (ok ? { ok: true, objects } : { ok: false, error });
}

function baseOptions(overrides: Partial<PageContextOptions> = {}): PageContextOptions {
  return {
    home: "C:/fake-home",
    hostSessionId: "sess-paging-1",
    messages: [],
    cfg: ENABLED_CFG,
    listEvicted: fakeList([]),
    ...overrides,
  };
}

describe("pageContext — disabled / zero-mutation baselines", () => {
  it("disabled config -> always undefined, even with eligible-looking input", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({ messages, cfg: { ...ENABLED_CFG, enabled: false }, listEvicted: fakeList([
        { objId: "obj-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } },
      ]) }),
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
        listEvicted: () => {
          called = true;
          return { ok: true, objects: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(called).toBe(false); // budget never exceeded -> vmem list never invoked
  });

  it("eligible elements exist but none match an EVICTED object -> undefined (zero mutation)", () => {
    const messages = [
      autoinjectMessage("del-unmatched"),
      assistantMessage(),
      assistantMessage(),
      assistantMessage(),
    ];
    const result = pageContext(baseOptions({ messages, listEvicted: fakeList([]) }));
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });
});

describe("pageContext — eligibility classes (only the two real captured classes page)", () => {
  it("pages an AutoInject custom message whose delivery_id resolves to an EVICTED RESEARCH_RESULT", () => {
    const original = autoinjectMessage("del-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listEvicted: fakeList([
          { objId: "obj-research-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } },
        ]),
      }),
    );
    expect(result.pagedCount).toBe(1);
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
    // Every other element byte-for-byte identical.
    expect(patched[1]).toBe(messages[1]);
    expect(patched[2]).toBe(messages[2]);
    expect(patched[3]).toBe(messages[3]);
  });

  it("pages a toolResult whose toolCallId resolves to an EVICTED TOOL_OBSERVATION", () => {
    const original = toolResultMessage("call-1");
    const messages = [original, assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listEvicted: fakeList([
          { objId: "obj-tool-1", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-1" } },
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
  });

  it("never pages a toolResult with isError === true", () => {
    const messages = [toolResultMessage("call-err", true), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listEvicted: fakeList([
          { objId: "obj-tool-err", kind: "TOOL_OBSERVATION", metadata: { toolCallId: "call-err" } },
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
        listEvicted: fakeList([
          { objId: "obj-x", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-should-not-match" } },
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
        listEvicted: fakeList([
          { objId: "obj-pinned", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-pinned" } },
        ]),
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
  });

  it("resident_token_budget respected: below budget -> undefined, vmem list never called", () => {
    let called = false;
    const messages = [autoinjectMessage("del-1", "tiny"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, residentTokenBudget: 999999 },
        listEvicted: () => {
          called = true;
          return { ok: true, objects: [] };
        },
      }),
    );
    expect(result).toEqual({ messages: undefined, pagedCount: 0 });
    expect(called).toBe(false);
  });

  it("max_pages_per_context_event cap respected: more eligible than the cap -> only the cap's worth replaced", () => {
    const messages = [
      autoinjectMessage("del-1"),
      autoinjectMessage("del-2"),
      autoinjectMessage("del-3"),
      autoinjectMessage("del-4"),
      assistantMessage(),
      assistantMessage(),
    ];
    const result = pageContext(
      baseOptions({
        messages,
        cfg: { ...ENABLED_CFG, maxPagesPerContextEvent: 2, pinRecentMessages: 2 },
        listEvicted: fakeList([
          { objId: "obj-1", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-1" } },
          { objId: "obj-2", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-2" } },
          { objId: "obj-3", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-3" } },
          { objId: "obj-4", kind: "RESEARCH_RESULT", metadata: { deliveryId: "del-4" } },
        ]),
      }),
    );
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
      baseOptions({ messages, listEvicted: fakeList([], false, "simulated vmem list failure") }),
    );
    expect(result.messages).toBeUndefined();
    expect(result.pagedCount).toBe(0);
    expect(result.error).toBe("simulated vmem list failure");
  });

  it("fail-open on a throwing listEvicted seam: undefined + error, never throws out of pageContext", () => {
    const messages = [autoinjectMessage("del-1"), assistantMessage(), assistantMessage(), assistantMessage()];
    const result = pageContext(
      baseOptions({
        messages,
        listEvicted: () => {
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
    const result = pageContext(baseOptions({ messages, listEvicted: fakeList([]) }));
    expect(result.messages).toBeUndefined();
  });
});
