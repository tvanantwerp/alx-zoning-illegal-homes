"""Front yards set by the neighbors along the street, and the helper that finds them."""
from dataclasses import replace

import pytest
from shapely.geometry import LineString, Polygon, box

from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.block_faces import BlockFaces, FrontSetback
from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import Street, classify, front_for_yard
from alx_zoning_illegal_homes.mapper.rule_results import (
    FAILS, NOT_CHECKED, NOT_REQUIRED, PASSES)
from alx_zoning_illegal_homes.mapper.rules import RB_HISTORIC, ZONES

from .helpers import MAIN, between_neighbors

# A block like the ordinance's drawing of a contextual block face: a row of
# 40 ft lots on each side of Main St, which runs east-west along y = 0.
# Lots 0-4 are on the north side (fronts at y = 30), lots 5-9 on the south.
MAIN_ST = ("MAIN", LineString([(-100, 0), (300, 0)]))
NORTH = [box(x, 30, x + 40, 130) for x in range(0, 200, 40)]
SOUTH = [box(x, -130, x + 40, -30) for x in range(0, 200, 40)]
LOTS = NORTH + SOUTH


def _block_faces(setbacks):
    """Lots along Main St, each with a house set back the given distance (None for no house)."""
    def lines_for(lot_id):
        others = [lot for i, lot in enumerate(LOTS) if i != lot_id]
        return classify(LOTS[lot_id], unary_union(others), [MAIN_ST], "MAIN")

    buildings = {}
    for lot_id, setback in enumerate(setbacks):
        if setback is None:
            continue
        x0, y0, x1, y1 = LOTS[lot_id].bounds
        if lot_id < 5:
            house = box(x0 + 8, y0 + setback, x1 - 8, y0 + setback + 30)
        else:
            house = box(x0 + 8, y1 - setback - 30, x1 - 8, y1 - setback)
        buildings[lot_id] = [(house, True)]
    return BlockFaces(LOTS, lines_for, buildings)


def test_narrow_middle_lot_sees_across_its_wider_neighbors():
    widths = [(0, 60), (60, 80), (80, 140)]
    lots = [box(x, y, end, y + 100) for y in (30, -130) for x, end in widths]
    def lines_for(i):
        neighbors = unary_union(lots[:i] + lots[i + 1:])
        return classify(lots[i], neighbors, [MAIN_ST], "MAIN")
    faces = BlockFaces(lots, lines_for, {})
    assert faces.across(1, "MAIN") == [3, 4, 5]


def test_block_average_counts_three_front_buildings_on_one_lot():
    lots = [box(0, 30, 60, 130), box(60, 30, 100, 130), box(100, 30, 140, 130)]
    buildings = {0: [(box(0, 30, 12, 60), True), (box(18, 42, 30, 65), True),
                     (box(40, 42, 52, 65), True)], 1: [(box(70, 60, 90, 90), True)]}
    faces = BlockFaces(lots, lambda i: classify(lots[i], unary_union(lots[:i] + lots[i + 1:]),
                                                [MAIN_ST], "MAIN"), buildings)
    assert sorted(s.distance for s in faces.block_side(2, "MAIN")) == [0, 12, 12, 30]


def test_block_face_is_the_lots_beside_and_across_the_street():
    faces = _block_faces([20] * 10)
    found = faces.contextual(2, "MAIN")
    assert sorted(s.lot_id for s in found if not s.across) == [1, 3]
    assert sorted(s.lot_id for s in found if s.across) == [6, 7, 8]
    assert all(s.distance == pytest.approx(20) for s in found)


@pytest.mark.parametrize("angle", [0, 20])
def test_corner_block_face_includes_the_opposite_corner_on_both_streets(angle):
    from shapely.affinity import skew

    # Four corners plus a lot farther along the far side of Main.
    lots = [box(30, 30, 100, 100), box(-100, 30, -30, 100),
            box(30, -100, 100, -30), box(-100, -100, -30, -30),
            box(-170, -100, -100, -30)]
    lots = [skew(lot, xs=angle, origin=(0, 0)) for lot in lots]
    side = ("SIDE", skew(LineString([(0, -300), (0, 300)]), xs=angle, origin=(0, 0)))

    def lines_for(i):
        neighbors = unary_union(lots[:i] + lots[i + 1:])
        return classify(lots[i], neighbors, [MAIN_ST, side], "MAIN")

    buildings = {i: [(lot.buffer(-10), True)] for i, lot in enumerate(lots)}
    faces = BlockFaces(lots, lines_for, buildings)
    for name in ("MAIN", "SIDE"):
        assert 3 not in faces.across(0, name)
        assert faces.diagonally_across(0, name) == [3]
        opposite = [setback for setback in faces.contextual(0, name) if setback.lot_id == 3]
        assert len(opposite) == 1 and opposite[0].across
        assert opposite[0].distance == pytest.approx(10)


def test_block_face_leaves_out_lots_without_buildings():
    setbacks = [20] * 10
    setbacks[1] = None
    found = _block_faces(setbacks).contextual(2, "MAIN")
    assert 1 not in {s.lot_id for s in found}


def test_block_side_runs_along_the_whole_side_of_the_street():
    setbacks = [20] * 10
    setbacks[3] = None   # an empty lot still carries the block along
    side = _block_faces(setbacks).block_side(0, "MAIN")
    assert sorted(s.lot_id for s in side) == [1, 2, 4]


def test_block_side_stops_at_a_different_street_with_the_same_short_name():
    lots = [
        box(0, 30, 40, 130),
        box(40, 30, 80, 130),
        box(80, 30, 120, 130),
    ]
    first = Street("MAIN", LineString([(0, 0), (39, 0)]), label="Main Court")
    second = Street("MAIN", LineString([(40, 0), (140, 0)]), label="Main Street")

    def lines_for(i):
        return classify(lots[i], unary_union(lots[:i] + lots[i + 1:]), [first, second], "MAIN")

    buildings = {1: [(box(50, 50, 70, 90), True)], 2: [(box(90, 50, 110, 90), True)]}
    faces = BlockFaces(lots, lines_for, buildings)
    assert faces.block_side(0, "MAIN") == []
    assert [s.lot_id for s in faces.block_side(1, "MAIN")] == [2]


LOT = box(0, 0, 60, 120)


def _with_block_face(zone, home, setbacks, field="contextual_block_face", rules=None,
                     home_type="single", historic=False):
    """Check a home on LOT, with neighbors along Main St set back these distances.

    `field` names the LotFacts field the neighbors go in.
    """
    neighbors = [FrontSetback(100 + i, "MAIN", d, LineString([(0, 0), (0, d)]))
                 for i, d in enumerate(setbacks)]
    facts = LotFacts(
        shape=LOT, area=LOT.area, rules=rules if rules is not None else ZONES[zone],
        home_type=home_type, homes=[Home(shape=home, height=20, floor_area=1000)],
        lines=classify(LOT, between_neighbors(LOT), [MAIN], "MAIN"),
        all_buildings=[home], in_historic_district=historic,
        **{field: {"MAIN": neighbors}})
    findings = check_lot(facts)
    return {r.rule: r for r in findings.results}["yard:front"], findings


def test_home_closer_than_every_neighbor_fails():
    row, findings = _with_block_face("R-8", box(10, 12, 50, 50), [20, 28])
    assert row.status == FAILS
    assert row.measured == pytest.approx(12) and row.required == pytest.approx(20)
    assert row.explanation.startswith(
        "Set back about 12.0 ft from Main; the neighboring homes there are set back 20 to 28 ft.")
    assert any(r.text.startswith("Too close to Main: set back about 12.0 ft")
               for r in findings.reasons)


@pytest.mark.parametrize("zone", ["R-8", "RA", "RB"])
def test_neighbor_touching_front_line_does_not_set_house_zone_range(zone):
    row, _ = _with_block_face(zone, box(10, 12, 50, 50), [0, 0.4, 20, 28])
    assert row.status == FAILS and row.required == pytest.approx(20)


def test_zero_setbacks_are_kept_where_buildings_may_stand_at_front_line():
    row, _ = _with_block_face("CL", box(10, 12, 50, 50), [0, 20, 28])
    assert row.status == PASSES and row.required == 0
    row, _ = _with_block_face("RM", box(10, 10, 50, 50), [0, 0, 8],
                              field="block_side")
    assert row.required == 0


def test_home_within_the_neighbors_range_passes():
    row, _ = _with_block_face("RA", box(10, 22, 50, 60), [20, 28])
    assert row.status == PASSES and row.required == pytest.approx(20)


def test_corner_street_without_neighbors_is_left_out():
    side = ("SIDE", LineString([(85, -100), (85, 300)]))
    home = box(10, 22, 50, 60)
    neighbors = [FrontSetback(100 + i, "MAIN", d, LineString([(0, 0), (0, d)]))
                 for i, d in enumerate([20, 28])]
    facts = LotFacts(
        shape=LOT, area=LOT.area, rules=ZONES["R-8"], home_type="single",
        homes=[Home(shape=home, height=20, floor_area=1000)],
        lines=classify(LOT, box(-60, 0, 0, 120), [MAIN, side], "MAIN"),
        all_buildings=[home], contextual_block_face={"MAIN": neighbors})
    assert set(facts.lines.fronts) == {"MAIN", "SIDE"}
    row = {r.rule: r for r in check_lot(facts).results}["yard:front"]
    assert row.status == PASSES and row.required == pytest.approx(20)


def test_home_set_back_further_than_its_neighbors_fails():
    row, findings = _with_block_face("R-8", box(10, 40, 50, 80), [20, 28])
    assert row.status == FAILS and row.required == 28 and row.limit == "max"
    assert "strip" not in row.shapes and row.shapes["gap"]
    assert any(reason.text.startswith("Too far back from Main")
               for reason in findings.reasons)


def test_a_little_further_back_than_the_neighbors_passes_on_the_margin():
    row, _ = _with_block_face("R-8", box(10, 30, 50, 65), [20, 28])
    assert row.status == PASSES and row.required == 28 and row.limit == "max"


def test_a_little_short_of_the_neighbors_passes_on_the_margin():
    row, findings = _with_block_face("R-5", box(10, 18.5, 50, 60), [20, 25])
    assert row.status == PASSES and not findings.reasons


def test_deep_neighbors_ask_no_more_than_the_zones_cap():
    # R-8's neighbors can ask at most 30 ft.
    row, _ = _with_block_face("R-8", box(10, 31, 50, 70), [45, 50])
    assert row.status == PASSES and row.required == 30
    row, findings = _with_block_face("R-8", box(10, 20, 50, 60), [45, 50])
    assert row.status == FAILS and row.required == 30
    assert any("asks for at least 30 ft" in r.text for r in findings.reasons)


def test_no_neighbors_leaves_the_front_yard_unchecked():
    row, findings = _with_block_face("R-8", box(10, 5, 50, 50), [])
    assert row.status == NOT_CHECKED and "nothing to compare" in row.explanation
    assert not [r for r in findings.reasons if r.kind == "yards"]


@pytest.mark.parametrize("zone", ["CL", "OCH", "W-1", "CRMU/L", "CRMU/X"])
def test_commercial_and_mixed_use_houses_use_their_neighbors(zone):
    row, _ = _with_block_face(zone, box(10, 5, 50, 50), [20, 28])
    assert row.status == FAILS and row.required == 20


def test_mixed_use_apartments_need_no_front_yard():
    row, _ = _with_block_face("CRMU/L", box(10, 5, 50, 50), [20, 28], home_type="multi")
    assert row.status == NOT_REQUIRED


def test_crmu_x_townhouses_need_no_front_yard():
    row, _ = _with_block_face("CRMU/X", box(10, 5, 50, 50), [20, 28], home_type="townhouse")
    assert row.status == NOT_REQUIRED
    row, _ = _with_block_face("CRMU/L", box(10, 5, 50, 50), [20, 28], home_type="townhouse")
    assert row.status == FAILS


def test_rm_front_yard_shows_the_lot_line_where_the_block_is_at_it():
    row, findings = _with_block_face("RM", box(10, 10, 50, 50), [0.5, 1, 8],
                                     field="block_side", home_type="townhouse")
    assert row.status == NOT_CHECKED and row.required == 0
    assert "only 1 of the 3 other buildings" in row.explanation
    assert not [r for r in findings.reasons if r.kind == "yards"]


def test_rm_front_yard_shows_the_average_of_a_block_that_stands_back():
    row, _ = _with_block_face("RM", box(10, 1, 50, 50), [8, 10, 12], field="block_side",
                              home_type="townhouse")
    assert row.status == NOT_CHECKED and row.required == pytest.approx(10)
    assert "on average they stand about 10.0 ft back" in row.explanation


@pytest.mark.parametrize("zone", ["RM", "CD"])
def test_block_average_ignores_setbacks_deeper_than_the_subject_lot(zone):
    row, _ = _with_block_face(zone, box(10, 1, 50, 50), [12, 16, 350],
                              field="block_side", home_type="townhouse")
    assert row.status == NOT_CHECKED and row.required == pytest.approx(14)
    assert "leaves out buildings" in row.explanation


def test_block_average_is_unknown_if_every_neighbor_is_too_far_away():
    row, _ = _with_block_face("RM", box(10, 1, 50, 50), [350, 1650],
                              field="block_side", home_type="townhouse")
    assert row.status == NOT_CHECKED and row.required is None
    assert "could not estimate" in row.explanation


def test_rb_in_the_historic_districts_passes_at_the_lot_line_and_is_unjudged_behind_it():
    row, _ = _with_block_face("RB", box(10, 1, 50, 50), [], rules=RB_HISTORIC, historic=True)
    assert row.status == PASSES
    row, _ = _with_block_face("RB", box(10, 15, 50, 50), [], rules=RB_HISTORIC, historic=True)
    assert row.status == NOT_CHECKED and "board of architectural review" in row.explanation


def test_planned_district_rules_leave_the_front_yard_unchecked():
    plan = replace(ZONES["R-8"], contextual_front_yard=None, name="Some approved plan")
    row, _ = _with_block_face("R-8", box(10, 5, 50, 50), [20, 28], rules=plan)
    assert row.status == NOT_CHECKED


def test_corner_yard_leaves_out_the_cut_corner():
    # A corner lot with a wide corner cut off at 45 degrees where Main St meets Side St.
    lot = Polygon([(0, 0), (35, 0), (60, 25), (60, 100), (0, 100)])
    side = ("SIDE", LineString([(85, -100), (85, 300)]))
    lines = classify(lot, None, [MAIN, side], "MAIN")
    assert set(lines.fronts) == {"MAIN", "SIDE"}
    home = box(10, 15, 45, 70)
    # Straight out to either street the yard is 15 ft; to the cut corner it is far less.
    assert min(home.distance(front) for front in lines.fronts.values()) < 5
    for street in ("MAIN", "SIDE"):
        assert home.distance(front_for_yard(lines, street)) == pytest.approx(15)
