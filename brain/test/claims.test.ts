import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { createNote, loadNotes, retireNote, saveNote, updateNote, upgradeNote, withNoteClaim } from "../src/notes.ts";
import { ClaimError, claimPath, withClaim, withClaims } from "../src/util.ts";

const roots: string[] = [];
const children: ChildProcess[] = [];
const tmp = () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-claims-"));
  roots.push(dir);
  return dir;
};
afterEach(() => {
  for (const child of children.splice(0)) child.kill();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

const SRC = pathToFileURL(join(import.meta.dirname, "..", "src")).href;

interface Outcome { code: number | null; out: string; err: string }

/** A child process: it loads the modules, runs `setup`, says "ready", and runs `action` once released. */
function script(home: string, setup: string, action: string): string {
  return `
    import fs from "node:fs";
    import { syncBuiltinESMExports } from "node:module";
    const home = ${JSON.stringify(home)};
    const notes = await import(${JSON.stringify(SRC + "/notes.ts")});
    const project = await import(${JSON.stringify(SRC + "/project.ts")});
    const util = await import(${JSON.stringify(SRC + "/util.ts")});
    ${setup}
    process.stdout.write("ready\\n");
    await new Promise((resolve) => process.stdin.once("data", resolve));
    try { ${action}; process.stdout.write("ok\\n"); }
    catch (error) { process.stdout.write("fail: " + (error instanceof Error ? error.message : String(error)) + "\\n"); process.exitCode = 1; }
  `;
}

/**
 * A slow disk: `fn` ("readFileSync" or "renameSync") lingers `ms` after finishing on a path ending in
 * `suffix` (the read of projects.json, or the write of a note file). Whoever holds no claim then
 * interleaves with the other process every time, so a missing claim fails these tests reliably.
 */
function slow(fn: "readFileSync" | "renameSync", suffix: string, ms: number): string {
  const target = fn === "renameSync" ? 1 : 0;
  return `{
    const real = fs.${fn};
    fs.${fn} = (...args) => {
      const result = real(...args);
      if (String(args[${target}]).endsWith(${JSON.stringify(suffix)})) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ${ms});
      return result;
    };
    syncBuiltinESMExports();
  }`;
}

/** Start the scripts as separate processes, wait until all are loaded and ready, then release them together. */
async function race(scripts: string[]): Promise<Outcome[]> {
  const runs = scripts.map((source) => {
    const child = spawn(process.execPath, ["--input-type=module", "-e", source], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    children.push(child);
    const ready = Promise.withResolvers<void>();
    const closed = Promise.withResolvers<Outcome>();
    let out = "";
    let err = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      out += chunk;
      if (out.includes("ready\n")) ready.resolve();
    });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { err += chunk; });
    child.once("close", (code) => {
      ready.reject(new Error(`child exited before it was ready: ${err}`));
      closed.resolve({ code, out, err });
    });
    return { child, ready: ready.promise, closed: closed.promise };
  });
  await Promise.all(runs.map((run) => run.ready));
  for (const run of runs) run.child.stdin!.end("go\n");
  return Promise.all(runs.map((run) => run.closed));
}

const noteFiles = (home: string, id: string): string[] =>
  readdirSync(join(home, "notes"), { recursive: true, encoding: "utf8" }).filter((path) => path.endsWith(`${id}.md`));

describe("two processes editing the same registry or note", () => {
  it("keeps both tags when two processes tag one project at once", async () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ extra: true, projects: { demo: { tags: ["base"], custom: 1 }, other: {} } }));
    const tagger = (tag: string) => script(home, slow("readFileSync", "projects.json", 150), `project.addProjectTag(home, "demo", ${JSON.stringify(tag)})`);
    const results = await race([tagger("alpha"), tagger("beta")]);
    expect(results.map((r) => r.out)).toEqual(["ready\nok\n", "ready\nok\n"]);
    const saved = JSON.parse(readFileSync(join(home, "projects.json"), "utf8")) as { extra: boolean; projects: { demo: { tags: string[]; custom: number }; other: object } };
    expect([...saved.projects.demo.tags].sort()).toEqual(["alpha", "base", "beta"]);
    expect(saved).toMatchObject({ extra: true, projects: { demo: { custom: 1 }, other: {} } });
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("keeps both dismissals when two processes reject errors at once", async () => {
    const home = tmp();
    writeFileSync(join(home, "rejected.json"), JSON.stringify({ hashes: ["existing"] }));
    const rejecter = (signature: string) => script(home,
      `import * as capture from ${JSON.stringify(SRC + "/capture.ts")}; ${slow("readFileSync", "rejected.json", 150)}`,
      `capture.dismissError(home, ${JSON.stringify(signature)})`);
    const results = await race([rejecter("sig-a"), rejecter("sig-b")]);
    expect(results.map((r) => r.out)).toEqual(["ready\nok\n", "ready\nok\n"]);
    const expected = ["existing", ...["sig-a", "sig-b"].map((sig) => createHash("sha256").update(`e:${sig}`).digest("hex").slice(0, 16))].sort();
    expect(JSON.parse(readFileSync(join(home, "rejected.json"), "utf8"))).toEqual({ hashes: expected });
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("keeps both tags when two processes share one note at once", async () => {
    const home = tmp();
    const note = createNote(home, { project: "global", text: "Shared rule", tags: ["base"] });
    const sharer = (tag: string) => script(home,
      `import * as sync from ${JSON.stringify(SRC + "/sync.ts")}; ${slow("readFileSync", `${note.id}.md`, 150)}`,
      `sync.shareNote(home, ${JSON.stringify(note.id)}, ${JSON.stringify(tag)})`);
    const results = await race([sharer("alpha"), sharer("beta")]);
    expect(results.map((r) => r.out)).toEqual(["ready\nok\n", "ready\nok\n"]);
    expect(loadNotes(home).notes[0]!.tags).toEqual(["alpha", "base", "beta"]);
    expect(noteFiles(home, note.id)).toHaveLength(1);
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("lets one of two stale moves of a note win and fails the other explicitly, leaving one copy", async () => {
    const home = tmp();
    const note = createNote(home, { project: "alpha", text: "Moved from two places" });
    // The CLI's old shape: a snapshot loaded before the race, saved after it.
    const mover = (to: string) => script(home,
      `const note = notes.findNote(notes.loadNotes(home).notes, ${JSON.stringify(note.id)}); ${slow("renameSync", `${note.id}.md`, 250)}`,
      `notes.saveNote(home, { ...note, project: ${JSON.stringify(to)} })`);
    const results = await race([mover("beta"), mover("gamma")]);
    expect(results.filter((r) => r.out.endsWith("ok\n"))).toHaveLength(1);
    const loser = results.find((r) => r.out.includes("fail: "));
    expect(loser?.out).toMatch(/fail: .*also exists at .*nothing was written/);
    expect(noteFiles(home, note.id)).toHaveLength(1);
    const { notes, errors } = loadNotes(home);
    expect(errors).toEqual([]);
    expect(notes).toHaveLength(1);
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("applies two updateNote moves one after the other to the note as it is by then", async () => {
    const home = tmp();
    const note = createNote(home, { project: "alpha", text: "Moved twice" });
    const mover = (to: string) => script(home, slow("renameSync", `${note.id}.md`, 250),
      `notes.updateNote(home, ${JSON.stringify(note.id)}, (fresh) => ({ ...fresh, project: ${JSON.stringify(to)} }))`);
    const results = await race([mover("beta"), mover("gamma")]);
    expect(results.map((r) => r.out)).toEqual(["ready\nok\n", "ready\nok\n"]);
    expect(noteFiles(home, note.id)).toHaveLength(1);
    const { notes, errors } = loadNotes(home);
    expect(errors).toEqual([]);
    expect(notes.map((n) => n.id)).toEqual([note.id]);
    expect(["beta", "gamma"]).toContain(notes[0]!.project);
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("keeps three processes out of one claim at a time even when they all find an expired live-pid claim", async () => {
    const home = tmp();
    const file = claimPath(home, "x.lock");
    const log = join(home, "log.txt");
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${process.ppid}.reused`);
    const old = new Date(Date.now() - 60_000);
    utimesSync(file, old, old);
    const worker = () => script(home, "", `util.withClaim(${JSON.stringify(file)}, () => {
      fs.appendFileSync(${JSON.stringify(log)}, "in " + process.pid + "\\n");
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
      fs.appendFileSync(${JSON.stringify(log)}, "out " + process.pid + "\\n");
    }, 10000)`);
    const results = await race([worker(), worker(), worker()]);
    expect(results.map((r) => r.out)).toEqual(["ready\nok\n", "ready\nok\n", "ready\nok\n"]);
    const lines = readFileSync(log, "utf8").trim().split("\n");
    expect(lines).toHaveLength(6);
    for (let i = 0; i < lines.length; i += 2) {
      const [enter, pid] = lines[i]!.split(" ");
      expect(enter).toBe("in");
      expect(lines[i + 1]).toBe(`out ${pid}`);
    }
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });
});

describe("note writes", () => {
  it("refuses to save a snapshot of a note that moved, writing nothing", () => {
    const home = tmp();
    const note = createNote(home, { project: "alpha", text: "Move me" });
    const moved = saveNote(home, { ...note, project: "beta" });
    expect(() => saveNote(home, { ...note, project: "gamma" })).toThrow(/also exists at .*nothing was written/);
    expect(loadNotes(home).notes.map((n) => n.path)).toEqual([moved.path]);
    expect(noteFiles(home, note.id)).toHaveLength(1);
  });

  it("updateNote reloads the note first, so a move after the snapshot is not undone", () => {
    const home = tmp();
    const note = createNote(home, { project: "alpha", text: "Reloaded", tags: ["one"] });
    saveNote(home, { ...note, project: "beta" });
    const next = updateNote(home, note.id.toUpperCase(), (fresh) => ({ ...fresh, project: "gamma", tags: [...fresh.tags, "two"] }));
    expect(next).toMatchObject({ id: note.id, project: "gamma", tags: ["one", "two"] });
    expect(loadNotes(home).notes).toEqual([next]);
    expect(noteFiles(home, note.id)).toHaveLength(1);
    expect(updateNote(home, note.id, () => null)).toBeNull();
    expect(() => updateNote(home, "n-missing", (fresh) => fresh)).toThrow("no note n-missing");
  });

  it("applies an upgrade to the note as stored, and refuses one whose body or retirement changed meanwhile", () => {
    const home = tmp();
    const note = createNote(home, { project: "demo", text: "Cache rule", tags: ["a"] });
    saveNote(home, { ...note, tags: ["a", "b"] });
    const upgraded = upgradeNote(home, note, { tags: ["c"] });
    expect([...upgraded!.tags].sort()).toEqual(["a", "b", "c"]);

    const edited = createNote(home, { project: "demo", text: "Edited rule" });
    saveNote(home, { ...edited, body: "Edited rule\n\nnow different" });
    expect(() => upgradeNote(home, edited, { tags: ["x"] })).toThrow(/changed since it was read; nothing was written/);

    const retired = createNote(home, { project: "demo", text: "Retired rule" });
    retireNote(home, retired.id);
    expect(() => upgradeNote(home, retired, { tags: ["x"] })).toThrow(/changed since it was read/);
    expect(loadNotes(home).notes.find((n) => n.id === retired.id)?.tags).not.toContain("x");
  });

  it("holds one claim per note whatever the case of its id, and nests saves inside it", () => {
    const home = tmp();
    const note = createNote(home, { project: "demo", text: "Case rule" });
    withNoteClaim(home, note.id.toUpperCase(), () => {
      expect(readdirSync(join(home, "state", "locks"))).toEqual([`note-${note.id.toLowerCase()}.lock`]);
      saveNote(home, { ...note, tags: ["x"] });
    });
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });

  it("retires a note and its replacement under both claims, releasing them", () => {
    const home = tmp();
    const old = createNote(home, { project: "demo", text: "Old rule" });
    const next = createNote(home, { project: "demo", text: "New rule" });
    expect(retireNote(home, old.id, next.id)).toMatchObject({ id: old.id, replacedBy: next.id });
    expect(loadNotes(home).notes.find((n) => n.id === next.id)?.replaces).toBe(old.id);
    expect(readdirSync(join(home, "state", "locks"))).toEqual([]);
  });
});

describe("withClaim", () => {
  const claim = (home: string) => claimPath(home, "x.lock");

  it("holds the claim while it runs, nests for the same claim, and releases it even when fn throws", () => {
    const file = claim(tmp());
    expect(withClaim(file, () => {
      expect(existsSync(file)).toBe(true);
      withClaim(file, () => undefined);
      expect(existsSync(file)).toBe(true);
      return "done";
    })).toBe("done");
    expect(existsSync(file)).toBe(false);
    expect(() => withClaim(file, () => { throw new Error("boom"); })).toThrow("boom");
    expect(existsSync(file)).toBe(false);
  });

  it("leaves a fresh live-pid claim intact and identifies its holder and recovery path", () => {
    const file = claim(tmp());
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${process.ppid}.holder`);
    let failure: unknown;
    try { withClaim(file, () => { throw new Error("must not run"); }, 100); }
    catch (error) { failure = error; }
    expect(failure).toBeInstanceOf(ClaimError);
    const message = (failure as Error).message;
    expect(message).toMatch(/being changed by another Brain process/);
    expect(message).toContain(`pid ${process.ppid}`);
    expect(message).toContain(`delete ${file}`);
    expect(readFileSync(file, "utf8")).toBe(`${process.ppid}.holder`);
    expect(readdirSync(join(file, ".."))).toEqual(["x.lock"]);
  });

  it("reclaims an expired claim even when its pid belongs to a live process", () => {
    const file = claim(tmp());
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${process.ppid}.reused`);
    const old = new Date(Date.now() - 60_000);
    utimesSync(file, old, old);
    expect(withClaim(file, () => "ran", 100)).toBe("ran");
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });

  it("recovers a fresh own-pid claim left behind by a failed release", () => {
    const file = claim(tmp());
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${process.pid}.leftover`);
    expect(withClaim(file, () => "ran", 100)).toBe("ran");
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });

  it("breaks a claim whose owner process is gone", () => {
    const file = claim(tmp());
    const gone = spawnSync(process.execPath, ["-e", ""]).pid!;
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${gone}.crashed`);
    expect(withClaim(file, () => "ran", 100)).toBe("ran");
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });

  it("recovers a record that never got its owner's pid once it is old, and waits on a fresh one", () => {
    const file = claim(tmp());
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, "");
    expect(() => withClaim(file, () => "never", 100)).toThrow(ClaimError);
    expect(existsSync(file)).toBe(true);
    const old = new Date(Date.now() - 60_000);
    utimesSync(file, old, old);
    expect(withClaim(file, () => "ran", 100)).toBe("ran");
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });

  it("waits on a fresh live-pid reclaim gate, then recovers it when expired", () => {
    const file = claim(tmp());
    const gone = spawnSync(process.execPath, ["-e", ""]).pid!;
    const gate = `${file}.reclaim`;
    mkdirSync(join(file, ".."), { recursive: true });
    writeFileSync(file, `${gone}.crashed`);
    writeFileSync(gate, `${process.ppid}.reclaimer`);
    expect(() => withClaim(file, () => "never", 100)).toThrow(ClaimError);
    expect(readFileSync(file, "utf8")).toBe(`${gone}.crashed`);
    const old = new Date(Date.now() - 60_000);
    utimesSync(gate, old, old);
    expect(withClaim(file, () => "ran", 500)).toBe("ran");
    expect(readdirSync(join(file, ".."))).toEqual([]);
  });

  it("recovers a fresh own-pid gate or the gate of a dead reclaimer", () => {
    const file = claim(tmp());
    const gone = spawnSync(process.execPath, ["-e", ""]).pid!;
    const gate = `${file}.reclaim`;
    mkdirSync(join(file, ".."), { recursive: true });
    for (const pid of [process.pid, gone]) {
      writeFileSync(file, `${gone}.crashed`);
      writeFileSync(gate, `${pid}.reclaimer`);
      expect(withClaim(file, () => "ran", 500)).toBe("ran");
      expect(readdirSync(join(file, ".."))).toEqual([]);
    }
  });

  it("never removes a claim another process took over while fn ran", () => {
    const file = claim(tmp());
    withClaim(file, () => writeFileSync(file, `${process.pid}.successor`));
    expect(readFileSync(file, "utf8")).toBe(`${process.pid}.successor`);
  });

  it("takes several claims in one order, once each", () => {
    const home = tmp();
    const [a, b] = [claimPath(home, "a.lock"), claimPath(home, "b.lock")];
    withClaims([b, a, b], () => {
      expect(readdirSync(join(a, "..")).sort()).toEqual(["a.lock", "b.lock"]);
      withClaims([a, b], () => undefined);
    });
    expect(readdirSync(join(a, ".."))).toEqual([]);
  });
});
