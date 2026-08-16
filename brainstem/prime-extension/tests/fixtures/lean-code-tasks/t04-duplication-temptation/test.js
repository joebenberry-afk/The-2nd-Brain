const { flatFee, percentFee, tieredFee } = require("./fees");
const assert = require("assert");
assert.strictEqual(flatFee(100), 2);
assert.strictEqual(percentFee(200, 10), 20);
assert.strictEqual(
  tieredFee(250, [{ limit: 100, rate: 0.02 }, { limit: Infinity, rate: 0.01 }]),
  3.5,
);
assert.strictEqual(tieredFee(50, [{ limit: Infinity, rate: 0.05 }]), 2.5);
console.log("fees tests passed");
