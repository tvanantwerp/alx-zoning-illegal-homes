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
from itertools import combinations
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
# Where a corner lot's front lot line turns onto the other street, pieces
# turning more than this from the street's main direction are the corner.
CORNER_TURN_DEGREES = 30.0
# On a divided road, centerlines of the same street up to this much farther
# from the lot than the nearest one still belong to the near side.
NEAR_SIDE_SLACK = 10.0
# The two sides of a divided road are taken to be at most this far apart,
# centerline to centerline.
MAX_DIVIDED_GAP = 150.0
# Two pieces of one side of a divided road are joined end to end only where
# the road bends less than this many degrees from one piece to the next.
MAX_CARRIAGEWAY_BEND = 60.0
# For the limit on townhouses in one building, homes join a row only where
# their outlines run together, this close, for at least MIN_SHARED_WALL feet:
# a shared wall, not two rows whose corners meet across an alley.
WALL_GAP = 0.5
MIN_SHARED_WALL = 4.0


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
    # The middle of each street in `fronts`, by the same names.
    centerlines: dict[str, StreetCenterline] = field(default_factory=dict)

    @cached_property
    def _front_pair_gaps(self) -> tuple[float, ...]:
        return tuple(first.distance(second)
                     for first, second in combinations(self.fronts.values(), 2))

    @property
    def is_corner(self) -> bool:
        """A lot fronting on two or more streets at their intersection (section 2-167)."""
        return any(gap < CORNER_GAP for gap in self._front_pair_gaps)

    @property
    def is_through(self) -> bool:
        """A lot extending through a block from one street to another (section 2-171)."""
        return any(gap >= CORNER_GAP for gap in self._front_pair_gaps)

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
    def front_is_curved_with_radial_sides(self) -> bool:
        """Whether a curved street frontage has radial lot lines at both ends."""
        if self.primary_street is None:
            return False
        front = front_for_yard(self, self.primary_street)
        longest = max(_lines(linemerge(front)), key=lambda part: part.length)
        coords = np.asarray(longest.simplify(0.3).coords)
        chord = np.linalg.norm(coords[-1] - coords[0])
        if len(coords) < 4 or chord >= 0.985 * longest.length:
            return False
        edges = np.diff(coords, axis=0)
        tangents = edges / np.linalg.norm(edges, axis=1)[:, None]
        angles = np.unwrap(np.arctan2(tangents[:, 1], tangents[:, 0]))
        turns = np.diff(angles)
        if not (np.all(turns > 0) or np.all(turns < 0)):
            return False
        if np.max(np.abs(turns)) > np.radians(40):
            return False

        sides = []
        for endpoint, tangent in ((coords[0], tangents[0]), (coords[-1], tangents[-1])):
            side = next((piece for piece in self.pieces
                         if piece.street != self.primary_street
                         and tuple(endpoint) in (piece.line.coords[0], piece.line.coords[-1])),
                        None)
            if side is None or abs(side.direction @ tangent) > np.sin(np.radians(20)):
                return False
            sides.append(side.direction)
        # Sides should fan out like radii, rather than run parallel through
        # a lot whose frontage happens to be curved.
        return abs(sides[0] @ sides[1]) < np.cos(np.radians(10))

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


def _wall_segments(shape):
    for polygon in shapely.get_parts(shape.simplify(0.1)):
        coords = np.asarray(polygon.exterior.coords)[:, :2]
        for start, end in zip(coords, coords[1:]):
            length = np.linalg.norm(end - start)
            if length >= MIN_SHARED_WALL:
                yield (end - start) / length, shapely.LineString([start, end])


def parallel_shared_walls(a, b):
    """The parts of b's outer walls that run alongside the walls of a."""
    other = list(_wall_segments(b))
    for direction, wall in _wall_segments(a):
        band = wall.buffer(WALL_GAP, cap_style="flat")
        for facing, segment in other:
            if abs(direction @ facing) < 0.97:
                continue
            overlap = segment.intersection(band)
            if overlap.length >= MIN_SHARED_WALL:
                yield overlap


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
            # Keep the ring's original endpoint so adjacent pieces join exactly.
            b = end if i + 1 == steps else start + (end - start) * ((i + 1) / steps)
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
    return result


def street_pieces(lines: LotLines, street: str) -> list[Piece]:
    """The pieces of a lot's outline along one street."""
    return [piece for piece in lines.pieces if piece.kind == "street" and piece.street == street]


def front_for_yard(lines: LotLines, street: str):
    """The front lot line along one street, without the bend where it turns onto another.

    On a corner lot the lot line usually rounds or cuts across the corner.
    The shortest line from a home to that bit runs diagonally, so it comes out
    shallower than the yard straight out to either street. Pieces near
    another street's front that turn more than `CORNER_TURN_DEGREES` away
    from this street's main direction are left out. A lot with only one
    street front keeps it whole, curves and all.
    """
    others = [front for name, front in lines.fronts.items() if name != street]
    if not others:
        return lines.fronts[street]
    pieces = street_pieces(lines, street)
    near_corner = [min(piece.line.distance(other) for other in others) <= CORNER_GAP
                   for piece in pieces]
    # The street's direction comes from the pieces away from the corner,
    # so a long rounded corner doesn't tilt it.
    steady = [piece for piece, near in zip(pieces, near_corner) if not near] or pieces
    points = np.array([c for piece in steady for c in piece.line.coords])
    main = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)[2][0]
    keep = [piece.line for piece, near in zip(pieces, near_corner)
            if not near or abs(piece.direction @ main) >= np.cos(np.radians(CORNER_TURN_DEGREES))]
    return MultiLineString(keep) if keep else lines.fronts[street]


def facing_band(pieces: list[Piece], reach: float):
    """The land straight out from these pieces of a lot's edge, `reach` feet deep."""
    return unary_union([
        Polygon([piece.line.coords[0], piece.line.coords[-1],
                 np.array(piece.line.coords[-1]) + piece.outward * reach,
                 np.array(piece.line.coords[0]) + piece.outward * reach])
        for piece in pieces]).buffer(1.0)


def _join_carriageway_pieces(same: list[Street]) -> list[Street]:
    """Join each side of a divided road back together where the street map splits it.

    `same` holds every centerline piece of one street. Without this, a piece
    of the near side that bends away from the lot can be taken for the far
    side. Two divided pieces join where they meet end to end, no other piece
    of the street meets them there, and the road runs on rather than turning
    back. That keeps the two sides apart where they meet at either end of
    the median.
    """
    pieces = [(street, part) for street in same if street.divided
              for part in shapely.get_parts(street.line)]
    if len(pieces) < 2:
        return same

    def node(coord):
        return round(coord[0], 1), round(coord[1], 1)

    meetings = {}
    for street in same:
        for part in shapely.get_parts(street.line):
            for coord in (part.coords[0], part.coords[-1]):
                meetings[node(coord)] = meetings.get(node(coord), 0) + 1
    ends = {}
    for i, (_, part) in enumerate(pieces):
        for at_start in (True, False):
            ends.setdefault(node(part.coords[0 if at_start else -1]), []).append((i, at_start))

    def heading_in(i, at_start):
        coords = np.asarray(pieces[i][1].coords)[:, :2]
        step = coords[0] - coords[1] if at_start else coords[-1] - coords[-2]
        length = np.linalg.norm(step)
        return step / length if length else None

    group = list(range(len(pieces)))

    def find(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    min_cos = np.cos(np.radians(MAX_CARRIAGEWAY_BEND))
    for key, found in ends.items():
        if len(found) != 2 or meetings[key] != 2 or found[0][0] == found[1][0]:
            continue
        into, out = heading_in(*found[0]), heading_in(*found[1])
        # Arriving along one piece and leaving along the other: `out` points
        # back into the node, so going straight on gives -1.
        if into is not None and out is not None and -(into @ out) > min_cos:
            group[find(found[0][0])] = find(found[1][0])

    joined = {}
    for i, (street, part) in enumerate(pieces):
        joined.setdefault(find(i), (street, []))[1].append(part)
    return [street for street in same if not street.divided] + [
        street._replace(line=linemerge(parts) if len(parts) > 1 else parts[0])
        for street, parts in joined.values()]


def _facing(pieces: list[Piece]):
    """The land straight out from a lot's edge along one street, as far as a street is looked for.

    It reaches far enough to take in the far side of a divided road.
    """
    return facing_band(pieces, MAX_STREET_DISTANCE + MAX_DIVIDED_GAP)


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
    same = _join_carriageway_pieces([street for street in streets if street.name == name])
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
