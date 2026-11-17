"""Load the city's map layers and tidy them for analysis.

Everything is converted to the Virginia North state plane grid, which is
measured in feet, so lengths and areas match the units in the ordinance.
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FEET_CRS = "EPSG:2283"

# Building categories that are sheds, garages and the like, not homes.
ACCESSORY_TYPES = {"Garage or shed", "Bus shelter", "Other"}
HOUSE_TYPES = {"Detached house", "Duplex", "Townhouse"}
# Smaller than this is a shed or a mapping scrap, whatever its label says.
MIN_HOME_FOOTPRINT = 250.0

# How the assessor's land-use description maps onto zoning home types.
HOME_TYPE_BY_LAND_USE = {
    "DETACHED HOUSE": "single",
    "SEMI-DETACHED HOUSE": "semi",
    "ROW (TOWNHOUSE)": "townhouse",
    "CONDO (TOWNHOUSE)": "townhouse",
    "CONDO (GARDEN)": "multi",
    "CONDO (HI-RISE)": "multi",
    "GARDEN APT 3 ST OR <": "multi",
    "SMALL APTS": "multi",
    "HI-RISE (7 ST AND UP": "multi",
    "MED RISE ELEV (4-6S)": "multi",
    "COOPERATIVE": "multi",
}
# Public housing comes in several shapes; the buildings decide the type.
HOME_TYPE_FROM_BUILDINGS = {"ALEX.REDV.HOUS.AUTH", "CONDO MASTER CARDS"}
STREET_KINDS = {
    "LOCAL NEIGHBORHOOD ROAD, RURAL ROAD, CITY STREET",
    "PRIMARY ROAD",
    "SECONDARY ROAD",
}


def load_layer(name: str) -> gpd.GeoDataFrame:
    """Read one zipped shapefile from the data folder, in feet."""
    layer = gpd.read_file(DATA_DIR / f"{name}.zip").to_crs(FEET_CRS)
    layer["geometry"] = layer.geometry.make_valid()
    return layer[~layer.geometry.is_empty & layer.geometry.notna()]


def _most_common(values: pd.Series):
    values = values.dropna()
    return values.mode().iloc[0] if len(values) else None


def load_lots() -> gpd.GeoDataFrame:
    """Load parcels and collapse stacked records into one row per lot.

    The parcel layer repeats the same polygon once for every condo unit in
    a building, plus once for the condo's "master card". We keep one shape
    and remember how many homes were stacked on it.
    """
    parcels = load_layer("Alexandria_Parcels")
    parcels = parcels[parcels.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    parcels = parcels[parcels.geometry.area > 50].copy()
    parcels["shape_key"] = parcels.geometry.normalize().to_wkb()
    parcels["is_condo_unit"] = parcels["LANDDESC"].fillna("").str.startswith(
        "CONDO ("
    )

    def collapse(group: pd.DataFrame) -> pd.Series:
        land_uses = group["LANDDESC"].dropna()
        homes = land_uses[land_uses.isin(list(HOME_TYPE_BY_LAND_USE))]
        land_use = _most_common(homes if len(homes) else land_uses)
        # A master card or a lone house gives the best address; condo
        # units all carry unit-specific addresses.
        lead = group.sort_values("is_condo_unit").iloc[0]
        return pd.Series({
            "zoning_label": _most_common(group["ZONING"]),
            "land_use": land_use,
            "land_uses": sorted(set(land_uses)),
            "condo_units": int(group["is_condo_unit"].sum()),
            "address": lead["ADDRESS_GI"],
            "address_street": lead["ST_NAME"],
            "owner": lead["OWN_NAME"],
            "recorded_area": float(group["LAND_SF"].fillna(0).max()),
        })

    info = parcels.groupby("shape_key", sort=False).apply(
        collapse, include_groups=False
    )
    shapes = parcels.drop_duplicates("shape_key").set_index("shape_key").geometry
    lots = gpd.GeoDataFrame(info, geometry=shapes.reindex(info.index), crs=FEET_CRS)
    return lots.reset_index(drop=True)


def load_buildings() -> gpd.GeoDataFrame:
    """Load building footprints and attach a height to each.

    Heights come from the city's 3D building layer, which splits a building
    into roof sections. We use the tallest section that covers a meaningful
    part of the footprint, so a chimney or stair tower does not set the
    height of a whole house.
    """
    buildings = load_layer("Building")
    buildings = buildings[buildings.geometry.geom_type.isin(
        ["Polygon", "MultiPolygon"])].copy()
    buildings["footprint"] = buildings.geometry.area
    buildings["is_home"] = (
        buildings["BTYPE"].isin(list(HOUSE_TYPES))
        | (
            ~buildings["BTYPE"].isin(list(ACCESSORY_TYPES))
            & buildings["BUSE"].isin(["Residential", "Multiple or Mixed"])
        )
    ) & (buildings["footprint"] >= MIN_HOME_FOOTPRINT)
    buildings = buildings.reset_index(drop=True)
    buildings["building_id"] = buildings.index

    sections = load_layer("Buildings_3D")
    sections = sections[(sections["HEIGHT"] > 0) & (sections["HEIGHT"] < 400)].copy()
    sections["section_area"] = sections.geometry.area
    sections["geometry"] = sections.geometry.representative_point()
    joined = gpd.sjoin(
        sections[["HEIGHT", "section_area", "geometry"]],
        buildings[["building_id", "footprint", "geometry"]],
        predicate="within",
    )
    sizeable = joined[joined["section_area"] >= 0.15 * joined["footprint"]]
    height = sizeable.groupby("building_id")["HEIGHT"].max()
    buildings["height"] = buildings["building_id"].map(height)
    return buildings


def load_streets() -> gpd.GeoDataFrame:
    """Load street centerlines, leaving out alleys, ramps and driveways."""
    streets = load_layer("Transport_Streets")
    streets = streets[
        streets["MTFCC"].isin(list(STREET_KINDS))
        & (streets["SEG_TYPE"] == "OTHER CENTERLINE")
    ].copy()
    streets["name"] = streets["STREET_NAM"].fillna(streets["FULL_NAME"]).fillna("?")
    return streets[["name", "geometry"]].reset_index(drop=True)


def load_historic_districts():
    """Return one shape covering both historic districts."""
    return load_layer("Historic_Districts").geometry.union_all()


def load_development_projects() -> gpd.GeoDataFrame:
    """Load outlines of development cases the city has reviewed.

    Used to point a planned-district lot at the approval it was built
    under. The layer mostly covers cases from about 2002 onward.
    """
    projects = gpd.read_file(DATA_DIR / "Development_Projects.geojson")
    projects = projects.to_crs(FEET_CRS)
    projects["geometry"] = projects.geometry.make_valid()
    return projects[~projects.geometry.is_empty].reset_index(drop=True)
