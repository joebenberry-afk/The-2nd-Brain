/**
 * Phase A: privacy-safe structural telemetry for the `context` event's
 * `messages` array (sensors.contextStructure). Never stores prompt/tool
 * text, thinking text, or any unrecognized string — only JS value types,
 * an object's OWN top-level key NAMES, a short recognized role/kind
 * TOKEN, and sizes/lengths.
 */
import { describe, expect, it } from "vitest";
import { contextStructure, RECOGNIZED_TOKEN_RE } from "../src/sensors";

const SESSION = "ctx-struct-session";

describe("contextStructure", () => {
  it("empty array -> count 0, elements []", () => {
    const record = contextStructure(SESSION, []);
    expect(record.kind).toBe("context_structure");
    expect(record.session).toBe(SESSION);
    expect(record.count).toBe(0);
    expect(record.elements).toEqual([]);
  });

  it("non-array messages input safely no-ops (matches sensors.context fallback)", () => {
    expect(contextStructure(SESSION, undefined).count).toBe(0);
    expect(contextStructure(SESSION, null).count).toBe(0);
    expect(contextStructure(SESSION, "not an array").count).toBe(0);
    expect(contextStructure(SESSION, { messages: [] }).count).toBe(0);
    expect(contextStructure(SESSION, 42).elements).toEqual([]);
  });

  it("array of plain role-message objects: type, keys, role, content_type captured", () => {
    const messages = [
      { role: "user", content: "hello" },
      { role: "assistant", content: [{ type: "text", text: "hi" }] },
    ];
    const record = contextStructure(SESSION, messages);
    expect(record.count).toBe(2);
    expect(record.elements[0]).toMatchObject({
      type: "object",
      keys: ["role", "content"],
      role: "user",
      content_type: "string",
    });
    expect(record.elements[0]?.length).toBeUndefined();
    expect(record.elements[1]).toMatchObject({
      type: "object",
      keys: ["role", "content"],
      role: "assistant",
      content_type: "object", // typeof [] === "object" in JS (Array.isArray decides content_length/blocks)
      content_length: 1,
    });
    expect(record.elements[1]?.blocks).toEqual([{ kind: "text", length: expect.any(Number) }]);
  });

  it("a long/unrecognized role string is OMITTED, never stored verbatim", () => {
    const longRole = "this is not a short enum-like role token, it is prose";
    const messages = [{ role: longRole, content: "x" }];
    const record = contextStructure(SESSION, messages);
    expect(record.elements[0]?.role).toBeUndefined();
    expect(JSON.stringify(record)).not.toContain(longRole);
  });

  it("a numeric/object role is omitted (only recognized short strings pass)", () => {
    expect(contextStructure(SESSION, [{ role: 42 }]).elements[0]?.role).toBeUndefined();
    expect(contextStructure(SESSION, [{ role: { nested: true } }]).elements[0]?.role).toBeUndefined();
    expect(contextStructure(SESSION, [{ role: "tool_result" }]).elements[0]?.role).toBe("tool_result");
  });

  it("content array with typed blocks: only recognized .type/.kind token values captured, never other fields", () => {
    const messages = [
      {
        role: "assistant",
        content: [
          { type: "text", text: "SECRET PROMPT TEXT SHOULD NEVER APPEAR" },
          { kind: "toolResult", output: "SECRET TOOL OUTPUT SHOULD NEVER APPEAR" },
          { type: "this-token-is-way-too-long-to-be-recognized-as-a-short-enum", text: "x" },
          "a bare string block",
          42,
        ],
      },
    ];
    const record = contextStructure(SESSION, messages);
    const blocks = record.elements[0]?.blocks ?? [];
    expect(blocks).toHaveLength(5);
    expect(blocks[0]?.kind).toBe("text");
    expect(blocks[1]?.kind).toBe("toolResult");
    expect(blocks[2]?.kind).toBeNull(); // too long to match RECOGNIZED_TOKEN_RE
    expect(blocks[3]?.kind).toBeNull(); // non-object block
    expect(blocks[4]?.kind).toBeNull();
    for (const b of blocks) expect(typeof b.length).toBe("number");
  });

  it("a string element records only its length, never the text itself", () => {
    const record = contextStructure(SESSION, ["a raw string message"]);
    expect(record.elements[0]).toEqual({ type: "string", content_type: "undefined", length: 20 });
  });

  it("null/array/primitive elements degrade to a bare type shape, never throw", () => {
    const record = contextStructure(SESSION, [null, [1, 2, 3], 7, true, undefined]);
    expect(record.count).toBe(5);
    for (const el of record.elements) {
      expect(el.keys).toBeUndefined();
      expect(el.role).toBeUndefined();
    }
  });

  it("RECOGNIZED_TOKEN_RE matches only short enum-like tokens", () => {
    expect(RECOGNIZED_TOKEN_RE.test("user")).toBe(true);
    expect(RECOGNIZED_TOKEN_RE.test("tool_result")).toBe(true);
    expect(RECOGNIZED_TOKEN_RE.test("a".repeat(24))).toBe(true);
    expect(RECOGNIZED_TOKEN_RE.test("a".repeat(25))).toBe(false);
    expect(RECOGNIZED_TOKEN_RE.test("has spaces here")).toBe(false);
    expect(RECOGNIZED_TOKEN_RE.test("has-dash")).toBe(false);
    expect(RECOGNIZED_TOKEN_RE.test("")).toBe(false);
  });

  it("privacy scan: no fixture input text ever appears verbatim in the produced record", () => {
    const secrets = [
      "THE SECRET PROMPT TEXT",
      "raw tool stdout with credentials sk-abcdef1234567890",
      "chain-of-thought reasoning trace that must never leak",
    ];
    const messages = [
      { role: "user", content: secrets[0] },
      { role: "tool", content: [{ type: "text", text: secrets[1] }] },
      { role: "not_a_recognized_role_" + secrets[2], content: secrets[2] },
    ];
    const record = contextStructure(SESSION, messages);
    const serialized = JSON.stringify(record);
    for (const secret of secrets) {
      expect(serialized).not.toContain(secret);
    }
  });
});
