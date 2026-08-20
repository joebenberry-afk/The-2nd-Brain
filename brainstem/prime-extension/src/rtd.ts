/**
 * Phase 5 (RTD — real-time distillation). Shadow measurement PLUS the P3-F
 * substitution surface (plan §11): when config/context.toml `[rtd] enabled =
 * true`, eligible large bash results (pytest/git/rg/grep, text-only, above
 * threshold_chars) are FIRST preserved byte-exactly through the existing
 * artifact store (`second_brain artifact store`, sha256 content-addressed)
 * and verified recoverable; ONLY THEN is the model-visible content replaced
 * by a deterministic [SECOND_BRAIN_RTD] block (head/tail + command-class
 * evidence + artifact pointer). Any preservation failure returns the ORIGINAL
 * content unchanged (plan §11.4: never trade recoverability for savings).
 *
 * Trigger rule (Phase 3 order — eligibility BEFORE any content work):
 *   toolName === "bash"
 *   AND the event input's command starts with one of
 *      ["pytest", "git", "rg", "grep"] (case-insensitive)
 *   AND precomputed serialized content length
 *      (JSON.stringify(content).length, legacy character metric) > threshold.
 *
 * RTD never serializes content itself: the caller decides eligibility FIRST
 * (`rtdEligibility`) and only then measures the result ONCE
 * (`measureContent`, serialized chars included only when eligible) and passes
 * the shared `ContentMeasurement` plus the precomputed eligibility.
 * Ineligible tools/commands therefore perform zero RTD-specific
 * serialization (ineligible primitive strings: not even one JSON.stringify).
 *
 * Privacy: only counts/sizes/decisions are ever stored — never content.
 */

/** Bash command prefixes that qualify for distillation. */
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import type { ContentMeasurement } from "./sensors";
import type { RtdFileConfig } from "./config";
import { resolveBrainHome, rtdThresholdFromConfig } from "./config";
export const RTD_COMMAND_PREFIXES = ["pytest", "git", "rg", "grep"] as const;

/** Canonical command classes `resolveCommandClass` can resolve a leading
 * command segment to. Kept identical to `RTD_COMMAND_PREFIXES`'s member
 * values so `whitelist_commands` config semantics are unchanged. */
export type CommandClass = "pytest" | "git" | "rg" | "grep";

/** Shell metacharacters/operators that terminate the LEADING command
 * segment (Part A adversarial requirement: nothing after a chain/redirect
 * is ever inspected). Order-independent; first match wins. */
const SHELL_CHAIN_RE = /&&|\|\||[;|<>`]|\$\(/;

/** Cut `command` at the first shell metacharacter/operator, keeping only
 * the leading segment. No match -> the whole string is the leading segment. */
function leadingCommandSegment(command: string): string {
  const match = SHELL_CHAIN_RE.exec(command);
  return match ? command.slice(0, match.index) : command;
}

/** Tokenize a leading command segment, respecting a single leading quoted
 * token (Windows absolute paths: `"C:\\...\\python.exe" -m pytest`).
 * Only the FIRST token is quote-aware; the rest is a plain whitespace
 * split (adequate for the fixed-position `-m`/`pytest` check below). */
function tokenizeLeadingSegment(segment: string): string[] {
  const trimmed = segment.trimStart();
  if (trimmed.length === 0) return [];
  const quoteChar = trimmed[0];
  if (quoteChar === '"' || quoteChar === "'") {
    const closeAt = trimmed.indexOf(quoteChar, 1);
    if (closeAt !== -1) {
      const first = trimmed.slice(1, closeAt);
      const rest = trimmed.slice(closeAt + 1).trim();
      const restTokens = rest.length > 0 ? rest.split(/\s+/) : [];
      return [first, ...restTokens];
    }
    // Unterminated quote: fall through to a defensive plain split so this
    // never throws or hangs; still fully deterministic.
  }
  return trimmed.split(/\s+/).filter((t) => t.length > 0);
}

/** Path basename of a command token, lower-cased, with a trailing `.exe`
 * stripped (case-insensitive). Handles both `/` and `\` separators. */
function commandBasename(token: string): string {
  const normalized = token.replace(/\\/g, "/");
  const parts = normalized.split("/");
  const base = (parts[parts.length - 1] ?? token).toLowerCase();
  return base.endsWith(".exe") ? base.slice(0, -4) : base;
}

/**
 * Deterministic canonical-command resolver (Part A, RC4 pass). Resolves the
 * LEADING command segment of a raw shell command string to one of the fixed
 * canonical classes RTD recognizes, or null when ineligible. Token-exact
 * comparisons only — never substring/`.includes()` matching against the raw
 * command string, so a benign later occurrence of a class name (e.g. inside
 * a quoted `-k` argument, or after a `&&`) never flips the decision either
 * way.
 *
 * Rules (in order):
 *   1. bin0 === "pytest" -> "pytest" (direct/quoted-absolute pytest[.exe]).
 *   2. bin0 in {python, python3, py} AND token[1] === "-m" AND
 *      token[2] === "pytest" (exact tokens; not "-mpytest", not "-m
 *      unittest") -> "pytest". No other `-m <module>` is recognized.
 *   3. bin0 === "git" -> "git", bin0 === "rg" -> "rg", bin0 === "grep" ->
 *      "grep".
 *   4. anything else -> null.
 */
export function resolveCommandClass(command: string): CommandClass | null {
  if (typeof command !== "string" || command.trim().length === 0) return null;
  const leading = leadingCommandSegment(command);
  const tokens = tokenizeLeadingSegment(leading);
  if (tokens.length === 0) return null;
  const bin0 = commandBasename(tokens[0] ?? "");
  if (bin0 === "pytest") return "pytest";
  if (bin0 === "python" || bin0 === "python3" || bin0 === "py") {
    if (tokens[1] === "-m" && tokens[2] === "pytest") return "pytest";
    return null;
  }
  if (bin0 === "git") return "git";
  if (bin0 === "rg") return "rg";
  if (bin0 === "grep") return "grep";
  return null;
}

/**
 * Default size threshold when neither SECOND_BRAIN_RTD_THRESHOLD nor
 * context.toml [rtd] threshold_chars provides a value.
 */
export const RTD_DEFAULT_THRESHOLD = 8000;

export type DistillReason = "size" | "tool" | "command" | "ok";

/** Minimal event surface consumed by the distill decision (no content). */
export interface DistillEvent {
  toolName: unknown;
  input?: unknown;
}

export interface DistillDecision {
  trigger: boolean;
  reason: DistillReason;
}

/**
 * Tool/command eligibility for RTD — decided WITHOUT touching result content
 * (Phase 3). Returns "tool" (not bash / not whitelisted), "command" (bash
 * command outside the prefix list), or "ok" (eligible for the size check).
 *
 * P3-F: an optional `[rtd]` config supplies whitelist_tools/whitelist_commands
 * (plan §11.3); when omitted the fixed P3 defaults apply (bash +
 * pytest/git/rg/grep — the proven bounded surface, plan §11.2). The first
 * whitespace-separated token only: `git status` matches, `gitx` must not.
 */
export interface ResolvedToolCommand {
  /** Canonical tool class recognized by `whitelist_tools` ("bash" today),
   * or null when the real host tool name maps to no known class. */
  toolClass: "bash" | null;
  /** Extracted command text for the `whitelist_commands` prefix check, when
   * this tool call's input shape actually carries one. */
  command?: string;
}

/**
 * Map a REAL host tool call (name + input) to the canonical tool class
 * `whitelist_tools` is expressed in (plan §11.2 default ["bash"]). Pilot 1
 * (outputs/reports/rc4/11-real-prime-pilot.md) found the real tool catalog
 * in an RLM/IPython-orchestrated Prime session is a single `"ipython"` tool
 * whose `{code}` input runs `%%bash\n<command>` cells for shell commands —
 * `whitelist_tools: ["bash"]` never matched the literal name `"ipython"`,
 * so RTD never fired. `whitelist_tools` config values stay canonical CLASS
 * names ("bash") — this function is only the seam that decides which real
 * tool names map to that class; it is not a change to whitelist semantics
 * (adding "ipython" as a bare string would make RTD try to distill EVERY
 * ipython call, including plain Python with no shell command at all, which
 * is explicitly not eligible here).
 */
export function resolveToolClass(toolName: unknown, input: unknown): ResolvedToolCommand {
  if (typeof toolName !== "string") return { toolClass: null };
  const lower = toolName.toLowerCase();
  if (lower === "bash") {
    // Real bash tool: unchanged existing behavior.
    return { toolClass: "bash", command: commandFromInput(input) };
  }
  if (lower === "ipython") {
    const code =
      input && typeof input === "object" ? (input as Record<string, unknown>).code : undefined;
    if (typeof code !== "string") return { toolClass: "bash" }; // no code -> no command
    const lines = code.split(/\r?\n/);
    let i = 0;
    while (i < lines.length && (lines[i] ?? "").trim() === "") i += 1;
    if (i >= lines.length || (lines[i] ?? "").trim() !== "%%bash") {
      return { toolClass: "bash" }; // plain Python cell: no %%bash header, no command
    }
    i += 1;
    while (i < lines.length && (lines[i] ?? "").trim() === "") i += 1;
    const candidate = i < lines.length ? (lines[i] ?? "").trim() : "";
    return { toolClass: "bash", command: candidate.length > 0 ? candidate : undefined };
  }
  return { toolClass: null };
}

/**
 * Tool/command eligibility for RTD — decided WITHOUT touching result content
 * (Phase 3). Returns "tool" (real tool name maps to no whitelisted class),
 * "command" (the resolved command is missing or outside the prefix list),
 * or "ok" (eligible for the size check).
 *
 * P3-F: an optional `[rtd]` config supplies whitelist_tools/whitelist_commands
 * (plan §11.3); when omitted the fixed P3 defaults apply (bash class +
 * pytest/git/rg/grep — the proven bounded surface, plan §11.2). The first
 * whitespace-separated token only: `git status` matches, `gitx` must not.
 * `resolveToolClass` (above) maps the real host tool name/input to the
 * canonical class BEFORE this whitelist check runs (Phase C host-tool
 * normalization).
 */
export function rtdEligibility(
  toolName: unknown,
  input: unknown,
  cfg?: Pick<RtdFileConfig, "whitelistTools" | "whitelistCommands">,
): Extract<DistillReason, "tool" | "command" | "ok"> {
  const tools = cfg?.whitelistTools ?? ["bash"];
  const resolved = resolveToolClass(toolName, input);
  if (resolved.toolClass === null || !tools.some((t) => t === resolved.toolClass)) {
    return "tool";
  }
  const command = resolved.command;
  if (!command) return "command";
  // Part A: canonical-class resolution (leading segment only, single quoted
  // first token, exact `-m pytest` recognition) replaces the old bare
  // first-whitespace-token literal check, which never matched a quoted
  // absolute interpreter path (e.g. this repo's own mandated venv-python
  // invocation) nor `python -m pytest`.
  const commandClass = resolveCommandClass(command);
  const commands = cfg?.whitelistCommands ?? RTD_COMMAND_PREFIXES;
  if (commandClass === null || !commands.some((prefix) => prefix === commandClass)) {
    return "command";
  }
  return "ok";
}

/** Serialized size of arbitrary content; 0 when not serializable. */
export function serializedSize(content: unknown): number {
  try {
    const serialized = JSON.stringify(content);
    return typeof serialized === "string" ? serialized.length : 0;
  } catch {
    return 0;
  }
}

/** Command string from a tool input object (bash tool), or undefined. */
export function commandFromInput(input: unknown): string | undefined {
  if (!input || typeof input !== "object") return undefined;
  const command = (input as Record<string, unknown>).command;
  return typeof command === "string" && command.length > 0 ? command : undefined;
}

/**
 * Resolve the RTD size threshold with the Phase 12 precedence ladder:
 *   1. env `SECOND_BRAIN_RTD_THRESHOLD` (highest) — when set AND a valid
 *      non-negative integer, it wins;
 *   2. `<brain-home>/config/context.toml [rtd] threshold_chars` — when the
 *      env value is absent OR invalid, the file value wins (brain home via
 *      `config.resolveBrainHome`, same env gate as the rest of the
 *      extension);
 *   3. `fallback` (default 8000) — when neither provides a valid value.
 * A missing/unreadable context.toml or absent/invalid file value falls back.
 * File reads never throw (see `rtdThresholdFromConfig`).
 */
export function parseThreshold(raw: string | undefined, fallback = RTD_DEFAULT_THRESHOLD): number {
  if (raw !== undefined && raw !== null) {
    const parsed = Number.parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
    // env set but invalid -> fall through to the file, then the fallback
  }
  return rtdThresholdFromConfig(resolveBrainHome()) ?? fallback;
}

/**
 * Decide whether a tool result would be distilled, using the caller's
 * precomputed `measurement` (Phase 3). Eligibility is decided first —
 * ineligible tools/commands short-circuit without using the measurement.
 * reason: "tool" (not bash), "command" (bash command not in the prefix
 * list), "size" (eligible but size not above threshold), "ok" (would
 * trigger). Size semantics: legacy `JSON.stringify(content).length` via
 * `measurement.serializedChars`.
 *
 * `eligibility` is the precomputed decision (real handler computes it before
 * any content measurement and passes it through). When omitted (public
 * compatibility for direct callers), it is derived from the event exactly
 * once. The event input is therefore never read twice on any path.
 */
export function shouldDistill(
  event: DistillEvent,
  threshold: number,
  measurement: ContentMeasurement,
  eligibility: Extract<DistillReason, "tool" | "command" | "ok"> = rtdEligibility(
    event.toolName,
    event.input,
  ),
): DistillDecision {
  if (eligibility !== "ok") {
    return { trigger: false, reason: eligibility };
  }
  if (!(measurement.serializedChars > threshold)) {
    return { trigger: false, reason: "size" };
  }
  return { trigger: true, reason: "ok" };
}

/** Shadow telemetry record for a would-distill result (schema v2, additive). */
export interface RtdShadowRecord {
  v: 2;
  ts: string;
  kind: "rtd_shadow";
  session: string;
  tool: string;
  id: string;
  size: number;
  threshold: number;
  would_trigger: boolean;
  reason: string;
  /** Present only when SECOND_BRAIN_RTD=active: substitution not implemented yet. */
  substitution?: string;
  // P3-F additive fields (plan §11.9 — never raw content):
  original_chars?: number;
  visible_chars?: number;
  saved_chars?: number;
  artifact_ref?: string;
  command_class?: string;
  error_status?: boolean;
  distilled?: boolean;
}

export interface RtdShadowOptions {
  session: string;
  tool: unknown;
  id: unknown;
  input: unknown;
  /**
   * Precomputed eligibility (Phase 3, corrected): the real handler decides
   * `rtdEligibility(toolName, input)` BEFORE any content measurement and
   * passes it here so the measurement mode can be chosen accordingly.
   * Optional for direct/standalone callers (derived from tool/input).
   */
  eligibility?: Extract<DistillReason, "tool" | "command" | "ok">;
  /** Shared precomputed measurement (Phase 3): one serialization, both metrics. */
  measurement: ContentMeasurement;
  threshold: number;
  /** SECOND_BRAIN_RTD === "active" — records intent; substitution is NOT implemented. */
  active: boolean;
  /** P3-F: populated on the substitution path (distilled or preservation-failed). */
  distill?: RtdDistillDetail;
}

/** P3-F additive detail for the rtd_shadow record (plan §11.9). */
export interface RtdDistillDetail {
  originalChars: number;
  visibleChars: number;
  savedChars: number;
  artifactRef: string;
  commandClass: string;
  errorStatus: boolean;
  distilled: boolean;
}

/**
 * Build the rtd_shadow record, or null when the result would not distill.
 * Eligibility is decided ONCE — the precomputed value when provided (real
 * handler), else derived from tool/input exactly once — and that SAME value
 * is passed to shouldDistill, so the event input is never re-read and the
 * decision cannot diverge. Ineligible results never touch the measurement.
 * Never logs content — only size/decision fields. `size` = legacy serialized
 * character length.
 */
export function rtdShadowRecord(options: RtdShadowOptions): RtdShadowRecord | null {
  // Single decision: precomputed (real path) or derived exactly once (compat).
  const eligibility = options.eligibility ?? rtdEligibility(options.tool, options.input);
  const decision = shouldDistill(
    { toolName: options.tool, input: options.input },
    options.threshold,
    options.measurement,
    eligibility,
  );
  if (!decision.trigger) return null;
  const record: RtdShadowRecord = {
    v: 2,
    ts: new Date().toISOString(),
    kind: "rtd_shadow",
    session: options.session,
    tool: typeof options.tool === "string" ? options.tool : "unknown",
    id: typeof options.id === "string" ? options.id : "unknown",
    size: options.measurement.serializedChars,
    threshold: options.threshold,
    would_trigger: true,
    reason: options.active ? "would-substitute" : decision.reason,
  };
  if (options.active && !options.distill) {
    record.substitution = "enabled-not-implemented";
  }
  if (options.distill) {
    record.original_chars = options.distill.originalChars;
    record.visible_chars = options.distill.visibleChars;
    record.saved_chars = options.distill.savedChars;
    record.artifact_ref = options.distill.artifactRef;
    record.command_class = options.distill.commandClass;
    record.error_status = options.distill.errorStatus;
    record.distilled = options.distill.distilled;
  }
  return record;
}

// ---------------------------------------------------------------------------
// P3-F substitution surface (plan §11) — preserve raw FIRST, then replace the
// model-visible content with a deterministic [SECOND_BRAIN_RTD] block.
// ---------------------------------------------------------------------------

/** Preservation seam: persists the exact raw result + proves recoverability. */
export interface RtdPreserver {
  /** Persist raw text through the artifact store; returns sha256 + handle,
   * or null when preservation failed (never throws). */
  preserve(raw: string): Promise<{ sha256: string; handle: string } | null>;
  /** Prove the artifact expands back to the EXACT raw bytes. */
  verify(sha256: string, raw: string): Promise<boolean>;
}

/** Artifact handle template (artifacts.py make_handle). */
export const RTD_ARTIFACT_HANDLE_RE = /\[brain-artifact:sha256:([0-9a-f]{64})\]/;

/** sha256 hex (same primitive as sensors.sha256Hex, kept local). */
export function rtdSha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/**
 * Shared preservation factory (RC4 byte-exact recovery pass, Part A): both
 * `cliRtdPreserver` (kind="rtd_raw", tool="bash") and the AutoInject packet
 * preserver (kind="autoinject_packet", tool="autoinject", index.ts) call
 * this SAME preserve->verify machinery -- there is exactly ONE
 * preserve/verify subprocess implementation in the extension. Real
 * preservation via the existing CLI: `second_brain artifact store --kind
 * <kind> --tool <tool> --session <sid> --no-distill` (content-addressed
 * blob + meta, atomic) then `artifact expand <sha256>` byte-compared
 * against the raw text (plan §11.4 "verify the reference is recoverable").
 * Any spawn/parse/mismatch failure => null/false (fail-open: caller keeps
 * the original content unchanged). No venv => not a runtime => fail open.
 */
export function cliArtifactPreserver(opts: {
  home: string;
  session: string;
  kind: string;
  tool: string;
  python?: string;
  timeoutMs?: number;
}): RtdPreserver {
  const python = opts.python ?? join(opts.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = opts.home;
  const run = (
    args: string[],
    input?: string,
  ): Promise<{ error?: string; stdout: string }> =>
    new Promise((resolve) => {
      if (!existsSync(python)) {
        resolve({ error: "no brain venv (artifact store unavailable)", stdout: "" });
        return;
      }
      const child = execFile(
        python,
        args,
        {
          cwd: opts.home,
          env,
          timeout: opts.timeoutMs ?? 5000,
          windowsHide: true,
          maxBuffer: 32 * 1024 * 1024,
        },
        (error, stdout) => resolve({ error: error?.message, stdout: stdout ?? "" }),
      );
      if (input !== undefined) {
        child.stdin?.write(input);
        child.stdin?.end();
      }
    });
  return {
    async preserve(raw) {
      const result = await run(
        [
          "-m",
          "second_brain",
          "artifact",
          "store",
          "--kind",
          opts.kind,
          "--tool",
          opts.tool,
          "--session",
          opts.session,
          "--no-distill",
        ],
        raw,
      );
      if (result.error) return null;
      const match = result.stdout.match(RTD_ARTIFACT_HANDLE_RE);
      if (!match) return null;
      const sha256 = match[1] ?? "";
      // Content-addressing cross-check: the handle MUST be the sha256 of the
      // exact raw bytes we sent.
      if (sha256 !== rtdSha256Hex(raw)) return null;
      return { sha256, handle: match[0] };
    },
    async verify(sha256, raw) {
      const result = await run(["-m", "second_brain", "artifact", "expand", sha256]);
      if (result.error) return false;
      return result.stdout === raw; // byte-identical recovery
    },
  };
}

/**
 * RTD-specific wrapper over the shared `cliArtifactPreserver` factory
 * (kind="rtd_raw", tool="bash") -- RTD's own call sites are unchanged.
 */
export function cliRtdPreserver(opts: {
  home: string;
  session: string;
  python?: string;
  timeoutMs?: number;
}): RtdPreserver {
  return cliArtifactPreserver({ ...opts, kind: "rtd_raw", tool: "bash" });
}


/** Command class of an eligible bash command (first token). */
export function commandClassOf(input: unknown): string {
  return commandFromInput(input)?.trim().split(/\s+/)[0]?.toLowerCase() ?? "bash";
}

/** Extract the exact raw text from Prime content blocks; undefined when any
 * block is not a plain text block (images/binary => NEVER distill, §11.8). */
export function textFromContent(content: unknown[]): string | undefined {
  if (!Array.isArray(content) || content.length === 0) return undefined;
  let text = "";
  for (const item of content) {
    if (!item || typeof item !== "object") return undefined;
    const block = item as { type?: unknown; text?: unknown };
    if (block.type !== "text" || typeof block.text !== "string") return undefined;
    text += block.text;
  }
  return text.length > 0 ? text : undefined;
}

/**
 * Deterministic pytest evidence: the FAILURES/ERRORS section (bounded),
 * failing test names, and the summary line. No LLM, no parsing framework.
 */
export function pytestEvidence(raw: string): string | undefined {
  const lines = raw.split(/\r?\n/);
  const start = lines.findIndex((l) => /^={3,}\s*(FAILURES|ERRORS)/.test(l));
  const summary = lines.find((l) => /^={3,}\s*\d+\s+(passed|failed)/.test(l));
  if (start === -1 && !summary) return undefined;
  const parts: string[] = [];
  if (start >= 0) {
    const end = lines.findIndex(
      (l, i) => i > start && /^={3,}\s*\d+\s+(passed|failed)/.test(l),
    );
    const section = lines
      .slice(start, end > start ? end : Math.min(lines.length, start + 400))
      .join("\n");
    parts.push(section.slice(0, 1500));
  }
  const failing = lines.filter((l) => l.startsWith("FAILED ")).slice(0, 20);
  if (failing.length > 0) {
    parts.push(`FAILING TESTS (${failing.length}):\n${failing.join("\n")}`);
  }
  if (summary) parts.push(summary);
  return parts.length > 0 ? parts.join("\n\n") : undefined;
}

/**
 * Deterministic reduction (plan §11.5/§11.6): bounded head + tail with an
 * omitted-count marker, pytest failure evidence prepended when present.
 * Error results keep a longer tail (failure evidence lives at the end,
 * §11.7 — never over-trim failures).
 */
export function distillText(
  raw: string,
  opts: { commandClass: string; maxChars: number; isError: boolean },
): { text: string; visibleChars: number } {
  if (raw.length <= opts.maxChars) return { text: raw, visibleChars: raw.length };
  // Pytest evidence is the highest-value content: reserve up to 40% of the
  // budget for it; the head/tail body gets the rest, marker included. The
  // composed text is deterministically capped at maxChars.
  let evidence = "";
  if (opts.commandClass === "pytest") {
    const extra = pytestEvidence(raw);
    if (extra) {
      const evBudget = Math.floor(opts.maxChars * 0.4);
      evidence = extra.length > evBudget ? extra.slice(0, evBudget) : extra;
    }
  }
  const joinLen = evidence.length > 0 ? 2 : 0; // "\n\n" separator
  const markerLen = `\n\n… [${raw.length} chars omitted] …\n\n`.length;
  const budget = Math.max(0, opts.maxChars - joinLen - evidence.length - markerLen);
  const headRatio = opts.isError ? 0.15 : 0.4;
  const headChars = Math.floor(budget * headRatio);
  const tailChars = Math.max(0, budget - headChars);
  const head = raw.slice(0, headChars);
  const tail = raw.slice(Math.max(0, raw.length - tailChars));
  const omitted = raw.length - head.length - tail.length;
  const body = `${head}\n\n… [${omitted} chars omitted] …\n\n${tail}`;
  const text = evidence.length > 0 ? `${evidence}\n\n${body}` : body;
  const final = text.length > opts.maxChars ? text.slice(0, opts.maxChars) : text;
  return { text: final, visibleChars: final.length };
}

/** Build the deterministic [SECOND_BRAIN_RTD] replacement block (§11.6). */
export function buildRtdBlock(opts: {
  rawChars: number;
  visibleChars: number;
  sha256: string;
  artifactRef: string;
  commandClass: string;
  isError: boolean;
  evidence: string;
  lineCount: number;
}): string {
  const saved = Math.max(0, opts.rawChars - opts.visibleChars);
  return [
    "[SECOND_BRAIN_RTD]",
    `original_chars=${opts.rawChars}`,
    `visible_chars=${opts.visibleChars}`,
    `saved_chars=${saved}`,
    `lines=${opts.lineCount}`,
    `sha256=${opts.sha256}`,
    `artifact=${opts.artifactRef}`,
    `command=${opts.commandClass}`,
    `error_status=${opts.isError ? "true" : "false"}`,
    "truncated=true",
    "",
    opts.evidence,
    "",
    `Full exact result preserved at ${opts.artifactRef}.`,
    "Reopen (exact): python -m second_brain artifact expand <hash>  (or: second_brain artifact expand <hash>)",
    "Request it only if the missing region is material to the current decision.",
  ].join("\n");
}

/** Result of one RTD run on the substitution path. */
export interface RtdRunResult {
  /** rtd_shadow record (extended with P3-F fields) or null when not triggered. */
  record: RtdShadowRecord | null;
  /** Content replacement patch for Prime, or undefined (no substitution). */
  patch: { content: Array<{ type: "text"; text: string }> } | undefined;
}

export interface RtdSubstitutionOptions {
  session: string;
  tool: unknown;
  id: unknown;
  input: unknown;
  /** Prime tool_result content blocks (text-only eligible). */
  content: unknown[];
  isError: boolean;
  /** Shared precomputed measurement (one serialization, both metrics). */
  measurement: ContentMeasurement;
  threshold: number;
  cfg: RtdFileConfig;
  preserver: RtdPreserver;
}

/**
 * Orchestrate one RTD decision on the substitution path (plan §11):
 * eligibility -> size -> enabled gate -> PRESERVE RAW FIRST (store + verify)
 * -> deterministic block -> patch. Preservation failure returns NO patch
 * (original content stays) and records distilled=false. Never throws, never
 * stores raw content in telemetry.
 */
export async function runRtd(options: RtdSubstitutionOptions): Promise<RtdRunResult> {
  const eligibility = rtdEligibility(options.tool, options.input, options.cfg);
  const decision = shouldDistill(
    { toolName: options.tool, input: options.input },
    options.threshold,
    options.measurement,
    eligibility,
  );
  if (!decision.trigger) {
    return { record: null, patch: undefined };
  }
  // Phase C: resolve command class through the same host-tool
  // normalization used for eligibility, so a real ipython+%%bash pytest
  // call reports command=pytest in the RTD block, not the bash fallback.
  // Part A: use the same canonical-class resolver as eligibility (not a
  // bare first-token split), so e.g. a quoted absolute venv-python `-m
  // pytest` invocation still reports command=pytest (and therefore still
  // gets pytest failure-evidence extraction), not command=python.
  const commandClass =
    resolveCommandClass(resolveToolClass(options.tool, options.input).command ?? "") ?? "bash";
  const baseRecord = (distill?: RtdDistillDetail): RtdShadowRecord | null =>
    rtdShadowRecord({
      session: options.session,
      tool: options.tool,
      id: options.id,
      input: options.input,
      eligibility,
      measurement: options.measurement,
      threshold: options.threshold,
      active: options.cfg.enabled,
      distill,
    });

  if (!options.cfg.enabled) {
    return { record: baseRecord(), patch: undefined }; // shadow-only
  }

  // §11.4 PRESERVE RAW FIRST. Text-only (images/binary never distill, §11.8).
  const raw = textFromContent(options.content);
  if (raw === undefined) {
    return { record: baseRecord(), patch: undefined };
  }
  const preserved = await options.preserver.preserve(raw);
  if (preserved === null) {
    // Preservation failed: DO NOT DISTILL — original content unchanged.
    return {
      record: baseRecord({
        originalChars: raw.length,
        visibleChars: raw.length,
        savedChars: 0,
        artifactRef: "",
        commandClass,
        errorStatus: options.isError,
        distilled: false,
      }),
      patch: undefined,
    };
  }
  const verified = await options.preserver.verify(preserved.sha256, raw);
  if (!verified) {
    return {
      record: baseRecord({
        originalChars: raw.length,
        visibleChars: raw.length,
        savedChars: 0,
        artifactRef: "",
        commandClass,
        errorStatus: options.isError,
        distilled: false,
      }),
      patch: undefined,
    };
  }

  // Recoverability proven: build the deterministic block. visible/saved are
  // measured on the FULL model-visible block (metadata + evidence + pointer).
  const distilled = distillText(raw, {
    commandClass,
    maxChars: options.cfg.maxDistillChars,
    isError: options.isError,
  });
  const block = buildRtdBlock({
    rawChars: raw.length,
    visibleChars: distilled.visibleChars,
    sha256: preserved.sha256,
    artifactRef: preserved.handle,
    commandClass,
    isError: options.isError,
    evidence: distilled.text,
    lineCount: raw.split(/\r?\n/).length,
  });
  return {
    record: baseRecord({
      originalChars: raw.length,
      visibleChars: block.length,
      savedChars: Math.max(0, raw.length - block.length),
      artifactRef: preserved.handle,
      commandClass,
      errorStatus: options.isError,
      distilled: true,
    }),
    patch: { content: [{ type: "text", text: block }] },
  };
}
