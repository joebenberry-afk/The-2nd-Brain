/** Per-project working state for the next session's card. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cutToTokens, estimateTokens, nowIso, writeAtomic } from "./util.ts";
import { parseFrontmatter } from "./notes.ts";
import { scrub } from "./scrub.ts";
import { anchorSection, bareAnchor } from "./docs.ts";
import { normalizePath, projectDocPath, worktreeSpelling } from "./project.ts";

export const WORK_BUDGET = 150;
export const AUTO_BUDGET = 80;

export interface Work {
  project: string;
  /** When the agent last wrote the plan (the text). Sync conflicts are won by the newer plan. */
  at: string;
  /** When the auto section was last refreshed (compaction, session end); "" when never. */
  autoAt: string;
  text: string;
  auto: string;
  path: string;
  /** Set by writeWork when the written text was over budget: its length in chars before the cut. */
  cutFrom?: number;
}

export interface AutoFields {
  edited?: string[];
  failure?: string;
  ask?: string;
}

export class WorkError extends Error {}

/** Path to the work file for a project: <home>/work/<project>.md */
export function workPath(home: string, project: string): string {
  return join(home, "work", `${project}.md`);
}

/** Read a work file; return null when missing, unreadable, or unparseable. */
function readPlan(home: string, project: string): Work | null {
  const path = workPath(home, project);
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    return null;
  }
  let fields: Map<string, string | string[]>;
  let body: string;
  try {
    ({ fields, body } = parseFrontmatter(raw));
  } catch {
    // Written by hand, or left by a merge: the whole file is the plan. It is shown, and never
    // replaced by an auto refresh.
    const text = raw.replace(/^\uFEFF/, "").trim();
    return text ? { project, at: "", autoAt: "", text, auto: "", path } : null;
  }
  const scalar = (key: string) => {
    const v = fields.get(key);
    return typeof v === "string" ? v : "";
  };
  const at = scalar("at");
  const autoAt = scalar("auto_at");
  // Only a file the extension refreshed (auto_at set) has an auto section, and it is the last
  // "## auto" heading — a plan that itself contains "## auto" is never split.
  const lines = body.split("\n");
  const autoIndex = autoAt ? lines.map((l) => l.trim()).lastIndexOf("## auto") : -1;
  const text = (autoIndex < 0 ? lines : lines.slice(0, autoIndex)).join("\n").trim();
  const auto = autoIndex < 0 ? "" : lines.slice(autoIndex + 1).join("\n").trim();
  return { project, at, autoAt, text, auto, path };
}

/** Merge the canonical agent plan with machine-local observations; old inline auto remains readable. */
export function readWork(home: string, project: string): Work | null {
  const plan = readPlan(home, project);
  try {
    const { fields, body } = parseFrontmatter(readFileSync(join(home, "state", "work", `${project}.auto.md`), "utf8"));
    const stamp = fields.get("at");
    return { project, path: workPath(home, project), at: plan?.at ?? "", text: plan?.text ?? "", autoAt: typeof stamp === "string" ? stamp : "", auto: body.trim() };
  } catch {
    return plan;
  }
}

/** A field cut shorter than this reads as noise ("Watch out: ca…"): drop it instead. */
const MIN_FIELD_CHARS = 40;

/**
 * Label-aware truncation: a long Done must never crowd out a late Next; text before the first
 * label leads.
 */
export function planFit(text: string, budget: number): string {
  const labels = [...text.matchAll(/(?:^|[\n/.;·]\s*|\s+)(Goal|Done|Next|Watch out):\s*|(?:^|[\n/·]\s*)(Goal|Done|Next|Watch out)\s+/gi)];
  if (!labels.length) return cutToTokens(text, budget);
  const parts = labels.map((match, i) => ({
    label: (match[1] ?? match[2]!).toLowerCase(),
    text: text.slice(match.index! + match[0].length, labels[i + 1]?.index ?? text.length).trim(),
  }));
  const preamble = text.slice(0, labels[0]!.index).trim();
  const lines: string[] = [];
  let remaining = budget * 4;
  for (const label of ["", "goal", "next", "watch out", "done"]) {
    const value = label ? parts.filter(part => part.label === label).map(part => part.text).join(" ") : preamble;
    if (!value) continue;
    const full = label ? `${label[0]!.toUpperCase()}${label.slice(1)}: ${value}` : value;
    const line = cutToTokens(full, Math.floor(Math.min(remaining, budget * 2) / 4));
    if (line.length - (full.length - value.length) < Math.min(value.length, MIN_FIELD_CHARS)) continue;
    lines.push(line);
    remaining -= line.length + 1;
  }
  return lines.join("\n");
}

/** Write work text (agent text, drops auto section). Throws WorkError on empty text. */
export function writeWork(home: string, project: string, text: string): Work {
  const trimmed = scrub(text, { longRuns: false }).text.trim();
  if (!trimmed) throw new WorkError("empty work text");

  const over = trimmed.length > WORK_BUDGET * 4;
  // See: anchors are kept whole (a cut one renders as "anchor missing"); the rest fits around them.
  // They get at most half the budget, so Goal and Next are never crowded out: whole lines while they
  // fit, the rest dropped. Only a first line longer than that half is cut.
  const seeLines = trimmed.match(/^See:.*$/gm) ?? [];
  const whole = seeLines.filter((_, i) => estimateTokens(seeLines.slice(0, i + 1).join("\n")) <= WORK_BUDGET / 2);
  const see = whole.length ? whole.join("\n") : cutToTokens(seeLines.join("\n"), WORK_BUDGET / 2);
  const cut = !over ? trimmed
    : cutToTokens([planFit(trimmed.replace(/^See:.*$\n?/gm, "").trim(), WORK_BUDGET - (see ? estimateTokens(see) + 1 : 0)), see].filter(Boolean).join("\n"), WORK_BUDGET);
  const at = nowIso();
  const frontmatter = `---\nat: ${at}\n---`;
  const content = `${frontmatter}\n\n${cut}\n`;

  const path = workPath(home, project);
  writeAtomic(path, content);

  return { ...readWork(home, project)!, ...(over ? { cutFrom: trimmed.length } : {}) };
}

/**
 * A section named without its file ("plan §8.8") sends the next session searching for it; a
 * See: anchor or any path in the text does not. Returns the reference to name in the warning.
 */
function unanchoredSection(text: string): string | undefined {
  if (/^See:/m.test(text) || /\w\/\w|[\w-]+\.[a-z][a-z0-9]{0,4}\b/i.test(text)) return undefined;
  return text.match(/§\s*\d+(?:\.\d+)*|\bsection\s+\d+(?:\.\d+)*/i)?.[0];
}

/** Acknowledge the stored plan without predicting what the host keeps in context. */
export function stateSaved(work: Work): string {
  const cut = work.cutFrom ? `; cut from ${work.cutFrom} chars to fit ${WORK_BUDGET} tokens — keep Goal/Next short` : "";
  const section = unanchoredSection(work.text);
  const anchor = section ? `; "${section}" names no file — add See: path#heading so the next session need not search for it` : "";
  return `state saved (${estimateTokens(work.text)} tokens)${cut}${anchor}`;
}

/**
 * Format auto fields as lines. Each field has its own share of AUTO_BUDGET (edited 80 chars,
 * failure 28 tokens, ask 24 tokens), so a long file list never pushes the last ask out.
 */
export function formatAuto(fields: AutoFields): string {
  const failure = fields.failure && scrub(fields.failure).text.replace(/\s+/g, " ").trim();
  const ask = fields.ask && scrub(fields.ask, { longRuns: false }).text.replace(/\s+/g, " ").trim();
  const lines: string[] = [];

  // Edited: the most recent unique files that fit, in last-occurrence order
  const latest = [...new Map((fields.edited ?? []).filter(Boolean).map((item, i) => [item, i] as const)).entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([item]) => item);
  const shown: string[] = [];
  for (const item of latest.slice(0, 8)) {
    const more = latest.length - shown.length - 1;
    if (shown.length && `- edited: ${[item, ...shown].join(", ")}${more ? ` +${more} more` : ""}`.length > 80) break;
    shown.unshift(item);
  }
  if (shown.length) {
    const tail = latest.length > shown.length ? ` +${latest.length - shown.length} more` : "";
    const list = shown.join(", ");
    // One path longer than the line keeps its end: the file name matters more than the folders.
    const room = 80 - "- edited: ".length - tail.length;
    lines.push(`- edited: ${list.length > room ? `…${list.slice(-(room - 1))}` : list}${tail}`);
  }
  if (failure) lines.push(`- last failure: ${cutToTokens(failure, 28)}`);
  if (ask) lines.push(`- last ask: ${cutToTokens(ask, 24)}`);

  return cutToTokens(lines.join("\n"), AUTO_BUDGET);
}

/** Write observations only to local state: never read-modify-write the synced plan. */
export function writeAuto(home: string, project: string, fields: AutoFields): Work | null {
  const formatted = formatAuto(fields);
  if (!formatted) return readWork(home, project);
  writeAtomic(join(home, "state", "work", `${project}.auto.md`), `---\nat: ${nowIso()}\n---\n\n${formatted}\n`);
  return readWork(home, project);
}

function timestamp(at: string): string {
  return at ? `${at.slice(0, 16).replace("T", " ")} UTC` : "time unknown";
}

function planHeading(work: Work): string {
  const stale = Date.parse(work.autoAt) - Date.parse(work.at) > 3 * 86400000;
  return `${stale ? "plan may be stale — " : ""}Where we left off (${timestamp(work.at)}):`;
}

/** Resolve See lines at display time, preserving the agent-owned delta around them. */
function anchoredText(text: string, root: string | null, budget: number, docRoot?: string, registered: string[] = []): string {
  const pattern = /^See:[ \t]*(.+?)[ \t]*$/gm;
  const count = [...text.matchAll(pattern)].length;
  if (!count) return text;
  const room = Math.floor((budget * 4 - text.replace(pattern, "").length) / Math.max(1, count) / 4);
  const docs = new Set(registered.map(normalizePath));
  return cutToTokens(text.replace(pattern, (_line, anchor: string) => {
    const bare = bareAnchor(anchor);
    // A repo inside a declared folder: the anchor may be spelled against the folder (as recall and
    // docs list print a doc outside the repo). A registered doc there wins, as docFile resolves it.
    const inFolder = docRoot ? projectDocPath(docRoot, bare.slice(0, Math.max(0, bare.indexOf("#")))) : undefined;
    const [first, second] = inFolder && docs.has(normalizePath(inFolder)) ? [docRoot, root] : [root, docRoot];
    // In a linked worktree, a folder-spelled anchor reads the worktree's own copy when it has one;
    // a heading missing there is missing, not read from main's older copy.
    const hash = bare.indexOf("#");
    const own = hash > 0 ? worktreeSpelling(root, docRoot, bare.slice(0, hash)) : undefined;
    const section = own && projectDocPath(root, own) ? anchorSection(root!, own + bare.slice(hash))
      : (first ? anchorSection(first, anchor) : undefined) ?? (second ? anchorSection(second, anchor) : undefined);
    const rendered = section ? `${bare.slice(0, bare.indexOf("#"))} › ${section.heading}:\n${section.text}` : `anchor missing: ${anchor}`;
    return cutToTokens(rendered, Math.max(0, room));
  }), budget);
}

/** Full working-state display; plan and observations retain their own timestamps. */
export function workText(work: Work | null, root: string | null = null, docRoot?: string, registered: string[] = []): string {
  if (!work || (!work.text && !work.auto)) return "";
  const parts = work.text ? [planHeading(work), anchoredText(work.text, root, WORK_BUDGET, docRoot, registered)] : ["Where we left off:"];
  if (work.auto) parts.push(`Auto (${timestamp(work.autoAt)}):`, work.auto);
  return parts.join("\n");
}
