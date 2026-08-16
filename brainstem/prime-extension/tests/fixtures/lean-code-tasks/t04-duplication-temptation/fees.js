function flatFee(amount) {
  return Math.round(amount * 0.02 * 100) / 100;
}
function percentFee(amount, pct) {
  return Math.round(amount * (pct / 100) * 100) / 100;
}
module.exports = { flatFee, percentFee };
