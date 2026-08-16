const { loadConfig } = require("../src/config");
const assert = require("assert");
const cfg = loadConfig();
assert.strictEqual(cfg.host, "localhost");
assert.strictEqual(cfg.port, 8080);
assert.strictEqual(cfg.url, "http://example.com//docs"); // "//" inside the string must survive
console.log("config tests passed");
