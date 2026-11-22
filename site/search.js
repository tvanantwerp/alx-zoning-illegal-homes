/**
 * Word swaps that turn the ways people type an address into the short forms
 * the city's records use, so "415 Prince Street" finds "415 PRINCE ST".
 * Both the records and the query go through the same swaps, which is why
 * "SAINT" and "MOUNT", spelled out in the records, are shortened too.
 */
const SHORT_FORMS = {
  STREET: "ST", SAINT: "ST",
  AVENUE: "AVE", AV: "AVE",
  DRIVE: "DR",
  PLACE: "PL",
  ROAD: "RD",
  LANE: "LN", LA: "LN",
  COURT: "CT",
  BOULEVARD: "BLVD",
  PARKWAY: "PKWY",
  CIRCLE: "CIR",
  TERRACE: "TER",
  SQUARE: "SQ",
  HIGHWAY: "HWY",
  QUAY: "QY",
  ALLEY: "ALY",
  PLAZA: "PLZ",
  MOUNT: "MT",
  NORTH: "N", SOUTH: "S", EAST: "E", WEST: "W",
  APARTMENT: "UNIT", APT: "UNIT", STE: "UNIT", SUITE: "UNIT",
};

/** An address in one standard spelling: capitals, single spaces, short suffixes, "UNIT" for apartments. */
export function normalizeAddress(text) {
  return String(text || "")
    .toUpperCase()
    .replace(/#\s*/g, " UNIT ")
    .replace(/[.,]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map(word => SHORT_FORMS[word] || word)
    .join(" ")
    .replace(/\bUNIT UNIT\b/g, "UNIT");
}

/**
 * Sort key that puts "415 PRINCE ST" before "1625 PRINCE ST": street, then house number.
 * A half or a letter after the house number ("415 1/2", "307 A", "607A") stays with the number.
 */
function streetOrder(address) {
  const match = address.match(/^(\d+)[A-Z]?(?:\s+(?:1\/2|[A-Z]))?\s+(.*)$/);
  return match ? [match[2], Number(match[1])] : [address, 0];
}

/**
 * The addresses matching what a reader typed, best first. Each match is
 * `{ index, exact }`, where `index` points into `addresses`.
 *
 * Best are exact matches, then addresses that start with the query, then ones
 * containing it. Within each, a query that ends on a whole word ("PRINCE" in
 * "PRINCE ST") beats one that stops partway through a word ("PRINCESS ST").
 * Addresses repeated across lots are listed once. Pass `normalized` to reuse
 * addresses that were already run through `normalizeAddress`.
 */
export function findAddresses(addresses, query, normalized = addresses.map(normalizeAddress)) {
  const wanted = normalizeAddress(query);
  if (!wanted) return [];
  const seen = new Set();
  const found = [];
  normalized.forEach((address, index) => {
    if (seen.has(address)) return;
    let rank;
    if (address === wanted) rank = 0;
    else {
      let at;
      if (address.startsWith(wanted)) at = 0;
      else {
        const space = address.indexOf(" " + wanted);
        if (space < 0) return;
        at = space + 1;
      }
      const end = at + wanted.length;
      const wholeWord = end === address.length || address[end] === " ";
      rank = (at === 0 ? 1 : 3) + (wholeWord ? 0 : 1);
    }
    seen.add(address);
    found.push({ index, rank, order: streetOrder(address) });
  });
  found.sort((a, b) => a.rank - b.rank
    || a.order[0].localeCompare(b.order[0])
    || a.order[1] - b.order[1]
    || normalized[a.index].localeCompare(normalized[b.index]));
  return found.map(({ index, rank }) => ({ index, exact: rank === 0 }));
}
