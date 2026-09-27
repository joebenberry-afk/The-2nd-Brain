/** Full-text search over notes with BM25 ranking (faithful port of V3 SQLite FTS5). */
import { headline, type Note } from "./notes.ts";
import type { Project } from "./project.ts";
import { visibleTo } from "./project.ts";

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
export function tokens(text: string): string[] {
  const found = text.toLowerCase().match(/[a-z0-9]{3,}/g) ?? [];
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

/** Recall over notes with BM25 ranking. */
export function recall(notes: Note[], query: string, opts: RecallOptions): Hit[] {
  const q = tokens(query);
  if (!q.length) return [];

  const limit = Math.max(1, Math.min(10, opts.limit ?? 3));

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
    title: headline(note),
    terms: [...note.tags, ...note.errors, note.kind].join(" "),
    body: note.body.split("\n").slice(1).join("\n"),
  }));

  // Tokenize for BM25 (unicode61 compatible: every length counts), once per row
  const scoreTokenize = (text: string): string[] => {
    const normalized = text.normalize("NFKD").replace(/\p{M}/gu, "");
    return normalized.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  };

  // counts[row][term][column] = tokens in that column starting with the term
  const D: number[] = [];
  const counts: number[][][] = [];
  const present = q.map(() => 0);
  for (const row of rows) {
    const cols = [row.id, row.title, row.terms, row.body].map(scoreTokenize);
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
  candidates.splice(200);

  // Apply filters
  const hits: Hit[] = [];
  for (const candidate of candidates) {
    const { row, score } = candidate;
    // Visibility filter
    if (!opts.all && !visibleTo(row.note, opts.project)) continue;

    // Retired filter
    if (!opts.history && row.note.retired) continue;

    // Match rule: need enough matched tokens
    const allText = `${row.title} ${row.terms} ${row.body}`.toLowerCase();
    const words = allText.match(/[a-z0-9]{3,}/g) ?? [];
    const matched: string[] = [];
    for (const term of q) {
      if (words.some((word) => word.startsWith(term))) {
        matched.push(term);
      }
    }

    const minMatched = q.length <= 2 ? 1 : 2;
    if (matched.length < minMatched) continue;

    hits.push({ note: row.note, score, matched });
  }

  // Relative floor
  if (hits.length > 0) {
    const topHit = hits[0];
    if (topHit) {
      const top = topHit.score;
      hits.splice(0, hits.length, ...hits.filter((h) => h.score >= RELATIVE_FLOOR * top));
    }
  }

  return hits.slice(0, limit);
}

/** Render a hit as a single line ≤ 240 chars. */
export function renderHit(hit: Hit): string {
  const { note } = hit;
  const h = headline(note);
  const tested = note.tested ? ", tested" : "";
  const kindLabel = `[${note.kind}${tested}]`;

  // Build the body excerpt
  const bodyLines = note.body.split("\n");
  const rest = bodyLines.slice(1).join("\n").trim();

  // Build the retired marker if needed
  let retiredMarker = "";
  if (note.retired) {
    const retiredDate = note.retired.slice(0, 10);
    const replacedBy = note.replacedBy ? `, replaced by ${note.replacedBy}` : "";
    retiredMarker = ` (retired ${retiredDate}${replacedBy})`;
  }

  // Assemble the parts
  const idAndKind = `${note.id} ${kindLabel}`;
  const headlineAndRetired = rest
    ? `${h}${retiredMarker} — ${rest}`
    : `${h}${retiredMarker}`;
  const fullLine = `${idAndKind} ${headlineAndRetired}`;

  // Cut to 240 chars, being careful not to cut the retired marker
  if (fullLine.length <= 240) return fullLine;

  const head = idAndKind + " " + h + retiredMarker;
  const remainder = rest ? ` — ${rest}` : "";

  if ((head + remainder).length <= 240) return head + remainder;

  const remaining = 240 - head.length - 1;
  if (remaining <= 0) {
    return head.slice(0, 237) + "…";
  }

  if (!remainder) {
    return head;
  }

  const cut = remainder.slice(0, remaining).trimEnd();
  return head + cut + "…";
}
