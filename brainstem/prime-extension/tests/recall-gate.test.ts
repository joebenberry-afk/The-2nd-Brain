/**
 * Phase 14 recall gate — pure decision/format tests + bounded spawn test
 * (execFile mocked; no real CLI ever runs).
 */
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ execFile: execFileMock }));
import {
  BRIEF_HEADER,
  BRIEF_MAX_WORDS,
  RECALL_DEFAULT_MAX_ROWS,
  RECALL_DEFAULT_MAX_TERMS,
  RECALL_DEFAULT_MIN_CHARS,
  RECALL_DEFAULT_TIMEOUT_MS,
  buildBrainBrief,
  buildRecallQuery,
  loadRecallGateConfig,
  parseRecallRows,
  runBrainRecall,
  shouldAttemptRecall,
  statusLabel,
} from "../src/recall-gate";

const SUBSTANTIAL =
  "the sqlite migration failed on the second run with a schema version mismatch and now the upgrade is blocked"; // >= 40 chars, >= 8 words

const ENV_KEYS = [
  "SECOND_BRAIN_RECALL",
  "SECOND_BRAIN_RECALL_MAX_ROWS",
  "SECOND_BRAIN_RECALL_MIN_CHARS",
  "SECOND_BRAIN_RECALL_TIMEOUT_MS",
  "SECOND_BRAIN_RECALL_MAX_TERMS",
] as const;
const SAVED: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const key of ENV_KEYS) {
    SAVED[key] = process.env[key];
    delete process.env[key];
  }
  vi.restoreAllMocks();
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (SAVED[key] === undefined) delete process.env[key];
    else process.env[key] = SAVED[key] as string;
  }
});

describe("loadRecallGateConfig", () => {
  it("defaults to OFF with sensible bounds", () => {
    const cfg = loadRecallGateConfig({});
    expect(cfg).toEqual({
      enabled: false,
      maxRows: RECALL_DEFAULT_MAX_ROWS,
      minChars: RECALL_DEFAULT_MIN_CHARS,
      timeoutMs: RECALL_DEFAULT_TIMEOUT_MS,
      maxQueryTerms: RECALL_DEFAULT_MAX_TERMS,
    });
  });

  it("enables on 1/true/yes case-insensitively", () => {
    for (const value of ["1", "true", "TRUE", "yes", "Yes"]) {
      expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL: value }).enabled).toBe(true);
    }
    for (const value of ["0", "false", "no", "on", "enabled", "", "  "]) {
      expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL: value }).enabled).toBe(false);
    }
  });

  it("parses max_rows/min_chars/timeout with fallback on invalid values", () => {
    expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_MAX_ROWS: "5" }).maxRows).toBe(5);
    expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_MIN_CHARS: "10" }).minChars).toBe(10);
    expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_TIMEOUT_MS: "250" }).timeoutMs).toBe(250);
    for (const bad of ["abc", "-1", "1.5", "   "]) {
      expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_MAX_ROWS: bad }).maxRows).toBe(RECALL_DEFAULT_MAX_ROWS);
      expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_MIN_CHARS: bad }).minChars).toBe(RECALL_DEFAULT_MIN_CHARS);
      expect(loadRecallGateConfig({ SECOND_BRAIN_RECALL_TIMEOUT_MS: bad }).timeoutMs).toBe(RECALL_DEFAULT_TIMEOUT_MS);
    }
  });
});

describe("buildRecallQuery (bounded keywords for the CLI)", () => {
  const cfg = loadRecallGateConfig({ SECOND_BRAIN_RECALL: "1" });

  it("selects content keywords instead of the raw prompt", () => {
    const prompt =
      "We keep hitting the writer admission problem: the previous worker left the lease held " +
      "and the successor was refused with WORKTREE_WRITER_BUSY, so please explain what to do next";
    const query = buildRecallQuery(prompt, cfg);

    expect(query).toBeDefined();
    expect(query).not.toContain("please");
    expect(query?.split(" ")).toHaveLength(RECALL_DEFAULT_MAX_TERMS);
    expect(query).toContain("writer");
    expect(query).toContain("admission");
    // The CLI tokenizes on ASCII alphanumerics; the query must match that shape.
    for (const term of query?.split(" ") ?? []) {
      expect(term).toMatch(/^[a-z0-9]{3,}$/);
    }
  });

  it("drops fenced code, inline code and URLs", () => {
    const prompt = [
      "Explain why the retrieval budget behaves like this:",
      "```sql",
      "SELECT secretcolumn FROM memory_fts WHERE zebra = 1;",
      "```",
      "see https://example.invalid/zebra/documents for the background",
      "and the `zebra_marker` inline snippet",
      "the ranking of candidate memories is wrong",
    ].join("\n");

    const query = buildRecallQuery(prompt, cfg);

    expect(query).toBeDefined();
    expect(query).not.toContain("zebra");
    expect(query).toContain("retrieval");
  });

  it("returns undefined when fewer than two usable terms remain", () => {
    expect(buildRecallQuery("the and to of it", cfg)).toBeUndefined();
    expect(buildRecallQuery("please fix", cfg)).toBeUndefined();
    expect(buildRecallQuery("", cfg)).toBeUndefined();
    expect(buildRecallQuery("```\nSELECT zebra FROM memory_fts\n```", cfg)).toBeUndefined();
  });

  it("honors maxQueryTerms and is deterministic", () => {
    const prompt = "alpha bravo charlie delta echo foxtrot golf hotel india juliet";

    expect(buildRecallQuery(prompt, { ...cfg, maxQueryTerms: 2 })).toBe("alpha bravo");
    expect(buildRecallQuery(prompt, cfg)).toBe(buildRecallQuery(prompt, cfg));
    expect(buildRecallQuery(prompt, cfg)?.split(" ")).toHaveLength(RECALL_DEFAULT_MAX_TERMS);
  });

  it("skips repeated tokens", () => {
    expect(buildRecallQuery("worktree worktree worktree lease lease budget", cfg)).toBe(
      "worktree lease budget",
    );
  });
});

describe("shouldAttemptRecall (gate matrix)", () => {
  const off = loadRecallGateConfig({});
  const on = loadRecallGateConfig({ SECOND_BRAIN_RECALL: "1" });
  const tiny = loadRecallGateConfig({ SECOND_BRAIN_RECALL: "1", SECOND_BRAIN_RECALL_MIN_CHARS: "10" });

  it("disabled default -> false for anything", () => {
    expect(shouldAttemptRecall(SUBSTANTIAL, off)).toBe(false);
    expect(shouldAttemptRecall(undefined, off)).toBe(false);
  });

  it("enabled + undefined/blank -> false", () => {
    expect(shouldAttemptRecall(undefined, on)).toBe(false);
    expect(shouldAttemptRecall(null as unknown as string, on)).toBe(false);
    expect(shouldAttemptRecall("   ", on)).toBe(false);
    expect(shouldAttemptRecall("", on)).toBe(false);
  });

  it("enabled + short (< min chars) -> false", () => {
    expect(shouldAttemptRecall("short query", on)).toBe(false);
    // under a lowered min chars but still >= 8 words -> allowed
    expect(shouldAttemptRecall("this query has eight words or more in total", tiny)).toBe(true);
  });

  it("enabled + fewer than 8 words -> false (independent of min chars)", () => {
    expect(shouldAttemptRecall("one two three four five", on)).toBe(false);
    expect(shouldAttemptRecall("one two three four five six seven", tiny)).toBe(false); // 7 words, low min
    expect(shouldAttemptRecall("one two three four five six seven eight", tiny)).toBe(true); // 8 words
  });

  it("enabled + greeting/acknowledgement -> false even when long", () => {
    const greeting =
      "hello there, thanks for the previous explanation and help with everything you have done so far today"; // long but greeting-led
    expect(shouldAttemptRecall(greeting, on)).toBe(false);
    expect(shouldAttemptRecall("Hi, could you please help me with the sqlite migration issue we discussed yesterday morning", on)).toBe(false);
  });

  it("enabled + continuation/CLI-ish start -> false", () => {
    expect(shouldAttemptRecall("/compact then continue with the sqlite migration fix and rerun the full test suite", on)).toBe(false);
    expect(shouldAttemptRecall("git status shows the working tree is dirty and the migration file is missing", on)).toBe(false);
    expect(shouldAttemptRecall("continue the sqlite migration work from where we left off", on)).toBe(false);
  });

  it("enabled + substantial -> true (deterministic)", () => {
    expect(shouldAttemptRecall(SUBSTANTIAL, on)).toBe(true);
    expect(shouldAttemptRecall(SUBSTANTIAL, on)).toBe(true);
    expect(shouldAttemptRecall(SUBSTANTIAL, tiny)).toBe(true);
  });
});

describe("statusLabel", () => {
  it("maps current/superseded exactly and everything else to uncertain", () => {
    expect(statusLabel("current")).toBe("current");
    expect(statusLabel("CURRENT")).toBe("current");
    expect(statusLabel("superseded")).toBe("superseded");
    expect(statusLabel("candidate")).toBe("uncertain");
    expect(statusLabel("archived")).toBe("uncertain");
    expect(statusLabel(undefined)).toBeUndefined();
  });
});

describe("buildBrainBrief", () => {
  it("builds labeled bullets with title/summary/grade/project/id", () => {
    const brief = buildBrainBrief([
      {
        memory_id: "mem-1",
        title: "sqlite migration failure recovery",
        summary: "verify schema version before rerunning",
        status: "current",
        evidence_grade: "VERIFIED",
        project_id: "brain",
      },
    ]);
    expect(brief).toBeDefined();
    expect(brief!.startsWith(BRIEF_HEADER)).toBe(true);
    expect(brief).toContain("**sqlite migration failure recovery**");
    expect(brief).toContain("(current)");
    expect(brief).toContain("verify schema version before rerunning");
    expect(brief).toContain("grade=VERIFIED");
    expect(brief).toContain("project=brain");
    expect(brief).toContain("`mem-1`");
  });

  it("labels superseded and unknown statuses", () => {
    const brief = buildBrainBrief([
      { title: "old approach", status: "superseded", grade: "INFERRED" },
      { title: "new approach", status: "candidate" },
    ]);
    expect(brief).toContain("(superseded)");
    expect(brief).toContain("(uncertain)");
  });

  it("caps at 3 rows by default and honors maxRows", () => {
    const rows = [1, 2, 3, 4, 5].map((n) => ({ title: `row ${n}`, status: "current" }));
    const brief = buildBrainBrief(rows)!;
    expect(brief.split("\n").filter((l) => l.startsWith("- "))).toHaveLength(RECALL_DEFAULT_MAX_ROWS);
    expect(buildBrainBrief(rows, 1)!.split("\n").filter((l) => l.startsWith("- "))).toHaveLength(1);
  });

  it("skips rows without a usable title; returns undefined when none valid", () => {
    const brief = buildBrainBrief([
      { summary: "no title here" },
      { title: "   " },
      null,
      "nonsense",
    ]);
    expect(brief).toBeUndefined();
    expect(buildBrainBrief([{ title: "ok", status: "current" }, { summary: "no title" }])).toContain("**ok**");
  });

  it("returns undefined for non-array input", () => {
    expect(buildBrainBrief(undefined)).toBeUndefined();
    expect(buildBrainBrief(null)).toBeUndefined();
    expect(buildBrainBrief("nope" as unknown as unknown[])).toBeUndefined();
  });

  it("respects the word cap (drops rows that would exceed it)", () => {
    const rows = [
      { title: "first row with several words in the title and a long summary here" }, // 14 words
      { title: "second row" }, // 3 words
    ];
    // first row fits (14 <= 16), adding the second would exceed -> exactly 1 row
    expect(buildBrainBrief(rows, 3, 16)!.split("\n").filter((l) => l.startsWith("- "))).toHaveLength(1);
    // cap smaller than the first row -> no valid line -> undefined
    expect(buildBrainBrief(rows, 3, 10)).toBeUndefined();
  });

  it("never exceeds BRIEF_MAX_WORDS by default", () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({
      title: `memory number ${i}`,
      summary: "a moderately long one-line summary with many words".repeat(3),
      status: "current",
    }));
    const brief = buildBrainBrief(rows)!;
    expect(brief.split(/\s+/).length).toBeLessThanOrEqual(BRIEF_MAX_WORDS);
  });
});

describe("parseRecallRows", () => {
  it("accepts a JSON array (forward-compatible --json)", () => {
    const rows = [
      { memory_id: "mem-1", title: "t", status: "current", summary: "s" },
      { memory_id: "mem-2", title: "u", status: "superseded" },
    ];
    expect(parseRecallRows(JSON.stringify(rows))).toEqual(rows);
  });

  it("parses the documented CLI text format", () => {
    const stdout = [
      "mem-ecf9c3209bb0  [candidate/VERIFIED] sqlite migration failure recovery",
      "mem-0d311ea11369  [current/TESTED] frontend build checklist",
      "",
      "Conflicting prior evidence:",
      "  mem-x <-> mem-y  (title)",
    ].join("\n");
    const rows = parseRecallRows(stdout);
    expect(rows).toEqual([
      { memory_id: "mem-ecf9c3209bb0", status: "candidate", evidence_grade: "VERIFIED", title: "sqlite migration failure recovery" },
      { memory_id: "mem-0d311ea11369", status: "current", evidence_grade: "TESTED", title: "frontend build checklist" },
    ]);
  });

  it("handles empty/no-match/garbage output as []", () => {
    expect(parseRecallRows("")).toEqual([]);
    expect(parseRecallRows("   ")).toEqual([]);
    expect(parseRecallRows(undefined)).toEqual([]);
    expect(parseRecallRows(null)).toEqual([]);
    expect(parseRecallRows("No matching memories.\n")).toEqual([]);
    expect(parseRecallRows("total garbage that is not json or rows")).toEqual([]);
    expect(parseRecallRows('{"not":"an array"}')).toEqual([]);
  });
});

describe("runBrainRecall (execFile mocked)", () => {
  beforeEach(() => {
    execFileMock.mockReset();
  });

  it("spawns python -m second_brain memory search with cleaned env, cwd=home, timeout", async () => {
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(null, "mem-1  [current/VERIFIED] some title\n", "");
    });
    const rows = await runBrainRecall({
      home: "C:/brain",
      query: "sqlite migration failure",
      cfg: loadRecallGateConfig({ SECOND_BRAIN_RECALL: "1", SECOND_BRAIN_RECALL_TIMEOUT_MS: "123" }),
      env: { PYTHONHOME: "junk", PYTHONPATH: "junk2", FOO: "bar" },
    });
    expect(rows).toEqual([
      { memory_id: "mem-1", status: "current", evidence_grade: "VERIFIED", title: "some title" },
    ]);
    expect(execFileMock).toHaveBeenCalledTimes(1);
    const [py, args, opts] = execFileMock.mock.calls[0];
    expect(py).toBe(join("C:/brain", ".venv", "Scripts", "python.exe"));
    expect(args).toEqual(["-m", "second_brain", "memory", "search", "sqlite migration failure"]);
    expect(opts.cwd).toBe("C:/brain");
    expect(opts.timeout).toBe(123);
    expect(opts.env.PYTHONHOME).toBeUndefined();
    expect(opts.env.PYTHONPATH).toBeUndefined();
    expect(opts.env.SECOND_BRAIN_HOME).toBe("C:/brain");
    expect(opts.env.FOO).toBe("bar");
  });

  it("resolves [] on spawn error (e.g. missing python) and on timeout", async () => {
    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(Object.assign(new Error("spawn ENOENT"), { code: "ENOENT" }), "", "");
    });
    expect(await runBrainRecall({ home: "C:/brain", query: "q", cfg: loadRecallGateConfig({}) })).toEqual([]);

    execFileMock.mockImplementation((_py, _args, _opts, cb) => {
      cb(Object.assign(new Error("ETIMEDOUT"), { code: "ETIMEDOUT" }), "", "");
    });
    expect(await runBrainRecall({ home: "C:/brain", query: "q", cfg: loadRecallGateConfig({}) })).toEqual([]);
  });
});
