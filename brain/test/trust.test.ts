import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { changedEvidence, createNote, evidenceHashes, formatNote, loadNotes, markTested, parseNote, testedCurrent, upgradeNote } from "../src/notes.ts";
import { answer, recall, staleHere } from "../src/search.ts";
import { findFix, appendEvent, parseEvent, toolEventFrom } from "../src/capture.ts";
import { rankForCard } from "../src/card.ts";
import { main } from "../src/cli.ts";
import { brainTools } from "../src/tools.ts";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup() {
  const base = mkdtempSync(join(tmpdir(), "brain-trust-")); roots.push(base);
  const home = join(base, "home"), root = join(base, "repo");
  mkdirSync(home); mkdirSync(root);
  writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { demo: { paths: [root] } } }));
  const project = { id: "demo", root, tags: [] };
  const file = join(root, "source.ts"); writeFileSync(file, "original\r\n");
  const note = createNote(home, { text: "Quartz repair\nClear the quartz cache.", project: "demo", errors: ["quartz cache corrupt"], evidence: ["source.ts:1"], evidenceRoots: [root], tested: true, testedBy: "agent" });
  return { home, root, project, file, note };
}

it("brain_note replaces a corrected headline, links both notes, and rejects invalid targets before saving", async () => {
  const { home, root, note } = setup();
  const tool = brainTools.find(tool => tool.name === "brain_note")!;
  const context = { home, cwd: root, env: { BRAIN_JUDGE: "off" }, sub: false, session: "replace" };
  expect(tool.params.replaces).toMatchObject({ type: "string", optional: true });
  expect(tool.description).toContain("replaces: id of a note this corrects");
  await expect(tool.run({ text: "Missing target correction", replaces: "n-missing" }, context)).rejects.toThrow("no note n-missing");
  expect(loadNotes(home).notes).toHaveLength(1);
  const result = await tool.run({ text: "Quartz repair\nRebuild the quartz cache instead.", replaces: note.id }, context);
  const notes = loadNotes(home).notes;
  const replacement = notes.find(n => n.id !== note.id)!;
  expect(result.text).toBe(`saved ${replacement.id} (retired ${note.id})`);
  expect(replacement).toMatchObject({ body: "Quartz repair\nRebuild the quartz cache instead.", replaces: note.id });
  expect(notes.find(n => n.id === note.id)).toMatchObject({ retired: expect.any(String), replacedBy: replacement.id });
  await expect(tool.run({ text: "Already retired correction", replaces: note.id }, context)).rejects.toThrow(`${note.id} is already retired`);
  expect(loadNotes(home).notes).toHaveLength(2);
});

it("snapshots attached evidence on create/upgrade, with flat parser-compatible hashes and normalized CRLF", () => {
  const { home, root, file, note } = setup();
  const sha = createHash("sha256").update("original\n").digest("hex").slice(0, 12);
  expect(note.evidenceSha).toEqual([`source.ts=${sha}`]);
  expect(parseNote(formatNote(note), note.path, note.project, false).evidenceSha).toEqual(note.evidenceSha);
  expect(loadNotes(home).notes[0]?.testedSha).toBe(note.testedSha);
  writeFileSync(file, "original\n");
  expect(changedEvidence(note, [root])).toBe(false);
  writeFileSync(join(root, "other.ts"), "other\n");
  const upgraded = upgradeNote(home, note, { evidence: ["other.ts#L1", "https://example.com", "missing.ts"], evidenceRoots: [root] })!;
  expect(upgraded.evidenceSha).toHaveLength(2);
  expect(upgraded.evidenceSha?.[0]).toBe(note.evidenceSha?.[0]);
  expect(upgraded.evidenceSha?.[1]).toMatch(/^other\.ts=[a-f\d]{12}$/);
  expect(upgradeNote(home, upgraded, { evidence: ["other.ts#L1"], evidenceRoots: [root] })).toBeNull();
});

it("hashes file bytes without losing invalid UTF-8 and ignores unresolvable/scheme evidence", () => {
  const { root, home, note } = setup();
  const legacy = { ...note, evidenceSha: undefined };
  expect(upgradeNote(home, legacy, { evidence: ["source.ts:1"], evidenceRoots: [root] })?.evidenceSha).toEqual(note.evidenceSha);
  const bytes = Buffer.from([0xff, 0x0d, 0x0a, 0xfe]);
  writeFileSync(join(root, "binary.bin"), bytes);
  const sha = createHash("sha256").update(Buffer.from([0xff, 0x0a, 0xfe])).digest("hex").slice(0, 12);
  expect(evidenceHashes(["binary.bin", "../outside.ts", "*.ts", "events:session#1", "commit:abc", "gone.ts"], [root])).toEqual([`binary.bin=${sha}`]);
});

it("changed evidence is immediately advisory in recall/card, and only post-test changes disable fix push", () => {
  const { home, root, project, file, note } = setup();
  const verified = { ...note, testedAt: "2026-01-02T00:00:00Z" };
  writeFileSync(file, "modified\n"); utimesSync(file, new Date("2026-01-01"), new Date("2026-01-01"));
  expect(changedEvidence(verified, [root])).toBe(true);
  expect(findFix([verified], "quartz cache corrupt", project, home)).toBe(verified);
  utimesSync(file, new Date("2026-01-03"), new Date("2026-01-03"));
  expect(staleHere(verified, project, home)).toBe(true);
  expect(answer([verified], "quartz repair", { project, home })).toContain("(evidence changed)");
  expect(answer([verified], verified.id, { project, home })).toContain("(evidence changed)");
  expect(findFix([verified], "quartz cache corrupt", project, home)).toBeNull();
  const fresh = createNote(home, { text: "Fresh repair", project: "demo", kind: "gotcha", tested: true });
  expect(rankForCard([verified, fresh], project, "", new Date(), home)[0]?.id).toBe(fresh.id);
  expect(markTested(verified, "owner", [root]).evidenceSha).not.toEqual(verified.evidenceSha);
  rmSync(file);
  expect(changedEvidence(verified, [root])).toBe(false);
  expect(findFix([verified], "quartz cache corrupt", project, home)).toBe(verified);
  expect(staleHere(verified, { ...project, id: "other" }, home)).toBe(false);
});

it("tested content covers normalized body plus errors, while legacy hashes remain trusted", () => {
  const { home, root, project, note } = setup();
  expect(testedCurrent({ ...note, testedSha: undefined })).toBe(true);
  expect(testedCurrent({ ...note, body: note.body.replace(/\n/g, "\r\n  ") })).toBe(true);
  const edited = { ...note, body: note.body + "\nChanged repair." };
  expect(testedCurrent(edited)).toBe(false);
  expect(testedCurrent({ ...note, errors: ["different quartz error"] })).toBe(false);
  expect(findFix([edited], "quartz cache corrupt", project, home)).toBeNull();
  expect(answer([edited], note.id, { project, home })).toContain("(edited since tested)");
  expect(recall([edited], "quartz repair", { project, home })[0]?.note.id).toBe(note.id);
  const peer = { ...note, id: "n-peer", evidence: [], evidenceSha: [], tested: false, testedSha: undefined, kind: "gotcha" as const };
  expect(rankForCard([edited, peer], project, "", new Date(), home)[0]?.id).toBe(peer.id);
  expect(testedCurrent(markTested(edited, "owner", [root]))).toBe(true);
});

it("CLI evidence and automatic tool evidence are stamped; brain tested re-stamps an edited note", async () => {
  const { home, root, project, note } = setup();
  const out: string[] = [];
  const io = { cwd: root, env: { SECOND_BRAIN_HOME: home, BRAIN_JUDGE: "off" }, stdin: () => "", out: (s: string) => out.push(s), err: (s: string) => out.push(s) };
  expect(await main(["note", "CLI quartz repair", "--evidence", "source.ts"], io)).toBe(0);
  expect(loadNotes(home).notes.find(n => n.body === "CLI quartz repair")?.evidenceSha).toHaveLength(1);
  await brainTools.find(tool => tool.name === "brain_note")!.run({ text: "Automatic repair cites source.ts" }, { home, cwd: root, env: io.env, sub: false, session: "auto" });
  expect(loadNotes(home).notes.find(n => n.body === "Automatic repair cites source.ts")?.evidenceSha).toHaveLength(1);
  writeFileSync(note.path, readFileSync(note.path, "utf8").replace("Clear the quartz cache.", "Clear the alternate cache."));
  expect(testedCurrent(loadNotes(home).notes.find(n => n.id === note.id)!)).toBe(false);
  expect(await main(["tested", note.id], io)).toBe(0);
  const retested = loadNotes(home).notes.find(n => n.id === note.id)!;
  expect(testedCurrent(retested)).toBe(true);
  expect(findFix([retested], "quartz cache corrupt", project, home)).toBe(retested);
});

it("records full-read status from OMP and Claude Code without counting ranged reads", () => {
  const { home, root } = setup();
  expect(toolEventFrom("read", { path: "PLAN.md" }, false, []).fullRead).toBe(true);
  expect(toolEventFrom("Read", { file_path: "PLAN.md", offset: 1, limit: 20 }, false, []).fullRead).toBe(false);
  expect(toolEventFrom("read", { path: "PLAN.md:2-9" }, false, []).fullRead).toBe(false);
  appendEvent(home, "reads", root, toolEventFrom("read", { path: "PLAN.md", limit: 5 }, false, []));
  const event = parseEvent(readFileSync(join(home, "state", "events", "reads.jsonl"), "utf8"));
  expect(event?.fullRead).toBe(false);
});
