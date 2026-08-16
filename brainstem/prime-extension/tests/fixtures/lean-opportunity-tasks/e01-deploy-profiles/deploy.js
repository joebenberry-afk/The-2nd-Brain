const { run } = require("./lib/runner");
const profile = process.argv[2] ?? "prod";
run(profile);
