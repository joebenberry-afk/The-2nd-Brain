/** Working state that survives compaction, per project. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cutToTokens, nowIso, writeAtomic } from "./util.ts";
import { parseFrontmatter } from "./notes.ts";
import { scrub } from "./scrub.ts";

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

/** Label-aware truncation: a long Done must never crowd out a late Next. */
function planText(text: string, budget: number): string {
  const labels = [...text.matchAll(/(?:^|[\n/.;·]\s*|\s+)(Goal|Done|Next|Watch out):\s*|(?:^|[\n/·]\s*)(Goal|Done|Next|Watch out)\s+/gi)];
  if (!labels.length) return cutToTokens(text, budget);
  const parts = labels.map((match, i) => ({
    label: (match[1] ?? match[2]!).toLowerCase(),
    text: text.slice(match.index! + match[0].length, labels[i + 1]?.index ?? text.length).trim(),
  }));
  const lines: string[] = [];
  let remaining = budget * 4;
  for (const label of ["goal", "next", "watch out", "done"]) {
    const value = parts.filter(part => part.label === label).map(part => part.text).join(" ");
    if (!value || remaining < label.length + 5) continue;
    const line = cutToTokens(`${label[0]!.toUpperCase()}${label.slice(1)}: ${value}`, Math.floor(Math.min(remaining, budget * 2) / 4));
    lines.push(line);
    remaining -= line.length + 1;
  }
  return lines.join("\n");
}

/** Write work text (agent text, drops auto section). Throws WorkError on empty text. */
export function writeWork(home: string, project: string, text: string): Work {
  const trimmed = scrub(text, { longRuns: false }).text.trim();
  if (!trimmed) throw new WorkError("empty work text");

  const cut = trimmed.length <= WORK_BUDGET * 4 ? trimmed : planText(trimmed, WORK_BUDGET);
  const at = nowIso();
  const frontmatter = `---\nat: ${at}\n---`;
  const content = `${frontmatter}\n\n${cut}\n`;

  const path = workPath(home, project);
  writeAtomic(path, content);

  return readWork(home, project)!;
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

/** Full working-state display; plan and observations retain their own timestamps. */
export function resumeText(work: Work | null): string {
  if (!work || (!work.text && !work.auto)) return "";
  const parts = work.text ? [planHeading(work), work.text] : ["Where we left off:"];
  if (work.auto) parts.push(`Auto (${timestamp(work.autoAt)}):`, work.auto);
  return parts.join("\n");
}

/** The complete compaction injection, including labels, is at most 150 estimated tokens. */
export function renderResume(work: Work | null, _now?: Date): string {
  if (!work || (!work.text && !work.auto)) return "";
  const parts = work.text ? [planHeading(work), planText(work.text, 100)] : ["Where we left off:"];
  if (work.auto) parts.push(`Auto (${timestamp(work.autoAt)}):`, work.auto);
  return cutToTokens(parts.join("\n"), WORK_BUDGET);
}

