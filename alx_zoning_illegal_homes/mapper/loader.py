"""Load data from shapefiles and clean as necessary."""
import os
import geopandas as gpd


def load_buildings_2d():
    """Load 2D building data from shapefile and filter it."""
    current_dir = os.path.dirname(__file__)
    shapefile_path = os.path.join(current_dir, "Building.zip")
    buildings_2d = gpd.read_file(f"zip://{shapefile_path}")

    # Filter out the specified BTYPE values
    dwellings = buildings_2d[
        ~buildings_2d["BTYPE"].isin(
            [
                "Garage or shed",
                "Bus shelter",
                "Other",
                "Detached structure",
                "Attached structure",
            ]
        )
    ]

    return dwellings


def load_parcels():
    """Load parcel data from shapefile and filter it."""
    current_dir = os.path.dirname(__file__)
    shapefile_path = os.path.join(current_dir, "Alexandria_Parcels.zip")
    parcels = gpd.read_file(f"zip://{shapefile_path}")

    residential_parcels = parcels[parcels["ZONING"].str.startswith("R", na=False)]

    return residential_parcels


def load_address_points():
    """Load address point data from shapefile and filter it."""
    current_dir = os.path.dirname(__file__)
    shapefile_path = os.path.join(current_dir, "Address_Points.zip")
    address_points = gpd.read_file(f"zip://{shapefile_path}")

    return address_points


def load_buildings_3d():
    """Load 3D building data from shapefile and filter it."""
    current_dir = os.path.dirname(__file__)
    shapefile_path = os.path.join(current_dir, "Buildings_3D.zip")
    buildings_3d = gpd.read_file(f"zip://{shapefile_path}")

    return buildings_3d


def load_road_edges():
    """Load road edge data from shapefile and filter it."""
    current_dir = os.path.dirname(__file__)
    shapefile_path = os.path.join(current_dir, "Road_Edges.zip")
    road_edges = gpd.read_file(f"zip://{shapefile_path}")

    return road_edges
