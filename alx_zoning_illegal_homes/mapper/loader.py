"""Load the city's map layers and tidy them for analysis.

Everything is converted to the Virginia North state plane grid, which is
measured in feet, so lengths and areas match the units in the ordinance.
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

from alx_zoning_illegal_homes.permits.catalog import load_catalog

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
# How the street layer abbreviates the words in street names.
STREET_WORDS = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "ST": "Street", "AVE": "Avenue", "RD": "Road", "DR": "Drive", "PL": "Place",
    "CT": "Court", "LN": "Lane", "TER": "Terrace", "BLVD": "Boulevard",
    "PKWY": "Parkway", "CIR": "Circle", "SQ": "Square", "HWY": "Highway",
    "WAY": "Way", "WY": "Way", "ALY": "Alley", "TRL": "Trail", "PLZ": "Plaza",
    "PSGE": "Passage",
}
# Codes in the city's roads, driveways and parking layer.
PARKING_LOT = 3
ALLEY = 7
OFF_STREET_PARKING = 2


def load_layer(name: str) -> gpd.GeoDataFrame:
    """Read one zipped shapefile from the data folder, in feet."""
    layer = gpd.read_file(DATA_DIR / f"{name}.zip").to_crs(FEET_CRS)
    layer["geometry"] = layer.geometry.make_valid()
    return layer[~layer.geometry.is_empty & layer.geometry.notna()]


def _most_common(values: pd.Series):
    values = values.dropna()
    return values.mode().iloc[0] if len(values) else None


def _id_text(value) -> str | None:
    """Spell a parcel ID as plain text, or None if it is blank or "0".

    Account numbers can arrive as numbers, so 50618820.0 becomes "50618820".
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text if text and text != "0" else None


def parcel_ids_of(group: pd.DataFrame) -> list[str]:
    """Every ID the city uses for the records stacked on one lot, sorted.

    Both the map, block and lot number (PID_RE, "075.01-04-08") and the
    assessor's account number (ACCOUNTNO, "50618820") are kept, since permit
    records use either.
    """
    ids = {_id_text(value) for column in ("PID_RE", "ACCOUNTNO") for value in group[column]}
    return sorted(ids - {None})


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
            "parcel_ids": parcel_ids_of(group),
            "recorded_area": float(group["LAND_SF"].fillna(0).max()),
        })

    info = parcels.groupby("shape_key", sort=False).apply(
        collapse, include_groups=False
    )
    shapes = parcels.drop_duplicates("shape_key").set_index("shape_key").geometry
    lots = gpd.GeoDataFrame(info, geometry=shapes.reindex(info.index), crs=FEET_CRS)
    return lots.reset_index(drop=True)


def load_permits() -> dict[str, dict]:
    """Load the permit catalog, keyed by case number."""
    return load_catalog()


def load_buildings() -> gpd.GeoDataFrame:
    """Load building footprints and attach a height to each.

    Heights come from the city's 3D building layer, which splits a building
    into roof sections. We use the tallest section that covers a meaningful
    part of the footprint, so a chimney or stair tower does not set the
    height of a whole house. Every section is also kept, in the "sections"
    column as (shape, height) pairs, so drawings can show a building's
    lower and higher parts.
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
    # The city writes "YES", "NO" or "No", or leaves it blank.
    retail = buildings["GFRETAIL"].str.strip().str.upper()
    buildings["ground_floor_retail"] = retail.map({"YES": True, "NO": False})
    buildings = buildings.reset_index(drop=True)
    buildings["building_id"] = buildings.index

    sections = load_layer("Buildings_3D")
    sections = sections[(sections["HEIGHT"] > 0) & (sections["HEIGHT"] < 400)].copy()
    sections["section_area"] = sections.geometry.area
    sections["shape"] = sections.geometry
    sections["geometry"] = sections.geometry.representative_point()
    joined = gpd.sjoin(
        sections[["HEIGHT", "section_area", "shape", "geometry"]],
        buildings[["building_id", "footprint", "geometry"]],
        predicate="within",
    )
    sizeable = joined[joined["section_area"] >= 0.15 * joined["footprint"]]
    height = sizeable.groupby("building_id")["HEIGHT"].max()
    buildings["height"] = buildings["building_id"].map(height)
    pairs = joined.groupby("building_id").apply(
        lambda group: list(zip(group["shape"], group["HEIGHT"].astype(float))),
        include_groups=False)
    buildings["sections"] = [pairs.get(i, []) for i in buildings["building_id"]]
    return buildings


def street_label(full_name) -> str | None:
    """Spell out a street's full name as the street layer writes it ("S FAYETTE ST")."""
    if not isinstance(full_name, str) or not full_name.strip():
        return None
    words = full_name.split()
    return " ".join(STREET_WORDS.get(word, word.capitalize()) for word in words)


def load_streets() -> gpd.GeoDataFrame:
    """Load street centerlines, leaving out alleys, ramps and driveways.

    "divided" marks roads with a median, which the layer draws as one
    centerline per side, and "label" is the street's full name spelled out.
    """
    streets = load_layer("Transport_Streets")
    streets = streets[
        streets["MTFCC"].isin(list(STREET_KINDS))
        & (streets["SEG_TYPE"] == "OTHER CENTERLINE")
        # Riddle Walk is private in the city street index (2026, p. 2).
        & ~streets["V_LOCALID"].astype(str).isin(
            {"5151000000911", "5151000002965", "5151000002969"})
    ].copy()
    streets["name"] = streets["STREET_NAM"].fillna(streets["FULL_NAME"]).fillna("?")
    streets["divided"] = streets["DIVIDED"].fillna("").str.upper() == "YES"
    streets["label"] = streets["FULL_NAME"].map(street_label)
    return streets[["name", "divided", "label", "geometry"]].reset_index(drop=True)


def load_paving() -> gpd.GeoDataFrame:
    """Load the city's outlines of roads, alleys, driveways and parking lots.

    These come from the city's planimetric map, traced from aerial photos.
    None of this land counts as open space. "is_parking" marks parking lots
    and driveways the city tags as off-street parking, for the RD zone,
    which lets part of its parking count toward open space. "is_alley"
    marks the alley outlines used by the rear yard rule.
    """
    paving = gpd.read_file(DATA_DIR / "Roads_Driveways_Parking.geojson")
    paving = paving.to_crs(FEET_CRS)
    paving["geometry"] = paving.geometry.make_valid()
    paving = paving[~paving.geometry.is_empty & paving.geometry.notna()]
    paving["is_parking"] = (paving["FEATURE"] == PARKING_LOT) | (
        paving["PARKING"] == OFF_STREET_PARKING)
    paving["is_alley"] = paving["FEATURE"] == ALLEY
    return paving[["is_parking", "is_alley", "geometry"]].reset_index(drop=True)


def load_zoning() -> gpd.GeoDataFrame:
    """Read the city's zoning districts as polygons with their zone labels."""
    return load_layer("Zoning")[["ZONING", "geometry"]].rename(columns={"ZONING": "zone"})


def load_height_districts() -> gpd.GeoDataFrame:
    """Load the height district map: one row per area, with its district code and limit text.

    "district" is the code (HD1 to HD6) and "limit_text" the limit as the city
    writes it ("50'", "30'/50'", "By Zone"). `rules.HEIGHT_MAP_LIMITS` turns
    the text into a rule.
    """
    areas = load_layer("Height_Districts")
    areas = areas.rename(columns={"HEIGHT_DIS": "district", "COMMENTS": "limit_text"})
    return areas[["district", "limit_text", "geometry"]].reset_index(drop=True)


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
