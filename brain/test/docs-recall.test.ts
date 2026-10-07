import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { main } from "../src/cli.ts";
import { docAnswer, suggestDocs } from "../src/docs.ts";
import { judgedAnswer, type Judge } from "../src/judge.ts";
import { answerWithHits } from "../src/search.ts";
import { logUse } from "../src/telemetry.ts";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup(docs: string[] = []) {
  const base = mkdtempSync(join(tmpdir(), "brain-docs-recall-"));
  roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(root);
  const config = join(home, "projects.json");
  writeFileSync(config, JSON.stringify({ projects: { demo: { paths: [root], docs } } }));
  const project = { id: "demo", root, tags: [] };
  const doc = (path: string, text: string) => writeFileSync(join(root, path), text);
  const query = (text: string, hits = 0, ids: string[] = [], at = new Date(), id = "demo") => logUse(home, { kind: "recall", project: id, query: text, hits, ids, tokens: 0, ms: 0 }, at);
  const run = async (args: string[] = []) => {
    const out: string[] = [], err: string[] = [];
    const code = await main(["project", "docs", "suggest", ...args], { cwd: root, env: { SECOND_BRAIN_HOME: home }, stdin: () => "", out: s => out.push(s), err: s => err.push(s) });
    return { code, out: out.join("\n"), err: err.join("\n") };
  };
  return { home, root, project, config, doc, query, run };
}

it("answers later section paragraphs and sends the best paragraph to the judge", async () => {
  const { home, project, doc } = setup(["PLAN.md"]);
  doc("PLAN.md", "## Runtime\nIntroductory overview.\n\nThermal sampler guards gpu.lock while runctl schedules telemetry.\n");
  const result = answerWithHits([], "thermal sampler gpu.lock", { home, project });
  expect(result).toMatchObject({ text: "PLAN.md › Runtime (line 1)", hits: 1, ids: ["doc:PLAN.md"] });
  expect(result.docExcerpt).toBe("Runtime: Thermal sampler guards gpu.lock while runctl schedules telemetry.");
  let received = "";
  const judge: Judge = async (_query, candidates) => {
    received = candidates[0]!.text;
    return new Map(candidates.map(candidate => [candidate.id, 0.99]));
  };
  expect((await judgedAnswer([], "thermal sampler gpu.lock", { home, project }, judge)).ids).toEqual(["doc:PLAN.md"]);
  expect(received).toContain("Thermal sampler guards gpu.lock");
  expect(received).not.toContain("Introductory overview");
});

it("keeps unnamed one-shared-word queries silent even when the word repeats", () => {
  const { home, project, doc } = setup(["PLAN.md"]);
  doc("PLAN.md", "## Sampler\nThermal sampling.\n\nSampler sampler sampler.\n");
  for (const query of ["sampler zebra", "sampler sampler", "sampler"]) {
    expect(answerWithHits([], query, { home, project }).hits).toBe(0);
  }
});

it("prefers more distinct section terms before heading matches or repetitions", () => {
  const { home, project, doc } = setup(["PLAN.md"]);
  doc("PLAN.md", "## Thermal sampler\nThermal sampler thermal sampler.\n\n## Runtime\nThermal scheduling.\n\nThe sampler holds gpu.lock.\n");
  expect(docAnswer(home, project, "thermal sampler gpu.lock")?.text).toBe("PLAN.md › Runtime (line 4)");
  expect(docAnswer(home, project, "thermal sampler")?.text).toBe("PLAN.md › Thermal sampler (line 1)");
});

it("answers a named section number ahead of word overlap, ignores version strings, and disambiguates by remaining words", () => {
  const { home, project, doc } = setup(["plan-v4.md", "plan-v5.md"]);
  doc("plan-v4.md", "## 1.5 Budget\nSpend cap.\n\n### 3.2 Rules\nBinding rules.\n\n## 6. Kill rules\nDelete it.\n");
  doc("plan-v5.md", "## 3.2 Recall judged\nReal queries.\n\n## 8.8 Token pass\nRollover budget kill.\n");
  expect(docAnswer(home, project, "speed latency token plan §8.8")?.text).toBe("plan-v5.md › 8.8 Token pass (line 4)");
  expect(docAnswer(home, project, "kill rules section 6")?.text).toBe("plan-v4.md › 6. Kill rules (line 7)");
  expect(docAnswer(home, project, "3.2 rules")?.text).toBe("plan-v4.md › 3.2 Rules (line 4)");
  expect(docAnswer(home, project, "see 3.2 recall")?.text).toBe("plan-v5.md › 3.2 Recall judged (line 1)");
  expect(docAnswer(home, project, "plan §3.2")?.text).toMatch(/^plan-v\d\.md › 3\.2 /);
  for (const query of ["node 26.7.0 budget", "speedup 1.5x budget", "bump to v1.5 budget"]) {
    expect(docAnswer(home, project, query)?.text ?? "").not.toContain("1.5 Budget");
  }
});

it("project docs suggest ranks two distinct silent queries above one and skips registered docs", async () => {
  const { home, project, config, doc, query, run } = setup(["REGISTERED.md"]);
  doc("REGISTERED.md", "## Runtime\nThermal sampler. Quartz migration.\n");
  doc("BOTH.md", "## Runtime\nIntro.\n\nThermal sampler.\n\nQuartz migration.\n");
  doc("ONE.md", "## Runtime\nThermal sampler.\n");
  query("thermal sampler"); query("quartz migration"); query("THERMAL   SAMPLER");
  const before = readFileSync(config, "utf8");
  expect(suggestDocs(home, project)).toEqual([{ path: "BOTH.md", queries: 2, reads: 0 }, { path: "ONE.md", queries: 1, reads: 0 }]);
  expect(await run()).toEqual({ code: 0, out: "2 queries · 0 full reads · BOTH.md  → brain project docs add BOTH.md\n1 queries · 0 full reads · ONE.md  → brain project docs add ONE.md", err: "" });
  expect(await run(["-n", "1"])).toEqual({ code: 0, out: "2 queries · 0 full reads · BOTH.md  → brain project docs add BOTH.md", err: "" });
  expect(readFileSync(config, "utf8")).toBe(before);
});

it("project docs suggest prints no suggestions without telemetry", async () => {
  const { doc, run } = setup();
  doc("PLAN.md", "## Runtime\nThermal sampler.\n");
  expect(await run()).toEqual({ code: 0, out: "no suggestions", err: "" });
});

it("suggests from doc-answered and rotated rows, not old, future, other-project or note-answered queries", () => {
  const { home, project, doc, query } = setup();
  const now = new Date("2026-10-04T12:00:00Z");
  doc("MATCH.md", "## Runtime\nThermal sampler. Quartz migration.\n");
  doc("EXCLUDED.md", "## Runtime\nZebra latency.\n");
  query("thermal sampler", 1, ["doc:PLAN.md"], now);
  for (const at of [new Date("2026-09-03T12:00:00Z"), new Date("2026-10-05T12:00:00Z")]) query("zebra latency", 0, [], at);
  query("zebra latency", 0, [], now, "other");
  query("zebra latency", 1, ["n-note"], now);
  writeFileSync(join(home, "state", "telemetry.1.jsonl"), "broken row\n" + JSON.stringify({ kind: "recall", project: "demo", hits: 0, query: "quartz migration", at: now.toISOString() }) + "\n");
  expect(suggestDocs(home, project, { now })).toEqual([{ path: "MATCH.md", queries: 2, reads: 0 }]);
});

it("bounds fallback scanning and skips hidden folders, dependencies, oversized files and unreadable targets", () => {
  const { root, home, project, doc, query } = setup();
  doc("GOOD.md", "## Runtime\nThermal sampler.\n");
  for (const dir of [".hidden", "node_modules"]) {
    mkdirSync(join(root, dir));
    writeFileSync(join(root, dir, "BAD.md"), "## Runtime\nThermal sampler.\n");
  }
  doc("BIG.md", "## Runtime\nThermal sampler.\n" + "x".repeat(512 * 1024));
  query("thermal sampler");
  expect(suggestDocs(home, project)).toEqual([{ path: "GOOD.md", queries: 1, reads: 0 }]);
  expect(suggestDocs(home, { ...project, root: join(root, "missing") })).toEqual([]);
});

it("uses tracked Markdown rather than untracked files when git is available", () => {
  const { root, home, project, doc, query } = setup();
  if (spawnSync("git", ["--version"], { windowsHide: true }).status !== 0) return;
  expect(spawnSync("git", ["init", "-q"], { cwd: root, windowsHide: true }).status).toBe(0);
  doc("TRACKED.md", "## Runtime\nThermal sampler.\n");
  doc("UNTRACKED.md", "## Runtime\nThermal sampler.\n");
  expect(spawnSync("git", ["add", "TRACKED.md"], { cwd: root, windowsHide: true }).status).toBe(0);
  query("thermal sampler");
  expect(suggestDocs(home, project)).toEqual([{ path: "TRACKED.md", queries: 1, reads: 0 }]);
});

it("project docs suggest uses an explicitly named project's checkout from another project", async () => {
  const { home, root, config, doc, query } = setup();
  const other = join(home, "other");
  mkdirSync(other);
  writeFileSync(join(other, "WRONG.md"), "## Runtime\nThermal sampler.\n");
  writeFileSync(config, JSON.stringify({ projects: { demo: { paths: [root] }, other: { paths: [other] } } }));
  doc("RIGHT.md", "## Runtime\nThermal sampler.\n");
  query("thermal sampler");
  const out: string[] = [], err: string[] = [];
  const code = await main(["project", "docs", "suggest", "--project", "demo"], { cwd: other, env: { SECOND_BRAIN_HOME: home }, stdin: () => "", out: s => out.push(s), err: s => err.push(s) });
  expect({ code, out: out.join("\n"), err: err.join("\n") }).toEqual({ code: 0, out: "1 queries · 0 full reads · RIGHT.md  → brain project docs add RIGHT.md", err: "" });
});

it("ranks distinct full-read sessions from both hosts, excluding ranged, failed, old, future and unrelated reads", async () => {
  const { home, root, project, doc, query, run } = setup(["REGISTERED.md"]);
  const now = new Date();
  doc("POPULAR.md", "## Popular\nAn unrelated document.");
  doc("QUERY.md", "## Runtime\nThermal sampler.");
  doc("REGISTERED.md", "## Registered\nAlready registered.");
  query("thermal sampler");
  mkdirSync(join(home, "state", "events"), { recursive: true });
  const row = (session: string, tool: string, path = "POPULAR.md", over: Record<string, unknown> = {}) => ({ v: 1, at: now.toISOString(), session, cwd: root, tool, path, ok: true, ...over });
  writeFileSync(join(home, "state", "events", "reads.jsonl"), [
    row("omp", "read"), row("omp", "read"), row("cc", "Read", join(root, "POPULAR.md")),
    row("ranged", "Read", "POPULAR.md", { fullRead: false }), row("suffix", "read", "POPULAR.md:1-3"),
    row("failed", "read", "POPULAR.md", { ok: false }), row("edit", "Edit"),
    row("old", "read", "POPULAR.md", { at: new Date(now.getTime() - 31 * 86_400_000).toISOString() }),
    row("future", "read", "POPULAR.md", { at: new Date(now.getTime() + 86_400_000).toISOString() }),
    row("elsewhere", "read", "POPULAR.md", { cwd: home }), row("registered", "Read", "REGISTERED.md"),
    row("invalid", "Read", "POPULAR.md", { fullRead: "yes" }), "broken row"
  ].map(value => typeof value === "string" ? value : JSON.stringify(value)).join("\n"));
  expect(suggestDocs(home, project, { now })).toEqual([
    { path: "POPULAR.md", queries: 0, reads: 2 }, { path: "QUERY.md", queries: 1, reads: 0 }
  ]);
  expect((await run()).out).toContain("0 queries · 2 full reads · POPULAR.md");
});
