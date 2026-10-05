import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { main } from "../src/cli.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { rolloverHint } from "../src/rollover.ts";
import { estimateTokens } from "../src/util.ts";

const homes: string[] = [];
function home(rollover?: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "brain-rollover-test-"));
  homes.push(dir);
  if (rollover !== undefined) writeFileSync(join(dir, "projects.json"), JSON.stringify({ projects: { demo: { rollover } } }));
  return dir;
}
afterEach(() => { for (const dir of homes.splice(0)) rmSync(dir, { recursive: true, force: true }); });

const line = "Brain: context 151k. Save brain_state (Goal/Next/See:) and start a fresh session; the card carries it over.";
describe("rollover threshold", () => {
  it("fires once per crossing, survives host reload, and rearms below the threshold", () => {
    const dir = home();
    expect(rolloverHint(dir, "demo", "main", 150000)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 150001)).toBe(line);
    expect(rolloverHint(dir, "demo", "main", 300000)).toBe("");
    expect(rolloverHint(dir, "demo", "main", undefined)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 300000)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 100000)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 150001)).toBe(line);
    expect(rolloverHint(dir, "demo", "fresh", 150001)).toBe(line);
    expect(estimateTokens(line)).toBeLessThanOrEqual(40);
    expect(line).not.toContain("\n");
  });
  it("silences subagents without consuming the main-session crossing", () => {
    const dir = home();
    expect(rolloverHint(dir, "demo", "main", 150001, true)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 150001)).toBe(line);
  });
  it("obeys config 0 and custom numeric thresholds without env flags", () => {
    expect(rolloverHint(home(0), "demo", "main", 900000)).toBe("");
    const dir = home(10000);
    expect(rolloverHint(dir, "demo", "main", 10000)).toBe("");
    expect(rolloverHint(dir, "demo", "main", 11000)).toContain("context 11k");
    for (const invalid of [-1, "0", null]) expect(rolloverHint(home(invalid), "demo", "main", 150001)).toBe(line);
  });
  it("fails open on invalid usage and unavailable state storage", () => {
    const dir = home();
    for (const tokens of [NaN, Infinity, -1, "251000", null]) expect(rolloverHint(dir, "demo", "main", tokens)).toBe("");
    writeFileSync(join(dir, "state"), "not a directory");
    expect(rolloverHint(dir, "demo", "main", 150001)).toBe("");
  });
});

describe("host rollover delivery", () => {
  it("reads Claude input plus cache usage, not cumulative output; Stop and tool hooks share one latch", async () => {
    const dir = home(), transcript = join(dir, "transcript.jsonl");
    const usage = (input: number) => writeFileSync(transcript, JSON.stringify({ type: "assistant", message: { usage: { input_tokens: input, cache_read_input_tokens: 140000, cache_creation_input_tokens: 5000, output_tokens: 999999 } } }) + "\n{unfinished");
    const hook = async (event: string, extra: object = {}) => {
      let out = "";
      const code = await main(["hook", "claude-code"], { env: { SECOND_BRAIN_HOME: dir, BRAIN_PROJECT: "demo" }, cwd: dir, stdin: () => JSON.stringify({ hook_event_name: event, session_id: "main", transcript_path: transcript, tool_name: "Read", ...extra }), out: text => { out = text; }, err: () => {} });
      expect(code).toBe(0);
      return JSON.parse(out);
    };
    usage(5000);
    expect(await hook("PostToolUse")).toEqual({});
    usage(6000);
    expect(await hook("PostToolUse", { agent_id: "child" })).toEqual({});
    expect(await hook("PostToolUse")).toEqual({ hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: line } });
    expect(await hook("Stop")).toEqual({});
    usage(1000); await hook("Stop"); usage(6000);
    expect(await hook("Stop", { agent_type: "custom-main" })).toEqual({ systemMessage: line });
  });
  it("keeps both Claude hooks silent with config 0 or a missing transcript", async () => {
    const dir = home(0), transcript = join(dir, "transcript.jsonl");
    writeFileSync(transcript, JSON.stringify({ type: "assistant", message: { usage: { input_tokens: 900000 } } }) + "\n");
    for (const event of ["Stop", "PostToolUse"]) {
      let out = "";
      await main(["hook", "claude-code"], { env: { SECOND_BRAIN_HOME: dir, BRAIN_PROJECT: "demo" }, cwd: dir, stdin: () => JSON.stringify({ hook_event_name: event, session_id: event, transcript_path: transcript }), out: text => { out = text; }, err: () => {} });
      expect(JSON.parse(out)).toEqual({});
    }
  });
  it("uses OMP context occupancy and queues no extra model turn; subagents and off are silent", () => {
    const dir = home(), handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>(), sendMessage = vi.fn();
    const host: HostLike = { on: (name, fn) => { handlers.set(name, fn); }, sendMessage };
    secondBrain(host, { SECOND_BRAIN_HOME: dir, BRAIN_PROJECT: "demo" });
    const ctx = (tokens: number, kind = "main") => ({ cwd: dir, agent: { kind }, getContextUsage: () => ({ tokens }), sessionManager: { getSessionId: () => "main" } });
    const turn = (tokens: number, kind = "main") => handlers.get("turn_end")!({}, ctx(tokens, kind));
    turn(150000); turn(150001, "sub"); expect(sendMessage).not.toHaveBeenCalled();
    turn(150001); turn(300000);
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith({ customType: "brain.rollover", content: line, display: false }, { triggerTurn: false, deliverAs: "nextTurn" });
    turn(100000); turn(150001); expect(sendMessage).toHaveBeenCalledTimes(2);
    writeFileSync(join(dir, "projects.json"), JSON.stringify({ projects: { demo: { rollover: 0 } } }));
    turn(500000); expect(sendMessage).toHaveBeenCalledTimes(2);
  });
});
