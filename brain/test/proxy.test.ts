/** Layer 4 proxy (brain/src/proxy.ts) against a fake upstream: rewriting, fail-open, pass-through, streaming, prefix stability. */
import { createServer, request, type IncomingHttpHeaders, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync, zstdCompressSync } from "node:zlib";
import { afterEach, describe, expect, it } from "vitest";
import { renderAnthropic, renderResponses, startProxy } from "../src/proxy.ts";
import { readElided, Renderer } from "../src/render.ts";

interface Block { type: string; tool_use_id?: string; content?: unknown; cache_control?: unknown; is_error?: boolean; text?: string; [key: string]: unknown }
interface Message { role: string; content: Block[] | string }
interface AnthropicBody { messages: Message[]; [key: string]: unknown }
interface Item { type: string; call_id?: string; output?: unknown; [key: string]: unknown }
interface ResponsesBody { input: Item[]; [key: string]: unknown }
interface Seen { method: string; url: string; headers: IncomingHttpHeaders; body: Buffer }
interface Reply { status: number; headers: IncomingHttpHeaders; body: Buffer }

const STUB = "[Second Brain elided this ";
const cleanup: (() => Promise<void> | void)[] = [];
afterEach(async () => { for (const undo of cleanup.splice(0).reverse()) await undo(); });

/** About `tokens` tokens (outputTokens counts this text within a few percent of chars/4) of distinct text per `n`. */
const big = (n: number, tokens = 25_000): string => `result ${n}\n`.padEnd(tokens * 4, `line ${n} of the output\n`).slice(0, tokens * 4);

async function listen(handler: (req: IncomingMessage, res: ServerResponse) => void): Promise<{ server: Server; url: string }> {
  const server = createServer(handler);
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  cleanup.push(() => new Promise<void>(resolve => { server.close(() => resolve()); server.closeAllConnections(); }));
  const address = server.address();
  return { server, url: `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}` };
}

/** A fake upstream that records every request and answers with `reply` (JSON 200 by default). */
async function fakeUpstream(reply: (seen: Seen, res: ServerResponse) => void = (_seen, res) => { res.writeHead(200, { "content-type": "application/json" }); res.end('{"ok":true}'); }) {
  const seen: Seen[] = [];
  const { url } = await listen((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const entry = { method: req.method ?? "", url: req.url ?? "", headers: req.headers, body: Buffer.concat(chunks) };
      seen.push(entry);
      reply(entry, res);
    });
  });
  return { seen, url };
}

async function proxyTo(url: string, home: string | null = null) {
  const lines: string[] = [];
  const proxy = await startProxy({ port: 0, home, upstreams: { anthropic: url, chatgpt: url, openai: url }, log: line => lines.push(line) });
  cleanup.push(() => proxy.close());
  return { port: proxy.port, lines };
}

function send(port: number, path: string, init: { method?: string; headers?: Record<string, string>; body?: Buffer | string } = {}): Promise<Reply> {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path, method: init.method ?? "GET", headers: init.headers, agent: false }, res => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    req.end(init.body);
  });
}

const post = (port: number, path: string, body: unknown, headers: Record<string, string> = {}) =>
  send(port, path, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });

const tmp = (): string => {
  const home = mkdtempSync(join(tmpdir(), "proxy-"));
  cleanup.push(() => rmSync(home, { recursive: true, force: true }));
  return home;
};

/** A Claude Code style conversation: one assistant tool_use and one user tool_result per entry of `results`. */
function anthropicBody(results: string[], prefix = "toolu_"): AnthropicBody {
  const messages: Message[] = [{ role: "user", content: [{ type: "text", text: "Fix the build" }] }];
  results.forEach((text, n) => {
    messages.push({ role: "assistant", content: [{ type: "text", text: `Running step ${n}` }, { type: "tool_use", id: `${prefix}${n}`, name: "Bash", input: { command: `cmd ${n}` } }] });
    const block: Block = { type: "tool_result", tool_use_id: `${prefix}${n}`, content: text };
    if (n === 0) block.cache_control = { type: "ephemeral" };
    if (n === 1) block.is_error = true;
    messages.push({ role: "user", content: [block] });
  });
  messages.push({ role: "user", content: [{ type: "text", text: "Now continue" }] });
  return { model: "claude-test", max_tokens: 16, system: "be brief", messages };
}

const toolResults = (body: AnthropicBody): Block[] =>
  body.messages.flatMap(message => (typeof message.content === "string" ? [] : message.content)).filter(block => block.type === "tool_result");

const isStub = (value: unknown): value is string => typeof value === "string" && value.startsWith(STUB);

function responsesBody(results: string[], prefix = "call_"): ResponsesBody {
  const input: Item[] = [{ type: "message", role: "user", content: [{ type: "input_text", text: "Fix the build" }] }];
  results.forEach((text, n) => {
    const custom = n % 2 === 1;
    input.push(custom
      ? { type: "custom_tool_call", call_id: `${prefix}${n}`, name: "apply_patch", input: `patch ${n}` }
      : { type: "function_call", call_id: `${prefix}${n}`, name: "shell", arguments: JSON.stringify({ command: [`cmd ${n}`] }) });
    input.push({ type: custom ? "custom_tool_call_output" : "function_call_output", call_id: `${prefix}${n}`, output: text });
  });
  input.push({ type: "message", role: "user", content: [{ type: "input_text", text: "Now continue" }] });
  return { model: "gpt-test", input, stream: true };
}

const outputsOf = (body: ResponsesBody): Item[] => body.input.filter(item => item.type.endsWith("_output"));

const RESULTS = [big(0), big(1), "ok", big(3), big(4), big(5)];

describe("anthropic rewriting", () => {
  it("sends stubs for big old tool_results and nothing else changed", async () => {
    const upstream = await fakeUpstream();
    const home = tmp();
    const { port, lines } = await proxyTo(upstream.url, home);
    const original = anthropicBody(RESULTS);
    const reply = await post(port, "/anthropic/v1/messages?beta=true", original, { "x-claude-code-session-id": "11112222-3333" });
    expect(reply.status).toBe(200);
    expect(upstream.seen[0]!.url).toBe("/v1/messages?beta=true");

    const sent = JSON.parse(upstream.seen[0]!.body.toString()) as AnthropicBody;
    const results = toolResults(sent);
    const stubbed = results.filter(block => isStub(block.content));
    expect(stubbed.length).toBeGreaterThanOrEqual(2);
    // newest outputs and the small one stay verbatim; the tool's name reaches the stub
    expect(results.slice(-2).every(block => !isStub(block.content))).toBe(true);
    expect(results[2]!.content).toBe("ok");
    expect(String(stubbed[0]!.content)).toContain("Bash output");
    // cache_control and is_error survive on the stubbed blocks
    expect(results[0]!.cache_control).toEqual({ type: "ephemeral" });
    expect(results[1]!.is_error).toBe(true);
    // every stub's id restores the exact original, and putting the originals back gives the request we sent
    for (const block of stubbed) {
      const id = /Recall id (t-[0-9a-f]{10})/.exec(String(block.content))![1]!;
      const text = original.messages.flatMap(m => (typeof m.content === "string" ? [] : m.content)).find(b => b.tool_use_id === block.tool_use_id)!.content;
      expect(readElided(home, id)).toBe(text);
      block.content = text;
    }
    expect(sent).toEqual(original);
    expect(upstream.seen[0]!.headers["content-length"]).toBe(String(upstream.seen[0]!.body.length));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatch(/^brain proxy: anthropic 11112222 outputs=6 elided=\d+ tokens=\d+->\d+$/);
  });

  it("writes one elide row for the epoch that elided, and none while the stubs stay put", async () => {
    const upstream = await fakeUpstream();
    const home = tmp();
    const { port } = await proxyTo(upstream.url, home);
    const headers = { "x-claude-code-session-id": "sess-h" };
    const rows = () => {
      try { return readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line) as { kind: string; via: string; session: string; hits: number; tokens: number }).filter(row => row.kind === "elide"); }
      catch { return []; }
    };
    await post(port, "/anthropic/v1/messages", anthropicBody(RESULTS), headers);
    expect(rows()).toHaveLength(1);
    expect(rows()[0]).toMatchObject({ via: "proxy", session: "sess-h" });
    expect(rows()[0]!.hits).toBeGreaterThanOrEqual(2);
    expect(rows()[0]!.tokens).toBeGreaterThan(40_000);

    // the same conversation grows by a few tokens: same stubs, byte for byte, and no new row
    await post(port, "/anthropic/v1/messages", anthropicBody([...RESULTS, big(6, 3_000)]), headers);
    const first = toolResults(JSON.parse(upstream.seen[0]!.body.toString()) as AnthropicBody).filter(block => isStub(block.content));
    const again = toolResults(JSON.parse(upstream.seen[1]!.body.toString()) as AnthropicBody);
    expect(first.length).toBeGreaterThanOrEqual(2);
    for (const block of first) expect(again.find(b => b.tool_use_id === block.tool_use_id)!.content).toBe(block.content);
    expect(rows()).toHaveLength(1);

    // a child sharing the session id has its own history: it must not reset its parent's state
    await post(port, "/anthropic/v1/messages", anthropicBody([big(20), big(21), big(22)], "child_"), headers);
    const afterChild = rows().length;
    await post(port, "/anthropic/v1/messages", anthropicBody([...RESULTS, big(6, 3_000), big(7, 3_000)]), headers);
    expect(rows()).toHaveLength(afterChild);
    const last = toolResults(JSON.parse(upstream.seen[3]!.body.toString()) as AnthropicBody);
    for (const block of first) expect(last.find(b => b.tool_use_id === block.tool_use_id)!.content).toBe(block.content);
  });

  it("leaves image results and mixed content alone and joins text parts", () => {
    const text = (n: number): Block => ({ type: "text", text: big(n, 6_000) });
    const body = anthropicBody([big(0, 30_000), big(1, 30_000), big(2, 30_000)]);
    const blocks = toolResults(body);
    blocks[0]!.content = [{ type: "image", source: { type: "base64", media_type: "image/png", data: "AAAA" } }, text(0)];
    blocks[1]!.content = [text(1), text(2)];
    const before = structuredClone(body);
    const seen: string[] = [];
    const renderer = new Renderer(null, { keep: 10_000, step: 5_000, min: 500 });
    const rewrite = renderAnthropic(body, { render: outputs => { seen.push(...outputs.map(o => o.text)); return renderer.render(outputs); }, get tokens() { return renderer.tokens; } });
    expect(body).toEqual(before); // input is never mutated
    expect(seen).toHaveLength(2); // the image result is not a candidate
    expect(seen[0]).toBe(`${text(1).text}\n${text(2).text}`);
    const out = rewrite.body as AnthropicBody;
    expect(toolResults(out)[0]!.content).toEqual(blocks[0]!.content);
    expect(toolResults(out)[1]!.content).toSatisfy(isStub);
  });
});

describe("responses rewriting", () => {
  it("sends stubs for function_call_output and custom_tool_call_output and nothing else changed", async () => {
    const upstream = await fakeUpstream();
    const home = tmp();
    const { port, lines } = await proxyTo(upstream.url, home);
    const original = responsesBody(RESULTS);
    // an image-bearing output is never a candidate: it is not counted either
    original.input.push({ type: "function_call_output", call_id: "call_img", output: [{ type: "input_image", image_url: "data:image/png;base64,AAAA" }] });
    const reply = await post(port, "/chatgpt/backend-api/codex/responses", original, { "session-id": "abcdef12-0000" });
    expect(reply.status).toBe(200);
    expect(upstream.seen[0]!.url).toBe("/backend-api/codex/responses");

    const sent = JSON.parse(upstream.seen[0]!.body.toString()) as ResponsesBody;
    const outputs = outputsOf(sent);
    const stubbed = outputs.filter(item => isStub(item.output));
    expect(stubbed.length).toBeGreaterThanOrEqual(2);
    expect(stubbed.map(item => item.type)).toContain("custom_tool_call_output");
    expect(stubbed.map(item => item.type)).toContain("function_call_output");
    expect(String(stubbed.find(item => item.type === "custom_tool_call_output")!.output)).toContain("apply_patch output");
    expect(String(stubbed.find(item => item.type === "function_call_output")!.output)).toContain("shell output");
    expect(outputs.find(item => item.call_id === "call_2")!.output).toBe("ok");
    for (const item of stubbed) {
      const id = /Recall id (t-[0-9a-f]{10})/.exec(String(item.output))![1]!;
      const text = outputsOf(original).find(o => o.call_id === item.call_id)!.output;
      expect(readElided(home, id)).toBe(text);
      item.output = text;
    }
    expect(sent).toEqual(original);
    expect(lines[0]).toMatch(/^brain proxy: chatgpt abcdef12 outputs=6 elided=\d+ tokens=\d+->\d+$/);
  });

  it("serves /responses/compact and the openai route the same way, keyed by prompt_cache_key", async () => {
    const upstream = await fakeUpstream();
    const { port, lines } = await proxyTo(upstream.url);
    const body = { ...responsesBody(RESULTS), prompt_cache_key: "cachekey-1" };
    await post(port, "/openai/v1/responses/compact", body);
    const sent = JSON.parse(upstream.seen[0]!.body.toString()) as ResponsesBody;
    expect(outputsOf(sent).some(item => isStub(item.output))).toBe(true);
    expect(lines[0]).toContain("brain proxy: openai cachekey ");
  });

  it("never mutates its input", () => {
    const body = responsesBody(RESULTS);
    const before = structuredClone(body);
    const rewrite = renderResponses(body, new Renderer(null));
    expect(rewrite.elided).toBeGreaterThanOrEqual(2);
    expect(body).toEqual(before);
    expect(rewrite.after).toBeLessThan(rewrite.before);
  });
});

describe("request bodies", () => {
  it("decodes a zstd body, rewrites it and forwards plain JSON", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    const raw = Buffer.from(JSON.stringify(anthropicBody(RESULTS)));
    const reply = await send(port, "/anthropic/v1/messages", { method: "POST", headers: { "content-type": "application/json", "content-encoding": "zstd" }, body: zstdCompressSync(raw) });
    expect(reply.status).toBe(200);
    const seen = upstream.seen[0]!;
    expect(seen.headers["content-encoding"]).toBeUndefined();
    expect(seen.headers["content-length"]).toBe(String(seen.body.length));
    expect(toolResults(JSON.parse(seen.body.toString()) as AnthropicBody).some(block => isStub(block.content))).toBe(true);
    expect(seen.body.length).toBeLessThan(raw.length);
  });

  it("forwards an unchanged compressed body as the original bytes with its headers", async () => {
    const upstream = await fakeUpstream();
    const { port, lines } = await proxyTo(upstream.url);
    const gz = gzipSync(JSON.stringify(anthropicBody(["small result"])));
    await send(port, "/anthropic/v1/messages", { method: "POST", headers: { "content-type": "application/json", "content-encoding": "gzip" }, body: gz });
    expect(upstream.seen[0]!.body.equals(gz)).toBe(true);
    expect(upstream.seen[0]!.headers["content-encoding"]).toBe("gzip");
    expect(lines).toHaveLength(0);
  });

  it("fails open: invalid JSON on a rewrite path goes upstream byte for byte", async () => {
    const upstream = await fakeUpstream();
    const { port, lines } = await proxyTo(upstream.url);
    const garbage = Buffer.from(`{"messages": [ not json ${big(0, 2_000)}`);
    const reply = await send(port, "/anthropic/v1/messages", { method: "POST", headers: { "content-type": "application/json" }, body: garbage });
    expect(reply.status).toBe(200);
    expect(upstream.seen[0]!.body.equals(garbage)).toBe(true);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("failed open");
  });

  it("fails open on an encoding it cannot decode", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    const raw = Buffer.from(JSON.stringify(anthropicBody(RESULTS)));
    await send(port, "/anthropic/v1/messages", { method: "POST", headers: { "content-type": "application/json", "content-encoding": "compress" }, body: raw });
    expect(upstream.seen[0]!.body.equals(raw)).toBe(true);
    expect(upstream.seen[0]!.headers["content-encoding"]).toBe("compress");
  });
});

describe("pass-through", () => {
  it("streams a GET that is not rewritten with its headers and status", async () => {
    const upstream = await fakeUpstream((_seen, res) => { res.writeHead(418, { "content-type": "application/json", "x-upstream": "yes", "x-ratelimit": "9" }); res.end('{"data":[]}'); });
    const { port } = await proxyTo(upstream.url);
    const reply = await send(port, "/anthropic/v1/models?limit=2", { headers: { "x-api-key": "k", authorization: "Bearer t", "chatgpt-account-id": "acct", "x-keep": "1" } });
    expect(reply.status).toBe(418);
    expect(reply.headers["x-upstream"]).toBe("yes");
    expect(reply.headers["x-ratelimit"]).toBe("9");
    expect(reply.body.toString()).toBe('{"data":[]}');
    const seen = upstream.seen[0]!;
    expect(seen.method).toBe("GET");
    expect(seen.url).toBe("/v1/models?limit=2");
    expect(seen.headers).toMatchObject({ "x-api-key": "k", authorization: "Bearer t", "chatgpt-account-id": "acct", "x-keep": "1", host: new URL(upstream.url).host });
  });

  it("does not forward hop-by-hop headers", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    await send(port, "/openai/v1/models", { headers: { "proxy-authorization": "x", "x-hop": "1", connection: "x-hop", te: "trailers" } });
    expect(upstream.seen[0]!.headers["proxy-authorization"]).toBeUndefined();
    expect(upstream.seen[0]!.headers["x-hop"]).toBeUndefined();
    expect(upstream.seen[0]!.headers.te).toBeUndefined();
  });

  it("streams a non-rewrite POST body through", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    const body = JSON.stringify({ messages: anthropicBody(RESULTS).messages });
    await send(port, "/anthropic/v1/messages/count_tokens", { method: "POST", headers: { "content-type": "application/json" }, body });
    expect(upstream.seen[0]!.body.toString()).toBe(body);
  });

  it("answers an unknown route with 404 and the route list", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    const reply = await send(port, "/nowhere/v1/messages");
    expect(reply.status).toBe(404);
    expect(reply.body.toString()).toContain("/anthropic/*");
    expect(upstream.seen).toHaveLength(0);
  });

  it("refuses a WebSocket upgrade by closing the socket", async () => {
    const upstream = await fakeUpstream();
    const { port } = await proxyTo(upstream.url);
    const outcome = await new Promise<string>(resolve => {
      const req = request({ host: "127.0.0.1", port, path: "/chatgpt/backend-api/codex/responses", headers: { connection: "Upgrade", upgrade: "websocket" }, agent: false });
      req.on("upgrade", () => resolve("upgraded"));
      req.on("error", () => resolve("closed"));
      req.on("response", () => resolve("response"));
      req.end();
    });
    expect(outcome).toBe("closed");
    expect(upstream.seen).toHaveLength(0);
  });

  it("answers 502 when the upstream is down", async () => {
    const { server, url } = await listen(() => undefined);
    await new Promise<void>(resolve => server.close(() => resolve()));
    const { port } = await proxyTo(url);
    const get = await send(port, "/anthropic/v1/models");
    expect(get.status).toBe(502);
    expect(get.headers["content-type"]).toContain("text/plain");
    const rewritten = await post(port, "/anthropic/v1/messages", anthropicBody(RESULTS));
    expect(rewritten.status).toBe(502);
  });
});

describe("streaming", () => {
  it("delivers the first SSE event before the upstream ends", async () => {
    const release = Promise.withResolvers<void>();
    const upstream = await fakeUpstream(async (_seen, res) => {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      res.write("event: message_start\ndata: {\"n\":1}\n\n");
      await release.promise;
      res.write("event: message_stop\ndata: {\"n\":2}\n\n");
      res.end();
    });
    const { port } = await proxyTo(upstream.url);
    const body = JSON.stringify(anthropicBody(RESULTS));
    const received: string[] = [];
    const first = Promise.withResolvers<void>();
    const done = new Promise<void>((resolve, reject) => {
      const req = request({ host: "127.0.0.1", port, path: "/anthropic/v1/messages", method: "POST", headers: { "content-type": "application/json" }, agent: false }, res => {
        res.setEncoding("utf8");
        res.on("data", (chunk: string) => { received.push(chunk); first.resolve(); });
        res.on("end", resolve);
      });
      req.on("error", reject);
      req.end(body);
    });
    // a proxy that buffered the stream would never get here: the upstream waits for `release`
    await first.promise;
    expect(received.join("")).toContain("message_start");
    expect(received.join("")).not.toContain("message_stop");
    release.resolve();
    await done;
    expect(received.join("")).toContain("message_stop");
  });
});
