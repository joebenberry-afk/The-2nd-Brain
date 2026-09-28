/** Start-of-session memory: complete facts, scoped context, and a hard total budget. */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { pendingCount } from "./capture.ts";
import { kitsFor, loadKits, type Kit } from "./kits.ts";
import { displayLine, firstLine, GLOBAL, staleEvidence, type Note } from "./notes.ts";
import type { Project } from "./project.ts";
import { recall } from "./search.ts";
import { cutToTokens, estimateTokens } from "./util.ts";
import { planFit, readWork, resumeText } from "./work.ts";

export const CARD_BUDGET = 400;
export const CARD_NOTES = 5;

const KIND_WEIGHT: Record<string, number> = { gotcha: 3, decision: 3, procedure: 2, fact: 1, note: 1 };
const DAY_MS = 86_400_000;
const RELEVANCE_WEIGHT = 6;

export interface CardOptions {
  /** The host exposes the brain_* tools (OMP); otherwise the card names the CLI. */
  tools?: boolean;
  now?: Date;
  subagent?: boolean;
  /** First user prompt, used only for ranking, never persisted. */
  prompt?: string;
}

/** Active project notes and global notes sharing a project tag; untagged globals stay pull-only. */
export function cardCandidates(notes: Note[], project: Project): Note[] {
  return notes.filter((n) => {
    if (n.retired) return false;
    if (n.project === project.id) return true;
    return n.project === GLOBAL && n.tags.length > 0 && n.tags.some((t) => project.tags.includes(t));
  });
}

/**
 * Prompt relevance first, then working-state relevance and the static tested/kind/recency rank.
 * Relevance is scored over the candidates alone: cheaper than the whole corpus, and notes the
 * card can never show cannot take the top-10 relevance slots.
 */
export function rankForCard(candidates: Note[], project: Project, workText: string, now: Date, home: string, prompt = ""): Note[] {
  const roots = [project.root, home].filter((root): root is string => !!root);
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
    return (n.tested ? 3 : 0) + (KIND_WEIGHT[n.kind] ?? 1) + recent - (staleEvidence(n, roots) ? 3 : 0) + RELEVANCE_WEIGHT * (relevance.get(n.id) ?? 0);
  };
  const scored = candidates.map((n) => ({ n, s: score(n), p: promptScores.get(n.id) ?? 0 }));
  scored.sort((a, b) => b.p - a.p || b.s - a.s || (a.n.at < b.n.at ? 1 : a.n.at > b.n.at ? -1 : 0) || (a.n.id < b.n.id ? -1 : 1));
  return scored.map((x) => x.n);
}

/** Never turn an essential fact into a clipped pointer requiring a second recall. */
function noteLine(n: Note, room: number): string {
  const prefix = `- [${n.kind}${n.tested ? ", tested" : ""}] `;
  const suffix = ` (${n.id})`;
  const lines = n.body.split("\n").map((line) => line.trim()).filter(Boolean);
  const title = firstLine(n);
  const full = title.length <= 48 && lines[1] ? title + " — " + lines[1] : title;
  const text = displayLine({ body: full }, Math.max(0, room - prefix.length - suffix.length));
  if (!text || text !== full) return "";
  const line = prefix + text + suffix;
  return line.length <= room ? line : "";
}

/** Inspect git metadata without spawning git on the host's first-turn hot path. */
function freshRoot(root: string | null): boolean {
  if (!root) return false;
  try {
    if (readdirSync(root).filter((name) => name !== ".git").length <= 3) return true;
    let gitdir = join(root, ".git");
    if (statSync(gitdir).isFile()) {
      const target = /^gitdir:\s*(.+)$/m.exec(readFileSync(gitdir, "utf8"))?.[1];
      if (!target) return false;
      gitdir = resolve(root, target.trim());
    }
    const head = readFileSync(join(gitdir, "HEAD"), "utf8").trim();
    const ref = /^ref: (refs\/.+)$/.exec(head)?.[1];
    if (!ref) return false; // Detached HEAD, or unreadable metadata: not known to be fresh.
    const commonPath = join(gitdir, "commondir");
    const common = existsSync(commonPath) ? resolve(gitdir, readFileSync(commonPath, "utf8").trim()) : gitdir;
    if (existsSync(join(common, ref))) return false;
    const packed = join(common, "packed-refs");
    return !existsSync(packed) || !readFileSync(packed, "utf8").split("\n").some((line) => line.trimEnd().endsWith(` ${ref}`));
  } catch {
    return false;
  }
}

/** Include complete kit names and a callable recall, reserving at most 64 tokens. */
function kitsLine(kits: Kit[], tools: boolean): string {
  const label = "Kits: ";
  const where = tools ? ' → brain_recall("kit <name>")' : ' → brain recall "kit <name>"';
  const names: string[] = [];
  for (const kit of kits) {
    if (/[\r\n]/.test(kit.name)) continue;
    if (estimateTokens(label + [...names, kit.name].join(", ") + where) > 64) continue;
    names.push(kit.name);
    if (names.length === 5) break;
  }
  return names.length ? label + names.join(", ") + where : "";
}

function footer(tools: boolean, subagent: boolean): string {
  const recall = tools ? "brain_recall(query)" : '`brain recall "<query>"`';
  const note = tools ? "brain_note(text)" : '`brain note "<text>"`';
  const state = tools ? "brain_state(text)" : '`brain state "<text>"`';
  return `${recall} before explore/choose/retry · ${note} for what code can't tell` + (subagent ? "" : ` · ${state} when goal/next changes`);
}

/** Complete card including header and tail fits CARD_BUDGET; nothing useful means no injection. */
export function renderCard(home: string, notes: Note[], project: Project, opts: CardOptions = {}): string {
  const now = opts.now ?? new Date();
  const work = readWork(home, project.id);
  // Parse labels before extracting warnings so parent goals, next steps and Done never leak.
  const warning = opts.subagent && work?.text
    ? planFit(work.text, work.text.length).text.split(/(?=^Done:)/m)[0]?.match(/^Watch out: [\s\S]*/m)?.[0] ?? "" : "";
  const resume = opts.subagent ? cutToTokens(warning.replace(/\s+/g, " ").trim(), 40) : resumeText(work);
  const candidates = cardCandidates(notes, project);
  const ranked = rankForCard(candidates, project, opts.subagent ? resume : work?.text ?? "", now, home, opts.prompt);
  const allKits = opts.subagent ? [] : loadKits(home);
  const fresh = allKits.length > 0 && !resume && !notes.some((n) => n.project === project.id) && freshRoot(project.root);
  const kits = kitsLine(fresh ? allKits : kitsFor(allKits, project), opts.tools === true);
  const pending = pendingCount(home, project.id);
  const head = `Brain · ${cutToTokens(project.id.replace(/[\r\n]/g, " "), 16)} — what prior sessions learned; the repo wins on conflict`;
  const tail = [kits, pending ? `${pending} proposal${pending === 1 ? "" : "s"} waiting → \`brain review\`` : "", footer(opts.tools === true, opts.subagent === true)].filter(Boolean);
  const lines = [head];
  const room = (extra: string[] = []): number => CARD_BUDGET * 4 - [...lines, ...extra, ...tail].join("\n").length - 1;
  if (resume) {
    const text = cutToTokens(resume, Math.floor(room() / 4));
    if (text.trim()) lines.push(text);
  }
  let count = 0;
  for (const note of ranked) {
    const label = count ? [] : ["Known here:"];
    const line = noteLine(note, room(label));
    if (!line) continue;
    lines.push(...label, line);
    if (++count === CARD_NOTES) break;
  }
  if (lines.length === 1 && !kits && !pending) return "";
  const card = [...lines, ...tail].join("\n");
  return estimateTokens(card) <= CARD_BUDGET ? card : "";
}
