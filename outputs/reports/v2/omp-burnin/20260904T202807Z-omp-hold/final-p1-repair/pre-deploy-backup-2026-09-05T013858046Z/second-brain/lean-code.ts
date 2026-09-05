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
 * P3-E fix (2026-08-16): the env gate alone cannot reach daemon-spawned
 * children (the Prime daemon pins its startup env), so the eval gate is
 * FILE-BASED as well: `SECOND_BRAIN_LEAN` (advisory/off) OVERRIDES; else
 * `config/skills.toml` `[lean] eval = "advisory" | "off"` is read per event
 * (absent => inert) — same live-flip pattern as AutoInject's
 * `config/autoinject.toml [autoinject] mode`. Precedence:
 * env advisory/off > file advisory/off > inert. No daemon, no new file, no
 * second promotion hierarchy. The resolved mode + its source are recorded
 * on every lean_kernel record (`mode`, `eval_source`).
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
import { existsSync, readFileSync, statSync, type Stats } from "node:fs";
import { join } from "node:path";
import type { AgentRole } from "./driver-orchestrator";

/** Stable dedup marker (plan §8.4): never inject the kernel twice. */
export const LEAN_KERNEL_MARKER = "second-brain-lean-code-kernel";

/** Env var that carries the smallest reversible eval mode (plan §8.2). */
export const LEAN_ENV = "SECOND_BRAIN_LEAN";

/** Exact section heading of the single canonical kernel source (plan §7.1). */
export const LEAN_KERNEL_HEADING = "# Runtime Kernel";

/** Exact section heading of the single canonical nudge source (plan T3.4). */
export const LEAN_NUDGE_HEADING = "# Nudge";

/** Frozen byte-stable 30-token nudge line (plan T3.4). */
export const LEAN_NUDGE_TEXT =
  "LEAN NUDGE: make the minimum sufficient change to meet acceptance; reuse existing code, avoid new abstractions or dependencies, and stop at acceptance.";

/** Literal rule table reasons (T3.4). */
export const LEAN_OPPORTUNITY_REASONS = [
  "REPEAT_READ",
  "SCOPE_EXPANSION",
  "NEW_DEPENDENCY",
  "NEW_ABSTRACTION",
  "POST_ACCEPTANCE_WORK",
  "UNRELATED_DIFF",
  "TEST_WEAKENING_RISK",
] as const;

export type LeanOpportunityReason = (typeof LEAN_OPPORTUNITY_REASONS)[number];

export type LeanLevel = "NOOP" | "NUDGE" | "FULL";
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

/** Resolved eval gate mode (env or file). */
export type LeanEvalMode = "advisory" | "off";

/** Lifecycle status resolved from the skill directory (missing = no file). */
export type LeanSkillStatus = "active" | "shadow" | "candidate" | "retired" | "missing";

/** Enumerated reason for every lean decision (SCHEMA.md `lean_kernel`). */
export type LeanReason =
  | "active"
  | "advisory"
  | "off"
  | "role"
  | "skill-missing"
  | "noop"
  | LeanOpportunityReason
  | string;

/** Final lean decision for one `before_agent_start`. */
export interface LeanRuntimeOutcome {
  /** inject = a kernel patch was produced for the caller to apply. */
  decision: "inject" | "omit";
  /** Why: active/advisory lifecycle; off (env or not-yet-active/retired); role (not driver/worker); skill-missing. */
  reason: LeanReason;
  /** Resolved eval gate value (trimmed, lowercased) or null when inert:
   * env SECOND_BRAIN_LEAN advisory/off wins; else config/skills.toml
   * [lean] eval advisory/off; absent => null (inert). */
  mode: string | null;
  /** Where the resolved mode came from: "env" | "file" | null. */
  evalSource: "env" | "file" | null;
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
  /** Opportunity controller level (T3.4): NOOP | NUDGE | FULL. */
  level?: LeanLevel;
  /** Placement slot (T3.4): TAIL (never prefix). */
  placement?: "tail";
  /** Active reasons triggered. */
  reasons?: string[];
  /** Frozen byte-stable nudge line if level === "NUDGE". */
  nudge?: string;
}

/** In-process kernel cache entry (plan §8.6). */
interface LeanSkillCacheEntry {
  path: string;
  mtimeMs: number;
  size: number;
  status: LeanSkillStatus;
  kernel: string | undefined;
  nudge: string | undefined;
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

/**
 * Extract the "# Nudge" section from a skill file's text (plan T3.4).
 */
export function extractRuntimeNudge(skillText: string): string | undefined {
  const lines = skillText.split(/\r?\n/);
  let inNudge = false;
  const body: string[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!inNudge) {
      if (line === LEAN_NUDGE_HEADING) inNudge = true;
      continue;
    }
    if (/^#\s/.test(line)) break;
    body.push(raw);
  }
  if (!inNudge) return undefined;
  const nudge = body.join("\n").trim();
  return nudge.length > 0 ? nudge : undefined;
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
    return { path: "", mtimeMs: -1, size: -1, status: "missing", kernel: undefined, nudge: undefined, error: "lean-code skill file not found under skills/active|shadow|candidates|retired" };
  }
  let stat: Stats | undefined;
  try {
    stat = statSync(resolved.path);
  } catch {
    return { path: resolved.path, mtimeMs: -1, size: -1, status: resolved.status, kernel: undefined, nudge: undefined, error: `cannot stat lean-code skill file: ${resolved.path}` };
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
      nudge: undefined,
      error: `cannot read lean-code skill file: ${error instanceof Error ? error.message : String(error)}`,
    };
    leanSkillCache.set(resolved.path, entry);
    return entry;
  }
  const kernel = extractRuntimeKernel(text);
  const nudge = extractRuntimeNudge(text) ?? LEAN_NUDGE_TEXT;
  const entry: LeanSkillCacheEntry = {
    path: resolved.path,
    mtimeMs: stat.mtimeMs,
    size: stat.size,
    status: resolved.status,
    kernel,
    nudge,
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
/**
 * Parse `[lean] eval` from a config/skills.toml text using the same tiny
 * TOML-subset parser style as autoinject.ts `modeFromAutoinjectToml`
 * (section headers, `key = value` lines, `#` comments stripped). PURE and
 * deterministic: never throws, never touches the filesystem.
 *
 * Returns "advisory" | "off" when the `[lean]` section carries a recognized
 * `eval` value, undefined when the section/key/value is absent or invalid
 * (absent => inert; invalid values are treated as absent — the AutoInject
 * precedent). An unrecognized value is NOT a parse error: it is inert.
 */
export function leanEvalFromSkillsToml(text: string): LeanEvalMode | undefined {
  let inLean = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inLean = line.startsWith("[lean]");
      continue;
    }
    if (!inLean || line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    if (key !== "eval") continue;
    const value = line.slice(eq + 1).split("#")[0].trim().replace(/^"|"$/g, "").toLowerCase();
    if (LEAN_ADVISORY_VALUES.has(value)) return "advisory";
    if (LEAN_OFF_VALUES.has(value)) return "off";
    return undefined;
  }
  return undefined;
}

/**
 * Parse `[lean] opportunity` from config/skills.toml text (plan T3.4).
 */
export function leanOpportunityFromSkillsToml(text: string): boolean {
  let inLean = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("[")) {
      inLean = line.startsWith("[lean]");
      continue;
    }
    if (!inLean || line === "" || line.startsWith("#")) continue;
    if (!line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    if (key.trim() !== "opportunity") continue;
    const val = rest.join("=").split("#")[0].trim().replace(/^["']|["']$/g, "").toLowerCase();
    return val === "true" || val === "1" || val === "yes" || val === "on" || val === "active";
  }
  return false;
}

export interface LeanCooldownState {
  currentPhase: string;
  nudgesEmittedInPhase: number;
  emittedReasons: Set<string>;
  lastSeverity: LeanLevel;
}

const sessionCooldownStates = new Map<string, LeanCooldownState>();

export function resetLeanCooldown(): void {
  sessionCooldownStates.clear();
}

export function computeLeanSeverity(reasons: string[]): LeanLevel {
  const distinct = new Set(reasons);
  if (distinct.size === 0) return "NOOP";
  if (distinct.has("TEST_WEAKENING_RISK") || distinct.size >= 2) return "FULL";
  return "NUDGE";
}

export function applyLeanCooldown(
  reasons: string[],
  opts?: { sessionId?: string; phase?: string },
): { finalLevel: LeanLevel; activeReasons: string[] } {
  const key = opts?.sessionId ?? "default";
  let state = sessionCooldownStates.get(key);
  if (!state) {
    state = {
      currentPhase: "default",
      nudgesEmittedInPhase: 0,
      emittedReasons: new Set(),
      lastSeverity: "NOOP",
    };
    sessionCooldownStates.set(key, state);
  }

  const taskPhase = opts?.phase ?? "default";
  if (taskPhase !== state.currentPhase) {
    state.currentPhase = taskPhase;
    state.nudgesEmittedInPhase = 0;
  }

  const candidateReasons = reasons.filter((r) => !state!.emittedReasons.has(r));
  if (candidateReasons.length === 0) {
    state.lastSeverity = "NOOP";
    return { finalLevel: "NOOP", activeReasons: [] };
  }

  const targetSeverity = computeLeanSeverity(candidateReasons);
  if (targetSeverity === "NUDGE") {
    if (state.nudgesEmittedInPhase >= 1) {
      state.lastSeverity = "NOOP";
      return { finalLevel: "NOOP", activeReasons: [] };
    }
    state.nudgesEmittedInPhase++;
    for (const r of candidateReasons) {
      state.emittedReasons.add(r);
    }
    state.lastSeverity = "NUDGE";
    return { finalLevel: "NUDGE", activeReasons: candidateReasons };
  }

  if (targetSeverity === "FULL") {
    if (state.lastSeverity === "FULL") {
      return { finalLevel: "NOOP", activeReasons: [] };
    }
    for (const r of candidateReasons) {
      state.emittedReasons.add(r);
    }
    state.lastSeverity = "FULL";
    return { finalLevel: "FULL", activeReasons: candidateReasons };
  }

  state.lastSeverity = "NOOP";
  return { finalLevel: "NOOP", activeReasons: [] };
}

export interface DecideLeanRuntimeOptions {
  home: string | null;
  role: AgentRole;
  base: string | undefined;
  env?: Record<string, string | undefined>;
  sessionId?: string;
  phase?: string;
  opportunity?: boolean;
  reasons?: string[];
  readLedger?: Array<{ blob_sha?: string; hash?: string; path?: string }>;
  diff?: string;
  capsule?: { files_touched?: string[] };
  requirements?: Array<{ id?: string; requirement?: string; status?: string; importance?: string; refs?: string[]; evidence?: string[] }>;
  modifiedFiles?: string[];
  requirementRefs?: string[];
  toolCalls?: unknown[];
  postAcceptanceWork?: boolean;
}

export interface LeanEvalResolution {
  mode: LeanEvalMode | null;
  source: "env" | "file" | null;
  /** Bounded failure detail (unreadable config file); undefined = ok. */
  error: string | undefined;
}

/**
 * Resolve the eval gate for one event: env `SECOND_BRAIN_LEAN` (advisory/off)
 * OVERRIDES; otherwise `config/skills.toml [lean] eval` (absent => inert).
 * An unrecognized env value falls through to the file (same as unset). A
 * missing file/key/value is NOT an error (default-off); an existing-but-
 * unreadable file is a fail-open bounded error (caller records ONE
 * extension_error and stays inert). No daemon, no new file.
 */
export function resolveLeanEvalFromFile(
  home: string | null,
): Omit<LeanEvalResolution, "source"> & { source: "file" | null } {
  if (home === null || home.trim() === "") {
    return { mode: null, source: null, error: undefined };
  }
  const file = join(home, "config", "skills.toml");
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch (error) {
    if (existsSync(file)) {
      return {
        mode: null,
        source: null,
        error: `cannot read config/skills.toml: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
    return { mode: null, source: null, error: undefined }; // absent file => inert
  }
  const mode = leanEvalFromSkillsToml(text);
  return mode === undefined
    ? { mode: null, source: null, error: undefined }
    : { mode, source: "file", error: undefined };
}

export function decideLeanRuntime(opts: DecideLeanRuntimeOptions): LeanRuntimeOutcome {
  const env = opts.env ?? process.env;
  const rawEnv = (env[LEAN_ENV] ?? "").trim().toLowerCase() || null;

  const omit = (
    reason: LeanReason,
    skillStatus: LeanSkillStatus | null,
    kernelChars: number,
    dedupHit: boolean,
    error: string | undefined,
    mode: string | null,
    evalSource: "env" | "file" | null,
    nudge?: string,
  ): LeanRuntimeOutcome => ({
    decision: "omit",
    reason,
    mode,
    evalSource,
    skillStatus,
    kernelChars,
    dedupHit,
    error,
    kernel: undefined,
    level: "NOOP",
    placement: "tail",
    reasons: [],
    nudge,
  });

  if (opts.role === "hard_orchestrator" || (opts.role !== "driver" && opts.role !== "worker")) {
    return omit("role", null, 0, false, undefined, null, null);
  }

  let mode: LeanEvalMode | null = null;
  let evalSource: "env" | "file" | null = null;
  if (rawEnv !== null && LEAN_ADVISORY_VALUES.has(rawEnv)) {
    mode = "advisory";
    evalSource = "env";
  } else if (rawEnv !== null && LEAN_OFF_VALUES.has(rawEnv)) {
    mode = "off";
    evalSource = "env";
  } else {
    const file = resolveLeanEvalFromFile(opts.home);
    if (file.error !== undefined) {
      return omit("off", null, 0, false, file.error, null, null);
    }
    mode = file.mode;
    evalSource = file.source;
  }

  if (mode === "off") {
    return omit("off", null, 0, false, undefined, mode, evalSource);
  }
  if (opts.home === null || opts.home.trim() === "") {
    return omit("skill-missing", null, 0, false, "brain home unavailable", mode, evalSource);
  }
  const loaded = loadLeanKernel(opts.home);
  if (loaded.error !== undefined || loaded.kernel === undefined) {
    return omit("skill-missing", loaded.status, 0, false, loaded.error, mode, evalSource);
  }
  if (loaded.status === "retired") {
    return omit("off", loaded.status, loaded.kernel.length, false, undefined, mode, evalSource, loaded.nudge);
  }
  const lifecycleActive = loaded.status === "active";
  const advisory = mode === "advisory";
  if (!lifecycleActive && !advisory) {
    return omit("off", loaded.status, loaded.kernel.length, false, undefined, mode, evalSource, loaded.nudge);
  }

  const isOpportunity =
    opts.opportunity === true ||
    opts.reasons !== undefined ||
    opts.readLedger !== undefined ||
    opts.diff !== undefined ||
    opts.capsule !== undefined ||
    opts.requirements !== undefined ||
    opts.modifiedFiles !== undefined ||
    opts.requirementRefs !== undefined ||
    opts.toolCalls !== undefined ||
    opts.postAcceptanceWork === true;

  const nudgeText = loaded.nudge ?? LEAN_NUDGE_TEXT;

  if (isOpportunity) {
    const reasons = opts.reasons ?? [];
    const cooldown = applyLeanCooldown(reasons, {
      sessionId: opts.sessionId,
      phase: opts.phase,
    });
    const base = opts.base;
    const dedupHit = base !== undefined && base.includes(LEAN_KERNEL_MARKER);

    if (cooldown.finalLevel === "NOOP" || dedupHit) {
      return {
        decision: "omit",
        reason: dedupHit ? (lifecycleActive ? "active" : "advisory") : "noop",
        mode,
        evalSource,
        skillStatus: loaded.status,
        kernelChars: 0,
        dedupHit,
        error: undefined,
        kernel: undefined,
        level: "NOOP",
        placement: "tail",
        reasons: cooldown.activeReasons,
        nudge: nudgeText,
      };
    }

    if (cooldown.finalLevel === "NUDGE") {
      return {
        decision: "inject",
        reason: cooldown.activeReasons[0] ?? (lifecycleActive ? "active" : "advisory"),
        mode,
        evalSource,
        skillStatus: loaded.status,
        kernelChars: nudgeText.length,
        dedupHit: false,
        error: undefined,
        kernel: nudgeText,
        level: "NUDGE",
        placement: "tail",
        reasons: cooldown.activeReasons,
        nudge: nudgeText,
      };
    }

    // FULL
    return {
      decision: "inject",
      reason: cooldown.activeReasons[0] ?? (lifecycleActive ? "active" : "advisory"),
      mode,
      evalSource,
      skillStatus: loaded.status,
      kernelChars: loaded.kernel.length,
      dedupHit: false,
      error: undefined,
      kernel: loaded.kernel,
      level: "FULL",
      placement: "tail",
      reasons: cooldown.activeReasons,
      nudge: nudgeText,
    };
  }

  // Classic mode
  const reason: LeanReason = lifecycleActive ? "active" : "advisory";
  const base = opts.base;
  if (base === undefined || base.trim() === "") {
    return omit(reason, loaded.status, loaded.kernel.length, false, undefined, mode, evalSource, nudgeText);
  }
  const dedupHit = base.includes(LEAN_KERNEL_MARKER);
  return {
    decision: dedupHit ? "omit" : "inject",
    reason,
    mode,
    evalSource,
    skillStatus: loaded.status,
    kernelChars: loaded.kernel.length,
    dedupHit,
    error: undefined,
    kernel: dedupHit ? undefined : loaded.kernel,
    level: dedupHit ? "NOOP" : "FULL",
    reasons: [],
    nudge: nudgeText,
  };
}

export function evaluateLeanOpportunity(opts: DecideLeanRuntimeOptions): LeanRuntimeOutcome {
  return decideLeanRuntime({ ...opts, opportunity: true });
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
