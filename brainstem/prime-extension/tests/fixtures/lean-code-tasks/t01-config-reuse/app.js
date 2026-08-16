const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync("config.json", "utf8"));
if (cfg.verbose === true) console.log("debug: starting logger");
console.log("title: " + cfg.title);
