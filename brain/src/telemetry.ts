/**
 * One local line per Brain moment, so "is this used?" is answered by data (plan rule 1).
 * `<home>/state/telemetry.jsonl`: local bounded usage, including subagent and recall-hit data. Never throws.
 */
import { appendFileSync, closeSync, existsSync, fstatSync, mkdirSync, openSync, readFileSync, readSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { nowIso } from "./util.ts";

export type UseKind = "card" | "resume" | "fix" | "recall" | "note" | "state";

export interface Use {
  kind: UseKind;
  project: string;
  tokens: number;
  ms: number;
  session?: string;
  sub?: boolean;
  hits?: number;
}

export function telemetryPath(home: string): string {
  return join(home, "state", "telemetry.jsonl");
}

export function logUse(home: string, use: Use, now: Date = new Date()): void {
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    const path = telemetryPath(home);
    const row = JSON.stringify({ at: nowIso(now), ...use, ms: Math.round(use.ms * 10) / 10 }) + "\n";
    const maxBytes = 1_048_576;
    if (Buffer.byteLength(row) > maxBytes / 2) return;
    if (existsSync(path) && statSync(path).size + Buffer.byteLength(row) > maxBytes) {
      const fd = openSync(path, "r");
      let tail: Buffer;
      try {
        const size = fstatSync(fd).size;
        tail = Buffer.alloc(Math.min(size, maxBytes / 2));
        const read = readSync(fd, tail, 0, tail.length, size - tail.length);
        tail = tail.subarray(0, read);
      } finally {
        closeSync(fd);
      }
      // Start after a newline, never in the middle of JSON or a UTF-8 code point.
      const newline = tail.indexOf(10);
      writeFileSync(path, newline < 0 ? "" : tail.subarray(newline + 1));
    }
    appendFileSync(path, row);
  } catch {
    // telemetry must never affect the caller
  }
}

export interface Stats {
  days: number;
  sessions: number;
  byKind: Record<string, { count: number; tokens: number }>;
  cards: { main: number; sub: number };
  recalls: { calls: number; measured: number; matched: number };
}

/** Usage over the last days; old recall rows without hit counts are unmeasured, not misses. */
export function stats(home: string, days = 7, now: Date = new Date()): Stats {
  const since = now.getTime() - days * 86_400_000;
  const byKind: Stats["byKind"] = Object.create(null);
  const cards = { main: 0, sub: 0 };
  const recalls = { calls: 0, measured: 0, matched: 0 };
  const sessions = new Set<string>();
  let text = "";
  try {
    text = readFileSync(telemetryPath(home), "utf8");
  } catch {
    return { days, sessions: 0, byKind, cards, recalls };
  }
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: { at?: unknown; kind?: unknown; tokens?: unknown; session?: unknown; sub?: unknown; hits?: unknown } | null;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (!row || typeof row.at !== "string" || !Number.isFinite(Date.parse(row.at)) || Date.parse(row.at) < since || typeof row.kind !== "string") continue;
    const slot = (byKind[row.kind] ??= { count: 0, tokens: 0 });
    slot.count += 1;
    slot.tokens += typeof row.tokens === "number" ? row.tokens : 0;
    if (row.kind === "card") cards[row.sub === true ? "sub" : "main"] += 1;
    if (row.kind === "recall") {
      recalls.calls += 1;
      if (typeof row.hits === "number" && Number.isInteger(row.hits) && row.hits >= 0) {
        recalls.measured += 1;
        if (row.hits > 0) recalls.matched += 1;
      }
    }
    if (typeof row.session === "string" && row.session) sessions.add(row.session);
  }
  return { days, sessions: sessions.size, byKind, cards, recalls };
}
