const cmd = process.argv[2];
if (cmd === "hello") {
  console.log("hello " + (process.argv[3] ?? "world"));
} else {
  console.log("unknown command");
}
