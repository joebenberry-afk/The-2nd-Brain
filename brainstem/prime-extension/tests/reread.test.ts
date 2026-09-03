import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

type Handler = (event: unknown, ctx: ExtensionContext) => unknown;
const savedHome = process.env.SECOND_BRAIN_HOME;

beforeEach(() => {
  delete process.env.SECOND_BRAIN_REREAD_AVOIDANCE;
});
afterEach(() => {
  if (savedHome === undefined) delete process.env.SECOND_BRAIN_HOME;
  else process.env.SECOND_BRAIN_HOME = savedHome;
});

async function setup(mode: "OFF" | "SHADOW" | "ACTIVE") {
  const home = await mkdtemp(join(tmpdir(), "sb-reread-"));
  await mkdir(join(home, "telemetry"), { recursive: true });
  process.env.SECOND_BRAIN_HOME = home;
  process.env.SECOND_BRAIN_REREAD_AVOIDANCE = mode;
  const handlers = new Map<string, Handler>();
  let runnerCalls = 0;
  const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler) } as unknown as ExtensionAPI;
  const options: ExtensionOptions = {
    rereadHintRunner: async () => {
      runnerCalls += 1;
      return { unchanged: true, prior_artifact: "sha256:prior", prior_turn: 3 };
    },
  };
  factory(pi, options);
  return { handlers, get runnerCalls() { return runnerCalls; } };
}

const context = { cwd: tmpdir(), model: { id: "test-model" }, sessionManager: undefined } as unknown as ExtensionContext;

describe("Prime reread avoidance hook", () => {
  it("SHADOW retains the read result", async () => {
    const { handlers } = await setup("SHADOW");
    const call = await handlers.get("tool_call")!({ toolName: "read", toolCallId: "read-shadow", input: { path: join(tmpdir(), "file") } }, context);
    expect(call).toBeUndefined();
    const result = await handlers.get("tool_result")!({ toolName: "read", toolCallId: "read-shadow", content: [{ type: "text", text: "original" }], isError: false }, context);
    expect(result).toBeUndefined();
  });

  it("ACTIVE replaces only an unchanged read result with a marker", async () => {
    const { handlers } = await setup("ACTIVE");
    const path = join(tmpdir(), `reread-${Date.now()}.txt`);
    await writeFile(path, "unchanged", "utf8");
    await handlers.get("tool_call")!({ toolName: "cat", toolCallId: "read-active", input: { path } }, context);
    const result = await handlers.get("tool_result")!({ toolName: "cat", toolCallId: "read-active", content: [{ type: "text", text: "original" }], isError: false }, context);

    const text = (result as { content: Array<{ text: string }> }).content[0]?.text;
    expect(text).toContain("[SECOND_BRAIN_UNCHANGED");
    expect(text).toContain("sha256:prior");
  });
  it("OFF skips the hint runner entirely", async () => {
    const { handlers, runnerCalls } = await setup("OFF");
    const call = await handlers.get("tool_call")!({
      toolName: "read",
      toolCallId: "read-off",
      input: { path: join(tmpdir(), "file") },
    }, context);
    expect(call).toBeUndefined();
    expect(runnerCalls).toBe(0);
  });
});
