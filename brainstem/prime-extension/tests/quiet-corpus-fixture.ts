/**
 * Quiet-precheck test corpus: a minimal Brain home whose `memories` +
 * `memory_fts` + `memory_fts_vocab` layout mirrors the live schema closely
 * enough for the precheck's read-only queries (it reads `memories.title`,
 * `memories.summary`, `memory_fts` and `memory_fts_vocab` only).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

export interface QuietMemory {
  id: string;
  title: string;
  summary: string;
  body?: string;
  /** `memories.status` (the retrieval filter excludes archived/superseded). */
  status?: string;
  /** `memories.evidence_grade` (the retrieval filter excludes REJECTED). */
  grade?: string;
}

export function writeQuietCorpus(home: string, memories: QuietMemory[]): void {
  mkdirSync(join(home, "db"), { recursive: true });
  const db = new DatabaseSync(join(home, "db", "brain.sqlite"));
  db.exec(
    "CREATE TABLE memories (memory_id TEXT PRIMARY KEY, title TEXT NOT NULL, " +
      "summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'current', " +
      "evidence_grade TEXT NOT NULL DEFAULT 'OBSERVED')",
  );
  db.exec(
    "CREATE VIRTUAL TABLE memory_fts USING fts5(" +
      "memory_id UNINDEXED, title, summary, body, tokenize = 'unicode61')",
  );
  db.exec("CREATE VIRTUAL TABLE memory_fts_vocab USING fts5vocab(memory_fts, 'row')");
  const insertMemory = db.prepare(
    "INSERT INTO memories (memory_id, title, summary, status, evidence_grade) VALUES (?, ?, ?, ?, ?)",
  );
  const insertIndex = db.prepare(
    "INSERT INTO memory_fts (memory_id, title, summary, body) VALUES (?, ?, ?, ?)",
  );
  for (const memory of memories) {
    insertMemory.run(
      memory.id,
      memory.title,
      memory.summary,
      memory.status ?? "current",
      memory.grade ?? "OBSERVED",
    );
    insertIndex.run(memory.id, memory.title, memory.summary, memory.body ?? "");
  }
  db.close();
}

/**
 * The canonical clean corpus: the shared vocabulary appears in BODIES only, so a
 * prompt stating it has term evidence without any headline confirmation.
 */
export function quietCorpusMemories(count = 40): QuietMemory[] {
  return Array.from({ length: count }, (_value, index) => ({
    id: `mem-${index.toString(16).padStart(12, "0")}`,
    title: `note ${index}`,
    summary: `summary entry ${index}`,
    body: "runtime state ledger shared vocabulary",
  }));
}
