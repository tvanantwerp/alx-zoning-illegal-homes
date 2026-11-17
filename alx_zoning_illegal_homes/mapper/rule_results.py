"""How a lot did against each rule, kept in a form the pop-up can show.

The checks in `checks.py` write one `RuleResult` per rule alongside the
plain-language reasons. A row is `fails` exactly when the check also wrote a
reason, so the table and the reasons never disagree.
"""
from dataclasses import dataclass, field

from .rules import ZoneRules

FAILS, PASSES, NOT_CHECKED, NO_RULE, NOT_REQUIRED = (
    "fails", "passes", "not_checked", "no_rule", "not_required")

RULE_IDS = ("lot_area", "frontage", "width", "yard:front", "yard:left", "yard:right",
            "yard:rear", "yard:nearest", "floor_area", "height", "coverage",
            "open_space", "home_type")

NO_STREET = ("The map couldn't find a public street next to this lot, so it "
             "can't tell which edge is the front.")
SHARED_LOT = ("Several homes share this one lot, so no single home has lot "
              "lines of its own to measure.")
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
    return f"The map's rules for the {zone_label} include no {what} for a {home_type_name}."


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
