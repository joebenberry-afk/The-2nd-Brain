/**
 * Capsule-write ordering barrier (`src/capsule-writes.ts`).
 *
 * Contract under test (V3 S2 review fix): every capsule write of one session is
 * strictly ordered — a foreground write waits for the quiet ensure already in
 * flight, supersedes a quiet prompt still queued (its text is OLDER than the
 * turn that supersedes it), and a quiet prompt that arrives afterwards runs after
 * it. Nothing overlaps, and `drain` settles everything queued so compaction and
 * shutdown persistence can run on a quiet barrier.
 */
import { describe, expect, it } from "vitest";
import { createCapsuleWrites } from "../src/capsule-writes";

/** Let queued microtasks (the barrier's chains) run. */
async function flush(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve();
}

/**
 * A write stand-in that records the prompt it receives and blocks until the test
 * releases it, so ordering and overlap are observable instead of timed.
 */
function recorder(): {
  write: (prompt: string) => Promise<void>;
  started: string[];
  maxConcurrent: () => number;
  releaseAll: () => Promise<void>;
} {
  const started: string[] = [];
  let waiting: Array<() => void> = [];
  let active = 0;
  let peak = 0;
  return {
    started,
    write: (prompt: string) =>
      new Promise<void>((resolve) => {
        started.push(prompt);
        active += 1;
        peak = Math.max(peak, active);
        waiting.push(() => {
          active -= 1;
          resolve();
        });
      }),
    maxConcurrent: () => peak,
    releaseAll: async () => {
      const current = waiting;
      waiting = [];
      for (const release of current) release();
      await flush();
    },
  };
}

describe("capsule write barrier", () => {
  it("coalesces quiet prompts to the latest text and never overlaps writes", async () => {
    const fake = recorder();
    const writes = createCapsuleWrites();
    writes.quiet("session-a", "first", fake.write);
    writes.quiet("session-a", "second", fake.write);
    await flush();
    // One write in flight, carrying the LATEST prompt of the run.
    expect(fake.started).toEqual(["second"]);

    writes.quiet("session-a", "third", fake.write);
    writes.quiet("session-a", "fourth", fake.write);
    await flush();
    expect(fake.started).toEqual(["second"]); // still queued, coalescing in place
    await fake.releaseAll();
    expect(fake.started).toEqual(["second", "fourth"]);
    expect(fake.maxConcurrent()).toBe(1);

    await fake.releaseAll();
    await writes.drain("session-a");
    expect(fake.started).toEqual(["second", "fourth"]);
  });

  it("keeps sessions independent", async () => {
    const fake = recorder();
    const writes = createCapsuleWrites();
    writes.quiet("session-a", "a-one", fake.write);
    writes.quiet("session-b", "b-one", fake.write);
    await flush();
    expect(fake.started).toEqual(["a-one", "b-one"]);
    await fake.releaseAll();
    await writes.drain("session-a");
    await writes.drain("session-b");
  });

  it("drains the running quiet write and discards the quiet prompt it supersedes", async () => {
    const fake = recorder();
    const writes = createCapsuleWrites();
    const order: string[] = [];
    writes.quiet("session-a", "quiet-a", fake.write);
    await flush();
    expect(fake.started).toEqual(["quiet-a"]);

    writes.quiet("session-a", "quiet-b", fake.write); // queued, not started
    const foreground = writes.foreground("session-a", async () => {
      order.push("foreground");
    });
    await flush();
    // The foreground write cannot run while the quiet spawn is still in flight.
    expect(order).toEqual([]);
    await fake.releaseAll();
    await foreground;
    expect(order).toEqual(["foreground"]);
    // "quiet-b" is older than the foreground write, so it never reaches the capsule.
    expect(fake.started).toEqual(["quiet-a"]);
  });

  it("runs a quiet prompt queued behind a foreground write after it", async () => {
    const fake = recorder();
    const writes = createCapsuleWrites();
    const gate: { resolve?: () => void } = {};
    let releaseForeground = (): void => undefined;
    const held = new Promise<void>((resolve) => {
      releaseForeground = resolve;
    });
    const foreground = writes.foreground("session-a", async () => {
      gate.resolve = releaseForeground;
      await held;
    });
    writes.quiet("session-a", "quiet-later", fake.write);
    await flush();
    expect(fake.started).toEqual([]);
    releaseForeground();
    await foreground;
    await flush();
    expect(fake.started).toEqual(["quiet-later"]);
  });

  it("drains work queued while draining, then reports idle", async () => {
    const fake = recorder();
    const writes = createCapsuleWrites();
    writes.quiet("session-a", "one", fake.write);
    await flush();
    let drained = false;
    const drain = writes.drain("session-a").then(() => {
      drained = true;
    });
    writes.quiet("session-a", "two", fake.write); // arrives mid-drain
    await fake.releaseAll();
    await flush();
    expect(drained).toBe(false);
    await fake.releaseAll();
    await drain;
    expect(fake.started).toEqual(["one", "two"]);
    expect(drained).toBe(true);
  });

  it("survives rejected writes and still surfaces a foreground failure", async () => {
    const writes = createCapsuleWrites();
    writes.quiet("session-a", "fails", async () => {
      throw new Error("spawn failed");
    });
    await flush();
    expect(await writes.foreground("session-a", async () => "ok")).toBe("ok");
    await expect(
      writes.foreground("session-a", async () => {
        throw new Error("foreground failed");
      }),
    ).rejects.toThrow("foreground failed");
    expect(await writes.foreground("session-a", async () => 1)).toBe(1);
    await writes.drain("session-a");
  });

  it("drains an unknown session immediately", async () => {
    const writes = createCapsuleWrites();
    await expect(writes.drain("never-seen")).resolves.toBeUndefined();
  });
});
