/**
 * Optional local scorer and judge (Tora: EmbeddingGemma 2 for cosines, Qwen3-Reranker-0.6B for
 * relevance) for recall and the start card. A live Tora publishes `<tora_pid>.json` (port, bearer
 * token, pid, host_pid, started) in `%LOCALAPPDATA%\tora\sessions`. Every failure yields undefined,
 * so the caller's answer is exactly what it would be without Tora.
 * Nothing here logs or rethrows: an error could carry the bearer token.
 */
import { readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * A cosine-prefiltered candidate for Jev must score this; local /judge skips this prefilter.
 * On 566 real queries (2026-10-15, three blind judges per changed answer), BM25-supported notes
 * Jev kept were right 15/15 at ≥0.74 and 11/16 below; fitted on the first half (highest wrong 0.736),
 * the floor held 6/6 on the second.
 */
export const TORA_FLOOR = 0.74;
/** At most this many gated-out BM25 candidates join a recall judge request. */
export const TORA_ADD = 2;
/**
 * Tora checks only notes BM25 ranked this high that the lexical answer left out: notes only Tora
 * finds were right 19 of 31 times when Jev kept them, which no Jev bar could separate.
 */
export const TORA_SUPPORT = 3;
/** A cold first call (model load) takes seconds; recall does not wait for it. */
export const TORA_TIMEOUT_MS = 800;
/** The start card waits less: warm scoring of a project's notes takes 20-70 ms; BM25 ranks otherwise. */
export const TORA_CARD_TIMEOUT_MS = 300;

export interface ToraScores { scores: Map<string, number>; ms: number }
export type ToraScorer = ((query: string, notes: { id: string; text: string }[], timeoutMs?: number) => Promise<ToraScores | undefined>) & { attempts?: ToraAttempt[] };

export interface ToraSession { port: number; token: string; hostPid: number | null; started: number }

export interface ToraAttempt { route: "/score" | "/judge"; outcome: "ok" | "no-session" | "refused" | "timeout" | "malformed" | "http" | "cooldown" | "transport"; ms: number }
const failures = new Map<string, number>();
const COOLDOWN_MS = 2000;

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** The live session for this process: its own host's Tora first, then the newest. */
function findSession(dir: string): ToraSession | undefined {
  let best: ToraSession | undefined;
  let names: string[];
  try { names = readdirSync(dir); } catch { return undefined; }
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    try {
      const file = JSON.parse(readFileSync(join(dir, name), "utf8")) as Record<string, unknown>;
      const { port, token, pid, host_pid: host, started } = file;
      if (typeof port !== "number" || !Number.isInteger(port) || port < 1 || port > 65535) continue;
      if (typeof token !== "string" || !token || typeof pid !== "number" || !Number.isInteger(pid) || pid <= 0 || !alive(pid)) continue;
      const session: ToraSession = { port, token, hostPid: typeof host === "number" ? host : null, started: typeof started === "string" ? Date.parse(started) || 0 : 0 };
      const own = session.hostPid === process.pid;
      const bestOwn = best?.hostPid === process.pid;
      if (!best || (own && !bestOwn) || (own === bestOwn && session.started > best.started)) best = session;
    } catch {
      // a half-written or foreign file is not a session
    }
  }
  return best;
}

/** The live session (this host's Tora first, then the newest); undefined when Tora is off or none is live. */
export function toraSession(env: NodeJS.ProcessEnv): ToraSession | undefined {
  if (env.BRAIN_TORA === "off") return undefined;
  return findSession(join(env.LOCALAPPDATA ?? tmpdir(), "tora", "sessions"));
}

/** POSTs {query, notes} to a Tora route; the per-note scores only when every note got a finite number. */
export async function toraPost(session: ToraSession, route: "/score" | "/judge", query: string, notes: { id: string; text: string }[], timeoutMs: number, report?: (attempt: ToraAttempt) => void, fullTimeout = true): Promise<ToraScores | undefined> {
  const started = performance.now();
  const key = `${session.port}:${session.started}:${session.token}:${route}`;
  const finish = (outcome: ToraAttempt["outcome"]) => {
    const ms = Math.round((performance.now() - started) * 10) / 10;
    if (outcome === "ok") failures.delete(key);
    else if (outcome !== "cooldown" && (outcome !== "timeout" || fullTimeout)) {
      failures.set(key, Date.now() + COOLDOWN_MS);
      while (failures.size > 64) failures.delete(failures.keys().next().value!);
    }
    report?.({ route, outcome, ms });
    return undefined;
  };
  // An exhausted caller budget says nothing about the server's health.
  if (timeoutMs <= 0) { report?.({ route, outcome: "timeout", ms: 0 }); return undefined; }
  if ((failures.get(key) ?? 0) > Date.now()) return finish("cooldown");
  try {
    if (!notes.length) return undefined;
    const response = await fetch(`http://127.0.0.1:${session.port}${route}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${session.token}` },
      body: JSON.stringify({ query, notes }),
      signal: AbortSignal.timeout(Math.max(1, Math.ceil(timeoutMs))),
    });
    if (response.status !== 200) return finish("http");
    let body: { scores?: unknown } | null;
    try { body = await response.json() as typeof body; } catch (error) {
      if ((error as Error).name === "TimeoutError" || (error as Error).name === "AbortError") throw error;
      return finish("malformed");
    }
    if (!body || !body.scores || typeof body.scores !== "object") return finish("malformed");
    const raw = body.scores as Record<string, unknown>;
    const scores = new Map<string, number>();
    for (const { id } of notes) {
      const score = Object.hasOwn(raw, id) ? raw[id] : undefined;
      if (typeof score !== "number" || !Number.isFinite(score) || (route === "/judge" && (score < 0 || score > 1))) return finish("malformed");
      scores.set(id, score);
    }
    finish("ok");
    return { scores, ms: Math.round((performance.now() - started) * 10) / 10 };
  } catch (error) {
    const e = error as { name?: string; cause?: { code?: string } };
    return finish(e.name === "TimeoutError" || e.name === "AbortError" ? "timeout" : e.cause?.code === "ECONNREFUSED" ? "refused" : "transport");
  }
}

/** A scorer bound to the live session; undefined when Tora is off or none is live, so callers without Tora stay synchronous. */
export function toraScorer(env: NodeJS.ProcessEnv): ToraScorer | undefined {
  const session = toraSession(env);
  if (!session) return undefined;
  const attempts: ToraAttempt[] = [];
  const scorer: ToraScorer = (query, notes, timeoutMs = TORA_TIMEOUT_MS) => {
    attempts.length = 0;
    return toraPost(session, "/score", query, notes, timeoutMs, attempt => { attempts.push(attempt); });
  };
  scorer.attempts = attempts;
  return scorer;
}
