const fs = require("fs");
const assert = require("assert");
// oracle: canonical one-off count of function-name call occurrences in src/
const { execFileSync } = require("child_process");
const canonical = execFileSync("bash", ["-lc",
  "grep -ohE \"[a-zA-Z_][a-zA-Z0-9_]*\\\(\" src/*.js | sed 's/($//' | sort | uniq -c | sort -rn | awk '{print $2, $1}'"], { encoding: "utf8" }).trim();
const got = fs.readFileSync("analysis.txt", "utf8").trim().split("\n").map((l) => l.trim()).filter(Boolean).sort().join("\n");
const want = canonical.split("\n").sort().join("\n");
assert.strictEqual(got, want, `analysis.txt mismatch:\n--- got ---\n${got}\n--- want ---\n${want}`);
console.log("analysis tests passed");
