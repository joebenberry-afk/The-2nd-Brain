/** Full-text search over notes with BM25 ranking (faithful port of V3 SQLite FTS5). */
import { resolve } from "node:path";
import { changedEvidence, testedCurrent, expired, findNote, firstLine, GLOBAL, idQuery, restOfBody, staleEvidence, type Note } from "./notes.ts";
import type { Project } from "./project.ts";
import { visibleTo } from "./project.ts";
import { cutToTokens } from "./util.ts";
import { docAnswer } from "./docs.ts";

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

/** Lower-cased, accents removed (é → e), so queries and notes compare letter for letter. */
export function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Original terms first, then identifier parts and light suffix aliases. Dotted names remain atomic. */
export function tokens(text: string, dotted = false, expand = true): string[] {
  const found = fold(text).match(dotted ? DOTTED_OR_WORD : /[\p{L}\p{N}]{3,}/gu) ?? [];
  const seen = new Set<string>();
  const result: string[] = [];
  const add = (token: string) => {
    if (token.length >= 3 && !STOPWORDS.has(token) && !seen.has(token)) { result.push(token); seen.add(token); }
  };
  for (const token of found) add(token);
  if (expand) {
    for (const token of fold(text).match(/[\p{L}\p{N}]+(?:[_\-/\\][\p{L}\p{N}]+)+/gu) ?? []) add(token);
    // Split before folding: lowercasing first would erase camelCase boundaries.
    const parts = text.normalize("NFKD").replace(/\p{M}/gu, "").replace(/([a-z\d])([A-Z])/g, "$1 $2").replace(/([A-Z])([A-Z][a-z])/g, "$1 $2");
    for (const token of fold(parts).match(dotted ? DOTTED_OR_WORD : /[\p{L}\p{N}]{3,}/gu) ?? []) add(token);
    for (const token of [...result]) if (/^[a-z]+$/.test(token)) add(stem(token));
  }
  return result;
}

function stem(token: string): string {
  if (!/^[a-z]{5,}$/.test(token)) return token;
  const suffix = /(?:ing|ed|es|s)$/.exec(token);
  if (!suffix || /(?:ss|us|is)$/.test(token)) return token;
  let root = token.slice(0, -suffix[0].length);
  if (suffix[0] === "ing" || suffix[0] === "ed") root = root.replace(/([b-df-hj-np-tv-z])\1$/, "$1");
  return root.length >= 3 ? root : token;
}

const DOTTED_OR_WORD = /[\p{L}\p{N}]+(?:\.[\p{L}\p{N}]+)+|[\p{L}\p{N}]{3,}/gu;

export interface Hit {
  note: Note;
  score: number;
  matched: string[];
  stale?: boolean;
  changed?: boolean;
  tombstone?: boolean;
}

export interface RecallOptions {
  project: Project | null;
  all?: boolean;
  history?: boolean;
  limit?: number;
  /** Brain home for evidence lookup; stored note paths supply it when omitted. */
  home?: string;
}

export const RELATIVE_FLOOR = 0.5;

/** FTS5 unicode61-style tokens: NFKD, marks removed, lower-cased runs of letters and digits. */
function scoreTokenize(text: string): string[] {
  return fold(text).match(/[\p{L}\p{N}]+/gu) ?? [];
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

/** The scored query and corpus-wide term information, before visibility or history filters. */
export interface Scored {
  q: string[];
  information: Map<string, number>;
  candidates: { note: Note; score: number; matched: string[] }[];
}

const ALIAS_CACHE = new Map<string, Set<string>>();
function tokenAliases(text: string): Set<string> {
  let aliases = ALIAS_CACHE.get(text);
  if (!aliases) {
    if (ALIAS_CACHE.size >= TOKEN_CACHE_MAX) ALIAS_CACHE.clear();
    aliases = new Set(tokens(text));
    ALIAS_CACHE.set(text, aliases);
  }
  return aliases;
}

/** BM25 over the whole corpus (IDF is corpus-wide, like the V3 index): the expensive half of recall. */
export function scoreQuery(notes: Note[], query: string): Scored {
  // The match rule sees file names and versions whole: "LOOP.md" is not any note about a loop.
  const q = tokens(query, true, false);
  // A query of only short dotted tokens ("18.3.5", "fs.rm") still searches: its parts find
  // candidates, and the match rule still needs the whole dotted token.
  const words = tokens(query, false, false);
  const terms = words.length ? words : [...new Set(q.flatMap((t) => t.split(".")).filter(Boolean))];
  if (!terms.length) return { q, information: new Map(), candidates: [] };

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
  const present = terms.map(() => 0);
  for (const row of rows) {
    const cols = columnTokens(row.id, row.title, row.terms, row.body);
    D.push(cols.reduce((sum, t) => sum + t.length, 0));
    counts.push(
      terms.map((term, ti) => {
        const perCol = cols.map(col => col.filter(token => token.startsWith(term)).length);
        if (perCol.some((c) => c > 0)) present[ti] = (present[ti] ?? 0) + 1;
        return perCol;
      }),
    );
  }
  // Aliases only rescue terms absent from the exact corpus. Existing exact matches keep their
  // ranking and precision; identifier/suffix expansion never adds a runner-up to a known term.
  const aliasTerms = new Set(terms.filter((_term, ti) => present[ti] === 0));
  if (aliasTerms.size) {
    for (let ri = 0; ri < rows.length; ri++) {
      const row = rows[ri]!;
      const aliases = [row.id, row.title, row.terms, row.body].map(tokenAliases);
      terms.forEach((term, ti) => {
        if (!aliasTerms.has(term)) return;
        const root = stem(term);
        const perCol = aliases.map(col => col.has(root) ? 0.2 : 0);
        counts[ri]![ti] = perCol;
        if (perCol.some(count => count > 0)) present[ti] = (present[ti] ?? 0) + 1;
      });
    }
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
    terms.forEach((_term, ti) => {
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

  const matchedCandidates = candidates.map(({ row, score }) => {
    const text = fold(`${row.title} ${row.terms} ${row.body}`);
    const words = [...(text.match(DOTTED_OR_WORD) ?? []), ...(text.match(/[\p{L}\p{N}]{3,}/gu) ?? [])];
    const aliases = aliasTerms.size ? tokenAliases(`${row.title} ${row.terms} ${row.body}`) : undefined;
    return { note: row.note, score, matched: q.filter(term => words.some(word => word.startsWith(term)) || (aliasTerms.has(term) && aliases?.has(stem(term)))) };
  });
  // Smoothed IDF includes absent query terms: unknown subjects are not free matches.
  const information = new Map(q.map(term => [term, 1 + Math.log((N + 1) /
    (1 + matchedCandidates.filter(candidate => candidate.matched.includes(term)).length))]));
  return { q, information, candidates: matchedCandidates };
}

/** The cheap half of recall: visibility, history, the match rule, the relative floor, the limit. */
function matchingHits(scored: Scored, opts: RecallOptions): Hit[] {
  // The project's own name says nothing inside its scope: "Absolute Laya …" matched every Laya note.
  const scope = new Set(opts.project ? tokens(opts.project.id, false, false) : []);
  const q = scored.q.some((term) => !scope.has(term)) ? scored.q.filter((term) => !scope.has(term)) : scored.q;
  // Keep the two-term minimum, then require a meaningful share of the query information.
  // Short queries need half; longer prompts allow context around the actual question.
  const minMatched = q.length <= 2 ? 1 : 2;
  const requiredInformation = q.reduce((sum, term) => sum + scored.information.get(term)!, 0) * (q.length <= 2 ? 0.5 : 0.2);
  const hits: Hit[] = [];
  for (const { note, score, matched: allMatched } of scored.candidates) {
    // Visibility filter
    if (!opts.all && !visibleTo(note, opts.project)) continue;

    // Retired filter
    if (!opts.history && note.retired) continue;

    const matched = allMatched.filter(term => q.includes(term));
    if (matched.length < minMatched || matched.reduce((sum, term) => sum + scored.information.get(term)!, 0) < requiredInformation) continue;
    // A keyword list (5+ words) must be about the note's subject, its first line: two of its words
    // there, or half of a short headline. Matches only in the body ("notes", "review") were noise.
    if (q.length >= 5) {
      const head = firstLine(note);
      const headWords = [...(fold(head).match(DOTTED_OR_WORD) ?? []), ...(fold(head).match(/[\p{L}\p{N}]{3,}/gu) ?? [])];
      const inHead = matched.filter(term => headWords.some(word => word.startsWith(term))).length;
      if (inHead < 2 && inHead * 2 < tokens(head, true, false).length) continue;
    }

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

/**
 * A note past its `stale_after` is stale everywhere. Evidence resolves against this project's
 * checkout and the Brain home (capture cites its event logs there). A project note's evidence is
 * judged only when that checkout is known; another project's never: its relative paths belong to a
 * checkout we cannot see. Unknown is never "stale".
 */
export function staleHere(note: Note, project: Project | null, home: string | undefined): boolean {
  if (expired(note)) return true;
  const root = project?.root ?? undefined;
  if (note.project !== GLOBAL && (note.project !== project?.id || !root)) return false;
  return changedEvidence(note, [root, project?.docRoot, home].filter((r): r is string => !!r)) || staleEvidence(note, [root, project?.docRoot, home].filter((r): r is string => !!r));
}

export function changedHere(note: Note, project: Project | null, home?: string, after?: string): boolean {
  if (note.project !== GLOBAL && (note.project !== project?.id || !project.root)) return false;
  return changedEvidence(note, [project?.root, project?.docRoot, home].filter((root): root is string => !!root), after);
}

export function verifiedHere(note: Note, project: Project | null, home?: string): boolean {
  return testedCurrent(note) && !changedHere(note, project, home, note.testedAt);
}

function noteHome(note: Note, opts: RecallOptions): string | undefined {
  return opts.home ?? (note.path ? resolve(note.path, note.private ? "../../../.." : "../../..") : undefined);
}

export function filterHits(scored: Scored, opts: RecallOptions): Hit[] {
  const hits = matchingHits(scored, opts).slice(0, Math.max(1, Math.min(10, opts.limit ?? 3)));
  // Keep the BM25 shortlist (and its relevance floor), but lead with usable evidence.
  for (const hit of hits) {
    hit.stale = staleHere(hit.note, opts.project, noteHome(hit.note, opts));
    hit.changed = changedHere(hit.note, opts.project, noteHome(hit.note, opts));
  }
  return hits.sort((a, b) => Number(a.stale) - Number(b.stale));
}

/** Recall over notes with BM25 ranking. */
export function recall(notes: Note[], query: string, opts: RecallOptions): Hit[] {
  return filterHits(scoreQuery(notes, query), opts);
}


/** Render a hit as a single line of at most `max` chars (default 240). */
export function renderHit(hit: Hit, max = 240): string {
  const { note } = hit;
  const idAndKind = `${note.id} [${note.kind}${testedCurrent(note) ? ", tested" : ""}]`;
  const retired = note.retired ? ` (retired${hit.tombstone ? "" : " " + note.retired.slice(0, 10)}${note.replacedBy ? `, replaced by ${note.replacedBy}` : ""})` : "";
  const marker = retired + (hit.changed ? " (evidence changed)" : "") + (hit.stale && !hit.changed ? (expired(note) ? ` (stale since ${note.staleAfter!.slice(0, 10)})` : " (stale evidence)") : "");
  const title = firstLine(note);
  let rest = hit.tombstone ? "" : restOfBody(note);
  while (title && rest.startsWith(title) && (!rest[title.length] || /[\s:;,.—–-]/.test(rest[title.length]!))) {
    rest = rest.slice(title.length).replace(/^[\s:;,.—–-]+/, "");
  }
  const full = `${idAndKind} ${title}${marker}${rest ? ` — ${rest}` : ""}`;
  if (full.length <= max) return full;
  // Cut the text, never the id, the kind or the retired marker.
  const room = max - idAndKind.length - 1 - marker.length;
  const text = `${title}${rest ? ` — ${rest}` : ""}`;
  return room <= 1 ? `${idAndKind}${marker}`.slice(0, max) : `${idAndKind} ${text.slice(0, room - 1).trimEnd()}…${marker}`;
}

/** Longest first answer: most questions are settled by the top hit, so it gets room to say it. */
export const FIRST_HIT_CHARS = 600;
/** A note read explicitly is cut to this many tokens. */
export const FULL_NOTE_TOKENS = 600;
/**
 * Search summaries cap at three lines: 600 + 240 + 240 characters plus two newlines, about 271
 * tokens on the estimator. Explicit id reads and the card have their own, larger budgets.
 */
export const RECALL_BUDGET = 300;

const NO_MATCH = "no match; note it once you learn it";

/** Hits as answer lines: the first up to FIRST_HIT_CHARS, the rest up to 240. */
export function renderHits(hits: Hit[]): string {
  if (!hits.length) return NO_MATCH;
  return hits.map((hit, i) => renderHit(hit, i === 0 ? FIRST_HIT_CHARS : 240)).join("\n");
}

/** A note that reached the answer by a route other than lexical scoring, trust markers as for any hit. */
export function plainHit(note: Note, opts: RecallOptions & { home?: string }): Hit {
  return { note, score: 0, matched: [], stale: staleHere(note, opts.project, noteHome(note, opts)), changed: changedHere(note, opts.project, noteHome(note, opts)) };
}

export interface AnswerOptions extends RecallOptions {
  /** Explicit Brain home for evidence and registered document lookup. */
  home?: string;
  /** The CLI has flags rather than tool arguments. */
  tools?: boolean;
  /** Drop judged-out shown notes, without promoting unjudged runners-up. */
  exclude?: Set<string>;
  /** Skip the plan-doc fallback (its heading was judged irrelevant). */
  noDoc?: boolean;
}

/** One call answers: exact ids, then scoped note search. */
export function answer(notes: Note[], query: string, opts: AnswerOptions): string {
  return answerWithHits(notes, query, opts).text;
}

/** Hit count measures results actually shown, not cross-project suggestions. */
export function answerWithHits(notes: Note[], query: string, opts: AnswerOptions, scored?: Scored): { text: string; hits: number; ids: string[]; docExcerpt?: string; docAnchor?: string } {
  const id = idQuery(query);
  const note = findNote(notes, query);
  if (note) {
    // "note it once you learn it" for a note that exists invites a duplicate: say where it is.
    if (!opts.all && !visibleTo(note, opts.project)) return { text: `no match here; ${note.id} is in ${note.project} (${opts.tools === false ? "--all" : "all: true"})`, hits: 0, ids: [] };
    const retiredMeta = note.retired ? `retired ${note.retired.slice(0, 10)}${note.replacedBy ? `, replaced by ${note.replacedBy}` : ""}` : "";
    const tested = note.tested ? ["tested", note.testedBy && `by ${note.testedBy}`, note.testedAt?.slice(0, 10)].filter(Boolean).join(" ") : "";
    const staleAfter = note.staleAfter ? `${expired(note) ? "stale since" : "stale after"} ${note.staleAfter}` : "";
    const meta = [note.kind, tested, staleAfter, retiredMeta, note.evidence.length ? `evidence: ${note.evidence.join("; ")}` : ""];
    const trust = (note.tested && !testedCurrent(note) ? " (edited since tested)" : "") + (changedHere(note, opts.project, noteHome(note, opts)) ? " (evidence changed)" : "");
    return { text: cutToTokens(`${note.id} [${meta.filter(Boolean).join(", ")}]${trust}\n${note.body}`, FULL_NOTE_TOKENS), hits: 1, ids: [note.id] };
  }
  if (/^(?:n|mem)-[0-9a-f]{6,}$/i.test(id)) return { text: `no note ${id}`, hits: 0, ids: [] };
  // Search summaries stay within the three-line budget; explicit id reads above retain history.
  opts = { ...opts, limit: Math.max(1, Math.min(3, opts.limit ?? 3)) };
  scored ??= scoreQuery(notes, query);
  let hits = filterHits(scored, opts);
  if (!opts.history) {
    const best = filterHits(scored, { ...opts, history: true, limit: 10 }).sort((a, b) => b.score - a.score).find((h) => h.note.retired);
    if (best && hits.every((hit) => best.score > hit.score)) {
      const seen = new Set<string>([best.note.id]);
      let replacement: Note | undefined = best.note;
      while (replacement?.retired) {
        const id: string | undefined = replacement.replacedBy;
        if (!id || seen.has(id)) { replacement = undefined; break; }
        seen.add(id);
        replacement = notes.find((n) => n.id === id && (opts.all || visibleTo(n, opts.project)));
      }
      if (replacement) {
        const next = { note: replacement, score: 0, matched: [], stale: staleHere(replacement, opts.project, noteHome(replacement, opts)) };
        const tombstone = { ...best, tombstone: true, note: { ...best.note, replacedBy: replacement.id } };
        hits = [next, tombstone, ...hits.filter((h) => h.note.id !== replacement.id)].slice(0, opts.limit);
      } else {
        hits = [best, ...hits.filter((h) => h.score >= RELATIVE_FLOOR * best.score)]
          .sort((a, b) => Number(a.stale) - Number(b.stale)).slice(0, opts.limit);
      }
    }
  }
  if (opts.exclude) hits = hits.filter(hit => !opts.exclude?.has(hit.note.id));
  if (!hits.length && opts.home && opts.project?.root && !opts.noDoc) {
    const heading = docAnswer(opts.home, opts.project, query);
    if (heading) return { text: heading.text, hits: 1, ids: ["doc:" + heading.path], ...(heading.excerpt ? { docExcerpt: heading.excerpt, docAnchor: heading.anchor } : {}) };
  }
  if (!hits.length && !opts.all) {
    const related = matchingHits(scored, { ...opts, all: true }).filter(hit => !opts.exclude || !visibleTo(hit.note, opts.project)).length
      || (!opts.history ? matchingHits(scored, { ...opts, all: true, history: true }).filter(hit => !opts.exclude || !visibleTo(hit.note, opts.project)).length : 0);
    if (related) return { text: `no match here; ${related} related in other projects (${opts.tools === false ? "--all" : "all: true"})`, hits: 0, ids: [] };
  }
  return { text: renderHits(hits), hits: hits.length, ids: hits.map(hit => hit.note.id) };
}
