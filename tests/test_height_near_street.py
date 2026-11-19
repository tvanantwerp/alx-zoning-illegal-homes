"""The height districts' rule tying height to distance from the street's center, on made-up lots.

Every lot here fronts Main St, whose centerline runs 25 ft south of the lot.
"""
import pytest
from shapely.geometry import LineString, box

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import Street, classify
from alx_zoning_illegal_homes.mapper.rule_results import (FAILS, NOT_CHECKED, NOT_REQUIRED,
                                                          PASSES, reason_kind)
from alx_zoning_illegal_homes.mapper.rules import ZONES, planned_district_rules

from .helpers import between_neighbors, check

LOT = box(0, 0, 100, 150)
# 30 ft from Main St's centerline, so 60 ft is allowed at its front wall.
NEAR_HOME = box(10, 5, 90, 60)


def _row(findings):
    return next(r for r in findings.results if r.rule == "height_near_street")


def _apartments(height, home=NEAR_HOME, **extra):
    """Check a flat-roofed apartment building in the RC zone, which allows 150 ft."""
    kinds, findings = check(LOT, home, "RC", home_type="multi", units=20, height=height,
                            neighbors=between_neighbors(LOT), **extra)
    return kinds, _row(findings), findings


def test_tall_building_close_to_the_street_fails():
    kinds, row, findings = _apartments(80)
    assert row.status == FAILS and "height" in kinds
    assert row.measured == 80 and row.required == pytest.approx(60)
    assert findings.reasons[-1].text == (
        "Too tall this close to the street: the home, about 80 ft tall, is about 30 ft "
        "from the center of Main; at most 60 ft is allowed there.")
    assert row.detail == "30 ft from the center of Main"
    assert row.shapes["gap"].length == pytest.approx(30)
    assert row.buildings == [0]


def test_building_within_twice_its_distance_passes():
    _, row, _ = _apartments(55)
    assert row.status == PASSES and row.required == pytest.approx(60)
    assert "about 30 ft from the center of Main" in row.explanation


def test_a_little_over_passes_within_the_margin():
    kinds, row, _ = _apartments(68)
    assert row.status == PASSES and "height" not in kinds
    assert "a little over" in row.explanation
    assert "5 ft of distance" in row.explanation


def test_upper_floors_that_step_back_pass():
    sections = [(box(10, 5, 90, 30), 40.0), (box(10, 30, 90, 60), 100.0)]
    kinds, row, _ = _apartments(100, sections=sections)
    assert row.status == PASSES and "height" not in kinds
    # The 100 ft back part, 55 ft from the center, may be 110 ft tall.
    assert row.measured == 100 and row.required == pytest.approx(110)
    assert "The part of the home closest to its limit" in row.explanation


def test_a_tall_part_too_close_fails_and_names_the_part():
    sections = [(box(10, 5, 90, 30), 90.0), (box(10, 30, 90, 60), 40.0)]
    kinds, row, findings = _apartments(90, sections=sections)
    assert row.status == FAILS
    assert "the part of the home about 90 ft tall is about 30 ft" in findings.reasons[-1].text
    assert row.shapes["part"].equals(box(10, 5, 90, 30))


def test_pitched_roof_is_measured_halfway_up():
    # Two stories: eaves about 22 ft up and a 35 ft peak, so it measures 28.5 ft.
    _, findings = check(LOT, box(10, 1, 90, 60), "R-5", height=35, stories=2,
                        neighbors=between_neighbors(LOT))
    row = _row(findings)
    assert row.measured == pytest.approx(28.5) and row.required == pytest.approx(52)


def test_every_street_a_corner_lot_faces_is_checked():
    oak = ("OAK", LineString([(-25, -300), (-25, 500)]))
    home = box(5, 60, 60, 140)
    kinds, findings = check(LOT, home, "RC", home_type="multi", units=20, height=80,
                            streets=[oak])
    row = _row(findings)
    assert row.status == FAILS and "center of Oak" in findings.reasons[-1].text
    assert row.required == pytest.approx(60)


def _facts(streets, height=80, rules=None):
    lot_lines = classify(LOT, between_neighbors(LOT), streets, "MAIN")
    return LotFacts(shape=LOT, area=LOT.area, rules=rules or ZONES["RC"], home_type="multi",
                    homes=[Home(shape=NEAR_HOME, height=height, floor_area=1000)],
                    lines=lot_lines, units=20, all_buildings=[NEAR_HOME])


NEAR_SIDE = Street("MAIN", LineString([(-300, -25), (500, -25)]), True, "Main Street")
FAR_SIDE = Street("MAIN", LineString([(-300, -85), (500, -85)]), True, "Main Street")


def test_divided_road_center_is_halfway_between_its_two_sides():
    lot_lines = classify(LOT, between_neighbors(LOT), [NEAR_SIDE, FAR_SIDE], "MAIN")
    distance, line = lot_lines.centerlines["MAIN"].measure(NEAR_HOME)
    assert distance == pytest.approx(60)
    assert line.length == pytest.approx(60)


def test_divided_road_lets_a_taller_building_pass():
    row = _row(check_lot(_facts([NEAR_SIDE, FAR_SIDE])))
    assert row.status == PASSES and row.required == pytest.approx(120)
    assert "Main Street is a divided road" in row.explanation


def test_divided_road_with_no_far_side_is_not_checked():
    row = _row(check_lot(_facts([NEAR_SIDE])))
    assert row.status == NOT_CHECKED
    assert "couldn't find the far side" in row.explanation


def test_planned_district_that_sets_the_rule_aside():
    _, plan, _ = planned_district_rules("CDD#2")
    row = _row(check_lot(_facts([("MAIN", LineString([(-300, -25), (500, -25)]))],
                                rules=plan)))
    assert row.status == NOT_REQUIRED and "sets aside" in row.explanation


def test_lot_with_no_street_is_not_checked():
    facts = _facts([])
    row = _row(check_lot(facts))
    assert row.status == NOT_CHECKED


def test_failing_row_counts_as_too_tall():
    assert reason_kind("height_near_street") == "height"


def test_only_the_stretch_of_street_the_lot_faces_counts():
    # Main St bends north past the lot's east side, behind a neighbor, 15 ft from the home.
    bent = ("MAIN", LineString([(-300, -25), (105, -25), (105, 500)]))
    neighbors = between_neighbors(LOT)
    lot_lines = classify(LOT, neighbors, [bent], "MAIN")
    distance, _ = lot_lines.centerlines["MAIN"].measure(box(10, 5, 90, 140))
    assert distance == pytest.approx(30)
