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
  observeBinding,
  observeCancellation,
  observeCensus,
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
      running: [
        { id: "ReconWorker", type: "task", status: "running", agentId: "ReconWorker" },
        { id: "ReconWorker-2", type: "task", status: "completed", agentId: "ReconWorker" },
      ],
      recent: [{ id: "FinishedJob", type: "task", status: "failed", agentId: "FinishedJob" }],
    }),
  };
}

const packagePath = argValue("--package", "");
const contextMode = argValue("--context", "real");
const context = contextMode === "absent" ? {} : stockContext();

console.log(JSON.stringify(advertise({ hostVersion: hostVersion(packagePath), context })));

const observations: Array<HostObservation | null> = [
  observeBinding(context, { attemptId: "attempt-sample", hostGeneration: 1, agentId: "ReconWorker" }),
  observeCancellation(context, {
    attemptId: "attempt-sample",
    hostGeneration: 1,
    executionId: "FinishedJob",
  }),
  observeCensus(context, { attemptId: "attempt-sample", hostGeneration: 1 }),
];
for (const observation of observations) {
  if (observation !== null) console.log(JSON.stringify(observation));
}
