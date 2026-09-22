/**
 * Completion-authority producer contract.
 *
 * The result bridge is the only place the extension sends a worker completion, and it had no test
 * at all — which is how a missing `callback_token` reached production review unnoticed. These
 * cases pin the wire contract that the Brain's terminal-evidence guard depends on:
 *
 *  - an attempt that holds authority sends it, bounded;
 *  - an attempt with none (read-only is minted nothing by design) sends no key at all, not null;
 *  - the token is not smuggled into any other field.
 *
 * The child process is mocked: this asserts payload construction, not Brain behaviour, which the
 * Python acceptance matrix covers.
 */
import { describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  writes: [] as string[],
  calls: [] as unknown[][],
}));

vi.mock("node:child_process", () => ({
  execFile: (...args: unknown[]) => {
    harness.calls.push(args);
    const callback = args[3] as ((error: unknown, stdout: string) => void) | undefined;
    const options = (args[2] ?? {}) as { input?: string };
    if (typeof options.input === "string") harness.writes.push(options.input);
    const child = {
      stdin: {
        write: (chunk: string) => {
          harness.writes.push(chunk);
          return true;
        },
        // The bridge sends the whole payload with a single `end(chunk)`.
        end: (chunk?: string) => {
          if (typeof chunk === "string") harness.writes.push(chunk);
        },
      },
    };
    const [python, argv] = args as [string, string[], unknown, (e: unknown, o: string) => void];
    expect(typeof python).toBe("string");
    expect(argv).toContain("omp-routing");
    // Deterministic ordering, no wall-clock wait: the bridge writes the payload to stdin
    // synchronously after execFile returns, so a microtask sees the complete payload.
    queueMicrotask(() => {
      const payload = JSON.parse(
        harness.writes.length ? harness.writes.join("") : (options.input ?? "{}"),
      ) as Record<string, unknown>;
      callback?.(
        null,
        JSON.stringify({
          task_id: payload.task_id,
          attempt_id: payload.attempt_id,
          packet_sha256: payload.packet_sha256,
          result_sha256: "a".repeat(64),
          status: payload.status,
        }),
      );
    });
    return child;
  },
}));

import { runOmpWorkerResult } from "../src/worker-result-bridge";

function options(extra: Record<string, unknown> = {}) {
  return {
    home: "C:/unused-brain-home",
    sessionId: "session-authority",
    taskId: "task-authority",
    attemptId: "attempt-authority",
    packetSha256: "b".repeat(64),
    status: "completed" as const,
    workerAgent: "child-agent",
    ...extra,
  };
}

function sent(): Record<string, unknown> {
  expect(harness.writes.length).toBeGreaterThan(0);
  return JSON.parse(harness.writes.join("")) as Record<string, unknown>;
}

describe("worker result bridge completion authority", () => {
  it("sends the attempt's authority when admission issued one", async () => {
    harness.writes.length = 0;
    const outcome = await runOmpWorkerResult(options({ callbackToken: "sentinel-callback-token" }));
    expect(outcome.ok).toBe(true);
    const payload = sent();
    expect(payload.callback_token).toBe("sentinel-callback-token");
    expect(payload.operation).toBe("worker_result");
  });

  it("sends no key at all when the attempt has no authority", async () => {
    harness.writes.length = 0;
    await runOmpWorkerResult(options());
    const payload = sent();
    expect("callback_token" in payload).toBe(false);
    expect(payload.callback_token).toBeUndefined();
  });

  it("bounds the authority instead of forwarding it whole", async () => {
    harness.writes.length = 0;
    await runOmpWorkerResult(options({ callbackToken: "x".repeat(600) }));
    const payload = sent();
    expect(payload.callback_token).toBe("x".repeat(512));
  });

  it("never places the authority in another field", async () => {
    harness.writes.length = 0;
    await runOmpWorkerResult(
      options({ callbackToken: "sentinel-elsewhere", summary: "bounded summary" }),
    );
    const payload = sent();
    const carrying = Object.entries(payload)
      .filter(([key, value]) => key !== "callback_token" && String(value).includes("sentinel"))
      .map(([key]) => key);
    expect(carrying).toEqual([]);
  });
});
