const { validate_order } = require("./orders");
const assert = require("assert");
assert.strictEqual(validate_order({ quantity: 5, items: ["a"] }), true);
assert.strictEqual(validate_order({ quantity: 0, items: ["a"] }), false);
assert.strictEqual(validate_order({ quantity: -1, items: ["a"] }), false);
assert.strictEqual(validate_order({ quantity: 5, items: [] }), false);
console.log("verify.js PASS — Requirement Ledger verification complete");
