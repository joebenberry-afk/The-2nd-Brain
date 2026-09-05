/**
 * Phase 14 — controlled Prime recall hook (DEFAULT OFF).
 *
 * When enabled (env `SECOND_BRAIN_RECALL` in {1,true,yes}, case-insensitive),
 * the extension runs ONE bounded Brain recall on `before_agent_start` for
 * substantial, non-trivial user prompts and injects a compact Brain Brief
 * into the systemPrompt. Default OFF = zero behavior change for every
 * existing session.
 *
 * This module is split into:
 *  - pure, side-effect-free decision/format functions (`shouldAttemptRecall`,
 *    `buildBrainBrief`, `parseRecallRows`, `loadRecallGateConfig`) —
 *    vitest-able with no I/O;
 *  - `runBrainRecall` — the one bounded out-of-process spawn (node:child_process
 *    execFile) with env cleanup and a hard timeout; every failure resolves to
 *    [] (fail silent, no injection).
 *
 * Config (env only, read at call time like src/config.ts):
 *   SECOND_BRAIN_RECALL            "1" | "true" | "yes" (case-insensitive) enables
 *   SECOND_BRAIN_RECALL_MAX_ROWS   default 3
 *   SECOND_BRAIN_RECALL_MIN_CHARS  default 40
 *   SECOND_BRAIN_RECALL_TIMEOUT_MS default 5000
 *
 * CLI contract (verified against the repo CLI, cli.py `cmd_memory` "search"):
 *   <home>/.venv/Scripts/python.exe -m second_brain memory search "<term>"
 *   with cwd=<home>, SECOND_BRAIN_HOME=<home>, PYTHONHOME/PYTHONPATH removed.
 *   rc=0 always for a search; stdout is the documented TEXT format
 *   `{memory_id}  [{status}/{evidence_grade}] {title}` per row (no --json mode
 *   exists for memory search). `parseRecallRows` accepts a JSON array as a
 *   forward-compatible extension (future --json) and falls back to the text
 *   format. The CLI text rows carry title/status/evidence_grade/memory_id but
 *   NOT summary/project_id — those fields are optional in `buildBrainBrief`
 *   (documented limitation; the JSON path can supply them later).
 */
import { execFile } from "node:child_process";
import { join } from "node:path";

export const RECALL_DEFAULT_MAX_ROWS = 3;
export const RECALL_DEFAULT_MIN_CHARS = 40;
export const RECALL_DEFAULT_TIMEOUT_MS = 5000;
export const RECALL_ENABLE_VALUES = new Set(["1", "true", "yes"]);

export interface RecallGateConfig {
  enabled: boolean;
  maxRows: number;
  minChars: number;
  timeoutMs: number;
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === null) return fallback;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return fallback; // whole-string integer only
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

/** Read recall config from the environment at call time (config.ts style). */
export function loadRecallGateConfig(
  env: Record<string, string | undefined> = process.env,
): RecallGateConfig {
  return {
    enabled: RECALL_ENABLE_VALUES.has((env.SECOND_BRAIN_RECALL ?? "").trim().toLowerCase()),
    maxRows: parsePositiveInt(env.SECOND_BRAIN_RECALL_MAX_ROWS, RECALL_DEFAULT_MAX_ROWS),
    minChars: parsePositiveInt(env.SECOND_BRAIN_RECALL_MIN_CHARS, RECALL_DEFAULT_MIN_CHARS),
    timeoutMs: parsePositiveInt(env.SECOND_BRAIN_RECALL_TIMEOUT_MS, RECALL_DEFAULT_TIMEOUT_MS),
  };
}

/** Trivial greetings/acknowledgements — never worth a recall query. */
const GREETING_RE = /^(hi|hello|hey|yo|thanks|thank you|thx|ok|okay|yes|no|ping|good morning|good afternoon|good evening|bye)\b/i;

/** Continuation/CLI-ish starts — not a fresh substantial request. */
const CONTINUATION_RE = /^(\/|!|`|brainctl|prime-agent|\.\/|\.\.|git |npm |uv |pip |python |cd |continue|resume|proceed|redo|retry|pick up where|fix the (last|previous))/i;

/**
 * Pure gate: should the extension attempt a recall for this user text?
 * Returns false when disabled, text missing/blank, text shorter than
 * `minChars`, fewer than 8 words, a greeting/acknowledgement, or a
 * continuation/CLI-ish start. Deterministic and cheap (no LLM, no I/O).
 */
export function shouldAttemptRecall(userText: string | undefined, cfg: RecallGateConfig): boolean {
  if (!cfg.enabled) return false;
  if (userText === undefined || userText === null) return false;
  const text = userText.trim();
  if (text.length === 0) return false;
  if (text.length < cfg.minChars) return false;
  if (text.split(/\s+/).length < 8) return false;
  if (GREETING_RE.test(text)) return false;
  if (CONTINUATION_RE.test(text)) return false;
  return true;
}

/** Normalized brief row (fields optional except title). */
export interface BriefRow {
  title: string;
  summary?: string;
  status?: string;
  grade?: string;
  project?: string;
  id?: string;
}

export const BRIEF_HEADER = "## Brain Brief (retrieved)";
export const BRIEF_MAX_WORDS = 1000;

/** current / superseded / uncertain label from a status string. */
export function statusLabel(status: string | undefined): string | undefined {
  if (status === undefined || status === null) return undefined;
  const s = status.toLowerCase();
  if (s === "current") return "current";
  if (s === "superseded") return "superseded";
  return "uncertain";
}

function toBriefRow(raw: unknown): BriefRow | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const r = raw as Record<string, unknown>;
  const title = typeof r.title === "string" && r.title.trim() !== "" ? r.title.trim() : undefined;
  if (title === undefined) return undefined; // title is required
  const summary = typeof r.summary === "string" && r.summary.trim() !== "" ? r.summary.trim() : undefined;
  const status = typeof r.status === "string" && r.status.trim() !== "" ? r.status.trim() : undefined;
  const grade =
    (typeof r.evidence_grade === "string" && r.evidence_grade.trim() !== "" ? r.evidence_grade.trim() : undefined) ??
    (typeof r.grade === "string" && r.grade.trim() !== "" ? r.grade.trim() : undefined);
  const project =
    (typeof r.project_id === "string" && r.project_id.trim() !== "" ? r.project_id.trim() : undefined) ??
    (typeof r.project === "string" && r.project.trim() !== "" ? r.project.trim() : undefined);
  const id =
    (typeof r.memory_id === "string" && r.memory_id.trim() !== "" ? r.memory_id.trim() : undefined) ??
    (typeof r.id === "string" && r.id.trim() !== "" ? r.id.trim() : undefined);
  return { title, summary, status, grade, project, id };
}

/**
 * Build a compact markdown Brain Brief from recall rows: header + one bullet
 * per row (title, current/superseded/uncertain label when status present,
 * one-line summary, grade, project, id). Caps: `maxRows` rows (default 3)
 * and `maxWords` total words (default 1000 — rows that would exceed the cap
 * are dropped). Rows without a usable title are skipped. Returns undefined
 * when no valid row remains.
 */
export function buildBrainBrief(
  rows: unknown[] | undefined | null,
  maxRows = RECALL_DEFAULT_MAX_ROWS,
  maxWords = BRIEF_MAX_WORDS,
): string | undefined {
  if (!Array.isArray(rows)) return undefined;
  const lines: string[] = [];
  let words = 0;
  for (const raw of rows) {
    if (lines.length >= maxRows) break;
    const row = toBriefRow(raw);
    if (row === undefined) continue;
    const label = statusLabel(row.status);
    const parts = [
      `**${row.title}**`,
      label !== undefined ? `(${label})` : undefined,
      row.summary !== undefined ? `— ${row.summary}` : undefined,
      row.grade !== undefined ? `grade=${row.grade}` : undefined,
      row.project !== undefined ? `project=${row.project}` : undefined,
      row.id !== undefined ? `\`${row.id}\`` : undefined,
    ].filter((p): p is string => p !== undefined);
    const line = `- ${parts.join(" ")}`;
    const lineWords = line.split(/\s+/).length;
    if (words + lineWords > maxWords) break;
    lines.push(line);
    words += lineWords;
  }
  if (lines.length === 0) return undefined;
  return [BRIEF_HEADER, ...lines].join("\n");
}

/** Documented CLI text row: `memory_id  [status/evidence_grade] title`. */
const TEXT_ROW_RE = /^(\S+)\s{2,}\[([^/\]]+)\/([^/\]]+)\]\s+(.+)$/;

/**
 * Parse the Brain CLI recall/search stdout defensively. Accepts a JSON array
 * (forward-compatible with a future --json mode); otherwise parses the
 * documented text format. Returns [] on garbage/empty output — never throws.
 */
export function parseRecallRows(stdout: string | undefined | null): unknown[] {
  if (stdout === undefined || stdout === null) return [];
  const text = stdout.trim();
  if (text === "") return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    // not JSON — fall through to the documented text format
  }
  const rows: unknown[] = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed === "No matching memories.") continue;
    if (trimmed.startsWith("Conflicting prior evidence:")) continue;
    const m = TEXT_ROW_RE.exec(trimmed);
    if (m === null) continue;
    rows.push({ memory_id: m[1], status: m[2], evidence_grade: m[3], title: m[4] });
  }
  return rows;
}

export interface RunRecallOptions {
  /** Brain home (also used to locate the repo venv python). */
  home: string;
  /** User prompt text to search for. */
  query: string;
  cfg: RecallGateConfig;
  /** Python executable override (tests). Default: <home>/.venv/Scripts/python.exe. */
  python?: string;
  /** Env override (tests). Default: process.env with PYTHONHOME/PYTHONPATH removed. */
  env?: Record<string, string | undefined>;
}

/**
 * Run ONE bounded Brain recall out-of-process: `<python> -m second_brain
 * memory search "<query>"` with cwd=home, SECOND_BRAIN_HOME=home, and
 * PYTHONHOME/PYTHONPATH removed (repo env gotcha; see AGENTS.md). Hard
 * timeout via cfg.timeoutMs; any failure (missing python, nonzero rc,
 * timeout, parse garbage) resolves to [] — fail silent, no injection.
 */
export function runBrainRecall(options: RunRecallOptions): Promise<unknown[]> {
  const python = options.python ?? process.env.SECOND_BRAIN_PYTHON ?? join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...(options.env ?? process.env) };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  return new Promise((resolve) => {
    execFile(
      python,
      ["-m", "second_brain", "memory", "search", options.query],
      {
        cwd: options.home,
        env,
        timeout: options.cfg.timeoutMs,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve([]);
          return;
        }
        resolve(parseRecallRows(stdout));
      },
    );
  });
}
