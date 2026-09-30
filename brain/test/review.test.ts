/** Regressions for the code-review findings on brain/src (each failed before its fix). */
import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { acceptProposal, listProposals, pendingCount, rejectProposal, errorSignature, findFix, scanCommits, scanEvents } from "../src/capture.ts";
import { convertV3 } from "../src/convert.ts";
import { createNote, loadNotes } from "../src/notes.ts";
import secondBrain, { type HostLike } from "../src/omp.ts";
import { loadProjects, projectById, resolveProject } from "../src/project.ts";
import { main } from "../src/cli.ts";
import { renderCard } from "../src/card.ts";
import { recall } from "../src/search.ts";
import { readWork } from "../src/work.ts";

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
      line({ command: "npm test", ok: false, error }) + line({ command: "npm ci && npm test", ok: true }),
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
    expect(out.content[1]?.text).toContain("Run npm ci first");
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

  it("move resolves aliases", async () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { "second-brain": { aliases: ["the-2nd-brain"] } } }));
    const out: string[] = [];
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "scratch" }, cwd: home, out: (s: string) => out.push(s), err: (s: string) => out.push(s) };
    await main(["note", "We chose vite", "--kind", "decision"], io);
    const id = out[0]?.replace("saved ", "") ?? "";
    await main(["move", id, "--to", "The-2nd-Brain"], io);
    expect(loadNotes(home).notes[0]?.project).toBe("second-brain");
  });

  it("counts only file-changing tools as edits", () => {
    const home = tmp();
    const handlers = new Map<string, (e: unknown, c: unknown) => unknown>();
    secondBrain({ on: (e, h) => void handlers.set(e, h) }, { SECOND_BRAIN_HOME: home });
    const ctx = { cwd: home, sessionManager: { getSessionId: () => "s" } };
    handlers.get("tool_result")?.({ toolName: "read", input: { path: "a.ts" }, isError: false, content: [] }, ctx);
    handlers.get("tool_result")?.({ toolName: "edit", input: { path: "b.ts" }, isError: false, content: [] }, ctx);
    handlers.get("session_compact")?.({}, { ...ctx });
    expect(readWork(home, resolveProject(home, home, {}).id)?.auto).toBe("- edited: b.ts");
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


  it("masks secrets under quoted JSON keys and every GitHub token prefix", async () => {
    const { scrub } = await import("../src/scrub.ts");
    expect(scrub('{"password": "hunter2", "api_key": "abcd1234", "user": "me"}').text).toBe('{"password": "***", "api_key": "***", "user": "me"}');
    for (const prefix of ["ghp", "gho", "ghu", "ghs", "ghr"]) expect(scrub(`${prefix}_${"A1b2".repeat(9)}`).text).toBe("***");
  });
});

describe("fourth review", () => {
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
    handlers.get("session_compact")?.({}, ctx);
    expect(readWork(home, resolveProject(home, home, {}).id)?.auto).toBe("- edited: b.ts, a.ts");
  });
});

describe("fifth review", () => {
  it("syncs a Brain home that is a subdirectory of its repository", async () => {
    const { sync } = await import("../src/sync.ts");
    const repoDir = tmp();
    git(repoDir, "init", "-q");
    git(repoDir, "commit", "-q", "--allow-empty", "-m", "init");
    const home = join(repoDir, "brain-home");
    const note = createNote(home, { text: "note in a nested home", project: "demo" });
    const result = sync(home, { push: false });
    expect(result.committed).toBe(true);
    expect(git(repoDir, "show", "--name-only", "--format=", "HEAD").stdout.trim()).toBe(`brain-home/notes/demo/${note.id}.md`);
  });

  it("commits the deletion of a whole sync path", async () => {
    const { sync } = await import("../src/sync.ts");
    const { rmSync } = await import("node:fs");
    const home = tmp();
    git(home, "init", "-q");
    git(home, "commit", "-q", "--allow-empty", "-m", "init");
    createNote(home, { text: "soon gone", project: "demo" });
    writeFileSync(join(home, "projects.json"), '{ "projects": {} }\n');
    sync(home, { push: false });
    rmSync(join(home, "notes"), { recursive: true });
    rmSync(join(home, "projects.json"));
    const result = sync(home, { push: false });
    expect(result.committed).toBe(true);
    expect(git(home, "ls-files").stdout.trim()).toBe("");
  });
});

it("resolves a working-state conflict in a nested Brain home", async () => {
  const { sync } = await import("../src/sync.ts");
  const root = tmp();
  const bare = join(root, "remote.git");
  mkdirSync(bare);
  git(bare, "init", "-q", "--bare");
  git(bare, "symbolic-ref", "HEAD", "refs/heads/main");
  const a = join(root, "a");
  mkdirSync(a);
  git(a, "init", "-q", "-b", "main");
  git(a, "commit", "-q", "--allow-empty", "-m", "init");
  git(a, "remote", "add", "origin", bare);
  git(a, "push", "-q", "-u", "origin", "main");
  git(root, "clone", "-q", bare, "b");
  const b = join(root, "b");
  const work = (at: string, text: string) => `---\nat: ${at}\n---\n\n${text}\n`;
  for (const clone of [a, b]) mkdirSync(join(clone, "home", "work"), { recursive: true });
  writeFileSync(join(a, "home", "work", "demo.md"), work("2026-09-27T09:00:00Z", "base"));
  sync(join(a, "home"));
  sync(join(b, "home"));
  writeFileSync(join(a, "home", "work", "demo.md"), work("2026-09-27T10:00:00Z", "older from A"));
  sync(join(a, "home"));
  writeFileSync(join(b, "home", "work", "demo.md"), work("2026-09-27T11:00:00Z", "newer from B"));
  expect(sync(join(b, "home"))).toMatchObject({ pulled: true, pushed: true });
  expect(readFileSync(join(b, "home", "work", "demo.md"), "utf8")).toContain("newer from B");
});

describe("sixth review: credentials by key name, URL and header", () => {
  it("masks every credential shape", async () => {
    const { scrub } = await import("../src/scrub.ts");
    const masked: [string, string][] = [
      ["aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "aws_secret_access_key = ***"],
      ['secret_key = "abc def ghi"', 'secret_key = "***"'],
      ["private_key: hunter22", "private_key: ***"],
      ["clientSecret=abcdef12345", "clientSecret=***"],
      ["PGPASSWORD='my pass phrase' psql", "PGPASSWORD='***' psql"],
      ["redis://:supersecret@host:6379", "redis://:***@host:6379"],
      ["curl --user=alice:s3cretpw https://x", "curl --user=alice:*** https://x"],
      ["Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: Basic ***"],
      ["Authorization: Token abcdef123456", "Authorization: Token ***"],
    ];
    for (const [input, expected] of masked) expect(scrub(input, { longRuns: false }).text, input).toBe(expected);
  });

  it("leaves look-alikes alone", async () => {
    const { scrub } = await import("../src/scrub.ts");
    for (const text of ["secretary: Bob", "key_count: 5", "sort key: name", "cache_key=build-123-abc", "KEYBOARD_LAYOUT=us", "OLDPWD=/home/me", "https://github.com/o/r.git", "Error: something failed"]) {
      expect(scrub(text), text).toEqual({ text, scrubbed: false });
    }
  });
});

describe("seventh review", () => {
  it("a note whose fields contain \\r or U+2028 still loads", () => {
    const home = tmp();
    const note = createNote(home, { text: "pip install stalls behind proxy", project: "demo", errors: ["Downloading 50%\rProxyError"], tags: ["a b"], tested: true });
    const { notes, errors } = loadNotes(home);
    expect(errors).toEqual([]);
    expect(notes[0]).toMatchObject({ id: note.id, errors: ["Downloading 50% ProxyError"], tags: ["a-b"] });
  });

  it("a global note the project cannot see is not a duplicate", async () => {
    const { findSameHeadline } = await import("../src/notes.ts");
    const home = tmp();
    createNote(home, { text: "Use uv for installs", project: "global", tags: ["python"] });
    const { notes } = loadNotes(home);
    expect(findSameHeadline(notes, "Use uv for installs", "web", ["node"])).toBeUndefined();
    expect(findSameHeadline(notes, "Use uv for installs", "etl", ["python"])).toBeDefined();
  });
});

describe("eighth review", () => {
  it("a moved note is committed as a move, never as two copies", async () => {
    const { sync } = await import("../src/sync.ts");
    const home = tmp();
    git(home, "init", "-q");
    git(home, "commit", "-q", "--allow-empty", "-m", "init");
    const out: string[] = [];
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "alpha" }, cwd: home, out: (s: string) => out.push(s), err: (s: string) => out.push(s) };
    await main(["note", "a note that will move"], io);
    const id = out[0]?.replace("saved ", "") ?? "";
    sync(home, { push: false });
    await main(["move", id, "--to", "beta"], io);
    sync(home, { push: false });
    expect(git(home, "ls-tree", "-r", "--name-only", "HEAD").stdout.trim()).toBe(`notes/beta/${id}.md`);
    expect(git(home, "status", "--porcelain", "--", "notes").stdout).toBe("");
  });

  it("masks quoted secrets that contain the other quote or an escaped quote", async () => {
    const { scrub } = await import("../src/scrub.ts");
    expect(scrub(`DB_PASSWORD="it's-a-secret"`).text).toBe(`DB_PASSWORD="***"`);
    expect(scrub(`{"password": "don't tell 99", "user": "me"}`).text).toBe(`{"password": "***", "user": "me"}`);
    expect(scrub(`password='ab"cd ef'`).text).toBe(`password='***'`);
    expect(scrub(`password="ab\\"cd" next`).text).toBe(`password="***" next`);
    expect(scrub(`password: it's-secret rest`).text).toBe("password: *** rest");
  });
});

describe("ninth review", () => {
  it("tags compare case-insensitively wherever they are written", async () => {
    const home = tmp();
    const repoDir = join(tmp(), "ts-app");
    mkdirSync(join(repoDir, ".git"), { recursive: true });
    writeFileSync(join(repoDir, "tsconfig.json"), "{}");
    const out: string[] = [];
    await main(["note", "Prefer strict null checks", "--global", "--tag", "TypeScript", "--tag", "C++"], { env: { SECOND_BRAIN_HOME: home }, cwd: repoDir, out: (s) => out.push(s), err: (s) => out.push(s) });
    expect(loadNotes(home).notes[0]?.tags).toEqual(["typescript", "c++"]);
    const project = resolveProject(home, repoDir, {});
    expect(recall(loadNotes(home).notes, "strict null checks", { project }).length).toBe(1);
  });

  it("resolves a working-state conflict for a project with a non-Latin name", async () => {
    const { sync } = await import("../src/sync.ts");
    const root = tmp();
    const bare = join(root, "remote.git");
    mkdirSync(bare);
    git(bare, "init", "-q", "--bare");
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main");
    const a = join(root, "a");
    mkdirSync(a);
    git(a, "init", "-q", "-b", "main");
    git(a, "commit", "-q", "--allow-empty", "-m", "init");
    git(a, "remote", "add", "origin", bare);
    git(a, "push", "-q", "-u", "origin", "main");
    git(root, "clone", "-q", bare, "b");
    const b = join(root, "b");
    const work = (at: string, text: string) => `---\nat: ${at}\n---\n\n${text}\n`;
    for (const clone of [a, b]) mkdirSync(join(clone, "work"), { recursive: true });
    writeFileSync(join(a, "work", "проект.md"), work("2026-09-27T09:00:00Z", "base"));
    sync(a);
    sync(b);
    writeFileSync(join(a, "work", "проект.md"), work("2026-09-27T10:00:00Z", "older from A"));
    sync(a);
    writeFileSync(join(b, "work", "проект.md"), work("2026-09-27T11:00:00Z", "newer from B"));
    expect(sync(b)).toMatchObject({ pulled: true, pushed: true });
    expect(readFileSync(join(b, "work", "проект.md"), "utf8")).toContain("newer from B");
  });
});


it("review displays each full scrubbed proposal body before acceptance", async () => {
  const home = tmp();
  mkdirSync(join(home, "state", "inbox"), { recursive: true });
  writeFileSync(join(home, "state", "inbox", "p-review.json"), JSON.stringify({ id: "p-review", at: new Date().toISOString(), project: "global", kind: "gotcha", text: "Use the repair\n\nActual command: npm test -- --run\n\npassword=SyntheticPassword\n\nError: package unavailable", tested: false, errors: [], evidence: [], source: "capture" }));
  const out: string[] = [];
  expect(await main(["review"], { env: { SECOND_BRAIN_HOME: home }, cwd: home, out: (s) => out.push(s), err: (s) => out.push(s) })).toBe(0);
  const text = out.join("\n");
  expect(text).toContain("Actual command: npm test -- --run");
  expect(text).toContain("Error: package unavailable");
  expect(text).not.toContain("SyntheticPassword");
});

it("review lists this project's and global proposals, and counts the rest (--all shows them)", async () => {
  const home = tmp();
  mkdirSync(join(home, "state", "inbox"), { recursive: true });
  for (const project of ["demo", "global", "other"]) {
    writeFileSync(join(home, "state", "inbox", `p-${project}.json`), JSON.stringify({ id: `p-${project}`, at: new Date().toISOString(), project, kind: "gotcha", text: `proposal from ${project}`, tested: false, errors: [], evidence: [], source: "capture" }));
  }
  const review = async (...args: string[]) => {
    const out: string[] = [];
    await main(["review", ...args], { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home, out: (s) => out.push(s), err: (s) => out.push(s) });
    return out.join("\n");
  };
  const scoped = await review();
  expect(scoped).toContain("proposal from demo");
  expect(scoped).toContain("proposal from global");
  expect(scoped).not.toContain("proposal from other");
  expect(scoped).toContain("+1 in other projects (brain review --all)");
  expect(await review("--all")).toContain("proposal from other");
  rmSync(join(home, "state", "inbox", "p-demo.json"));
  rmSync(join(home, "state", "inbox", "p-global.json"));
  expect(await review()).toBe("nothing to review here; +1 in other projects (brain review --all)");
});

it("a proposal under an id that became an alias is listed, counted and accepted under its owner", () => {
  const home = tmp();
  mkdirSync(join(home, "state", "inbox"), { recursive: true });
  writeFileSync(join(home, "state", "inbox", "p-0123456789.json"), JSON.stringify({ id: "p-0123456789", at: new Date().toISOString(), project: "old", kind: "gotcha", text: "proposal from old", tested: false, errors: [], evidence: [], source: "capture" }));
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { owner: { aliases: ["old"] } } }));
  expect(listProposals(home)[0]?.project).toBe("owner");
  expect(pendingCount(home, "owner")).toBe(1);
  const note = acceptProposal(home, "p-0123456789");
  expect(note.project).toBe("owner");
  expect(existsSync(join(home, "notes", "owner", `${note.id}.md`))).toBe(true);
});

describe("proposal id boundary", () => {
  it.each(["accept", "reject"])("%s refuses an outside JSON file without mutation", async (command) => {
    const home = tmp();
    mkdirSync(join(home, "state", "inbox"), { recursive: true });
    const victim = join(home, "victim.json");
    const content = JSON.stringify({ text: "Untouched victim", project: "global", kind: "gotcha", errors: ["specific error"], evidence: [], tested: false, source: "capture" });
    writeFileSync(victim, content);
    const errors: string[] = [];
    expect(await main([command, "../../victim"], { env: { SECOND_BRAIN_HOME: home }, cwd: home, out: () => {}, err: (s) => errors.push(s) })).toBe(1);
    expect(errors.join("\n")).toContain("invalid proposal id");
    expect(readFileSync(victim, "utf8")).toBe(content);
    expect(loadNotes(home).notes).toEqual([]);
    expect(existsSync(join(home, "rejected.json"))).toBe(false);
  });
  it.each(["p-123", "p-ABCDEFGHIJ", "../victim", "p-0123456789/other", "p-0123456789\n"])("rejects malformed id %j in the library", (id) => {
    const home = tmp();
    expect(() => acceptProposal(home, id)).toThrow("invalid proposal id");
    expect(() => rejectProposal(home, id)).toThrow("invalid proposal id");
  });
});
