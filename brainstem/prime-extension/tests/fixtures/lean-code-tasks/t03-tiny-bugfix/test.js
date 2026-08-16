const { rangeSum } = require("./sum");
const assert = require("assert");
assert.strictEqual(rangeSum(1, 5), 15);
assert.strictEqual(rangeSum(1, 1), 1);
assert.strictEqual(rangeSum(5, 5), 5);
console.log("sum tests passed");
