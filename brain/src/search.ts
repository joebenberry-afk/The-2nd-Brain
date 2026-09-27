/** Full-text search over notes with BM25 ranking (faithful port of V3 SQLite FTS5). */
import { firstLine, restOfBody, type Note } from "./notes.ts";
import type { Project } from "./project.ts";
import { visibleTo } from "./project.ts";
import { cutToTokens } from "./util.ts";
import { findKit, loadKits } from "./kits.ts";

export const STOPWORDS = new Set([
  "the",
  "and",
  "what",
  "which",
  "how",
  "does",
  "did",
  "with",
  "for",
  "from",
  "this",
  "that",
  "these",
  "those",
  "into",
  "about",
  "please",
  "tell",
  "show",
  "give",
  "explain",
  "need",
  "want",
  "use",
  "using",
  "make",
  "can",
  "could",
  "would",
  "should",
  "will",
  "just",
  "only",
  "also",
  "any",
  "all",
  "some",
  "our",
  "your",
  "you",
  "are",
  "was",
  "were",
  "has",
  "have",
  "had",
  "not",
  "but",
  "why",
  "when",
  "where",
  "who",
  "there",
  "here",
  "then",
  "than",
  "them",
  "they",
  "its",
  "been",
  "being",
  "more",
  "most",
  "other",
  "such",
  "very",
  "reply",
  "answer",
  "line",
  "lines",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
  "by",
  "or",
  "an",
  "as",
  "is",
  "be",
  "go",
  "do",
  "if",
  "up",
  "out",
  "at",
  "to",
  "in",
  "on",
  "it",
  "he",
  "she",
  "we",
  "me",
]);

/** Extract tokens from text: 3+ alphanumeric, lowercased, no stopwords, duplicates removed. */
/** Lower-cased, accents removed (é → e), so queries and notes compare letter for letter. */
export function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

export function tokens(text: string): string[] {
  const found = fold(text).match(/[\p{L}\p{N}]{3,}/gu) ?? [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const token of found) {
    if (!STOPWORDS.has(token) && !seen.has(token)) {
      result.push(token);
      seen.add(token);
    }
  }
  return result;
}

export interface Hit {
  note: Note;
  score: number;
  matched: string[];
}

export interface RecallOptions {
  project: Project | null;
  all?: boolean;
  history?: boolean;
  limit?: number;
}

export const RELATIVE_FLOOR = 0.5;

/** FTS5 unicode61-style tokens: NFKD, marks removed, lower-cased runs of letters and digits. */
function scoreTokenize(text: string): string[] {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
}

/**
 * Tokenizing is most of a search's cost, and the same notes are searched again and again (the
 * OMP process lives for the session; one answer searches twice). Keyed by the full column text,
 * so an edited note is never served stale tokens; cleared wholesale when it grows large.
 */
const TOKEN_CACHE = new Map<string, string[][]>();
const TOKEN_CACHE_MAX = 20_000;

function columnTokens(...columns: string[]): string[][] {
  const key = columns.join("\u0000");
  let cols = TOKEN_CACHE.get(key);
  if (!cols) {
    if (TOKEN_CACHE.size >= TOKEN_CACHE_MAX) TOKEN_CACHE.clear();
    cols = columns.map(scoreTokenize);
    TOKEN_CACHE.set(key, cols);
  }
  return cols;
}

/** The scored query: its tokens and the 200 best candidates, before any filter. */
export interface Scored {
  q: string[];
  candidates: { note: Note; score: number; words: string }[];
}

/** BM25 over the whole corpus (IDF is corpus-wide, like the V3 index): the expensive half of recall. */
export function scoreQuery(notes: Note[], query: string): Scored {
  const q = tokens(query);
  if (!q.length) return { q, candidates: [] };

  // Build FTS columns for every note
  interface Row {
    note: Note;
    id: string;
    title: string;
    terms: string;
    body: string;
  }

  const rows: Row[] = notes.map((note) => ({
    note,
    id: note.id,
    title: firstLine(note),
    terms: [...note.tags, ...note.errors, note.kind].join(" "),
    body: restOfBody(note),
  }));

  // Tokenize for BM25 (unicode61 compatible: every length counts), once per row

  // counts[row][term][column] = tokens in that column starting with the term
  const D: number[] = [];
  const counts: number[][][] = [];
  const present = q.map(() => 0);
  for (const row of rows) {
    const cols = columnTokens(row.id, row.title, row.terms, row.body);
    D.push(cols.reduce((sum, t) => sum + t.length, 0));
    counts.push(
      q.map((term, ti) => {
        const perCol = cols.map((col) => col.filter((token) => token.startsWith(term)).length);
        if (perCol.some((c) => c > 0)) present[ti] = (present[ti] ?? 0) + 1;
        return perCol;
      }),
    );
  }

  const N = rows.length;
  const avgdl = D.length > 0 ? D.reduce((a, b) => a + b, 0) / D.length || 1 : 1;
  const idf = present.map((ni) => {
    const value = Math.log((N - ni + 0.5) / (ni + 0.5));
    return value <= 0 ? 1e-6 : value;
  });

  // BM25 scoring: k1=1.2, b=0.75, weights=[0, 5, 3, 1]
  const k1 = 1.2;
  const b = 0.75;
  const weights = [0, 5, 3, 1];

  interface Candidate {
    row: Row;
    score: number;
  }

  const candidates: Candidate[] = [];
  for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
    const row = rows[rowIdx] as Row;
    const d = D[rowIdx] ?? 0;
    let score = 0;
    q.forEach((_term, ti) => {
      const perCol = counts[rowIdx]?.[ti] ?? [];
      const fi = perCol.reduce((sum, c, ci) => sum + (weights[ci] ?? 0) * c, 0);
      if (fi > 0) score += (idf[ti] ?? 0) * ((fi * (k1 + 1)) / (fi + k1 * (1 - b + (b * d) / avgdl)));
    });
    if (score > 0) candidates.push({ row, score });
  }

  // Sort by score desc, id asc; keep first 200
  candidates.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    return a.row.id < b.row.id ? -1 : a.row.id > b.row.id ? 1 : 0;
  });
  // (V3's SQL took the top 200 before filtering; here visibility filters first, so a project's own
  // match is never crowded out by other projects' notes.)

  return { q, candidates: candidates.map(({ row, score }) => ({ note: row.note, score, words: `${row.title} ${row.terms} ${row.body}` })) };
}

/** The cheap half of recall: visibility, history, the match rule, the relative floor, the limit. */
function matchingHits(scored: Scored, opts: RecallOptions): Hit[] {
  const q = scored.q;
  const hits: Hit[] = [];
  for (const { note, score, words: text } of scored.candidates) {
    // Visibility filter
    if (!opts.all && !visibleTo(note, opts.project)) continue;

    // Retired filter
    if (!opts.history && note.retired) continue;

    // Match rule: need enough matched tokens
    const allText = fold(text);
    const words = allText.match(/[\p{L}\p{N}]{3,}/gu) ?? [];
    const matched: string[] = [];
    for (const term of q) {
      if (words.some((word) => word.startsWith(term))) {
        matched.push(term);
      }
    }

    const minMatched = q.length <= 2 ? 1 : 2;
    if (matched.length < minMatched) continue;

    hits.push({ note, score, matched });
  }

  // Relative floor
  if (hits.length > 0) {
    const topHit = hits[0];
    if (topHit) {
      const top = topHit.score;
      hits.splice(0, hits.length, ...hits.filter((h) => h.score >= RELATIVE_FLOOR * top));
    }
  }

  return hits;
}

export function filterHits(scored: Scored, opts: RecallOptions): Hit[] {
  return matchingHits(scored, opts).slice(0, Math.max(1, Math.min(10, opts.limit ?? 3)));
}

/** Recall over notes with BM25 ranking. */
export function recall(notes: Note[], query: string, opts: RecallOptions): Hit[] {
  return filterHits(scoreQuery(notes, query), opts);
}


/** Render a hit as a single line of at most `max` chars (default 240). */
export function renderHit(hit: Hit, max = 240): string {
  const { note } = hit;
  const idAndKind = `${note.id} [${note.kind}${note.tested ? ", tested" : ""}]`;
  const marker = note.retired ? ` (retired ${note.retired.slice(0, 10)}${note.replacedBy ? `, replaced by ${note.replacedBy}` : ""})` : "";
  const rest = restOfBody(note);
  const full = `${idAndKind} ${firstLine(note)}${marker}${rest ? ` — ${rest}` : ""}`;
  if (full.length <= max) return full;
  // Cut the text, never the id, the kind or the retired marker.
  const room = max - idAndKind.length - 1 - marker.length;
  const text = `${firstLine(note)}${rest ? ` — ${rest}` : ""}`;
  return room <= 1 ? `${idAndKind}${marker}`.slice(0, max) : `${idAndKind} ${text.slice(0, room - 1).trimEnd()}…${marker}`;
}

/** Longest first answer: most questions are settled by the top hit, so it gets room to say it. */
export const FIRST_HIT_CHARS = 600;
/** A note read in full by id is cut to this many tokens. */
export const FULL_NOTE_TOKENS = 600;

/** Hits as answer lines: the first up to FIRST_HIT_CHARS, the rest up to 240; "no match" when empty. */
export function renderHits(hits: Hit[]): string {
  if (!hits.length) return "no match";
  return hits.map((hit, i) => renderHit(hit, i === 0 ? FIRST_HIT_CHARS : 240)).join("\n");
}

export interface AnswerOptions extends RecallOptions {
  /** Explicit Brain home enables kit recall without consulting process-global state. */
  home?: string;
}

/** One call answers: exact ids, named kits, then scoped note search. */
export function answer(notes: Note[], query: string, opts: AnswerOptions): string {
  return answerWithHits(notes, query, opts).text;
}

/** Hit count measures results actually shown, not cross-project suggestions. */
export function answerWithHits(notes: Note[], query: string, opts: AnswerOptions): { text: string; hits: number } {
  const id = query.trim();
  const note = notes.find((n) => n.id === id);
  if (note) {
    if (!opts.all && !visibleTo(note, opts.project)) return { text: "no match", hits: 0 };
    const retiredMeta = note.retired ? `retired ${note.retired.slice(0, 10)}${note.replacedBy ? `, replaced by ${note.replacedBy}` : ""}` : "";
    const meta = [note.kind, note.tested ? "tested" : "", retiredMeta, note.evidence.length ? `evidence: ${note.evidence.join("; ")}` : ""];
    return { text: cutToTokens(`${note.id} [${meta.filter(Boolean).join(", ")}]\n${note.body}`, FULL_NOTE_TOKENS), hits: 1 };
  }
  if (opts.home && id) {
    const kit = findKit(loadKits(opts.home), id.replace(/^kit\s+/i, ""));
    if (kit) {
      const description = kit.description.replace(/\s+/g, " ").trim();
      return { text: `${kit.path}\n${description}`, hits: 1 };
    }
  }
  const scored = scoreQuery(notes, query);
  let hits = filterHits(scored, opts);
  if (!opts.history) {
    // Keep a better retired answer visible so obsolete advice is not silently replaced.
    const retired = filterHits(scored, { ...opts, history: true, limit: 10 }).find((h) => h.note.retired);
    if (retired && (!hits.length || retired.score > (hits[0]?.score ?? 0))) {
      const limit = Math.max(1, Math.min(10, opts.limit ?? 3));
      hits = [retired, ...hits.filter((h) => h.score >= RELATIVE_FLOOR * retired.score)].slice(0, limit);
    }
  }
  if (!hits.length && !opts.all) {
    const related = matchingHits(scored, { ...opts, all: true }).length
      || (!opts.history ? matchingHits(scored, { ...opts, all: true, history: true }).length : 0);
    if (related) return { text: `no match here; ${related} related in other projects (all: true)`, hits: 0 };
  }
  return { text: renderHits(hits), hits: hits.length };
}
