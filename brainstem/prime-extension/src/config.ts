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
import { existsSync, readFileSync, statSync } from "node:fs";
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

// ---------------------------------------------------------------------------
// context.toml [rtd] threshold_chars (Phase 12 wiring)
// ---------------------------------------------------------------------------

/**
 * Parse `threshold_chars` from a context.toml `[rtd]` section using a tiny
 * TOML-subset parser (section headers `[name]` and `key = value` lines,
 * `#` comments stripped). Deterministic and pure: never throws, never reads
 * the filesystem.
 *
 * Returns the parsed non-negative integer, or undefined when the section,
 * key, or a valid value is absent (an invalid value is treated as absent).
 * Only `threshold_chars` is consumed — RTD tool/command eligibility stays
 * fixed source constants (`rtd.ts` `RTD_COMMAND_PREFIXES`) and
 * `enabled`/`max_distill_chars`/`whitelist_*` remain informational.
 */
export function thresholdCharsFromContextToml(text: string): number | undefined {
  let inRtd = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inRtd = line.startsWith("[rtd]");
      continue;
    }
    if (!inRtd || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    if (key !== "threshold_chars") continue;
    const value = line.slice(eq + 1).split("#")[0].trim();
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
    return undefined;
  }
  return undefined;
}

/**
 * Read `[rtd] threshold_chars` from `<home>/config/context.toml`, or
 * undefined when the home is null, the file is missing/unreadable, or the
 * value is absent/invalid. Never throws.
 */
export function rtdThresholdFromConfig(home: string | null): number | undefined {
  if (!home) return undefined;
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return thresholdCharsFromContextToml(text);
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// P3-F: full [rtd] config surface (plan §11.3) — the documented-but-unwired
// fields become real for the RTD substitution surface ONLY. Same tiny
// TOML-subset parser style; no second config file.
// ---------------------------------------------------------------------------

/** Default visible budget for the deterministic RTD block (plan §11.6). */
export const RTD_DEFAULT_MAX_DISTILL_CHARS = 2000;

/** Resolved [rtd] configuration for the Prime extension (defaults safe). */
export interface RtdFileConfig {
  /** Master switch: substitution happens only when true (plan §11.3/§11.5). */
  enabled: boolean;
  /** Distill when serialized result size exceeds this (legacy threshold ladder). */
  thresholdChars: number;
  /** Cap on the model-visible distilled block size (plan §11.6). */
  maxDistillChars: number;
  /** Tools eligible for RTD (default: bash only — plan §11.2). */
  whitelistTools: string[];
  /** First-token commands eligible for RTD (default: pytest/git/rg/grep). */
  whitelistCommands: string[];
}

/** Parse a TOML string list `["a", "b"]` (quotes/whitespace stripped). */
function parseStringList(raw: string): string[] | undefined {
  const inner = raw.trim();
  if (!inner.startsWith("[") || !inner.endsWith("]")) return undefined;
  const items = inner
    .slice(1, -1)
    .split(",")
    .map((item) => item.trim().replace(/^"|"$/g, "").toLowerCase())
    .filter((item) => item.length > 0);
  return items.length > 0 ? items : undefined;
}

/**
 * Parse the `[rtd]` section of config/context.toml into the full config
 * surface. Missing/invalid values fall back to the documented defaults
 * (safe-by-default: enabled=false). PURE, never throws, never reads fs.
 */
export function rtdConfigFromContextToml(text: string): RtdFileConfig {
  let inRtd = false;
  let enabled = false;
  let thresholdChars = 8000; // rtd.ts RTD_DEFAULT_THRESHOLD (no import cycle)
  let maxDistillChars = RTD_DEFAULT_MAX_DISTILL_CHARS;
  let whitelistTools = ["bash"];
  let whitelistCommands = ["pytest", "git", "rg", "grep"];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inRtd = line.startsWith("[rtd]");
      continue;
    }
    if (!inRtd || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split("#")[0].trim();
    if (key === "enabled") {
      const v = value.toLowerCase();
      enabled = v === "true" || v === "1" || v === "yes";
    } else if (key === "threshold_chars") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) thresholdChars = parsed;
    } else if (key === "max_distill_chars") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) maxDistillChars = parsed;
    } else if (key === "whitelist_tools") {
      const parsed = parseStringList(value);
      if (parsed) whitelistTools = parsed;
    } else if (key === "whitelist_commands") {
      const parsed = parseStringList(value);
      if (parsed) whitelistCommands = parsed;
    }
  }
  return { enabled, thresholdChars, maxDistillChars, whitelistTools, whitelistCommands };
}

/**
 * Load the full [rtd] config from `<home>/config/context.toml`; missing or
 * unreadable file returns the safe defaults (enabled=false). Never throws.
 */
export function loadRtdConfig(home: string | null): RtdFileConfig {
  if (!home) return rtdConfigFromContextToml("");
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return rtdConfigFromContextToml(text);
  } catch {
    return rtdConfigFromContextToml("");
  }
}
