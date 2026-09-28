/**
 * Recall quality on the frozen V3 S2 case sets, against the real converted notes.
 * V3 (SQLite FTS5) scored dev 13/15 and held-out 7/8 in the top 3; V4 must not regress.
 * The misses V3 had: the retired 2-worker-cap policy (correctly not current) and one long prompt.
 */
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { loadNotes } from "../src/notes.ts";
import { answer, answerWithHits, recall } from "../src/search.ts";
import { judgedAnswer, type Judge } from "../src/judge.ts";
import { PACKAGE_HOME } from "../src/util.ts";
import { loadProjects } from "../src/project.ts";

interface Case {
  id: string;
  prompt: string;
  expect: string[];
  forbid?: string[];
}

function cases(name: string): Case[] {
  const text = readFileSync(join(import.meta.dirname, "fixtures", name), "utf8");
  return text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l) as Case);
}

const hasNotes = existsSync(join(PACKAGE_HOME, "notes", "second-brain"));
const project = { id: "second-brain", tags: [], root: null };

function score(set: Case[]): { hits: number; total: number; missed: string[] } {
  const { notes } = loadNotes(PACKAGE_HOME);
  const memory = set.filter((c) => c.expect.length);
  const missed: string[] = [];
  for (const c of memory) {
    const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
    if (!c.expect.some((id) => ids.includes(id))) missed.push(c.id);
  }
  return { hits: memory.length - missed.length, total: memory.length, missed };
}

describe.skipIf(!hasNotes)("recall eval on the frozen S2 cases", () => {
  it("dev: at least 13 of 15 memory cases in the top 3", () => {
    const result = score(cases("recall-dev.jsonl"));
    console.log(`dev ${result.hits}/${result.total} missed ${result.missed.join(",")}`);
    expect(result.total).toBe(15);
    expect(result.hits).toBeGreaterThanOrEqual(13);
  });

  it("held-out: at least 7 of 8 memory cases in the top 3", () => {
    const result = score(cases("recall-heldout.jsonl"));
    console.log(`held-out ${result.hits}/${result.total} missed ${result.missed.join(",")}`);
    expect(result.total).toBe(8);
    expect(result.hits).toBeGreaterThanOrEqual(7);
  });

  it("what the agent sees (answer, with retired history): dev >= 14/15, held-out 8/8", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    for (const [file, min] of [["recall-dev.jsonl", 14], ["recall-heldout.jsonl", 8]] as const) {
      const memory = cases(file).filter((c) => c.expect.length);
      const found = memory.filter((c) => c.expect.some((id) => answer(notes, c.prompt, { project }).includes(id)));
      console.log(`answer ${file}: ${found.length}/${memory.length}`);
      expect(found.length).toBeGreaterThanOrEqual(min);
    }
  });

  it("never returns a forbidden note: other projects' notes, archived duplicates", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    const guarded = [...cases("recall-dev.jsonl"), ...cases("recall-heldout.jsonl")].filter((c) => c.forbid?.length);
    expect(guarded.length).toBeGreaterThan(0);
    for (const c of guarded) {
      const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
      expect(ids.filter((id) => c.forbid?.includes(id)), c.id).toEqual([]);
    }
  });

  it("answers in at most 3 lines and stays fast on the whole corpus", () => {
    const { notes } = loadNotes(PACKAGE_HOME);
    const started = performance.now();
    for (const c of cases("recall-dev.jsonl")) expect(recall(notes, c.prompt, { project }).length).toBeLessThanOrEqual(3);
    const perQuery = (performance.now() - started) / 28;
    console.log(`recall ${perQuery.toFixed(1)} ms/query over ${notes.length} notes`);
    expect(perQuery).toBeLessThan(50);
  });
});

interface RealCase {
  id: string;
  project: string;
  query: string;
  expect: string[];
  verdict: "note" | "silence";
  doc?: string;
}
function answeredDoc(text: string): string | undefined {
  return /^([^\n]+) › [^\n]+ \(line [1-9]\d*\)$/.exec(text)?.[1];
}

it("grades only a single heading line naming the hinted document as a doc answer", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-eval-doc-"));
  try {
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { test: { docs: ["PLAN.md"] } } }));
    writeFileSync(join(home, "PLAN.md"), "# Quartz migration\nStage the update.\n");
    const text = answer([], "quartz migration", { project: { id: "test", tags: [], root: home }, home });
    expect(answeredDoc(text)).toBe("PLAN.md");
    expect(answeredDoc(text)).not.toBe("OTHER.md");
    expect(answeredDoc(text + "\nUnrelated answer")).toBeUndefined();
    expect(answeredDoc(answer([], "unknown topic", { project: null }))).toBeUndefined();
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

describe.skipIf(!hasNotes)("real queries", () => {
  // The first recording and three reruns of the same pairs: Jev drifts about ±0.02 between runs,
  // so "0 wrong" must hold on every run, not on one lucky recording.
  const runs = [
    JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-judge.json"), "utf8")) as Record<string, Record<string, number>>,
    ...(JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-judge-reruns.json"), "utf8")) as Record<string, Record<string, number>>[]),
  ];
  // The labels judged the notes that existed when the pools were built: a note written later was
  // never judged, so it must not change this score (or fail the gate for want of a recording).
  const LABELLED_AT = "2026-09-28T14:12:00Z";
  const notes = loadNotes(PACKAGE_HOME).notes.filter(note => note.at <= LABELLED_AT);
  const projects = loadProjects(PACKAGE_HOME);

  function recordedJudge(recordings: Record<string, Record<string, number>>, caseId: string, shown: string[]): Judge {
    // Assert outside the fail-open boundary: a missing recording must fail the test, not return lexical results.
    for (const id of shown.filter(id => notes.some(note => note.id === id && !note.private))) {
      const p = recordings[caseId]?.[id];
      expect(typeof p, `missing recorded pair ${caseId}/${id}`).toBe("number");
      expect(p, `invalid recorded pair ${caseId}/${id}`).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThanOrEqual(1);
    }
    return async (_query, candidates) => new Map(candidates.map(c => [c.id, recordings[caseId]![c.id]!]));
  }

  for (const [file, size, lexicalRight, lexicalWrong, judgedRight] of [
    ["recall-real.jsonl", 34, 6, 8, 5],
    ["recall-real-heldout.jsonl", 20, 2, 4, 2],
  ] as const) {
    for (const judged of [false, true]) it(`${judged ? "judged (every recorded run)" : "lexical"}: ${file} retains right answers and bounds wrong answers`, async () => {
     for (const recordings of judged ? runs : [undefined]) {
      const set = readFileSync(join(import.meta.dirname, "fixtures", file), "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line) as RealCase);
      let right = 0, miss = 0, silence = 0;
      const wrong: string[] = [];
      for (const c of set) {
        const project = { id: c.project, tags: [], root: projects[c.project]?.paths?.find(path => existsSync(path)) ?? null };
        for (const id of c.expect) expect(notes.some(note => note.id === id && !note.retired && !note.private), `${c.id}: ${id}`).toBe(true);
        const opts = { project, home: PACKAGE_HOME };
        const lexical = answerWithHits(notes, c.query, opts);
        const result = recordings ? await judgedAnswer(notes, c.query, opts, recordedJudge(recordings, c.id, lexical.ids)) : lexical;
        const ids = result.ids.filter(id => !id.startsWith("doc:"));
        if (ids.some(id => !c.expect.includes(id))) wrong.push(`${c.id}: ${ids.join(",")}`);
        else if (ids.length) right++;
        else if (c.doc && answeredDoc(result.text) === c.doc) right++;
        else if (c.expect.length) miss++;
        else silence++;
      }
      console.log(`${judged ? "judged" : "lexical"} ${file}: right ${right}/${set.length}; wrong ${wrong.length}; miss ${miss}; silence ${silence}; wrong cases ${wrong.join("; ")}`);
      expect(set).toHaveLength(size);
      expect(right).toBeGreaterThanOrEqual(judged ? judgedRight : lexicalRight);
      // Majority-of-3 blind labels, frozen 2026-09-28: lexical 6/8 and held-out 2/4 right/wrong.
      if (judged) expect(wrong).toEqual([]);
      else expect(wrong.length).toBeLessThanOrEqual(lexicalWrong);
     }
    });
  }

  it("recorded judge retains V3 dev >= 12/15 and held-out >= 7/8 on every run", async () => {
    // Owner approved 2026-09-28 lowering the judged dev gate 13→12: D27 'How do I clear PYTHONHOME?'
    // scores 0.45, D28 'migration' about 0.75-0.78. The lexical V3 gates above are unchanged.
    for (const recordings of runs) {
      for (const [file, min, total] of [["recall-dev.jsonl", 12, 15], ["recall-heldout.jsonl", 7, 8]] as const) {
        const memory = cases(file).filter(c => c.expect.length);
        const missed: string[] = [];
        for (const c of memory) {
          const lexical = answerWithHits(notes, c.prompt, { project });
          const result = await judgedAnswer(notes, c.prompt, { project }, recordedJudge(recordings, `v3:${c.id}`, lexical.ids));
          if (!c.expect.some(id => result.ids.includes(id))) missed.push(c.id);
        }
        console.log(`judged V3 ${file}: ${memory.length - missed.length}/${memory.length}; missed ${missed.join(",")}`);
        expect(memory).toHaveLength(total);
        expect(memory.length - missed.length).toBeGreaterThanOrEqual(min);
      }
    }
  });
});
