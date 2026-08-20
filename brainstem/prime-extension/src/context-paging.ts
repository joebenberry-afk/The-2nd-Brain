/**
 * Context Virtual Memory pager (Part B, RC4 pass; proactive-paging repair,
 * RC4 Defect B pass) — the conservative `{messages}` context-replacement
 * patch.
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
 *      AND `element.details.delivery_id` resolves to a real, currently
 *      claimable (PRE-PAGE: RESIDENT, optionally FAULTED_IN, never PINNED)
 *      RESEARCH_RESULT VMem object for this session WHOSE metadata ALSO
 *      contains a non-empty `packetArtifactRef` (or `packet_artifact_ref`)
 *      AND a `packetSha256` (or `packet_sha256`) that is a valid
 *      64-character hex string — i.e. exact, durable, already-preserved
 *      artifact proof, not merely a delivery id. A delivery-only admission
 *      (index.ts's `before_agent_start` fail-open path, `packetMetadata =
 *      undefined`, used when packet preservation failed) correctly does
 *      NOT correlate here — it simply finds no match, same as any other
 *      unmatched candidate (`vmem resolve` still handles delivery-only
 *      reconstruction; that fallback is unaffected).
 *   2. `role === "toolResult"` elements (never `isError === true` — see
 *      below) where `element.toolCallId` resolves to a real, currently
 *      claimable (PRE-PAGE) TOOL_OBSERVATION VMem object for this session
 *      WHOSE metadata ALSO contains a non-empty `artifactRef` (or
 *      `artifact_ref`) — again, exact durable artifact proof, not merely a
 *      tool-call id — correlated via that object's `metadata.toolCallId`
 *      (Part C: `vmem list --json` returns `metadata` but never `content`,
 *      so this correlation would be impossible without the Part C metadata
 *      extension). A `toolCallId`-only object correctly finds no match.
 *
 * Never paged: `assistant`, `thinking`/`toolCall` blocks, `compactionSummary`,
 * `custom` with any other/missing `customType`, `toolResult` with
 * `isError === true` (recovery semantics for errors are out of scope this
 * pass — the simplest safe choice is to never page them), anything without
 * a resolvable durable reference, and anything inside the current-turn pin
 * window (the last `pinRecentMessages` elements, default 6).
 *
 * ---------------------------------------------------------------------
 * Defect B fix (RC4 proactive-paging-repair pass) — WHY this module now
 * causes the RESIDENT/FAULTED_IN -> EVICTED transition itself:
 *
 * Pilot 3 (outputs/reports/rc4/13-real-prime-pilot-3.md, "3. Real context
 * paging") found that VMem objects only ever became EVICTED via
 * `prepare_compaction()`, which fires at the SAME real compaction event
 * that also causes Prime's own host-level compaction to remove the
 * corresponding OLD live message from `event.messages` entirely. By the
 * time an object was EVICTED, its live message was already gone — so the
 * OLD version of this module (which only ever looked for already-EVICTED
 * objects) could never find a real match. `pageContext` now performs its
 * own bounded claim BEFORE Prime's own compaction ever runs, on
 * currently-live, currently-RESIDENT (or FAULTED_IN), artifact-backed
 * objects, so a currently-live old message can actually be replaced.
 *
 * Critical safety ordering (do not deviate):
 *   1. Structural candidates from live `event.messages` (unchanged, same
 *      shape rules as above, current-turn pin window respected).
 *   2. Estimate the ACTUAL model-visible size of those candidate messages
 *      (the existing `estimateTokens`/`serializedSize` convention applied
 *      to the message content itself — NOT the tiny VMem metadata blob).
 *      Under `resident_token_budget` -> stop, zero subprocess calls.
 *   3. Only once over budget: ONE bounded `vmem list` call targeting
 *      PRE-PAGE residency states (RESIDENT, optionally FAULTED_IN —
 *      matching `evict_to_budget`'s own existing precedent of treating
 *      FAULTED_IN as evictable too; never PINNED) for THIS session, same
 *      strict artifact-proof gates as before, UNWEAKENED.
 *   4. Correlate structural candidates against those real, proof-backed,
 *      currently-pageable objects. None correlate -> stop.
 *   5. Select up to `max_pages_per_context_event` correlated candidates,
 *      bounded, deterministic (message-index order).
 *   6. ONE new synchronous claim call (`runVmemClaimPagesSync`) atomically
 *      attempts to transition EXACTLY those selected obj_ids from their
 *      current pre-page state to EVICTED, and reports which ones actually
 *      succeeded. At most ONE such call per `context` event, only reached
 *      when step 5 selected >=1 candidate. This is "the claim".
 *   7. ONLY for obj_ids the claim call confirms were actually claimed:
 *      build the `{messages}` replacement patch (unchanged mechanics —
 *      replace ONLY `content`, preserve every other field exactly). Any
 *      candidate whose claim did not succeed (lost a race, wrong state,
 *      unknown object) is left completely untouched.
 *   8. If the claim call itself fails/errors: fail-open exactly as today —
 *      `undefined` + `extension_error`, ORIGINAL untouched messages, never
 *      a partial application. No replacement patch is EVER constructed
 *      before step 6's claim call has returned a confirmed success list.
 * ---------------------------------------------------------------------
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
 * list`/`vmem claim-pages` subprocess call, unparsable metadata, anything —
 * returns `{ messages: undefined, error: <the error> }` so the caller can
 * record an `extension_error` telemetry record; this module itself never
 * throws.
 */
import { AUTOINJECT_CUSTOM_TYPE } from "./autoinject";
import type { ContextPagingFileConfig } from "./config";
import { serializedSize } from "./rtd";
import {
  runVmemClaimPagesSync,
  runVmemListPrePageSync,
  type VmemClaimPagesResult,
  type VmemListPrePageSyncResult,
  type VmemPrePageObject,
} from "./vmem";

/** ~4 chars/token heuristic (VMem's own vmem.py `_estimate_tokens` style) —
 * no new tokenizer, matches the existing codebase convention. */
function estimateTokens(value: unknown): number {
  return Math.max(1, Math.floor(serializedSize(value) / 4));
}

/** Structural check ONLY — a non-empty string, nothing more. */
function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Structural check ONLY — a well-formed 64-character hex string (the
 * SHA-256 digest SHAPE). Does not read or hash any artifact; that real
 * verification happens once, for real, in `vmem resolve`/`resolve_object`. */
const SHA256_HEX_RE = /^[0-9a-f]{64}$/i;
function isValidSha256Hex(value: unknown): value is string {
  return typeof value === "string" && SHA256_HEX_RE.test(value);
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
  hostSessionId: string;
}): string {
  return [
    "[SECOND_BRAIN_VMEM]",
    `kind=${opts.kind}`,
    `obj_id=${opts.objId}`,
    `${opts.correlationLabel}=${opts.correlationKey}`,
    "state=EVICTED",
    `Recoverable (deterministic, no LLM): second_brain vmem resolve ${opts.hostSessionId} ${opts.objId} --json`,
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
  /** Test seam: defaults to the real synchronous CLI bridge
   * (`runVmemListPrePageSync`). Defect B: queries PRE-PAGE residency
   * states (RESIDENT, optionally FAULTED_IN) — NOT EVICTED. */
  listPrePage?: (options: {
    home: string;
    hostSessionId: string;
    python?: string;
    timeoutMs?: number;
  }) => VmemListPrePageSyncResult;
  /** Test seam: defaults to the real synchronous CLI bridge
   * (`runVmemClaimPagesSync`). Defect B: the ONE claim call per `context`
   * event (step 6) — never called before step 5 selects >=1 candidate,
   * and no replacement is ever built before this returns. */
  claimPages?: (options: {
    home: string;
    hostSessionId: string;
    candidates: Array<{ objId: string; kind: string }>;
    python?: string;
    timeoutMs?: number;
  }) => VmemClaimPagesResult;
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
  // ---- Defect B additive telemetry fields (privacy-safe: counts/kinds/
  // states/estimates only — populated ONLY alongside a real patch,
  // i.e. when `messages !== undefined`). ----
  /** Structurally-matched candidates found (step 1), before any VMem call. */
  candidateCount?: number;
  /** Structural candidates that ALSO correlated to a real, proof-backed,
   * currently-pageable VMem object (step 4), pre-claim. */
  eligibleCount?: number;
  /** Estimated total tokens of the candidate set (step 2) that triggered
   * the over-budget decision. */
  pressureEstimatedTokens?: number;
  /** The configured `resident_token_budget` this decision was checked
   * against. */
  residentBudget?: number;
  /** Candidates actually sent to the claim call (step 5, bounded by
   * `max_pages_per_context_event`). */
  requestedPageCount?: number;
  /** Candidates the claim call actually confirmed (step 6). */
  claimedPageCount?: number;
  /** Estimated tokens of the ORIGINAL content of the elements actually
   * replaced (same ~4-chars/token estimate as the budget check). */
  estimatedTokensBefore?: number;
  /** Estimated tokens of the REPLACEMENT content of the elements actually
   * replaced. */
  estimatedTokensAfter?: number;
  /** Distinct VMem object kinds actually paged this event. */
  objectKinds?: string[];
  /** Distinct pre-claim residency states of the objects actually paged. */
  stateBefore?: string[];
  /** Post-claim residency state(s) of the objects actually paged (always
   * `["EVICTED"]` for any object this function reports as paged). */
  stateAfter?: string[];
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

    // Step 1: structural candidates (unchanged).
    const candidates: PageCandidate[] = [];
    for (let i = 0; i < pinFrom; i += 1) {
      const candidate = candidateFor(messages[i]);
      if (candidate !== null) candidates.push({ ...candidate, index: i });
    }
    if (candidates.length === 0) return noop;

    // Step 2: resident_token_budget — page nothing until the ESTIMATED
    // total size of eligible OLD content (the actual model-visible message,
    // never the tiny VMem metadata blob) exceeds the configured budget.
    let estimatedTotal = 0;
    for (const candidate of candidates) estimatedTotal += estimateTokens(messages[candidate.index]);
    if (estimatedTotal <= options.cfg.residentTokenBudget) return noop;

    // Step 3 (Defect B): at most ONE vmem-list call per context event,
    // never once per element, only reached once there is real over-budget
    // old content — now targeting PRE-PAGE states (RESIDENT/FAULTED_IN),
    // not EVICTED.
    const listFn = options.listPrePage ?? runVmemListPrePageSync;
    const listed = listFn({
      home: options.home,
      hostSessionId: options.hostSessionId,
      python: options.python,
      timeoutMs: options.timeoutMs,
    });
    if (!listed.ok || listed.objects === undefined) {
      // Part E fail-open: a failed vmem-list call never mutates messages.
      return { messages: undefined, pagedCount: 0, error: listed.error ?? "vmem list failed" };
    }

    // Only correlate PRE-PAGE (RESIDENT/FAULTED_IN), UNPINNED objects whose
    // metadata proves an EXACT, durable, already-preserved backing exists
    // (packet artifact + verified hash shape for AutoInject; tool-
    // observation artifact for toolResult) — NOT merely that some
    // identifier is present. Anything short of that is simply absent from
    // these maps, which candidates then fail to match (the existing,
    // unchanged "no-op / untouched" path). These gates are UNWEAKENED from
    // the prior pass.
    const byDeliveryId = new Map<string, VmemPrePageObject>();
    const byToolCallId = new Map<string, VmemPrePageObject>();
    for (const obj of listed.objects) {
      if (obj.pinned) continue; // never PINNED
      if (obj.residencyState !== "RESIDENT" && obj.residencyState !== "FAULTED_IN") continue;
      if (obj.kind === "RESEARCH_RESULT") {
        const deliveryId = obj.metadata.deliveryId ?? obj.metadata.delivery_id;
        const packetArtifactRef = obj.metadata.packetArtifactRef ?? obj.metadata.packet_artifact_ref;
        const packetSha256 = obj.metadata.packetSha256 ?? obj.metadata.packet_sha256;
        if (
          isNonEmptyString(deliveryId) &&
          isNonEmptyString(packetArtifactRef) &&
          isValidSha256Hex(packetSha256)
        ) {
          byDeliveryId.set(deliveryId, obj);
        }
      } else if (obj.kind === "TOOL_OBSERVATION") {
        const toolCallId = obj.metadata.toolCallId ?? obj.metadata.tool_call_id;
        const artifactRef = obj.metadata.artifactRef ?? obj.metadata.artifact_ref;
        if (isNonEmptyString(toolCallId) && isNonEmptyString(artifactRef)) {
          byToolCallId.set(toolCallId, obj);
        }
      }
    }

    // Step 4: correlate structural candidates against real, proof-backed,
    // currently-pageable objects (message-index order preserved, since
    // `candidates` was built in ascending index order).
    const correlated: Array<{ candidate: PageCandidate; match: VmemPrePageObject }> = [];
    for (const candidate of candidates) {
      const match =
        candidate.elementKind === "autoinject"
          ? byDeliveryId.get(candidate.correlationKey)
          : byToolCallId.get(candidate.correlationKey);
      if (match !== undefined) correlated.push({ candidate, match });
    }
    if (correlated.length === 0) return noop;

    // Step 5: bounded, deterministic selection — up to
    // max_pages_per_context_event, in message-index order.
    const selected = correlated.slice(0, options.cfg.maxPagesPerContextEvent);

    // Step 6 (Defect B): the ONE claim call — the ONLY mutation attempt
    // this function ever makes, reached only because step 5 selected >=1
    // candidate. NOTHING is constructed before this returns a confirmed
    // success list (the single most important ordering rule here).
    const claimFn = options.claimPages ?? runVmemClaimPagesSync;
    const claimResult = claimFn({
      home: options.home,
      hostSessionId: options.hostSessionId,
      candidates: selected.map((s) => ({ objId: s.match.objId, kind: s.match.kind })),
      python: options.python,
      timeoutMs: options.timeoutMs,
    });
    if (!claimResult.ok || claimResult.claimedObjIds === undefined) {
      // Part E fail-open: a failed/errored claim call never mutates messages.
      return {
        messages: undefined,
        pagedCount: 0,
        error: claimResult.error ?? "vmem claim-pages failed",
      };
    }
    const claimedSet = new Set(claimResult.claimedObjIds);
    if (claimedSet.size === 0) return noop; // claim call succeeded but confirmed nothing

    // Step 7: build the replacement patch ONLY for confirmed-claimed
    // obj_ids. A candidate whose claim did not succeed (lost a race, wrong
    // state, unknown object) is left completely untouched.
    let patched: unknown[] | undefined;
    let pagedCount = 0;
    const kindsPaged = new Set<string>();
    const statesBeforePaged = new Set<string>();
    let tokensBefore = 0;
    let tokensAfter = 0;
    for (const { candidate, match } of selected) {
      if (!claimedSet.has(match.objId)) continue;

      const original = messages[candidate.index] as Record<string, unknown>;
      const pointerText = buildVmemPointerText({
        objId: match.objId,
        kind: match.kind,
        correlationKey: candidate.correlationKey,
        correlationLabel: candidate.elementKind === "autoinject" ? "delivery_id" : "toolCallId",
        hostSessionId: options.hostSessionId,
      });
      // toolResult content is an array of blocks in the real schema (Pilot
      // 2); custom (AutoInject) content is a plain string. Replace ONLY
      // content, in the SAME shape the host already provided, and keep
      // every other field byte-for-byte identical.
      const replacementContent =
        candidate.elementKind === "toolResult" ? [{ type: "text", text: pointerText }] : pointerText;
      const replacement = { ...original, content: replacementContent };

      tokensBefore += estimateTokens(original);
      tokensAfter += estimateTokens(replacement);
      kindsPaged.add(match.kind);
      if (match.residencyState) statesBeforePaged.add(match.residencyState);

      if (patched === undefined) patched = messages.slice();
      patched[candidate.index] = replacement;
      pagedCount += 1;
    }

    if (patched === undefined) return noop; // selected candidates existed, but the claim confirmed none
    return {
      messages: patched,
      pagedCount,
      candidateCount: candidates.length,
      eligibleCount: correlated.length,
      pressureEstimatedTokens: estimatedTotal,
      residentBudget: options.cfg.residentTokenBudget,
      requestedPageCount: selected.length,
      claimedPageCount: claimedSet.size,
      estimatedTokensBefore: tokensBefore,
      estimatedTokensAfter: tokensAfter,
      objectKinds: [...kindsPaged],
      stateBefore: [...statesBeforePaged],
      stateAfter: ["EVICTED"],
    };
  } catch (error) {
    // Part E fail-open: never throw from this module.
    return {
      messages: undefined,
      pagedCount: 0,
      error: error instanceof Error ? error.message : "context paging failed",
    };
  }
}
