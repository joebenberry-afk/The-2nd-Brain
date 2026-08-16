const { loadConfig } = require("./load");
const assert = require("assert");
const cfg = loadConfig("config.json5");
assert.strictEqual(cfg.host, "localhost");
assert.strictEqual(cfg.port, 8080);
console.log("load tests passed");
