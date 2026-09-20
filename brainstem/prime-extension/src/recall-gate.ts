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
 *   SECOND_BRAIN_RECALL_MAX_TERMS  default 4 (content terms per recall query)
 *
 * `buildRecallQuery` turns the prompt into that bounded keyword query. The CLI
 * tokenizes its query, keeps up to eight terms by IDF and requires at least half
 * of them to occur in one memory, so passing the raw prompt matches nothing.
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
export const RECALL_DEFAULT_MAX_TERMS = 4;
export const RECALL_ENABLE_VALUES = new Set(["1", "true", "yes"]);

export interface RecallGateConfig {
  enabled: boolean;
  maxRows: number;
  minChars: number;
  timeoutMs: number;
  /** Distinct content terms the recall query may carry (bounds retrieval). */
  maxQueryTerms: number;
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
    maxQueryTerms: parsePositiveInt(
      env.SECOND_BRAIN_RECALL_MAX_TERMS,
      RECALL_DEFAULT_MAX_TERMS,
    ),
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

/**
 * Words that carry no retrieval signal for a bounded recall query. The Brain
 * CLI drops its own subset too; this list keeps the out-of-process query short
 * so the CLI's "at least half the terms must match one memory" rule (see
 * semantic._query_plan msm=0.5) can actually be satisfied by a stored memory.
 */
const RECALL_STOPWORDS: Record<string, true> = {
  the: true, a: true, an: true, and: true, or: true, but: true, if: true, then: true,
  than: true, that: true, this: true, these: true, those: true, there: true, here: true,
  is: true, are: true, was: true, were: true, be: true, been: true, being: true, am: true,
  do: true, does: true, did: true, done: true, have: true, has: true, had: true, having: true,
  will: true, would: true, can: true, could: true, should: true, shall: true, may: true,
  might: true, must: true, i: true, me: true, my: true, we: true, our: true, you: true,
  your: true, it: true, its: true, they: true, them: true, their: true, to: true, of: true,
  in: true, on: true, at: true, by: true, for: true, with: true, without: true, from: true,
  into: true, over: true, under: true, about: true, as: true, so: true, not: true, no: true,
  nor: true, too: true, very: true, just: true, also: true, only: true, again: true,
  more: true, most: true, some: true, any: true, all: true, both: true, each: true, few: true,
  other: true, such: true, same: true, own: true, because: true, while: true, when: true,
  where: true, which: true, who: true, what: true, why: true, how: true, please: true,
  help: true, need: true, needs: true, want: true, wants: true, make: true, makes: true,
  get: true, gets: true, let: true, lets: true, use: true, uses: true, using: true,
  used: true, run: true, runs: true, work: true, works: true, thing: true, things: true,
  really: true, still: true, even: true, well: true, much: true, many: true, like: true,
  back: true, out: true, up: true, down: true, off: true, now: true, new: true, dont: true,
  doesnt: true, cant: true,
};

const RECALL_FENCE_RE = /```[\s\S]*?```/g;
const RECALL_INLINE_CODE_RE = /`[^`]*`/g;
const RECALL_URL_RE = /\bhttps?:\/\/\S+/gi;
/** Same token shape the Brain CLI keeps: ASCII alphanumeric runs of 3+ after casefolding. */
const RECALL_TOKEN_RE = /[a-z0-9]{3,}/g;

/**
 * Build the bounded keyword query for one recall attempt.
 *
 * The CLI must not receive the whole prompt: it tokenizes the query, keeps up
 * to eight terms by IDF and requires at least half of them to occur in a single
 * memory, so a prose prompt matches nothing. This selects a few distinct
 * content terms instead (code fences, inline code and URLs are dropped, and
 * stopwords and duplicated tokens are skipped). Returns undefined when fewer
 * than two usable terms remain — the CLI would return no rows for those too,
 * and "no query" is the honest outcome.
 */
export function buildRecallQuery(userText: string, cfg: RecallGateConfig): string | undefined {
  if (typeof userText !== "string") return undefined;
  const withoutNoise = userText
    .replace(RECALL_FENCE_RE, " ")
    .replace(RECALL_INLINE_CODE_RE, " ")
    .replace(RECALL_URL_RE, " ")
    .toLowerCase();
  const limit = Math.max(1, cfg.maxQueryTerms);
  const selected: string[] = [];
  const seen = new Set<string>();
  for (const token of withoutNoise.match(RECALL_TOKEN_RE) ?? []) {
    if (RECALL_STOPWORDS[token] === true || seen.has(token)) continue;
    seen.add(token);
    selected.push(token);
    if (selected.length >= limit) break;
  }
  if (selected.length < 2) return undefined;
  return selected.join(" ");
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
