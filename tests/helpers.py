"""Shared setup for tests that check made-up lots."""
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rules import ZONES

MAIN = ("MAIN", LineString([(-300, -25), (500, -25)]))


def check(lot, home, zone, home_type="single", neighbors=None, attached=None,
          height=20, floor_area=1000, units=1, rules=None, streets=(), all_buildings=None,
          sections=(), year_built=None, historic=False, near_eisenhower=False, stories=None,
          height_map=None, retail=None, row=None, outbuildings=(), street_setbacks=None,
          townhouse_development=None, residential_abutters=None, alleys=None):
    """Check one lot holding one home, fronting Main St to its south.

    Pass `rules` to use those instead of the zone's own, `streets` to add
    (name, centerline) pairs beside Main St, as for a corner lot, and
    `sections` to give the home roof sections as (shape, height) pairs, and
    `stories` to give its number of stories.
    `year_built` is the year the oldest home went up, `historic` puts the
    lot in a historic district, and `near_eisenhower` puts it within
    1,000 ft of Eisenhower Avenue. `height_map` is the height district
    map's rule for the lot and `retail` whether the home has ground floor shops.
    `row` is the TownhouseRow the home stands in. `outbuildings` are the
    lot's garages and sheds, as Outbuildings indexing into `all_buildings`.
    `street_setbacks` holds section 7-1006 setbacks keyed by street name.
    """
    facts = LotFacts(
        shape=lot,
        area=lot.area,
        rules=rules if rules is not None else ZONES[zone],
        home_type=home_type,
        homes=[Home(shape=home, height=height, floor_area=floor_area,
                    sections=list(sections), stories=stories,
                    ground_floor_retail=retail)],
        lines=classify(lot, neighbors, [MAIN, *streets], "MAIN"),
        units=units,
        all_buildings=[home] if all_buildings is None else all_buildings,
        attached_neighbors=attached,
        residential_abutters=residential_abutters,
        year_built=year_built,
        in_historic_district=historic,
        near_eisenhower_avenue=near_eisenhower,
        height_map=height_map,
        row=row,
        townhouse_development=townhouse_development,
        outbuildings=list(outbuildings),
        street_setbacks=street_setbacks or {},
        alleys=alleys,
    )
    findings = check_lot(facts)
    return {reason.kind for reason in findings.reasons}, findings


def between_neighbors(lot):
    """Lots on both sides and behind, so every edge but the front is shared."""
    x0, y0, x1, y1 = lot.bounds
    return unary_union([box(x0 - 80, y0, x0, y1), box(x1, y0, x1 + 80, y1),
                        box(x0 - 80, y1, x1 + 80, y1 + 100)])
