/** Start-of-session memory: complete facts, scoped context, and a hard total budget. */
import { childDocContext, projectDocs } from "./docs.ts";
import { displayLine, expired, firstLine, GLOBAL, testedCurrent, type Note } from "./notes.ts";
import { visibleTo, type Project } from "./project.ts";
import { changedHere, recall, staleHere, tokens, verifiedHere } from "./search.ts";
import { scrub } from "./scrub.ts";
import { fixFires, pausedFixes } from "./telemetry.ts";
import { TORA_CARD_TIMEOUT_MS, type ToraScorer } from "./tora.ts";
import { cutToTokens, estimateTokens } from "./util.ts";
import { planFit, readWork, workText } from "./work.ts";

/** Lean by owner request (2026-10-14): low-ranked notes cost every session; recall fetches them on demand. */
export const CARD_BUDGET = 320;
export const CHILD_CARD_BUDGET = 200;
export const CARD_NOTES = 5;
/** Distinct sessions of the same role in 7 days before a fix is said up front (E1: 8/8 → 2/8). */
const RECURRING_FIX_SESSIONS = 3;
/** Two lines at most: pre-empting mistakes must not crowd out what the project knows. */
const RECURRING_FIX_LINES = 2;
/**
 * Every turn re-sends the whole context and every tool result stays in it, so fewer and smaller
 * turns beat terser prose. Measured (agentbench, 28 GPT runs each): -10% tokens, -9% cost.
 */
export const LEAN_LINE = "Work lean: batch independent tool calls in one turn · read the lines you need, not whole files · finish with the result, no recap.";

const KIND_WEIGHT: Record<string, number> = { gotcha: 3, decision: 3, procedure: 2, fact: 1, note: 1 };
const DAY_MS = 86_400_000;
const RELEVANCE_WEIGHT = 6;
/**
 * A prompt with fewer content words ("continue", "fix the tests") names no topic: on 45 real first
 * prompts Tora and BM25 ranked those equally, so the static order stays. With more, Tora's cosine
 * ranking doubled the relevant notes in the top three (0.45 vs 0.20 precision, 32 prompts).
 */
const CARD_TOPIC_WORDS = 3;

export interface CardOptions {
  /** The host exposes the brain_* tools (OMP); otherwise the card names the CLI. */
  tools?: boolean;
  now?: Date;
  subagent?: boolean;
  /** The host rendering the card; recurring fixes count only that host's fires. */
  host?: "omp" | "claude-code";
  /** First user prompt, used only for ranking, never persisted. */
  prompt?: string;
  /** Tora's cosine of each public candidate against the prompt (cardSemantic); replaces BM25's prompt ranking. */
  semantic?: Map<string, number>;
  /** Parent session edits supplied by the host, never the persisted project auto state. */
  parentEdits?: string[];
}

/** Active project notes and applicable tagged globals; untagged globals stay pull-only. */
export function cardCandidates(notes: Note[], project: Project): Note[] {
  return notes.filter((n) => {
    if (n.retired) return false;
    if (n.project === project.id) return true;
    return n.project === GLOBAL && n.tags.length > 0 && visibleTo(n, project);
  });
}

/**
 * Prompt relevance first, then working-state relevance and the static tested/kind/recency rank.
 * Relevance is scored over the candidates alone: cheaper than the whole corpus, and notes the
 * card can never show cannot take the top-10 relevance slots. Tora's cosines, when given, rank
 * by prompt instead of BM25.
 */
export function rankForCard(candidates: Note[], project: Project, workText: string, now: Date, home: string, prompt = "", semantic?: Map<string, number>): Note[] {
  const relevance = new Map<string, number>();
  if (workText.trim()) {
    const hits = recall(candidates, workText, { project, limit: 10 });
    const top = hits.reduce((max, hit) => Math.max(max, hit.score), 0);
    for (const hit of hits) if (top > 0) relevance.set(hit.note.id, hit.score / top);
  }
  const promptScores = semantic ?? new Map(prompt.trim()
    ? recall(candidates, prompt, { project, limit: candidates.length }).map((hit) => [hit.note.id, hit.score])
    : []);
  const score = (n: Note, stale: boolean): number => {
    const age = (now.getTime() - Date.parse(n.at)) / DAY_MS;
    const recent = age <= 14 ? 2 : age <= 60 ? 1 : 0;
    return (testedCurrent(n) ? 3 : 0) + (KIND_WEIGHT[n.kind] ?? 1) + recent - (stale ? 3 : 0) + RELEVANCE_WEIGHT * (relevance.get(n.id) ?? 0);
  };
  const scored = candidates.map((n) => {
    const stale = staleHere(n, project, home);
    return { n, stale, s: score(n, stale), p: promptScores.get(n.id) ?? 0 };
  });
  // Stale notes sit behind live ones even under a prompt match, as in recall.
  scored.sort((a, b) => Number(a.stale) - Number(b.stale) || b.p - a.p || b.s - a.s || (a.n.at < b.n.at ? 1 : a.n.at > b.n.at ? -1 : 0) || (a.n.id < b.n.id ? -1 : 1));
  return scored.map((x) => x.n);
}

/**
 * Tora's cosine of every public card candidate and standing rule against the prompt, or nothing to
 * wait for (undefined): no live Tora, or a prompt naming no topic. The promise resolves to undefined
 * when Tora fails or misses TORA_CARD_TIMEOUT_MS; BM25 then ranks, and Tora is warm for recall.
 */
export function cardSemantic(notes: Note[], project: Project, prompt: string | undefined, tora: ToraScorer | undefined): Promise<Map<string, number> | undefined> | undefined {
  if (!tora || !prompt || tokens(prompt, false, false).length < CARD_TOPIC_WORDS) return undefined;
  const pool = [...new Set([...cardCandidates(notes, project), ...briefNotes(notes, project)])].filter(note => !note.private);
  if (!pool.length) return undefined;
  return tora(scrub(prompt).text, pool.map(note => ({ id: note.id, text: note.body })), TORA_CARD_TIMEOUT_MS).then(found => found?.scores, () => undefined);
}

/** Never turn an essential fact into a clipped pointer requiring a second recall. */
function noteLine(n: Note, room: number, project: Project, home: string): string {
  const changed = changedHere(n, project, home);
  const marker = changed ? " (evidence changed)" : staleHere(n, project, home)
    ? expired(n) ? ` (stale since ${n.staleAfter!.slice(0, 10)})` : " (stale evidence)" : "";
  const prefix = `- [${n.kind}${testedCurrent(n) ? ", tested" : ""}] `;
  const suffix = `${marker} (${n.id})`;
  const lines = n.body.split("\n").map((line) => line.trim()).filter(Boolean);
  const title = firstLine(n);
  const next = lines[1];
  const headline = title.replace(/(?:…|\.\.\.)$/, "").trimEnd();
  const duplicate = next && next.startsWith(headline) && (headline !== title || !next[headline.length] || /[\s:;,.—–-]/.test(next[headline.length]!));
  const full = duplicate ? next : next && (title.endsWith(":") || title.length <= 48) ? title + " — " + next : title;
  const text = displayLine({ body: full }, Math.max(0, room - prefix.length - suffix.length));
  if (!text || text !== full) return "";
  const line = prefix + text + suffix;
  return line.length <= room ? line : "";
}

/** The CLI's when-to-act line; hosts with resident brain_* tools carry it in the tool descriptions. */
function footer(subagent: boolean): string {
  const recall = '`brain recall "<query>"` before explore/choose/retry, batched with other calls';
  // Children keep only recall: their notes went unused (0 of 27) and their state writes are refused.
  if (subagent) return recall;
  return `${recall} · \`brain note "<text>"\` for what code can't tell · \`brain state "<text>"\` when goal/next changes`;
}
/** Active standing rules in the central project/global visibility scope. */
export function briefNotes(notes: Note[], project: Project): Note[] {
  return notes.filter(note => !note.retired && note.tags.includes("brief") && visibleTo(note, project));
}

/** Child cards never inherit a parent goal, next step or automatic observations. */
export function renderChildCard(home: string, notes: Note[], project: Project, opts: CardOptions = {}): string {
  const now = opts.now ?? new Date();
  const work = readWork(home, project.id);
  const warning = work?.text
    ? planFit(work.text.replace(/^See:.*$/gm, ""), work.text.length).split(/(?=^Done:)/m)[0]?.match(/^Watch out: [\s\S]*/m)?.[0] ?? "" : "";
  const lines = [
    `Brain · ${cutToTokens(project.id.replace(/[\r\n]/g, " "), 16)} — child context; the repo wins on conflict`
  ];
  const tail = opts.tools === true ? [] : [footer(true)];
  const room = (): number => CHILD_CARD_BUDGET * 4 - [...lines, ...tail].join("\n").length - 1;
  const add = (text: string): boolean => {
    if (!text || text.length > room()) return false;
    lines.push(text);
    return true;
  };
  add(cutToTokens(warning.replace(/\s+/g, " ").trim(), Math.min(40, Math.floor(room() / 4))));
  const fires = fixFires(home, true, 7, now, opts.host);
  const paused = pausedFixes(home, notes);
  const recurring = notes.filter(note => !note.retired && !expired(note) && verifiedHere(note, project, home) && note.errors.length && !paused.has(note.id)
    && (fires.get(note.id) ?? 0) >= RECURRING_FIX_SESSIONS && visibleTo(note, project)
    && !(opts.host && note.host && note.host !== opts.host))
    .sort((a, b) => (fires.get(b.id) ?? 0) - (fires.get(a.id) ?? 0) || a.id.localeCompare(b.id))
    .slice(0, RECURRING_FIX_LINES);
  const said = new Set<string>();
  for (const note of recurring) {
    const label = said.size ? "" : "Often hit lately (sessions this week):\n";
    const count = (fires.get(note.id) ?? 0) + "× ";
    const line = noteLine(note, room() - label.length - count.length, project, home);
    if (line && add(label + "- " + count + line.slice(2))) said.add(note.id);
  }
  const rules: string[] = [];
  for (const note of rankForCard(briefNotes(notes, project), project, warning, now, home, opts.prompt, opts.semantic)) {
    if (said.has(note.id)) continue;
    const line = noteLine(note, 80 * 4 - ["Rules:", ...rules].join("\n").length - 1, project, home);
    if (!line || ["Rules:", ...rules, line].join("\n").length > room()) continue;
    rules.push(line);
    if (rules.length === 6) break;
  }
  if (rules.length) add(["Rules:", ...rules].join("\n"));
  const paths = [...new Set((opts.parentEdits ?? []).filter(path => path && !/[\r\n\0]/.test(path)))].slice(-8);
  const files: string[] = [];
  for (const path of paths) {
    const block = ["Files in play:", ...files, path].join("\n");
    if (block.length <= room()) files.push(path);
  }
  if (files.length) add(["Files in play:", ...files].join("\n"));
  const docs = childDocContext(home, project, opts.prompt);
  const sectionAdded = docs.section ? add(docs.section) : false;
  for (const line of docs.outline.split("\n")) if (!sectionAdded || line !== docs.section?.split("\n")[0]) add(line);
  // Existing project memories remain eligible only after the child-specific blocks.
  let known = 0;
  const topical = tokens(opts.prompt ?? "", false, false).length >= CARD_TOPIC_WORDS;
  const eligible = topical ? new Set(recall(cardCandidates(notes, project), opts.prompt!, { project, limit: 10 }).map(hit => hit.note.id)) : undefined;
  // Cosine order alone has no calibrated abstention threshold: lexical recall gates ordinary facts.
  const candidates = cardCandidates(notes, project).filter(note => !note.tags.includes("brief") && (!eligible || eligible.has(note.id)));
  for (const note of rankForCard(candidates, project, warning, now, home, opts.prompt, opts.semantic)) {
    if (said.has(note.id)) continue;
    const label = known ? "" : "Known here:\n";
    const line = noteLine(note, room() - label.length, project, home);
    if (line && add(label + line) && ++known === CARD_NOTES) break;
  }

  if (lines.length === 1) return "";
  const card = [...lines, ...tail].join("\n");
  return estimateTokens(card) <= CHILD_CARD_BUDGET ? card : "";
}


/** Complete card including header and tail fits CARD_BUDGET; nothing useful means no injection. */
export function renderCard(home: string, notes: Note[], project: Project, opts: CardOptions = {}): string {
  if (opts.subagent) return renderChildCard(home, notes, project, opts);
  const now = opts.now ?? new Date();
  const work = readWork(home, project.id);
  const workingState = workText(work, project.root, project.docRoot, project.docRoot ? projectDocs(home, project) : []);
  const rules = briefNotes(notes, project);
  const candidates = cardCandidates(notes, project).filter(note => !rules.includes(note));
  // A fix that fired in several recent sessions of this role (child or not) is a mistake agents
  // here keep making: say it before the first attempt, not after. It retires itself when the
  // mistake stops, because then it stops firing.
  const fires = fixFires(home, false, 7, now, opts.host);
  const paused = pausedFixes(home, notes);
  // Any note that could fire as a fix here qualifies, untagged globals included.
  const recurring = notes
    .filter((n) => !n.retired && !expired(n) && verifiedHere(n, project, home) && n.errors.length && !paused.has(n.id) && (fires.get(n.id) ?? 0) >= RECURRING_FIX_SESSIONS && visibleTo(n, project) && !(opts.host && n.host && n.host !== opts.host))
    .sort((a, b) => (fires.get(b.id) ?? 0) - (fires.get(a.id) ?? 0) || (a.id < b.id ? -1 : 1))
    .slice(0, RECURRING_FIX_LINES);
  const ranked = rankForCard(candidates, project, work?.text ?? "", now, home, opts.prompt, opts.semantic);
  const head = `Brain · ${cutToTokens(project.id.replace(/[\r\n]/g, " "), 16)} — what prior sessions learned; the repo wins on conflict`;
  // Owner-facing counts (pending proposals) stay in `brain review`; resident tools describe themselves.
  const tail = opts.tools === true ? [LEAN_LINE] : [LEAN_LINE, footer(false)];
  const lines = [head];
  const room = (extra: string[] = []): number => CARD_BUDGET * 4 - [...lines, ...extra, ...tail].join("\n").length - 1;
  if (rules.length) lines.push(`children get: ${rules.length} rules`);
  if (workingState) {
    const text = cutToTokens(workingState, Math.floor(room() / 4));
    if (text.trim()) lines.push(text);
  }
  // A recurring fix that does not fit its slot stays eligible as an ordinary note below.
  const said = new Set<string>();
  for (const fix of recurring) {
    const label = said.size ? [] : ["Often hit lately (sessions this week):"];
    const count = `${fires.get(fix.id)}× `;
    const line = noteLine(fix, Math.min(80 * 4, room(label) - count.length), project, home);
    if (!line) continue;
    lines.push(...label, "- " + count + line.slice(2));
    said.add(fix.id);
  }
  let count = 0;
  for (const note of ranked) {
    if (said.has(note.id)) continue;
    const label = count ? [] : ["Known here:"];
    const line = noteLine(note, room(label), project, home);
    if (!line) continue;
    lines.push(...label, line);
    if (++count === CARD_NOTES) break;
  }
  if (lines.length === 1) return "";
  const card = [...lines, ...tail].join("\n");
  return estimateTokens(card) <= CARD_BUDGET ? card : "";
}

/** Only rendered note/fix lines count: omitted notes were not delivered. */
export function cardIds(card: string): string[] {
  return [...new Set([...card.matchAll(/^- (?:\d+× )?\[[^\]\n]+\] .+ \(([^()\s]+)\)$/gm)].map(match => match[1]!))];
}
