/**
 * Context Virtual Memory pager (Part B, RC4 pass) — the first conservative
 * `{messages}` context-replacement patch.
 *
 * Gated behind `[context_paging] enabled=false` by default (config.ts
 * `loadContextPagingConfig`), INDEPENDENT of `[vmem]`/`[vmem_admission]`/
 * `[context_structure]` (all four may need to be true for paging to have
 * anything to page, but paging itself needs its own top-level switch — see
 * config/context.toml).
 *
 * Eligible-for-paging classes (ONLY these two — Pilot 2's REAL captured
 * schema, outputs/reports/rc4/12-real-prime-pilot-2.md "Observed context
 * message schema"; everything else passes through completely untouched):
 *   1. `role === "custom"` elements where `customType ===
 *      AUTOINJECT_CUSTOM_TYPE` ("brain.autoinject.packet", autoinject.ts)
 *      AND `element.details.delivery_id` resolves to a real, currently-
 *      EVICTED RESEARCH_RESULT VMem object for this session.
 *   2. `role === "toolResult"` elements (never `isError === true` — see
 *      below) where `element.toolCallId` resolves to a real, currently-
 *      EVICTED TOOL_OBSERVATION VMem object for this session, correlated
 *      via that object's `metadata.toolCallId` (Part C: `vmem list --json`
 *      returns `metadata` but never `content`, so this correlation would be
 *      impossible without the Part C metadata extension).
 *
 * Never paged: `assistant`, `thinking`/`toolCall` blocks, `compactionSummary`,
 * `custom` with any other/missing `customType`, `toolResult` with
 * `isError === true` (recovery semantics for errors are out of scope this
 * pass — the simplest safe choice is to never page them), anything without
 * a resolvable durable reference, and anything inside the current-turn pin
 * window (the last `pinRecentMessages` elements, default 6).
 *
 * For a paged `toolResult`: `role`, `toolCallId`, `toolName`, `isError`,
 * `timestamp`, and `details` are kept EXACTLY as the host provided them —
 * ONLY `content` is replaced, with an ARRAY of one text block (the same
 * `content` shape RTD's own `runRtd` patch already uses for toolResult
 * elements) containing a small deterministic `[SECOND_BRAIN_VMEM]` pointer.
 *
 * For a paged AutoInject `custom` message: `role`, `customType`, `display`,
 * `timestamp`, and `details` are kept EXACTLY as provided — ONLY `content`
 * is replaced, this time with a PLAIN STRING (matching the real captured
 * schema: custom message `content` is a string, not a block array) carrying
 * the same small deterministic pointer.
 *
 * Return value: `undefined` when zero elements were paged this call (zero
 * mutation — never constructs an identical-looking patch just to prove the
 * hook works); the FULL messages array, with only the eligible elements'
 * `content` replaced, when at least one element was paged.
 *
 * Fail-open (Part E): ANY error anywhere in this path — a failed `vmem
 * list` subprocess call, unparsable metadata, anything — returns
 * `{ messages: undefined, error: <the error> }` so the caller can record an
 * `extension_error` telemetry record; this module itself never throws.
 */
import { AUTOINJECT_CUSTOM_TYPE } from "./autoinject";
import type { ContextPagingFileConfig } from "./config";
import { serializedSize } from "./rtd";
import { runVmemListSync, type VmemListedObject, type VmemListSyncResult } from "./vmem";

/** ~4 chars/token heuristic (VMem's own vmem.py `_estimate_tokens` style) —
 * no new tokenizer, matches the existing codebase convention. */
function estimateTokens(value: unknown): number {
  return Math.max(1, Math.floor(serializedSize(value) / 4));
}

interface PageCandidate {
  index: number;
  elementKind: "autoinject" | "toolResult";
  correlationKey: string;
}

/** Structural check ONLY (no VMem call yet) — is this element even the
 * right shape to be a paging candidate, and does it carry a correlation
 * key? Mirrors Pilot 2's real captured schema exactly (Part A of this doc). */
function candidateFor(element: unknown): PageCandidate | null {
  if (element === null || typeof element !== "object" || Array.isArray(element)) return null;
  const obj = element as Record<string, unknown>;

  if (obj.role === "custom" && obj.customType === AUTOINJECT_CUSTOM_TYPE) {
    const details = obj.details;
    if (details !== null && typeof details === "object" && !Array.isArray(details)) {
      const deliveryId = (details as Record<string, unknown>).delivery_id;
      if (typeof deliveryId === "string" && deliveryId.length > 0) {
        return { index: -1, elementKind: "autoinject", correlationKey: deliveryId };
      }
    }
    return null;
  }

  if (obj.role === "toolResult" && obj.isError !== true) {
    const toolCallId = obj.toolCallId;
    if (typeof toolCallId === "string" && toolCallId.length > 0) {
      return { index: -1, elementKind: "toolResult", correlationKey: toolCallId };
    }
  }
  return null;
}

/** Small, deterministic Second Brain reference (comparable in spirit to
 * RTD's own [SECOND_BRAIN_RTD] block, but intentionally much smaller — a
 * pointer, not a distilled summary). Recoverable via Part D:
 * `second_brain vmem resolve <session_id> <obj_id> --json`. */
function buildVmemPointerText(opts: {
  objId: string;
  kind: string;
  correlationKey: string;
  correlationLabel: string;
}): string {
  return [
    "[SECOND_BRAIN_VMEM]",
    `kind=${opts.kind}`,
    `obj_id=${opts.objId}`,
    `${opts.correlationLabel}=${opts.correlationKey}`,
    "state=EVICTED",
    `Recoverable (deterministic, no LLM): second_brain vmem resolve <session_id> ${opts.objId} --json`,
    "Request it only if the missing content is material to the current decision.",
  ].join("\n");
}

export interface PageContextOptions {
  home: string;
  hostSessionId: string;
  messages: unknown[];
  cfg: ContextPagingFileConfig;
  python?: string;
  timeoutMs?: number;
  /** Test seam: defaults to the real synchronous CLI bridge. */
  listEvicted?: (options: {
    home: string;
    hostSessionId: string;
    state?: string;
    python?: string;
    timeoutMs?: number;
  }) => VmemListSyncResult;
}

export interface PageContextResult {
  /** The patch to return from the `context` handler, or undefined (no
   * mutation — either nothing was eligible, or a fail-open path fired). */
  messages: unknown[] | undefined;
  /** Present only on a fail-open path (Part E) — caller should record an
   * `extension_error` telemetry record and MUST still treat `messages` as
   * undefined (never throw, never partially apply). */
  error?: string;
  /** Count of elements actually replaced (0 on every no-op/fail-open path). */
  pagedCount: number;
}

/**
 * Decide + (maybe) build the bounded `{messages}` replacement patch for one
 * `context` event. Synchronous (Part B/C: the real host `context` handler
 * contract, types/prime.d.ts `ContextEventResult | undefined`, has no
 * `Promise` variant, unlike `before_agent_start`) and NEVER throws.
 */
export function pageContext(options: PageContextOptions): PageContextResult {
  const noop: PageContextResult = { messages: undefined, pagedCount: 0 };
  try {
    if (!options.cfg.enabled) return noop;
    const messages = options.messages;
    if (!Array.isArray(messages) || messages.length === 0) return noop;

    // Part E: current-turn pin window — never touch the last N elements.
    const pinFrom = Math.max(0, messages.length - options.cfg.pinRecentMessages);
    if (pinFrom <= 0) return noop;

    const candidates: PageCandidate[] = [];
    for (let i = 0; i < pinFrom; i += 1) {
      const candidate = candidateFor(messages[i]);
      if (candidate !== null) candidates.push({ ...candidate, index: i });
    }
    if (candidates.length === 0) return noop;

    // Part E: resident_token_budget — page nothing until the ESTIMATED
    // total size of eligible OLD content exceeds the configured budget.
    let estimatedTotal = 0;
    for (const candidate of candidates) estimatedTotal += estimateTokens(messages[candidate.index]);
    if (estimatedTotal <= options.cfg.residentTokenBudget) return noop;

    // At most ONE vmem-list call per context event (Part C), never once per
    // element, and only reached once there is real over-budget old content.
    const listFn = options.listEvicted ?? runVmemListSync;
    const listed = listFn({
      home: options.home,
      hostSessionId: options.hostSessionId,
      state: "EVICTED",
      python: options.python,
      timeoutMs: options.timeoutMs,
    });
    if (!listed.ok || listed.objects === undefined) {
      // Part E fail-open: a failed vmem-list call never mutates messages.
      return { messages: undefined, pagedCount: 0, error: listed.error ?? "vmem list failed" };
    }

    const byDeliveryId = new Map<string, VmemListedObject>();
    const byToolCallId = new Map<string, VmemListedObject>();
    for (const obj of listed.objects) {
      if (obj.kind === "RESEARCH_RESULT") {
        const key = obj.metadata.deliveryId ?? obj.metadata.delivery_id;
        if (typeof key === "string" && key.length > 0) byDeliveryId.set(key, obj);
      } else if (obj.kind === "TOOL_OBSERVATION") {
        const key = obj.metadata.toolCallId ?? obj.metadata.tool_call_id;
        if (typeof key === "string" && key.length > 0) byToolCallId.set(key, obj);
      }
    }

    let patched: unknown[] | undefined;
    let pagedCount = 0;
    for (const candidate of candidates) {
      if (pagedCount >= options.cfg.maxPagesPerContextEvent) break;
      const match =
        candidate.elementKind === "autoinject"
          ? byDeliveryId.get(candidate.correlationKey)
          : byToolCallId.get(candidate.correlationKey);
      if (match === undefined) continue;

      const original = messages[candidate.index] as Record<string, unknown>;
      const pointerText = buildVmemPointerText({
        objId: match.objId,
        kind: match.kind,
        correlationKey: candidate.correlationKey,
        correlationLabel: candidate.elementKind === "autoinject" ? "delivery_id" : "toolCallId",
      });
      // toolResult content is an array of blocks in the real schema (Pilot
      // 2); custom (AutoInject) content is a plain string. Replace ONLY
      // content, in the SAME shape the host already provided, and keep
      // every other field byte-for-byte identical.
      const replacementContent =
        candidate.elementKind === "toolResult" ? [{ type: "text", text: pointerText }] : pointerText;
      if (patched === undefined) patched = messages.slice();
      patched[candidate.index] = { ...original, content: replacementContent };
      pagedCount += 1;
    }

    if (patched === undefined) return noop; // eligible candidates existed, but none matched an EVICTED object
    return { messages: patched, pagedCount };
  } catch (error) {
    // Part E fail-open: never throw from this module.
    return {
      messages: undefined,
      pagedCount: 0,
      error: error instanceof Error ? error.message : "context paging failed",
    };
  }
}
