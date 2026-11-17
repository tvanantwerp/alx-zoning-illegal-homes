"""Lot-edge detection and lot measurement on simple made-up blocks."""
import pytest
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.lot_lines import classify, lot_width

# Two streets cross at the origin corner of a block of 50 x 100 ft lots.
# Main St runs east-west 25 ft south of the lots; Oak St runs north-south
# 25 ft west of them.
MAIN = ("MAIN", LineString([(-200, -25), (400, -25)]))
OAK = ("OAK", LineString([(-25, -200), (-25, 400)]))
CORNER_LOT = box(0, 0, 50, 100)
MIDDLE_LOT = box(50, 0, 100, 100)
FAR_LOT = box(100, 0, 150, 100)
BACK_LOT = box(0, 100, 150, 200)


def neighbors_of(lot):
    others = [CORNER_LOT, MIDDLE_LOT, FAR_LOT, BACK_LOT]
    return unary_union([other for other in others if not other.equals(lot)])


def test_interior_lot_has_one_front():
    lines = classify(MIDDLE_LOT, neighbors_of(MIDDLE_LOT), [MAIN, OAK], "MAIN")
    assert list(lines.fronts) == ["MAIN"]
    assert not lines.is_corner and not lines.is_through
    assert lines.frontage == pytest.approx(50, abs=0.1)
    assert lot_width(MIDDLE_LOT, lines, 30) == pytest.approx(50, abs=0.5)


def test_corner_lot_fronts_two_streets():
    lines = classify(CORNER_LOT, neighbors_of(CORNER_LOT), [MAIN, OAK], "MAIN")
    assert set(lines.fronts) == {"MAIN", "OAK"}
    assert lines.is_corner
    assert lines.primary_street == "MAIN"
    assert lines.frontage == pytest.approx(50, abs=0.1)


def test_corner_lot_front_follows_the_address():
    lines = classify(CORNER_LOT, neighbors_of(CORNER_LOT), [MAIN, OAK], "OAK")
    assert lines.primary_street == "OAK"
    assert lines.frontage == pytest.approx(100, abs=0.1)


def test_edge_beside_an_alley_is_not_a_street_front():
    # With no lot to the east, the far lot's east edge is open land, but it
    # runs square to Main St and so must not count as fronting it.
    lines = classify(FAR_LOT, unary_union([CORNER_LOT, MIDDLE_LOT, BACK_LOT]),
                     [MAIN, OAK], "MAIN")
    assert list(lines.fronts) == ["MAIN"]
    assert lines.frontage == pytest.approx(50, abs=0.1)
    kinds = {piece.kind for piece in lines.pieces}
    assert kinds == {"street", "shared", "open"}


def test_lot_behind_others_has_no_front():
    landlocked = box(50, 100, 100, 200)
    around = unary_union([MIDDLE_LOT, box(0, 100, 50, 200), box(100, 100, 150, 200),
                          box(0, 200, 150, 300)])
    lines = classify(landlocked, around, [MAIN, OAK], "MAIN")
    assert lines.frontage is None
    assert lot_width(landlocked, lines, 30) is None


def test_pie_shaped_lot_is_wider_at_the_building_line():
    # 20 ft of frontage fanning out to 80 ft at the back.
    pie = Polygon([(40, 0), (60, 0), (90, 100), (10, 100)])
    lines = classify(pie, None, [MAIN], "MAIN")
    assert lines.frontage == pytest.approx(20, abs=0.1)
    assert lot_width(pie, lines, 30) == pytest.approx(38, abs=1.5)


def test_flag_lot_is_measured_in_its_narrow_stem():
    flag = Polygon([(0, 0), (15, 0), (15, 80), (100, 80), (100, 160), (0, 160)])
    lot_in_front = box(15, 0, 100, 80)
    lines = classify(flag, lot_in_front, [MAIN], "MAIN")
    assert lines.frontage == pytest.approx(15, abs=0.1)
    assert lot_width(flag, lines, 30) == pytest.approx(15, abs=0.5)


def test_shallow_lot_has_no_width_at_that_depth():
    shallow = box(0, 0, 60, 20)
    lines = classify(shallow, None, [MAIN], "MAIN")
    assert lot_width(shallow, lines, 30) is None
