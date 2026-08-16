function rangeSum(a, b) {
  let total = 0;
  for (let i = a; i < b; i++) total += i;
  return total;
}
module.exports = { rangeSum };
