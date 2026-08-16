const fs = require("fs");
function loadCustomers(path) {
  return fs.readFileSync(path, "utf8").split("\n").filter(Boolean).slice(1)
    .map((line) => { const [name, region] = line.split(","); return { name, region }; });
}
module.exports = { loadCustomers };
