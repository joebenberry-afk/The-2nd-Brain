/**
 * Unit tests for the in-host quiet precheck (`src/quiet-precheck.ts`).
 *
 * The contract under test is one-directional: `skip` may only be returned when
 * the Python pipeline provably cannot contribute a model-visible message, and
 * every ambiguous, unreadable or unknown input resolves to `run`. The parity
 * test (`tests/test_quiet_precheck_parity.py`) is the end-to-end safety net
 * against the real Python decision; these tests pin each rule and its failure
 * modes.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  loadQuietPrecheckEnabled,
  precheckQuiet,
  queryCandidates,
  quietQueryText,
  QUIET_ECHO_MAX_CHARS,
  QUIET_STOPWORD_TOKENS,
} from "../src/quiet-precheck";
import { quietCorpusMemories, writeQuietCorpus, type QuietMemory } from "./quiet-corpus-fixture";

const SESSION = "2026-01-01T00-00-00-000Z_quiet";
let home: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "sb-quiet-"));
});

afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

const sessionPath = (...parts: string[]): string => join(home, "state", "sessions", SESSION, ...parts);

function writeCapsule(content: Record<string, unknown>): void {
  mkdirSync(sessionPath(), { recursive: true });
  writeFileSync(sessionPath("active-state.json"), JSON.stringify(content), "utf8");
}

/**
 * The canonical capsule `working_set._load_capsule` accepts (`CAPSULE_FIELDS` +
 * `_validate_capsule_fields`), so the capsule half of the precheck can be tested
 * independently of the schema check itself.
 */
function canonicalCapsule(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    objective: "runtime state ledger",
    task_mode: "STANDARD",
    risk: "MEDIUM",
    constraints: [],
    confirmed_facts: [],
    current_hypotheses: [],
    decisions_this_session: [],
    files_touched: [],
    open_questions: [],
    verification: {},
    next_action: "",
    brain_refs: [],
    artifact_refs: [],
    updated_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

function writeVmem(rows: number, garbage = false): void {
  mkdirSync(sessionPath(), { recursive: true });
  if (garbage) {
    writeFileSync(sessionPath("ledger.sqlite"), "not a database", "utf8");
    return;
  }
  const db = new DatabaseSync(sessionPath("ledger.sqlite"));
  db.exec(
    "CREATE TABLE IF NOT EXISTS session_vmem (obj_id TEXT PRIMARY KEY, internal_session_id TEXT, " +
      "kind TEXT, title TEXT, summary TEXT, residency_state TEXT)",
  );
  db.exec("DELETE FROM session_vmem");
  const insert = db.prepare(
    "INSERT INTO session_vmem (obj_id, internal_session_id, kind, title, summary, residency_state) VALUES (?, ?, 'RAW', 't', 's', 'RESIDENT')",
  );
  for (let index = 0; index < rows; index += 1) insert.run(`obj-${index}`, SESSION);
  db.close();
}

function decide(prompt: string, session = SESSION) {
  return precheckQuiet({ home, session, prompt });
}

describe("quiet precheck tokenization", () => {
  it("tokens are ASCII, 3+ chars, stopword-free and deduped in first-seen order", () => {
    const candidates = queryCandidates(
      "Rename the local variable tmp to buffer in this snippet: tmp = 1; print(tmp)",
    );
    expect(candidates).toEqual(["rename", "local", "variable", "tmp", "buffer", "snippet", "print"]);
    for (const token of candidates) {
      expect(token).toMatch(/^[a-z0-9]{3,}$/u);
      expect(QUIET_STOPWORD_TOKENS[token]).toBeUndefined();
    }
  });

  it("declines non-ASCII text exactly like Python's _query_candidates", () => {
    expect(queryCandidates("summarize the café notes")).toEqual([]);
    expect(quietQueryText("résumé review")).toBeUndefined();
  });

  it("returns undefined for an empty prompt and for a 512-cut that lands on whitespace", () => {
    expect(quietQueryText("   ")).toBeUndefined();
    // A clean 512-cut (no whitespace at the boundary) is the retrieval text.
    const long = "runtime-state-ledger-".repeat(30);
    const cut = quietQueryText(long);
    expect(cut).toHaveLength(QUIET_ECHO_MAX_CHARS);
    expect(long.startsWith(cut as string)).toBe(true);
    expect(cut).not.toMatch(/\s$/u);
    // 511 chars + " tail": the cut keeps the space, so the capsule objective
    // would not reproduce the host's echo string — the precheck must not skip.
    expect(quietQueryText(`${"a".repeat(QUIET_ECHO_MAX_CHARS - 1)} tail`)).toBeUndefined();
  });

  it("honors the env kill switch", () => {
    expect(loadQuietPrecheckEnabled({})).toBe(true);
    for (const value of ["0", "false", "no", "off", "current", " OFF "]) {
      expect(loadQuietPrecheckEnabled({ SECOND_BRAIN_QUIET_PRECHECK: value })).toBe(false);
    }
    expect(loadQuietPrecheckEnabled({ SECOND_BRAIN_QUIET_PRECHECK: "1" })).toBe(true);
  });
});

describe("quiet precheck run reasons", () => {
  it("runs without a resolvable corpus or session", () => {
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "db_unavailable",
    });
    writeQuietCorpus(home, quietCorpusMemories());
    expect(precheckQuiet({ home, session: "../escape", prompt: "runtime state ledger" })).toMatchObject(
      { decision: "run", reason: "invalid_session" },
    );
    expect(precheckQuiet({ home: "", session: SESSION, prompt: "runtime state ledger" })).toMatchObject(
      { decision: "run", reason: "invalid_session" },
    );
  });

  it("runs on prompt shapes Python cannot answer lexically", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("")).toMatchObject({ decision: "run", reason: "empty_prompt" });
    expect(decide("   ")).toMatchObject({ decision: "run", reason: "empty_prompt" });
    expect(decide("Résumé du paragraphe")).toMatchObject({
      decision: "run",
      reason: "non_ascii_prompt",
    });
    expect(decide("it is a to be or not")).toMatchObject({
      decision: "run",
      reason: "no_candidates",
    });
    expect(decide("What does mem-a8d221e64549 say about migrations?")).toMatchObject({
      decision: "run",
      reason: "exact_ref",
    });
    expect(decide("a8d221e64549")).toMatchObject({ decision: "run", reason: "exact_ref" });
    expect(decide(`${"a".repeat(QUIET_ECHO_MAX_CHARS - 1)} tail`)).toMatchObject({
      decision: "run",
      reason: "echo_boundary",
    });
    // The same prompt cut cleanly is tokenized on the 512-char retrieval text.
    expect(decide("runtime-state-ledger-".repeat(30))).toMatchObject({ decision: "skip" });
  });

  it("an unbuilt or unknown index always runs (a termless plan lets every row through)", () => {
    expect(decide("runtime state ledger")).toMatchObject({ decision: "run" }); // no db at all
    writeQuietCorpus(home, []);
    expect(decide("runtime state ledger")).toMatchObject({ decision: "run", reason: "empty_index" });
    // memories without any FTS row: retrieval would fall back to the linear scan
    const db = new DatabaseSync(join(home, "db", "brain.sqlite"));
    db.prepare("INSERT INTO memories (memory_id, title, summary) VALUES ('mem-1', 'note', 's')").run();
    db.close();
    expect(decide("runtime state ledger")).toMatchObject({ decision: "run", reason: "empty_index" });
  });

  it("runs when no candidate exists in the vocabulary", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("translate 'good morning' into French")).toMatchObject({
      decision: "run",
      reason: "no_vocab_terms",
    });
  });

  it("runs when two near-unique terms land on one retrievable row", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-rare1", title: "note rare", summary: "s", body: "zephyr quokka sighting" },
    ]);
    expect(decide("zephyr quokka")).toMatchObject({ decision: "run", reason: "unique_terms" });
  });

  it("two rare terms on different rows are not a coincidence", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-rare1", title: "note rare", summary: "s", body: "zephyr sighting" },
      { id: "mem-rare2", title: "note rare two", summary: "s", body: "quokka sighting" },
    ]);
    // Python's rule needs >= 2 near-unique matches on the SAME row.
    expect(decide("zephyr quokka")).toMatchObject({ decision: "skip" });
  });

  it("runs when a specific term is confirmed by a memory headline", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-k8s1", title: "kubernetes rollout", summary: "s" },
      { id: "mem-k8s2", title: "kubernetes ingress", summary: "s" },
      { id: "mem-k8s3", title: "kubernetes secrets", summary: "s" },
    ]);
    expect(decide("kubernetes runtime")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
    // The same term without any headline occurrence stays skippable evidence-wise
    // for the headline rule (it is ubiquitous here, so rule 3 applies instead).
    expect(decide("zephyr runtime")).toMatchObject({ decision: "skip" });
  });

  it("runs when a ubiquitous term is confirmed by a memory headline", () => {
    const memories: QuietMemory[] = quietCorpusMemories().map((memory) => ({
      ...memory,
      title: `brain ${memory.title}`,
    }));
    writeQuietCorpus(home, memories);
    // "brain" is ubiquitous here and appears in every headline, while "runtime"
    // is shared by every body, so the whole plan is undiscriminating.
    expect(decide("brain runtime")).toMatchObject({ decision: "run", reason: "ubiquitous_headline" });
    // A question makes a focused retry possible, so the exact-plan tightening
    // must not be relied on and the conservative rule applies.
    expect(decide("how does brain runtime behave?")).toMatchObject({
      decision: "run",
      reason: "ubiquitous_headline",
    });
  });

  it("a specific plan term blocks the ubiquity rule", () => {
    // "kubernetes" is specific and has NO headline hit, but it is part of the
    // plan, so not every plan term can be ubiquitous and Python's rule 3 is
    // disabled while rule 1 has no confirmation either.
    writeQuietCorpus(
      home,
      quietCorpusMemories(30).concat([
        { id: "mem-k8s", title: "note extra", summary: "s", body: "runtime state ledger kubernetes" },
      ]),
    );
    expect(decide("runtime state kubernetes")).toMatchObject({ decision: "skip" });
  });

  it("a mid-word headline coincidence is not a confirmation", () => {
    // "file" is specific and appears inside the word "profiles", which Python's
    // token-prefix rule does not count.
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-mode", title: "centralised profiles", summary: "s", body: "runtime state ledger" },
    ]);
    expect(decide("file runtime state")).toMatchObject({ decision: "skip" });
  });

  it("a headline token prefix is a confirmation", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-file", title: "file profiles", summary: "s", body: "runtime state ledger" },
    ]);
    expect(decide("file runtime state")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
  });

  /**
   * Review counterexample: the focused retry's plan is an unknown subset of the
   * ORIGINAL candidates, and `_plan_with_stats` skips its vocabulary filter only
   * for a single-candidate query. "kubernet" is absent from the FTS vocabulary
   * (the corpus stores "kubernetes"), so a focused attempt built from the
   * vocabulary-filtered terms searches just the common words and skips a row
   * Python confirms through the headline.
   */
  it("keeps vocabulary-filtered prefixes available to the focused retry", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-k8s", title: "kubernetes rollout", summary: "s" },
    ]);
    // No request sentence, so no focused retry exists: the out-of-vocabulary
    // prefix is not part of the plan and the common words carry no headline.
    expect(decide("runtime state ledger kubernet")).toMatchObject({ decision: "skip" });
    // A request sentence focuses to "What is kubernet?" — one candidate, which
    // Python searches as the prefix `"kubernet"*` against the real headline.
    expect(decide("runtime state ledger. What is kubernet?")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
    // The same focus through the vocabulary the corpus actually stores needs no
    // widening, and keeps deciding exactly as before.
    expect(decide("runtime state ledger. What is kubernetes?")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
  });

  /**
   * Review counterexample: Python matches on `str.casefold()` text, whose full
   * folding turns "Straße" into "strasse" — a headline confirmation
   * `toLowerCase()` cannot reproduce. A RETRIEVED row whose text is not ASCII
   * must answer `run` instead of being judged, because Python confirms that
   * headline and injects.
   */
  it("runs for a retrieved row whose text Python casefolds asymmetrically", () => {
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-umlaut", title: "Straße rollout", summary: "s", body: "strasse sign" },
    ]);
    const result = decide("strasse");
    expect(result).toMatchObject({ decision: "run", reason: "non_ascii_row" });
    expect(result.detail.total_documents).toBe(41);

    // The same memory with an ASCII headline is judged on its merits, and both
    // sides agree: the rare headline term is a specific confirmation.
    rmSync(join(home, "db", "brain.sqlite"));
    writeQuietCorpus(home, [
      ...quietCorpusMemories(),
      { id: "mem-ascii", title: "strasse rollout", summary: "s", body: "runtime state ledger" },
    ]);
    expect(decide("strasse")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
  });

  it("runs when the corpus schema is not the expected one", () => {
    mkdirSync(join(home, "db"), { recursive: true });
    const db = new DatabaseSync(join(home, "db", "brain.sqlite"));
    db.exec("CREATE TABLE memories (memory_id TEXT PRIMARY KEY, title TEXT, summary TEXT)");
    db.close();
    expect(decide("runtime state ledger")).toMatchObject({ decision: "run", reason: "schema_unknown" });
    writeFileSync(join(home, "db", "brain.sqlite"), "not a database either", "utf8");
    expect(decide("runtime state ledger").decision).toBe("run");
  });
});

describe("quiet precheck capsule and vmem conditions", () => {
  it("skips only when the capsule would render as a pure echo", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip", reason: "no_evidence" });

    writeCapsule(
      canonicalCapsule({ decisions_this_session: ["we chose the batched path"] }),
    );
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "capsule_content",
    });

    writeCapsule(canonicalCapsule({ open_questions: ["why"] }));
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "capsule_content",
    });

    writeCapsule(canonicalCapsule());
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });

    // Unknown extra fields are not part of the canonical schema Python checks,
    // so they must not cost a spawn either.
    writeCapsule(canonicalCapsule({ future_field: "x" }));
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });

    writeFileSync(sessionPath("active-state.json"), "{not json", "utf8");
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "capsule_unreadable",
    });
    writeFileSync(sessionPath("active-state.json"), JSON.stringify({ objective: "x" }), "utf8");
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "capsule_unreadable",
    });
  });

  /**
   * Review counterexample: an existing capsule Python REJECTS makes
   * `ensure_capsule` fail, and AutoInject then retrieves with the FULL task text
   * instead of the 512-char objective this module models. Any such capsule must
   * answer `run`, never `skip`.
   */
  it("runs for every capsule shape working_set._load_capsule rejects", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    const rejected: unknown[] = [
      [], // not a JSON object at all
      { decisions_this_session: [], open_questions: [] }, // missing required fields
      canonicalCapsule({ task_mode: "PLAN" }), // not in TASK_MODES
      canonicalCapsule({ risk: "low" }), // not in RISK_LEVELS
      canonicalCapsule({ task_mode: 7 }),
      canonicalCapsule({ objective: "   " }), // objective must be non-empty
      canonicalCapsule({ objective: null }),
      canonicalCapsule({ constraints: "not a list" }),
      canonicalCapsule({ open_questions: [1] }), // list items must be strings
      canonicalCapsule({ decisions_this_session: "nope" }),
      canonicalCapsule({ verification: [] }), // must be an object
      canonicalCapsule({ verification: { key: ["nested"] } }), // values must be scalars
      canonicalCapsule({ next_action: null }), // must be a string
      canonicalCapsule({ updated_at: "" }), // must be non-empty
      canonicalCapsule({ updated_at: 7 }),
    ];
    for (const capsule of rejected) {
      mkdirSync(sessionPath(), { recursive: true });
      writeFileSync(sessionPath("active-state.json"), JSON.stringify(capsule), "utf8");
      const result = decide("runtime state ledger");
      expect(result, JSON.stringify(capsule)).toMatchObject({
        decision: "run",
        reason: "capsule_unreadable",
      });
      expect(result.detail.capsule).toBe("unreadable");
    }
    // Every task mode and risk level Python accepts stays a valid capsule.
    for (const mode of ["MICRO", "STANDARD", "DEBUG", "HANDOFF"]) {
      writeFileSync(
        sessionPath("active-state.json"),
        JSON.stringify(canonicalCapsule({ task_mode: mode, risk: "CRITICAL" })),
        "utf8",
      );
      expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });
    }
  });

  it("skips only when the session has no VMem objects", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    writeVmem(0);
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });
    writeVmem(2);
    expect(decide("runtime state ledger")).toMatchObject({ decision: "run", reason: "vmem_objects" });
    writeVmem(0, true);
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "vmem_unreadable",
    });
  });

  it("finds the session state in the hashed directory too", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    const hashed = join(
      home,
      "state",
      "sessions",
      // ledger.internal_session_id: sha256 hex of the host session id
      "de1b1f6d1d9a6c1c5eb3f2a2d34c3c0face6d5b0eb1dd3f2b6e0b3c9f0a1d2e3",
    );
    mkdirSync(hashed, { recursive: true });
    const db = new DatabaseSync(join(hashed, "ledger.sqlite"));
    db.exec(
      "CREATE TABLE session_vmem (obj_id TEXT PRIMARY KEY, internal_session_id TEXT, kind TEXT, title TEXT, summary TEXT, residency_state TEXT)",
    );
    db.close();
    // an existing but empty vmem table is not evidence of a render
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });
  });
});

describe("quiet precheck database freshness", () => {
  it("reuses its read-only connection yet sees a corpus written afterwards", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("kubernetes runtime")).toMatchObject({ decision: "skip" });

    const db = new DatabaseSync(join(home, "db", "brain.sqlite"));
    db.prepare(
      "INSERT INTO memories (memory_id, title, summary) VALUES ('mem-new', 'kubernetes rollout', 's')",
    ).run();
    db.prepare(
      "INSERT INTO memory_fts (memory_id, title, summary, body) VALUES ('mem-new', 'kubernetes rollout', 's', '')",
    ).run();
    db.close();

    expect(decide("kubernetes runtime")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
  });

  it("treats a replaced database file as a new corpus", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("runtime state ledger")).toMatchObject({ decision: "skip" });
    rmSync(join(home, "db", "brain.sqlite"));
    expect(decide("runtime state ledger")).toMatchObject({
      decision: "run",
      reason: "db_unavailable",
    });
    writeQuietCorpus(home, quietCorpusMemories(30).concat([
      { id: "mem-k8s", title: "kubernetes note", summary: "s" },
    ]));
    expect(decide("kubernetes runtime")).toMatchObject({
      decision: "run",
      reason: "specific_headline",
    });
  });
});

describe("quiet precheck skip details", () => {
  it("reports counts only — never prompt text, terms or ids", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    const result = decide("runtime state ledger");
    expect(result).toEqual({
      decision: "skip",
      reason: "no_evidence",
      detail: {
        candidates: 3,
        vocab_terms: 3,
        unique_terms: 0,
        headline_terms: 0,
        ubiquitous_headline_terms: 0,
        capsule: "missing",
        vmem_objects: 0,
        total_documents: 40,
      },
    });
    expect(JSON.stringify(result)).not.toContain("runtime");
  });

  it("skips a single candidate that has no trace in the corpus", () => {
    writeQuietCorpus(home, quietCorpusMemories());
    expect(decide("zephyrr")).toMatchObject({ decision: "skip" });
    expect(decide("ze")).toMatchObject({ decision: "run", reason: "no_candidates" });
  });
});
