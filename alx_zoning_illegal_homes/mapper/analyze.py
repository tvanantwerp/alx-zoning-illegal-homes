"""Check every lot with a home in the city against today's zoning rules."""
from dataclasses import replace

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import shapely.ops
from shapely.ops import unary_union

from . import loader
from .checks import Home, LotFacts, check_lot
from .lot_lines import MAX_STREET_DISTANCE, classify
from .rule_results import under_special_approval
from .rules import (HOME_TYPE_NAMES, PLANNED_DISTRICTS, king_street_retail_rules,
                    normalize_zone, planned_district_rules, potomac_yard_zone,
                    rules_for)

# A building counts as sitting on a second lot when this much of it does.
STRADDLE_SHARE = 0.15
STRADDLE_AREA = 100.0
# A building with at least this share on one lot belongs wholly to that lot.
WHOLE_BUILDING_SHARE = 0.88
# The part of a shared building on one lot counts as a home there only if it
# is at least this big, and a real share of the building or of the lot.
MIN_PART_AREA = 150.0
MIN_PART_OF_BUILDING = 0.2
MIN_PART_OF_LOT = 0.25
# A small outline is a condo unit, not a lot, when a lot at least this many
# times its size covers at least this share of it.
UNIT_LOT_RATIO = 2.0
UNIT_COVERED_SHARE = 0.8
# Lots west of this longitude are not really in Potomac Yard.
POTOMAC_YARD_WEST_EDGE = -77.06
# Homes on different lots closer than this are treated as attached.
ATTACHED_GAP = 1.5
# Homes this close together count as one attached row.
ROW_GAP = 1.0
HOME_TYPE_BY_BUILDING = {
    "Townhouse": "townhouse",
    "Detached house": "single",
    "Duplex": "semi",
}


def _match_buildings_to_lots(lots, buildings):
    """Find how much of each building sits on each lot it touches."""
    pairs = gpd.sjoin(
        buildings[["building_id", "footprint", "is_home", "geometry"]],
        lots[["geometry"]],
        predicate="intersects",
    ).rename(columns={"index_right": "lot_id"})
    pairs["overlap"] = shapely.area(shapely.intersection(
        pairs.geometry.values, lots.geometry.loc[pairs["lot_id"]].values
    ))
    pairs["lot_area"] = lots.geometry.area.loc[pairs["lot_id"]].values
    return pairs[pairs["overlap"] > 1.0]


def _merge_lots_under_one_home(lots, pairs):
    """Join lots that one owner uses as a single home site.

    A house built across two lots with the same owner is, for zoning, on
    one lot. Without this step the house would look like it has no side
    yard at the line it sits on.
    """
    parent = list(range(len(lots)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    homes = pairs[pairs["is_home"]]
    for _, group in homes.groupby("building_id"):
        if len(group) < 2:
            continue
        group = group.sort_values("overlap", ascending=False)
        main = group.iloc[0]
        owner = lots.at[main["lot_id"], "owner"]
        for _, other in group.iloc[1:].iterrows():
            big_enough = other["overlap"] >= max(
                STRADDLE_AREA, STRADDLE_SHARE * other["footprint"])
            same_owner = owner and lots.at[other["lot_id"], "owner"] == owner
            if big_enough and same_owner:
                parent[find(other["lot_id"])] = find(main["lot_id"])

    roots = np.array([find(i) for i in range(len(lots))])
    if (roots == np.arange(len(lots))).all():
        return lots
    merged = []
    for root, group in lots.groupby(roots):
        lead = lots.loc[root].copy()
        if len(group) > 1:
            lead["geometry"] = unary_union(group.geometry.values)
            lead["recorded_area"] = group["recorded_area"].sum()
            lead["condo_units"] = group["condo_units"].sum()
        merged.append(lead)
    return gpd.GeoDataFrame(
        merged, geometry="geometry", crs=lots.crs).reset_index(drop=True)


def _fold_units_into_their_lots(lots):
    """Remove condo-unit outlines drawn inside a larger lot.

    Some condos appear twice in the parcel layer: once as the land they
    stand on, and again as a small outline for each unit, drawn on top.
    The units are not lots. We count them toward the lot beneath, pass
    along their land use if that lot has none of its own, and drop them.
    """
    areas = lots.geometry.area
    points = gpd.GeoDataFrame(
        {"unit_id": lots.index}, geometry=lots.geometry.representative_point(),
        crs=lots.crs)
    inside = gpd.sjoin(points, lots[["geometry"]], predicate="within").rename(
        columns={"index_right": "lot_id"})
    inside = inside[inside["unit_id"] != inside["lot_id"]]
    inside = inside[areas.loc[inside["lot_id"]].values
                    > UNIT_LOT_RATIO * areas.loc[inside["unit_id"]].values]
    is_home_use = lots["land_use"].isin(list(loader.HOME_TYPE_BY_LAND_USE))
    inside = inside[is_home_use.loc[inside["unit_id"]].values]
    covered = shapely.area(shapely.intersection(
        lots.geometry.loc[inside["unit_id"]].values,
        lots.geometry.loc[inside["lot_id"]].values,
    )) >= UNIT_COVERED_SHARE * areas.loc[inside["unit_id"]].values
    inside = inside[covered]
    # A unit sitting on several stacked lots goes to the smallest of them.
    inside = inside.assign(lot_area=areas.loc[inside["lot_id"]].values)
    inside = inside.sort_values("lot_area").drop_duplicates("unit_id")
    # Lots that are themselves units of something bigger are not hosts.
    inside = inside[~inside["lot_id"].isin(inside["unit_id"])]

    lots = lots.copy()
    for lot_id, units in inside.groupby("lot_id"):
        unit_rows = lots.loc[units["unit_id"]]
        lots.at[lot_id, "condo_units"] += int(
            unit_rows["condo_units"].clip(lower=1).sum())
        if lots.at[lot_id, "land_use"] not in loader.HOME_TYPE_BY_LAND_USE:
            lots.at[lot_id, "land_use"] = unit_rows["land_use"].mode().iloc[0]
    return lots.drop(index=inside["unit_id"]).reset_index(drop=True)


def _polygons_only(shape):
    """Drop stray lines and points left over from cutting shapes."""
    if shape.geom_type in ("Polygon", "MultiPolygon"):
        return shape
    parts = [part for part in getattr(shape, "geoms", [])
             if part.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(parts) if parts else shapely.Polygon()


def _place_buildings(lots, buildings, pairs):
    """Decide which lot, or lots, each building stands on.

    Most buildings sit on one lot. But the city often draws a whole row of
    townhouses or a condo building as one outline across many lots. Such a
    building is cut along the lot lines and each lot gets its own part, so
    every one of those lots is recognized as having a home.

    Returns one row per (building, lot) with the building part on that lot
    and the share of the whole building it represents.
    """
    shapes = buildings.geometry
    lot_shapes = lots.geometry
    rows = []
    for building_id, group in pairs.groupby("building_id"):
        # Where lots overlap on the map, the smaller, more specific one
        # gets first claim on the building.
        group = group.sort_values(["overlap", "lot_area"], ascending=[False, True])
        best = group.iloc[0]
        whole = shapes.loc[building_id]
        if (not best["is_home"]
                or best["overlap"] >= WHOLE_BUILDING_SHARE * best["footprint"]):
            rows.append((building_id, best["lot_id"], whole, 1.0))
            continue
        remaining = whole
        for _, pair in group.sort_values("lot_area").iterrows():
            lot = lot_shapes.loc[pair["lot_id"]]
            part = _polygons_only(remaining.intersection(lot))
            remaining = remaining.difference(lot)
            big_enough = part.area >= MIN_PART_AREA and (
                part.area >= MIN_PART_OF_BUILDING * pair["footprint"]
                or part.area >= MIN_PART_OF_LOT * pair["lot_area"])
            if big_enough:
                rows.append((building_id, pair["lot_id"], part,
                             part.area / pair["footprint"]))
    placed = gpd.GeoDataFrame(
        rows, columns=["building_id", "lot_id", "geometry", "share"],
        geometry="geometry", crs=lots.crs)
    details = buildings.set_index("building_id")[
        ["is_home", "BUSE", "BTYPE", "BSIZE", "BUNITS", "STORIES", "YEARBLT", "height",
         "footprint", "sections"]]
    return placed.join(details, on="building_id")


def _row_sizes(home_shapes, home_lots):
    """Count, for each lot, how many lots its row of attached homes spans.

    1 means free-standing, 2 a twin house, 3 or more a row of townhouses.
    """
    tree = shapely.STRtree(home_shapes)
    left, right = tree.query(home_shapes, predicate="dwithin", distance=ROW_GAP)
    parent = {lot: lot for lot in set(home_lots)}

    def find(lot):
        while parent[lot] != lot:
            parent[lot] = parent[parent[lot]]
            lot = parent[lot]
        return lot

    for a, b in zip(home_lots[left], home_lots[right]):
        if a != b:
            parent[find(a)] = find(b)
    roots = pd.Series({lot: find(lot) for lot in parent})
    return roots.map(roots.value_counts()).to_dict()


def _home_type(lot, homes, row_size):
    """Decide the zoning home type from land use and how homes attach.

    The assessor's labels are loose about twins versus townhouses, so for
    one-home lots the number of attached neighbors has the final say.
    """
    land_use = lot["land_use"]
    if land_use in loader.HOME_TYPE_BY_LAND_USE:
        home_type = loader.HOME_TYPE_BY_LAND_USE[land_use]
        if home_type != "multi" and lot["condo_units"] == 0:
            if row_size >= 3:
                return "townhouse"
            if row_size == 2:
                return "semi"
        return home_type
    if land_use in loader.HOME_TYPE_FROM_BUILDINGS and len(homes):
        common = homes["BTYPE"].mode()
        return HOME_TYPE_BY_BUILDING.get(common.iloc[0] if len(common) else None,
                                         "multi")
    return None


def _potomac_yard_zone(point, lon_lat, route_1):
    """Find a Potomac Yard lot's fallback zone from where it sits.

    Returns "outside" for the few lots that carry the Potomac Yard label
    but lie elsewhere in the city, where its sub-areas mean nothing.
    """
    if lon_lat.x < POTOMAC_YARD_WEST_EDGE:
        return "outside"
    nearest = route_1.interpolate(route_1.project(point))
    distance = point.distance(nearest) if point.x >= nearest.x else -1.0
    return potomac_yard_zone(lon_lat.x, lon_lat.y, distance)


def _king_street_divide(streets):
    """Where the KR zone's two parts meet, as a function of a lot's location.

    The ordinance splits the zone at South Peyton Street on the south side of
    King Street and Harvard Street on the north side. Returns a function
    that says whether a point lies east of that line, or None when the
    streets aren't in the data.
    """
    by_name = {name: unary_union(streets.geometry[streets["name"] == name].values)
               for name in ("KING", "PEYTON", "HARVARD")}
    if any(shape.is_empty for shape in by_name.values()):
        return None
    king = by_name["KING"]
    # Each cross street's x where it meets King Street.
    peyton_x = shapely.ops.nearest_points(by_name["PEYTON"], king)[0].x
    harvard_x = shapely.ops.nearest_points(by_name["HARVARD"], king)[0].x

    def is_east(point) -> bool:
        on_king = king.interpolate(king.project(point))
        north_side = point.y > on_king.y
        return point.x > (harvard_x if north_side else peyton_x)
    return is_east


def _project_for(point, projects, project_tree):
    """Name the city development case whose outline contains a point.

    Where several outlines overlap, the smallest is the most specific.
    Returns text like "Cameron Station Phase VI (DSP2003-00018)", or None.
    """
    hits = project_tree.query(point, predicate="within")
    if not len(hits):
        return None
    best = projects.iloc[min(hits, key=lambda i: projects.geometry.iloc[i].area)]
    # Blank cells arrive as NaN, not as text.
    name, case = (value.strip() if isinstance(value, str) else ""
                  for value in (best["PROJECTNAME"], best["PERMIT_PLAN_CASE"]))
    return f"{name} ({case})" if name and case else name or case or None


def _add_district_totals(records):
    """Compare each planned district's home count with its approved cap.

    The caps apply to a district as a whole, so no single lot can break
    one. The comparison is added to every lot's notes instead.
    """
    totals = {}
    for record in records:
        label = record.get("district_label")
        if label:
            homes, land = totals.get(label, (0, 0.0))
            totals[label] = (homes + record.get("homes", 0),
                             land + record.get("lot_area", 0))
    for record in records:
        label = record.get("district_label")
        if not label:
            continue
        district = PLANNED_DISTRICTS[label]
        homes, land = totals[label]
        if district.home_cap:
            record["notes"].append(
                f"District total: about {homes:,} homes on the lots checked, "
                f"against {district.home_cap:,} allowed.")
        elif district.homes_per_acre_cap and land:
            record["notes"].append(
                f"District total: about {homes / (land / 43560):.0f} homes "
                "per acre on the lots checked, against "
                f"{district.homes_per_acre_cap:g} allowed.")


def _lot_area(lot):
    """Prefer the assessor's recorded land area when it agrees with the map."""
    drawn = lot.geometry.area
    recorded = lot["recorded_area"]
    if recorded and 0.8 <= recorded / drawn <= 1.25:
        return float(recorded)
    return float(drawn)


def _floor_area(part):
    """Floor space from city records, or estimated from outline and stories.

    A lot holding only part of a building gets that share of its floor space.
    """
    if part["BSIZE"] and part["BSIZE"] > 0:
        return float(part["BSIZE"] * part["share"])
    if part["STORIES"] and part["STORIES"] > 0:
        # Outlines include eaves and porches, so trim the estimate.
        return float(part["footprint"] * part["share"] * part["STORIES"] * 0.8)
    return None


def analyze(keep_facts: dict | None = None) -> gpd.GeoDataFrame:
    """Return one row per lot with its status and the reasons it fails.

    Pass a dict as keep_facts to receive the raw inputs of every checked
    lot, keyed by row number, for debugging and drawing.

    status is "illegal" (breaks at least one rule), "ok" (no problem
    found), or "not_checked" (no home, or a zone this project has no rules
    for). Lots in planned districts are judged by what the district's
    special approval allows. They also carry "ordinary_reasons": how they
    would fare under the ordinary zone that applies without that approval.
    """
    lots = loader.load_lots()
    buildings = loader.load_buildings()
    streets = loader.load_streets()
    historic = loader.load_historic_districts()

    buildings["BSIZE"] = buildings["BSIZE"].fillna(0)
    buildings["STORIES"] = buildings["STORIES"].fillna(0)
    buildings["height"] = buildings["height"].fillna(
        buildings["STORIES"].where(buildings["STORIES"] > 0) * 10)

    lots = _fold_units_into_their_lots(lots)
    pairs = _match_buildings_to_lots(lots, buildings)
    lots = _merge_lots_under_one_home(lots, pairs)
    pairs = _match_buildings_to_lots(lots, buildings)
    placed = _place_buildings(lots, buildings, pairs)

    lot_shapes = lots.geometry.values
    lot_tree = shapely.STRtree(lot_shapes)
    street_shapes, street_names = streets.geometry.values, streets["name"].values
    street_tree = shapely.STRtree(street_shapes)
    home_parts = placed[placed["is_home"]]
    home_shapes, home_lots = home_parts.geometry.values, home_parts["lot_id"].values
    home_tree = shapely.STRtree(home_shapes)
    row_sizes = _row_sizes(home_shapes, home_lots)
    parts_by_lot = dict(tuple(placed.groupby("lot_id")))
    lot_points = lots.geometry.representative_point()
    in_historic = lot_points.within(historic)
    lot_lon_lat = lot_points.to_crs("EPSG:4326")
    route_1 = unary_union(streets.geometry[streets["name"] == "RICHMOND"].values)
    kr_is_east = _king_street_divide(streets)
    projects = loader.load_development_projects()
    project_tree = shapely.STRtree(projects.geometry.values)

    records = []
    for lot_id, lot in lots.iterrows():
        record = {
            "address": lot["address"],
            "zone": lot["zoning_label"],
            "status": "not_checked",
            "land_use": lot["land_use"],
            "home_type": None,
            "reasons": [],
            "kinds": [],
            "notes": [],
        }
        records.append(record)
        on_lot = parts_by_lot.get(lot_id)
        if on_lot is None:
            continue
        homes = on_lot[on_lot["is_home"]]
        home_type = _home_type(lot, homes, row_sizes.get(lot_id, 1))
        if home_type is None or homes.empty:
            continue
        years = homes["YEARBLT"][homes["YEARBLT"] > 1600]
        record["home_type"] = HOME_TYPE_NAMES[home_type]
        record["year_built"] = int(years.min()) if len(years) else None

        is_historic = bool(in_historic.loc[lot_id])
        label = lot["zoning_label"]
        zone = normalize_zone(label)
        district = fallback_rules = None
        if zone is not None:
            rules = rules_for(zone, is_historic)
            if zone == "KR" and kr_is_east is not None:
                rules = king_street_retail_rules(
                    kr_is_east(lot_points.loc[lot_id]),
                    residential_only=on_lot["BUSE"].eq("Residential").fillna(False).all())
        else:
            sub_zone = None
            if isinstance(label, str) and label.strip().upper() == "CDD#10":
                sub_zone = _potomac_yard_zone(
                    lot_points.loc[lot_id], lot_lon_lat.loc[lot_id], route_1)
            planned = (planned_district_rules(label, is_historic, sub_zone)
                       if sub_zone != "outside" else None)
            if planned is None:
                continue
            district, rules, fallback_rules = planned

        shape = lot.geometry
        nearby = lot_tree.query(shape.buffer(3.0), predicate="intersects")
        neighbors = [
            lot_shapes[i] for i in nearby
            # Skip the lot itself and any larger lot drawn on top of it.
            if i != lot_id
            and lot_shapes[i].intersection(shape).area < 0.5 * shape.area
        ]
        neighbor_shape = unary_union(neighbors) if neighbors else None
        near_streets = street_tree.query(
            shape.buffer(MAX_STREET_DISTANCE), predicate="intersects")
        lines = classify(
            shape, neighbor_shape,
            [(street_names[i], street_shapes[i]) for i in near_streets],
            lot["address_street"],
        )

        home_union = unary_union(homes.geometry.values)
        touching = home_tree.query(home_union.buffer(ATTACHED_GAP),
                                   predicate="intersects")
        attached = [home_shapes[i] for i in touching if home_lots[i] != lot_id]

        units = 1
        if home_type == "multi":
            recorded_units = (homes["BUNITS"].fillna(0) * homes["share"]).sum()
            units = int(max(lot["condo_units"], round(recorded_units), 1))
        elif home_type == "townhouse":
            units = int(max(lot["condo_units"], len(homes), 1))

        facts = LotFacts(
            shape=shape,
            area=_lot_area(lot),
            rules=rules,
            home_type=home_type,
            homes=[
                Home(
                    shape=part.geometry,
                    height=part["height"] if pd.notna(part["height"]) else None,
                    floor_area=_floor_area(part),
                    sections=part["sections"],
                )
                for _, part in homes.iterrows()
            ],
            lines=lines,
            units=units,
            all_buildings=list(on_lot.geometry.values),
            building_sections=list(on_lot["sections"]),
            attached_neighbors=unary_union(attached) if attached else None,
            in_historic_district=is_historic,
        )
        findings = check_lot(facts)
        if keep_facts is not None:
            keep_facts[lot_id] = facts
        if district:
            # Second opinion: the same home under the ordinary zone that
            # would apply if the district's special approval did not exist.
            ordinary = check_lot(replace(facts, rules=fallback_rules))
            findings.results = under_special_approval(findings.results, district)
            project = _project_for(lot_points.loc[lot_id], projects, project_tree)
            record.update({
                "district": district.name,
                "district_label": label.strip().upper(),
                "fallback_zone": fallback_rules.name,
                "ordinary_reasons": [r.text for r in ordinary.reasons],
                "ordinary_kinds": sorted({r.kind for r in ordinary.reasons}),
                "ordinary_rule_results": ordinary.results,
                "ordinary_notes": ordinary.notes,
                "case": project,
            })
            findings.notes.insert(0, (
                f"This lot is in the {district.name} planned district "
                f"({label.strip()}), built under a special approval from City "
                f"Council. {district.plan_summary} Lot sizes and yards there "
                "are fixed by the approved site plan drawings, not by general "
                "rules, so they are not judged."
                + (f" City case file: {project}." if project else "")))
        record.update({
            "zone": label.strip() if district else rules.name,
            "status": "illegal" if findings.reasons else "ok",
            "reasons": [reason.text for reason in findings.reasons],
            "kinds": sorted({reason.kind for reason in findings.reasons}),
            "notes": findings.notes,
            "rule_results": findings.results,
            "lot_area": round(facts.area),
            "homes": units,
            "historic": is_historic,
            **{key: (round(value, 2) if isinstance(value, float) else value)
               for key, value in findings.measurements.items()
               if value is not None},
        })

    _add_district_totals(records)
    return gpd.GeoDataFrame(records, geometry=lots.geometry.values, crs=lots.crs)
