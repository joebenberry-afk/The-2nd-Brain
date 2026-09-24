/**
 * P0 AutoInject host adapter — SHADOW (plan §6.9/§6.10, Phase 0C part 2).
 *
 * Thin deterministic adapter: on host lifecycle events it spawns the Python
 * control CLI (`second_brain autoinject shadow --json`) once per event,
 * records the decision privacy-safe, and NEVER returns a packet/patch in
 * shadow mode. Fail-open: any spawn error, timeout, non-zero exit, or parse
 * failure records an `extension_error` and resolves silently — the host
 * session is never blocked and never mutated.
 *
 * Mode switch: SECOND_BRAIN_AUTOINJECT_MODE = "shadow" (default) | "off".
 * "advisory"/"active" are reserved for Phase 0D and deliberately not
 * accepted here.
 *
 * Spawn contract (verified against cli.py `cmd_autoinject`):
 *   <home>/.venv/Scripts/python.exe -m second_brain autoinject shadow
 *     --task <task> --project <project> --session <sid> --agent <aid>
 *     --branch <branch> --role <role> --json
 * with cwd=<home>, SECOND_BRAIN_HOME=<home>, PYTHONHOME/PYTHONPATH removed.
 * stdout is ONE canonical JSON object (contracts.canonical_json).
 */
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { autoinjectShadowDecision, extensionError } from "./sensors";

export const AUTOINJECT_DEFAULT_TIMEOUT_MS = 5000;
export const AUTOINJECT_MODE_OFF_VALUES = new Set(["off", "0", "false", "no"]);
export const AUTOINJECT_MODE_ACTIVE_VALUES = new Set(["advisory", "active", "1", "true", "yes"]);
export const AUTOINJECT_CUSTOM_TYPE = "brain.autoinject.packet";
export const AUTOINJECT_DEFAULT_EMIT_TTL_MS = 45000;
export const AUTOINJECT_EMIT_TTL_ENV = "SECOND_BRAIN_AUTOINJECT_EMIT_TTL_MS";
/** Windows argv safety margin for --task (CreateProcess ~32k char limit). */
export const AUTOINJECT_MAX_TASK_ARG_CHARS = 4000;

export type AutoInjectMode = "off" | "shadow" | "advisory" | "active";

export interface AutoInjectHostConfig {
  mode: AutoInjectMode;
  timeoutMs: number;
}

/**
 * Read `[autoinject] mode` from `<home>/config/autoinject.toml` using the
 * same tiny TOML-subset parser style as config.ts (`[section]` headers,
 * `key = value` lines, `#` comments). Returns undefined when home is null,
 * the file is missing/unreadable, or the key is absent/invalid. The file is
 * the LIVE FLIP SWITCH (Phase C): editing it takes effect on the next event
 * without redeploying; rollback = set `mode = "shadow"`.
 */
export function modeFromAutoinjectToml(text: string): AutoInjectMode | undefined {
  let inAutoinject = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inAutoinject = line.startsWith("[autoinject]");
      continue;
    }
    if (!inAutoinject || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    if (key !== "mode") continue;
    const value = line.slice(eq + 1).split("#")[0].trim().replace(/^"|"$/g, "").toLowerCase();
    if (AUTOINJECT_MODE_OFF_VALUES.has(value)) return "off";
    if (value === "advisory" || value === "active") return value;
    if (value === "shadow") return "shadow";
    return undefined;
  }
  return undefined;
}

export interface AutoInjectEmitEntry {
  /** Cached patch payload (undefined when the decision produced no packet). */
  message:
    | { customType: string; content: string; display: boolean; details: unknown }
    | undefined;
  /** Outcome from the spawn that populated the cache. */
  outcome: AutoInjectShadowOutcome | null;
  /** Number of emits served by this entry (1 = the spawning emit). */
  emits: number;
  expiresAt: number;
  createdAt: number;
  taskSha256: string;
  projectId: string;
  retrievalConfigFingerprint: string;
  corpusGeneration: string;
  runtimeBuildIdentity: string;
}

/**
 * Per-extension-process emit cache (Phase C5): the host re-emits
 * before_agent_start multiple times per turn and the LAST result wins, so
 * every re-emit of the SAME task must return the SAME computed message
 * without re-spawning (which also prevents duplicate deliveries and
 * re-resolution variance such as project=default). Key = session + task
 * sha256; TTL bounds staleness; process-scoped, no global clearing needed.
 */
const autoInjectEmitCache = new Map<string, AutoInjectEmitEntry>();

export function autoInjectEmitCacheSize(): number {
  return autoInjectEmitCache.size;
}

/** Test seam: clear the process-scoped emit cache. */
export function resetAutoInjectEmitCache(): void {
  autoInjectEmitCache.clear();
}

/**
 * Cross-process emit cache (Phase C6): the daemon can recover/replace the
 * session worker mid-turn (observed: "Session worker is recovering" while a
 * turn was preparing), which resets the in-memory cache and makes a
 * recovered worker re-spawn + possibly drop the message (last-emit-wins).
 * Persist entries to <brain home>/state/autoinject-emit-cache.json so cache
 * hits work ACROSS processes. Best-effort: persistence failures never break
 * injection (fail open to in-memory-only behavior).
 */
/**
 * Resolve the cache directory home defensively: prefer the caller's home,
 * fall back to SECOND_BRAIN_HOME, then to the OS default brain path
 * (mirrors config.ts resolveBrainHome semantics for the state file).
 */
function emitCacheHome(home: string): string {
  if (home !== undefined && home.trim().length > 0) return home;
  const envHome = process.env.SECOND_BRAIN_HOME;
  if (envHome !== undefined && envHome.trim().length > 0) return envHome;
  const base = process.env.USERPROFILE ?? process.env.HOME ?? "";
  return join(base, "Documents", "The-Second-Brain");
}

function emitCacheFile(home: string): string {
  return join(emitCacheHome(home), "state", "autoinject-emit-cache.json");
}

interface PersistedEmitEntry {
  message:
    | { customType: string; content: string; display: boolean; details: unknown }
    | null;
  outcome: AutoInjectShadowOutcome | null;
  emits: number;
  expiresAt: number;
  createdAt: number;
  taskSha256: string;
  projectId: string;
  retrievalConfigFingerprint: string;
  corpusGeneration: string;
  runtimeBuildIdentity: string;
}

function loadEmitCache(home: string): void {
  try {
    const raw = readFileSync(emitCacheFile(home), "utf8");
    const data = JSON.parse(raw) as Record<string, PersistedEmitEntry>;
    const now = Date.now();
    for (const [key, entry] of Object.entries(data)) {
      if (
        entry !== null &&
        typeof entry === "object" &&
        typeof entry.expiresAt === "number" &&
        entry.expiresAt > now &&
        !autoInjectEmitCache.has(key)
      ) {
        autoInjectEmitCache.set(key, {
          message: entry.message ?? undefined,
          outcome: entry.outcome ?? null,
          emits: typeof entry.emits === "number" ? entry.emits : 1,
          expiresAt: entry.expiresAt,
          createdAt: typeof entry.createdAt === "number" ? entry.createdAt : now,
          taskSha256: typeof entry.taskSha256 === "string" ? entry.taskSha256 : "",
          projectId: typeof entry.projectId === "string" ? entry.projectId : "",
          retrievalConfigFingerprint:
            typeof entry.retrievalConfigFingerprint === "string"
              ? entry.retrievalConfigFingerprint
              : "",
          corpusGeneration:
            typeof entry.corpusGeneration === "string" ? entry.corpusGeneration : "",
          runtimeBuildIdentity:
            typeof entry.runtimeBuildIdentity === "string" ? entry.runtimeBuildIdentity : "",
        });
      }
    }
  } catch {
    // missing/corrupt file -> empty cache (fail open)
  }
}

function persistEmitCache(home: string): void {
  const target = emitCacheFile(home);
  const lockPath = `${target}.lock`;
  let lock: number | undefined;
  let tmp: string | undefined;
  try {
    const dir = join(emitCacheHome(home), "state");
    mkdirSync(dir, { recursive: true });
    lock = openSync(lockPath, "wx");
    const now = Date.now();
    const data: Record<string, PersistedEmitEntry> = {};
    for (const [key, entry] of autoInjectEmitCache) {
      if (entry.expiresAt > now) {
        data[key] = {
          message: entry.message ?? null,
          outcome: entry.outcome,
          emits: entry.emits,
          expiresAt: entry.expiresAt,
          createdAt: entry.createdAt,
          taskSha256: entry.taskSha256,
          projectId: entry.projectId,
          retrievalConfigFingerprint: entry.retrievalConfigFingerprint,
          corpusGeneration: entry.corpusGeneration,
          runtimeBuildIdentity: entry.runtimeBuildIdentity,
        };
      }
    }
    tmp = `${target}.${process.pid}.${Date.now()}.tmp`;
    writeFileSync(tmp, JSON.stringify(data));
    renameSync(tmp, target);
  } catch {
    // A competing writer or filesystem failure only disables persistence.
  } finally {
    if (lock !== undefined) closeSync(lock);
    if (tmp && existsSync(tmp)) unlinkSync(tmp);
    if (lock !== undefined && existsSync(lockPath)) unlinkSync(lockPath);
  }
}

function emitTtlMs(): number {
  const raw = Number(process.env[AUTOINJECT_EMIT_TTL_ENV] ?? AUTOINJECT_DEFAULT_EMIT_TTL_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : AUTOINJECT_DEFAULT_EMIT_TTL_MS;
}

function fileFingerprint(path: string): string {
  try {
    return createHash("sha256").update(readFileSync(path)).digest("hex");
  } catch {
    return "missing";
  }
}

function corpusGeneration(home: string): string {
  // The whole brain.sqlite file's mtime changes on every ledger/telemetry/
  // heartbeat write, which happens on nearly every OMP turn -- using it here
  // would invalidate the cross-process cache almost every call, defeating
  // the cache entirely (confirmed live: cache_hit stayed false across a
  // resumed OMP session with an identical repeated task). `brain_meta`'s
  // `memory_epoch` row is bumped ONLY when canonical memory content itself
  // changes (second_brain.db.bump_memory_epoch), so it is the correct,
  // narrow invalidation signal. Read it directly via Node's built-in
  // `node:sqlite` (supported natively by both Bun and Node, no new
  // dependency) so a cache-hit check never pays a Python spawn to avoid one.
  let db: DatabaseSync | undefined;
  try {
    db = new DatabaseSync(join(home, "db", "brain.sqlite"), { readOnly: true });
    const row = db
      .prepare("SELECT value FROM brain_meta WHERE key = 'memory_epoch'")
      .get() as { value?: string } | undefined;
    return row?.value ?? "0";
  } catch {
    return "unknown";
  } finally {
    db?.close();
  }
}

function emitKey(call: ShadowAutoInjectCall, task: string): string {
  const identity = {
    session: call.session,
    taskSha256: createHash("sha256").update(task, "utf8").digest("hex"),
    project: process.env.SECOND_BRAIN_PROJECT ?? "",
    cwd: call.cwd ?? "",
    mode: call.cfg.mode,
    timeoutMs: call.cfg.timeoutMs,
    autoinjectConfig: fileFingerprint(join(call.home, "config", "autoinject.toml")),
    retrievalConfig: fileFingerprint(join(call.home, "config", "retrieval.toml")),
    corpusGeneration: corpusGeneration(call.home),
    runtime: process.env.SECOND_BRAIN_RUNTIME_ROOT ?? process.env.SECOND_BRAIN_PYTHON ?? "",
  };
  return createHash("sha256").update(JSON.stringify(identity), "utf8").digest("hex");
}

function entryProvenance(call: ShadowAutoInjectCall, task: string) {
  return {
    createdAt: Date.now(),
    taskSha256: createHash("sha256").update(task, "utf8").digest("hex"),
    projectId: call.projectId ?? process.env.SECOND_BRAIN_PROJECT ?? "default",
    retrievalConfigFingerprint: fileFingerprint(
      join(call.home, "config", "retrieval.toml"),
    ),
    corpusGeneration: corpusGeneration(call.home),
    runtimeBuildIdentity:
      process.env.SECOND_BRAIN_RUNTIME_ROOT ?? process.env.SECOND_BRAIN_PYTHON ?? "compat",
  };
}

function lookupEmitEntry(call: ShadowAutoInjectCall, task: string): AutoInjectEmitEntry | undefined {
  const entry = autoInjectEmitCache.get(emitKey(call, task));
  if (entry === undefined || entry.expiresAt <= Date.now()) return undefined;
  if (entry.taskSha256 !== createHash("sha256").update(task, "utf8").digest("hex")) {
    return undefined;
  }
  return entry;
}

export function loadAutoInjectHostConfig(home?: string | null): AutoInjectHostConfig {
  // Precedence: env override > config/autoinject.toml [autoinject] mode > shadow.
  const envRaw = (process.env.SECOND_BRAIN_AUTOINJECT_MODE ?? "").trim().toLowerCase();
  let mode: AutoInjectMode = "shadow";
  if (envRaw !== "") {
    if (AUTOINJECT_MODE_OFF_VALUES.has(envRaw)) mode = "off";
    else if (envRaw === "advisory" || envRaw === "active") mode = envRaw;
  } else if (home) {
    try {
      const text = readFileSync(join(home, "config", "autoinject.toml"), "utf8");
      mode = modeFromAutoinjectToml(text) ?? "shadow";
    } catch {
      // missing/unreadable file -> shadow (fail safe)
    }
  }
  const parsed = Number(process.env.SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS ?? AUTOINJECT_DEFAULT_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(parsed) && parsed > 0 ? parsed : AUTOINJECT_DEFAULT_TIMEOUT_MS;
  return { mode, timeoutMs };
}

/** Project id: no host event carries one today -> env override, else "default". */
export function resolveProject(): string {
  const p = process.env.SECOND_BRAIN_PROJECT;
  return p !== undefined && p.trim().length > 0 ? p.trim() : "default";
}

export interface AutoInjectShadowOutcome {
  decision: string;
  reason: string | null;
  packet: string | null;
  packetTokens: number | null;
  deliveryId: string | null;
  candidateCount: number;
  selectedCount: number;
  packetSha256: string | null;
  /** Length of the parsed packet text (Phase C7 instrumentation). */
  cliPacketChars: number | null;
  /** Length of the raw CLI stdout that was parsed. */
  cliStdoutChars: number;
  /** Canonical project id resolved by Python (autoinject.resolve_project). */
  projectId: string | null;
  /** Resolution rung: explicit | manifest | registry_path | git_remote | env | default. */
  projectResolution: string | null;
}

/**
 * Last project id Python resolved for each session (Phase 11 repair): the
 * host-visible prefix/other bridges must reuse the SAME canonical
 * resolution AutoInject already computed instead of an independent
 * env-only guess. Read via `resolvedProjectIdForSession`.
 */
const sessionProjectIds: Record<string, string> = {};

export function resolvedProjectIdForSession(session: string): string | undefined {
  return sessionProjectIds[session];
}

function rememberResolvedProject(session: string, outcome: AutoInjectShadowOutcome | null): void {
  if (outcome?.projectId) sessionProjectIds[session] = outcome.projectId;
}

export interface AutoInjectRunOptions {
  home: string;
  task: string;
  cwd?: string;
  sessionId: string;
  agentId: string;
  branchId?: string;
  roleProfile?: string;
  cfg: AutoInjectHostConfig;
  python?: string;
  env?: NodeJS.ProcessEnv;
}

export function parseShadowOutput(stdout: string): AutoInjectShadowOutcome | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const obj = parsed as Record<string, unknown>;
  if (typeof obj.decision !== "string") return null;
  const packet = typeof obj.packet === "string" ? obj.packet : null;
  return {
    decision: obj.decision,
    reason: typeof obj.reason === "string" ? obj.reason : null,
    packet,
    packetTokens: typeof obj.packet_tokens === "number" ? obj.packet_tokens : null,
    deliveryId: typeof obj.delivery_id === "string" ? obj.delivery_id : null,
    candidateCount: Array.isArray(obj.candidate_ids) ? obj.candidate_ids.length : 0,
    selectedCount: Array.isArray(obj.selected_ids) ? obj.selected_ids.length : 0,
    packetSha256:
      packet !== null ? createHash("sha256").update(packet, "utf8").digest("hex") : null,
    cliPacketChars: packet !== null ? packet.length : null,
    cliStdoutChars: stdout.length,
    projectId: typeof obj.project_id === "string" ? obj.project_id : null,
    projectResolution: typeof obj.project_resolution === "string" ? obj.project_resolution : null,
  };
}

/**
 * One bounded out-of-process spawn (execFile) with env cleanup and a hard
 * timeout. Resolves null on ANY failure (fail-open); never rejects.
 */
export function runAutoInjectShadow(options: AutoInjectRunOptions): Promise<AutoInjectShadowOutcome | null> {
  const python =
    options.python ??
    process.env.SECOND_BRAIN_PYTHON ??
    join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...(options.env ?? process.env) };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const task = options.task.slice(0, AUTOINJECT_MAX_TASK_ARG_CHARS);
  // Project resolution happens in Python (FIX 1): explicit --project or
  // Brain registry root containing cwd, then env, then "default". The host
  // passes its working directory; env SECOND_BRAIN_PROJECT still works.
  const args = [
    "-m",
    "second_brain",
    "autoinject",
    "shadow",
    "--task",
    task,
    "--session",
    options.sessionId,
    "--agent",
    options.agentId,
    "--branch",
    options.branchId ?? "main",
    "--role",
    options.roleProfile ?? "worker",
    "--json",
  ];
  if (options.cwd !== undefined && options.cwd.trim().length > 0) {
    args.push("--cwd", options.cwd);
  }
  return new Promise((resolve) => {
    execFile(
      python,
      args,
      {
        cwd: options.home,
        env,
        timeout: options.cfg.timeoutMs,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve(null);
          return;
        }
        resolve(parseShadowOutput(stdout));
      },
    );
  });
}

export interface ShadowAutoInjectCall {
  home: string;
  session: string;
  task: string;
  agentId: string;
  cwd?: string;
  projectId?: string;
  branchId?: string;
  roleProfile?: string;
  cfg: AutoInjectHostConfig;
  /**
   * Telemetry sink. Assumed non-throwing: TelemetryStore.append is
   * fire-and-forget — unserializable records are dropped and write failures
   * are swallowed by its internal promise chain (storage.ts) — so callers
   * may invoke it outside try/catch.
   */
  append: (record: unknown) => void;
  runner?: (options: AutoInjectRunOptions) => Promise<AutoInjectShadowOutcome | null>;
}

/**
 * Orchestrates one ADVISORY/ACTIVE decision: guard -> spawn -> record ->
 * return a LOW-AUTHORITY model-visible custom_message patch (SDK
 * BeforeAgentStartEventResult.message = Pick<CustomMessage, "customType" |
 * "content" | "display" | "details">; CustomMessage.role = "custom").
 * The packet itself carries "authority: advisory" (contracts renderer) —
 * this adapter never claims higher authority. NEVER throws; every failure
 * degrades to undefined (fail-open). Returns undefined for NO_INJECTION.
 */
export interface AdvisoryAutoInjectCall extends ShadowAutoInjectCall {
  customType?: string;
}

/**
 * Would {@link runAdvisoryAutoInject} serve a cached emit for this (session,
 * task)? The batched turn bridge (E01) probes this BEFORE it spawns, so a
 * host re-emit of the same prompt never re-runs the Python AutoInject
 * decision — exactly the ordering the per-phase path gets by checking the
 * cache before its spawn.
 */
export function advisoryEmitCached(call: ShadowAutoInjectCall, task: string): boolean {
  const trimmed = (task ?? "").trim();
  if (trimmed.length === 0) return false;
  loadEmitCache(call.home);
  return lookupEmitEntry(call, trimmed) !== undefined;
}

export async function runAdvisoryAutoInject(
  call: AdvisoryAutoInjectCall,
): Promise<{ customType: string; content: string; display: boolean; details: unknown } | undefined> {
  if (call.cfg.mode === "off" || call.cfg.mode === "shadow") return undefined;
  const task = (call.task ?? "").trim();
  if (task.length === 0) return undefined;
  // Phase C5/C6 emit stability: every re-emit of the same task returns the
  // SAME computed message without a new spawn (host re-emits
  // before_agent_start several times per turn; last result wins). The cache
  // is file-backed so a recovered session worker (new process) still serves
  // cache hits instead of re-spawning.
  const key = emitKey(call, task);
  loadEmitCache(call.home);
  const hit = lookupEmitEntry(call, task);
  if (hit !== undefined) {
    return serveEmitCacheHit(call, hit, call.cfg.mode);
  }
  const runtime = process.env.SECOND_BRAIN_PYTHON ?? join(call.home, ".venv", "Scripts", "python.exe");
  if (call.runner === undefined && !existsSync(runtime)) {
    return undefined;
  }
  const started = Date.now();
  try {
    const outcome = await (call.runner ?? runAutoInjectShadow)({
      home: call.home,
      task,
      cwd: call.cwd,
      sessionId: call.session,
      agentId: call.agentId,
      branchId: call.branchId,
      roleProfile: call.roleProfile,
      cfg: call.cfg,
    });
    const latencyMs = Date.now() - started;
    if (outcome === null) {
      call.append(
        extensionError(call.session, new Error("autoinject advisory spawn failed (timeout/error)")),
      );
      autoInjectEmitCache.set(key, {
        message: undefined,
        outcome: null,
        emits: 1,
        expiresAt: Date.now() + emitTtlMs(),
        ...entryProvenance(call, task),
      });
      persistEmitCache(call.home);
      return undefined;
    }
    rememberResolvedProject(call.session, outcome);
    const message = messageFromOutcome(outcome, call.customType ?? AUTOINJECT_CUSTOM_TYPE);
    appendDecisionRecord(call, outcome, latencyMs, call.cfg.mode, message !== undefined, 1, false);
    autoInjectEmitCache.set(key, {
      message,
      outcome,
      emits: 1,
      expiresAt: Date.now() + emitTtlMs(),
      ...entryProvenance(call, task),
    });
    persistEmitCache(call.home);
    return message;
  } catch (error) {
    try {
      call.append(extensionError(call.session, error));
    } catch {
      // storage failed too — stay silent
    }
    return undefined;
  }
}

function appendDecisionRecord(
  call: ShadowAutoInjectCall,
  outcome: AutoInjectShadowOutcome,
  latencyMs: number,
  mode: "off" | "shadow" | "advisory" | "active",
  resultPatch: boolean,
  emitIndex: number,
  cacheHit: boolean,
): void {
  call.append(
    autoinjectShadowDecision(call.session, {
      decision: outcome.decision,
      reason: outcome.reason,
      packet_tokens: outcome.packetTokens,
      latency_ms: latencyMs,
      candidate_count: outcome.candidateCount,
      selected_count: outcome.selectedCount,
      delivery_id: outcome.deliveryId,
      packet_sha256: outcome.packetSha256,
      mode,
      // Shadow decisions are never model-visible; advisory/active is the
      // custom-message injection path (unambiguous marker, SCHEMA.md).
      model_visible: mode === "advisory" || mode === "active",
      result_patch: resultPatch,
      emit_index: emitIndex,
      cache_hit: cacheHit,
      handler_returned_message: resultPatch,
      cli_packet_chars: outcome.cliPacketChars ?? null,
      cli_stdout_chars: outcome.cliStdoutChars,
    }),
  );
}

/**
 * Build the patch message deterministically from an outcome's packet text
 * (Phase C7): the message must be derived from the packet, never from
 * ambient entry state — an entry persisted by the shadow path may carry
 * message=undefined while outcome.packet is present, and advisory re-emits
 * must still return the SAME message.
 */
function messageFromOutcome(
  outcome: AutoInjectShadowOutcome | null,
  customType: string,
): AutoInjectEmitEntry["message"] {
  if (outcome === null || outcome.packet === null) return undefined;
  return {
    customType,
    content: outcome.packet,
    display: true,
    details: { delivery_id: outcome.deliveryId, packet_tokens: outcome.packetTokens },
  };
}

/** Serve a cache hit: bump the emit counter, record the FIRST hit only. */
function serveEmitCacheHit(
  call: ShadowAutoInjectCall,
  entry: AutoInjectEmitEntry,
  mode: "off" | "shadow" | "advisory" | "active",
): AutoInjectEmitEntry["message"] {
  rememberResolvedProject(call.session, entry.outcome);
  entry.emits += 1;
  const message =
    entry.message ?? messageFromOutcome(entry.outcome, AUTOINJECT_CUSTOM_TYPE);
  entry.message = message;
  if (entry.emits === 2) {
    // One extra record per key on the first hit (emit_stability marker);
    // later re-emits stay silent (no per-emit rows). Phase C10 (verifier):
    // result_patch / handler_returned_message must be true ONLY in
    // advisory/active — a shadow cache hit never returned a patch, and
    // telemetry must never claim one.
    if (entry.outcome !== null) {
      const returnedPatch = (mode === "advisory" || mode === "active") && message !== undefined;
      appendDecisionRecord(call, entry.outcome, 0, mode, returnedPatch, entry.emits, true);
    }
  }
  return message;
}

/**
 * Orchestrates one SHADOW decision: guard -> spawn -> record. NEVER throws,
 * NEVER returns a patch (shadow invariant), never blocks on the event path
 * (callers fire-and-forget). Empty task text (e.g. session_start has no
 * prompt) is a legitimate no-op — nothing to retrieve.
 */
export async function runShadowAutoInject(call: ShadowAutoInjectCall): Promise<void> {
  if (call.cfg.mode === "off") return;
  const task = (call.task ?? "").trim();
  if (task.length === 0) return;
  // Phase C5: cache also applies to shadow — re-emits of the same task skip
  // the spawn entirely (no duplicate ledger writes, no duplicate records).
  const key = emitKey(call, task);
  loadEmitCache(call.home);
  const hit = lookupEmitEntry(call, task);
  if (hit !== undefined) {
    serveEmitCacheHit(call, hit, call.cfg.mode);
    return;
  }
  // Fail-open: a Brain home without an installed venv is not a runtime;
  // skip silently (no spawn, no record) so host sessions are never touched.
  const runtime = process.env.SECOND_BRAIN_PYTHON ?? join(call.home, ".venv", "Scripts", "python.exe");
  if (call.runner === undefined && !existsSync(runtime)) {
    return;
  }
  const started = Date.now();
  try {
    const outcome = await (call.runner ?? runAutoInjectShadow)({
      home: call.home,
      task,
      cwd: call.cwd,
      sessionId: call.session,
      agentId: call.agentId,
      branchId: call.branchId,
      roleProfile: call.roleProfile,
      cfg: call.cfg,
    });
    const latencyMs = Date.now() - started;
    if (outcome === null) {
      call.append(
        extensionError(call.session, new Error("autoinject shadow spawn failed (timeout/error)")),
      );
      autoInjectEmitCache.set(key, {
        message: undefined,
        outcome: null,
        emits: 1,
        expiresAt: Date.now() + emitTtlMs(),
        ...entryProvenance(call, task),
      });
      persistEmitCache(call.home);
      return;
    }
    rememberResolvedProject(call.session, outcome);
    appendDecisionRecord(call, outcome, latencyMs, call.cfg.mode, false, 1, false);
    autoInjectEmitCache.set(key, {
      message: messageFromOutcome(outcome, AUTOINJECT_CUSTOM_TYPE),
      outcome,
      emits: 1,
      expiresAt: Date.now() + emitTtlMs(),
      ...entryProvenance(call, task),
    });
    persistEmitCache(call.home);
  } catch (error) {
    try {
      call.append(extensionError(call.session, error));
    } catch {
      // storage failed too — stay silent
    }
  }
}
