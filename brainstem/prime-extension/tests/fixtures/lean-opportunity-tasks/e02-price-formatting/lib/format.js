function formatPrice(n) {
  return "$" + n.toFixed(2);
}
function formatQty(n) {
  return n.toFixed(0) + " units";
}
module.exports = { formatPrice, formatQty };
