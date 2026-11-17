"""Build the map data: download layers, check every lot, write the results."""
import json
from pathlib import Path

import shapely

from alx_zoning_illegal_homes.downloader.download import get_data
from alx_zoning_illegal_homes.mapper.analyze import analyze

SITE_DIR = Path(__file__).resolve().parent.parent.parent / "site"
OUTPUT = SITE_DIR / "lots.geojson"

# Short property names keep the file the browser downloads small.
PROPERTY_NAMES = {
    "address": "address",
    "zone": "zone",
    "status": "status",
    "home_type": "type",
    "reasons": "reasons",
    "notes": "notes",
    "year_built": "year",
    "lot_area": "lot_area",
    "homes": "homes",
    "frontage": "frontage",
    "width": "width",
    "height": "height",
    "floor_area_ratio": "far",
    "historic": "historic",
    "district": "district",
    "fallback_zone": "fallback_zone",
    "ordinary_reasons": "ordinary_reasons",
    "case": "case",
}


# Plain descriptions for the assessor's most common non-home land uses.
LAND_USE_DESCRIPTIONS = {
    "VACANT LAND COM AREA": "Shared community land: private streets, alleys "
                            "and green space owned by a homeowners association",
    "VACANT LAND - RESID.": "Vacant residential land",
    "VACANT LAND COMMERC.": "Vacant commercial land",
    "VACANT LAND - APT": "Vacant land for apartments",
    "CITY PKS/PLAYGROUNDS": "City park or playground",
    "CITY VACANT LAND": "Vacant city land",
    "CHURCHES/RELIGIOUS": "Place of worship",
    "GENERAL COMMERCIAL": "Commercial property",
    "OFFICE BUILDINGS": "Office building",
    "JR OFFICE BUILDING": "Small office building",
    "RES SUB PARCEL": "Leftover piece of a residential lot",
    "SUB-PARCEL": "Leftover piece of a lot",
    "ED. PUBLIC SCHOOLS": "Public school",
    "PRIVATE ED INSTS.": "Private school",
}


def _describe_land_use(land_use):
    """Say in plain words what a lot that was not checked is used for."""
    if not isinstance(land_use, str):
        return None
    return LAND_USE_DESCRIPTIONS.get(
        land_use, f"City records list this as: {land_use.capitalize()}")


def _clean(value):
    """Turn a table cell into something JSON can hold, or None to skip it."""
    if value is None or isinstance(value, (list, str, bool)):
        return value or None
    if value != value:  # NaN
        return None
    number = float(value)
    return int(number) if number.is_integer() else round(number, 2)


def export(results, path: Path = OUTPUT) -> None:
    """Write the checked lots as GeoJSON for the web map."""
    results = results.copy()
    results["geometry"] = results.geometry.simplify(0.5).to_crs("EPSG:4326")
    results["geometry"] = shapely.set_precision(results.geometry.values, 1e-6)
    results = results[~results.geometry.is_empty]

    features = []
    for row in results.itertuples(index=False):
        record = row._asdict()
        properties = {}
        for column, name in PROPERTY_NAMES.items():
            value = _clean(record.get(column))
            if value is not None:
                properties[name] = value
        if record["status"] == "not_checked":
            use = _describe_land_use(record.get("land_use"))
            if use:
                properties["use"] = use
        # One flag per kind of problem lets the map filter without parsing.
        for kind in record.get("kinds") or []:
            properties[f"has_{kind}"] = 1
        ordinary_kinds = record.get("ordinary_kinds")
        for kind in ordinary_kinds if isinstance(ordinary_kinds, list) else []:
            properties[f"ordinary_{kind}"] = 1
        properties["problems"] = len(record.get("kinds") or [])
        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": shapely.geometry.mapping(row.geometry),
        })

    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features},
                   separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    """Command line entry point."""
    get_data()
    results = analyze()
    export(results)
    checked = results[results["status"].isin(["illegal", "ok"])]
    illegal = (checked["status"] == "illegal").sum()
    planned = checked["district"].notna().sum()
    print(f"Checked {len(checked):,} lots with homes.")
    print(f"{planned:,} of them are in planned districts, judged by what "
          "their special approvals allow.")
    print(f"{illegal:,} ({illegal / len(checked):.0%}) break at least one "
          "of today's zoning rules.")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
