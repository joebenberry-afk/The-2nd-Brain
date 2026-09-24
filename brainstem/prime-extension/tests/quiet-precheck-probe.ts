/**
 * Quiet precheck probe: a NON-test entry point that runs the real
 * `src/quiet-precheck.ts` in-host, outside vitest, so the Python parity test and
 * the latency measurement exercise production code.
 *
 * Both runtimes resolve the explicit `.ts` specifier below, so this file is
 * runnable as `node tests/quiet-precheck-probe.ts` or
 * `bun tests/quiet-precheck-probe.ts` (the extension's own host supports both).
 *
 * Usage:
 *   <runner> tests/quiet-precheck-probe.ts --stopwords
 *   <runner> tests/quiet-precheck-probe.ts --requests requests.jsonl
 *
 * `--stopwords` prints `{"stopwords": [...]}`: the TS token set the parity test
 * compares against `semantic._QUERY_STOPWORD_TOKENS`.
 *
 * `--requests` reads one JSON object per line
 * (`{"index": 0, "home": "...", "session": "...", "prompt": "..."}`) and writes
 * one result per line, in input order:
 *   {"index":0,"decision":"skip","reason":"no_evidence","ms":1.23,
 *    "candidates":[...],"detail":{...},"errors":[]}
 * `candidates` is `queryCandidates(queryText)` (the tokenized retrieval text) so
 * the parity test can also compare tokenization against Python.
 */
import { readFileSync } from "node:fs";
import {
  precheckQuiet,
  queryCandidates,
  quietQueryText,
  QUIET_STOPWORD_TOKENS,
} from "../src/quiet-precheck.ts";

interface ProbeRequest {
  index?: number;
  home?: string;
  session?: string;
  prompt?: string;
}

function argumentValue(flag: string): string | undefined {
  const index = process.argv.indexOf(flag);
  return index === -1 ? undefined : process.argv[index + 1];
}

function stopwordDump(): void {
  process.stdout.write(`${JSON.stringify({ stopwords: Object.keys(QUIET_STOPWORD_TOKENS).sort() })}\n`);
}

function runRequests(): void {
  const file = argumentValue("--requests");
  if (file === undefined) throw new Error("--requests <file> is required");
  const lines = readFileSync(file, "utf8").split(/\r?\n/u);
  const out: string[] = [];
  let index = 0;
  for (const line of lines) {
    if (line.trim().length === 0) continue;
    const request = JSON.parse(line) as ProbeRequest;
    const prompt = typeof request.prompt === "string" ? request.prompt : "";
    const started = performance.now();
    const result = precheckQuiet({
      home: typeof request.home === "string" ? request.home : "",
      session: typeof request.session === "string" ? request.session : "",
      prompt,
    });
    const ms = performance.now() - started;
    const queryText = quietQueryText(prompt);
    out.push(
      JSON.stringify({
        index: request.index ?? index,
        decision: result.decision,
        reason: result.reason,
        ms: Math.round(ms * 1000) / 1000,
        candidates: queryText === undefined ? [] : queryCandidates(queryText),
        query_chars: queryText === undefined ? 0 : queryText.length,
        detail: result.detail,
      }),
    );
    index += 1;
  }
  process.stdout.write(`${out.join("\n")}\n`);
}

if (process.argv.includes("--stopwords")) stopwordDump();
else runRequests();
