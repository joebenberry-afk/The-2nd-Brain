const { netAmount, grossUp } = require("../lib/tax");
const assert = require("assert");
assert.strictEqual(netAmount(100, 0.075), 92.5);
assert.strictEqual(netAmount(33.33, 0.07), 31.0);
assert.strictEqual(grossUp(92.5, 0.075), 99.44);
assert.strictEqual(grossUp(100, 0.05), 105.0);
console.log("tax tests passed");
