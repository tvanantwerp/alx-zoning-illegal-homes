"""Rule checks on made-up lots where the right answer is obvious."""
import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.rules import normalize_zone, rules_for

from .helpers import between_neighbors, check


@pytest.mark.parametrize("width,corner", [(25, False), (40, True)])
def test_crmu_side_yard_exempts_exact_width_and_corner_end_lots(width, corner):
    from shapely.geometry import LineString
    lot = box(0, 0, width, 100)
    home = box(3, 20, width, 60)
    east = box(width, 0, width + 60, 100)
    side = [("SIDE", LineString([(-25, -100), (-25, 150)]))] if corner else []
    _, findings = check(lot, home, "CRMU/L", home_type="townhouse",
                        neighbors=east if corner else between_neighbors(lot),
                        attached=box(width, 20, width + 20, 60), streets=side)
    assert findings.measurements["position"] == ("corner" if corner else "end")
    assert all(row.status == "not_required" for row in findings.results
               if row.rule in ("yard:left", "yard:right"))


def test_w1_tapered_house_lot_width_is_measured_inland():
    from shapely.geometry import Polygon
    lot = Polygon([(0, 0), (52, 0), (46, 20), (46, 150), (6, 150), (6, 20)])
    _, findings = check(lot, box(10, 20, 40, 80), "W-1", neighbors=between_neighbors(lot))
    rows = {row.rule: row for row in findings.results}
    assert rows["frontage"].measured >= 52
    assert rows["width"].measured == pytest.approx(40)


def test_roomy_house_passes_everything():
    lot = box(0, 0, 80, 120)  # 9,600 sq ft in R-8
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8",
                     neighbors=between_neighbors(lot), floor_area=3000)
    assert kinds == set()


def test_small_narrow_lot_is_flagged():
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide in R-8
    kinds, _ = check(lot, box(10, 35, 30, 65), "R-8",
                     neighbors=between_neighbors(lot))
    assert {"lot_size", "lot_width"} <= kinds
    assert "yards" not in kinds


def test_house_near_side_line_is_flagged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(3, 35, 43, 75), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == {"yards"}
    assert "Side yard" in findings.reasons[0].text


def test_tall_house_needs_a_deeper_side_yard():
    lot = box(0, 0, 80, 120)
    home = box(11, 35, 51, 75)  # 11 ft side yard: fine at 20 ft tall
    assert check(lot, home, "R-8", neighbors=between_neighbors(lot))[0] == set()
    kinds, findings = check(lot, home, "R-8", neighbors=between_neighbors(lot),
                            height=34)
    assert "yards" in kinds
    assert "height" in findings.reasons[0].text


def test_house_near_rear_line_is_flagged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(20, 80, 60, 116), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == {"yards"}
    assert "Rear yard" in findings.reasons[0].text


def _rear_row(findings):
    return next(row for row in findings.results if row.rule == "yard:rear")


def test_low_rear_extension_is_judged_by_its_own_height():
    # Rear lot line at y=120. The 30 ft main block is 40 ft from it; the
    # 14 ft extension is 15 ft from it. Each part clears its own setback
    # ratio, though 15 ft is too little for the full 30 ft height.
    lot = box(0, 0, 80, 120)
    sections = [(box(20, 35, 60, 80), 30.0), (box(20, 80, 60, 105), 14.0)]
    home = box(20, 35, 60, 105)
    kinds, _ = check(lot, home, "R-8", neighbors=between_neighbors(lot), height=30)
    assert "yards" in kinds   # without sections the whole home is 30 ft tall
    kinds, findings = check(lot, home, "R-8", neighbors=between_neighbors(lot),
                            height=30, sections=sections)
    assert kinds == set()
    assert _rear_row(findings).status == "passes"


def test_tall_part_is_measured_from_where_it_stands():
    # The 30 ft main block is 20 ft from the rear line and needs about 25.5 ft.
    # The 10 ft extension behind it is 10 ft away, which is enough for it.
    lot = box(0, 0, 80, 120)
    sections = [(box(20, 35, 60, 100), 30.0), (box(20, 100, 60, 110), 10.0)]
    kinds, findings = check(lot, box(20, 35, 60, 110), "R-8",
                            neighbors=between_neighbors(lot), height=30,
                            sections=sections)
    assert kinds == {"yards"}
    row = _rear_row(findings)
    assert row.status == "fails"
    assert row.measured == pytest.approx(20)
    assert row.required == pytest.approx(25.5)
    assert "part" in findings.reasons[0].text


def test_fixed_minimum_counts_the_closest_part():
    # A low extension 5 ft from the rear line breaks the 8 ft minimum.
    lot = box(0, 0, 80, 120)
    sections = [(box(20, 35, 60, 80), 30.0), (box(20, 80, 60, 115), 8.0)]
    kinds, findings = check(lot, box(20, 35, 60, 115), "R-8",
                            neighbors=between_neighbors(lot), height=30,
                            sections=sections)
    assert kinds == {"yards"}
    row = _rear_row(findings)
    assert row.measured == pytest.approx(5) and row.required == 8


def test_oversized_house_breaks_floor_area_limit():
    lot = box(0, 0, 80, 120)
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8",
                     neighbors=between_neighbors(lot), floor_area=5000)
    assert kinds == {"floor_area"}


def test_townhouse_is_not_allowed_in_a_house_zone():
    lot = box(0, 0, 80, 120)
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8", home_type="townhouse",
                     neighbors=between_neighbors(lot))
    assert "home_type" in kinds


def _home_type_row(findings):
    return next(row for row in findings.results if row.rule == "home_type")


@pytest.mark.parametrize("historic", [False, True])
def test_older_apartments_pass_in_rb(historic):
    lot = box(0, 0, 100, 150)
    home = box(20, 35, 80, 100)
    rules = rules_for("RB", historic)
    kinds, findings = check(lot, home, "RB", home_type="multi", units=8,
                            year_built=1950, rules=rules, historic=historic)
    assert "home_type" not in kinds
    row = _home_type_row(findings)
    assert row.status == "passes"
    assert "1950" in row.explanation and "zoned RB by 1973" in row.explanation
    kinds, _ = check(lot, home, "RB", home_type="multi", units=8, year_built=1978,
                     rules=rules)
    assert "home_type" in kinds
    kinds, _ = check(lot, home, "RB", home_type="multi", units=8, rules=rules)
    assert "home_type" in kinds


@pytest.mark.parametrize("zone", ["RC", "RCX"])
def test_older_houses_pass_in_rc_and_rcx(zone):
    lot = box(0, 0, 40, 100)
    home = box(0, 20, 30, 60)
    kinds, findings = check(lot, home, zone, home_type="semi", year_built=1985,
                            attached=box(-30, 20, 0, 60))
    assert "home_type" not in kinds
    row = _home_type_row(findings)
    assert row.status == "passes" and "deemed to be in compliance" in row.explanation
    lot_size = next(row for row in findings.results if row.rule == "lot_area")
    assert lot_size.status == "not_checked"
    assert "rebuilt under the limits in force when it was built" in lot_size.explanation
    kinds, findings = check(lot, home, zone, home_type="semi", year_built=1999,
                            attached=box(-30, 20, 0, 60))
    assert "home_type" in kinds
    lot_size = next(row for row in findings.results if row.rule == "lot_area")
    assert "rebuilt" not in lot_size.explanation


def test_shared_walls_are_not_missing_side_yards():
    # A 20 ft wide townhouse filling its lot width, neighbors attached.
    lot = box(0, 0, 20, 110)
    home = box(0, 15, 20, 55)
    attached = unary_union([box(-20, 15, 0, 55), box(20, 15, 40, 55)])
    kinds, findings = check(lot, home, "RB", home_type="townhouse",
                            neighbors=between_neighbors(lot), attached=attached)
    assert kinds == set()
    assert findings.measurements["position"] == "interior"


def test_end_townhouse_needs_a_wider_lot():
    lot = box(0, 0, 20, 110)
    home = box(0, 15, 12, 55)
    attached = box(-20, 15, 0, 55)
    kinds, findings = check(lot, home, "RB", home_type="townhouse",
                            neighbors=between_neighbors(lot), attached=attached)
    assert findings.measurements["position"] == "end"
    assert "lot_width" in kinds


def test_home_drawn_on_the_lot_line_is_not_judged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(0.1, 35, 40, 75), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == set()
    assert any("mapping error" in note for note in findings.notes)


def test_zone_labels_from_the_parcel_layer():
    assert normalize_zone("R 8") == "R-8"
    assert normalize_zone("R 2-5") == "R-2-5"
    assert normalize_zone("RB") == "RB"
    assert normalize_zone("RB/R-8") is None
    assert normalize_zone("CDD#9") is None
    assert normalize_zone(None) is None


def test_historic_district_loosens_rb_floor_area():
    assert rules_for("RB", False).max_floor_area_ratio == 0.75
    assert rules_for("RB", True).max_floor_area_ratio == 1.50


def test_king_street_retail_zone_allows_only_apartments():
    lot = box(0, 0, 40, 100)
    kinds, _ = check(lot, box(0, 0, 40, 80), "KR", home_type="townhouse")
    assert "home_type" in kinds
    kinds, _ = check(lot, box(0, 0, 40, 80), "KR", home_type="multi", units=8,
                     floor_area=6000)
    assert "home_type" not in kinds


@pytest.mark.parametrize("ratio", [1.61, 1.48])
def test_eastern_kr_residential_records_use_the_residential_far(ratio):
    from alx_zoning_illegal_homes.mapper.rules import king_street_retail_rules
    lot = box(0, 0, 40, 100)
    for residential, expected in [(True, True), (False, False)]:
        rules = king_street_retail_rules(True, residential_only=residential)
        kinds, _ = check(lot, box(0, 0, 40, 80), "KR", home_type="multi", rules=rules,
                         floor_area=lot.area * ratio)
        assert ("floor_area" in kinds) == expected


def test_king_street_retail_floor_space_is_stricter_east_of_peyton():
    from alx_zoning_illegal_homes.mapper.rules import king_street_retail_rules
    lot = box(0, 0, 40, 100)  # 4,000 sq ft
    home = box(0, 0, 40, 80)
    # 7,200 sq ft of floor space is a ratio of 1.8: under 2.0, well over 1.5.
    kinds, _ = check(lot, home, "KR", home_type="multi", units=8, floor_area=7200,
                     rules=king_street_retail_rules(False))
    assert "floor_area" not in kinds
    kinds, _ = check(lot, home, "KR", home_type="multi", units=8, floor_area=7200,
                     rules=king_street_retail_rules(True))
    assert "floor_area" in kinds


def test_king_street_retail_floor_space_row_explains_the_shops():
    lot = box(0, 0, 40, 100)
    _, findings = check(lot, box(0, 0, 40, 80), "KR", home_type="multi", units=8,
                        floor_area=6000)
    row = next(r for r in findings.results if r.rule == "floor_area")
    assert "shops below included" in row.about


def test_rt_townhouse_needs_no_street_frontage():
    # 23 ft wide where width is measured (6 ft back), but only 15 ft on the
    # street: the lot narrows to a 15 ft stem at the front.
    from shapely.geometry import Polygon
    lot = Polygon([(4, 0), (19, 0), (19, 3), (23, 3), (23, 140), (0, 140), (0, 3), (4, 3)])
    kinds, findings = check(lot, box(1, 20, 22, 60), "RT", home_type="townhouse",
                            neighbors=between_neighbors(lot), floor_area=500)
    rows = {row.rule: row for row in findings.results}
    assert rows["frontage"].status == "no_rule"
    assert rows["width"].status == "passes"
    assert "lot_width" not in kinds


def test_ra_townhouse_frontage_still_follows_width():
    lot = box(0, 0, 14, 140)
    kinds, findings = check(lot, box(0, 20, 14, 60), "RA", home_type="townhouse",
                            neighbors=between_neighbors(lot))
    rows = {row.rule: row for row in findings.results}
    assert rows["frontage"].required == 18 and rows["frontage"].status == "fails"


@pytest.mark.parametrize("zone", ["CRMU/L", "CRMU/M", "CRMU/H", "CRMU/X", "W-1"])
def test_mixed_use_house_on_a_small_lot_is_flagged(zone):
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide: under 5,000 and 50
    kinds, _ = check(lot, box(10, 35, 30, 65), zone, neighbors=between_neighbors(lot))
    assert {"lot_size", "lot_width"} <= kinds


@pytest.mark.parametrize("zone", ["CRMU/L", "CRMU/X", "W-1"])
def test_mixed_use_house_rear_yard_grows_with_height(zone):
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 100)   # 20 ft from the rear line
    assert "yards" not in check(lot, home, zone, neighbors=between_neighbors(lot),
                                height=20)[0]
    kinds, findings = check(lot, home, zone, neighbors=between_neighbors(lot), height=34)
    assert "yards" in kinds and "Rear" in findings.reasons[0].text


def test_crmu_townhouse_has_yards_but_no_lot_size():
    lot = box(0, 0, 20, 100)
    kinds, findings = check(lot, box(0, 20, 20, 95), "CRMU/L", home_type="townhouse",
                            neighbors=between_neighbors(lot))
    rows = {row.rule: row for row in findings.results}
    assert rows["lot_area"].status == "no_rule"
    assert rows["yard:rear"].status == "fails"


def test_duke_street_fallback_floor_space_depends_on_the_metro():
    from alx_zoning_illegal_homes.mapper.rules import (duke_street_floor_area,
                                                       planned_district_rules)
    _, _, near = planned_district_rules("CDD#1", changes=duke_street_floor_area(True))
    _, _, far = planned_district_rules("CDD#1", changes=duke_street_floor_area(False))
    assert near.max_floor_area_ratio == 1.25 and far.max_floor_area_ratio == 1.0
    assert far.max_height["townhouse"] == 77


def test_route_1_properties_fallback_by_street():
    from alx_zoning_illegal_homes.mapper.rules import (planned_district_rules,
                                                       route_1_properties_fallback)
    assert route_1_properties_fallback(True, 50)[0] == "RB"
    zone, changes = route_1_properties_fallback(False, 80)
    _, _, rules = planned_district_rules("CDD#7", zone=zone, changes=changes)
    assert rules.name == "RC" and rules.max_height["multi"] == 45
    assert route_1_properties_fallback(False, 400) == ("OC", {})


def test_triangle_sites_fallback_allows_no_houses():
    from alx_zoning_illegal_homes.mapper.rules import planned_district_rules
    _, _, rules = planned_district_rules("CDD#13")
    assert rules.allowed == frozenset({"multi"})
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(20, 35, 60, 75), "CL", home_type="townhouse",
                            rules=rules)
    assert "home_type" in kinds
    assert "Triangle Sites" in findings.reasons[0].text


def test_braddock_gateway_fallback_near_first_and_fayette():
    from alx_zoning_illegal_homes.mapper.rules import (braddock_gateway_fallback,
                                                       planned_district_rules)
    zone, changes = braddock_gateway_fallback(100)
    _, _, rules = planned_district_rules("CDD#15", zone=zone, changes=changes)
    assert rules.name == "CRMU-H" and rules.max_floor_area_ratio == 1.25
    _, _, rules = planned_district_rules("CDD#15", changes=braddock_gateway_fallback(600)[1])
    assert rules.name == "OCM(50)" and rules.max_floor_area_ratio == 1.50
