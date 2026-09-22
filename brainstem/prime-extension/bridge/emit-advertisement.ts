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

/** A present-but-malformed group: `null` is not an empty list, so the surface is unreadable. */
function nullGroupContext(): unknown {
  return {
    events: { on: () => () => undefined },
    getAsyncJobSnapshot: () => ({ running: null }),
  };
}

/** Rows whose id reads but whose agent field is renamed: binding can never resolve. */
function idOnlyRowsContext(): unknown {
  return {
    events: { on: () => () => undefined },
    getAsyncJobSnapshot: () => ({
      running: [{ id: "ReconWorker", agent: "ReconWorker", status: "running" }],
    }),
  };
}

/** Rows that keep both ids but rename only the status field: binding stays valid, and
 *  cancellation must not be claimed from the same evidence. */
function statusRenamedContext(): unknown {
  return {
    events: { on: () => () => undefined },
    getAsyncJobSnapshot: () => ({
      running: [{ id: "ReconWorker", agentId: "ReconWorker", state: "running" }],
    }),
  };
}

/** Executed checks for the behaviours a review flagged. Returns the verdict; the caller
 *  refuses to advertise when it is false. */
function selfCheck(): boolean {
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
  // Second review round: a present-but-non-array group, and rows whose agent field is
  // renamed while their id still reads. Both previously advertised binding as available
  // while `executionIdForAgent` could only ever return null.
  const nullGroup = advertise({ hostVersion: "null-group", context: nullGroupContext() }).capabilities;
  record("null job group disables execution_binding", false, nullGroup.execution_binding);
  const idOnly = advertise({ hostVersion: "id-only", context: idOnlyRowsContext() }).capabilities;
  record("id-only rows disable execution_binding", false, idOnly.execution_binding);
  // Third round: renaming only `status` leaves binding genuinely valid while making a
  // cancellation unobservable, so the two capabilities must be decided separately.
  const statusRenamed = advertise({ hostVersion: "status-renamed", context: statusRenamedContext() }).capabilities;
  record("renamed status keeps execution_binding", true, statusRenamed.execution_binding);
  record("renamed status disables cancellation_observation", false, statusRenamed.cancellation_observation);
  const stockCaps = advertise({ hostVersion: "stock", context }).capabilities;
  record("readable status keeps cancellation_observation", true, stockCaps.cancellation_observation);

  const ok = checks.every((check) => check.ok);
  console.error(JSON.stringify({ self_check: "bridge behaviours", checks, ok }));
  return ok;
}

const packagePath = argValue("--package", "");
const contextMode = argValue("--context", "real");

// Fail closed BEFORE presenting an advertisement: a bridge whose narrowing has regressed
// must not hand a harness something that merely looks conformant.
if (!selfCheck()) {
  console.error("bridge self-check failed: refusing to present an advertisement");
  process.exit(1);
}

const context = contextMode === "absent" ? {} : stockContext();
console.log(JSON.stringify(advertise({ hostVersion: hostVersion(packagePath), context })));

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
