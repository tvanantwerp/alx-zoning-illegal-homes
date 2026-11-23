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

/** Direction words, which a reader may type alone to mean a street named after one. */
const DIRECTIONS = new Set(["NORTH", "SOUTH", "EAST", "WEST"]);

/** Capitals and single spaces, with nothing else changed. */
const tidy = text => String(text || "").toUpperCase().trim().replace(/\s+/g, " ");

/**
 * An address in one standard spelling: capitals, single spaces, short suffixes,
 * "UNIT" for apartments, and a half or a direction split from its house number
 * ("1001/2 DUKE ST" becomes "100 1/2 DUKE ST", "300S UNION ST" becomes "300 S UNION ST").
 */
export function normalizeAddress(text) {
  return String(text || "")
    .toUpperCase()
    .replace(/(\d)1\/2\b/g, "$1 1/2")
    .replace(/\b(\d+)([NSEW])\s/g, "$1 $2 ")
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
 * A fraction or a letter after the house number ("415 1/2", "517 3/4", "307 A", "607A")
 * stays with the number. N, S, E and W are never house-number letters but directions,
 * part of the street, so "105 N UNION ST" and "105 S UNION ST" sort as different streets.
 */
function streetOrder(address) {
  const match = address.match(/^(\d+)[A-Z]?(?:\s+(?:\d\/\d|[A-DF-MO-RT-VX-Z]))?\s+(.*)$/);
  return match ? [match[2], Number(match[1])] : [address, 0];
}

/**
 * The addresses matching what a reader typed, best first. Each match is
 * `{ index, exact }`, where `index` points into `addresses`.
 *
 * Best are exact matches, then addresses that start with the query, then ones
 * containing it. Within each, a query that ends on a whole word ("PRINCE" in
 * "PRINCE ST") beats one that stops partway through a word ("PRINCESS ST").
 * Pass `normalized` to reuse addresses that were already run through `normalizeAddress`.
 *
 * When several lots share an address, only one is listed, unless `preferred`
 * picks out some of them (lots that were checked, say): then each of those is listed.
 *
 * A direction word typed alone ("West") is matched as a whole word against the
 * addresses as written, so it finds WEST ST rather than every address with a W.
 */
export function findAddresses(addresses, query, normalized = addresses.map(normalizeAddress), preferred = () => false) {
  const lone = tidy(query);
  const asWritten = DIRECTIONS.has(lone);
  const wanted = asWritten ? lone : normalizeAddress(query);
  if (!wanted) return [];
  const searched = asWritten ? addresses.map(tidy) : normalized;
  const hasPreferred = new Set(normalized.filter((address, index) => preferred(index)));
  const seen = new Set();
  const found = [];
  searched.forEach((address, index) => {
    const key = normalized[index];
    if (hasPreferred.has(key) ? !preferred(index) : seen.has(key)) return;
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
    seen.add(key);
    found.push({ index, rank, order: streetOrder(key) });
  });
  found.sort((a, b) => a.rank - b.rank
    || a.order[0].localeCompare(b.order[0])
    || a.order[1] - b.order[1]
    || normalized[a.index].localeCompare(normalized[b.index]));
  return found.map(({ index, rank }) => ({ index, exact: rank === 0 }));
}
