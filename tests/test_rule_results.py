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
    zone = next(z for z, rules in ZONES.items() if "single" in rules.allowed and not rules.lot_area.get("single"))
    _, findings = check(lot, box(20, 35, 60, 75), zone)
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


def test_rm_open_space_not_checked_until_the_rule_exists():
    lot = box(0, 0, 30, 100)
    _, f = check(lot, box(5, 20, 25, 60), "RM", home_type="single", neighbors=between_neighbors(lot))
    r = rows(f)
    assert "coverage" not in r and r["open_space"].status == NOT_CHECKED
    assert "June 24, 1992" in r["open_space"].explanation


def test_open_space_zone_gets_an_open_space_row():
    lot = box(0, 0, 80, 120)
    zone = next(z for z, rules in ZONES.items() if rules.min_open_space and not rules.max_coverage)
    kind = next(iter(ZONES[zone].open_space_applies_to or ZONES[zone].allowed))
    _, f = check(lot, box(5, 20, 75, 110), zone, home_type=kind)
    r = rows(f)
    assert "coverage" not in r and r["open_space"].limit == "min"
    assert r["open_space"].measured == pytest.approx(1 - 70 * 90 / 9600)


BIG_LOT = box(0, 0, 80, 120)
BIG_HOME = box(5, 20, 75, 110)   # covers about 66% of the lot


def test_height_unknown_is_not_checked():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=None)
    row = rows(f)["height"]
    assert row.status == NOT_CHECKED and "3D building data" in row.explanation


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
    assert r["open_space"].measured == pytest.approx(1 - 6300 / 9600)


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
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=limit + 3)
    row = rows(f)["height"]
    assert row.status == PASSES
    assert row.explanation.startswith(f"About {limit + 3:.0f} ft, a little over the {limit:.0f} ft limit.")
    assert "benefit of the doubt" in row.explanation


def test_clearly_passing_row_gets_no_margin_explanation():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=20)
    row = rows(f)["height"]
    assert row.status == PASSES and row.explanation is None


def test_failing_row_gets_no_margin_explanation():
    _, f = check(BIG_LOT, box(20, 35, 60, 75), "R-8", height=60)
    row = rows(f)["height"]
    assert row.status == FAILS and row.explanation is None


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
