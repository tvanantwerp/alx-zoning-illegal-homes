"""Compare one lot and its homes against the zone's rules.

Every check returns plain-language reasons. Map data is never exact (lot
lines and building outlines come from different surveys, and outlines are
traced from roofs, eaves included), so each check leaves a margin and only
reports a problem when the home misses the rule by more than that margin.
"""
import math
from dataclasses import dataclass, field, replace

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import nearest_points, substring, unary_union

from .heights import FLAT, MIN_PART_AREA, BuildingHeight, RoofHeight, building_height
from .lot_lines import (LotLines, StreetCenterline, front_for_yard, largest_polygon,
                        lot_width, lot_width_line)
from .rule_results import (
    CORNER_NO_REAR, CROSSES_LOT_LINE, FAILS, MAPPING_ERROR, NO_FLOOR_AREA, NO_HEIGHT,
    NO_OUTLINES, NO_REAR_FOUND, NO_RULE, NO_SIDE_LINE, NO_STREET, NOT_CHECKED, NOT_REQUIRED,
    OLDER_LOT, PASSES, RULE_IDS,
    SHARED_LOT, SHARED_WALL, SIDE_COUNT_ON_CORNER, TOO_SHALLOW, TWO_UNIT_LOT, YARD_BENEFIT_OF_DOUBT,
    CRMU_M_OLDER_LOT_NOTE, FLOOR_AREA_MEASURED, HEIGHT_MEASURED, HEIGHT_NEAR_STREET_ABOUT,
    RuleResult,
    eisenhower_older_home_note, eisenhower_special_permit_explanation,
    explain_margin, format_feet as _feet, front_yard_explanation, frontage_about,
    height_explanation, height_map_explanation, height_near_street_explanation,
    height_near_street_waived_explanation, height_winner_explanation,
    margin_explanation, no_front_yard_explanation, no_height_limit_explanation,
    block_average_front_yard_explanation,
    contextual_front_yard_explanation, contextual_front_yard_reason,
    corner_no_rear_yard_explanation, corner_rear_yard_explanation,
    corner_wall_not_found_explanation,
    corner_side_as_rear_explanation,
    historic_front_yard_explanation, no_block_face_explanation,
    no_rule_explanation, outbuildings_explanation, pitched_roof_height_explanation,
    zone_height_source_explanation,
    older_lot_explanation, older_lot_limit_explanation,
    older_rules_explanation, open_space_about, side_count_explanation,
    ROW_LENGTH_ABOUT, long_row_explanation, long_row_reason, row_length_summary,
    row_no_townhouses_explanation, row_set_by_plan_explanation,
    split_twin_explanation, split_twin_reason, unplaced_divided_explanation,
    yard_height_explanation)
from .rules import (HOME_TYPE_NAMES, HOUSE_LIKE, MAX_TOWNHOUSE_ROW_LENGTH,
                    MAX_TOWNHOUSES_IN_ROW, OLDER_LOTS, HeightMapLimit, OlderHomeAllowance,
                    ZoneRules, outbuilding_allowance)

# Slack given to distance measurements, in feet. Covers measuring error and
# the 30 inches that eaves and roof overhangs may reach into a yard, since
# building outlines are traced from roof edges.
DISTANCE_MARGIN = 2.5
AREA_MARGIN = 0.03
WIDTH_MARGIN = 0.05
FLOOR_AREA_MARGIN = 0.10
HEIGHT_MARGIN = 5.0
COVERAGE_MARGIN = 0.03
# Open space must be at least this wide and long to count.
MIN_OPEN_WIDTH = 8.0
OVERLAY_GRID = 0.01
OPEN_SPACE_LEFT_OUT = ("once buildings, roads, driveways, parking and strips "
                       "narrower than 8 ft are left out")
# In every height district a building may be at most this many times as
# tall as its distance from the center of the street it faces.
STREET_HEIGHT_RATIO = 2.0
# Slack given to the distance from a building to the center of the street,
# in feet: the roof overhangs and measuring error DISTANCE_MARGIN covers,
# plus a few feet for a street map centerline that follows the middle of
# the pavement rather than the middle of the public street.
CENTERLINE_MARGIN = 5.0
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

YARD_ROLES = ("front", "left", "right", "rear")
# Rows the rule for older lots can excuse: lot size (or land per home),
# lot width and street frontage.
LOT_RULES = ("lot_area", "width", "frontage")
YARD_NAMES = {"front": "Front yard", "left": "Left side yard",
              "right": "Right side yard", "rear": "Rear yard",
              "nearest": "Closest lot line"}
_STATUS_RANK = {NO_RULE: 0, NOT_REQUIRED: 1, NOT_CHECKED: 2, PASSES: 3, FAILS: 4}


@dataclass
class Home:
    """A residential building on the lot being checked."""

    shape: object
    # Height to the top of the roof, from the city's 3D data.
    height: float | None = None
    floor_area: float | None = None
    # Roof sections from the city's 3D data, as (shape, height) pairs.
    sections: list = field(default_factory=list)
    year_built: int | None = None
    # Number of stories from the city's building records, or None.
    stories: float | None = None
    # Whether city building records mark shops on the ground floor, or None
    # when they don't say.
    ground_floor_retail: bool | None = None
    height_areas: list = field(default_factory=list)  # (intersection or whole outline, map rule)


@dataclass
class Outbuilding:
    """A building on the lot that isn't a home: a garage, a shed or the like.

    index:      where its outline sits in LotFacts.all_buildings.
    floor_area: its floor space, from city records or estimated from its outline.
    label:      what to call it, e.g. "garage or shed".
    """

    index: int
    floor_area: float
    label: str = "outbuilding"


@dataclass
class TownhouseRow:
    """The row of attached homes a lot's homes stand in, found by shared walls.

    homes:        how many homes the row holds, this lot's included.
    length:       the row's overall length in feet.
    outlines:     outlines of the row's buildings on other lots, for drawing.
                  Filled in only for rows too long to pass.
    all_outlined: False when `outlines` leaves out the buildings furthest
                  from this lot, to keep the drawing small.
    """

    homes: int
    length: float
    outlines: list = field(default_factory=list)
    all_outlined: bool = True

    @property
    def exceeds_permit_length(self):
        return self.length > MAX_TOWNHOUSE_ROW_LENGTH + 2 * DISTANCE_MARGIN

    @property
    def severity(self):
        return (self.homes > MAX_TOWNHOUSES_IN_ROW and self.exceeds_permit_length,
                self.homes, self.length)


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
    # Buildings on the lot other than homes, for the floor space rule.
    outbuildings: list[Outbuilding] = field(default_factory=list)
    # Homes on other lots that touch this lot's homes.
    attached_neighbors: object = None
    in_historic_district: bool = False
    # Year the oldest home on the lot was built, from city records.
    year_built: int | None = None
    # Whether the lot lies within 1,000 ft of Eisenhower Avenue's centerline.
    near_eisenhower_avenue: bool = False
    parking_spaces: list | None = None  # Individual stall outlines, when surveyed.
    # Roads, alleys, driveways and parking lots on the lot, from the city's
    # map, or None. None of this counts as open space.
    paved: object = None
    # The parking part of `paved`, for zones that count some parking as
    # open space (RD).
    parking: object = None
    # The height district map's rule for the area the lot is in, or None.
    height_map: HeightMapLimit | None = None
    # The neighbors along each street the lot faces, keyed by street name,
    # each a list of `FrontSetback`s: the contextual block face (lots beside
    # and across the street), and every other building on the same side of
    # the block. Filled in only for zones whose front yard rule uses them.
    contextual_block_face: dict = field(default_factory=dict)
    block_side: dict = field(default_factory=dict)
    # The row of attached homes this lot's homes stand in, or None when they
    # share a wall with no home on another lot.
    row: TownhouseRow | None = None


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


def _for_whole_house(kind: str) -> str:
    """Words that make clear a lot rule covers a whole two-unit house, or nothing."""
    return " for a two-unit house" if kind == "two_unit" else ""


def check_lot(facts: LotFacts) -> Findings:
    """Run every check on a lot and collect the reasons it fails."""
    findings = Findings()
    position = _position(facts)
    findings.measurements["position"] = position
    allowance = _check_home_type(facts, findings)
    _check_row_length(facts, findings)
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
    older_lot = _excuse_older_lot(facts, findings)
    _check_yards(facts, findings, width)
    marginal = (not older_lot and facts.rules.name in OLDER_LOTS.zones
                and facts.home_type in HOUSE_LIKE and facts.home_type in facts.rules.allowed
                and any(row.rule in LOT_RULES and row.status == PASSES and row.required
                        and row.measured is not None and row.measured < row.required
                        for row in findings.results))
    for check_bulk in (_check_floor_area, _check_height):
        check_bulk(facts, findings, older_lot)
        if marginal:
            alternative = Findings()
            check_bulk(facts, alternative, True)
            row, other = findings.results[-1], alternative.results[-1]
            if (row.status == FAILS) != (other.status == FAILS):
                row.status = NOT_CHECKED
                row.explanation = ("The lot falls below a minimum by less than the measurement "
                                   "margin. The outcome depends on whether the older-lot limit applies.")
                findings.reasons = [reason for reason in findings.reasons if reason.kind != row.rule]
    _check_height_near_street(facts, findings)
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


def _wall_runs(line, outline):
    """Project each connected footprint portion beside the lot line onto it."""
    band = line.buffer(SHARED_WALL_GAP, cap_style="flat")
    runs = []
    for part in shapely.get_parts(outline.intersection(band)):
        points = shapely.points(shapely.get_coordinates(part)[:, :2])
        distances = shapely.line_locate_point(line, points)
        if len(distances):
            runs.append((distances.min(), distances.max()))
    return runs


def _shared_line(line, shape, neighbor, min_run=4):
    """Return the runs of lot line alongside both outlines for at least four feet."""
    if neighbor is None or line.distance(shape) >= SHARED_WALL_GAP or line.distance(
            neighbor) >= SHARED_WALL_GAP:
        return shapely.LineString()
    other_runs = _wall_runs(line, neighbor)
    shared = []
    for start, end in _wall_runs(line, shape):
        for other_start, other_end in other_runs:
            lo, hi = max(start, other_start), min(end, other_end)
            if hi - lo >= min_run:
                shared.append(substring(line, lo, hi))
    return unary_union(shared)


def _attached_sides(facts: LotFacts) -> set[int]:
    """Which sides of the lot's homes share a wall with a neighbor."""
    if facts.attached_neighbors is None or facts.lines.front_direction is None:
        return set()
    sides = set()
    for home in facts.homes:
        for piece in facts.lines.pieces:
            if piece.kind == "street":
                continue
            if not _shared_line(piece.line, home.shape, facts.attached_neighbors).is_empty:
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
    elif facts.near_eisenhower_avenue and kind in rules.special_permit_near_eisenhower:
        status = FAILS
        summary = f"{name} near Eisenhower Avenue needs a special permit in the {rules.label}"
        explanation = eisenhower_special_permit_explanation(rules.label)
        findings.reasons.append(Reason(
            "home_type",
            f"This kind of home ({name}) is on a lot within 1,000 ft of the centerline of "
            f"Eisenhower Avenue, where the {rules.label} allows it only with a special "
            "permit. It would need a special permit from City Council.",
        ))
        older = rules.eisenhower_older_homes
        if (older is not None and facts.year_built is not None
                and facts.year_built < older.before_year):
            note = eisenhower_older_home_note(older, facts.year_built)
            explanation = f"{explanation} {note}"
            findings.notes.append(note)
    findings.results.append(RuleResult(
        "home_type", "Home type", status, summary=summary, explanation=explanation))
    return allowance


def _check_row_length(facts, findings):
    """Check how many townhouses share one building with this lot's.

    The townhouse rule allows at most eight townhouses in one building; City
    Council can allow more with a special permit in some zones, up to a
    building 212 ft long. A row a few feet over that length passes, since
    outlines are traced from roofs and include the eaves at both ends. Only
    townhouses get this row.
    """
    if facts.home_type != "townhouse":
        return
    rules = facts.rules
    row = facts.row or TownhouseRow(homes=1, length=0.0)
    result = RuleResult("row_length", "Townhouses in one row", PASSES,
                        measured=float(row.homes), required=float(MAX_TOWNHOUSES_IN_ROW),
                        limit="max", about=ROW_LENGTH_ABOUT,
                        summary=row_length_summary(row.homes))
    findings.results.append(result)
    if "townhouse" not in rules.allowed:
        result.status = NO_RULE
        result.explanation = row_no_townhouses_explanation(rules.label)
        return
    if rules.long_townhouse_rows == "plan":
        result.status = NOT_CHECKED
        result.explanation = row_set_by_plan_explanation(rules.label)
        return
    if row.homes <= MAX_TOWNHOUSES_IN_ROW:
        return
    permit = rules.long_townhouse_rows == "permit"
    too_long = row.exceeds_permit_length
    result.status = FAILS
    result.explanation = long_row_explanation(rules.label, row.homes, row.length,
                                              permit, too_long)
    result.buildings = _home_indexes(facts)
    if row.outlines:
        result.shapes["row"] = shapely.MultiPolygon(
            [part for outline in row.outlines
             for part in getattr(outline, "geoms", [outline])])
    if not row.all_outlined:
        result.detail = f"the {len(row.outlines)} buildings nearest this lot outlined"
    findings.reasons.append(Reason(
        "row_length", long_row_reason(rules.label, row.homes, row.length, permit, too_long)))


def _check_lot_area(facts, findings, position):
    rules, kind = facts.rules, facts.home_type
    table = rules.corner_lot_area if position == "corner" else rules.lot_area
    required = table.get(kind, rules.lot_area.get(kind))
    per_home = kind == "townhouse" and facts.units > 1
    row = RuleResult("lot_area", "Land per home" if per_home else "Lot size",
                     NO_RULE, unit="sq ft",
                     about=TWO_UNIT_LOT if kind == "two_unit" else None)
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
            f"{rules.label} requires {_square_feet(required)}{corner}"
            f"{_for_whole_house(kind)}.",
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
            f"{where if kind == 'townhouse' else _for_whole_house(kind)}.",
        ))
    return width


def _excuse_older_lot(facts, findings) -> bool:
    """Excuse a house, twin or townhouse on an older lot that falls short of the lot rules.

    In the zones the rule for older lots covers (see `OLDER_LOTS`), a lot
    recorded before December 16, 2023 that is too small, too narrow, has too
    little street frontage, or holds more homes than its land allows, may
    still hold a detached house, a two-unit house or a townhouse. Every lot
    on the map is taken to be that old. The rows it falls short on get a
    status of their own that counts as passing, keeping the shortfall on
    show, and their reasons are dropped.

    Returns True when the lot is excused this way, so floor space and
    height are judged by that rule's limits instead of the zone's.
    """
    rules, kind = facts.rules, facts.home_type
    short = [row for row in findings.results
             if row.rule in LOT_RULES and row.status == FAILS]
    if not short or kind not in HOUSE_LIKE or kind not in rules.allowed:
        return False
    if rules.name not in OLDER_LOTS.zones:
        if rules.name == "CRMU-M":
            findings.notes.append(CRMU_M_OLDER_LOT_NOTE)
        return False
    for row in short:
        row.status = OLDER_LOT
        row.explanation = older_lot_explanation(row, rules.label)
    findings.reasons = [reason for reason in findings.reasons
                        if reason.kind not in ("lot_size", "lot_width")]
    findings.notes.append(
        f"This lot falls short of what the {rules.label} asks of new lots, but lots "
        f"recorded before {OLDER_LOTS.recorded_before} may still hold a house, a "
        "two-unit house or a townhouse. The home is held to the zone's yard and open "
        f"space rules, floor space up to {OLDER_LOTS.floor_area_ratio:.0%} of the lot, "
        f"and a height of {_feet(OLDER_LOTS.height)}.")
    return True


def _add_older_lot_note(row: RuleResult, note: str) -> None:
    """Put the older-lot note ahead of whatever the row's tooltip already says.

    A row that passes only thanks to the margin also keeps that explanation,
    which `explain_margin` would otherwise add later.
    """
    row.explanation = " ".join(filter(None, [note, row.explanation or margin_explanation(row)]))


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
    # The roof of the part of the home this gap is measured from, whose
    # height as the ordinance measures it sets the setback ratio's depth.
    roof: RoofHeight | None = None
    facing_only: bool = False

    @property
    def height(self) -> float:
        """The part's height as the ordinance measures it, or 0 when unknown."""
        return self.roof.height if self.roof is not None else 0.0


def _nearest_line(home, line) -> LineString:
    """The shortest line between a home and a lot line."""
    on_home, on_line = nearest_points(home.shape, line)
    return LineString([on_home, on_line])


def _facing_gap(shape, line):
    """Measure only the wall facing the interior of this stretch of boundary."""
    if line.length <= 0.02:
        return None
    interior = substring(line, 0.01, line.length - 0.01)
    reach = max(shape.length, shape.distance(line) + shape.length)
    facing = shape.intersection(interior.buffer(reach, cap_style="flat"))
    if facing.area <= 0:
        return None
    return LineString(nearest_points(facing, line))


def _part_gaps(gap: YardGap, parts: list[RoofHeight]) -> list[YardGap]:
    """The same side's gap, measured again from each part of the home.

    The setback ratio pairs each part of a building with its own height
    (the ordinance's definition of setback ratio), so a low rear wing is
    judged by its own height and a taller block behind it by its own
    distance. Each part's height is the one the ordinance measures: the top
    of a flat roof, or halfway up a gable or hip roof (see `heights.py`).
    """
    measured = []
    for roof in parts:
        if gap.facing_only:
            facing = [(_facing_gap(roof.outline, line), is_open)
                      for line, is_open in zip(gap.lines, gap.lines_open)]
            choices = [(g.length, g, is_open) for g, is_open in facing if g is not None]
            if choices:
                distance, segment, is_open = min(choices, key=lambda entry: entry[0])
                measured.append(YardGap(distance, is_open, segment, gap.lines, gap.lines_open, roof))
            continue
        distance, line, is_open = min(
            ((line.distance(roof.outline), line, is_open)
             for line, is_open in zip(gap.lines, gap.lines_open)),
            key=lambda found: found[0])
        on_part, on_line = nearest_points(roof.outline, line)
        measured.append(YardGap(distance, is_open, LineString([on_part, on_line]),
                                gap.lines, gap.lines_open, roof))
    return measured


def _corner_remainder_is_rear(facts) -> bool:
    """Whether the lot lines away from both streets make up the lot's rear yard.

    True for a townhouse on a corner lot in a zone with the RM zone's corner
    lot rule: both street sides are front yards, and "the remaining yard on
    an exterior townhouse lot" must meet the rear yard rule. A townhouse on
    a corner is at the end of its row, so it is such an exterior lot.
    """
    return (facts.lines.is_corner and facts.rules.corner_townhouse_rear_yard
            and facts.home_type == "townhouse")


def _yard_gaps(facts, home) -> tuple[dict, dict]:
    """Measure a home's gap to each side, the rear, and the street.

    Returns a dict with keys -1 and +1 (the two sides), "rear" and "front",
    each a YardGap, or missing when the lot has no such edge. Also returns
    the keys that share a wall with a neighbor, each with the lot lines
    along that wall. Sides with a shared wall are left out of the first
    dict; a rear only loses the lines on the wall.

    Corner and through lots have no rear: every lot line off the street is
    a side. The exception is a corner townhouse lot under the RM zone's
    corner lot rule, where every such line not on a shared wall is the rear,
    as long as it lies straight across from some part of the home and no
    attached neighbor fills the ground in between. That leaves out the
    stretch of a shared-wall lot line that runs on past the back of the
    home, which the home's corner sits right beside but which bounds no
    yard of its own, and a shared wall the map draws a few feet off its
    lot line.
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
    remainder_is_rear = _corner_remainder_is_rear(facts)

    gaps, shared_wall = {}, {}
    for piece in lines.pieces:
        gap = piece.line.distance(home.shape)
        if piece.kind == "street":
            key = "front"
        else:
            runs_along_front = abs(piece.direction @ along) > np.cos(np.radians(45))
            behind_home = (piece.midpoint - front_anchor) @ inward > rear_starts
            wall = _shared_line(piece.line, home.shape, facts.attached_neighbors,
                                min_run=0.01 if remainder_is_rear else 4)
            on_shared_wall = not wall.is_empty
            if remainder_is_rear:
                if on_shared_wall:
                    key = _side_of(facts, piece.midpoint, home)
                    shared_wall.setdefault(key, []).append(wall)
                for line in shapely.get_parts(piece.line.difference(wall)):
                    nearest = _facing_gap(home.shape, line)
                    if nearest is None or _behind_neighbor(facts, nearest):
                        continue
                    is_open = piece.kind == "open"
                    if "rear" not in gaps:
                        gaps["rear"] = YardGap(nearest.length, is_open, nearest, [], [],
                                              facing_only=True)
                    entry = gaps["rear"]
                    entry.lines.append(line)
                    entry.lines_open.append(is_open)
                    if nearest.length < entry.gap:
                        entry.gap, entry.on_open, entry.nearest = nearest.length, is_open, nearest
                continue
            elif has_rear and runs_along_front and behind_home:
                if on_shared_wall:
                    shared_wall.setdefault("rear", []).append(piece.line)
                    continue
                key = "rear"
            else:
                key = _side_of(facts, piece.midpoint, home)
                if on_shared_wall:
                    shared_wall.setdefault(key, []).append(piece.line)
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
    for key in shared_wall.keys() - {"rear"}:
        gaps.pop(key, None)
    return gaps, shared_wall


def _behind_neighbor(facts, gap) -> bool:
    """Whether a home attached to this one fills the gap between it and a lot line piece.

    A yard is open ground between a building and its lot line. When the
    attached neighbor's outline covers that ground, the city's lot lines and
    building outlines are a few feet apart there, and the line is really the
    shared wall between the two.
    """
    if facts.attached_neighbors is None:
        return False
    return gap.intersection(facts.attached_neighbors).length > 0.5 * gap.length


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
            row.shapes["strip"] = _strip(facts, gap.lines, required)
    return row


def _strip(facts, lines, depth):
    """The part of the lot within `depth` of the given lot lines."""
    return unary_union(
        [line.buffer(depth, cap_style="flat") for line in lines]).intersection(facts.shape)


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

    lot_neighbors = facts.attached_neighbors
    for home in homes:
        if _corner_remainder_is_rear(facts) and lot_neighbors is not None:
            touching_homes = [n for n in shapely.get_parts(lot_neighbors)
                              if home.shape.distance(n) <= 1.5]
            facts = replace(facts, attached_neighbors=unary_union(touching_homes)
                            if touching_homes else None)
        gaps, shared = _yard_gaps(facts, home)
        estimate = _home_height(facts, home)
        parts = estimate.parts if estimate is not None else []
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

        _keep_worst(rows, _front_row(facts, record, gaps["front"], home))
        for row in _side_rows(facts, record, gaps, shared, touching, parts, width):
            _keep_worst(rows, row)
        _keep_worst(rows, _rear_row(facts, record, gaps.get("rear"), shared,
                                    touching, parts))

    findings.results += rows.values()
    for _, text in worst.values():
        findings.reasons.append(Reason("yards", text))


def _front_row(facts, record, gap, home):
    """Judge the front yard by whichever rule the zone sets for it.

    `gap` is the home's distance to the closest street the lot faces.
    """
    rules = facts.rules
    if facts.home_type in rules.no_front_yard_for:
        return _yard_row(facts, "front", NOT_REQUIRED, gap,
                         explanation=no_front_yard_explanation(rules))
    if rules.contextual_front_yard is not None:
        return _contextual_front_row(facts, record, gap, home)
    if rules.front_yard_by_block_average:
        return _block_average_front_row(facts, home)
    if rules.front_at_lot_line_unless_approved:
        return _historic_front_row(facts, gap)
    if not rules.front_yard:
        return _yard_row(facts, "front", NOT_CHECKED, gap,
                         explanation=front_yard_explanation(rules))
    fails = gap.gap + DISTANCE_MARGIN < rules.front_yard
    if fails:
        record("front", rules.front_yard - gap.gap,
               f"Too close to the street: front yard is about "
               f"{_feet(gap.gap)}, but {_feet(rules.front_yard)} is required.")
    return _yard_row(facts, "front", FAILS if fails else PASSES, gap,
                     rules.front_yard, detail="needs")


@dataclass
class StreetFront:
    """A home's front yard along one street the lot faces, and the neighbors it is compared with."""

    label: str
    gap: YardGap
    neighbors: list


def _street_fronts(facts, home, neighbors_by_street) -> list[StreetFront]:
    """The home's gap to each street the lot faces, paired with the neighbors along that street.

    `neighbors_by_street` holds lists of `FrontSetback`s keyed by street name.
    """
    lines = facts.lines
    found = []
    for street in lines.fronts:
        front = front_for_yard(lines, street)
        center = lines.centerlines.get(street)
        gap = YardGap(front.distance(home.shape), False, _nearest_line(home, front),
                      list(front.geoms))
        found.append(StreetFront(center.label if center else street.title(), gap,
                                 neighbors_by_street.get(street) or []))
    return found


def _contextual_front_row(facts, record, closest, home):
    """Judge the front yard against the neighbors along the same street.

    Most zones ask that the front yard "be between the range established by
    the front yards within the contextual block face": the neighboring lots
    with buildings beside the lot and across the street (see
    `block_faces.py`). Once the shallowest of those is deeper than the zone's
    cap, the cap is enough. So the home must stand back at least as far as
    the closest neighbor, or the cap, whichever is less.

    The lot's own home isn't counted in the range. The ordinance defines the
    block face as the "abutting property", and its cap clause, the one place
    that counts the lot's own front yard, comes out the same either way for
    a home too close to the street.

    Each street a corner or through lot faces is judged against its own
    neighbors; the street where the home comes closest to failing sets the
    row. Streets with no neighbors to compare with are left out.
    """
    rules = facts.rules
    cap = rules.contextual_front_yard
    fronts = _street_fronts(facts, home, facts.contextual_block_face)
    judged = [front for front in fronts if front.neighbors]
    alone = [front.label for front in fronts if not front.neighbors]
    if not judged:
        return _yard_row(facts, "front", NOT_CHECKED, closest,
                         explanation=no_block_face_explanation(rules.label, alone))

    def needs(front):
        return min(min(n.distance for n in front.neighbors), cap)

    worst = min(judged, key=lambda front: front.gap.gap - needs(front))
    too_deep = [front for front in judged
                if front.gap.gap > max(n.distance for n in front.neighbors) + DISTANCE_MARGIN
                and min(n.distance for n in front.neighbors) <= cap]
    if worst.gap.gap + DISTANCE_MARGIN >= needs(worst) and too_deep:
        worst = too_deep[0]
    required = needs(worst)
    distances = [n.distance for n in worst.neighbors]
    homes_only = all(n.is_home for n in worst.neighbors)
    fails = worst.gap.gap + DISTANCE_MARGIN < required
    if fails:
        record("front", required - worst.gap.gap, contextual_front_yard_reason(
            worst.label, worst.gap.gap, distances, homes_only, rules.label, cap))
    row = _yard_row(facts, "front", FAILS if fails else PASSES, worst.gap, required,
                    detail="needs")
    if not fails and too_deep:
        row.status = NOT_CHECKED
    row.explanation = " ".join(filter(None, [
        "The setback exceeds the measured range. Its upper bound is unverified." if too_deep and not fails else None,
        contextual_front_yard_explanation(worst.label, worst.gap.gap, distances, homes_only,
                                          rules.label, cap, len(judged) > 1, alone),
        margin_explanation(row)]))
    return row


def _block_average_front_row(facts, home):
    """Measure the front yard in the RM and CD zones, which line homes up with their block.

    The front wall sits at the front lot line, "unless a majority of the
    existing buildings with frontage on the same side of the block ... have
    a greater setback, in which case the front building line shall be the
    average distance of the existing buildings from the front lot line."
    With no other buildings on that side of the block, it sits at the lot
    line. A building measured within the yard margin of its lot line counts
    as at the line, since outlines include roof overhangs.

    The rule sets one exact line, so a home a few feet off the block's
    average breaks it. On real data about a third of RM street fronts miss
    it by more than the yard margin, which says more about how exact the
    map's measurements are than about the homes. So the row shows the
    home's setback and the line the block sets, but isn't judged. On a
    corner lot (both streets count, the RM zone says) the street where the
    home is furthest off its line is shown.
    """
    found = []
    for front in _street_fronts(facts, home, facts.block_side):
        others = [n.distance for n in front.neighbors]
        set_back = sum(distance > DISTANCE_MARGIN for distance in others)
        target = sum(others) / len(others) if set_back * 2 > len(others) else 0.0
        found.append((front, target, set_back))
    front, target, set_back = max(found, key=lambda each: abs(each[0].gap.gap - each[1]))
    row = _yard_row(facts, "front", NOT_CHECKED, front.gap, detail="should be about",
                    limit="max" if front.gap.gap > target else "min")
    row.required = target
    row.explanation = block_average_front_yard_explanation(
        front.label, front.gap.gap, target, len(front.neighbors), set_back, facts.rules.label)
    return row


def _historic_front_row(facts, gap):
    """Judge the front yard of an RB home in the historic districts.

    There the front wall sits at the front lot line, or on another line the
    board of architectural review approves as fitting the district. A home
    at the line passes. One set back from it may have that approval, which
    the map has no record of, so it isn't judged.
    """
    at_line = gap.gap <= DISTANCE_MARGIN
    return _yard_row(facts, "front", PASSES if at_line else NOT_CHECKED, gap,
                     explanation=historic_front_yard_explanation(
                         facts.rules.label, gap.gap, at_line))


def _side_rows(facts, record, gaps, shared, touching, parts, width):
    """Judge both side yards. Returns the left and right rows.

    `parts` is the home split by roof height, each part's roof estimated
    the ordinance's way, or empty when the home's height is unknown.
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
    if _corner_remainder_is_rear(facts):
        if key in shared:
            return _yard_row(facts, role, NOT_REQUIRED, explanation=SHARED_WALL)
        return _yard_row(facts, role, NOT_CHECKED, explanation=(
            corner_side_as_rear_explanation(facts.rules.label)))
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
    if has_yard and gap.gap < 5:
        text += (f" This side is about {_feet(gap.gap)}, a little under 5 ft, and "
                 f"counts as a side yard. {YARD_BENEFIT_OF_DOUBT}")
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
    if key in shared and kind == "semi" and not rules.split_twin_lots_allowed:
        return _split_twin_row(facts, record, role, shared[key])
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
    part_gaps = _part_gaps(gap, parts)
    fails, required, detail, shown = _judge_yard(
        record, "side", "Side", gap, part_gaps, rules.side_yard[kind])
    row = _yard_row(facts, role, FAILS if fails else PASSES, shown, required,
                    detail=detail)
    _explain_yard_height(row, rules.side_yard[kind], shown, len(part_gaps) > 1)
    return row


def _split_twin_row(facts, record, role, wall_lines):
    """Fail the shared-wall side of a twin half on a lot of its own, where the zone forbids that.

    The lot line runs along the wall the two halves share, so this side has
    no yard at all. The row shows the zone's least side yard as a strip
    along that line.
    """
    rules = facts.rules
    minimum = rules.side_yard["semi"].minimum
    record("split twin", minimum, split_twin_reason(rules.label))
    row = _yard_row(facts, role, FAILS, required=minimum, measured=0.0, detail="needs",
                    explanation=split_twin_explanation(rules.label, minimum))
    row.shapes["strip"] = _strip(facts, wall_lines, minimum)
    return row


def _rear_row(facts, record, gap, shared, touching, parts):
    """The rear yard row, crediting half of an alley behind the lot.

    On a corner lot this is checked only under the RM zone's corner lot
    rule, where the yard left over on a townhouse lot, away from both
    streets, must meet the rear yard rule. It isn't judged when the home is
    attached to a neighbor but no lot line runs along the shared wall: the
    lot lines and outlines are a few feet apart there, and the map can't
    tell which line is the wall and which bounds the yard.
    """
    rules, kind = facts.rules, facts.home_type
    corner_rear = _corner_remainder_is_rear(facts)
    if "rear" in touching:
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=MAPPING_ERROR)
    if facts.lines.is_corner and not corner_rear:
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=CORNER_NO_REAR)
    if gap is None and corner_rear:
        return _yard_row(facts, "rear", NOT_CHECKED,
                         explanation=corner_no_rear_yard_explanation(rules.label))
    if corner_rear and not shared and facts.attached_neighbors is not None:
        return _yard_row(facts, "rear", NOT_CHECKED, gap,
                         explanation=corner_wall_not_found_explanation(rules.label))
    if gap is None:
        if "rear" in shared:
            return _yard_row(facts, "rear", NOT_REQUIRED, explanation=SHARED_WALL)
        return _yard_row(facts, "rear", NOT_CHECKED, explanation=NO_REAR_FOUND)
    rear_yard = rules.rear_yard_for(kind)
    if not rear_yard:
        return _yard_row(facts, "rear", NO_RULE, gap, explanation=no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "rear yard rule"))
    part_gaps = _part_gaps(gap, parts)
    fails, required, detail, shown = _judge_yard(
        record, "rear", "Rear", gap, part_gaps, rear_yard, alley_credit=True)
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
                explanation += " " + YARD_BENEFIT_OF_DOUBT
    row = _yard_row(facts, "rear", FAILS if fails else PASSES, shown, required,
                    detail=detail, explanation=explanation)
    _explain_yard_height(row, rear_yard, shown, len(part_gaps) > 1)
    if corner_rear:
        row.explanation = " ".join(filter(None, [
            corner_rear_yard_explanation(rules.label),
            row.explanation or margin_explanation(row)]))
    return row


def _explain_yard_height(row: RuleResult, yard, shown: YardGap, several: bool) -> None:
    """Say which height sized this yard, when the home's height set its depth.

    Adds to the row's explanation, keeping whatever it already says (or the
    note about the margin, which `explain_margin` would otherwise add later).
    Rows judged against the fixed minimum are left alone.
    """
    if shown.roof is None or row.required is None or row.required <= yard.minimum:
        return
    row.explanation = " ".join(filter(None, [
        row.explanation or margin_explanation(row),
        yard_height_explanation(yard.per_foot_of_height, shown.roof, several)]))


def _credited(gap: YardGap, alley_credit: bool) -> float:
    """A gap plus half the alley, when the line borders one and the yard allows it."""
    return gap.gap + (ALLEY_CREDIT if alley_credit and gap.on_open else 0)


def _judge_yard(record, name, label, gap, part_gaps, yard, alley_credit=False):
    """Judge one yard, recording it when it is too small.

    The fixed minimum is measured from the closest part of the home (`gap`).
    The setback ratio is checked for each part in `part_gaps` at that part's
    own distance and height, and the part that comes off worst decides.
    With no parts (the home's height is unknown) only the minimum is checked.
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
    if not part_gaps:
        return False, yard.minimum, "needs", gap
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
            f"Too close to a lot line: about {_feet(gap)}, but at least "
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


def _counted_outbuildings(facts) -> list[Outbuilding]:
    """The garages, sheds and other outbuildings that count toward this lot's floor space.

    Only where the zone's way of counting floor space takes them in: every
    home in R-20 through R-2-5, and houses and two-unit houses in RA and RB,
    outside the historic districts. Elsewhere none count.
    """
    if (facts.in_historic_district
            or facts.home_type not in facts.rules.outbuildings_counted_for):
        return []
    return list(facts.outbuildings)


def _check_floor_area(facts, findings, older_lot=False):
    """Check floor space against the zone's limit, or the older-lot limit when `older_lot`.

    Where the zone counts them, garages, sheds and other outbuildings add
    whatever floor space they hold beyond the lot's allowance.
    """
    kind = facts.home_type
    usual = facts.rules.floor_area_ratio_for(kind, facts.in_historic_district)
    limit = OLDER_LOTS.floor_area_ratio if older_lot else usual
    about = " ".join(filter(None, [
        facts.rules.floor_area_note, FLOOR_AREA_MEASURED if kind in HOUSE_LIKE else None]))
    row = RuleResult("floor_area", "Floor space", NO_RULE, unit="sq ft", limit="max",
                     about=about or None)
    findings.results.append(row)
    if not limit:
        row.explanation = no_rule_explanation(
            facts.rules.label, HOME_TYPE_NAMES[kind], "floor space limit")
        return
    note = older_lot_limit_explanation(
        facts.rules.label, f"floor space up to {limit:.0%} of the lot",
        f"limit of {usual:.0%}" if usual else None) if older_lot else None
    if any(home.floor_area is None for home in facts.homes):
        row.status, row.explanation = NOT_CHECKED, NO_FLOOR_AREA
        if note:
            _add_older_lot_note(row, note)
        return
    outbuildings = _counted_outbuildings(facts)
    allowance = outbuilding_allowance(facts.area)
    total = sum(building.floor_area for building in outbuildings)
    accessory = sum(building.floor_area for building in outbuildings
                    if building.label == "garage or shed")
    added = total - min(accessory, allowance)
    floor_area = sum(home.floor_area for home in facts.homes) + added
    ratio = floor_area / facts.area
    findings.measurements["floor_area_ratio"] = ratio
    row.status, row.measured, row.required = PASSES, floor_area, limit * facts.area
    row.buildings = _home_indexes(facts) + [building.index for building in outbuildings]
    if ratio > limit * (1 + FLOOR_AREA_MARGIN):
        row.status = FAILS
        allows = (f"On an older lot that falls short of the {facts.rules.label}'s "
                  "minimums for new lots, floor space may be" if older_lot
                  else f"The {facts.rules.label} allows floor space")
        counting = (f", counting about {_square_feet(added)} in garages, sheds and other "
                    "outbuildings beyond what the zoning rules leave out" if added else "")
        findings.reasons.append(Reason(
            "floor_area",
            f"Too much building for the lot: about {_square_feet(floor_area)} "
            f"of floor space on a {_square_feet(facts.area)} lot{counting}. {allows} up to "
            f"{limit:.0%} of the lot ({_square_feet(limit * facts.area)}).",
        ))
    found = outbuildings_explanation(
        facts.rules.label, [(building.label, building.floor_area) for building in outbuildings],
        allowance, added) if outbuildings else None
    if note or found:
        row.explanation = " ".join(filter(None, [note, found, margin_explanation(row)]))


def _home_height(facts: LotFacts, home: Home) -> BuildingHeight | None:
    """A home's height as the ordinance measures it, part by part, or None when unknown.

    The height check and the yard check both use this, so a home gets the
    same height in each.
    """
    return building_height(home, apartment=facts.home_type == "multi")


def home_heights(facts: LotFacts) -> list[tuple[Home, BuildingHeight]]:
    """Each home with a known height, paired with its height as the ordinance measures it."""
    found = [(home, _home_height(facts, home)) for home in facts.homes]
    return [(home, estimate) for home, estimate in found if estimate is not None]


def _missing_home_height(facts: LotFacts, known: list[tuple[Home, BuildingHeight]]) -> bool:
    """Whether a home or a measurable part of its footprint lacks a height."""
    return len(known) < len(facts.homes) or any(
        not home.height and not home.stories and
        home.shape.difference(unary_union([part.outline for part in estimate.parts])).area >= MIN_PART_AREA
        for home, estimate in known)


@dataclass
class HeightLimit:
    """One height limit that applies to a home, and how to speak of it.

    allows: what the limit allows, for a reason ("the RC zone allows 150 ft").
    source: the limit's name, for saying which limit set the height
            ("the limit in the RC zone").
    """

    feet: float
    allows: str
    source: str


def _map_height_limit(facts: LotFacts, home: Home) -> HeightLimit | None:
    """The height district map's limit for one home, or None where the map sets none."""
    area = facts.height_map
    if area is None or area.height is None:
        return None
    name = f"the {area.district}"
    source = f"{name}'s limit"
    if area.along_street and area.along_street in facts.lines.fronts:
        return HeightLimit(area.along_height,
                           f"{name} allows {_feet(area.along_height)} along {area.along_name}",
                           f"{source} along {area.along_name}")
    if area.retail_height and home.ground_floor_retail:
        return HeightLimit(area.retail_height,
                           f"{name} allows {_feet(area.retail_height)} for a building with "
                           "shops on its ground floor, as city records show this one has",
                           f"{source} for a building with ground floor shops")
    allows = f"{name} allows {_feet(area.height)}"
    if area.retail_height:
        allows += (f" ({_feet(area.retail_height)} only for a building with shops on its "
                   "ground floor, which city records don't show here)")
    elif area.permit_height:
        allows += (f" without a special permit; up to {_feet(area.permit_height)} would "
                   "need a special permit from City Council")
    elif area.along_street:
        allows += f" away from {area.along_name}"
    return HeightLimit(area.height, allows, source)


def _height_limits(facts: LotFacts, home: Home, older_lot: bool,
                   roof: RoofHeight) -> list[HeightLimit]:
    """Every height limit that applies to one home: the zone's, or the older-lot limit, and the map's.

    The rule for older lots replaces the zone's own height limit. The height
    district map's limit applies on top of either, since "the lowest
    applicable height limitation shall prevail" (section 6-402).

    Where the zone allows more for a roof whose ridge runs along the street
    (RM, and houses and townhouses in CD), `roof` decides which limit
    applies: the roof of the home's tallest part, as the ordinance measures
    it, since the limit is on the height of the whole building. A roof the
    map takes as flat gets the lower limit, since it has no ridge. Every
    other roof gets the higher one: the map can't see a ridge's direction or
    a roof's slope.
    """
    rules = facts.rules
    limits = []
    if older_lot:
        limits.append(HeightLimit(
            OLDER_LOTS.height,
            f"on an older lot that falls short of the {rules.label}'s minimums for new "
            f"lots, homes may be only {_feet(OLDER_LOTS.height)} tall",
            "the limit for older lots"))
    elif rules.max_height.get(facts.home_type):
        usual = rules.max_height[facts.home_type]
        higher = rules.pitched_roof_height.get(facts.home_type)
        allows = f"the {rules.label} allows {_feet(usual)}"
        if higher and roof.shape != FLAT:
            usual, allows = higher, (f"the {rules.label} allows {_feet(higher)} for a roof "
                                     "whose ridge runs along the street")
        elif higher:
            allows += (f" ({_feet(higher)} only for a roof whose ridge runs along the "
                       "street, and this one looks flat)")
        limits.append(HeightLimit(usual, allows, f"the limit in the {rules.label}"))
    on_map = _map_height_limit(facts, home)
    if on_map is not None:
        limits.append(on_map)
    return limits


def _check_height(facts, findings, older_lot=False):
    """Check each home against the lowest height limit that applies to it.

    That is the zone's limit (or the older-lot limit when `older_lot`) and
    the height district map's limit, whichever is lower. The row shows the
    home that comes closest to, or goes furthest over, its limit.
    """
    rules, kind = facts.rules, facts.home_type
    usual = rules.max_height.get(kind)
    row = RuleResult("height", "Height", NO_RULE, unit="ft", limit="max",
                     about=HEIGHT_MEASURED)
    findings.results.append(row)
    note = older_lot_limit_explanation(
        rules.label, f"a height of up to {_feet(OLDER_LOTS.height)}",
        f"limit of {_feet(usual)}" if usual else None) if older_lot else None
    mapped = any(home.height_areas for home in facts.homes) or (
        facts.height_map is not None and facts.height_map.height is not None)
    missing_plan = bool(rules.height_set_by and "height district" not in rules.height_set_by
                        and not older_lot and not usual)
    if not (older_lot or usual or mapped):
        row.status = NOT_CHECKED if missing_plan else NO_RULE
        row.explanation = no_height_limit_explanation(rules, HOME_TYPE_NAMES[kind])
        return
    candidates = []
    known = home_heights(facts)
    for home, estimate in known:
        # Check the whole building against its zone, then each mapped portion
        # against both limits. A roof section only counts where it overlaps.
        regions = home.height_areas or [(None, facts.height_map)]
        if home.height_areas and all(shape is not None for shape, _ in regions):
            regions = [*regions, (None, None)]
        for shape, area in regions:
            relevant = (estimate.parts if shape is None else
                        [p for p in estimate.parts if p.outline.intersection(shape).area > 0])
            limits = _height_limits(replace(facts, height_map=area), home, older_lot, estimate.tallest)
            if relevant and limits:
                candidates.append((home, BuildingHeight(relevant), limits, area))
    if not candidates:
        row.status, row.explanation = NOT_CHECKED, NO_HEIGHT
        if note:
            _add_older_lot_note(row, note)
        return
    tallest, estimate, limits, area = max(
        candidates, key=lambda found: (found[1].height - min(l.feet for l in found[2]),
                                       found[1].height, found[3] is not None))
    on_map = area is not None and area.height is not None
    # On a tie the earlier limit (the zone's) is named as the one that sets it.
    deciding = min(limits, key=lambda limit: limit.feet)
    height, limit = estimate.height, deciding.feet
    findings.measurements["height"] = height
    row.status, row.measured, row.required = PASSES, height, limit
    missing_height = _missing_home_height(facts, known)
    row.buildings = [i for i, outline in enumerate(facts.all_buildings)
                     if outline.equals(tallest.shape)][:1]
    shrunk = height < estimate.peak
    if shrunk:
        row.detail = f"roof peak {_feet(estimate.peak)}"
    if height > limit + HEIGHT_MARGIN:
        row.status = FAILS
        measured = (f"about {_feet(height)} measured the ordinance's way (roof peak about "
                    f"{_feet(estimate.peak)})" if shrunk else f"about {_feet(height)}")
        findings.reasons.append(Reason("height", f"Too tall: {measured}, but {deciding.allows}."))
    if row.status == PASSES and (missing_plan or missing_height):
        row.status = NOT_CHECKED
    others = [(other.source, other.feet) for other in limits if other is not deciding]
    higher = rules.pitched_roof_height.get(kind)
    roof_rule = None
    if higher and usual and not older_lot:
        fails_usual = height > usual + HEIGHT_MARGIN and limit > usual
        whole_roof = next(found.shape for home, found in known if home is tallest)
        if whole_roof == "unknown":
            roof_rule = (f"The roof shape is unknown. The height limit is {_feet(usual)}, "
                         f"or {_feet(higher)} for a qualifying pitched roof.")
            if fails_usual and row.status == PASSES:
                row.status = NOT_CHECKED
        else:
            roof_rule = pitched_roof_height_explanation(
                rules.label, usual, higher, whole_roof == FLAT,
                height if fails_usual else None)
    row.explanation = " ".join(filter(None, [
        note,
        "Some building heights are unknown." if missing_height else None,
        zone_height_source_explanation(rules) if on_map and not usual else None,
        height_winner_explanation(deciding.source, limit, others),
        roof_rule,
        height_map_explanation(area, facts.lines.fronts) if on_map else None,
        height_explanation(estimate),
        margin_explanation(row)]))


@dataclass
class StreetGap:
    """How far one part of a home is from the center of one street the lot faces."""

    home: Home
    roof: RoofHeight
    street: StreetCenterline
    distance: float
    # From the part's closest wall to the center of the street.
    line: LineString

    @property
    def allowed(self) -> float:
        """The tallest this part may be at this distance."""
        return STREET_HEIGHT_RATIO * self.distance

    @property
    def over(self) -> float:
        """How far the part's height goes past what it may be, or below zero when under."""
        return self.roof.height - self.allowed


def _street_gaps(facts: LotFacts, known: list) -> tuple[list[StreetGap], list[str]]:
    """Measure every part of every home against the center of every street the lot faces.

    `known` holds each home with its height, from `home_heights`. Returns
    the measurements and the names of divided roads whose center couldn't
    be placed for at least one part.
    """
    gaps, unplaced = [], []
    for home, estimate in known:
        for roof in estimate.parts:
            for street in facts.lines.centerlines.values():
                found = street.measure(roof.outline)
                if found is None:
                    if street.label not in unplaced:
                        unplaced.append(street.label)
                    continue
                gaps.append(StreetGap(home, roof, street, *found))
    return gaps, unplaced


def _check_height_near_street(facts, findings):
    """Check that no part of a home is more than twice as tall as its distance to the street's center.

    Every height district holds a building to this (section 6-403(A),
    "relationship of height to setback"). Each part of each home is judged
    at its own height, measured the ordinance's way, so an upper floor that
    steps back passes on its own. It is measured against every street the
    lot faces, not just its main one. The row shows the part that comes
    closest to, or goes furthest over, what it may be.
    """
    row = RuleResult("height_near_street", "Height near the street", NOT_CHECKED, unit="ft",
                     limit="max", about=HEIGHT_NEAR_STREET_ABOUT)
    findings.results.append(row)
    if facts.rules.height_near_street_waived:
        row.status = NOT_REQUIRED
        row.explanation = height_near_street_waived_explanation(facts.rules.label)
        return
    if not facts.lines.centerlines:
        row.explanation = NO_STREET
        return
    known = home_heights(facts)
    if not known:
        row.explanation = NO_HEIGHT
        return
    gaps, unplaced = _street_gaps(facts, known)
    unplaced_note = unplaced_divided_explanation(unplaced) if unplaced else None
    if not gaps:
        row.explanation = unplaced_note
        return
    worst = max(gaps, key=lambda gap: (gap.over, gap.roof.height))
    several = len({id(gap.roof) for gap in gaps}) > 1
    label = worst.street.label
    row.status, row.measured, row.required = PASSES, worst.roof.height, worst.allowed
    row.detail = f"{_feet(worst.distance)} from the center of {label}"
    row.shapes = {"gap": worst.line, "part": worst.roof.outline}
    row.buildings = [i for i, outline in enumerate(facts.all_buildings)
                     if outline.equals(worst.home.shape)][:1]
    if worst.roof.height > STREET_HEIGHT_RATIO * (worst.distance + CENTERLINE_MARGIN):
        row.status = FAILS
        which = (f"the part of the home about {_feet(worst.roof.height)} tall is" if several
                 else f"the home, about {_feet(worst.roof.height)} tall, is")
        findings.reasons.append(Reason(
            "height",
            f"Too tall this close to the street: {which} about {_feet(worst.distance)} from "
            f"the center of {label}; at most {_feet(worst.allowed)} is allowed there.",
        ))
    missing_height = _missing_home_height(facts, known)
    if row.status == PASSES and (unplaced or missing_height):
        row.status = NOT_CHECKED
    row.explanation = " ".join(filter(None, [
        "Some building heights are unknown." if missing_height else None,
        height_near_street_explanation(worst.roof, worst.distance, worst.allowed, label,
                                       worst.street.far is not None, several),
        unplaced_note,
        margin_explanation(row)]))


def _polygons(shape):
    """Keep only the areas in a shape, dropping stray lines and points."""
    parts = [part for part in shapely.get_parts(shape)
             if part.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(parts) if parts else shapely.Polygon()


def open_and_usable_area(facts: LotFacts, covered) -> tuple[float, float]:
    """Measure the lot's open and usable space, in sq ft.

    The ordinance counts only land at ground level that is at least 8 ft
    wide and long and isn't used for buildings, roads, alleys, driveways or
    parking. We take the land left over once buildings and paving are
    removed, then shrink it by half that width and grow it back. Any piece
    narrower than 8 ft vanishes in the shrinking and doesn't come back.

    Returns the open land's area and, for zones that let some parking
    count (RD), the area of parking counted on top of it, up to the zone's cap.
    """
    rules = facts.rules
    # Snapping to a hundredth of a foot keeps the city's slightly
    # mismatched outlines from tripping up the shape arithmetic.
    open_land = shapely.difference(_polygons(facts.shape), _polygons(covered),
                                   grid_size=OVERLAY_GRID)
    if facts.paved is not None:
        open_land = shapely.difference(open_land, _polygons(facts.paved),
                                       grid_size=OVERLAY_GRID)
    stalls = []
    if facts.parking_spaces:
        stalls = [s.intersection(facts.shape).difference(covered) for s in facts.parking_spaces]
        stalls = [s for s in stalls if s.area > 0]
        open_land = open_land.difference(unary_union(stalls))
    open_land = _polygons(open_land)
    # Leave a sliver for a strip exactly eight feet wide. At this grid
    # precision the next narrower representable strip still disappears.
    radius = (MIN_OPEN_WIDTH - OVERLAY_GRID / 2) / 2
    opened = (open_land.buffer(-radius, join_style="mitre")
              .buffer(radius, join_style="mitre"))
    usable = shapely.intersection(opened, open_land, grid_size=OVERLAY_GRID)
    credit = 0.0
    if facts.home_type in rules.parking_space_credit_for:
        if len(stalls) >= 2:
            credit = max(s.area for s in stalls)
    if rules.parking_counted_as_open and facts.parking is not None:
        need = (rules.min_open_space or 0.0) * facts.shape.area
        credit = min(rules.parking_counted_as_open * facts.parking.area,
                     rules.parking_open_space_cap * need)
    return usable.area, credit


def _check_open_space(facts, findings):
    rules, kind = facts.rules, facts.home_type
    open_row = RuleResult("open_space", "Open space", NO_RULE, unit="share",
                          about=open_space_about(rules.open_space_note, kind))
    cover_row = RuleResult("coverage", "Land covered by buildings", NO_RULE,
                           unit="share", limit="max")
    row = cover_row if rules.max_coverage else open_row
    if rules.name == "CRMU-X" and kind == "multi":
        open_row.status, open_row.required = NOT_CHECKED, 0.25
        open_row.explanation = ("The multi-unit residential portion must provide 25% open space. "
                                "Its land area and any approved substitute amenities are unknown.")
        findings.results.append(open_row)
        return
    if (rules.open_space_applies_to and kind not in rules.open_space_applies_to) or (
            not rules.min_open_space and not rules.max_coverage):
        row = cover_row
        row.explanation = no_rule_explanation(
            rules.label, HOME_TYPE_NAMES[kind], "open space or coverage limit")
        findings.results.append(row)
        return
    if not facts.all_buildings:
        findings.results.append(row)
        row.status, row.explanation = NOT_CHECKED, NO_OUTLINES
        return
    covered = unary_union(facts.all_buildings).intersection(facts.shape)
    share = covered.area / facts.shape.area
    findings.measurements["coverage"] = share
    too_much = bool(rules.max_coverage) and share > rules.max_coverage + COVERAGE_MARGIN
    # A floor in sq ft is turned into a share of this lot, so one number and
    # one margin cover both parts of the rule.
    need_open = max(rules.min_open_space or 0.0,
                    rules.min_open_space_area / facts.shape.area)
    open_area = open_share = None
    credit = 0.0
    if rules.min_open_space:
        open_area, credit = open_and_usable_area(facts, covered)
        open_share = (open_area + credit) / facts.shape.area
        findings.measurements["open_space"] = open_share
    too_little = (not too_much and need_open > 0
                  and open_share < need_open - COVERAGE_MARGIN)
    if too_little:
        row = open_row
    elif too_much:
        row = cover_row
    if row is cover_row:
        row.measured, row.required = share, rules.max_coverage
    else:
        row.measured, row.required, row.limit = open_share, need_open, "min"
    row.status = FAILS if (too_much or too_little) else PASSES
    row.buildings = list(range(len(facts.all_buildings)))
    findings.results.append(row)
    stall_credit = kind in rules.parking_space_credit_for
    if credit and stall_credit:
        row.explanation = f"One parking space counts, adding {_square_feet(credit)} of open space."
    if too_little and stall_credit and facts.parking_spaces is None and facts.parking is not None:
        possible_credit = facts.parking.difference(covered).area
        if (open_area + possible_credit) / facts.shape.area + COVERAGE_MARGIN >= need_open:
            row.status = NOT_CHECKED
            row.explanation = ("The paving map does not distinguish individual stalls. "
                               "One space can count if the lot provides at least two.")
            return
    if too_much:
        findings.reasons.append(Reason(
            "open_space",
            f"Buildings cover too much of the lot: about {share:.0%}, but "
            f"the {rules.label} allows {rules.max_coverage:.0%}.",
        ))
    elif too_little and need_open > (rules.min_open_space or 0.0):
        findings.reasons.append(Reason(
            "open_space",
            f"Not enough open space: only about {open_area:,.0f} sq ft of the lot is "
            f"left open {OPEN_SPACE_LEFT_OUT}, but the {rules.label} requires at least "
            f"{rules.min_open_space_area:,.0f} sq ft.",
        ))
    elif too_little:
        findings.reasons.append(Reason(
            "open_space",
            f"Not enough open space: only about {open_share:.0%} of the lot is left "
            f"open {OPEN_SPACE_LEFT_OUT}, but {need_open:.0%} must be left open."
            + (f" That counts {credit:,.0f} sq ft of parking, as the {rules.label} allows."
               if credit else ""),
        ))
