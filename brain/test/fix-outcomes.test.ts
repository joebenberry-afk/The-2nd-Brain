/**
 * Fix outcomes: which results may judge a fired fix, and which outcome rows may pause it.
 * (OMP's side is in omp.test.ts; the Claude Code hook and the telemetry rules are here.)
 */
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { main } from "../src/cli.ts";
import { appendEvent } from "../src/capture.ts";
import { createNote } from "../src/notes.ts";
import { demotedFixes, logUse, stats } from "../src/telemetry.ts";

const tmp = (prefix = "brain-fixout-") => mkdtempSync(join(tmpdir(), prefix));

function repo(name: string): string {
  const dir = join(tmp(), name);
  mkdirSync(join(dir, ".git"), { recursive: true });
  writeFileSync(join(dir, ".git", "config"), "[core]\n\tbare = false\n");
  return dir;
}

describe("pausing a fix on outcome rows", () => {
  const FIX = "n-fix";
  const T0 = Date.UTC(2026, 9, 12, 10, 0, 0);
  const at = (seconds: number) => new Date(T0 + seconds * 1000);
  const fire = (home: string, session: string, seconds: number) => logUse(home, { kind: "fix", id: FIX, project: "demo", session, tokens: 0, ms: 0 }, at(seconds));
  const outcome = (home: string, session: string, seconds: number, result: "helped" | "missed") => logUse(home, { kind: "fixout", id: FIX, project: "demo", session, outcome: result, tokens: 0, ms: 0 }, at(seconds));
  const paused = (home: string) => demotedFixes(home, () => undefined).has(FIX);

  it("does not count outcomes scored in the second their fix fired", () => {
    const home = tmp();
    // Older builds scored the next same-key result: a sibling of the same batch, not an answer.
    for (const [i, session] of ["a", "b", "c", "d"].entries()) {
      fire(home, session, i * 100);
      outcome(home, session, i * 100, "missed");
    }
    expect(paused(home)).toBe(false);
    // `brain stats` reports the same evidence the pause rule uses, in every build view.
    fire(home, "e", 500);
    outcome(home, "e", 520, "helped");
    for (const allBuilds of [true, false]) {
      expect(stats(home, 7, at(600), { allBuilds }).fixOutcomes).toEqual([{ id: FIX, firings: 5, helped: 1, missed: 0 }]);
    }
  });

  it("neither lets such rows rescue a fix that real answers show failing", () => {
    const home = tmp();
    for (const [i, result] of (["helped", "missed", "missed", "missed"] as const).entries()) {
      fire(home, "real", i * 100);
      outcome(home, "real", i * 100 + 5, result);
    }
    expect(paused(home)).toBe(true);
    for (let i = 0; i < 5; i++) {
      fire(home, `sibling-${i}`, 1000 + i * 100);
      outcome(home, `sibling-${i}`, 1000 + i * 100, "helped");
    }
    expect(paused(home)).toBe(true);
  });

  it("counts a miss written in the same second as the fix's re-fire", () => {
    const home = tmp();
    // The failing retry scores the first firing and fires again in one tool result: outcome, then fire.
    fire(home, "retry", 0);
    for (let i = 1; i <= 4; i++) {
      outcome(home, "retry", i * 30, "missed");
      fire(home, "retry", i * 30);
    }
    expect(paused(home)).toBe(true);
  });
});

describe("Claude Code hook outcomes and capture timing", () => {
  function hooks() {
    const home = tmp();
    const cwd = repo("demo");
    const transcript = join(home, "transcript.jsonl");
    const lines: string[] = [];
    /** One tool_use block, written as its own row like the host does; `message` is the model message. */
    const call = (message: string, toolUse: string) => {
      lines.push(JSON.stringify({ type: "assistant", message: { id: message, content: [{ type: "tool_use", id: toolUse, name: "Bash", input: {} }] } }));
      writeFileSync(transcript, lines.join("\n") + "\n");
    };
    const send = async (payload: Record<string, unknown>): Promise<{ hookSpecificOutput?: { additionalContext?: string } }> => {
      const out: string[] = [];
      await main(["hook", "claude-code"], { env: { SECOND_BRAIN_HOME: home }, cwd, stdin: () => JSON.stringify({ cwd, session_id: "s", transcript_path: transcript, ...payload }), out: text => out.push(text), err: () => undefined });
      return JSON.parse(out.join(""));
    };
    const failure = (toolUse: string) => send({ hook_event_name: "PostToolUseFailure", tool_name: "Bash", tool_input: { command: "build" }, error: "runtime mismatch", tool_use_id: toolUse });
    const success = (toolUse: string) => send({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "build" }, tool_use_id: toolUse });
    const outcomes = () => {
      const text = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n");
      return text.map(line => JSON.parse(line)).filter(row => row.kind === "fixout").map(row => [row.id, row.outcome]);
    };
    const note = createNote(home, { project: "demo", text: "Install runtime", tested: true, errors: ["runtime mismatch"] });
    return { home, cwd, call, send, failure, success, outcomes, note };
  }

  it("scores a fix on a later model message, never on a sibling call of the message that got it", async () => {
    const { call, failure, success, outcomes, note } = hooks();
    call("msg_1", "toolu_a");
    call("msg_1", "toolu_b");
    call("msg_2", "toolu_c");
    expect((await failure("toolu_a")).hookSpecificOutput?.additionalContext).toContain("Install runtime");
    // A parallel sibling finishes before the model has seen the fix.
    await success("toolu_b");
    expect(outcomes()).toEqual([]);
    await success("toolu_c");
    expect(outcomes()).toEqual([[note.id, "helped"]]);
    await success("toolu_c");
    expect(outcomes()).toHaveLength(1);
  });

  it("a failing sibling gets no outcome; the next message's failure is a miss", async () => {
    const { call, failure, outcomes, note } = hooks();
    call("msg_1", "toolu_a");
    call("msg_1", "toolu_b");
    call("msg_2", "toolu_c");
    await failure("toolu_a");
    await failure("toolu_b");
    expect(outcomes()).toEqual([]);
    await failure("toolu_c");
    expect(outcomes()).toEqual([[note.id, "missed"]]);
  });

  it("waits for a call that is provably from a later message", async () => {
    const { call, failure, success, outcomes, note } = hooks();
    call("msg_1", "toolu_a");
    call("msg_2", "toolu_c");
    await failure("toolu_a");
    // A call the transcript does not show yet cannot be placed after the fix.
    await success("toolu_unwritten");
    expect(outcomes()).toEqual([]);
    await success("toolu_c");
    expect(outcomes()).toEqual([[note.id, "helped"]]);
  });

  it.each(["SessionEnd", "PreCompact"])("catches up on earlier sessions' events at %s, not at SessionStart", async (event) => {
    const { home, cwd, send } = hooks();
    appendEvent(home, "earlier", cwd, { tool: "bash", command: "npm test", ok: false, error: "boom: failed" });
    appendEvent(home, "earlier", cwd, { tool: "bash", command: "npm ci && npm test", ok: true });
    const cursor = join(home, "state", "capture-cursor.json");
    createNote(home, { project: "demo", text: "Demo decision", kind: "decision" });
    const start = await send({ hook_event_name: "SessionStart", source: "startup" });
    expect(start.hookSpecificOutput?.additionalContext).toContain("Demo decision");
    expect(existsSync(cursor)).toBe(false);
    await send({ hook_event_name: event });
    expect(readdirSync(join(home, "state", "events"))).toHaveLength(1);
    expect(Object.values(JSON.parse(readFileSync(cursor, "utf8")) as Record<string, number>)[0]).toBeGreaterThan(0);
  });
});
