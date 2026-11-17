"""Shared setup for tests that check made-up lots."""
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rules import ZONES

MAIN = ("MAIN", LineString([(-300, -25), (500, -25)]))


def check(lot, home, zone, home_type="single", neighbors=None, attached=None,
          height=20, floor_area=1000, units=1, rules=None):
    """Check one lot holding one home, fronting Main St to its south.

    Pass `rules` to use those instead of the zone's own.
    """
    facts = LotFacts(
        shape=lot,
        area=lot.area,
        rules=rules if rules is not None else ZONES[zone],
        home_type=home_type,
        homes=[Home(shape=home, height=height, floor_area=floor_area)],
        lines=classify(lot, neighbors, [MAIN], "MAIN"),
        units=units,
        all_buildings=[home],
        attached_neighbors=attached,
    )
    findings = check_lot(facts)
    return {reason.kind for reason in findings.reasons}, findings


def between_neighbors(lot):
    """Lots on both sides and behind, so every edge but the front is shared."""
    x0, y0, x1, y1 = lot.bounds
    return unary_union([box(x0 - 80, y0, x0, y1), box(x1, y0, x1 + 80, y1),
                        box(x0 - 80, y1, x1 + 80, y1 + 100)])
