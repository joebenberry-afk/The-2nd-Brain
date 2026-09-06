export interface StopEvidence {
  decision: "stop" | "continue";
  stop_id: string;
  task_id: string;
  session_id: string;
  parent_session_id: string;
  worker_session_id: string;
  reason_code: string;
  triggering_condition: string;
  verification_state: "passed" | "failed" | "blocked" | "unverified";
  completion_condition_state: "satisfied" | "failed" | "blocked" | "unresolved";
  final_substantive_event: string;
  continuation_forbidden: boolean;
  [key: string]: unknown;
}

const STOP_OUTPUT_MAX_CHARS = 8192;
const STOP_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const TASK_ID_PATTERN = /^[A-Za-z0-9._:-]{1,256}$/;

/** The only shell control command understood by the OMP adapter. */
export const STOP_CONTROL_COMMAND = /(?:^|\s)(?:brainctl(?:\.cmd)?|python(?:\.exe)?|second_brain)[^\r\n]*\bstop\s+decide\b/i;
export function rewriteSessionPlaceholders(
  command: string,
  session: string,
  parentSession = session,
): string {
  return command
    .replace(/(--session\s+)current\b/gi, `$1${session}`)
    .replace(/(--parent-session-id\s+)current\b/gi, `$1${parentSession}`)
    .replace(/(--worker-session-id\s+)current\b/gi, `$1${session}`)
    .replace(/(--verifier-session-id\s+)current\b/gi, `$1${session}`)
    .replace(/(--implementation-session-id\s+)current\b/gi, `$1${parentSession}`)
    .replace(
      /\b(requirements\s+(?:add|evidence|status|show|check)|verify\s+(?:gate|build-brief|independent))\s+current\b/gi,
      `$1 ${session}`,
    );
}

export function rewriteStopControlCommand(
  command: string,
  session: string,
  parentSession = session,
): string {
  if (!STOP_CONTROL_COMMAND.test(command)) return command;
  return rewriteSessionPlaceholders(command, session, parentSession);
}

export interface StopControlIdentity {
  session: string;
  task: string;
  parent?: string;
  worker?: string;
  stop?: string;
}

/** Literal identity options only; this is not a shell parser. Ambiguous shell
 * expressions have no STOP authority, even if the tool itself executes them. */
export function stopControlIdentity(command: string): StopControlIdentity | undefined {
  if (command.length > STOP_OUTPUT_MAX_CHARS || /[;&|`$<>\r\n]/.test(command) ||
      !/^\s*(?:brainctl(?:\.cmd)?|(?:python(?:\.exe)?\s+-m\s+)?second_brain)\s+stop\s+decide\b/i.test(command)) return undefined;
  const option = (name: string): string | undefined => {
    if ([...command.matchAll(new RegExp(`(?:^|\\s)--${name}(?==|\\s|$)`, "g"))].length !== 1) return undefined;
    const matches = [...command.matchAll(new RegExp(`(?:^|\\s)--${name}(?:=|\\s+)(\"[^\"]*\"|'[^']*'|[^\\s]+)`, "g"))];
    if (matches.length !== 1) return undefined;
    const raw = matches[0][1];
    const value = raw.replace(/^(['"])(.*)\1$/, "$2");
    return TASK_ID_PATTERN.test(value) && !/^(?:current|unknown|anonymous)$/i.test(value) ? value : undefined;
  };
  const session = option("session");
  const task = option("task-id");
  if (!session || !task) return undefined;
  const parent = option("parent-session-id");
  const worker = option("worker-session-id");
  const stop = option("stop-id");
  if ((!parent && /--parent-session-id\b/.test(command)) ||
      (!worker && /--worker-session-id\b/.test(command)) ||
      (!stop && /--stop-id\b/.test(command))) return undefined;
  return { session, task, parent, worker, stop };
}

/** Parsing establishes shape; applicability binds that shape to a specific call. */
export function stopEvidenceMatches(
  evidence: StopEvidence,
  expected: StopControlIdentity,
  parentSession: string,
): boolean {
  return evidence.session_id === expected.session &&
    evidence.task_id === expected.task &&
    (expected.stop === undefined || evidence.stop_id === expected.stop) &&
    (evidence.worker_session_id === (expected.worker ?? "") ||
      (expected.worker === undefined && evidence.worker_session_id === expected.session)) &&
    (evidence.parent_session_id === (expected.parent ?? "") ||
      (expected.parent === undefined && evidence.parent_session_id === parentSession)) &&
    evidence.continuation_forbidden === (evidence.decision === "stop");
}

const FINALIZATION_TOOLS: Record<string, true> = {
  session_shutdown: true,
  telemetry: true,
  stop_finalize: true,
  yield: true,
};
export function parseStopDecisionOutput(stdout: string): StopEvidence | undefined {
  if (stdout.length > STOP_OUTPUT_MAX_CHARS) return undefined;
  const start = stdout.indexOf("{");
  const end = stdout.lastIndexOf("}");
  if (start < 0 || end < start) return undefined;
  let value: unknown;
  try {
    value = JSON.parse(stdout.slice(start, end + 1));
  } catch {
    return undefined;
  }
  const data = value as Record<string, unknown>;
  if (
    (data.decision !== "stop" && data.decision !== "continue") ||
    typeof data.stop_id !== "string" ||
    !STOP_ID_PATTERN.test(data.stop_id) ||
    typeof data.task_id !== "string" ||
    !TASK_ID_PATTERN.test(data.task_id) ||
    typeof data.session_id !== "string" ||
    typeof data.parent_session_id !== "string" ||
    typeof data.worker_session_id !== "string" ||
    typeof data.reason_code !== "string" ||
    typeof data.triggering_condition !== "string" ||
    typeof data.verification_state !== "string" ||
    typeof data.completion_condition_state !== "string" ||
    typeof data.final_substantive_event !== "string" ||
    typeof data.continuation_forbidden !== "boolean"
  ) {
    return undefined;
  }
  return data as unknown as StopEvidence;
}

export class StopBoundaryState {
  private evidence: StopEvidence | undefined;
  private substantiveAfterBoundary = 0;

  accept(next: StopEvidence): void {
    if (next.decision === "stop" && next.continuation_forbidden) {
      this.evidence = next;
    }
  }

  get stopped(): boolean {
    return this.evidence !== undefined;
  }

  get substantiveEventsAfterBoundary(): number {
    return this.substantiveAfterBoundary;
  }

  get current(): StopEvidence | undefined {
    return this.evidence;
  }

  shouldBlock(toolName: string): boolean {
    return this.stopped && FINALIZATION_TOOLS[toolName] !== true;
  }
}

export function extractTextContent(content: unknown[]): string | undefined {
  for (const item of content) {
    if (typeof item === "string" && item.length <= STOP_OUTPUT_MAX_CHARS) return item;
    if (item == null || typeof item !== "object") continue;
    const data = item as Record<string, unknown>;
    const text = data.text;
    if (typeof text === "string" && text.length <= STOP_OUTPUT_MAX_CHARS) return text;
    const nested = data.content;
    if (typeof nested === "string" && nested.length <= STOP_OUTPUT_MAX_CHARS) return nested;
  }
  return undefined;
}
