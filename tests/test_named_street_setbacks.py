"""The extra setbacks along a few named streets (section 7-1006)."""
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.rules import (NamedStreetSetback, named_street_setbacks,
                                                   planned_district_rules)

from .helpers import between_neighbors, check

LOT = box(0, 0, 60, 160)  # Main St's centerline runs 25 ft in front of the lot
FROM_CENTER = {"MAIN": NamedStreetSetback("MAIN", "7-1006(B)", 60,
                                          stretch="from Diagonal Road to Quaker Lane")}
FROM_LOT_LINE = {"MAIN": NamedStreetSetback("MAIN", "7-1006(A)", 10, from_centerline=False,
                                            stretch="from Braddock Road north")}


def _street_row(findings):
    rows = [row for row in findings.results if row.rule == "yard:street"]
    return rows[0] if rows else None


def _check(front, setbacks, zone="R-8", **kw):
    """A house whose front wall stands `front` ft behind the front lot line."""
    return check(LOT, box(10, front, 50, front + 50), zone, neighbors=between_neighbors(LOT),
                 street_setbacks=setbacks, **kw)


def test_home_too_close_to_the_centerline_fails():
    kinds, findings = _check(20, FROM_CENTER)  # 45 ft from the centerline
    row = _street_row(findings)
    assert "yards" in kinds
    assert row.status == "fails" and row.required == 60 and round(row.measured) == 45
    assert row.name == "Setback from Main"
    reason = next(r.text for r in findings.reasons if "7-1006" in r.text)
    assert reason.startswith("Too close to Main: about 45 ft from the center of the street")
    assert "section 7-1006(B)" in reason and "from Diagonal Road to Quaker Lane" in reason
    assert row.shapes["gap"] is not None


def test_home_far_enough_back_passes():
    _, findings = _check(40, FROM_CENTER)  # 65 ft
    assert _street_row(findings).status == "passes"


def test_the_margin_gives_the_benefit_of_the_doubt():
    _, findings = _check(32, FROM_CENTER)  # 57 ft, within the 5 ft centerline margin
    row = _street_row(findings)
    assert row.status == "passes" and "a little under" in row.explanation


def test_mount_vernon_avenue_is_measured_from_the_lot_line():
    kinds, findings = _check(4, FROM_LOT_LINE, zone="CL")
    row = _street_row(findings)
    assert row.status == "fails" and round(row.measured) == 4 and row.required == 10
    assert "front lot line" in findings.reasons[-1].text
    _, findings = _check(12, FROM_LOT_LINE, zone="CL")
    assert _street_row(findings).status == "passes"


def test_applies_even_where_the_zone_asks_no_front_yard():
    _, findings = _check(20, FROM_CENTER, zone="RC", home_type="multi")
    assert _street_row(findings).status == "fails"


def test_no_row_off_the_named_streets():
    _, findings = _check(20, {})
    assert _street_row(findings) is None
    _, findings = _check(20, {"DUKE": FROM_CENTER["MAIN"]})  # the lot doesn't face Duke
    assert _street_row(findings) is None
    south_only = {"MAIN": NamedStreetSetback("MAIN", "7-1006(F)", 50, label_starts="South")}
    _, findings = _check(20, south_only)
    assert _street_row(findings) is None


def test_planned_district_plans_set_it_aside():
    _, plan, fallback = planned_district_rules("CDD#9")
    _, findings = _check(20, FROM_CENTER, rules=plan)
    assert _street_row(findings) is None
    _, findings = _check(20, FROM_CENTER, rules=fallback)
    assert _street_row(findings).status == "fails"


def test_which_stretch_a_lot_is_on():
    def rule(lon, lat, street):
        found = named_street_setbacks(lon, lat).get(street)
        return found.distance if found else None
    assert rule(-77.075, 38.806, "DUKE") == 60     # between Diagonal Road and Quaker Lane
    assert rule(-77.110, 38.805, "DUKE") == 75     # west of Quaker Lane
    assert rule(-77.050, 38.804, "DUKE") is None   # Old Town, east of Diagonal Road
    assert rule(-77.100, 38.835, "KING") == 75
    assert rule(-77.060, 38.806, "KING") is None
    assert rule(-77.058, 38.830, "MOUNT VERNON") == 10
    assert rule(-77.058, 38.810, "MOUNT VERNON") is None
    assert rule(-77.120, 38.840, "BEAUREGARD") == 80


def test_a_garage_inside_the_setback_fails_even_when_the_home_passes():
    from alx_zoning_illegal_homes.mapper.checks import Outbuilding
    home = box(10, 70, 50, 120)    # 95 ft from Main's centerline
    garage = box(10, 15, 30, 35)   # 40 ft
    kinds, findings = check(LOT, home, "R-8", neighbors=between_neighbors(LOT),
                            street_setbacks=FROM_CENTER, all_buildings=[home, garage],
                            outbuildings=[Outbuilding(1, 400, "garage or shed")])
    row = _street_row(findings)
    assert "yards" in kinds
    assert row.status == "fails" and round(row.measured) == 40 and row.buildings == [1]
    assert row.explanation.startswith("A garage or shed is about 40 ft")
    reason = next(r.text for r in findings.reasons if "7-1006" in r.text)
    assert reason.startswith("Too close to Main: a garage or shed on the lot is about 40 ft")


def test_an_unmeasured_street_turns_a_pass_into_not_checked():
    from alx_zoning_illegal_homes.mapper import checks
    setbacks = FROM_CENTER | {"SIDE": NamedStreetSetback("SIDE", "7-1006(E)", 80)}
    real = checks._named_street_gaps

    def with_side_unmeasured(facts):
        gaps, unmeasured = real(facts)
        return gaps, unmeasured | {"Side": setbacks["SIDE"]}
    checks._named_street_gaps = with_side_unmeasured
    try:
        kinds, findings = _check(40, setbacks)  # 65 ft from Main passes
    finally:
        checks._named_street_gaps = real
    row = _street_row(findings)
    assert row.status == "not_checked" and "yards" not in kinds


def test_nothing_measured_still_explains_the_rule():
    from alx_zoning_illegal_homes.mapper import checks
    real = checks._named_street_gaps
    checks._named_street_gaps = lambda facts: ([], {"Main": FROM_CENTER["MAIN"]})
    try:
        _, findings = _check(40, FROM_CENTER)
    finally:
        checks._named_street_gaps = real
    row = _street_row(findings)
    assert row.status == "not_checked" and "7-1006(B)" in row.about


def test_lots_judged_under_older_rules_still_get_a_row():
    _, findings = _check(20, FROM_CENTER, zone="RC", year_built=1950)
    row = _street_row(findings)
    assert row.status == "not_checked" and row.name == "Setback from Main"
    assert "rebuilt under the limits in force when it was built" in row.explanation
    rules = [r.rule for r in findings.results]
    assert rules.index("yard:front") < rules.index("yard:street") < rules.index("yard:left")
