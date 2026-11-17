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
from .rule_results import RuleResult

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
    """A line as a list of points. Lines that can't be joined come back as a list of such lists."""
    if shape.geom_type == "MultiLineString":
        shape = linemerge(shape)
    if shape.geom_type == "MultiLineString":
        return [_points(part.coords) for part in shape.geoms]
    return _points(shape.coords)


def _shape_data(shape: BaseGeometry):
    """Polygon list or line list for a shape, or None for points and empty shapes."""
    if shape is None or shape.is_empty:
        return None
    if shape.geom_type in ("Polygon", "MultiPolygon"):
        return polygons(shape) or None
    if shape.geom_type in ("LineString", "MultiLineString"):
        return line_points(shape)
    return None


def _number(value):
    if isinstance(value, float):
        value = round(value, 2)
        return int(value) if value.is_integer() else value
    return value


def _row(result: RuleResult, frame) -> dict:
    """One table row, with its shapes in lot coordinates and no empty values."""
    row = {field.name: getattr(result, field.name) for field in fields(result)}
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


def _buildings(facts: LotFacts, frame) -> list[dict]:
    buildings = []
    for outline in facts.all_buildings:
        home = next((h for h in facts.homes if h.shape.equals(outline)), None)
        building = {
            "outline": polygons(frame(outline)),
            "height": _number(float(home.height)) if home and home.height else DEFAULT_HEIGHT,
            "is_home": home is not None,
        }
        if home is not None and home.floor_area:
            building["floor_area"] = _number(float(home.floor_area))
        buildings.append(building)
    return buildings


def lot_drawing(lot_id: int, record: dict, facts: LotFacts) -> dict:
    """Everything the pop-up needs for one lot, as plain JSON-ready data."""
    frame = lot_frame(facts)
    district = record.get("district")
    district = district if isinstance(district, str) else None
    fallback = record.get("fallback_zone") if district else None
    zone_label = f"{district} planned district" if district else facts.rules.label
    results_label = "Special approval" if district else f"{facts.rules.label} rules"

    drawing = {
        "id": int(lot_id),
        "address": record.get("address"),
        "zone": record.get("zone"),
        "zone_label": zone_label,
        "home_type": facts.home_type,
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
        "notes": list(record.get("notes") or []),
    }
    if district:
        drawing["ordinary"] = {
            "label": f"Ordinary {fallback} zone",
            "rules": _rows(record["ordinary_rule_results"], frame),
        }
        drawing["ordinary_notes"] = list(record.get("ordinary_notes") or [])
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
            continue
        drawing = lot_drawing(lot_id, row.to_dict(), facts[lot_id])
        (folder / f"{int(lot_id)}.json").write_text(
            json.dumps(drawing, separators=(",", ":")), encoding="utf-8")
        count += 1
    return count
