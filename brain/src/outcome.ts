/**
 * Which later result scores a fix the model has seen: the repaired operation, not the exact command
 * string. A prepared retry (`PYTHONPATH=. python app.py` for `python app.py`) is the same operation;
 * the same error persisting is a miss; a different diagnostic is unknown (the fix may have worked
 * and the operation moved on), so it logs no outcome.
 */
import { errorSignature, hostNoise, keepsCommand } from "./capture.ts";
import { scrub } from "./scrub.ts";

/** A fired fix awaiting its outcome, with what is needed to tell whether a result is its operation. */
export interface PendingFix {
  id: string;
  project: string;
  /** The failed command, when the tool ran one. */
  command?: string;
  tool?: string;
  /** The failed call's target path, for tools without a command. */
  path?: string;
  /** errorSignature of the error the fix answered. */
  sig?: string;
}

export interface ResultFields { tool: string; command?: string; path?: string; ok: boolean; error?: string }

/** The operation facts a pending fix keeps from the failed result it answered; persisted, so scrubbed. */
export function operationOf(fields: ResultFields): Pick<PendingFix, "command" | "tool" | "path" | "sig"> {
  return {
    ...(fields.command ? { command: scrub(fields.command).text } : {}),
    tool: fields.tool,
    ...(fields.path ? { path: fields.path } : {}),
    ...(fields.error ? { sig: errorSignature(scrub(fields.error).text) } : {}),
  };
}

/**
 * "other": this result is not the fix's operation (or is host noise), keep waiting.
 * "unknown": it is, but a different error: the fix is neither credited nor blamed.
 */
export function outcomeOf(pending: PendingFix, fields: ResultFields): "helped" | "missed" | "unknown" | "other" {
  if (!fields.ok && hostNoise(fields.tool, fields.error ?? "")) return "other";
  if (pending.tool !== fields.tool) return "other";
  if (pending.command !== undefined || fields.command !== undefined) {
    if (pending.command === undefined || fields.command === undefined) return "other";
    const current = scrub(fields.command).text;
    if (pending.command !== current && !keepsCommand(pending.command, current)) return "other";
  } else if (pending.path !== fields.path) {
    return "other";
  }
  if (fields.ok) return "helped";
  // Only the originating diagnostic persisting is a miss; a missing or different one proves nothing.
  return pending.sig !== undefined && fields.error && errorSignature(scrub(fields.error).text) === pending.sig ? "missed" : "unknown";
}
