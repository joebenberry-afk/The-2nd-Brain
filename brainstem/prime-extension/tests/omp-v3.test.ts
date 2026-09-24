/**
 * The standalone V3 OMP extension (brainstem/omp-v3/index.ts). It is tested here only because
 * this package owns the vitest setup; the extension imports nothing from this package.
 */
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import secondBrainV3, {
  EVENT_LOG_CAP_BYTES,
  logToolEvent,
  matchCorrection,
  normalizePath,
  readBrief,
  viewKey,
} from "../../omp-v3/index";

type Handler = (event: unknown, ctx: unknown) => unknown;
let root = "";
let home = "";
let repo = "";

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "omp-v3-"));
  home = join(root, "brain");
  repo = join(root, "work", "repo");
  mkdirSync(join(repo, "sub"), { recursive: true });
  const views = join(home, "views");
  mkdirSync(join(views, "p1"), { recursive: true });
  mkdirSync(join(views, "_none"), { recursive: true });
  writeFileSync(
    join(views, "projects.json"),
    JSON.stringify([
      { id: "p1", paths: [normalizePath(repo)] },
      { id: "outer", paths: [normalizePath(join(root, "work"))] },
      { paths: ["/malformed/without/id"] },
    ]),
  );
  writeFileSync(join(views, "p1", "brief.md"), "# Brain brief — p1\n- A decision [mem-aaaaaaaaaaaa]\n");
  writeFileSync(join(views, "_none", "brief.md"), "");
  writeFileSync(
    join(views, "p1", "corrections.json"),
    JSON.stringify([
      { id: "mem-bbbbbbbbbbbb", errors: ["module mismatch"], text: "Short pattern" },
      { id: "mem-cccccccccccc", errors: ["SRE module mismatch"], text: "Unset PYTHONHOME" },
      { id: "mem-dddddddddddd", errors: ["re:(unclosed"], text: "Invalid" },
      { id: "mem-eeeeeeeeeeee", errors: ["re:no such table: \\w+"], text: "Run migrations" },
      { errors: ["SRE module mismatch plus"], text: "no id: ignored" },
    ]),
  );
});

afterEach(() => rmSync(root, { recursive: true, force: true }));

function load(env: NodeJS.ProcessEnv = { SECOND_BRAIN_HOME: home }): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  secondBrainV3({ on: (name, handler) => void handlers.set(name, handler) }, env);
  return handlers;
}

const ctx = (session: string, cwd = repo) => ({
  cwd,
  sessionManager: { getSessionId: () => session },
});

describe("view readers", () => {
  it("normalizes paths like the Python core and resolves the longest project path", () => {
    expect(normalizePath("C:\\Users\\X\\Repo\\")).toBe("c:/users/x/repo");
    expect(normalizePath("/srv/repo/")).toBe("/srv/repo");
    expect(viewKey(home, join(repo, "sub"))).toBe("p1");
    expect(viewKey(home, "/elsewhere")).toBe("_none");
    expect(viewKey(home, undefined)).toBe("_none");
  });

  it("returns the brief, or nothing for an empty or missing one", () => {
    expect(readBrief(home, repo)).toContain("[mem-aaaaaaaaaaaa]");
    expect(readBrief(home, "/elsewhere")).toBeUndefined();
    expect(readBrief("/no/such/home", repo)).toBeUndefined();
  });

  it("matches one correction: longest pattern, regex, invalid regex and id-less entries ignored", () => {
    expect(matchCorrection(home, repo, "AssertionError: SRE module mismatch plus")).toBe(
      "Brain correction (advisory): Unset PYTHONHOME [mem-cccccccccccc]",
    );
    expect(matchCorrection(home, repo, "OperationalError: no such table: kb_meta")).toContain("[mem-eeeeeeeeeeee]");
    expect(matchCorrection(home, repo, "unrelated failure")).toBeUndefined();
    expect(matchCorrection(home, "/elsewhere", "SRE module mismatch")).toBeUndefined();
    expect(matchCorrection(home, repo, "   ")).toBeUndefined();
  });
});

describe("extension wiring (version-tolerant host surface)", () => {
  it("registers nothing without a Brain home", () => {
    expect(load({}).size).toBe(0);
  });

  it("sends the brief on the first turn only, and again after compaction", async () => {
    const handlers = load();
    const start = handlers.get("before_agent_start")!;
    const first = (await start({ prompt: "hi" }, ctx("s1"))) as { message: { customType: string; content: string } };
    expect(first.message.customType).toBe("brain.v3.brief");
    expect(first.message.content).toContain("[mem-aaaaaaaaaaaa]");
    expect(await start({ prompt: "again" }, ctx("s1"))).toBeUndefined();
    expect(await handlers.get("session_before_compact")!({}, ctx("s1"))).toBeUndefined();
    expect(await start({ prompt: "after compaction" }, ctx("s1"))).toBeDefined();
    const lines = readFileSync(join(home, "telemetry", "kb-hooks.jsonl"), "utf8").trim().split("\n");
    expect(JSON.parse(lines[0])).toMatchObject({ event: "brief", host: "omp" });
  });

  it("appends one correction to a failed tool result and nothing otherwise", async () => {
    const toolResult = load().get("tool_result")!;
    const failed = (await toolResult(
      { isError: true, content: [{ type: "text", text: "AssertionError: SRE module mismatch" }] },
      ctx("s2"),
    )) as { content: Array<{ text: string }> };
    expect(failed.content).toHaveLength(2);
    expect(failed.content[1].text).toContain("[mem-cccccccccccc]");
    expect(await toolResult({ isError: false, content: [{ type: "text", text: "SRE module mismatch" }] }, ctx("s2"))).toBeUndefined();
    expect(await toolResult({ isError: true, content: [{ type: "text", text: "other" }] }, ctx("s2"))).toBeUndefined();
  });

  it("degrades to nothing when the host shape changes", async () => {
    const handlers = load();
    // No session manager, no cwd, odd event payloads: never throws, never injects wrongly.
    expect(await handlers.get("before_agent_start")!(undefined, {})).toBeUndefined(); // _none brief is empty
    expect(await handlers.get("before_agent_start")!(null, { sessionManager: { getSessionId: () => { throw new Error("x"); } } })).toBeUndefined();
    expect(await handlers.get("tool_result")!("not an object", null)).toBeUndefined();
    expect(await handlers.get("tool_result")!({ isError: true, content: "not an array" }, ctx("s3"))).toBeUndefined();
    expect(await handlers.get("session_before_compact")!(undefined, undefined)).toBeUndefined();
  });
});

describe("capture input (Brain-owned tool event log)", () => {
  it("logs every tool result with the fields brain capture reads", async () => {
    const toolResult = load().get("tool_result")!;
    await toolResult(
      { toolName: "bash", input: { command: "pytest -x" }, isError: true, content: [{ type: "text", text: "E   ImportError: no module" }] },
      ctx("s9"),
    );
    await toolResult({ toolName: "bash", input: { command: "python -m pytest -x" }, isError: false, content: [] }, ctx("s9"));
    await toolResult({ toolName: "read", input: { path: "a.py" }, content: [] }, ctx("s9"));
    const dir = join(home, "state", "kb-events");
    const files = readdirSync(dir);
    expect(files).toHaveLength(1);
    const lines = readFileSync(join(dir, files[0]), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(lines).toHaveLength(3);
    expect(lines[0]).toMatchObject({ v: 1, cwd: repo, tool: "bash", command: "pytest -x", ok: false, error: "E   ImportError: no module" });
    expect(lines[1]).toMatchObject({ tool: "bash", command: "python -m pytest -x", ok: true, error: null });
    expect(lines[2]).toMatchObject({ tool: "read", command: null, ok: true });
  });

  it("stops growing past the cap and never throws on odd events", () => {
    const dir = join(home, "state", "kb-events");
    logToolEvent(home, "s10", { toolName: "bash", input: { command: "x" } }, repo);
    const file = join(dir, readdirSync(dir)[0]);
    writeFileSync(file, "x".repeat(EVENT_LOG_CAP_BYTES + 1));
    logToolEvent(home, "s10", { toolName: "bash", input: { command: "y" } }, repo);
    expect(readFileSync(file, "utf8").length).toBe(EVENT_LOG_CAP_BYTES + 1);
    expect(() => logToolEvent(home, "s10", "not an object", undefined)).not.toThrow();
    expect(() => logToolEvent(file, "s10", { toolName: "bash" }, undefined)).not.toThrow();
  });
});
