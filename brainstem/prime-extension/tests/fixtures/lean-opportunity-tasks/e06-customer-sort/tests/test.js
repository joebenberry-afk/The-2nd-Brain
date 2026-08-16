const { buildReport } = require("../src/report");
const assert = require("assert");
const out = buildReport("data/customers.csv");
const lines = out.split("\n");
assert.deepStrictEqual(lines, [
  "apple inc (west)",
  "Apple store (south)",
  "Banana corp (east)",
  "cherry ltd (north)",
], out);
console.log("sort tests passed");
