import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import factory from "../src/index";
import { normalizePath } from "../src/v3-memory";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

type Handler = (event: any, ctx: ExtensionContext) => unknown;

const ENV_KEYS = ["SECOND_BRAIN_HOME", "SECOND_BRAIN_V3", "SECOND_BRAIN_OBSERVABILITY"] as const;
const saved: Record<string, string | undefined> = {};
let home = "";
let repo = "";

beforeEach(() => {
  for (const key of ENV_KEYS) saved[key] = process.env[key];
  const root = mkdtempSync(join(tmpdir(), "v3-wiring-"));
  home = join(root, "brain");
  repo = join(root, "repo");
  mkdirSync(repo, { recursive: true });
  const views = join(home, "views");
  mkdirSync(join(views, "p1"), { recursive: true });
  writeFileSync(join(views, "projects.json"), JSON.stringify([{ id: "p1", paths: [normalizePath(repo)] }]));
  writeFileSync(join(views, "p1", "brief.md"), "# Brain brief — p1\n- Decision [mem-aaaaaaaaaaaa]\n");
  writeFileSync(
    join(views, "p1", "corrections.json"),
    JSON.stringify([{ id: "mem-cccccccccccc", errors: ["SRE module mismatch"], text: "Unset PYTHONHOME" }]),
  );
  process.env.SECOND_BRAIN_HOME = home;
  process.env.SECOND_BRAIN_V3 = "on";
  delete process.env.SECOND_BRAIN_OBSERVABILITY;
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  rmSync(join(home, ".."), { recursive: true, force: true });
});

function load(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const pi = {
    on: (name: string, handler: Handler): void => void handlers.set(name, handler),
    appendEntry: (): void => undefined,
  } as unknown as ExtensionAPI;
  factory(pi);
  return handlers;
}

function ctx(session: string): ExtensionContext {
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    cwd: repo,
    model: { id: "m", provider: "p" },
    getContextUsage: () => ({ tokens: 10, contextWindow: 1000, percent: 1 }),
    getSystemPrompt: () => "BASE",
    signal: undefined,
    hasUI: false,
    ui: undefined,
    sessionManager: {
      getSessionFile: () => join(home, "sessions", `${session}.jsonl`),
      getSessionId: () => session,
      getHeader: () => ({ type: "session", version: 1, id: session, timestamp }),
      getEntries: () => [],
    },
  } as unknown as ExtensionContext;
}

describe("V3 wiring (SECOND_BRAIN_V3=on)", () => {
  it("sends the brief on the first turn only, and again after compaction", async () => {
    const handlers = load();
    const start = handlers.get("before_agent_start")!;
    const first = (await start({ prompt: "hello" }, ctx("s1"))) as { message?: { content: string; customType: string } };
    expect(first.message?.customType).toBe("brain.v3.brief");
    expect(first.message?.content).toContain("[mem-aaaaaaaaaaaa]");
    expect(await start({ prompt: "second prompt" }, ctx("s1"))).toBeUndefined();

    await handlers.get("session_before_compact")!({ preparation: {} }, ctx("s1"));
    const afterCompact = (await start({ prompt: "third" }, ctx("s1"))) as { message?: { content: string } };
    expect(afterCompact.message?.content).toContain("[mem-aaaaaaaaaaaa]");

    const telemetry = readFileSync(join(home, "telemetry", "kb-hooks.jsonl"), "utf8").trim().split("\n");
    expect(telemetry.length).toBeGreaterThanOrEqual(2);
  });

  it("appends one correction to a failed tool result and nothing to a successful one", async () => {
    const handlers = load();
    const toolResult = handlers.get("tool_result")!;
    const failed = (await toolResult(
      { toolName: "bash", toolCallId: "t1", input: {}, isError: true, content: [{ type: "text", text: "AssertionError: SRE module mismatch" }] },
      ctx("s2"),
    )) as { content: Array<{ type: string; text: string }> };
    expect(failed.content).toHaveLength(2);
    expect(failed.content[1].text).toBe("Brain correction (advisory): Unset PYTHONHOME [mem-cccccccccccc]");

    expect(
      await toolResult(
        { toolName: "bash", toolCallId: "t2", input: {}, isError: false, content: [{ type: "text", text: "SRE module mismatch" }] },
        ctx("s2"),
      ),
    ).toBeUndefined();
    expect(
      await toolResult(
        { toolName: "bash", toolCallId: "t3", input: {}, isError: true, content: [{ type: "text", text: "other failure" }] },
        ctx("s2"),
      ),
    ).toBeUndefined();
  });

  it("adds nothing when the project has no brief", async () => {
    writeFileSync(join(home, "views", "p1", "brief.md"), "");
    const handlers = load();
    expect(await handlers.get("before_agent_start")!({ prompt: "hi" }, ctx("s3"))).toBeUndefined();
  });
});
