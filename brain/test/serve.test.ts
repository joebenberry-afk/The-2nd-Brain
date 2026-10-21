import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { LEAN_LINE } from "../src/card.ts";
import { createNote, loadNotes } from "../src/notes.ts";
import { serveRequest, type ServeBase } from "../src/serve.ts";

const homes: string[] = [];
afterEach(() => { for (const dir of homes.splice(0)) rmSync(dir, { recursive: true, force: true }); });

/** A temp Brain home plus a git-shaped project folder so the cwd names the project. */
function setup(projects: string[] = []): { home: string; cwd: string; base: ServeBase } {
  const home = mkdtempSync(join(tmpdir(), "brain-serve-test-"));
  homes.push(home);
  const root = join(home, projects[0] ?? "demo");
  for (const name of projects.length ? projects : ["demo"]) {
    const dir = join(home, name);
    mkdirSync(join(dir, ".git"), { recursive: true });
    writeFileSync(join(dir, ".git", "config"), "[core]\n\tbare = false\n");
  }
  return { home, cwd: root, base: { env: { SECOND_BRAIN_HOME: home, BRAIN_TORA: "off" }, cwd: root } };
}

function ask(base: ServeBase, argv: string[], extra: { id?: unknown; cwd?: string; session?: string; stdin?: string } = {}) {
  return serveRequest(base, { id: 1, argv, ...extra });
}

describe("brain serve", () => {
  it("resolves each request in its own cwd, session and project, warm", async () => {
    const { home, base } = setup(["alpha", "beta"]);
    const alpha = createNote(home, { project: "alpha", text: "alpha rendezvous fact" });
    const beta = createNote(home, { project: "beta", text: "beta rendezvous fact" });

    const one = await ask(base, ["recall", "rendezvous"], { cwd: join(home, "alpha"), session: "s1" });
    expect(one.code).toBe(0);
    expect(one.out).toContain(alpha.id);
    expect(one.out).not.toContain(beta.id);

    const two = await ask(base, ["recall", "rendezvous"], { cwd: join(home, "beta"), session: "s2" });
    expect(two.code).toBe(0);
    expect(two.out).toContain(beta.id);
    expect(two.out).not.toContain(alpha.id);

    // The service is one process: telemetry rows from both requests carry their own session.
    const rows = readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows.filter((row) => row.kind === "recall").map((row) => row.session)).toEqual(["s1", "s2"]);
  });

  it("keeps answering after malformed input, a missing command and a nested serve", async () => {
    const { base } = setup();
    for (const request of [null, {}, { id: 2, argv: ["serve"] }, { id: 3, argv: ["mcp"] }, { id: 4, argv: ["nope"] }]) {
      const reply = await serveRequest(base, request);
      expect(reply.code).not.toBe(0);
    }
    const alive = await ask(base, ["state"]);
    expect(alive).toMatchObject({ id: 1, code: 0 });
  });

  it("records a failed tool outcome and answers its tested fix, then its repeat pointer", async () => {
    const { home, base } = setup();
    const note = createNote(home, { project: "demo", text: "Clear PYTHONHOME before python", errors: ["SRE module mismatch"], tested: true });
    const stdin = JSON.stringify({ tool: "pwsh", input: { command: "python -c x" }, isError: true, content: "SRE module mismatch" });

    const first = await ask(base, ["event", "--fix"], { session: "served", stdin });
    expect(first.code).toBe(0);
    expect(first.out).toContain(note.id);
    const second = await ask(base, ["event", "--fix"], { session: "served", stdin });
    expect(second.out).toBe(`Brain: same fix as above [${note.id}]`);

    const events = readFileSync(join(home, "state", "events", "served.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ tool: "pwsh", command: "python -c x", ok: false, error: "SRE module mismatch" });
  });

  it("scores a fired fix only once a later step retries the operation", async () => {
    const { home, base } = setup();
    const note = createNote(home, { project: "demo", text: "Clear PYTHONHOME before python", errors: ["SRE module mismatch"], tested: true });
    const failed = JSON.stringify({ tool: "pwsh", input: { command: "npm test" }, isError: true, content: "SRE module mismatch", step: 3 });
    expect((await ask(base, ["event", "--fix"], { session: "steps", stdin: failed })).out).toContain(note.id);

    const rows = () => readFileSync(join(home, "state", "telemetry.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line)).filter((row) => row.kind === "fixout");
    const retry = (step: number) => ask(base, ["event"], { session: "steps", stdin: JSON.stringify({ tool: "pwsh", input: { command: "npm test" }, isError: false, step }) });
    // A sibling call of the failing message ran before the model read the fix: no outcome.
    await retry(3);
    expect(rows()).toEqual([]);
    await retry(4);
    expect(rows()).toMatchObject([{ kind: "fixout", id: note.id, project: "demo", outcome: "helped", session: "steps" }]);
    // The pending fix was consumed: a second success scores nothing.
    await retry(5);
    expect(rows()).toHaveLength(1);
  });

  it("answers the rollover hint once per crossing and never for subagents", async () => {
    const { home, base } = setup();
    expect((await ask(base, ["rollover", "--threshold"])).out).toBe("150000");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { rollover: 10000 } } }));
    expect((await ask(base, ["rollover", "--threshold"])).out).toBe("10000");
    expect((await ask(base, ["rollover", "11000"], { session: "custom" })).out).toContain("context 11k");
    rmSync(join(home, "projects.json"), { force: true });
    expect((await ask(base, ["rollover", "151000"], { session: "main" })).out).toContain("context 151k");
    expect((await ask(base, ["rollover", "200000"], { session: "main" })).out).toBe("");
    expect((await ask(base, ["rollover", "301000"], { session: "main" })).out).toContain("context 301k");
    expect((await ask(base, ["rollover", "301000", "--sub"], { session: "child" })).out).toBe("");
  });

  it("learns a tested repair from recorded events at scan", async () => {
    const { home, base } = setup();
    await ask(base, ["event"], {
      session: "learn",
      stdin: JSON.stringify({ tool: "pwsh", input: { command: "npm test" }, isError: true, content: "error TS2322: Type 'string' is not assignable to type 'number'.", step: 2 }),
    });
    await ask(base, ["event"], {
      session: "learn",
      stdin: JSON.stringify({ tool: "pwsh", input: { command: "npm ci && npm test" }, isError: false, step: 3 }),
    });
    expect((await ask(base, ["scan"], { session: "learn" })).code).toBe(0);
    const note = loadNotes(home).notes.find((candidate) => candidate.source === "capture");
    expect(note).toMatchObject({ project: "demo", tested: true, errors: ["error TS2322: Type 'string' is not assignable to type 'number'."] });
  });

  it("renders the resident-tools card without the CLI footer", async () => {
    const { home, base } = setup();
    createNote(home, { project: "demo", text: "a durable demo fact" });
    const reply = await ask(base, ["card", "--tools"]);
    expect(reply.code).toBe(0);
    expect(reply.out).toContain("a durable demo fact");
    expect(reply.out).toContain(LEAN_LINE);
    expect(reply.out).not.toContain("brain recall");
  });

  it("does not leave working state behind for a read", async () => {
    const { home, base } = setup();
    const reply = await ask(base, ["state"]);
    expect(reply).toMatchObject({ code: 0, out: "no working state" });
    expect(existsSync(join(home, "work", "demo.md"))).toBe(false);
  });
});
