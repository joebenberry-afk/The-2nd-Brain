/**
 * P2 host event mirror — thin fail-open adapter (plan §16 PHASE 2B,
 * amendment §19.1/19.3).
 *
 * Mirrors host lifecycle events into the Brain session ledger by spawning the
 * Python control CLI, `<home>/.venv/Scripts/python.exe -m second_brain ledger
 * append --session <hostSessionId> --batch --init`, with cwd=<home>,
 * SECOND_BRAIN_HOME=<home>, PYTHONHOME/PYTHONPATH removed, 5s timeout.
 *
 * LedgerBatch: events are QUEUED per session and shipped as ONE batch spawn
 * (JSON Lines on stdin) instead of one spawn per event — a turn that mirrors
 * six events used to cost six interpreter startups plus one init. The queue
 * flushes at every boundary the host and the ledger already agree on
 * (turn_end / agent_ended / the compaction pair), when it reaches
 * MIRROR_BATCH_MAX_EVENTS, or after MIRROR_FLUSH_DEBOUNCE_MS idle. Terminal
 * kinds flush SYNCHRONOUSLY (the session worker may be torn down the moment
 * their handler returns), and `runLedgerCheckpoint` flushes the queue before
 * the checkpoint's own durability barrier.
 *
 * Ordering is preserved: one queue per session, one in-flight batch at a time,
 * stdin order inside a batch, and the ledger assigns seq contiguously inside
 * the append transaction. PRIVACY: task text is only ever sent as a sha256;
 * tool events carry names + byte sizes only. NEVER raw prompts, never
 * transcript content. Fail-open: any error/timeout/non-zero exit resolves
 * `{ok:false,error}` — the caller records an extension_error; nothing throws,
 * nothing blocks the host turn.
 */
import { execFile, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { extensionError } from "./sensors";

export const MIRROR_DEFAULT_TIMEOUT_MS = 5000;
/** P3-E fix: ONE bounded retry on transient ledger spawn failures (first-init
 * races under mirror bursts). Delay between attempts. */
export const MIRROR_RETRY_DELAY_MS = 150;
/** Total spawn attempts per mirrored event (1 initial + 1 retry). */
export const MIRROR_MAX_ATTEMPTS = 2;

/** Queued events for one session that force an immediate flush (before the
 * debounce). Also the ledger's own append transaction size. */
export const MIRROR_BATCH_MAX_EVENTS = 64;
/** Idle debounce: a non-empty queue flushes this long after its last enqueue. */
export const MIRROR_FLUSH_DEBOUNCE_MS = 2000;
/**
 * Kinds that end a unit of host work, so their batch ships immediately instead
 * of waiting out the debounce: `turn_end`/`agent_ended` close a turn, and the
 * compaction pair brackets the one point where the ledger's own durability
 * barrier runs (segment checkpoint / segment rollover). Same static-lookup
 * shape as LEDGER_EVENT_TYPES below.
 */
export const MIRROR_FLUSH_KINDS: Record<string, true> = {
  turn_end: true,
  agent_ended: true,
  compaction_started: true,
  compaction_completed: true,
};
/**
 * Terminal kinds whose process may exit as soon as the handler returns
 * (`session_shutdown` is a `final` handler: the SDK guarantees no further
 * event-loop turn). Their flush is SYNCHRONOUS — a debounce timer or an
 * unawaited promise would drop the session's last evidence on teardown.
 */
export const MIRROR_TERMINAL_FLUSH_KINDS: Record<string, true> = { session_inactive: true };
/**
 * Extra pump cycles for a batch that already failed its immediate retry
 * (init race under a burst). Bounded: the batch is requeued ONCE and retried
 * after the idle debounce before its events are dropped with an error record.
 */
export const MIRROR_BATCH_DEFERRED_RETRIES = 1;
/** Session queues kept in memory before idle (empty, untimed) ones are evicted. */
export const MIRROR_MAX_SESSION_QUEUES = 128;

export interface MirrorResult {
  ok: boolean;
  error?: string;
}

export interface MirrorRecord {
  /** Lifecycle event type (contracts LifecycleEventType value). */
  kind: string;
  /** Privacy-safe fields, already hashed/trimmed by the caller. */
  fields: Record<string, unknown>;
  /** Optional event_id (auto-generated when absent). */
  eventId?: string;
  /** Optional parent event id for lineage. */
  parentEventId?: string;
  agentId?: string;
  /** bookkeeping events are recorded but skipped in projections. */
  ignorable?: boolean;
  surfaceVisibility?: string;
}

export interface MirrorOptions {
  home: string;
  hostSessionId: string;
  /** HOST parent session identity. The CLI resolves it to the canonical root. */
  parentSessionId?: string;
  record: MirrorRecord;
  python?: string;
  timeoutMs?: number;
  /** Working directory for `ledger init` project attribution (reuses the
   * AutoInject project-resolution ladder). Omitted when unknown. */
  cwd?: string;
}

/**
 * Parent identity used for each ledger auto-init in THIS process (T-G6-F3).
 * A later authoritative parent re-runs init so the CLI can persist or reject
 * ancestry; an omitted parent never erases an established root.
 */
const initializedSessions = new Map<string, string | undefined>();

/** Test seam: clear the per-process init cache AND every queued/pending batch
 * (call it between tests: both are process-global state). */
export function resetMirrorInitCache(): void {
  initializedSessions.clear();
  resetMirrorQueues();
}

function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** Deterministic event id for a mirror record (unique per call). */
function eventIdFor(kind: string): string {
  return `mirror-${kind}-${randomUUID()}`;
}

/**
 * True when the CLI error is the ledger's duplicate rejection for THE SAME
 * event this mirror is delivering (P3-E final fix). The bounded retry
 * re-sends the byte-identical payload when a first attempt persisted the
 * event but reported failure (crash between commit and stdout); the ledger's
 * deterministic duplicate rejection then means the event IS durably in the
 * ledger — delivery succeeded (fire-and-forget goal met; the ledger remains
 * the sequence authority). A duplicate of a DIFFERENT event is a real error.
 */
/**
 * The ledger's own event vocabulary (kernel semantics), and the host kinds that map onto it.
 *
 * Host telemetry names stop at this boundary (owner decision D-6: OMP field names belong to
 * the adapter, not the kernel), so the adapter — not the ledger — is what translates. The
 * ledger's contract makes an unknown `event_type` a hard error unless the record is
 * ignorable, which is why an unmapped kind used to fail every append it appeared in.
 */
/**
 * The ledger's event vocabulary (kernel semantics), kept in sync with
 * `src/second_brain/contracts.py::LifecycleEventType` — 40 members as of 2026-09-21.
 *
 * A kind in this set travels unchanged. A kind the ledger does not know is recorded as
 * ignorable host bookkeeping, because the ledger treats an unknown non-ignorable
 * `event_type` as a HARD error — which is what took this mirror down 7,755 times between
 * 2026-08-16 and 2026-09-21. There is deliberately NO rename table here: guessing that a
 * host kind means some other ledger type is how a kernel type gets silently remapped.
 */
const LEDGER_EVENT_TYPES: Record<string, true> = {
  accuracy_gate: true,
  agent_ended: true,
  brain_no_injection: true,
  brain_packet_delivered: true,
  brain_retrieval_attempt: true,
  compaction_completed: true,
  compaction_started: true,
  decision: true,
  environment_assessment: true,
  file_change_observed: true,
  finding: true,
  independent_verification: true,
  result_corrected: true,
  result_correction_requested: true,
  result_returned: true,
  result_reviewed: true,
  session_finalized: true,
  session_inactive: true,
  session_started: true,
  simplification_review: true,
  stop_decided: true,
  stop_finalized: true,
  task_assigned: true,
  task_completed: true,
  task_context_resolved: true,
  task_created: true,
  task_failed: true,
  test_observed: true,
  tool_completed: true,
  tool_requested: true,
  tool_started: true,
  turn_end: true,
  user_task: true,
  worker_cancelled: true,
  worker_completed: true,
  worker_failed: true,
  worker_message: true,
  worker_report: true,
  worker_spawned: true,
  worker_started: true,
};


export function ledgerEventTypeFor(kind: string): {
  eventType: string;
  /** True when the ledger has no such type, so the record must be ignorable. */
  unknownToLedger: boolean;
} {
  if (Object.hasOwn(LEDGER_EVENT_TYPES, kind)) return { eventType: kind, unknownToLedger: false };
  // Unknown: record it as host bookkeeping. The ledger skips an unknown ignorable record
  // instead of raising, so a new host kind can never take the mirror down again.
  return { eventType: kind, unknownToLedger: true };
}

/**
 * Kinds the adapter mirrors that the ledger vocabulary does not contain. Each is a candidate
 * for the kernel vocabulary rather than an adapter name — an artifact reference, prefix
 * drift, a degraded ledger, skipped shutdown telemetry — but kernel growth needs the owner's
 * decision, so for now they travel as ignorable bookkeeping: stored nowhere, projected
 * nowhere, and never a hard failure.
 */
export const UNPROJECTED_MIRROR_KINDS: readonly string[] = [
  "host_artifact_ref",
  "prefix_drift",
  "ledger_degraded",
  "worker_shutdown_telemetry_skipped",
];

function isDuplicateOfThisEvent(cliError: string, eventJson: string): boolean {
  let eventId: unknown;
  try {
    eventId = (JSON.parse(eventJson) as { event_id?: unknown }).event_id;
  } catch {
    return false;
  }
  return (
    typeof eventId === "string" &&
    cliError.includes(`duplicate event_id: '${eventId}'`)
  );
}

export function buildMirrorEventJson(record: MirrorRecord): string {
  const mapped = ledgerEventTypeFor(record.kind);
  const event = {
    // T-G6-F1: seq is OMITTED entirely — the ledger auto-assigns the
    // authoritative contiguous seq (host mirrors are stateless).
    event_id: record.eventId ?? eventIdFor(record.kind),
    agent_id: record.agentId ?? null,
    parent_event_id: record.parentEventId ?? null,
    event_type: mapped.eventType,
    timestamp: new Date().toISOString(),
    surface_visibility: record.surfaceVisibility ?? "raw_only",
    // An unknown event type is a HARD ERROR to the ledger unless it is ignorable
    // (`contracts.py`: "unknown required event type"), and a caller passing
    // `ignorable: false` therefore used to fail every append for a kind the ledger
    // had never heard of — 7,755 recorded failures between 2026-08-16 and 2026-09-21.
    // The kind the ledger does not know is, by definition, not one Brain requires:
    // it is recorded as host bookkeeping (skipped, never raised) and a caller cannot
    // escalate it back into a hard error.
    ignorable: record.ignorable === true || mapped.unknownToLedger,
    payload: record.fields,
  };
  return JSON.stringify(event);
}

/** sha256 of a task prompt — the ONLY form task text ever takes in the ledger. */
export function taskSha256(prompt: string): string {
  return sha256Hex(prompt);
}

/**
 * Synchronous mirror for terminal control-plane evidence. STOP finalization
 * must reach the ledger before OMP may tear down the session worker.
 */
export function mirrorEventSync(options: MirrorOptions): MirrorResult {
  const homePython = join(options.home, ".venv", "Scripts", "python.exe");
  const fallbackPython = join(process.cwd(), ".venv", "Scripts", "python.exe");
  const python =
    options.python ??
    (existsSync(homePython) ? homePython : existsSync(fallbackPython) ? fallbackPython : homePython);
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const appendArgs = [
    "-m",
    "second_brain",
    "ledger",
    "append",
    "--session",
    options.hostSessionId,
    "--stdin-json",
  ];
  const initArgs = [
    "-m",
    "second_brain",
    "ledger",
    "init",
    "--session",
    options.hostSessionId,
    "--host",
    "prime",
  ];
  if (
    typeof options.parentSessionId === "string" &&
    options.parentSessionId.length > 0
  ) {
    initArgs.push("--parent-session", options.parentSessionId);
  }
  if (typeof options.cwd === "string" && options.cwd.length > 0) {
    initArgs.push("--cwd", options.cwd);
  }
  try {
    execFileSync(python, initArgs, {
      cwd: options.home,
      env,
      timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
      stdio: "ignore",
    });
    execFileSync(python, appendArgs, {
      cwd: options.home,
      env,
      timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
      input: buildMirrorEventJson(options.record),
      stdio: ["pipe", "ignore", "ignore"],
    });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
/**
 * Mirror one event. Resolves {ok:true} silently when the brain home has no
 * venv (not a runtime — no-op, matches the autoinject adapter); resolves
 * {ok:false, error} on any spawn failure. NEVER throws, NEVER blocks.
 */
export async function mirrorEvent(options: MirrorOptions): Promise<MirrorResult> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) {
    return { ok: true }; // no runtime installed -> silent no-op
  }
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  // Payload is built ONCE; every retry re-sends the SAME byte-identical JSON.
  const json = buildMirrorEventJson(options.record);
  const appendArgs = [
    "-m",
    "second_brain",
    "ledger",
    "append",
    "--session",
    options.hostSessionId,
    "--stdin-json",
  ];
  const initArgs = [
    "-m",
    "second_brain",
    "ledger",
    "init",
    "--session",
    options.hostSessionId,
    "--host",
    "prime",
  ];
  const requestedParent =
    typeof options.parentSessionId === "string" && options.parentSessionId.length > 0
      ? options.parentSessionId
      : undefined;
  if (requestedParent !== undefined) {
    initArgs.push("--parent-session", requestedParent);
  }
  // Project attribution: pass the caller's cwd through to `ledger init` so
  // the ledger's project_id resolves through the same ladder AutoInject uses.
  // Only when a real cwd is available — never garbage.
  if (typeof options.cwd === "string" && options.cwd.length > 0) {
    initArgs.push("--cwd", options.cwd);
  }
  const run = (
    args: string[],
    input?: string,
  ): Promise<{ error?: string; stdout?: string }> =>
    new Promise((resolve) => {
      try {
        const child = execFile(
          python,
          args,
          {
            cwd: options.home,
            env,
            timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
            windowsHide: true,
            maxBuffer: 1024 * 1024,
          },
          (error, stdout) => resolve({ error: error?.message, stdout }),
        );
        if (input !== undefined) {
          child.stdin?.write(input);
          child.stdin?.end();
        }
      } catch (err) {
        // A synchronous spawn failure (e.g. an unspawnable interpreter path)
        // must resolve fail-open, never reject this fire-and-forget chain.
        resolve({ error: err instanceof Error ? err.message : String(err) });
      }
    });
  // One full init->append chain. P3-E fix: on ANY transient failure (init
  // race under burst, locked append, unparsable output) the caller retries
  // this chain ONCE after a short delay; fail-open is preserved (a second
  // failure records the existing bounded error and never throws).
  const attempt = (): Promise<MirrorResult> => {
    // T-G6-F3: auto-init the ledger once per session BEFORE the first append
    // (fire-and-forget chain; idempotent across races and recovered workers).
    // Only added to the cache on SUCCESS, so a retry after a failed init
    // re-runs the init chain.
    const alreadyInitialized = initializedSessions.has(options.hostSessionId);
    const cachedParent = initializedSessions.get(options.hostSessionId);
    const parentNeedsValidation =
      requestedParent !== undefined && requestedParent !== cachedParent;
    const ensureInit = alreadyInitialized && !parentNeedsValidation
      ? Promise.resolve({ error: undefined, stdout: "" })
      : run(initArgs).then((result) => {
          if (!result.error) {
            initializedSessions.set(
              options.hostSessionId,
              requestedParent ?? cachedParent,
            );
          }
          return result;
        });
    return ensureInit.then((initResult) => {
      if (initResult.error) {
        return { ok: false, error: `ledger init: ${initResult.error}` };
      }
      return new Promise((resolve) => {
        try {
          const child = execFile(
            python,
            appendArgs,
            {
              cwd: options.home,
              env,
              timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
              windowsHide: true,
              maxBuffer: 1024 * 1024,
            },
            (error, stdout) => {
              if (error) {
                resolve({ ok: false, error: error.message });
                return;
              }
              try {
                const parsed = JSON.parse(stdout) as { appended?: unknown; error?: string };
                if (parsed && parsed.error) {
                  // P3-E final fix: the retry re-sends the SAME payload; if the
                  // ledger already holds THIS event (first attempt persisted but
                  // reported failure), delivery succeeded — resolve ok, do not
                  // pollute telemetry with an error record.
                  if (isDuplicateOfThisEvent(String(parsed.error), json)) {
                    resolve({ ok: true });
                    return;
                  }
                  resolve({ ok: false, error: String(parsed.error) });
                  return;
                }
                resolve({ ok: true });
              } catch {
                resolve({ ok: false, error: "ledger append returned unparsable output" });
              }
            },
          );
          child.stdin?.write(json);
          child.stdin?.end();
        } catch (err) {
          // Same synchronous-spawn-failure guard as the init `run()` helper.
          resolve({ ok: false, error: err instanceof Error ? err.message : String(err) });
        }
      });
    });
  };
  let result = await attempt();
  if (!result.ok) {
    // Bounded: exactly ONE retry (MIRROR_MAX_ATTEMPTS total spawn chains).
    await new Promise((resolve) => setTimeout(resolve, MIRROR_RETRY_DELAY_MS));
    result = await attempt();
  }
  return result;
}

/** Fire-and-forget wrapper used by index.ts: queues the event for its session
 * batch and records extension_error on failure (fail-open, never blocks).
 *
 * Returns a promise that settles when the event was handled — durably in the
 * ledger, permanently rejected, or dropped after the bounded retries — so a
 * caller that measures mirror latency still closes its span at the right time.
 * Nothing in the host awaits it before continuing (index.ts: `void Promise.
 * resolve(...)`), and no failure ever rejects. */
export function mirrorFireAndForget(
  options: MirrorOptions & { onError?: (error: string) => void },
): Promise<void> {
  const settled = enqueueMirrorEvent(options);
  const kind = options.record.kind;
  if (Object.hasOwn(MIRROR_TERMINAL_FLUSH_KINDS, kind)) {
    // Final handler: the process may exit the moment this returns.
    flushSessionSync(options.hostSessionId);
    return settled;
  }
  scheduleFlush(
    options.hostSessionId,
    Object.hasOwn(MIRROR_FLUSH_KINDS, kind) ? 0 : MIRROR_FLUSH_DEBOUNCE_MS,
  );
  return settled;
}

/** Convenience: build an extension_error record for a mirror failure. */
export function mirrorExtensionError(session: string, error: string): unknown {
  return extensionError(session, new Error(`ledger mirror: ${error}`));
}

// ---------------------------------------------------------------------------
// LedgerBatch: per-session event queue, ONE spawn per flush.
// ---------------------------------------------------------------------------

interface QueuedMirrorEvent {
  /** Byte-identical JSON line; retries re-send exactly this. */
  json: string;
  parentSessionId?: string;
  cwd?: string;
  onError?: (error: string) => void;
  /** Pump cycles this event has already been through. */
  attempts: number;
  /** Resolves when this event is handled (durable, rejected, or dropped). */
  settled: () => void;
}

interface SessionQueue {
  events: QueuedMirrorEvent[];
  /** Idle-debounce timer (`setTimeout` under @types/node). */
  timer?: NodeJS.Timeout;
  /** Serializes this session's spawns: batches never interleave. */
  chain: Promise<void>;
  /**
   * True while this queue's pump is awaiting its spawn. During that window the
   * queue LOOKS idle (its events were spliced out, its timer was cleared), but
   * it is not: evicting it would orphan the pump, so a requeue after a failed
   * batch would land in an object `scheduleFlush` can no longer reach.
   */
  pumping: boolean;
  home: string;
  python?: string;
  timeoutMs?: number;
}

/**
 * One queue per session. Bounded by MIRROR_MAX_SESSION_QUEUES: idle (empty,
 * untimed, not pumping) queues are evicted first, so a long-lived host process
 * cannot grow this without bound. A queue whose pump is in flight is NOT idle
 * even though it holds no events — evicting it would orphan that pump.
 */
const mirrorQueues = new Map<string, SessionQueue>();

/** Test seam: drop every queue, pending timer, and the per-process init cache. */
export function resetMirrorQueues(): void {
  for (const queue of mirrorQueues.values()) clearQueueTimer(queue);
  mirrorQueues.clear();
}

/** Events still waiting to be shipped for a session (test seam). */
export function pendingMirrorEvents(hostSessionId: string): number {
  return mirrorQueues.get(hostSessionId)?.events.length ?? 0;
}

function clearQueueTimer(queue: SessionQueue): void {
  if (queue.timer !== undefined) {
    clearTimeout(queue.timer);
    queue.timer = undefined;
  }
}

function queueFor(options: MirrorOptions): SessionQueue {
  let queue = mirrorQueues.get(options.hostSessionId);
  if (queue === undefined) {
    if (mirrorQueues.size >= MIRROR_MAX_SESSION_QUEUES) {
      for (const [session, candidate] of mirrorQueues) {
        if (
          candidate.events.length === 0 &&
          candidate.timer === undefined &&
          !candidate.pumping
        ) {
          mirrorQueues.delete(session);
          break;
        }
      }
    }
    queue = { events: [], chain: Promise.resolve(), pumping: false, home: options.home };
    mirrorQueues.set(options.hostSessionId, queue);
  }
  // The brain home is a process-level constant; keep the newest value.
  queue.home = options.home;
  queue.python = options.python ?? queue.python;
  queue.timeoutMs = options.timeoutMs ?? queue.timeoutMs;
  return queue;
}

/** Queue one event; resolves when the batch containing it has been handled. */
function enqueueMirrorEvent(
  options: MirrorOptions & { onError?: (error: string) => void },
): Promise<void> {
  const queue = queueFor(options);
  let settled: () => void = () => {};
  const done = new Promise<void>((resolve) => {
    settled = resolve;
  });
  queue.events.push({
    json: buildMirrorEventJson(options.record),
    parentSessionId: options.parentSessionId,
    cwd: options.cwd,
    onError: options.onError,
    attempts: 0,
    settled,
  });
  if (queue.events.length >= MIRROR_BATCH_MAX_EVENTS) scheduleFlush(options.hostSessionId, 0);
  return done;
}

/** Flush a session's queue now (delay 0) or after the idle debounce. */
function scheduleFlush(hostSessionId: string, delayMs: number): void {
  const queue = mirrorQueues.get(hostSessionId);
  if (queue === undefined) return;
  clearQueueTimer(queue);
  if (delayMs <= 0) {
    queue.chain = queue.chain.then(() => pumpQueue(hostSessionId, queue)).catch(() => {});
    return;
  }
  const timer = setTimeout(() => {
    queue.timer = undefined;
    queue.chain = queue.chain.then(() => pumpQueue(hostSessionId, queue)).catch(() => {});
  }, delayMs);
  // A queued mirror event must never keep the host process alive by itself.
  if (typeof timer.unref === "function") timer.unref();
  queue.timer = timer;
}

/**
 * Flush whatever is queued for a session and settle when it has been shipped.
 * Used as a barrier by the compaction checkpoint (and by tests); never rejects.
 */
export function flushMirrorQueue(hostSessionId: string): Promise<void> {
  const queue = mirrorQueues.get(hostSessionId);
  if (queue === undefined) return Promise.resolve();
  clearQueueTimer(queue);
  queue.chain = queue.chain.then(() => pumpQueue(hostSessionId, queue)).catch(() => {});
  return queue.chain;
}

/** One flush: take the whole queue and ship it as one batch. */
async function pumpQueue(hostSessionId: string, queue: SessionQueue): Promise<void> {
  const batch = queue.events.splice(0, queue.events.length);
  if (batch.length === 0) return;
  clearQueueTimer(queue);
  // The queue now holds no events and no timer: flag it BUSY before the first
  // await so `queueFor` cannot evict it while its spawn is in flight.
  queue.pumping = true;
  try {
    const outcome = await spawnBatch(queue, hostSessionId, batch);
    if (outcome.ok) {
      reportBatchEventErrors(batch, outcome.errors);
      for (const event of batch) event.settled();
      return;
    }
    if (batch[0].attempts < MIRROR_BATCH_DEFERRED_RETRIES) {
      // Keep the evidence: the events go back to the FRONT of the queue, in
      // order, and the idle debounce retries them once more before they are
      // dropped with an error record.
      for (const event of batch) event.attempts += 1;
      queue.events.unshift(...batch);
      scheduleFlush(hostSessionId, MIRROR_FLUSH_DEBOUNCE_MS);
      return;
    }
    reportBatchFailure(batch, outcome.error ?? "ledger batch append failed");
    for (const event of batch) event.settled();
  } finally {
    queue.pumping = false;
  }
}

function mirrorPython(home: string, python?: string): string {
  return python ?? process.env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe");
}

function mirrorSpawnEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

/** True when this flush must carry `--init` (fresh session, or a new parent). */
function flushNeedsInit(hostSessionId: string, requestedParent?: string): boolean {
  if (!initializedSessions.has(hostSessionId)) return true;
  const cached = initializedSessions.get(hostSessionId);
  return requestedParent !== undefined && requestedParent !== cached;
}

/**
 * The parent identity a batch carries: its last non-empty `parentSessionId`, so
 * a flush that includes session_started still resolves the session through the
 * same ladder `ledger init` uses. ONE definition — the async pump, the sync
 * shutdown flush and the argv builder must all decide "which parent" the same
 * way, or a flush can cache a parent it never sent (and never validated).
 */
function batchParentSession(batch: QueuedMirrorEvent[]): string | undefined {
  return batch.reduce<string | undefined>(
    (latest, event) => (event.parentSessionId ? event.parentSessionId : latest),
    undefined,
  );
}

function batchAppendArgs(
  hostSessionId: string,
  batch: QueuedMirrorEvent[],
  needsInit: boolean,
): string[] {
  const args = ["-m", "second_brain", "ledger", "append", "--session", hostSessionId, "--batch"];
  if (!needsInit) return args;
  args.push("--init", "--host", "prime");
  // Project attribution + ancestry: the last value the batch carries, so a
  // flush that includes session_started still resolves the session through the
  // same ladder `ledger init` uses (never a fabricated cwd).
  const parent = batchParentSession(batch);
  if (parent !== undefined) args.push("--parent-session", parent);
  const cwd = batch.reduce<string | undefined>(
    (latest, event) => (event.cwd ? event.cwd : latest),
    undefined,
  );
  if (cwd !== undefined) args.push("--cwd", cwd);
  return args;
}

/** One per-event rejection reported by `ledger append --batch`. */
interface BatchErrorEntry {
  eventId: string;
  message: string;
}

interface BatchOutcome {
  ok: boolean;
  error?: string;
  errors: BatchErrorEntry[];
}

/** Validate the CLI's `errors` array once, so consumers read typed values. */
function batchErrorEntries(value: unknown): BatchErrorEntry[] {
  if (!Array.isArray(value)) return [];
  const entries: BatchErrorEntry[] = [];
  for (const entry of value) {
    if (entry === null || typeof entry !== "object") continue;
    // `in` narrowing keeps the read typed `unknown` — validated before use.
    const eventId = "event_id" in entry ? entry.event_id : undefined;
    const message = "error" in entry ? entry.error : undefined;
    entries.push({
      eventId: typeof eventId === "string" ? eventId : "",
      message: typeof message === "string" ? message : "rejected",
    });
  }
  return entries;
}

/** Validate one `ledger append --batch` stdout document. */
function parseBatchOutput(stdout: string): BatchOutcome {
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { ok: false, error: "ledger append --batch returned unparsable output", errors: [] };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { ok: false, error: "ledger append --batch returned unparsable output", errors: [] };
  }
  const error = "error" in parsed ? parsed.error : undefined;
  if (typeof error === "string" && error) return { ok: false, error, errors: [] };
  return { ok: true, errors: batchErrorEntries("errors" in parsed ? parsed.errors : undefined) };
}

/** ONE batch append: one spawn, one immediate retry on failure. */
async function spawnBatch(
  queue: SessionQueue,
  hostSessionId: string,
  batch: QueuedMirrorEvent[],
): Promise<BatchOutcome> {
  const python = mirrorPython(queue.home, queue.python);
  if (!existsSync(python)) return { ok: true, errors: [] }; // no runtime -> silent no-op
  const payload = `${batch.map((event) => event.json).join("\n")}\n`;
  const parent = batchParentSession(batch);
  const needsInit = flushNeedsInit(hostSessionId, parent);
  const args = batchAppendArgs(hostSessionId, batch, needsInit);
  let outcome = await runBatchAppend(queue, python, args, payload);
  if (!outcome.ok) {
    // Bounded: exactly ONE retry, byte-identical payload (the ledger's
    // per-event duplicate rejection makes a re-sent batch idempotent).
    await new Promise((resolve) => setTimeout(resolve, MIRROR_RETRY_DELAY_MS));
    outcome = await runBatchAppend(queue, python, args, payload);
  }
  if (outcome.ok && needsInit) {
    initializedSessions.set(hostSessionId, parent ?? initializedSessions.get(hostSessionId));
  }
  return outcome;
}

function runBatchAppend(
  queue: SessionQueue,
  python: string,
  args: string[],
  input: string,
): Promise<BatchOutcome> {
  return new Promise((resolve) => {
    try {
      const child = execFile(
        python,
        args,
        {
          cwd: queue.home,
          env: mirrorSpawnEnv(queue.home),
          timeout: queue.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
          windowsHide: true,
          maxBuffer: 1024 * 1024,
        },
        (error, stdout) =>
          resolve(error ? { ok: false, error: error.message, errors: [] } : parseBatchOutput(stdout)),
      );
      child.stdin?.write(input);
      child.stdin?.end();
    } catch (err) {
      // A synchronous spawn failure (unspawnable interpreter) fails open.
      resolve({ ok: false, error: err instanceof Error ? err.message : String(err), errors: [] });
    }
  });
}

/**
 * Synchronous flush for terminal kinds. The session worker may be torn down as
 * soon as the shutdown handler returns, so this waits for the spawn (bounded by
 * the mirror timeout) rather than relying on a timer nobody can await. ONE
 * attempt: a retry here would double the block for a race the session has long
 * outgrown, and the failure is recorded either way.
 */
function flushSessionSync(hostSessionId: string): void {
  const queue = mirrorQueues.get(hostSessionId);
  if (queue === undefined) return;
  clearQueueTimer(queue);
  const batch = queue.events.splice(0, queue.events.length);
  if (batch.length === 0) return;
  const outcome = spawnBatchSync(queue, hostSessionId, batch);
  if (outcome.ok) reportBatchEventErrors(batch, outcome.errors);
  else reportBatchFailure(batch, outcome.error ?? "ledger batch append failed (shutdown)");
  for (const event of batch) event.settled();
}

function spawnBatchSync(
  queue: SessionQueue,
  hostSessionId: string,
  batch: QueuedMirrorEvent[],
): BatchOutcome {
  const python = mirrorPython(queue.home, queue.python);
  if (!existsSync(python)) return { ok: true, errors: [] };
  const payload = `${batch.map((event) => event.json).join("\n")}\n`;
  const parent = batchParentSession(batch);
  // Same decision as the async pump: a batch that carries a new authoritative
  // parent must re-run `--init` with it, or the ancestry is never persisted and
  // the success path would cache a parent the CLI never validated.
  const args = batchAppendArgs(hostSessionId, batch, flushNeedsInit(hostSessionId, parent));
  let stdout: string;
  try {
    stdout = execFileSync(python, args, {
      cwd: queue.home,
      env: mirrorSpawnEnv(queue.home),
      timeout: queue.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
      input: payload,
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      stdio: ["pipe", "pipe", "ignore"],
    });
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      errors: [],
    };
  }
  const outcome = parseBatchOutput(stdout);
  if (outcome.ok) {
    initializedSessions.set(hostSessionId, parent ?? initializedSessions.get(hostSessionId));
  }
  return outcome;
}

function eventIdOf(json: string): string | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return undefined;
  }
  if (parsed === null || typeof parsed !== "object") return undefined;
  const id = "event_id" in parsed ? parsed.event_id : undefined;
  return typeof id === "string" ? id : undefined;
}

/** Per-event rejections: report them, but never a duplicate of the same event. */
function reportBatchEventErrors(batch: QueuedMirrorEvent[], errors: BatchErrorEntry[]): void {
  const rejected: string[] = [];
  for (const entry of errors) {
    // P3-E final fix: the retry re-sends the SAME payload; the ledger's
    // deterministic duplicate rejection for a byte-identical event means that
    // event IS durably in the ledger — delivery succeeded.
    const event = entry.eventId
      ? batch.find((candidate) => eventIdOf(candidate.json) === entry.eventId)
      : undefined;
    if (event !== undefined && isDuplicateOfThisEvent(entry.message, event.json)) continue;
    rejected.push(entry.eventId ? `${entry.eventId}: ${entry.message}` : entry.message);
  }
  if (rejected.length === 0) return;
  reportMirrorError(
    batch,
    `ledger mirror: ${rejected.length} of ${batch.length} events rejected: ${rejected.slice(0, 3).join("; ")}`,
  );
}

function reportBatchFailure(batch: QueuedMirrorEvent[], error: string): void {
  reportMirrorError(batch, `ledger mirror: ${batch.length} event(s) not mirrored: ${error}`);
}

/** Report through the caller's onError; a throwing callback stays silent. */
function reportMirrorError(batch: QueuedMirrorEvent[], message: string): void {
  const callback = batch.find((event) => event.onError !== undefined)?.onError;
  if (callback === undefined) return;
  try {
    callback(message);
  } catch {
    // storage failed too — stay silent
  }
}

// ---------------------------------------------------------------------------
// T-G4: compaction barrier + segment rollover (plan §10.2/§10.3).
// ---------------------------------------------------------------------------

export interface LedgerCheckpointResult {
  ok: boolean;
  integrity?: Record<string, unknown>;
  error?: string;
}

/**
 * Pre-compaction durability barrier: `ledger segment checkpoint`.
 *
 * LedgerBatch: queued mirror events flush FIRST. The checkpoint proves the
 * ledger's integrity (contiguous seq + unbroken hash chain), and index.ts calls
 * it right after mirroring `compaction_started` — without this barrier the
 * pre-compaction segment could be checkpointed before the events that belong to
 * it had even been spawned into the ledger.
 */
export function runLedgerCheckpoint(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
}): Promise<LedgerCheckpointResult> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (checkpoint unavailable)" });
  }
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  // Flush first, then checkpoint: the barrier is only as durable as the events
  // it claims to cover. Fail-open — a failed flush still runs the checkpoint
  // (its own result reports the ledger's real state).
  return flushMirrorQueue(options.hostSessionId).then(
    () =>
      new Promise((resolve) => {
        execFile(
          python,
          ["-m", "second_brain", "ledger", "segment", "checkpoint", options.hostSessionId],
          {
            cwd: options.home,
            env,
            timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
            windowsHide: true,
            maxBuffer: 1024 * 1024,
          },
          (error, stdout) => {
            if (error) {
              resolve({ ok: false, error: error.message });
              return;
            }
            try {
              const parsed = JSON.parse(stdout) as {
                ok?: boolean;
                integrity?: Record<string, unknown>;
                error?: string;
              };
              resolve({
                ok: parsed.ok === true,
                integrity: parsed.integrity,
                error: parsed.error,
              });
            } catch {
              resolve({ ok: false, error: "checkpoint returned unparsable output" });
            }
          },
        );
      }),
  );
}

/** Segment rollover at the compaction boundary: `ledger segment open --reason compact`
 * (closes the prior active segment and opens a new one). Fire-and-forget.
 *
 * LedgerBatch: the queue flushes first, so events mirrored before the compaction
 * (`compaction_completed` included) stay in the segment they were observed in
 * instead of racing the rollover. */
export function runLedgerSegmentRollover(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
  onError?: (error: string) => void;
}): void {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) return;
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  void flushMirrorQueue(options.hostSessionId).then(() =>
    execFile(
      python,
      ["-m", "second_brain", "ledger", "segment", "open", options.hostSessionId, "--reason", "compact"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? MIRROR_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error) => {
        if (error && options.onError) {
          try {
            options.onError(error.message);
          } catch {
            // stay silent
          }
        }
      },
    ),
  );
}
