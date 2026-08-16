const fs = require("fs");
// current: reads a FILE argument (CSV with header date,amount)
const file = process.argv[2];
if (!file) { console.error("usage: node stats.js <csv>"); process.exit(1); }
const rows = fs.readFileSync(file, "utf8").split("\n").filter(Boolean).slice(1);
const amounts = rows.map((r) => Number(r.split(",")[1])).filter((n) => !Number.isNaN(n));
const mean = amounts.reduce((a, b) => a + b, 0) / amounts.length;
const sorted = [...amounts].sort((a, b) => a - b);
console.log(`mean: ${mean.toFixed(2)}`);
console.log(`min: ${sorted[0].toFixed(2)}`);
console.log(`max: ${sorted[sorted.length - 1].toFixed(2)}`);
