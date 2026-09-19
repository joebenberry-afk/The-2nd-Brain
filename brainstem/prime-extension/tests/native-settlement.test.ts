import { describe, expect, it, vi } from "vitest";
import {
  createNativeSettlementObserver,
  nativeJobIdForAgent,
  type NativeSettlementSource,
  type NativeSubagentLifecycleFrame,
} from "../src/native-settlement";
import type { AsyncJobLifecycleObservation } from "../types/prime";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

/** ES2022 lib has no `Promise.withResolvers`, so tests build the deferred locally. */
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function source(): NativeSettlementSource & {
  push: (frame: NativeSubagentLifecycleFrame) => void;
  listeners: number;
} {
  const handlers = new Set<(frame: NativeSubagentLifecycleFrame) => void>();
  return {
    listeners: 0,
    subscribe(handler) {
      handlers.add(handler);
      this.listeners = handlers.size;
      return () => {
        handlers.delete(handler);
        this.listeners = handlers.size;
      };
    },
    snapshot: () => ({ running: [], recent: [] }),
    push(frame) {
      for (const handler of handlers) handler(frame);
    },
  };
}

/**
 * Emit recorder whose `next()` resolves on the next durable emission, so tests wait
 * on the observed signal instead of a wall-clock delay.
 */
function recorder() {
  const emitted: AsyncJobLifecycleObservation[] = [];
  const waiters: Array<() => void> = [];
  return {
    emitted,
    emit: (observation: Readonly<AsyncJobLifecycleObservation>) => {
      emitted.push(observation as AsyncJobLifecycleObservation);
      waiters.shift()?.();
      return true;
    },
    next: () => {
      const gate = deferred<void>();
      waiters.push(() => gate.resolve());
      return gate.promise;
    },
  };
}

describe("native settlement observer (stock OMP signals)", () => {
  it("derives a settled observation from a post-finalization lifecycle frame", async () => {
    const bus = source();
    const sink = recorder();
    createNativeSettlementObserver({
      sourceToolCallId: "call-1",
      source: bus,
      cleanupProvenByFrame: true,
      attemptIdentity: (index) =>
        index === 0 ? { nativeAttemptId: "epoch:1", generation: 1 } : undefined,
      emit: sink.emit,
    });

    const settled = sink.next();
    bus.push({ id: "WorkerA", parentToolCallId: "call-1", index: 0, status: "completed" });
    await settled;

    expect(sink.emitted).toHaveLength(1);
    expect(sink.emitted[0]).toMatchObject({
      type: "task",
      agentId: "WorkerA",
      jobId: "WorkerA",
      sourceToolCallId: "call-1",
      sourceIndex: 0,
      status: "completed",
      executorSettled: true,
      cleanupComplete: true,
      revision: 1,
      generation: 1,
      nativeAttemptId: "epoch:1",
    });
  });

  it("ignores non-terminal frames, other calls and unadmitted spawns without inventing settlement", () => {
    const bus = source();
    const sink = recorder();
    const unresolved: string[] = [];
    createNativeSettlementObserver({
      sourceToolCallId: "call-1",
      source: bus,
      cleanupProvenByFrame: false,
      attemptIdentity: (index) =>
        index === 0 ? { nativeAttemptId: "epoch:1", generation: 1 } : undefined,
      emit: sink.emit,
      onUnresolved: (detail) => unresolved.push(detail.reason),
    });

    bus.push({ id: "WorkerA", parentToolCallId: "call-1", index: 0, status: "started" });
    bus.push({ id: "WorkerB", parentToolCallId: "call-other", index: 0, status: "completed" });
    bus.push({ id: "WorkerC", parentToolCallId: "call-1", index: 7, status: "completed" });

    expect(sink.emitted).toHaveLength(0);
    expect(unresolved).toEqual(["NATIVE_SETTLEMENT_ATTEMPT_UNKNOWN"]);
  });

  it("maps an aborted worker to a cancelled outcome rather than a success", async () => {
    const bus = source();
    const sink = recorder();
    createNativeSettlementObserver({
      sourceToolCallId: "call-2",
      source: bus,
      cleanupProvenByFrame: false,
      attemptIdentity: () => ({ nativeAttemptId: "epoch:2", generation: 2 }),
      emit: sink.emit,
    });

    const settled = sink.next();
    bus.push({ id: "WorkerA", parentToolCallId: "call-2", index: 0, status: "aborted" });
    await settled;

    expect(sink.emitted[0]?.status).toBe("cancelled");
    expect(sink.emitted[0]?.executorSettled).toBe(true);
  });

  it("uses the native job id from the snapshot when the host exposes one", async () => {
    const bus = source();
    bus.snapshot = () => ({
      running: [],
      recent: [{ id: "job-42", type: "task", status: "completed", agentId: "WorkerA" }],
    });
    const sink = recorder();
    createNativeSettlementObserver({
      sourceToolCallId: "call-3",
      source: bus,
      cleanupProvenByFrame: false,
      attemptIdentity: () => ({ nativeAttemptId: "epoch:3", generation: 3 }),
      emit: sink.emit,
    });

    const settled = sink.next();
    bus.push({ id: "WorkerA", parentToolCallId: "call-3", index: 0, status: "completed" });
    await settled;

    expect(sink.emitted[0]?.jobId).toBe("job-42");
  });

  it("advances the revision per attempt and stops after disposal", async () => {
    const bus = source();
    const sink = recorder();
    const dispose = createNativeSettlementObserver({
      sourceToolCallId: "call-4",
      source: bus,
      cleanupProvenByFrame: false,
      attemptIdentity: () => ({ nativeAttemptId: "epoch:4", generation: 4 }),
      emit: sink.emit,
    });

    const first = sink.next();
    bus.push({ id: "WorkerA", parentToolCallId: "call-4", index: 0, status: "completed" });
    await first;
    const second = sink.next();
    bus.push({ id: "WorkerA", parentToolCallId: "call-4", index: 0, status: "completed" });
    await second;
    expect(sink.emitted.map((item) => item.revision)).toEqual([1, 2]);

    dispose();
    bus.push({ id: "WorkerA", parentToolCallId: "call-4", index: 0, status: "completed" });
    expect(sink.emitted).toHaveLength(2);
    expect(bus.listeners).toBe(0);
  });

  it("resolves the native job id only from real snapshot rows", () => {
    expect(nativeJobIdForAgent(null, "WorkerA")).toBeNull();
    expect(nativeJobIdForAgent({ running: [{ id: "job-1", agentId: "WorkerA" }] }, "WorkerA")).toBe(
      "job-1",
    );
    expect(nativeJobIdForAgent({ recent: [{ id: "job-2", agentId: "Other" }] }, "WorkerA")).toBeNull();
  });

  it("never throws into the host when the durable emit rejects", async () => {
    const bus = source();
    const onError = vi.fn();
    process.once("uncaughtException", onError);
    const failed = deferred<void>();
    createNativeSettlementObserver({
      sourceToolCallId: "call-5",
      source: bus,
      cleanupProvenByFrame: false,
      attemptIdentity: () => ({ nativeAttemptId: "epoch:5", generation: 5 }),
      emit: async () => {
        failed.resolve();
        throw new Error("durable unavailable");
      },
    });

    bus.push({ id: "WorkerA", parentToolCallId: "call-5", index: 0, status: "completed" });
    await failed.promise;
    process.removeListener("uncaughtException", onError);
    expect(onError).not.toHaveBeenCalled();
  });
});
