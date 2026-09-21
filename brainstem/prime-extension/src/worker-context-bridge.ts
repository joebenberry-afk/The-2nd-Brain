/** Thin OMP task-dispatch bridge to the existing Brain worker handoff. */

import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_WORKER_CONTEXT_TIMEOUT_MS = 5000;
export const OMP_WORKER_CONTEXT_MAX_STDOUT_CHARS = 256 * 1024;
export const OMP_WORKER_CONTEXT_MAX_TEXT_CHARS = 4096;

type HandoffMode = "full" | "unchanged" | "delta";
export type OmpWorkerAccessIntent = "read_only" | "mutating";

export interface OmpWorkerContextHandoff {
  mode: HandoffMode;
  resolved_context: unknown[];
  context_delta: Record<string, unknown>;
  context_fingerprint: string;
  jit_context: string;
}

export interface OmpWorkerContextMetadata {
  mode: HandoffMode;
  reused: boolean;
  cache_hit: boolean;
  resolved_count: number;
  context_fingerprint: string;
  context_handoff_bytes: number;
  context_handoff_tokens_estimate: number;
  context_delta_bytes: number;
  context_delta_tokens_estimate: number;
  [key: string]: unknown;
}

export interface OmpWorkerContextResult {
  ok: boolean;
  taskId?: string;
  attemptId?: string;
  packetSha256?: string;
  projectId?: string;
  worktreeId?: string | null;
  accessIntent?: OmpWorkerAccessIntent;
  callbackToken?: string;
  contextHandoff?: OmpWorkerContextHandoff;
  contextMetadata?: OmpWorkerContextMetadata;
  error?: string;
}

export interface OmpWorkerContextOptions {
  home: string;
  sessionId: string;
  taskId: string;
  task: string;
  scope: string;
  completionCondition: string;
  projectId: string;
  accessIntent: OmpWorkerAccessIntent;
  cwd: string;
  role: string;
  provider: string;
  model: string;
  workerRole?: string;
  depth?: number;
  contextRefs?: string[];
  python?: string;
  timeoutMs?: number;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

function validMode(value: unknown): value is HandoffMode {
  return value === "full" || value === "unchanged" || value === "delta";
}

function validAccessIntent(value: unknown): value is OmpWorkerAccessIntent {
  return value === "read_only" || value === "mutating";
}

function parseMetadata(value: unknown): OmpWorkerContextMetadata | undefined {
  if (value == null || typeof value !== "object") return undefined;
  const metadata = value as Record<string, unknown>;
  if (
    !validMode(metadata.mode) ||
    typeof metadata.reused !== "boolean" ||
    typeof metadata.cache_hit !== "boolean" ||
    typeof metadata.resolved_count !== "number" ||
    !sha256(metadata.context_fingerprint) ||
    typeof metadata.context_handoff_bytes !== "number" ||
    typeof metadata.context_handoff_tokens_estimate !== "number" ||
    typeof metadata.context_delta_bytes !== "number" ||
    typeof metadata.context_delta_tokens_estimate !== "number"
  ) {
    return undefined;
  }
  return metadata as OmpWorkerContextMetadata;
}

function parseHandoff(value: unknown): OmpWorkerContextHandoff | undefined {
  if (value == null || typeof value !== "object") return undefined;
  const handoff = value as Record<string, unknown>;
  if (
    !validMode(handoff.mode) ||
    !Array.isArray(handoff.resolved_context) ||
    handoff.context_delta == null ||
    typeof handoff.context_delta !== "object" ||
    !sha256(handoff.context_fingerprint) ||
    typeof handoff.jit_context !== "string"
  ) {
    return undefined;
  }
  return handoff as unknown as OmpWorkerContextHandoff;
}

export function parseOmpWorkerContextOutput(stdout: string): OmpWorkerContextResult {
  if (stdout.length > OMP_WORKER_CONTEXT_MAX_STDOUT_CHARS) {
    return { ok: false, error: "BRAIN_WORKER_CONTEXT_OUTPUT_TOO_LARGE" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { ok: false, error: "BRAIN_WORKER_CONTEXT_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") {
    return { ok: false, error: "BRAIN_WORKER_CONTEXT_INVALID_RESPONSE" };
  }
  const value = parsed as Record<string, unknown>;
  if (value.status !== "prepared") {
    return { ok: false, error: bounded(value.failure_code, 128) || "BRAIN_WORKER_CONTEXT_FAILED" };
  }
  const taskId = bounded(value.task_id, 512);
  const attemptId = bounded(value.attempt_id, 128);
  const packetSha256 = value.packet_sha256;
  const projectId = bounded(value.project_id, 128);
  const accessIntent = value.access_intent;
  const worktreeId = value.worktree_id === null ? null : bounded(value.worktree_id, 512);
  const callbackToken = bounded(value.callback_token, 512);
  const contextMetadata = parseMetadata(value.context_metadata);
  const contextHandoff = parseHandoff(value.context_handoff);
  if (
    !taskId ||
    !attemptId ||
    !sha256(packetSha256) ||
    !projectId ||
    !validAccessIntent(accessIntent) ||
    contextMetadata === undefined ||
    contextHandoff === undefined ||
    (accessIntent === "mutating" && (!worktreeId || !callbackToken)) ||
    (accessIntent === "read_only" && (worktreeId !== null || callbackToken))
  ) {
    return { ok: false, error: "BRAIN_WORKER_CONTEXT_INVALID_RESPONSE" };
  }
  return {
    ok: true,
    taskId,
    attemptId,
    packetSha256,
    projectId,
    worktreeId,
    accessIntent,
    ...(callbackToken ? { callbackToken } : {}),
    contextMetadata,
    contextHandoff,
  };
}

export function renderOmpWorkerContext(handoff: OmpWorkerContextHandoff): string {
  const resolved = Array.isArray(handoff.resolved_context) ? handoff.resolved_context : [];
  const delta = handoff.context_delta ?? {};
  const changed = Array.isArray(delta.changed_refs) ? delta.changed_refs : [];
  const jitDelta = typeof delta.jit_delta === "string" ? delta.jit_delta.trim() : "";
  const jit = typeof handoff.jit_context === "string" ? handoff.jit_context.trim() : "";
  // Omit the envelope when it carries no facts. Live 2026-09-21: recon workers
  // received an envelope whose every section was empty (`resolved_context: []`,
  // `(none)`, `count: 0`) — pure prompt cost with no retrieved content.
  if (resolved.length === 0 && changed.length === 0 && jit === "" && jitDelta === "") {
    return "";
  }
  const wire = JSON.stringify({
    mode: handoff.mode,
    resolved_context: handoff.resolved_context,
    context_delta: handoff.context_delta,
    context_fingerprint: handoff.context_fingerprint,
    jit_context: jit,
  });
  return `[SECOND_BRAIN_WORKER_CONTEXT]\n${wire}\n[/SECOND_BRAIN_WORKER_CONTEXT]`;
}

export function runOmpWorkerContext(options: OmpWorkerContextOptions): Promise<OmpWorkerContextResult> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const payload = {
    operation: "worker_context",
    harness: "omp",
    host_session_id: bounded(options.sessionId, 128),
    task_id: bounded(options.taskId, 512),
    task: bounded(options.task, OMP_WORKER_CONTEXT_MAX_TEXT_CHARS),
    scope: bounded(options.scope, OMP_WORKER_CONTEXT_MAX_TEXT_CHARS),
    completion_condition: bounded(options.completionCondition, OMP_WORKER_CONTEXT_MAX_TEXT_CHARS),
    access_intent: options.accessIntent,
    project_id: bounded(options.projectId, 128),
    cwd: bounded(options.cwd, 512),
    role: bounded(options.role, 128),
    provider: bounded(options.provider, 128),
    model: bounded(options.model, 128),
    worker_role: bounded(options.workerRole ?? "worker", 128),
    depth: options.depth ?? 0,
    context_refs: options.contextRefs,
  };
  return new Promise((resolve) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_WORKER_CONTEXT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_WORKER_CONTEXT_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: "BRAIN_WORKER_CONTEXT_UNAVAILABLE" });
          return;
        }
        const result = parseOmpWorkerContextOutput(stdout);
        if (
          result.ok &&
          (result.taskId !== payload.task_id ||
            result.projectId !== payload.project_id ||
            result.accessIntent !== payload.access_intent)
        ) {
          resolve({ ok: false, error: "BRAIN_WORKER_CONTEXT_RECEIPT_MISMATCH" });
          return;
        }
        resolve(result);
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}
