"""How a lot did against each rule, kept in a form the pop-up can show.

The checks in `checks.py` write one `RuleResult` per rule alongside the
plain-language reasons. A row is `fails` exactly when the check also wrote a
reason, so the table and the reasons never disagree.
"""
from dataclasses import dataclass, field, replace

from .rules import OlderHomeAllowance, PlannedDistrict, ZoneRules

FAILS, PASSES, NOT_CHECKED, NO_RULE, NOT_REQUIRED = (
    "fails", "passes", "not_checked", "no_rule", "not_required")

RULE_IDS = ("lot_area", "frontage", "width", "yard:front", "yard:left", "yard:right",
            "yard:rear", "yard:nearest", "floor_area", "height", "coverage",
            "open_space", "home_type")

NO_STREET = ("The map couldn't find a public street next to this lot, so it "
             "can't tell which edge is the front.")
SHARED_LOT = ("Several homes share this one lot, so no single home has lot "
              "lines of its own to measure.")
TWO_UNIT_LOT = (
    "This lot holds a whole two-unit house: two homes side by side, sharing a wall, "
    "on one lot. The lot size and street frontage rules here are for the whole house, "
    "which in most zones means room for each of its two homes.")
TOO_SHALLOW = ("The lot is shallower than the depth where this zone measures "
               "width, so the map couldn't measure it.")
SHARED_WALL = ("This side of the home shares a wall with the house next door, "
               "so no yard is expected here.")
CORNER_NO_REAR = ("On a corner lot the map treats every edge that isn't on a street "
                  "as a side, so there is no rear yard to check. The side yard rules "
                  "apply instead.")
NO_REAR_FOUND = ("The map couldn't pick out a back lot line behind this home, as "
                 "happens on lots with streets at both ends or odd shapes. Every edge "
                 "that isn't on the street was judged against the side yard rule instead.")
MAPPING_ERROR = ("The city's map shows this home touching the lot line with no "
                 "neighbor attached. That is more likely a mapping error than a real "
                 "wall on the line, so this yard wasn't checked.")
CROSSES_LOT_LINE = ("A building outline on this lot crosses the lot line in the city's "
                    "map, so its yards weren't checked.")
SIDE_COUNT_ON_CORNER = ("On corner lots the map doesn't count side yards in this zone.")
NO_SIDE_LINE = "The map couldn't find a lot line on this side of the home."
NO_FLOOR_AREA = ("City records don't give this home's floor space, and it couldn't be "
                 "estimated from the number of stories.")
NO_HEIGHT = "The city's 3D building data has no height for this home."
NO_OUTLINES = "The city's map has no building outlines on this lot."
OPEN_SPACE_MEASURED = (
    "Open space is land at ground level at least 8 ft wide that isn't under a "
    "building, a road, a driveway or parking. The map takes buildings, roads, "
    "driveways and parking lots from the city's map, which is traced from aerial "
    "photos, and leaves out every strip of open land narrower than 8 ft. Patios, "
    "small parking pads and other paving missing from the city's map still count "
    "as open here, so a lot may have less open space than the map finds.")
ROOF_OPEN_SPACE = (
    "Many zones also let a landscaped roof or other outdoor space above the ground "
    "count, if the city's planning director agrees. The map can't see those, so an "
    "apartment building may have more open space than it shows.")
BENEFIT_OF_DOUBT = ("Measurements from the city's map and records aren't exact, so "
                    "the map gives it the benefit of the doubt.")
YARD_BENEFIT_OF_DOUBT = (
    "The city's building outlines are traced from roof edges, and the zoning rules "
    "let eaves and roof overhangs reach up to 30 inches into a yard, so the walls "
    "may well be far enough back. With that and some room for measuring error, "
    "the map gives it the benefit of the doubt.")

# Rows the approved site plan of a planned district sets, along with every yard row.
SITE_PLAN_RULES = ("lot_area", "frontage", "width")


@dataclass
class RuleResult:
    """How a lot did against one rule, with what's needed to explain and draw it."""

    rule: str                 # fixed id, see RULE_IDS
    name: str                 # as the table shows it, e.g. "Lot size"
    status: str               # one of the five labels above
    measured: float | None = None
    required: float | None = None
    unit: str = ""            # "sq ft", "ft", "share" or ""
    limit: str = "min"        # "min" or "max"
    explanation: str | None = None  # tooltip on the result label
    about: str | None = None        # tooltip on the rule name
    detail: str | None = None       # short drawing label, e.g. "measured 25 ft back"
    summary: str | None = None      # one-line text where numbers don't fit (home type)
    shapes: dict = field(default_factory=dict)   # name -> shapely geometry, lot coordinates
    buildings: list[int] = field(default_factory=list)  # indexes into LotFacts.all_buildings


def reason_kind(rule: str) -> str:
    """The Reason.kind a failing row of this rule goes with."""
    if rule.startswith("yard:"):
        return "yards"
    return {
        "lot_area": "lot_size",
        "frontage": "lot_width",
        "width": "lot_width",
        "coverage": "open_space",
        "open_space": "open_space",
    }.get(rule, rule)


def format_feet(value: float) -> str:
    """Write a length in feet, with a decimal only when it's a short one."""
    return f"{value:,.0f} ft" if value >= 20 else f"{value:,.1f} ft"


def no_rule_explanation(zone_label: str, home_type_name: str, what: str) -> str:
    """Say that the zone's rules set no limit of this kind for this kind of home."""
    return f"The map's rules for the {zone_label} include no {what} for a {home_type_name}."


def open_space_about(zone_note: str, home_type: str) -> str:
    """Say what the open space rule asks and what the map counts as open space."""
    parts = [zone_note] if zone_note else []
    parts.append(OPEN_SPACE_MEASURED)
    if home_type == "multi":
        parts.append(ROOF_OPEN_SPACE)
    return " ".join(parts)


def older_rules_explanation(zone_label: str, before: str) -> str:
    """Say that an older home may be rebuilt under the limits it was built under."""
    return (f"This home was built before {before}, so the {zone_label} lets it be "
            "rebuilt under the limits in force when it was built. The map doesn't "
            "know those older limits.")


def eisenhower_special_permit_explanation(zone_label: str) -> str:
    """Say why a home near Eisenhower Avenue fails the home type rule."""
    return (f"The {zone_label} allows homes on lots within 1,000 ft of the centerline of "
            "Eisenhower Avenue only with a special permit from City Council. This lot is "
            "that close. The map has no record of special permits, so it can't tell "
            "whether this home has one.")


def eisenhower_older_home_note(allowance: OlderHomeAllowance, year_built: int) -> str:
    """Say that an older home near Eisenhower Avenue may need no special permit."""
    return (f"{allowance.rule} The oldest home on this lot was built in {year_built}, "
            "so it may qualify. The map judges whether this home could be built new.")


def _show(value: float, unit: str, precise: bool = False) -> str:
    """Write a measured or required value in its unit, with one more decimal when `precise`."""
    if unit == "ft":
        return f"{value:,.1f} ft" if precise else format_feet(value)
    if unit == "sq ft":
        return f"{value:,.0f} sq ft"
    if unit == "share":
        return f"{value:.1%}" if precise else f"{value:.0%}"
    return f"{value:,.1f}"


def explain_margin(results: list[RuleResult]) -> None:
    """Explain rows that pass only thanks to the margin left for measuring error.

    The checks only fail a rule when a home misses it by more than that margin,
    so a row can pass with a number on the wrong side of the limit, such as a
    33 ft home under a 30 ft height limit. Each such row without an explanation
    of its own gets one saying so; yard rows also mention roof overhangs, which
    the margin allows for. Changes the rows in place.
    """
    for row in results:
        if (row.status != PASSES or row.explanation
                or row.measured is None or row.required is None):
            continue
        if row.limit == "min" and row.measured < row.required:
            side, word = "under", "minimum"
        elif row.limit == "max" and row.measured > row.required:
            side, word = "over", "limit"
        else:
            continue
        measured, required = _show(row.measured, row.unit), _show(row.required, row.unit)
        if measured == required:
            measured = _show(row.measured, row.unit, precise=True)
            required = _show(row.required, row.unit, precise=True)
        benefit = YARD_BENEFIT_OF_DOUBT if row.rule.startswith("yard:") else BENEFIT_OF_DOUBT
        row.explanation = f"About {measured}, a little {side} the {required} {word}. {benefit}"


def frontage_about(street: str, zone_label: str, required: float | None,
                   width_measured_at: float) -> str:
    """Explain street frontage for this lot (the tooltip on the rule's name)."""
    text = ("How much of the lot touches the street: the length of the front "
            f"lot line along {street}, following any curve.")
    if required:
        text += f" The {zone_label} requires at least {format_feet(required)}."
    if width_measured_at > 0:
        text += (" This is a separate rule from lot width, which is measured "
                 f"in a straight line across the lot {format_feet(width_measured_at)} "
                 "back from the street, where the front yard ends. A lot can "
                 "pass one and fail the other, as on a cul-de-sac, where lots "
                 "are narrow at the street and widen further back.")
    else:
        text += (" In this zone, lot width is also measured right at the "
                 "street, so here the two rules measure the same line.")
    return text


def no_front_yard_explanation(rules: ZoneRules) -> str:
    """Why no front yard is required in this lot's zone."""
    text = (f"The {rules.label} requires no front yard. Six streets have extra setbacks "
            "of their own (Duke Street, King Street, Seminary Road, Beauregard Street, "
            "South Pickett Street and Mount Vernon Avenue), which the map doesn't "
            "check yet.")
    if rules.name == "RC":
        text += (" RC lots along the George Washington Memorial Parkway also have a "
                 "deep setback from Washington Street.")
    return text


def front_yard_explanation(rules: ZoneRules, in_historic_district: bool) -> str:
    """Why the front yard isn't checked in this lot's zone."""
    label = rules.label
    if rules.name == "RM" or (rules.name == "RB" and in_historic_district):
        return (f"In the {label}, a home's front wall is meant to sit right at the "
                "front lot line, unless most homes on the block are set back further. "
                "Then it must line up with their average. The map doesn't measure the "
                "neighbors' homes yet, so this rule isn't checked.")
    if rules.name.startswith("R"):
        return (f"In the {label}, the front yard must fall within the range of front "
                "yards of the neighboring homes that share this street frontage. The "
                "map doesn't measure the neighbors' homes yet, so this rule isn't checked.")
    return f"The map doesn't check front yards in the {label}."


def side_count_explanation(zone_label: str, width: float, needed: int) -> str:
    """Explain the zones where the number of side yards depends on lot width."""
    ending = {0: "none.", 1: "a 5 ft yard on at least one side."}.get(
        needed, "a 5 ft yard on both sides.")
    return (f"In the {zone_label}, side yards depend on lot width: none on lots under "
            "25 ft wide, one 5 ft side yard from 25 to 35 ft, and two at 35 ft or more. "
            f"This lot is about {format_feet(width)} wide, so it needs {ending}")


def under_special_approval(results: list[RuleResult],
                           district: PlannedDistrict) -> list[RuleResult]:
    """The results as they stand under a planned district's special approval.

    Lot size, frontage, width and yard rows with no rule or no check become
    "not required", since the approved site plan sets them. Other rows with no
    rule say the approval sets no lot-by-lot limit. Returns new rows and leaves
    the ones passed in alone.
    """
    out = []
    for row in results:
        plan_sets_it = row.rule in SITE_PLAN_RULES or row.rule.startswith("yard:")
        if plan_sets_it and row.status in (NO_RULE, NOT_CHECKED):
            row = replace(row, status=NOT_REQUIRED, explanation=(
                f"The approved site plan for {district.name} sets lot sizes and "
                "yards here, so no general rule applies."))
        elif row.status == NO_RULE:
            row = replace(row, explanation=(
                "The special approval sets no lot-by-lot limit for this. "
                f"{district.plan_summary}"))
        out.append(row)
    return out
