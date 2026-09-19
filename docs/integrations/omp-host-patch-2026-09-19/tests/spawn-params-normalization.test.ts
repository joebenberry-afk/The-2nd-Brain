/**
 * Deterministic regression for isolated-task normalization.
 *
 * The repairing patch must never replace upstream normalization: an item-level
 * isolation request has to survive into the per-spawn parameters (the object the
 * async dispatch hands to job registration), the flat value is only a fallback,
 * and an explicit `false` must stay false rather than being upgraded.
 *
 * Runs against the patched host source; needs no model and no session.
 */
import { describe, expect, test } from "bun:test";
import { spawnParamsFor } from "../../src/task/index";

type Params = Parameters<typeof spawnParamsFor>[0];
type Item = Parameters<typeof spawnParamsFor>[1];

const params = (extra: Record<string, unknown> = {}) =>
	({ agent: "task", task: "do the thing", ...extra }) as unknown as Params;
const item = (extra: Record<string, unknown> = {}) => ({ agent: "task", ...extra }) as unknown as Item;

// The forcing seam exists for canary runs only; it must not mask these assertions.
delete process.env.OM_CANARY_FORCE_ISOLATED;

describe("spawnParamsFor isolation normalization", () => {
	test("item-level explicit true survives into the per-spawn params", () => {
		expect(spawnParamsFor(params(), item({ isolated: true }), "task").isolated).toBe(true);
	});

	test("item-level explicit false is preserved, not upgraded by the flat value", () => {
		expect(spawnParamsFor(params({ isolated: true }), item({ isolated: false }), "task").isolated).toBe(false);
	});

	test("an absent item value falls back to the flat value", () => {
		expect(spawnParamsFor(params({ isolated: true }), item(), "task").isolated).toBe(true);
		expect(spawnParamsFor(params({ isolated: false }), item(), "task").isolated).toBe(false);
	});

	test("absent everywhere stays absent - no implicit isolation", () => {
		expect(spawnParamsFor(params(), item(), "task").isolated).toBeUndefined();
	});
});
