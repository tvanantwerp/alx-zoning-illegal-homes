"""The per-rule results that back the lot pop-up's table."""
from dataclasses import replace

import pytest
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rule_results import (
    RULE_IDS, FAILS, NO_RULE, NOT_CHECKED, NOT_REQUIRED, PASSES, reason_kind, under_special_approval)
from alx_zoning_illegal_homes.mapper.rules import ZONES, planned_district_rules

from .helpers import between_neighbors, check


def rows(findings):
    return {r.rule: r for r in findings.results}


def test_lot_rows_on_a_small_narrow_lot():
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide, R-8
    _, findings = check(lot, box(10, 35, 30, 65), "R-8", neighbors=between_neighbors(lot))
    r = rows(findings)
    assert r["lot_area"].status == FAILS and r["lot_area"].measured == 4000
    assert r["lot_area"].required == 8000 and r["lot_area"].unit == "sq ft"
    assert r["width"].status == FAILS and r["width"].required == 65
    assert r["width"].detail == "measured 30 ft back"   # R-8 width_measured_at
    assert r["width"].shapes["line"].length == pytest.approx(40, abs=0.5)
    assert r["frontage"].status == PASSES and r["frontage"].required == 40
    assert "front lot line" in r["frontage"].about
    assert r["home_type"].status == PASSES
    assert r["home_type"].summary == "detached house allowed in the R-8 zone"


def test_townhouse_in_house_zone_fails_home_type():
    lot = box(0, 0, 80, 120)
    _, findings = check(lot, box(20, 35, 60, 75), "R-8", home_type="townhouse")
    assert rows(findings)["home_type"].status == FAILS


def test_zone_without_lot_size_rule_says_no_rule():
    lot = box(0, 0, 80, 120)
    _, findings = check(lot, box(20, 35, 60, 75), "CRMU/L", home_type="multi")
    row = rows(findings)["lot_area"]
    assert row.status == NO_RULE and "minimum lot size" in row.explanation


def test_no_street_leaves_frontage_and_width_unchecked():
    lot = box(0, 0, 80, 120)
    facts = LotFacts(shape=lot, area=lot.area, rules=ZONES["R-8"], home_type="single",
                     homes=[Home(shape=box(20, 35, 60, 75), height=20, floor_area=1000)],
                     lines=classify(lot, None, [], None), all_buildings=[box(20, 35, 60, 75)])
    r = rows(check_lot(facts))
    assert r["frontage"].status == r["width"].status == NOT_CHECKED
    assert "public street" in r["frontage"].explanation


def test_failing_rows_match_reasons_for_lot_rules():
    lot = box(0, 0, 40, 100)
    _, findings = check(lot, box(10, 35, 30, 65), "R-8", neighbors=between_neighbors(lot))
    failing = {reason_kind(r.rule) for r in findings.results if r.status == FAILS}
    assert failing == {reason.kind for reason in findings.reasons}


YARD_LOT = box(0, 0, 80, 120)   # street to the south, so +x is right
SHARED_WALL_LOT = box(0, 0, 20, 110)
# Streets on the south and west. Neighbors only to the east and behind,
# so the west edge is left open to face the side street.
CORNER_LOT = box(0, 0, 80, 120)
CORNER_NEIGHBORS = unary_union([box(80, 0, 160, 120), box(0, 120, 160, 220)])
SIDE_STREET = ("SIDE", LineString([(-25, -300), (-25, 500)]))
NARROW_RM_LOT = box(0, 0, 20, 100)
RM_LOT = box(0, 0, 30, 100)

YARD_CASES = {
    "thin left side": dict(lot=YARD_LOT, home=box(3, 35, 43, 75), zone="R-8",
                           neighbors=between_neighbors(YARD_LOT)),
    "tall home": dict(lot=YARD_LOT, home=box(11, 35, 51, 75), zone="R-8",
                      neighbors=between_neighbors(YARD_LOT), height=34),
    "shared walls": dict(lot=SHARED_WALL_LOT, home=box(0, 15, 20, 55), zone="RB",
                         home_type="townhouse",
                         neighbors=between_neighbors(SHARED_WALL_LOT),
                         attached=unary_union([box(-20, 15, 0, 55),
                                               box(20, 15, 40, 55)])),
    "end townhouse": dict(lot=SHARED_WALL_LOT, home=box(0, 15, 12, 55), zone="RB",
                          home_type="townhouse",
                          neighbors=between_neighbors(SHARED_WALL_LOT),
                          attached=box(-20, 15, 0, 55)),
    "corner": dict(lot=CORNER_LOT, home=box(20, 35, 60, 75), zone="R-8",
                   neighbors=CORNER_NEIGHBORS, streets=[SIDE_STREET]),
    "roomy": dict(lot=YARD_LOT, home=box(20, 35, 60, 75), zone="R-8",
                  neighbors=between_neighbors(YARD_LOT)),
    "narrow RM": dict(lot=NARROW_RM_LOT, home=box(0.6, 20, 19.4, 60), zone="RM",
                      home_type="townhouse", neighbors=between_neighbors(NARROW_RM_LOT)),
    "RM missing side yard": dict(lot=RM_LOT, home=box(1, 20, 29, 60), zone="RM",
                                 neighbors=between_neighbors(RM_LOT)),
    "near rear": dict(lot=YARD_LOT, home=box(20, 80, 60, 116), zone="R-8",
                      neighbors=between_neighbors(YARD_LOT)),
    "on the line": dict(lot=YARD_LOT, home=box(0.1, 35, 40, 75), zone="R-8",
                        neighbors=between_neighbors(YARD_LOT)),
}


def yard_rows(case):
    return rows(check(**YARD_CASES[case])[1])


def test_every_lot_with_a_front_gets_four_yard_rows():
    r = yard_rows("roomy")
    assert [r[k].name for k in ("yard:front", "yard:left", "yard:right", "yard:rear")] == [
        "Front yard", "Left side yard", "Right side yard", "Rear yard"]
    assert "yard:nearest" not in r


def test_side_yard_too_small_is_drawn_on_the_correct_side():
    r = yard_rows("thin left side")
    assert r["yard:left"].status == FAILS and r["yard:left"].measured == pytest.approx(3)
    assert r["yard:left"].required == 8 and r["yard:left"].detail == "needs"
    assert r["yard:right"].status == PASSES
    assert r["yard:left"].shapes["strip"].bounds[0] == pytest.approx(0)
    assert r["yard:left"].shapes["strip"].bounds[2] == pytest.approx(8)
    assert r["yard:left"].shapes["gap"].length == pytest.approx(3)


def test_tall_home_row_says_height_drives_the_yard():
    row = yard_rows("tall home")["yard:left"]
    assert row.status == FAILS and row.detail == "a home this tall needs" and row.required > 11


def test_yard_row_says_which_height_sized_it():
    lot = box(0, 0, 80, 120)
    home = box(20, 35, 60, 93)
    rear = rows(check(lot, home, "R-8", neighbors=between_neighbors(lot),
                      height=30, stories=3)[1])["yard:rear"]
    assert "setback ratio of 1:1" in rear.explanation
    assert "treated as a flat roof" in rear.explanation
    rear = rows(check(lot, home, "R-8", neighbors=between_neighbors(lot),
                      height=30, stories=2)[1])["yard:rear"]
    assert "roof peak about 30 ft" in rear.explanation
    assert "about 26 ft tall" in rear.explanation and "gable or hip" in rear.explanation


def test_yard_row_set_by_the_minimum_says_nothing_about_height():
    # An 8 ft shed-like home measures under R-8's 8 ft minimum rear yard.
    lot = box(0, 0, 80, 120)
    rear = rows(check(lot, box(20, 35, 60, 75), "R-8", neighbors=between_neighbors(lot),
                      height=8)[1])["yard:rear"]
    assert rear.status == PASSES and rear.required == 8 and not rear.explanation


def test_shared_wall_side_is_not_required():
    r = yard_rows("shared walls")
    for side in ("yard:left", "yard:right"):
        assert r[side].status == NOT_REQUIRED
        assert "shares a wall" in r[side].explanation


def test_end_townhouse_has_one_shared_wall():
    r = yard_rows("end townhouse")
    assert r["yard:left"].status == NOT_REQUIRED     # neighbor attached on the west
    assert r["yard:right"].status == NOT_REQUIRED    # lot under 25 ft wide
    assert "narrower than 25 ft" in r["yard:right"].explanation


def test_corner_lot_has_no_rear_yard_row_checked():
    _, f = check(**YARD_CASES["corner"])
    assert f.measurements["position"] == "corner"
    assert rows(f)["yard:rear"].status == NOT_CHECKED
    assert "corner lot" in rows(f)["yard:rear"].explanation


def test_front_yard_not_checked_in_contextual_zone():
    row = yard_rows("roomy")["yard:front"]
    assert row.status == NOT_CHECKED and row.measured == pytest.approx(35)
    assert "neighboring homes" in row.explanation


def test_narrow_rm_lot_needs_no_side_yards():
    r = yard_rows("narrow RM")
    assert r["yard:left"].status == NOT_REQUIRED
    assert "under 25 ft wide" in r["yard:left"].explanation
    assert "front lot line" in r["yard:front"].explanation


def test_rm_lot_missing_its_one_side_yard_fails_both_thin_sides():
    r = yard_rows("RM missing side yard")
    assert r["yard:left"].status == r["yard:right"].status == FAILS
    assert r["yard:left"].required == 5
    assert r["yard:left"].explanation.endswith("a 5 ft yard on at least one side.")


def test_rear_yard_row_fails_near_the_rear_line():
    r = yard_rows("near rear")
    assert r["yard:rear"].status == FAILS and r["yard:rear"].measured == pytest.approx(4)


def test_home_on_the_line_is_a_mapping_error():
    row = yard_rows("on the line")["yard:left"]
    assert row.status == NOT_CHECKED and "mapping error" in row.explanation


def test_crossing_outline_leaves_yards_unchecked():
    lot = YARD_LOT
    _, f = check(lot, box(-30, 35, 30, 75), "R-8", neighbors=between_neighbors(lot))
    r = rows(f)
    assert r["yard:left"].status == NOT_CHECKED
    assert "crosses the lot line" in r["yard:left"].explanation


def test_no_street_leaves_an_exempt_front_yard_exempt():
    lot, home = YARD_LOT, box(20, 5, 60, 65)
    facts = LotFacts(shape=lot, area=lot.area, rules=ZONES["RD"], home_type="multi",
                     homes=[Home(shape=home, height=20, floor_area=1000)],
                     lines=classify(lot, None, [], None), all_buildings=[home])
    findings = check_lot(facts)
    assert rows(findings)["yard:front"].status == NOT_REQUIRED
    assert "yard:nearest" not in rows(findings)
    assert all(r.kind != "yards" for r in findings.reasons)


def test_rt_townhouse_without_a_street_has_no_frontage_rule():
    lot = YARD_LOT
    home = box(10, 15, 45, 55)
    facts = LotFacts(shape=lot, area=lot.area, rules=ZONES["RT"], home_type="townhouse",
                     homes=[Home(shape=home, height=20, floor_area=1000)],
                     lines=classify(lot, None, [], None), all_buildings=[home])
    result = rows(check_lot(facts))
    assert result["frontage"].status == NO_RULE
    assert result["width"].status == NOT_CHECKED


def test_no_street_leaves_yards_unchecked_but_measures_the_nearest_line():
    lot = YARD_LOT
    facts = LotFacts(shape=lot, area=lot.area, rules=ZONES["R-8"], home_type="single",
                     homes=[Home(shape=box(3, 35, 43, 75), height=20, floor_area=1000)],
                     lines=classify(lot, None, [], None), all_buildings=[box(3, 35, 43, 75)])
    f = check_lot(facts)
    r = rows(f)
    assert r["yard:left"].status == NOT_CHECKED and "public street" in r["yard:left"].explanation
    assert r["yard:nearest"].name == "Closest lot line"
    assert r["yard:nearest"].status == FAILS and r["yard:nearest"].required == 8
    assert r["yard:nearest"].shapes["gap"].length == pytest.approx(3)
    assert {reason.kind for reason in f.reasons} >= {"yards"}


@pytest.mark.parametrize("case", YARD_CASES)
def test_yard_failures_match_reasons(case):
    _, f = check(**YARD_CASES[case])
    failing = {reason_kind(r.rule) for r in f.results if r.status == FAILS}
    assert failing == {reason.kind for reason in f.reasons}


def test_oversized_home_marks_floor_space_and_its_building():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(20, 35, 60, 75), "R-8", neighbors=between_neighbors(lot), floor_area=9000)
    row = rows(f)["floor_area"]
    ratio = ZONES["R-8"].floor_area_ratio_for("single", False)
    assert row.status == FAILS and row.measured == 9000
    assert row.required == pytest.approx(ratio * 9600)
    assert row.buildings == [0]


def test_height_row_carries_the_limit():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(25, 40, 55, 70), "R-8", neighbors=between_neighbors(lot), height=60)
    row = rows(f)["height"]
    assert row.status == FAILS and row.required == ZONES["R-8"].max_height["single"]
    assert row.buildings == [0]


def test_unknown_floor_space_is_not_checked():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(20, 35, 60, 75), "R-8", floor_area=None)
    assert rows(f)["floor_area"].status == NOT_CHECKED


@pytest.mark.parametrize("home_type", ["single", "semi", "townhouse"])
def test_rm_open_space_is_checked_for_every_home_type(home_type):
    lot = box(0, 0, 30, 100)
    _, f = check(lot, box(5, 20, 25, 60), "RM", home_type=home_type,
                 neighbors=between_neighbors(lot))
    row = rows(f)["open_space"]
    assert row.status == PASSES and row.required == pytest.approx(0.35)
    # The 5 ft strips beside the home are too narrow to count.
    assert row.measured == pytest.approx((30 * 20 + 30 * 40) / 3000)
    assert "June 24, 1992" in row.about and "driveway" in row.about


def test_rm_lot_mostly_covered_fails_open_space():
    lot = box(0, 0, 18, 100)
    reasons, f = check(lot, box(0, 10, 18, 90), "RM", home_type="townhouse",
                       neighbors=between_neighbors(lot))
    assert "open_space" in reasons
    assert rows(f)["open_space"].status == FAILS
    assert any("35% must be left open" in r.text for r in f.reasons)


def test_small_rm_lot_needs_at_least_300_sq_ft_open():
    lot = box(0, 0, 16, 50)   # 800 sq ft, so 35% would be only 280 sq ft
    reasons, f = check(lot, box(0, 10, 16, 43.5), "RM", home_type="townhouse",
                       neighbors=between_neighbors(lot))
    row = rows(f)["open_space"]
    assert "open_space" in reasons and row.status == FAILS
    assert row.required == pytest.approx(300 / 800)
    assert any("300 sq ft" in r.text for r in f.reasons)


def test_open_space_zone_gets_an_open_space_row():
    lot = box(0, 0, 80, 120)
    zone = next(z for z, rules in ZONES.items() if rules.min_open_space and not rules.max_coverage)
    kind = next(iter(ZONES[zone].open_space_applies_to or ZONES[zone].allowed))
    _, f = check(lot, box(5, 20, 75, 110), zone, home_type=kind)
    r = rows(f)
    assert "coverage" not in r and r["open_space"].limit == "min"
    # Only the 20 ft front and 10 ft rear strips count; the 5 ft sides don't.
    assert r["open_space"].measured == pytest.approx(80 * 30 / 9600)


BIG_LOT = box(0, 0, 80, 120)
BIG_HOME = box(5, 20, 75, 110)   # covers about 66% of the lot


def open_space_facts(zone, home_type, lot, home, paved=None, parking=None):
    """Facts for a lot with one home and, optionally, paving and parking on it."""
    return LotFacts(
        shape=lot, area=lot.area, rules=ZONES[zone], home_type=home_type,
        homes=[Home(shape=home, height=20, floor_area=1000)],
        lines=classify(lot, None, [], ""), all_buildings=[home],
        paved=paved, parking=parking)


def test_strips_narrower_than_8_ft_are_not_open_space():
    lot = box(0, 0, 40, 100)
    # 7 ft on the left, 13 ft on the right, 30 ft in front and 30 ft behind.
    f = check_lot(open_space_facts("RA", "single", lot, box(7, 30, 27, 70)))
    row = rows(f)["open_space"]
    assert row.measured == pytest.approx((40 * 60 + 13 * 40) / 4000)


@pytest.mark.parametrize("width, counted", [(7.99, 0), (8, 320), (8.01, 320.4)])
def test_eight_foot_open_strip(width, counted):
    lot = box(0, 0, 20, 40)
    home = box(0, 0, 20 - width, 40)
    row = rows(check_lot(open_space_facts("RM", "single", lot, home)))["open_space"]
    assert row.measured * lot.area == pytest.approx(counted)


def test_driveways_and_parking_are_not_open_space():
    lot = box(0, 0, 40, 100)
    home = box(10, 30, 30, 70)
    driveway = box(0, 0, 10, 100)
    f = check_lot(open_space_facts("RA", "single", lot, home, paved=driveway))
    row = rows(f)["open_space"]
    # Left: the driveway. Right: a 10 ft strip beside the home.
    assert row.measured == pytest.approx((30 * 60 + 10 * 40) / 4000)
    assert row.status == PASSES


def test_lot_paved_over_fails_open_space():
    lot = box(0, 0, 100, 100)
    home = box(20, 20, 60, 60)
    parking = lot.difference(home.buffer(5, join_style="mitre"))
    f = check_lot(open_space_facts("RA", "single", lot, home, paved=parking))
    assert rows(f)["open_space"].status == FAILS
    assert any("driveways, parking" in r.text for r in f.reasons)


def test_rd_counts_half_its_parking_as_open_space():
    lot = box(0, 0, 200, 200)              # 40,000 sq ft, 16,000 must be open
    home = box(20, 20, 180, 120)           # 16,000 sq ft
    parking = box(0, 130, 200, 200)        # 14,000 sq ft
    paved = unary_union([parking, box(0, 0, 200, 15)])
    f = check_lot(open_space_facts("RD", "multi", lot, home, paved=paved, parking=parking))
    row = rows(f)["open_space"]
    # Open: two 20 ft strips beside the home and a 10 ft strip behind it. The
    # 5 ft strip in front is too narrow. Half the parking (7,000 sq ft) counts.
    open_land = 20 * 115 * 2 + 160 * 10
    assert row.measured == pytest.approx((open_land + 7000) / 40000)
    assert "Half of" in row.about and "roof" in row.about


def test_rd_parking_counts_no_more_than_90_percent_of_required_open_space():
    lot = box(0, 0, 200, 200)
    home = box(40, 40, 60, 60)
    f = check_lot(open_space_facts("RD", "multi", lot, home, paved=lot, parking=lot))
    row = rows(f)["open_space"]
    assert row.measured == pytest.approx(0.9 * 0.40)
    assert row.status == FAILS
    assert any("sq ft of parking" in r.text for r in f.reasons)


def test_paving_does_not_change_building_coverage():
    lot = box(0, 0, 80, 120)
    f = check_lot(open_space_facts("RT", "townhouse", lot, box(20, 35, 60, 75), paved=lot))
    row = rows(f)["coverage"]
    assert row.measured == pytest.approx(1600 / 9600) and row.status == PASSES


def test_height_unknown_is_not_checked():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=None)
    row = rows(f)["height"]
    assert row.status == NOT_CHECKED and "3D building data" in row.explanation


@pytest.mark.parametrize(("section_size", "peak", "expected"), [
    (10, 20, NOT_CHECKED), (10, 50, FAILS), (50, 20, PASSES),
])
def test_whole_home_height_from_roof_sections(section_size, peak, expected):
    home = box(20, 20, 70, 70)
    section = box(20, 20, 20 + section_size, 20 + section_size)
    _, findings = check(BIG_LOT, home, "R-8", height=None, sections=[(section, peak)])
    row = rows(findings)["height"]
    assert row.status == expected
    if expected == NOT_CHECKED:
        assert "unknown" in row.explanation


def test_no_floor_space_limit_says_no_rule():
    rules = replace(ZONES["R-8"], max_floor_area_ratio=None)
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", rules=rules)
    row = rows(f)["floor_area"]
    assert row.status == NO_RULE and "floor space limit" in row.explanation


def test_no_height_limit_says_no_rule():
    rules = replace(ZONES["R-8"], max_height={})
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", rules=rules)
    row = rows(f)["height"]
    assert row.status == NO_RULE and "height limit" in row.explanation


def test_no_outlines_leaves_open_space_unchecked():
    rules = replace(ZONES["R-8"], max_coverage=0.30)
    _, f = check(BIG_LOT, BIG_HOME, "R-8", rules=rules, all_buildings=[])
    row = rows(f)["coverage"]
    assert row.status == NOT_CHECKED and "no building outlines" in row.explanation


def test_coverage_row_fails_with_every_building():
    rules = replace(ZONES["R-8"], max_coverage=0.30)
    _, f = check(BIG_LOT, BIG_HOME, "R-8", rules=rules)
    row = rows(f)["coverage"]
    assert row.status == FAILS and row.limit == "max" and row.required == 0.30
    assert row.measured == pytest.approx(6300 / 9600) and row.buildings == [0]
    assert "open_space" not in rows(f)


def test_coverage_row_passes_with_every_building():
    rules = replace(ZONES["R-8"], max_coverage=0.30)
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", rules=rules)
    row = rows(f)["coverage"]
    assert row.status == PASSES and row.buildings == [0]


def test_excluded_home_type_has_no_open_space_rule():
    rules = replace(ZONES["R-8"], min_open_space=0.35,
                    open_space_applies_to=frozenset({"multi"}))
    reasons, f = check(BIG_LOT, BIG_HOME, "R-8", rules=rules)
    r = rows(f)
    assert r["coverage"].status == NO_RULE and "open_space" not in r
    assert "open_space" not in reasons


def test_zone_with_both_limits_shows_the_row_that_failed():
    rules = replace(ZONES["R-8"], max_coverage=0.80, min_open_space=0.50)
    reasons, f = check(BIG_LOT, BIG_HOME, "R-8", rules=rules)
    r = rows(f)
    assert "open_space" in reasons
    assert r["open_space"].status == FAILS and "coverage" not in r
    assert r["open_space"].measured == pytest.approx(80 * 30 / 9600)


def test_zone_with_both_limits_shows_coverage_when_both_pass():
    rules = replace(ZONES["R-8"], max_coverage=0.80, min_open_space=0.10)
    reasons, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", rules=rules)
    assert rows(f)["coverage"].status == PASSES and "open_space" not in reasons


ALL_CASES = [
    dict(lot=BIG_LOT, home=BIG_HOME, zone="R-8", rules=replace(ZONES["R-8"], max_coverage=0.30)),
    dict(lot=BIG_LOT, home=BIG_HOME, zone="R-8", all_buildings=[]),
    dict(lot=BIG_LOT, home=BIG_HOME, zone="R-8",
         rules=replace(ZONES["R-8"], max_coverage=0.80, min_open_space=0.50)),
    dict(lot=box(0, 0, 80, 120), home=box(20, 35, 60, 75), zone="R-8"),
    dict(lot=box(0, 0, 80, 120), home=box(20, 35, 60, 75), zone="R-8", floor_area=None, height=None),
    dict(lot=box(0, 0, 80, 120), home=box(20, 35, 60, 75), zone="R-8", home_type="townhouse"),
    dict(lot=box(0, 0, 80, 120), home=box(20, 35, 60, 75), zone="RM", home_type="single",
         neighbors=between_neighbors(box(0, 0, 80, 120))),
    dict(lot=box(0, 0, 80, 120), home=box(20, 35, 60, 75), zone="R-8", floor_area=9000, height=60),
    *YARD_CASES.values(),
]


def test_every_case_has_one_row_per_rule_in_order_and_rows_match_reasons():
    for kwargs in ALL_CASES:
        _, f = check(**kwargs)
        ids = [r.rule for r in f.results]
        assert ids == sorted(ids, key=RULE_IDS.index) and len(ids) == len(set(ids))
        assert ("coverage" in ids) != ("open_space" in ids)
        failing = {reason_kind(r.rule) for r in f.results if r.status == FAILS}
        assert failing == {reason.kind for reason in f.reasons}


def test_special_approval_turns_lot_rules_into_not_required():
    district, plan, fallback = planned_district_rules("CDD#9")
    lot = box(0, 0, 20, 90)
    _, f = check(lot, box(0, 20, 20, 60), "R-8", home_type="townhouse", rules=plan)
    before = [(x.rule, x.status, x.explanation) for x in f.results]
    r = {x.rule: x for x in under_special_approval(f.results, district)}
    assert r["lot_area"].status == NOT_REQUIRED and "site plan" in r["lot_area"].explanation
    assert district.name in r["lot_area"].explanation
    assert r["yard:left"].status == NOT_REQUIRED
    assert r["height"].status == PASSES and r["height"].required == 120
    assert [(x.rule, x.status, x.explanation) for x in f.results] == before


def test_special_approval_explains_other_rows_without_a_rule():
    district, plan, _ = planned_district_rules("CDD#9")
    lot = box(0, 0, 20, 90)
    _, f = check(lot, box(0, 20, 20, 60), "R-8", home_type="townhouse", rules=plan)
    out = under_special_approval(f.results, district)
    for old, new in zip(f.results, out):
        if old.status == NO_RULE and not (old.rule in ("lot_area", "frontage", "width")
                                          or old.rule.startswith("yard:")):
            assert new.status == NO_RULE
            assert new.explanation.endswith(district.plan_summary)


def test_height_passing_within_the_margin_says_so():
    limit = ZONES["R-8"].max_height["single"]
    # Three stories reach nearly to the top, so the roof is taken as flat.
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=limit + 3, stories=3)
    row = rows(f)["height"]
    assert row.status == PASSES
    assert f"About {limit + 3:.0f} ft, a little over the {limit:.0f} ft limit." in row.explanation
    assert "benefit of the doubt" in row.explanation


def test_clearly_passing_row_gets_no_margin_explanation():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=20, stories=2)
    row = rows(f)["height"]
    assert row.status == PASSES and "benefit of the doubt" not in row.explanation


def test_failing_row_gets_no_margin_explanation():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=60)
    row = rows(f)["height"]
    assert row.status == FAILS and "benefit of the doubt" not in row.explanation


def test_pitched_roof_height_row_gives_peak_and_measured_height():
    limit = ZONES["R-8"].max_height["single"]
    # A 2.5-story house with a 37 ft peak: eaves about 22 ft up, so it is
    # measured at 29.5 ft and passes, where the peak alone would have failed.
    kinds, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=37, stories=2.5)
    row = rows(f)["height"]
    assert "height" not in kinds and row.status == PASSES
    assert row.measured == pytest.approx(29.5) and row.required == limit
    assert row.explanation.startswith(
        "Roof peak about 37 ft; measured the ordinance's way, about 30 ft.")
    assert row.detail == "roof peak 37 ft"
    assert "gable or hip" in row.about


def test_too_tall_pitched_roof_reason_names_the_peak():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=50, stories=3)
    assert rows(f)["height"].status == FAILS
    assert f.reasons[0].text.startswith(
        "Too tall: about 42 ft measured the ordinance's way (roof peak about 50 ft)")


def test_apartment_building_roof_is_taken_as_flat():
    lot = box(0, 0, 200, 200)
    rules = ZONES["RA"]
    limit = rules.max_height["multi"]
    _, f = check(lot, box(40, 40, 160, 160), "RA", home_type="multi", units=4,
                 height=limit + 10, stories=2)
    row = rows(f)["height"]
    assert row.status == FAILS and row.measured == limit + 10
    assert row.detail is None


def test_side_yard_short_by_a_roof_overhang_passes_and_says_why():
    # R-5 needs a 7 ft side yard. A wall right at 7 ft with a 30 inch overhang
    # is drawn about 4.5 ft from the line.
    row = rows(check(YARD_LOT, box(4.5, 35, 44.5, 75), "R-5",
                     neighbors=between_neighbors(YARD_LOT))[1])["yard:left"]
    assert row.status == PASSES and row.required == 7
    assert row.explanation.startswith("About 4.5 ft, a little under the 7.0 ft minimum.")
    assert "roof overhangs" in row.explanation


def test_side_yard_short_by_more_than_an_overhang_fails():
    row = rows(check(YARD_LOT, box(4.3, 35, 44.3, 75), "R-5",
                     neighbors=between_neighbors(YARD_LOT))[1])["yard:left"]
    assert row.status == FAILS


def test_counted_side_yard_within_the_margin_mentions_overhangs():
    r = rows(check(RM_LOT, box(2.6, 20, 29, 60), "RM", neighbors=between_neighbors(RM_LOT))[1])
    assert r["yard:left"].status == r["yard:right"].status == PASSES
    assert "roof overhangs" in r["yard:left"].explanation
    assert "roof overhangs" not in r["yard:right"].explanation


def test_lot_size_within_the_margin_uses_square_feet():
    lot = box(0, 0, 80, 98)   # 7,840 sq ft against R-8's 8,000
    _, f = check(lot, box(20, 35, 60, 75), "R-8", neighbors=between_neighbors(lot))
    row = rows(f)["lot_area"]
    assert row.status == PASSES
    assert row.explanation.startswith("About 7,840 sq ft, a little under the 8,000 sq ft minimum.")


def test_width_measured_at_the_street_is_drawn_along_the_front_line():
    rules = replace(ZONES["R-8"], width_measured_at=0)
    lot = box(0, 0, 40, 100)
    _, f = check(lot, box(10, 35, 30, 65), "R-8", rules=rules, neighbors=between_neighbors(lot))
    row = rows(f)["width"]
    assert row.status == FAILS and row.detail == "measured at the street"
    assert row.shapes["line"].length == pytest.approx(40, abs=0.5)
    assert row.shapes["line"].equals(rows(f)["frontage"].shapes["line"])


@pytest.mark.parametrize("zone, home_type", [
    ("RC", "townhouse"), ("RCX", "townhouse"), ("RD", "multi"), ("W-1", "multi"),
    ("KR", "multi")])
def test_front_yard_not_required_where_the_zone_asks_for_none(zone, home_type):
    lot = box(0, 0, 80, 120)
    _, findings = check(lot, box(20, 35, 60, 75), zone, home_type=home_type,
                        neighbors=between_neighbors(lot))
    row = rows(findings)["yard:front"]
    assert row.status == NOT_REQUIRED
    assert "requires no front yard" in row.explanation
    assert "Duke Street" in row.explanation


def test_cdx_houses_get_the_historic_floor_space_limit():
    assert ZONES["CDX"].floor_area_ratio_for("townhouse", historic=True) == 1.50
    assert ZONES["CDX"].floor_area_ratio_for("townhouse", historic=False) == 1.25


def test_w1_houses_still_have_a_front_yard_rule():
    lot = box(0, 0, 80, 120)
    _, findings = check(lot, box(20, 35, 60, 75), "W-1", neighbors=between_neighbors(lot))
    assert rows(findings)["yard:front"].status == NOT_CHECKED
