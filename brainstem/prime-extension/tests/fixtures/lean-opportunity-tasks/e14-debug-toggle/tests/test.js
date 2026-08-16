const { execFileSync } = require("child_process");
const assert = require("assert");
const out = execFileSync("node", ["src/app.js"], { encoding: "utf8" });
assert.ok(out.includes("DEBUG ON"), out);
assert.ok(out.includes("title: svc"), out);
console.log("debug tests passed");
