/**
 * Per-session ordering barrier for capsule writes (V3 S2 review fix).
 *
 * Two kinds of writer touch one session's capsule:
 *
 *   - FOREGROUND — the object the current turn's Python phases use
 *     (`ensure_capsule` / `update_capsule` inside the batched turn prepare, or
 *     the per-phase spawn): it writes the turn's objective/next_action and the
 *     SAME process may then render hot context and decide AutoInject from those
 *     fields (`autoinject._retrieval_query_text` reads objective+next_action);
 *   - QUIET — the coalesced background ensure a memory-invisible turn schedules
 *     so compaction-recovery state stays current at no critical-path cost.
 *
 * Without one barrier a quiet write can land between a later turn's capsule
 * write and its AutoInject read (selecting another task's memories), and a quiet
 * prompt queued behind an in-flight ensure can overwrite a NEWER foreground
 * write when it completes. This module therefore gives every session ONE strict
 * FIFO of writes:
 *
 *   - foreground tasks never run concurrently with a quiet write, and wait for
 *     the one in flight (a spawned Python process cannot be cancelled);
 *   - a foreground task supersedes (discards) a queued-but-not-started quiet
 *     prompt: that prompt is older than the turn that supersedes it, so letting
 *     it run afterwards would restore a stale objective/next_action;
 *   - quiet prompts coalesce to the LATEST text at their queue position, so a run
 *     of memory-invisible turns costs one spawn at a time, never one per turn;
 *   - `drain` resolves once nothing is queued or running, so compaction and
 *     shutdown persistence can settle the barrier before writing their own state.
 *
 * The barrier owns ORDER only: the write itself (spawn, telemetry, failure
 * recording) is injected per quiet prompt, and a rejected task never breaks the
 * chain.
 */

interface QuietWrite {
  /** Latest text for this queue slot; replaced while the slot waits. */
  prompt: string;
  /** Superseded by a newer foreground write: the slot becomes a no-op. */
  discarded: boolean;
}

interface Barrier {
  /** Chain of every write enqueued for one session, in enqueue order. */
  tail: Promise<void>;
  /** The single queued quiet slot (its prompt is the latest quiet prompt). */
  quiet?: QuietWrite;
}

export interface CapsuleWrites {
  /**
   * Run one foreground critical section: ordered after every write already
   * queued for the session, and discarding a quiet prompt still waiting.
   */
  foreground<T>(session: string, task: () => Promise<T>): Promise<T>;
  /**
   * Queue one coalesced quiet write. `write` is called with the latest prompt
   * for the slot; a prompt arriving while the slot waits replaces it.
   */
  quiet(session: string, prompt: string, write: (prompt: string) => Promise<void>): void;
  /** Resolve once every write enqueued so far has settled. */
  drain(session: string): Promise<void>;
}

export function createCapsuleWrites(): CapsuleWrites {
  const barriers = new Map<string, Barrier>();
  const barrierFor = (session: string): Barrier => {
    let barrier = barriers.get(session);
    if (barrier === undefined) {
      barrier = { tail: Promise.resolve() };
      barriers.set(session, barrier);
    }
    return barrier;
  };
  const enqueue = <T>(barrier: Barrier, task: () => Promise<T>): Promise<T> => {
    const started = barrier.tail.then(task);
    // The chain must survive a rejected task; callers of `foreground` still see
    // their own rejection through the returned promise.
    barrier.tail = started.then(
      () => undefined,
      () => undefined,
    );
    return started;
  };
  return {
    foreground<T>(session: string, task: () => Promise<T>): Promise<T> {
      const barrier = barrierFor(session);
      const queued = barrier.quiet;
      if (queued !== undefined) {
        queued.discarded = true;
        barrier.quiet = undefined;
      }
      return enqueue(barrier, task);
    },
    quiet(session: string, prompt: string, write: (prompt: string) => Promise<void>): void {
      const barrier = barrierFor(session);
      const queued = barrier.quiet;
      if (queued !== undefined) {
        queued.prompt = prompt; // latest quiet prompt wins at this queue position
        return;
      }
      const slot: QuietWrite = { prompt, discarded: false };
      barrier.quiet = slot;
      void enqueue(barrier, async () => {
        // The slot leaves the queue as it starts: a prompt arriving from here on
        // must queue behind this write, not be folded into a text already used.
        if (barrier.quiet === slot) barrier.quiet = undefined;
        if (slot.discarded) return;
        try {
          await write(slot.prompt);
        } catch {
          // Fire-and-forget: the injected writer records its own failures, and an
          // escaping rejection would surface as an unhandled promise rejection.
        }
      });
    },
    async drain(session: string): Promise<void> {
      const barrier = barriers.get(session);
      if (barrier === undefined) return;
      for (;;) {
        const tail = barrier.tail;
        await tail;
        if (barrier.tail === tail) return; // nothing new was enqueued while draining
      }
    },
  };
}
