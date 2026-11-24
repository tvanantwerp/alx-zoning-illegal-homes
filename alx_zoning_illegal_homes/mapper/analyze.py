"""Check every lot with a home in the city against today's zoning rules."""
import warnings
from dataclasses import replace

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import shapely.ops
from shapely.ops import unary_union

from . import loader
from .block_faces import BlockFaces
from .places import near_a_station, near_eisenhower_avenue, station_points
from .checks import Home, LotFacts, Outbuilding, TownhouseRow, check_lot
from .lot_lines import MAX_DIVIDED_GAP, MAX_STREET_DISTANCE, Street, classify
from .rule_results import under_special_approval
from .rules import (HOME_TYPE_NAMES, MAX_TOWNHOUSES_IN_ROW, PLANNED_DISTRICTS,
                    braddock_gateway_fallback, duke_street_floor_area, height_map_limit,
                    king_street_retail_rules, normalize_zone, office_high_rules,
                    named_street_setbacks, planned_district_rules, potomac_yard_fallback,
                    route_1_properties_fallback, rules_for, zoning_key)

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
# A piece too small to count joins a counted piece of the same building
# that lies within this distance.
JOIN_GAP = 0.5
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
# For the limit on townhouses in one building, homes join a row only where
# their outlines run together, this close, for at least MIN_SHARED_WALL feet:
# a shared wall, not two rows whose corners meet across an alley.
WALL_GAP = 0.5
MIN_SHARED_WALL = 4.0
# The pop-up outlines at most this many of the other buildings in a row.
MAX_ROW_OUTLINES = 40
# Building outlines in a row drawing are simplified to within this many feet.
ROW_OUTLINE_TOLERANCE = 0.5
# Building outlines are traced from roofs, so they take in eaves and
# porches. Where floor space is estimated from an outline, each story is
# taken to cover this share of it.
OUTLINE_FLOOR_SHARE = 0.8
# An outbuilding shorter than this in the city's 3D data holds one story.
TWO_STORY_OUTBUILDING = 18.0
# What to call buildings that aren't homes, by the city's building type.
OUTBUILDING_LABELS = {"Garage or shed": "garage or shed"}
# A lot the assessor calls half of a twin, holding one detached house with
# no other home this close, is judged as a detached house.
LONE_HOUSE_GAP = 6.0
TWIN_LAND_USE = "SEMI-DETACHED HOUSE"
TWO_UNIT_NOTE = (
    "City land records call this a semi-detached house, and the map finds both "
    "halves of the twin on this one lot, so it is judged as a whole two-unit house. "
    "Both of its homes need room on this lot.")
LONE_HOUSE_NOTE = (
    "City land records call this a semi-detached house (one half of a twin), but "
    "the city's map shows a detached house here with no other home within "
    f"{LONE_HOUSE_GAP:.0f} ft, so it is judged as a detached house.")
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


def _mapped_zone_labels(lots: gpd.GeoSeries, zoning: gpd.GeoDataFrame) -> pd.Series:
    """Select the zone covering the most area on each lot, if any."""
    districts = zoning.assign(zone=zoning["zone"].map(zoning_key)).dissolve(by="zone")
    lot_ids, district_ids = districts.sindex.query(lots, predicate="intersects")
    overlap = shapely.area(shapely.intersection(
        lots.values[lot_ids], districts.geometry.values[district_ids]))
    candidates = pd.DataFrame({"lot": lot_ids,
                               "zone": districts.index.to_numpy()[district_ids],
                               "overlap": overlap})
    largest = (candidates[candidates["overlap"] > 0]
               .sort_values(["overlap", "zone"], ascending=[False, True])
               .drop_duplicates("lot").set_index("lot"))
    return pd.Series(largest["zone"].reindex(range(len(lots))).to_numpy(), index=lots.index)


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


def _join_small_pieces(counted, small):
    """Fold pieces of a building too small to count into the counted piece beside them.

    When the city draws a lot line a few feet inside a building, a thin strip
    of it lands on the neighboring lot. That strip is too small to count as
    a home there, but dropping it would open a gap where the building really
    meets its neighbor, hiding the shared wall between twin halves or
    townhouses. Instead each strip joins the counted piece it touches most.
    A strip that touches no counted piece is dropped.

    `counted` maps lot id to that lot's counted piece, and `small` lists the
    other pieces. Returns `counted` with the strips joined in.
    """
    counted = dict(counted)
    small = [polygon for piece in small for polygon in shapely.get_parts(piece)
             if not polygon.is_empty]
    # Joining a strip can bring another strip into reach, so repeat until
    # nothing more joins.
    while counted and small:
        contact, index, lot_id = max(
            (part.buffer(JOIN_GAP).intersection(piece).area, i, lot_id)
            for i, part in enumerate(small) for lot_id, piece in counted.items())
        if contact <= 0:
            break
        counted[lot_id] = unary_union([counted[lot_id], small.pop(index)])
    return counted


def _place_buildings(lots, buildings, pairs):
    """Decide which lot, or lots, each building stands on.

    Most buildings sit on one lot. But the city often draws a whole row of
    townhouses or a condo building as one outline across many lots. Such a
    building is cut along the lot lines and each lot gets its own part, so
    every one of those lots is recognized as having a home. Pieces too
    small to count as a home stay with the counted piece they touch.

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
        if best["overlap"] >= WHOLE_BUILDING_SHARE * best["footprint"]:
            rows.append((building_id, best["lot_id"], whole, 1.0))
            continue
        remaining = whole
        counted, small = {}, []
        for _, pair in group.sort_values("lot_area").iterrows():
            lot = lot_shapes.loc[pair["lot_id"]]
            part = _polygons_only(remaining.intersection(lot))
            remaining = remaining.difference(lot)
            if best["is_home"]:
                big_enough = part.area >= MIN_PART_AREA and (
                    part.area >= MIN_PART_OF_BUILDING * pair["footprint"]
                    or part.area >= MIN_PART_OF_LOT * pair["lot_area"])
            else:
                # Garages and sheds are often smaller than MIN_PART_AREA, so
                # only the piece's share of the building decides.
                big_enough = part.area >= MIN_PART_OF_BUILDING * pair["footprint"]
            if big_enough:
                counted[pair["lot_id"]] = part
            else:
                small.append(part)
        if not counted and not best["is_home"]:
            rows.append((building_id, best["lot_id"], whole, 1.0))
            continue
        for lot_id, part in _join_small_pieces(counted, small).items():
            rows.append((building_id, lot_id, part, part.area / best["footprint"]))
    placed = gpd.GeoDataFrame(
        rows, columns=["building_id", "lot_id", "geometry", "share"],
        geometry="geometry", crs=lots.crs)
    details = buildings.set_index("building_id")[
        ["is_home", "BUSE", "BTYPE", "BSIZE", "BUNITS", "STORIES", "YEARBLT", "height",
         "footprint", "sections", "ground_floor_retail"]]
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


def _union_groups(count: int, left, right) -> np.ndarray:
    """Join items 0..count-1 linked by the pairs (left[i], right[i]); return each one's group."""
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in zip(left, right):
        parent[find(a)] = find(b)
    return np.array([find(i) for i in range(count)])


def _wall_segments(shape):
    for polygon in shapely.get_parts(shape.simplify(0.1)):
        coords = np.asarray(polygon.exterior.coords)[:, :2]
        for start, end in zip(coords, coords[1:]):
            length = np.linalg.norm(end - start)
            if length >= MIN_SHARED_WALL:
                yield (end - start) / length, shapely.LineString([start, end])


def _parallel_wall(a, b):
    other = list(_wall_segments(b))
    for direction, wall in _wall_segments(a):
        band = wall.buffer(WALL_GAP, cap_style="flat")
        for facing, segment in other:
            if abs(direction @ facing) < 0.97:
                continue
            if segment.intersection(band).length >= MIN_SHARED_WALL:
                return True
    return False


def _shared_walls(home_shapes) -> tuple[np.ndarray, np.ndarray]:
    """Pairs of home outlines that share a wall: they run together for at least MIN_SHARED_WALL."""
    left, right = shapely.STRtree(home_shapes).query(home_shapes, predicate="dwithin",
                                                     distance=WALL_GAP)
    keep = left < right
    left, right = left[keep], right[keep]
    a, b = home_shapes[left], home_shapes[right]
    # Measure both ways, so a long wall can't pass on the strength of a short one.
    along = np.minimum(
        shapely.length(shapely.intersection(shapely.boundary(a), shapely.buffer(b, WALL_GAP))),
        shapely.length(shapely.intersection(shapely.boundary(b), shapely.buffer(a, WALL_GAP))))
    keep = [i for i in np.flatnonzero(along >= MIN_SHARED_WALL) if _parallel_wall(a[i], b[i])]
    return left[keep], right[keep]


def _long_side(shape) -> float:
    """The long side of the smallest rectangle, turned to any angle, that holds a shape."""
    # GEOS warns, harmlessly, about some outlines with nearly straight runs of points.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rectangle = shapely.oriented_envelope(shape)
    if rectangle.geom_type != "Polygon":
        return float(rectangle.length)
    corners = np.array(rectangle.exterior.coords)
    return float(max(np.hypot(*(corners[1] - corners[0])), np.hypot(*(corners[2] - corners[1]))))


def _row_outlines(group: pd.DataFrame, lot_id: int) -> tuple[list, bool]:
    """Outlines of a row's buildings on lots other than this one, nearest first.

    Each building's pieces on other lots are joined and simplified. Returns
    at most MAX_ROW_OUTLINES of them, and whether that was all of them.
    """
    others = group[group["lot_id"] != lot_id]
    if others.empty:
        return [], True
    here = unary_union(group.geometry[group["lot_id"] == lot_id].values)
    outlines = [unary_union(pieces.values).simplify(ROW_OUTLINE_TOLERANCE)
                for _, pieces in others.geometry.groupby(others["building_id"])]
    outlines.sort(key=here.distance)
    return outlines[:MAX_ROW_OUTLINES], len(outlines) <= MAX_ROW_OUTLINES


def _home_sites(parts: pd.DataFrame, lots: gpd.GeoDataFrame) -> dict:
    """Group lots that hold one home recorded as several parcels.

    Some condo townhouses are recorded as a unit parcel plus a second parcel
    beside it, each holding part of the same building. So exactly two lots
    holding pieces of exactly the same buildings, at least one of them a
    condo, are one site. Their addresses can't confirm it: the city often
    gives the second parcel a neighbor's street number. Three or more lots
    sharing one outline are a row drawn as a single building, each lot its
    own home. Lots beside each other in an ordinary row hold different sets,
    since each home's outline is cut along its own lot lines. Returns each
    lot id's site, keyed by lot id.
    """
    held = parts.groupby("lot_id")["building_id"].agg(frozenset)
    condo = lots.loc[held.index, "condo_units"].values > 0
    sites = {}
    for buildings, group in pd.Series(held.index, index=held.values).groupby(level=0):
        lot_ids = list(group.values)
        if len(lot_ids) == 2 and condo[held.index.get_indexer(lot_ids)].any():
            sites |= {lot_id: lot_ids[0] for lot_id in lot_ids}
        else:
            sites |= {lot_id: lot_id for lot_id in lot_ids}
    return sites


def _townhouse_rows(home_parts: gpd.GeoDataFrame, lots: gpd.GeoDataFrame) -> dict:
    """Find the row of attached homes each lot's homes stand in, for the townhouse row limit.

    Stricter than `_row_sizes`: homes join only where they share a wall (see
    `_shared_walls`), and the pieces of one building cut by lot lines always
    stay together. When each home was built doesn't matter; the rule counts
    the homes in "a single structure".

    Homes are counted, not outlines. Each lot in the row counts as one home,
    since the city often draws a townhouse a few feet off its lot lines, so
    one home's outline spreads over two lots. A condo lot counts each of its
    building outlines in the row instead. A home recorded as two parcels
    counts once (see `_home_sites`). A lot not used for homes adds none, but
    still joins the homes on either side of it.

    Returns a TownhouseRow for each lot with homes, keyed by lot id. Where a
    lot's homes stand in several rows, prioritize a row too long for a permit.
    """
    parts = home_parts[["building_id", "lot_id", "geometry"]].reset_index(drop=True)
    shapes = parts.geometry.values
    left, right = _shared_walls(shapes)
    same_building = parts.groupby("building_id").indices.values()
    left = np.concatenate([left] + [group[1:] for group in same_building])
    right = np.concatenate([right] + [np.full(len(group) - 1, group[0])
                                      for group in same_building])
    parts["row"] = _union_groups(len(parts), left, right)
    parts["site"] = parts["lot_id"].map(_home_sites(parts, lots))

    home_uses = set(loader.HOME_TYPE_BY_LAND_USE) | set(loader.HOME_TYPE_FROM_BUILDINGS)
    rows = {}
    for _, group in parts.groupby("row"):
        lot_ids = group["lot_id"].unique()
        homes = 0
        for _, site in group.groupby("site"):
            site_lots = site["lot_id"].unique()
            if (lots.loc[site_lots, "condo_units"] > 0).any():
                homes += site["building_id"].nunique()
            elif lots.loc[site_lots, "land_use"].isin(home_uses).any():
                homes += 1
        length = _long_side(unary_union(group.geometry.values))
        for lot_id in lot_ids:
            row = TownhouseRow(homes=max(homes, 1), length=length)
            if lot_id in rows and rows[lot_id].severity >= row.severity:
                continue
            if homes > MAX_TOWNHOUSES_IN_ROW:
                row.outlines, row.all_outlined = _row_outlines(group, lot_id)
            rows[lot_id] = row
    return rows


def _has_attached_homes(shapes) -> bool:
    """Whether at least two of these home outlines touch, or nearly touch."""
    left, right = shapely.STRtree(shapes).query(shapes, predicate="dwithin",
                                                distance=ROW_GAP)
    return bool((left != right).any())


def _home_type(lot, homes, row_size, alone=False):
    """Decide the zoning home type from land use and how homes attach.

    The assessor's labels are loose about twins versus townhouses, so for
    one-home lots the number of attached neighbors has the final say.

    A lot labeled as half of a twin needs a closer look when its homes
    attach to no home on another lot. If it holds exactly two attached
    home outlines, both halves stand on this one lot: a whole two-unit
    house. If it holds a single outline drawn as a detached house, and
    `alone` says no other home stands within LONE_HOUSE_GAP, it is judged
    as the detached house it looks like. A detached house with an apartment
    inside is labeled a detached house, so it never becomes a two-unit house.
    """
    land_use = lot["land_use"]
    if land_use in loader.HOME_TYPE_BY_LAND_USE:
        home_type = loader.HOME_TYPE_BY_LAND_USE[land_use]
        if home_type != "multi" and lot["condo_units"] == 0:
            if row_size >= 3:
                return "townhouse"
            if row_size == 2:
                return "semi"
            if land_use == TWIN_LAND_USE and len(homes) == 2 and _has_attached_homes(
                    homes.geometry.values):
                return "two_unit"
            if (land_use == TWIN_LAND_USE and alone and len(homes) == 1
                    and homes["BTYPE"].iloc[0] == "Detached house"):
                return "single"
        return home_type
    if land_use in loader.HOME_TYPE_FROM_BUILDINGS and len(homes):
        common = homes["BTYPE"].mode()
        return HOME_TYPE_BY_BUILDING.get(common.iloc[0] if len(common) else None,
                                         "multi")
    return None


def _potomac_yard_fallback(point, lon_lat, route_1):
    """Find a Potomac Yard lot's fallback zone and changes to it from where it sits.

    Returns ("outside", {}) for the few lots that carry the Potomac Yard label
    but lie elsewhere in the city, where its sub-areas mean nothing.
    """
    if lon_lat.x < POTOMAC_YARD_WEST_EDGE:
        return "outside", {}
    nearest = route_1.interpolate(route_1.project(point))
    distance = point.distance(nearest) if point.x >= nearest.x else -1.0
    return potomac_yard_fallback(lon_lat.x, lon_lat.y, distance)


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


def _street(streets, name):
    """One street's centerline, all its segments together."""
    return unary_union(streets.geometry[streets["name"] == name].values)


def _district_fallback(label, lot, point, places):
    """The fallback zone and changes for planned districts where they depend on location.

    Returns (zone, changes), where zone None keeps the district's usual
    fallback zone, or "outside" for a Potomac Yard lot that lies elsewhere.
    """
    if label == "CDD#10":
        return _potomac_yard_fallback(point, places["lon_lat"], places["route_1"])
    if label == "CDD#1":
        return None, duke_street_floor_area(near_a_station(
            lot.geometry, places["stations"], ["King Street-Old Town"]))
    if label == "CDD#7":
        on_reed = str(lot["address_street"]).strip().upper() == "REED"
        commonwealth = places["commonwealth"]
        return route_1_properties_fallback(
            on_reed, point.distance(commonwealth) if not commonwealth.is_empty else None)
    if label == "CDD#15":
        corner = places["first_and_fayette"]
        return braddock_gateway_fallback(
            point.distance(corner) if not corner.is_empty else None)
    return None, {}


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
                f"Across all of {district.name}, the lots this map checked hold "
                f"about {homes:,} homes. The plan allows up to "
                f"{district.home_cap:,} in the whole district.")
        elif district.homes_per_acre_cap and land:
            record["notes"].append(
                f"Across all of {district.name}, the lots this map checked hold "
                f"about {homes / (land / 43560):.0f} homes per acre. The plan "
                f"allows up to {district.homes_per_acre_cap:g} per acre across "
                "the district.")


def _paving_on(shape, tree, paving_shapes, is_parking):
    """Return the roads, driveways and parking on a lot, and the parking alone.

    Either is None when the lot has none.
    """
    nearby = tree.query(shape, predicate="intersects")
    if nearby.size == 0:
        return None, None
    paved = unary_union(paving_shapes[nearby]).intersection(shape)
    parking_parts = paving_shapes[nearby[is_parking[nearby]]]
    parking = (unary_union(parking_parts).intersection(shape)
               if parking_parts.size else None)
    return (paved if paved.area > 0 else None,
            parking if parking is not None and parking.area > 0 else None)


def _height_map_areas(footprints, areas):
    """Index each numbered district intersecting a home, keeping boundary cuts."""
    labels = zip(areas["district"], areas["limit_text"])
    rules = {key: height_map_limit(*key) for key in set(labels)}
    by_home = {}
    for i, j in zip(*areas.sindex.query(footprints, predicate="intersects")):
        area = areas.iloc[j]
        rule = rules[area.district, area.limit_text]
        if rule.height is None:
            continue
        outline = footprints.iloc[i]
        covered = None if area.geometry.covers(outline) else outline.intersection(area.geometry)
        if covered is None or covered.area > 0:
            by_home.setdefault(footprints.index[i], []).append((covered, rule))
    return by_home


def _home_height_areas(address, mapped):
    # Ordinance 5526 amended the 50 ft area for this site only.
    # https://alexandriava.gov/sites/default/files/2024-05/ordinance5526.pdf
    if address == "1201 E ABINGDON DR":
        return [(shape, height_map_limit("HD4", "65'") if rule == height_map_limit("HD4", "50'")
                 else rule) for shape, rule in mapped]
    return mapped


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
        return float(part["footprint"] * part["share"] * part["STORIES"] * OUTLINE_FLOOR_SHARE)
    return None


def _outbuilding(index: int, part) -> Outbuilding:
    """A garage, shed or other building that isn't a home, with its floor space.

    Floor space is estimated from the outline, as one story unless the
    city's 3D data shows a building tall enough for more. City records for
    outbuildings aren't trusted: many garages about 11 ft tall are recorded
    as two stories, and the few recorded floor space figures are mostly just
    the outline's area, now and then several times it.
    """
    tall = (bool(part["sections"]) and pd.notna(part["height"])
            and part["height"] >= TWO_STORY_OUTBUILDING)
    stories = part["STORIES"] if tall and part["STORIES"] > 1 else 1
    return Outbuilding(
        index=index,
        floor_area=float(part["footprint"] * part["share"] * stories * OUTLINE_FLOOR_SHARE),
        label=("commercial building" if part.get("BUSE") == "Commercial"
               else OUTBUILDING_LABELS.get(part["BTYPE"], "outbuilding")))


def _main_buildings(placed) -> dict:
    """Each lot's main buildings as (shape, is_home) pairs, keyed by lot id.

    Homes, and other buildings big enough to be more than a shed, garage or
    bus shelter. These are the buildings a neighbor's front yard is measured to.
    """
    main = placed[placed["is_home"] | (
        ~placed["BTYPE"].isin(list(loader.ACCESSORY_TYPES))
        & (placed["footprint"] >= loader.MIN_HOME_FOOTPRINT))]
    return {lot_id: list(zip(group.geometry.values, group["is_home"].values))
            for lot_id, group in main.groupby("lot_id")}


def _add_neighbors(facts: LotFacts, lot_id: int, block_faces: BlockFaces,
                   fallback_rules) -> LotFacts:
    """Fill in the neighbors along the street that the lot's front yard rule compares with.

    Looked up only where the lot's rules, or the ordinary zone of its planned
    district, call for them.
    """
    every_rules = [facts.rules] + ([fallback_rules] if fallback_rules is not None else [])
    fronts = facts.lines.fronts
    changes = {}
    if any(rules.contextual_front_yard is not None for rules in every_rules):
        changes["contextual_block_face"] = {
            street: block_faces.contextual(lot_id, street) for street in fronts}
    if any(rules.front_yard_by_block_average for rules in every_rules):
        changes["block_side"] = {
            street: block_faces.block_side(lot_id, street) for street in fronts}
    return replace(facts, **changes) if changes else facts


def _historic_shares(lot_shapes: gpd.GeoSeries, historic) -> pd.Series:
    """Return each lot's share inside the union of the historic district polygons."""
    shares = pd.Series(0.0, index=lot_shapes.index)
    intersecting = lot_shapes.sindex.query(historic, predicate="intersects")
    nearby = lot_shapes.iloc[intersecting]
    shares.iloc[intersecting] = nearby.intersection(historic).area / nearby.area
    return shares.clip(upper=1.0)


def analyze(keep_facts: dict | None = None) -> gpd.GeoDataFrame:
    """Return one row per lot with its status and the reasons it fails.

    Pass a dict as keep_facts to receive the raw inputs of every checked
    lot, keyed by row number, for debugging and drawing.

    status is "illegal" (breaks at least one rule), "ok" (no problem
    found), or "not_checked". A lot not checked says why in "skipped":
    "no_building" (no home building on it in the city's map),
    "not_home_use" (city records don't list it as a home), "no_zone" (no
    zone on the zoning map) or "no_rules" (a zone this project has no rules
    for). Lots in planned districts are judged by what the district's
    approved plan allows. They also carry "ordinary_reasons": how they
    would fare under the ordinary zone that applies without that plan.
    """
    lots = loader.load_lots()
    buildings = loader.load_buildings()
    streets = loader.load_streets()
    historic = loader.load_historic_districts()

    buildings["BSIZE"] = buildings["BSIZE"].fillna(0)
    buildings["STORIES"] = buildings["STORIES"].fillna(0)

    lots = _fold_units_into_their_lots(lots)
    pairs = _match_buildings_to_lots(lots, buildings)
    lots = _merge_lots_under_one_home(lots, pairs)
    parcel_zones = lots["zoning_label"].map(zoning_key)
    mapped_zones = _mapped_zone_labels(lots.geometry, loader.load_zoning())
    lots["zoning_label"] = mapped_zones.fillna(parcel_zones)
    # The city's downloaded zoning layer still shows the previous zone here.
    # Ordinance 5526 applies while the map is awaiting an update (section 1-300(A)(2)).
    amended = (lots["address"].eq("1201 E ABINGDON DR")
               & lots["zoning_label"].eq("OCM(50)"))
    lots.loc[amended, "zoning_label"] = "CRMU/X"
    pairs = _match_buildings_to_lots(lots, buildings)
    placed = _place_buildings(lots, buildings, pairs)

    lot_shapes = lots.geometry.values
    lot_tree = shapely.STRtree(lot_shapes)
    street_shapes = streets.geometry.values
    street_list = [Street(name, line, bool(divided), label if isinstance(label, str) else None)
                   for name, line, divided, label in zip(
                       streets["name"], street_shapes, streets["divided"], streets["label"])]
    street_tree = shapely.STRtree(street_shapes)
    home_parts = placed[placed["is_home"]]
    home_shapes, home_lots = home_parts.geometry.values, home_parts["lot_id"].values
    residential_lots = set(home_lots) | set(lots.index[
        lots["land_use"].isin(list(loader.HOME_TYPE_BY_LAND_USE))])
    home_tree = shapely.STRtree(home_shapes)
    row_sizes = _row_sizes(home_shapes, home_lots)
    townhouse_rows = _townhouse_rows(home_parts, lots)
    parts_by_lot = dict(tuple(placed.groupby("lot_id")))
    lot_points = lots.geometry.representative_point()
    historic_shares = _historic_shares(lots.geometry, historic)
    height_map = _height_map_areas(home_parts.geometry, loader.load_height_districts())
    lot_lon_lat = lot_points.to_crs("EPSG:4326")
    route_1 = _street(streets, "RICHMOND")
    kr_is_east = _king_street_divide(streets)
    stations = station_points()
    places = {
        "route_1": route_1,
        "stations": stations,
        "commonwealth": _street(streets, "COMMONWEALTH"),
        "eisenhower": _street(streets, "EISENHOWER"),
        "first_and_fayette": _street(streets, "FIRST").intersection(
            _street(streets, "FAYETTE")),
    }
    projects = loader.load_development_projects()
    project_tree = shapely.STRtree(projects.geometry.values)
    paving = loader.load_paving()
    paving_shapes, paving_is_parking = paving.geometry.values, paving["is_parking"].values
    paving_tree = shapely.STRtree(paving_shapes)

    # Lots without a home often have no address, which arrives as NaN.
    address_streets = [name if isinstance(name, str) else None
                       for name in lots["address_street"]]
    known_lines = {}

    def lines_for(lot_id):
        """Sort a lot's outline into street fronts and other edges, once per lot."""
        if lot_id not in known_lines:
            shape = lot_shapes[lot_id]
            nearby = lot_tree.query(shape.buffer(3.0), predicate="intersects")
            neighbors = [
                lot_shapes[i] for i in nearby
                # Skip the lot itself and any larger lot drawn on top of it.
                if i != lot_id
                and lot_shapes[i].intersection(shape).area < 0.5 * shape.area
            ]
            neighbor_shape = unary_union(neighbors) if neighbors else None
            # Reaching past the distance a front can be from its street also
            # takes in the far side of a divided road, to find its middle.
            near_streets = street_tree.query(
                shape.buffer(MAX_STREET_DISTANCE + MAX_DIVIDED_GAP), predicate="intersects")
            known_lines[lot_id] = classify(
                shape, neighbor_shape, [street_list[i] for i in near_streets],
                address_streets[lot_id],
            )
        return known_lines[lot_id]

    records, waiting = [], []
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
            "skipped": "no_building",
        }
        records.append(record)
        on_lot = parts_by_lot.get(lot_id)
        if on_lot is None:
            continue
        homes = on_lot[on_lot["is_home"]]
        if homes.empty:
            continue
        record["skipped"] = "not_home_use"
        home_union = unary_union(homes.geometry.values)
        nearby_homes = home_tree.query(home_union, predicate="dwithin",
                                       distance=LONE_HOUSE_GAP)
        alone = not (home_lots[nearby_homes] != lot_id).any()
        home_type = _home_type(lot, homes, row_sizes.get(lot_id, 1), alone)
        if home_type is None:
            continue
        record["skipped"] = "no_rules" if isinstance(lot["zoning_label"], str) else "no_zone"
        years = homes["YEARBLT"][homes["YEARBLT"] > 1600]
        record["home_type"] = HOME_TYPE_NAMES[home_type]
        record["year_built"] = int(years.min()) if len(years) else None

        historic_share = historic_shares.loc[lot_id]
        is_historic = bool(historic_share > 0.5)
        if 0 < historic_share < 1:
            classification = "inside" if is_historic else "outside"
            historic_note = (
                f"A historic district boundary crosses this lot. About {historic_share:.1%} "
                f"of the lot is inside. The map treats the lot as {classification} based "
                "on which side contains more than half of its area. Ties count as outside.")
            record["notes"].append(historic_note)
        label = lot["zoning_label"]
        zone = normalize_zone(label)
        parcel_zone = parcel_zones.loc[lot_id]
        if amended.loc[lot_id]:
            record["notes"].append("The map applies CRMU/X to this lot per Ordinance 5526.")
        elif pd.notna(mapped_zones.loc[lot_id]) and pd.notna(parcel_zone) and label != parcel_zone:
            record["notes"].append(
                f"The parcel record lists {parcel_zone}. "
                f"The map applies {label} from the city's zoning layer.")
        district = fallback_rules = None
        if zone is not None:
            rules = rules_for(zone, is_historic)
            if zone == "KR" and kr_is_east is not None:
                rules = king_street_retail_rules(
                    kr_is_east(lot_points.loc[lot_id]),
                    residential_only=on_lot["BUSE"].eq("Residential").fillna(False).all(),
                    near_station=near_a_station(lot.geometry, stations))
            elif zone == "OCH":
                rules = office_high_rules(near_a_station(lot.geometry, stations))
        else:
            sub_zone, changes = None, {}
            if isinstance(label, str):
                places["lon_lat"] = lot_lon_lat.loc[lot_id]
                sub_zone, changes = _district_fallback(
                    label.strip().upper(), lot, lot_points.loc[lot_id], places)
            planned = (planned_district_rules(label, is_historic, sub_zone, changes)
                       if sub_zone != "outside" else None)
            if planned is None:
                continue
            district, rules, fallback_rules = planned
        record["skipped"] = None

        shape = lot.geometry
        lines = lines_for(lot_id)
        residential_abutters = None
        if rules.residential_rear_stepback:
            adjacent = [lot_shapes[i] for i in lot_tree.query(shape, predicate="touches")
                        if i in residential_lots]
            residential_abutters = unary_union(adjacent) if adjacent else None

        touching = home_tree.query(home_union.buffer(ATTACHED_GAP),
                                   predicate="intersects")
        attached = [home_shapes[i] for i in touching if home_lots[i] != lot_id]

        paved, parking = _paving_on(shape, paving_tree, paving_shapes, paving_is_parking)

        units = len(homes)
        if home_type == "multi":
            recorded_units = (homes["BUNITS"].fillna(0) * homes["share"]).sum()
            units = int(max(lot["condo_units"], round(recorded_units), 1))
        elif home_type == "townhouse":
            units = int(max(lot["condo_units"], len(homes), 1))
        elif home_type == "two_unit":
            units = 2

        facts = LotFacts(
            shape=shape,
            area=_lot_area(lot),
            rules=rules,
            home_type=home_type,
            homes=[
                Home(
                    shape=part.geometry,
                    height_areas=_home_height_areas(lot["address"], height_map.get(index, [])),
                    height=part["height"] if pd.notna(part["height"]) else None,
                    floor_area=_floor_area(part),
                    sections=part["sections"],
                    stories=float(part["STORIES"]) if part["STORIES"] > 0 else None,
                    ground_floor_retail=(bool(part["ground_floor_retail"])
                                         if pd.notna(part["ground_floor_retail"]) else None),
                )
                for index, part in homes.iterrows()
            ],
            lines=lines,
            units=units,
            all_buildings=list(on_lot.geometry.values),
            outbuildings=[_outbuilding(index, part)
                          for index, (_, part) in enumerate(on_lot.iterrows())
                          if not part["is_home"]],
            building_sections=list(on_lot["sections"]),
            attached_neighbors=unary_union(attached) if attached else None,
            residential_abutters=residential_abutters,
            in_historic_district=is_historic,
            year_built=record["year_built"],
            near_eisenhower_avenue=near_eisenhower_avenue(shape, places["eisenhower"]),
            paved=paved,
            parking=parking,
            row=townhouse_rows.get(lot_id),
            street_setbacks=named_street_setbacks(lot_lon_lat.loc[lot_id].x,
                                                  lot_lon_lat.loc[lot_id].y),
        )
        waiting.append((lot_id, lot, record, facts, district, fallback_rules))

    # Front yards in most zones depend on the neighbors' buildings, so every
    # lot's edges are sorted out above before any lot is checked.
    block_faces = BlockFaces(lot_shapes, lines_for, _main_buildings(placed), lot_tree)
    for lot_id, lot, record, facts, district, fallback_rules in waiting:
        facts = _add_neighbors(facts, lot_id, block_faces, fallback_rules)
        label, home_type = lot["zoning_label"], facts.home_type
        findings = check_lot(facts)
        findings.notes.extend(record["notes"])
        if lot["land_use"] == TWIN_LAND_USE and home_type in ("two_unit", "single"):
            findings.notes.append(
                TWO_UNIT_NOTE if home_type == "two_unit" else LONE_HOUSE_NOTE)
        if keep_facts is not None:
            keep_facts[lot_id] = facts
        if district:
            # Second opinion: the same home under the ordinary zone that
            # would apply if the district's approved plan did not exist.
            ordinary = check_lot(replace(facts, rules=fallback_rules))
            ordinary.notes.extend(record["notes"])
            if label.strip().upper() == "CDD#10" and fallback_rules.name == "CRMU-L":
                ordinary.notes.append(
                    "The map estimates where the Slaters Lane and Piggyback Yard "
                    "CRMU-L options apply. In the Piggyback Yard, section 5-602 "
                    "requires a special use permit and caps development at 275 homes "
                    "and 50 ft. These results show the CRMU-L rules before those "
                    "conditions. The map lacks the rezoning plat needed to tell "
                    "which lots are subject to them.")
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
                f"({label.strip()}). City Council approved a plan for the whole "
                "district, which replaces the ordinary zone rules there. "
                f"{district.plan_summary} Lot sizes and ordinary yards there are drawn "
                "lot by lot on the approved site plans, not set by general "
                "rules, so they are not judged."
                + (f" City case file: {project}." if project else "")))
        record.update({
            "zone": label.strip() if district else facts.rules.name,
            "status": "illegal" if findings.reasons else "ok",
            "reasons": [reason.text for reason in findings.reasons],
            "kinds": sorted({reason.kind for reason in findings.reasons}),
            "notes": findings.notes,
            "rule_results": findings.results,
            "lot_area": round(facts.area),
            "homes": facts.units,
            "historic": facts.in_historic_district,
            **{key: (round(value, 2) if isinstance(value, float) else value)
               for key, value in findings.measurements.items()
               if value is not None},
        })

    _add_district_totals(records)
    return gpd.GeoDataFrame(records, geometry=lots.geometry.values, crs=lots.crs)
