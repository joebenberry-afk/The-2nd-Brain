/**
 * E01 latency measurement only — never a product behavior.
 *
 * The Prime adapter's pre-dispatch latency is the sum of a handful of awaited
 * bridge calls plus the background work that competes with them. This module
 * records one JSON line per span (extension clock, epoch milliseconds) into
 * the file named by `SECOND_BRAIN_E01_TRACE`, so the harness can attribute
 * launch -> host user `message_end` and reconcile it against the inert
 * extension. Inert unless that env var names a file: no I/O, no timing, no
 * behavior change.
 *
 * Span records (`t: "span"`) carry `start_ms`/`end_ms` from
 * `performance.now()` (milliseconds since process start, same clock the
 * adapter's own awaits use) plus `wall_ms` (epoch) for reconciliation with
 * the harness clock. The `boot` record publishes the fixed offset between
 * the two clocks.
 */
import { appendFileSync } from "node:fs";

export const E01_TRACE_ENV = "SECOND_BRAIN_E01_TRACE";

interface E01TraceState {
  path: string;
  pid: number;
  monoOffset: number;
}

let state: E01TraceState | undefined;
let stateResolved = false;

function traceState(): E01TraceState | undefined {
  if (!stateResolved) {
    stateResolved = true;
    const path = process.env[E01_TRACE_ENV]?.trim();
    if (path && path.length > 0) {
      state = { path, pid: process.pid, monoOffset: Date.now() - performance.now() };
      e01Trace("boot", { mono_offset_ms: state.monoOffset });
    }
  }
  return state;
}

/** Is span recording active for this process? */
export function e01TraceEnabled(): boolean {
  return traceState() !== undefined;
}

/** Append one trace record; measurement never throws into a host turn. */
export function e01Trace(kind: string, fields?: Record<string, unknown>): void {
  const current = state ?? traceState();
  if (current === undefined) return;
  const record: Record<string, unknown> = {
    t: kind,
    pid: current.pid,
    wall_ms: Date.now(),
    mono_ms: performance.now(),
  };
  if (fields !== undefined) record.fields = fields;
  try {
    appendFileSync(current.path, `${JSON.stringify(record)}\n`, "utf8");
  } catch {
    // Unwritable trace file: measurement degrades, the turn does not.
  }
}

/** Close a span whose start came from `performance.now()`. */
export function e01SpanEnd(name: string, startMs: number, fields?: Record<string, unknown>): void {
  if (state === undefined && !traceState()) return;
  const end = performance.now();
  e01Trace("span", {
    name,
    start_ms: round3(startMs),
    end_ms: round3(end),
    duration_ms: round3(end - startMs),
    ...fields,
  });
}

/** Await a promise inside a span (the awaited bridge calls on the critical path). */
export async function e01SpanAsync<T>(
  name: string,
  work: Promise<T>,
  fields?: Record<string, unknown>,
): Promise<T> {
  const start = performance.now();
  try {
    return await work;
  } finally {
    e01SpanEnd(name, start, fields);
  }
}

/** Milliseconds with microsecond-resolution rounding (trace readability only). */
function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}
