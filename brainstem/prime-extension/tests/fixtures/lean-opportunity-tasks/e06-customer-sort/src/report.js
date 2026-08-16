const { loadCustomers } = require("./customers");
function buildReport(path) {
  const customers = loadCustomers(path);
  customers.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return customers.map((c) => `${c.name} (${c.region})`).join("\n");
}
module.exports = { buildReport };
