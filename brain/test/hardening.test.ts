/** Tests for the hardening pass: scrubbing on write, answer(), duplicates, display paths. */
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { main } from "../src/cli.ts";
import { createNote, findSameHeadline, loadNotes } from "../src/notes.ts";
import { displayPath } from "../src/omp.ts";
import { answer, FIRST_HIT_CHARS, recall, renderHits } from "../src/search.ts";
import { scrub } from "../src/scrub.ts";
import { estimateTokens } from "../src/util.ts";
import { readWork, writeAuto, writeWork } from "../src/work.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-hard-"));
const project = { id: "demo", tags: [], root: null };
const SHA = "0123456789abcdef0123456789abcdef01234567";

describe("secrets never reach notes or working state", () => {
  it("masks compound double-dash credential flags", () => {
    for (const flag of ["db-password", "db-passwd", "api-token", "client-secret", "service-api-key", "service-apikey", "service-auth", "service-credential", "service-credentials"]) {
      for (const sep of [" ", "="]) {
        expect(scrub(`dbcli --${flag}${sep}hunter2`).text).toBe(`dbcli --${flag}${sep}***`);
      }
    }
  });

  it("masks cookie headers, session-cookie assignments and ASIA ids, but not prose", () => {
    const sid = "q8Zr3kLm0Pw7Xv2NbT5yHc9DaE4sUf1G";
    for (const [text, expected] of [
      [`Cookie: sessionid=${sid}; csrftoken=abc`, "Cookie: sessionid=***; csrftoken=***"],
      [`set-cookie: sid=${sid}; Path=/; Secure`, "set-cookie: sid=***; Path=/; Secure"],
      [`curl -H 'Cookie: a=${sid}' https://h`, "curl -H 'Cookie: a=***' https://h"],
      [`curl -b "a=${sid}; b=2" https://h`, 'curl -b "a=***; b=***" https://h'],
      ["curl --cookie=a=1 https://h", "curl --cookie=a=*** https://h"],
      ["curl -b'a=1' --cookie \"b=2\" https://h", "curl -b'a=***' --cookie \"b=***\" https://h"],
      ["curl -b a=1 https://h; make -b CC=clang", "curl -b a=*** https://h; make -b CC=clang"],
      [`{"cookie": "sid=${sid}"}`, '{"cookie": "sid=***"}'],
      [`PHPSESSID=${sid}`, "PHPSESSID=***"],
      [`session_id: "${sid}"`, 'session_id: "***"'],
      ["key ASIAABCDEFGHIJKLMNOP", "key ***"],
    ] as const) {
      expect(scrub(text).text).toBe(expected);
    }
    for (const text of ["Cookie: banner shown on first visit", "curl -b cookies.txt https://h", "session_id: str", "the session expired; session id=abc", "sessionId=self.sessionId", "git checkout -b feature/x"]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
  });

  it.each(["go test -bench=. ./...", "go build -buildmode=c-shared", "go test -benchtime=10s -bench=BenchmarkParse", "make -b CC=clang", "curl https://h; make -b CC=clang"])("preserves non-cookie flags in events and note bodies: %s", (text) => {
    expect(scrub(text)).toEqual({ text, scrubbed: false });
    const home = tmp();
    createNote(home, { text, project: "global", kind: "gotcha" });
    expect(loadNotes(home).notes[0]!.body).toBe(text);
  });

  it("preserves prose colon keys but masks credential assignments", () => {
    for (const text of ["SyntaxError: Unexpected token: identifier", "pytest fails from pwd: C:/repo/tests", "The secret: never commit .env", "csrf_token: generated per request"]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    for (const text of ["token: ghp_abcdefghijklmnopqrstuvwxyz0123456789", "token: abcdefghijklmnop1234", "password: hunter2secret", "API_KEY=hunter2secret", "Authorization: Bearer hunter2secret"]) {
      expect(scrub(text).text).toContain("***");
      expect(scrub(text).text).not.toContain("hunter2secret");
    }
  });

  it("masks credential pairs inside URL queries and flag=KEY=value", () => {
    for (const [text, secret] of [
      ["curl https://h/p?api_key=a1b2c3d4e5f6g7h8i9j0", "a1b2c3d4e5f6g7h8i9j0"],
      ['Invoke-RestMethod "https://h/?apikey=hunter1&password=hunter2"', "hunter"],
      ["Max retries exceeded with url: /v1?api_key=hunter2", "hunter2"],
      ["kubectl create secret generic db --from-literal=password=hunter2", "hunter2"],
      ["docker run --env=API_TOKEN=abcdef123456789 img", "abcdef123456789"],
      ["terraform apply -var=db_password=hunter2", "hunter2"],
      ["helm install x --set=db.password=hunter2", "hunter2"],
      ["curl http://localhost:8080/v1?api_key=a1b2c3d4e5f6g7h8i9j0", "a1b2c3d4e5f6g7h8i9j0"],
      ["curl https://api.example.com:443/v1?password=hunter2", "hunter2"],
      ["with url: https://h/p?api_key=a1b2c3d4e5f6g7h8i9j0", "a1b2c3d4e5f6g7h8i9j0"],
      ["wget --url=https://h/p?password=hunter2", "hunter2"],
      ['{"url":"https://h/p?password=hunter2"}', "hunter2"],
      ["kubectl create secret generic db --from-literal=password=s3cr?tvalue9", "tvalue9"],
    ]) {
      for (const longRuns of [true, false]) expect(scrub(text as string, { longRuns }).text).not.toContain(secret);
    }
    for (const text of ["open https://example.com/p?page=2", "vite --port=8080", "curl http://localhost:8080/v1?page=2"]) expect(scrub(text)).toEqual({ text, scrubbed: false });
  });

  it("masks short password names, JWTs and mysql -p<password>, not ports or BYPASS", () => {
    const jwt = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJkZW1vIn0.c2lnbmF0dXJlLXNhbXBsZQ";
    for (const [text, secret] of [
      ["export DB_PASS=hunter2; npm run migrate", "hunter2"],
      ["$env:PGPASS='hunter2'", "hunter2"],
      ["export MYSQL_PWD=hunter2", "hunter2"],
      ["SMTP_PASS=hunter2 node send.js", "hunter2"],
      [`curl -H "Cookie: session=${jwt}"`, "eyJ"],
      [jwt, "eyJ"],
      ["mysql -u root -phunter2 -h db", "hunter2"],
      ["docker exec -it db mysql -uroot -phunter2", "hunter2"],
      ["kubectl exec -it pod -- mariadb-dump -phunter2 app", "hunter2"],
      ["/usr/bin/mysql -uroot -phunter2 app", "hunter2"],
      ["./mysql -uroot -phunter2 app", "hunter2"],
      [String.raw`C:\xampp\mysql\bin\mysql.exe -u root -phunter2 shop`, "hunter2"],
      [String.raw`.\mysqldump.exe -uroot -phunter2 shop > dump.sql`, "hunter2"],
      [String.raw`& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -phunter2`, "hunter2"],
      ["cd x && C:/xampp/mysql/bin/mysql.exe -uroot -phunter2 shop", "hunter2"],
      ['& "mysql.exe" -uroot -phunter2', "hunter2"],
      ["for db in a b; do\n  if true; then\n            /usr/bin/mysql -uroot -phunter2 $db\n  fi\ndone", "hunter2"],
      ["mysql -h db -u app \\\n  -pS3cretPw9 app < seed.sql", "S3cretPw9"],
      ["/usr/bin/mysql -h db \\\r\n  -u app -pS3cretPw9 app", "S3cretPw9"],
      ["mysql -h db -u app `\n  -pS3cretPw9 app", "S3cretPw9"],
      [String.raw`Local DB: connect with ` + "`" + String.raw`C:\xampp\mysql\bin\mysql.exe -uroot -pS3cretPw9` + "` from the repo root", "S3cretPw9"],
      ["Next: run `/usr/local/mysql/bin/mysql -uapp -pS3cretPw9 app < seed.sql`", "S3cretPw9"],
      ['"$MYSQL_HOME"/bin/mysql -uroot -phunter2', "hunter2"],
      ["SMTP_PASS: hunter2", "hunter2"],
      ["pass=hunter2", "hunter2"],
      ["auth: { user: 'me@x.com', pass: 'hunter2' }", "hunter2"],
      ['{ "pass": "hunter2" }', "hunter2"],
      ["mailer needs pass: 'Sup3rS3cret!' in config", "Sup3rS3cret"],
      ["DB_PASS={s3cr3t-Value} npm run migrate", "s3cr3t"],
      ["SMTP_PASS=[Zx81aa] node send.mjs", "Zx81aa"],
    ]) {
      for (const longRuns of [true, false]) expect(scrub(text as string, { longRuns }).text).not.toContain(secret);
    }
    for (const text of ["docker run -p 8080:80 img", "BYPASS_CACHE=true npm test", "pytest fails from pwd: C:/repo/tests", "vitest --passWithNoTests=true", 'docker run -v "$PWD":/app img',
      "docker run --name mysql-db -p3306:3306 mysql:8", "docker run --name mysql -p3306:3306 mysql:8", "gcc $(mysql_config --cflags) -pthread",
      "gcc -I/usr/include/mysql -pthread -o app app.c", "find /etc/mysql -path '*.cnf' -print",
      'docker run --name "mysql" -p3306:3306 mysql:8', "docker run --name 'mysql' -p8080:80 -d mysql:8", 'docker run -e MYSQL_DATABASE="mysql" -p3306:3306 mysql:8',
      'docker run -d --hostname "mysql" -p3306:3306', 'git log -S "mysql" -p3', "gcc -O2 \\\n  -I/usr/include/mysql -pthread -o app app.c",
      "./configure \\\n  --with-mysql=/usr/local/mysql -prefix=/opt", "make: *** [app] Error 1\ncc -c x.c\n-L/usr/lib/mysql -pthread -lmysqlclient",
      "gcc `mysql_config --cflags --libs` -pthread -o app app.c",
      "ls /etc/mysql -p", "cp ./mysql -p /tmp", String.raw`C:\xampp\mysql\bin\mysql.exe: [Warning] Using a password on the command line interface can be insecure.`,
      "E2 gate. Pass: anchored arm needs at most 2 tool calls; memory.pass=true in summary.json", "First pass: collect the files",
      "--- PASS: TestParseConfig (0.00s)", "{ pass: true }", '{"pass":true}', '{"firstPass":{"tokens":1}}', "s.pass === s.runs", "s.pass == n", "s.pass = []", "firstPass: {"]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    for (const hostile of ["x" + " ".repeat(32_768) + "y", "\n" + " ".repeat(32_768) + "y", "mysql " + "\\\n".repeat(16_384), "mysql " + "`\n ".repeat(10_922),
      "`mysql ".repeat(4_681), ";`/a/".repeat(6_553), ';"/a'.repeat(8_192), "\n/a/a/a/a/a/a/a/a/a/a/a/a/a".repeat(1_260)]) {
      const started = performance.now();
      scrub(hostile);
      expect(performance.now() - started).toBeLessThan(250);
    }
  });

  it("leaves prose after Basic/Bearer alone but masks scheme tokens", () => {
    for (const text of ["Basic Upscaler project architecture decisions", "Visual Basic Scripting", "Digest username", "Run The Basic Upscaler/tools/bench.ps1", "C:/x/The Basic Upscaler/src/x.py"]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    for (const text of ["Basic dXNlcjpwYXNzd29yZA==", "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "Authorization: Basic Upscaler", "Bearer abcdefghijklmnopqrstuvwxyz",
      "Bearer abc123def456/xyz", "Basic dXNl/cjpwYXNz", "Authorization: Basic Upscaler/x", `curl -H "X-Upstream: Basic ywi/ajQ+iX5HpKGDKf8ezbL1F5efJVr5"`,
      "Basic dxnlcg/cGFzcw==", "Bearer abcdefghij/KLMNOP1234567890", "Bearer ya/29a0AfH6SMBx3kq"]) {
      expect(scrub(text, { longRuns: false }).text).toMatch(/(Basic|Bearer) \*\*\*/);
      expect(scrub(text).text).toMatch(/(Basic|Bearer) \*\*\*/);
    }
  });

  it("masks credentials in note bodies and error patterns but keeps commit SHAs", () => {
    const home = tmp();
    const note = createNote(home, {
      text: `Deploy key rotated\n\nOld token=abc123def456 and ghp_${"x".repeat(30)} were in the log; fixed in ${SHA}.`,
      project: "demo",
      errors: ["Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig rejected"],
    });
    const file = readFileSync(note.path, "utf8");
    expect(file).not.toContain("abc123");
    expect(file).not.toContain("ghp_");
    expect(file).not.toContain("eyJhbGci");
    expect(file).toContain(SHA);
    expect(file).toContain("token=***");
  });

  it("masks credentials in the working state and its auto section", () => {
    const home = tmp();
    writeWork(home, "demo", "Goal: ship. api_key=sk-" + "a".repeat(30));
    writeAuto(home, "demo", { ask: "use password: hunter2" });
    const work = readFileSync(join(home, "work", "demo.md"), "utf8");
    expect(work).not.toMatch(/sk-a{30}|hunter2/);
    expect(readWork(home, "demo")?.auto).toBe("- last ask: use password: ***");
    expect(readWork(home, "demo")?.text).toContain("Goal: ship.");
  });

  it("leaves ordinary words, paths and parser errors alone", () => {
    for (const text of [
      "Use the disk-usage-analyzer-config-v2 for this",
      "task-runner-configuration-file",
      "open /home/runner/work/myproject/myproject/package.json",
      "C:/Users/me/Documents/The-Second-Brain/brain/src/omp.ts",
      "SyntaxError: Unexpected token: } at line 3",
    ]) {
      expect(scrub(text)).toEqual({ text, scrubbed: false });
    }
    expect(scrub("key sk-proj-abc123def456ghi789jkl012").text).toBe("key ***");
    expect(scrub("aGVsbG8gd29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IHN0cmluZyE=").text).toBe("***");
  });

  it("the long-run rule stays on for captured output", () => {
    expect(scrub(`blob ${SHA}`).text).not.toContain(SHA);
    expect(scrub(`blob ${SHA}`, { longRuns: false }).text).toContain(SHA);
  });
});

describe("answer", () => {
  it("returns a whole note for its id, only when visible", () => {
    const home = tmp();
    const long = "Headline here\n\n" + "detail ".repeat(200);
    const note = createNote(home, { text: long, project: "demo", evidence: ["src/a.ts"] });
    const { notes } = loadNotes(home);
    const full = answer(notes, note.id, { project });
    expect(full.startsWith(`${note.id} [note, evidence: src/a.ts]\nHeadline here`)).toBe(true);
    expect(estimateTokens(full)).toBeLessThanOrEqual(600);
    expect(full.length).toBeGreaterThan(1000);
    expect(answer(notes, note.id, { project: { id: "other", tags: [], root: null } })).not.toContain("Headline here");
    expect(answer(notes, note.id, { project: { id: "other", tags: [], root: null }, all: true })).toContain("Headline here");
  });

  it("gives the first hit more room than the rest", () => {
    const home = tmp();
    for (const w of ["alpha", "alpha beta", "alpha gamma"]) createNote(home, { text: `${w} rule\n\n${"words ".repeat(150)}`, project: "demo" });
    const hits = recall(loadNotes(home).notes, "alpha rule", { project });
    const lines = renderHits(hits).split("\n");
    expect(lines.length).toBe(hits.length);
    expect(lines[0]?.length).toBe(FIRST_HIT_CHARS);
    for (const line of lines.slice(1)) expect(line.length).toBeLessThanOrEqual(240);

  });
});

describe("duplicate notes", () => {
  it("finds an active note with the same headline in the project or global", () => {
    const home = tmp();
    const first = createNote(home, { text: "Use Node 22.18+\n\nbecause of type stripping", project: "demo" });
    const { notes } = loadNotes(home);
    expect(findSameHeadline(notes, "  use   node 22.18+ \n\nother body", "demo")?.id).toBe(first.id);
    expect(findSameHeadline(notes, "Use Node 22.18+", "other")).toBeUndefined();
    expect(findSameHeadline(notes, "Use Node 24", "demo")).toBeUndefined();
  });

  it("brain note does not write the same learning twice", async () => {
    const home = tmp();
    const out: string[] = [];
    const io = { env: { SECOND_BRAIN_HOME: home, BRAIN_PROJECT: "demo" }, cwd: home, out: (s: string) => out.push(s), err: () => {} };
    await main(["note", "Always run npm ci before tests"], io);
    await main(["note", "  Always  run npm ci before tests  "], io);
    expect(out[1]).toBe(out[0]?.replace("saved", "already noted"));
    expect(loadNotes(home).notes).toHaveLength(1);
  });
});

describe("displayPath", () => {
  it("is relative to the project root inside it, with forward slashes", () => {
    expect(displayPath("/work/app/src/a.ts", "/work/app", "/work/app")).toBe("src/a.ts");
    expect(displayPath("src/b.ts", "/work/app", "/work/app")).toBe("src/b.ts");
    expect(displayPath("/elsewhere/c.ts", "/work/app", "/work/app")).toBe("/elsewhere/c.ts");
    expect(displayPath("/work/application/d.ts", "/work/app", "/work")).toBe("/work/application/d.ts");
    expect(displayPath("x\\y.ts", null, "/w")).toBe("x/y.ts");
  });
});

describe("answer shows a retired note that fits better than anything current", () => {
  it("answers with the active replacement while keeping explicit history reads", async () => {
    const { retireNote } = await import("../src/notes.ts");
    const home = tmp();
    const old = createNote(home, { text: "Hard cap of two workers per session", project: "demo", kind: "decision" });
    const next = createNote(home, { text: "Adaptive fan-out sizes worker pools", project: "demo", kind: "decision" });
    createNote(home, { text: "Session logs rotate daily", project: "demo" });
    retireNote(home, old.id, next.id);
    const { notes } = loadNotes(home);
    const text = answer(notes, "two workers cap", { project });
    expect(text.split("\n")[0]).toContain(next.id);
    expect(text.split("\n")[1]).toContain(`${old.id} [decision] Hard cap of two workers per session (retired`);
    expect(text).toContain(`replaced by ${next.id}`);
    expect(answer(notes, "adaptive fan-out worker pools", { project })).not.toContain("retired");
    expect(answer(notes, "two workers cap", { project, history: true }).split("\n")[0]).toContain(old.id);
  });
});
