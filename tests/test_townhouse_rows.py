"""The limit on townhouses in one row: finding rows by shared walls and judging them."""
import geopandas as gpd
import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.analyze import MAX_ROW_OUTLINES, _townhouse_rows
from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, TownhouseRow
from alx_zoning_illegal_homes.mapper.lot_files import lot_drawing
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rule_results import FAILS, NO_RULE, NOT_CHECKED, PASSES
from alx_zoning_illegal_homes.mapper.rules import ZONES, planned_district_rules, rules_for

from .helpers import MAIN, check

ROW = "ROW (TOWNHOUSE)"


def rows_for(parts, lot_uses, condo_units=None, addresses=None):
    """Run the row finder on made-up home pieces.

    `parts` holds (building id, lot id, outline) triples; `lot_uses` gives
    each lot's land use, in lot id order.
    """
    lots = gpd.GeoDataFrame({
        "land_use": lot_uses,
        "address": addresses or [None] * len(lot_uses),
        "condo_units": condo_units or [0] * len(lot_uses),
    }, geometry=[box(0, 0, 1, 1)] * len(lot_uses))
    home_parts = gpd.GeoDataFrame(
        {"building_id": [p[0] for p in parts], "lot_id": [p[1] for p in parts]},
        geometry=[p[2] for p in parts])
    return _townhouse_rows(home_parts, lots)


def row_of(count, width=20, depth=40, x0=0):
    """`count` townhouses side by side, each its own building on its own lot."""
    return [(i, i, box(x0 + i * width, 0, x0 + (i + 1) * width, depth)) for i in range(count)]


def test_homes_sharing_walls_make_one_row():
    rows = rows_for(row_of(10), [ROW] * 10)
    assert {row.homes for row in rows.values()} == {10}
    assert rows[0].length == pytest.approx(200)


def test_rows_meeting_at_a_corner_stay_apart():
    # A second row of 5 starts where the first ends, one alley-width up:
    # the end homes touch only at a corner.
    first = row_of(5)
    second = [(5 + i, 5 + i, box(100 + i * 20, 40, 120 + i * 20, 80)) for i in range(5)]
    rows = rows_for(first + second, [ROW] * 10)
    assert {row.homes for row in rows.values()} == {5}


def test_small_corner_overlap_does_not_merge_rows():
    first = row_of(5)
    second = [(5 + i, 5 + i, box(98.3 + i * 20, 38.3, 118.3 + i * 20, 78.3))
              for i in range(5)]
    rows = rows_for(first + second, [ROW] * 10)
    assert {row.homes for row in rows.values()} == {5}


def test_overlength_row_takes_precedence_on_a_lot_in_two_rows():
    short = row_of(10, width=18)
    long = [(10 + i, (0 if i == 0 else 9 + i), box(i * 26, 100, (i + 1) * 26, 140))
            for i in range(9)]
    row = rows_for(short + long, [ROW] * 18)[0]
    assert row.homes == 9 and row.length == pytest.approx(234)


def test_home_drawn_across_two_lots_counts_once_per_lot():
    # Each outline is drawn 8 ft off its lot lines, so it is cut into two pieces.
    parts = []
    for i in range(9):
        parts.append((i, i, box(i * 20 + 8, 0, (i + 1) * 20, 40)))
        parts.append((i, i + 1, box((i + 1) * 20, 0, (i + 1) * 20 + 8, 40)))
    rows = rows_for(parts, [ROW] * 10)
    assert rows[0].homes == 10


def test_condo_lot_counts_each_building():
    parts = [(i, 0, box(i * 20, 0, (i + 1) * 20, 40)) for i in range(12)]
    rows = rows_for(parts, ["CONDO (TOWNHOUSE)"], condo_units=[12])
    assert rows[0].homes == 12
    assert rows[0].outlines == []  # every home is on this lot, already drawn


def test_lot_not_used_for_homes_links_the_row_but_adds_no_home():
    rows = rows_for(row_of(9), [ROW] * 4 + ["OFFICE"] + [ROW] * 4)
    assert rows[0].homes == 8


def test_long_rows_carry_the_other_buildings_nearest_first():
    rows = rows_for(row_of(MAX_ROW_OUTLINES + 5), [ROW] * (MAX_ROW_OUTLINES + 5))
    first = rows[0]
    assert len(first.outlines) == MAX_ROW_OUTLINES and not first.all_outlined
    assert first.outlines[0].bounds[0] == pytest.approx(20)
    short = rows_for(row_of(8), [ROW] * 8)
    assert short[0].outlines == []


LOT, HOME = box(0, 0, 20, 100), box(0, 30, 20, 70)


def row_result(zone=None, row=None, rules=None, home_type="townhouse"):
    _, findings = check(LOT, HOME, zone, home_type=home_type, rules=rules, row=row)
    return findings, next((r for r in findings.results if r.rule == "row_length"), None)


def test_row_of_eight_passes():
    _, result = row_result("RM", TownhouseRow(homes=8, length=160))
    assert result.status == PASSES
    assert result.summary == "8 homes; at most 8 allowed"
    assert "single structure" in result.about


def test_long_row_fails_outright_where_no_permit_can_allow_it():
    findings, result = row_result("RM", TownhouseRow(homes=11, length=190))
    assert result.status == FAILS
    assert result.summary == "11 homes; at most 8 allowed"
    reason = next(r for r in findings.reasons if r.kind == "row_length")
    assert "no special permit can allow more" in reason.text
    assert "whenever each home was built" in result.explanation


def test_long_row_elsewhere_would_need_a_special_permit():
    findings, result = row_result("OC", TownhouseRow(homes=11, length=190))
    assert result.status == FAILS
    reason = next(r for r in findings.reasons if r.kind == "row_length")
    assert reason.text.endswith("It would need a special permit from City Council.")


def test_row_longer_than_any_permit_allows_fails_without_a_permit_way_out():
    findings, result = row_result("OC", TownhouseRow(homes=11, length=230))
    reason = next(r for r in findings.reasons if r.kind == "row_length")
    assert "longer than 212 ft" in reason.text and "would need" not in reason.text
    # A few feet over is within the roof overhangs at the row's two ends.
    findings, _ = row_result("OC", TownhouseRow(homes=11, length=215))
    assert "would need a special permit" in next(
        r.text for r in findings.reasons if r.kind == "row_length")


def test_short_row_over_212_ft_passes():
    # The 212 ft cap limits what a special permit may allow; eight homes need none.
    _, result = row_result("OC", TownhouseRow(homes=8, length=240))
    assert result.status == PASSES


def test_approved_plan_leaves_the_row_unchecked_but_ordinary_zoning_checks_it():
    _, plan, fallback = planned_district_rules("CDD#5")
    findings, result = row_result(rules=plan, row=TownhouseRow(homes=12, length=190))
    assert result.status == NOT_CHECKED
    assert not any(r.kind == "row_length" for r in findings.reasons)
    _, ordinary = row_result(rules=fallback, row=TownhouseRow(homes=12, length=190))
    assert ordinary.status == FAILS


def test_zone_without_townhouses_has_no_row_limit_to_check():
    _, result = row_result("R-8", TownhouseRow(homes=12, length=190))
    assert result.status == NO_RULE


def test_only_townhouses_get_the_row():
    _, result = row_result("RM", TownhouseRow(homes=12, length=190), home_type="single")
    assert result is None


def test_historic_rb_keeps_the_no_permit_rule():
    assert ZONES["RB"].long_townhouse_rows == "never"
    assert rules_for("RB", True).long_townhouse_rows == "never"
    assert ZONES["CG"].long_townhouse_rows == "permit"


def test_drawing_file_outlines_the_rest_of_the_row():
    neighbors = [box(20 * i, 30, 20 * (i + 1), 70) for i in range(1, 11)]
    findings, result = row_result("RM", TownhouseRow(homes=11, length=220,
                                                     outlines=neighbors))
    assert result.buildings == [0]
    facts = LotFacts(shape=LOT, area=LOT.area, rules=ZONES["RM"], home_type="townhouse",
                     homes=[Home(shape=HOME, height=30)], all_buildings=[HOME],
                     lines=classify(LOT, None, [MAIN], "MAIN"))
    record = {"rule_results": findings.results, "notes": []}
    drawing = lot_drawing(1, record, facts)
    row = next(r for r in drawing["results"]["rules"] if r["rule"] == "row_length")
    assert len(row["shapes"]["row"]) == 10


def test_home_recorded_as_two_condo_parcels_counts_once():
    # Each townhouse is split between a condo unit parcel at the back and a
    # parcel at the front.
    parts = []
    for i in range(9):
        parts += [(i, i, box(i * 20, 0, (i + 1) * 20, 20)),
                  (i, 9 + i, box(i * 20, 20, (i + 1) * 20, 40))]
    rows = rows_for(parts, ["CONDO (TOWNHOUSE)"] * 18, condo_units=[1] * 18,
                    addresses=[f"{i} Main St" for i in range(9)] * 2)
    assert rows[0].homes == 9


def test_condo_parcel_pairs_count_once_whatever_their_addresses():
    # As on Franklin St: a unit parcel ("809 Franklin St Unit 665") and a
    # second parcel that carries the next home's street number.
    parts = []
    for i in range(6):
        parts += [(i, i, box(i * 20, 0, (i + 1) * 20, 20)),
                  (i, 6 + i, box(i * 20, 20, (i + 1) * 20, 40))]
    addresses = ([f"{809 - 2 * i} Franklin St Unit {665 + 2 * i}" for i in range(6)]
                 + [f"{807 - 2 * i} Franklin St" for i in range(6)])
    rows = rows_for(parts, ["CONDO (TOWNHOUSE)"] * 12, condo_units=[1] * 12,
                    addresses=addresses)
    assert {row.homes for row in rows.values()} == {6}


def test_single_outline_does_not_merge_freehold_lots_with_a_condo():
    parts = [(0, i, shape) for _, i, shape in row_of(9)]
    rows = rows_for(parts, [ROW] * 9, condo_units=[1] + [0] * 8)
    assert {row.homes for row in rows.values()} == {9}
