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

 * ---------------------------------------------------------------------
 * RC4 CVM closure repair (Repair B) — already-EVICTED reprojection:
 *
 * Pilot 4 (outputs/reports/rc4/14-real-prime-pilot-4.md) found that even
 * though the claim above patches the LIVE outgoing provider request,
 * Prime's OWN persisted transcript can still hold the original full
 * message. A later resume/reconstruction can therefore present
 * `event.messages` containing the FULL original content for an object
 * whose VMem state is ALREADY `EVICTED` (claimed on an earlier `context`
 * event in the same session, or evicted by compact-prep). The single
 * `runVmemListPrePageSync` call already returns objects across every
 * residency state — this module simply also accepts `EVICTED` (alongside
 * `RESIDENT`/`FAULTED_IN`) when building the correlation maps, still
 * requiring unpinned + the SAME unweakened metadata-proof gates, and
 * carries each matched object's `residencyState` forward.
 *
 * Two paging paths result from one correlated/selected candidate set
 * (bounded together by `max_pages_per_context_event`):
 *   Path A — newly claimed (unchanged): RESIDENT/FAULTED_IN candidates are
 *     sent to ONE `claim-pages` call; only objIds it confirms are
 *     pointerized. Exactly as before this repair.
 *   Path B — already-evicted reprojection (new): EVICTED candidates are
 *     NEVER sent to the claim call (no claim call is made for them, and
 *     if the ONLY selected candidates are EVICTED, the claim call is
 *     never invoked AT ALL this event) and perform ZERO DB mutation —
 *     they are proof-backed and already EVICTED, so they are pointerized
 *     directly with the SAME deterministic pointer text.
 *
 * Claim-failure / mixed-event design decision (documented, tested):
 * if the ONE claim call for the RESIDENT/FAULTED_IN group fails (or
 * throws), that failure is caught LOCALLY (not by this function's
 * top-level fail-open catch) so it can never suppress Path B — EVICTED
 * reprojection candidates in the SAME event are still pointerized
 * independently, since reprojection performs no subprocess call and needs
 * no claim at all. A pure RESIDENT/FAULTED_IN-only event whose claim call
 * fails still returns the ORIGINAL fully fail-open shape (`messages:
 * undefined`, `error` set) — unaffected, exactly as before this repair.
 *
 * Double-wrap guard: an element whose `content` (plain string for
 * `custom`, or `content[0].text` for `toolResult` — same shapes
 * `buildVmemPointerText`'s output already takes) starts with the EXACT
 * literal `"[SECOND_BRAIN_VMEM]"` is NOT a candidate at all (`candidateFor`
 * returns `null` before any other check) — an already-pointerized message
 * is never reprojected/replaced again on a later event.
 * ---------------------------------------------------------------------
 */
import { AUTOINJECT_CUSTOM_TYPE } from "./autoinject";
import type { ContextPagingFileConfig } from "./config";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { serializedSize } from "./rtd";
import {
  runVmemClaimPagesSync,
  runVmemListPrePageSync,
  type VmemClaimPagesResult,
  type VmemListPrePageSyncResult,
  type VmemPrePageObject,
} from "./vmem";

const DEFAULT_CHARS_PER_TOKEN = 4;
const MIN_CHARS_PER_TOKEN = 0.25;
const MAX_CHARS_PER_TOKEN = 100;

interface TokenCalibrationState {
  schema_version?: unknown;
  source?: unknown;
  default_chars_per_token?: unknown;
  models?: Record<string, { chars_per_token?: unknown; source?: unknown; pair_count?: unknown }>;
}

function validCalibrationRatio(value: unknown): number | undefined {
  return typeof value === "number" &&
      Number.isFinite(value) &&
      value >= MIN_CHARS_PER_TOKEN &&
      value <= MAX_CHARS_PER_TOKEN
    ? value
    : undefined;
}

function readCalibrationState(home: string): TokenCalibrationState | undefined {
  try {
    return JSON.parse(
      readFileSync(join(home, "state", "calibration", "tokens.json"), "utf8"),
    ) as TokenCalibrationState;
  } catch {
    return undefined;
  }
}

function calibrationRatio(home?: string, model?: string): number {
  if (!home) return DEFAULT_CHARS_PER_TOKEN;
  const state = readCalibrationState(home);
  if (state?.schema_version !== 1) return DEFAULT_CHARS_PER_TOKEN;
  const entry = state.models?.[model ?? "default"];
  const calibrated = entry?.source === "calibrated" &&
      typeof entry.pair_count === "number" &&
      Number.isInteger(entry.pair_count) &&
      entry.pair_count > 0
    ? validCalibrationRatio(entry.chars_per_token)
    : undefined;
  return calibrated ??
    (state.source === "default" ? validCalibrationRatio(state.default_chars_per_token) : undefined) ??
    DEFAULT_CHARS_PER_TOKEN;
}

export function estimateTokens(value: unknown, model?: string, home?: string): number {
  return Math.max(1, Math.floor(serializedSize(value) / calibrationRatio(home, model)));
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

/** The exact, literal first line `buildVmemPointerText` always produces.
 * Repair B double-wrap guard: an element whose content already starts with
 * this is a PREVIOUSLY paged message, never a fresh candidate. */
const VMEM_POINTER_PREFIX = "[SECOND_BRAIN_VMEM]";

/** Narrow, O(1)-ish exact-prefix check ONLY — never a broad scan of
 * arbitrary content. Checks the SAME two shapes `buildVmemPointerText`'s
 * output already takes: a plain string (`custom`/AutoInject) or an array
 * whose first block carries `.text` (`toolResult`). Any other shape is
 * simply not already-pointerized. */
function isAlreadyPointerized(content: unknown): boolean {
  if (typeof content === "string") return content.startsWith(VMEM_POINTER_PREFIX);
  if (Array.isArray(content) && content.length > 0) {
    const first = content[0];
    if (first !== null && typeof first === "object" && !Array.isArray(first)) {
      const text = (first as Record<string, unknown>).text;
      if (typeof text === "string") return text.startsWith(VMEM_POINTER_PREFIX);
    }
  }
  return false;
}

/** Structural check ONLY (no VMem call yet) — is this element even the
 * right shape to be a paging candidate, and does it carry a correlation
 * key? Mirrors Pilot 2's real captured schema exactly (Part A of this doc).
 * Repair B: the double-wrap guard runs FIRST, before any other check, so
 * an already-pointerized message never even reaches the residency-state
 * split / claim / reprojection decision. */
function candidateFor(element: unknown): PageCandidate | null {
  if (element === null || typeof element !== "object" || Array.isArray(element)) return null;
  const obj = element as Record<string, unknown>;

  if (obj.role === "custom" && obj.customType === AUTOINJECT_CUSTOM_TYPE) {
    if (isAlreadyPointerized(obj.content)) return null;
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
    if (isAlreadyPointerized(obj.content)) return null;
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
  /** Path A ONLY: candidates actually sent to the claim call (step 5,
   * bounded by `max_pages_per_context_event`) — reprojections (Path B)
   * were never "requested" to claim, so this is never inflated by them. */
  requestedPageCount?: number;
  /** Path A ONLY: candidates the claim call actually confirmed (step 6). */
  claimedPageCount?: number;
  /** Repair B: objects actually transitioned RESIDENT/FAULTED_IN ->
   * EVICTED this event (Path A's real state-transition count — the same
   * real count `claimedPageCount` already meant). */
  newlyClaimedCount?: number;
  /** Repair B: already-EVICTED, proof-backed objects pointerized this
   * event via reprojection (Path B) — ZERO DB writes, no claim call. */
  reprojectedPageCount?: number;
  /** Estimated tokens of the ORIGINAL content of the elements actually
   * replaced (same ~4-chars/token estimate as the budget check). */
  estimatedTokensBefore?: number;
  /** Estimated tokens of the REPLACEMENT content of the elements actually
   * replaced. */
  estimatedTokensAfter?: number;
  /** Distinct VMem object kinds actually paged this event. */
  objectKinds?: string[];
  /** Distinct pre-page residency states of the objects actually paged
   * (RESIDENT/FAULTED_IN for Path A, EVICTED for Path B). */
  stateBefore?: string[];
  /** Post-page residency state label(s) of the objects actually paged:
   * `"EVICTED"` for a real Path A state transition, `"EVICTED_REPROJECTED"`
   * for a Path B no-op relabel (already EVICTED, no state change, no DB
   * write — just pointerized again). */
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
    for (const candidate of candidates) {
      estimatedTotal += estimateTokens(messages[candidate.index], undefined, options.home);
    }
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
      // Repair B: PRE-PAGE states (RESIDENT/FAULTED_IN, Path A) PLUS
      // already-EVICTED (Path B reprojection) are all correlation
      // candidates now — everything else (STORED/SUPERSEDED/PURGED/etc.)
      // still falls through untouched, unweakened.
      if (
        obj.residencyState !== "RESIDENT" &&
        obj.residencyState !== "FAULTED_IN" &&
        obj.residencyState !== "EVICTED"
      ) {
        continue;
      }
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
    // max_pages_per_context_event, in message-index order. Both Path A
    // (RESIDENT/FAULTED_IN) and Path B (already-EVICTED) candidates share
    // this SAME bound, combined, exactly as any other candidate would.
    const selected = correlated.slice(0, options.cfg.maxPagesPerContextEvent);

    // Repair B split: Path A (needs a real claim) vs Path B (already
    // EVICTED, proof-backed, reprojected directly — no claim, no DB write).
    const residentGroup = selected.filter(
      (s) => s.match.residencyState === "RESIDENT" || s.match.residencyState === "FAULTED_IN",
    );
    const evictedGroup = selected.filter((s) => s.match.residencyState === "EVICTED");

    // Step 6 (Defect B, Path A only): the ONE claim call — the ONLY
    // mutation attempt this function ever makes, reached only when the
    // RESIDENT/FAULTED_IN group is non-empty. NOTHING for this group is
    // constructed before this returns a confirmed success list (the single
    // most important ordering rule here, unchanged from before this pass).
    // No claim call is EVER made for an object that is already EVICTED —
    // when `residentGroup` is empty (e.g. an all-reprojection event), this
    // call is skipped entirely.
    //
    // Repair B claim-failure design decision (documented + tested, see
    // module docstring): a failed/thrown claim call is caught LOCALLY here
    // (not by this function's top-level fail-open catch) so it can never
    // suppress Path B — EVICTED reprojection candidates in the SAME event
    // are still pointerized independently, since reprojection performs no
    // subprocess call and needs no claim at all. If `evictedGroup` is also
    // empty (a pure RESIDENT/FAULTED_IN event), the ORIGINAL fully
    // fail-open shape is preserved below, byte-for-byte.
    let claimedSet = new Set<string>();
    let claimError: string | undefined;
    if (residentGroup.length > 0) {
      const claimFn = options.claimPages ?? runVmemClaimPagesSync;
      let claimResult: VmemClaimPagesResult;
      try {
        claimResult = claimFn({
          home: options.home,
          hostSessionId: options.hostSessionId,
          candidates: residentGroup.map((s) => ({ objId: s.match.objId, kind: s.match.kind })),
          python: options.python,
          timeoutMs: options.timeoutMs,
        });
      } catch (error) {
        claimResult = { ok: false, error: error instanceof Error ? error.message : "vmem claim-pages failed" };
      }
      if (claimResult.ok && claimResult.claimedObjIds !== undefined) {
        claimedSet = new Set(claimResult.claimedObjIds);
      } else {
        claimError = claimResult.error ?? "vmem claim-pages failed";
      }
    }

    if (claimError !== undefined && evictedGroup.length === 0) {
      // Pure Path A failure, nothing to reproject: Part E fail-open,
      // UNCHANGED from before this pass.
      return { messages: undefined, pagedCount: 0, error: claimError };
    }

    // Step 7: build the replacement patch.
    //   - Path A: ONLY for confirmed-claimed obj_ids. A candidate whose
    //     claim did not succeed (lost a race, wrong state, unknown object,
    //     or the claim call itself failed) is left completely untouched.
    //   - Path B: EVERY selected EVICTED candidate — already proof-backed,
    //     already EVICTED, nothing further to verify at the state-machine
    //     level, zero DB mutation.
    let patched: unknown[] | undefined;
    let newlyClaimedCount = 0;
    let reprojectedCount = 0;
    const kindsPaged = new Set<string>();
    const statesBeforePaged = new Set<string>();
    const statesAfterPaged = new Set<string>();
    let tokensBefore = 0;
    let tokensAfter = 0;
    for (const { candidate, match } of selected) {
      const isReprojection = match.residencyState === "EVICTED";
      if (!isReprojection && !claimedSet.has(match.objId)) continue;

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

      tokensBefore += estimateTokens(original, undefined, options.home);
      tokensAfter += estimateTokens(replacement, undefined, options.home);
      statesAfterPaged.add(isReprojection ? "EVICTED_REPROJECTED" : "EVICTED");
      kindsPaged.add(match.kind);
      if (match.residencyState) statesBeforePaged.add(match.residencyState);

      if (patched === undefined) patched = messages.slice();
      patched[candidate.index] = replacement;
      if (isReprojection) reprojectedCount += 1;
      else newlyClaimedCount += 1;
    }

    if (patched === undefined) {
      // Selected candidates existed, but neither path actually replaced
      // anything (claim confirmed none, and no reprojection candidates).
      if (claimError !== undefined) return { messages: undefined, pagedCount: 0, error: claimError };
      return noop;
    }
    const pagedCount = newlyClaimedCount + reprojectedCount;
    const result: PageContextResult = {
      messages: patched,
      pagedCount,
      candidateCount: candidates.length,
      eligibleCount: correlated.length,
      pressureEstimatedTokens: estimatedTotal,
      residentBudget: options.cfg.residentTokenBudget,
      requestedPageCount: residentGroup.length,
      claimedPageCount: claimedSet.size,
      newlyClaimedCount,
      reprojectedPageCount: reprojectedCount,
      estimatedTokensBefore: tokensBefore,
      estimatedTokensAfter: tokensAfter,
      objectKinds: [...kindsPaged],
      stateBefore: [...statesBeforePaged],
      stateAfter: [...statesAfterPaged],
    };
    // Partial-success case: the RESIDENT/FAULTED_IN claim call failed but
    // one or more EVICTED reprojection candidates in the SAME event were
    // still pointerized independently (see the claim-failure design
    // decision above) — surface the claim error for observability without
    // ever treating this as a full no-op.
    if (claimError !== undefined) result.error = claimError;
    return result;
  } catch (error) {
    // Part E fail-open: never throw from this module.
    return {
      messages: undefined,
      pagedCount: 0,
      error: error instanceof Error ? error.message : "context paging failed",
    };
  }
}
