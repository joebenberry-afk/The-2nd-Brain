/** Small shared helpers. Node built-ins only. */
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Rough token count used for every budget: ceil(chars / 4). */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/** Cut `text` to at most `budget` tokens, ending with "…" when cut, on a word end when one is near. */
export function cutToTokens(text: string, budget: number): string {
  const max = Math.floor(budget) * 4;
  if (max <= 0) return "";
  if (text.length <= max) return text;
  const cut = text.slice(0, Math.max(0, max - 1));
  // "…upload the latest 2nd brai…" reads as noise; drop the partial word unless that loses much.
  const space = /\s/.test(text[cut.length] ?? "") ? cut.length : cut.search(/\s\S*$/);
  return (space > cut.length / 2 && space >= cut.length - 24 ? cut.slice(0, space) : cut).trimEnd() + "…";
}

/** ISO-8601 UTC time at second precision, e.g. 2026-09-27T10:00:00Z. */
export function nowIso(date: Date = new Date()): string {
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * Lowercase slug: accents removed, runs of anything but letters and digits (of any script) become
 * "-", at most 64 characters. "The 2nd Brain!" → "the-2nd-brain", "Café" → "cafe", "проект" stays.
 */
export function slug(value: string): string {
  const s = Array.from(
    value
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, ""),
  )
    .slice(0, 64)
    .join("")
    .replace(/-+$/g, "");
  return s || "default";
}

/** A tag as stored and compared: trimmed, lower-case, spaces as "-" ("TypeScript" → "typescript", "c++" stays). */
export function tagKey(tag: string): string {
  return tag.trim().toLowerCase().replace(/\s+/g, "-");
}

/** Normalized, de-duplicated tags, in first-seen order. */
export function tagList(tags: readonly string[]): string[] {
  return [...new Set(tags.map(tagKey).filter(Boolean))];
}

/** Random id with a prefix, e.g. n-3f9a2c1b7d. */
export function randomId(prefix: string): string {
  return `${prefix}-${randomBytes(5).toString("hex")}`;
}

/**
 * Run a file operation, retrying briefly while it fails with EPERM, EACCES or EBUSY: on Windows
 * antivirus, the indexer or a preview pane holds files for a moment. Any other error is rethrown.
 */
export function retrying<T>(fn: () => T): T {
  for (let attempt = 0; ; attempt++) {
    try {
      return fn();
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (attempt >= 10 || !(code === "EPERM" || code === "EACCES" || code === "EBUSY")) throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
    }
  }
}

/**
 * Write a file atomically (temp file + rename), creating parent directories. A held target is
 * retried (see retrying), and the temp file is never left behind.
 */
export function writeAtomic(path: string, text: string): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.${randomBytes(3).toString("hex")}.tmp`;
  writeFileSync(tmp, text, "utf8");
  try {
    retrying(() => renameSync(tmp, path));
  } catch (error) {
    rmSync(tmp, { force: true });
    throw error;
  }
}

/** The checkout this package lives in (brain/src/util.ts → repo root). */
export const PACKAGE_HOME = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * The Brain home: an explicit path, else SECOND_BRAIN_HOME, else the checkout this package lives
 * in when it holds a `notes/` directory. Null when none applies, or when the given path does not
 * exist (a typo would otherwise answer "no match" and write notes nothing reads).
 */
export function findHome(explicit?: string, env: NodeJS.ProcessEnv = process.env): string | null {
  const given = explicit || env.SECOND_BRAIN_HOME?.trim();
  if (given) return existsSync(resolve(given)) ? resolve(given) : null;
  return existsSync(join(PACKAGE_HOME, "notes")) ? PACKAGE_HOME : null;
}

/** Why findHome returned null, naming a given path that does not exist. */
export function noHome(explicit?: string, env: NodeJS.ProcessEnv = process.env): string {
  const given = explicit || env.SECOND_BRAIN_HOME?.trim();
  return given ? `Brain home ${resolve(given)} does not exist (check SECOND_BRAIN_HOME or --home)` : "no Brain home (set SECOND_BRAIN_HOME)";
}
