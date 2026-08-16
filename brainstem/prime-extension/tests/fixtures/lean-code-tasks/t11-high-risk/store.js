const fs = require("fs");
const path = require("path");
const DB = path.join("data", "db.json");
function load() {
  try { return JSON.parse(fs.readFileSync(DB, "utf8")); } catch { return {}; }
}
function set(key, value) {
  const db = load();
  db[key] = value;
  fs.writeFileSync(DB, JSON.stringify(db, null, 2));
}
module.exports = { load, set };
