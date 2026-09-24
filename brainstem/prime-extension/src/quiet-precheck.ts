/**
 * In-host quiet fast path (V3 S2, QuietPath): a CONSERVATIVE necessary-condition
 * precheck for the per-prompt Python memory phases.
 *
 * `before_agent_start` currently spawns a Python process per prompt for capsule
 * ensure + hot-context render + the AutoInject decision. On a turn where the
 * Brain cannot contribute a model-visible message, that spawn buys nothing. This
 * module answers, IN HOST and read-only, "could the Python pipeline possibly
 * produce a message for this prompt?" and returns:
 *
 *   - `run`  — anything unresolved, unreadable, unknown, non-ASCII, a memory-id
 *              reference, or any lexical evidence that a memory could contribute.
 *   - `skip` — ONLY when every rule the Python pipeline uses to decide "this row
 *              contributes" is provably unsatisfied, and the capsule/render half
 *              is provably model-invisible (echo objective, no decisions, no open
 *              questions, no VMem objects).
 *
 * Duty of care is one-directional: a false `skip` loses memory the user needed
 * (unacceptable); a false `run` only costs the latency this path is trying to
 * save. Every rule below therefore errs toward `run`, and every measurement used
 * for a "cannot contribute" conclusion is an UNDER-estimate of the Python
 * quantity it mirrors.
 *
 * Mirrors of Python rules (src/second_brain/semantic.py, autoinject.py,
 * working_set.py, capsule_runtime.py, vmem.py):
 *
 *  - `_query_candidates` tokenization and `_QUERY_STOPWORD_TOKENS` (data copy,
 *    drift-tested by tests/test_quiet_precheck_parity.py);
 *  - the retrieval/contribution text is the capsule objective after `ensure_capsule`
 *    (`autoinject._retrieval_query_text`): this prompt stripped and cut to
 *    `capsule_runtime.MAX_TEXT_CHARS` (512). That holds only while the session's
 *    capsule is ABSENT or exactly the shape `working_set._load_capsule` accepts:
 *    an existing capsule Python rejects makes `ensure_capsule` fail and AutoInject
 *    falls back to the FULL task text, so an unrecognized capsule answers `run`;
 *  - tier-0 `_EXACT_REF_PATTERN` (an exact id reference contributes by construction);
 *  - `semantic._plan_with_stats` / `QueryMatchPlan` corpus statistics;
 *  - `semantic.match_evidence`'s three contribution rules: a specific plan term
 *    confirmed by the row's headline, two near-unique plan terms coinciding
 *    anywhere in the row, or a headline confirmation when no plan term can
 *    discriminate. Matching is `str.casefold()` token prefixes, which JS cannot
 *    reproduce for non-ASCII text (`"ß"` folds to `"ss"`), so a RETRIEVED row
 *    whose text is not ASCII answers `run` instead of being judged;
 *  - `capsule_runtime.ensure_capsule` + `vmem.VMemStore.render_hot_context` plus the
 *    host's echo suppression (`activeStateMessage`): the render of a capsule with
 *    no decisions/questions and no VMem objects is exactly `[SECOND_BRAIN_HOT_CONTEXT]`
 *    plus `Objective: <this prompt>`, which the host drops as an echo.
 *
 * No prompt text, memory id or term ever leaves this module: the result carries
 * counts and a fixed reason token only (constitution/security-boundaries.md).
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

/** Env kill switch: set to 0/false/no/off/current to disable the fast path. */
export const QUIET_PRECHECK_ENV = "SECOND_BRAIN_QUIET_PRECHECK";
export const QUIET_PRECHECK_OFF_VALUES = new Set(["0", "false", "no", "off", "current"]);

/** `capsule_runtime.MAX_TEXT_CHARS` — the bounded capsule objective length. */
export const QUIET_ECHO_MAX_CHARS = 512;
/** `semantic._SPECIFIC_TERM_DF_RATIO` / `_SPECIFIC_TERM_MIN_DF`. */
export const QUIET_SPECIFIC_TERM_DF_RATIO = 0.1;
export const QUIET_SPECIFIC_TERM_MIN_DF = 2;
/** `semantic._UNIQUE_TERM_MAX_DF`. */
export const QUIET_UNIQUE_TERM_MAX_DF = 2;
/** `semantic._UNIQUE_TERM_MIN_HITS` (rule 2 needs two such terms on one row). */
export const QUIET_UNIQUE_TERM_MIN_HITS = 2;
/**
 * Retrieval-emulation bound: rows examined before the check answers `run`. A
 * truncated row set cannot prove that no retrievable row contributes. 256 rows
 * spans any corpus this size (the live corpus has 116 memories) while keeping
 * the per-row scan bounded.
 */
export const QUIET_RETRIEVAL_ROW_LIMIT = 256;
/**
 * `semantic.query_match_plan`'s default `msm` — the share of the plan's terms a
 * retrieved row must contain (`_query_term_hits >= required`).
 */
export const QUIET_MSM_REQUIRED_RATIO = 0.5;
/** `semantic._UBIQUITOUS_TERM_DF_RATIO`. */
export const QUIET_UBIQUITOUS_TERM_DF_RATIO = 0.5;

/**
 * `semantic._QUERY_STOPWORD_TOKENS` — the exact token set Python drops from a
 * query. GENERATED from the Python module; `tests/test_quiet_precheck_parity.py`
 * asserts the two sets are equal, because drift is asymmetric: a token Python
 * drops while TS keeps only widens the candidate set (conservative), but a token
 * TS drops while Python keeps could hide a contributing term.
 */
// >>> STOPWORD DATA (generated)
export const QUIET_STOPWORD_TOKENS: Readonly<Record<string, true>> = Object.assign(
  Object.create(null) as Record<string, true>,
  Object.fromEntries(
    (
      "able about above absolutely according accordingly across actually after afterwards again " +
      "against all and any anyhow anything anyway anyways anywhere apparently appreciate " +
      "appropriate are aren aside away became because become becomes becoming been before being " +
      "believe below between both but can cannot could couldn did didn does doesn doing don down " +
      "during each few for from further had hadn has hasn have haven having her here hers herself " +
      "him himself his how into isn its itself let more most mustn myself nor not off once only " +
      "other ought our ours ourselves out over own same shan she should shouldn some such than that " +
      "the their theirs them themselves then there these they this those through too under until " +
      "very was wasn were weren what when where which while who whom why will with won would wouldn " +
      "you your yours yourself yourselves"
    )
      .split(/\s+/u)
      .filter((token) => token.length >= 3)
      .map((token) => [token, true as const]),
  ),
);
// <<< STOPWORD DATA

/** `working_set.SESSION_ID_RE` — a session id that can be a path component. */
const SESSION_ID_RE = /^[A-Za-z0-9._-]{1,64}$/u;
/**
 * `working_set.TASK_MODES` / `RISK_LEVELS`. Deliberately a SUBSET mirror: a mode
 * or risk Python added while this module did not would make a canonical capsule
 * look unreadable here, which only costs a spawn (`run`). Adding a value Python
 * does NOT have would let a capsule Python rejects look canonical — so these
 * sets are only ever extended together with the Python tuples.
 */
const CAPSULE_TASK_MODES: Readonly<Record<string, true>> = {
  MICRO: true,
  STANDARD: true,
  DEEP: true,
  DEBUG: true,
  RESEARCH: true,
  REVIEW: true,
  ADVISOR: true,
  EXECUTOR: true,
  HANDOFF: true,
};
const CAPSULE_RISK_LEVELS: Readonly<Record<string, true>> = {
  LOW: true,
  MEDIUM: true,
  HIGH: true,
  CRITICAL: true,
};
/** `working_set.CAPSULE_LIST_FIELDS` / `CAPSULE_FIELDS`. */
const CAPSULE_LIST_FIELDS = [
  "constraints",
  "confirmed_facts",
  "current_hypotheses",
  "decisions_this_session",
  "files_touched",
  "open_questions",
  "brain_refs",
  "artifact_refs",
] as const;
const CAPSULE_FIELDS = [
  "objective",
  "task_mode",
  "risk",
  ...CAPSULE_LIST_FIELDS,
  "verification",
  "next_action",
  "updated_at",
] as const;
/** `hybrid_retrieval._EXACT_REF_PATTERN`. */
const EXACT_REF_RE = /^(?:mem-|obj-|ref:)?[0-9a-f]{8,32}$/iu;
/** Python's `_query_candidates` declines any non-ASCII text outright. */
const NON_ASCII_RE = /[^\x00-\x7F]/u;
const TOKEN_RE = /[a-z0-9]{3,}/gu;
const WHITESPACE_RE = /\s+/u;
/** `autoinject._WH_WORD`: the closed class whose presence can form a request sentence. */
const WH_WORD_RE = /\b(?:what|which|when|where|who|whom|whose|why|how)\b/iu;
/** `semantic._plan_with_stats` default term budget (`query_match_plan`'s `k`). */
export const QUIET_PLAN_TERM_LIMIT = 8;
/** `autoinject._MAX_NARROW_TERMS`: the narrowed retry keeps this many plan terms. */
export const QUIET_NARROW_TERM_LIMIT = 4;

export type QuietDecision = "skip" | "run";

/** Fixed reason tokens (never prompt text). */
export type QuietReason =
  | "no_evidence"
  | "empty_prompt"
  | "echo_boundary"
  | "non_ascii_prompt"
  | "exact_ref"
  | "no_candidates"
  | "invalid_session"
  | "db_unavailable"
  | "schema_unknown"
  | "empty_index"
  | "no_vocab_terms"
  | "unique_terms"
  | "specific_headline"
  | "ubiquitous_headline"
  | "non_ascii_row"
  | "retrieval_unbounded"
  | "db_error"
  | "capsule_content"
  | "capsule_unreadable"
  | "vmem_objects"
  | "vmem_unreadable";

export interface QuietPrecheckDetail {
  /** Candidate tokens the prompt yields after the stopword filter. */
  candidates: number;
  /** Candidates present in the FTS vocabulary (the plan's candidate pool). */
  vocab_terms: number;
  /** Candidates matching at most `QUIET_UNIQUE_TERM_MAX_DF` documents. */
  unique_terms: number;
  /** Candidates with a title/summary hit, and the ubiquitous subset. */
  headline_terms: number;
  ubiquitous_headline_terms: number;
  /** Capsule state: missing | echo_only | content | unreadable. */
  capsule: "missing" | "echo_only" | "content" | "unreadable" | "unknown";
  /** VMem objects in the session store (-1 unknown). */
  vmem_objects: number;
  total_documents: number;
}

export interface QuietPrecheckResult {
  decision: QuietDecision;
  reason: QuietReason;
  detail: QuietPrecheckDetail;
}

export interface QuietPrecheckOptions {
  home: string;
  session: string;
  /** The raw `before_agent_start` prompt. */
  prompt: string;
}

export function loadQuietPrecheckEnabled(
  env: Record<string, string | undefined> = process.env,
): boolean {
  const raw = (env[QUIET_PRECHECK_ENV] ?? "").trim().toLowerCase();
  return !QUIET_PRECHECK_OFF_VALUES.has(raw);
}

/**
 * The retrieval/contribution text the Python pipeline will use, or `undefined`
 * when no text can be proven: the capsule objective after `ensure_capsule` is the
 * prompt stripped and cut to 512 chars, and the host's echo suppression only
 * holds when that cut leaves no whitespace at the boundary (see module doc).
 */
export function quietQueryText(prompt: string): string | undefined {
  if (typeof prompt !== "string") return undefined;
  const trimmed = prompt.trim();
  if (trimmed.length === 0) return undefined;
  const bounded = trimmed.slice(0, QUIET_ECHO_MAX_CHARS);
  if (bounded !== bounded.trimEnd()) return undefined;
  if (NON_ASCII_RE.test(bounded)) return undefined;
  return bounded;
}

/** `semantic._query_candidates`: casefold, ASCII-only, `[a-z0-9]{3,}`, deduped. */
export function queryCandidates(text: string): string[] {
  if (typeof text !== "string" || NON_ASCII_RE.test(text)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  // Python's casefold and JS's toLowerCase agree on ASCII, which is all this
  // function is allowed to see (non-ASCII input returns [] above).
  for (const match of text.toLowerCase().matchAll(TOKEN_RE)) {
    const token = match[0];
    if (QUIET_STOPWORD_TOKENS[token] === true) continue;
    if (seen.has(token)) continue;
    seen.add(token);
    out.push(token);
  }
  return out;
}

/** A memory id reference anywhere in the text (broader than Python's whole-query test). */
function looksLikeExactRef(text: string): boolean {
  if (EXACT_REF_RE.test(text)) return true;
  return text.split(WHITESPACE_RE).some((token) => EXACT_REF_RE.test(token));
}

/** Both directories a session's state can live in (`working_set.session_dir`). */
function sessionDirs(home: string, session: string): string[] {
  const root = join(home, "state", "sessions");
  const hashed = createHash("sha256").update(session, "utf8").digest("hex");
  return [join(root, session), join(root, hashed)];
}

/**
 * `working_set._load_capsule` + `_validate_capsule_fields`: the exact shape
 * Python accepts for an EXISTING capsule. A capsule this rejects makes
 * `ensure_capsule` fail, and AutoInject then falls back to the FULL task text as
 * its retrieval text (`autoinject._retrieval_query_text`) instead of the
 * 512-char objective this module mirrors — so an unrecognized shape must answer
 * `run`, never `skip`.
 */
function isCanonicalCapsule(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const capsule = value as Record<string, unknown>;
  for (const field of CAPSULE_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(capsule, field)) return false;
  }
  const objective = capsule["objective"];
  if (typeof objective !== "string" || objective.trim().length === 0) return false;
  const taskMode = capsule["task_mode"];
  if (typeof taskMode !== "string" || CAPSULE_TASK_MODES[taskMode] !== true) return false;
  const risk = capsule["risk"];
  if (typeof risk !== "string" || CAPSULE_RISK_LEVELS[risk] !== true) return false;
  for (const field of CAPSULE_LIST_FIELDS) {
    const list = capsule[field];
    if (!Array.isArray(list) || list.some((item) => typeof item !== "string")) return false;
  }
  const verification = capsule["verification"];
  if (verification === null || typeof verification !== "object" || Array.isArray(verification)) {
    return false;
  }
  for (const item of Object.values(verification as Record<string, unknown>)) {
    if (item === null) continue;
    const kind = typeof item;
    if (kind !== "string" && kind !== "number" && kind !== "boolean") return false;
  }
  if (typeof capsule["next_action"] !== "string") return false;
  const updatedAt = capsule["updated_at"];
  if (typeof updatedAt !== "string" || updatedAt.length === 0) return false;
  return true;
}

/** Capsule state for the render rule: only an echo-only capsule is invisible. */
function capsuleState(home: string, session: string): QuietPrecheckDetail["capsule"] {
  for (const dir of sessionDirs(home, session)) {
    const file = join(dir, "active-state.json");
    if (!existsSync(file)) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(readFileSync(file, "utf8"));
    } catch {
      return "unreadable";
    }
    if (!isCanonicalCapsule(parsed)) return "unreadable";
    const capsule = parsed; // narrowed by isCanonicalCapsule
    const decisions = capsule["decisions_this_session"] as unknown[];
    const questions = capsule["open_questions"] as unknown[];
    if (decisions.length > 0 || questions.length > 0) return "content";
    return "echo_only";
  }
  return "missing";
}

/** VMem objects in the session's own ledger database (any residency state). */
function vmemObjectCount(home: string, session: string): number | null {
  for (const dir of sessionDirs(home, session)) {
    const file = join(dir, "ledger.sqlite");
    if (!existsSync(file)) continue;
    let db: DatabaseSync | undefined;
    try {
      db = new DatabaseSync(file, { readOnly: true });
      const table = db
        .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_vmem'")
        .get();
      if (table === undefined) return 0; // vmem never wrote to this session
      const count = db.prepare("SELECT COUNT(*) AS n FROM session_vmem").get() as
        | { n?: number }
        | undefined; // sqlite COUNT row
      return Number(count?.n ?? 0);
    } catch {
      return null;
    } finally {
      try {
        db?.close();
      } catch {
        // fail-open: a close failure cannot change the decision
      }
    }
  }
  return 0;
}

interface CountRow {
  n?: number;
}

/**
 * Open the corpus read-only for the duration of ONE precheck.
 *
 * Deliberately NOT cached across calls: on Windows an open handle makes
 * `os.replace`/`unlink` of `brain.sqlite` fail with a sharing violation, and this
 * repository's own restore flow replaces the LIVE database file (D22/D24). The
 * first statement on a fresh connection costs ~3 ms (pager + schema load on the
 * live 5 MB database) against a Python spawn of 50-370 ms, so correctness wins.
 */
function openReadOnly(file: string): DatabaseSync | null {
  try {
    return new DatabaseSync(file, { readOnly: true });
  } catch {
    return null;
  }
}

/**
 * The conservative necessary-condition precheck. Never throws; any unreadable or
 * unrecognized input resolves to `run`.
 */
export function precheckQuiet(options: QuietPrecheckOptions): QuietPrecheckResult {
  const detail: QuietPrecheckDetail = {
    candidates: 0,
    vocab_terms: 0,
    unique_terms: 0,
    headline_terms: 0,
    ubiquitous_headline_terms: 0,
    capsule: "unknown",
    vmem_objects: -1,
    total_documents: 0,
  };
  const run = (reason: QuietReason): QuietPrecheckResult => ({ decision: "run", reason, detail });
  try {
    const { home, session } = options;
    if (typeof home !== "string" || home.length === 0 || !SESSION_ID_RE.test(session)) {
      return run("invalid_session");
    }
    const queryText = quietQueryText(options.prompt);
    if (queryText === undefined) {
      const raw = typeof options.prompt === "string" ? options.prompt.trim() : "";
      if (raw.length === 0) return run("empty_prompt");
      if (NON_ASCII_RE.test(raw.slice(0, QUIET_ECHO_MAX_CHARS))) return run("non_ascii_prompt");
      return run("echo_boundary");
    }
    if (looksLikeExactRef(queryText)) return run("exact_ref");
    const candidates = queryCandidates(queryText);
    detail.candidates = candidates.length;
    if (candidates.length === 0) return run("no_candidates");

    // Cheap in-host file checks first: a session with capsule content or VMem
    // objects cannot skip, and answering that without opening the corpus keeps
    // those turns free of the ~3 ms first-statement cost.
    detail.capsule = capsuleState(home, session);
    if (detail.capsule === "content") return run("capsule_content");
    if (detail.capsule === "unreadable") return run("capsule_unreadable");
    const vmem = vmemObjectCount(home, session);
    if (vmem === null) return run("vmem_unreadable");
    detail.vmem_objects = vmem;
    if (vmem > 0) return run("vmem_objects");

    const dbFile = join(home, "db", "brain.sqlite");
    if (!existsSync(dbFile)) return run("db_unavailable");
    const db = openReadOnly(dbFile);
    if (db === null) return run("db_unavailable");
    try {
      const schemaRow = db
        .prepare(
          "SELECT COUNT(*) AS n FROM sqlite_master WHERE name IN ('memories','memory_fts','memory_fts_vocab')",
        )
        .get() as CountRow | undefined; // sqlite COUNT row
      if (Number(schemaRow?.n ?? 0) < 3) return run("schema_unknown");
      const totalRow = db.prepare("SELECT COUNT(*) AS n FROM memories").get() as
        | CountRow
        | undefined; // sqlite COUNT row
      const indexedRow = db.prepare("SELECT COUNT(*) AS n FROM memory_fts").get() as
        | CountRow
        | undefined; // sqlite COUNT row
      const total = Number(totalRow?.n ?? 0);
      const indexed = Number(indexedRow?.n ?? 0);
      detail.total_documents = total;
      // An absent or unbuilt index routes retrieval to the linear fallback,
      // whose plan carries no terms at all — and `match_evidence` then treats
      // every retrieved row as contributing.
      if (total <= 0 || indexed <= 0) return run("empty_index");

      // `_plan_with_stats`: candidates are filtered to the FTS vocabulary, and an
      // empty pool yields a termless plan (again "everything contributes").
      const frequencies = new Map<string, number>();
      const placeholders = candidates.map(() => "?").join(",");
      const vocabRows = db
        .prepare(`SELECT term, doc FROM memory_fts_vocab WHERE term IN (${placeholders})`)
        .all(...candidates) as Array<{ term?: string; doc?: number }>; // fts5vocab rows
      for (const row of vocabRows) frequencies.set(String(row.term), Number(row.doc ?? 0));
      const terms =
        candidates.length === 1 ? candidates : candidates.filter((term) => frequencies.has(term));
      detail.vocab_terms = terms.length;
      if (terms.length === 0) return run("no_vocab_terms");

      const countStatement = db.prepare(
        "SELECT COUNT(*) AS n FROM memory_fts WHERE memory_fts MATCH ?",
      );
      const specificThreshold = Math.max(
        QUIET_SPECIFIC_TERM_MIN_DF,
        Math.ceil(QUIET_SPECIFIC_TERM_DF_RATIO * total),
      );
      const ubiquitousThreshold = QUIET_UBIQUITOUS_TERM_DF_RATIO * total;
      // Exact prefix document count — the same measurement Python's
      // `_prefix_document_frequencies` makes, and never larger than the summed
      // breadth Python falls back to (`document_frequency`). The exact-token
      // vocabulary count is a LOWER bound for it, so a term whose exact count
      // already exceeds a threshold needs no FTS count at all.
      const prefixDf = new Map<string, number>();
      const countPrefix = (term: string): number => {
        const cached = prefixDf.get(term);
        if (cached !== undefined) return cached;
        const row = countStatement.get(`"${term}"*`) as CountRow | undefined; // sqlite COUNT row
        const value = Math.min(total, Number(row?.n ?? 0));
        prefixDf.set(term, value);
        return value;
      };
      // Python's `is_specific`/`is_unique`/`is_ubiquitous` with `prefixDf`, which
      // is at most Python's own document frequency: over-classifying a term as
      // specific/unique can only make this check answer `run`.
      const isSpecific = (term: string): boolean =>
        (frequencies.get(term) ?? 0) <= specificThreshold &&
        countPrefix(term) <= specificThreshold;
      const isUnique = (term: string): boolean =>
        (frequencies.get(term) ?? 0) <= QUIET_UNIQUE_TERM_MAX_DF &&
        countPrefix(term) <= QUIET_UNIQUE_TERM_MAX_DF;
      const isUbiquitous = (term: string): boolean =>
        (frequencies.get(term) ?? 0) > ubiquitousThreshold ||
        countPrefix(term) > ubiquitousThreshold;
      // `_plan_with_stats` term selection, mirrored exactly: IDF over the exact
      // vocabulary counts, ties broken by position in the vocabulary-filtered
      // candidate order, capped to `k` (the contribution plan is built by
      // `query_match_plan(home, text)` with its own defaults, never by config).
      const positions = new Map<string, number>(terms.map((term, index) => [term, index]));
      const inverseFrequency = (term: string): number =>
        Math.log((total + 1) / ((frequencies.get(term) ?? 0) + 1));
      const selected = [...terms]
        .sort(
          (left, right) =>
            inverseFrequency(right) - inverseFrequency(left) ||
            (positions.get(left) ?? 0) - (positions.get(right) ?? 0),
        )
        .slice(0, QUIET_PLAN_TERM_LIMIT);
      // `_focused_query_text` needs a request sentence, and a request sentence
      // needs a question mark or a wh-word — so when the text has neither, the
      // focused retry does not exist and the plan of every attempt is known.
      const focusPossible = WH_WORD_RE.test(queryText) || queryText.includes("?");
      // `match_evidence`'s two per-row rules, evaluated against one attempt.
      const contributionReason = (
        hits: string[],
        headlineHits: string[],
      ): QuietReason | undefined => {
        if (headlineHits.some(isSpecific)) return "specific_headline";
        if (hits.filter(isUnique).length >= QUIET_UNIQUE_TERM_MIN_HITS) return "unique_terms";
        return undefined;
      };
      const requiredFull = Math.max(1, Math.ceil(QUIET_MSM_REQUIRED_RATIO * selected.length));
      const narrowedTerms = selected.slice(0, QUIET_NARROW_TERM_LIMIT);
      const requiredNarrow = Math.max(
        1,
        Math.ceil(QUIET_MSM_REQUIRED_RATIO * narrowedTerms.length),
      );
      const allUbiquitous = (planTerms: string[]): boolean =>
        planTerms.length > 0 && planTerms.every(isUbiquitous);
      // `_term_hit_tokens`: plan terms with a token-prefix hit. Every row this
      // loop examines is proven ASCII first (see the `non_ascii_row` guard
      // below), so the token test is the whole rule.
      const hitsIn = (planTerms: string[], tokens: string[]): string[] =>
        planTerms.filter((term) => tokens.some((token) => token.startsWith(term)));
      const tokenize = (text: string): string[] => text.toLowerCase().match(TOKEN_RE) ?? [];

      // ---- retrieval-stage emulation ----------------------------------------
      // `autoinject.retrieve_contributing` -> `retrieve_rows` ->
      // `HybridCascadeRetriever.retrieve` -> `semantic.search_memories` ->
      // `_search_fts`: rows matching an attempt's plan expression under the
      // Phase-7 filters (`evidence_grade != 'REJECTED'`, archived/superseded
      // excluded), then `_query_term_hits(row) >= msm_required`. Each attempt
      // Python makes is mirrored with its own term set and requirement:
      //
      //   * the full retrieval text — the plan mirrored above, exactly;
      //   * `_narrowed_query_text`'s top four terms, when the plan is longer;
      //   * the focused retry, whose plan is an unknown SUBSET of the retrieval
      //     text's candidates (`_focused_query_text` keeps only the request
      //     sentences), so it is emulated with the WIDEST possible term set —
      //     every ORIGINAL candidate, requirement 1 — which can only add rows
      //     and rule firings. `_plan_with_stats` drops a vocabulary-absent term
      //     only when a query has MORE than one candidate, so a focused sentence
      //     reduced to one term ("What is kubernet?" -> "kubernetes" in the
      //     corpus) still searches: the unfiltered candidate set is required, not
      //     the vocabulary-filtered plan.
      //
      // Everything Python applies after retrieval (indexed-file-hash freshness,
      // history partition, dedupe, ranking budget, lane authority, the score
      // gate, `_valid_candidates`) only removes rows, so ignoring it is safe.
      interface RetrievalRow {
        title?: string;
        summary?: string;
        body?: string;
      }
      interface RetrievalAttempt {
        planTerms: string[];
        required: number;
        /** The focused retry's plan is unknown: evaluate the rules loosely. */
        loose: boolean;
      }
      const attempts: RetrievalAttempt[] = [
        { planTerms: selected, required: requiredFull, loose: false },
      ];
      if (narrowedTerms.length < selected.length) {
        attempts.push({ planTerms: narrowedTerms, required: requiredNarrow, loose: false });
      }
      if (focusPossible) {
        attempts.push({ planTerms: candidates, required: 1, loose: true });
      }
      const retrievalStatement = db.prepare(
        "SELECT m.title AS title, m.summary AS summary, f.body AS body FROM memory_fts f " +
          "JOIN memories m ON m.memory_id = f.memory_id " +
          "WHERE memory_fts MATCH ? AND m.evidence_grade != 'REJECTED' " +
          "AND m.status NOT IN ('archived', 'superseded') LIMIT ?",
      );
      const matchedHeadline = new Set<string>();
      const ubiquitousHeadline = new Set<string>();
      const uniqueMatched = new Set<string>();
      for (const attempt of attempts) {
        const expression = `(${attempt.planTerms.map((term) => `"${term}"*`).join(" OR ")})`;
        const rows = retrievalStatement.all(expression, QUIET_RETRIEVAL_ROW_LIMIT + 1) as
          RetrievalRow[]; // memory_fts joined with memories
        if (rows.length > QUIET_RETRIEVAL_ROW_LIMIT) return run("retrieval_unbounded");
        for (const row of rows) {
          const headline = `${row.title ?? ""} ${row.summary ?? ""}`;
          const haystack = `${headline} ${row.body ?? ""}`;
          // Python matches on `str.casefold()` text, and full case folding is
          // not `toLowerCase()`: ``"Straße".casefold()`` is ``"strasse"``, so a
          // non-ASCII row can carry an ASCII headline/prefix hit this module
          // cannot reproduce. Such a row's contribution cannot be disproved
          // here, so the whole check answers `run` (this row was retrieved,
          // i.e. it already matched the plan's term evidence).
          if (NON_ASCII_RE.test(haystack)) return run("non_ascii_row");
          const headlineTokens = tokenize(headline);
          const haystackTokens = tokenize(haystack);
          const hits = hitsIn(attempt.planTerms, haystackTokens);
          if (hits.length < attempt.required) continue;
          const headlineHits = hitsIn(attempt.planTerms, headlineTokens);
          for (const term of headlineHits) {
            matchedHeadline.add(term);
            if (isUbiquitous(term)) ubiquitousHeadline.add(term);
          }
          for (const term of hits) {
            if (isUnique(term)) uniqueMatched.add(term);
          }
          const reason = contributionReason(hits, headlineHits);
          if (reason !== undefined) return run(reason);
          // Rule 3 (`no discrimination left`): every plan term ubiquitous, with a
          // headline confirmation among them. For the focused retry, whose plan is
          // unknown, any ubiquitous candidate confirmed by the headline keeps that
          // reachable.
          const ubiquitousRule = attempt.loose
            ? headlineHits.some(isUbiquitous)
            : allUbiquitous(attempt.planTerms) && headlineHits.length > 0;
          if (ubiquitousRule) {
            detail.ubiquitous_headline_terms = 1;
            return run("ubiquitous_headline");
          }
        }
      }
      detail.headline_terms = matchedHeadline.size;
      detail.unique_terms = uniqueMatched.size;
      detail.ubiquitous_headline_terms += ubiquitousHeadline.size;


    } catch {
      return run("db_error");
    } finally {
      try {
        db.close();
      } catch {
        // fail-open: a close failure cannot change the decision
      }
    }

    return { decision: "skip", reason: "no_evidence", detail };
  } catch {
    // Any unexpected failure is `run`: the fast path must never be able to lose
    // memory it did not understand.
    return run("db_error");
  }
}
