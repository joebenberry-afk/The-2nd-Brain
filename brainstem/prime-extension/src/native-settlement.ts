/**
 * Native settlement observation for stock OMP hosts.
 *
 * The patched host candidate exposed `ctx.observeAsyncJobLifecycle`, which joined the
 * async-job manager's own run promise and reported `executorSettled`/`cleanupComplete`
 * per attempt. Stock OMP does not expose that API, but it publishes the facts the
 * Brain needs through two supported surfaces:
 *
 * 1. `task:subagent:lifecycle` frames on the session event bus, emitted inside
 *    `finalizeRunResult` *after* the run's output artifact and structured sidecar are
 *    written and progress is flushed (`packages/coding-agent/src/task/executor.ts`).
 *    The frame carries the agent id, the parent tool-call id and the spawn index.
 * 2. `ctx.getAsyncJobSnapshot()`, whose rows bind that agent id to the native
 *    `type: "task"` job and its terminal status.
 *
 * This observer derives attempt-scoped observations from exactly those two surfaces.
 * It never invents a fact: `executorSettled` and `cleanupComplete` stay false until the
 * host's post-finalization frame is observed for the bound attempt, and an attempt that
 * yields no frame stays unresolved so the durable writer lease is never released.
 */

import type { AsyncJobLifecycleObservation } from "../types/prime";

/** One `task:subagent:lifecycle` frame from the OMP session event bus. */
export interface NativeSubagentLifecycleFrame {
  id?: unknown;
  agent?: unknown;
  parentToolCallId?: unknown;
  index?: unknown;
  status?: unknown;
  sessionFile?: unknown;
  detached?: unknown;
}

/** One async-job row from `ctx.getAsyncJobSnapshot()`. */
export interface NativeAsyncJobRow {
  id?: unknown;
  type?: unknown;
  status?: unknown;
  agentId?: unknown;
}

/** The supported read-only job view of the current session. */
export interface NativeAsyncJobSnapshot {
  running?: unknown;
  recent?: unknown;
}

/** Host surfaces this observer consumes; injected so tests can drive them directly. */
export interface NativeSettlementSource {
  subscribe(handler: (frame: NativeSubagentLifecycleFrame) => void): () => void;
  snapshot(): NativeAsyncJobSnapshot | null;
}

/** Native identity for one admitted spawn, minted once and reused across observations. */
export interface NativeAttemptIdentity {
  nativeAttemptId: string;
  generation: number;
}

export interface NativeSettlementObserverOptions {
  /** Native tool-call id the observations belong to (the `task` call). */
  sourceToolCallId: string;
  /** Resolve the identity for one spawn index; undefined means "not an admitted spawn". */
  attemptIdentity(sourceIndex: number): NativeAttemptIdentity | undefined;
  /** Durable observer callback; return value mirrors the host callback contract. */
  emit(observation: Readonly<AsyncJobLifecycleObservation>): boolean | Promise<boolean>;
  source: NativeSettlementSource;
  /**
   * Whether a post-finalization frame also proves the attempt's cleanup finished.
   *
   * Stock hosts detach late cleanup (child session disposal, advisor drain,
   * owner-job reaping) past their grace deadline and expose no completion signal, so
   * `false` keeps the durable writer lease held/quarantined. `true` is the explicit
   * attempt-scoped mode where the frame alone is treated as the settlement boundary.
   */
  cleanupProvenByFrame: boolean;
  /** Optional journal hook for an attempt that never produced a settlement frame. */
  onUnresolved?(detail: { sourceIndex: number; agentId: string; reason: string }): void;
}

/** Terminal native frame statuses, mapped onto durable lifecycle outcomes. */
const OUTCOME_BY_FRAME_STATUS: Record<string, "completed" | "failed" | "cancelled"> = {
  completed: "completed",
  failed: "failed",
  aborted: "cancelled",
};

function asJobRows(value: unknown): NativeAsyncJobRow[] {
  return Array.isArray(value)
    ? (value.filter((row) => row !== null && typeof row === "object") as NativeAsyncJobRow[])
    : [];
}

/** Find the native job id for one agent id; stock task jobs are registered under it. */
export function nativeJobIdForAgent(snapshot: unknown, agentId: string): string | null {
  // The host API returns `unknown`; validate the shape here so callers can pass it
  // through without casting.
  if (snapshot === null || typeof snapshot !== "object") return null;
  const { running, recent } = snapshot as { running?: unknown; recent?: unknown };
  for (const row of [...asJobRows(running), ...asJobRows(recent)]) {
    if (row.agentId === agentId && typeof row.id === "string" && row.id.length > 0) return row.id;
  }
  return null;
}

/**
 * Observe one `task` call's admitted spawns through supported stock signals.
 *
 * Returns a disposer; after disposal no further observations are emitted.
 */
export function createNativeSettlementObserver(
  options: NativeSettlementObserverOptions,
): () => void {
  const revisions = new Map<string, number>();
  let disposed = false;

  const emitObservation = async (frame: NativeSubagentLifecycleFrame): Promise<void> => {
    if (disposed) return;
    if (frame.parentToolCallId !== options.sourceToolCallId) return;
    const agentId = frame.id;
    const sourceIndex = frame.index;
    const status = typeof frame.status === "string" ? frame.status : undefined;
    const outcome = status === undefined ? undefined : OUTCOME_BY_FRAME_STATUS[status];
    if (outcome === undefined) return;
    if (typeof agentId !== "string" || agentId.length === 0 || agentId.length > 512) return;
    if (typeof sourceIndex !== "number" || !Number.isInteger(sourceIndex) || sourceIndex < 0) return;
    const identity = options.attemptIdentity(sourceIndex);
    if (identity === undefined) {
      options.onUnresolved?.({
        sourceIndex,
        agentId,
        reason: "NATIVE_SETTLEMENT_ATTEMPT_UNKNOWN",
      });
      return;
    }
    const key = `${sourceIndex}:${agentId}`;
    const revision = (revisions.get(key) ?? 0) + 1;
    revisions.set(key, revision);
    // The frame is the post-finalization fact. The snapshot only supplies the native
    // job id when the host exposes it; a missing row never blocks settlement and is
    // never replaced with an invented identifier.
    const jobId = nativeJobIdForAgent(options.source.snapshot(), agentId) ?? agentId;
    await options.emit({
      jobId,
      generation: identity.generation,
      nativeAttemptId: identity.nativeAttemptId,
      type: "task",
      agentId,
      sourceToolCallId: options.sourceToolCallId,
      sourceIndex,
      status: outcome,
      executorSettled: true,
      cleanupComplete: options.cleanupProvenByFrame,
      revision,
    });
  };

  const unsubscribe = options.source.subscribe((frame) => {
    void emitObservation(frame).catch(() => {
      // Durable rejection is journaled by the caller's emit path; observation must
      // never throw into the host's event dispatch.
    });
  });

  return () => {
    disposed = true;
    unsubscribe();
  };
}
