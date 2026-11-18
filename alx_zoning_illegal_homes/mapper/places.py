"""Named places the ordinance measures from, which the city's layers don't hold.

Several rules apply only within 1,000 feet of a Metrorail station. The
city's open data has no layer of stations, so their locations are listed
here. Each is the middle of the station's platform.
"""
import geopandas as gpd
import shapely

from .loader import FEET_CRS

# (longitude, latitude). King Street, Braddock Road and Potomac Yard are the
# platform canopies in the city's buildings layer. Eisenhower Avenue and Van
# Dorn Street aren't in that layer, so they come from public maps.
METRO_STATIONS = {
    "King Street-Old Town": (-77.0611, 38.8065),
    "Braddock Road": (-77.0538, 38.8140),
    "Potomac Yard": (-77.0464, 38.8334),
    "Eisenhower Avenue": (-77.0711, 38.8003),
    "Van Dorn Street": (-77.1291, 38.7994),
}
# The ordinance's distances run from a station or its kiosk, not from the
# middle of the platform, which is up to about 300 ft long each way. Lots this
# much past the limit still count as near, so none is wrongly held to the
# stricter rule.
STATION_MARGIN = 300.0
NEAR_STATION = 1000.0


def station_points() -> dict:
    """Each Metro station as a point in feet, keyed by name."""
    names = list(METRO_STATIONS)
    points = gpd.GeoSeries(
        [shapely.Point(*METRO_STATIONS[name]) for name in names], crs="EPSG:4326"
    ).to_crs(FEET_CRS)
    return dict(zip(names, points))


def near_a_station(shape, stations: dict, names=None) -> bool:
    """Whether any part of a lot lies within 1,000 ft of a Metro station.

    `names` limits the test to some stations, as when a rule names one.
    """
    chosen = names or stations
    return any(shape.distance(stations[name]) <= NEAR_STATION + STATION_MARGIN
               for name in chosen)
