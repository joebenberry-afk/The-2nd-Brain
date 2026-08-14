/**
 * Phase 5 (RTD — real-time distillation) shadow measurement.
 *
 * SHADOW ONLY: this module only decides and measures. It never substitutes
 * tool-result content. Actual substitution lands in a later phase after gate
 * review (plan §20/§21/§101).
 *
 * Trigger rule:
 *   serialized content length (JSON.stringify(content).length) > threshold
 *   AND toolName === "bash"
 *   AND the event input's command string starts with one of
 *      ["pytest", "git", "rg", "grep"] (case-insensitive).
 *
 * Privacy: only counts/sizes/decisions are ever stored — never content.
 */

/** Bash command prefixes that qualify for distillation. */
export const RTD_COMMAND_PREFIXES = ["pytest", "git", "rg", "grep"] as const;

/** Default size threshold when SECOND_BRAIN_RTD_THRESHOLD is unset/invalid. */
export const RTD_DEFAULT_THRESHOLD = 8000;

export type DistillReason = "size" | "tool" | "command" | "ok";

/** Minimal event surface consumed by the distill decision. */
export interface DistillEvent {
  toolName: unknown;
  content: unknown;
  input?: unknown;
}

export interface DistillDecision {
  trigger: boolean;
  reason: DistillReason;
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
 * Decide whether a tool result would be distilled.
 * reason: "size" (content not above threshold), "tool" (not bash),
 * "command" (bash command not in the prefix list), "ok" (would trigger).
 */
export function shouldDistill(event: DistillEvent, threshold: number): DistillDecision {
  if (!(serializedSize(event.content) > threshold)) {
    return { trigger: false, reason: "size" };
  }
  if (event.toolName !== "bash") {
    return { trigger: false, reason: "tool" };
  }
  const command = commandFromInput(event.input);
  if (!command) return { trigger: false, reason: "command" };
  // First whitespace-separated token only: `git status` matches, `gitx`
  // must not, and leading whitespace must not defeat the match.
  const firstToken = command.trim().split(/\s+/)[0] ?? "";
  const lower = firstToken.toLowerCase();
  if (!RTD_COMMAND_PREFIXES.some((prefix) => prefix === lower)) {
    return { trigger: false, reason: "command" };
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
  content: unknown;
  input: unknown;
  threshold: number;
  /** SECOND_BRAIN_RTD === "active" — records intent; substitution is NOT implemented. */
  active: boolean;
}

/**
 * Build the rtd_shadow record, or null when the result would not distill.
 * Never logs content — only size/decision fields.
 */
export function rtdShadowRecord(options: RtdShadowOptions): RtdShadowRecord | null {
  const decision = shouldDistill(
    { toolName: options.tool, content: options.content, input: options.input },
    options.threshold,
  );
  if (!decision.trigger) return null;
  const record: RtdShadowRecord = {
    v: 2,
    ts: new Date().toISOString(),
    kind: "rtd_shadow",
    session: options.session,
    tool: typeof options.tool === "string" ? options.tool : "unknown",
    id: typeof options.id === "string" ? options.id : "unknown",
    size: serializedSize(options.content),
    threshold: options.threshold,
    would_trigger: true,
    reason: options.active ? "would-substitute" : decision.reason,
  };
  if (options.active) {
    record.substitution = "enabled-not-implemented";
  }
  return record;
}
