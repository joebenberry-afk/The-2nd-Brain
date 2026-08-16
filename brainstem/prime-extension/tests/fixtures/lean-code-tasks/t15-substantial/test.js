const { execFileSync } = require("child_process");
const assert = require("assert");
const fs = require("fs");
const path = require("path");

// 1) seeded file: exact stats
let out = execFileSync("node", ["stats.js", "data/transactions.csv"], { encoding: "utf8" });
assert.ok(out.includes("mean: 19.94"), out);
assert.ok(out.includes("median: 17.75"), out);
assert.ok(out.includes("min: 8.25"), out);
assert.ok(out.includes("max: 40.00"), out);

// 2) missing file -> exit 1
let code = 0;
try { execFileSync("node", ["stats.js", "missing.csv"], { stdio: "pipe" }); } catch (e) { code = e.status; }
assert.strictEqual(code, 1);

// 3) empty file (header only) -> exit 2
const empty = path.join("data", "empty.csv");
fs.writeFileSync(empty, "date,amount\n");
try { execFileSync("node", ["stats.js", empty], { stdio: "pipe" }); } catch (e) { code = e.status; }
assert.strictEqual(code, 2);
fs.unlinkSync(empty);

// 4) bad row -> skipped, stats still printed
const bad = path.join("data", "bad.csv");
fs.writeFileSync(bad, "date,amount\n2026-01-01,1\n2026-01-02,oops\n2026-01-03,3\n");
out = execFileSync("node", ["stats.js", bad], { encoding: "utf8" });
assert.ok(out.includes("mean: 2.00"), out);
assert.ok(out.includes("min: 1.00"), out);
assert.ok(out.includes("max: 3.00"), out);
fs.unlinkSync(bad);

console.log("stats tests passed");
