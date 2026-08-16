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
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { autoinjectShadowDecision, extensionError } from "./sensors";

export const AUTOINJECT_DEFAULT_TIMEOUT_MS = 5000;
export const AUTOINJECT_MODE_OFF_VALUES = new Set(["off", "0", "false", "no"]);
export const AUTOINJECT_MODE_ACTIVE_VALUES = new Set(["advisory", "active", "1", "true", "yes"]);
export const AUTOINJECT_CUSTOM_TYPE = "brain.autoinject.packet";
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
      return undefined;
    }
    appendDecisionRecord(call, outcome, latencyMs);
    if (outcome.decision !== "INJECT" || outcome.packet === null) return undefined;
    return {
      customType: call.customType ?? AUTOINJECT_CUSTOM_TYPE,
      content: outcome.packet,
      display: true,
      details: { delivery_id: outcome.deliveryId, packet_tokens: outcome.packetTokens },
    };
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
    }),
  );
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
      return;
    }
    appendDecisionRecord(call, outcome, latencyMs);
  } catch (error) {
    try {
      call.append(extensionError(call.session, error));
    } catch {
      // storage failed too — stay silent
    }
  }
}
