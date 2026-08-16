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
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
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
  /** First 64 chars of the task that produced this entry (correctness guard:
   * the key is session-only, so a genuinely different task within TTL must
   * replace the entry instead of being served a stale message). */
  promptHead: string;
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
function emitCacheFile(home: string): string {
  return join(home, "state", "autoinject-emit-cache.json");
}

interface PersistedEmitEntry {
  message:
    | { customType: string; content: string; display: boolean; details: unknown }
    | null;
  outcome: AutoInjectShadowOutcome | null;
  emits: number;
  expiresAt: number;
  promptHead: string;
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
          promptHead: typeof entry.promptHead === "string" ? entry.promptHead : "",
        });
      }
    }
  } catch {
    // missing/corrupt file -> empty cache (fail open)
  }
}

function persistEmitCache(home: string): void {
  try {
    const dir = join(home, "state");
    mkdirSync(dir, { recursive: true });
    const now = Date.now();
    const data: Record<string, PersistedEmitEntry> = {};
    for (const [key, entry] of autoInjectEmitCache) {
      if (entry.expiresAt > now) {
        data[key] = {
          message: entry.message ?? null,
          outcome: entry.outcome,
          emits: entry.emits,
          expiresAt: entry.expiresAt,
          promptHead: entry.promptHead,
        };
      }
    }
    const target = emitCacheFile(home);
    const tmp = `${target}.tmp`;
    writeFileSync(tmp, JSON.stringify(data));
    renameSync(tmp, target);
  } catch {
    // persistence must never break injection (fail open)
  }
}

function emitTtlMs(): number {
  const raw = Number(process.env[AUTOINJECT_EMIT_TTL_ENV] ?? AUTOINJECT_DEFAULT_EMIT_TTL_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : AUTOINJECT_DEFAULT_EMIT_TTL_MS;
}

/**
 * Phase C8: the cache key is the SESSION only — the host re-emits the same
 * turn several times with identical prompt text (verified: 7/7
 * brain_retrieval_attempt rows carried the same task_sha256 in observer6),
 * and worker processes are long-lived + diverse, so per-task keys fragment
 * the cache. Correctness: the prompt-head guard (first 64 chars) in
 * lookupEmitEntry ensures a genuinely different task replaces the entry.
 */
function emitKey(sessionId: string): string {
  return `session:${sessionId}`;
}

function promptHead(task: string): string {
  return task.slice(0, 64);
}

function lookupEmitEntry(sessionId: string, task: string): AutoInjectEmitEntry | undefined {
  const entry = autoInjectEmitCache.get(emitKey(sessionId));
  if (entry === undefined || entry.expiresAt <= Date.now()) return undefined;
  if (entry.promptHead !== promptHead(task)) return undefined; // new task -> replace
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
  };
}

/**
 * One bounded out-of-process spawn (execFile) with env cleanup and a hard
 * timeout. Resolves null on ANY failure (fail-open); never rejects.
 */
export function runAutoInjectShadow(options: AutoInjectRunOptions): Promise<AutoInjectShadowOutcome | null> {
  const python = options.python ?? join(options.home, ".venv", "Scripts", "python.exe");
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
  branchId?: string;
  roleProfile?: string;
  cfg: AutoInjectHostConfig;
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
  const key = emitKey(call.session);
  loadEmitCache(call.home);
  const hit = lookupEmitEntry(call.session, task);
  if (hit !== undefined) {
    return serveEmitCacheHit(call, hit, call.cfg.mode);
  }
  if (call.runner === undefined && !existsSync(join(call.home, ".venv", "Scripts", "python.exe"))) {
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
        promptHead: promptHead(task),
      });
      persistEmitCache(call.home);
      return undefined;
    }
    const message = messageFromOutcome(outcome, call.customType ?? AUTOINJECT_CUSTOM_TYPE);
    appendDecisionRecord(call, outcome, latencyMs, call.cfg.mode, message !== undefined, 1, false);
    autoInjectEmitCache.set(key, {
      message,
      outcome,
      emits: 1,
      expiresAt: Date.now() + emitTtlMs(),
      promptHead: promptHead(task),
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
  entry.emits += 1;
  const message =
    entry.message ?? messageFromOutcome(entry.outcome, AUTOINJECT_CUSTOM_TYPE);
  entry.message = message;
  if (entry.emits === 2) {
    // One extra record per key on the first hit (emit_stability marker);
    // later re-emits stay silent (no per-emit rows).
    if (entry.outcome !== null) {
      appendDecisionRecord(
        call,
        entry.outcome,
        0,
        mode,
        message !== undefined,
        entry.emits,
        true,
      );
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
  const key = emitKey(call.session);
  loadEmitCache(call.home);
  const hit = lookupEmitEntry(call.session, task);
  if (hit !== undefined) {
    serveEmitCacheHit(call, hit, call.cfg.mode);
    return;
  }
  // Fail-open: a Brain home without an installed venv is not a runtime;
  // skip silently (no spawn, no record) so host sessions are never touched.
  if (call.runner === undefined && !existsSync(join(call.home, ".venv", "Scripts", "python.exe"))) {
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
        promptHead: promptHead(task),
      });
      persistEmitCache(call.home);
      return;
    }
    appendDecisionRecord(call, outcome, latencyMs, call.cfg.mode, false, 1, false);
    autoInjectEmitCache.set(key, {
      message: messageFromOutcome(outcome, AUTOINJECT_CUSTOM_TYPE),
      outcome,
      emits: 1,
      expiresAt: Date.now() + emitTtlMs(),
      promptHead: promptHead(task),
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
