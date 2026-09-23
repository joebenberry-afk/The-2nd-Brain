/**
 * T2.4 Injection placement slots: stable PREFIX and per-turn TAIL for Prime extension.
 *
 * Two slots only:
 * 1. PREFIX (session-constant):
 *    (1) Lean kernel (from lean-code)
 *    (2) Skill descriptors (from visibility plan)
 *    (3) The two T1.6 commands
 *    (4) Project identity line: Project: <project_id>
 *    Rendered once at session start and never changed across turns.
 *    sha256(PREFIX) stored at session start; comparing later turns detects drift
 *    and logs prefix_drift=1.
 *
 * 2. TAIL (per-turn):
 *    [BRAIN_CONTEXT_DELTA], hot-context refs (VMem), freshness lines, Skill hydration bodies.
 *    Appended after the latest user message in the turn context.
 */

import { createHash } from "node:crypto";

const PROJECT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

/** A project identifier is data, never arbitrary model-visible instruction text. */
function projectIdForPrompt(value: unknown): string {
  return typeof value === "string" && PROJECT_ID_RE.test(value) ? value : "default";
}

/**
 * T1.6 memory commands (PREFIX component 3).
 *
 * Emptied 2026-09-21. An OMP session mounts no `brainctl` device, so the prefix
 * told every session to run a command that does not exist there; recall is
 * delivered by the Brain's own injection path and needs no model action. The
 * instruction also pointed at an authority-minting entrypoint (`brainctl
 * remember` can mint USER_AUTHORED/VERIFIED), which an agent-facing prompt
 * should not recommend. The constant stays as a single seam for the slot.
 */
export const MEMORY_COMMANDS_TEXT = "";

const sessionPrefixHashes = new Map<string, string>();

/** Test seam: clear in-process prefix hash store. */
export function resetPrefixDriftStore(): void {
  sessionPrefixHashes.clear();
}

export function formatSkillDescriptors(
  descriptors?: string | Record<string, string> | null,
): string {
  if (!descriptors) return "";
  if (typeof descriptors === "string") return descriptors.trim();
  const parts: string[] = [];
  for (const skillId of Object.keys(descriptors).sort()) {
    const text = descriptors[skillId]?.trim();
    if (text) {
      parts.push(text);
    }
  }
  return parts.join("\n\n");
}

export function formatHydratedSkills(
  skills?: string | Record<string, string> | null,
): string {
  if (!skills) return "";
  if (typeof skills === "string") return skills.trim();
  const parts: string[] = [];
  for (const skillId of Object.keys(skills).sort()) {
    const text = skills[skillId]?.trim();
    if (text) {
      parts.push(text);
    }
  }
  return parts.join("\n\n");
}

export interface AssemblePrefixOptions {
  projectId: string;
  leanKernel?: string | null;
  skillDescriptors?: string | Record<string, string> | null;
}

export function assemblePrefix(options: AssemblePrefixOptions): string {
  const parts: string[] = [];

  // (1) Lean kernel
  if (options.leanKernel && options.leanKernel.trim()) {
    parts.push(options.leanKernel.trim());
  }

  // (2) Skill descriptors
  const descText = formatSkillDescriptors(options.skillDescriptors);
  if (descText) {
    parts.push(descText);
  }

  // (3) Memory command slot — empty since 2026-09-21 (no such device is mounted)
  const memoryCommands = MEMORY_COMMANDS_TEXT.trim();
  if (memoryCommands) {
    parts.push(memoryCommands);
  }

  // (4) Project identity line
  const proj = projectIdForPrompt(options.projectId);
  parts.push(`Project: ${proj}`);

  return parts.join("\n\n");
}

/** Stable dedup marker for memory commands and project identity.
 * Like the approved Lean marker, it prevents duplicate recipient context. */
export const PREFIX_EXTRAS_MARKER = "second-brain-prefix-extras";

/**
 * Append stable memory commands and a validated project ID to a host prompt.
 * Undefined/empty bases stay unchanged; the marker prevents duplicate
 * recipient context on later turns.
 */
export function appendPrefixExtras(base: string | undefined, projectId: string): string | undefined {
  if (base === undefined || base.trim() === "") return undefined;
  if (base.includes(PREFIX_EXTRAS_MARKER)) return base;
  const proj = projectIdForPrompt(projectId);
  const extras = [MEMORY_COMMANDS_TEXT.trim(), `Project: ${proj}`].filter(Boolean).join("\n\n");
  return `${base}\n\n[${PREFIX_EXTRAS_MARKER}]\n${extras}`;
}

export interface DriftCheckResult {
  drift: boolean;
  hash: string;
}

export function checkPrefixDrift(session: string, prefix: string): DriftCheckResult {
  const currentHash = createHash("sha256").update(prefix).digest("hex");
  const storedHash = sessionPrefixHashes.get(session);

  if (storedHash === undefined) {
    sessionPrefixHashes.set(session, currentHash);
    return { drift: false, hash: currentHash };
  }

  if (storedHash !== currentHash) {
    return { drift: true, hash: currentHash };
  }

  return { drift: false, hash: currentHash };
}

export interface AssembleTailOptions {
  deltaContext?: string | null;
  hotContextRefs?: string | null;
  freshnessLines?: string | null;
  hydratedSkills?: string | Record<string, string> | null;
  budgetWarning?: string | null;
  leanContent?: string | null;
}

export function assembleTail(options: AssembleTailOptions): string {
  const parts: string[] = [];

  if (options.deltaContext && options.deltaContext.trim()) {
    parts.push(options.deltaContext.trim());
  }

  if (options.hotContextRefs && options.hotContextRefs.trim()) {
    parts.push(options.hotContextRefs.trim());
  }

  if (options.freshnessLines && options.freshnessLines.trim()) {
    const trimmed = options.freshnessLines.trim();
    if (!options.deltaContext || !options.deltaContext.includes(trimmed)) {
      parts.push(trimmed);
    }
  }

  const skillsText = formatHydratedSkills(options.hydratedSkills);
  if (skillsText) {
    parts.push(skillsText);
  }

  if (options.budgetWarning && options.budgetWarning.trim()) {
    parts.push(options.budgetWarning.trim());
  }

  if (options.leanContent && options.leanContent.trim()) {
    parts.push(options.leanContent.trim());
  }
  return parts.join("\n\n");
}

export function appendTailAfterUserMessage(
  messages: unknown[],
  tail: string,
): unknown[] {
  if (!tail || !tail.trim()) {
    return [...messages];
  }

  const result = [...messages];
  let lastUserIdx = -1;

  for (let i = result.length - 1; i >= 0; i--) {
    const item = result[i];
    if (item && typeof item === "object" && "role" in item && item.role === "user") {
      lastUserIdx = i;
      break;
    }
  }
  const tailMessage = {
    role: "custom",
    customType: "brain.tail",
    content: tail,
  };
  if (lastUserIdx >= 0) {
    result.splice(lastUserIdx + 1, 0, tailMessage);
  } else {
    result.push(tailMessage);
  }

  return result;
}
