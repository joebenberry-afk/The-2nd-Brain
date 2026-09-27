/** Regressions for the code-review findings on brain/src (each failed before its fix). */
import { spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { errorSignature, findFix, scanCommits, scanEvents } from "../src/capture.ts";
import { convertV3 } from "../src/convert.ts";
import { createNote, loadNotes } from "../src/notes.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { loadProjects, projectById, resolveProject } from "../src/project.ts";
import { main } from "../src/cli.ts";
import { renderCard } from "../src/card.ts";
import { recall } from "../src/search.ts";

const tmp = (p = "brain-review-") => mkdtempSync(join(tmpdir(), p));
const git = (cwd: string, ...args: string[]) => spawnSync("git", ["-c", "user.name=T", "-c", "user.email=t@t", ...args], { cwd, encoding: "utf8" });
const line = (o: object) => JSON.stringify({ v: 1, at: "2026-09-27T10:00:00Z", session: "s", cwd: "", tool: "bash", ...o }) + "\n";

describe("capture", () => {
  it("a captured gotcha's signature matches the next identical raw error (no *** in it)", () => {
    const home = tmp();
    mkdirSync(join(home, "state", "events"), { recursive: true });
    const error = "fatal: bad object 0123456789abcdef0123456789abcdef01234567 (error)";
    writeFileSync(
      join(home, "state", "events", "s.jsonl"),
      line({ command: "npm test", ok: false, error }) + line({ command: "npm --prefix app test", ok: true }),
    );
    const [proposal] = scanEvents(home, []);
    expect(proposal?.errors[0]).not.toContain("***");
    const note = createNote(home, { text: proposal?.text ?? "", project: "global", kind: "gotcha", errors: proposal?.errors, tested: true });
    expect(findFix([note], error, null)?.id).toBe(note.id);
  });

  it("a failure at the end of a live log waits for its fix instead of being skipped", () => {
    const home = tmp();
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    const log = join(events, "s.jsonl");
    writeFileSync(log, line({ command: "tsc", ok: false, error: "error TS2307: cannot find module" }));
    expect(scanEvents(home, [])).toEqual([]);
    appendFileSync(log, line({ command: "tsc -p .", ok: true }));
    expect(scanEvents(home, [])).toHaveLength(1);
  });

  it("a torn last line is read once it is complete, and a quiet log does not wait", () => {
    const home = tmp();
    const events = join(home, "state", "events");
    mkdirSync(events, { recursive: true });
    const log = join(events, "s.jsonl");
    const fail = line({ command: "make", ok: false, error: "make: *** No rule to make target" });
    const fix = line({ command: "make -C src", ok: true });
    writeFileSync(log, fail + fix.slice(0, 20));
    expect(scanEvents(home, [])).toEqual([]);
    appendFileSync(log, fix.slice(20));
    expect(scanEvents(home, [])).toHaveLength(1);

    const quiet = join(events, "q.jsonl");
    writeFileSync(quiet, line({ command: "cargo build", ok: false, error: "error[E0425]: cannot find value" }));
    const hourAgo = Date.now() / 1000 - 7200;
    utimesSync(quiet, hourAgo, hourAgo);
    scanEvents(home, []);
    appendFileSync(quiet, line({ command: "cargo build --release", ok: true }));
    utimesSync(quiet, hourAgo, hourAgo);
    expect(scanEvents(home, [])).toEqual([]);
  });

  it("commit capture recovers when its cursor commit no longer exists", () => {
    const home = tmp();
    const repo = tmp("brain-review-repo-");
    git(repo, "init", "-q");
    git(repo, "commit", "-q", "--allow-empty", "-m", "first\n\nBrain-Decision: Use pnpm workspaces");
    expect(scanCommits(home, repo, "demo", [])).toHaveLength(1);
    mkdirSync(join(home, "state"), { recursive: true });
    writeFileSync(join(home, "state", "git-cursor.json"), JSON.stringify({ [repo]: "f".repeat(40) }));
    git(repo, "commit", "-q", "--allow-empty", "-m", "second\n\nBrain-Gotcha: vitest needs --pool=forks on CI");
    const again = scanCommits(home, repo, "demo", []);
    expect(again.map((p) => p.text)).toContain("vitest needs --pool=forks on CI");
  });
});

describe("extension", () => {
  it("keeps a string error when it appends a fix", () => {
    const home = tmp();
    createNote(home, { text: "Run npm ci first", project: "global", kind: "gotcha", errors: ["Cannot find module"], tested: true });
    let onResult: ((e: unknown, c: unknown) => unknown) | undefined;
    const pi: HostLike = { on: (e, h) => void (e === "tool_result" && (onResult = h)) };
    secondBrain(pi, { SECOND_BRAIN_HOME: home });
    const out = onResult?.({ toolName: "bash", input: {}, isError: true, content: "Error: Cannot find module 'x'" }, { cwd: home }) as { content: { text: string }[] };
    expect(out.content[0]?.text).toBe("Error: Cannot find module 'x'");
    expect(out.content[1]?.text).toMatch(/^Brain \(advisory\): Run npm ci first/);
  });
});

describe("conversion and project ids", () => {
  it("a source home whose path contains 'private' keeps its public records public", () => {
    const from = join(tmp(), "private-brain");
    mkdirSync(join(from, "records"), { recursive: true });
    writeFileSync(join(from, "records", "mem-1.md"), "---\nid: mem-1\ntitle: A fact\ntype: fact\nscope: project\nproject: demo\nstatus: current\ngrade: TESTED\nrecorded_at: 2026-01-01T00:00:00+00:00\n---\n\nBody.\n");
    const to = tmp();
    convertV3(from, to);
    expect(loadNotes(to).notes[0]?.private).toBe(false);
  });

  it("an explicit project id is slugged, aliased, and can never escape the home", () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { sztool: { aliases: ["sz-tool"] } } }));
    expect(projectById(home, "The-2nd-Brain", home).id).toBe("the-2nd-brain");
    expect(projectById(home, "SZ Tool", home).id).toBe("sztool");
    expect(projectById(home, "../../tmp/x", home).id).toBe("tmp-x");
    expect(resolveProject(home, home, { BRAIN_PROJECT: "SZ_Tool" }).id).toBe("sztool");
  });
});

describe("second review", () => {
  it("masks env-style and unpadded secrets", async () => {
    const { scrub } = await import("../src/scrub.ts");
    for (const [text, kept] of [
      ["DB_PASSWORD=hunter2 psql", "DB_PASSWORD="],
      ["curl -d client_secret=abcdef12345", "client_secret="],
      ["access_token=abcdEFGH1234ijkl", "access_token="],
      ["GITHUB_TOKEN=abcd1234efgh5678", "GITHUB_TOKEN="],
      ["export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "AWS_SECRET_ACCESS_KEY="],
    ] as const) {
      const out = scrub(text).text;
      expect(out, text).toContain(kept);
      expect(out, text).toContain("***");
      expect(out, text).not.toMatch(/hunter2|abcdef12345|abcdEFGH1234ijkl|abcd1234efgh5678|bPxRfiCYEXAMPLEKEY/);
    }
    expect(scrub("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEYmore").text).toBe("***");
    expect(scrub("KEYBOARD_LAYOUT=us").scrubbed).toBe(false);
  });

  it("names a project the same way whether it comes from a path, an id, or a synced key", () => {
    const home = tmp();
    const dir = tmp("brain-review-sz-");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { SZ_Tool: { paths: [dir], tags: ["sparking-zero"] }, "../escape": {} } }));
    expect(resolveProject(home, dir, {})).toMatchObject({ id: "sz-tool", tags: ["sparking-zero"] });
    expect(projectById(home, "SZ_Tool", dir).id).toBe("sz-tool");
    expect(Object.keys(loadProjects(home)).sort()).toEqual(["escape", "sz-tool"]);
  });

  it("files a captured failure under the directory it happened in, not BRAIN_PROJECT", () => {
    const home = tmp();
    const repoDir = join(tmp(), "beta");
    mkdirSync(join(repoDir, ".git"), { recursive: true });
    mkdirSync(join(home, "state", "events"), { recursive: true });
    writeFileSync(
      join(home, "state", "events", "s.jsonl"),
      line({ cwd: repoDir, command: "pytest", ok: false, error: "ImportError: no module named x" }) + line({ cwd: repoDir, command: "pytest -p no:cacheprovider", ok: true }),
    );
    const before = process.env.BRAIN_PROJECT;
    process.env.BRAIN_PROJECT = "alpha";
    try {
      expect(scanEvents(home, [])[0]?.project).toBe("beta");
    } finally {
      if (before === undefined) delete process.env.BRAIN_PROJECT;
      else process.env.BRAIN_PROJECT = before;
    }
  });

  it("refreshing the auto section does not make the plan newer", async () => {
    const { writeAuto, writeWork, readWork } = await import("../src/work.ts");
    const home = tmp();
    const plan = writeWork(home, "demo", "Goal: the new plan");
    await new Promise((r) => setTimeout(r, 1100));
    const after = writeAuto(home, "demo", { ask: "closing the session" });
    expect(after?.at).toBe(plan.at);
    expect((after?.autoAt ?? "") > plan.at).toBe(true);
    expect(readWork(home, "demo")?.autoAt).toBe(after?.autoAt);
  });

  it("move and kit new resolve aliases", async () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { "second-brain": { aliases: ["the-2nd-brain"] } } }));
    const out: string[] = [];
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "scratch" }, cwd: home, out: (s: string) => out.push(s), err: (s: string) => out.push(s) };
    await main(["note", "We chose vite", "--kind", "decision"], io);
    const id = out[0]?.replace("saved ", "") ?? "";
    await main(["move", id, "--to", "The-2nd-Brain"], io);
    expect(loadNotes(home).notes[0]?.project).toBe("second-brain");
    await main(["kit", "new", "web", "--from", "the-2nd-brain"], io);
    expect(readFileSync(join(home, "kits", "web", "SKILL.md"), "utf8")).toContain("We chose vite");
  });

  it("counts only file-changing tools as edits", () => {
    const home = tmp();
    const handlers = new Map<string, (e: unknown, c: unknown) => unknown>();
    secondBrain({ on: (e, h) => void handlers.set(e, h) }, { SECOND_BRAIN_HOME: home });
    const ctx = { cwd: home, sessionManager: { getSessionId: () => "s" } };
    handlers.get("tool_result")?.({ toolName: "read", input: { path: "a.ts" }, isError: false, content: [] }, ctx);
    handlers.get("tool_result")?.({ toolName: "edit", input: { path: "b.ts" }, isError: false, content: [] }, ctx);
    handlers.get("session_before_compact")?.({}, { ...ctx });
    expect(readFileSync(join(home, "work", `${resolveProject(home, home, {}).id}.md`), "utf8")).toContain("- edited: b.ts\n");
  });

  it("finds notes with accented words", () => {
    const home = tmp();
    createNote(home, { text: "Résumé export uses the cache", project: "demo" });
    const { notes } = loadNotes(home);
    const project = { id: "demo", tags: [], root: null };
    expect(recall(notes, "resume", { project }).length).toBe(1);
    expect(recall(notes, "Résumé", { project }).length).toBe(1);
  });

  it("cuts an oversized working state to fit the card instead of dropping it", () => {
    const home = tmp();
    mkdirSync(join(home, "work"), { recursive: true });
    writeFileSync(join(home, "work", "demo.md"), `---\nat: 2026-09-27T10:00:00Z\n---\n\nGoal: ${"a long plan ".repeat(300)}\n`);
    createNote(home, { text: "A decision", project: "demo", kind: "decision" });
    const card = renderCard(home, loadNotes(home).notes, { id: "demo", tags: [], root: null });
    expect(card).toContain("Where we left off");
    expect(Math.ceil(card.length / 4)).toBeLessThanOrEqual(400);
  });
});

describe("third review", () => {
  it("a captured signature matches its own error with CRLF, colour codes and doubled spaces", () => {
    const raw = "\x1b[31merror TS2304:\x1b[0m  Cannot   find name 'x'.\r\nat src/a.ts:1\r\n";
    const home = tmp();
    const note = createNote(home, { text: "Declare x", project: "global", kind: "gotcha", errors: [errorSignature(raw)], tested: true });
    expect(errorSignature(raw)).toBe("error TS2304: Cannot find name 'x'.");
    expect(findFix([note], raw, null)?.id).toBe(note.id);
  });

  it("a working state without a plan never outranks a plan in a sync conflict", async () => {
    const { writeAuto } = await import("../src/work.ts");
    const home = tmp();
    writeAuto(home, "demo", { ask: "hello" });
    expect(readFileSync(join(home, "work", "demo.md"), "utf8")).not.toMatch(/^at:/m);
  });

  it("masks secrets under quoted JSON keys and every GitHub token prefix", async () => {
    const { scrub } = await import("../src/scrub.ts");
    expect(scrub('{"password": "hunter2", "api_key": "abcd1234", "user": "me"}').text).toBe('{"password": "***", "api_key": "***", "user": "me"}');
    for (const prefix of ["ghp", "gho", "ghu", "ghs", "ghr"]) expect(scrub(`${prefix}_${"A1b2".repeat(9)}`).text).toBe("***");
  });
});

describe("fourth review", () => {
  it("kits never include private notes", async () => {
    const { draftKit } = await import("../src/kits.ts");
    const home = tmp();
    createNote(home, { text: "Public stack decision", project: "demo", kind: "decision" });
    createNote(home, { text: "Private vendor pricing decision", project: "demo", kind: "decision", private: true });
    const kit = draftKit(home, "k", "demo", loadNotes(home).notes);
    expect(kit.body).toContain("Public stack decision");
    expect(kit.body).not.toContain("Private vendor pricing");
  });

  it("sync commits the working state even when notes/ holds only private notes", async () => {
    const { sync } = await import("../src/sync.ts");
    const home = tmp();
    git(home, "init", "-q");
    writeFileSync(join(home, ".gitignore"), "notes/*/private/\n");
    git(home, "add", ".gitignore");
    git(home, "commit", "-q", "-m", "init");
    createNote(home, { text: "only private", project: "demo", private: true });
    mkdirSync(join(home, "work"));
    writeFileSync(join(home, "work", "demo.md"), "---\nat: 2026-09-27T10:00:00Z\n---\n\nGoal: x\n");
    mkdirSync(join(home, "kits"));
    const result = sync(home, { push: false });
    expect(result.committed).toBe(true);
    expect(git(home, "show", "--name-only", "--format=", "HEAD").stdout.trim()).toBe("work/demo.md");
  });

  it("masks whole quoted secrets and URL / curl credentials", async () => {
    const { scrub } = await import("../src/scrub.ts");
    expect(scrub('{"password": "correct horse battery staple", "user": "me"}').text).toBe('{"password": "***", "user": "me"}');
    expect(scrub("PGPASSWORD='my pass phrase' psql").text).toBe("PGPASSWORD='***' psql");
    expect(scrub("git clone https://joe:s3cretPass@github.com/o/r.git").text).toBe("git clone https://joe:***@github.com/o/r.git");
    expect(scrub("curl -u admin:hunter2 https://x").text).toBe("curl -u admin:*** https://x");
  });

  it("gives non-Latin project names their own ids", async () => {
    const { slug } = await import("../src/util.ts");
    expect(slug("日本語")).toBe("日本語");
    expect(slug("проект")).toBe("проект");
    expect(slug("日本語")).not.toBe(slug("проект"));
    expect(slug("Café Tools")).toBe("cafe-tools");
  });

  it("a re-edited file becomes the most recent edit", () => {
    const home = tmp();
    const handlers = new Map<string, (e: unknown, c: unknown) => unknown>();
    secondBrain({ on: (e, h) => void handlers.set(e, h) }, { SECOND_BRAIN_HOME: home });
    const ctx = { cwd: home, sessionManager: { getSessionId: () => "s" } };
    for (const path of ["a.ts", "b.ts", "a.ts"]) handlers.get("tool_result")?.({ toolName: "edit", input: { path }, isError: false, content: [] }, ctx);
    handlers.get("session_before_compact")?.({}, ctx);
    expect(readFileSync(join(home, "work", `${resolveProject(home, home, {}).id}.md`), "utf8")).toContain("- edited: b.ts, a.ts\n");
  });
});
