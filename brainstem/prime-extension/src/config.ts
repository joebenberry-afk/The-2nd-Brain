/**
 * Config gate for the Second Brain observability extension.
 *
 * Disabled when:
 *  - SECOND_BRAIN_OBSERVABILITY is set to off|0|false|no (case-insensitive), or
 *  - the brain home directory does not exist.
 *
 * Brain home = SECOND_BRAIN_HOME env var, else %USERPROFILE%\Documents\The-Second-Brain.
 * Telemetry dir = <home>/telemetry/agent-performance.
 *
 * All functions read the environment at call time so tests can manipulate it.
 */
import { existsSync, statSync } from "node:fs";
import { join } from "node:path";

/** Values of SECOND_BRAIN_OBSERVABILITY that disable the extension (case-insensitive). */
export const DISABLED_VALUES = new Set(["off", "0", "false", "no"]);

/** True when the env var explicitly disables observability. */
export function observabilityDisabledByEnv(): boolean {
  const raw = process.env.SECOND_BRAIN_OBSERVABILITY;
  if (raw == null) return false;
  return DISABLED_VALUES.has(raw.trim().toLowerCase());
}

/** Default brain home when SECOND_BRAIN_HOME is unset. */
export function defaultBrainHome(): string {
  const base = process.env.USERPROFILE ?? process.env.HOME ?? "";
  return join(base, "Documents", "The-Second-Brain");
}

/**
 * Resolve the brain home directory, or null when it does not exist
 * (silent disable).
 */
export function resolveBrainHome(): string | null {
  const explicit = process.env.SECOND_BRAIN_HOME;
  const candidate = explicit && explicit.trim().length > 0 ? explicit.trim() : defaultBrainHome();
  if (candidate.length === 0) return null;
  try {
    return existsSync(candidate) && statSync(candidate).isDirectory() ? candidate : null;
  } catch {
    return null;
  }
}

export interface ObservabilityConfig {
  enabled: boolean;
  home: string | null;
  telemetryDir: string | null;
}

/** Load the effective configuration. */
export function loadConfig(): ObservabilityConfig {
  if (observabilityDisabledByEnv()) {
    return { enabled: false, home: null, telemetryDir: null };
  }
  const home = resolveBrainHome();
  if (!home) {
    return { enabled: false, home: null, telemetryDir: null };
  }
  return { enabled: true, home, telemetryDir: join(home, "telemetry", "agent-performance") };
}
