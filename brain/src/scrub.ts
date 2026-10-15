/** Secret scrubbing for everything the Brain writes: notes, working state, captured events. */
import { createHash } from "node:crypto";

const CREDENTIAL_WORDS = new Set(["password", "passwd", "passphrase", "secret", "credential", "credentials", "apikey"]);
const SUFFIX_WORDS = ["password", "passwd", "passphrase", "secret", "credentials"];
// Short names count as the last part only: DB_PASS, PGPASS, MYSQL_PWD — not passWithNoTests or BYPASS.
const SHORT_WORDS = new Set(["pass", "pgpass", "pwd"]);
const KEY_OWNERS = new Set(["api", "private", "access", "secret", "client", "auth", "signing", "encryption", "master"]);

/**
 * A reference to a secret, not the secret: $DB_PASSWORD, ${{ secrets.X }}, %X%, process.env.X,
 * os.environ[…], $env:X. Each form names one variable and nothing else, so a literal riding after a
 * reference (`process.env["K"]||"hunter2"`, `os.getenv('K', 'hunter2')` quoted whole) stays masked.
 */
const REFERENCE = /^(?:\$\{?[A-Z_][A-Z0-9_]*\}?|\$\{\{[^}]*(?:\}\})?|%[A-Za-z_][A-Za-z0-9_]*%|\$env:\w+|env:\w+|process\.env(?:\.\w+)+|(?:process\.env|os\.environ)\[["']?\w+["']?\]|(?:os\.environ\.get|os\.getenv|Deno\.env\.get)\(["']?\w+["']?\)?)[)'"}\]]*$/;
/** A configuration size or switch, not a secret: password_min_length=12 (unless the value is generated-looking). */
const SETTING_SUFFIX = /^(?:length|size|min|max|count|ttl|expiry|enabled|required|policy)$/;

/**
 * A value that cannot be a secret: a reference, true/false/null/undefined, fetch's `credentials`
 * enum, a setting named after a credential (password_min_length), PWD=<directory>.
 */
function benignValue(name: string, value: string): boolean {
  const bare = value.replace(/^["']+|["']+$/g, "");
  if (REFERENCE.test(bare) || /^(?:true|false|null|undefined)$/i.test(bare)) return true;
  if (name === "credentials" && /^(?:include|omit|same-origin)$/.test(bare)) return true;
  if (name === "PWD" && /^(?:[/~]|[A-Za-z]:[\\/])/.test(bare)) return true;
  const last = name.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase().split(/[_.-]+/).filter(Boolean).at(-1) ?? "";
  return SETTING_SUFFIX.test(last) && !tokenLike(bare);
}

/**
 * Whether a key name holds a credential: one of its parts (split on _ . - and camelCase) is a
 * credential word (DB_PASSWORD, clientSecret, aws_secret_access_key), a word pair names a key
 * (api_key, private-key, accessKey), a name ending in "key" holds a generated-looking value
 * (STRIPE_KEY=…), or it is a token and the value looks like one (8+ letters or digits in a row — so
 * "Unexpected token: }" stays).
 */
function isCredential(name: string, value: string): boolean {
  if (benignValue(name, value)) return false;
  const parts = name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[_.-]+/)
    .filter(Boolean);
  // A part that is, or ends in, a credential word: PASSWORD, PGPASSWORD, mysecret.
  if (parts.some((p) => CREDENTIAL_WORDS.has(p) || SUFFIX_WORDS.some((w) => p.endsWith(w)))) return true;
  if (SHORT_WORDS.has(parts.at(-1) ?? "") && !/^(?:true|false|null)$/i.test(value) && !/^(?:=|[[{]\s*(?:["'{[\]}]|$))/.test(value)) return true; // not memory.pass=true, s.pass === x, "firstPass":{"…"}, pass = []
  if (parts.some((p, i) => p === "key" && i > 0 && KEY_OWNERS.has(parts[i - 1] as string))) return true;
  // STRIPE_KEY, MAILGUN_KEY: a key named after anything, when the value looks generated
  if (parts.at(-1) === "key" && tokenLike(value)) return true;
  return parts.includes("token") && /[A-Za-z0-9]{8}/.test(value);
}

/** 16+ letters, digits, "_" or "-" in a row, with both a letter and a digit: a generated value, not a word. */
function tokenLike(value: string): boolean {
  return (value.match(/[A-Za-z0-9_-]{16,}/g) ?? []).some((run) => /\d/.test(run) && /[A-Za-z]/.test(run));
}

/**
 * Colon prose is not an assignment; passwords remain protected even in sentences. A quoted value
 * (`pass: 'hunter2'`, `"pass": "…"`) is an assignment, not prose.
 */
function credentialAssignment(name: string, value: string, sep: string, offset: number, text: string, quoted = false): boolean {
  if (sep.includes(":")) {
    // "pwd: C:/repo", docker -v "$PWD":/app — the working directory, quoted or not; "First pass: …",
    // "--- PASS: TestX". Pwd=… (connection strings), pass=…, pass: '…', DB_PASS: … stay masked.
    if (/^pwd$/i.test(name) || (!quoted && /^pass$/i.test(name))) return false;
    if (/(?:^|[_.-])token$/i.test(name) && !tokenLike(value)) return false;
    if (name === "secret" && /\w[^\S\r\n]+$/.test(text.slice(0, offset)) && !tokenLike(value)) return false;
  }
  return isCredential(name, value);
}

/**
 * Replace secret-looking values with ***, return (text, scrubbed).
 * Cover: known token formats (GitHub, sk-, Slack, AWS, Google, Stripe, GitLab, npm, SendGrid, JWT),
 * private key blocks, Authorization headers, URL and
 * curl credentials, any key=value / key: value whose key names a credential (quoted values are
 * masked whole) and, unless `longRuns` is false, runs of ≥ 40 hex or base64 characters. Notes and
 * working state pass `longRuns: false` so the commit SHAs they cite survive; captured tool output
 * keeps it on. `tagRuns` (the event log's commands) masks each long run as *** plus 6 hex of its
 * hash, so commands that differ only in a SHA or token stay different. Paths and ordinary words are
 * left alone.
 */
export function scrub(text: string, opts: { longRuns?: boolean; tagRuns?: boolean } = {}): { text: string; scrubbed: boolean } {
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
  result = result.replace(/\bhf_[A-Za-z0-9]{30,}/g, "***"); // Hugging Face
  result = result.replace(/\bshp(?:at|ss|ca|pa)_[a-fA-F0-9]{32}/g, "***"); // Shopify
  result = result.replace(/\bpypi-AgE[A-Za-z0-9_-]{50,}/g, "***"); // PyPI
  result = result.replace(/\bhv[sb]\.[A-Za-z0-9_-]{24,}/g, "***"); // HashiCorp Vault
  result = result.replace(/\bdop_v1_[a-f0-9]{64}/g, "***"); // DigitalOcean
  result = result.replace(/\bya29\.[A-Za-z0-9_-]{20,}/g, "***"); // Google OAuth access token
  result = result.replace(/\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b/g, "***"); // Telegram bot
  result = result.replace(/\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}\b/g, "***"); // Discord bot
  result = result.replace(/([?&]sig=)[A-Za-z0-9%+/_=-]{8,}/g, "$1***"); // Azure SAS signature
  result = result.replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, "***"); // JWT

  // Private key blocks (PEM, OpenSSH), also when the output was cut before the END line
  // A retained tail can contain an END marker without its BEGIN: discard the orphaned span.
  const endKey = /-----END [A-Z0-9 ]*PRIVATE KEY-----/.exec(result);
  const beginKey = result.search(/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/);
  if (endKey && (beginKey < 0 || beginKey > endKey.index)) result = "***" + result.slice(endKey.index + endKey[0].length);
  result = result.replace(/(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)/g, "$1 *** -----END PRIVATE KEY-----");

  // Authorization headers and schemes: Bearer ***, Basic ***, Authorization: Token ***. A bare
  // scheme word before an ordinary word is prose ("Basic Upscaler", "Visual Basic Scripting"), and
  // a word followed by path segments is a path ("The Basic Upscaler/tools/bench.ps1"): outside an
  // Authorization header only a token-shaped value (digit, symbol, inner capital, or 20+ letters) is
  // masked. A path has no "+" or "=", no 20-letter run and no generated-looking one, so base64 with a
  // "/" is masked.
  result = result.replace(/\b(Bearer|Basic|Digest)\s+([A-Za-z0-9._~+/-]{6,}=*)/g, (match, scheme: string, value: string) =>
    /^[A-Za-z][a-z]{0,18}$/.test(value) || (/^[A-Za-z][a-z]{0,18}(?:\/[\w.-]+)+\/?$/.test(value) && !/[A-Za-z]{20,}/.test(value) && !tokenLike(value) && !randomLooking(value)) ? match : `${scheme} ***`);
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
  // …except mysql/mariadb -p<password>, attached, to the end of that command (across a trailing \ or
  // PowerShell ` line continuation). mysql must be the word run: bare, or by a path or quoted in command
  // position (line start, or after ; & | ( ` including PowerShell's &) — not a path argument
  // (find /etc/mysql, -I/usr/include/mysql), an image (mysql:8), a name (mysql-db) or a flag's value
  // (--name mysql, --name "mysql"). The command-position match starts at the separator itself, so a
  // long blank run is scanned once from there, not retried at every blank.
  result = result.replace(/(?:(^|[\n;&|(`])[ \t]*(?:(["'])(?:(?:(?!\2)[^\n])*[\\/])?|[^\s;&|()=`-][^\s;&|()=`]*[\\/])|(?<![\w/\\.:=-]))(?:mysql\w*|mariadb(?:-\w+)?)(?:\.exe)?\2(?=\s)(?:[^\n;|&)`]|`(?=\r?\n)|(?<=[\\`]\r?)\n)*/g, (command, start: string | undefined, _quote, offset: number, text: string) =>
    start === undefined && /\s--\w[\w-]*\s+$/.test(text.slice(Math.max(0, offset - 64), offset)) ? command : command.replace(/(\s-p)(?:(['"])(?:\\.|(?!\2)[^\\\n])*\2|\S+)/g, "$1***"));

  // Windows: setx NAME value, [Environment]::SetEnvironmentVariable("NAME", "value", …)
  result = result.replace(/\b(setx\s+)(\S+)(\s+)("[^"]*"|\S+)/gi, (match, cmd: string, name: string, space: string, value: string) =>
    isCredential(name, value) ? `${cmd}${name}${space}***` : match,
  );
  result = result.replace(/(SetEnvironmentVariable\(\s*)(["'])([^"']+)\2(\s*,\s*)(["'])((?:\\.|(?!\5)[^\\\n])*)\5/gi, (match, call: string, q1: string, name: string, comma: string, q2: string, value: string) =>
    isCredential(name, value) ? `${call}${q1}${name}${q1}${comma}${q2}***${q2}` : match,
  );

  // key = "quoted value": masked whole — spaces, the other quote and escaped quotes included
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)(["'])((?:\\.|(?!\3)[^\\\n])*)\3/g, (match, name: string, sep: string, quote: string, value: string, offset: number, text: string) =>
    value !== "***" && credentialAssignment(name, value, sep, offset, text, true) ? name + sep + quote + "***" + quote : match,
  );
  // key = value: up to whitespace, a comma, a semicolon or a closing brace (quotes inside included).
  // The value of any other pair is searched once more, split at "&" and at a "?" that starts a pair:
  // https://h/?api_key=…, http://localhost:8080/v1?password=…, url: https://h/p?api_key=…,
  // --from-literal=password=…, -var=db_password=….
  const pair = (inner: boolean) => (match: string, name: string, sep: string, value: string, offset: number, text: string): string => {
    if (/^["']?\*\*\*["']?$/.test(value)) return match;
    if (!value.startsWith("//") && credentialAssignment(name, value, sep, offset, text)) return name + sep + "***";
    return inner ? match : name + sep + value.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)((?:[^\s,;}&?]|\?(?![A-Za-z0-9_.-]+["']?\s*[=:]))+)/g, pair(true));
  };
  result = result.replace(/(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)(["']?\s*[=:]\s*)([^\s,;}]+)/g, pair(false));

  if (opts.longRuns === false) return { text: result, scrubbed: result !== original };

  // Long hex runs (hashes, keys) and base64 runs. A run containing "/" is a path unless it is padded
  // or reads like random base64 (digits present and at least a quarter of its letters upper-case).
  // The 6-hex tag is below every threshold here, so a later scrub leaves it alone.
  const mask = (run: string) => (opts.tagRuns ? "***" + createHash("sha256").update(run).digest("hex").slice(0, 6) : "***");
  result = result.replace(/\b[A-Fa-f0-9]{40,}\b/g, mask);
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+]{40,}={0,2}/g, mask);
  result = result.replace(/(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}/g, (run) => (run.endsWith("=") || randomLooking(run) ? mask(run) : run));

  return { text: result, scrubbed: result !== original };
}

function randomLooking(run: string): boolean {
  const letters = run.replace(/[^A-Za-z]/g, "");
  const upper = run.replace(/[^A-Z]/g, "").length;
  return /\d/.test(run) && letters.length > 0 && upper / letters.length >= 0.25;
}
