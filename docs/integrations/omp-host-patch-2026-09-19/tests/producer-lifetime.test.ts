/**
 * Producer-lifetime gate: a producer retained by the manager stays accounted
 * for across job eviction and a timed-out dispose. An empty job map or a
 * completed callback must never be read as producer quiescence.
 */
import { describe, expect, test } from "bun:test";
import { AsyncJobManager } from "../../src/async/job-manager";

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

describe("producer lifetime", () => {
  test("a retained producer survives a timed-out dispose and is still awaited", async () => {
    const manager = new AsyncJobManager({});
    let release!: () => void;
    const gate = new Promise<void>(resolve => {
      release = resolve;
    });
    let producerSettled = false;
    manager.register(
      "bash",
      "delayed producer",
      async () => {
        await gate;
        producerSettled = true;
        return "done";
      },
      { ownerId: "owner-a" },
    );
    await manager.dispose({ timeoutMs: 20 });
    let drained = false;
    const drain = manager.waitForProducers("owner-a").then(() => {
      drained = true;
    });
    await sleep(30);
    expect(drained).toBe(false);
    expect(producerSettled).toBe(false);
    release();
    await drain;
    expect(producerSettled).toBe(true);
  });
});
