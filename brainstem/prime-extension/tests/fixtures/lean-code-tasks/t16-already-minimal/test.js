const { twice, double } = require("./math");
const assert = require("assert");
assert.strictEqual(twice(4), 8);
assert.strictEqual(double(4), 8);
console.log("math tests passed");
