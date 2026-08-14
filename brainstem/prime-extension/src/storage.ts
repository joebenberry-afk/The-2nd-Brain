/**
 * Async JSONL telemetry store.
 *
 * Writes are fire-and-forget: append() queues work on an internal promise
 * chain and never throws into the caller. Order is preserved because each
 * append runs after the previous one. The first failure is logged to stderr
 * once; later failures stay silent so measurement can never disturb the
 * agent session.
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { appendFile, mkdir } from "node:fs/promises";
import { join } from "node:path";

export class TelemetryStore {
  private chain: Promise<void> = Promise.resolve();
  private loggedFailure = false;

  constructor(
    private readonly telemetryDir: string,
    readonly sessionId: string,
  ) {}

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
        await mkdir(this.telemetryDir, { recursive: true });
        await appendFile(this.filePath(), `${line}\n`, "utf8");
      })
      .catch((error: unknown) => {
        if (!this.loggedFailure) {
          this.loggedFailure = true;
          const message = error instanceof Error ? error.message : String(error);
          console.error(`[second-brain-observability] telemetry write failed: ${message}`);
        }
      });
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
      mkdirSync(this.telemetryDir, { recursive: true });
      appendFileSync(this.filePath(), `${line}\n`, "utf8");
    } catch (error) {
      if (!this.loggedFailure) {
        this.loggedFailure = true;
        const message = error instanceof Error ? error.message : String(error);
        console.error(`[second-brain-observability] telemetry write failed: ${message}`);
      }
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
