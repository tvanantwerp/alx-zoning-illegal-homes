"""Lot-edge detection and lot measurement on simple made-up blocks."""
import math

import pytest
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.lot_lines import classify, lot_width, lot_width_line

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


@pytest.mark.parametrize("address", ["MAIN", "OAK", "NORTH"])
def test_three_front_lot_can_be_both_corner_and_through(address):
    # The west edge faces Oak only at the north end of the parcel. It meets
    # North St, while the Main St frontage sits at the other end of the lot.
    lot = box(0, 0, 50, 200)
    north = ("NORTH", LineString([(-200, 225), (400, 225)]))
    neighbors = unary_union([box(-50, 0, 0, 110), box(50, 0, 100, 200)])
    lines = classify(lot, neighbors, [MAIN, OAK, north], address)
    assert set(lines.fronts) == {"MAIN", "OAK", "NORTH"}
    assert lines.primary_street == address
    assert lines.is_corner and lines.is_through


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


@pytest.mark.parametrize("radial", [True, False])
def test_curved_frontage_needs_radial_side_lot_lines(radial):
    def arc(radius):
        return [(radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle)))
                for angle in range(60, 121, 10)]

    front = arc(50)
    if radial:
        outer = arc(120)
        back = [outer[-1], outer[0]]
    else:
        back = [(front[-1][0], 120), (front[0][0], 120)]
    lot = Polygon([*front, *back])
    lines = classify(lot, None, [("CURVE", LineString(arc(25)))], "CURVE")
    assert lines.front_is_curved_with_radial_sides == radial


def test_rounded_street_corner_does_not_qualify_for_curved_frontage():
    lot = Polygon([(0, 0), (35, 0), (46, 2), (55, 10), (60, 22),
                   (60, 100), (0, 100)])
    side = ("SIDE", LineString([(85, -100), (85, 300)]))
    lines = classify(lot, None, [MAIN, side], "MAIN")
    assert lines.is_corner
    assert not lines.front_is_curved_with_radial_sides


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


def test_width_line_sits_the_measuring_depth_back():
    lot = box(0, 0, 60, 100)
    lines = classify(lot, None, [MAIN], "MAIN")   # MAIN runs along y = -25
    line = lot_width_line(lot, lines, 25)
    assert line.length == pytest.approx(60, abs=0.5)
    assert all(y == pytest.approx(25, abs=0.5) for _, y in line.coords)
    assert lot_width_line(lot, lines, 0) is None


# A street that changes its name partway along, at x = 25. The lot straddles
# the change, with neighbors on both sides.
WEST_PART = ("WEST", LineString([(-300, -25), (25, -25)]))
EAST_PART = ("EAST", LineString([(25, -25), (400, -25)]))
STRADDLING_LOT = box(0, 0, 50, 100)
STRADDLING_NEIGHBORS = unary_union([box(-50, 0, 0, 100), box(50, 0, 100, 100)])


@pytest.mark.parametrize("side_street", [False, True])
def test_street_that_only_changes_its_name_is_not_a_corner(side_street):
    # A third street leaving the junction on the far side doesn't change that
    # the lot sits along one straight road.
    streets = [WEST_PART, EAST_PART]
    if side_street:
        streets.append(("SOUTH", LineString([(25, -25), (25, -300)])))
    lines = classify(STRADDLING_LOT, STRADDLING_NEIGHBORS, streets, "WEST")
    assert set(lines.fronts) == {"WEST", "EAST"}
    assert not lines.is_corner and not lines.is_through


# A road running west along y = -25 to x = 0, where it is renamed and bends
# 45 degrees to the north-west.
BEND_WEST = ("ROAD", LineString([(400, -25), (0, -25)]))
BEND_ON = ("RENAMED", LineString([(0, -25), (-200, 175)]))


def test_lot_line_that_turns_a_corner_where_a_street_is_renamed_is_a_corner():
    # The lot's own edge turns square where the road bends and is renamed.
    lot = Polygon([(10, 0), (60, 0), (60, 100), (10, 100), (10, 60), (-20, 30)])
    lines = classify(lot, None, [BEND_WEST, BEND_ON], "ROAD")
    assert set(lines.fronts) == {"ROAD", "RENAMED"}
    assert lines.is_corner


def test_lot_line_that_runs_straight_past_a_renamed_bend_is_not_a_corner():
    # On the outside of the bend, the lot's edge runs straight across it.
    lot = box(-60, -120, 10, -50)
    lines = classify(lot, None, [BEND_WEST, BEND_ON], "ROAD")
    assert set(lines.fronts) == {"ROAD", "RENAMED"}
    assert not lines.is_corner


# Main runs east-west along y = -25. Side St runs south from Main at x = -40,
# so the lot north of Main sits across the street from where Side St ends.
SIDE_ENDS_AT_MAIN = ("SIDE", LineString([(-40, -25), (-40, -300)]))
# The lot's south-west corner is cut off by an edge facing toward the end of Side St.
CUT_CORNER_LOT = Polygon([(8, 0), (50, 0), (50, 100), (0, 100), (0, 30)])


def test_lot_across_the_street_from_where_a_street_ends_is_not_a_corner():
    lines = classify(CUT_CORNER_LOT, box(50, 0, 100, 100), [MAIN, SIDE_ENDS_AT_MAIN], "MAIN")
    assert list(lines.fronts) == ["MAIN"]
    assert not lines.is_corner


def test_edge_looking_across_at_a_street_end_keeps_its_front_when_another_street_is_nearer():
    # A street closer to that edge, which the map couldn't match it to, means the
    # lot really does sit at a second street; dropping the front would hide that.
    nearer = ("NEARER", LineString([(-20, 50), (-300, 50)]))
    lines = classify(CUT_CORNER_LOT, box(50, 0, 100, 100),
                     [MAIN, SIDE_ENDS_AT_MAIN, nearer], "MAIN")
    assert "SIDE" in lines.fronts
