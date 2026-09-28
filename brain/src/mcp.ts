/** Local MCP stdio transport: newline-delimited JSON-RPC, never diagnostic stdout. */
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { brainTools, jsonSchema } from "./tools.ts";
import { logUse } from "./telemetry.ts";
import { estimateTokens, findHome } from "./util.ts";

// 2025-03-26 is left out: it requires JSON-RPC batches, which this server does not accept.
const PROTOCOLS = ["2024-11-05", "2025-06-18"];
type Json = Record<string, unknown>;

function object(value: unknown): Json | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Json : undefined;
}

export async function runMcp(opts: {
  home?: string;
  env?: NodeJS.ProcessEnv;
  input?: NodeJS.ReadableStream;
  output?: NodeJS.WritableStream;
} = {}): Promise<number> {
  const env = opts.env ?? process.env;
  const input = opts.input ?? process.stdin;
  const output = opts.output ?? process.stdout;
  const lines = createInterface({ input, terminal: false, crlfDelay: Infinity });
  let failed = false;
  const ioError = () => { failed = true; lines.close(); };
  input.on("error", ioError);
  output.on("error", ioError);
  const send = async (message: Json): Promise<void> => {
    await new Promise<void>((resolve, reject) => {
      output.write(JSON.stringify(message) + "\n", (error?: Error | null) => error ? reject(error) : resolve());
    });
  };
  try {
    const home = findHome(opts.home, env);
    const session = env.BRAIN_SESSION ?? env.CLAUDE_SESSION_ID;
    const cwd = process.cwd();
    for await (const line of lines) {
      if (failed) break;
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        await send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
        continue;
      }
      const request = object(parsed);
      const id = request?.id;
      if (!request || request.jsonrpc !== "2.0" || typeof request.method !== "string"
        || (id !== undefined && typeof id !== "string" && !(typeof id === "number" && Number.isFinite(id)))) {
        await send({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "Invalid Request" } });
        continue;
      }
      // Notifications never get responses or perform tool writes, including initialized/cancelled.
      if (id === undefined) continue;
      const params = object(request.params);
      let result: unknown;
      try {
        switch (request.method) {
          case "initialize": {
            const requested = params?.protocolVersion;
            const metadata = object(JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")));
            if (typeof metadata?.version !== "string") throw new Error("missing package version");
            result = {
              protocolVersion: typeof requested === "string" && PROTOCOLS.includes(requested) ? requested : PROTOCOLS[PROTOCOLS.length - 1],
              capabilities: { tools: {} },
              serverInfo: { name: "second-brain", version: metadata.version },
            };
            break;
          }
          case "ping":
            result = {};
            break;
          case "tools/list":
            result = { tools: brainTools.map(tool => ({ name: tool.name, description: tool.description, inputSchema: jsonSchema(tool.params) })) };
            break;
          case "tools/call": {
            // Unknown tools and malformed arguments are protocol errors (-32602); isError is
            // reserved for a valid call whose execution failed.
            const tool = brainTools.find(tool => tool.name === params?.name);
            const args = params?.arguments === undefined ? {} : object(params.arguments);
            let invalid = !tool ? `unknown tool: ${String(params?.name)}` : !args ? "arguments must be an object" : "";
            if (tool && args) {
              for (const [key, prop] of Object.entries(tool.params)) {
                if (!(key in args) && prop.optional) continue;
                if (typeof args[key] !== prop.type) invalid ||= `${key} must be a ${prop.type}`;
              }
              for (const key of Object.keys(args)) if (!Object.hasOwn(tool.params, key)) invalid ||= `unknown argument: ${key}`;
            }
            if (invalid || !tool || !args) {
              await send({ jsonrpc: "2.0", id, error: { code: -32602, message: invalid } });
              continue;
            }
            try {
              if (!home) throw new Error("Brain home not found; set SECOND_BRAIN_HOME");
              const started = performance.now();
              // MCP has no child identity: the host must withhold brain_state from its children.
              const used = tool.run(args, { home, cwd, env, sub: false, session });
              if (used.kind) logUse(home, { kind: used.kind, project: used.project, tokens: estimateTokens(used.text), ms: performance.now() - started, session, sub: false, hits: used.hits, query: used.query, ids: used.ids, via: "mcp" });
              result = { content: [{ type: "text", text: used.text }], isError: false };
            } catch (error) {
              result = { content: [{ type: "text", text: `brain: ${error instanceof Error ? error.message : String(error)}` }], isError: true };
            }
            break;
          }
          default:
            await send({ jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
            continue;
        }
      } catch (error) {
        await send({ jsonrpc: "2.0", id, error: { code: -32603, message: error instanceof Error ? error.message : String(error) } });
        continue;
      }
      await send({ jsonrpc: "2.0", id, result });
    }
    return failed ? 1 : 0;
  } catch {
    // A disconnected client or broken stream must not bring down its host.
    return 1;
  } finally {
    lines.close();
    input.off("error", ioError);
    output.off("error", ioError);
  }
}
