const { execFileSync } = require("child_process");
const assert = require("assert");
const pipeline = `node scripts/filter.js error data/*.log | node scripts/stats.js`;
const out = execFileSync("bash", ["-lc", pipeline], { encoding: "utf8" });
assert.ok(out.includes("mean: 13.94"), out); // (10.5+25+8.25+12)/4
assert.ok(out.includes("min: 8.25"), out);
assert.ok(out.includes("max: 25.00"), out);
console.log("pipeline tests passed");
