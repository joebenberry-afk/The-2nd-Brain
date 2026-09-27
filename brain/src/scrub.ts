/** Secret scrubbing for everything the Brain writes: notes, working state, captured events. */

/**
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: GitHub tokens, sk-* keys, xox*, AWS/Google keys, Bearer tokens, password/secret/api-key
 * values, token values that look like tokens and, unless `longRuns` is false, runs of ≥ 40
 * hex or base64 characters. Notes and working state pass `longRuns: false` so the commit SHAs
 * they cite survive; captured tool output keeps it on. Paths and ordinary words are left alone:
 * a key needs a word boundary, and a long run containing "/" counts only with base64 padding.
 */
export function scrub(text: string, opts: { longRuns?: boolean } = {}): { text: string; scrubbed: boolean } {
  const original = text;
  let result = text;

  // GitHub tokens
  result = result.replace(/\bgh[po]_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/\bgithub_pat_[A-Za-z0-9_]+/g, "***");

  // OpenAI-style and Slack tokens (a key starts a word and carries a digit)
  result = result.replace(/\bsk-(?=[A-Za-z0-9_\-.]*\d)[A-Za-z0-9_\-.]{20,}/g, "***");
  result = result.replace(/\bxox[baprs]-[A-Za-z0-9_-]+/g, "***");

  // AWS and Google keys
  result = result.replace(/\bAKIA[0-9A-Z]{16}\b/g, "***");
  result = result.replace(/\bAIza[0-9A-Za-z_-]{35}/g, "***");

  // Bearer tokens
  result = result.replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer ***");

  // key=value / key: value — the key is kept, the value masked. Passwords, secrets and API keys
  // at any length; a "token" only when its value looks like one (so "Unexpected token: }" stays).
  result = result.replace(/\b(password|passwd|pwd|secret|api[_-]?key)(\s*[=:])\s*([^\s,;]+)/gi, "$1$2 ***");
  result = result.replace(/\b(token)(\s*[=:])\s*(?=[^\s,;]*[A-Za-z0-9]{8})([^\s,;]+)/gi, "$1$2 ***");

  if (opts.longRuns === false) return { text: result, scrubbed: result !== original };

  // Long hex runs (hashes, keys) and base64 runs. A run with "/" is a path unless it is padded.
  result = result.replace(/\b[A-Fa-f0-9]{40,}\b/g, "***");
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+]{40,}={0,2}/g, "***");
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={1,2}/g, "***");

  return { text: result, scrubbed: result !== original };
}
