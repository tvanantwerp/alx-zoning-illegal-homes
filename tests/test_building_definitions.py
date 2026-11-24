"""Checks for the ordinance's twin and accessory building definitions."""
import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.analyze import _twin_wall_share
from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, Outbuilding, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rules import ZONES
from tests.helpers import MAIN

LOT = box(0, 0, 100, 120)
HOUSE = box(20, 30, 55, 65)


def test_twin_wall_share_uses_overlap_along_the_shorter_facing_wall():
    first = box(0, 0, 20, 20)
    assert _twin_wall_share(first, box(20.5, 10, 40, 30)) == pytest.approx(0.5)
    assert _twin_wall_share(first, box(20.5, 18, 40, 38)) == pytest.approx(0.1)
    assert _twin_wall_share(first, box(20.5, 20, 40, 40)) == pytest.approx(0)


def test_twin_wall_share_has_a_separate_result():
    facts = LotFacts(LOT, LOT.area, ZONES["RA"], "semi", [Home(HOUSE, height=18)],
                     classify(LOT, None, [MAIN], "MAIN"), all_buildings=[HOUSE],
                     twin_wall_share=0.4)
    findings = check_lot(facts)
    row = next(row for row in findings.results if row.rule == "twin_wall")
    assert row.status == "fails" and row.required == 0.5
    assert any(reason.kind == "home_type" for reason in findings.reasons)


def _accessory_results(home, outbuildings):
    outlines = [HOUSE, box(70, 70, 80, 80), box(70, 90, 80, 100)]
    facts = LotFacts(LOT, LOT.area, ZONES["R-8"], "single", [home],
                     classify(LOT, None, [MAIN], "MAIN"), all_buildings=outlines,
                     outbuildings=outbuildings)
    found = check_lot(facts)
    return {reason.kind for reason in found.reasons}, {row.rule: row for row in found.results}


def test_accessory_size_compares_the_garage_with_the_principal_building():
    home = Home(HOUSE, height=18, stories=1, gross_floor_area=900)
    kinds, rows = _accessory_results(home, [Outbuilding(1, 450, "garage or shed", 32)])
    assert rows["accessory_area"].status == "fails"
    assert rows["accessory_area"].required == 300
    assert rows["accessory_height"].status == "fails"
    assert {"height", "floor_area"} <= kinds


def test_accessory_height_remains_unchecked_if_one_building_lacks_data():
    home = Home(HOUSE, height=20, gross_floor_area=1500)
    _, rows = _accessory_results(home, [Outbuilding(1, 80, "garage or shed", 10),
                                      Outbuilding(2, 80, "garage or shed")])
    assert rows["accessory_height"].status == "not_checked"
    assert rows["accessory_area"].status == "passes"
