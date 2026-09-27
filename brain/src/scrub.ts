/** Secret scrubbing for everything the Brain writes: notes, working state, captured events. */

const CREDENTIAL_WORDS = new Set(["password", "passwd", "pwd", "passphrase", "secret", "credential", "credentials", "apikey"]);
const SUFFIX_WORDS = ["password", "passwd", "passphrase", "secret", "credentials"];
const KEY_OWNERS = new Set(["api", "private", "access", "secret", "client", "auth", "signing", "encryption", "master"]);

/**
 * Whether a key name holds a credential: one of its parts (split on _ . - and camelCase) is a
 * credential word (DB_PASSWORD, clientSecret, aws_secret_access_key), a word pair names a key
 * (api_key, private-key, accessKey), or it is a token and the value looks like one (8+ letters
 * or digits in a row — so "Unexpected token: }" stays).
 */
function isCredential(name: string, value: string): boolean {
  const parts = name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[_.-]+/)
    .filter(Boolean);
  // A part that is, or ends in, a credential word: PASSWORD, PGPASSWORD, mysecret.
  if (parts.some((p) => CREDENTIAL_WORDS.has(p) || SUFFIX_WORDS.some((w) => p.endsWith(w)))) return true;
  if (parts.some((p, i) => p === "key" && i > 0 && KEY_OWNERS.has(parts[i - 1] as string))) return true;
  return parts.includes("token") && /[A-Za-z0-9]{8}/.test(value);
}

/**
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: known token formats (GitHub, sk-, Slack, AWS, Google), Authorization headers, URL and
 * curl credentials, any key=value / key: value whose key names a credential (quoted values are
 * masked whole) and, unless `longRuns` is false, runs of ≥ 40 hex or base64 characters. Notes and
 * working state pass `longRuns: false` so the commit SHAs they cite survive; captured tool output
 * keeps it on. Paths and ordinary words are left alone.
 */
export function scrub(text: string, opts: { longRuns?: boolean } = {}): { text: string; scrubbed: boolean } {
  const original = text;
  let result = text;

  // Known token formats
  result = result.replace(/\bgh[pousr]_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/\bgithub_pat_[A-Za-z0-9_]+/g, "***");
  result = result.replace(/\bsk-(?=[A-Za-z0-9_\-.]*\d)[A-Za-z0-9_\-.]{20,}/g, "***");
  result = result.replace(/\bxox[baprs]-[A-Za-z0-9_-]+/g, "***");
  result = result.replace(/\bAKIA[0-9A-Z]{16}\b/g, "***");
  result = result.replace(/\bAIza[0-9A-Za-z_-]{35}/g, "***");

  // Authorization headers and schemes: Bearer ***, Basic ***, Authorization: Token ***
  result = result.replace(/\b(Bearer|Basic|Digest)\s+[A-Za-z0-9._~+/-]{6,}=*/g, "$1 ***");
  result = result.replace(/\b(authorization)(["']?\s*[=:]\s*["']?)(?!(?:Bearer|Basic|Digest) \*\*\*)(?:(\w+)\s+)?([^\s"',;]+)/gi, (_m, name: string, sep: string, scheme: string | undefined) =>
    `${name}${sep}${scheme ? `${scheme} ` : ""}***`,
  );

  // Credentials in URLs and curl: https://user:***@host, redis://:***@host, curl -u user:***
  result = result.replace(/(\b[a-z][a-z0-9+.-]*:\/\/[^\s:/@]*:)[^\s@/]+@/gi, "$1***@");
  result = result.replace(/((?:^|\s)(?:-u\s*|--user[=\s]\s*)[^\s:]+:)\S+/g, "$1***");

  // Windows: setx NAME value, [Environment]::SetEnvironmentVariable("NAME", "value", …)
  result = result.replace(/\b(setx\s+)(\S+)(\s+)("[^"]*"|\S+)/gi, (match, cmd: string, name: string, space: string, value: string) =>
    isCredential(name, value) ? `${cmd}${name}${space}***` : match,
  );
  result = result.replace(/(SetEnvironmentVariable\(\s*)(["'])([^"']+)\2(\s*,\s*)(["'])((?:\\.|(?!\5)[^\\\n])*)\5/gi, (match, call: string, q1: string, name: string, comma: string, q2: string, value: string) =>
    isCredential(name, value) ? `${call}${q1}${name}${q1}${comma}${q2}***${q2}` : match,
  );

  // key = "quoted value": masked whole — spaces, the other quote and escaped quotes included
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)(["'])((?:\\.|(?!\3)[^\\\n])*)\3/g, (match, name: string, sep: string, quote: string, value: string) =>
    value !== "***" && isCredential(name, value) ? `${name}${sep}${quote}***${quote}` : match,
  );
  // key = value: up to whitespace, a comma, a semicolon or a closing brace (quotes inside included)
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)([^\s,;}]+)/g, (match, name: string, sep: string, value: string) =>
    !/^["']?\*\*\*["']?$/.test(value) && !value.startsWith("//") && isCredential(name, value) ? `${name}${sep}***` : match,
  );

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
