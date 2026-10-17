/**
 * Host transcripts as one event stream, for offline scripts. Read-only.
 *
 * Sources:
 *  - OMP and Claude Code main-session files: the formats `brain stats` reads (src/asks.ts).
 *  - Codex rollouts: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`.
 *
 * Each session becomes prompts, tool calls and results, injected context, and compactions. A
 * compaction carries what the model can still read after it:
 *  - its summary text;
 *  - the verbatim context the host keeps: OMP's kept tail from `firstKeptEntryId`, Claude Code's
 *    preserved messages, Codex's replacement history.
 *
 * Promote this to src when a runtime layer needs it, not before.
 */
import { closeSync, createReadStream, openSync, readdirSync, readSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { hostSessionRoots, humanPrompt, promptText } from "../src/asks.ts";
import type { Entry } from "../src/asks.ts";

export type Host = "omp" | "claude" | "codex";

/**
 * How readable the summary is:
 *  - `text`: the model reads the summary as written.
 *  - `opaque`: the provider holds an encrypted summary; the file has a placeholder or nothing.
 *  - `archive`: OMP snapcompact; the old transcript comes back as images of its text.
 */
export type Visibility = "text" | "opaque" | "archive";

export type Compaction = {
  /**
   * Host method or trigger:
   *  - OMP: `remote`, `snapcompact`, …;
   *  - Claude Code: `auto` or `manual`;
   *  - Codex: `auto`.
   */
  method: string;
  tokensBefore: number | null;
  tokensAfter: number | null;
  summary: string;
  visibility: Visibility;
  /** Verbatim context the host carries past the compaction. */
  carried: string;
};

export type Event =
  | { kind: "prompt"; text: string; at: number }
  /** `read` and `edits` are comparable path keys (see `pathKey`); Codex shell reads are not parsed. */
  | { kind: "call"; id: string; tool: string; read: string | null; edits: string[]; command: string | null; at: number }
  | { kind: "result"; id: string; error: boolean; card: boolean }
  | { kind: "inject"; text: string; card: boolean }
  | { kind: "compaction"; at: number; compaction: Compaction };

export type Session = { host: Host; file: string; cwd: string; events: Event[] };

type Obj = Record<string, unknown>;
const isObj = (value: unknown): value is Obj => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const time = (value: unknown): number => {
  const at = Date.parse(str(value));
  return Number.isFinite(at) ? at : 0;
};

/** The head line of a Brain card (src/card.ts), in whatever envelope the host delivered it. */
export const CARD = /Brain · .{1,80} — (?:what prior sessions learned|child context)/;

/**
 * Characters kept per entry for carried context. Enough for the retention checks, and it keeps a
 * 200 MB transcript from becoming a 200 MB string map.
 */
const KEEP = 1500;

export function sessionRoots(env: NodeJS.ProcessEnv = process.env): Record<Host, string> {
  const { omp, claude } = hostSessionRoots(env);
  return { omp, claude, codex: join(env.CODEX_HOME || join(homedir(), ".codex"), "sessions") };
}

/**
 * Main-session transcripts modified at or after `since` (ms).
 * Layouts:
 *  - OMP and Claude Code: `<root>/<project>/<session>.jsonl`. Subagent transcripts sit one level
 *    deeper, so they are skipped.
 *  - Codex: `<root>/YYYY/MM/DD/<rollout>.jsonl`.
 */
export function sessionFiles(host: Host, root: string, since: number): string[] {
  const out: string[] = [];
  const walk = (dir: string, depth: number): void => {
    let names: string[];
    try { names = readdirSync(dir); } catch { return; }
    for (const name of names) {
      const path = join(dir, name);
      if (depth > 0) {
        if (!name.endsWith(".jsonl")) walk(path, depth - 1);
      } else if (name.endsWith(".jsonl")) {
        try { if (statSync(path).mtimeMs >= since) out.push(path); } catch { /* removed meanwhile */ }
      }
    }
  };
  walk(root, host === "codex" ? 3 : 1);
  return out;
}

const MARKER: Record<Host, Buffer> = {
  omp: Buffer.from('"type":"compaction"'),
  claude: Buffer.from('"subtype":"compact_boundary"'),
  codex: Buffer.from('"type":"compacted"'),
};
const CHUNK = Buffer.alloc(1 << 22);

/**
 * Whether a file records a compaction. It scans raw bytes in chunks, because most sessions never
 * compact and a full parse of every file would read gigabytes of JSON.
 */
export function hasCompaction(host: Host, file: string): boolean {
  const marker = MARKER[host];
  let fd: number | undefined;
  try {
    fd = openSync(file, "r");
    let carry = 0;
    for (;;) {
      const read = readSync(fd, CHUNK, carry, CHUNK.length - carry, null);
      if (read <= 0) return false;
      const end = carry + read;
      if (CHUNK.subarray(0, end).includes(marker)) return true;
      carry = Math.min(marker.length - 1, end);
      CHUNK.copy(CHUNK, 0, end - carry, end);
    }
  } catch {
    return false;
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}

async function* rows(file: string): AsyncGenerator<Obj> {
  const lines = createInterface({ input: createReadStream(file, { encoding: "utf8" }), crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line) continue;
    try {
      const row: unknown = JSON.parse(line);
      if (isObj(row)) yield row;
    } catch { /* a torn last line, or a row from an older format */ }
  }
}

/**
 * Plain text of a content value. Accepts a string or an array of typed parts: text, tool
 * results, tool calls.
 */
function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  return list(content).map((part) => {
    if (!isObj(part)) return "";
    if (typeof part.text === "string") return part.text;
    if (part.type === "tool_result" || part.type === "toolResult") return contentText(part.content);
    if (part.type === "toolCall" || part.type === "tool_use") return JSON.stringify(part.arguments ?? part.input ?? {});
    return "";
  }).filter(Boolean).join("\n");
}

/**
 * A file target as a comparable key:
 *  - selector suffixes (`:50-80`, `:raw`) dropped;
 *  - resolved against the session's cwd;
 *  - case-folded, with forward slashes.
 * Internal URLs are not files; they give null.
 */
export function pathKey(path: string, cwd: string): string | null {
  if (!path || path.includes("://")) return null;
  const drive = /^[A-Za-z]:[\\/]/.test(path) ? 2 : 0;
  const colon = path.indexOf(":", drive);
  const bare = (colon >= 0 ? path.slice(0, colon) : path).trim();
  if (!bare) return null;
  const full = isAbsolute(bare) || !cwd ? bare : resolve(cwd, bare);
  return full.replace(/\\/g, "/").toLowerCase();
}

/** Edited files as de-duplicated path keys, the same for every host; anything `pathKey` rejects drops out. */
const editKeys = (paths: string[], cwd: string): string[] =>
  [...new Set(paths.map((path) => pathKey(path, cwd)).filter((key): key is string => key !== null))];

/** Tool names for OMP (read/edit/write/bash) and Claude Code (Read/Edit/Write/MultiEdit/Bash/PowerShell). */
function callEvent(id: string, tool: string, args: Obj, cwd: string, at: number): Event {
  const name = tool.toLowerCase();
  const path = str(args.path) || str(args.file_path) || str(args.notebook_path);
  const edits: string[] = [];
  let read: string | null = null;
  let command: string | null = null;
  if (name === "read") read = pathKey(path, cwd);
  else if (["edit", "write", "multiedit", "notebookedit"].includes(name)) {
    if (path) edits.push(path);
    // OMP's hashline edit names its files in `[path#TAG]` headers.
    for (const [, file] of str(args.input).matchAll(/^\[([^\]\n#]+)#[0-9A-Fa-f]{4}\]/gm)) if (file) edits.push(file);
  } else if (name === "bash" || name === "powershell") command = str(args.command) || null;
  return { kind: "call", id, tool: name, read, edits: editKeys(edits, cwd), command, at };
}

/**
 * Codex runs tools through the exec tool's JavaScript and patches.
 * Recovered from the call body: the shell command and the patched files. File reads are not.
 */
function codexCall(id: string, tool: string, body: string, cwd: string, at: number): Event {
  const edits = [...body.matchAll(/\*\*\* (?:Update|Add) File: ([^\n"\\]+)/g)].map(([, file = ""]) => file.trim());
  const cmd = /\bcmd["']?\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`]*)`)/.exec(body);
  return { kind: "call", id, tool: tool.toLowerCase(), read: null, edits: editKeys(edits, cwd), command: cmd ? cmd[1] ?? cmd[2] ?? cmd[3] ?? null : null, at };
}

type Kept = { order: string[]; at: Map<string, number> };
const keep = (kept: Kept, id: string, text: string): void => {
  if (!id) return;
  kept.at.set(id, kept.order.length);
  kept.order.push(text.slice(0, KEEP));
};

async function parseOmp(file: string): Promise<Session> {
  const session: Session = { host: "omp", file, cwd: "", events: [] };
  let kept: Kept = { order: [], at: new Map() };
  for await (const row of rows(file)) {
    const type = str(row.type);
    const id = str(row.id);
    const at = time(row.timestamp);
    if (type === "session") {
      session.cwd ||= str(row.cwd);
    } else if (type === "message" && isObj(row.message)) {
      const message = row.message;
      const role = str(message.role);
      let text: string;
      if (role === "user") {
        text = promptText(message.content) ?? "";
        if (text.trim() && humanPrompt(row as Entry, "omp")) session.events.push({ kind: "prompt", text, at });
      } else if (role === "assistant") {
        text = contentText(message.content);
        for (const part of list(message.content)) {
          if (isObj(part) && part.type === "toolCall") {
            session.events.push(callEvent(str(part.id), str(part.name), isObj(part.arguments) ? part.arguments : {}, session.cwd, at));
          }
        }
      } else {
        text = contentText(message.content);
        if (role === "toolResult") session.events.push({ kind: "result", id: str(message.toolCallId), error: message.isError === true, card: CARD.test(text) });
      }
      keep(kept, id, text);
    } else if (type === "custom_message") {
      const text = contentText(row.content);
      if (str(row.customType).startsWith("brain")) session.events.push({ kind: "inject", text: text.slice(0, 300), card: CARD.test(text) });
      keep(kept, id, text);
    } else if (type === "compaction") {
      const preserve = isObj(row.preserveData) ? row.preserveData : {};
      const snap = isObj(preserve.snapcompact) ? preserve.snapcompact : null;
      const method = str(row.method) || "unknown";
      const start = kept.at.get(str(row.firstKeptEntryId));
      const carried = start === undefined ? "" : kept.order.slice(start).join("\n");
      // Only the Anthropic lane stores the summary it sends. The OpenAI lanes store a placeholder
      // plus the file lists; the provider keeps the encrypted summary.
      const visibility: Visibility = snap ? "archive" : method === "remote" && !isObj(preserve.anthropicCompaction) ? "opaque" : "text";
      session.events.push({
        kind: "compaction", at,
        compaction: {
          method, tokensBefore: num(row.tokensBefore), tokensAfter: num(row.tokensAfter),
          summary: snap ? `${str(row.summary)}\n${str(snap.text)}` : str(row.summary), visibility, carried,
        },
      });
      // Later compactions keep entries from this tail onward; earlier entries can never come back.
      const order = start === undefined ? [] : kept.order.slice(start);
      const ids = [...kept.at.entries()].filter(([, index]) => start !== undefined && index >= start);
      kept = { order, at: new Map(ids.map(([key, index]) => [key, index - (start ?? 0)])) };
      keep(kept, id, str(row.summary));
    }
  }
  return session;
}

async function parseClaude(file: string): Promise<Session> {
  const session: Session = { host: "claude", file, cwd: "", events: [] };
  const kept: Kept = { order: [], at: new Map() };
  let pending: Compaction | null = null;
  for await (const row of rows(file)) {
    if (row.isSidechain === true) continue;
    const type = str(row.type);
    const at = time(row.timestamp);
    session.cwd ||= str(row.cwd);
    if (type === "system" && row.subtype === "compact_boundary") {
      const meta = isObj(row.compactMetadata) ? row.compactMetadata : {};
      const preserved = isObj(meta.preservedMessages) ? meta.preservedMessages : {};
      const ids = list(preserved.allUuids).length ? list(preserved.allUuids) : list(preserved.uuids);
      let carried = ids.map((uuid) => kept.order[kept.at.get(str(uuid)) ?? -1] ?? "").filter(Boolean).join("\n");
      if (!carried && isObj(meta.preservedSegment)) {
        const head = kept.at.get(str(meta.preservedSegment.headUuid));
        const tail = kept.at.get(str(meta.preservedSegment.tailUuid));
        if (head !== undefined && tail !== undefined) carried = kept.order.slice(head, tail + 1).join("\n");
      }
      pending = { method: str(meta.trigger) || "auto", tokensBefore: num(meta.preTokens), tokensAfter: num(meta.postTokens), summary: "", visibility: "text", carried };
      session.events.push({ kind: "compaction", at, compaction: pending });
      continue;
    }
    if (type === "user" && row.isCompactSummary === true) {
      if (pending) pending.summary = contentText(isObj(row.message) ? row.message.content : "");
      pending = null;
      continue;
    }
    if (type === "attachment" && isObj(row.attachment) && row.attachment.type === "hook_additional_context") {
      const text = list(row.attachment.content).map(str).join("\n");
      session.events.push({ kind: "inject", text: text.slice(0, 300), card: CARD.test(text) });
      continue;
    }
    if (!isObj(row.message)) continue;
    const message = row.message;
    let text = "";
    if (type === "user") {
      const prompt = promptText(message.content);
      if (prompt !== null) {
        text = prompt;
        if (prompt.trim() && humanPrompt(row as Entry, "claude")) session.events.push({ kind: "prompt", text, at });
      } else {
        for (const part of list(message.content)) {
          if (!isObj(part) || part.type !== "tool_result") continue;
          const body = contentText(part.content);
          text += `${body}\n`;
          session.events.push({ kind: "result", id: str(part.tool_use_id), error: part.is_error === true, card: CARD.test(body) });
        }
      }
    } else if (type === "assistant") {
      text = contentText(message.content);
      for (const part of list(message.content)) {
        if (isObj(part) && part.type === "tool_use") session.events.push(callEvent(str(part.id), str(part.name), isObj(part.input) ? part.input : {}, session.cwd, at));
      }
    }
    keep(kept, str(row.uuid), text);
  }
  return session;
}

/** Null for `codex exec` runs: harness work, not an owner session. */
async function parseCodex(file: string): Promise<Session | null> {
  const session: Session = { host: "codex", file, cwd: "", events: [] };
  let context: number | null = null;
  for await (const row of rows(file)) {
    const type = str(row.type);
    const payload = isObj(row.payload) ? row.payload : {};
    const at = time(row.timestamp);
    if (type === "session_meta") {
      if (str(payload.originator).includes("exec") || payload.source === "exec") return null;
      session.cwd ||= str(payload.cwd);
    } else if (type === "response_item") {
      const item = str(payload.type);
      if (item === "message" && payload.role === "user") {
        const text = contentText(payload.content);
        // Environment, instruction and hook blocks are tagged; the owner's prompts are not.
        if (text.trim() && !/^\s*</.test(text)) session.events.push({ kind: "prompt", text, at });
      } else if (item === "function_call" || item === "custom_tool_call") {
        session.events.push(codexCall(str(payload.call_id), str(payload.name), item === "function_call" ? str(payload.arguments) : str(payload.input), session.cwd, at));
      } else if (item === "function_call_output" || item === "custom_tool_call_output") {
        session.events.push({ kind: "result", id: str(payload.call_id), error: false, card: false });
      }
    } else if (type === "event_msg" && payload.type === "token_count" && isObj(payload.info) && isObj(payload.info.last_token_usage)) {
      context = num(payload.info.last_token_usage.total_tokens) ?? context;
    } else if (type === "compacted") {
      const history = list(payload.replacement_history).filter(isObj);
      const carried = history.filter((item) => item.type === "message").map((item) => contentText(item.content)).join("\n");
      const summary = str(payload.message);
      const opaque = history.some((item) => item.type === "compaction") || !summary;
      session.events.push({
        kind: "compaction", at,
        compaction: { method: "auto", tokensBefore: context, tokensAfter: null, summary, visibility: opaque ? "opaque" : "text", carried },
      });
    }
  }
  return session;
}

/**
 * One transcript as events. Returns null when it is not an owner session, which only happens for
 * Codex: `codex exec` runs are harness work.
 */
export function parseSession(host: Host, file: string): Promise<Session | null> {
  if (host === "omp") return parseOmp(file);
  if (host === "claude") return parseClaude(file);
  return parseCodex(file);
}
