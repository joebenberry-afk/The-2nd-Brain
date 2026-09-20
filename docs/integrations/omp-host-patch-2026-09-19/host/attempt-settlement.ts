/**
 * Attempt-scoped settlement facts for extension consumers.
 *
 * A spawned worker has three separate boundaries, and they are deliberately not the
 * same moment:
 *
 *  1. **result accepted** — the run's yield/result is available to the caller;
 *  2. **cleanup pending** — teardown that outlived its grace deadline (session
 *     disposal, advisor drain, owner-job reaping, isolation handle release) is still
 *     running;
 *  3. **settled** — every resource this attempt owns has finished, so an external
 *     owner of the same protected resource may be released.
 *
 * This registry records those transitions per attempt and lets an extension observe
 * them. It reports "settled" only when every tracked cleanup promise has *fulfilled*;
 * a rejected one is reported as `failed` and never as settlement — an `allSettled`
 * aggregate resolving is not evidence of success. Nothing here infers settlement from
 * elapsed time, job snapshots, terminal frames or abort requests.
 */

import { logger } from "@oh-my-pi/pi-utils";
import { appendFileSync as __bootAppend } from "node:fs";
const __boot = (step: string): void => {
	try {
		if (process.env.OM_CANARY_BOOT) {
			__bootAppend(process.env.OM_CANARY_BOOT, `${new Date().toISOString()} pid=${process.pid} ${step}\n`);
		}
	} catch {
		// boot trace only
	}
};
try {
	if (process.env.OM_CANARY_BOOT) {
		__bootAppend(process.env.OM_CANARY_BOOT, `${new Date().toISOString()} pid=${process.pid} module=canary-attempt-settlement\n`);
	}
} catch {
	// boot trace only
}

/** Version of the observation payload extensions must accept. */
export const ATTEMPT_SETTLEMENT_CAPABILITY_VERSION = 1;

export type AttemptCleanupState = "pending" | "settled" | "failed";

export interface AttemptSettlementIdentity {
	/** Host-minted identity, unique per spawn attempt within this process. */
	attemptId: string;
	/** Native worker (agent) id. */
	agentId: string;
	/** Async job id when the attempt runs as a background job. */
	jobId: string | null;
	/** Tool call that admitted the spawn, when the caller supplied one. */
	parentToolCallId: string | null;
	/** Spawn index inside a batch call, when the caller supplied one. */
	sourceIndex: number | null;
}

export type AttemptOutcome = "running" | "completed" | "failed" | "cancelled";

export interface AttemptSettlementSnapshot extends AttemptSettlementIdentity {
	capabilityVersion: typeof ATTEMPT_SETTLEMENT_CAPABILITY_VERSION;
	/** Monotonic attempt generation inside this host process. */
	generation: number;
	/** The run's result is available to the caller. */
	resultAccepted: boolean;
	/** The run's own outcome; independent of cleanup state. */
	outcome: AttemptOutcome;
	cleanupState: AttemptCleanupState;
	/** Resources whose cleanup is still running. */
	cleanupPendingResources: string[];
	/** Resources whose cleanup threw. */
	cleanupFailedResources: string[];
	/**
	 * True when an abort was reported after the outcome was accepted. The accepted
	 * outcome stays authoritative; this only records that cleanup observed a cancel.
	 */
	cancellationAfterAcceptance: boolean;
	/** True only when the result is accepted and every owned resource settled. */
	releasePermitted: boolean;
	/** Monotonic per attempt; a later revision supersedes earlier ones. */
	revision: number;
}

type Subscriber = (snapshot: AttemptSettlementSnapshot) => void;

interface AttemptRecord {
	identity: AttemptSettlementIdentity;
	generation: number;
	resultAccepted: boolean;
	outcome: AttemptOutcome;
	cancellationAfterAcceptance: boolean;
	cleanupState: AttemptCleanupState;
	pending: Set<string>;
	failed: Set<string>;
	revision: number;
	subscribers: Set<Subscriber>;
}

function snapshotOf(record: AttemptRecord): AttemptSettlementSnapshot {
	return {
		capabilityVersion: ATTEMPT_SETTLEMENT_CAPABILITY_VERSION,
		...record.identity,
		generation: record.generation,
		resultAccepted: record.resultAccepted,
		outcome: record.outcome,
		cancellationAfterAcceptance: record.cancellationAfterAcceptance,
		cleanupState: record.cleanupState,
		cleanupPendingResources: [...record.pending].sort(),
		cleanupFailedResources: [...record.failed].sort(),
		releasePermitted:
			record.resultAccepted && record.cleanupState === "settled" && record.pending.size === 0,
		revision: record.revision,
	};
}

/** Handle used by the executor to report one attempt's real transitions. */
export class AttemptSettlementHandle {
	readonly #record: AttemptRecord;
	readonly #deliver: (record: AttemptRecord) => void;

	constructor(record: AttemptRecord, deliver: (record: AttemptRecord) => void) {
		this.#record = record;
		this.#deliver = deliver;
	}

	get attemptId(): string {
		return this.#record.identity.attemptId;
	}

	/** Result is available to the caller; cleanup may still be running. */
	resultAccepted(outcome: AttemptOutcome): void {
		this.#record.resultAccepted = true;
		this.#record.outcome = outcome;
		this.#publish();
	}

	/**
	 * Register cleanup that outlived its grace deadline. Each promise's own outcome
	 * decides the state: fulfilled → settled, rejected → failed (never settlement).
	 */
	trackCleanups(
		entries: ReadonlyArray<{ resource: string; work: Promise<unknown> }>,
		outcome?: AttemptOutcome,
	): void {
		this.#applyOutcome(outcome);
		if (entries.length === 0) return;
		for (const entry of entries) {
			if (this.#record.pending.has(entry.resource) || this.#record.failed.has(entry.resource)) continue;
			this.#record.pending.add(entry.resource);
			void entry.work.then(
				() => {
					this.#record.pending.delete(entry.resource);
					this.#record.cleanupState = this.#record.failed.size > 0 ? "failed" : "settled";
					this.#publish();
				},
				error => {
					this.#record.pending.delete(entry.resource);
					this.#record.failed.add(entry.resource);
					this.#record.cleanupState = "failed";
					logger.warn("Attempt cleanup failed", {
						attemptId: this.#record.identity.attemptId,
						resource: entry.resource,
						error: error instanceof Error ? error.message : String(error),
					});
					this.#publish();
				},
			);
		}
		this.#publish();
	}

	/** No cleanup was deferred: every owned resource finished inside the run. */
	cleanupComplete(outcome?: AttemptOutcome): void {
		this.#applyOutcome(outcome);
		if (this.#record.failed.size > 0) {
			this.#record.cleanupState = "failed";
		} else if (this.#record.pending.size === 0) {
			this.#record.cleanupState = "settled";
		}
		this.#publish();
	}

	/** Explicit failure with no promise to await. */
	cleanupFailed(resource: string, error?: unknown): void {
		this.#record.pending.delete(resource);
		this.#record.failed.add(resource);
		this.#record.cleanupState = "failed";
		logger.warn("Attempt cleanup reported failed", {
			attemptId: this.#record.identity.attemptId,
			resource,
			error: error instanceof Error ? error.message : typeof error === "string" ? error : undefined,
		});
		this.#publish();
	}

	/**
	 * The run's outcome is decided once, at acceptance, and is immutable after it.
	 * The durable ledger rejects a changed terminal outcome (OUTCOME_CONFLICT) and
	 * then quarantines the writer without proving cleanup, which blocks successor
	 * admission for that worktree. A cancellation that arrives after acceptance is
	 * therefore recorded as its own fact (`cancellationAfterAcceptance`) instead of
	 * rewriting the outcome; cleanup progress continues to be reported through
	 * `cleanupState`/`releasePermitted`, and `exitCode` salvage (e.g. a missing-yield
	 * warning) can never rewrite an accepted outcome either.
	 */
	#applyOutcome(outcome?: AttemptOutcome): void {
		if (outcome === undefined) return;
		if (!this.#record.resultAccepted) {
			this.#record.outcome = outcome;
			return;
		}
		if (outcome === "cancelled" && this.#record.outcome !== "cancelled") {
			this.#record.cancellationAfterAcceptance = true;
		}
	}

	snapshot(): AttemptSettlementSnapshot {
		return snapshotOf(this.#record);
	}

	#publish(): void {
		__boot(`publish:${this.#record.identity.agentId}:${this.#record.cleanupState}`);
		this.#record.revision += 1;
		// Delivery goes through the registry: subscribers are registered while a
		// dispatch is being prepared, i.e. before this attempt exists.
		this.#deliver(this.#record);
	}
}

/** Process-global registry; workers can be spawned by any session in the process. */
export class AttemptSettlementRegistry {
	static #instance: AttemptSettlementRegistry | undefined;

	static instance(): AttemptSettlementRegistry {
		AttemptSettlementRegistry.#instance ??= new AttemptSettlementRegistry();
		return AttemptSettlementRegistry.#instance;
	}

	#attempts = new Map<string, AttemptRecord>();
	#order: string[] = [];
	#sequence = 0;
	/**
	 * Subscribers live at the registry level, not on individual attempts: a consumer
	 * subscribes while preparing a dispatch, which is *before* the executor registers
	 * the attempt, so binding subscribers only to existing records would silently drop
	 * every observation for that dispatch.
	 */
	#subscribers = new Set<{ subscriber: Subscriber; sourceToolCallId?: string }>();

	/** Bounded retention so a long session cannot grow without limit. */
	readonly #retention: number;

	constructor(retention = 256) {
		this.#retention = retention;
	}

	begin(identity: Omit<AttemptSettlementIdentity, "attemptId"> & { attemptId?: string }): AttemptSettlementHandle {
		this.#sequence += 1;
		__boot(`begin:${identity.agentId}:call=${identity.parentToolCallId}:idx=${identity.sourceIndex}:job=${identity.jobId}`);
		const attemptId = identity.attemptId ?? `${process.pid}:${this.#sequence}:${identity.agentId}`;
		const record: AttemptRecord = {
			generation: this.#sequence,
			outcome: "running",
			identity: {
				attemptId,
				agentId: identity.agentId,
				jobId: identity.jobId,
				parentToolCallId: identity.parentToolCallId,
				sourceIndex: identity.sourceIndex,
			},
			resultAccepted: false,
			cancellationAfterAcceptance: false,
			cleanupState: "pending",
			pending: new Set<string>(),
			failed: new Set<string>(),
			revision: 0,
			subscribers: new Set<Subscriber>(),
		};
		this.#attempts.set(attemptId, record);
		this.#order.push(attemptId);
		while (this.#order.length > this.#retention) {
			const evicted = this.#order.shift();
			if (evicted !== undefined) this.#attempts.delete(evicted);
		}
		return new AttemptSettlementHandle(record, candidate => this.#deliver(candidate));
	}

	/** Current snapshot, or null when the attempt is unknown or already evicted. */
	get(attemptId: string): AttemptSettlementSnapshot | null {
		const record = this.#attempts.get(attemptId);
		return record === undefined ? null : snapshotOf(record);
	}

	/**
	 * Subscribe to transition snapshots. With `sourceToolCallId`, only that call's
	 * attempts are delivered, and a late subscriber first receives the current
	 * snapshot of any matching in-flight attempt so a fast completion cannot be missed.
	 */
	observe(subscriber: Subscriber, filter?: { sourceToolCallId?: string }): () => void {
		const entry = { subscriber, sourceToolCallId: filter?.sourceToolCallId };
		this.#subscribers.add(entry);
		__boot(
			`observe:filter=${entry.sourceToolCallId ?? "none"}:attempts=${this.#attempts.size}:subscribers=${this.#subscribers.size}`,
		);
		let replayed = 0;
		for (const record of this.#attempts.values()) {
			if (!this.#matches(entry, record)) continue;
			replayed += 1;
			this.#notify(entry, record);
		}
		__boot(`observe-replay:matched=${replayed}`);
		return () => {
			this.#subscribers.delete(entry);
		};
	}

	#matches(entry: { sourceToolCallId?: string }, record: AttemptRecord): boolean {
		return entry.sourceToolCallId === undefined || record.identity.parentToolCallId === entry.sourceToolCallId;
	}

	#notify(entry: { subscriber: Subscriber }, record: AttemptRecord): void {
		try {
			entry.subscriber(snapshotOf(record));
		} catch (error) {
			logger.warn("Attempt settlement subscriber threw", {
				attemptId: record.identity.attemptId,
				error: error instanceof Error ? error.message : String(error),
			});
		}
	}

	#deliver(record: AttemptRecord): void {
		let matched = 0;
		for (const entry of this.#subscribers) {
			if (this.#matches(entry, record)) {
				matched += 1;
				this.#notify(entry, record);
			}
		}
		__boot(
			`deliver:${record.identity.agentId}:subs=${this.#subscribers.size}:matched=${matched}:call=${record.identity.parentToolCallId}`,
		);
	}
}
