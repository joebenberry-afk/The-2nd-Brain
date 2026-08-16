const { greet } = require("../src/greet");
const assert = require("assert");
assert.strictEqual(greet("  Bob "), "Hello Bob");
assert.strictEqual(greet("Alice"), "Hello Alice");
console.log("greet tests passed");
