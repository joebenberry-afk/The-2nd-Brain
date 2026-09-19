/**
 * Cleanup-barrier gates (B1-B12). The barrier answers one question: has the real
 * cleanup operation for this exact execution reached a proven terminal state?
 */
import { describe, expect, test } from "bun:test";
import {
	createCleanupBarrier,
	cleanupOperationId,
	failBarrier,
	settleBarrier,
	type CleanupIdentity,
} from "../../src/task/cleanup-barrier";

const identity: CleanupIdentity = { attemptId: "attempt-1", generation: 0, cleanupOperationId: "cleanup-1" };
const make = (timeoutMs?: number) => createCleanupBarrier(identity, { timeoutMs });
describe("cleanup barrier", () => {
	test("B1 actual success resolves exactly once", async () => {
		const b = make();
		expect(settleBarrier(b, { ok: true })).toBe("resolved");
		await b.promise;
		expect(b.state).toBe("resolved");
		expect(b.timeline.filter(e => e.event === "resolved")).toHaveLength(1);
	});

	test("B2 actual rejection rejects and blocks release", async () => {
		const b = make();
		expect(settleBarrier(b, { ok: false, error: new Error("isoStop failed") })).toBe("rejected");
		await expect(b.promise).rejects.toThrow();
		expect(b.state).toBe("rejected");
	});

	test("B3 timeout rejects and a later success does not revive it", async () => {
		const b = createCleanupBarrier(identity, { timeoutMs: 1 });
		await new Promise(r => setTimeout(r, 10));
		expect(b.state).toBe("rejected");
		expect(settleBarrier(b, { ok: true })).toBe("duplicate");
		expect(b.state).toBe("rejected");
		expect(b.lateCompletions).toBe(1);
	});

	test("B4 stale sentinel (identity mismatch) fails closed", () => {
		const b = make();
		const stale: CleanupIdentity = { ...identity, generation: 1 };
		expect(settleBarrier(b, { ok: true }, Date.now(), stale)).toBe("identity-mismatch");
		expect(b.state).toBe("rejected");
	});

	test("B5 duplicate success settles once and is recorded", () => {
		const b = make();
		expect(settleBarrier(b, { ok: true })).toBe("resolved");
		expect(settleBarrier(b, { ok: true })).toBe("duplicate");
		expect(b.duplicateSettlements).toBe(1);
		expect(b.state).toBe("resolved");
	});

	test("B6 success then rejection keeps the first terminal settlement", () => {
		const b = make();
		settleBarrier(b, { ok: true });
		settleBarrier(b, { ok: false });
		expect(b.state).toBe("resolved");
	});

	test("B7 rejection then success stays blocked", () => {
		const b = make();
		settleBarrier(b, { ok: false });
		settleBarrier(b, { ok: true });
		expect(b.state).toBe("rejected");
		expect(b.lateCompletions).toBe(1);
	});

	test("B8 one-shot route settles the same canonical barrier shape", () => {
		const id = cleanupOperationId("one-shot", "attempt-1", 0);
		const b = make();
		expect(id.startsWith("one-shot:")).toBe(true);
		expect(settleBarrier(b, { ok: true })).toBe("resolved");
	});

	test("B9 deferred route converges on the same semantics", () => {
		const id = cleanupOperationId("deferred", "attempt-1", 0);
		const b = make();
		expect(id.startsWith("deferred:")).toBe(true);
		expect(settleBarrier(b, { ok: true })).toBe("resolved");
	});

	test("B10 cancellation while pending fails closed even if cleanup later completes", () => {
		const b = make();
		failBarrier(b, "cancelled");
		expect(b.state).toBe("rejected");
		settleBarrier(b, { ok: true });
		expect(b.state).toBe("rejected");
	});

	test("B11 cancellation after cleanup success does not unsettle the barrier", () => {
		const b = make();
		settleBarrier(b, { ok: true });
		failBarrier(b, "cancelled");
		expect(b.state).toBe("resolved");
		expect(b.duplicateSettlements).toBe(1);
	});

	test("B12 another execution's cleanup cannot settle this barrier", () => {
		const b = make();
		const other: CleanupIdentity = { attemptId: "attempt-2", generation: 0, cleanupOperationId: "cleanup-1" };
		expect(settleBarrier(b, { ok: true }, Date.now(), other)).toBe("identity-mismatch");
		expect(b.state).toBe("rejected");
	});
});
