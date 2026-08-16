function sortByName(list) {
  return [...list].sort((a, b) => (a.name < b.name ? -1 : 1));
}
module.exports = { sortByName };
