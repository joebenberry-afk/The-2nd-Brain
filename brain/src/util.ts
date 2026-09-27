/** Small shared helpers. Node built-ins only. */
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Rough token count used for every budget: ceil(chars / 4). */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/** Cut `text` to at most `budget` tokens, ending with "…" when cut. */
export function cutToTokens(text: string, budget: number): string {
  const max = budget * 4;
  if (text.length <= max) return text;
  return text.slice(0, Math.max(0, max - 1)).trimEnd() + "…";
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

/** Write a file atomically (temp file + rename), creating parent directories. */
export function writeAtomic(path: string, text: string): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.${randomBytes(3).toString("hex")}.tmp`;
  writeFileSync(tmp, text, "utf8");
  renameSync(tmp, path);
}

/** The checkout this package lives in (brain/src/util.ts → repo root). */
export const PACKAGE_HOME = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * The Brain home: an explicit path, else SECOND_BRAIN_HOME, else the checkout this package lives
 * in when it holds a `notes/` directory. Null when none applies.
 */
export function findHome(explicit?: string, env: NodeJS.ProcessEnv = process.env): string | null {
  if (explicit) return resolve(explicit);
  const fromEnv = env.SECOND_BRAIN_HOME?.trim();
  if (fromEnv) return resolve(fromEnv);
  return existsSync(join(PACKAGE_HOME, "notes")) ? PACKAGE_HOME : null;
}
