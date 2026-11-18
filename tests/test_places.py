"""Metro station locations and the 1,000 ft test."""
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.places import near_a_station, station_points


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

