/**
 * Attempt settlement outcome immutability (audit F-06).
 *
 * The run's outcome is decided once, at acceptance, and nothing that happens during
 * cleanup may rewrite it. The durable ledger rejects a changed terminal outcome
 * (OUTCOME_CONFLICT) and then quarantines the writer without proving cleanup, which
 * blocks successor admission for that worktree; the host must therefore report the
 * accepted outcome and, separately, that cleanup observed a cancellation.
 */
import { describe, expect, test } from "bun:test";
import { AttemptSettlementRegistry } from "../../src/task/attempt-settlement";

const begin = () => {
	const registry = new AttemptSettlementRegistry();
	return registry.begin({
		agentId: "worker-a",
		jobId: null,
		parentToolCallId: "call-1",
		sourceIndex: null,
	});
};

describe("attempt settlement outcome immutability", () => {
	test("F-06a an accepted failed outcome survives a cleanup-time cancellation", () => {
		const handle = begin();
		handle.resultAccepted("failed");

		handle.cleanupComplete("cancelled");

		const snapshot = handle.snapshot();
		expect(snapshot.outcome).toBe("failed");
		expect(snapshot.cancellationAfterAcceptance).toBe(true);
		expect(snapshot.cleanupState).toBe("settled");
		expect(snapshot.releasePermitted).toBe(true);
	});

	test("F-06b an accepted completed outcome survives a cancellation too", () => {
		const handle = begin();
		handle.resultAccepted("completed");

		handle.cleanupComplete("cancelled");

		const snapshot = handle.snapshot();
		expect(snapshot.outcome).toBe("completed");
		expect(snapshot.cancellationAfterAcceptance).toBe(true);
	});

	test("F-06c deferred cleanup cannot rewrite the accepted outcome", () => {
		const handle = begin();
		handle.resultAccepted("failed");

		handle.trackCleanups(
			[{ resource: "isolation-handle", work: Promise.resolve() }],
			"cancelled",
		);

		expect(handle.snapshot().outcome).toBe("failed");
	});

	test("F-06d cancellation before acceptance is still the run's outcome", () => {
		const handle = begin();

		handle.cleanupComplete("cancelled");

		const snapshot = handle.snapshot();
		expect(snapshot.outcome).toBe("cancelled");
		expect(snapshot.cancellationAfterAcceptance).toBe(false);
	});

	test("F-06e a failed cleanup keeps the accepted outcome and never releases", () => {
		const handle = begin();
		handle.resultAccepted("failed");

		handle.cleanupFailed("isolation-handle");

		const snapshot = handle.snapshot();
		expect(snapshot.outcome).toBe("failed");
		expect(snapshot.cleanupState).toBe("failed");
		expect(snapshot.releasePermitted).toBe(false);
	});
});
