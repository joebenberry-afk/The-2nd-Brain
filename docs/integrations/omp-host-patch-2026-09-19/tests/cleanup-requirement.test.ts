/**
 * Cleanup-obligation gates (O1-O5): "cleanup not required" is an authoritative
 * classification, never the absence of a barrier and never a synthetic one.
 */
import { beforeEach, describe, expect, test } from "bun:test";
import {
	assertNoDowngrade,
	classifyCleanupRequirement,
	cleanupOperationId,
	releaseEligible,
	resetBarriers,
	settleBarrier,
	type CleanupIdentity,
} from "../../src/task/cleanup-barrier";

const identity = (route: "one-shot" | "deferred", generation = 0): CleanupIdentity => ({
	attemptId: "attempt-1",
	generation,
	cleanupOperationId: cleanupOperationId(route, "attempt-1", generation),
});

beforeEach(() => resetBarriers());

describe("cleanup obligation", () => {
	test("O1 one-shot with no owned resources is authoritatively none and may release", async () => {
		const requirement = classifyCleanupRequirement("one-shot", identity("one-shot"), {
			isolationResources: 0,
			registeredCleanupWork: 0,
		});
		expect(requirement.kind).toBe("none");
		let permitted = 0;
		const outcome = await releaseEligible(
			requirement,
			() => true,
			() => {
				permitted += 1;
			},
		);
		expect(outcome).toBe("released");
		expect(permitted).toBe(1);
	});

	test("O2 one-shot owning an isolation resource cannot be classified none", () => {
		const requirement = classifyCleanupRequirement("one-shot", identity("one-shot"), {
			isolationResources: 1,
			registeredCleanupWork: 0,
		});
		expect(requirement.kind).toBe("required");
	});

	test("O3 a required obligation with an unfinished barrier fails closed", async () => {
		const requirement = classifyCleanupRequirement("deferred", identity("deferred"), {
			isolationResources: 1,
			registeredCleanupWork: 0,
		});
		if (requirement.kind !== "required") throw new Error("expected required");
		const outcome = await Promise.race([
			releaseEligible(
				requirement,
				() => true,
				() => undefined,
			),
			new Promise<"pending">(r => setTimeout(() => r("pending"), 20)),
		]);
		expect(outcome).toBe("pending");
		expect(requirement.barrier.state).toBe("pending");
	});

	test("O4 deferred releases only through the exact resolved barrier", async () => {
		const id = identity("deferred");
		const requirement = classifyCleanupRequirement("deferred", id, {
			isolationResources: 0,
			registeredCleanupWork: 0,
		});
		if (requirement.kind !== "required") throw new Error("expected required");
		const pending = releaseEligible(
			requirement,
			() => true,
			() => undefined,
		);
		settleBarrier(requirement.barrier, { ok: true });
		expect(await pending).toBe("released");
	});

	test("O5 a required obligation can never be downgraded to none", () => {
		const required = classifyCleanupRequirement("deferred", identity("deferred"), {
			isolationResources: 1,
			registeredCleanupWork: 0,
		});
		const none = classifyCleanupRequirement("one-shot", identity("one-shot"), {
			isolationResources: 0,
			registeredCleanupWork: 0,
		});
		expect(() => assertNoDowngrade(required, none)).toThrow();
		expect(() => assertNoDowngrade(none, required)).not.toThrow();
	});
});

describe("classification idempotence (Astra finding 4)", () => {
	test("O6 a second classification cannot downgrade a live obligation to none", () => {
		const id = identity("one-shot");
		const first = classifyCleanupRequirement("one-shot", id, {
			isolationResources: 1,
			registeredCleanupWork: 0,
		});
		expect(first.kind).toBe("required");
		// A later evidence read that reports nothing must not downgrade the live
		// obligation: the canonical barrier already exists for this identity.
		const second = classifyCleanupRequirement("one-shot", id, {
			isolationResources: 0,
			registeredCleanupWork: 0,
		});
		expect(second.kind).toBe("required");
		if (second.kind === "required" && first.kind === "required") {
			expect(second.barrier).toBe(first.barrier);
		}
	});
});
