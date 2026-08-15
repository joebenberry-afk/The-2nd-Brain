import { mkdirSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTelemetryDirEnsurer, sanitizeSessionStem, TelemetryStore } from "../src/storage";

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

  it("creates the telemetry directory at construction (mkdir -p once)", async () => {
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
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const store = new TelemetryStore(join(blocker, "telemetry"), "sess-4");

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
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const store = new TelemetryStore(join(blocker, "telemetry"), "sess-6");
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

describe("Phase 4: mkdir-once + no buffering (src/storage.ts)", () => {
  it("establishes the directory exactly ONCE per store lifecycle, never per append", async () => {
    const ensureDir = vi.fn((dir: string) => {
      mkdirSync(dir, { recursive: true });
    });
    const store = new TelemetryStore(join(tmp, "once"), "sess-mk", ensureDir);
    for (let i = 0; i < 20; i++) {
      store.append({ v: 2, ts: `2026-01-01T00:00:0${i}.000Z`, kind: "turn_start", session: "sess-mk", turn: i });
    }
    await store.flush();
    expect(ensureDir).toHaveBeenCalledTimes(1); // construction only — zero mkdir per append
    const parsed = (await readFile(join(tmp, "once", "sess-mk.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(parsed).toHaveLength(20); // complete
    expect(parsed.map((p) => p.turn)).toEqual(Array.from({ length: 20 }, (_, i) => i)); // ordered
  });

  it("rapid interleaved appends stay ordered and complete (concurrent fire-and-forget)", async () => {
    const store = new TelemetryStore(tmp, "sess-conc");
    for (let i = 0; i < 10; i++) {
      // two appends per loop iteration: queued back-to-back, one chain
      store.append({ v: 2, ts: `2026-01-01T00:00:0${i}.000Z`, kind: "turn_start", session: "sess-conc", turn: i * 2 });
      store.append({ v: 2, ts: `2026-01-01T00:00:0${i}.000Z`, kind: "tool_call", session: "sess-conc", tool: "bash", id: `c${i}` });
    }
    await store.flush();
    const parsed = (await readFile(join(tmp, "sess-conc.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(parsed).toHaveLength(20);
    expect(parsed.map((p) => p.kind)).toEqual(
      Array.from({ length: 10 }, () => ["turn_start", "tool_call"]).flat(),
    );
    expect(parsed.map((p) => (p.kind === "turn_start" ? p.turn : p.id))).toEqual(
      Array.from({ length: 10 }, (_, i) => [i * 2, `c${i}`]).flat(),
    );
  });

  it("independent destinations: two stores append concurrently without cross-talk", async () => {
    const dirA = join(tmp, "a");
    const dirB = join(tmp, "b");
    const storeA = new TelemetryStore(dirA, "sA");
    const storeB = new TelemetryStore(dirB, "sB");
    for (let i = 0; i < 5; i++) {
      storeA.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sA", turn: i });
      storeB.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sB", turn: i });
    }
    await Promise.all([storeA.flush(), storeB.flush()]);
    const rawA = (await readFile(join(dirA, "sA.jsonl"), "utf8")).trim().split("\n");
    const rawB = (await readFile(join(dirB, "sB.jsonl"), "utf8")).trim().split("\n");
    expect(rawA).toHaveLength(5);
    expect(rawB).toHaveLength(5);
    expect(rawA.map((l) => JSON.parse(l).session)).toEqual(["sA", "sA", "sA", "sA", "sA"]);
    expect(rawB.map((l) => JSON.parse(l).session)).toEqual(["sB", "sB", "sB", "sB", "sB"]);
    expect(rawA.join("\n")).not.toContain("sB");
    expect(rawB.join("\n")).not.toContain("sA");
  });

  it("constructor/ensure-dir failure is fail-open: construction + append + appendFinal never throw, one log total", async () => {
    const blocker = join(tmp, "blocker");
    await writeFile(blocker, "i am a file, not a dir");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let store: TelemetryStore;
    expect(() => {
      store = new TelemetryStore(join(blocker, "telemetry"), "sess-fail");
    }).not.toThrow(); // construction never throws, even though mkdir fails
    expect(() => {
      store!.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sess-fail", turn: 0 });
    }).not.toThrow();
    expect(() => {
      store!.appendFinal({ v: 2, ts: "2026-01-01T00:00:01.000Z", kind: "session_shutdown", session: "sess-fail", reason: "quit" });
    }).not.toThrow(); // final sync write also non-fatal
    await store!.flush(); // resolves, never rejects
    expect(errorSpy).toHaveBeenCalledTimes(1); // readiness failure logged exactly once; appends/final stay silent
    errorSpy.mockRestore();
  });

  it("appendFinal does not re-create the directory (mkdir-once covers it)", async () => {
    const ensureDir = vi.fn((dir: string) => {
      mkdirSync(dir, { recursive: true });
    });
    const store = new TelemetryStore(join(tmp, "final"), "sess-final", ensureDir);
    store.appendFinal({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "session_shutdown", session: "sess-final", reason: "quit" });
    expect(ensureDir).toHaveBeenCalledTimes(1);
    const parsed = JSON.parse(await readFile(join(tmp, "final", "sess-final.jsonl"), "utf8"));
    expect(parsed.kind).toBe("session_shutdown");
  });
});

describe("createTelemetryDirEnsurer (factory-scoped, at-most-once)", () => {
  it("attempts mkdir exactly once across ANY number of calls (shared destination)", () => {
    const mkdir = vi.fn((dir: string) => {
      mkdirSync(dir, { recursive: true });
    });
    const ensurer = createTelemetryDirEnsurer(mkdir);
    ensurer(join(tmp, "shared"));
    ensurer(join(tmp, "shared"));
    ensurer(join(tmp, "shared"));
    expect(mkdir).toHaveBeenCalledTimes(1);
  });

  it("two stores sharing one ensurer produce one mkdir attempt and both write", async () => {
    const mkdir = vi.fn((dir: string) => {
      mkdirSync(dir, { recursive: true });
    });
    const ensurer = createTelemetryDirEnsurer(mkdir);
    const dir = join(tmp, "shared-dest");
    const storeA = new TelemetryStore(dir, "sessA", ensurer);
    const storeB = new TelemetryStore(dir, "sessB", ensurer);
    storeA.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sessA", turn: 0 });
    storeB.append({ v: 2, ts: "2026-01-01T00:00:00.000Z", kind: "turn_start", session: "sessB", turn: 0 });
    await Promise.all([storeA.flush(), storeB.flush()]);
    expect(mkdir).toHaveBeenCalledTimes(1);
    expect((await readFile(join(dir, "sessA.jsonl"), "utf8")).trim().split("\n")).toHaveLength(1);
    expect((await readFile(join(dir, "sessB.jsonl"), "utf8")).trim().split("\n")).toHaveLength(1);
  });

  it("a FAILED first attempt is permanently marked attempted (never retried) and propagates once", () => {
    const mkdir = vi.fn(() => {
      throw new Error("disk full");
    });
    const ensurer = createTelemetryDirEnsurer(mkdir);
    expect(() => ensurer(join(tmp, "x"))).toThrow("disk full"); // first caller sees the failure
    expect(() => ensurer(join(tmp, "x"))).not.toThrow(); // later callers: permanently attempted, no re-attempt
    expect(mkdir).toHaveBeenCalledTimes(1); // deliberate fail-open choice: report once, never storm mkdir
  });

  it("separate ensurers are independent (factory-scoped, not module-global)", () => {
    const mkdirA = vi.fn((dir: string) => mkdirSync(dir, { recursive: true }));
    const mkdirB = vi.fn((dir: string) => mkdirSync(dir, { recursive: true }));
    createTelemetryDirEnsurer(mkdirA)(tmp);
    createTelemetryDirEnsurer(mkdirB)(tmp);
    expect(mkdirA).toHaveBeenCalledTimes(1);
    expect(mkdirB).toHaveBeenCalledTimes(1);
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
