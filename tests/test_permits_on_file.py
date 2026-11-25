"""A permit on file settling a rule row, and the limits on when it may."""
import copy

from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.checks import TownhouseRow
from alx_zoning_illegal_homes.mapper.permits import apply_permits
from alx_zoning_illegal_homes.mapper.rule_results import FAILS, PERMIT_ON_FILE
from alx_zoning_illegal_homes.mapper.rules import height_map_limit
from alx_zoning_illegal_homes.permits.match import CaseMatch

from .helpers import between_neighbors, check

LOT = box(0, 0, 80, 120)
HOME = box(20, 35, 60, 75)


def by_rule(findings, rule):
    return next(row for row in findings.results if row.rule == rule)


def eisenhower_home():
    return check(LOT, HOME, "OCM(100)", neighbors=between_neighbors(LOT),
                 near_eisenhower=True)[1]


def townhouse_row(length):
    return check(LOT, box(0, 35, 20, 75), "OC", home_type="townhouse",
                 row=TownhouseRow(homes=11, length=length))[1]


def narrow_side_yards():
    """An R-5 home 4.3 ft from both side lot lines, where 7 ft is needed."""
    return check(LOT, box(4.3, 35, 75.7, 75), "R-5", neighbors=between_neighbors(LOT))[1]


def tall_apartments(height):
    """Apartments under the 30'/50' height district, where a permit can allow up to 50 ft."""
    lot = box(0, 0, 100, 150)
    return check(lot, box(30, 40, 70, 100), "W-1", home_type="multi", units=10,
                 height=height, neighbors=between_neighbors(lot),
                 height_map=height_map_limit("HD3", "30'/50'"))[1]


def case(number, tags, year=2010):
    return {"case": number, "year": year, "tags": tags}


def test_eisenhower_home_with_permit_on_file_passes():
    findings = eisenhower_home()
    assert by_rule(findings, "home_type").status == FAILS
    apply_permits(findings, [case("SUP2010-00005", ["homes_near_eisenhower"])],
                  [CaseMatch("SUP2010-00005", "parcel")])
    row = by_rule(findings, "home_type")
    assert row.status == PERMIT_ON_FILE and row.permit == {"case": "SUP2010-00005", "how": "parcel"}
    assert row.explanation.endswith("City case SUP2010-00005 is on file for this.")
    assert not [r for r in findings.reasons if r.kind == "home_type"]


def test_permit_cannot_lift_past_its_ceiling():
    findings = townhouse_row(230)
    apply_permits(findings, [case("SUP2001-00009", ["townhouse_row"], 2001)],
                  [CaseMatch("SUP2001-00009", "address")])
    row = by_rule(findings, "row_length")
    assert row.status == FAILS and row.permit is None
    assert "SUP2001-00009" in row.explanation
    assert [r for r in findings.reasons if r.kind == "row_length"]


def test_townhouse_row_within_the_ceiling_is_lifted():
    findings = townhouse_row(190)
    apply_permits(findings, [case("SUP2001-00009", ["townhouse_row"], 2001)],
                  [CaseMatch("SUP2001-00009", "address")])
    assert by_rule(findings, "row_length").status == PERMIT_ON_FILE
    assert not [r for r in findings.reasons if r.kind == "row_length"]


def test_untagged_case_changes_nothing():
    findings = eisenhower_home()
    before = copy.deepcopy(findings)
    apply_permits(findings, [case("SUP2010-00006", [])], [CaseMatch("SUP2010-00006", "parcel")])
    assert findings == before


def test_no_cases_change_nothing():
    findings = eisenhower_home()
    before = copy.deepcopy(findings)
    apply_permits(findings, [], [])
    assert findings == before


def test_variance_lifts_its_yard_even_without_the_flag():
    findings = narrow_side_yards()
    assert by_rule(findings, "yard:left").status == by_rule(findings, "yard:right").status == FAILS
    assert not by_rule(findings, "yard:left").permit_can_allow
    apply_permits(findings, [case("BZA2015-00003", ["variance:yard:left"], 2015)],
                  [CaseMatch("BZA2015-00003", "parcel")])
    assert by_rule(findings, "yard:left").status == PERMIT_ON_FILE
    assert by_rule(findings, "yard:right").status == FAILS
    # The right side still fails, so the yard reasons stay.
    assert [r for r in findings.reasons if r.kind == "yards"]


def test_a_point_match_never_lifts_a_row():
    findings = eisenhower_home()
    apply_permits(findings, [case("SUP2010-00005", ["homes_near_eisenhower"])],
                  [CaseMatch("SUP2010-00005", "point")])
    assert by_rule(findings, "home_type").status == FAILS


def test_an_outline_match_lifts_only_development_wide_tags():
    findings = eisenhower_home()
    apply_permits(findings, [case("DSUP2010-00005", ["homes_near_eisenhower"])],
                  [CaseMatch("DSUP2010-00005", "outline")])
    assert by_rule(findings, "home_type").status == PERMIT_ON_FILE

    findings = narrow_side_yards()
    apply_permits(findings, [case("BZA2015-00003", ["variance:yard:left"], 2015)],
                  [CaseMatch("BZA2015-00003", "outline")])
    assert by_rule(findings, "yard:left").status == FAILS


def test_undersized_lot_needs_a_close_match():
    lot = box(0, 0, 40, 100)  # 4,000 sq ft and 40 ft wide, where R-5 asks 5,000 and 50
    tags = [case("SUP1990-00001", ["undersized_lot"], 1990)]
    findings = check(lot, box(8, 30, 32, 70), "R-5", neighbors=between_neighbors(lot))[1]
    assert by_rule(findings, "lot_area").status == FAILS
    apply_permits(findings, tags, [CaseMatch("SUP1990-00001", "outline")], year_built=1991)
    assert by_rule(findings, "lot_area").status == FAILS
    apply_permits(findings, tags, [CaseMatch("SUP1990-00001", "parcel")], year_built=1991)
    assert by_rule(findings, "lot_area").status == PERMIT_ON_FILE
    assert by_rule(findings, "width").status == PERMIT_ON_FILE
    assert not [r for r in findings.reasons if r.kind in ("lot_size", "lot_width")]


def test_tract_does_not_lift_rows_outside_crmu_zones():
    lot = box(0, 0, 40, 100)
    findings = check(lot, box(8, 30, 32, 70), "R-5", neighbors=between_neighbors(lot),
                     floor_area=8000)[1]
    assert by_rule(findings, "floor_area").status == FAILS
    assert by_rule(findings, "lot_area").status == FAILS
    apply_permits(findings, [case("DSUP2005-00001", ["tract"], 2005)],
                  [CaseMatch("DSUP2005-00001", "parcel")])
    assert by_rule(findings, "floor_area").status == FAILS
    assert by_rule(findings, "lot_area").status == FAILS


def test_tract_lifts_floor_space_in_a_crmu_zone():
    lot = box(0, 0, 100, 150)
    findings = check(lot, box(30, 40, 70, 100), "CRMU/L", home_type="multi", units=10,
                     floor_area=30000, neighbors=between_neighbors(lot))[1]
    assert by_rule(findings, "floor_area").status == FAILS
    apply_permits(findings, [case("DSUP2005-00001", ["tract"], 2005)],
                  [CaseMatch("DSUP2005-00001", "outline")])
    assert by_rule(findings, "floor_area").status == PERMIT_ON_FILE
    assert not [r for r in findings.reasons if r.kind == "floor_area"]


def test_height_permit_lifts_up_to_the_permit_height_only():
    findings = tall_apartments(45)
    apply_permits(findings, [case("SUP2012-00002", ["extra_height"], 2012)],
                  [CaseMatch("SUP2012-00002", "parcel")])
    assert by_rule(findings, "height").status == PERMIT_ON_FILE

    findings = tall_apartments(60)
    apply_permits(findings, [case("SUP2012-00002", ["extra_height"], 2012)],
                  [CaseMatch("SUP2012-00002", "parcel")])
    row = by_rule(findings, "height")
    assert row.status == FAILS and "SUP2012-00002" in row.explanation


def test_closest_match_then_newest_case_wins():
    findings = eisenhower_home()
    cases = [case("SUP2015-00001", ["homes_near_eisenhower"], 2015),
             case("SUP2001-00001", ["homes_near_eisenhower"], 2001),
             case("SUP2005-00001", ["homes_near_eisenhower"], 2005)]
    apply_permits(findings, cases, [CaseMatch("SUP2015-00001", "address"),
                                    CaseMatch("SUP2001-00001", "parcel"),
                                    CaseMatch("SUP2005-00001", "parcel")])
    assert by_rule(findings, "home_type").permit == {"case": "SUP2005-00001", "how": "parcel"}


def test_lot_files_carry_the_permit_but_not_the_workings():
    from alx_zoning_illegal_homes.mapper.lot_files import _row
    findings = eisenhower_home()
    before = _row(by_rule(findings, "home_type"), lambda shape: shape)
    assert "permit_tags" not in before and "permit_can_allow" not in before and "permit" not in before
    apply_permits(findings, [case("SUP2010-00005", ["homes_near_eisenhower"])],
                  [CaseMatch("SUP2010-00005", "parcel")])
    after = _row(by_rule(findings, "home_type"), lambda shape: shape)
    assert after["status"] == "permit_on_file"
    assert after["permit"] == {"case": "SUP2010-00005", "how": "parcel"}


def test_settled_row_drops_the_no_record_sentence():
    findings = eisenhower_home()
    assert "has no record" in by_rule(findings, "home_type").explanation
    apply_permits(findings, [case("SUP2010-00005", ["homes_near_eisenhower"])],
                  [CaseMatch("SUP2010-00005", "parcel")])
    explanation = by_rule(findings, "home_type").explanation
    assert "no record" not in explanation and "can't tell" not in explanation
    assert "Eisenhower Avenue only with a special permit" in explanation
    assert explanation.endswith("City case SUP2010-00005 is on file for this.")


def test_settled_variance_drops_the_site_plan_no_record_sentence():
    from alx_zoning_illegal_homes.mapper.rule_results import RuleResult
    from alx_zoning_illegal_homes.mapper.checks import Findings

    row = RuleResult("yard:left", "Left side yard", FAILS, measured=4.3, required=7.0,
                     explanation=("Needs 7 ft. An approved site plan may relax this minimum "
                                  "under section 11-416. The map has no record of any change "
                                  "to the requirement."))
    findings = Findings(results=[row])
    apply_permits(findings, [case("BZA2015-00003", ["variance:yard:left"], 2015)],
                  [CaseMatch("BZA2015-00003", "parcel")])
    assert row.explanation == ("Needs 7 ft. An approved site plan may relax this minimum "
                               "under section 11-416. City case BZA2015-00003 is on file "
                               "for this.")


def test_undersized_lot_settled_drops_the_cant_count_sentence():
    from alx_zoning_illegal_homes.mapper.rule_results import RuleResult
    from alx_zoning_illegal_homes.mapper.checks import Findings

    row = RuleResult("lot_area", "Lot size", FAILS, explanation=(
        "City Council can allow a home on a qualifying older undersized lot by special use "
        "permit under sections 12-401 and 12-402. The map can't verify eligibility or count "
        "that permit."), permit_tags=("undersized_lot",), permit_can_allow=True)
    findings = Findings(results=[row])
    apply_permits(findings, [case("SUP2001-00002", ["undersized_lot"])],
                  [CaseMatch("SUP2001-00002", "address")], year_built=2011)
    assert "can't verify" not in row.explanation
    assert row.explanation.endswith("12-402. City case SUP2001-00002 is on file for this.")


def undersized_row():
    from alx_zoning_illegal_homes.mapper.checks import Findings
    from alx_zoning_illegal_homes.mapper.rule_results import RuleResult

    row = RuleResult("lot_area", "Lot size", FAILS, permit_tags=("undersized_lot",),
                     permit_can_allow=True)
    return Findings(results=[row]), row


def test_undersized_lot_permit_newer_than_the_house_settles_nothing():
    findings, row = undersized_row()
    apply_permits(findings, [case("SUP2011-00064", ["undersized_lot"], 2011)],
                  [CaseMatch("SUP2011-00064", "address")], year_built=1918)
    assert row.status == FAILS and row.permit is None


def test_undersized_lot_permit_settles_a_house_built_from_the_year_before():
    for built in (2014, 2015):
        findings, row = undersized_row()
        apply_permits(findings, [case("SUP2015-00090", ["undersized_lot"], 2015)],
                      [CaseMatch("SUP2015-00090", "address")], year_built=built)
        assert row.status == PERMIT_ON_FILE


def test_undersized_lot_permit_needs_both_years_known():
    for built, year in ((None, 2015), (2016, None)):
        findings, row = undersized_row()
        apply_permits(findings, [case("SUP2015-00090", ["undersized_lot"], year)],
                      [CaseMatch("SUP2015-00090", "address")], year_built=built)
        assert row.status == FAILS


def test_variances_are_not_gated_by_year_built():
    findings = narrow_side_yards()
    apply_permits(findings, [case("BZA2015-00003", ["variance:yard:left"], 2015)],
                  [CaseMatch("BZA2015-00003", "parcel")], year_built=1920)
    assert by_rule(findings, "yard:left").status == PERMIT_ON_FILE
