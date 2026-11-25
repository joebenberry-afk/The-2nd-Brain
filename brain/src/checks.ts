/**
 * Dated checks (V6 §7.10): a note that agents are being shown gets its claim compared with the
 * world by an agent, offline, and the result is stored on the note with its date. Nothing here
 * runs at read time and nothing blocks; recall only prints what the last check found.
 */
import { checkCurrent, GLOBAL, headline, isActive, VERDICTS, type Note, type Verdict } from "./notes.ts";
import { noteUsage } from "./telemetry.ts";

/** A check older than this is due again. */
export const RECHECK_DAYS = 30;
/** Notes shown within this window are worth a check. */
export const USED_DAYS = 14;
export const WHY_CHARS = 300;

const DAY = 86_400_000;

export interface Due {
  note: Note;
  /** Times recall, the card or a fix showed it in the window. */
  uses: number;
}

/** Public active notes shown in the window whose current text has no check newer than RECHECK_DAYS, most shown first. */
export function dueChecks(home: string, notes: Note[], opts: { days?: number; now?: Date } = {}): Due[] {
  const now = opts.now ?? new Date();
  const usage = noteUsage(home, opts.days ?? USED_DAYS, now).notes;
  const due: Due[] = [];
  for (const note of notes) {
    const use = usage.get(note.id);
    if (!use || note.private || !isActive(note)) continue;
    const check = checkCurrent(note);
    if (check && now.getTime() - Date.parse(check.at) < RECHECK_DAYS * DAY) continue;
    due.push({ note, uses: use.recalled + use.opened + use.carded + use.fired });
  }
  return due.sort((a, b) => b.uses - a.uses || a.note.id.localeCompare(b.note.id));
}

/** `<id> <verdict>[: <why>]`; a verdict other than holds must say what it saw. */
export function parseCheck(text: string): { id: string; verdict: Verdict; why: string } | string {
  const match = /^\s*(\S+)\s+([a-z]+)\b[\s:;,.—–-]*([\s\S]*)$/i.exec(text);
  const verdict = match?.[2]!.toLowerCase() as Verdict | undefined;
  if (!match || !verdict || !VERDICTS.includes(verdict)) return `use brain checked "<id> ${VERDICTS.join("|")}: <what you saw, with the path or command>"`;
  const why = match[3]!.replace(/\s+/g, " ").trim().slice(0, WHY_CHARS);
  if (!why && verdict !== "holds") return `${verdict} needs what you saw: brain checked "${match[1]} ${verdict}: <one line, with the path or command>"`;
  return { id: match[1]!, verdict, why };
}

export const PROTOCOL = [
  "Check each statement against what is true today, read-only. Read it with `brain recall <id>`, then record one verdict:",
  "  holds        you saw the file, commit or output that shows the main claim",
  "  moved        true when written, no longer true; say what changed",
  "  wrong        evidence shows it was not true when written",
  "  uncheckable  cannot be decided read-only here (a measurement, a preference, a past event without trace)",
  "Judge the main claim, not trivia. Do not trust the note, its evidence list or other notes; look.",
  "  brain checked \"<id> <verdict>: <what you saw, with the path or command>\"",
].join("\n");

/** The worklist an agent works through, grouped by where to look. */
export function renderDue(due: Due[], limit: number, rootOf: (project: string) => string | null): string {
  if (!due.length) return "no checks due";
  const shown = due.slice(0, limit);
  const groups = new Map<string, Due[]>();
  for (const item of shown) groups.set(item.note.project, [...(groups.get(item.note.project) ?? []), item]);
  const lines = [PROTOCOL, ""];
  for (const [project, items] of groups) {
    const root = project === GLOBAL ? "this machine" : rootOf(project) ?? "checkout not known from here: run brain checks inside it";
    lines.push(`${project} · ${root}`);
    for (const { note, uses } of items) lines.push(`  ${note.id}  shown ${uses}×${note.check ? `, last ${note.check.verdict} ${note.check.at.slice(0, 10)}${checkCurrent(note) ? "" : " (edited since)"}` : ""}  ${headline(note).slice(0, 100)}`);
  }
  if (due.length > shown.length) lines.push(`+${due.length - shown.length} more (--limit N)`);
  return lines.join("\n");
}
