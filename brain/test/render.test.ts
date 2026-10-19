/** Layer 4 (brain/src/render.ts): determinism, prefix stability, keep window, sticky keys, restore and the OMP adapter. */
import { mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { judgedAnswer } from "../src/judge.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { outputTokens, readElided, Renderer, RENDER_POLICY, storeElided, type ToolOutput } from "../src/render.ts";
import { stats } from "../src/telemetry.ts";

const SMALL = { keep: 1000, step: 500, min: 50 };

/** An output of exactly `tokens` tokens: letters only, a fifth of a token each, distinct per `n`. */
const out = (n: number, tokens: number, key = `k${n}`): ToolOutput => {
  const tag = String(n).replace(/\d/g, digit => "abcdefghij"[Number(digit)]!);
  return { key, tool: "bash", text: `output${tag}`.padEnd(tokens * 5, `line${tag}`).slice(0, tokens * 5) };
};
const history = (count: number, tokens = 100): ToolOutput[] => Array.from({ length: count }, (_, n) => out(n, tokens));
const tmp = (): string => mkdtempSync(join(tmpdir(), "render-"));

const CODE = `import { readFile } from "node:fs/promises";
import { EOL } from "node:os";

/** Parses a key=value config file; later keys win and blank lines or # comments are skipped. */
export async function loadConfig(path: string, defaults: Record<string, string> = {}): Promise<Map<string, string>> {
  const config = new Map(Object.entries(defaults));
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return config;
    throw error;
  }
  for (const [index, raw] of text.split(EOL).entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const at = line.indexOf("=");
    if (at <= 0) throw new Error(path + ":" + (index + 1) + ": expected key=value, got " + JSON.stringify(line));
    config.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
  }
  return config;
}

export function retryDelay(attempt: number, base = 250, cap = 30_000): number {
  const jitter = Math.random() * base;
  return Math.min(cap, base * 2 ** attempt + jitter);
}
`;

/** Deterministic tool outputs with their o200k_base token counts, measured with tiktoken 0.14 when outputTokens' weights were fitted. */
function samples(): [kind: string, text: string, o200k: number][] {
  let seed = 7;
  const next = (n: number): number => (seed = (seed * 48271) % 2147483647) % n;
  const pick = (list: string[]): string => list[next(list.length)]!;
  const two = (n: number): string => String(next(n)).padStart(2, "0");
  const log = Array.from({ length: 120 }, () => `2026-03-04T${two(24)}:${two(60)}:${two(60)}Z ${pick(["INFO", "WARN", "DEBUG", "ERROR"])} ${pick(["gateway", "billing", "indexer", "auth", "queue"])} ${pick(["retry skipped", "connection reused", "heartbeat ok", "batch flushed", "lease renewed"])} id=${next(2147483647).toString(16).padStart(8, "0")}`).join("\n");
  const json = JSON.stringify(Array.from({ length: 30 }, (_, i) => ({ id: next(2147483647).toString(16).padStart(8, "0"), path: `src/module${next(50)}/file${i}.ts`, line: next(2000), ok: next(2) === 1, ms: next(100000) / 100 })), null, 2);
  const prose = Array.from({ length: 6 }, () => `The ${pick(["proxy", "renderer", "host", "session"])} keeps the newest tool output verbatim and replaces older results with a short stub that names a recall id. When the model needs the original again, it asks for that id and the brain returns the stored text, so nothing is lost; the request simply carries less of it until then.`).join(" ");
  return [["log", log, 3003], ["json", json, 1483], ["code", CODE, 293], ["prose", prose, 354]];
}

describe("render core", () => {
  it("keeps originals full when persistence fails", () => {
    // A regular file cannot contain state/elided.
    const home = join(tmp(), "file");
    writeFileSync(home, "blocked");
    expect(new Renderer(home, SMALL).render(history(30))).toEqual([]);
  });

  it("recounts equal-length replacement text before deciding the watermark", () => {
    const renderer = new Renderer(null, SMALL);
    const outputs = Array.from({ length: 10 }, (_, n) => ({ key: String(n), text: "a".repeat(500) }));
    expect(renderer.render(outputs)).toEqual([]);
    const changed = outputs.map(output => ({ ...output, text: "1".repeat(500) }));
    expect(renderer.render(changed).length).toBeGreaterThan(0);
    expect(renderer.tokens).toBe(4000);
  });
  it("counts logs, JSON, code and prose within 10% of real tokens", () => {
    // chars/4, the brain's budget unit, is 40% low on the log and JSON samples
    for (const [kind, text, o200k] of samples()) expect(Math.abs(outputTokens(text) / o200k - 1), kind).toBeLessThan(0.1);
  });

  it("is deterministic across calls and instances", () => {
    const outputs = history(30);
    const first = new Renderer(null, SMALL).render(outputs);
    expect(first.length).toBeGreaterThan(0);
    expect(new Renderer(null, SMALL).render(outputs).map(e => e.stub)).toEqual(first.map(e => e.stub));
    const again = new Renderer(null, SMALL);
    expect(again.render(outputs).map(e => e.stub)).toEqual(first.map(e => e.stub));
    expect(again.render(outputs).map(e => e.stub)).toEqual(first.map(e => e.stub));
  });

  it("never changes an earlier stub between epochs and moves the watermark forward in step jumps", () => {
    const renderer = new Renderer(null, SMALL);
    const seen = new Map<number, string>();
    let mark = -1;
    const marks: number[] = [];
    const all = history(80);
    for (let n = 1; n <= all.length; n++) {
      const elisions = renderer.render(all.slice(0, n));
      for (const e of elisions) {
        expect(seen.get(e.index) ?? e.stub).toBe(e.stub);
        seen.set(e.index, e.stub);
      }
      // nothing once elided is ever sent verbatim again
      for (const index of seen.keys()) expect(elisions.some(e => e.index === index)).toBe(true);
      const top = elisions.length ? elisions[elisions.length - 1]!.index : -1;
      expect(top).toBeGreaterThanOrEqual(mark);
      if (top !== mark) marks.push((top + 1) * 100);
      mark = top;
    }
    expect(marks.length).toBeGreaterThan(2);
    // 100-token outputs divide the step, so every boundary is an exact multiple and jumps are whole steps
    for (let i = 0; i < marks.length; i++) {
      expect(marks[i]! % SMALL.step).toBe(0);
      if (i) expect(marks[i]! - marks[i - 1]!).toBeGreaterThanOrEqual(SMALL.step);
    }
    expect(marks.length).toBeLessThanOrEqual(Math.floor(8000 / SMALL.step));
  });

  it("keeps the newest keep tokens, small outputs and existing stubs verbatim", () => {
    const outputs = history(60);
    outputs[3] = out(3, 20);
    const first = new Renderer(null, SMALL).render(outputs);
    const elided = new Set(first.map(e => e.index));
    const last = Math.max(...elided);
    expect(outputs.slice(last + 1).reduce((sum, o) => sum + outputTokens(o.text), 0)).toBeGreaterThanOrEqual(SMALL.keep);
    expect(elided.has(3)).toBe(false);
    expect(new Renderer(null, SMALL).render(outputs.map(o => ({ ...o, text: o.text.slice(0, 40) }))).length).toBe(0);
    const withStub = [...outputs, { key: "stub", tool: "bash", text: first[0]!.stub }, ...Array.from({ length: 40 }, (_, n) => out(1000 + n, 100))];
    const second = new Renderer(null, SMALL).render(withStub);
    expect(second.some(e => e.index === outputs.length)).toBe(false);
  });

  it("re-sends an elided key's stub byte for byte when the host shrinks or replaces its text; a re-read under a new key stays verbatim; fewer outputs reset", () => {
    const renderer = new Renderer(null, SMALL);
    const outputs = history(40);
    const first = renderer.render(outputs).find(e => e.index === 0)!;
    expect(first).toMatchObject({ fresh: true });
    for (const text of [outputs[0]!.text.slice(0, 600), "[Output truncated - 100 tokens]", ""]) {
      const pruned = outputs.map((o, i) => i === 0 ? { ...o, text } : o);
      expect(renderer.render(pruned).find(e => e.index === 0)).toMatchObject({ id: first.id, stub: first.stub, fresh: false });
    }
    const reread = [...outputs, { ...outputs[0]!, key: "again" }];
    const third = renderer.render(reread);
    expect(third.some(e => e.index === outputs.length)).toBe(false);
    renderer.render(outputs.slice(0, 5));
    expect(renderer.render(outputs.slice(0, 5))).toEqual([]);
  });

  it("does not count the same output as fresh again after the host shrinks and restores the history", () => {
    const renderer = new Renderer(null, SMALL);
    const outputs = history(40);
    const first = renderer.render(outputs);
    expect(first.some(e => e.fresh)).toBe(true);
    renderer.render(outputs.slice(0, 20));
    const restored = renderer.render(outputs);
    expect(restored.length).toBeGreaterThan(0);
    expect(restored.every(e => !e.fresh)).toBe(true);
  });

  it("counts a duplicate copy under a new call id once it reaches the watermark", () => {
    const renderer = new Renderer(null, SMALL);
    const base = history(40);
    const first = renderer.render(base);
    const original = first.find(e => e.index === 0)!;
    const extended = [...base, { ...base[0]!, key: "copy" }, ...Array.from({ length: 60 }, (_, n) => out(1000 + n, 100))];
    const result = renderer.render(extended);
    expect(result.find(e => e.index === 0)).toMatchObject({ id: original.id, fresh: false });
    expect(result.find(e => e.index === base.length)).toMatchObject({ id: original.id, fresh: true });
  });

  it("never puts half a surrogate pair in a stub", () => {
    const lone = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
    for (const lead of ["a".repeat(99), "a".repeat(399), " ".repeat(399)]) {
      const outputs = history(40);
      outputs[0] = { key: "k0", tool: "read", text: `${lead}${"\u{1F600}".repeat(300)}` };
      const stub = new Renderer(null, SMALL).render(outputs).find(e => e.index === 0)!.stub;
      expect(stub).not.toMatch(lone);
    }
  });

  it("suggests re-running the tool only for tools that just read", () => {
    const stubOf = (tool: string): string => new Renderer(null, SMALL).render(history(40).map(o => ({ ...o, tool })))[0]!.stub;
    expect(stubOf("Read")).toContain("re-running the tool also shows it");
    expect(stubOf("grep")).toContain("re-running the tool also shows it");
    expect(stubOf("bash")).not.toContain("re-running");
  });
});

describe("restore", () => {
  it("keeps the first original under an id and refuses a second, different one", () => {
    const home = tmp();
    expect(storeElided(home, "t-1111111111", "first original")).toBe(true);
    expect(storeElided(home, "t-1111111111", "first original")).toBe(true);
    expect(storeElided(home, "t-1111111111", "a colliding output")).toBe(false);
    expect(readElided(home, "t-1111111111")).toBe("first original");
  });

  it("never stores an ill-formed string", () => {
    const home = tmp();
    expect(storeElided(home, "t-2222222222", "cut \ud800")).toBe(false);
    expect(readElided(home, "t-2222222222")).toBeUndefined();
  });

  it("keeps a reused original recallable after a later retention sweep", async () => {
    const home = tmp(), outputs = history(40);
    const first = new Renderer(home, SMALL).render(outputs)[0]!;
    const now = Date.now(), day = 86_400_000, old = (now - 13.5 * day) / 1000;
    const unused = "t-0123456789";
    storeElided(home, unused, "unused output");
    for (const id of [first.id, unused]) utimesSync(join(home, "state", "elided", `${id}.txt`), old, old);
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    try {
      const reused = new Renderer(home, SMALL).render(outputs)[0]!;
      expect(reused).toMatchObject({ id: first.id, fresh: true });
      clock.mockReturnValue(now + 2 * day);
      expect(storeElided(home, "t-fffffffffe", "trigger the daily sweep")).toBe(true);
      expect(readElided(home, unused)).toBeUndefined();
      const answer = await judgedAnswer([], reused.id, { home, project: null });
      expect(answer).toMatchObject({ text: outputs[reused.index]!.text, hits: 1, ids: [reused.id] });
    } finally { clock.mockRestore(); }
  });

  it("round-trips the original through judgedAnswer and answers an unknown id with the re-run message", async () => {
    const home = tmp();
    const outputs = history(40);
    const elisions = new Renderer(home, SMALL).render(outputs);
    expect(elisions.length).toBeGreaterThan(0);
    for (const e of elisions) {
      const answer = await judgedAnswer([], e.id.toUpperCase(), { home, project: null });
      expect(answer).toMatchObject({ text: outputs[e.index]!.text, hits: 1, ids: [e.id] });
    }
    const missing = await judgedAnswer([], "t-0123456789", { home, project: null });
    expect(missing).toMatchObject({ hits: 0, ids: [] });
    expect(missing.text).toContain("re-run the tool");
  });
});

describe("OMP adapter", () => {
  type Msg = { role: string; toolCallId?: string; toolName?: string; content: { type: string; text?: string; data?: string; mimeType?: string }[] };
  const text = (value: string) => [{ type: "text", text: value }];
  const messages = (): Msg[] => [
    { role: "user", content: text("start") },
    ...Array.from({ length: 12 }, (_, n) => ({ role: "toolResult", toolCallId: `c${n}`, toolName: "bash", content: text(out(n, 10_000).text) })),
    { role: "toolResult", toolCallId: "img", toolName: "read", content: [{ type: "text", text: out(99, 10_000).text }, { type: "image", data: "AAAA", mimeType: "image/png" }] },
    { role: "toolResult", toolCallId: "tail", toolName: "bash", content: text(out(100, 10_000).text) },
  ];
  const load = (extra: NodeJS.ProcessEnv) => {
    const home = tmp();
    mkdirSync(home, { recursive: true });
    const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
    const pi: HostLike = { on: (name, handler) => void handlers.set(name, handler) };
    secondBrain(pi, { SECOND_BRAIN_HOME: home, ...extra });
    return { home, context: handlers.get("context")! };
  };
  const ctx = { cwd: tmp(), sessionManager: { getSessionId: () => "render" } };

  it("returns nothing with BRAIN_RENDER=off", () => {
    const { context } = load({ BRAIN_RENDER: "off" });
    expect(context({ messages: messages() }, ctx)).toBeUndefined();
  });

  it("leaves Anthropic Messages models alone unless BRAIN_RENDER=on: their cache writes cost more than an elided read saves", () => {
    const claude = { ...ctx, model: { api: "anthropic-messages", provider: "anthropic", id: "claude-opus-5-5" } };
    const gpt = { ...ctx, model: { api: "openai-codex-responses", provider: "openai-codex", id: "gpt-6-astra" } };
    expect(load({}).context({ messages: messages() }, claude)).toBeUndefined();
    expect(load({}).context({ messages: messages() }, gpt)).toBeDefined();
    expect(load({ BRAIN_RENDER: "on" }).context({ messages: messages() }, claude)).toBeDefined();
  });

  it("is on by default: returns new messages with stubs for old, big results and mutates nothing", () => {
    const { home, context } = load({});
    const input = messages();
    const before = structuredClone(input);
    const reply = context({ messages: input }, ctx) as { messages: Msg[] } | undefined;
    expect(input).toEqual(before);
    expect(reply).toBeDefined();
    const sent = reply!.messages;
    expect(sent).not.toBe(input);
    expect(sent.length).toBe(input.length);
    expect(sent[0]).toBe(input[0]);
    const stubbed = sent.flatMap((m, i) => m !== input[i] ? [i] : []);
    expect(stubbed.length).toBeGreaterThan(0);
    for (const i of stubbed) {
      const msg = sent[i]!;
      expect(msg.content).toHaveLength(1);
      expect(msg.content[0]?.text).toContain("Second Brain elided");
      expect(sent[i]).toMatchObject({ role: "toolResult", toolCallId: input[i]!.toolCallId });
    }
    // the image-bearing result and the newest result are never replaced
    expect(sent[sent.length - 2]).toBe(input[input.length - 2]);
    expect(sent[sent.length - 1]).toBe(input[input.length - 1]);
    const row = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map(l => JSON.parse(l)).find(r => r.kind === "elide");
    expect(row).toMatchObject({ kind: "elide", via: "hook", session: "render", hits: stubbed.length });
    expect(row.tokens).toBeGreaterThan(stubbed.length * (10_000 - 200));
    expect(stats(home).layer4).toMatchObject({ epochs: 1, elided: stubbed.length });
    // the same history later: stubs repeat byte for byte and no second row is written
    const again = context({ messages: input }, ctx) as { messages: Msg[] };
    expect(again.messages.map(m => JSON.stringify(m))).toEqual(sent.map(m => JSON.stringify(m)));
    expect(readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").filter(l => l.includes('"elide"')).length).toBe(1);
  });

  it("scales: the default policy leaves small histories alone", () => {
    const { context } = load({});
    const small = [{ role: "toolResult", toolCallId: "a", toolName: "bash", content: text(out(1, RENDER_POLICY.min * 2).text) }];
    expect(context({ messages: small }, ctx)).toBeUndefined();
  });
});
