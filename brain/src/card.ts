/**
 * The start card: what an agent gets on a session's first turn and again after compaction.
 *
 *   Brain · <project> — advisory memory, verify before relying on it
 *   Where we left off (…):          working state, the thing compaction would otherwise lose
 *   Known here:                      up to 5 notes, ranked for this project and the current work
 *   Kits: …                          MVP kits for this kind of project (all kits on a new project)
 *   N proposals waiting → brain review
 *   Memory: …                        how to recall, note and update the state
 *
 * Push only what is scoped: project notes and global notes that share a tag with the project.
 * Untagged global notes are reachable by recall and by known fixes, never pushed on the card.
 * Nothing to say → "" (the host adds nothing).
 */
import { pendingCount } from "./capture.ts";
import { kitsFor, loadKits, type Kit } from "./kits.ts";
import { GLOBAL, headline, type Note } from "./notes.ts";
import type { Project } from "./project.ts";
import { recall } from "./search.ts";
import { estimateTokens } from "./util.ts";
import { readWork, resumeText } from "./work.ts";

export const CARD_BUDGET = 400;
export const CARD_NOTES = 5;

const KIND_WEIGHT: Record<string, number> = { gotcha: 3, decision: 3, procedure: 2, fact: 1, note: 1 };
const DAY_MS = 86_400_000;

export interface CardOptions {
  /** The host exposes the brain_* tools (OMP); otherwise the card names the CLI. */
  tools?: boolean;
  now?: Date;
}

/** Active notes the card may push for `project`: its own, plus global notes sharing a tag. */
export function cardCandidates(notes: Note[], project: Project): Note[] {
  return notes.filter((n) => {
    if (n.retired) return false;
    if (n.project === project.id) return true;
    return n.project === GLOBAL && n.tags.length > 0 && n.tags.some((t) => project.tags.includes(t));
  });
}

/** Rank candidates: tested and actionable kinds first, recent work next, relevance to the working state on top. */
export function rankForCard(notes: Note[], candidates: Note[], project: Project, workText: string, now: Date): Note[] {
  const relevance = new Map<string, number>();
  if (workText.trim()) {
    const hits = recall(notes, workText, { project, limit: 10 });
    const top = hits[0]?.score ?? 0;
    for (const hit of hits) if (top > 0) relevance.set(hit.note.id, hit.score / top);
  }
  const score = (n: Note): number => {
    const age = (now.getTime() - Date.parse(n.at)) / DAY_MS;
    const recent = age <= 14 ? 2 : age <= 60 ? 1 : 0;
    return (n.tested ? 3 : 0) + (KIND_WEIGHT[n.kind] ?? 1) + recent + 4 * (relevance.get(n.id) ?? 0);
  };
  const scored = candidates.map((n) => ({ n, s: score(n) }));
  scored.sort((a, b) => b.s - a.s || (a.n.at < b.n.at ? 1 : a.n.at > b.n.at ? -1 : 0) || (a.n.id < b.n.id ? -1 : 1));
  return scored.map((x) => x.n);
}

function noteLine(n: Note): string {
  return `- [${n.kind}${n.tested ? ", tested" : ""}] ${headline(n)} (${n.id})`;
}

function kitsLine(kits: Kit[], fresh: boolean): string {
  if (!kits.length) return "";
  const names = kits.slice(0, 5).map((k) => k.name).join(", ");
  return fresh
    ? `New project? MVP kits: ${names} → \`brain kit show <name>\``
    : `Kits for this kind of project: ${names} → \`brain kit show <name>\``;
}

function footer(tools: boolean): string {
  return tools
    ? "Memory: brain_recall(query) · brain_note(text) · brain_state(goal/done/next — update it when the plan changes)"
    : 'Memory: `brain recall "<query>"` · `brain note "<text>"` · `brain state "<goal/done/next>"` (update it when the plan changes)';
}

/** Build the card for `project` from the notes already loaded; "" when there is nothing to say. */
export function renderCard(home: string, notes: Note[], project: Project, opts: CardOptions = {}): string {
  const now = opts.now ?? new Date();
  const work = readWork(home, project.id);
  const resume = resumeText(work);
  const candidates = cardCandidates(notes, project);
  const ranked = rankForCard(notes, candidates, project, work?.text ?? "", now);
  const allKits = loadKits(home);
  const fresh = !resume && candidates.length === 0;
  const kits = fresh ? allKits : kitsFor(allKits, project);
  const pending = pendingCount(home, project.id);
  if (!resume && !ranked.length && !kits.length && !pending) return "";

  const head = `Brain · ${project.id} — advisory memory, verify before relying on it`;
  const tail = [kitsLine(kits, fresh), pending ? `${pending} proposal${pending === 1 ? "" : "s"} waiting → \`brain review\`` : "", footer(opts.tools === true)].filter(Boolean);
  const lines = [head];
  const fits = (extra: string[]): boolean => estimateTokens([...lines, ...extra, ...tail].join("\n")) <= CARD_BUDGET;
  if (resume && fits([resume])) lines.push(resume);
  const known = ranked.slice(0, CARD_NOTES).map(noteLine);
  if (known.length && fits(["Known here:", known[0] as string])) {
    lines.push("Known here:");
    for (const line of known) {
      if (!fits([line])) break;
      lines.push(line);
    }
  }
  lines.push(...tail);
  return lines.join("\n");
}
