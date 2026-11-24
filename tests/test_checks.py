"""Rule checks on made-up lots where the right answer is obvious."""
import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.rules import (
    normalize_zone, planned_district_rules, rules_for)

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


def test_flat_roofed_apartment_side_yard_uses_its_full_height():
    # RA asks an apartment building for 1 ft of side yard per 2 ft of height.
    # At 60 ft tall it needs 30 ft; this one is 26 ft from its side line.
    lot = box(0, 0, 200, 200)
    home = box(26, 35, 174, 120)
    kinds, findings = check(lot, home, "RA", home_type="multi",
                            neighbors=between_neighbors(lot), height=60)
    assert "yards" in kinds
    left = next(row for row in findings.results if row.rule == "yard:left")
    assert left.status == "fails" and left.required == pytest.approx(30)


def test_rear_yard_counts_a_flat_roof_at_the_top_and_a_pitched_one_halfway():
    # R-8 asks for 1 ft of rear yard per foot of height. The home is 30 ft
    # to its peak and 27 ft from the rear line. With three stories the
    # roof is flat and needs 30 ft; with two it is a pitched roof, measured
    # halfway between eaves at about 22 ft and the peak: 26 ft.
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 93)
    kinds, findings = check(lot, home, "R-8", neighbors=between_neighbors(lot),
                            height=30, stories=3)
    assert kinds == {"yards"}
    assert _rear_row(findings).required == pytest.approx(30)
    kinds, findings = check(lot, home, "R-8", neighbors=between_neighbors(lot),
                            height=30, stories=2)
    assert kinds == set()
    assert _rear_row(findings).required == pytest.approx(26)


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


def test_historical_rc_bulk_limits_do_not_generate_current_far_failures():
    lot, home = box(0, 0, 100, 100), box(10, 10, 90, 90)
    kinds, findings = check(lot, home, "RC", year_built=1980, floor_area=15000)
    row = next(r for r in findings.results if r.rule == "floor_area")
    assert row.status == "not_checked" and row.required is None
    assert "floor_area" not in kinds


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
    kinds, findings = check(lot, home, "RS", home_type="townhouse",
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


def test_historic_district_loosens_rb_floor_area_for_houses_only():
    assert rules_for("RB", False).max_floor_area_ratio == 0.75
    historic = rules_for("RB", True)
    assert historic.floor_area_ratio_for("townhouse", historic=True) == 1.50
    assert historic.floor_area_ratio_for("multi", historic=True) == 0.75


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
    # The rule for older lots excuses the shortfall, but the row still shows it.
    assert rows["frontage"].required == 18 and rows["frontage"].status == "older_lot"


@pytest.mark.parametrize("zone", ["CRMU/M", "W-1"])
def test_mixed_use_house_on_a_small_lot_is_flagged(zone):
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide: under 5,000 and 50
    kinds, _ = check(lot, box(10, 35, 30, 65), zone, neighbors=between_neighbors(lot))
    assert {"lot_size", "lot_width"} <= kinds


@pytest.mark.parametrize("zone", ["CRMU/L", "CRMU/H", "CRMU/X"])
def test_mixed_use_house_on_a_small_older_lot_is_excused(zone):
    lot = box(0, 0, 40, 100)
    kinds, findings = check(lot, box(10, 35, 30, 65), zone, neighbors=between_neighbors(lot))
    assert not {"lot_size", "lot_width"} & kinds
    rows = {row.rule: row for row in findings.results}
    assert rows["lot_area"].status == rows["width"].status == "older_lot"


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


def test_potomac_yard_fallback_by_area():
    from alx_zoning_illegal_homes.mapper.rules import (planned_district_rules,
                                                       potomac_yard_fallback)
    # East of the tracks: RB south of the Monroe Avenue bridge, CRMU-L north of it.
    assert potomac_yard_fallback(-77.0465, 38.8200, None) == ("RB", {})
    zone, changes = potomac_yard_fallback(-77.0455, 38.8280, None)
    _, _, rules = planned_district_rules("CDD#10", zone=zone, changes=changes)
    assert rules.name == "CRMU-L" and "townhouse" in rules.allowed
    assert not rules.max_height
    assert rules.label == "CRMU-L zone rules for the Piggyback Yard and Slaters Lane"
    # West of the tracks: CSL along Route 1, industrial on the rest.
    assert potomac_yard_fallback(-77.0495, 38.8260, 100) == ("CSL", {})
    assert potomac_yard_fallback(-77.0485, 38.8260, 600) == ("I", {})


def test_crmu_l_townhouse_east_of_the_tracks_gets_no_unplaced_height_cap():
    from alx_zoning_illegal_homes.mapper.rules import (planned_district_rules,
                                                       potomac_yard_fallback)
    zone, changes = potomac_yard_fallback(-77.0455, 38.8280, None)
    _, _, rules = planned_district_rules("CDD#10", zone=zone, changes=changes)
    lot = box(0, 0, 20, 100)
    home = box(0, 20, 20, 75)
    kinds, _ = check(lot, home, "CRMU/L", home_type="townhouse", rules=rules,
                     neighbors=between_neighbors(lot), height=45)
    assert "home_type" not in kinds and "height" not in kinds
    # The Piggyback Yard's 50 ft cap can't be placed, so a taller townhouse isn't flagged for it.
    kinds, findings = check(lot, home, "CRMU/L", home_type="townhouse", rules=rules,
                            neighbors=between_neighbors(lot), height=66, stories=6)
    assert "height" not in kinds
    height = next(r for r in findings.results if r.rule == "height")
    assert "Potomac Yard/Potomac Greens Small Area Plan" in height.explanation


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


@pytest.mark.parametrize("zone", ["OCM(100)", "OCH"])
def test_homes_near_eisenhower_avenue_need_a_special_permit(zone):
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 75)
    kinds, _ = check(lot, home, zone, neighbors=between_neighbors(lot))
    assert "home_type" not in kinds
    kinds, findings = check(lot, home, zone, neighbors=between_neighbors(lot),
                            near_eisenhower=True)
    assert "home_type" in kinds
    assert "would need a special permit from City Council" in findings.reasons[0].text
    assert _home_type_row(findings).status == "fails"
    # The rule is only in these two office zones.
    assert "home_type" not in check(lot, home, "OCM(50)", neighbors=between_neighbors(lot),
                                    near_eisenhower=True)[0]


def test_older_och_homes_near_eisenhower_get_a_note():
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 75)
    kinds, findings = check(lot, home, "OCH", neighbors=between_neighbors(lot),
                            near_eisenhower=True, year_built=1999)
    assert "home_type" in kinds
    assert any("November 9, 1999" in note and "may" in note for note in findings.notes)
    assert "1999" in _home_type_row(findings).explanation
    _, findings = check(lot, home, "OCH", neighbors=between_neighbors(lot),
                        near_eisenhower=True, year_built=2000)
    assert not findings.notes
    # OCM(100) has no such exception.
    _, findings = check(lot, home, "OCM(100)", neighbors=between_neighbors(lot),
                        near_eisenhower=True, year_built=1950)
    assert not findings.notes


def test_south_carlyle_fallback_keeps_the_eisenhower_rule():
    from alx_zoning_illegal_homes.mapper.rules import planned_district_rules
    _, plan, fallback = planned_district_rules("CDD#11")
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 75)
    assert "home_type" in check(lot, home, "OCM(100)", rules=fallback,
                                near_eisenhower=True)[0]
    assert "home_type" not in check(lot, home, "OCM(100)", rules=plan,
                                    near_eisenhower=True)[0]


def test_och_floor_space_depends_on_metro_and_historic_district():
    from alx_zoning_illegal_homes.mapper.rules import office_high_rules
    far, near = office_high_rules(False), office_high_rules(True)
    assert far.floor_area_ratio_for("multi", False) == 1.25
    assert far.floor_area_ratio_for("townhouse", True) == 1.50
    assert far.floor_area_ratio_for("multi", True) == 1.25
    assert near.floor_area_ratio_for("multi", False) == 2.0
    assert near.floor_area_ratio_for("townhouse", True) == 2.0
    lot = box(0, 0, 80, 120)  # 9,600 sq ft
    home = box(20, 35, 60, 75)
    # 15,000 sq ft of floor space is a ratio of about 1.56: under 2.0, over 1.25.
    assert "floor_area" in check(lot, home, "OCH", rules=far, floor_area=15000,
                                 neighbors=between_neighbors(lot))[0]
    assert "floor_area" not in check(lot, home, "OCH", rules=near, floor_area=15000,
                                     neighbors=between_neighbors(lot))[0]


def test_every_home_type_has_a_name():
    from alx_zoning_illegal_homes.mapper.rules import ALL_TYPES, HOME_TYPE_NAMES
    assert set(HOME_TYPE_NAMES) == ALL_TYPES


def test_zones_that_allow_twin_halves_allow_whole_two_unit_houses():
    from alx_zoning_illegal_homes.mapper.rules import RB_HISTORIC, ZONES
    for rules in [*ZONES.values(), RB_HISTORIC]:
        for table in ("allowed", "allowed_if_built_before", "lot_area", "lot_width",
                      "frontage", "side_yard", "max_height"):
            kinds = getattr(rules, table)
            assert ("semi" in kinds) == ("two_unit" in kinds), (rules.name, table)


@pytest.mark.parametrize("zone, area, frontage", [
    ("R-8", 8000, 40), ("R-2-5", 5000, 50), ("RA", 3960, 50), ("RB", 3960, 50),
    ("RM", 2904, 50), ("CD", 1452, 50), ("CL", 5000, 50), ("OCM(50)", 5000, 50),
    ("CRMU/L", 5000, 50), ("CRMU/X", 5000, 50), ("W-1", 5000, 50),
])
def test_two_unit_house_needs_room_for_the_whole_house(zone, area, frontage):
    from alx_zoning_illegal_homes.mapper.rules import ZONES
    rules = ZONES[zone]
    assert rules.lot_area["two_unit"] == area
    assert rules.frontage["two_unit"] == frontage


def test_two_unit_house_on_a_twin_halfs_lot_is_too_small():
    # 40 by 75 ft: 3,000 sq ft, enough for half of a twin in the RB zone
    # (1,980) but not for both halves (3,960).
    lot = box(0, 0, 40, 75)
    halves = [box(8, 20, 20, 50), box(20, 20, 32, 50)]
    kinds, findings = check(lot, halves[0], "RB", home_type="semi",
                            neighbors=between_neighbors(lot), attached=box(-12, 20, 0, 50))
    assert "lot_size" not in kinds
    kinds, findings = check(lot, halves[0], "RB", home_type="two_unit", units=2,
                            neighbors=between_neighbors(lot), all_buildings=halves)
    # The RB zone's rule for older lots excuses it, but the rows keep the
    # whole house's minimums.
    assert not {"lot_size", "lot_width"} & kinds
    rows = {row.rule: row for row in findings.results}
    assert rows["lot_area"].required == 3960 and rows["lot_area"].status == "older_lot"
    assert rows["frontage"].required == 50 and rows["frontage"].status == "older_lot"
    assert rows["lot_area"].name == "Lot size" and "whole two-unit house" in rows["lot_area"].about
    # R-2-5 has no such rule, so there the reasons spell out the whole house.
    kinds, findings = check(lot, halves[0], "R-2-5", home_type="two_unit", units=2,
                            neighbors=between_neighbors(lot), all_buildings=halves)
    assert {"lot_size", "lot_width"} <= kinds
    text = " ".join(r.text for r in findings.reasons)
    assert "requires 5,000 sq ft for a two-unit house" in text
    assert "requires 50 ft for a two-unit house" in text


def test_older_two_unit_house_passes_in_rc():
    lot = box(0, 0, 60, 100)
    _, findings = check(lot, box(10, 20, 50, 60), "RC", home_type="two_unit", units=2,
                        year_built=1950)
    assert _home_type_row(findings).status == "passes"


@pytest.mark.parametrize("zone, allowed", [
    ("R-20", False), ("R-12", False), ("R-8", False), ("R-5", False), ("R-2-5", True),
    ("RA", True), ("RB", True), ("RM", True), ("CD", True), ("CL", True),
    ("OCM(50)", True), ("CRMU/L", True), ("W-1", True),
])
def test_which_zones_let_twin_halves_have_lots_of_their_own(zone, allowed):
    from alx_zoning_illegal_homes.mapper.rules import ZONES
    assert ZONES[zone].split_twin_lots_allowed is allowed


# Half of a twin on a 30 ft lot of its own, its other half attached to the
# west, with a roomy yard on the east.
TWIN_HALF_LOT = box(0, 0, 30, 200)
TWIN_HALF = box(0, 30, 18, 70)
OTHER_HALF = box(-18, 30, 0, 70)


def test_point_contact_is_not_a_split_twin_wall():
    _, findings = check(TWIN_HALF_LOT, box(2, 15, 30, 55), "R-5", home_type="semi",
                        neighbors=between_neighbors(TWIN_HALF_LOT), attached=box(30, 55, 55, 88))
    assert all("lot line through the building" not in r.text for r in findings.reasons)


def _twin_half(zone, home_type="semi"):
    return check(TWIN_HALF_LOT, TWIN_HALF, zone, home_type=home_type,
                 neighbors=between_neighbors(TWIN_HALF_LOT), attached=OTHER_HALF)


def test_twin_half_on_its_own_lot_has_no_side_yard_at_the_shared_wall_in_r5():
    kinds, findings = _twin_half("R-5")
    assert "yards" in kinds
    text = " ".join(r.text for r in findings.reasons)
    assert ("In the R-5 zone the two halves of a twin house must share one lot; "
            "this half has a lot line through the building.") in text
    left = next(r for r in findings.results if r.rule == "yard:left")
    assert left.status == "fails" and left.measured == 0 and left.required == 7
    assert "at least 7.0 ft" in left.explanation
    # Drawn along the stretch of lot line that runs beside the shared wall.
    x0, y0, x1, y1 = left.shapes["strip"].bounds
    assert (x0, x1) == pytest.approx((0, 7)) and y0 < 30 and y1 > 70
    right = next(r for r in findings.results if r.rule == "yard:right")
    assert right.status == "passes"


def test_twin_half_on_its_own_lot_is_fine_at_the_shared_wall_in_r2_5():
    kinds, findings = _twin_half("R-2-5")
    assert "yards" not in kinds
    left = next(r for r in findings.results if r.rule == "yard:left")
    assert left.status == "not_required" and "shares a wall" in left.explanation


def test_whole_two_unit_house_in_r5_needs_no_extra_side_yard():
    lot = box(0, 0, 60, 200)
    halves = [box(12, 30, 30, 70), box(30, 30, 48, 70)]
    kinds, findings = check(lot, unary_union(halves), "R-5", home_type="two_unit",
                            units=2, neighbors=between_neighbors(lot),
                            all_buildings=halves)
    assert "yards" not in kinds


def _rows(findings):
    return {row.rule: row for row in findings.results}


def test_older_undersized_lot_may_hold_a_house():
    lot = box(0, 0, 30, 60)  # 1,800 sq ft and 30 ft wide in RB: under 1,980 and 50
    kinds, findings = check(lot, box(8, 20, 22, 45), "RB",
                            neighbors=between_neighbors(lot), floor_area=1000)
    assert not {"lot_size", "lot_width"} & kinds
    rows = _rows(findings)
    for rule in ("lot_area", "width", "frontage"):
        assert rows[rule].status == "older_lot"
        assert "December 16, 2023" in rows[rule].explanation
    assert rows["lot_area"].measured == 1800 and rows["lot_area"].required == 1980
    assert "about 1,800 sq ft; the RB zone asks 1,980 sq ft" in rows["lot_area"].explanation
    assert any("may still hold a house" in note for note in findings.notes)


def test_marginal_older_lot_fails_only_above_both_floor_space_caps():
    lot, home = box(0, 0, 50, 39), box(10, 10, 40, 30)
    for floor_area, status in [(2400, "not_checked"), (3500, "fails")]:
        kinds, findings = check(lot, home, "RB", floor_area=floor_area)
        assert _rows(findings)["lot_area"].status == "passes"
        assert _rows(findings)["floor_area"].status == status
        assert ("floor_area" in kinds) == (status == "fails")


def test_older_lot_floor_space_is_capped_at_one_and_a_half():
    lot = box(0, 0, 30, 60)  # 1,800 sq ft
    home = box(8, 20, 22, 45)
    # 1.40 times the lot: far over RB's 0.75, but under the older-lot 1.50.
    kinds, findings = check(lot, home, "RB", neighbors=between_neighbors(lot),
                            floor_area=2520)
    assert "floor_area" not in kinds
    row = _rows(findings)["floor_area"]
    assert row.required == 1.5 * 1800
    assert "rule for older lots" in row.explanation and "75%" in row.explanation
    kinds, findings = check(lot, home, "RB", neighbors=between_neighbors(lot),
                            floor_area=3240)  # 1.80 times the lot
    assert "floor_area" in kinds
    assert "older lot" in next(r.text for r in findings.reasons if r.kind == "floor_area")


def test_older_lot_height_is_capped_at_35_ft():
    lot = box(0, 0, 20, 60)  # 1,200 sq ft in RM: under 1,452
    home = box(0, 15, 20, 45)
    # A sloped roof with a 50 ft peak over four stories, measured at 46 ft:
    # under the 45 ft RM allows a sloped roof (with the margin), over 35 ft.
    kinds, findings = check(lot, home, "RM", neighbors=between_neighbors(lot),
                            height=50, stories=4)
    assert "lot_size" not in kinds and "height" in kinds
    row = _rows(findings)["height"]
    assert row.required == 35 and "rule for older lots" in row.explanation
    assert "ridge" not in row.explanation
    roomy = box(0, 0, 30, 60)  # 1,800 sq ft: no excuse needed, RM's own 45 ft applies
    kinds, findings = check(roomy, box(0, 15, 30, 45), "RM",
                            neighbors=between_neighbors(roomy), height=50, stories=4)
    assert "height" not in kinds and _rows(findings)["height"].required == 45


ROOMY_RM_LOT = box(0, 0, 30, 60)  # 1,800 sq ft: RM's own height limits apply
ROOMY_RM_HOME = box(0, 15, 30, 45)


def _roomy_height(zone="RM", **home):
    """Check a house on a lot big enough for the zone. Returns (kinds, height row, findings)."""
    kinds, findings = check(ROOMY_RM_LOT, ROOMY_RM_HOME, zone,
                            neighbors=between_neighbors(ROOMY_RM_LOT), **home)
    return kinds, _rows(findings)["height"], findings


@pytest.mark.parametrize("zone", ["RM", "CD"])
def test_flat_roofed_house_is_held_to_35_ft(zone):
    # Four stories reach nearly to the 42 ft top, so the roof is taken as flat.
    kinds, row, findings = _roomy_height(zone, height=42, stories=4)
    assert "height" in kinds and row.required == 35
    assert "this one looks flat" in findings.reasons[-1].text
    assert "a flat roof has no ridge line" in row.explanation


@pytest.mark.parametrize("zone", ["RM", "CD"])
def test_sloped_roof_gets_45_ft_and_says_it_may_be_held_to_35(zone):
    # A 50 ft peak over four stories is a sloped roof, measured at 46 ft.
    kinds, row, _ = _roomy_height(zone, height=50, stories=4)
    assert "height" not in kinds and row.required == 45
    assert "can't see which way a roof's ridge runs" in row.explanation
    assert "may be held to 35 ft if its roof doesn't qualify" in row.explanation
    assert "At about 46 ft, it would fail the 35 ft limit." in row.explanation


def test_stories_only_cd_height_leaves_roof_qualification_open():
    _, row, _ = _roomy_height(zone="CD", height=None, stories=4.5)
    assert row.measured == 45 and row.required == 45
    assert row.status == "not_checked" and "roof shape is unknown" in row.explanation


def test_rm_apartments_are_subject_to_the_structure_height_limit():
    _, row, _ = _roomy_height(home_type="multi", height=44, stories=4)
    assert row.status == "fails" and row.required == 35


def test_short_sloped_roof_skips_the_would_fail_sentence():
    _, row, _ = _roomy_height(height=30, stories=2)
    assert row.required == 45 and "may be held to 35 ft" in row.explanation
    assert "would fail" not in row.explanation


def test_roof_of_the_tallest_part_decides_the_limit():
    # The main block is a sloped roof measured at 46 ft, the home's height.
    # The 44 ft wing has room for four stories under its top, so it is
    # taken as flat, but the limit is on the whole building.
    main, wing = box(0, 15, 30, 35), box(0, 35, 30, 45)
    kinds, row, _ = _roomy_height(height=50, stories=4, sections=[(main, 50), (wing, 44)])
    assert "height" not in kinds and row.required == 45 and row.measured == 46


def test_cd_apartment_building_keeps_its_50_ft_limit():
    lot = box(0, 0, 120, 120)
    _, findings = check(lot, box(30, 30, 90, 90), "CD", home_type="multi", units=6,
                        neighbors=between_neighbors(lot), height=48, stories=4)
    row = _rows(findings)["height"]
    assert row.required == 50 and "ridge" not in row.explanation


def test_roomy_lot_keeps_the_zones_own_floor_space_limit():
    lot = box(0, 0, 60, 100)
    kinds, findings = check(lot, box(15, 30, 45, 70), "RB",
                            neighbors=between_neighbors(lot), floor_area=6000)
    assert "floor_area" in kinds and _rows(findings)["floor_area"].required == 0.75 * 6000


def test_older_lot_rule_skips_apartments():
    lot = box(0, 0, 40, 100)  # 40 ft wide in RA: apartments need 50
    kinds, findings = check(lot, box(10, 35, 30, 65), "RA", home_type="multi", units=3,
                            neighbors=between_neighbors(lot))
    assert "lot_width" in kinds and _rows(findings)["width"].status == "fails"


def test_crmu_m_is_left_out_of_the_older_lot_rule():
    lot = box(0, 0, 40, 100)
    kinds, findings = check(lot, box(10, 35, 30, 65), "CRMU/M",
                            neighbors=between_neighbors(lot))
    assert "lot_size" in kinds
    assert any("leaves CRMU-M out" in note for note in findings.notes)


def test_planned_district_fallback_uses_the_older_lot_rule():
    _, _, fallback = planned_district_rules("CDD#16")  # James Bland falls back to RB
    lot = box(0, 0, 30, 60)
    kinds, findings = check(lot, box(8, 20, 22, 45), "RB", rules=fallback,
                            neighbors=between_neighbors(lot))
    assert not {"lot_size", "lot_width"} & kinds
    assert _rows(findings)["lot_area"].status == "older_lot"


def test_older_lot_rule_covers_land_per_home_on_a_shared_townhouse_lot():
    lot = box(0, 0, 50, 60)  # 3,000 sq ft for three townhouses: 1,000 each, under 1,980
    kinds, findings = check(lot, box(0, 15, 50, 45), "RB", home_type="townhouse", units=3,
                            neighbors=between_neighbors(lot))
    assert "lot_size" not in kinds
    row = _rows(findings)["lot_area"]
    assert row.name == "Land per home" and row.status == "older_lot"
    assert "of land for each home; the RB zone asks 1,980 sq ft" in row.explanation


def test_outbuilding_allowance_grows_with_lot_size():
    from alx_zoning_illegal_homes.mapper.rules import outbuilding_allowance
    assert outbuilding_allowance(2499) == 100
    assert outbuilding_allowance(2500) == 350
    assert outbuilding_allowance(7999) == 350
    assert outbuilding_allowance(8000) == 600


def _house_with_garage(garage_floor_area, zone="R-8", home_type="single", historic=False):
    """A 9,600 sq ft lot holding a house of 3,000 sq ft and one garage."""
    from alx_zoning_illegal_homes.mapper.checks import Outbuilding
    lot = box(0, 0, 80, 120)
    home, garage = box(20, 35, 60, 75), box(50, 90, 70, 110)
    return check(lot, home, zone, home_type=home_type, neighbors=between_neighbors(lot),
                 floor_area=3000, all_buildings=[home, garage], historic=historic,
                 outbuildings=[Outbuilding(1, garage_floor_area, "garage or shed")])


def test_garage_beyond_the_allowance_counts_toward_floor_space():
    # R-8 allows 35% of 9,600 sq ft, 3,360 sq ft, and fails only past 3,696.
    # The first 600 sq ft of the 1,300 sq ft garage is left out.
    kinds, findings = _house_with_garage(1300)
    assert "floor_area" in kinds
    row = _rows(findings)["floor_area"]
    assert row.measured == 3700
    assert row.buildings == [0, 1]
    assert "a garage or shed of about 1,300 sq ft" in row.explanation
    assert "adds about 700 sq ft" in row.explanation
    reason = next(r.text for r in findings.reasons if r.kind == "floor_area")
    assert "counting about 700 sq ft in garages, sheds" in reason


def test_garage_within_the_allowance_adds_nothing():
    kinds, findings = _house_with_garage(500)
    assert "floor_area" not in kinds
    row = _rows(findings)["floor_area"]
    assert row.measured == 3000
    assert "within the allowance" in row.explanation


def test_garages_are_left_out_where_the_zone_does_not_count_them():
    # The historic districts and RA townhouses count floor space the other way.
    for options in ({"historic": True}, {"zone": "RA", "home_type": "townhouse"}):
        _, findings = _house_with_garage(1300, **options)
        row = _rows(findings)["floor_area"]
        assert row.measured == 3000 and row.buildings == [0]
    _, findings = _house_with_garage(1300, zone="RA")
    assert _rows(findings)["floor_area"].measured == 3700


def test_house_floor_space_row_says_city_records_may_run_low():
    _, findings = _house_with_garage(100)
    assert "finished living space" in _rows(findings)["floor_area"].about


def test_shop_counts_in_full_alongside_an_exempt_shed():
    from alx_zoning_illegal_homes.mapper.checks import Outbuilding
    lot = box(0, 0, 80, 120)
    shapes = [box(20, 35, 60, 75), box(5, 85, 25, 105), box(55, 90, 65, 100)]
    _, findings = check(lot, shapes[0], "R-8", all_buildings=shapes, floor_area=3000,
                        outbuildings=[Outbuilding(1, 400, "commercial building"),
                                      Outbuilding(2, 100, "garage or shed")])
    assert _rows(findings)["floor_area"].measured == 3400


@pytest.mark.parametrize(("development_area", "status"), [(None, "not_checked"),
                         (15000, "passes"), (12000, "fails")])
def test_crmu_x_townhouse_area_belongs_to_the_development(development_area, status):
    from alx_zoning_illegal_homes.mapper.checks import TownhouseDevelopment

    lot = box(0, 0, 20, 60)
    development = (TownhouseDevelopment("Test development", development_area, 10)
                   if development_area is not None else None)
    kinds, findings = check(lot, box(0, 10, 20, 40), "CRMU/X", home_type="townhouse",
                            neighbors=between_neighbors(lot), height=60,
                            townhouse_development=development)
    rows = {row.rule: row for row in findings.results}
    assert "lot_area" not in rows
    row = rows["development_area"]
    assert row.status == status and row.required == 1452
    assert row.measured == (development_area / 10 if development_area is not None else None)
    assert ("lot_size" in kinds) == (status == "fails")
    assert rows["height"].required != 35
