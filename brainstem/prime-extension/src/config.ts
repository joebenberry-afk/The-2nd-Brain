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

/** Parse the safe-by-default read-avoidance rollout stage. */
export function rereadAvoidanceFromContextToml(text: string): "OFF" | "SHADOW" | "ACTIVE" {
  let section = "";
  let value: "OFF" | "SHADOW" | "ACTIVE" = "SHADOW";
  try {
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (line.startsWith("[")) {
        section = line.slice(1, -1).trim();
        continue;
      }
      if (section !== "rollout") continue;
      const eq = line.indexOf("=");
      if (!line.startsWith("reread_avoidance") || eq <= 0) continue;
      const candidate = line.slice(eq + 1).split("#")[0].trim().replace(/^"|"$/g, "").toUpperCase();
      if (candidate === "OFF" || candidate === "SHADOW" || candidate === "ACTIVE") value = candidate;
    }
  } catch {
    return "SHADOW";
  }
  return value;
}

/** Read `[rollout] reread_avoidance`, defaulting to SHADOW for compatibility. */
export function loadRereadAvoidance(home: string | null): "OFF" | "SHADOW" | "ACTIVE" {
  if (!home) return "SHADOW";
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return rereadAvoidanceFromContextToml(text);
  } catch {
    return "SHADOW";
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

// ---------------------------------------------------------------------------
// [vmem] config surface (Phase R3) — same tiny TOML-subset parser style as
// [rtd]. Safe-by-default: enabled=false until a live pilot proves the
// compaction-boundary bookkeeping is sound.
// ---------------------------------------------------------------------------

/** Default hot-context token budget (mirrors vmem.py DEFAULT_HOT_CONTEXT_BUDGET_TOKENS). */
export const VMEM_DEFAULT_BUDGET_TOKENS = 1500;

/** Resolved [vmem] configuration for the Prime extension (defaults safe). */
export interface VmemFileConfig {
  /** Master switch: compact-prep/hot-context calls happen only when true. */
  enabled: boolean;
  /** Hot working-set token budget passed to `vmem hot-context --budget`. */
  budgetTokens: number;
}

/**
 * Parse the `[vmem]` section of config/context.toml. Missing/invalid values
 * fall back to the documented defaults. PURE, never throws, never reads fs.
 */
export function vmemConfigFromContextToml(text: string): VmemFileConfig {
  let inVmem = false;
  let enabled = false;
  let budgetTokens = VMEM_DEFAULT_BUDGET_TOKENS;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inVmem = line.startsWith("[vmem]");
      continue;
    }
    if (!inVmem || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split("#")[0].trim();
    if (key === "enabled") {
      const v = value.toLowerCase();
      enabled = v === "true" || v === "1" || v === "yes";
    } else if (key === "budget_tokens") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) budgetTokens = parsed;
    }
  }
  return { enabled, budgetTokens };
}

/**
 * Load the full [vmem] config from `<home>/config/context.toml`; missing or
 * unreadable file returns the safe defaults (enabled=false). Never throws.
 */
export function loadVmemConfig(home: string | null): VmemFileConfig {
  if (!home) return vmemConfigFromContextToml("");
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return vmemConfigFromContextToml(text);
  } catch {
    return vmemConfigFromContextToml("");
  }
}

// ---------------------------------------------------------------------------
// [context_structure] config surface — same tiny TOML-subset parser style
// as [vmem]/[rtd]. Safe-by-default: enabled=false. Gates ONLY the additional
// privacy-safe structural sensor (sensors.contextStructure); the existing
// unconditional `sensors.context` (messages.length) is never affected.
// ---------------------------------------------------------------------------

export interface ContextStructureFileConfig {
  /** Master switch: contextStructure() is appended only when true. */
  enabled: boolean;
}

/**
 * Parse the `[context_structure]` section of config/context.toml.
 * Missing/invalid values fall back to enabled=false. PURE, never throws,
 * never reads fs.
 */
export function contextStructureConfigFromContextToml(text: string): ContextStructureFileConfig {
  let inSection = false;
  let enabled = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inSection = line.startsWith("[context_structure]");
      continue;
    }
    if (!inSection || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split("#")[0].trim();
    if (key === "enabled") {
      const v = value.toLowerCase();
      enabled = v === "true" || v === "1" || v === "yes";
    }
  }
  return { enabled };
}

/**
 * Load the full [context_structure] config from
 * `<home>/config/context.toml`; missing or unreadable file returns the safe
 * default (enabled=false). Never throws.
 */
export function loadContextStructureConfig(home: string | null): ContextStructureFileConfig {
  if (!home) return contextStructureConfigFromContextToml("");
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return contextStructureConfigFromContextToml(text);
  } catch {
    return contextStructureConfigFromContextToml("");
  }
}

// ---------------------------------------------------------------------------
// [vmem_admission] config surface — same tiny TOML-subset parser style.
// Safe-by-default: enabled=false, INDEPENDENT of [vmem].enabled (compact-
// prep/hot-context bookkeeping stays a separate toggle from admission calls
// into VMem's session-object store via `vmem.ts` runVmemStore).
// ---------------------------------------------------------------------------

export interface VmemAdmissionFileConfig {
  /** Master switch: admission calls (runVmemStore) happen only when true. */
  enabled: boolean;
}

/**
 * Parse the `[vmem_admission]` section of config/context.toml.
 * Missing/invalid values fall back to enabled=false. PURE, never throws,
 * never reads fs.
 */
export function vmemAdmissionConfigFromContextToml(text: string): VmemAdmissionFileConfig {
  let inSection = false;
  let enabled = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inSection = line.startsWith("[vmem_admission]");
      continue;
    }
    if (!inSection || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split("#")[0].trim();
    if (key === "enabled") {
      const v = value.toLowerCase();
      enabled = v === "true" || v === "1" || v === "yes";
    }
  }
  return { enabled };
}

/**
 * Load the full [vmem_admission] config from `<home>/config/context.toml`;
 * missing or unreadable file returns the safe default (enabled=false).
 * Never throws.
 */
export function loadVmemAdmissionConfig(home: string | null): VmemAdmissionFileConfig {
  if (!home) return vmemAdmissionConfigFromContextToml("");
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return vmemAdmissionConfigFromContextToml(text);
  } catch {
    return vmemAdmissionConfigFromContextToml("");
  }
}

// ---------------------------------------------------------------------------
// [context_paging] config surface (Part B/E, RC4 pass) — same tiny
// TOML-subset parser style. Safe-by-default: enabled=false, INDEPENDENT of
// [vmem]/[vmem_admission]/[context_structure] (all four may need to be true
// for paging to have anything to page, but paging itself needs its own
// top-level switch — see context-paging.ts).
// ---------------------------------------------------------------------------

/** Default: never page any of the last N live `event.messages` elements. */
export const CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES = 6;
/** Default: page nothing until eligible OLD content estimate exceeds this. */
export const CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET = 4000;
/** Default: hard cap on elements replaced in a single `context` call. */
export const CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT = 3;

/** Resolved [context_paging] configuration (defaults safe/conservative). */
export interface ContextPagingFileConfig {
  /** Master switch: pageContext() only ever returns a patch when true. */
  enabled: boolean;
  /** Never page any of the LAST N elements of event.messages (current-turn pin). */
  pinRecentMessages: number;
  /** Page nothing until estimated eligible OLD content exceeds this (tokens). */
  residentTokenBudget: number;
  /** Hard cap on how many elements may be replaced in one `context` call. */
  maxPagesPerContextEvent: number;
}

/**
 * Parse the `[context_paging]` section of config/context.toml.
 * Missing/invalid values fall back to the documented conservative defaults
 * (enabled=false). PURE, never throws, never reads fs.
 */
export function contextPagingConfigFromContextToml(text: string): ContextPagingFileConfig {
  let inSection = false;
  let enabled = false;
  let pinRecentMessages = CONTEXT_PAGING_DEFAULT_PIN_RECENT_MESSAGES;
  let residentTokenBudget = CONTEXT_PAGING_DEFAULT_RESIDENT_TOKEN_BUDGET;
  let maxPagesPerContextEvent = CONTEXT_PAGING_DEFAULT_MAX_PAGES_PER_EVENT;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inSection = line.startsWith("[context_paging]");
      continue;
    }
    if (!inSection || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split("#")[0].trim();
    if (key === "enabled") {
      const v = value.toLowerCase();
      enabled = v === "true" || v === "1" || v === "yes";
    } else if (key === "pin_recent_messages") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) pinRecentMessages = parsed;
    } else if (key === "resident_token_budget") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) residentTokenBudget = parsed;
    } else if (key === "max_pages_per_context_event") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) maxPagesPerContextEvent = parsed;
    }
  }
  return { enabled, pinRecentMessages, residentTokenBudget, maxPagesPerContextEvent };
}

/**
 * Load the full [context_paging] config from `<home>/config/context.toml`;
 * missing or unreadable file returns the safe defaults (enabled=false).
 * Never throws.
 */
export function loadContextPagingConfig(home: string | null): ContextPagingFileConfig {
  if (!home) return contextPagingConfigFromContextToml("");
  try {
    const text = readFileSync(join(home, "config", "context.toml"), "utf8");
    return contextPagingConfigFromContextToml(text);
  } catch {
    return contextPagingConfigFromContextToml("");
  }
}

export interface ModelFileConfig {
  contextTokens: number;
}

export interface ProviderFileConfig {
  cacheScope: string;
}

export function loadModelConfig(home: string | null | undefined, modelId: string): ModelFileConfig {
  let contextTokens = 128_000;
  if (!home) return { contextTokens };
  try {
    const text = readFileSync(join(home, "config", "v2.toml"), "utf8");
    let currentSection = "";
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      if (line.startsWith("[") && line.endsWith("]")) {
        currentSection = line.slice(1, -1).trim();
        continue;
      }
      if (currentSection === `models.${modelId}` || (currentSection === "models.default" && contextTokens === 128_000)) {
        const eq = line.indexOf("=");
        if (eq > 0) {
          const key = line.slice(0, eq).trim();
          const value = line.slice(eq + 1).split("#")[0].trim();
          if (key === "context_tokens") {
            const parsed = Number.parseInt(value, 10);
            if (Number.isFinite(parsed) && parsed > 0) contextTokens = parsed;
          }
        }
      }
    }
  } catch {
    // fallback
  }
  return { contextTokens };
}

export function loadProviderConfig(home: string | null | undefined, providerId: string): ProviderFileConfig {
  let cacheScope = "model";
  if (!home) return { cacheScope };
  try {
    const text = readFileSync(join(home, "config", "v2.toml"), "utf8");
    let currentSection = "";
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      if (line.startsWith("[") && line.endsWith("]")) {
        currentSection = line.slice(1, -1).trim();
        continue;
      }
      if (currentSection === `providers.${providerId}` || (currentSection === "providers.default" && cacheScope === "model")) {
        const eq = line.indexOf("=");
        if (eq > 0) {
          const key = line.slice(0, eq).trim();
          const value = line.slice(eq + 1).split("#")[0].trim().replace(/["']/g, "").toLowerCase();
          if (key === "cache_scope" && (value === "model" || value === "account")) {
            cacheScope = value;
          }
        }
      }
    }
  } catch {
    // fallback
  }
  return { cacheScope };
}

