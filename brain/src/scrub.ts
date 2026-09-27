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
  result = result.replace(/\bgh[pousr]_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/\bgithub_pat_[A-Za-z0-9_]+/g, "***");

  // OpenAI-style and Slack tokens (a key starts a word and carries a digit)
  result = result.replace(/\bsk-(?=[A-Za-z0-9_\-.]*\d)[A-Za-z0-9_\-.]{20,}/g, "***");
  result = result.replace(/\bxox[baprs]-[A-Za-z0-9_-]+/g, "***");

  // AWS and Google keys
  result = result.replace(/\bAKIA[0-9A-Z]{16}\b/g, "***");
  result = result.replace(/\bAIza[0-9A-Za-z_-]{35}/g, "***");

  // Bearer tokens
  result = result.replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer ***");

  // key=value / key: value — the key is kept, the value masked. The key may end a longer name
  // (DB_PASSWORD, client_secret, access_token, GITHUB_TOKEN). Passwords, secrets and API keys at
  // any length; a token only when its value looks like one (so "Unexpected token: }" stays).
  // Credentials in URLs and curl: https://user:***@host, curl -u user:***
  result = result.replace(/(\b[a-z][a-z0-9+.-]*:\/\/[^\s:/@]+:)[^\s@/]+@/gi, "$1***@");
  result = result.replace(/((?:^|\s)(?:-u|--user)\s+[^\s:]+:)\S+/g, "$1***");

  // A quoted value is masked whole, spaces included: "password": "***", PGPASSWORD='***'.
  result = result.replace(/(password|passwd|pwd|secret|api[_-]?key|token)(["']?\s*[=:]\s*)(["'])(?!\*\*\*\3)[^"'\n]*\3/gi, "$1$2$3***$3");

  // Quoted keys and values (JSON, YAML) keep their quotes: "password": "***".
  result = result.replace(/(password|passwd|pwd|secret|api[_-]?key)(["']?\s*[=:]\s*["']?)([^\s,;"'}]+)/gi, "$1$2***");
  result = result.replace(/(token)(["']?\s*[=:]\s*["']?)(?=[^\s,;"'}]*[A-Za-z0-9]{8})([^\s,;"'}]+)/gi, "$1$2***");
  // Upper-case environment names that end in a credential word: AWS_SECRET_ACCESS_KEY=…, NPM_TOKEN=…
  result = result.replace(/\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|CREDENTIALS?))(["']?\s*[=:]\s*["']?)(?!\*\*\*)([^\s,;"'}]+)/g, "$1$2***");

  if (opts.longRuns === false) return { text: result, scrubbed: result !== original };

  // Long hex runs (hashes, keys) and base64 runs. A run containing "/" is a path unless it is padded
  // or reads like random base64 (digits present and at least a quarter of its letters upper-case).
  result = result.replace(/\b[A-Fa-f0-9]{40,}\b/g, "***");
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+]{40,}={0,2}/g, "***");
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}/g, (run) => (run.endsWith("=") || randomLooking(run) ? "***" : run));

  return { text: result, scrubbed: result !== original };
}

function randomLooking(run: string): boolean {
  const letters = run.replace(/[^A-Za-z]/g, "");
  const upper = run.replace(/[^A-Z]/g, "").length;
  return /\d/.test(run) && letters.length > 0 && upper / letters.length >= 0.25;
}
