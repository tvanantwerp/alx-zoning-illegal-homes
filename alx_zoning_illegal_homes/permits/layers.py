"""Permit cases read from the city's map layers."""
from alx_zoning_illegal_homes.permits.catalog import case_kind, case_year, normalize_case


def _clean(value) -> str:
    return " ".join(str(value).split()) if value else ""


def _new_case(case: str, source: str) -> dict:
    """An empty case record in the catalog's shape, without ``first_seen``/``last_seen``."""
    return {
        "case": case,
        "kind": case_kind(case),
        "year": case_year(case),
        "descriptions": [],
        "addresses": [],
        "parcel_ids": [],
        "project_names": [],
        "master_cases": [],
        "applicants": [],
        "status": "",
        "documents": [],
        "sources": [source],
        "points": [],
    }


def cases_from_sup_layer(geojson: dict) -> list[dict]:
    """One case per feature of the special use permit layer.

    Each case gets the layer's description, address, status and map point.
    Features whose case number is not one we track are skipped.
    """
    cases = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        case = normalize_case(props.get("PLANNUMBER"))
        if case is None:
            continue
        record = _new_case(case, "sup_layer")
        description = _clean(props.get("DESCRIPTION"))
        address = _clean(props.get("GISAdd"))
        if description:
            record["descriptions"].append(description)
        if address:
            record["addresses"].append(address)
        record["status"] = _clean(props.get("PlanStatus"))
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "Point" and geometry.get("coordinates"):
            lon, lat = geometry["coordinates"][:2]
            record["points"].append([lon, lat])
        cases.append(record)
    return cases


def cases_from_projects(projects: dict) -> list[dict]:
    """One case per feature of the development projects layer that has a readable case number.

    These cases carry the project name and address but no points, because the
    layer holds outlines that are matched to cases later.
    """
    cases = []
    for feature in projects.get("features", []):
        props = feature.get("properties") or {}
        case = normalize_case(props.get("PERMIT_PLAN_CASE"))
        if case is None:
            continue
        record = _new_case(case, "projects_layer")
        name = _clean(props.get("PROJECTNAME"))
        address = _clean(props.get("PROJECTGENLOCATION"))
        if name:
            record["project_names"].append(name)
        if address:
            record["addresses"].append(address)
        cases.append(record)
    return cases
