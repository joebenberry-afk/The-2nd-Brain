/**
 * Cleanup barrier: one promise, one cleanup operation, one terminal settlement.
 *
 * The barrier answers exactly one question - has the real cleanup operation for
 * this exact execution reached a proven terminal state - and nothing else. It
 * does not decide ownership, census completeness, generation validity or
 * successor eligibility; those live upstream (identity/census) and downstream
 * (release).
 *
 * Success is deliberately narrow: only the authoritative cleanup completion
 * resolves the barrier. A scheduled cleanup, a registered callback, a returned
 * cleanup function, an empty queue, a vanished sentinel or a timeout that did not
 * fire are NOT success - each can precede a later failure.
 *
 * Failure is aggressive: rejection, timeout, cancellation, a mismatched identity,
 * a callback that never arrives, duplicate settlement and late settlement after a
 * terminal outcome all fail closed. A failure is never converted into release
 * eligibility because the caller can no longer observe cleanup.
 */

export type BarrierState = "pending" | "resolved" | "rejected";

export interface CleanupIdentity {
	/** The exact execution this cleanup belongs to. */
	attemptId: string;
	/** Host generation: a number or its canonical string form. */
	generation: number | string;
	/** Identity of the cleanup operation itself. */
	cleanupOperationId: string;
}

export interface CleanupResult {
	ok: boolean;
	error?: unknown;
}

export type BarrierFailure = "cleanup-rejected" | "timeout" | "cancelled" | "identity-mismatch";

export type BarrierTimelineEvent =
	| { event: "armed"; at: number }
	| { event: "resolved"; at: number }
	| { event: "rejected"; at: number; reason: BarrierFailure }
	| { event: "duplicate-settlement"; at: number; ok: boolean }
	| { event: "late-completion"; at: number; ok: boolean };

export interface CleanupBarrier {
	readonly identity: CleanupIdentity;
	readonly promise: Promise<void>;
	state: BarrierState;
	readonly timeline: BarrierTimelineEvent[];
	duplicateSettlements: number;
	lateCompletions: number;
	settledAt?: number;
}

export interface BarrierOptions {
	timeoutMs?: number;
	now?: () => number;
}

interface Internals {
	resolve: () => void;
	reject: (error: unknown) => void;
}

const INTERNALS = new WeakMap<CleanupBarrier, Internals>();

export type SettlementOutcome = "resolved" | "rejected" | "duplicate" | "identity-mismatch";

const sameIdentity = (a: CleanupIdentity, b: CleanupIdentity): boolean =>
	a.attemptId === b.attemptId &&
	String(a.generation) === String(b.generation) &&
	a.cleanupOperationId === b.cleanupOperationId;

/**
 * Raw constructor. NOT canonical: it bypasses the registry, so a caller can end
 * up with a barrier that no other participant can reach. Production paths must
 * use barrierFor(); this exists for tests and for building the registry entry.
 */
export function createCleanupBarrier(identity: CleanupIdentity, options: BarrierOptions = {}): CleanupBarrier {
	if (
		!identity.attemptId ||
		!identity.cleanupOperationId ||
		identity.generation === undefined ||
		identity.generation === null
	) {
		throw new Error("cleanup barrier requires attemptId, generation and cleanupOperationId");
	}
	const now = options.now ?? (() => Date.now());
	let resolveFn: () => void = () => {};
	let rejectFn: (error: unknown) => void = () => {};
	const promise = new Promise<void>((res, rej) => {
		resolveFn = res;
		rejectFn = rej;
	});
	// Release awaits this promise; an unhandled rejection must never crash the host
	// while the rejection stays observable through the barrier's state.
	void promise.catch(() => {});
	const barrier: CleanupBarrier = {
		identity,
		promise,
		state: "pending",
		timeline: [{ event: "armed", at: now() }],
		duplicateSettlements: 0,
		lateCompletions: 0,
	};
	INTERNALS.set(barrier, { resolve: resolveFn, reject: rejectFn });
	if (options.timeoutMs !== undefined) {
		const timer = setTimeout(() => failBarrier(barrier, "timeout", now()), Math.max(0, options.timeoutMs));
		timer.unref?.();
	}
	return barrier;
}

/** Settle the barrier from the authoritative cleanup outcome. */
export function settleBarrier(
	barrier: CleanupBarrier,
	result: CleanupResult,
	at = Date.now(),
	identity: CleanupIdentity = barrier.identity,
): SettlementOutcome {
	if (!sameIdentity(barrier.identity, identity)) {
		failBarrier(barrier, "identity-mismatch", at);
		return "identity-mismatch";
	}
	if (barrier.state !== "pending") {
		barrier.duplicateSettlements += 1;
		barrier.timeline.push({ event: "duplicate-settlement", at, ok: result.ok });
		if (barrier.state === "rejected" && result.ok) {
			// Completion after a terminal failure is reconciliation evidence only: it
			// must never retroactively convert that failure into eligibility.
			barrier.lateCompletions += 1;
			barrier.timeline.push({ event: "late-completion", at, ok: true });
		}
		return "duplicate";
	}
	const internals = INTERNALS.get(barrier);
	if (result.ok) {
		barrier.state = "resolved";
		barrier.settledAt = at;
		barrier.timeline.push({ event: "resolved", at });
		internals?.resolve();
		return "resolved";
	}
	barrier.state = "rejected";
	barrier.settledAt = at;
	barrier.timeline.push({ event: "rejected", at, reason: "cleanup-rejected" });
	internals?.reject(result.error ?? new Error("cleanup rejected"));
	return "rejected";
}

/** Fail the barrier closed: timeout, cancellation and identity mismatch are not success. */
export function failBarrier(barrier: CleanupBarrier, reason: BarrierFailure, at = Date.now()): void {
	if (barrier.state !== "pending") {
		barrier.duplicateSettlements += 1;
		barrier.timeline.push({ event: "duplicate-settlement", at, ok: false });
		return;
	}
	barrier.state = "rejected";
	barrier.settledAt = at;
	barrier.timeline.push({ event: "rejected", at, reason });
	INTERNALS.get(barrier)?.reject(new Error(`cleanup not proven: ${reason}`));
}

/** Routes that must converge on the same canonical barrier semantics. */
export type CleanupRoute = "one-shot" | "deferred";

export function cleanupOperationId(
	route: CleanupRoute,
	attemptId: string,
	generation: number | string,
): string {
	return `${route}:${attemptId}:${String(generation)}`;
}

/**
 * One barrier per cleanup operation, for the whole process.
 *
 * Identity continuity is structural rather than conventional: the dispatch path
 * and the release path ask for the barrier by identity and receive the same
 * object, so a reconstructed second barrier cannot become an alternate release
 * authority.
 */
const BARRIERS = new Map<string, CleanupBarrier>();

export function barrierKey(identity: CleanupIdentity): string {
	return `${identity.attemptId}:${String(identity.generation)}:${identity.cleanupOperationId}`;
}

export function barrierFor(identity: CleanupIdentity, options: BarrierOptions = {}): CleanupBarrier {
	const key = barrierKey(identity);
	const existing = BARRIERS.get(key);
	if (existing) return existing;
	const created = createCleanupBarrier(identity, options);
	BARRIERS.set(key, created);
	return created;
}

/** Test/runtime reset hook; production paths never clear live barriers. */
export function resetBarriers(): void {
	BARRIERS.clear();
}

export type ReleaseOutcome = "released" | "blocked";

/**
 * Await the barrier, then revalidate and permit release in one step.
 *
 * The revalidation runs after the barrier settles and immediately before the
 * caller's short atomic transition, so release never merely reads a state and
 * then races with cancellation or a newer attempt.
 */
export async function releaseWhenProven(
	barrier: CleanupBarrier,
	revalidate: () => boolean | Promise<boolean>,
	permit: () => void | Promise<void>,
): Promise<ReleaseOutcome> {
	try {
		await barrier.promise;
	} catch {
		return "blocked";
	}
	if (barrier.state !== "resolved") return "blocked";
	const decision = revalidate();
	if (decision === false) return "blocked";
	if (decision !== true) {
		// Only an explicitly asynchronous revalidation costs a turn; a synchronous
		// answer keeps permit() adjacent to the check, narrowing the window in which
		// a queued microtask could cancel or supersede this attempt.
		if (!(await decision)) return "blocked";
	}
	await permit();
	return "released";
}

/**
 * Cleanup obligation: distinguishes "cleanup proven complete" from "cleanup not
 * required for this execution". The second must never be inferred from a barrier
 * that simply does not exist, and never manufactured as an already-resolved
 * barrier - a missing barrier is not success.
 */
export type CleanupRequirement =
	| {
			kind: "none";
			reason: "no-isolation-resources";
			attemptId: string;
			generation: number;
	  }
	| { kind: "required"; barrier: CleanupBarrier };

export interface RouteEvidence {
	/** Authoritative route facts, read from the route's own resource state. */
	isolationResources: number;
	registeredCleanupWork: number;
}

export function classifyCleanupRequirement(
	route: CleanupRoute,
	identity: CleanupIdentity,
	evidence: RouteEvidence,
	options: BarrierOptions = {},
): CleanupRequirement {
	// Idempotence: once a canonical barrier exists for this identity, the
	// obligation is required regardless of what a later evidence read reports. A
	// second classification must never downgrade a live obligation to none.
	const existingKey = barrierKey(identity);
	if (BARRIERS.has(existingKey)) {
		return { kind: "required", barrier: BARRIERS.get(existingKey) as CleanupBarrier };
	}
	if (evidence.isolationResources > 0 || evidence.registeredCleanupWork > 0) {
		// This execution owns something; it cannot be classified as nothing.
		return { kind: "required", barrier: barrierFor(identity, options) };
	}
	if (route === "one-shot" && evidence.isolationResources === 0 && evidence.registeredCleanupWork === 0) {
		return {
			kind: "none",
			reason: "no-isolation-resources",
			attemptId: identity.attemptId,
			generation: Number(identity.generation),
		};
	}
	// A route that can acquire isolation resources is never pre-classified as none.
	return { kind: "required", barrier: barrierFor(identity, options) };
}

/** Downgrading a required obligation to none is not a legal transition. */
export function assertNoDowngrade(previous: CleanupRequirement, next: CleanupRequirement): void {
	if (previous.kind === "required" && next.kind === "none") {
		throw new Error("cleanup requirement cannot be downgraded from required to none");
	}
}

/**
 * One release gate for both proof forms: authoritative CLEANUP_NOT_REQUIRED, or
 * an exact resolved barrier. The revalidation runs after the proof and
 * immediately before the caller's short atomic release transition.
 */
export async function releaseEligible(
	requirement: CleanupRequirement,
	revalidate: () => boolean | Promise<boolean>,
	permit: () => void | Promise<void>,
): Promise<ReleaseOutcome> {
	if (requirement.kind === "required") {
		return releaseWhenProven(requirement.barrier, revalidate, permit);
	}
	const decision = revalidate();
	if (decision === false) return "blocked";
	if (decision !== true && !(await decision)) return "blocked";
	await permit();
	return "released";
}
