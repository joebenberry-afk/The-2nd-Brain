/**
 * Integration gates (I1-I10): both host cleanup routes must await the exact
 * barrier that the real cleanup path settles, with no alternate release
 * authority. These exercise the production seam functions (barrierFor,
 * releaseWhenProven) rather than re-testing the components in isolation.
 */
import { beforeEach, describe, expect, test } from "bun:test";
import {
	barrierFor,
	cleanupOperationId,
	failBarrier,
	resetBarriers,
	releaseWhenProven,
	settleBarrier,
	type CleanupIdentity,
} from "../../src/task/cleanup-barrier";

const idFor = (route: "one-shot" | "deferred", generation = 0): CleanupIdentity => ({
	attemptId: "attempt-1",
	generation,
	cleanupOperationId: cleanupOperationId(route, "attempt-1", generation),
});

beforeEach(() => resetBarriers());

describe("barrier integration", () => {
	test("I1 one-shot identity continuity: dispatch and release share one object", () => {
		const identity = idFor("one-shot");
		const atDispatch = barrierFor(identity);
		const atRelease = barrierFor(identity);
		expect(atRelease).toBe(atDispatch);
		settleBarrier(atDispatch, { ok: true });
		expect(atRelease.state).toBe("resolved");
	});

	test("I2 deferred identity continuity: same guarantee on the deferred route", () => {
		const identity = idFor("deferred");
		const atDispatch = barrierFor(identity);
		expect(barrierFor(identity)).toBe(atDispatch);
		settleBarrier(atDispatch, { ok: true });
		expect(atDispatch.state).toBe("resolved");
	});

	test("I3 a sentinel claiming clean cannot bypass a pending barrier", async () => {
		const barrier = barrierFor(idFor("one-shot"));
		let sentinelSaysClean = true;
		let permitCalls = 0;
		const outcome = await Promise.race([
			releaseWhenProven(
				barrier,
				() => sentinelSaysClean,
				() => {
					permitCalls += 1;
				},
			),
			new Promise<"still-blocked">(r => setTimeout(() => r("still-blocked"), 20)),
		]);
		expect(outcome).toBe("still-blocked");
		expect(permitCalls).toBe(0);
		expect(barrier.state).toBe("pending");
	});

	test("I4 real cleanup success resolves the exact barrier and releases", async () => {
		const identity = idFor("one-shot");
		const barrier = barrierFor(identity);
		const release = releaseWhenProven(
			barrier,
			() => true,
			() => undefined,
		);
		settleBarrier(barrierFor(identity), { ok: true });
		expect(await release).toBe("released");
	});

	test("I5 cleanup rejection propagates and the successor never releases", async () => {
		const identity = idFor("deferred");
		const barrier = barrierFor(identity);
		const release = releaseWhenProven(
			barrier,
			() => true,
			() => undefined,
		);
		settleBarrier(barrier, { ok: false, error: new Error("isoStop failed") });
		expect(await release).toBe("blocked");
	});

	test("I6 a callback that never arrives (timeout) blocks the successor", async () => {
		const barrier = barrierFor(idFor("one-shot"), { timeoutMs: 1 });
		const outcome = await releaseWhenProven(
			barrier,
			() => true,
			() => undefined,
		);
		expect(outcome).toBe("blocked");
		expect(barrier.state).toBe("rejected");
	});

	test("I7 cancel while cleanup is pending cannot be resurrected by later success", async () => {
		const barrier = barrierFor(idFor("one-shot"));
		failBarrier(barrier, "cancelled");
		const outcome = await releaseWhenProven(
			barrier,
			() => true,
			() => undefined,
		);
		expect(outcome).toBe("blocked");
		settleBarrier(barrier, { ok: true });
		expect(barrier.state).toBe("rejected");
	});

	test("I8 cancel after cleanup success leaves the cleanup fact true", async () => {
		const identity = idFor("one-shot");
		const barrier = barrierFor(identity);
		settleBarrier(barrier, { ok: true });
		expect(await releaseWhenProven(barrier, () => true, () => undefined)).toBe("released");
		expect(barrier.state).toBe("resolved");
		// Successor eligibility is the caller's revalidation, not the barrier's.
		const second = barrierFor(idFor("deferred"));
		settleBarrier(second, { ok: true });
		expect(await releaseWhenProven(second, () => false, () => undefined)).toBe("blocked");
	});

	test("I9 a stale callback cannot settle the active barrier", () => {
		const barrier = barrierFor(idFor("one-shot", 0));
		const stale: CleanupIdentity = { ...idFor("one-shot", 0), generation: 3 };
		expect(settleBarrier(barrier, { ok: true }, Date.now(), stale)).toBe("identity-mismatch");
		expect(barrier.state).toBe("rejected");
	});

	test("I10 both routes differ only in mechanics, never in release authority", async () => {
		const oneShot = barrierFor(idFor("one-shot"));
		const deferred = barrierFor(idFor("deferred"));
		expect(oneShot).not.toBe(deferred);
		settleBarrier(oneShot, { ok: true });
		settleBarrier(deferred, { ok: false });
		expect(await releaseWhenProven(oneShot, () => true, () => undefined)).toBe("released");
		expect(await releaseWhenProven(deferred, () => true, () => undefined)).toBe("blocked");
	});

	test("negative: cleanup function returning is not cleanup completion", async () => {
		const barrier = barrierFor(idFor("one-shot"));
		let cleanupFunctionReturned = true;
		const outcome = await Promise.race([
			releaseWhenProven(
				barrier,
				() => cleanupFunctionReturned,
				() => undefined,
			),
			new Promise<"still-pending">(r => setTimeout(() => r("still-pending"), 20)),
		]);
		expect(cleanupFunctionReturned).toBe(true);
		expect(outcome).toBe("still-pending");
		expect(barrier.state).toBe("pending");
	});
});
