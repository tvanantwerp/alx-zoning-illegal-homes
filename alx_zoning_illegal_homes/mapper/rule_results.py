"""How a lot did against each rule, kept in a form the pop-up can show.

The checks in `checks.py` write one `RuleResult` per rule alongside the
plain-language reasons. A row is `fails` exactly when the check also wrote a
reason, so the table and the reasons never disagree.
"""
from dataclasses import dataclass, field, replace

from .heights import FLAT, UNKNOWN, RoofHeight
from .rules import (MAX_TOWNHOUSE_ROW_LENGTH, MAX_TOWNHOUSES_IN_ROW, OLDER_LOTS,
                    HeightMapLimit, OlderHomeAllowance, PlannedDistrict, ZoneRules)


FAILS, PASSES, NOT_CHECKED, NO_RULE, NOT_REQUIRED = (
    "fails", "passes", "not_checked", "no_rule", "not_required")
# A lot rule this older lot falls short of, but which the rule for older
# lots excuses. Counts as passing; the row keeps the shortfall on show.
OLDER_LOT = "older_lot"

RULE_IDS = ("lot_area", "frontage", "width", "yard:front", "yard:street", "yard:left", "yard:right",
            "yard:rear", "yard:nearest", "floor_area", "height", "height_near_street",
            "coverage", "open_space", "home_type", "row_length")

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
FLOOR_AREA_MEASURED = (
    "The zoning rules count all floor space under a roof, measured from the outside of "
    "the walls, finished or not, but leave out basements, stairs, attic space under 7 ft "
    "high and open porches up to 8 ft deep. The map uses each home's floor space from "
    "the city's assessment records, or, where they give none, an estimate from its "
    "outline and number of stories. The city's figure seems to count only finished "
    "living space, leaving out attached garages and unfinished space, so the real "
    "figure may be somewhat higher than the map shows.")
NO_HEIGHT = "The city's 3D building data has no height for this home."
HEIGHT_MEASURED = (
    "The zoning rules measure height from the ground to the top of a flat roof, but "
    "only to halfway between the eaves and the peak of a gable or hip roof. The city's "
    "3D building data gives only the peak, so the map guesses the roof's shape and "
    "where its eaves are from the number of stories in city records. It can't see "
    "gambrel or mansard roofs, which the rules measure higher up, or wide dormers, "
    "which in most house zones move the measurement up to the dormers.")
HEIGHT_NEAR_STREET_ABOUT = (
    "In every height district, a building may be at most twice as tall at any point as "
    "the distance from its wall there to the center of the street it faces. A wall 25 ft "
    "from the center of the street may be 50 ft tall; taller parts must step back. The "
    "map checks each part of each home at its own height, measured the same way as the "
    "height rule, against the center of every street the lot faces.")
CENTERLINE_MEASURED = (
    "The center of the street comes from the city's street map, which traces the middle "
    "of the pavement. The rule means the middle of the public street, which can sit a "
    "few feet off it, and building outlines include roof overhangs, so the map allows "
    "5 ft of distance (10 ft of height) before calling it a problem.")
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
        "height_near_street": "height",
    }.get(rule, rule)


def format_feet(value: float) -> str:
    """Write a length in feet, with a decimal only when it's a short one."""
    return f"{value:,.0f} ft" if value >= 20 else f"{value:,.1f} ft"


def no_rule_explanation(zone_label: str, home_type_name: str, what: str) -> str:
    """Say that the zone's rules set no limit of this kind for this kind of home."""
    article = "an" if home_type_name[0] in "aeiou" else "a"
    return (f"The map's rules for the {zone_label} include no {what} for "
            f"{article} {home_type_name}.")


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


def _older_lot_rule(zone_label: str) -> str:
    """The rule for older lots, in plain words."""
    return (f"Lots recorded before {OLDER_LOTS.recorded_before} in the {zone_label} may "
            "still hold a detached house, a two-unit house or a townhouse when they fall "
            "short of the minimum lot size, width, street frontage or land per home. The "
            "home must still meet the zone's yard and open space rules, with floor space "
            f"up to {OLDER_LOTS.floor_area_ratio:.0%} of the lot area and a height of "
            f"up to {format_feet(OLDER_LOTS.height)}, whatever the zone's own limits. The "
            "map takes every lot as recorded before that date; it can't tell a lot that "
            "was split or redrawn since.")


def older_lot_explanation(row: "RuleResult", zone_label: str) -> str:
    """Explain a lot size, width or frontage row that the rule for older lots excuses."""
    measured, required = _show(row.measured, row.unit), _show(row.required, row.unit)
    if row.rule == "lot_area" and row.name == "Land per home":
        shortfall = (f"About {measured} of land for each home; the {zone_label} asks "
                     f"{required} for each home on a new lot.")
    else:
        what = {"lot_area": f"This lot is about {measured}",
                "width": f"This lot is about {measured} wide",
                "frontage": f"This lot has about {measured} of street frontage"}[row.rule]
        shortfall = f"{what}; the {zone_label} asks {required} of a new lot."
    return f"{shortfall} {_older_lot_rule(zone_label)}"


def older_lot_limit_explanation(zone_label: str, what: str, usual: str | None) -> str:
    """Say that the rule for older lots sets this row's limit in place of the zone's own.

    `what` names the limit ("floor space up to 1.50 times the lot area") and
    `usual` is the zone's own limit in words, or None when it sets none.
    """
    instead = (f"in place of the zone's usual {usual}" if usual
               else "where the zone sets no limit of its own")
    return (f"This lot falls short of what the {zone_label} asks of new lots, so the rule "
            f"for older lots applies: {what}, {instead}.")


CRMU_M_OLDER_LOT_NOTE = (
    "This lot falls short of what the CRMU-M zone asks of new lots. The zoning rules "
    "let older lots in many zones that fall short still hold a house, a two-unit house "
    "or a townhouse (section 12-1000). That section's title names the CRMU-M zone, but "
    "its text leaves CRMU-M out, and the text governs, so the map doesn't apply it here.")


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


def margin_explanation(row: RuleResult) -> str | None:
    """Say why a row passes with a number on the wrong side of its limit, or None.

    The checks only fail a rule when a home misses it by more than a margin
    left for measuring error, so a row can pass with a number on the wrong
    side of the limit, such as a 33 ft home under a 30 ft height limit. Yard
    rows also mention roof overhangs, which the margin allows for.
    """
    if row.status != PASSES or row.measured is None or row.required is None:
        return None
    if row.limit == "min" and row.measured < row.required:
        side, word = "under", "minimum"
    elif row.limit == "max" and row.measured > row.required:
        side, word = "over", "limit"
    else:
        return None
    measured, required = _show(row.measured, row.unit), _show(row.required, row.unit)
    if measured == required:
        measured = _show(row.measured, row.unit, precise=True)
        required = _show(row.required, row.unit, precise=True)
    benefit = YARD_BENEFIT_OF_DOUBT if row.rule.startswith("yard:") else BENEFIT_OF_DOUBT
    return f"About {measured}, a little {side} the {required} {word}. {benefit}"


def explain_margin(results: list[RuleResult]) -> None:
    """Explain rows that pass only thanks to the margin left for measuring error.

    Each such row without an explanation of its own gets the one from
    `margin_explanation`. Changes the rows in place.
    """
    for row in results:
        if not row.explanation:
            row.explanation = margin_explanation(row)


def height_explanation(estimate) -> str:
    """Give a home's roof peak and its height as the zoning rules measure it, and how it was guessed."""
    peak, height, why = estimate.peak, estimate.height, estimate.why
    if estimate.shape == "unknown":
        return f"Estimated height: {format_feet(height)}. {why}"
    if height < peak:
        numbers = (f"Roof peak about {format_feet(peak)}; measured the ordinance's way, "
                   f"about {format_feet(height)}.")
    else:
        numbers = f"About {format_feet(height)} to the top of the roof."
    return f"{numbers} {why}"


def pitched_roof_height_explanation(zone_label: str, usual: float, higher: float,
                                    flat: bool, fails_usual_at: float | None = None) -> str:
    """Explain the RM and CD zones' two height limits and which one the map used.

    `usual` is the zone's limit and `higher` the one allowed for a roof
    whose ridge runs along the street. `flat` is whether the map takes the
    roof it judged as flat. `fails_usual_at` is the home's height when it
    would fail the lower limit, so whether its roof qualifies matters, and
    None otherwise.
    """
    rule = (f"The {zone_label} allows {format_feet(usual)}, or up to {format_feet(higher)} "
            "when the roof's ridge line runs parallel to the street and its slope is "
            "compatible with neighboring buildings.")
    if flat:
        return (f"{rule} The map takes this roof as flat, and a flat roof has no ridge "
                f"line, so the {format_feet(usual)} limit applies.")
    held = (f" At about {format_feet(fails_usual_at)}, it would fail the "
            f"{format_feet(usual)} limit." if fails_usual_at is not None else "")
    return (f"{rule} The city's 3D data draws each part of a home as a flat-topped "
            "block, so the map can't see which way a roof's ridge runs or compare its "
            f"slope with the neighbors'. It allows {format_feet(higher)} for every home it takes to have a "
            f"sloped roof, but this home may be held to {format_feet(usual)} if its roof "
            f"doesn't qualify.{held}")


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def height_winner_explanation(source: str, feet: float,
                              others: list[tuple[str, float]]) -> str | None:
    """Say which height limit applies when more than one does: the lowest wins.

    `source` names the limit that applies and `feet` is that limit; `others`
    holds the other limits as (name, feet) pairs. Returns None when only one
    limit applies.
    """
    if not others:
        return None
    other, other_feet = others[0]
    if other_feet == feet:
        return f"{_capitalized(source)} and {other} are both {format_feet(feet)}."
    return (f"{_capitalized(source)} ({format_feet(feet)}) is lower than {other} "
            f"({format_feet(other_feet)}), and the lowest height limit always wins.")


def _height_from_map(rules: ZoneRules) -> bool:
    """Whether the zone's own height limit is the one on the height district map."""
    return "height district" in rules.height_set_by


def zone_height_source_explanation(rules: ZoneRules) -> str:
    """Say why the height district map sets this lot's height where the zone sets none."""
    if not rules.height_set_by:
        return (f"The {rules.label} sets no height limit of its own, so the height "
                "district map's limit applies.")
    if _height_from_map(rules):
        return f"The {rules.label} takes its height limit from {rules.height_set_by}."
    return (f"The {rules.label} takes its height limit from {rules.height_set_by}, which "
            "the map doesn't have. The height district map's limit applies everywhere, "
            "so that is what's checked.")


def no_height_limit_explanation(rules: ZoneRules, home_type_name: str) -> str:
    """Say why a home has no height limit to check."""
    if not rules.height_set_by:
        return no_rule_explanation(rules.label, home_type_name, "height limit")
    if _height_from_map(rules):
        return (f"The {rules.label} takes its height limit from {rules.height_set_by}, "
                "which sets none here.")
    return (f"The {rules.label} takes its height limit from {rules.height_set_by}, which "
            "the map doesn't have, and the height district map sets no limit here.")


def height_map_explanation(area: HeightMapLimit, fronts) -> str | None:
    """Explain the parts of a height district map rule the map had to decide on.

    `fronts` holds the names of the streets the lot faces. Returns None for
    an area with a single plain limit.
    """
    if area.note:
        return area.note
    if area.along_street:
        on_it = area.along_street in fronts
        return (f"The Old Town North Small Area Plan gives {format_feet(area.along_height)} "
                f"along {area.along_name} and {format_feet(area.height)} behind it here. "
                f"The map couldn't find how deep the {format_feet(area.along_height)} strip "
                f"runs, so it uses {format_feet(area.along_height)} for any lot with a street "
                f"edge on {area.along_name}. This lot "
                + ("has one." if on_it else
                   f"has none, so it gets {format_feet(area.height)}."))
    if area.retail_height:
        return (f"The {area.district} allows {format_feet(area.height)}, or "
                f"{format_feet(area.retail_height)} for a building with shops along at least "
                "the first 30 ft of its depth facing the street. The map goes by city "
                "building records, which mark buildings with shops on the ground floor, "
                "and can't check how deep the shops run.")
    if area.permit_height:
        return (f"The {area.district} allows {format_feet(area.height)}, or up to "
                f"{format_feet(area.permit_height)} with a special permit from City Council "
                "and the historic district board's approval. The map has no record of "
                f"special permits, so it holds every building to {format_feet(area.height)}.")
    return None


def yard_height_explanation(per_foot_of_height: float, roof: RoofHeight, several: bool) -> str:
    """Say which height sized a yard that grows with the home's height, and how it was found.

    `roof` is the part of the home that set the yard's depth; `several` is
    True when the home was split into parts of different heights.
    """
    feet = 1 / per_foot_of_height
    every = "every foot" if feet == 1 else f"every {feet:g} ft"
    text = (f"A taller home needs a deeper yard here (a setback ratio of 1:{feet:g}): "
            f"1 ft of yard for {every} of height")
    if several:
        text += ", judged for each part of the home at its own height and distance"
    whose = "The part of the home that sets this yard" if several else "This home"
    if roof.shape == UNKNOWN:
        numbers = f"{whose} is estimated at {format_feet(roof.height)} from its stories."
    elif roof.shape == FLAT:
        numbers = (f"{whose} is about {format_feet(roof.height)} to the top of its roof, "
                   "treated as a flat roof.")
    else:
        numbers = (f"{whose} has a roof peak about {format_feet(roof.peak)}; measured the "
                   f"ordinance's way, it is about {format_feet(roof.height)} tall.")
    return f"{text}. {numbers} {roof.why}"


def named_street_setback_about(label: str, stretch: str, section: str) -> str:
    """The tooltip on a section 7-1006 row's name: what the rule is and why it exists."""
    where = f"{label} {stretch}".strip()
    return (f"Section {section} of the zoning ordinance sets an extra setback along {where}, "
            "to leave room for sidewalks and road widening and to keep buildings in a steady "
            "line. Where it asks more than the zone's own front yard, it wins. It applies "
            "whatever the zone.")


def named_street_setback_explanation(label: str, distance: float, required: float,
                                     from_centerline: bool, what: str = "the home") -> str:
    """How a building's distance from a named street was measured against section 7-1006.

    `what` names the building: "the home", or an outbuilding such as "a garage or shed".
    """
    building = what[0].upper() + what[1:]
    if from_centerline:
        return (f"{building} is about {format_feet(distance)} from the center of {label}; "
                f"at least {format_feet(required)} is required. The ordinance measures from "
                "the street's centerline as mapped in 1960. The map uses the centerline in "
                "today's street map, which may differ where the street was widened or moved.")
    return (f"{building} is about {format_feet(distance)} from the front lot line along "
            f"{label}; at least {format_feet(required)} is required.")


def named_street_setback_reason(label: str, distance: float, required: float,
                                from_centerline: bool, stretch: str, section: str,
                                what: str = "the home") -> str:
    """The reason a lot breaks a section 7-1006 setback, in one sentence.

    `what` names the building that stands too close. A home is taken as read;
    an outbuilding is named, since the home itself may stand far enough back.
    """
    measured_from = "the center of the street" if from_centerline else "the front lot line"
    where = f"on {label} {stretch}".strip()
    which = "" if what == "the home" else f"{what} on the lot is "
    return (f"Too close to {label}: {which}about {format_feet(distance)} from {measured_from}, but "
            f"buildings {where} must stand at least {format_feet(required)} back from it "
            f"(section {section}).")


def height_near_street_waived_explanation(rules_label: str) -> str:
    """Say that these rules set aside the rule tying height to distance from the street."""
    return (f"The {rules_label} sets aside the height districts' rule tying a building's "
            "height to its distance from the center of the street (section 5-602), so "
            "it isn't checked here.")


def _divided_note(label: str) -> str:
    return (f"{label} is a divided road, which the street map draws as one centerline "
            "for each side, so its center is taken as halfway between the two.")


def unplaced_divided_explanation(labels: list[str]) -> str:
    """Say that the center of a divided road couldn't be placed, so it wasn't measured from."""
    names = " and ".join(labels)
    one = len(labels) == 1
    return (f"{names} {'is a divided road' if one else 'are divided roads'}, which the "
            "street map draws as one centerline for each side. The map couldn't find the "
            f"far side near this lot to place the center, so {'it' if one else 'they'} "
            f"{'was' if one else 'were'}n't measured from.")


def height_near_street_explanation(roof: RoofHeight, distance: float, allowed: float,
                                   label: str, divided: bool, several: bool) -> str:
    """Explain the height near the street row: which part, how far, and how it was measured.

    `roof` is the part of a home that comes closest to its limit, `distance`
    its distance from the center of the street named `label`, and `allowed`
    twice that. `divided` is True when that street is a divided road, and
    `several` when the home was split into parts of different heights.
    """
    whose = "The part of the home closest to its limit" if several else "This home"
    text = (f"{whose} is about {format_feet(distance)} from the center of {label}, so it "
            f"may be up to about {format_feet(allowed)} tall there.")
    if roof.shape == UNKNOWN:
        numbers = f"Its estimated height is {format_feet(roof.height)}."
    elif roof.shape == FLAT:
        numbers = (f"It is about {format_feet(roof.height)} to the top of its roof, "
                   "treated as a flat roof.")
    else:
        numbers = (f"Its roof peak is about {format_feet(roof.peak)}; measured the "
                   f"ordinance's way, it is about {format_feet(roof.height)} tall.")
    return " ".join(filter(None, [text, numbers, roof.why,
                                  _divided_note(label) if divided else None,
                                  CENTERLINE_MEASURED]))


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


def front_yard_explanation(rules: ZoneRules) -> str:
    """Why the front yard isn't checked in this lot's zone."""
    return f"The map doesn't check front yards in the {rules.label}."


FRONT_MEASURED = (
    "Each building is measured from its closest part to its front lot line. Building "
    "outlines are traced from roofs, so a porch roof or overhang counts as part of the "
    "building, for this home and its neighbors alike.")


def _neighbors_set_back(distances: list[float], homes_only: bool) -> str:
    """Say how far the neighbors along a street stand back: "the neighboring homes there are set back 20 to 28 ft"."""
    what = "home" if homes_only else "building"
    low, high = format_feet(min(distances)), format_feet(max(distances))
    if len(distances) == 1:
        return f"the neighboring {what} there is set back {low}"
    if low == high:
        return f"the {len(distances)} neighboring {what}s there are all set back about {low}"
    return f"the neighboring {what}s there are set back {low.removesuffix(' ft')} to {high}"


def contextual_front_yard_reason(street: str, gap: float, distances: list[float],
                                 homes_only: bool, zone_label: str, cap: float) -> str:
    """The reason a home stands too close to the street for its neighbors."""
    text = (f"Too close to {street}: set back about {format_feet(gap)}, but "
            f"{_neighbors_set_back(distances, homes_only)}")
    if min(distances) > cap:
        return f"{text}, and the {zone_label} asks for at least {format_feet(cap)}."
    return f"{text}."


def contextual_front_yard_explanation(street: str, gap: float, distances: list[float],
                                      homes_only: bool, zone_label: str, cap: float,
                                      several: bool, alone: list[str]) -> str:
    """Explain a front yard judged against the neighbors along the same street.

    `street` is the street that set the row, `gap` this home's setback from it
    and `distances` its neighbors'. `several` is True when more than one of the
    lot's streets had neighbors to compare with, and `alone` names any it faces
    with none.
    """
    parts = [
        f"Set back about {format_feet(gap)} from {street}; "
        f"{_neighbors_set_back(distances, homes_only)}.",
        f"In the {zone_label}, a home's front yard must fall within the range of the "
        "front yards of its neighbors along the same street: the lots on either side "
        "and the lots across the street that have buildings on them. Once the "
        f"shallowest of those is deeper than {format_feet(cap)}, {format_feet(cap)} is "
        "enough. This home itself isn't counted in the range.",
    ]
    if several:
        parts.append("Each street this lot faces is judged against its own neighbors; "
                     "this is the one where the home comes closest to the line.")
    if alone:
        parts.append(f"No neighbors share its frontage on {' and '.join(alone)}, so that "
                     "side wasn't judged.")
    parts.append(FRONT_MEASURED)
    parts.append("The map checks only that the home stands back far enough, not that it "
                 "stands no further back than its neighbors.")
    return " ".join(parts)


def no_block_face_explanation(zone_label: str, streets: list[str]) -> str:
    """Say why a front yard set by the neighbors couldn't be judged: there are none."""
    along = f" on {' or '.join(streets)}" if streets else ""
    return (f"In the {zone_label}, a home's front yard must fall within the range of the "
            "front yards of its neighbors along the same street. The map found no lots "
            f"with buildings beside this one or across the street that share its "
            f"frontage{along}, so there is nothing to compare it with.")


def block_average_front_yard_explanation(street: str, gap: float, target: float,
                                         others: int, set_back: int, zone_label: str) -> str:
    """Explain the RM and CD zones' front yard, which the map measures but doesn't judge.

    `others` counts the other buildings found on the same side of the block
    and `set_back` how many of them stand back from the lot line.
    """
    parts = [
        f"Set back about {format_feet(gap)} from {street}.",
        f"In the {zone_label}, a home's front wall sits at the front lot line, unless most "
        "other buildings on the same side of the block stand further back. Then it lines "
        "up with their average distance from the lot line.",
    ]
    if not others:
        parts.append("The map found no other buildings on this side of the block, so the "
                     "home belongs at the lot line.")
    elif target > 0:
        parts.append(f"Here {set_back} of the {others} other buildings on this side of the "
                     "block stand back from the lot line, and on average they stand about "
                     f"{format_feet(target)} back.")
    else:
        parts.append(f"Here only {set_back} of the {others} other buildings on this side "
                     "of the block stand back from the lot line, so the home belongs at it.")
    parts.append(
        "The map doesn't judge this rule. It sets one exact line, so a home a few feet off "
        "the block's average breaks it, and the map's measurements aren't that exact: "
        f"{FRONT_MEASURED[0].lower()}{FRONT_MEASURED[1:]} The map also takes the side of the "
        "block to be the run of lots along the street that touch one another, so an alley "
        "through the block ends it early.")
    return " ".join(parts)


def historic_front_yard_explanation(zone_label: str, gap: float, at_line: bool) -> str:
    """Explain the RB zone's front yard in the historic districts."""
    rule = (f"In the Old and Historic Alexandria and Parker-Gray districts, the {zone_label} "
            "puts a home's front wall at the front lot line, or on another line the board "
            "of architectural review approves as fitting the district.")
    if at_line:
        return f"{rule} This home stands at the lot line."
    return (f"{rule} This home is set back about {format_feet(gap)}. The map has no record "
            "of the board's approvals, so it can't judge this.")


def split_twin_reason(zone_label: str) -> str:
    """Say that this zone keeps a twin house whole on one lot."""
    return (f"In the {zone_label} the two halves of a twin house must share one lot; "
            "this half has a lot line through the building.")


def split_twin_explanation(zone_label: str, minimum: float) -> str:
    """Explain the failing side yard where a twin's halves sit on lots of their own."""
    return (f"{split_twin_reason(zone_label)} The {zone_label} allows a two-unit house "
            "only as one building on one lot, and asks every home for two side yards. "
            "Here the lot line runs along the wall shared with the other half, so "
            f"this side has no yard at all, where it needs at least "
            f"{format_feet(minimum)}. The map can't tell whether the lot was split "
            "with the city's approval or before today's rules.")


def side_count_explanation(zone_label: str, width: float, needed: int) -> str:
    """Explain the zones where the number of side yards depends on lot width."""
    ending = {0: "none.", 1: "a 5 ft yard on at least one side."}.get(
        needed, "a 5 ft yard on both sides.")
    return (f"In the {zone_label}, side yards depend on lot width: none on lots under "
            "25 ft wide, one 5 ft side yard from 25 ft up to 35 ft, and two at "
            "35 ft or more. With the 5% margin for measuring width, "
            f"this lot measures about {format_feet(width)} wide and needs {ending}")


def under_special_approval(results: list[RuleResult],
                           district: PlannedDistrict) -> list[RuleResult]:
    """The results as they stand under a planned district's approved plan.

    Lot size, frontage, width and yard rows with no rule or no check become
    "not required", since the approved site plan sets them. Other rows with no
    rule say the plan sets no lot-by-lot limit. Returns new rows and leaves
    the ones passed in alone.
    """
    out = []
    for row in results:
        plan_sets_it = (row.rule in SITE_PLAN_RULES
                        or (row.rule.startswith("yard:") and row.rule != "yard:street"))
        if plan_sets_it and row.status in (NO_RULE, NOT_CHECKED):
            row = replace(row, status=NOT_REQUIRED, explanation=(
                f"The approved site plan for {district.name} sets lot sizes and "
                "yards here, so no general rule applies."))
        elif row.status == NO_RULE:
            row = replace(row, explanation=(
                "The approved plan sets no lot-by-lot limit for this. "
                f"{district.plan_summary}"))
        out.append(row)
    return out


def corner_rear_yard_explanation(zone_label: str) -> str:
    """Explain why a corner townhouse lot's leftover yard is judged as a rear yard."""
    return (f"On a corner lot both street sides count as front yards. On a townhouse lot "
            f"at the end of a row, the {zone_label} asks that the yard left over meet its "
            "rear yard rule, so every lot line away from both streets, apart from walls "
            "shared with a neighbor, is measured here as the rear yard.")


def corner_no_rear_yard_explanation(zone_label: str) -> str:
    """Explain a corner townhouse lot where every lot line away from the streets is a shared wall."""
    return (f"{corner_rear_yard_explanation(zone_label)} Here every lot line away from "
            "both streets runs along a wall shared with a neighbor, so the map finds no "
            "yard left over to measure. A wall shared at the back of a lot is unusual "
            "enough that it may be a mapping error, so this wasn't judged.")


def corner_side_as_rear_explanation(zone_label: str) -> str:
    """Explain the side yard rows of a corner townhouse lot, whose leftover yard is judged as the rear."""
    return (f"On a corner townhouse lot in the {zone_label}, the lot lines away from both "
            "streets are judged together as the rear yard (see that row), not counted "
            "as side yards.")


def corner_wall_not_found_explanation(zone_label: str) -> str:
    """Explain a corner townhouse lot whose shared wall the map can't place on a lot line."""
    return (f"{corner_rear_yard_explanation(zone_label)} This home is attached to the next "
            "home in its row, but in the city's map no lot line runs along the wall they "
            "share: the lot lines and building outlines are a few feet apart. The map "
            "can't tell which line is the shared wall and which bounds the yard left "
            "over, so this wasn't judged.")


ROW_LENGTH_ABOUT = (
    f"The zoning rules allow at most {MAX_TOWNHOUSES_IN_ROW} townhouses in one building. "
    "City Council can allow more with a special permit, but not in the RA, RB, RM, RS, "
    f"RT, CD and CL zones, and never in a building longer than "
    f"{format_feet(MAX_TOWNHOUSE_ROW_LENGTH)}. The map counts as one building every home "
    "whose outline shares a wall with the next one along, whenever each was built, since "
    "the rule counts homes in \"a single structure\". Outlines that only meet at a corner "
    "don't count as sharing a wall. Each lot in the row counts as one home, except a condo "
    "lot, where each building outline counts as one; a row the city's map draws as one "
    "outline on one condo lot counts as one home. The row's length is the long side of "
    "the smallest rectangle around it, so a row that bends may be longer than that.")


def row_length_summary(homes: int) -> str:
    """The table's one-line result for the townhouse row rule: "11 homes; at most 8 allowed"."""
    return (f"{homes} home{'' if homes == 1 else 's'}; "
            f"at most {MAX_TOWNHOUSES_IN_ROW} allowed")


def _row_words(homes: int, length: float) -> str:
    return f"a row of {homes} attached homes about {format_feet(length)} long"


def long_row_reason(zone_label: str, homes: int, length: float, permit: bool,
                    too_long: bool) -> str:
    """The reason a townhouse fails the townhouse row rule.

    `permit` is True where the zone lets City Council allow a longer row with
    a special permit, and `too_long` when the row is longer than any special
    permit may allow.
    """
    text = (f"Stands in {_row_words(homes, length)}; the {zone_label} allows at most "
            f"{MAX_TOWNHOUSES_IN_ROW} townhouses in one building")
    if not permit:
        return f"{text}, and no special permit can allow more there."
    if too_long:
        return (f"{text}, and no special permit can allow a building longer than "
                f"{format_feet(MAX_TOWNHOUSE_ROW_LENGTH)}.")
    return (f"{text} without a special permit. It would need a special permit from "
            "City Council.")


def long_row_explanation(zone_label: str, homes: int, length: float, permit: bool,
                         too_long: bool) -> str:
    """Explain a failing townhouse row: its size, and whether a special permit could allow it.

    `permit` and `too_long` are as for `long_row_reason`.
    """
    parts = [f"This home stands in {_row_words(homes, length)}, counted by shared walls "
             "whenever each home was built."]
    if not permit:
        parts.append(f"The {zone_label} allows at most {MAX_TOWNHOUSES_IN_ROW} townhouses "
                     "in one building, and no special permit can allow more there.")
    elif too_long:
        parts.append(f"The {zone_label} allows more than {MAX_TOWNHOUSES_IN_ROW} townhouses "
                     "in one building only with a special permit from City Council, and no "
                     "special permit can allow a building longer than "
                     f"{format_feet(MAX_TOWNHOUSE_ROW_LENGTH)}.")
    else:
        parts.append(f"The {zone_label} allows more than {MAX_TOWNHOUSES_IN_ROW} townhouses "
                     "in one building only with a special permit from City Council. The map "
                     "has no record of special permits, so it can't tell whether this row "
                     "has one.")
    return " ".join(parts)


def row_set_by_plan_explanation(rules_label: str) -> str:
    """Say that a planned district's approved plan, not the townhouse rule, sets how homes are grouped."""
    return (f"The {rules_label} sets how townhouses are grouped, so this isn't judged here. "
            "Tick \"Judge by ordinary zoning instead\" to see it checked.")


def row_no_townhouses_explanation(zone_label: str) -> str:
    """Say why the townhouse row rule doesn't come into it where townhouses aren't allowed."""
    return (f"The {zone_label} doesn't allow townhouses (see the home type row), so the "
            "limit on townhouses in one building doesn't come into it.")


def _plural(label: str) -> str:
    """The plural of an outbuilding label: "garage or shed" becomes "garages or sheds"."""
    return " or ".join(word + "s" for word in label.split(" or "))


def _outbuilding_list(outbuildings: list[tuple[str, float]]) -> str:
    """Name the outbuildings found, with their floor space.

    Up to three are named one by one ("a garage or shed of about 140 sq ft");
    more are summed up by kind.
    """
    def size(area):
        return f"about {area:,.0f} sq ft"

    if len(outbuildings) <= 3:
        named = [f"{'an' if label[0] in 'aeiou' else 'a'} {label} of {size(area)}"
                 for label, area in outbuildings]
        return named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
    by_label = {}
    for label, area in outbuildings:
        by_label.setdefault(label, []).append(area)
    kinds = [f"{len(areas)} {_plural(label) if len(areas) > 1 else label}"
             for label, areas in by_label.items()]
    listed = kinds[0] if len(kinds) == 1 else f"{', '.join(kinds[:-1])} and {kinds[-1]}"
    return f"{listed}, with {size(sum(area for _, area in outbuildings))} in all"


def outbuildings_explanation(zone_label: str, outbuildings: list[tuple[str, float]],
                             allowance: float, added: float) -> str:
    """Say which garages, sheds and other outbuildings count toward floor space, and how much.

    `outbuildings` holds a (label, floor space) pair for each, `allowance`
    is the floor space in them the zoning rules leave out on this lot, and
    `added` is what the map adds to the homes' floor space.
    """
    one = len(outbuildings) == 1
    found = (f"In the {zone_label}, floor space takes in every building on the lot, garages "
             f"and sheds included. On a lot this size, up to {allowance:,.0f} sq ft in qualifying "
             f"garages and sheds is excluded. Other than homes, the map found {_outbuilding_list(outbuildings)} "
             "on this lot. ")
    measured = (f"{'Its' if one else 'Their'} floor space is estimated from "
                f"{'its outline' if one else 'their outlines'}, less a fifth for eaves, as "
                "one story unless the city's 3D data shows a building tall enough for more. ")
    if added > 0:
        return f"{found}{measured}So the map adds about {added:,.0f} sq ft to the floor space."
    return (f"{found}{measured}That is within the allowance, so none of it is added to the "
            "floor space.")
