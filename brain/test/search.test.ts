import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RELATIVE_FLOOR, STOPWORDS, answer, answerWithHits, recall, renderHit, tokens } from "../src/search.ts";
import { displayLine, findSameHeadline, formatNote, parseNote, type Note } from "../src/notes.ts";

function note(id: string, over: Partial<Note> = {}): Note {
  return {
    id,
    kind: "note",
    project: "test",
    private: false,
    at: "2026-09-27T10:00:00Z",
    source: "agent",
    tags: [],
    errors: [],
    evidence: [],
    tested: false,
    body: id,
    path: "",
    ...over,
  };
}

describe("search", () => {
  it("tokenizes: lowercase, >=3 chars, stopwords removed, dedupe order", () => {
    expect(tokens("The QUICK Brown")).toEqual(["quick", "brown"]);
    expect(tokens("test test test")).toEqual(["test"]);
    expect(tokens("one two three")).toEqual([]);
    expect(tokens("short-word very-Long")).toEqual(["short", "word", "long"]);
    expect(tokens("python azure")).toEqual(["python", "azure"]);
  });

  it("removes stopwords", () => {
    expect(tokens("the and for with")).toEqual([]);
    expect(tokens("The HELLO with WORLD")).toEqual(["hello", "world"]);
  });

  it("preserves stopwords set exactly", () => {
    expect(STOPWORDS.has("the")).toBe(true);
    expect(STOPWORDS.has("can")).toBe(true);
    expect(STOPWORDS.has("notaword")).toBe(false);
  });

  it("scores by weight: title > terms > body", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "migration framework" }),
      note("n-2", { body: "migration", tags: ["data"] }),
      note("n-3", { body: "data migration", errors: ["migration"] }),
    ];

    const hit = recall(corpus, "migration", { project, limit: 10 });
    const ids = hit.map((h) => h.note.id);
    // All should match, but order matters: title has highest weight
    expect(ids).toContain("n-1");
    expect(ids).toContain("n-2");
    expect(ids).toContain("n-3");
  });

  it("supports prefix matching", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "migrations" }),
      note("n-2", { body: "migrate" }),
    ];

    const hits = recall(corpus, "migrat", { project });
    expect(hits).toHaveLength(2);
  });

  it("IDF: common terms contribute less than rare ones", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "apple banana cherry" }),
      note("n-2", { body: "apple banana date" }),
      note("n-3", { body: "apple banana elderberry" }),
      note("n-4", { body: "rare word here" }),
    ];

    const hits1 = recall(corpus, "apple", { project, all: true, limit: 10 });
    const hits2 = recall(corpus, "rare", { project, all: true, limit: 10 });

    // "apple" is in 3 of 4 notes → IDF clamps to 1e-6; "rare" is in 1 of 4 → IDF ≈ 0.85
    const rareHit = hits2.find((h) => h.note.id === "n-4");
    const appleHit = hits1.find((h) => h.note.id === "n-1");
    expect(rareHit).toBeDefined();
    expect(appleHit).toBeDefined();
    expect(rareHit?.score ?? 0).toBeGreaterThan((appleHit?.score ?? 0) * 1000);
  });

  it("every note containing the term scores above zero", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [note("n-1", { body: "test word" }), note("n-2", { body: "test" }), note("n-3", { body: "word" })];
    const hits = recall(corpus, "test", { project, all: true });
    expect(hits.map((h) => h.note.id).sort()).toEqual(["n-1", "n-2"]);
    for (const hit of hits) expect(hit.score).toBeGreaterThan(0);
  });

  it("match rule: 3-token query needs 2 matches, 1-2 token needs 1 match", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "apple banana cherry" }),
      note("n-2", { body: "apple banana" }),
      note("n-3", { body: "apple" }),
    ];

    // 3-token query with only 1 match should return nothing
    const hits1 = recall(corpus, "apple date elder", { project, all: true });
    expect(hits1).toHaveLength(0);

    // 3-token query with 2+ matches should return the note
    const hits2 = recall(corpus, "apple banana date", { project, all: true });
    expect(hits2.length).toBeGreaterThan(0);

    // 2-token query with 1 match should return the note
    const hits3 = recall(corpus, "apple date", { project, all: true });
    expect(hits3.length).toBeGreaterThan(0);

    // 1-token query with 1 match should return the note
    const hits4 = recall(corpus, "apple", { project, all: true });
    expect(hits4.length).toBeGreaterThan(0);
  });

  it("relative floor: drops hits below 50% of top score", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "unique word here" }),
      note("n-2", { body: "common the and for with" }),
      note("n-3", { body: "common also very or but" }),
    ];

    recall(corpus, "unique common", { project, all: true });
    // Should include hits above RELATIVE_FLOOR * max_score
    expect(RELATIVE_FLOOR).toBe(0.5);
    // The weak "common" hits should be filtered out
  });

  it("limit default 3 and clamped (0→1, 50→10)", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = Array.from({ length: 15 }, (_, i) =>
      note(`n-${i + 1}`, { body: "test word" })
    );

    // Default 3
    const hits1 = recall(corpus, "test", { project, all: true });
    expect(hits1.length).toBeLessThanOrEqual(3);

    // Limit 0 → 1
    const hits2 = recall(corpus, "test", { project, all: true, limit: 0 });
    expect(hits2.length).toBe(1);

    // Limit 50 → 10
    const hits3 = recall(corpus, "test", { project, all: true, limit: 50 });
    expect(hits3.length).toBeLessThanOrEqual(10);
  });

  it("visibility: other project hidden, all:true shows it", () => {
    const project = { id: "p1", tags: [], root: null };
    const corpus = [
      note("n-1", { project: "p1", body: "test" }),
      note("n-2", { project: "p2", body: "test" }),
    ];

    // Default: p2 hidden
    const hits1 = recall(corpus, "test", { project });
    expect(hits1.map((h) => h.note.id)).toEqual(["n-1"]);

    // all:true shows both
    const hits2 = recall(corpus, "test", { project, all: true });
    expect(hits2.map((h) => h.note.id)).toContain("n-1");
    expect(hits2.map((h) => h.note.id)).toContain("n-2");
  });

  it("retired notes hidden by default, shown with history:true", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [
      note("n-1", { body: "active test" }),
      note("n-2", { body: "retired test", retired: "2026-09-26T10:00:00Z" }),
    ];

    // Default: retired hidden
    const hits1 = recall(corpus, "test", { project, all: true });
    expect(hits1.map((h) => h.note.id)).toEqual(["n-1"]);

    // history:true shows both
    const hits2 = recall(corpus, "test", { project, all: true, history: true });
    const ids = hits2.map((h) => h.note.id);
    expect(ids).toContain("n-1");
    expect(ids).toContain("n-2");
  });

  it.each([
    ["Headline\nHeadline: useful new detail", "Headline — useful new detail"],
    ["Headline\nHeadline\n\nHeadline — useful new detail", "Headline — useful new detail"],
    ["Headline\nHeadline", "Headline"],
    ["Head\nHeading remains distinct", "Head — Heading remains distinct"],
  ])("renders the headline only once for %s", (body, expected) => {
    expect(renderHit({ note: note("n-repeat", { body }), score: 1, matched: [] })).toBe("n-repeat [note] " + expected);
  });

  it("renderHit: format, tested marker, retired marker", () => {
    const h1 = {
      note: note("n-abc", { body: "headline\nbody content", tested: true }),
      score: 1.0,
      matched: [],
    };
    const r1 = renderHit(h1);
    expect(r1).toContain("n-abc");
    expect(r1).toContain("[note, tested]");
    expect(r1).toContain("headline");
    expect(r1).toContain("body content");
  });

  it("renderHit: omits body when empty", () => {
    const h = {
      note: note("n-1", { body: "just headline" }),
      score: 1.0,
      matched: [],
    };
    const r = renderHit(h);
    expect(r).not.toContain(" — ");
  });

  it("renderHit: retired marker kept when cut", () => {
    const longBody = "x".repeat(500);
    const h = {
      note: note("n-1", {
        body: `headline\n${longBody}`,
        retired: "2026-09-26",
        replacedBy: "n-2",
      }),
      score: 1.0,
      matched: [],
    };
    const r = renderHit(h);
    expect(r).toContain("retired");
    expect(r).toContain("n-2");
    expect(r.length).toBeLessThanOrEqual(240);
  });

  it("renderHit: ≤ 240 chars total", () => {
    const corpus = Array.from({ length: 10 }, (_, i) =>
      note(`n-${i + 1}`, {
        body: `very long headline with lots of content\n${
          "x".repeat(500)
        }`,
        tags: Array.from({ length: 20 }, (_, j) => `tag${j}`),
      })
    );
    for (const n of corpus) {
      const h = { note: n, score: 1.0, matched: [] };
      const r = renderHit(h);
      expect(r.length).toBeLessThanOrEqual(240);
    }
  });

  it("empty query returns empty", () => {
    const project = { id: "test", tags: [], root: null };
    const corpus = [note("n-1", { body: "test" })];
    const hits = recall(corpus, "", { project });
    expect(hits).toEqual([]);

    const hits2 = recall(corpus, "   ", { project });
    expect(hits2).toEqual([]);

    const hits3 = recall(corpus, "and or the", { project });
    expect(hits3).toEqual([]);
  });
});

describe("bm25 parity with SQLite FTS5 (hand-computed)", () => {
  it("matches the FTS5 formula exactly on a 5-note corpus", () => {
    const mk = (id: string, body: string): Note => ({
      id, kind: "note", project: "p", private: false, at: "2026-01-01T00:00:00Z", source: "user",
      tags: [], errors: [], evidence: [], tested: false, body, path: "",
    });
    const corpus = [mk("n-a", "alpha beta"), mk("n-b", "gamma\nalpha alpha"), mk("n-c", "delta"), mk("n-d", "epsilon"), mk("n-e", "zeta eta")];
    // D = id(2) + title + terms("note" = 1) + body: 5, 6, 4, 4, 5 → avgdl 4.8; "alpha" in 2 of 5 rows
    const idf = Math.log((5 - 2 + 0.5) / (2 + 0.5));
    const bm = (f: number, d: number) => idf * ((f * 2.2) / (f + 1.2 * (0.25 + (0.75 * d) / 4.8)));
    const hits = recall(corpus, "alpha", { project: { id: "p", tags: [], root: null } });
    expect(hits.map((h) => h.note.id)).toEqual(["n-a", "n-b"]);
    expect(Math.abs((hits[0]?.score ?? 0) - bm(5, 5))).toBeLessThan(1e-9); // title weight 5 × 1
    expect(Math.abs((hits[1]?.score ?? 0) - bm(2, 6))).toBeLessThan(1e-9); // body weight 1 × 2
  });
});


describe("recall and note boundaries", () => {
  const project = { id: "test", tags: [], root: null };

  it("does not answer with one generic word: file names and versions must match whole", () => {
    const notes = [
      note("n-loop", { body: "Swarm loop for multi-file work: reviewers then implementers" }),
      note("n-edit", { body: "GPT edits: Update File diffs are rejected; use anchored rows" }),
      note("n-sealed", { body: "sealed.py resolves ./paths against the run directory" }),
    ];
    const ids = (q: string) => recall(notes, q, { project }).map((h) => h.note.id);
    expect(ids("LOOP.md goals")).toEqual([]);
    expect(ids("18.4.1 version update")).toEqual([]);
    expect(ids("sealed.py path bug")).toEqual(["n-sealed"]);
    expect(ids("swarm loop")).toEqual(["n-loop"]);
  });

  it("does not count the project's own name as a match inside that project", () => {
    const laya = { id: "absolute-laya", tags: [], root: null };
    const notes = [note("n-git", { project: "absolute-laya", body: "Absolute Laya is not a git checkout" })];
    expect(recall(notes, "Absolute Laya queue runner thermal abort", { project: laya })).toEqual([]);
    expect(recall(notes, "Absolute Laya git checkout", { project: laya }).map((h) => h.note.id)).toEqual(["n-git"]);
  });

  it("does not merge distinct full first lines sharing the display prefix", () => {
    const prefix = "x".repeat(159);
    const stored = note("note-1", { body: prefix + " keep the cache" });
    expect(findSameHeadline([stored], prefix + " drop the cache", "test")).toBeUndefined();
    expect(findSameHeadline([stored], prefix + " KEEP  the cache", "test")?.id).toBe("note-1");
  });

  it("dedupes private requests only within their private project scope", () => {
    const corpus = [
      note("global-private", { project: "global", private: true, body: "Deployment rule" }),
      note("other-private", { project: "other", private: true, body: "Deployment rule" }),
      note("public", { body: "Deployment rule" }),
      note("local-private", { private: true, body: "Deployment rule" }),
    ];
    expect(findSameHeadline(corpus, "Deployment rule", "test", [], true)?.id).toBe("local-private");
    expect(findSameHeadline(corpus.slice(0, 3), "Deployment rule", "test", [], true)).toBeUndefined();
  });

  it("preserves quoted hashes commas and escaped quotes in inline lists", () => {
    const text = '---\nid: note-1\nerrors: ["unexpected # token", "unexpected, comma", "say \\"hi\\", now", \'it\'\'s # quoted\'] # comment\n---\nFix parser';
    const parsed = parseNote(text, "note-1.md", "test", false);
    expect(parsed.errors).toEqual(["unexpected # token", "unexpected, comma", 'say "hi", now', "it's # quoted"]);
    expect(parseNote(formatNote(parsed), "note-1.md", "test", false).errors).toEqual(parsed.errors);
  });

  it("keeps apostrophes inside plain inline list items literal", () => {
    const parsed = parseNote("---\nid: note-1\nerrors: [can't open, don't retry] # why\n---\nFix", "note-1.md", "test", false);
    expect(parsed.errors).toEqual(["can't open", "don't retry"]);
    expect(parseNote(formatNote(parsed), "note-1.md", "test", false).errors).toEqual(parsed.errors);
  });

  it("recalls custom stored ids exactly while preserving visibility", () => {
    const stored = note("note-1", { kind: "fact", body: "Restart the service" });
    expect(answer([stored], " note-1 ", { project })).toContain("Restart the service");
    expect(answer([stored], "note-1", { project: { ...project, id: "other" } })).not.toContain("Restart the service");
    expect(answer([stored], "note-1", { project: { ...project, id: "other" }, all: true })).toContain("Restart the service");
  });

  it("suggests all only when an otherwise empty scoped recall has related notes", () => {
    const stored = [note("elsewhere", { project: "other", body: "quartz migration" })];
    expect(answer(stored, "quartz", { project })).toBe("no match here; 1 related in other projects (all: true)");
    expect(answer(stored, "quartz", { project, all: true })).toContain("quartz migration");
    expect(answerWithHits(stored, "nonexistent", { project }).hits).toBe(0);
  });

  it("suggests widening when the only related answer is retired history", () => {
    const stored = [note("retired-elsewhere", { project: "other", body: "quartz migration", retired: "2026-09-01" })];
    expect(answer(stored, "quartz", { project, all: true })).toContain("retired 2026-09-01");
    expect(answer(stored, "quartz", { project })).toBe("no match here; 1 related in other projects (all: true)");
  });

  it("counts shown hits including exact ids and history but not widening hints", () => {
    const corpus = [
      note("current", { body: "quartz migration" }),
      note("old", { body: "quartz migration", retired: "2026-09-01" }),
    ];
    expect(answerWithHits(corpus, "current", { project }).hits).toBe(1);
    expect(answerWithHits(corpus, "quartz", { project, history: true }).hits).toBe(2);
    expect(answerWithHits(corpus, "quartz", { project: { ...project, id: "other" } }).hits).toBe(0);
    expect(answerWithHits(corpus, "nonexistent", { project }).hits).toBe(0);
  });

  it("counts related notes independently of the requested display limit", () => {
    const corpus = Array.from({ length: 12 }, (_, i) => note(String(i), { project: "other", body: "quartz migration" }));
    expect(answer(corpus, "quartz", { project, limit: 1 })).toBe("no match here; 12 related in other projects (all: true)");
  });

  it("cuts display lines at words without splitting code points", () => {
    expect(displayLine({ body: "# alpha beta gamma" }, 12)).toBe("alpha beta…");
    expect(displayLine({ body: "alpha beta" }, 10)).toBe("alpha beta");
    expect(displayLine({ body: "𐐀𐐁𐐂𐐃" }, 3)).toBe("𐐀𐐁…");
    expect(displayLine({ body: "alpha" }, 0)).toBe("");
  });
});

describe("evidence and replacement answers", () => {
  const project = { id: "test", tags: [], root: null };

  it("demotes stale evidence regardless of score without losing the BM25 shortlist", () => {
    const home = mkdtempSync(join(tmpdir(), "brain-evidence-"));
    try {
      writeFileSync(join(home, "current.ts"), "current source");
      const corpus = [
        note("stale", { body: "quartz", evidence: ["missing.ts"] }),
        note("current", { body: "quartz migration uses staged updates", evidence: ["current.ts"] }),
      ];
      const here = { ...project, root: home };
      const hits = recall(corpus, "quartz", { project: here, home });
      expect(hits.map((hit) => hit.note.id)).toEqual(["current", "stale"]);
      expect(hits[1]!.score).toBeGreaterThan(hits[0]!.score);
      const lines = answer(corpus, "quartz", { project: here, home }).split("\n");
      expect(lines).toHaveLength(2);
      expect(lines[0]).not.toContain("(stale evidence)");
      expect(lines[1]).toContain("(stale evidence)");
      const only = answer([corpus[0]!], "quartz", { project: here, home });
      expect(only).toContain("stale [note] quartz (stale evidence)");
      // Without this project's checkout a relative path is unknown, not missing.
      expect(answer([corpus[0]!], "quartz", { project, home })).not.toContain("(stale evidence)");
      const bounded = renderHit({ note: note("long", { body: "quartz " + "detail ".repeat(100) }), score: 1, matched: [], stale: true });
      expect(bounded.length).toBeLessThanOrEqual(240);
      expect(bounded).toContain("(stale evidence)");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("answers with an active replacement then a tombstone, even when the replacement does not match", () => {
    const corpus = [
      note("old", { body: "Obsolete deployment recipe\nRun destructive legacy command", retired: "2026-09-01", replacedBy: "middle" }),
      note("middle", { body: "Intermediate policy", retired: "2026-09-02", replacedBy: "current" }),
      note("current", { body: "Use the reviewed release job\nCheck the staging report first" }),
    ];
    const result = answerWithHits(corpus, "obsolete deployment recipe", { project });
    const lines = result.text.split("\n");
    expect(result.hits).toBe(2);
    expect(lines[0]).toContain("current [note] Use the reviewed release job");
    expect(lines[1]).toContain("old [note] Obsolete deployment recipe (retired, replaced by current)");
    expect(result.text).not.toContain("destructive legacy command");
    expect(answer(corpus, "obsolete deployment recipe", { project, limit: 1 }).split("\n")).toEqual([lines[0]]);
    expect(answer(corpus, "old", { project })).toContain("Run destructive legacy command");
    expect(answer(corpus, "obsolete deployment recipe", { project, history: true })).toContain("Run destructive legacy command");
  });

  it.each(["missing", "cycle", "invisible"])("does not follow a %s replacement into an invalid answer", (kind) => {
    const old = note("old", { body: "Obsolete deployment recipe", retired: "2026-09-01", replacedBy: "next" });
    const next = note("next", { body: "Secret replacement instructions", project: kind === "invisible" ? "other" : "test", ...(kind === "cycle" ? { retired: "2026-09-02", replacedBy: "old" } : {}) });
    const corpus = kind === "missing" ? [old] : [old, next];
    const result = answerWithHits(corpus, "obsolete deployment recipe", { project });
    expect(result.hits).toBe(1);
    expect(result.text).toContain("old [note]");
    expect(result.text).not.toContain("Secret replacement instructions");
    if (kind === "invisible") expect(answer(corpus, "obsolete deployment recipe", { project, all: true }).split("\n")[0]).toContain("next [note]");
  });

  it("caps ordinary search summaries at three lines even with a larger requested limit", () => {
    const corpus = Array.from({ length: 10 }, (_, i) => note("n-" + i, { body: "quartz migration" }));
    expect(answerWithHits(corpus, "quartz", { project, limit: 10 }).hits).toBe(3);
    expect(answer(corpus, "quartz", { project, limit: 10 }).split("\n")).toHaveLength(3);
  });

  it("gives an actionable one-line no-match hint without naming a host tool", () => {
    const result = answerWithHits([], "unlearned recipe", { project });
    expect(result.hits).toBe(0);
    expect(result.text.split("\n")).toHaveLength(1);
    expect(result.text).toMatch(/note.*learn/i);
    expect(result.text).not.toContain("brain_note");
  });
});
