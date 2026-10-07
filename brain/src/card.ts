/** Start-of-session memory: complete facts, scoped context, and a hard total budget. */
import { pendingCount } from "./capture.ts";
import { childDocContext, projectDocs } from "./docs.ts";
import { displayLine, firstLine, GLOBAL, testedCurrent, type Note } from "./notes.ts";
import { visibleTo, type Project } from "./project.ts";
import { recall, staleHere, verifiedHere } from "./search.ts";
import { fixFires, pausedFixes } from "./telemetry.ts";
import { cutToTokens, estimateTokens } from "./util.ts";
import { planFit, readWork, workText } from "./work.ts";

export const CARD_BUDGET = 400;
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

export interface CardOptions {
  /** The host exposes the brain_* tools (OMP); otherwise the card names the CLI. */
  tools?: boolean;
  now?: Date;
  subagent?: boolean;
  /** The host rendering the card; recurring fixes count only that host's fires. */
  host?: "omp" | "claude-code";
  /** First user prompt, used only for ranking, never persisted. */
  prompt?: string;
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
 * card can never show cannot take the top-10 relevance slots.
 */
export function rankForCard(candidates: Note[], project: Project, workText: string, now: Date, home: string, prompt = ""): Note[] {
  const relevance = new Map<string, number>();
  if (workText.trim()) {
    const hits = recall(candidates, workText, { project, limit: 10 });
    const top = hits.reduce((max, hit) => Math.max(max, hit.score), 0);
    for (const hit of hits) if (top > 0) relevance.set(hit.note.id, hit.score / top);
  }
  const promptScores = new Map(prompt.trim()
    ? recall(candidates, prompt, { project, limit: candidates.length }).map((hit) => [hit.note.id, hit.score])
    : []);
  const score = (n: Note): number => {
    const age = (now.getTime() - Date.parse(n.at)) / DAY_MS;
    const recent = age <= 14 ? 2 : age <= 60 ? 1 : 0;
    return (testedCurrent(n) ? 3 : 0) + (KIND_WEIGHT[n.kind] ?? 1) + recent - (staleHere(n, project, home) ? 3 : 0) + RELEVANCE_WEIGHT * (relevance.get(n.id) ?? 0);
  };
  const scored = candidates.map((n) => ({ n, s: score(n), p: promptScores.get(n.id) ?? 0 }));
  scored.sort((a, b) => b.p - a.p || b.s - a.s || (a.n.at < b.n.at ? 1 : a.n.at > b.n.at ? -1 : 0) || (a.n.id < b.n.id ? -1 : 1));
  return scored.map((x) => x.n);
}

/** Never turn an essential fact into a clipped pointer requiring a second recall. */
function noteLine(n: Note, room: number): string {
  const prefix = `- [${n.kind}${testedCurrent(n) ? ", tested" : ""}] `;
  const suffix = ` (${n.id})`;
  const lines = n.body.split("\n").map((line) => line.trim()).filter(Boolean);
  const title = firstLine(n);
  const full = title.length <= 48 && lines[1] ? title + " — " + lines[1] : title;
  const text = displayLine({ body: full }, Math.max(0, room - prefix.length - suffix.length));
  if (!text || text !== full) return "";
  const line = prefix + text + suffix;
  return line.length <= room ? line : "";
}

function footer(tools: boolean, subagent: boolean): string {
  const recall = tools ? "brain_recall(query)" : '`brain recall "<query>"`';
  const note = tools ? "brain_note(text)" : '`brain note "<text>"`';
  const state = tools ? "brain_state(text)" : '`brain state "<text>"`';
  // Children keep only recall: their notes went unused (0 of 27) and their state writes are refused.
  if (subagent) return `${recall} before explore/choose/retry, batched with other calls`;
  return `${recall} before explore/choose/retry, batched with other calls · ${note} for what code can't tell · ${state} when goal/next changes`;
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
  const tail = footer(opts.tools === true, true);
  const room = (): number => CHILD_CARD_BUDGET * 4 - [...lines, tail].join("\n").length - 1;
  const add = (text: string): boolean => {
    if (!text || text.length > room()) return false;
    lines.push(text);
    return true;
  };
  add(cutToTokens(warning.replace(/\s+/g, " ").trim(), Math.min(40, Math.floor(room() / 4))));
  const fires = fixFires(home, true, 7, now, opts.host);
  const paused = pausedFixes(home, notes);
  const recurring = notes.filter(note => !note.retired && verifiedHere(note, project, home) && note.errors.length && !paused.has(note.id)
    && (fires.get(note.id) ?? 0) >= RECURRING_FIX_SESSIONS && visibleTo(note, project)
    && !(opts.host && note.host && note.host !== opts.host))
    .sort((a, b) => (fires.get(b.id) ?? 0) - (fires.get(a.id) ?? 0) || a.id.localeCompare(b.id))
    .slice(0, RECURRING_FIX_LINES);
  const said = new Set<string>();
  for (const note of recurring) {
    const label = said.size ? "" : "Often hit lately (sessions this week):\n";
    const count = (fires.get(note.id) ?? 0) + "× ";
    const line = noteLine(note, room() - label.length - count.length);
    if (line && add(label + "- " + count + line.slice(2))) said.add(note.id);
  }
  const rules: string[] = [];
  for (const note of rankForCard(briefNotes(notes, project), project, warning, now, home, opts.prompt)) {
    if (said.has(note.id)) continue;
    const line = noteLine(note, 80 * 4 - ["Rules:", ...rules].join("\n").length - 1);
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
  for (const line of docs.outline.split("\n")) add(line);
  if (docs.section) add(docs.section);
  // Existing project memories remain eligible only after the child-specific blocks.
  let known = 0;
  const candidates = cardCandidates(notes, project).filter(note => !note.tags.includes("brief"));
  for (const note of rankForCard(candidates, project, warning, now, home, opts.prompt)) {
    if (said.has(note.id)) continue;
    const label = known ? "" : "Known here:\n";
    const line = noteLine(note, room() - label.length);
    if (line && add(label + line) && ++known === CARD_NOTES) break;
  }

  if (lines.length === 1) return "";
  const card = [...lines, tail].join("\n");
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
    .filter((n) => !n.retired && verifiedHere(n, project, home) && n.errors.length && !paused.has(n.id) && (fires.get(n.id) ?? 0) >= RECURRING_FIX_SESSIONS && visibleTo(n, project) && !(opts.host && n.host && n.host !== opts.host))
    .sort((a, b) => (fires.get(b.id) ?? 0) - (fires.get(a.id) ?? 0) || (a.id < b.id ? -1 : 1))
    .slice(0, RECURRING_FIX_LINES);
  const ranked = rankForCard(candidates, project, work?.text ?? "", now, home, opts.prompt);
  const pending = pendingCount(home, project.id);
  const head = `Brain · ${cutToTokens(project.id.replace(/[\r\n]/g, " "), 16)} — what prior sessions learned; the repo wins on conflict`;
  const tail = [pending ? `${pending} proposal${pending === 1 ? "" : "s"} waiting → ` + "`brain review`" : "", LEAN_LINE, footer(opts.tools === true, false)].filter(Boolean);
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
    const line = noteLine(fix, Math.min(80 * 4, room(label) - count.length));
    if (!line) continue;
    lines.push(...label, "- " + count + line.slice(2));
    said.add(fix.id);
  }
  let count = 0;
  for (const note of ranked) {
    if (said.has(note.id)) continue;
    const label = count ? [] : ["Known here:"];
    const line = noteLine(note, room(label));
    if (!line) continue;
    lines.push(...label, line);
    if (++count === CARD_NOTES) break;
  }
  if (lines.length === 1 && !pending) return "";
  const card = [...lines, ...tail].join("\n");
  return estimateTokens(card) <= CARD_BUDGET ? card : "";
}

/** Only rendered note/fix lines count: omitted notes were not delivered. */
export function cardIds(card: string): string[] {
  return [...new Set([...card.matchAll(/^- (?:\d+× )?\[[^\]\n]+\] .+ \(([^()\s]+)\)$/gm)].map(match => match[1]!))];
}
