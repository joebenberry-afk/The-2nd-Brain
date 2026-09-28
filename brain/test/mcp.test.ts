import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough, Writable } from "node:stream";
import { afterEach, expect, it } from "vitest";
import { runMcp } from "../src/mcp.ts";
import { loadNotes } from "../src/notes.ts";
import { readWork } from "../src/work.ts";

const homes: string[] = [];
afterEach(() => { for (const home of homes.splice(0)) rmSync(home, { recursive: true, force: true }); });

interface Response {
  jsonrpc: string;
  id: number | string | null;
  result?: {
    protocolVersion?: string;
    capabilities?: unknown;
    serverInfo?: { name: string; version: string };
    tools?: { name: string; inputSchema: { type: string; required: string[]; properties: Record<string, { type: string }>; additionalProperties: boolean } }[];
    content?: { type: string; text: string }[];
    isError?: boolean;
  };
  error?: { code: number };
}

async function exchange(messages: unknown[]) {
  const home = mkdtempSync(join(tmpdir(), "brain-mcp-"));
  homes.push(home);
  const input = new PassThrough();
  const output = new PassThrough();
  let text = "";
  output.setEncoding("utf8");
  output.on("data", (chunk: string) => { text += chunk; });
  const running = runMcp({ home, env: { BRAIN_PROJECT: "demo", BRAIN_SESSION: "mcp-session" }, input, output });
  input.end(messages.map(message => typeof message === "string" ? message : JSON.stringify(message)).join("\n") + "\n");
  const code = await running;
  return { home, code, replies: text.trim().split("\n").map(line => JSON.parse(line) as Response) };
}

it("negotiates, discovers tools, saves and recalls memory, and recovers after invalid requests", async () => {
  const { home, code, replies } = await exchange([
    { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "test", version: "1" } } },
    { jsonrpc: "2.0", method: "notifications/initialized" },
    { jsonrpc: "2.0", id: "tools", method: "tools/list" },
    { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "brain_note", arguments: { text: "Compiler needs a project-local plugin", kind: "gotcha" } } },
    { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "brain_recall", arguments: { query: "compiler plugin" } } },
    { jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "not_a_tool", arguments: {} } },
    "not json",
    { jsonrpc: "2.0", id: 6, method: "ping" },
    { jsonrpc: "2.0", id: 7, method: "unknown" },
    { jsonrpc: "2.0", id: 8, method: "tools/call", params: { name: "brain_state", arguments: { text: "Goal: ship. Next: test plugin." } } },
  ]);
  expect(code).toBe(0);
  expect(replies.map(reply => reply.id)).toEqual([1, "tools", 3, 4, 5, null, 6, 7, 8]);
  const init = replies[0]!.result!;
  expect(init.protocolVersion).toBe("2024-11-05");
  expect(init.capabilities).toEqual({ tools: {} });
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string };
  expect(init.serverInfo).toEqual({ name: "second-brain", version: pkg.version });
  const tools = replies[1]!.result!.tools!;
  expect(tools.map(tool => tool.name)).toEqual(["brain_recall", "brain_note", "brain_state"]);
  for (const tool of tools) {
    expect(tool.inputSchema.type).toBe("object");
    expect(tool.inputSchema.additionalProperties).toBe(false);
    const required = tool.name === "brain_recall" ? "query" : "text";
    expect(tool.inputSchema.required).toEqual([required]);
    expect(tool.inputSchema.properties[required]).toMatchObject({ type: "string" });
  }
  const note = loadNotes(home).notes[0]!;
  expect(note.body).toBe("Compiler needs a project-local plugin");
  expect(replies[2]!.result!.content).toEqual([{ type: "text", text: "saved " + note.id }]);
  expect(replies[3]!.result!.content![0]!.text).toContain(note.body);
  expect(replies[4]!.error?.code).toBe(-32602);
  expect(replies[5]!.error?.code).toBe(-32700);
  expect(replies[6]).toEqual({ jsonrpc: "2.0", id: 6, result: {} });
  expect(replies[7]!.error?.code).toBe(-32601);
  expect(readWork(home, "demo")?.text).toBe("Goal: ship. Next: test plugin.");
  const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line) as { kind: string; via: string; session: string });
  expect(rows.map(row => ({ kind: row.kind, via: row.via, session: row.session }))).toEqual([
    { kind: "note", via: "mcp", session: "mcp-session" },
    { kind: "recall", via: "mcp", session: "mcp-session" },
    { kind: "state", via: "mcp", session: "mcp-session" },
  ]);
});

it.each(["2024-11-05", "2025-06-18", "2025-03-26", "unsupported"])("negotiates protocol %s", async version => {
  const { replies } = await exchange([{ jsonrpc: "2.0", id: 0, method: "initialize", params: { protocolVersion: version } }]);
  // 2025-03-26 would oblige batch support: the server answers with the version it speaks.
  expect(replies[0]!.result!.protocolVersion).toBe(version === "2024-11-05" ? version : "2025-06-18");
});

it("rejects malformed calls as protocol errors, failed execution as isError, without writing", async () => {
  const { home, replies } = await exchange([
    { jsonrpc: "2.0", method: "tools/call", params: { name: "brain_note", arguments: { text: "not a request" } } },
    { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "brain_note", arguments: { text: "bad boolean", tested: "yes" } } },
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "brain_note", arguments: { text: "  " } } },
    { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "brain_state", arguments: { text: "Goal: invalid extra", extra: true } } },
    null,
    { jsonrpc: "2.0", id: 4, method: "ping" },
  ]);
  expect(replies.map(reply => reply.id)).toEqual([1, 2, 3, null, 4]);
  expect(replies.map(reply => reply.error?.code ?? (reply.result?.isError ? "isError" : "ok")).slice(0, 3)).toEqual([-32602, "isError", -32602]);
  expect(loadNotes(home).notes).toEqual([]);
  expect(readWork(home, "demo")).toBeNull();
  expect(replies[3]!.error?.code).toBe(-32600);
  expect(replies[4]!.result).toEqual({});
});

it("settles without an unhandled stream error when the client disconnects", async () => {
  const input = new PassThrough();
  const output = new Writable({ write(_chunk, _encoding, callback) { callback(new Error("closed pipe")); } });
  const running = runMcp({ input, output });
  input.end('{"jsonrpc":"2.0","id":1,"method":"ping"}\n');
  expect(await running).toBe(1);
});
