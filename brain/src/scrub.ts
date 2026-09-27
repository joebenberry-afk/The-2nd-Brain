/** Secret scrubbing for everything the Brain writes: notes, working state, captured events. */

/**
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: GitHub tokens, sk-*, xox*, AWS/Google tokens, Bearer, password=value and, unless
 * `longRuns` is false, any run of ≥ 40 hex/base64 characters. Notes and working state pass
 * `longRuns: false` so the commit SHAs they cite survive; captured tool output keeps it on.
 */
export function scrub(text: string, opts: { longRuns?: boolean } = {}): { text: string; scrubbed: boolean } {
  const original = text;
  let result = text;

  // GitHub tokens
  result = result.replace(/ghp_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/gho_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/github_pat_[A-Za-z0-9_]+/g, "***");

  // OpenAI/Slack tokens
  result = result.replace(/sk-[A-Za-z0-9_\-.]{20,}/g, "***");
  result = result.replace(/xox[baprs]-[A-Za-z0-9_]+/g, "***");

  // AWS and Google tokens
  result = result.replace(/AKIA[0-9A-Z]{16}/g, "***");
  result = result.replace(/AIza[0-9A-Za-z_-]{35}/g, "***");

  // Bearer tokens
  result = result.replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer ***");

  // Password/secret/token patterns (key kept, value masked)
  result = result.replace(
    /(password|passwd|secret|token|api[_-]?key)\s*([=:])\s*([^\s]+)/gi,
    "$1$2 ***"
  );

  if (opts.longRuns === false) return { text: result, scrubbed: result !== original };

  // Long base64/hex runs (≥40 chars)
  result = result.replace(/[A-Fa-f0-9]{40,}/g, "***");
  result = result.replace(
    /[A-Za-z0-9+/]{40,}={0,2}/g,
    (match) => (match.includes("=") || match.length >= 40 ? "***" : match)
  );

  return { text: result, scrubbed: result !== original };
}
