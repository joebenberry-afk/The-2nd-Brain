function validateName(v) {
  if (typeof v !== "string" || v.trim() === "") return false;
  if (v.length > 50) return false;
  return true;
}
function validateTitle(v) {
  if (typeof v !== "string" || v.trim() === "") return false;
  if (v.length > 50) return false;
  return true;
}
function validateCode(v) {
  if (typeof v !== "string" || v.trim() === "") return false;
  if (v.length > 50) return false;
  return true;
}
module.exports = { validateName, validateTitle, validateCode };
