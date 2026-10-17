/**
 * Recall quality on the frozen V3 S2 case sets, against the real converted notes.
 * V3 (SQLite FTS5) scored dev 13/15 and held-out 7/8 in the top 3; V4 must not regress.
 * The misses V3 had: the retired 2-worker-cap policy (correctly not current) and one long prompt.
 */
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Note } from "../src/notes.ts";
import { answer, answerWithHits, recall, type AnswerOptions } from "../src/search.ts";
import { JEV_CHARS, judgedAnswer, onJevScale, type Answer, type JudgeName } from "../src/judge.ts";
import { toraPost, toraSession } from "../src/tora.ts";
import { projectById, resolveProject } from "../src/project.ts";

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

// The complete pre-curation corpus keeps historical competition and score gates stable.
const historicalNotes = JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-v3-corpus.json"), "utf8")) as Note[];
const project = { id: "second-brain", tags: [], root: null };

function score(set: Case[]): { hits: number; total: number; missed: string[] } {
  const notes = historicalNotes;
  const memory = set.filter((c) => c.expect.length);
  const missed: string[] = [];
  for (const c of memory) {
    const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
    if (!c.expect.some((id) => ids.includes(id))) missed.push(c.id);
  }
  return { hits: memory.length - missed.length, total: memory.length, missed };
}

describe("recall eval on the frozen S2 cases", () => {
  it("retains the complete pre-curation public corpus, not just expected positives", () => {
    expect(historicalNotes).toHaveLength(520);
    expect(new Set(historicalNotes.map(note => note.id)).size).toBe(520);
    expect(historicalNotes.some(note => note.private)).toBe(false);
    expect(historicalNotes.every(note => note.path === "")).toBe(true);
    expect(new Set(historicalNotes.map(note => note.project)).size).toBeGreaterThan(10);
  });

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
    const notes = historicalNotes;
    for (const [file, min] of [["recall-dev.jsonl", 14], ["recall-heldout.jsonl", 8]] as const) {
      const memory = cases(file).filter((c) => c.expect.length);
      const found = memory.filter((c) => c.expect.some((id) => answer(notes, c.prompt, { project }).includes(id)));
      console.log(`answer ${file}: ${found.length}/${memory.length}`);
      expect(found.length).toBeGreaterThanOrEqual(min);
    }
  });

  it("never returns a forbidden note: other projects' notes, archived duplicates", () => {
    const notes = historicalNotes;
    const guarded = [...cases("recall-dev.jsonl"), ...cases("recall-heldout.jsonl")].filter((c) => c.forbid?.length);
    expect(guarded.length).toBeGreaterThan(0);
    for (const c of guarded) {
      const ids = recall(notes, c.prompt, { project }).map((h) => h.note.id);
      expect(ids.filter((id) => c.forbid?.includes(id)), c.id).toEqual([]);
    }
  });

  it("answers in at most 3 lines and stays fast on the whole corpus", () => {
    const notes = historicalNotes;
    const started = performance.now();
    for (const c of cases("recall-dev.jsonl")) expect(recall(notes, c.prompt, { project }).length).toBeLessThanOrEqual(3);
    const perQuery = (performance.now() - started) / 28;
    console.log(`recall ${perQuery.toFixed(1)} ms/query over ${notes.length} notes`);
    expect(perQuery).toBeLessThan(50);
  });
});

it("resolves a temporary m worktree through its registered main checkout, not its pre-split remote", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-scope-"));
  try {
    const main = join(home, "frame-generation");
    const linked = join(home, "temporary", "m");
    const gitdir = join(main, ".git", "worktrees", "m");
    mkdirSync(gitdir, { recursive: true });
    mkdirSync(linked, { recursive: true });
    writeFileSync(join(linked, ".git"), `gitdir: ${gitdir.replace(/\\/g, "/")}\n`);
    writeFileSync(join(gitdir, "commondir"), "../..\n");
    writeFileSync(join(main, ".git", "config"), '[remote "origin"]\nurl = https://github.com/example/basicupscaler.git\n');
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: {
      "basicupscaler-frame-gen": { paths: [main], tags: ["capture"] },
      basicupscaler: { remote: "https://github.com/example/basicupscaler.git" },
    } }));
    expect(resolveProject(home, linked, {})).toMatchObject({ id: "basicupscaler-frame-gen", root: linked, tags: ["capture"] });
    expect(projectById(home, "m", home).id).toBe("m");
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

interface RealCase {
  id: string;
  project: string;
  query: string;
  expect: string[];
  verdict: "note" | "silence";
}
interface DocLabel {
  caseId: string;
  id: string;
  answer: string;
  votes: boolean[];
  right: boolean;
  recordings: number[];
  textSha256: string;
}

function grade(c: Pick<RealCase, "id" | "expect">, result: Pick<Answer, "ids" | "text">, labels: DocLabel[]): "right" | "wrong" | "miss" | "silence" {
  if (result.ids.some(id => id.startsWith("doc:")
    ? !labels.some(label => label.caseId === c.id && label.id === id && result.text.split("\n").includes(label.answer) && label.right)
    : !c.expect.includes(id))) return "wrong";
  return result.ids.length ? "right" : c.expect.length ? "miss" : "silence";
}

/** Live Tora's cosines (2026-10-15) for every note the judged path asks it about, frozen so the eval stays deterministic. */
const toraCosines = JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-tora.json"), "utf8")) as Record<string, Record<string, number>>;

/**
 * One recorded judge run: per case, the verdict for every candidate the judged path sent. Jev runs
 * hold probabilities; Tora runs hold the reranker's raw scores, put on Jev's scale by onJevScale
 * exactly as the live judge does. `live` (recording only) asks a running Tora for pairs and stores them.
 */
interface Run {
  name: string;
  judge: JudgeName;
  scores: Record<string, Record<string, number>>;
  live?: (query: string, candidates: { id: string; text: string }[]) => Promise<Map<string, number> | undefined>;
}

async function replay(notes: Note[], query: string, opts: AnswerOptions, run: Run, caseId: string, labels: DocLabel[] = []): Promise<Answer> {
  const sent: { id: string; text: string }[] = [];
  const scored: string[] = [];
  const result = await judgedAnswer(notes, query, opts, async (judgedQuery, candidates) => {
    sent.push(...candidates);
    const found = await run.live?.(judgedQuery, candidates);
    if (found) for (const c of candidates) (run.scores[caseId] ??= {})[c.id] = found.get(c.id)!;
    return new Map(candidates.map(c => {
      const p = run.scores[caseId]?.[c.id];
      return [c.id, p !== undefined && run.judge === "tora" ? onJevScale(p) : p!];
    }));
  }, async (_query, pool) => {
    scored.push(...pool.map(n => n.id));
    return { scores: new Map(pool.map(n => [n.id, toraCosines[caseId]?.[n.id]!])), ms: 0 };
  });
  // Outside the fail-open boundary, and over actual requests (including conditional fallbacks).
  for (const id of scored) expect(typeof toraCosines[caseId]?.[id], `missing Tora cosine ${caseId}/${id}`).toBe("number");
  for (const { id, text } of sent) {
    const p = run.scores[caseId]?.[id];
    expect(typeof p, `missing recorded pair ${run.name} ${caseId}/${id}`).toBe("number");
    expect(p, `invalid recorded pair ${caseId}/${id}`).toBeGreaterThanOrEqual(0);
    expect(p).toBeLessThanOrEqual(1);
    if (id.startsWith("doc:")) {
      // Labels hash the text Jev read; Tora reads further into the same frozen document.
      const label = labels.find(label => label.caseId === caseId && label.id === id);
      expect(label?.textSha256, `changed document candidate ${caseId}/${id}`).toBe(createHash("sha256").update(text.slice(0, JEV_CHARS)).digest("hex"));
    }
  }
  return result;
}

it("counts unlabelled or irrelevant document headings as wrong, even on silence cases", () => {
  const c = { id: "case", expect: [] };
  const result = { ids: ["doc:PLAN.md"], text: "PLAN.md › Quartz migration (line 1)" };
  const label: DocLabel = { caseId: c.id, id: result.ids[0]!, answer: result.text, votes: [true, true, false], right: true, recordings: [], textSha256: "" };
  expect(grade(c, result, [])).toBe("wrong");
  expect(grade(c, result, [{ ...label, right: false }])).toBe("wrong");
  expect(grade(c, result, [label])).toBe("right");
  expect(grade(c, { ...result, text: "PLAN.md › Unrelated section (line 8)" }, [label])).toBe("wrong");
  expect(grade(c, { ...result, ids: [...result.ids, "irrelevant-note"] }, [label])).toBe("wrong");
  expect(grade({ ...c, expect: ["relevant-note"] }, { ids: [...result.ids, "relevant-note"], text: result.text + "\nrelevant-note [note] Useful advice" }, [label])).toBe("right");
});

it("fails missing document recordings outside runtime fail-open, including after note rejection", async () => {
  const home = mkdtempSync(join(tmpdir(), "brain-eval-doc-"));
  try {
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { test: { docs: ["PLAN.md"] } } }));
    writeFileSync(join(home, "PLAN.md"), "# Quartz migration\nStage the update.\n");
    const opts = { project: { id: "test", tags: [], root: home }, home };
    const note: Note = { id: "note", kind: "note", project: "test", private: false, at: "2026-09-28", source: "agent", tags: [], errors: [], evidence: [], tested: false, body: "Quartz migration guidance", path: "" };
    await expect(replay([], "quartz migration", opts, { name: "test", judge: "jev", scores: {} }, "case")).rejects.toThrow();
    await expect(replay([note], "quartz migration", opts, { name: "test", judge: "jev", scores: { case: { note: 0.1 } } }, "case")).rejects.toThrow();
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

describe("real queries", () => {
  // The first recording and three reruns of the same pairs: Jev drifts about ±0.02 between runs,
  // so "0 wrong" must hold on every run, not on one lucky recording.
  const jevRuns: Run[] = [
    JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-judge.json"), "utf8")) as Record<string, Record<string, number>>,
    ...(JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-judge-reruns.json"), "utf8")) as Record<string, Record<string, number>>[]),
  ].map((scores, i) => ({ name: `jev ${i}`, judge: "jev" as const, scores }));
  // Tora's reranker (Qwen3-Reranker-0.6B Q8_0, IDEAS TJ-02) through Tora's own /judge, on the GPU and
  // on the CPU (their scores differ by up to ~0.09 mid-range). Re-record against a live Tora started
  // with that --device: BRAIN_EVAL_RECORD_TORA=gpu npx vitest run test/eval.test.ts
  const toraFile = join(import.meta.dirname, "fixtures", "recall-judge-tora.json");
  const toraJudged = JSON.parse(readFileSync(toraFile, "utf8")) as { protocol: string; model: string; recordedAt: Record<string, string>; runs: Record<string, Record<string, Record<string, number>>> };
  const recording = process.env.BRAIN_EVAL_RECORD_TORA;
  if (recording) {
    const session = toraSession({ LOCALAPPDATA: process.env.LOCALAPPDATA });
    if (!session) throw new Error("BRAIN_EVAL_RECORD_TORA needs a live Tora session");
    toraJudged.runs[recording] = {};
    toraJudged.recordedAt[recording] = new Date().toISOString();
  }
  const toraRuns: Run[] = Object.entries(toraJudged.runs).map(([device, scores]) => ({
    name: `tora ${device}`, judge: "tora" as const, scores,
    ...(device === recording ? { live: async (query: string, candidates: { id: string; text: string }[]) => (await toraPost(toraSession({ LOCALAPPDATA: process.env.LOCALAPPDATA })!, "/judge", query, candidates, 120_000))?.scores } : {}),
  }));
  const runs = [...jevRuns, ...toraRuns];
  if (recording) vi.setConfig({ testTimeout: 900_000 });
  beforeEach(() => { if (recording) vi.unstubAllGlobals(); });
  afterAll(() => { if (recording) writeFileSync(toraFile, JSON.stringify(toraJudged, null, 1) + "\n"); });
  // The labels judged the notes that existed when the pools were built: a note written later was
  // never judged, so it must not change this score (or fail the gate for want of a recording).
  const LABELLED_AT = "2026-09-28T14:12:00Z";
  const notes = historicalNotes.filter(note => note.at <= LABELLED_AT);
  const frozen = JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-documents.json"), "utf8")) as { projects: Record<string, { docs: Record<string, string> }> };
  const documentJudgments: { labels: DocLabel[] } = JSON.parse(readFileSync(join(import.meta.dirname, "fixtures", "recall-document-judge.json"), "utf8"));
  const labels = documentJudgments.labels;
  for (const label of labels) {
    expect(label.votes).toHaveLength(3);
    expect(label.right).toBe(label.votes.filter(Boolean).length >= 2);
    expect(label.recordings).toHaveLength(jevRuns.length);
    jevRuns.forEach((run, i) => { (run.scores[label.caseId] ??= {})[label.id] = label.recordings[i]!; });
  }
  let home: string;
  beforeAll(() => {
    home = mkdtempSync(join(tmpdir(), "brain-eval-frozen-"));
    const projects: Record<string, { docs: string[] }> = {};
    for (const [id, project] of Object.entries(frozen.projects)) {
      projects[id] = { docs: Object.keys(project.docs) };
      for (const [path, text] of Object.entries(project.docs)) {
        const file = join(home, "repos", id, path);
        mkdirSync(dirname(file), { recursive: true });
        writeFileSync(file, text);
      }
    }
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects }));
  });
  afterAll(() => { if (home) rmSync(home, { recursive: true, force: true }); });

  // Judged held-out 5: H04 is answered only through Tora's second look at BM25's top three (frozen cosines).
  // Tora's reranker (owner, 15 Oct: the default judge, Jev only as its fallback) is worse than Jev
  // on this hand-labelled set and better on 276 blind-labelled October candidates (Tora IDEAS TJ-02).
  // Its gate is what it measured: right answers kept, and no wrong answer beyond the known ones,
  // each a note on the query's topic that does not answer it.
  for (const [file, size, lexicalRight, lexicalWrong, judgedRight, toraRight, toraWrong] of [
    ["recall-real.jsonl", 34, 15, 8, 7, 2, ["R27", "R33"]],
    ["recall-real-heldout.jsonl", 20, 10, 6, 5, 6, ["H07"]],
  ] as const) {
    for (const judged of [false, true]) it(`${judged ? "judged (every recorded run)" : "lexical"}: ${file} retains right answers and bounds wrong answers`, async () => {
     for (const run of judged ? runs : [undefined]) {
      const set = readFileSync(join(import.meta.dirname, "fixtures", file), "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line) as RealCase);
      let right = 0, miss = 0, silence = 0;
      const wrong: string[] = [];
      for (const c of set) {
        const project = { id: c.project, tags: [], root: frozen.projects[c.project] ? join(home, "repos", c.project) : null };
        for (const id of c.expect) expect(notes.some(note => note.id === id && !note.retired && !note.private), `${c.id}: ${id}`).toBe(true);
        const opts = { project, home };
        const result = run ? await replay(notes, c.query, opts, run, c.id, labels) : answerWithHits(notes, c.query, opts);
        const outcome = grade(c, result, labels);
        if (outcome === "wrong") wrong.push(c.id);
        else if (outcome === "right") right++;
        else if (outcome === "miss") miss++;
        else silence++;
      }
      console.log(`${run ? `judged (${run.name})` : "lexical"} ${file}: right ${right}/${set.length}; wrong ${wrong.length}; miss ${miss}; silence ${silence}; wrong cases ${wrong.join("; ")}`);
      expect(set).toHaveLength(size);
      // Soft: every run is graded (and, when recording, every pair recorded) before the test fails.
      expect.soft(right, run?.name).toBeGreaterThanOrEqual(!run ? lexicalRight : run.judge === "tora" ? toraRight : judgedRight);
      // Note labels are frozen at 2026-09-28; blind document-section labels include two
      // additional wrong lexical headings in held-out. Every Jev-judged answer must be right.
      if (run) expect.soft(wrong.filter(id => run.judge === "jev" || !(toraWrong as readonly string[]).includes(id)), run.name).toEqual([]);
      else expect(wrong.length).toBeLessThanOrEqual(lexicalWrong);
     }
    });
  }

  it("recorded judge retains V3 dev >= 12/15 (Tora 10) and held-out >= 7/8 on every run", async () => {
    // Owner approved 2026-09-28 lowering the judged dev gate 13→12: D27 'How do I clear PYTHONHOME?'
    // scores 0.45, D28 'migration' about 0.75-0.78. The lexical V3 gates above are unchanged.
    // Tora's reranker measured 10/15 (owner chose it as the default, 15 Oct).
    for (const run of runs) {
      for (const [file, min, total] of [["recall-dev.jsonl", run.judge === "tora" ? 10 : 12, 15], ["recall-heldout.jsonl", 7, 8]] as const) {
        const memory = cases(file).filter(c => c.expect.length);
        const missed: string[] = [];
        for (const c of memory) {
          const result = await replay(notes, c.prompt, { project }, run, `v3:${c.id}`);
          if (!c.expect.some(id => result.ids.includes(id))) missed.push(c.id);
        }
        console.log(`judged (${run.name}) V3 ${file}: ${memory.length - missed.length}/${memory.length}; missed ${missed.join(",")}`);
        expect(memory).toHaveLength(total);
        expect.soft(memory.length - missed.length, run.name).toBeGreaterThanOrEqual(min);
      }
    }
  });
});
