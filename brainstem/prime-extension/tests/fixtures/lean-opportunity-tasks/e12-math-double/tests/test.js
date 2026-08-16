const { twice, double } = require("../lib/math");
const assert = require("assert");
assert.strictEqual(twice(4), 8);
assert.strictEqual(double(4), 8);
assert.strictEqual(double(0), 0);
console.log("math tests passed");
