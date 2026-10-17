/** Small shared helpers. Node built-ins only. */
import { randomBytes } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, statSync, writeFileSync, writeSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
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

/** Block this thread for `ms` milliseconds (the callers are synchronous). */
function pause(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
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
      pause(50);
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

/** Another process held a claim for the whole bounded wait; the error identifies its pid and file. */
export class ClaimError extends Error {}

/** Where claim files live: local derived state, never committed or synced. */
export function claimPath(home: string, name: string): string {
  return join(home, "state", "locks", name);
}

/** Longest a caller waits for a claim: a held one is a read-modify-write of milliseconds. */
const CLAIM_WAIT_MS = 3_000;
/** Holds are synchronous writes of milliseconds; this also bounds recovery from pid reuse or failed cleanup. */
const CLAIM_STALE_MS = 15_000;
/** Claims this process holds, so a nested request for the same one runs instead of waiting for itself. */
const HELD = new Set<string>();

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** A claim's token is `<pid>.<random>`. */
const CLAIM_OWNER = /^([1-9]\d*)\./;

/**
 * A dead owner, an unheld claim from this process, or any record older than CLAIM_STALE_MS is
 * abandoned. The age bound handles reused pids and live hosts whose earlier release failed.
 */
function abandoned(file: string, owner: string): boolean {
  const pid = Number(CLAIM_OWNER.exec(owner)?.[1]);
  return Date.now() - statSync(file).mtimeMs > CLAIM_STALE_MS
    || (pid > 0 && (pid === process.pid ? !HELD.has(resolve(file)) : !alive(pid)));
}

/** Create `file` exclusively holding `token`; EEXIST when another process holds the claim. */
function createClaim(file: string, token: string): void {
  const fd = openSync(file, "wx");
  try {
    writeSync(fd, token);
  } catch (error) {
    closeSync(fd);
    rmSync(file, { force: true });
    throw error;
  }
  closeSync(fd);
}

function release(file: string, token: string): void {
  try {
    if (readFileSync(file, "utf8") === token) retrying(() => rmSync(file, { force: true }));
  } catch {
    // Already reclaimed, or held by a scanner: an unheld own-pid claim or an expired one is recoverable.
  }
}

/**
 * Reclaim under an exclusive gate, taking the abandonment verdict afresh so a replacement claim
 * survives. Gates use the same bounded lifetime as claims. A held or unreadable file is retried
 * within acquire's deadline.
 */
function reclaim(file: string): boolean {
  const gate = `${file}.reclaim`;
  const token = `${process.pid}.${randomBytes(6).toString("hex")}`;
  try {
    retrying(() => createClaim(gate, token));
  } catch (error) {
    try {
      if ((error as NodeJS.ErrnoException).code === "EEXIST" && abandoned(gate, readFileSync(gate, "utf8"))) rmSync(gate, { force: true });
    } catch {
      // the gate was released meanwhile
    }
    return false;
  }
  try {
    if (!abandoned(file, readFileSync(file, "utf8"))) return false;
    retrying(() => rmSync(file, { force: true }));
    return true;
  } catch {
    return false; // gone already (the next attempt creates it) or unreadable
  } finally {
    release(gate, token);
  }
}

function acquire(file: string, waitMs: number): string {
  mkdirSync(dirname(file), { recursive: true });
  const token = `${process.pid}.${randomBytes(6).toString("hex")}`;
  const deadline = Date.now() + waitMs;
  for (;;) {
    try {
      retrying(() => createClaim(file, token));
      return token;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
    if (reclaim(file)) continue;
    if (Date.now() >= deadline) {
      let pid = "unknown";
      try { pid = CLAIM_OWNER.exec(readFileSync(file, "utf8"))?.[1] ?? pid; }
      catch { /* released meanwhile, or unreadable */ }
      throw new ClaimError(`${basename(file, ".lock")} is being changed by another Brain process (pid ${pid}); nothing was written. Try again; if no Brain command is running, delete ${file}`);
    }
    pause(10 + Math.floor(Math.random() * 15));
  }
}

/**
 * Run `fn` holding the cross-process claim `file` (a path from claimPath), so that read-modify-write
 * operations on one registry or note never interleave across processes: load, change and save all
 * inside `fn`. A claim is a file created exclusively and holding its owner's token (`<pid>.<random>`).
 * A waiter gives up after `waitMs` with a ClaimError identifying the holder and claim path. A dead
 * owner's claim, an unheld claim from this process, or any claim older than CLAIM_STALE_MS is
 * reclaimed, so a crash, reused pid or failed release cannot wedge later writes indefinitely.
 * Claims nest for the same file within one process. `fn` must be synchronous and finish well
 * within CLAIM_STALE_MS.
 */
export function withClaim<T>(file: string, fn: () => T, waitMs: number = CLAIM_WAIT_MS): T {
  const key = resolve(file);
  if (HELD.has(key)) return fn();
  const token = acquire(key, waitMs);
  HELD.add(key);
  try {
    return fn();
  } finally {
    HELD.delete(key);
    release(key, token);
  }
}

/** Several claims at once, always taken in the same (sorted) order so two writers cannot wait on each other. */
export function withClaims<T>(files: readonly string[], fn: () => T): T {
  const [first, ...rest] = [...new Set(files)].sort();
  return first === undefined ? fn() : withClaim(first, () => withClaims(rest, fn));
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
