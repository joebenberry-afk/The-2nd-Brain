const { formatPrice } = require("../lib/format");
function renderLine(label, amount) {
  return `${label}: ${formatPrice(amount)}`;
}
module.exports = { renderLine };
