/**
 * One local line per Brain moment, so "is this used?" is answered by data (plan rule 1).
 * `<home>/state/telemetry.jsonl`: local usage, including subagent and recall-hit data. Past 1 MiB
 * it is renamed to `telemetry.1.jsonl` (replacing the previous one): a rename, never a rewrite, so a
 * concurrent session's append lands in one file or the other and is never lost. Never throws.
 */
import { appendFileSync, mkdirSync, readFileSync, renameSync, statSync } from "node:fs";
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

const MAX_BYTES = 1_048_576;

export function logUse(home: string, use: Use, now: Date = new Date()): void {
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    const path = telemetryPath(home);
    const row = JSON.stringify({ at: nowIso(now), ...use, ms: Math.round(use.ms * 10) / 10 }) + "\n";
    try {
      if (statSync(path).size + Buffer.byteLength(row) > MAX_BYTES) renameSync(path, join(home, "state", "telemetry.1.jsonl"));
    } catch {
      // no file yet, or another session rotated it first
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
  for (const file of [join(home, "state", "telemetry.1.jsonl"), telemetryPath(home)]) {
    try {
      text += readFileSync(file, "utf8") + "\n";
    } catch {
      // either file may be missing
    }
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
