/**
 * Layer 4 for hosts with no request hook (Claude Code, Codex): a local reverse proxy that runs the
 * shared Renderer over the tool output in each model request and forwards everything else, every
 * response and all auth untouched. Opt-in: it runs only when the user starts `brain proxy` and
 * points the host at it. It fails open: any parse or transform error forwards the original bytes.
 * Node built-ins only.
 */
import type { IncomingHttpHeaders, IncomingMessage, OutgoingHttpHeaders, ServerResponse } from "node:http";
import { brotliDecompressSync, gunzipSync, inflateSync, zstdDecompressSync } from "node:zlib";
import { outputTokens, Renderer, type ToolOutput } from "./render.ts";
import { logUse } from "./telemetry.ts";

export type Provider = "anthropic" | "chatgpt" | "openai";

const UPSTREAMS: Record<Provider, string> = {
  anthropic: "https://api.anthropic.com",
  chatgpt: "https://chatgpt.com",
  openai: "https://api.openai.com",
};

function isProvider(name: string): name is Provider {
  return Object.hasOwn(UPSTREAMS, name);
}

/** Conversations whose Renderer is kept; the least recently used is dropped past this. */
const CONVERSATIONS = 64;
/** A bomb guard: a request body that inflates past this is forwarded as it came. */
const MAX_BODY = 256 * 1024 * 1024;
/** Connection-level headers a proxy must not forward (RFC 9110 §7.6.1), plus `expect`, which this proxy answers itself. */
const HOP_BY_HOP = new Set(["connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade", "expect"]);

type Obj = Record<string, unknown>;

function isObj(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** What a transform did: `body` is the input itself when nothing was elided. */
export interface Rewrite {
  body: unknown;
  /** Tool outputs the request carried, and how many of them were sent as stubs. */
  outputs: number;
  elided: number;
  /** Elisions this request made first, and the tokens they saved (stub cost already taken off). */
  fresh: number;
  saved: number;
  /** Tokens (outputTokens) of all tool output before and after rewriting. */
  before: number;
  after: number;
}

/** The part of Renderer a transform needs: lets the proxy pick the Renderer once it sees the outputs. `tokens` is read after render(). */
export type Renders = Pick<Renderer, "render" | "tokens">;

const ANTHROPIC_PARTS = new Set(["text"]);
const RESPONSES_PARTS = new Set(["input_text", "output_text"]);

/** A tool output's text: a string, or the text parts joined with a newline; undefined when any part is not text. */
function textOf(value: unknown, parts: ReadonlySet<string>): string | undefined {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return undefined;
  const texts: string[] = [];
  for (const part of value) {
    if (!isObj(part) || typeof part.type !== "string" || !parts.has(part.type) || typeof part.text !== "string") return undefined;
    texts.push(part.text);
  }
  return texts.join("\n");
}

function elide(body: unknown, outputs: ToolOutput[], renderer: Renders): { rewrite: Rewrite; stubs: Map<number, string> } {
  const stubs = new Map<number, string>();
  let fresh = 0, saved = 0, cut = 0;
  for (const e of outputs.length ? renderer.render(outputs) : []) {
    const gain = e.tokens - outputTokens(e.stub);
    stubs.set(e.index, e.stub);
    cut += gain;
    if (e.fresh) { fresh++; saved += gain; }
  }
  const before = outputs.length ? renderer.tokens : 0;
  return { rewrite: { body, outputs: outputs.length, elided: stubs.size, fresh, saved, before, after: before - cut }, stubs };
}

/**
 * Anthropic Messages: `tool_result` blocks of user messages whose content is text. An elided block
 * becomes `{ ...block, content: stub }`, so cache_control, is_error and every other field stay.
 * The input is never mutated.
 */
export function renderAnthropic(body: unknown, renderer: Renders): Rewrite {
  const root: Obj = isObj(body) ? body : {};
  const messages = Array.isArray(root.messages) ? root.messages : [];
  const names = new Map<string, string>();
  const outputs: ToolOutput[] = [];
  const slots: { at: number; message: Obj; content: unknown[]; index: number; block: Obj }[] = [];
  messages.forEach((message, at) => {
    if (!isObj(message) || !Array.isArray(message.content)) return;
    const content: unknown[] = message.content;
    content.forEach((block, index) => {
      if (!isObj(block)) return;
      if (block.type === "tool_use" && typeof block.id === "string" && typeof block.name === "string") names.set(block.id, block.name);
      if (message.role !== "user" || block.type !== "tool_result" || typeof block.tool_use_id !== "string") return;
      const text = textOf(block.content, ANTHROPIC_PARTS);
      if (text === undefined) return;
      outputs.push({ key: block.tool_use_id, text, tool: names.get(block.tool_use_id) });
      slots.push({ at, message, content, index, block });
    });
  });
  const { rewrite, stubs } = elide(root, outputs, renderer);
  if (!stubs.size) return rewrite;
  const rewritten = messages.slice();
  const contents = new Map<number, unknown[]>();
  for (const [i, stub] of stubs) {
    const slot = slots[i]!;
    let content = contents.get(slot.at);
    if (!content) {
      content = slot.content.slice();
      contents.set(slot.at, content);
      rewritten[slot.at] = { ...slot.message, content };
    }
    content[slot.index] = { ...slot.block, content: stub };
  }
  rewrite.body = { ...root, messages: rewritten };
  return rewrite;
}

/**
 * OpenAI Responses: `input` items whose type ends in `_output` and that carry a `call_id` and text
 * `output`. An elided item becomes `{ ...item, output: stub }`. The input is never mutated.
 */
export function renderResponses(body: unknown, renderer: Renders): Rewrite {
  const root: Obj = isObj(body) ? body : {};
  const input = Array.isArray(root.input) ? root.input : [];
  const names = new Map<string, string>();
  const outputs: ToolOutput[] = [];
  const slots: { at: number; item: Obj }[] = [];
  input.forEach((item, at) => {
    if (!isObj(item) || typeof item.call_id !== "string") return;
    if (item.type === "local_shell_call") names.set(item.call_id, "shell");
    else if ((item.type === "function_call" || item.type === "custom_tool_call") && typeof item.name === "string") names.set(item.call_id, item.name);
    else if (typeof item.type === "string" && item.type.endsWith("_output")) {
      const text = textOf(item.output, RESPONSES_PARTS);
      if (text === undefined) return;
      outputs.push({ key: item.call_id, text, tool: names.get(item.call_id) });
      slots.push({ at, item });
    }
  });
  const { rewrite, stubs } = elide(root, outputs, renderer);
  if (!stubs.size) return rewrite;
  const rewritten = input.slice();
  for (const [i, stub] of stubs) {
    const slot = slots[i]!;
    rewritten[slot.at] = { ...slot.item, output: stub };
  }
  rewrite.body = { ...root, input: rewritten };
  return rewrite;
}

const DECODERS = new Map<string, (body: Buffer) => Buffer>([
  ["gzip", body => gunzipSync(body, { maxOutputLength: MAX_BODY })],
  ["x-gzip", body => gunzipSync(body, { maxOutputLength: MAX_BODY })],
  ["deflate", body => inflateSync(body, { maxOutputLength: MAX_BODY })],
  ["br", body => brotliDecompressSync(body, { maxOutputLength: MAX_BODY })],
  ["zstd", body => zstdDecompressSync(body, { maxOutputLength: MAX_BODY })],
  ["identity", body => body],
]);

/** The body with its content-encodings undone (listed in the order they were applied); throws on one it does not know. */
function decode(body: Buffer, encoding: string | undefined): Buffer {
  let out = body;
  for (const name of (encoding ?? "").toLowerCase().split(",").map(part => part.trim()).filter(Boolean).reverse()) {
    const decoder = DECODERS.get(name);
    if (!decoder) throw new Error(`unsupported content-encoding ${name}`);
    out = decoder(out);
  }
  return out;
}

/** Headers to forward either way: hop-by-hop and the ones the Connection header names are dropped, as are proxy-*. */
function forwardable(headers: IncomingHttpHeaders): OutgoingHttpHeaders {
  const drop = new Set(HOP_BY_HOP);
  const connection = headers.connection;
  for (const name of Array.isArray(connection) ? connection.join(",").split(",") : (connection ?? "").split(",")) if (name.trim()) drop.add(name.trim().toLowerCase());
  const out: OutgoingHttpHeaders = {};
  for (const [name, value] of Object.entries(headers)) if (value !== undefined && !drop.has(name) && !name.startsWith("proxy-")) out[name] = value;
  return out;
}

/** Which transform a request gets, if any: a POST to a model endpoint of that provider's wire format. */
function transformFor(provider: Provider, method: string | undefined, pathname: string): ((body: unknown, renderer: Renders) => Rewrite) | undefined {
  if (method !== "POST") return undefined;
  if (provider === "anthropic") return pathname.endsWith("/v1/messages") ? renderAnthropic : undefined;
  return pathname.endsWith("/responses") || pathname.endsWith("/responses/compact") ? renderResponses : undefined;
}

/** The conversation a request belongs to: a host session header, else what the body carries; undefined when it names none. */
function conversationKey(headers: IncomingHttpHeaders, body: unknown): string | undefined {
  for (const name of ["x-claude-code-session-id", "session-id", "thread-id"]) {
    const value = headers[name];
    if (typeof value === "string" && value) return value;
  }
  if (!isObj(body)) return undefined;
  if (typeof body.prompt_cache_key === "string" && body.prompt_cache_key) return body.prompt_cache_key;
  const user = isObj(body.metadata) ? body.metadata.user_id : undefined;
  return typeof user === "string" && user ? user : undefined;
}

export interface ProxyOptions {
  /** 0 lets the OS pick a free port. */
  port: number;
  /** The Brain home: originals are stored under it for recall and elide rows go to its telemetry; null for neither. */
  home: string | null;
  upstreams?: Partial<Record<Provider, string>>;
  /** One line per rewritten request or fail-open; stderr by default. */
  log?: (line: string) => void;
}

const ROUTE = /^\/([a-z]+)(?=[/?]|$)(.*)$/s;

/** Starts the proxy on 127.0.0.1. Resolves once it listens; rejects when the port cannot be bound. */
export function startProxy(opts: ProxyOptions): Promise<{ port: number; close(): Promise<void> }> {
  const upstreams = { ...UPSTREAMS, ...opts.upstreams };
  const log = opts.log ?? (line => void process.stderr.write(line + "\n"));
  // Fetched here, not imported: an ESM import of node:http builds its facade, which loads undici (16 ms
  // measured) in every process that loads this module, and cli.ts loads it for every Claude Code hook.
  const http = process.getBuiltinModule("node:http"), https = process.getBuiltinModule("node:https");
  const agents = { http: new http.Agent({ keepAlive: true }), https: new https.Agent({ keepAlive: true }) };
  const conversations = new Map<string, Renderer>();
  /** Renderer of one conversation, least recently used dropped past the cap. Keyed by host session and the conversation's first tool call, so a subagent sharing its parent's session does not reset the parent's sticky set. */
  const rendererFor = (key: string): Renderer => {
    let renderer = conversations.get(key);
    if (renderer) conversations.delete(key);
    else {
      renderer = new Renderer(opts.home);
      if (conversations.size >= CONVERSATIONS) for (const oldest of conversations.keys()) { conversations.delete(oldest); break; }
    }
    conversations.set(key, renderer);
    return renderer;
  };

  /**
   * Parse, render and re-serialise `raw`. Undefined (original bytes go on) when nothing was elided or
   * anything failed. Each original is persisted before the Renderer commits its sticky stub.
   */
  const rewrite = (provider: Provider, transform: (body: unknown, renderer: Renders) => Rewrite, req: IncomingMessage, raw: Buffer): { body: Buffer } | undefined => {
    const started = performance.now();
    try {
      const encoding = req.headers["content-encoding"];
      const body: unknown = JSON.parse(decode(raw, Array.isArray(encoding) ? encoding.join(",") : encoding).toString("utf8"));
      const session = conversationKey(req.headers, body);
      let renderer: Renderer | undefined;
      const result = transform(body, {
        render: outputs => (renderer = session === undefined ? new Renderer(opts.home) : rendererFor(`${session}\0${outputs[0]!.key}`)).render(outputs),
        get tokens() { return renderer?.tokens ?? 0; },
      });
      if (!result.elided) return undefined;
      const out = Buffer.from(JSON.stringify(result.body));
      const ms = performance.now() - started;
      log(`brain proxy: ${provider} ${session === undefined ? "-" : session.slice(0, 8).replace(/\s/g, "_")} outputs=${result.outputs} elided=${result.elided} tokens=${result.before}->${result.after}`);
      const home = opts.home;
      if (!home) return { body: out };
      if (result.fresh) logUse(home, { kind: "elide", project: "", tokens: result.saved, ms, session, via: "proxy", hits: result.fresh });
      return { body: out };
    } catch (error) {
      log(`brain proxy: failed open (${provider}): ${error instanceof Error ? error.message : String(error)}`);
      return undefined;
    }
  };

  const forward = (req: IncomingMessage, res: ServerResponse, target: URL, headers: OutgoingHttpHeaders, body?: Buffer): void => {
    const secure = target.protocol === "https:";
    headers.host = target.host;
    const up = (secure ? https.request : http.request)(target, { method: req.method, headers, agent: secure ? agents.https : agents.http }, response => {
      res.writeHead(response.statusCode ?? 502, response.statusMessage, forwardable(response.headers));
      response.on("error", () => res.destroy());
      // Untouched: SSE reaches the client event by event, and a client abort below stops this pipe.
      response.pipe(res);
    });
    up.on("error", error => {
      if (res.headersSent) res.destroy();
      else {
        res.writeHead(502, { "content-type": "text/plain" });
        res.end(`brain proxy: upstream unreachable: ${error.message}\n`);
      }
    });
    res.on("close", () => { if (!res.writableFinished) up.destroy(); });
    if (body) up.end(body);
    else req.pipe(up);
  };

  const server = http.createServer((req, res) => {
    try {
      const url = req.url ?? "/";
      const match = ROUTE.exec(url);
      const name = match?.[1];
      const provider = name !== undefined && isProvider(name) ? name : undefined;
      if (!match || !provider) {
        res.writeHead(404, { "content-type": "text/plain" });
        res.end(`brain proxy: no route for ${url}; routes: ${Object.keys(upstreams).map(name => `/${name}/*`).join(", ")}\n`);
        return;
      }
      const rest = match[2]!.startsWith("/") ? match[2]! : `/${match[2]}`;
      const target = new URL(upstreams[provider].replace(/\/$/, "") + rest);
      const headers = forwardable(req.headers);
      const transform = transformFor(provider, req.method, target.pathname);
      if (!transform) return forward(req, res, target, headers);
      const chunks: Buffer[] = [];
      req.on("data", (chunk: Buffer) => chunks.push(chunk));
      req.on("error", () => res.destroy());
      req.on("end", () => {
        const raw = Buffer.concat(chunks);
        const rewritten = rewrite(provider, transform, req, raw);
        if (rewritten) delete headers["content-encoding"];
        const sent = rewritten?.body ?? raw;
        headers["content-length"] = String(sent.length);
        forward(req, res, target, headers, sent);
      });
    } catch (error) {
      log(`brain proxy: request failed: ${error instanceof Error ? error.message : String(error)}`);
      if (res.headersSent) res.destroy();
      else {
        res.writeHead(502, { "content-type": "text/plain" });
        res.end("brain proxy: request failed\n");
      }
    }
  });
  // A WebSocket upgrade is refused at once: hosts fall back to plain HTTP.
  server.on("upgrade", (_req, socket) => void socket.destroy());

  const listening = Promise.withResolvers<{ port: number; close(): Promise<void> }>();
  server.once("error", listening.reject);
  server.listen(opts.port, "127.0.0.1", () => {
    server.off("error", listening.reject);
    const address = server.address();
    listening.resolve({
      port: typeof address === "object" && address ? address.port : opts.port,
      close() {
        const closed = Promise.withResolvers<void>();
        server.close(() => closed.resolve());
        server.closeAllConnections();
        agents.http.destroy();
        agents.https.destroy();
        return closed.promise;
      },
    });
  });
  return listening.promise;
}
