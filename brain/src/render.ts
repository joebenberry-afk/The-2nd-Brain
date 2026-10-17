/**
 * Layer 4, reversible rendering: in the request a model receives, old and large tool output
 * becomes a short stub carrying a recall id; `brain recall <id>` (or brain_recall) returns the
 * original from state/elided. Host history is never edited. Host-neutral: an adapter (omp.ts
 * `context`, proxy.ts) maps its messages to ToolOutput[] and writes the stubs back. Owner decision
 * of 2026-10-17: docs/intake/2026-10-17-layer4-reversible-rendering.md.
 *
 * Providers cache exact prefixes, so stubs change only in epochs. The watermark is a pure function
 * of the outputs' original sizes and moves only when another `step` tokens of output have aged
 * past the `keep` window; between epochs every stub, and so the request prefix, is byte-identical.
 * A Renderer (one per conversation) re-sends an elided output's stub unchanged when the host later
 * shrinks or rewrites that output in place (pruning), so the prefix and the recall id stay the same.
 */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, rmSync, statSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { writeAtomic } from "./util.ts";

/** One tool output as the host sent it, in conversation order. `key` is the host's call id. */
export interface ToolOutput { key: string; text: string; tool?: string }

/** An output to send as `stub`; `fresh` when this conversation first elided this output. */
export interface Elision { index: number; id: string; stub: string; tokens: number; fresh: boolean }

/** Token budgets, counted by outputTokens: newest `keep` tokens of tool output stay verbatim; epochs advance by `step`; outputs under `min` are never elided. */
export interface RenderPolicy { keep: number; step: number; min: number }

/**
 * An epoch re-sends everything after its first new stub uncached (1.25x base price on Anthropic,
 * 2x with 1-hour caching, 1x on OpenAI) while each elided token then saves one cache read (0.1x)
 * per request, so `step` is above `keep`: an epoch pays back in about 7 requests, 11 with 1-hour
 * caching (40k/20k needed about 23 and cost more than it saved on short log-heavy sessions).
 * keep + step caps live tool output near 80k: in the E6 bench Claude Code's requests peaked at
 * 124k tokens (Claude counts logs about 1.4x heavier than this estimate) against 224k without.
 * A stub costs 60-90 tokens, hence `min` 500.
 */
export const RENDER_POLICY: RenderPolicy = { keep: 30_000, step: 50_000, min: 500 };

/** Recall ids for elided output: `t-` and 10 hex of the original's SHA-256. */
export const ELIDED_ID = /^t-[0-9a-f]{10}$/;

const STUB_PREFIX = "[Second Brain elided this ";
const HEAD_CHARS = 100;
// Slicing can split a surrogate pair; a lone surrogate is invalid UTF-16 that providers may reject.
const LONE_HIGH = /[\ud800-\udbff]$/;
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
// Re-running these only reads, so the stub may suggest it; re-running anything else repeats its effects.
const READ_ONLY = /^(?:read|read_file|grep|glob|find|ls|list_dir)$/i;
const RETENTION_MS = 14 * 86_400_000;
let lastSweep = 0;

// Tenths of a token per UTF-16 unit: letters 2, digits 8, space and tab 1, line feed 10, carriage return 0, other ASCII 6, anything else 10.
const WEIGHTS = new Uint8Array(128).fill(6);
for (let c = 65; c <= 90; c++) WEIGHTS[c] = WEIGHTS[c + 32] = 2;
for (let c = 48; c <= 57; c++) WEIGHTS[c] = 8;
WEIGHTS[9] = WEIGHTS[32] = 1;
WEIGHTS[10] = 10;
WEIGHTS[13] = 0;

/**
 * Tokens of a tool output, from per-character weights fitted to o200k_base counts of code, prose,
 * logs, JSON, CSV, diffs and listings: mean error 5-6%, every kind within 13%. chars/4 (the brain's
 * budget unit) runs 33-39% low on logs, JSON and listings, which would keep most of a log-heavy
 * history verbatim. Claude's tokenizer counts about 1.4x more on logs, so there the policy keeps more.
 */
export function outputTokens(text: string): number {
  let tenths = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    tenths += code < 128 ? WEIGHTS[code]! : 10;
  }
  return Math.ceil(tenths / 10);
}

function elidedDir(home: string): string {
  return join(home, "state", "elided");
}

/** Write-once copy of an elided original; reuse refreshes its 14-day retention. Sweeps at most daily. Never throws. */
export function storeElided(home: string, id: string, text: string): boolean {
  const dir = elidedDir(home);
  try {
    const now = Date.now();
    if (now - lastSweep > 86_400_000) {
      lastSweep = now;
      let names: string[] = [];
      try { names = readdirSync(dir); } catch { /* nothing stored yet */ }
      for (const name of names) {
        try { if (now - statSync(join(dir, name)).mtimeMs > RETENTION_MS) rmSync(join(dir, name), { force: true }); } catch { /* raced */ }
      }
    }
    const path = join(dir, `${id}.txt`);
    const existing = readElided(home, id);
    if (existing === text) {
      utimesSync(path, now / 1000, now / 1000);
      return true;
    }
    // A hash collision or a stale id must keep the output full: the stored original is not this one.
    if (existing !== undefined) return false;
    // Never store text that cannot be valid UTF-8; the renderer leaves that output full.
    if (LONE_SURROGATE.test(text)) return false;
    writeAtomic(path, text);
    return true;
  } catch {
    return false; // Preserve the full output when its original cannot be saved.
  }
}

/** The original behind an elided-output recall id, when this machine still holds it. */
export function readElided(home: string, id: string): string | undefined {
  if (!ELIDED_ID.test(id)) return undefined;
  try {
    return readFileSync(join(elidedDir(home), `${id}.txt`), "utf8");
  } catch {
    return undefined;
  }
}

/**
 * Index of the newest output at or before which output may be elided, or -1. Boundaries sit where
 * the running total of output tokens first reaches each multiple of `step`; the watermark is the
 * last boundary followed by at least `keep` tokens of output. Appending output only adds later
 * boundaries, so the watermark never moves back and jumps about `step` tokens at a time.
 */
function watermark(sizes: readonly number[], policy: RenderPolicy): number {
  let total = 0;
  for (const size of sizes) total += size;
  let mark = -1, prefix = 0, next = policy.step;
  for (let i = 0; i < sizes.length; i++) {
    prefix += sizes[i]!;
    if (prefix < next) continue;
    if (total - prefix < policy.keep) break;
    mark = i;
    next = (Math.floor(prefix / policy.step) + 1) * policy.step;
  }
  return mark;
}

/**
 * Stateful per conversation. Per call key it keeps the id and stub it elided with: holding a key is
 * what makes an elision sticky, and the stored stub goes out again even after the host shrinks or
 * rewrites that output in place. A request hashes and formats only output it has not elided before.
 * It also keeps each key's size, so a request counts only new or changed output.
 */
export class Renderer {
  readonly #policy: RenderPolicy;
  readonly #home: string | null;
  readonly #elided = new Map<string, { id: string; stub: string }>();
  readonly #sizes = new Map<string, { text: string; tokens: number }>();
  /** Output instances (call id and content) elided at any point in this conversation: a shrink can forget the sticky map, not the saving. */
  readonly #seen = new Set<string>();
  #count = 0;
  #tokens = 0;

  constructor(home: string | null = null, policy: Partial<RenderPolicy> = {}) {
    this.#home = home;
    this.#policy = { ...RENDER_POLICY, ...policy };
  }

  /** Tokens of all tool output in the last render() call, before stubs. */
  get tokens(): number {
    return this.#tokens;
  }

  /** Stubs for this request, oldest first. Same outputs and history give the same stubs, byte for byte. */
  render(outputs: readonly ToolOutput[]): Elision[] {
    // Fewer outputs than last time: compaction, /clear or a branch switch rewrote the history, and
    // an output elided there may now be recent.
    if (outputs.length < this.#count) {
      this.#elided.clear();
      this.#sizes.clear();
    }
    this.#count = outputs.length;
    this.#tokens = 0;
    const sizes = outputs.map(({ key, text }) => {
      let size = this.#sizes.get(key);
      if (size?.text !== text) {
        size = { text, tokens: outputTokens(text) };
        this.#sizes.set(key, size);
      }
      this.#tokens += size.tokens;
      return size.tokens;
    });
    const mark = watermark(sizes, this.#policy);
    const elisions: Elision[] = [];
    for (let index = 0; index < outputs.length; index++) {
      const output = outputs[index]!, tokens = sizes[index]!;
      const held = this.#elided.get(output.key);
      if (held) {
        elisions.push({ index, id: held.id, stub: held.stub, tokens, fresh: false });
        continue;
      }
      if (index > mark || tokens < this.#policy.min || output.text.startsWith(STUB_PREFIX)) continue;
      const text = output.text;
      const id = `t-${createHash("sha256").update(text).digest("hex").slice(0, 10)}`;
      if (this.#home && !storeElided(this.#home, id, text)) continue;
      let lines = 1;
      for (let at = text.indexOf("\n"); at !== -1; at = text.indexOf("\n", at + 1)) lines++;
      const tool = (output.tool ?? "").replace(/[^\w.-]/g, "") || "tool";
      const flat = text.slice(0, HEAD_CHARS * 4).replace(LONE_HIGH, "").trim().replace(/\s+/g, " ");
      const head = flat.length > HEAD_CHARS ? `${flat.slice(0, HEAD_CHARS).replace(LONE_HIGH, "")}…` : flat;
      const again = READ_ONLY.test(tool) ? "; re-running the tool also shows it" : "";
      const stub = `${STUB_PREFIX}${tool} output to save context: ${lines} line${lines === 1 ? "" : "s"}, ~${tokens} tokens. Recall id ${id} returns it in full${again}. It began: ${head}]`;
      this.#elided.set(output.key, { id, stub });
      const seen = `${output.key}\0${id}`;
      elisions.push({ index, id, stub, tokens, fresh: !this.#seen.has(seen) });
      this.#seen.add(seen);
    }
    return elisions;
  }
}
