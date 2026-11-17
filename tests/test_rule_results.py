"""The per-rule results that back the lot pop-up's table."""
import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rule_results import (
    FAILS, NO_RULE, NOT_CHECKED, PASSES, reason_kind)
from alx_zoning_illegal_homes.mapper.rules import ZONES

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
