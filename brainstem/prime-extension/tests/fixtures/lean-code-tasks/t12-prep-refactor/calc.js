function netAmount(gross, taxRate) {
  return gross - Math.round(taxRate * 100) / 100;
}
function grossUp(net, taxRate) {
  return net + Math.round(net * taxRate * 100) / 100;
}
module.exports = { netAmount, grossUp };
