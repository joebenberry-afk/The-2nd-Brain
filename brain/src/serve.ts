/**
 * A long-lived Brain service for host plugins: one process, many commands.
 *
 * Each stdin line is one request (`{id, argv, cwd?, session?, stdin?}`); each reply is one line
 * (`{id, code, out, err}`). Requests run in order through the same `main` the CLI uses, so the
 * stat-validated note cache and the compiled sources are paid once per host session instead of once
 * per call: a warm `recall`/`fix` costs ~30 ms against ~380 ms for a fresh CLI process.
 *
 * The protocol is deliberately dumb — it carries any command — so it stays one implementation of
 * the Brain. Commands that own stdio (`mcp`, `proxy`) or the service itself are refused; a request
 * may not start a nested `serve`. Failures answer with a code and text, never exit, so one bad
 * request cannot take the host's memory down.
 */
import { once } from "node:events";
import { createInterface } from "node:readline";
import type { Readable, Writable } from "node:stream";
import { main, type Io } from "./cli.ts";

export interface ServeBase {
  /** Host environment; `SECOND_BRAIN_HOME` is normally set here. */
  env: NodeJS.ProcessEnv;
  /** The host process's directory, used when a request names none. */
  cwd: string;
}

export interface ServeReply {
  id: unknown;
  code: number;
  out: string;
  err: string;
}

/** One request line may carry a long note body; anything larger is a host bug, not a note. */
const MAX_LINE = 2 * 1024 * 1024;
/** A reply is a model-facing card, recall answer or fix: a few KiB. Bound a runaway report. */
const MAX_REPLY_CHARS = 512 * 1024;
const MAX_ARGV = 64;
/** Commands that stream on stdout or never return: inside the service they would corrupt it. */
const OWN_STDIO = new Set(["serve", "mcp", "proxy"]);

function text(value: unknown, max = MAX_LINE): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

/**
 * Answer one request. Exported for tests: the same path `runServe` uses for every line, with an
 * injected environment/cwd instead of a live child.
 */
export async function serveRequest(base: ServeBase, request: unknown): Promise<ServeReply> {
  const record = request && typeof request === "object" && !Array.isArray(request) ? (request as Record<string, unknown>) : {};
  const id = record.id ?? null;
  const argv = Array.isArray(record.argv) ? record.argv.filter((arg): arg is string => typeof arg === "string") : [];
  if (!argv.length || argv.length > MAX_ARGV) {
    return { id, code: 1, out: "", err: "brain serve: expected argv" };
  }
  if (OWN_STDIO.has(argv[0] ?? "")) {
    return { id, code: 1, out: "", err: `brain serve: ${argv[0]} owns stdio and cannot run inside serve` };
  }
  const out: string[] = [];
  const err: string[] = [];
  const env: NodeJS.ProcessEnv = { ...base.env };
  const session = text(record.session, 200);
  if (session) env.BRAIN_SESSION = session;
  const stdin = text(record.stdin, MAX_LINE);
  const io: Io = {
    out: (line) => { if (out.length < 2_000) out.push(line); },
    err: (line) => { if (err.length < 2_000) err.push(line); },
    env,
    cwd: text(record.cwd, 4_096) || base.cwd,
    stdin: () => stdin,
  };
  let code = 1;
  try {
    code = await main(argv, io);
  } catch (error) {
    err.push(`brain serve: ${error instanceof Error ? error.message : String(error)}`);
  }
  return {
    id,
    code,
    out: out.join("\n").slice(0, MAX_REPLY_CHARS),
    err: err.join("\n").slice(0, MAX_REPLY_CHARS),
  };
}

/**
 * Read request lines until stdin ends, answering each in order. The service never stops on a
 * request, so a host keeps one warm process for the life of its session.
 */
export async function runServe(base: ServeBase, input: Readable, output: Writable): Promise<number> {
  const lines = createInterface({ input, crlfDelay: Infinity, terminal: false });
  try {
    for await (const line of lines) {
      if (!line.trim()) continue;
      const reply = line.length > MAX_LINE
        ? { id: null, code: 1, out: "", err: "brain serve: request too large" }
        : await serveRequest(base, parse(line));
      if (!output.write(`${JSON.stringify(reply)}\n`)) await once(output, "drain");
    }
  } catch {
    // A closed pipe means the host is gone; nothing left to answer.
  }
  return 0;
}

function parse(line: string): unknown {
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}
