"""Detached garage and shed setback checks."""
import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.checks import Outbuilding

from .helpers import between_neighbors, check


def _accessory_yards(buildings, historic=False, zone="R-12"):
    lot = box(0, 0, 100, 150)
    home = box(30, 40, 70, 80)
    kinds, findings = check(
        lot, home, zone, neighbors=between_neighbors(lot), historic=historic,
        all_buildings=[home, *(shape for shape, _, _ in buildings)],
        outbuildings=[Outbuilding(i, area, "garage or shed", height)
                      for i, (_, area, height) in enumerate(buildings, start=1)])
    return kinds, next(row for row in findings.results if row.rule == "yard:accessory")


def test_large_outbuilding_in_a_side_yard_fails():
    kinds, row = _accessory_yards([(box(6, 95, 33, 124), 626, 12)])
    assert "yards" in kinds and row.status == "fails"
    assert row.measured == 6 and row.required == 10 and row.buildings == [1]


def test_yard_exceptions_allow_a_small_shed_and_one_rear_garage():
    kinds, row = _accessory_yards([
        (box(0, 88, 10, 98), 80, 8), (box(4, 105, 24, 130), 400, 13)])
    assert "yards" not in kinds and row.status == "passes"


def test_small_sheds_cannot_be_in_a_required_front_yard():
    kinds, row = _accessory_yards([(box(28, 10, 38, 20), 80, 8)])
    assert "yards" in kinds and row.status == "fails"
    assert "forward of the main building" in row.explanation


@pytest.mark.parametrize("height,x,expected", [
    (12, 2, "not_checked"), (None, 4, "not_checked"), (12, 0.5, "fails"),
])
def test_rear_garage_checks_measurable_conditions_and_reports_unknowns(height, x, expected):
    _, row = _accessory_yards([(box(x, 105, x + 20, 125), 320, height)])
    assert row.status == expected


def test_historic_shed_uses_the_smaller_area_limit():
    _, row = _accessory_yards([(box(2, 110, 12, 120), 80, 8)], historic=True)
    assert row.status == "fails"


def test_shed_beside_a_shared_wall_needs_no_side_yard():
    from shapely.ops import unary_union
    # An interior RA townhouse with a 64 sq ft, 8 ft shed 1 ft from each side lot line.
    lot = box(0, 0, 30, 110)
    home = box(0, 15, 30, 55)
    attached = unary_union([box(-20, 15, 0, 55), box(30, 15, 50, 55)])
    left_shed, right_shed = box(1, 95, 9, 103), box(21, 95, 29, 103)
    kinds, findings = check(
        lot, home, "RA", home_type="townhouse", neighbors=between_neighbors(lot),
        attached=attached, all_buildings=[home, left_shed, right_shed],
        outbuildings=[Outbuilding(1, 64, "garage or shed", 8),
                      Outbuilding(2, 64, "garage or shed", 8)])
    row = next(row for row in findings.results if row.rule == "yard:accessory")
    assert "yards" not in kinds and row.status == "passes"


def test_shed_still_needs_the_side_yard_the_home_needs():
    lot = box(0, 0, 40, 110)
    home = box(8, 15, 32, 55)
    shed = box(1, 95, 9, 103)
    kinds, findings = check(
        lot, home, "RA", home_type="townhouse", neighbors=between_neighbors(lot),
        all_buildings=[home, shed], outbuildings=[Outbuilding(1, 64, "garage or shed", 8)])
    row = next(row for row in findings.results if row.rule == "yard:accessory")
    assert "yards" in kinds and row.status == "fails"
