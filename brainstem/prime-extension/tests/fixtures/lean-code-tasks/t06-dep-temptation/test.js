const { sortByName } = require("./sort");
const assert = require("assert");
const list = [{ name: "apple" }, { name: "Banana" }, { name: "cherry" }];
assert.deepStrictEqual(sortByName(list).map((x) => x.name), ["apple", "Banana", "cherry"]);
console.log("sort tests passed");
