/**
 * Runnable rehearsal entry for BrainHostProtocol v1.
 *
 * Prints one JSON object per line: the advertisement, then one sample of every
 * observation kind this bridge can produce. Run against a disposable candidate
 * install so the rehearsal never touches the production extension.
 *
 *   bun emit-advertisement.ts --package <path/to/package.json> [--context real|absent]
 */

import { readFileSync } from "node:fs";
import {
  advertise,
  executionIdForAgent,
  observeBinding,
  observeCancellation,
  observeInventory,
  type HostObservation,
} from "./brain-host-bridge";

function argValue(flag: string, fallback: string): string {
  const index = process.argv.indexOf(flag);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

function hostVersion(packageJsonPath: string): string {
  try {
    const parsed: unknown = JSON.parse(readFileSync(packageJsonPath, "utf8"));
    if (parsed !== null && typeof parsed === "object" && "version" in parsed) {
      const version: unknown = parsed.version;
      if (typeof version === "string") return version;
    }
  } catch {
    // fall through: an unreadable candidate package is reported as unknown, never guessed
  }
  return "unknown";
}

/** The stock 18.2.8 shape, as observed live: snapshot rows name both ids; no observers. */
function stockContext(): unknown {
  return {
    events: { on: () => () => undefined },
    getAsyncJobSnapshot: () => ({
      running: [{ id: "ReconWorker", type: "task", status: "running", agentId: "ReconWorker" }],
      recent: [
        { id: "CancelledJob", type: "task", status: "cancelled", agentId: "CancelledJob" },
        { id: "FailedJob", type: "task", status: "failed", agentId: "FailedJob" },
        // Two rows that share an agent identity: binding must refuse, not pick one.
        { id: "ReusedA", type: "task", status: "completed", agentId: "ReusedAgent" },
        { id: "ReusedB", type: "task", status: "completed", agentId: "ReusedAgent" },
      ],
    }),
  };
}

/** A deliberately renamed ROW layout, arrays intact: the row narrowing must fail closed. */
function mutatedContext(): unknown {
  return {
    events: { on: () => () => undefined },
    getAsyncJobSnapshot: () => ({
      running: [{ job_id: "ReconWorker", agent: "ReconWorker", state: "running" }],
    }),
  };
}

/** Executed checks for the behaviours a review flagged: these print, not assert. */
function selfCheck(): void {
  const context = stockContext();
  const checks: Array<{ check: string; expected: unknown; observed: unknown; ok: boolean }> = [];
  const record = (check: string, expected: unknown, observed: unknown): void => {
    checks.push({ check, expected, observed, ok: observed === expected });
  };

  record("unique agent binds its execution id", "ReconWorker", executionIdForAgent(context, "ReconWorker"));
  record("reused agent refuses to bind", null, executionIdForAgent(context, "ReusedAgent"));
  record(
    "cancelled execution reports a cancellation",
    true,
    observeCancellation(context, { attemptId: "a", hostGeneration: 1, executionId: "CancelledJob" })?.cancelled,
  );
  record(
    "failed execution is not a cancellation",
    null,
    observeCancellation(context, { attemptId: "a", hostGeneration: 1, executionId: "FailedJob" }),
  );
  record(
    "inventory never claims complete scope",
    false,
    observeInventory(context, { attemptId: "a", hostGeneration: 1 })?.census_scope_complete,
  );
  // Field-shape mutation: renamed host row fields must switch the host-dependent
  // capabilities off rather than leave the bridge binding against a shape it misreads.
  const mutated = advertise({ hostVersion: "mutated", context: mutatedContext() }).capabilities;
  record("renamed row fields disable execution_binding", false, mutated.execution_binding);
  record("renamed row fields disable cancellation", false, mutated.cancellation_observation);

  console.error(JSON.stringify({ self_check: "bridge behaviours", checks, ok: checks.every((c) => c.ok) }));
}

const packagePath = argValue("--package", "");
const contextMode = argValue("--context", "real");
const context = contextMode === "absent" ? {} : stockContext();

console.log(JSON.stringify(advertise({ hostVersion: hostVersion(packagePath), context })));
selfCheck();

const observations: Array<HostObservation | null> = [
  observeBinding(context, { attemptId: "attempt-sample", hostGeneration: 1, agentId: "ReconWorker" }),
  observeCancellation(context, {
    attemptId: "attempt-sample",
    hostGeneration: 1,
    executionId: "CancelledJob",
  }),
  observeInventory(context, { attemptId: "attempt-sample", hostGeneration: 1 }),
];
for (const observation of observations) {
  if (observation !== null) console.log(JSON.stringify(observation));
}
