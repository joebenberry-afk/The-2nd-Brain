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
export function readWork(home: string, project: string): Work | null {
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

/** Write work text (agent text, drops auto section). Throws WorkError on empty text. */
export function writeWork(home: string, project: string, text: string): Work {
  const trimmed = scrub(text, { longRuns: false }).text.trim();
  if (!trimmed) throw new WorkError("empty work text");

  const cut = cutToTokens(trimmed, WORK_BUDGET);
  const at = nowIso();
  const frontmatter = `---\nat: ${at}\n---`;
  const content = `${frontmatter}\n\n${cut}\n`;

  const path = workPath(home, project);
  writeAtomic(path, content);

  return {
    project,
    at,
    autoAt: "",
    text: cut,
    auto: "",
    path,
  };
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

/** Write/update auto section. Returns updated work, or null if nothing to say and no existing file. */
export function writeAuto(home: string, project: string, fields: AutoFields): Work | null {
  const formatted = formatAuto(fields);
  if (!formatted) {
    // Nothing to say: return existing work unchanged, or null
    return readWork(home, project);
  }

  const existing = readWork(home, project);
  const text = existing?.text ?? "";

  // Refreshing the auto section does not make the plan newer: `at` moves only with the text, and a
  // file without a plan has no `at` at all (so it never wins a sync conflict against a real plan).
  const autoAt = nowIso();
  const at = text ? (existing?.at ?? autoAt) : "";
  const frontmatter = at ? `---\nat: ${at}\nauto_at: ${autoAt}\n---` : `---\nauto_at: ${autoAt}\n---`;
  const autoSection = `## auto\n${formatted}`;
  const parts = [frontmatter];
  if (text) parts.push("", text);
  parts.push("", autoSection, "");
  const content = parts.join("\n");

  const path = workPath(home, project);
  writeAtomic(path, content);

  return {
    project,
    at,
    autoAt,
    text,
    auto: formatted,
    path,
  };
}

/** Resume text for an agent (context of where we left off). */
export function resumeText(work: Work | null): string {
  if (!work || (!work.text && !work.auto)) return "";

  const latest = work.autoAt > work.at ? work.autoAt : work.at;
  const timeStr = latest.slice(0, 16).replace("T", " ");
  const prefix = `Where we left off (${timeStr} UTC):`;
  const parts = [prefix];

  if (work.text) parts.push(work.text);
  if (work.auto) parts.push(work.auto);

  return parts.join("\n");
}
