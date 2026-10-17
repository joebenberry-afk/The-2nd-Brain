/** Read-only maintenance suggestions; semantic failures leave lexical candidates intact. */
import { JUDGE_THRESHOLD, judgeText, type PairJudge } from "./judge.ts";
import { GLOBAL, type Note } from "./notes.ts";
import { tagList } from "./util.ts";
import { inferTags, loadProjects, projectById, visibleTo, type Project } from "./project.ts";
import { tokens } from "./search.ts";
import { noteUsage, usageWindow } from "./telemetry.ts";
import type { ToraScorer } from "./tora.ts";

export interface SimilarPair {
  id: string;
  a: Note;
  b: Note;
  score: number;
  /** How it became a candidate: whole-body overlap, an explicit note-id reference, shared rare terms, or Tora's nearest-note list at write time. */
  via: "lexical" | "reference" | "entity" | "tora";
}

/** Never the same note, a replacement chain, two unrelated projects, or globals sharing no tag. */
function comparable(a: Note, b: Note): boolean {
  if (a.id === b.id || a.replaces === b.id || a.replacedBy === b.id || b.replaces === a.id || b.replacedBy === a.id || (a.project !== b.project && a.project !== GLOBAL && b.project !== GLOBAL)) return false;
  return !(a.project === GLOBAL && b.project === GLOBAL && a.tags.some(tag => tag !== "brief") && b.tags.some(tag => tag !== "brief")
    && !a.tags.some(tag => tag !== "brief" && b.tags.includes(tag)));
}

/** Older first, regardless of input order: a suggestion retires it in favour of b. */
function ordered(a: Note, b: Note, score: number, via: SimilarPair["via"]): SimilarPair {
  const ageOrder = Date.parse(a.at) - Date.parse(b.at);
  if (ageOrder > 0 || (ageOrder === 0 && a.id > b.id)) [a, b] = [b, a];
  return { id: JSON.stringify([a.id, b.id]), a, b, score, via };
}

function overlap(left: Set<string>, right: Set<string>): { shared: number; score: number } {
  let shared = 0;
  for (const word of left) if (right.has(word)) shared++;
  return { shared, score: shared / (left.size + right.size - shared) };
}

function pair(a: Note, b: Note, left: Set<string>, right: Set<string>): SimilarPair | undefined {
  if (!comparable(a, b)) return undefined;
  const { shared, score } = overlap(left, right);
  return shared < 2 || score < 0.2 ? undefined : ordered(a, b, score, "lexical");
}

const bySimilarity = (a: SimilarPair, b: SimilarPair) => b.score - a.score || a.id.localeCompare(b.id);

/** Bound on pairs the two non-lexical sources add: advisory candidates must not flood the report. */
const EXTRA_CAP = 50;
/** A term is a rare entity when at most this many active notes contain it; two shared make a candidate. */
const RARE_DF = 3;
const NOTE_ID = /\b(?:n-[0-9a-f]{10}|mem-[0-9a-f]{12})\b/gi;

/**
 * Low-overlap candidates the lexical threshold cannot see: a note naming another note's id (a
 * correction), and same-scope notes sharing at least two rare terms. Lexical pairs are not repeated.
 */
function extraPairs(active: Note[], words: Set<string>[], seen: Set<string>): SimilarPair[] {
  const index = new Map<string, number>();
  active.forEach((note, i) => index.set(note.id.toLowerCase(), i));
  const found = new Map<string, { i: number; j: number; via: SimilarPair["via"]; rank: number }>();
  const add = (i: number, j: number, via: SimilarPair["via"], rank: number) => {
    const [lo, hi] = i < j ? [i, j] : [j, i];
    const key = lo + ":" + hi;
    const old = found.get(key);
    if (!old || (via === "reference" && old.via !== "reference")) found.set(key, { i: lo, j: hi, via, rank: Math.max(rank, old?.rank ?? 0) });
  };
  active.forEach((note, i) => {
    for (const match of note.body.matchAll(NOTE_ID)) {
      const j = index.get(match[0].toLowerCase());
      if (j !== undefined && j !== i) add(i, j, "reference", Infinity);
    }
  });
  const holders = new Map<string, number[]>();
  words.forEach((set, i) => {
    for (const word of set) {
      const list = holders.get(word);
      if (list) list.push(i);
      else holders.set(word, [i]);
    }
  });
  const shared = new Map<string, number>();
  for (const [word, list] of holders) {
    if (word.length < 4 || list.length < 2 || list.length > RARE_DF) continue;
    for (let x = 0; x < list.length; x++) for (let y = x + 1; y < list.length; y++) {
      const key = list[x]! + ":" + list[y]!;
      shared.set(key, (shared.get(key) ?? 0) + 1);
    }
  }
  for (const [key, count] of shared) {
    const [i, j] = key.split(":").map(Number) as [number, number];
    if (count >= 2 && active[i]!.project === active[j]!.project) add(i, j, "entity", count);
  }
  const result: { pair: SimilarPair; rank: number }[] = [];
  for (const { i, j, via, rank } of found.values()) {
    const a = active[i]!, b = active[j]!;
    if (!comparable(a, b)) continue;
    const candidate = ordered(a, b, overlap(words[i]!, words[j]!).score, via);
    if (!seen.has(candidate.id)) result.push({ pair: candidate, rank });
  }
  return result.sort((x, y) => y.rank - x.rank || bySimilarity(x.pair, y.pair)).slice(0, EXTRA_CAP).map(({ pair }) => pair);
}

/**
 * Bounded shortlist, never comparing retired notes or two unrelated projects: lexical pairs
 * (Jaccard ≥ 0.2, never lowered) plus at most EXTRA_CAP reference/rare-entity candidates.
 */
export function similarPairs(notes: Note[], limit: number): SimilarPair[] {
  const active = notes.filter(note => !note.retired);
  const words = active.map(note => new Set(tokens(note.body)));
  const pairs: SimilarPair[] = [];
  for (let i = 0; i < active.length; i++) {
    for (let j = i + 1; j < active.length; j++) {
      const candidate = pair(active[i]!, active[j]!, words[i]!, words[j]!);
      if (candidate) pairs.push(candidate);
    }
  }
  pairs.push(...extraPairs(active, words, new Set(pairs.map(p => p.id))));
  return pairs.sort(bySimilarity).slice(0, Math.max(0, limit));
}

function valid(scores: { same: number; contradicts: number } | undefined): boolean {
  return !!scores && [scores.same, scores.contradicts].every(p => Number.isFinite(p) && p >= 0 && p <= 1);
}

/** Active global notes whose scoping tags match no registered or inferred project tag: invisible to scoped recall. */
export function orphanGlobals(home: string, notes: Note[], project: Project): Note[] {
  const known = new Set(project.tags);
  for (const entry of Object.values(loadProjects(home))) {
    const declared = Array.isArray(entry.tags) ? entry.tags.filter((tag): tag is string => typeof tag === "string") : [];
    const paths = Array.isArray(entry.paths) ? entry.paths.filter((path): path is string => typeof path === "string") : [];
    for (const tag of tagList([...declared, ...paths.flatMap(inferTags)])) known.add(tag);
  }
  return notes.filter(note => !note.retired && note.project === GLOBAL && note.tags.some(tag => tag !== "brief") && !note.tags.some(tag => tag !== "brief" && known.has(tag)));
}

export interface TidyReport {
  duplicates: SimilarPair[];
  contradictions: SimilarPair[];
  /** Candidates no judge classified: all of them without a judge, private ones, and those past the budget. */
  similar: SimilarPair[];
  unused: Note[];
  unusedWindow: string;
  /** Public pairs sent to the judge, and public pairs left unreviewed by the budget. */
  reviewed: number;
  unreviewed: number;
  orphans: Note[];
}

export const PAIR_BUDGET = 20;

export async function tidyReport(home: string, notes: Note[], project: Project, opts: { judge?: PairJudge; all?: boolean; days?: number; pairBudget?: number } = {}): Promise<TidyReport> {
  const days = opts.days ?? 30;
  const active = notes.filter(note => !note.retired && (opts.all || visibleTo(note, project)));
  const usage = noteUsage(home, days);
  const since = Date.now() - days * 86_400_000;
  // Telemetry keeps about two weeks: a note's absence from rows that start later says nothing about
  // the days before them. "Unused" holds for the window they cover; with no rows it holds for none.
  const unused = usage.from === undefined ? [] : active.filter(note => Date.parse(note.at) < since && !usage.notes.has(note.id));
  // Notes already costing context (recalled, opened, carded, fired) come before unused repetition.
  const exposure = (note: Note) => { const u = usage.notes.get(note.id); return u ? u.recalled + u.opened + u.carded + u.fired : 0; };
  const pairExposure = ({ a, b }: SimilarPair) => exposure(a) + exposure(b);
  const pairs = similarPairs(active, Infinity).filter(({ a, b }) => {
    if (a.project === b.project) return true;
    const local = a.project === GLOBAL ? b : a;
    const global = a.project === GLOBAL ? a : b;
    return visibleTo(global, opts.all ? projectById(home, local.project, home) : project);
  }).sort((x, y) => pairExposure(y) - pairExposure(x) || bySimilarity(x, y));
  const orphans = orphanGlobals(home, notes, project);
  const report: TidyReport = { duplicates: [], contradictions: [], similar: pairs, unused, unusedWindow: usageWindow(usage, days), reviewed: 0, unreviewed: pairs.filter(({ a, b }) => !a.private && !b.private).length, orphans };
  if (!opts.judge) return report;
  const budget = Math.max(0, Math.floor(opts.pairBudget ?? PAIR_BUDGET));
  const publicPairs = pairs.filter(({ a, b }) => !a.private && !b.private).slice(0, budget);
  try {
    if (!publicPairs.length) return report;
    const scores = await opts.judge(publicPairs.map(({ id, a, b }) => ({ id, a: judgeText(a), b: judgeText(b) })));
    if (!scores || publicPairs.some(pair => !valid(scores.get(pair.id)))) return report;
    const judged = new Set(publicPairs.map(pair => pair.id));
    report.similar = pairs.filter(pair => !judged.has(pair.id));
    report.reviewed = publicPairs.length;
    report.unreviewed -= publicPairs.length;
    for (const pair of publicPairs) {
      const score = scores.get(pair.id)!;
      if (score.contradicts >= JUDGE_THRESHOLD) report.contradictions.push(pair);
      else if (score.same >= JUDGE_THRESHOLD) report.duplicates.push(pair);
    }
  } catch { /* local maintenance remains useful when the judge fails */ }
  return report;
}

/**
 * A write-time hint cannot stop or undo the write, including on file/judge errors. Tora's three
 * nearest notes join the lexical three in the same Jev request: on 10 real replacements they held a
 * contradiction the lexical shortlist missed, and on 40 ordinary writes they raised no hint.
 */
export async function noteHint(home: string, note: Note, notes: Note[], judge?: PairJudge, tora?: ToraScorer): Promise<string> {
  if (!judge || note.private || note.retired) return "";
  try {
    const project = note.project === GLOBAL ? { id: GLOBAL, tags: note.tags, root: null } : projectById(home, note.project, home);
    const others = notes.filter(other => !other.retired && !other.private && visibleTo(other, project) && comparable(note, other));
    const left = new Set(tokens(note.body));
    const pairs = others.flatMap(other => {
      const candidate = pair(note, other, left, new Set(tokens(other.body)));
      return candidate ? [candidate] : [];
    }).sort(bySimilarity).slice(0, 3);
    const found = tora && others.length ? await tora(note.body, others.map(other => ({ id: other.id, text: other.body }))).catch(() => undefined) : undefined;
    if (found) {
      const near = [...others].sort((a, b) => found.scores.get(b.id)! - found.scores.get(a.id)!).slice(0, 3);
      pairs.push(...near.filter(other => !pairs.some(p => p.a === other || p.b === other)).map(other => ordered(note, other, found.scores.get(other.id)!, "tora")));
    }
    if (!pairs.length) return "";
    const scores = await judge(pairs.map(({ id, a, b }) => ({ id, a: judgeText(a), b: judgeText(b) })));
    if (!scores || pairs.some(pair => !valid(scores.get(pair.id)))) return "";
    for (const pair of pairs) {
      const other = pair.a.id === note.id ? pair.b : pair.a;
      if (scores.get(pair.id)!.contradicts >= JUDGE_THRESHOLD) return ` (contradicts ${other.id}: if it replaces it, brain retire ${other.id} --by ${note.id})`;
    }
    for (const pair of pairs) {
      const other = pair.a.id === note.id ? pair.b : pair.a;
      if (scores.get(pair.id)!.same >= JUDGE_THRESHOLD) return ` (same as ${other.id}: brain retire ${note.id} if redundant)`;
    }
  } catch { /* the saved reply stays unchanged */ }
  return "";
}
