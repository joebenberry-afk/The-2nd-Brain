import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sanitizeSessionStem, TelemetryStore } from "../src/storage";

let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "sb-obs-"));
});

afterEach(async () => {
  await rm(tmp, { recursive: true, force: true });
});

describe("TelemetryStore", () => {
  it("writes valid JSONL records to <dir>/<session>.jsonl", async () => {
    const store = new TelemetryStore(tmp, "sess-1");
    store.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_start", session: "sess-1" });
    store.append({ v: 2, ts: "2026-01-01T00:00:01.000Z", kind: "turn_start", session: "sess-1", turn: 0 });
    store.append({ v: 2, ts: "2026-01-01T00:00:02.000Z", kind: "session_shutdown", session: "sess-1", reason: "quit" });
    await store.flush();

    const raw = await readFile(join(tmp, "sess-1.jsonl"), "utf8");
    const lines = raw.trim().split("\n");
    expect(lines).toHaveLength(3);
    const parsed = lines.map((l) => JSON.parse(l));
    expect(parsed.map((p) => p.kind)).toEqual(["session_start", "turn_start", "session_shutdown"]);
    for (const p of parsed) {
      expect(p.v).toBe(2);
      expect(typeof p.ts).toBe("string");
      expect(p.session).toBe("sess-1");
    }
  });

  it("creates the telemetry directory on first write (mkdir -p)", async () => {
    const deep = join(tmp, "a", "b", "c");
    const store = new TelemetryStore(deep, "sess-2");
    store.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_shutdown", session: "sess-2", reason: "quit" });
    await store.flush();
    const raw = await readFile(join(deep, "sess-2.jsonl"), "utf8");
    expect(raw.trim().split("\n")).toHaveLength(1);
  });

  it("preserves append order under rapid fire-and-forget writes", async () => {
    const store = new TelemetryStore(tmp, "sess-3");
    for (let i = 0; i < 10; i++) {
      store.append({ v: 2, ts: `2026-01-01T00:00:0${i}.000Z`, kind: "turn_start", session: "sess-3", turn: i });
    }
    await store.flush();
    const parsed = (await readFile(join(tmp, "sess-3.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(parsed.map((p) => p.turn)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });

  it("never throws when the telemetry dir cannot be created (path is a file)", async () => {
    const blocker = join(tmp, "blocker");
    await writeFile(blocker, "i am a file, not a dir");
    const store = new TelemetryStore(join(blocker, "telemetry"), "sess-4");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => {
      store.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_shutdown", session: "sess-4", reason: "quit" });
      store.append({ v: 2, ts: "2026-01-01T00:00:01.000Z", kind: "turn_start", session: "sess-4", turn: 1 });
    }).not.toThrow();

    await store.flush(); // must resolve, not reject
    // exactly one stderr log for the whole failure streak
    expect(errorSpy).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });

  it("append survives unserializable records", async () => {
    const store = new TelemetryStore(tmp, "sess-5");
    const circular: Record<string, unknown> = { name: "x" };
    circular.self = circular;
    expect(() => store.append(circular)).not.toThrow();
    store.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_shutdown", session: "sess-5", reason: "quit" });
    await store.flush();
    const parsed = (await readFile(join(tmp, "sess-5.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(parsed).toHaveLength(1);
    expect(parsed[0].kind).toBe("session_shutdown");
  });

  it("filePath names the file after the session id", () => {
    const store = new TelemetryStore(tmp, "abc-123");
    expect(store.filePath()).toBe(join(tmp, "abc-123.jsonl"));
  });

  it("appendFinal writes synchronously and survives a broken async chain", async () => {
    const blocker = join(tmp, "blocker");
    await writeFile(blocker, "i am a file, not a dir");
    const store = new TelemetryStore(join(blocker, "telemetry"), "sess-6");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // poison the async chain (unwritable dir), then write the final record sync
    store.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sess-6", turn: 0 });
    await store.flush();
    expect(() => {
      store.appendFinal({ v: 2, ts: "2026-01-01T00:00:01.000Z", kind: "session_shutdown", session: "sess-6", reason: "quit" });
    }).not.toThrow();
    expect(errorSpy).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });

  it("appendFinal writes through to the file", async () => {
    const store = new TelemetryStore(join(tmp, "deep", "dir"), "sess-7");
    store.appendFinal({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_shutdown", session: "sess-7", reason: "quit" });
    const parsed = JSON.parse(await readFile(join(tmp, "deep", "dir", "sess-7.jsonl"), "utf8"));
    expect(parsed.kind).toBe("session_shutdown");
    expect(parsed.v).toBe(2);
  });
});

describe("sanitizeSessionStem", () => {
  it("keeps safe stems, scrubs path separators and dots", () => {
    expect(sanitizeSessionStem("019ffe7d-9d5b-75dc")).toBe("019ffe7d-9d5b-75dc");
    expect(sanitizeSessionStem("../../evil")).toBe("evil");
    expect(sanitizeSessionStem("a b/c")).toBe("a-b-c");
    expect(sanitizeSessionStem("")).toMatch(/^anon-/);
  });
});


describe("SEC-08: persisted telemetry contains no command secrets", () => {
  it("tool_call bash records persist [REDACTED], never the secret", async () => {
    const { toolCall } = await import("../src/sensors");
    const SECRET = "sk-super-secret-value-1234567890";
    const store = new TelemetryStore(tmp, "sess-sec");
    store.append(
      toolCall("sess-sec", "bash", "call-1", { command: `curl -H "Authorization: Bearer ${SECRET}" url` }),
    );
    store.append(toolCall("sess-sec", "bash", "call-2", { command: `--token=${SECRET}` }));
    await store.flush();
    const raw = await readFile(join(tmp, "sess-sec.jsonl"), "utf8");
    expect(raw).not.toContain(SECRET);
    expect(raw).toContain("[REDACTED]");
    for (const line of raw.trim().split("\n")) {
      const parsed = JSON.parse(line);
      expect(parsed.kind).toBe("tool_call");
      expect(parsed.command).toBeDefined();
    }
  });
});
