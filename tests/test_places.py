"""Metro station locations and the 1,000 ft test."""
from shapely.geometry import LineString, box

from alx_zoning_illegal_homes.mapper.places import (near_a_station, near_eisenhower_avenue,
                                                    station_points)


def test_lot_beside_king_street_station_is_near_it():
    stations = station_points()
    king = stations["King Street-Old Town"]
    lot = box(king.x + 500, king.y, king.x + 550, king.y + 50)
    assert near_a_station(lot, stations)
    assert near_a_station(lot, stations, ["King Street-Old Town"])
    assert not near_a_station(lot, stations, ["Van Dorn Street"])


def test_lot_far_from_every_station_is_not_near():
    stations = station_points()
    king = stations["King Street-Old Town"]
    lot = box(king.x, king.y + 2000, king.x + 50, king.y + 2050)
    assert not near_a_station(lot, stations)


def test_lot_near_eisenhower_avenue_counts_only_inside_the_margin():
    avenue = LineString([(0, 0), (5000, 0)])
    assert near_eisenhower_avenue(box(100, 900, 150, 950), avenue)
    # 990 ft from the drawn roadway may be past 1,000 ft from the true centerline.
    assert not near_eisenhower_avenue(box(100, 990, 150, 1040), avenue)
    assert not near_eisenhower_avenue(box(100, 900, 150, 950), LineString())
