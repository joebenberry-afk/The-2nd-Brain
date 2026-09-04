/**
 * Prime <-> Context Virtual Memory (VMem) bridge (plan §6, Phase R3; Parts
 * B-E RC4 pass).
 *
 * VMem (`src/second_brain/vmem.py`) is a real, tested, session-object-level
 * paging store, reachable via `second_brain vmem ...` CLI subcommands (§
 * 01-rc3-evidence-disposition / 02-prime-live-callgraph). This module wires:
 *   - `compact-prep`/`hot-context` — the two compaction-boundary operations
 *     VMem's own docstrings describe as its natural integration point (§6.7
 *     "Compaction barrier interaction"): bookkeeping only, advances
 *     residency state and reports counts as telemetry.
 *   - `store` — admission of an already-computed structured reference
 *     object (Phase B admission), now with an optional `metadata` field
 *     (Part C: threads into `VMemStore.store_object`'s existing, previously
 *     unused `metadata` parameter) so a live message element (a
 *     `toolCallId` or `delivery_id`) can be correlated back to a specific
 *     VMem object.
 *   - `list` (synchronous, Part B/C) — the one correlation query
 *     `context-paging.ts` needs: "is a given object EVICTED right now, for
 *     THIS session". Pilot 2 (outputs/reports/rc4/12-real-prime-pilot-2.md)
 *     captured the real Prime `context` message shape, so a bounded
 *     `{messages}` replacement patch is now possible for exactly two
 *     eligible element classes (see context-paging.ts) — everything else
 *     still passes through completely untouched.
 *   - `resolve` (Part D) — explicit fault-in + durable backing resolution,
 *     exposed here only as a bridge function for Pilot 3's deliberate
 *     operator step; nothing calls it automatically yet.
 *
 * Fail-open, same subprocess pattern as `ledger-mirror.ts`'s
 * runLedgerCheckpoint/runLedgerSegmentRollover and `rtd.ts`'s
 * cliRtdPreserver: any spawn/parse failure resolves `ok: false` with an
 * `error` string, never throws.
 */
import { execFile, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const VMEM_DEFAULT_TIMEOUT_MS = 5000;
/** Shorter than the async default: this is the only SYNCHRONOUS subprocess
 * call in the extension, deliberately timeout-bounded (see runVmemListSync). */
const VMEM_LIST_SYNC_TIMEOUT_MS = 3000;

function pythonExe(home: string, python?: string): string {
  return python ?? process.env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe");
}

function runEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

export interface VmemCompactPrepResult {
  ok: boolean;
  evictedAtCompaction?: number;
  pinnedPreserved?: number;
  error?: string;
}

/** `second_brain vmem compact-prep <session> --json`: mark unpinned resident
 * objects EVICTED ahead of a real compaction event. */
export function runVmemCompactPrep(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
}): Promise<VmemCompactPrepResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem compact-prep unavailable)" });
  }
  return new Promise((resolve) => {
    execFile(
      python,
      ["-m", "second_brain", "vmem", "compact-prep", options.hostSessionId, "--json"],
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        try {
          const parsed = JSON.parse(stdout) as {
            evicted_at_compaction?: number;
            pinned_preserved?: number;
          };
          resolve({
            ok: true,
            evictedAtCompaction: parsed.evicted_at_compaction,
            pinnedPreserved: parsed.pinned_preserved,
          });
        } catch {
          resolve({ ok: false, error: "compact-prep returned unparsable output" });
        }
      },
    );
  });
}

export interface VmemStoreOptions {
  home: string;
  hostSessionId: string;
  /** SessionObjectKind (vmem.py): WORKER_FINDING | TEST_EVIDENCE |
   * LOG_EXCERPT | TOOL_OBSERVATION | CODE_REGION | DECISION | BLOCKER |
   * RESEARCH_RESULT | GENERIC. Invalid values fall back to GENERIC
   * (store_object's own behavior — never rejected here). */
  kind: string;
  title: string;
  /** Small structured text (ids/hashes/sizes only — never raw prompt, tool
   * output, or memory text). Sent via stdin, never a CLI arg. */
  content: string;
  summary?: string;
  pinned?: boolean;
  /** Part C: small correlation keys ONLY (e.g. {toolCallId} for RTD,
   * {deliveryId} for AutoInject) — sent as `--metadata <json>` (a CLI arg,
   * not stdin: keep it small). `vmem list --json`'s output includes
   * `metadata` but NOT `content`, so this is the only way context-paging.ts
   * can correlate a live message element back to a specific EVICTED VMem
   * object without an extra per-element resolve() call. Never raw prompt/
   * tool content — same rule as `content` above. */
  metadata?: Record<string, unknown>;
  python?: string;
  timeoutMs?: number;
}

export interface VmemStoreResult {
  ok: boolean;
  objId?: string;
  error?: string;
}

/** `second_brain vmem store <session> <kind> <title> --json` (content piped
 * via stdin, same as `cliRtdPreserver`'s preserve()): admit an already-
 * computed, structured reference object into VMem's session-object store
 * (§6.7). Same fail-open subprocess pattern as runVmemCompactPrep/
 * runVmemHotContext — any spawn/parse failure resolves `ok: false`, never
 * throws, never blocks the caller. */
export function runVmemStore(options: VmemStoreOptions): Promise<VmemStoreResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem store unavailable)" });
  }
  const args = [
    "-m",
    "second_brain",
    "vmem",
    "store",
    options.hostSessionId,
    options.kind,
    options.title,
    "--json",
  ];
  if (options.summary !== undefined) args.push("--summary", options.summary);
  if (options.pinned) args.push("--pinned");
  if (options.metadata !== undefined) {
    let metadataJson: string | undefined;
    try {
      metadataJson = JSON.stringify(options.metadata);
    } catch {
      metadataJson = undefined; // unserializable metadata: omit the flag, never throw
    }
    if (metadataJson !== undefined) args.push("--metadata", metadataJson);
  }
  return new Promise((resolve) => {
    const child = execFile(
      python,
      args,
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        try {
          const parsed = JSON.parse(stdout) as { obj_id?: string };
          resolve({ ok: true, objId: parsed.obj_id });
        } catch {
          resolve({ ok: false, error: "store returned unparsable output" });
        }
      },
    );
    child.stdin?.write(options.content);
    child.stdin?.end();
  });
}

export interface VmemHotContextResult {
  ok: boolean;
  sessionId?: string;
  residentCount?: number;
  evictedCount?: number;
  residentTokens?: number;
  renderedText?: string;
  error?: string;
}

/** `second_brain vmem hot-context <session> --budget <n> --json`: render the
 * resident/evicted working set after a compaction boundary. Renders (not
 * mutates) — the model-visible context is untouched by this call. */
export function runVmemHotContext(options: {
  home: string;
  hostSessionId: string;
  budgetTokens: number;
  python?: string;
  timeoutMs?: number;
}): Promise<VmemHotContextResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem hot-context unavailable)" });
  }
  return new Promise((resolve) => {
    execFile(
      python,
      [
        "-m",
        "second_brain",
        "vmem",
        "hot-context",
        options.hostSessionId,
        "--budget",
        String(options.budgetTokens),
        "--json",
      ],
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        try {
          const parsed = JSON.parse(String(stdout)) as {
            session_id?: string;
            resident_count?: number;
            evicted_count?: number;
            resident_tokens?: number;
            rendered_text?: string;
          };
          const result: VmemHotContextResult = {
            ok: true,
            residentCount: parsed.resident_count,
            evictedCount: parsed.evicted_count,
            residentTokens: parsed.resident_tokens,
          };
          if (typeof parsed.session_id === "string") result.sessionId = parsed.session_id;
          if (typeof parsed.rendered_text === "string") result.renderedText = parsed.rendered_text;
          resolve(result);
        } catch {
          resolve({ ok: false, error: "hot-context returned unparsable output" });
        }
      },
    );
  });
}


// ---------------------------------------------------------------------------
// Part B/C (RC4 pass): the `context` event's REAL host contract
// (types/prime.d.ts `ContextEventResult | undefined`) is SYNCHRONOUS —
// unlike `before_agent_start`, there is no `Promise<...>` variant in the
// verified type surface. context-paging.ts's one correlation query ("is a
// given VMem object EVICTED right now, for THIS session") therefore cannot
// use the async execFile pattern every other bridge in this file uses; it
// must complete before the handler returns. This is the ONLY synchronous
// subprocess call in the extension — kept intentionally small, separate,
// short-timeout-bounded, and called at most once per `context` event by its
// only caller (never once per element).
// ---------------------------------------------------------------------------

export interface VmemListedObject {
  objId: string;
  kind: string;
  metadata: Record<string, unknown>;
}

export interface VmemListSyncResult {
  ok: boolean;
  objects?: VmemListedObject[];
  error?: string;
}

/** `second_brain vmem list <session> [--state <state>] --json` (synchronous).
 * Fail-open: any spawn/parse/timeout failure resolves `{ok: false, error}`,
 * never throws. */
export function runVmemListSync(options: {
  home: string;
  hostSessionId: string;
  state?: string;
  python?: string;
  timeoutMs?: number;
}): VmemListSyncResult {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return { ok: false, error: "no brain venv (vmem list unavailable)" };
  }
  const args = ["-m", "second_brain", "vmem", "list", options.hostSessionId, "--json"];
  if (options.state) args.push("--state", options.state);
  try {
    const stdout = execFileSync(python, args, {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? VMEM_LIST_SYNC_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      encoding: "utf8",
    });
    const parsed: unknown = JSON.parse(stdout);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "list returned non-array output" };
    }
    const objects: VmemListedObject[] = [];
    for (const item of parsed) {
      if (item === null || typeof item !== "object") continue;
      const rec = item as Record<string, unknown>;
      if (typeof rec.obj_id !== "string" || typeof rec.kind !== "string") continue;
      const metadata =
        rec.metadata !== null && typeof rec.metadata === "object" && !Array.isArray(rec.metadata)
          ? (rec.metadata as Record<string, unknown>)
          : {};
      objects.push({ objId: rec.obj_id, kind: rec.kind, metadata });
    }
    return { ok: true, objects };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "vmem list failed" };
  }
}


// ---------------------------------------------------------------------------
// Defect B (RC4 proactive-paging-repair pass): pre-page correlation query +
// the claim call. Pilot 3 found VMem objects only ever became EVICTED via
// `prepare_compaction()`, at the SAME real compaction event that removed
// the corresponding old live message from `event.messages` entirely — so a
// paging pass that only ever looked for already-EVICTED objects could
// never find a real match. `context-paging.ts`'s `pageContext` now causes
// the RESIDENT/FAULTED_IN -> EVICTED transition itself, BEFORE Prime's own
// compaction ever runs, via these two bridge functions. Same synchronous,
// short-timeout-bounded pattern as `runVmemListSync` above (the real
// `context` host contract has no async variant).
// ---------------------------------------------------------------------------

/** A `vmem list` object additionally carrying `residency_state`/`pinned`
 * (already present in the CLI's `to_dict()` JSON, simply not previously
 * read). Deliberately a SEPARATE type/function from `VmemListedObject`/
 * `runVmemListSync` above — rather than extending that function's return
 * shape — so the EXISTING `runVmemListSync` contract/tests (which target
 * EVICTED objects only) stay byte-for-byte unchanged. */
export interface VmemPrePageObject extends VmemListedObject {
  residencyState: string;
  pinned: boolean;
}

export interface VmemListPrePageSyncResult {
  ok: boolean;
  objects?: VmemPrePageObject[];
  error?: string;
}

/** `second_brain vmem list <session> --json` (synchronous, NO `--state`
 * filter — every residency state for this session, in ONE bounded call).
 * The Defect B pre-page correlation query: callers filter client-side to
 * PRE-PAGE states (RESIDENT, optionally FAULTED_IN) and exclude PINNED
 * objects — see `context-paging.ts`. Fail-open: any spawn/parse/timeout
 * failure resolves `{ok: false, error}`, never throws. */
export function runVmemListPrePageSync(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
}): VmemListPrePageSyncResult {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return { ok: false, error: "no brain venv (vmem list unavailable)" };
  }
  const args = ["-m", "second_brain", "vmem", "list", options.hostSessionId, "--json"];
  try {
    const stdout = execFileSync(python, args, {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? VMEM_LIST_SYNC_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      encoding: "utf8",
    });
    const parsed: unknown = JSON.parse(stdout);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "list returned non-array output" };
    }
    const objects: VmemPrePageObject[] = [];
    for (const item of parsed) {
      if (item === null || typeof item !== "object") continue;
      const rec = item as Record<string, unknown>;
      if (typeof rec.obj_id !== "string" || typeof rec.kind !== "string") continue;
      const metadata =
        rec.metadata !== null && typeof rec.metadata === "object" && !Array.isArray(rec.metadata)
          ? (rec.metadata as Record<string, unknown>)
          : {};
      const residencyState = typeof rec.residency_state === "string" ? rec.residency_state : "";
      const pinned = rec.pinned === true;
      objects.push({ objId: rec.obj_id, kind: rec.kind, metadata, residencyState, pinned });
    }
    return { ok: true, objects };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "vmem list failed" };
  }
}

export interface VmemClaimPagesResult {
  ok: boolean;
  claimedObjIds?: string[];
  error?: string;
}

/** `second_brain vmem claim-pages <session> --json` (synchronous, stdin
 * JSON `{"candidates":[{"obj_id":..., "kind":...}, ...]}`): atomically
 * attempt to transition EXACTLY the given obj_ids from their current
 * pre-page residency state (RESIDENT/FAULTED_IN, unpinned) to EVICTED, and
 * return which ones ACTUALLY succeeded — the compare-and-set winner list
 * (see `VMemStore.claim_pages`, vmem.py). This is "the claim" —
 * `context-paging.ts` calls this AT MOST ONCE per `context` event, only
 * once selected candidates exist, and never constructs a replacement patch
 * before this call returns. Fail-open: any spawn/parse/timeout failure
 * resolves `{ok: false, error}`, never throws. */
export function runVmemClaimPagesSync(options: {
  home: string;
  hostSessionId: string;
  candidates: Array<{ objId: string; kind: string }>;
  python?: string;
  timeoutMs?: number;
}): VmemClaimPagesResult {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return { ok: false, error: "no brain venv (vmem claim-pages unavailable)" };
  }
  const args = ["-m", "second_brain", "vmem", "claim-pages", options.hostSessionId, "--json"];
  let payload: string;
  try {
    payload = JSON.stringify({
      candidates: options.candidates.map((c) => ({ obj_id: c.objId, kind: c.kind })),
    });
  } catch {
    return { ok: false, error: "unserializable claim-pages candidates" };
  }
  try {
    const stdout = execFileSync(python, args, {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? VMEM_LIST_SYNC_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      encoding: "utf8",
      input: payload,
    });
    const parsed: unknown = JSON.parse(stdout);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "claim-pages returned non-array output" };
    }
    const claimedObjIds = parsed.filter((item): item is string => typeof item === "string");
    return { ok: true, claimedObjIds };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "vmem claim-pages failed" };
  }
}

export interface VmemEvictResult {
  ok: boolean;
  evictedCount?: number;
  evictedTokens?: number;
  error?: string;
}

export function runVmemEvictSync(options: {
  home: string;
  hostSessionId: string;
  budgetTokens: number;
  python?: string;
  timeoutMs?: number;
}): VmemEvictResult {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return { ok: false, error: "no brain venv (vmem evict unavailable)" };
  }
  const args = ["-m", "second_brain", "vmem", "evict", options.hostSessionId, "--budget", String(options.budgetTokens), "--json"];
  try {
    const stdout = execFileSync(python, args, {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? VMEM_LIST_SYNC_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      encoding: "utf8",
    });
    const parsed: unknown = JSON.parse(stdout);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "evict returned non-array output" };
    }
    let evictedTokens = 0;
    for (const item of parsed) {
      if (item !== null && typeof item === "object") {
        const est = (item as Record<string, unknown>).token_estimate;
        if (typeof est === "number" && Number.isFinite(est)) {
          evictedTokens += est;
        }
      }
    }
    return { ok: true, evictedCount: parsed.length, evictedTokens };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "vmem evict failed" };
  }
}


// ---------------------------------------------------------------------------
// Part D (RC4 pass): explicit fault-in bridge. `second_brain vmem resolve`
// (src/second_brain/cli.py / vmem.py resolve_object) does the real work —
// fault_in() + durable backing resolution (deliveries+memories for
// RESEARCH_RESULT, the artifact store for TOOL_OBSERVATION, raw passthrough
// otherwise), never an LLM summarizer. This bridge mirrors the existing
// runVmemStore/runVmemCompactPrep async pattern and is exported + unit-
// tested even though nothing in index.ts calls it automatically yet —
// Pilot 3 will invoke real fault-in as a deliberate operator step, the same
// spirit as RTD's own `/brain-expand` recovery path.
// ---------------------------------------------------------------------------

export interface VmemResolveResult {
  ok: boolean;
  content?: string;
  resolution?: string;
  error?: string;
}

/** `second_brain vmem resolve <session> <obj_id> --json`: explicit fault-in
 * + durable backing resolution. Fail-open: any spawn/parse failure resolves
 * `{ok: false, error}`, never throws. */
export function runVmemResolve(options: {
  home: string;
  hostSessionId: string;
  objId: string;
  python?: string;
  timeoutMs?: number;
}): Promise<VmemResolveResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem resolve unavailable)" });
  }
  return new Promise((resolve) => {
    execFile(
      python,
      ["-m", "second_brain", "vmem", "resolve", options.hostSessionId, options.objId, "--json"],
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 32 * 1024 * 1024,
      },
      (error, stdout) => {
        // The CLI itself exits non-zero on a structured failure (see
        // cli.py's `resolve` branch: `0 if result["ok"] else 1`) — parse
        // stdout regardless of exit code before treating it as a spawn
        // failure, so a clean {ok:false,...} JSON body is not discarded.
        try {
          const parsed = JSON.parse(stdout) as { ok?: unknown; content?: unknown; resolution?: unknown; error?: unknown };
          if (typeof parsed.ok === "boolean") {
            return resolve({
              ok: parsed.ok,
              content: typeof parsed.content === "string" ? parsed.content : undefined,
              resolution: typeof parsed.resolution === "string" ? parsed.resolution : undefined,
              error: typeof parsed.error === "string" ? parsed.error : undefined,
            });
          }
        } catch {
          // fall through to the spawn-error/unparsable-output path below
        }
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        resolve({ ok: false, error: "resolve returned unparsable output" });
      },
    );
  });
}
