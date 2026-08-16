/**
 * P3-D Lean Code runtime adapter (plan §7-§8, Second Brain P3 Lean Code One
 * Shot Plan v2).
 *
 * The smallest runtime influence surface for the Lean Code doctrine: on
 * `before_agent_start` the extension may append the canonical "# Runtime
 * Kernel" section of the `lean-code` skill to the system prompt — for
 * code-capable implementation roles (driver, worker) ONLY.
 *
 * Lifecycle behavior (plan §8.2):
 *   candidate -> no runtime influence by default (measurement only);
 *   shadow    -> measurement/eval only; no live policy effect by default;
 *   active    -> inject the compact Runtime Kernel into driver/worker sessions;
 *   retired   -> no injection (plan §26.1: demotion/retirement disables the
 *                runtime behavior);
 *   missing/corrupt skill file -> FAIL OPEN: no patch, no invented text,
 *                bounded error surfaced for an `extension_error` record.
 *
 * Smallest reversible eval mode (plan §8.2 last para): env
 * `SECOND_BRAIN_LEAN=advisory` forces kernel injection for driver/worker
 * sessions even when the skill is still candidate/shadow — this is how P3-E
 * candidate-arm runs happen without promotion. `SECOND_BRAIN_LEAN=off` forces
 * inert. No second promotion hierarchy, no new config file.
 *
 * Sol hard-orchestrator sessions NEVER get the kernel (plan §8.3): the
 * wiring returns before this module could inject, and this module also
 * refuses the role defensively.
 *
 * Kernel source: the canonical skill file ONLY (`skills/<level>/lean-code/
 * SKILL.md`, level resolved from the skill lifecycle dirs — active, shadow,
 * candidates, retired — mirroring `src/second_brain/paths.py`
 * SKILL_LEVEL_DIRS). The kernel text is NEVER duplicated as a TS constant;
 * it is parsed from the "# Runtime Kernel" section at runtime and cached
 * in-process keyed by resolved path + mtime/size (plan §8.6: no reread per
 * turn).
 *
 * Dedup (plan §8.4): stable marker `second-brain-lean-code-kernel`; the
 * injected block starts with `[second-brain-lean-code-kernel]` and the
 * append is a no-op when the base prompt already carries the marker, so one
 * assembled prompt never receives the kernel twice.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import type { AgentRole } from "./driver-orchestrator";

/** Stable dedup marker (plan §8.4): never inject the kernel twice. */
export const LEAN_KERNEL_MARKER = "second-brain-lean-code-kernel";

/** Env var that carries the smallest reversible eval mode (plan §8.2). */
export const LEAN_ENV = "SECOND_BRAIN_LEAN";

/** Exact section heading of the single canonical kernel source (plan §7.1). */
export const LEAN_KERNEL_HEADING = "# Runtime Kernel";

/** Skill directory name (mirrors the Skill Forge lifecycle). */
export const LEAN_SKILL_NAME = "lean-code";

/** Skill lifecycle levels in precedence order (active wins over shadow/candidate). */
export const LEAN_LEVEL_DIRS: Array<{ status: LeanSkillStatus; dir: string }> = [
  { status: "active", dir: "skills/active" },
  { status: "shadow", dir: "skills/shadow" },
  { status: "candidate", dir: "skills/candidates" },
  { status: "retired", dir: "skills/retired" },
];

/** Values of SECOND_BRAIN_LEAN that force inert behavior (case-insensitive). */
export const LEAN_OFF_VALUES = new Set(["off", "0", "false", "no"]);

/** Values of SECOND_BRAIN_LEAN that force injection (eval mode, plan §8.2). */
export const LEAN_ADVISORY_VALUES = new Set(["advisory"]);

/** Lifecycle status resolved from the skill directory (missing = no file). */
export type LeanSkillStatus = "active" | "shadow" | "candidate" | "retired" | "missing";

/** Enumerated reason for every lean decision (SCHEMA.md `lean_kernel`). */
export type LeanReason = "active" | "advisory" | "off" | "role" | "skill-missing";

/** Final lean decision for one `before_agent_start`. */
export interface LeanRuntimeOutcome {
  /** inject = a kernel patch was produced for the caller to apply. */
  decision: "inject" | "omit";
  /** Why: active/advisory lifecycle; off (env or not-yet-active/retired); role (not driver/worker); skill-missing. */
  reason: LeanReason;
  /** Raw SECOND_BRAIN_LEAN value (trimmed, lowercased) or null when unset. */
  mode: string | null;
  /** Resolved skill lifecycle status (null when the file is missing). */
  skillStatus: LeanSkillStatus | null;
  /** Character length of the canonical kernel section (0 when unavailable). */
  kernelChars: number;
  /** True when the base prompt already carried the marker (no re-injection). */
  dedupHit: boolean;
  /** Bounded failure detail for an `extension_error` record (undefined = ok). */
  error: string | undefined;
  /** Canonical kernel text; set only when decision === "inject". */
  kernel: string | undefined;
}

/** In-process kernel cache entry (plan §8.6). */
interface LeanSkillCacheEntry {
  path: string;
  mtimeMs: number;
  size: number;
  status: LeanSkillStatus;
  kernel: string | undefined;
  error: string | undefined;
}

/**
 * Process-scoped kernel cache (scoped to the extension lifecycle: the
 * extension is loaded once per Prime process). Keyed by resolved path with
 * mtime+size invalidation, so an unchanged file is read AT MOST ONCE per
 * process and a promoted/edited skill reloads on the next event.
 */
const leanSkillCache = new Map<string, LeanSkillCacheEntry>();

/** Test seam: clear the process-scoped kernel cache. */
export function resetLeanKernelCache(): void {
  leanSkillCache.clear();
}

/** Test seam: number of cached skill entries (0 = nothing cached yet). */
export function leanKernelCacheSize(): number {
  return leanSkillCache.size;
}

/**
 * Extract the "# Runtime Kernel" section from a skill file's text. The
 * section is the single canonical kernel source: the block after the exact
 * `# Runtime Kernel` heading until the next markdown heading (or EOF),
 * trimmed. Returns undefined when the heading or a non-empty body is absent
 * (corrupt/unrecognized file -> fail open).
 */
export function extractRuntimeKernel(skillText: string): string | undefined {
  const lines = skillText.split(/\r?\n/);
  let inKernel = false;
  const body: string[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!inKernel) {
      if (line === LEAN_KERNEL_HEADING) inKernel = true;
      continue;
    }
    if (/^#\s/.test(line)) break; // next markdown heading ends the section
    body.push(raw);
  }
  if (!inKernel) return undefined;
  const kernel = body.join("\n").trim();
  return kernel.length > 0 ? kernel : undefined;
}

/** Resolve the canonical skill file path for the current lifecycle level. */
export function resolveLeanSkillFile(home: string): { path: string; status: LeanSkillStatus } | undefined {
  for (const level of LEAN_LEVEL_DIRS) {
    const candidate = join(home, level.dir, LEAN_SKILL_NAME, "SKILL.md");
    try {
      if (existsSync(candidate)) return { path: candidate, status: level.status };
    } catch {
      // unreadable parent dir -> treat as absent and keep looking
    }
  }
  return undefined;
}

/**
 * Load + parse the canonical kernel with the in-process cache. Never throws;
 * every failure becomes a fail-open result (`kernel` undefined + bounded
 * `error`). Cache hit requires the same resolved path AND identical
 * mtimeMs+size — a promoted skill (new path) or an edited file (new mtime)
 * reloads exactly once on the next event.
 */
export function loadLeanKernel(home: string): LeanSkillCacheEntry {
  const resolved = resolveLeanSkillFile(home);
  if (resolved === undefined) {
    return { path: "", mtimeMs: -1, size: -1, status: "missing", kernel: undefined, error: "lean-code skill file not found under skills/active|shadow|candidates|retired" };
  }
  let stat: ReturnType<typeof statSync> | undefined;
  try {
    stat = statSync(resolved.path);
  } catch {
    return { path: resolved.path, mtimeMs: -1, size: -1, status: resolved.status, kernel: undefined, error: `cannot stat lean-code skill file: ${resolved.path}` };
  }
  const cached = leanSkillCache.get(resolved.path);
  if (cached !== undefined && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
    return cached;
  }
  let text: string;
  try {
    text = readFileSync(resolved.path, "utf8");
  } catch (error) {
    const entry: LeanSkillCacheEntry = {
      path: resolved.path,
      mtimeMs: stat.mtimeMs,
      size: stat.size,
      status: resolved.status,
      kernel: undefined,
      error: `cannot read lean-code skill file: ${error instanceof Error ? error.message : String(error)}`,
    };
    leanSkillCache.set(resolved.path, entry);
    return entry;
  }
  const kernel = extractRuntimeKernel(text);
  const entry: LeanSkillCacheEntry = {
    path: resolved.path,
    mtimeMs: stat.mtimeMs,
    size: stat.size,
    status: resolved.status,
    kernel,
    error:
      kernel === undefined
        ? `lean-code skill file has no parsable '# Runtime Kernel' section (${resolved.path})`
        : undefined,
  };
  leanSkillCache.set(resolved.path, entry);
  return entry;
}

/**
 * Decide the lean runtime behavior for one `before_agent_start` (pure
 * decision + fail-open load; never throws, never crashes the session).
 *
 * Precedence: role (hard_orchestrator/normal -> never) > env off > skill
 * missing/corrupt > retired > lifecycle active > env advisory. The base
 * prompt is required for injection (never invent a prompt) and checked for
 * the dedup marker.
 */
export function decideLeanRuntime(opts: {
  home: string | null;
  role: AgentRole;
  base: string | undefined;
  env?: Record<string, string | undefined>;
}): LeanRuntimeOutcome {
  const env = opts.env ?? process.env;
  const mode = (env[LEAN_ENV] ?? "").trim().toLowerCase() || null;

  const omit = (
    reason: LeanReason,
    skillStatus: LeanSkillStatus | null,
    kernelChars: number,
    dedupHit: boolean,
    error: string | undefined,
  ): LeanRuntimeOutcome => ({
    decision: "omit",
    reason,
    mode,
    skillStatus,
    kernelChars,
    dedupHit,
    error,
    kernel: undefined,
  });

  // Sol hard-orchestrator (plan §8.3) and non-code roles: NEVER inject.
  if (opts.role === "hard_orchestrator" || (opts.role !== "driver" && opts.role !== "worker")) {
    return omit("role", null, 0, false, undefined);
  }
  // Explicit off: forces inert (plan §8.2 env=off).
  if (mode !== null && LEAN_OFF_VALUES.has(mode)) {
    return omit("off", null, 0, false, undefined);
  }
  if (opts.home === null || opts.home.trim() === "") {
    return omit("skill-missing", null, 0, false, "brain home unavailable");
  }
  const loaded = loadLeanKernel(opts.home);
  if (loaded.error !== undefined || loaded.kernel === undefined) {
    return omit("skill-missing", loaded.status, 0, false, loaded.error);
  }
  // Retired disables runtime behavior (plan §26.1) — even under advisory.
  if (loaded.status === "retired") {
    return omit("off", loaded.status, loaded.kernel.length, false, undefined);
  }
  const lifecycleActive = loaded.status === "active";
  const advisory = mode !== null && LEAN_ADVISORY_VALUES.has(mode);
  if (!lifecycleActive && !advisory) {
    return omit("off", loaded.status, loaded.kernel.length, false, undefined);
  }
  const reason: LeanReason = lifecycleActive ? "active" : "advisory";
  const base = opts.base;
  if (base === undefined || base.trim() === "") {
    // Never invent a prompt: nothing to append to.
    return omit(reason, loaded.status, loaded.kernel.length, false, undefined);
  }
  const dedupHit = base.includes(LEAN_KERNEL_MARKER);
  return {
    decision: dedupHit ? "omit" : "inject",
    reason,
    mode,
    skillStatus: loaded.status,
    kernelChars: loaded.kernel.length,
    dedupHit,
    error: undefined,
    kernel: dedupHit ? undefined : loaded.kernel,
  };
}

/**
 * Append the lean kernel block to a base prompt. Returns undefined when the
 * base is undefined/empty (never invent a prompt) and returns the base
 * UNCHANGED when it already contains LEAN_KERNEL_MARKER (dedup, plan §8.4).
 * The block starts with the stable marker so one assembled prompt never
 * carries the kernel twice; the kernel text itself is the canonical section
 * verbatim (byte-stable, plan §7.4).
 */
export function appendLeanKernel(base: string | undefined, kernel: string): string | undefined {
  if (base === undefined || base.trim() === "") return undefined;
  if (base.includes(LEAN_KERNEL_MARKER)) return base;
  return `${base}

[${LEAN_KERNEL_MARKER}]
${kernel}`;
}
