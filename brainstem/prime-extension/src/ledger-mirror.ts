/**
 * P2 host event mirror — thin fail-open adapter (plan §16 PHASE 2B,
 * amendment §19.1/19.3).
 *
 * Mirrors ONE privacy-safe lifecycle event into the Brain session ledger by
 * spawning the Python control CLI:
 *
 *   <home>/.venv/Scripts/python.exe -m second_brain ledger append
 *     --session <hostSessionId> --stdin-json
 *
 * with cwd=<home>, SECOND_BRAIN_HOME=<home>, PYTHONHOME/PYTHONPATH removed,
 * 5s timeout. PRIVACY: task text is only ever sent as a sha256; tool events
 * carry names + byte sizes only. NEVER raw prompts, never transcript
 * content. Fail-open: any error/timeout/non-zero exit resolves
 * {ok:false,error} — the caller records an extension_error; nothing throws,
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

/** Test seam: clear the per-process init cache. */
export function resetMirrorInitCache(): void {
  initializedSessions.clear();
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

/** Fire-and-forget wrapper used by index.ts: mirrors and records
 * extension_error on failure (fail-open, never blocks). */
export function mirrorFireAndForget(
  options: MirrorOptions & { onError?: (error: string) => void },
): Promise<void> {
  // Returns the (never-rejecting) chain so a caller that measures bridge
  // latency can close its span when the mirror actually finished; callers
  // that ignore the value keep the original fire-and-forget behavior.
  return mirrorEvent(options)
    .then((result) => {
      if (!result.ok && options.onError) {
        try {
          options.onError(result.error ?? "ledger mirror failed");
        } catch {
          // storage failed too — stay silent
        }
      }
    })
    .catch((error) => {
      // Defense in depth: mirrorEvent's own internals already resolve
      // fail-open on every known failure path, but this wrapper's whole
      // contract is "never blocks" — a rejection must never escape here
      // regardless of its source.
      if (options.onError) {
        try {
          options.onError(error instanceof Error ? error.message : String(error));
        } catch {
          // storage failed too — stay silent
        }
      }
    });
}

/** Convenience: build an extension_error record for a mirror failure. */
export function mirrorExtensionError(session: string, error: string): unknown {
  return extensionError(session, new Error(`ledger mirror: ${error}`));
}

// ---------------------------------------------------------------------------
// T-G4: compaction barrier + segment rollover (plan §10.2/§10.3).
// ---------------------------------------------------------------------------

export interface LedgerCheckpointResult {
  ok: boolean;
  integrity?: Record<string, unknown>;
  error?: string;
}

/** Pre-compaction durability barrier: `ledger segment checkpoint`. */
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
  return new Promise((resolve) => {
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
  });
}

/** Segment rollover at the compaction boundary: `ledger segment open --reason compact`
 * (closes the prior active segment and opens a new one). Fire-and-forget. */
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
  );
}
