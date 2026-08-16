const fs = require("fs");
const path = require("path");
const profiles = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "config", "profiles.json"), "utf8"));
function run(profile) {
  const cfg = profiles[profile] ?? { timeout_ms: profiles.default_timeout_ms };
  console.log(`deploy ${profile} timeout=${cfg.timeout_ms}`);
}
module.exports = { run };
