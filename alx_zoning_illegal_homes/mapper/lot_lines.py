"""Work out which edges of a lot face a street, and measure the lot.

Zoning rules talk about a lot's front, sides and rear, but the city's parcel
map is only a bag of polygons. This module rebuilds those ideas from shape
alone, in a way that holds up for pie-shaped, flag-shaped and corner lots:

1. Chop the lot outline into short pieces.
2. A piece is "shared" if another lot sits right across it. Otherwise it is
   "open" (it borders a street, alley, park, or a gap in the map).
3. An open piece "faces a street" if a street centerline lies close by,
   roughly straight out from the piece, with nothing in between.
4. Street-facing pieces are grouped by street name. Two streets that meet
   make a corner lot; two that do not make a through lot.
5. Each street the lot faces keeps its centerline, for rules measured from
   the middle of the street. A divided road is drawn as two one-way
   centerlines, one per side, so its middle is taken as halfway between them.

All coordinates are in feet.
"""
from dataclasses import dataclass, field
from functools import cached_property
from typing import NamedTuple

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, nearest_points, unary_union

PIECE_LENGTH = 12.0
# How far outside the lot we look to see whether another lot is there.
PROBE_DISTANCE = 2.5
MAX_STREET_DISTANCE = 110.0
# A piece faces a street only if the street lies within this angle of
# straight out from the piece. Keeps alley-side edges from counting as
# fronting the street the alley opens onto.
MAX_FACING_ANGLE_COS = np.cos(np.radians(50))
# Open edges that carry on from a street front with less of a turn than
# this are part of the same front.
SMOOTH_TURN_COS = np.cos(np.radians(40))
MIN_FRONT_LENGTH = 8.0
CORNER_GAP = 30.0
# On a divided road, centerlines of the same street up to this much farther
# from the lot than the nearest one still belong to the near side.
NEAR_SIDE_SLACK = 10.0
# The two sides of a divided road are taken to be at most this far apart,
# centerline to centerline.
MAX_DIVIDED_GAP = 150.0


class Street(NamedTuple):
    """One stretch of street centerline from the city's street map.

    `divided` marks a road with a median, drawn as one centerline per side.
    `label` is the street's full name for messages ("South Fayette Street"),
    or None to use a tidied `name`.
    """

    name: str
    line: object
    divided: bool = False
    label: str | None = None


@dataclass
class StreetCenterline:
    """The middle of one street a lot faces, for rules measured from it.

    `near` is the street's centerline on the lot's side. On a divided road
    that is only the near side's own centerline, and `far` is the other
    side's; the middle of the road is taken as halfway between the two.
    `far` is None on an ordinary street, and on a divided road whose other
    side couldn't be found.
    """

    name: str
    label: str
    near: object
    far: object = None
    divided: bool = False

    def measure(self, shape) -> tuple[float, LineString] | None:
        """How far a shape is from the middle of the street, and the line to draw for it.

        Returns None on a divided road whose other side couldn't be found
        nearby, where the middle can't be placed.
        """
        on_shape, on_near = nearest_points(shape, self.near)
        distance = on_shape.distance(on_near)
        if self.divided:
            if self.far is None:
                return None
            far = shape.distance(self.far)
            if far - distance > MAX_DIVIDED_GAP:
                return None
            distance = (distance + far) / 2
        start, toward = np.array(on_shape.coords[0]), np.array(on_near.coords[0])
        step = toward - start
        length = np.linalg.norm(step)
        end = start + step / length * distance if length else toward
        return distance, LineString([start, end])


@dataclass
class Piece:
    """One short stretch of a lot's outline."""

    line: LineString
    midpoint: np.ndarray
    outward: np.ndarray
    kind: str = "shared"  # "shared", "open", or "street"
    street: str | None = None

    @property
    def length(self) -> float:
        return self.line.length

    @property
    def direction(self) -> np.ndarray:
        (x0, y0), (x1, y1) = self.line.coords[0], self.line.coords[-1]
        vector = np.array([x1 - x0, y1 - y0])
        return vector / (np.linalg.norm(vector) or 1.0)


@dataclass
class LotLines:
    """A lot's outline, sorted into street fronts and everything else."""

    pieces: list[Piece]
    fronts: dict[str, MultiLineString] = field(default_factory=dict)
    primary_street: str | None = None
    is_corner: bool = False
    is_through: bool = False
    # The middle of each street in `fronts`, by the same names.
    centerlines: dict[str, StreetCenterline] = field(default_factory=dict)

    @cached_property
    def front_line(self):
        """The front lot line: the edge along the lot's main street."""
        return self.fronts.get(self.primary_street)

    @cached_property
    def frontage(self) -> float | None:
        """Length of the front lot line, or None if no street was found."""
        line = self.front_line
        return line.length if line is not None else None

    @cached_property
    def front_is_curved(self) -> bool:
        """True when the front line bends, as on a cul-de-sac."""
        line = self.front_line
        if line is None:
            return False
        merged = linemerge(line)
        longest = max(_lines(merged), key=lambda part: part.length)
        start, end = longest.coords[0], longest.coords[-1]
        chord = np.hypot(end[0] - start[0], end[1] - start[1])
        return chord < 0.985 * longest.length

    @cached_property
    def front_direction(self) -> np.ndarray | None:
        """Unit vector running along the front lot line."""
        pieces = [p for p in self.pieces
                  if p.kind == "street" and p.street == self.primary_street]
        if not pieces:
            return None
        points = np.array([c for p in pieces for c in p.line.coords])
        centered = points - points.mean(axis=0)
        # The first principal axis is the best-fit straight line.
        return np.linalg.svd(centered, full_matrices=False)[2][0]

    @cached_property
    def inward(self) -> np.ndarray | None:
        """Unit vector pointing from the front line into the lot."""
        pieces = [p for p in self.pieces
                  if p.kind == "street" and p.street == self.primary_street]
        if not pieces:
            return None
        weights = np.array([p.length for p in pieces])
        outward = (np.array([p.outward for p in pieces])
                   * weights[:, None]).sum(axis=0)
        return -outward / (np.linalg.norm(outward) or 1.0)


def _lines(geometry) -> list[LineString]:
    """Flatten any line-like geometry into a list of LineStrings."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _lines(part)]
    return []


def largest_polygon(geometry) -> Polygon:
    """Return the biggest polygon of a possibly multi-part shape."""
    if geometry.geom_type == "Polygon":
        return geometry
    return max(geometry.geoms, key=lambda part: part.area)


def cut_outline(lot: Polygon) -> list[Piece]:
    """Chop the outer ring of a lot into short pieces with outward normals."""
    ring = orient(lot.simplify(0.3), 1.0).exterior
    coords = np.asarray(ring.coords)[:, :2]
    pieces = []
    for start, end in zip(coords[:-1], coords[1:]):
        length = float(np.linalg.norm(end - start))
        if length < 0.5:
            continue
        steps = max(1, int(np.ceil(length / PIECE_LENGTH)))
        unit = (end - start) / length
        # For a counter-clockwise ring the outside is on the right.
        outward = np.array([unit[1], -unit[0]])
        for i in range(steps):
            a = start + (end - start) * (i / steps)
            b = start + (end - start) * ((i + 1) / steps)
            pieces.append(Piece(LineString([a, b]), (a + b) / 2, outward))
    return pieces


def _street_for(piece, lot_core, neighbors, streets):
    """Name the street a piece faces, or None if it faces no street.

    streets is a list of (name, line) pairs near the lot.
    """
    best_name, best_distance = None, MAX_STREET_DISTANCE
    for name, line, *_ in streets:
        distance = line.distance(shapely.Point(piece.midpoint))
        if distance >= best_distance:
            continue
        nearest = line.interpolate(line.project(shapely.Point(piece.midpoint)))
        toward = np.array([nearest.x, nearest.y]) - piece.midpoint
        norm = np.linalg.norm(toward)
        if norm < 1e-6 or toward @ piece.outward / norm < MAX_FACING_ANGLE_COS:
            continue
        sight = LineString([piece.midpoint + piece.outward, (nearest.x, nearest.y)])
        if neighbors is not None and sight.intersects(neighbors):
            continue
        if sight.intersects(lot_core):
            continue
        best_name, best_distance = name, distance
    return best_name


def classify(lot, neighbors, streets, address_street=None) -> LotLines:
    """Sort a lot's outline into street fronts and other edges.

    lot: the lot polygon.
    neighbors: one geometry holding every other lot near this one, or None.
    streets: `Street`s near the lot, or plain (name, centerline) pairs.
    address_street: street name from the lot's address, used to choose the
        main front on corner lots.
    """
    streets = [Street(*street) for street in streets]
    lot = largest_polygon(lot)
    pieces = cut_outline(lot)
    if not pieces:
        return LotLines(pieces=[])

    if neighbors is not None and not neighbors.is_empty:
        shapely.prepare(neighbors)
        probes = np.array([p.midpoint + p.outward * PROBE_DISTANCE for p in pieces])
        shared = shapely.contains_xy(neighbors, probes[:, 0], probes[:, 1])
        # Shrink slightly so the sight line may graze a neighbor's corner.
        blockers = neighbors.buffer(-1.0)
        shapely.prepare(blockers)
    else:
        shared = np.zeros(len(pieces), dtype=bool)
        blockers = None

    lot_core = lot.buffer(-1.0)
    for piece, is_shared in zip(pieces, shared):
        if is_shared:
            continue
        piece.kind = "open"
        street = _street_for(piece, lot_core, blockers, streets)
        if street is not None:
            piece.kind, piece.street = "street", street

    _extend_fronts_along_curves(pieces)

    by_street: dict[str, list[Piece]] = {}
    for piece in pieces:
        if piece.kind == "street":
            by_street.setdefault(piece.street, []).append(piece)
    for name, group in list(by_street.items()):
        if sum(p.length for p in group) < MIN_FRONT_LENGTH:
            for piece in group:
                piece.kind, piece.street = "open", None
            del by_street[name]

    result = LotLines(pieces=pieces)
    result.fronts = {
        name: MultiLineString([p.line for p in group])
        for name, group in by_street.items()
    }
    if not result.fronts:
        return result

    result.centerlines = {name: _centerline(name, result.fronts[name], group, streets)
                          for name, group in by_street.items()}
    result.primary_street = _choose_primary(result.fronts, address_street)
    if len(result.fronts) > 1:
        primary = result.fronts[result.primary_street]
        touching = any(
            line.distance(primary) < CORNER_GAP
            for name, line in result.fronts.items()
            if name != result.primary_street
        )
        result.is_corner = touching
        result.is_through = not touching
    return result


def _facing(pieces: list[Piece]):
    """The land straight out from a lot's edge along one street, as far as a street is looked for.

    It reaches far enough to take in the far side of a divided road.
    """
    reach = MAX_STREET_DISTANCE + MAX_DIVIDED_GAP
    return unary_union([
        Polygon([piece.line.coords[0], piece.line.coords[-1],
                 np.array(piece.line.coords[-1]) + piece.outward * reach,
                 np.array(piece.line.coords[0]) + piece.outward * reach])
        for piece in pieces]).buffer(1.0)


def _centerline(name: str, front, pieces: list[Piece],
                streets: list[Street]) -> StreetCenterline:
    """The middle of the named street, as seen from a lot whose edge along it is `front`.

    `pieces` are the lot's edge pieces along the street. Only the stretch
    of centerline straight out from them counts, so a street that bends
    around the far side of a building isn't measured from there, past land
    the lot doesn't face. When no centerline lies straight out (around a
    cul-de-sac, where the centerline stops short), the whole of it counts.

    On a divided road the centerlines closest to the lot are its near side,
    and divided centerlines of the same street a little farther off, but no
    more than `MAX_DIVIDED_GAP` beyond, are its far side.
    """
    same = [street for street in streets if street.name == name]
    facing = _facing(pieces)
    ahead = [street._replace(line=street.line.intersection(facing)) for street in same]
    same = [street for street in ahead if not street.line.is_empty] or same
    same.sort(key=lambda street: street.line.distance(front))
    closest = same[0].line.distance(front)
    label = next((street.label for street in same if street.label), None) or name.title()
    if not any(street.divided for street in same):
        return StreetCenterline(name, label, unary_union([street.line for street in same]))
    near, far = [], []
    for street in same:
        gap = street.line.distance(front) - closest
        if gap <= NEAR_SIDE_SLACK:
            near.append(street.line)
        elif street.divided and gap <= MAX_DIVIDED_GAP:
            far.append(street.line)
    return StreetCenterline(name, label, unary_union(near),
                            unary_union(far) if far else None, divided=True)


def _extend_fronts_along_curves(pieces):
    """Grow each street front along open edges that continue it smoothly.

    Around a cul-de-sac bulb the centerline stops short, so the far part of
    the curve fails the facing test even though it is plainly street front.
    An alley, by contrast, meets the front at a sharp turn and is left alone.
    """
    count = len(pieces)
    changed = True
    while changed:
        changed = False
        for i, piece in enumerate(pieces):
            if piece.kind != "open":
                continue
            for j in ((i - 1) % count, (i + 1) % count):
                other = pieces[j]
                if (other.kind == "street"
                        and piece.direction @ other.direction > SMOOTH_TURN_COS):
                    piece.kind, piece.street = "street", other.street
                    changed = True
                    break


def _choose_primary(fronts, address_street):
    """Pick the main street front: the address street, else the shortest.

    On a corner lot the narrow end is conventionally the front.
    """
    if address_street:
        wanted = address_street.strip().upper()
        for name in fronts:
            if name and name.strip().upper() == wanted:
                return name
    return min(fronts, key=lambda name: fronts[name].length)


def lot_width_line(lot, lines: LotLines, distance_back: float) -> LineString | None:
    """The straight line the ordinance measures lot width along.

    The ordinance measures width along a straight line between the side lot
    lines, at the depth of the zone's minimum front yard. We trace every
    point in the lot that is exactly that far from the front line, then take
    the straight line between the two ends of that trace. For a plain
    rectangle this spans its width; for a pie-shaped lot it is the chord
    across the wedge at that depth.

    Returns None when the lot has no street front, when the distance is not
    above zero, or when the lot is shallower than the measuring depth.
    """
    front = lines.front_line
    if front is None or distance_back <= 0:
        return None
    lot = largest_polygon(lot)
    trace = front.buffer(distance_back, quad_segs=16).boundary.intersection(lot)
    parts = _lines(trace)
    if not parts:
        return None
    if len(parts) > 1:
        parts = _lines(linemerge(unary_union(parts)))
    longest = max(parts, key=lambda part: part.length)
    return LineString([longest.coords[0], longest.coords[-1]])


def lot_width(lot, lines: LotLines, distance_back: float) -> float | None:
    """Measure lot width a set distance back from the front lot line.

    Returns the street frontage when the distance is zero, and None when the
    lot has no street front or is shallower than the measuring depth.
    """
    if lines.front_line is None:
        return None
    if distance_back <= 0:
        return lines.frontage
    line = lot_width_line(lot, lines, distance_back)
    return float(line.length) if line is not None else None
