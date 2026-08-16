const { execFileSync } = require("child_process");
const assert = require("assert");
const out = execFileSync("node", ["make_table.js"], { encoding: "utf8" });
assert.ok(out.includes("| name | qty |\n| apple | 3 |\n| pear | 5 |"), out);
assert.ok(out.includes("| name | price |\n| apple | 1.5 |\n| banana | 0.8 |"), out);
assert.ok(out.includes("| name | stock |\n| kiwi | 2 |"), out);
console.log("table tests passed");
