const fs = require("fs");
const pattern = process.argv[2];
if (!pattern) { console.error("usage: node filter.js <regex> <file...>"); process.exit(1); }
const re = new RegExp(pattern);
for (const file of process.argv.slice(3)) {
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (re.test(line)) console.log(line);
  }
}
