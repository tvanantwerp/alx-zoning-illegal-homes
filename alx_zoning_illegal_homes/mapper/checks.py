"""Compare one lot and its homes against the zone's rules.

Every check returns plain-language reasons. Map data is never exact (lot
lines and building outlines come from different surveys, and outlines are
traced from roofs, eaves included), so each check leaves a margin and only
reports a problem when the home misses the rule by more than that margin.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString
from shapely.ops import nearest_points, unary_union

from .lot_lines import LotLines, largest_polygon, lot_width, lot_width_line
from .rule_results import (
    BENEFIT_OF_DOUBT, CORNER_NO_REAR, CROSSES_LOT_LINE, FAILS, MAPPING_ERROR, NO_FLOOR_AREA, NO_HEIGHT,
    NO_OUTLINES, NO_REAR_FOUND, NO_RULE, NO_SIDE_LINE, NO_STREET, NOT_CHECKED, NOT_REQUIRED, PASSES, RULE_IDS,
    RM_OPEN_SPACE, SHARED_LOT, SHARED_WALL, SIDE_COUNT_ON_CORNER, TOO_SHALLOW, RuleResult,
    explain_margin, format_feet as _feet, front_yard_explanation, frontage_about,
    no_front_yard_explanation, no_rule_explanation, older_rules_explanation,
    side_count_explanation)
from .rules import HOME_TYPE_NAMES, OlderHomeAllowance, ZoneRules

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
# Roof pieces smaller than this, in square feet, are dropped as slivers.
MIN_PART_AREA = 5.0

YARD_ROLES = ("front", "left", "right", "rear")
YARD_NAMES = {"front": "Front yard", "left": "Left side yard",
              "right": "Right side yard", "rear": "Rear yard",
              "nearest": "Closest lot line"}
_STATUS_RANK = {NO_RULE: 0, NOT_REQUIRED: 1, NOT_CHECKED: 2, PASSES: 3, FAILS: 4}


@dataclass
class Home:
    """A residential building on the lot being checked."""

    shape: object
    height: float | None = None
    floor_area: float | None = None
    # Roof sections from the city's 3D data, as (shape, height) pairs.
    sections: list = field(default_factory=list)
    year_built: int | None = None


def roof_parts(outline, sections: list, height: float) -> list[tuple]:
    """Split a building outline into parts by roof height, as (shape, height) pairs.

    Sections are trimmed to the outline and merged when they share a height.
    Any piece of the outline no section covers gets `height`, the building's
    overall height. With no usable sections the whole outline is one part.
    Pieces smaller than MIN_PART_AREA are slivers where the 3D data and the
    outline don't quite line up, and are dropped.
    """
    by_height: dict[float, list] = {}
    for shape, section_height in sections:
        piece = shape.intersection(outline)
        if piece.area >= MIN_PART_AREA:
            by_height.setdefault(round(float(section_height), 1), []).append(piece)
    if not by_height:
        return [(outline, height)]
    uncovered = outline.difference(unary_union([shape for shape, _ in sections]))
    if uncovered.area >= MIN_PART_AREA:
        by_height.setdefault(height, []).append(uncovered)
    return [(unary_union(pieces), part_height)
            for part_height, pieces in sorted(by_height.items())]


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
    # Roof sections from the city's 3D data, one list per entry in
    # all_buildings, each a list of (shape, height) pairs. Used only for
    # drawing; empty or missing when there is no 3D data.
    building_sections: list = field(default_factory=list)
    # Homes on other lots that touch this lot's homes.
    attached_neighbors: object = None
    in_historic_district: bool = False
    # Year the oldest home on the lot was built, from city records.
    year_built: int | None = None


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
    results: list[RuleResult] = field(default_factory=list)


def _square_feet(value: float) -> str:
    return f"{value:,.0f} sq ft"


def check_lot(facts: LotFacts) -> Findings:
    """Run every check on a lot and collect the reasons it fails."""
    findings = Findings()
    position = _position(facts)
    findings.measurements["position"] = position
    allowance = _check_home_type(facts, findings)
    if allowance is not None and allowance.older_rules:
        note = older_rules_explanation(facts.rules.label, allowance.before)
        for rule, name in (("lot_area", "Lot size"), ("frontage", "Street frontage"),
                           ("width", "Lot width"), ("yard:front", "Front yard"),
                           ("yard:left", "Left side yard"), ("yard:right", "Right side yard"),
                           ("yard:rear", "Rear yard"), ("floor_area", "Floor space"),
                           ("height", "Height"), ("open_space", "Open space")):
            findings.results.append(RuleResult(rule, name, NOT_CHECKED, explanation=note))
        findings.results.sort(key=lambda row: RULE_IDS.index(row.rule))
        return findings
    _check_lot_area(facts, findings, position)
    width = _check_width_and_frontage(facts, findings, position)
    _check_yards(facts, findings, width)
    _check_floor_area(facts, findings)
    _check_height(facts, findings)
    _check_open_space(facts, findings)
    explain_margin(findings.results)
    findings.results.sort(key=lambda row: RULE_IDS.index(row.rule))
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


def _older_home_allowance(facts) -> OlderHomeAllowance | None:
    """The zone's exception for older homes of this type, if this lot's homes are old enough."""
    allowance = facts.rules.allowed_if_built_before.get(facts.home_type)
    if (allowance is None or facts.year_built is None
            or facts.year_built >= allowance.before_year):
        return None
    return allowance


def _check_home_type(facts, findings) -> OlderHomeAllowance | None:
    """Check the kind of home against the zone.

    Returns the zone's exception for older homes when that is what lets this
    home pass, so the other rows can say the older limits apply.
    """
    rules, kind = facts.rules, facts.home_type
    name = HOME_TYPE_NAMES[kind]
    status, summary = PASSES, f"{name} allowed in the {rules.label}"
    allowance = None if kind in rules.allowed else _older_home_allowance(facts)
    explanation = None
    if allowance is not None:
        summary = f"older {name} allowed in the {rules.label}"
        explanation = " ".join(filter(None, [
            f"This kind of home ({name}) isn't normally allowed in the {rules.label}.",
            allowance.rule,
            f"The oldest home on this lot was built in {facts.year_built}, so it counts.",
            allowance.unconfirmed,
        ]))
    elif kind not in rules.allowed:
        status, summary = FAILS, f"{name} not allowed in the {rules.label}"
        findings.reasons.append(Reason(
            "home_type",
            f"This kind of home ({name}) is not allowed in the "
            f"{rules.label}.",
        ))
    elif (kind == "multi" and rules.max_multi_units
          and facts.units > rules.max_multi_units):
        status = FAILS
        summary = (f"{facts.units} homes in one building; the {rules.label} "
                   f"allows {rules.max_multi_units}")
        findings.reasons.append(Reason(
            "home_type",
            f"Has {facts.units} homes in one building; the {rules.label} allows at most {rules.max_multi_units}.",
        ))
    findings.results.append(RuleResult(
        "home_type", "Home type", status, summary=summary, explanation=explanation))
    return allowance


def _check_lot_area(facts, findings, position):
    rules, kind = facts.rules, facts.home_type
    table = rules.corner_lot_area if position == "corner" else rules.lot_area
    required = table.get(kind, rules.lot_area.get(kind))
    per_home = kind == "townhouse" and facts.units > 1
    row = RuleResult("lot_area", "Land per home" if per_home else "Lot size",
                     NO_RULE, unit="sq ft")
    findings.results.append(row)
    if not required:
        row.explanation = no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "minimum lot size")
        return
    area = facts.area / facts.units if per_home else facts.area
    row.status, row.measured, row.required = PASSES, area, required
    if area < required * (1 - AREA_MARGIN):
        row.status = FAILS
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
    measured_at = rules.width_measured_at
    if rules.name == "W-1" and kind in {"single", "semi", "two_unit"}:
        measured_at = 20  # Front building line proxy, as in CRMU.
    frontage_row = RuleResult("frontage", "Street frontage", NOT_CHECKED,
                              unit="ft", measured=lines.frontage)
    width_row = RuleResult(
        "width", "Lot width", NOT_CHECKED, unit="ft",
        detail=(f"measured {_feet(measured_at)} back" if measured_at > 0
                else "measured at the street"))
    findings.results += [frontage_row, width_row]
    if position == "corner":
        need_width = rules.corner_lot_width.get(kind, rules.lot_width.get(kind))
    elif position == "end":
        need_width = rules.end_lot_width.get(kind, rules.lot_width.get(kind))
    else:
        need_width = rules.lot_width.get(kind)
    where = {"corner": " for a corner lot", "end": " for an end-of-row lot"}.get(
        position, "")

    if kind == "townhouse" and rules.townhouse_frontage_matches_width:
        need_frontage = need_width
    else:
        need_frontage = rules.frontage.get(kind)
    if lines.front_is_curved and kind in rules.curved_frontage:
        need_frontage = rules.curved_frontage[kind]

    if not need_frontage:
        frontage_row.status = NO_RULE
        frontage_row.explanation = no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "minimum street frontage")
    if lines.frontage is None:
        width_row.explanation = NO_STREET
        if need_frontage:
            frontage_row.explanation = NO_STREET
        findings.notes.append(
            "Could not find a public street next to this lot, so its width "
            "and street frontage were not checked."
        )
        return None
    width = lot_width(facts.shape, lines, measured_at)
    findings.measurements["frontage"] = lines.frontage
    findings.measurements["width"] = width
    frontage_row.shapes["line"] = lines.front_line
    width_line = (lot_width_line(facts.shape, lines, measured_at) if measured_at > 0
                  else lines.front_line)
    if width_line is not None:
        width_row.shapes["line"] = width_line
    # Several homes on one shared lot have no lot lines of their own.
    if kind == "townhouse" and facts.units > 1:
        width_row.explanation = SHARED_LOT
        if need_frontage:
            frontage_row.explanation = SHARED_LOT
        return width

    street = lines.primary_street
    frontage_row.about = frontage_about(street, rules.label, need_frontage, measured_at)
    if need_width:
        width_row.required = need_width
        if width is None:
            width_row.explanation = TOO_SHALLOW
        else:
            width_row.status, width_row.measured = PASSES, width
    else:
        width_row.status = NO_RULE
        width_row.explanation = no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "minimum lot width")
    if need_frontage:
        frontage_row.status, frontage_row.required = PASSES, need_frontage

    if need_width and width is not None and width < need_width * (1 - WIDTH_MARGIN):
        width_row.status = FAILS
        findings.reasons.append(Reason(
            "lot_width",
            f"Lot is too narrow: about {_feet(width)} wide, but the "
            f"{rules.label} requires {_feet(need_width)}{where}.",
        ))

    if need_frontage and lines.frontage < need_frontage * (1 - WIDTH_MARGIN):
        frontage_row.status = FAILS
        findings.reasons.append(Reason(
            "lot_width",
            f"Too little street frontage: about {_feet(lines.frontage)}, "
            f"but the {rules.label} requires {_feet(need_frontage)}"
            f"{where if kind == 'townhouse' else ''}.",
        ))
    return width


@dataclass
class YardGap:
    """How far a home sits from one side of its lot, and where."""

    gap: float
    # True when the closest lot line borders an alley or other open land.
    on_open: bool
    # From the closest point on the home to the closest point on the lot line.
    nearest: LineString
    # Every lot line on this side, and whether each borders open land.
    lines: list[LineString]
    lines_open: list[bool] = field(default_factory=list)
    # Height of the part of the home this gap is measured from, for the
    # setback ratio. Already shaved by HEIGHT_DISCOUNT.
    height: float = 0.0


def _nearest_line(home, line) -> LineString:
    """The shortest line between a home and a lot line."""
    on_home, on_line = nearest_points(home.shape, line)
    return LineString([on_home, on_line])


def _part_gaps(gap: YardGap, parts: list[tuple]) -> list[YardGap]:
    """The same side's gap, measured again from each part of the home.

    The setback ratio pairs each part of a building with its own height
    (section 2-193), so a low rear wing is judged by its own height and a
    taller block behind it by its own distance.
    """
    measured = []
    for shape, height in parts:
        distance, line, is_open = min(
            ((line.distance(shape), line, is_open)
             for line, is_open in zip(gap.lines, gap.lines_open)),
            key=lambda found: found[0])
        on_part, on_line = nearest_points(shape, line)
        measured.append(YardGap(distance, is_open, LineString([on_part, on_line]),
                                gap.lines, gap.lines_open,
                                (height or 0) * HEIGHT_DISCOUNT))
    return measured


def _yard_gaps(facts, home) -> tuple[dict, set]:
    """Measure a home's gap to each side, the rear, and the street.

    Returns a dict with keys -1 and +1 (the two sides), "rear" and "front",
    each a YardGap, or missing when the lot has no such edge. Also returns
    the set of keys that share a wall with a neighbor. Sides with a shared
    wall are left out of the dict; a rear only loses the lines on the wall.
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
                    shared_wall.add("rear")
                    continue
                key = "rear"
            else:
                key = _side_of(facts, piece.midpoint, home)
                if on_shared_wall:
                    shared_wall.add(key)
        if key not in gaps:
            gaps[key] = YardGap(gap, piece.kind == "open",
                                _nearest_line(home, piece.line), [piece.line],
                                [piece.kind == "open"])
            continue
        entry = gaps[key]
        entry.lines.append(piece.line)
        entry.lines_open.append(piece.kind == "open")
        if gap < entry.gap:
            entry.gap, entry.on_open = gap, piece.kind == "open"
            entry.nearest = _nearest_line(home, piece.line)
    for key in shared_wall - {"rear"}:
        gaps.pop(key, None)
    return gaps, shared_wall


def _side_name(facts, key) -> str:
    """Name side -1 or +1 "left" or "right", seen from the street facing the lot."""
    inward = facts.lines.inward
    toward_right = np.array([inward[1], -inward[0]])
    return "right" if key * (facts.lines.front_direction @ toward_right) > 0 else "left"


def _yard_row(facts, role, status, gap=None, required=None, **fields) -> RuleResult:
    """One yard's row, with the gap and the required strip to draw when known.

    The strip is the required depth measured in from that side's lot lines.
    """
    row = RuleResult(f"yard:{role}", YARD_NAMES[role], status, unit="ft",
                     required=required, **fields)
    if gap is not None:
        row.measured = gap.gap
        row.shapes["gap"] = gap.nearest
        if required:
            row.shapes["strip"] = unary_union(
                [line.buffer(required, cap_style="flat") for line in gap.lines]
            ).intersection(facts.shape)
    return row


def _keep_worst(rows: dict, row: RuleResult):
    """Keep whichever row for this yard shows the worst result.

    Status counts first, then how far the home falls short of the rule.
    """
    def badness(r):
        slack = (r.measured - r.required
                 if r.measured is not None and r.required is not None else math.inf)
        return _STATUS_RANK[r.status], -slack
    if row.rule not in rows or badness(row) > badness(rows[row.rule]):
        rows[row.rule] = row


def _check_yards(facts, findings, width):
    rules, lines = facts.rules, facts.lines
    lot = largest_polygon(facts.shape)
    homes, crossing = [], False
    for home in facts.homes:
        outside = home.shape.difference(lot.buffer(DISTANCE_MARGIN)).area
        if outside > MAX_SHARE_OUTSIDE_LOT * home.shape.area:
            crossing = True
            findings.notes.append(
                "A building outline on this lot crosses the lot line in the "
                "city's map, so its yards were not checked."
            )
        else:
            homes.append(home)

    if lines.front_line is None:
        _check_yards_without_front(facts, findings, homes)
        return

    worst = {}  # yard name -> (shortfall, text)

    def record(name, shortfall, text):
        if name not in worst or shortfall > worst[name][0]:
            worst[name] = (shortfall, text)

    rows = {}
    if crossing:
        for role in YARD_ROLES:
            _keep_worst(rows, _yard_row(facts, role, NOT_CHECKED,
                                        explanation=CROSSES_LOT_LINE))

    for home in homes:
        gaps, shared = _yard_gaps(facts, home)
        parts = roof_parts(home.shape, home.sections, home.height or 0)
        # Where side yards are simply counted (RM, historic RB), a wall on
        # the line is normal, so only the rear is screened there.
        screened = ("rear",) if rules.side_yards_by_lot_width else (-1, 1, "rear")
        touching = [key for key in screened
                    if key in gaps and gaps[key].gap < TOUCHING_GAP]
        for key in touching:
            del gaps[key]
        if touching:
            findings.notes.append(
                "The city's map shows this home touching a lot line with "
                "no neighbor attached. That is more likely a mapping "
                "error than a real wall on the line, so that yard was "
                "not checked."
            )

        _keep_worst(rows, _front_row(facts, record, gaps["front"]))
        for row in _side_rows(facts, record, gaps, shared, touching, parts, width):
            _keep_worst(rows, row)
        _keep_worst(rows, _rear_row(facts, record, gaps.get("rear"), shared,
                                    touching, parts))

    findings.results += rows.values()
    for _, text in worst.values():
        findings.reasons.append(Reason("yards", text))


def _front_row(facts, record, gap):
    """Judge the front yard, where the zone sets a fixed one."""
    rules = facts.rules
    if facts.home_type in rules.no_front_yard_for:
        return _yard_row(facts, "front", NOT_REQUIRED, gap,
                         explanation=no_front_yard_explanation(rules))
    if not rules.front_yard:
        return _yard_row(facts, "front", NOT_CHECKED, gap, explanation=(
            front_yard_explanation(rules, facts.in_historic_district)))
    fails = gap.gap + DISTANCE_MARGIN < rules.front_yard
    if fails:
        record("front", rules.front_yard - gap.gap,
               f"Too close to the street: front yard is about "
               f"{_feet(gap.gap)}, but {_feet(rules.front_yard)} is required.")
    return _yard_row(facts, "front", FAILS if fails else PASSES, gap,
                     rules.front_yard, detail="needs")


def _side_rows(facts, record, gaps, shared, touching, parts, width):
    """Judge both side yards. Returns the left and right rows.

    `parts` is the home split by roof height, as (shape, height) pairs.
    """
    rules, lines = facts.rules, facts.lines
    if not rules.side_yards_by_lot_width:
        return [_side_row(facts, record, key, gaps.get(key), shared, touching,
                          parts, width) for key in (-1, 1)]

    measure = width if width is not None else lines.frontage
    needed = 2 if measure >= 35 else 1 if measure >= 25 else 0
    # A shared wall is a side with no yard at all.
    have = sum(gaps[key].gap + DISTANCE_MARGIN >= 5 for key in (-1, 1) if key in gaps)
    short = not lines.is_corner and have < needed
    if short:
        record("side", needed - have,
               f"A lot this wide ({_feet(measure)}) needs "
               f"{'two side yards' if needed == 2 else 'a side yard'} "
               f"of at least 5 ft; this home has {have}.")
    return [_counted_side_row(facts, key, gaps.get(key), shared, measure, needed, short)
            for key in (-1, 1)]


def _counted_side_row(facts, key, gap, shared, measure, needed, short):
    """A side yard row where the zone counts side yards by lot width.

    When the home has too few yards, every side without one fails, so the
    rows always agree with the reason written for the lot.
    """
    role = _side_name(facts, key)
    if facts.lines.is_corner:
        return _yard_row(facts, role, NOT_CHECKED, gap, explanation=SIDE_COUNT_ON_CORNER)
    text = side_count_explanation(facts.rules.label, measure, needed)
    if needed == 0:
        return _yard_row(facts, role, NOT_REQUIRED, gap, explanation=text)
    has_yard = gap is not None and gap.gap + DISTANCE_MARGIN >= 5
    if short and not has_yard:
        return _yard_row(facts, role, FAILS, gap, 5, detail="needs", explanation=text)
    if key in shared:
        return _yard_row(facts, role, NOT_REQUIRED, explanation=SHARED_WALL)
    if gap is None:
        return _yard_row(facts, role, NOT_CHECKED, explanation=NO_SIDE_LINE)
    return _yard_row(facts, role, PASSES, gap, 5, detail="needs", explanation=text)


def _side_row(facts, record, key, gap, shared, touching, parts, width):
    """A side yard row where the zone sets a side yard depth."""
    rules, kind = facts.rules, facts.home_type
    role = _side_name(facts, key)
    if rules.name in {"CRMU-L", "CRMU-M", "CRMU-H"} and kind == "townhouse":
        explanation = "Only interior end lots wider than 25 ft require a townhouse side yard."
        if _position(facts) != "end" or (width is not None and width <= 25):
            return _yard_row(facts, role, NOT_REQUIRED, gap, explanation=explanation)
        if width is None:
            return _yard_row(facts, role, NOT_CHECKED, gap, explanation=explanation)
    if key in touching:
        return _yard_row(facts, role, NOT_CHECKED, explanation=MAPPING_ERROR)
    if key in shared:
        return _yard_row(facts, role, NOT_REQUIRED, explanation=SHARED_WALL)
    if width is not None and width < rules.no_side_yard_below_width:
        return _yard_row(facts, role, NOT_REQUIRED, gap, explanation=(
            f"Lots narrower than {_feet(rules.no_side_yard_below_width)} need "
            f"no side yards in the {rules.label}."))
    if kind not in rules.side_yard:
        return _yard_row(facts, role, NO_RULE, gap, explanation=no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "side yard rule"))
    if gap is None:
        return _yard_row(facts, role, NOT_CHECKED, explanation=NO_SIDE_LINE)
    fails, required, detail, shown = _judge_yard(
        record, "side", "Side", gap, _part_gaps(gap, parts), rules.side_yard[kind])
    return _yard_row(facts, role, FAILS if fails else PASSES, shown, required,
                     detail=detail)


def _rear_row(facts, record, gap, shared, touching, parts):
    """The rear yard row, crediting half of an alley behind the lot."""
    rules, kind = facts.rules, facts.home_type
    if "rear" in touching:
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=MAPPING_ERROR)
    if facts.lines.is_corner:
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=CORNER_NO_REAR)
    if gap is None:
        if "rear" in shared:
            return _yard_row(facts, "rear", NOT_REQUIRED, explanation=SHARED_WALL)
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=NO_REAR_FOUND)
    rear_yard = rules.rear_yard_for(kind)
    if not rear_yard:
        return _yard_row(facts, "rear", NO_RULE, gap, explanation=no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "rear yard rule"))
    fails, required, detail, shown = _judge_yard(
        record, "rear", "Rear", gap, _part_gaps(gap, parts), rear_yard, alley_credit=True)
    explanation = None
    if shown.on_open:
        credited = _credited(shown, True)
        detail += ", counting half the alley"
        if not fails and shown.gap < required:
            explanation = (
                f"About {_feet(shown.gap)} to the back lot line. Half of the alley behind "
                f"the lot also counts, which brings the rear yard to about "
                f"{_feet(credited)} against the {_feet(required)} needed.")
            if credited < required:
                explanation += " " + BENEFIT_OF_DOUBT
    return _yard_row(facts, "rear", FAILS if fails else PASSES, shown, required,
                     detail=detail, explanation=explanation)


def _credited(gap: YardGap, alley_credit: bool) -> float:
    """A gap plus half the alley, when the line borders one and the yard allows it."""
    return gap.gap + (ALLEY_CREDIT if alley_credit and gap.on_open else 0)


def _judge_yard(record, name, label, gap, part_gaps, yard, alley_credit=False):
    """Judge one yard, recording it when it is too small.

    The fixed minimum is measured from the closest part of the home (`gap`).
    The setback ratio is checked for each part in `part_gaps` at that part's
    own distance and height, and the part that comes off worst decides.
    The fixed minimum is a firm finding. The taller-building rule leans on
    an estimated height, so its wording says so.

    Returns whether the yard fails, the depth it was judged against, a
    short label for that depth ("needs", or "a home this tall needs" when
    height sets it), and the gap to show: the closest one, or the deciding
    part's when the setback ratio sets the depth.
    """
    if gap.gap + DISTANCE_MARGIN < yard.minimum:
        record(name, yard.minimum - gap.gap + 1000,
               f"{label} yard is too small: about {_feet(gap.gap)}, but at least "
               f"{_feet(yard.minimum)} is required.")
        return True, yard.minimum, "needs", gap
    worst = max(part_gaps, key=lambda part: (yard.required(part.height)
                                             - _credited(part, alley_credit)))
    required = yard.required(worst.height)
    if required <= yard.minimum:
        return False, yard.minimum, "needs", gap
    several = len(part_gaps) > 1
    detail = (f"its {_feet(worst.height)} tall part needs" if several
              else "a home this tall needs")
    if _credited(worst, alley_credit) + DISTANCE_MARGIN < required:
        if several:
            text = (f"{label} yard is too small for the building's height: the part "
                    f"of the home roughly {_feet(worst.height)} tall is about "
                    f"{_feet(worst.gap)} from the lot line, but needs about "
                    f"{_feet(required)}.")
        else:
            text = (f"{label} yard is too small for the building's height: about "
                    f"{_feet(worst.gap)}, but a building this tall (roughly "
                    f"{_feet(worst.height)}) needs about {_feet(required)}.")
        record(name, required - _credited(worst, alley_credit), text)
        return True, required, detail, worst
    return False, required, detail, worst


def _check_yards_without_front(facts, findings, homes):
    """Fallback when no street front is known: test only the fixed minimum.

    Without a front we cannot tell side from rear, so we use the smaller of
    the two fixed minimums and skip homes that share a wall. The four usual
    yard rows are left unchecked; the nearest lot line gets a row of its own.
    """
    rules, kind = facts.rules, facts.home_type
    exempt = kind in rules.no_front_yard_for
    for role in YARD_ROLES:
        if role == "front" and exempt:
            findings.results.append(_yard_row(facts, role, NOT_REQUIRED,
                                              explanation=no_front_yard_explanation(rules)))
        else:
            findings.results.append(_yard_row(facts, role, NOT_CHECKED, explanation=NO_STREET))
    if exempt:
        return  # The closest edge could be the exempt front.
    if not homes or facts.attached_neighbors is not None or rules.side_yards_by_lot_width:
        return
    minimums = [yard.minimum for yard in
                (rules.side_yard.get(kind), rules.rear_yard_for(kind)) if yard]
    if not minimums:
        return
    needed = min(minimums)
    gap, home, piece = min(((piece.line.distance(home.shape), home, piece)
                            for home in homes for piece in facts.lines.pieces),
                           key=lambda found: found[0])
    nearest = YardGap(gap, piece.kind == "open", _nearest_line(home, piece.line),
                      [piece.line])
    if gap < TOUCHING_GAP:
        # Drawn on the line with no neighbor attached: a mapping error.
        findings.results.append(_yard_row(facts, "nearest", NOT_CHECKED, nearest,
                                          explanation=MAPPING_ERROR))
        return
    fails = gap + DISTANCE_MARGIN < needed
    if fails:
        findings.reasons.append(Reason(
            "yards",
            f"Too close to the lot line: about {_feet(gap)}, but at least "
            f"{_feet(needed)} is required.",
        ))
    row = _yard_row(facts, "nearest", FAILS if fails else PASSES, nearest, detail="needs")
    row.required = needed
    findings.results.append(row)


def _home_indexes(facts) -> list[int]:
    """Where each home's outline sits in `facts.all_buildings`."""
    found = []
    for home in facts.homes:
        for index, outline in enumerate(facts.all_buildings):
            if outline.equals(home.shape):
                found.append(index)
                break
    return found


def _check_floor_area(facts, findings):
    kind = facts.home_type
    limit = facts.rules.floor_area_ratio_for(kind, facts.in_historic_district)
    row = RuleResult("floor_area", "Floor space", NO_RULE, unit="sq ft", limit="max",
                     about=facts.rules.floor_area_note or None)
    findings.results.append(row)
    if not limit:
        row.explanation = no_rule_explanation(
            facts.rules.label, HOME_TYPE_NAMES[kind], "floor space limit")
        return
    if any(home.floor_area is None for home in facts.homes):
        row.status, row.explanation = NOT_CHECKED, NO_FLOOR_AREA
        return
    floor_area = sum(home.floor_area for home in facts.homes)
    ratio = floor_area / facts.area
    findings.measurements["floor_area_ratio"] = ratio
    row.status, row.measured, row.required = PASSES, floor_area, limit * facts.area
    row.buildings = _home_indexes(facts)
    if ratio > limit * (1 + FLOOR_AREA_MARGIN):
        row.status = FAILS
        findings.reasons.append(Reason(
            "floor_area",
            f"Too much building for the lot: about {_square_feet(floor_area)} "
            f"of floor space on a {_square_feet(facts.area)} lot. The "
            f"{facts.rules.label} allows floor space up to "
            f"{limit:.0%} of the lot ({_square_feet(limit * facts.area)}).",
        ))


def _check_height(facts, findings):
    kind = facts.home_type
    limit = facts.rules.max_height.get(kind)
    row = RuleResult("height", "Height", NO_RULE, unit="ft", limit="max")
    findings.results.append(row)
    if not limit:
        row.explanation = no_rule_explanation(
            facts.rules.label, HOME_TYPE_NAMES[kind], "height limit")
        return
    known = [home for home in facts.homes if home.height]
    if not known:
        row.status, row.explanation = NOT_CHECKED, NO_HEIGHT
        return
    tallest = max(known, key=lambda home: home.height)
    height = tallest.height
    findings.measurements["height"] = height
    row.status, row.measured, row.required = PASSES, height, limit
    row.buildings = [i for i, outline in enumerate(facts.all_buildings)
                     if outline.equals(tallest.shape)][:1]
    if height > limit + HEIGHT_MARGIN:
        row.status = FAILS
        findings.reasons.append(Reason(
            "height",
            f"Too tall: about {_feet(height)}, but the {facts.rules.label} allows {_feet(limit)}.",
        ))


def _check_open_space(facts, findings):
    rules, kind = facts.rules, facts.home_type
    open_row = RuleResult("open_space", "Open space", NO_RULE, unit="share")
    cover_row = RuleResult("coverage", "Land covered by buildings", NO_RULE,
                           unit="share", limit="max")
    row = cover_row if rules.max_coverage else open_row
    if (rules.open_space_applies_to and kind not in rules.open_space_applies_to) or (
            not rules.min_open_space and not rules.max_coverage):
        if rules.name == "RM" and not rules.max_coverage:
            row = open_row
            row.status, row.explanation = NOT_CHECKED, RM_OPEN_SPACE
        else:
            row = cover_row
            row.explanation = no_rule_explanation(
                rules.label, HOME_TYPE_NAMES[kind], "open space or coverage limit")
        findings.results.append(row)
        return
    if not facts.all_buildings:
        findings.results.append(row)
        row.status, row.explanation = NOT_CHECKED, NO_OUTLINES
        return
    covered = unary_union(facts.all_buildings).intersection(facts.shape).area
    share = covered / facts.shape.area
    findings.measurements["coverage"] = share
    too_much = bool(rules.max_coverage) and share > rules.max_coverage + COVERAGE_MARGIN
    too_little = (not too_much and bool(rules.min_open_space)
                  and 1 - share < rules.min_open_space - COVERAGE_MARGIN)
    if too_little:
        row = open_row
    elif too_much:
        row = cover_row
    if row is cover_row:
        row.measured, row.required = share, rules.max_coverage
    else:
        row.measured, row.required, row.limit = 1 - share, rules.min_open_space, "min"
    row.status = FAILS if (too_much or too_little) else PASSES
    row.buildings = list(range(len(facts.all_buildings)))
    findings.results.append(row)
    if too_much:
        findings.reasons.append(Reason(
            "open_space",
            f"Buildings cover too much of the lot: about {share:.0%}, but "
            f"the {rules.label} allows {rules.max_coverage:.0%}.",
        ))
    elif too_little:
        findings.reasons.append(Reason(
            "open_space",
            f"Not enough open space: buildings alone cover about {share:.0%} "
            f"of the lot, but {rules.min_open_space:.0%} must be left open.",
        ))
