"""Compare one lot and its homes against the zone's rules.

Every check returns plain-language reasons. Map data is never exact (lot
lines and building outlines come from different surveys, and outlines are
traced from roofs, eaves included), so each check leaves a margin and only
reports a problem when the home misses the rule by more than that margin.
"""
from dataclasses import dataclass, field

import numpy as np
from shapely.ops import unary_union

from .lot_lines import LotLines, largest_polygon, lot_width
from .rules import HOME_TYPE_NAMES, ZoneRules

# Slack given to distance measurements, in feet.
DISTANCE_MARGIN = 2.0
AREA_MARGIN = 0.03
WIDTH_MARGIN = 0.05
FLOOR_AREA_MARGIN = 0.10
HEIGHT_MARGIN = 5.0
COVERAGE_MARGIN = 0.03
# The 3D layer measures to the top of a roof. The ordinance measures a
# pitched roof to halfway up the slope, so we shave the height before
# using it to size a yard.
HEIGHT_DISCOUNT = 0.85
# Half of a typical alley, which the ordinance credits toward a rear yard.
ALLEY_CREDIT = 5.0
# Lot lines closer than this to both a home and its neighbor's home are
# treated as a shared wall, where no yard is expected.
SHARED_WALL_GAP = 3.0
# A free-standing home drawn closer than this to a lot line is treated as
# a mapping error, not a real zero-foot yard.
TOUCHING_GAP = 0.5
# A building with more than this share of its outline outside the lot is
# probably one outline drawn across several lots; its yards can't be judged.
MAX_SHARE_OUTSIDE_LOT = 0.12


@dataclass
class Home:
    """A residential building on the lot being checked."""

    shape: object
    height: float | None = None
    floor_area: float | None = None
    year_built: int | None = None


@dataclass
class LotFacts:
    """Everything known about a lot before checking it."""

    shape: object
    area: float
    rules: ZoneRules
    home_type: str
    homes: list[Home]
    lines: LotLines
    units: int = 1
    # Outlines of every building on the lot, sheds included.
    all_buildings: list = field(default_factory=list)
    # Homes on other lots that touch this lot's homes.
    attached_neighbors: object = None
    in_historic_district: bool = False


@dataclass
class Reason:
    """One way a home breaks today's rules."""

    kind: str
    text: str


@dataclass
class Findings:
    """The outcome of checking a lot."""

    reasons: list[Reason] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)


def _feet(value: float) -> str:
    return f"{value:,.0f} ft" if value >= 20 else f"{value:,.1f} ft"


def _square_feet(value: float) -> str:
    return f"{value:,.0f} sq ft"


def check_lot(facts: LotFacts) -> Findings:
    """Run every check on a lot and collect the reasons it fails."""
    findings = Findings()
    position = _position(facts)
    findings.measurements["position"] = position
    _check_home_type(facts, findings)
    _check_lot_area(facts, findings, position)
    width = _check_width_and_frontage(facts, findings, position)
    _check_yards(facts, findings, width)
    _check_floor_area(facts, findings)
    _check_height(facts, findings)
    _check_open_space(facts, findings)
    return findings


def _side_of(facts: LotFacts, point, home) -> int:
    """Say whether a point is left (-1) or right (+1) of a home.

    "Left" and "right" run along the front lot line.
    """
    along = facts.lines.front_direction
    center = np.array(home.shape.centroid.coords[0])
    return 1 if (np.asarray(point) - center) @ along >= 0 else -1


def _attached_sides(facts: LotFacts) -> set[int]:
    """Which sides of the lot's homes share a wall with a neighbor."""
    if facts.attached_neighbors is None or facts.lines.front_direction is None:
        return set()
    sides = set()
    for home in facts.homes:
        for piece in facts.lines.pieces:
            if piece.kind == "street":
                continue
            if (piece.line.distance(home.shape) < SHARED_WALL_GAP
                    and piece.line.distance(facts.attached_neighbors)
                    < SHARED_WALL_GAP):
                sides.add(_side_of(facts, piece.midpoint, home))
    return sides


def _position(facts: LotFacts) -> str:
    """Classify the lot as corner, end-of-row, or interior."""
    if facts.lines.is_corner:
        return "corner"
    if facts.home_type == "townhouse" and len(_attached_sides(facts)) == 1:
        return "end"
    return "interior"


def _check_home_type(facts, findings):
    rules, kind = facts.rules, facts.home_type
    name = HOME_TYPE_NAMES[kind]
    if kind not in rules.allowed:
        findings.reasons.append(Reason(
            "home_type",
            f"This kind of home ({name}) is not allowed in the "
            f"{rules.label}.",
        ))
    elif (kind == "multi" and rules.max_multi_units
          and facts.units > rules.max_multi_units):
        findings.reasons.append(Reason(
            "home_type",
            f"Has {facts.units} homes in one building; the {rules.label} allows at most {rules.max_multi_units}.",
        ))


def _check_lot_area(facts, findings, position):
    rules, kind = facts.rules, facts.home_type
    table = rules.corner_lot_area if position == "corner" else rules.lot_area
    required = table.get(kind, rules.lot_area.get(kind))
    if not required:
        return
    per_home = kind == "townhouse" and facts.units > 1
    area = facts.area / facts.units if per_home else facts.area
    if area < required * (1 - AREA_MARGIN):
        what = "Land per home" if per_home else "Lot"
        corner = " on a corner" if (position == "corner"
                                    and required != rules.lot_area.get(kind)) else ""
        findings.reasons.append(Reason(
            "lot_size",
            f"{what} is too small: {_square_feet(area)}, but the "
            f"{rules.label} requires {_square_feet(required)}{corner}.",
        ))


def _check_width_and_frontage(facts, findings, position):
    """Check lot width and street frontage. Returns the measured width."""
    rules, kind, lines = facts.rules, facts.home_type, facts.lines
    if lines.frontage is None:
        findings.notes.append(
            "Could not find a public street next to this lot, so its width "
            "and street frontage were not checked."
        )
        return None
    width = lot_width(facts.shape, lines, rules.width_measured_at)
    findings.measurements["frontage"] = lines.frontage
    findings.measurements["width"] = width
    # Several homes on one shared lot have no lot lines of their own.
    if kind == "townhouse" and facts.units > 1:
        return width

    if position == "corner":
        need_width = rules.corner_lot_width.get(kind, rules.lot_width.get(kind))
    elif position == "end":
        need_width = rules.end_lot_width.get(kind, rules.lot_width.get(kind))
    else:
        need_width = rules.lot_width.get(kind)
    where = {"corner": " for a corner lot", "end": " for an end-of-row lot"}.get(
        position, "")

    if need_width and width is not None and width < need_width * (1 - WIDTH_MARGIN):
        findings.reasons.append(Reason(
            "lot_width",
            f"Lot is too narrow: about {_feet(width)} wide, but the "
            f"{rules.label} requires {_feet(need_width)}{where}.",
        ))

    need_frontage = need_width if kind == "townhouse" else rules.frontage.get(kind)
    if lines.front_is_curved and kind in rules.curved_frontage:
        need_frontage = rules.curved_frontage[kind]
    if need_frontage and lines.frontage < need_frontage * (1 - WIDTH_MARGIN):
        findings.reasons.append(Reason(
            "lot_width",
            f"Too little street frontage: about {_feet(lines.frontage)}, "
            f"but the {rules.label} requires {_feet(need_frontage)}"
            f"{where if kind == 'townhouse' else ''}.",
        ))
    return width


def _yard_gaps(facts, home):
    """Measure a home's gap to each side, the rear, and the street.

    Returns a dict with keys -1 and +1 (the two sides), "rear" and "front".
    Each value is (gap in feet, borders an alley or other open land), or
    missing when the lot has no such edge. Sides with a shared wall are
    left out.
    """
    lines = facts.lines
    along, inward = lines.front_direction, lines.inward
    center = np.array(home.shape.centroid.coords[0])
    front_anchor = np.array(lines.front_line.centroid.coords[0])
    home_depth = (center - front_anchor) @ inward
    outline = np.asarray(largest_polygon(home.shape).exterior.coords)[:, :2]
    deepest = ((outline - front_anchor) @ inward).max()
    # A lot line only counts as the rear if it lies toward the back of the
    # home. This keeps a small jog in a side line from passing as a rear.
    rear_starts = home_depth + 0.6 * (deepest - home_depth)
    has_rear = not (lines.is_corner or lines.is_through)

    gaps, shared_wall = {}, set()
    for piece in lines.pieces:
        gap = piece.line.distance(home.shape)
        if piece.kind == "street":
            key = "front"
        else:
            runs_along_front = abs(piece.direction @ along) > np.cos(np.radians(45))
            behind_home = (piece.midpoint - front_anchor) @ inward > rear_starts
            on_shared_wall = (
                facts.attached_neighbors is not None
                and gap < SHARED_WALL_GAP
                and piece.line.distance(facts.attached_neighbors) < SHARED_WALL_GAP
            )
            if has_rear and runs_along_front and behind_home:
                if on_shared_wall:
                    continue
                key = "rear"
            else:
                key = _side_of(facts, piece.midpoint, home)
                if on_shared_wall:
                    shared_wall.add(key)
        if key not in gaps or gap < gaps[key][0]:
            gaps[key] = (gap, piece.kind == "open")
    for key in shared_wall:
        gaps.pop(key, None)
    return gaps


def _check_yards(facts, findings, width):
    rules, kind, lines = facts.rules, facts.home_type, facts.lines
    lot = largest_polygon(facts.shape)
    homes = []
    for home in facts.homes:
        outside = home.shape.difference(lot.buffer(DISTANCE_MARGIN)).area
        if outside > MAX_SHARE_OUTSIDE_LOT * home.shape.area:
            findings.notes.append(
                "A building outline on this lot crosses the lot line in the "
                "city's map, so its yards were not checked."
            )
        else:
            homes.append(home)
    if not homes:
        return

    if lines.front_line is None:
        _check_yards_without_front(facts, findings, homes)
        return

    worst = {}  # yard name -> (shortfall, text)

    def record(name, shortfall, text):
        if name not in worst or shortfall > worst[name][0]:
            worst[name] = (shortfall, text)

    for home in homes:
        gaps = _yard_gaps(facts, home)
        height = (home.height or 0) * HEIGHT_DISCOUNT
        # Where side yards are simply counted (RM, historic RB), a wall on
        # the line is normal, so only the rear is screened there.
        screened = ("rear",) if rules.side_yards_by_lot_width else (-1, 1, "rear")
        touching = [key for key in screened
                    if key in gaps and gaps[key][0] < TOUCHING_GAP]
        for key in touching:
            del gaps[key]
        if touching:
            findings.notes.append(
                "The city's map shows this home touching a lot line with "
                "no neighbor attached. That is more likely a mapping "
                "error than a real wall on the line, so that yard was "
                "not checked."
            )

        if rules.front_yard and "front" in gaps:
            gap = gaps["front"][0]
            if gap + DISTANCE_MARGIN < rules.front_yard:
                record("front", rules.front_yard - gap,
                       f"Too close to the street: front yard is about "
                       f"{_feet(gap)}, but {_feet(rules.front_yard)} is required.")

        side_gaps = [gaps[side] for side in (-1, 1) if side in gaps]
        if rules.side_yards_by_lot_width:
            measure = width if width is not None else lines.frontage
            if measure is not None and not lines.is_corner:
                needed = 2 if measure >= 35 else 1 if measure >= 25 else 0
                # A shared wall is a side with no yard at all.
                have = sum(gap + DISTANCE_MARGIN >= 5 for gap, _ in side_gaps)
                if have < needed:
                    record("side", needed - have,
                           f"A lot this wide ({_feet(measure)}) needs "
                           f"{'two side yards' if needed == 2 else 'a side yard'} "
                           f"of at least 5 ft; this home has {have}.")
        elif kind in rules.side_yard and not (
                width is not None and width < rules.no_side_yard_below_width):
            yard = rules.side_yard[kind]
            for gap, _ in side_gaps:
                _judge_yard(record, "side", "Side", gap, gap, yard, height)

        rear_yard = rules.rear_yard_for(kind)
        if rear_yard and "rear" in gaps:
            gap, on_alley = gaps["rear"]
            credited = gap + (ALLEY_CREDIT if on_alley else 0)
            _judge_yard(record, "rear", "Rear", gap, credited, rear_yard, height)

    for _, text in worst.values():
        findings.reasons.append(Reason("yards", text))


def _judge_yard(record, name, label, gap, credited_gap, yard, height):
    """Record a yard that is too small, saying which rule it misses.

    The fixed minimum is a firm finding. The taller-building rule leans on
    an estimated height, so its wording says so.
    """
    if gap + DISTANCE_MARGIN < yard.minimum:
        record(name, yard.minimum - gap + 1000,
               f"{label} yard is too small: about {_feet(gap)}, but at least "
               f"{_feet(yard.minimum)} is required.")
        return
    required = yard.required(height)
    if credited_gap + DISTANCE_MARGIN < required:
        record(name, required - credited_gap,
               f"{label} yard is too small for the building's height: about "
               f"{_feet(gap)}, but a building this tall (roughly "
               f"{_feet(height)}) needs about {_feet(required)}.")


def _check_yards_without_front(facts, findings, homes):
    """Fallback when no street front is known: test only the fixed minimum.

    Without a front we cannot tell side from rear, so we use the smaller of
    the two fixed minimums and skip homes that share a wall.
    """
    rules, kind = facts.rules, facts.home_type
    if facts.attached_neighbors is not None or rules.side_yards_by_lot_width:
        return
    minimums = [yard.minimum for yard in
                (rules.side_yard.get(kind), rules.rear_yard_for(kind)) if yard]
    if not minimums:
        return
    needed = min(minimums)
    gap = min(piece.line.distance(home.shape)
              for home in homes for piece in facts.lines.pieces)
    if gap < TOUCHING_GAP:
        # Drawn on the line with no neighbor attached: a mapping error.
        return
    if gap + DISTANCE_MARGIN < needed:
        findings.reasons.append(Reason(
            "yards",
            f"Too close to the lot line: about {_feet(gap)}, but at least "
            f"{_feet(needed)} is required.",
        ))


def _check_floor_area(facts, findings):
    limit = facts.rules.floor_area_ratio_for(
        facts.home_type, facts.in_historic_district)
    if not limit or any(home.floor_area is None for home in facts.homes):
        return
    floor_area = sum(home.floor_area for home in facts.homes)
    ratio = floor_area / facts.area
    findings.measurements["floor_area_ratio"] = ratio
    if ratio > limit * (1 + FLOOR_AREA_MARGIN):
        findings.reasons.append(Reason(
            "floor_area",
            f"Too much building for the lot: about {_square_feet(floor_area)} "
            f"of floor space on a {_square_feet(facts.area)} lot. The "
            f"{facts.rules.label} allows floor space up to "
            f"{limit:.0%} of the lot ({_square_feet(limit * facts.area)}).",
        ))


def _check_height(facts, findings):
    limit = facts.rules.max_height.get(facts.home_type)
    heights = [home.height for home in facts.homes if home.height]
    if not limit or not heights:
        return
    height = max(heights)
    findings.measurements["height"] = height
    if height > limit + HEIGHT_MARGIN:
        findings.reasons.append(Reason(
            "height",
            f"Too tall: about {_feet(height)}, but the {facts.rules.label} allows {_feet(limit)}.",
        ))


def _check_open_space(facts, findings):
    rules = facts.rules
    if not facts.all_buildings or not (rules.min_open_space or rules.max_coverage):
        return
    if (rules.open_space_applies_to
            and facts.home_type not in rules.open_space_applies_to):
        return
    covered = unary_union(facts.all_buildings).intersection(facts.shape).area
    share = covered / facts.shape.area
    findings.measurements["coverage"] = share
    if rules.max_coverage and share > rules.max_coverage + COVERAGE_MARGIN:
        findings.reasons.append(Reason(
            "open_space",
            f"Buildings cover too much of the lot: about {share:.0%}, but "
            f"the {rules.label} allows {rules.max_coverage:.0%}.",
        ))
    elif rules.min_open_space and 1 - share < rules.min_open_space - COVERAGE_MARGIN:
        findings.reasons.append(Reason(
            "open_space",
            f"Not enough open space: buildings alone cover about {share:.0%} "
            f"of the lot, but {rules.min_open_space:.0%} must be left open.",
        ))
