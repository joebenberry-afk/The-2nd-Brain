/** Detached shutdown maintenance: the OPTIONAL per-shutdown Brain work
 * (environment assessment ~1.4 s, P4 pulse ~250 ms measured) is started as
 * DETACHED Python processes that outlive the host worker instead of blocking
 * its teardown. Two consequences of that trade-off are deliberate:
 *
 * - the host never reads a result, so the detached `p4 pulse` runs WITHOUT
 *   `--no-telemetry`: Python writes its own `heartbeat_pulse` /
 *   `bottleneck_fingerprint` records (the TS sensors can no longer relay them);
 * - every failure is silent and local (fail-open). A detached child that cannot
 *   start must never surface as an error in the host's shutdown path, and an
 *   exit-code/`error` event that arrives after the host is gone has no reader.
 *
 * `src/detached-spawn.ts` owns the spawn semantics this shares with the ledger's
 * terminal flush and the shutdown capsule update: `detached: true` (own process
 * group) + `unref()` + ignored stdio, which is what makes the child survive the
 * parent's exit on Windows. */
import { existsSync } from "node:fs";
import { join } from "node:path";
import { startDetachedBrainCommand } from "./detached-spawn";

export interface DetachedMaintenanceOptions {
  /** Brain home: the child's `cwd` and `SECOND_BRAIN_HOME`. */
  home: string;
  hostSessionId: string;
  /** Repo the assessment reads. `env assess` is skipped when it is empty. */
  repo?: string;
  /** Radar project attribution; `--project-id` is omitted when unknown. */
  projectId?: string;
  /** Start `env assess --phase shutdown` (fingerprint changed or the deferred
   * session-start assessment never ran). The P4 pulse always runs. */
  assessEnvironment: boolean;
  python?: string;
}

export interface DetachedMaintenanceResult {
  /** The environment assessment process started. */
  environment: boolean;
  /** The P4 pulse process started. */
  p4: boolean;
}

/**
 * Start Brain's optional shutdown maintenance detached. Returns as soon as the
 * processes are spawned (never waits for either command) and never throws: a
 * missing venv, an unstartable child, or an unreadable repo all degrade to
 * "not started" with no effect on the host's shutdown path.
 */
export function startDetachedShutdownMaintenance(
  options: DetachedMaintenanceOptions,
): DetachedMaintenanceResult {
  const python =
    options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) return { environment: false, p4: false };
  const repo = options.repo ?? "";
  const environment =
    options.assessEnvironment &&
    repo.length > 0 &&
    startDetachedBrainCommand(
      python,
      ["-m", "second_brain", "env", "assess", repo, "--session", options.hostSessionId, "--phase", "shutdown", "--json"],
      options.home,
    );
  // No `--no-telemetry`: the detached pulse owns its own heartbeat/fingerprint writes.
  const p4 = startDetachedBrainCommand(
    python,
    [
      "-m", "second_brain", "p4", "pulse",
      "--event", "session_shutdown",
      "--session", options.hostSessionId,
      ...(repo.length > 0 ? ["--repo", repo] : []),
      ...(options.projectId ? ["--project-id", options.projectId] : []),
      "--json",
    ],
    options.home,
  );
  return { environment, p4 };
}
