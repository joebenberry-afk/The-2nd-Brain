const fs = require("fs");
function loadConfig(path) {
  return JSON.parse(fs.readFileSync(path, "utf8"));
}
module.exports = { loadConfig };
