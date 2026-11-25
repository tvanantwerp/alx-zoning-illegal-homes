"""One JSON file per checked lot, holding everything the pop-up draws."""
import json
import math
import shutil
from dataclasses import fields
from pathlib import Path
from typing import Callable

from geopandas import GeoDataFrame
from shapely import affinity
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from .checks import LotFacts
from .heights import roof_parts
from .rule_results import RuleResult
from .rules import HOME_TYPE_NAMES

SITE_DIR = Path(__file__).resolve().parent.parent.parent / "site"
LOTS_DIR = SITE_DIR / "lots"

# Height used for buildings the city's 3D data gives no height for.
DEFAULT_HEIGHT = 12.0


def lot_frame(facts: LotFacts) -> Callable[[BaseGeometry], BaseGeometry]:
    """Move and turn shapes so the lot's center is at zero and its street is at the bottom.

    A lot with no street is only moved. After turning, the direction into the
    lot points up (+y) and the street sits along -y.
    """
    center = facts.shape.centroid
    inward = facts.lines.inward
    turn = 0.0
    if inward is not None:
        turn = 90 - math.degrees(math.atan2(inward[1], inward[0]))

    def frame(shape: BaseGeometry) -> BaseGeometry:
        if turn:
            shape = affinity.rotate(shape, turn, origin=center)
        return affinity.translate(shape, -center.x, -center.y)

    return frame


def _points(coords) -> list[list[float]]:
    return [[round(x, 1), round(y, 1)] for x, y, *_ in coords]


def polygons(shape: BaseGeometry) -> list:
    """A shape as a list of polygons, each a list of rings (outer ring first, then holes)."""
    parts = shape.geoms if hasattr(shape, "geoms") else [shape]
    result = []
    for part in parts:
        if part.geom_type != "Polygon" or part.is_empty:
            continue
        rings = [part.exterior, *part.interiors]
        result.append([_points(ring.coords)[:-1] for ring in rings])
    return result


def line_points(shape: BaseGeometry) -> list:
    """A single line as a list of points."""
    return _points(shape.coords)


def line_list(shape: BaseGeometry) -> list:
    """Any line shape as a list of lines, each a list of points."""
    if shape.geom_type == "MultiLineString":
        shape = linemerge(shape)
    parts = shape.geoms if shape.geom_type == "MultiLineString" else [shape]
    return [_points(part.coords) for part in parts]


def _shape_data(shape: BaseGeometry):
    """Polygon list or line list for a shape, or None for points and empty shapes."""
    if shape is None or shape.is_empty:
        return None
    if shape.geom_type in ("Polygon", "MultiPolygon"):
        return polygons(shape) or None
    if shape.geom_type in ("LineString", "MultiLineString"):
        return line_list(shape)
    return None


def _number(value):
    if isinstance(value, float):
        value = round(value, 2)
        return int(value) if value.is_integer() else value
    return value


# What the checks note for `apply_permits` about which permits could settle a
# row. The pop-up only needs the outcome, `status` and `permit`.
_PERMIT_WORKINGS = ("permit_tags", "permit_can_allow")


def _row(result: RuleResult, frame) -> dict:
    """One table row, with its shapes in lot coordinates and no empty values."""
    row = {field.name: getattr(result, field.name) for field in fields(result)
           if field.name not in _PERMIT_WORKINGS}
    shapes = {}
    for name, shape in result.shapes.items():
        data = _shape_data(frame(shape))
        if data is not None:
            shapes[name] = data
    row["shapes"] = shapes
    row["buildings"] = [int(i) for i in result.buildings]
    return {key: _number(value) for key, value in row.items() if value is not None}


def _rows(results, frame) -> list[dict]:
    return [_row(result, frame) for result in results]


def _parts(outline: BaseGeometry, sections: list, height: float, frame) -> list[dict]:
    """Pieces of a building outline at their own roof heights, or [] when it has one height."""
    found = roof_parts(outline, sections, height)
    if len(found) < 2:
        return []
    parts = []
    for shape, part_height in found:
        drawn = polygons(frame(shape))
        if drawn:
            parts.append({"outline": drawn, "height": _number(float(part_height))})
    return parts


def _buildings(facts: LotFacts, frame) -> list[dict]:
    buildings = []
    for index, outline in enumerate(facts.all_buildings):
        home = next((h for h in facts.homes if h.shape.equals(outline)), None)
        height = (home.height or (home.stories or 0) * 10 or DEFAULT_HEIGHT
                  if home else DEFAULT_HEIGHT)
        building = {
            "outline": polygons(frame(outline)),
            "height": _number(height),
            "is_home": home is not None,
        }
        if home is not None and home.floor_area:
            building["floor_area"] = _number(float(home.floor_area))
        sections = (facts.building_sections[index]
                    if index < len(facts.building_sections) else [])
        parts = _parts(outline, sections, height, frame)
        if parts:
            building["parts"] = parts
        buildings.append(building)
    return buildings


def lot_drawing(lot_id: int, record: dict, facts: LotFacts) -> dict:
    """Everything the pop-up needs for one lot, as plain JSON-ready data.

    "permits", when the lot has any, is the record's list of city cases
    matched to the lot (see `mapper.permits.lot_permits`).
    """
    frame = lot_frame(facts)
    district = record.get("district")
    district = district if isinstance(district, str) else None
    fallback = record.get("fallback_zone") if district else None
    zone_label = f"{district} planned district" if district else facts.rules.label
    results_label = f"{district} approved plan" if district else f"{facts.rules.label} rules"

    drawing = {
        "id": int(lot_id),
        "address": record.get("address"),
        "zone": record.get("zone"),
        "zone_label": zone_label,
        "home_type": HOME_TYPE_NAMES.get(facts.home_type, facts.home_type),
        "street": facts.lines.primary_street,
        "position": record.get("position"),
        "historic": bool(record.get("historic")),
        "district": district,
        "fallback_zone": fallback,
        "lot": polygons(frame(facts.shape)),
        "edges": [
            {"line": line_points(frame(piece.line)), "kind": piece.kind,
             "street": piece.street}
            for piece in facts.lines.pieces
        ],
        "buildings": _buildings(facts, frame),
        "results": {"label": results_label,
                    "rules": _rows(record["rule_results"], frame)},
        "notes": list(dict.fromkeys(record.get("notes") or [])),
    }
    if district:
        drawing["ordinary"] = {
            "label": f"Ordinary {fallback} zone",
            "rules": _rows(record["ordinary_rule_results"], frame),
        }
        drawing["ordinary_notes"] = list(dict.fromkeys(record.get("ordinary_notes") or []))
    permits = record.get("permits")
    if isinstance(permits, list) and permits:
        drawing["permits"] = permits
    return drawing


def write_lot_files(results: GeoDataFrame, facts: dict[int, LotFacts],
                    folder: Path = LOTS_DIR) -> int:
    """Empty the folder, then write <id>.json for every checked lot. Returns the count."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    count = 0
    checked = results[results["status"].isin(["illegal", "ok"])]
    for lot_id, row in checked.iterrows():
        if lot_id not in facts:
            raise KeyError(f"Lot {int(lot_id)} was checked but its facts were not kept, "
                           "so its drawing file can't be written.")
        drawing = lot_drawing(lot_id, row.to_dict(), facts[lot_id])
        (folder / f"{int(lot_id)}.json").write_text(
            json.dumps(drawing, separators=(",", ":")), encoding="utf-8")
        count += 1
    return count


def replace_lot_files(results: GeoDataFrame, facts: dict[int, LotFacts],
                      folder: Path = LOTS_DIR) -> int:
    """Write every lot file to a temporary folder beside `folder`, then swap it in.

    If writing fails partway, the old folder is left as it was, so the map
    never points at a half-filled one. Returns the count.
    """
    staging = folder.with_name(folder.name + ".tmp")
    count = write_lot_files(results, facts, staging)
    if folder.exists():
        shutil.rmtree(folder)
    staging.rename(folder)
    return count
