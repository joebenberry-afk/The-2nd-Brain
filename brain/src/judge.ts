/** Optional relevance check over the lexical answer; failures preserve that answer. */
import { findNote, type Note } from "./notes.ts";
import { answerWithHits, type AnswerOptions } from "./search.ts";
import { scrub } from "./scrub.ts";

/** 0.75 gave 0-2 wrong answers across four runs of the same 54 real queries (Jev drifts about ±0.02); 0.78 gave 0 in all four. */
export const JUDGE_THRESHOLD = 0.78;
/** Warm calls take ~300 ms; a spike waits here rather than letting an unchecked answer through. */
export const JUDGE_TIMEOUT_MS = 5000;
export type Judge = (query: string, candidates: { id: string; text: string }[]) => Promise<Map<string, number> | undefined>;

/** Scrubbed before the cut: a secret straddling character 450 would fall below its pattern's length. */
export function judgeText(note: Note): string {
  return scrub(note.body.replace(/\s+/g, " ")).text.slice(0, 450);
}

const cache = new Map<string, number>();
const CACHE_LIMIT = 512;
const probability = (p: unknown): p is number => typeof p === "number" && Number.isFinite(p) && p >= 0 && p <= 1;

export function typesafeJudge(env: NodeJS.ProcessEnv): Judge | undefined {
  const key = env.TYPESAFE_API_KEY;
  if (!key || env.BRAIN_JUDGE === "off") return undefined;
  return async (query, candidates) => {
    try {
      query = scrub(query).text;
      const keys = candidates.map(c => JSON.stringify([query, c.id, c.text]));
      const missing = candidates.filter((_c, i) => !cache.has(keys[i]!));
      const result = new Map<string, number>();
      if (missing.length) {
        const questions = Object.fromEntries(missing.map((c, i) => [`rel_${i}`, {
          type: "noul",
          instructions: `Is candidate c${i} relevant to the query in the state? Candidate c${i}: ${c.text}`,
          criteria: {
            true: "The candidate addresses the subject the query asks about, or provides what it seeks",
            false: "The candidate is about a different subject, or only shares vocabulary with the query",
          },
        }]));
        const response = await fetch(`${env.TYPESAFE_BASE_URL || "https://api.typesafe.ai"}/v1/systemone`, {
          method: "POST",
          headers: { Authorization: `Bearer ${key}`, Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ state: { query }, questions, model: "jev-latest" }),
          signal: AbortSignal.timeout(JUDGE_TIMEOUT_MS),
        });
        if (!response.ok) return undefined;
        const body = await response.json() as { answers?: Record<string, { noul?: unknown }> } | null;
        for (const [i, candidate] of missing.entries()) {
          const p = body?.answers?.[`rel_${i}`]?.noul;
          if (!probability(p)) return undefined;
          result.set(candidate.id, p);
        }
      }
      // Validate the whole response before admitting any of it to the cache.
      for (const [i, c] of candidates.entries()) {
        const p = result.get(c.id) ?? cache.get(keys[i]!)!;
        result.set(c.id, p);
        cache.set(keys[i]!, p);
      }
      while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!);
      return result;
    } catch {
      // No exception (including a transport error containing credentials) leaves this boundary.
      return undefined;
    }
  };
}

export async function judgedAnswer(notes: Note[], query: string, opts: AnswerOptions, judge?: Judge) {
  const lexical = { ...answerWithHits(notes, query, opts), judged: false, dropped: 0 };
  if (!judge || !lexical.hits || findNote(notes, query)) return lexical;
  const candidates = lexical.ids.flatMap(id => {
    const note = notes.find(n => n.id === id);
    return note && !note.private ? [{ id, text: judgeText(note) }] : [];
  });
  let result = lexical;
  try {
    if (candidates.length) {
      const scores = await judge(scrub(query).text, candidates);
      if (!scores || candidates.some(c => !probability(scores.get(c.id)))) return lexical;
      const dropped = candidates.filter(c => scores.get(c.id)! < JUDGE_THRESHOLD).map(c => c.id);
      opts = { ...opts, exclude: new Set([...opts.exclude ?? [], ...dropped]) };
      result = { ...(dropped.length ? answerWithHits(notes, query, opts) : lexical), judged: true, dropped: dropped.length };
    }
    // A plan-doc heading (all notes dropped, or none matched) is checked the same way. A doc the
    // query names by file (its outline) is what was asked for and is not judged.
    if (result.docExcerpt) {
      const id = result.ids[0]!;
      const scores = await judge(scrub(query).text, [{ id, text: scrub(result.docExcerpt).text.slice(0, 450) }]);
      if (!scores || !probability(scores.get(id))) return result;
      const keep = scores.get(id)! >= JUDGE_THRESHOLD;
      result = { ...(keep ? result : answerWithHits(notes, query, { ...opts, noDoc: true })), judged: true, dropped: result.dropped + (keep ? 0 : 1) };
    }
    return result;
  } catch {
    return result;
  }
}
