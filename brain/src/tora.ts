/**
 * Optional local scorer (Tora, EmbeddingGemma 2) for recall: a second candidate source for the Jev
 * judge and a shadow-mode pre-filter. A live Tora publishes `<tora_pid>.json` (port, bearer token,
 * pid, host_pid, started) in `%LOCALAPPDATA%\tora\sessions`. Every failure yields undefined, so the
 * caller's answer is exactly what it would be without Tora. Nothing here logs or rethrows: an error
 * could carry the bearer token.
 */
import { readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Lowest Jev-relevant cosine on recorded data was 0.717. */
export const TORA_FLOOR = 0.70;
/** At most this many Tora-added candidates per recall. */
export const TORA_ADD = 2;
/** A cold first call (model load) takes seconds; recall does not wait for it. */
export const TORA_TIMEOUT_MS = 800;

export interface ToraScores { scores: Map<string, number>; cut: number; ms: number }
export type ToraScorer = (query: string, notes: { id: string; text: string }[]) => Promise<ToraScores | undefined>;

interface Session { port: number; token: string; hostPid: number | null; started: number }

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** The live session for this process: its own host's Tora first, then the newest. */
function findSession(dir: string): Session | undefined {
  let best: Session | undefined;
  let names: string[];
  try { names = readdirSync(dir); } catch { return undefined; }
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    try {
      const file = JSON.parse(readFileSync(join(dir, name), "utf8")) as Record<string, unknown>;
      const { port, token, pid, host_pid: host, started } = file;
      if (typeof port !== "number" || !Number.isInteger(port) || port < 1 || port > 65535) continue;
      if (typeof token !== "string" || !token || typeof pid !== "number" || !Number.isInteger(pid) || pid <= 0 || !alive(pid)) continue;
      const session: Session = { port, token, hostPid: typeof host === "number" ? host : null, started: typeof started === "string" ? Date.parse(started) || 0 : 0 };
      const own = session.hostPid === process.pid;
      const bestOwn = best?.hostPid === process.pid;
      if (!best || (own && !bestOwn) || (own === bestOwn && session.started > best.started)) best = session;
    } catch {
      // a half-written or foreign file is not a session
    }
  }
  return best;
}

export function toraScorer(env: NodeJS.ProcessEnv): ToraScorer | undefined {
  if (env.BRAIN_TORA === "off") return undefined;
  const dir = join(env.LOCALAPPDATA ?? tmpdir(), "tora", "sessions");
  return async (query, notes) => {
    try {
      if (!notes.length) return undefined;
      const session = findSession(dir);
      if (!session) return undefined;
      const started = performance.now();
      const response = await fetch(`http://127.0.0.1:${session.port}/score`, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${session.token}` },
        body: JSON.stringify({ query, notes }),
        signal: AbortSignal.timeout(TORA_TIMEOUT_MS),
      });
      if (response.status !== 200) return undefined;
      const body = await response.json() as { scores?: unknown; cut?: unknown } | null;
      if (!body || typeof body.cut !== "number" || !Number.isFinite(body.cut) || !body.scores || typeof body.scores !== "object") return undefined;
      const raw = body.scores as Record<string, unknown>;
      const scores = new Map<string, number>();
      for (const { id } of notes) {
        const score = Object.hasOwn(raw, id) ? raw[id] : undefined;
        if (typeof score !== "number" || !Number.isFinite(score)) return undefined;
        scores.set(id, score);
      }
      return { scores, cut: body.cut, ms: Math.round((performance.now() - started) * 10) / 10 };
    } catch {
      return undefined;
    }
  };
}
