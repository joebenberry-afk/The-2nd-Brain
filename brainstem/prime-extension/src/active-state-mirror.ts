import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { startDetachedBrainCommand } from "./detached-spawn";

import { runVmemHotContext, type VmemHotContextResult } from "./vmem";
export const ACTIVE_STATE_DEFAULT_TIMEOUT_MS = 5000;
export const ACTIVE_STATE_MAX_TEXT_CHARS = 512;
export const ACTIVE_STATE_DEFAULT_BUDGET = 256;
export const ACTIVE_STATE_CUSTOM_TYPE = "brain.active-state";

type JsonRecord = Record<string, unknown>;

export interface ActiveStateResult {
  ok: boolean;
  sessionId?: string;
  changed?: boolean;
  capsulePath?: string;
  capsuleSha256?: string;
  capsuleBytes?: number;
  capsule?: JsonRecord;
  error?: string;
}

export interface ActiveStateRenderResult {
  ok: boolean;
  sessionId?: string;
  renderedText?: string;
  error?: string;
}

export interface ActiveStateOptions {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
  objective?: string;
  nextAction?: string;
  decisions?: string[];
  openQuestions?: string[];
  facts?: string[];
  hypotheses?: string[];
  filesTouched?: string[];
  constraints?: string[];
  brainRefs?: string[];
  artifactRefs?: string[];
  verification?: JsonRecord;
}

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

function boundedText(value: string): string {
  return value.trim().slice(0, ACTIVE_STATE_MAX_TEXT_CHARS);
}

function addRepeated(args: string[], flag: string, values?: string[]): void {
  for (const value of values ?? []) {
    const bounded = boundedText(value);
    if (bounded.length > 0) args.push(flag, bounded);
  }
}

function baseArgs(command: "ensure" | "update", session: string): string[] {
  return ["-m", "second_brain", "capsule", command, session];
}

function updateArgs(options: ActiveStateOptions): string[] {
  const args = baseArgs("update", options.hostSessionId);
  if (options.objective !== undefined) args.push("--objective", boundedText(options.objective));
  if (options.nextAction !== undefined) args.push("--next-action", boundedText(options.nextAction));
  addRepeated(args, "--add-constraint", options.constraints);
  addRepeated(args, "--add-fact", options.facts);
  addRepeated(args, "--add-hypothesis", options.hypotheses);
  addRepeated(args, "--add-decision", options.decisions);
  addRepeated(args, "--add-file", options.filesTouched);
  addRepeated(args, "--add-question", options.openQuestions);
  addRepeated(args, "--add-brain-ref", options.brainRefs);
  addRepeated(args, "--add-artifact-ref", options.artifactRefs);
  if (options.verification !== undefined) {
    args.push("--verification-json", JSON.stringify(options.verification));
  }
  args.push("--json");
  return args;
}

/** Parse one `capsule ensure --json` stdout payload. Shared by this direct
 * bridge call and the batched turn bridge (E01). */
export function parseActiveStateResult(stdout: string, expectedSession: string): ActiveStateResult {
  try {
    const parsed = JSON.parse(stdout) as JsonRecord;
    if (parsed.session_id !== expectedSession) {
      return { ok: false, error: "active-state session mismatch" };
    }
    return {
      ok: true,
      sessionId: expectedSession,
      changed: parsed.changed === true,
      capsulePath: typeof parsed.capsule_path === "string" ? parsed.capsule_path : undefined,
      capsuleSha256: typeof parsed.capsule_sha256 === "string" ? parsed.capsule_sha256 : undefined,
      capsuleBytes: typeof parsed.capsule_bytes === "number" ? parsed.capsule_bytes : undefined,
      capsule: parsed.capsule as JsonRecord | undefined,
    };
  } catch {
    return { ok: false, error: "active-state returned unparsable output" };
  }
}

function execute(
  options: ActiveStateOptions,
  args: string[],
): Promise<ActiveStateResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: true, sessionId: options.hostSessionId, changed: false });
  }
  const execOptions = {
    cwd: options.home,
    env: runEnv(options.home),
    timeout: options.timeoutMs ?? ACTIVE_STATE_DEFAULT_TIMEOUT_MS,
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  };
  const { promise, resolve } = Promise.withResolvers<ActiveStateResult>();
  execFile(python, args, execOptions, (error, stdout) => {
    if (error) {
      resolve({ ok: false, error: error.message });
      return;
    }
    resolve(parseActiveStateResult(String(stdout), options.hostSessionId));
  });
  return promise;
}

export function runActiveStateEnsure(options: ActiveStateOptions): Promise<ActiveStateResult> {
  const args = baseArgs("ensure", options.hostSessionId);
  args.push(boundedText(options.objective ?? ""));
  if (options.nextAction !== undefined) args.push("--next-action", boundedText(options.nextAction));
  args.push("--json");
  return execute(options, args);
}

export function runActiveStateUpdate(options: ActiveStateOptions): Promise<ActiveStateResult> {
  return execute(options, updateArgs(options));
}

/**
 * Hand the shutdown capsule update to a DETACHED child. `session_shutdown` is
 * the host worker's last event: waiting for the spawn (the previous
 * `execFileSync` update blocked every turn the host still had to serve) cost the
 * exit tail for a write nobody reads. The caller starts it only after the
 * session's capsule-write barrier is idle, so this is the last write that
 * capsule receives.
 *
 * Returns whether the process was started; fail-open, no result to report.
 */
export function startDetachedActiveStateUpdate(options: ActiveStateOptions): boolean {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) return false;
  return startDetachedBrainCommand(python, updateArgs(options), options.home);
}

export async function renderActiveState(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
  budgetTokens?: number;
}): Promise<ActiveStateRenderResult> {
  const rendered = await runVmemHotContext({
    home: options.home,
    hostSessionId: options.hostSessionId,
    budgetTokens: options.budgetTokens ?? ACTIVE_STATE_DEFAULT_BUDGET,
    python: options.python,
    timeoutMs: options.timeoutMs ?? ACTIVE_STATE_DEFAULT_TIMEOUT_MS,
  });
  return activeStateRenderResult(rendered, options.hostSessionId);
}

/** Map a hot-context render onto the active-state result shape. Shared by the
 * direct bridge call and the batched turn bridge (E01), so both paths produce
 * the same model-visible message for the same render. */
export function activeStateRenderResult(
  rendered: VmemHotContextResult,
  hostSessionId: string,
): ActiveStateRenderResult {
  if (!rendered.ok && rendered.error?.startsWith("no brain venv")) {
    return { ok: true, sessionId: hostSessionId, renderedText: "" };
  }
  if (!rendered.ok) return { ok: false, error: rendered.error };
  if (rendered.sessionId !== hostSessionId) {
    return { ok: false, error: "active-state session mismatch" };
  }
  return {
    ok: true,
    sessionId: hostSessionId,
    renderedText: rendered.renderedText?.slice(0, 8192),
  };
}

const HOT_CONTEXT_HEADER = "[SECOND_BRAIN_HOT_CONTEXT]";

/**
 * Build the model-visible active-state message. When `currentPrompt` is
 * supplied, an `Objective:` line that merely echoes that prompt is dropped
 * (the model already has the prompt), and a render with nothing left
 * returns undefined so a no-benefit turn adds no Brain message (PERF-01).
 */
export function activeStateMessage(
  result: ActiveStateRenderResult,
  currentPrompt?: string,
): { customType: string; content: string; display: boolean; details: JsonRecord } | undefined {
  if (!result.ok || !result.sessionId || !result.renderedText) return undefined;
  let text = result.renderedText;
  if (currentPrompt !== undefined) {
    // The capsule stores the bounded text stripped again (Python `strip()`), so a
    // cut that ends on whitespace loses it; compare against that stored form.
    const echo = `${HOT_CONTEXT_HEADER}\nObjective: ${boundedText(currentPrompt).trim()}`;
    if (text === echo || text.startsWith(`${echo}\n`)) {
      text = HOT_CONTEXT_HEADER + text.slice(echo.length);
    }
    if (text.trim() === HOT_CONTEXT_HEADER) return undefined;
  }
  return {
    customType: ACTIVE_STATE_CUSTOM_TYPE,
    content: `[SECOND_BRAIN_ACTIVE_STATE]\n${text}`,
    display: false,
    details: { session_id: result.sessionId, source: "vmem.hot-context" },
  };
}
