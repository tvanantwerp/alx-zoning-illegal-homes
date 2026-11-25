"""Build the map data: download layers, check every lot, write the results."""
import json
from pathlib import Path

import shapely

from alx_zoning_illegal_homes.downloader.download import DATA_DIR, get_data
from alx_zoning_illegal_homes.mapper.analyze import analyze
from alx_zoning_illegal_homes.mapper.lot_files import LOTS_DIR, replace_lot_files

SITE_DIR = Path(__file__).resolve().parent.parent.parent / "site"
OUTPUT = SITE_DIR / "lots.geojson"
NEEDED_PERMITS = DATA_DIR / "permits" / "needed.json"

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
    "skipped": "skipped",
    "permit_count": "permits",
}
# Properties where 0 means there is nothing to show, so it's left out like other empty values.
ZERO_IS_EMPTY = {"permit_count"}


# Plain descriptions for the assessor's land use codes, shown on lots that
# were not checked. Codes not listed here are shown as the city writes them.
LAND_USE_DESCRIPTIONS = {
    "VACANT LAND COM AREA": "Shared community land: private streets, alleys "
                            "and green space owned by a homeowners association",
    "VACANT LAND - RESID.": "Vacant residential land",
    "VACANT LAND COMMERC.": "Vacant commercial land",
    "VACANT LAND - APT": "Vacant land for apartments",
    "VACANT LAND - INDUST": "Vacant industrial land",
    "CITY PKS/PLAYGROUNDS": "City park or playground",
    "CITY VACANT LAND": "Vacant city land",
    "CITY AVAILABLE USE": "City-owned land",
    "CITY GOVT BLDGS": "City government building",
    "CITY LEASED TO OTHER": "City-owned land leased to someone else",
    "CITY LIBRARIES": "City library",
    "CITY PARKING": "City parking lot or garage",
    "CITY REC/CUL/CENTERS": "City recreation or cultural center",
    "BOARDS/COMMISSIONS": "City board or commission property",
    "ALEX.REDV.HOUS.AUTH": "Alexandria Redevelopment and Housing Authority property",
    "FEDERAL": "Federal government property",
    "STATE/GENERAL": "State government property",
    "REGIONAL/GENERAL": "Regional government property",
    "WASH METRO TRAN AUTH": "Metro (WMATA) property",
    "SANITATION AUTHORITY": "Sewer authority property",
    "ELE LG & POW COM SCC": "Electric utility property",
    "TELPH/TELGR CO SCC": "Phone company property",
    "WATER CORP. SCC": "Water company property",
    "OP.RAILROAD VDT": "Railroad tracks in use",
    "RAILROAD PROPERTY": "Railroad property",
    "CHURCHES/RELIGIOUS": "Place of worship",
    "RES. RELIGIOUS": "Housing for a religious order",
    "CHARITABLE": "Charity property",
    "GENERAL COMMERCIAL": "Commercial property",
    "OFFICE BUILDINGS": "Office building",
    "JR OFFICE BUILDING": "Small office building",
    "OFFICE/COMM WHSE": "Office or warehouse",
    "CONDO/OFFICE": "Office condo",
    "RETAIL CONDO": "Shop condo",
    "CONDO MASTER CARDS": "Condo building's shared land",
    "SHOPPING CENTERS": "Shopping center",
    "RESTAURANT/FST FOOD": "Restaurant",
    "FAST FOOD": "Fast food restaurant",
    "FINANCIAL INST": "Bank",
    "SERVICE STATIONS": "Gas station",
    "GAS KIOSK": "Gas station",
    "INDUSTRIAL FLEX": "Industrial building",
    "INDUST. WASTE ENERGY": "Waste-to-energy plant",
    "HOTEL AND MOTEL": "Hotel or motel",
    "EXTENDED STAY": "Extended-stay hotel",
    "FACULTY/STF HOUSING": "School staff housing",
    "HOSPITALS": "Hospital",
    "NURSING HOME": "Nursing home",
    "FUNERAL HOME": "Funeral home",
    "VETERINARY CLINIC": "Veterinary clinic",
    "DRUG STORE": "Drug store",
    "CONVENIENCE STORE": "Convenience store",
    "AUTO DEALERSHIP": "Car dealership",
    "REPAIR SERVICES": "Repair shop",
    "SELF STORAGE FACILITY": "Self-storage building",
    "PARKING GARAGE": "Parking garage",
    "PRIVATE CEMETERIES": "Private cemetery",
    "PUBLIC CEMETERIES": "Public cemetery",
    "RES SUB PARCEL": "Leftover piece of a residential lot",
    "SUB-PARCEL": "Leftover piece of a lot",
    "Legal Parcel beneath Leased": "Land under a leased building",
    "ED. PUBLIC SCHOOLS": "Public school",
    "PRIVATE ED INSTS.": "Private school",
    "ST. ED. INSTITUTIONS": "State college property",
    "ROW (TOWNHOUSE)": "City records list this as a townhouse",
    "SEMI-DETACHED HOUSE": "City records list this as half of a twin house",
    "DETACHED HOUSE": "City records list this as a detached house",
    "CONDO (TOWNHOUSE)": "City records list this as a townhouse condo",
    "CONDO (GARDEN)": "City records list this as a low-rise condo building",
    "CONDO (HI-RISE)": "City records list this as a high-rise condo building",
    "GARDEN APT 3 ST OR <": "City records list this as an apartment building of 3 stories or fewer",
    "MED RISE ELEV (4-6S)": "City records list this as an apartment building of 4 to 6 stories",
    "HI-RISE (7 ST AND UP": "City records list this as an apartment building of 7 stories or more",
    "SMALL APTS": "City records list this as a small apartment building",
    "COOPERATIVE": "City records list this as a co-op apartment building",
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
    for row in results.itertuples(index=True):
        record = row._asdict()
        properties = {}
        if record["status"] in ("illegal", "ok"):
            properties["id"] = int(row.Index)
        for column, name in PROPERTY_NAMES.items():
            value = _clean(record.get(column))
            if column in ZERO_IS_EMPTY and value == 0:
                continue
            if value is not None:
                properties[name] = value
        # A home skipped for its zone already shows its home type, which the
        # city's land use label would only repeat or contradict.
        if record["status"] == "not_checked" and _clean(record.get("home_type")) is None:
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


def write_needed_permits(results, path: Path = NEEDED_PERMITS) -> int:
    """Write the sorted case numbers matched to a checked home lot, for `collect-permits --documents`.

    Returns how many there are.
    """
    checked = results[results["status"].isin(["illegal", "ok"])]
    cases = sorted({permit["case"] for permits in checked["permits"]
                    if isinstance(permits, list) for permit in permits})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, indent=0) + "\n", encoding="utf-8")
    return len(cases)


def main() -> None:
    """Command line entry point."""
    get_data()
    facts = {}
    results = analyze(keep_facts=facts)
    # The map links each lot to its file by id, so the files go in place first.
    count = replace_lot_files(results, facts)
    export(results)
    needed = write_needed_permits(results)
    checked = results[results["status"].isin(["illegal", "ok"])]
    illegal = (checked["status"] == "illegal").sum()
    planned = checked["district"].notna().sum()
    print(f"Checked {len(checked):,} lots with homes.")
    print(f"{planned:,} of them are in planned districts, judged by what "
          "their approved plans allow.")
    print(f"{illegal:,} ({illegal / len(checked):.0%}) break at least one "
          "of today's zoning rules.")
    print(f"Wrote {OUTPUT}")
    print(f"Wrote {count:,} lot files to {LOTS_DIR}")
    with_permits = (checked["permit_count"] > 0).sum()
    print(f"{with_permits:,} checked lots have city cases on file; "
          f"wrote {needed:,} case numbers to {NEEDED_PERMITS}")


if __name__ == "__main__":
    main()
