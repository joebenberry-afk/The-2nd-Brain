const { utilA } = require("./util");
const { dbGet } = require("./db");
function appMain() {
  utilA();
  dbGet();
  utilA();
  return dbGet();
}
module.exports = { appMain };
