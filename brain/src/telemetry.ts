/**
 * One local line per Brain moment, so "is this used?" is answered by data (plan rule 1).
 * `<home>/state/telemetry.jsonl`: {at, kind, project, tokens, ms, session?}. Never throws.
 */
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { nowIso } from "./util.ts";

export type UseKind = "card" | "resume" | "fix" | "recall" | "note" | "state";

export interface Use {
  kind: UseKind;
  project: string;
  tokens: number;
  ms: number;
  session?: string;
}

export function telemetryPath(home: string): string {
  return join(home, "state", "telemetry.jsonl");
}

export function logUse(home: string, use: Use, now: Date = new Date()): void {
  try {
    mkdirSync(join(home, "state"), { recursive: true });
    appendFileSync(telemetryPath(home), JSON.stringify({ at: nowIso(now), ...use, ms: Math.round(use.ms * 10) / 10 }) + "\n");
  } catch {
    // telemetry must never affect the caller
  }
}

export interface Stats {
  days: number;
  sessions: number;
  byKind: Record<string, { count: number; tokens: number }>;
}

/** Usage over the last `days` days. */
export function stats(home: string, days = 7, now: Date = new Date()): Stats {
  const since = now.getTime() - days * 86_400_000;
  const byKind: Stats["byKind"] = {};
  const sessions = new Set<string>();
  let text = "";
  try {
    text = readFileSync(telemetryPath(home), "utf8");
  } catch {
    return { days, sessions: 0, byKind };
  }
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: { at?: unknown; kind?: unknown; tokens?: unknown; session?: unknown };
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (typeof row.at !== "string" || Date.parse(row.at) < since || typeof row.kind !== "string") continue;
    const slot = (byKind[row.kind] ??= { count: 0, tokens: 0 });
    slot.count += 1;
    slot.tokens += typeof row.tokens === "number" ? row.tokens : 0;
    if (typeof row.session === "string" && row.session) sessions.add(row.session);
  }
  return { days, sessions: sessions.size, byKind };
}
