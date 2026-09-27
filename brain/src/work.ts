/** Working state that survives compaction, per project. */
import { existsSync, readFileSync } from "node:fs";
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
  if (!existsSync(path)) return null;

  try {
    const text = readFileSync(path, "utf8");
    const { fields, body } = parseFrontmatter(text);

    const atRaw = fields.get("at");
    const at = typeof atRaw === "string" ? atRaw : "1970-01-01T00:00:00Z";
    const autoAtRaw = fields.get("auto_at");
    const autoAt = typeof autoAtRaw === "string" ? autoAtRaw : "";

    // Find the "## auto" marker
    const lines = body.split("\n");
    let autoIndex = -1;
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i];
      if (line && line.trim() === "## auto") {
        autoIndex = i;
        break;
      }
    }

    let workText: string;
    let autoText: string;
    if (autoIndex === -1) {
      workText = body.trim();
      autoText = "";
    } else {
      workText = lines.slice(0, autoIndex).join("\n").trim();
      autoText = lines.slice(autoIndex + 1).join("\n").trim();
    }

    return {
      project,
      at,
      autoAt,
      text: workText,
      auto: autoText,
      path,
    };
  } catch {
    return null;
  }
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

/** Format auto fields as lines. */
export function formatAuto(fields: AutoFields): string {
  fields = {
    edited: fields.edited,
    failure: fields.failure && scrub(fields.failure).text,
    ask: fields.ask && scrub(fields.ask, { longRuns: false }).text,
  };
  const lines: string[] = [];

  // Edited: last 8 unique in last-occurrence order
  if (fields.edited && fields.edited.length > 0) {
    const seen = new Map<string, number>();
    for (let i = 0; i < fields.edited.length; i++) {
      const item = fields.edited[i];
      if (item) {
        seen.set(item, i);
      }
    }
    const unique = Array.from(seen.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .sort((a, b) => a[1] - b[1])
      .map(([v]) => v);
    if (unique.length > 0) {
      lines.push(`- edited: ${unique.join(", ")}`);
    }
  }

  // Failure
  if (fields.failure && typeof fields.failure === "string") {
    const collapsed = fields.failure.replace(/\s+/g, " ").trim();
    const cut = cutToTokens(collapsed, 50); // 50 tokens = 200 chars
    lines.push(`- last failure: ${cut}`);
  }

  // Ask
  if (fields.ask && typeof fields.ask === "string") {
    const collapsed = fields.ask.replace(/\s+/g, " ").trim();
    const cut = cutToTokens(collapsed, 40); // 40 tokens = 160 chars
    lines.push(`- last ask: ${cut}`);
  }

  const result = lines.join("\n");
  return cutToTokens(result, AUTO_BUDGET);
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

  // Refreshing the auto section does not make the plan newer: `at` moves only with the text.
  const autoAt = nowIso();
  const at = text ? (existing?.at ?? autoAt) : autoAt;
  const frontmatter = `---\nat: ${at}\nauto_at: ${autoAt}\n---`;
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
