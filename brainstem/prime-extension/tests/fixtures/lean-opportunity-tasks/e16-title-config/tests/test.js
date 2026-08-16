const { execFileSync } = require("child_process");
const assert = require("assert");
const out = execFileSync("node", ["src/app.js"], { encoding: "utf8" });
assert.strictEqual(out.trim(), "title: P3 Eval");
console.log("title tests passed");
