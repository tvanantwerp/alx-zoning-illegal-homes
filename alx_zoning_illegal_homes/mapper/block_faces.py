"""Find the buildings along the same street as a lot, and how far each stands back from it.

Several zones tie a home to its neighbors along the street rather than to a
fixed number. Most set the front yard by the "contextual block face", which
the ordinance defines (section 2-122.1) as "abutting property developed with
buildings that share a common street frontage or frontages with the property
in question." The drawings with that definition show what counts: the lots
on either side that face the same street, the lots straight across the
street from the lot and those two neighbors, and the lot diagonally across
the intersection from a corner lot. A corner lot has a block face for each
street it faces. The RM and CD zones look further, at every building on the
same side of the block.

`BlockFaces` finds both, for any lot and any street it faces, and measures
each neighbor's front setback: the gap between its front lot line on that
street and the closest of its buildings. It is built once per run and keeps
what it works out, since each lot is a neighbor of several others.
"""
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import nearest_points

from .lot_lines import (CORNER_GAP, MAX_STREET_DISTANCE, LotLines, facing_band, front_for_yard,
                        street_pieces)

# Lots this close to each other count as touching, to bridge small gaps
# between lot lines drawn by different surveys.
TOUCHING_GAP = 3.0
# Neighbors beside a lot have their front lot line on the street within this
# distance of the lot's own, so a lot that touches only the back of this one
# isn't taken for a neighbor along the street.
FRONTS_GAP = 10.0
# How far past the street's center to look for lots across the street.
ACROSS_PAST_CENTER = 25.0
# A lot across the street must face this much of the stretch straight out
# from the lot and its neighbors, so one that only grazes a corner is left out.
ACROSS_MIN_OVERLAP = 8.0


def _corner_point(front, side):
    """Approximate the lot's corner where its two street fronts meet."""
    first, second = nearest_points(front, side)
    if first.distance(second) >= CORNER_GAP:
        return None
    return LineString([first, second]).centroid


def _half_street_width(front, center):
    distance = front.distance(center.near)
    return ((distance + front.distance(center.far)) / 2 if center.far is not None
            else distance)


def _across_reach(half_width):
    return min(2 * half_width + ACROSS_PAST_CENTER, 2 * MAX_STREET_DISTANCE)


@dataclass(frozen=True)
class FrontSetback:
    """How far one lot's buildings stand back from one street it faces.

    distance: from the lot's front lot line on that street to the closest
              of its main buildings, in feet. Sheds and garages don't count.
    line:     the shortest line between them, for drawing.
    is_home:  whether that closest building is a home.
    across:   True for a lot across the street, rather than beside.
    """

    lot_id: int
    street: str
    distance: float
    line: LineString
    is_home: bool = True
    across: bool = False


class BlockFaces:
    """Finds the neighbors along each street a lot faces, and their front setbacks.

    lot_shapes: every lot's shape, indexed by lot id.
    lines_for:  returns a lot's `LotLines` by lot id, or None when its edges
                can't be worked out. Called only for lots near the ones asked about.
    buildings:  each lot's main buildings (not sheds or garages) as
                (shape, is_home) pairs, keyed by lot id. Lots with none are
                left out; they count toward a block's length but have no
                setback.
    tree:       a spatial index over `lot_shapes`, if one is already built.
    """

    def __init__(self, lot_shapes, lines_for: Callable[[int], LotLines | None],
                 buildings: dict, tree: shapely.STRtree | None = None):
        self._shapes = np.asarray(lot_shapes, dtype=object)
        self._lines_for = lines_for
        self._buildings = buildings
        self._tree = tree if tree is not None else shapely.STRtree(self._shapes)
        self._setbacks: dict = {}
        self._beside: dict = {}
        self._contextual: dict = {}
        self._block_sides: dict = {}

    def front_setback(self, lot_id: int, street: str) -> FrontSetback | None:
        """How far a lot's closest main building stands back from the named street.

        None when the lot doesn't face that street or has no main building.
        """
        return min(self._building_setbacks(lot_id, street), key=lambda s: s.distance,
                   default=None)

    def _building_setbacks(self, lot_id, street):
        key = (lot_id, street)
        if key in self._setbacks:
            return self._setbacks[key]
        lines = self._lines_for(lot_id)
        buildings = self._buildings.get(lot_id, [])
        setbacks = []
        if lines and street in lines.fronts:
            front = front_for_yard(lines, street)
            for shape, is_home in buildings:
                gap = LineString(nearest_points(shape, front))
                if any(other is not shape and gap.crosses(other) for other, _ in buildings):
                    continue
                setbacks.append(FrontSetback(lot_id, street, gap.length, gap, is_home))
        self._setbacks[key] = setbacks
        return setbacks

    def beside(self, lot_id: int, street: str) -> list[int]:
        """The lots touching this one that face the same street right alongside it.

        Includes lots with no buildings, which still carry a block along.
        """
        key = (lot_id, street)
        if key in self._beside:
            return self._beside[key]
        lines = self._lines_for(lot_id)
        front = lines.fronts.get(street) if lines is not None else None
        found = []
        if front is not None:
            shape = self._shapes[lot_id]
            for other in self._touching(lot_id):
                other_lines = self._lines_for(other)
                other_front = (other_lines.fronts.get(street)
                               if other_lines is not None else None)
                if other_front is not None and other_front.distance(front) <= FRONTS_GAP:
                    found.append(other)
        self._beside[key] = found
        return found

    def _touching(self, lot_id) -> list[int]:
        """Lots within a few feet of this one, leaving out any drawn on top of it."""
        shape = self._shapes[lot_id]
        near = self._tree.query(shape.buffer(TOUCHING_GAP), predicate="intersects")
        near = near[near != lot_id]
        if not len(near):
            return []
        overlap = shapely.area(shapely.intersection(self._shapes[near], shape))
        smaller = np.minimum(shapely.area(self._shapes[near]), shape.area)
        return [int(i) for i in near[overlap < 0.5 * smaller]]

    def across(self, lot_id: int, street: str) -> list[int]:
        """The lots across the named street from this lot and the lots beside it.

        These are the lots facing the same street from its far side whose
        front lot lines lie straight out from the front lot lines of this lot
        and its neighbors along the street.
        """
        lines = self._lines_for(lot_id)
        if lines is None or street not in lines.fronts:
            return []
        beside = self.beside(lot_id, street)
        found = set()
        skip = {lot_id, *beside}
        for source in [lot_id, *beside]:
            source_lines = self._lines_for(source)
            front = source_lines.fronts[street]
            center = source_lines.centerlines[street]
            reach = _across_reach(_half_street_width(front, center))
            band = facing_band(street_pieces(source_lines, street), reach)
            for other in self._tree.query(band, predicate="intersects"):
                other = int(other)
                if other in skip or other in found:
                    continue
                other_lines = self._lines_for(other)
                other_front = other_lines.fronts.get(street) if other_lines else None
                if other_front is None:
                    continue
                facing = other_front.intersection(band)
                if facing.length >= ACROSS_MIN_OVERLAP and LineString(
                        [front.centroid, facing.centroid]).intersects(center.near):
                    found.add(other)
        return sorted(found)

    def diagonally_across(self, lot_id: int, street: str) -> list[int]:
        """The opposite corner at each intersection this front meets (section 2-102)."""
        lines = self._lines_for(lot_id)
        if lines is None or street not in lines.fronts:
            return []
        front = lines.fronts[street]
        found = set()
        for cross_street, side in lines.fronts.items():
            if cross_street == street:
                continue
            corner = _corner_point(front, side)
            if corner is None:
                continue
            opposite = self._opposite_corner(lot_id, lines, street, cross_street, corner)
            if opposite is not None:
                found.add(opposite)
        return sorted(found)

    def _opposite_corner(self, lot_id, lines, street, cross_street, corner):
        names = (street, cross_street)
        outward, widths = [], []
        for name in names:
            pieces = street_pieces(lines, name)
            direction = sum(piece.length * piece.outward for piece in pieces)
            outward.append(direction / (np.linalg.norm(direction) or 1.0))
            widths.append(_half_street_width(lines.fronts[name], lines.centerlines[name]))
        # Search beyond both street centers, a little farther than the
        # expected far edges. Movement is measured across each street so
        # the search follows the intersection even when its angle is skewed.
        if abs(np.linalg.det(outward)) < 0.25:
            return None
        near_a, near_b = widths
        far_a, far_b = map(_across_reach, widths)
        origin = np.asarray(corner.coords[0])
        area = Polygon([origin + np.linalg.solve(outward, offset) for offset in
                        ((near_a, near_b), (far_a, near_b), (far_a, far_b), (near_a, far_b))])
        candidates = []
        for other in self._tree.query(area, predicate="intersects"):
            if other == lot_id:
                continue
            other_lines = self._lines_for(int(other))
            if other_lines is None or not all(
                    name in other_lines.fronts
                    and other_lines.centerlines[name].label == lines.centerlines[name].label
                    for name in names):
                continue
            other_corner = _corner_point(other_lines.fronts[street], other_lines.fronts[cross_street])
            if other_corner is not None and area.covers(other_corner):
                candidates.append((corner.distance(other_corner), int(other)))
        return min(candidates)[1] if candidates else None

    def contextual(self, lot_id: int, street: str) -> list[FrontSetback]:
        """The lot's contextual block face along one street, with each neighbor's setback.

        Abutting property with a main building includes lots beside the
        subject, directly across, and diagonally across an intersection.
        """
        key = (lot_id, street)
        if key not in self._contextual:
            found = [self.front_setback(other, street) for other in self.beside(lot_id, street)]
            across = set(self.across(lot_id, street)) | set(self.diagonally_across(lot_id, street))
            found += [replace(setback, across=True) for setback in
                      (self.front_setback(other, street)
                       for other in sorted(across)) if setback is not None]
            self._contextual[key] = [setback for setback in found if setback is not None]
        return self._contextual[key]

    def block_side(self, lot_id: int, street: str) -> list[FrontSetback]:
        """Every other building on the same side of the block, with its setback from the street.

        The block's side is the run of lots facing the street that touch one
        another in a chain from this lot; it ends at a cross street, where
        the next lot sits across it. An alley or other gap wider than a few
        feet also ends it, since the map can't tell an alley from a street
        there.
        """
        key = (lot_id, street)
        if key not in self._block_sides:
            chain, waiting = {lot_id}, [lot_id]
            while waiting:
                current = waiting.pop()
                neighbors = self.beside(current, street)
                if not neighbors:
                    continue
                # The short street key can join different streets, such
                # as Lee Court and South Lee Street at the same corner.
                current_street = self._lines_for(current).centerlines[street].label
                for other in neighbors:
                    if other not in chain and self._lines_for(other).centerlines[street].label == current_street:
                        chain.add(other)
                        waiting.append(other)
            for member in chain:
                self._block_sides[(member, street)] = chain
        chain = self._block_sides[key]
        return [setback for other in sorted(chain) if other != lot_id
                for setback in self._building_setbacks(other, street)]
