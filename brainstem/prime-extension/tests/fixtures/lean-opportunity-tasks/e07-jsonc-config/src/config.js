const fs = require("fs");
function loadConfig() {
  return JSON.parse(fs.readFileSync("config/server.json5", "utf8"));
}
module.exports = { loadConfig };
