import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { collectAsks, formatWeek, parseAsks, weeklyAsks } from "../src/asks.ts";

const roots: string[] = [];
afterEach(() => { while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true }); });

const t = (minute: number, second = 0): string => new Date(Date.UTC(2026, 9, 5, 10, minute, second)).toISOString();
const jsonl = (...entries: object[]): string[] => entries.map(e => JSON.stringify(e));

const ompUser = (at: string, attribution = "user") => ({ type: "message", timestamp: at, message: { role: "user", attribution, content: [{ type: "text", text: "do it" }] } });
const ompAssistant = (at: string) => ({ type: "message", timestamp: at, message: { role: "assistant", content: [], stopReason: "toolUse" } });
const ompResult = (at: string) => ({ type: "message", timestamp: at, message: { role: "toolResult", content: [] } });

it("OMP: counts every model request of a tool-call loop up to the next prompt, and ignores injected messages", () => {
  const asks = parseAsks(jsonl(
    { type: "session", timestamp: t(0), cwd: "/x" },
    ompUser(t(0, 10)),
    { type: "custom_message", customType: "brain.card", timestamp: t(0, 11), content: "card" },
    ompAssistant(t(0, 20)), ompResult(t(0, 25)), ompAssistant(t(0, 40)), ompResult(t(0, 45)), ompAssistant(t(1, 10)),
    { type: "custom_message", customType: "async-result", timestamp: t(2), content: "job done" },
    ompAssistant(t(2, 10)),
    ompUser(t(5)), // a prompt with no model request is dropped
    ompUser(t(6)),
    ompAssistant(t(6, 30)),
    ompUser(t(9), "agent"), // injected by an agent, not the owner: stays in the open span
    ompAssistant(t(9, 30)),
  ), "omp");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[4, 120], [2, 210]]);
});

it("an idle gap over 5 minutes ends the ask: later turns are a background wake-up and count for nothing", () => {
  const asks = parseAsks(jsonl(
    ompUser(t(0)),
    ompAssistant(t(0, 30)), ompResult(t(1)), ompAssistant(t(1, 30)),
    ompAssistant(t(21, 30)), ompResult(t(22)), ompAssistant(t(22, 30)), ompAssistant(t(23)),
  ), "omp");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[2, 90]]);
});

const ccUser = (at: string, content: unknown, extra: object = {}) => ({ type: "user", isSidechain: false, timestamp: at, message: { role: "user", content }, ...extra });
const ccAssistant = (at: string, id: string, extra: object = {}) => ({ type: "assistant", isSidechain: false, timestamp: at, message: { id, role: "assistant", model: "claude-opus-5-5", content: [{ type: "text", text: "x" }] }, ...extra });
const ccToolResult = (at: string) => ccUser(at, [{ type: "tool_result", tool_use_id: "t1", content: "out" }]);

it("Claude Code: one request spans several content-block entries; tool results, meta, sidechain and harness prompts never split or inflate an ask", () => {
  const asks = parseAsks(jsonl(
    ccUser(t(0), "fix the bug", { origin: { kind: "human" } }),
    ccAssistant(t(0, 5), "m1"), ccAssistant(t(0, 6), "m1"), ccAssistant(t(0, 7), "m1"), // thinking + text + tool_use of one request
    ccToolResult(t(0, 20)),
    ccAssistant(t(0, 30), "m2"),
    ccAssistant(t(0, 40), "side", { isSidechain: true }), // subagent work inside the parent file
    ccUser(t(0, 50), [{ type: "text", text: "[Image: source: x.png]" }], { isMeta: true }),
    ccUser(t(0, 55), "<task-notification>done</task-notification>", { origin: { kind: "task-notification" } }),
    ccUser(t(1), [{ type: "text", text: "<command-name>/compact</command-name>" }]),
    ccAssistant(t(1, 5), "err", { message: { id: "err", role: "assistant", model: "<synthetic>", content: [] } }),
    ccAssistant(t(1, 30), "m3"),
    ccUser(t(3), "second request"),
    ccAssistant(t(3, 30), "m4"),
    ccUser(t(4), "scripted", { entrypoint: "sdk-py" }), // headless harness run, not the owner
    ccAssistant(t(4, 30), "m5"),
  ), "claude");
  expect(asks.map(a => [a.turns, a.wallMs / 1000])).toEqual([[3, 90], [2, 90]]);
});

it("collects main sessions of the project only, never subagent transcripts, and reports weekly medians", () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-asks-"));
  roots.push(dir);
  const write = (path: string, header: object, ...entries: object[]): void => {
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, jsonl(header, ...entries).join("\n") + "\n");
  };
  const ask = (start: number, turns: number, seconds: number): object[] => [
    ompUser(t(start)), ...Array.from({ length: turns }, (_, i) => ompAssistant(t(start, i === turns - 1 ? seconds : 1 + i))),
  ];
  write(join(dir, "omp", "proj", "main.jsonl"), { type: "session", cwd: "/work/mine" }, ...ask(0, 3, 30), ...ask(10, 7, 60), ...ask(20, 5, 30));
  write(join(dir, "omp", "proj", "main", "sub.jsonl"), { type: "session", cwd: "/work/mine" }, ...ask(30, 40, 59)); // subagent: deeper folder
  write(join(dir, "omp", "other", "main.jsonl"), { type: "session", cwd: "/work/theirs" }, ...ask(40, 9, 50));
  write(join(dir, "claude", "proj", "c.jsonl"), { type: "queue-operation", timestamp: t(0) }, ccUser(t(0), "hi", { cwd: "/work/mine" }), ccAssistant(t(0, 30), "a"));

  const asks = collectAsks({ omp: join(dir, "omp"), claude: join(dir, "claude") }, Date.UTC(2026, 9, 1), cwd => cwd === "/work/mine");
  expect(asks.map(a => a.turns).sort((a, b) => a - b)).toEqual([1, 3, 5, 7]);

  const rows = weeklyAsks(asks, 2, new Date(Date.UTC(2026, 9, 6)));
  expect(rows.map(r => r.week)).toEqual(["2026-09-28", "2026-10-05"]);
  expect(rows[0]).toMatchObject({ asks: 0 });
  expect(formatWeek(rows[0]!)).toBe("2026-09-28 · 0 asks");
  expect(formatWeek(rows[1]!)).toBe("2026-10-05 · 4 asks · turns median 4 (p75 5) · wall median 0.5 min");
});
