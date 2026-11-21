"""The height district maps, checked on made-up lots."""
import pytest
from shapely.geometry import LineString, box

from alx_zoning_illegal_homes.mapper.rules import HEIGHT_MAP_LIMITS, ZONES, height_map_limit

from .helpers import between_neighbors, check

LOT = box(0, 0, 100, 150)
HOME = box(30, 40, 70, 100)


def _height(zone, area, height, home_type="multi", lot=LOT, neighbors=None, **extra):
    """Check a flat-roofed apartment building of the given height. Returns (kinds, height row)."""
    units = 10 if home_type == "multi" else 1
    kinds, findings = check(lot, HOME, zone, home_type=home_type, units=units, height=height,
                            neighbors=neighbors or between_neighbors(lot), height_map=area,
                            **extra)
    row = next(r for r in findings.results if r.rule == "height")
    return kinds, row, findings


def test_every_area_text_in_the_city_layer_has_a_rule():
    for text in ("By Zone", "30'", "45'", "50'", "66'", "77'", "100'", "30'/50'",
                 "77', 82' if 60% of first floor used for retail", "77' Max. 50' Avg.",
                 "77' (50' along N. Royal)"):
        assert text in HEIGHT_MAP_LIMITS
    with pytest.raises(ValueError):
        height_map_limit("HD4", "999'")


def test_map_limit_lower_than_the_zones_wins():
    area = height_map_limit("HD1", "50'")
    kinds, row, findings = _height("RC", area, 70)
    assert "height" in kinds and row.required == 50
    assert "Old and Historic Alexandria height district allows 50 ft" in findings.reasons[-1].text
    assert "lowest height limit always wins" in row.explanation
    assert "the limit in the RC zone (150 ft)" in row.explanation


def test_zone_limit_lower_than_the_maps_wins():
    area = height_map_limit("HD1", "50'")
    kinds, row, _ = _height("RM", area, 48, home_type="single", stories=4)
    assert row.required == 45
    assert row.explanation.startswith("The limit in the RM zone (45 ft) is lower than")


def test_by_zone_area_keeps_the_zones_limit_and_says_nothing_more():
    _, row, _ = _height("RC", height_map_limit("HD6", "By Zone"), 70)
    assert row.required == 150 and "height district" not in (row.explanation or "")


def test_zone_whose_height_is_the_maps_is_now_checked():
    kinds, row, _ = _height("W-1", height_map_limit("HD3", "30'/50'"), 45)
    assert "height" in kinds and row.required == 30
    assert "takes its height limit from the height district map" in row.explanation


def test_zone_whose_height_comes_from_a_plan_says_so():
    _, row, _ = _height("CDX", height_map_limit("HD4", "66'"), 40)
    assert row.status == "not_checked" and row.required == 66
    assert "Old Town North Small Area Plan, which the map doesn't have" in row.explanation
    _, row, _ = _height("CDX", height_map_limit("HD6", "By Zone"), 40)
    assert row.status == "not_checked"
    assert "height district map sets no limit here" in row.explanation


def test_potomac_river_area_needs_a_permit_above_30_ft():
    kinds, _, findings = _height("W-1", height_map_limit("HD3", "30'/50'"), 45)
    text = next(r.text for r in findings.reasons if r.kind == "height")
    assert "30 ft without a special permit" in text
    assert "up to 50 ft would need a special permit from City Council" in text


@pytest.mark.parametrize("retail, limit", [(True, 82), (False, 77), (None, 77)])
def test_king_street_metro_area_allows_more_with_ground_floor_shops(retail, limit):
    area = height_map_limit("HD5", "77', 82' if 60% of first floor used for retail")
    _, row, _ = _height("RD", area, 85, retail=retail)
    assert row.required == limit and row.status == ("passes" if retail else "fails")
    _, _, findings = _height("RD", area, 95, retail=retail)
    if retail:
        assert "as city records show this one has" in findings.reasons[-1].text
    else:
        assert "which city records don't show here" in findings.reasons[-1].text


def test_north_royal_street_lots_get_50_ft():
    area = height_map_limit("HD4", "77' (50' along N. Royal)")
    royal = ("ROYAL", LineString([(-25, -100), (-25, 400)]))
    # Neighbors to the east and behind only, so the west edge faces North Royal Street.
    east_and_behind = box(100, 0, 180, 150).union(box(-80, 150, 180, 250))
    kinds, row, _ = _height("CDX", area, 60, streets=[royal], neighbors=east_and_behind)
    assert "height" in kinds and row.required == 50
    assert "This lot has one." in row.explanation
    kinds, row, _ = _height("CDX", area, 60)
    assert "height" not in kinds and row.required == 77
    assert "This lot has none, so it gets 77 ft." in row.explanation


def test_average_height_is_left_to_the_tooltip():
    _, row, _ = _height("CRMU/X", height_map_limit("HD4", "77' Max. 50' Avg."), 60,
                        home_type="single", stories=6)
    assert row.required == 77 and "can't judge it lot by lot" in row.explanation


def test_older_lot_limit_gives_way_to_a_lower_map_limit():
    lot = box(0, 0, 20, 60)  # too small for RM, so the 35 ft older-lot limit applies
    kinds, findings = check(lot, box(0, 15, 20, 45), "RM", home_type="townhouse",
                            neighbors=between_neighbors(lot), height=34, stories=3,
                            height_map=height_map_limit("HD3", "30'/50'"))
    row = next(r for r in findings.results if r.rule == "height")
    assert row.required == 30 and "rule for older lots" in row.explanation
    assert "lower than the limit for older lots (35 ft)" in row.explanation


def test_footprint_and_abingdon_amendment():
    import geopandas as gpd
    from alx_zoning_illegal_homes.mapper.analyze import _height_map_areas, _home_height_areas
    areas = gpd.GeoDataFrame({"district": ["HD4", "HD4"], "limit_text": ["50'", "45'"]},
                             geometry=[box(0, 0, 80, 100), box(80, 0, 100, 100)])
    homes = gpd.GeoSeries([box(85, 20, 95, 80), box(10, 10, 40, 40)])
    found = _height_map_areas(homes, areas)
    assert found[0][0][1].height == 45
    assert _home_height_areas("1201 E ABINGDON DR", found[1])[0][1].height == 65
    areas.loc[0, "limit_text"] = "unrecognized"
    with pytest.raises(ValueError):
        _height_map_areas(homes.iloc[:1], areas)


def test_height_sections_on_a_district_boundary_use_their_own_caps():
    from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
    from alx_zoning_illegal_homes.mapper.lot_lines import classify
    west, east = box(30, 40, 50, 100), box(50, 40, 70, 100)
    home = Home(shape=west.union(east), height=70, sections=[(west, 40), (east, 70)],
                height_areas=[(west, height_map_limit("HD4", "45'")),
                              (east, height_map_limit("HD4", "77'"))], floor_area=2000)
    facts = LotFacts(shape=LOT, area=LOT.area, rules=ZONES["RC"],
        home_type="multi", homes=[home], lines=classify(LOT, None, [], None),
        all_buildings=[home.shape])
    row = next(r for r in check_lot(facts).results if r.rule == "height")
    assert row.status == "passes" and row.required == 45 and row.measured == 40
