/** Read-only maintenance suggestions; semantic failures leave lexical candidates intact. */
import { JUDGE_THRESHOLD, judgeText, type PairJudge } from "./judge.ts";
import { GLOBAL, type Note } from "./notes.ts";
import { projectById, visibleTo, type Project } from "./project.ts";
import { tokens } from "./search.ts";
import { noteUsage, usageWindow } from "./telemetry.ts";
import type { ToraScorer } from "./tora.ts";

export interface SimilarPair {
  id: string;
  a: Note;
  b: Note;
  score: number;
}

/** Never the same note, a replacement chain, two unrelated projects, or globals sharing no tag. */
function comparable(a: Note, b: Note): boolean {
  if (a.id === b.id || a.replaces === b.id || a.replacedBy === b.id || b.replaces === a.id || b.replacedBy === a.id || (a.project !== b.project && a.project !== GLOBAL && b.project !== GLOBAL)) return false;
  return !(a.project === GLOBAL && b.project === GLOBAL && a.tags.some(tag => tag !== "brief") && b.tags.some(tag => tag !== "brief")
    && !a.tags.some(tag => tag !== "brief" && b.tags.includes(tag)));
}

/** Older first, regardless of input order: a suggestion retires it in favour of b. */
function ordered(a: Note, b: Note, score: number): SimilarPair {
  const ageOrder = Date.parse(a.at) - Date.parse(b.at);
  if (ageOrder > 0 || (ageOrder === 0 && a.id > b.id)) [a, b] = [b, a];
  return { id: JSON.stringify([a.id, b.id]), a, b, score };
}

function pair(a: Note, b: Note, left: Set<string>, right: Set<string>): SimilarPair | undefined {
  if (!comparable(a, b)) return undefined;
  let shared = 0;
  for (const word of left) if (right.has(word)) shared++;
  const score = shared / (left.size + right.size - shared);
  return shared < 2 || score < 0.2 ? undefined : ordered(a, b, score);
}

const bySimilarity = (a: SimilarPair, b: SimilarPair) => b.score - a.score || a.id.localeCompare(b.id);

/** Bounded lexical shortlist, never comparing retired notes or two unrelated projects. */
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
  return pairs.sort(bySimilarity).slice(0, Math.max(0, limit));
}

function valid(scores: { same: number; contradicts: number } | undefined): boolean {
  return !!scores && [scores.same, scores.contradicts].every(p => Number.isFinite(p) && p >= 0 && p <= 1);
}

export async function tidyReport(home: string, notes: Note[], project: Project, opts: { judge?: PairJudge; all?: boolean; days?: number } = {}): Promise<{ duplicates: SimilarPair[]; contradictions: SimilarPair[]; similar: SimilarPair[]; unused: Note[]; unusedWindow: string }> {
  const days = opts.days ?? 30;
  const active = notes.filter(note => !note.retired && (opts.all || visibleTo(note, project)));
  const usage = noteUsage(home, days);
  const since = Date.now() - days * 86_400_000;
  // Telemetry keeps about two weeks: a note's absence from rows that start later says nothing about
  // the days before them. "Unused" holds for the window they cover; with no rows it holds for none.
  const unused = usage.from === undefined ? [] : active.filter(note => Date.parse(note.at) < since && !usage.notes.has(note.id));
  const pairs = similarPairs(active, Infinity).filter(({ a, b }) => {
    if (a.project === b.project) return true;
    const local = a.project === GLOBAL ? b : a;
    const global = a.project === GLOBAL ? a : b;
    return visibleTo(global, opts.all ? projectById(home, local.project, home) : project);
  });
  const report = { duplicates: [] as SimilarPair[], contradictions: [] as SimilarPair[], similar: pairs, unused, unusedWindow: usageWindow(usage, days) };
  if (!opts.judge) return report;
  const publicPairs = pairs.filter(({ a, b }) => !a.private && !b.private);
  try {
    if (!publicPairs.length) return report;
    const scores = await opts.judge(publicPairs.map(({ id, a, b }) => ({ id, a: judgeText(a), b: judgeText(b) })));
    if (!scores || publicPairs.some(pair => !valid(scores.get(pair.id)))) return report;
    report.similar = pairs.filter(({ a, b }) => a.private || b.private);
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
      pairs.push(...near.filter(other => !pairs.some(p => p.a === other || p.b === other)).map(other => ordered(note, other, found.scores.get(other.id)!)));
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
