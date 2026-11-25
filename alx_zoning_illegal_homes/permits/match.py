"""Matching permit cases to the lots they cover.

A case is matched to lots four ways, from most to least trusted:

1. parcel: one of the case's parcel IDs is one of the lot's IDs;
2. outline: a site plan outline from the development projects layer covers
   the lot's inner point (every overlapping outline counts, not just the
   smallest);
3. address: one of the case's addresses, tidied by ``normalize_address``,
   one of the addresses of the records stacked on the lot. An address
   written without its direction ("108 ROSEMONT AVE") matches a lot's
   "108 W ROSEMONT AVE" only when no other direction of that address appears
   on any record of any lot;
4. point: one of the case's map points falls inside the lot.

A lot keeps one match per case, made the most trusted way.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

import geopandas as gpd
import shapely
from pyproj import Transformer

from alx_zoning_illegal_homes.mapper.loader import FEET_CRS
from alx_zoning_illegal_homes.permits.catalog import normalize_case

HOW_ORDER = ("parcel", "outline", "address", "point")

STREET_TYPES = {
    "AV": "AVE", "AVE": "AVE", "AVENUE": "AVE",
    "HY": "HWY", "HWY": "HWY", "HIGHWAY": "HWY",
    "ST": "ST", "STREET": "ST",
    "RD": "RD", "ROAD": "RD",
    "DR": "DR", "DRIVE": "DR",
    "LN": "LN", "LA": "LN", "LANE": "LN",
    "PL": "PL", "PLACE": "PL",
    "CT": "CT", "COURT": "CT",
    "BLVD": "BLVD", "BV": "BLVD", "BOULEVARD": "BLVD",
    "CIR": "CIR", "CR": "CIR", "CIRCLE": "CIR",
    "TER": "TER", "TR": "TER", "TERRACE": "TER",
    "WAY": "WAY", "WY": "WAY",
    "SQ": "SQ", "SQUARE": "SQ",
    "PKWY": "PKWY", "PY": "PKWY", "PARKWAY": "PKWY",
    "PLZ": "PLZ", "PZ": "PLZ", "PLAZA": "PLZ",
}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
# Words that mean something else at the start of a street name ("ST STEPHENS RD").
NAME_WORDS = {"ST": "SAINT", "MT": "MOUNT"}
STREET_RENAMES = {"JEFFERSON DAVIS": "RICHMOND"}

_UNIT = re.compile(r"(\s(UNIT|APT|STE|SUITE)\b|#).*$")
_CITY_TAIL = re.compile(
    r"(?:[\s,]+ALEXANDRIA)?[\s,]+(?:VA|VIRGINIA)(?:[\s,]+\d{5}(?:-\d{4})?)?\s*$"
    r"|,\s*ALEXANDRIA\s*$")
_NUMBER = re.compile(r"^(\d+)\s*(.*)$")
_TO_FEET = Transformer.from_crs("EPSG:4326", FEET_CRS, always_xy=True)


@dataclass(frozen=True)
class CaseMatch:
    """One case matched to one lot, and how (see ``HOW_ORDER``)."""
    case: str
    how: str


def normalize_address(text: str | None) -> str | None:
    """Spell an address one way: "<number> <STREET WORDS> <TYPE>".

    Unit parts and a trailing city, state and ZIP code are dropped, the
    street type and directions get one spelling each, and old street names
    get today's name. Returns None when there is no house number or no street.
    """
    if not text:
        return None
    text = re.sub(r"[.,]", " ", _CITY_TAIL.sub("", text.upper()))
    text = _UNIT.sub("", " ".join(text.split()))
    match = _NUMBER.match(text)
    if not match or not match.group(2):
        return None
    number, street = match.groups()
    words = [DIRECTIONS.get(word, word) for word in street.split()]
    if len(words) > 1 and words[-1] in STREET_TYPES:
        words[-1] = STREET_TYPES[words[-1]]
    first = 1 if words[0] in DIRECTIONS.values() else 0
    if first < len(words) - 1:
        words[first] = NAME_WORDS.get(words[first], words[first])
    street = f" {' '.join(words)} "
    for old, new in STREET_RENAMES.items():
        street = street.replace(f" {old} ", f" {new} ")
    return f"{number} {street.strip()}"


def _without_direction(address: str) -> str:
    """Drop the N/S/E/W word after the house number, if there is one."""
    words = address.split()
    if len(words) > 2 and words[1] in DIRECTIONS.values():
        del words[1]
    return " ".join(words)


def _lot_addresses(lots: gpd.GeoDataFrame) -> list[set[str]]:
    """Each lot's lead address plus every stacked record's address, if listed."""
    stacked = lots["addresses"] if "addresses" in lots else [()] * len(lots)
    return [{a for a in [lead, *(others if isinstance(others, list) else ())]
             if isinstance(a, str)}
            for lead, others in zip(lots["address"], stacked)]


def _parcel_key(value) -> str | None:
    """Tidy a parcel ID for comparing; blanks and "0" never match."""
    if value is None:
        return None
    key = str(value).strip().upper().replace(" ", "")
    return key if key and key != "0" else None


def match_cases(lots: gpd.GeoDataFrame, cases: dict[str, dict],
                projects: gpd.GeoDataFrame) -> dict[int, list[CaseMatch]]:
    """Find the cases on each lot, keyed by lot index.

    ``lots`` is in feet with ``address`` and ``parcel_ids`` columns, and
    optionally ``addresses`` for the addresses of every stacked record.
    ``projects`` holds site plan outlines in feet with a ``PERMIT_PLAN_CASE``
    column; their cases are matched even when the catalog lacks them.
    Case points are longitude and latitude. Lots with no match are left out.
    """
    best: dict[int, dict[str, str]] = defaultdict(dict)

    def add(lot, case, how):
        current = best[lot].get(case)
        if current is None or HOW_ORDER.index(how) < HOW_ORDER.index(current):
            best[lot][case] = how

    lot_ids = list(lots.index)
    by_parcel = defaultdict(list)
    for lot, ids in zip(lot_ids, lots["parcel_ids"]):
        for value in ids if isinstance(ids, (list, tuple)) else ():
            key = _parcel_key(value)
            if key:
                by_parcel[key].append(lot)
    by_address = defaultdict(set)
    directional_forms = defaultdict(set)
    for lot, addresses in zip(lot_ids, _lot_addresses(lots)):
        for address in addresses:
            key = normalize_address(address)
            if key:
                by_address[key].add(lot)
                directional_forms[_without_direction(key)].add(key)

    def lots_at(address):
        key = normalize_address(address)
        if key is None:
            return ()
        if key in by_address:
            return by_address[key]
        forms = directional_forms.get(key, ()) if key == _without_direction(key) else ()
        return by_address[next(iter(forms))] if len(forms) == 1 else ()

    lot_shapes = lots.geometry.values
    shape_tree = shapely.STRtree(lot_shapes)
    point_tree = shapely.STRtree(lots.geometry.representative_point().values)

    for case_number, record in cases.items():
        for value in record.get("parcel_ids") or ():
            for lot in by_parcel.get(_parcel_key(value), ()):
                add(lot, case_number, "parcel")
        for address in record.get("addresses") or ():
            for lot in lots_at(address):
                add(lot, case_number, "address")
        points = record.get("points") or ()
        if points:
            xs, ys = _TO_FEET.transform([p[0] for p in points], [p[1] for p in points])
            for hit in shape_tree.query(shapely.points(xs, ys), predicate="within")[1]:
                add(lot_ids[hit], case_number, "point")

    for outline, raw_case in zip(projects.geometry.values, projects["PERMIT_PLAN_CASE"]):
        case_number = normalize_case(raw_case) if isinstance(raw_case, str) else None
        if case_number is None or outline is None or outline.is_empty:
            continue
        for hit in point_tree.query(outline, predicate="contains"):
            add(lot_ids[hit], case_number, "outline")

    return {
        lot: [CaseMatch(case, how) for case, how in sorted(found.items())]
        for lot, found in best.items()
    }
