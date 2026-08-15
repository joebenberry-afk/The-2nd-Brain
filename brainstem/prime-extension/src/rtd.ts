/**
 * Phase 5 (RTD — real-time distillation) shadow measurement.
 *
 * SHADOW ONLY: this module only decides and measures. It never substitutes
 * tool-result content. Actual substitution lands in a later phase after gate
 * review (plan §20/§21/§101).
 *
 * Trigger rule (Phase 3 order — eligibility BEFORE any content work):
 *   toolName === "bash"
 *   AND the event input's command starts with one of
 *      ["pytest", "git", "rg", "grep"] (case-insensitive)
 *   AND precomputed serialized content length
 *      (JSON.stringify(content).length, legacy character metric) > threshold.
 *
 * RTD never serializes content itself: the caller decides eligibility FIRST
 * (`rtdEligibility`) and only then measures the result ONCE
 * (`measureContent`, serialized chars included only when eligible) and passes
 * the shared `ContentMeasurement` plus the precomputed eligibility.
 * Ineligible tools/commands therefore perform zero RTD-specific
 * serialization (ineligible primitive strings: not even one JSON.stringify).
 *
 * Privacy: only counts/sizes/decisions are ever stored — never content.
 */

/** Bash command prefixes that qualify for distillation. */
import type { ContentMeasurement } from "./sensors";
export const RTD_COMMAND_PREFIXES = ["pytest", "git", "rg", "grep"] as const;

/** Default size threshold when SECOND_BRAIN_RTD_THRESHOLD is unset/invalid. */
export const RTD_DEFAULT_THRESHOLD = 8000;

export type DistillReason = "size" | "tool" | "command" | "ok";

/** Minimal event surface consumed by the distill decision (no content). */
export interface DistillEvent {
  toolName: unknown;
  input?: unknown;
}

export interface DistillDecision {
  trigger: boolean;
  reason: DistillReason;
}

/**
 * Tool/command eligibility for RTD — decided WITHOUT touching result content
 * (Phase 3). Returns "tool" (not bash), "command" (bash command outside the
 * prefix list), or "ok" (eligible for the size check).
 */
export function rtdEligibility(
  toolName: unknown,
  input: unknown,
): Extract<DistillReason, "tool" | "command" | "ok"> {
  if (toolName !== "bash") {
    return "tool";
  }
  const command = commandFromInput(input);
  if (!command) return "command";
  // First whitespace-separated token only: `git status` matches, `gitx`
  // must not, and leading whitespace must not defeat the match.
  const firstToken = command.trim().split(/\s+/)[0] ?? "";
  const lower = firstToken.toLowerCase();
  if (!RTD_COMMAND_PREFIXES.some((prefix) => prefix === lower)) {
    return "command";
  }
  return "ok";
}

/** Serialized size of arbitrary content; 0 when not serializable. */
export function serializedSize(content: unknown): number {
  try {
    const serialized = JSON.stringify(content);
    return typeof serialized === "string" ? serialized.length : 0;
  } catch {
    return 0;
  }
}

/** Command string from a tool input object (bash tool), or undefined. */
export function commandFromInput(input: unknown): string | undefined {
  if (!input || typeof input !== "object") return undefined;
  const command = (input as Record<string, unknown>).command;
  return typeof command === "string" && command.length > 0 ? command : undefined;
}

/**
 * Parse a SECOND_BRAIN_RTD_THRESHOLD-style raw value.
 * Invalid/missing/negative values fall back to `fallback` (default 8000).
 */
export function parseThreshold(raw: string | undefined, fallback = RTD_DEFAULT_THRESHOLD): number {
  if (raw === undefined || raw === null) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

/**
 * Decide whether a tool result would be distilled, using the caller's
 * precomputed `measurement` (Phase 3). Eligibility is decided first —
 * ineligible tools/commands short-circuit without using the measurement.
 * reason: "tool" (not bash), "command" (bash command not in the prefix
 * list), "size" (eligible but size not above threshold), "ok" (would
 * trigger). Size semantics: legacy `JSON.stringify(content).length` via
 * `measurement.serializedChars`.
 *
 * `eligibility` is the precomputed decision (real handler computes it before
 * any content measurement and passes it through). When omitted (public
 * compatibility for direct callers), it is derived from the event exactly
 * once. The event input is therefore never read twice on any path.
 */
export function shouldDistill(
  event: DistillEvent,
  threshold: number,
  measurement: ContentMeasurement,
  eligibility: Extract<DistillReason, "tool" | "command" | "ok"> = rtdEligibility(
    event.toolName,
    event.input,
  ),
): DistillDecision {
  if (eligibility !== "ok") {
    return { trigger: false, reason: eligibility };
  }
  if (!(measurement.serializedChars > threshold)) {
    return { trigger: false, reason: "size" };
  }
  return { trigger: true, reason: "ok" };
}

/** Shadow telemetry record for a would-distill result (schema v2, additive). */
export interface RtdShadowRecord {
  v: 2;
  ts: string;
  kind: "rtd_shadow";
  session: string;
  tool: string;
  id: string;
  size: number;
  threshold: number;
  would_trigger: boolean;
  reason: string;
  /** Present only when SECOND_BRAIN_RTD=active: substitution not implemented yet. */
  substitution?: string;
}

export interface RtdShadowOptions {
  session: string;
  tool: unknown;
  id: unknown;
  input: unknown;
  /**
   * Precomputed eligibility (Phase 3, corrected): the real handler decides
   * `rtdEligibility(toolName, input)` BEFORE any content measurement and
   * passes it here so the measurement mode can be chosen accordingly.
   * Optional for direct/standalone callers (derived from tool/input).
   */
  eligibility?: Extract<DistillReason, "tool" | "command" | "ok">;
  /** Shared precomputed measurement (Phase 3): one serialization, both metrics. */
  measurement: ContentMeasurement;
  threshold: number;
  /** SECOND_BRAIN_RTD === "active" — records intent; substitution is NOT implemented. */
  active: boolean;
}

/**
 * Build the rtd_shadow record, or null when the result would not distill.
 * Eligibility is decided ONCE — the precomputed value when provided (real
 * handler), else derived from tool/input exactly once — and that SAME value
 * is passed to shouldDistill, so the event input is never re-read and the
 * decision cannot diverge. Ineligible results never touch the measurement.
 * Never logs content — only size/decision fields. `size` = legacy serialized
 * character length.
 */
export function rtdShadowRecord(options: RtdShadowOptions): RtdShadowRecord | null {
  // Single decision: precomputed (real path) or derived exactly once (compat).
  const eligibility = options.eligibility ?? rtdEligibility(options.tool, options.input);
  const decision = shouldDistill(
    { toolName: options.tool, input: options.input },
    options.threshold,
    options.measurement,
    eligibility,
  );
  if (!decision.trigger) return null;
  const record: RtdShadowRecord = {
    v: 2,
    ts: new Date().toISOString(),
    kind: "rtd_shadow",
    session: options.session,
    tool: typeof options.tool === "string" ? options.tool : "unknown",
    id: typeof options.id === "string" ? options.id : "unknown",
    size: options.measurement.serializedChars,
    threshold: options.threshold,
    would_trigger: true,
    reason: options.active ? "would-substitute" : decision.reason,
  };
  if (options.active) {
    record.substitution = "enabled-not-implemented";
  }
  return record;
}
