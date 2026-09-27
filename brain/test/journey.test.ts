/**
 * The whole loop through the real extension (a fake OMP host calls the handlers and tools the way
 * OMP does) and the real CLI: work → compaction → resume → capture → review → next session's card
 * and known fix → cross-project scope.
 */
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { main } from "../src/cli.ts";
import secondBrain, { CARD_TYPE, type HostLike } from "../src/omp.ts";

type Handler = (event: unknown, ctx: unknown) => unknown;
interface Tool {
  name: string;
  execute: (...args: unknown[]) => { content: { text: string }[] };
}

function repo(name: string, manifest: string): string {
  const dir = join(mkdtempSync(join(tmpdir(), "journey-")), name);
  mkdirSync(join(dir, ".git"), { recursive: true });
  writeFileSync(join(dir, ".git", "config"), "[core]\n");
  writeFileSync(join(dir, manifest), "{}");
  return dir;
}

function omp(home: string) {
  const handlers = new Map<string, Handler>();
  const tools = new Map<string, Tool>();
  const pi: HostLike = { on: (e, h) => void handlers.set(e, h), registerTool: (t) => void tools.set((t as Tool).name, t as Tool) };
  secondBrain(pi, { SECOND_BRAIN_HOME: home });
  const fire = (event: string, payload: unknown, ctx: unknown) => handlers.get(event)?.(payload, ctx);
  const call = (tool: string, params: unknown, ctx: unknown) => tools.get(tool)?.execute("call-1", params, undefined, undefined, ctx).content[0]?.text ?? "";
  return { fire, call };
}

async function cli(home: string, cwd: string, ...argv: string[]): Promise<string> {
  const out: string[] = [];
  await main(argv, { env: { SECOND_BRAIN_HOME: home }, cwd, out: (s) => out.push(s), err: (s) => out.push(`ERR ${s}`) });
  return out.join("\n");
}

it("a failure fixed in one session becomes the known fix, the card and the resume of the next", async () => {
  const home = mkdtempSync(join(tmpdir(), "journey-home-"));
  const app = repo("shop-app", "package.json");
  const tool = repo("etl-tool", "pyproject.toml");

  // Session 1 in the app: nothing known yet, so no card.
  const day1 = omp(home);
  const s1 = { cwd: app, sessionManager: { getSessionId: () => "s1" } };
  expect(day1.fire("before_agent_start", { prompt: "make the tests pass" }, s1)).toBeUndefined();
  expect(day1.call("brain_state", { text: "Goal: green test suite. Next: install deps, rerun." }, s1)).toMatch(/^state saved/);
  day1.fire("tool_result", { toolName: "bash", input: { command: "npm test" }, isError: true, content: [{ type: "text", text: "Error: Cannot find module 'left-pad'" }] }, s1);
  day1.fire("tool_result", { toolName: "bash", input: { command: "npm ci && npm test" }, isError: false, content: [{ type: "text", text: "ok" }] }, s1);
  day1.fire("tool_result", { toolName: "edit", input: { path: join(app, "src", "cart.ts") }, isError: false, content: [] }, s1);

  // Compaction mid-run: the model's next calls start with the resume card.
  day1.fire("session_before_compact", {}, s1);
  day1.fire("session_compact", {}, s1);
  const patched = day1.fire("context", { messages: [{ role: "compactionSummary", summary: "…" }] }, s1) as { messages: { customType?: string; content?: string }[] };
  const resume = patched.messages[0];
  expect(resume?.customType).toBe(CARD_TYPE);
  expect(resume?.content).toContain("Goal: green test suite.");
  expect(resume?.content).toContain("- edited: src/cart.ts");
  expect(resume?.content).toContain("- last failure: npm test → Error: Cannot find module 'left-pad'");
  day1.fire("session_shutdown", {}, s1);

  // Between sessions: review turns the failed → fixed pair into a tested gotcha.
  const review = await cli(home, app, "review");
  const pid = /^(p-[0-9a-f]+) \[gotcha, tested\] npm: npm test fails/m.exec(review)?.[1];
  expect(pid, review).toBeDefined();
  expect(await cli(home, app, "accept", pid as string)).toMatch(/^accepted p-[0-9a-f]+ → n-[0-9a-f]{10}$/);

  // Session 2 in the app: the card resumes the work and knows the gotcha …
  const day2 = omp(home);
  const s2 = { cwd: app, sessionManager: { getSessionId: () => "s2" } };
  const card = (day2.fire("before_agent_start", { prompt: "continue" }, s2) as { message: { content: string } }).message.content;
  expect(card).toMatch(/^Brain · shop-app/);
  expect(card).toContain("Where we left off");
  expect(card).toContain("[gotcha, tested] npm: npm test fails (Error: Cannot find module 'left-pad')");
  expect(card).toContain("brain_state(");
  // … and the same failure gets its fix appended.
  const failed = day2.fire("tool_result", { toolName: "bash", input: { command: "npm test" }, isError: true, content: [{ type: "text", text: "Error: Cannot find module 'left-pad'\n  at require" }] }, s2) as {
    content: { text: string }[];
  };
  expect(failed.content.at(-1)?.text).toMatch(/^Brain \(advisory\): npm: npm test fails .*npm ci && npm test works/);

  // Another project does not see the app's gotcha unless asked across projects.
  const other = { cwd: tool, sessionManager: { getSessionId: () => "s3" } };
  expect(day2.call("brain_recall", { query: "left-pad module" }, other)).toBe("no match");
  expect(day2.call("brain_recall", { query: "left-pad module", all: true }, other)).toContain("npm test fails");
  // A learning marked global reaches every project; a duplicate is refused.
  expect(day2.call("brain_note", { text: "Use UTC timestamps in every log line", kind: "decision", global: true }, other)).toMatch(/^saved n-/);
  expect(day2.call("brain_note", { text: "use utc timestamps in every log line", global: true }, other)).toMatch(/^already noted n-/);
  expect(day2.call("brain_recall", { query: "UTC timestamps log" }, s2)).toContain("[decision] Use UTC timestamps in every log line");
});
