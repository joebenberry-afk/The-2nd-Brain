/** Tests for the hardening pass: scrubbing on write, answer(), duplicates, display paths. */
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { main } from "../src/cli.ts";
import { createNote, findSameHeadline, loadNotes } from "../src/notes.ts";
import { displayPath } from "../src/omp.ts";
import { answer, FIRST_HIT_CHARS, recall, renderHits } from "../src/search.ts";
import { scrub } from "../src/scrub.ts";
import { estimateTokens } from "../src/util.ts";
import { readWork, writeAuto, writeWork } from "../src/work.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-hard-"));
const project = { id: "demo", tags: [], root: null };
const SHA = "0123456789abcdef0123456789abcdef01234567";

describe("secrets never reach notes or working state", () => {
  it("masks compound double-dash credential flags", () => {
    for (const flag of ["db-password", "db-passwd", "api-token", "client-secret", "service-api-key", "service-apikey", "service-auth", "service-credential", "service-credentials"]) {
      for (const sep of [" ", "="]) {
        expect(scrub(`dbcli --${flag}${sep}hunter2`).text).toBe(`dbcli --${flag}${sep}***`);
      }
    }
  });

  it("preserves prose colon keys but masks credential assignments", () => {
    for (const text of ["SyntaxError: Unexpected token: identifier", "pytest fails from pwd: C:/repo/tests", "The secret: never commit .env", "csrf_token: generated per request"]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    for (const text of ["token: ghp_abcdefghijklmnopqrstuvwxyz0123456789", "token: abcdefghijklmnop1234", "password: hunter2secret", "API_KEY=hunter2secret", "Authorization: Bearer hunter2secret"]) {
      expect(scrub(text).text).toContain("***");
      expect(scrub(text).text).not.toContain("hunter2secret");
    }
  });

  it("masks credentials in note bodies and error patterns but keeps commit SHAs", () => {
    const home = tmp();
    const note = createNote(home, {
      text: `Deploy key rotated\n\nOld token=abc123def456 and ghp_${"x".repeat(30)} were in the log; fixed in ${SHA}.`,
      project: "demo",
      errors: ["Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig rejected"],
    });
    const file = readFileSync(note.path, "utf8");
    expect(file).not.toContain("abc123");
    expect(file).not.toContain("ghp_");
    expect(file).not.toContain("eyJhbGci");
    expect(file).toContain(SHA);
    expect(file).toContain("token=***");
  });

  it("masks credentials in the working state and its auto section", () => {
    const home = tmp();
    writeWork(home, "demo", "Goal: ship. api_key=sk-" + "a".repeat(30));
    writeAuto(home, "demo", { failure: `curl -H "Authorization: Bearer ${"t".repeat(40)}" → 401`, ask: "use password: hunter2" });
    const work = readFileSync(join(home, "work", "demo.md"), "utf8");
    expect(work).not.toMatch(/sk-a{30}|hunter2|t{40}/);
    expect(readWork(home, "demo")?.text).toContain("Goal: ship.");
  });

  it("leaves ordinary words, paths and parser errors alone", () => {
    for (const text of [
      "Use the disk-usage-analyzer-config-v2 for this",
      "task-runner-configuration-file",
      "open /home/runner/work/myproject/myproject/package.json",
      "C:/Users/me/Documents/The-Second-Brain/brain/src/omp.ts",
      "SyntaxError: Unexpected token: } at line 3",
    ]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    expect(scrub("key sk-proj-abc123def456ghi789jkl012").text).toBe("key ***");
    expect(scrub("aGVsbG8gd29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IHN0cmluZyE=").text).toBe("***");
  });

  it("the long-run rule stays on for captured output", () => {
    expect(scrub(`blob ${SHA}`).text).not.toContain(SHA);
    expect(scrub(`blob ${SHA}`, { longRuns: false }).text).toContain(SHA);
  });
});

describe("answer", () => {
  it("returns a whole note for its id, only when visible", () => {
    const home = tmp();
    const long = "Headline here\n\n" + "detail ".repeat(200);
    const note = createNote(home, { text: long, project: "demo", evidence: ["src/a.ts"] });
    const { notes } = loadNotes(home);
    const full = answer(notes, note.id, { project });
    expect(full.startsWith(`${note.id} [note, evidence: src/a.ts]\nHeadline here`)).toBe(true);
    expect(estimateTokens(full)).toBeLessThanOrEqual(600);
    expect(full.length).toBeGreaterThan(1000);
    expect(answer(notes, note.id, { project: { id: "other", tags: [], root: null } })).not.toContain("Headline here");
    expect(answer(notes, note.id, { project: { id: "other", tags: [], root: null }, all: true })).toContain("Headline here");
  });

  it("gives the first hit more room than the rest", () => {
    const home = tmp();
    for (const w of ["alpha", "alpha beta", "alpha gamma"]) createNote(home, { text: `${w} rule\n\n${"words ".repeat(150)}`, project: "demo" });
    const hits = recall(loadNotes(home).notes, "alpha rule", { project });
    const lines = renderHits(hits).split("\n");
    expect(lines.length).toBe(hits.length);
    expect(lines[0]?.length).toBe(FIRST_HIT_CHARS);
    for (const line of lines.slice(1)) expect(line.length).toBeLessThanOrEqual(240);

  });
});

describe("duplicate notes", () => {
  it("finds an active note with the same headline in the project or global", () => {
    const home = tmp();
    const first = createNote(home, { text: "Use Node 22.18+\n\nbecause of type stripping", project: "demo" });
    const { notes } = loadNotes(home);
    expect(findSameHeadline(notes, "  use   node 22.18+ \n\nother body", "demo")?.id).toBe(first.id);
    expect(findSameHeadline(notes, "Use Node 22.18+", "other")).toBeUndefined();
    expect(findSameHeadline(notes, "Use Node 24", "demo")).toBeUndefined();
  });

  it("brain note does not write the same learning twice", async () => {
    const home = tmp();
    const out: string[] = [];
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home, out: (s: string) => out.push(s), err: () => {} };
    await main(["note", "Always run npm ci before tests"], io);
    await main(["note", "  Always  run npm ci before tests  "], io);
    expect(out[1]).toBe(out[0]?.replace("saved", "already noted"));
    expect(loadNotes(home).notes).toHaveLength(1);
  });
});

describe("displayPath", () => {
  it("is relative to the project root inside it, with forward slashes", () => {
    expect(displayPath("/work/app/src/a.ts", "/work/app", "/work/app")).toBe("src/a.ts");
    expect(displayPath("src/b.ts", "/work/app", "/work/app")).toBe("src/b.ts");
    expect(displayPath("/elsewhere/c.ts", "/work/app", "/work/app")).toBe("/elsewhere/c.ts");
    expect(displayPath("/work/application/d.ts", "/work/app", "/work")).toBe("/work/application/d.ts");
    expect(displayPath("x\\y.ts", null, "/w")).toBe("x/y.ts");
  });
});

describe("answer shows a retired note that fits better than anything current", () => {
  it("answers with the active replacement while keeping explicit history reads", async () => {
    const { retireNote } = await import("../src/notes.ts");
    const home = tmp();
    const old = createNote(home, { text: "Hard cap of two workers per session", project: "demo", kind: "decision" });
    const next = createNote(home, { text: "Adaptive fan-out sizes worker pools", project: "demo", kind: "decision" });
    createNote(home, { text: "Session logs rotate daily", project: "demo" });
    retireNote(home, old.id, next.id);
    const { notes } = loadNotes(home);
    const text = answer(notes, "two workers cap", { project });
    expect(text.split("\n")[0]).toContain(next.id);
    expect(text.split("\n")[1]).toContain(`${old.id} [decision] Hard cap of two workers per session (retired`);
    expect(text).toContain(`replaced by ${next.id}`);
    expect(answer(notes, "adaptive fan-out worker pools", { project })).not.toContain("retired");
    expect(answer(notes, "two workers cap", { project, history: true }).split("\n")[0]).toContain(old.id);
  });
});
