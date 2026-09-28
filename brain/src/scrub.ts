/** Secret scrubbing for everything the Brain writes: notes, working state, captured events. */

const CREDENTIAL_WORDS = new Set(["password", "passwd", "passphrase", "secret", "credential", "credentials", "apikey"]);
const SUFFIX_WORDS = ["password", "passwd", "passphrase", "secret", "credentials"];
const KEY_OWNERS = new Set(["api", "private", "access", "secret", "client", "auth", "signing", "encryption", "master"]);

/**
 * Whether a key name holds a credential: one of its parts (split on _ . - and camelCase) is a
 * credential word (DB_PASSWORD, clientSecret, aws_secret_access_key), a word pair names a key
 * (api_key, private-key, accessKey), a name ending in "key" holds a generated-looking value
 * (STRIPE_KEY=…), or it is a token and the value looks like one (8+ letters or digits in a row — so
 * "Unexpected token: }" stays).
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
  // STRIPE_KEY, MAILGUN_KEY: a key named after anything, when the value looks generated
  if (parts.at(-1) === "key" && tokenLike(value)) return true;
  return parts.includes("token") && /[A-Za-z0-9]{8}/.test(value);
}

/** 16+ letters, digits, "_" or "-" in a row, with both a letter and a digit: a generated value, not a word. */
function tokenLike(value: string): boolean {
  return (value.match(/[A-Za-z0-9_-]{16,}/g) ?? []).some((run) => /\d/.test(run) && /[A-Za-z]/.test(run));
}

/** Colon prose is not an assignment; passwords remain protected even in sentences. */
function credentialAssignment(name: string, value: string, sep: string, offset: number, text: string): boolean {
  if (sep.includes(":")) {
    if (/(?:^|[_.-])token$/i.test(name) && !tokenLike(value)) return false;
    if (name === "secret" && /\w[^\S\r\n]+$/.test(text.slice(0, offset)) && !tokenLike(value)) return false;
  }
  return isCredential(name, value);
}

/**
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: known token formats (GitHub, sk-, Slack, AWS, Google, Stripe, GitLab, npm, SendGrid),
 * private key blocks, Authorization headers, URL and
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
  result = result.replace(/\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}/g, "***"); // Stripe
  result = result.replace(/\bglpat-[A-Za-z0-9_-]{20,}/g, "***"); // GitLab
  result = result.replace(/\bnpm_[A-Za-z0-9]{36}\b/g, "***"); // npm
  result = result.replace(/\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}/g, "***"); // SendGrid

  // Private key blocks (PEM, OpenSSH), also when the output was cut before the END line
  // A retained tail can contain an END marker without its BEGIN: discard the orphaned span.
  const endKey = /-----END [A-Z0-9 ]*PRIVATE KEY-----/.exec(result);
  const beginKey = result.search(/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/);
  if (endKey && (beginKey < 0 || beginKey > endKey.index)) result = "***" + result.slice(endKey.index + endKey[0].length);
  result = result.replace(/(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)/g, "$1 *** -----END PRIVATE KEY-----");

  // Authorization headers and schemes: Bearer ***, Basic ***, Authorization: Token ***. A bare
  // scheme word before an ordinary word is prose ("Basic Upscaler", "Visual Basic Scripting"):
  // outside an Authorization header only a token-shaped value (digit, symbol, inner capital, or 20+
  // letters) is masked.
  result = result.replace(/\b(Bearer|Basic|Digest)\s+([A-Za-z0-9._~+/-]{6,}=*)/g, (match, scheme: string, value: string) =>
    /^[A-Za-z][a-z]{0,18}$/.test(value) ? match : `${scheme} ***`);
  result = result.replace(/\b(authorization)(["']?\s*[=:]\s*["']?)(?!(?:Bearer|Basic|Digest) \*\*\*)(?:(\w+)\s+)?([^\s"',;]+)/gi, (_m, name: string, sep: string, scheme: string | undefined) =>
    `${name}${sep}${scheme ? `${scheme} ` : ""}***`,
  );

  // Credentials in URLs and curl: https://user:***@host, redis://:***@host, curl -u user:***
  // (the scheme's start is anchored by a lookbehind: "a.a.a.…" must not be retried at every dot)
  result = result.replace(/((?<![a-z0-9+.-])[a-z][a-z0-9+.-]*:\/\/[^\s:/@]*:)[^\s@/]+@/gi, "$1***@");
  result = result.replace(/((?:^|\s)(?:-u\s*|--user[=\s]\s*))(?:(['"])((?:\\.|(?!\2)[^\\\n])*)\2|([^\s]+))/g, (match, flag: string, quote: string | undefined, quoted: string | undefined, plain: string | undefined) => {
    const value = quoted ?? plain ?? "";
    const colon = value.indexOf(":");
    return colon < 0 ? match : flag + (quote ?? "") + value.slice(0, colon + 1) + "***" + (quote ?? "");
  });
  // Explicit long credential flags only: -p commonly names a port.
  result = result.replace(/((?:^|\s)--(?:[a-z0-9]+-)*(?:password|passwd|token|api-key|apikey|secret|auth|credentials?)(?:\s+|=))(?:(['"])(?:\\.|(?!\2)[^\\\n])*\2|[^\s]+)/gi, "$1***");

  // Windows: setx NAME value, [Environment]::SetEnvironmentVariable("NAME", "value", …)
  result = result.replace(/\b(setx\s+)(\S+)(\s+)("[^"]*"|\S+)/gi, (match, cmd: string, name: string, space: string, value: string) =>
    isCredential(name, value) ? `${cmd}${name}${space}***` : match,
  );
  result = result.replace(/(SetEnvironmentVariable\(\s*)(["'])([^"']+)\2(\s*,\s*)(["'])((?:\\.|(?!\5)[^\\\n])*)\5/gi, (match, call: string, q1: string, name: string, comma: string, q2: string, value: string) =>
    isCredential(name, value) ? `${call}${q1}${name}${q1}${comma}${q2}***${q2}` : match,
  );

  // key = "quoted value": masked whole — spaces, the other quote and escaped quotes included
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)(["'])((?:\\.|(?!\3)[^\\\n])*)\3/g, (match, name: string, sep: string, quote: string, value: string, offset: number, text: string) =>
    value !== "***" && credentialAssignment(name, value, sep, offset, text) ? name + sep + quote + "***" + quote : match,
  );
  // key = value: up to whitespace, a comma, a semicolon or a closing brace (quotes inside included)
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)([^\s,;}]+)/g, (match, name: string, sep: string, value: string, offset: number, text: string) =>
    !/^["']?\*\*\*["']?$/.test(value) && !value.startsWith("//") && credentialAssignment(name, value, sep, offset, text) ? name + sep + "***" : match,
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
