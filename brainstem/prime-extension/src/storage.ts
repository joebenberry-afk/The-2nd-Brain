/**
 * Async JSONL telemetry store.
 *
 * Writes are fire-and-forget: append() queues work on an internal promise
 * chain and never throws into the caller. Order is preserved because each
 * append runs after the previous one. The first failure is logged to stderr
 * once; later failures stay silent so measurement can never disturb the
 * agent session.
 *
 * Phase 4 (fs churn): directory readiness is established at most ONCE per
 * destination instead of mkdir-per-append. The extension factory shares one
 * readiness seam (`createTelemetryDirEnsurer`) across every TelemetryStore it
 * constructs, so one mkdir attempt covers the whole factory lifecycle even
 * when several session stores share the destination (plan: "at extension
 * startup, ensure the telemetry directory once"). The default per-store seam
 * performs one mkdir per store for standalone/direct constructions. Fail-open
 * is preserved: a readiness failure is swallowed (logged once through the
 * store's one-time error reporting) and construction, appends, and final
 * writes never throw into the caller. A failed first attempt is permanently
 * marked attempted (never retried) — see `createTelemetryDirEnsurer`.
 *
 * Buffering is deliberately NOT implemented: Prime's daemon tears the worker
 * process down immediately after the terminal `session_shutdown` event, and
 * the only shutdown flush in this lifecycle is the synchronous
 * `appendFinal()` write. There is no awaited session-end flush that could
 * drain a buffer, so buffered records could be lost; immediate append
 * semantics are kept.
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { appendFile } from "node:fs/promises";
import { join } from "node:path";

/** Directory-readiness seam: ensures a directory exists (at most once). */
export type DirEnsurer = (dir: string) => void;

/**
 * Factory-scoped directory ensurer (Phase 4): the mkdir for the shared
 * destination is ATTEMPTED AT MOST ONCE for the lifetime of the returned
 * closure. Success or failure, the attempt is permanently recorded — a
 * failed first attempt is deliberately NOT retried by later stores: the
 * destination is unlikely to heal within one extension lifecycle, and the
 * single failure is reported once through the first constructing store's
 * one-time error handler (fail-open). Appends then fail silently per store
 * rather than storming the filesystem with repeated mkdir attempts.
 *
 * `mkdir` is injectable for deterministic tests; the default is
 * `mkdirSync(dir, { recursive: true })`.
 */
export function createTelemetryDirEnsurer(
  mkdir: (dir: string) => void = (dir) => mkdirSync(dir, { recursive: true }),
): DirEnsurer {
  let attempted = false;
  return (dir: string): void => {
    if (attempted) return;
    attempted = true;
    mkdir(dir);
  };
}

export class TelemetryStore {
  private chain: Promise<void> = Promise.resolve();
  private loggedFailure = false;

  constructor(
    private readonly telemetryDir: string,
    readonly sessionId: string,
    private readonly ensureDir: (dir: string) => void = (dir) => mkdirSync(dir, { recursive: true }),
  ) {
    // Phase 4: establish directory readiness at most once per store
    // lifecycle. Fail-open: a failure here is logged once and every append
    // still fails independently and silently afterwards.
    try {
      this.ensureDir(this.telemetryDir);
    } catch (error) {
      this.logFailure(error);
    }
  }

  /** Absolute path of this session's telemetry file. */
  filePath(): string {
    return join(this.telemetryDir, `${this.sessionId}.jsonl`);
  }

  /**
   * Queue a record for append. Never throws synchronously; never rejects the
   * returned promise (the caller should ignore it anyway).
   */
  append(record: unknown): void {
    let line: string;
    try {
      line = JSON.stringify(record);
      if (line === undefined) line = "null";
    } catch {
      // Unserializable record — drop it rather than crash the session.
      return;
    }
    this.chain = this.chain
      .then(async () => {
        await appendFile(this.filePath(), `${line}\n`, "utf8");
      })
      .catch((error: unknown) => this.logFailure(error));
  }

  /**
   * Final synchronous write, used only for the terminal `session_shutdown`
   * record. Prime's daemon supervisor tears the worker process down right
   * after the shutdown event, so an async fire-and-forget write can lose the
   * race with process.exit(). A single sync write at session end guarantees
   * delivery while still never blocking agent behavior (the session is
   * already over).
   */
  appendFinal(record: unknown): void {
    let line: string;
    try {
      line = JSON.stringify(record);
      if (line === undefined) line = "null";
    } catch {
      return;
    }
    try {
      appendFileSync(this.filePath(), `${line}\n`, "utf8");
    } catch (error) {
      this.logFailure(error);
    }
  }

  /** Log the first failure once; later failures stay silent (fail-open). */
  private logFailure(error: unknown): void {
    if (!this.loggedFailure) {
      this.loggedFailure = true;
      const message = error instanceof Error ? error.message : String(error);
      console.error(`[second-brain-observability] telemetry write failed: ${message}`);
    }
  }

  /** Test/debug helper: await all queued writes. */
  flush(): Promise<void> {
    return this.chain;
  }
}

/** Sanitize a session stem so it can never escape the telemetry directory. */
export function sanitizeSessionStem(stem: string): string {
  const cleaned = stem.replace(/[^A-Za-z0-9._-]/g, "-").replace(/^[._-]+|[._-]+$/g, "");
  return cleaned.length > 0 ? cleaned : `anon-${Date.now()}`;
}
