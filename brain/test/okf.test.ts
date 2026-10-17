import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findFix } from "../src/capture.ts";
import { main, type Io } from "../src/cli.ts";
import { createNote, expired, loadNotes, retireNote, saveNote, type Note } from "../src/notes.ts";
import { answer } from "../src/search.ts";

const tmp = (p = "brain-okf-") => mkdtempSync(join(tmpdir(), p));

async function run(argv: string[], io: Partial<Io>): Promise<{ code: number; out: string; err: string }> {
  const out: string[] = [];
  const err: string[] = [];
  const code = await main(argv, { stdin: () => "", ...io, out: (s) => out.push(s), err: (s) => err.push(s) });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

function setup() {
  const home = tmp();
  return { home, io: { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home } };
}

describe("stale_after", () => {
  it("a date expires at its UTC start; an instant at itself; a bad value never", () => {
    const midnight = Date.parse("2026-10-05T00:00:00Z");
    expect(expired({ staleAfter: "2026-10-05" }, midnight - 1)).toBe(false);
    expect(expired({ staleAfter: "2026-10-05" }, midnight)).toBe(true);
    expect(expired({ staleAfter: "2026-10-05T02:00:00+02:00" }, midnight)).toBe(true);
    expect(expired({ staleAfter: "2026-02-30" }, midnight)).toBe(false);
    expect(expired({ staleAfter: undefined }, midnight)).toBe(false);
  });

  it("an expired fix is never pushed, and recall demotes and marks it without hiding it", () => {
    const { home } = setup();
    const old = createNote(home, { project: "global", text: "Pin quartz to 1.2", tested: true, errors: ["quartz version mismatch"], staleAfter: "2020-01-01" });
    const live = createNote(home, { project: "global", text: "Quartz cache lives in AppData", staleAfter: "2999-01-01" });
    const notes = loadNotes(home).notes;
    expect(findFix(notes, "Error: quartz version mismatch", null)).toBeNull();
    saveNote(home, { ...old, staleAfter: "2999-01-01" });
    expect(findFix(loadNotes(home).notes, "Error: quartz version mismatch", null)?.id).toBe(old.id);
    saveNote(home, { ...old, staleAfter: "2020-01-01" });
    const lines = answer(loadNotes(home).notes, "quartz", { project: null, home }).split("\n");
    expect(lines[0]).toContain(live.id);
    expect(lines[0]).not.toContain("stale");
    expect(lines[1]).toContain(old.id);
    expect(lines[1]).toContain("(stale since 2020-01-01)");
  });

  it("brain note --stale-after refuses a bad date and updates a repeated note", async () => {
    const { home, io } = setup();
    const bad = await run(["note", "Promo price ends", "--stale-after", "next week"], io);
    expect(bad.code).toBe(1);
    expect(loadNotes(home).notes).toHaveLength(0);
    expect((await run(["note", "Promo price ends", "--stale-after", "2026-11-01"], io)).code).toBe(0);
    expect((await run(["note", "Promo price ends", "--stale-after", "2026-12-01"], io)).out).toMatch(/^updated n-/);
    expect(loadNotes(home).notes[0]?.staleAfter).toBe("2026-12-01");
  });
});

describe("tested provenance", () => {
  it("records who verified a note; the first verifier sticks until the owner confirms", async () => {
    const { home, io } = setup();
    const saved = await run(["note", "Clear PYTHONHOME first", "--error", "SRE module mismatch", "--tested"], io);
    const id = saved.out.split(" ")[1]!;
    expect(loadNotes(home).notes[0]).toMatchObject({ tested: true, testedBy: "agent" });
    const at = loadNotes(home).notes[0]?.testedAt;
    expect(at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    await run(["note", "Clear PYTHONHOME first", "--tested"], io);
    expect(loadNotes(home).notes[0]).toMatchObject({ testedBy: "agent", testedAt: at });
    await run(["tested", id], io);
    expect(loadNotes(home).notes[0]?.testedBy).toBe("owner");
    expect((await run(["recall", id], io)).out).toMatch(new RegExp(`^${id} \\[note, tested by owner \\d{4}-\\d{2}-\\d{2}\\]`));
  });

  it("brain check flags a stale_after that never expires and an unknown verifier", async () => {
    const { home, io } = setup();
    mkdirSync(join(home, "notes", "demo"), { recursive: true });
    writeFileSync(join(home, "notes", "demo", "n-a.md"), "---\nid: n-a\nstale_after: soon\n---\n\nA\n");
    writeFileSync(join(home, "notes", "demo", "n-b.md"), "---\nid: n-b\ntested: true\ntested_by: bob\n---\n\nB\n");
    const r = await run(["check"], io);
    expect(r.code).toBe(1);
    expect(r.err).toContain("n-a.md: stale_after \"soon\"");
    expect(r.err).toContain("n-b.md: tested_by \"bob\"");
  });
});

describe("brain export (OKF)", () => {
  it("exports verified metadata only while body and error patterns match verification", async () => {
    const { home, io } = setup();
    const original = createNote(home, { project: "demo", text: "Verified content", errors: ["specific failure"], tested: true });
    const out = join(tmp(), "bundle");
    const cases: [Note, boolean][] = [
      [original, true],
      [{ ...original, body: "Edited content" }, false],
      [{ ...original, errors: ["different failure"] }, false],
      [{ ...original, testedSha: undefined }, true],
    ];
    for (const [note, verified] of cases) {
      saveNote(home, note);
      expect((await run(["export", out], io)).code).toBe(0);
      const text = readFileSync(join(out, "demo", `${original.id}.md`), "utf8");
      expect(text.includes("\nverified:")).toBe(verified);
      expect(text).toContain(note.body);
    }
  });

  it("writes public notes as OKF concepts with trust, lifecycle and lineage", async () => {
    const { home, io } = setup();
    const old = createNote(home, { project: "demo", kind: "gotcha", text: "Use port 8080\n\nThe proxy expects it. More detail.", evidence: ["src/server.ts", "https://example.test/doc"], tested: true, testedBy: "owner" });
    const next = createNote(home, { project: "demo", kind: "gotcha", text: "Use port 9090", staleAfter: "2027-01-01" });
    retireNote(home, old.id, next.id);
    const secret = createNote(home, { project: "demo", text: "Private detail", private: true });
    createNote(home, { project: "global", text: "Untested global fact" });
    const out = join(tmp(), "bundle");
    const r = await run(["export", out], io);
    expect(r).toMatchObject({ code: 0, out: "exported 3 notes in 2 folders (OKF 0.2); 1 private left out" });
    expect(existsSync(join(out, "demo", `${secret.id}.md`))).toBe(false);
    expect(readFileSync(join(out, "index.md"), "utf8")).toMatch(/^---\nokf_version: "0\.2"\n---\n/);
    const retired = readFileSync(join(out, "demo", `${old.id}.md`), "utf8");
    expect(retired).toMatch(/^---\ntype: "Gotcha"\ntitle: "Use port 8080"\ndescription: "The proxy expects it\."\n/);
    expect(retired).toMatch(/\nverified: \{ by: "human:owner", at: "\d{4}-[^"]+Z" \}\n/);
    expect(retired).toContain("\nstatus: deprecated\n");
    expect(retired).toContain('  - resource: "src/server.ts in the demo checkout"\n  - resource: "https://example.test/doc"\n');
    expect(retired).toContain(`Replaced by [${next.id}](/demo/${next.id}.md).`);
    const current = readFileSync(join(out, "demo", `${next.id}.md`), "utf8");
    expect(current).toContain('\nstale_after: "2027-01-01T00:00:00Z"\n');
    expect(current).not.toContain("verified:");
    expect(readFileSync(join(out, "demo", "index.md"), "utf8")).toContain(`# Gotcha\n\n* [Use port 9090](${next.id}.md)\n\n# Deprecated\n\n* [Use port 8080](${old.id}.md) - The proxy expects it.`);
  });

  it("replaces its own earlier export, never a foreign folder or the Brain home", async () => {
    const { home, io } = setup();
    const gone = createNote(home, { project: "demo", text: "Deleted between exports" });
    const out = join(tmp(), "bundle");
    await run(["export", out], io);
    expect(existsSync(join(out, "demo", `${gone.id}.md`))).toBe(true);
    rmSync(gone.path);
    createNote(home, { project: "other", text: "Other project note" });
    expect((await run(["export", out], io)).code).toBe(0);
    expect(existsSync(join(out, "demo"))).toBe(false);
    expect(existsSync(join(out, "other", "index.md"))).toBe(true);
    const foreign = tmp();
    writeFileSync(join(foreign, "keep.txt"), "mine");
    expect((await run(["export", foreign], io)).err).toContain("not empty");
    expect(readFileSync(join(foreign, "keep.txt"), "utf8")).toBe("mine");
    expect((await run(["export", join(home, "okf")], io)).err).toContain("inside the Brain home");
    expect((await run(["export", join(home, "state", "okf")], io)).code).toBe(0);
  });
});
