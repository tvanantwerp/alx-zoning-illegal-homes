"""Uses shapefile data to generate map of non-conforming dwellings."""
import os
import geopandas as gpd
from alx_zoning_illegal_homes.downloader.download import get_data


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


def main():
    get_data()


if __name__ == "__main__":
    main()
