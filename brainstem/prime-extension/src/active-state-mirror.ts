import { execFile, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

import { runVmemHotContext } from "./vmem";
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

function parseResult(stdout: string, expectedSession: string): ActiveStateResult {
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
  sync: boolean,
): ActiveStateResult | Promise<ActiveStateResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return { ok: true, sessionId: options.hostSessionId, changed: false };
  }
  const execOptions = {
    cwd: options.home,
    env: runEnv(options.home),
    timeout: options.timeoutMs ?? ACTIVE_STATE_DEFAULT_TIMEOUT_MS,
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  };
  if (sync) {
    try {
      return parseResult(String(execFileSync(python, args, execOptions)), options.hostSessionId);
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  }
  return new Promise((resolve) => {
    execFile(python, args, execOptions, (error, stdout) => {
      if (error) {
        resolve({ ok: false, error: error.message });
        return;
      }
      resolve(parseResult(String(stdout), options.hostSessionId));
    });
  });
}

export function runActiveStateEnsure(options: ActiveStateOptions): Promise<ActiveStateResult> {
  const args = baseArgs("ensure", options.hostSessionId);
  args.push(boundedText(options.objective ?? ""));
  if (options.nextAction !== undefined) args.push("--next-action", boundedText(options.nextAction));
  args.push("--json");
  return Promise.resolve(execute(options, args, false));
}

export function runActiveStateUpdate(options: ActiveStateOptions): Promise<ActiveStateResult> {
  return Promise.resolve(execute(options, updateArgs(options), false));
}

export function runActiveStateUpdateSync(options: ActiveStateOptions): ActiveStateResult {
  return execute(options, updateArgs(options), true) as ActiveStateResult;
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
  if (!rendered.ok && rendered.error?.startsWith("no brain venv")) {
    return { ok: true, sessionId: options.hostSessionId, renderedText: "" };
  }
  if (!rendered.ok) return { ok: false, error: rendered.error };
  if (rendered.sessionId !== options.hostSessionId) {
    return { ok: false, error: "active-state session mismatch" };
  }
  return {
    ok: true,
    sessionId: options.hostSessionId,
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
