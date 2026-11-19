"""Alexandria, VA's zoning rules for homes, written as data.

Numbers come from the Zoning Ordinance as amended through Ordinance 5614
(January 24, 2026): Article III for the residential zones, and Articles IV
and V for homes in commercial, office and waterfront zones. Distances are in feet
and areas in square feet.

Home types used throughout:
    single     a detached house with one home in it
    semi       one half of a twin house, sitting on its own lot
    two_unit   a whole two-unit house (both halves of a twin) on one lot
    townhouse  one of a row of three or more attached homes
    multi      a building with three or more homes (apartments, condos)

The ordinance's "two-unit dwelling" covers both a twin (two homes side by
side, sharing a wall) and a duplex (one home above the other). Where the
two get different street frontage, a whole two-unit house on one lot uses
the twin's: the map finds these houses as two attached outlines side by
side, which a stacked duplex would not show.
"""
from dataclasses import dataclass, field, replace


ALL_TYPES = frozenset({"single", "semi", "two_unit", "townhouse", "multi"})
HOUSE_LIKE = ("single", "semi", "two_unit", "townhouse")


@dataclass(frozen=True)
class Yard:
    """A required yard: a fixed minimum plus a share of the building height.

    The ordinance writes the height share as a "setback ratio". A ratio of
    1:2 means one foot of yard for every two feet of height, so
    per_foot_of_height is 0.5.
    """

    minimum: float
    per_foot_of_height: float = 0.0

    def required(self, height: float) -> float:
        """The yard depth needed for a building of the given height."""
        return max(self.minimum, self.per_foot_of_height * height)


@dataclass(frozen=True)
class OlderHomeAllowance:
    """A zone's own exception that allows a kind of home it otherwise bars, if old enough.

    A few zones say that a kind of home they don't normally allow is fine
    when it was there before some date. City records give only the year a
    home was built, so a home counts when that year is before `before_year`.
    A home built in that year itself can't be told apart, so it doesn't count.

    rule:        the exception in plain words, shown on the home type row.
    before:      the cutoff date as the ordinance writes it.
    unconfirmed: what else the exception asks that the map can't confirm.
    older_rules: True when the zone also lets these homes be rebuilt under
                 the limits in force when they were built, which the map
                 doesn't have.
    """

    before_year: int
    before: str
    rule: str
    unconfirmed: str = ""
    older_rules: bool = False


# The RB zone's exception for older apartment land (section 3-707(A)).
_RB_OLDER_APARTMENTS = OlderHomeAllowance(
    before_year=1978,
    before="March 28, 1978",
    rule=("The RB zone lets land that was zoned RB by February 27, 1973 be used "
          "for apartment buildings if it had apartment buildings on it before "
          "March 28, 1978."),
    unconfirmed=("The map has no record of past zoning, so it couldn't confirm "
                 "this land was zoned RB by 1973."),
)


def _older_houses(zone: str) -> dict:
    """The RC and RCX zones' exception for older houses and twin houses.

    Both zones (sections 3-807(A) and 3-907(A)) say detached and two-unit
    houses "developed prior to June 24, 1992 shall be deemed to be in
    compliance with this ordinance", and may be rebuilt under the limits
    they were built under.
    """
    allowance = OlderHomeAllowance(
        before_year=1992,
        before="June 24, 1992",
        rule=(f"The {zone} zone says detached houses and two-unit houses built before "
              "June 24, 1992 are \"deemed to be in compliance\" with the zoning "
              "rules, and lets them be rebuilt under the limits they were built under."),
        older_rules=True,
    )
    return {"single": allowance, "semi": allowance, "two_unit": allowance}


@dataclass(frozen=True)
class ZoneRules:
    """Everything we check for one zone. Dicts are keyed by home type."""

    name: str
    allowed: frozenset
    # Home types the zone allows only when built before a date, keyed by
    # home type, each an OlderHomeAllowance.
    allowed_if_built_before: dict = field(default_factory=dict)
    # Home types that need a special permit from City Council on lots within
    # 1,000 ft of the centerline of Eisenhower Avenue.
    special_permit_near_eisenhower: frozenset = frozenset()
    # Homes near Eisenhower Avenue old enough to need no special permit
    # (OCH only), as an OlderHomeAllowance.
    eisenhower_older_homes: OlderHomeAllowance | None = None
    # How messages refer to these rules, after the word "the".
    described_as: str = ""
    # Largest apartment building allowed, counted in homes. None = no cap.
    max_multi_units: int | None = None
    # Minimum lot area. For townhouses this is per home.
    lot_area: dict = field(default_factory=dict)
    corner_lot_area: dict = field(default_factory=dict)
    lot_width: dict = field(default_factory=dict)
    corner_lot_width: dict = field(default_factory=dict)
    end_lot_width: dict = field(default_factory=dict)
    frontage: dict = field(default_factory=dict)
    # Most zones give a townhouse lot the same minimum at the front lot line
    # (frontage) as at the building line (width), including the larger end
    # and corner lot numbers. False where the zone sets width only (RT).
    townhouse_frontage_matches_width: bool = True
    # Lower frontage allowed on curving streets (R-20 and R-12 only).
    curved_frontage: dict = field(default_factory=dict)
    # Lot width is measured this far back from the street.
    width_measured_at: float = 0.0
    side_yard: dict = field(default_factory=dict)
    # Whether each half of a twin house may sit on a lot of its own, with
    # the lot line running along the shared wall. Where it may not (R-20
    # through R-5), that lot line leaves the half with no side yard there.
    split_twin_lots_allowed: bool = True
    # One rear yard rule for the zone, or a dict keyed by home type.
    rear_yard: Yard | dict | None = None
    # Fixed front yard. None where the rule depends on neighboring homes.
    front_yard: float | None = None
    # Where the front yard is set by the "contextual block face" (the
    # neighboring buildings along the same street, see block_faces.py): the
    # most it can ask. The front yard must fall within the range of the
    # neighbors' front yards, but once the shallowest of them is deeper than
    # this, a home needs only this much.
    contextual_front_yard: float | None = None
    # The RM and CD zones' rule: the front wall sits at the front lot line,
    # unless most other buildings on the same side of the block stand
    # further back, and then at their average distance from it.
    front_yard_by_block_average: bool = False
    # The RB zone's rule in the historic districts: the front wall sits at the
    # front lot line, or on another line the board of architectural review approves.
    front_at_lot_line_unless_approved: bool = False
    # Home types the zone asks no front yard of at all, apart from the extra
    # setbacks along a few named streets (section 7-1006).
    no_front_yard_for: frozenset = frozenset()
    # Zones where side yards depend only on lot width (RM, historic RB).
    side_yards_by_lot_width: bool = False
    # Lots narrower than this need no side yards.
    no_side_yard_below_width: float = 0.0
    # One limit for the zone, or a dict keyed by home type.
    max_floor_area_ratio: float | dict | None = None
    # Looser floor area limit inside the historic districts, by home type.
    historic_floor_area_ratio: dict = field(default_factory=dict)
    # Shown on the floor space row's name, where the zone's limit needs explaining.
    floor_area_note: str = ""
    max_height: dict = field(default_factory=dict)
    # A higher height limit, by home type, for a home whose roof's ridge line
    # runs parallel to the street and whose roof slope is compatible with
    # neighboring buildings (RM, and houses and townhouses in CD).
    pitched_roof_height: dict = field(default_factory=dict)
    # Where the zone sends you for its height limit instead of setting one,
    # e.g. "the Old Town North Small Area Plan".
    height_set_by: str = ""
    # True where these rules set aside the height districts' rule tying a
    # building's height to its distance from the middle of the street
    # (section 6-403(A)), as some planned districts' approvals do.
    height_near_street_waived: bool = False
    # Share of the lot that must stay open (0.35 = 35%).
    min_open_space: float | None = None
    # Least open space in sq ft, however small the lot (RM only).
    min_open_space_area: float = 0.0
    # Shown on the open space row's name, where the zone's rule needs explaining.
    open_space_note: str = ""
    # Share of the land used for parking that may count as open space, and
    # the most of the required open space that parking may make up (RD only).
    parking_counted_as_open: float = 0.0
    parking_open_space_cap: float = 0.0
    # Largest share of the lot that buildings may cover.
    max_coverage: float | None = None
    # Home types the open space rule applies to. Empty means all.
    open_space_applies_to: frozenset = frozenset()

    @property
    def label(self) -> str:
        """What to call these rules in a sentence, after "the"."""
        return self.described_as or f"{self.name} zone"

    def rear_yard_for(self, home_type: str) -> Yard | None:
        """The rear yard rule for a home type."""
        if isinstance(self.rear_yard, dict):
            return self.rear_yard.get(home_type)
        return self.rear_yard

    def floor_area_ratio_for(self, home_type: str, historic: bool) -> float | None:
        """The floor area limit for a home type, as a share of lot area."""
        if historic and home_type in self.historic_floor_area_ratio:
            return self.historic_floor_area_ratio[home_type]
        if isinstance(self.max_floor_area_ratio, dict):
            return self.max_floor_area_ratio.get(home_type)
        return self.max_floor_area_ratio


def _low_density(name, area, corner_area, width, corner_width, frontage,
                 measured_at, yard, side_share, far, front, curved=None, semi=None):
    """Build rules for the five house zones (R-20 through R-2-5).

    These zones allow a detached house, a two-home building, or a building
    with up to four homes. Each building needs its own full-size lot, except
    in R-2-5 where each half of a twin house may have its own smaller lot.
    `semi` holds R-2-5's own numbers for twin houses, keyed like the tables;
    the other four zones, which pass none, keep a twin house whole on one lot.
    `front` is the most front yard the neighboring homes can ask for.
    """
    types = ("single", "semi", "two_unit", "multi")
    semi = semi or {}
    return ZoneRules(
        name=name,
        allowed=frozenset(types),
        max_multi_units=4,
        lot_area={t: area for t in types} | semi.get("area", {}),
        corner_lot_area={t: corner_area for t in types}
        | semi.get("corner_area", {}),
        lot_width={t: width for t in types} | semi.get("width", {}),
        corner_lot_width={t: corner_width for t in types}
        | semi.get("width", {}),
        frontage={t: frontage for t in types} | semi.get("frontage", {}),
        curved_frontage={t: curved for t in types} if curved else {},
        width_measured_at=measured_at,
        contextual_front_yard=front,
        side_yard={t: Yard(yard, side_share) for t in types},
        split_twin_lots_allowed=bool(semi),
        rear_yard=Yard(yard, 1.0),
        max_floor_area_ratio=far,
        max_height={t: 30 for t in types},
    )


_TOWNHOUSE_WIDTHS = {
    "lot_width": {"townhouse": 18},
    "end_lot_width": {"townhouse": 26},
    "corner_lot_width": {"townhouse": 38},
    "frontage": {"townhouse": 18},
}

ZONES = {
    "R-20": _low_density("R-20", 20000, 20000, 100, 120, 75, 40, 12, 1 / 2,
                         0.25, 40, curved=55),
    "R-12": _low_density("R-12", 12000, 12000, 80, 95, 60, 35, 10, 1 / 2,
                         0.30, 35, curved=45),
    "R-8": _low_density("R-8", 8000, 9000, 65, 80, 40, 30, 8, 1 / 2, 0.35, 30),
    "R-5": _low_density("R-5", 5000, 6500, 50, 65, 40, 20, 7, 1 / 3, 0.45, 20),
    "R-2-5": _low_density(
        "R-2-5", 5000, 6500, 50, 65, 40, 20, 7, 1 / 3, 0.45, 20,
        semi={
            "area": {"semi": 2500},
            "corner_area": {"semi": 3250},
            "width": {"semi": 25},
            # A whole twin on one lot needs 25 ft for each of its two homes.
            "frontage": {"semi": 25, "two_unit": 50},
        },
    ),
    "RA": ZoneRules(
        name="RA",
        allowed=ALL_TYPES,
        # 1,980 sq ft for each home, so a two-unit house needs twice that.
        lot_area={"single": 1980, "semi": 1980, "two_unit": 3960, "townhouse": 1980},
        lot_width={"single": 50, "semi": 25, "two_unit": 50, "multi": 50,
                   "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"single": 50, "semi": 25, "two_unit": 50, "multi": 50,
                  "townhouse": 18},
        width_measured_at=20,
        contextual_front_yard=20,
        side_yard={
            "single": Yard(7, 1 / 3),
            "semi": Yard(7, 1 / 3),
            "two_unit": Yard(7, 1 / 3),
            "townhouse": Yard(8, 1 / 3),
            "multi": Yard(16, 1 / 2),
        },
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=0.75,
        max_height={"single": 30, "semi": 30, "two_unit": 30, "townhouse": 45,
                    "multi": 45},
        min_open_space=0.35,
    ),
    "RB": ZoneRules(
        name="RB",
        allowed=frozenset(HOUSE_LIKE),
        allowed_if_built_before={"multi": _RB_OLDER_APARTMENTS},
        lot_area={"single": 1980, "semi": 1980, "two_unit": 3960, "townhouse": 1980},
        lot_width={"single": 50, "semi": 25, "two_unit": 50, "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"single": 50, "semi": 25, "two_unit": 50, "townhouse": 18},
        width_measured_at=20,
        contextual_front_yard=20,
        side_yard={
            "single": Yard(8, 1 / 3),
            "semi": Yard(8, 1 / 3),
            "two_unit": Yard(8, 1 / 3),
            "townhouse": Yard(8, 1 / 3),
            "multi": Yard(16, 1 / 2),
        },
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=0.75,
        max_height={"single": 30, "semi": 30, "two_unit": 30, "townhouse": 45,
                    "multi": 45},
        min_open_space=0.35,
    ),
    "RCX": ZoneRules(
        name="RCX",
        allowed=frozenset({"townhouse", "multi"}),
        allowed_if_built_before=_older_houses("RCX"),
        no_front_yard_for=ALL_TYPES,
        lot_area={"townhouse": 1600},
        lot_width={"multi": 50, "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"multi": 50, "townhouse": 18},
        side_yard={"townhouse": Yard(8, 1 / 3), "multi": Yard(16, 1 / 3)},
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=1.25,
        max_height={"townhouse": 50, "multi": 50},
        min_open_space=0.35,
    ),
    "RC": ZoneRules(
        name="RC",
        allowed=frozenset({"townhouse", "multi"}),
        allowed_if_built_before=_older_houses("RC"),
        no_front_yard_for=ALL_TYPES,
        lot_area={"townhouse": 1600},
        lot_width={"multi": 50, "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"multi": 50, "townhouse": 18},
        side_yard={"townhouse": Yard(8, 1 / 3), "multi": Yard(16, 1 / 3)},
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=1.25,
        max_height={"townhouse": 150, "multi": 150},
        min_open_space=0.35,
    ),
    "RD": ZoneRules(
        name="RD",
        allowed=frozenset({"multi"}),
        no_front_yard_for=ALL_TYPES,
        lot_area={"multi": 43560},
        frontage={"multi": 100},
        side_yard={"multi": Yard(16, 1 / 2)},
        rear_yard=Yard(16, 1 / 2),
        max_height={"multi": 150},
        min_open_space=0.40,
        parking_counted_as_open=0.5,
        parking_open_space_cap=0.9,
        open_space_note=(
            "The RD zone requires 40% of each lot to be open, usable space. Half of "
            "the land used for parking may count toward it, as long as parking makes "
            "up no more than 90% of the open space required. The map counts parking "
            "that way."),
    ),
    "RM": ZoneRules(
        name="RM",
        allowed=frozenset(HOUSE_LIKE),
        # 1,452 sq ft and 25 ft of frontage for each home, so a two-unit
        # house needs twice both.
        lot_area={"single": 1452, "semi": 1452, "two_unit": 2904, "townhouse": 1452},
        lot_width={"single": 25, "semi": 25, "two_unit": 25, "townhouse": 18},
        frontage={"single": 25, "semi": 25, "two_unit": 50, "townhouse": 18},
        front_yard_by_block_average=True,
        side_yards_by_lot_width=True,
        rear_yard=Yard(16, 1 / 2),
        max_floor_area_ratio=1.50,
        max_height={kind: 35 for kind in HOUSE_LIKE},
        pitched_roof_height={kind: 45 for kind in HOUSE_LIKE},
        # The zone also lets a lot keep the open space it had on June 24,
        # 1992 if that was less. That says nothing about building on an
        # empty lot today, so only the note mentions it.
        min_open_space=0.35,
        min_open_space_area=300,
        open_space_note=(
            "The RM zone requires each home lot to keep open, usable space: 35% "
            "of the lot, and never less than 300 sq ft. A lot may instead keep "
            "the open space it had on June 24, 1992, if that was less, and a lot "
            "that already fell short then may count strips narrower than 8 ft, so "
            "an older home may be fine as it stands. The map judges whether these "
            "buildings could be built new."),
    ),
    "RS": ZoneRules(
        name="RS",
        allowed=frozenset({"townhouse"}),
        lot_area={"townhouse": 2904},
        width_measured_at=20,
        side_yard={"townhouse": Yard(8, 1 / 3)},
        rear_yard=Yard(16, 1.0),
        front_yard=20,
        max_floor_area_ratio=0.75,
        max_height={"townhouse": 35},
        min_open_space=0.35,
        **_TOWNHOUSE_WIDTHS,
    ),
    "RT": ZoneRules(
        name="RT",
        allowed=frozenset({"townhouse"}),
        lot_area={"townhouse": 2500},
        lot_width={"townhouse": 22},
        end_lot_width={"townhouse": 45},
        corner_lot_width={"townhouse": 45},
        # Section 3-1305(C) sets lot widths only, with no frontage rule.
        frontage={},
        townhouse_frontage_matches_width=False,
        width_measured_at=6,
        side_yard={"townhouse": Yard(12, 1 / 2)},
        rear_yard=Yard(12, 1.0),
        front_yard=4,
        max_floor_area_ratio=0.50,
        max_height={"townhouse": 35},
        max_coverage=0.30,
    ),
}

def _commercial(name, townhouse_area, far, height, historic_far=False,
                **overrides):
    """Build the rules for homes in a commercial or office zone.

    These zones (Article IV of the ordinance) share one pattern for homes:
    house-sized lots, townhouse lots, and yards much like the RB zone.
    """
    settings = {
        "name": name,
        "allowed": ALL_TYPES,
        # A two-unit house needs 2,500 sq ft and 25 ft of frontage for each home.
        "lot_area": {"single": 5000, "semi": 2500, "two_unit": 5000,
                     "townhouse": townhouse_area},
        "lot_width": {"single": 50, "semi": 25, "two_unit": 50, "multi": 50,
                      "townhouse": 18},
        "end_lot_width": {"townhouse": 26},
        "corner_lot_width": {"townhouse": 38},
        "frontage": {"single": 50, "semi": 25, "two_unit": 50, "multi": 50,
                     "townhouse": 18},
        "width_measured_at": 20,
        "contextual_front_yard": 20,
        "side_yard": {
            "single": Yard(8, 1 / 3),
            "semi": Yard(8, 1 / 3),
            "two_unit": Yard(8, 1 / 3),
            "townhouse": Yard(8, 1 / 3),
            "multi": Yard(16, 1 / 2),
        },
        "rear_yard": Yard(8, 1.0),
        "no_side_yard_below_width": 25,
        "max_floor_area_ratio": far,
        "historic_floor_area_ratio":
            {kind: 1.50 for kind in HOUSE_LIKE} if historic_far else {},
        "max_height": {kind: height for kind in ALL_TYPES} if height else {},
        "min_open_space": 0.35,
    }
    return ZoneRules(**(settings | overrides))


# Office zones set no lot size for townhouses, only a cap of one home per
# 800 sq ft of land, and no lot width for townhouses or apartments.
_OFFICE = {
    "lot_width": {"single": 50, "semi": 25, "two_unit": 50},
    "end_lot_width": {},
    "corner_lot_width": {},
    "frontage": {"single": 50, "semi": 25, "two_unit": 50},
}

# OCH homes near Eisenhower Avenue that were there by November 9, 1999 need
# no special permit (section 4-1107). Homes built in 1999 count too, since
# most of that year came before the date and the note only says "may".
_OCH_OLDER_HOMES = OlderHomeAllowance(
    before_year=2000,
    before="November 9, 1999",
    rule=("The OCH zone lets homes here that existed on November 9, 1999, or had a "
          "building permit or site plan filed by then, stay without a special permit."),
)

ZONES |= {
    "CL": _commercial("CL", 1980, 0.75, 35, historic_far=True),
    "CC": _commercial("CC", 1980, 0.75, 35),
    "CSL": _commercial("CSL", 1980, 0.75, 50, historic_far=True),
    "CG": _commercial("CG", 1980, 0.75, 50),
    "OC": _commercial("OC", 1600, 1.25, 50, historic_far=True),
    # Height in CDX comes from a neighborhood plan (section 4-606(C)), which
    # the map doesn't have; only the height district map's limit is checked.
    "CDX": _commercial("CDX", 1245, 1.25, None, historic_far=True,
                       end_lot_width={}, corner_lot_width={},
                       height_set_by="the Old Town North Small Area Plan"),
    "OCM(50)": _commercial("OCM(50)", 800, 1.50, 50, **_OFFICE),
    # Both OCM(100) and OCH allow homes near Eisenhower Avenue only with a
    # special permit (sections 4-1003(AA) and 4-1103(W)).
    "OCM(100)": _commercial("OCM(100)", 800, 1.50, 100,
                            special_permit_near_eisenhower=ALL_TYPES, **_OFFICE),
    # Floor space near a Metro station is looser; see office_high_rules().
    "OCH": _commercial("OCH", 800, 1.25, 100, historic_far=True,
                       special_permit_near_eisenhower=ALL_TYPES,
                       eisenhower_older_homes=_OCH_OLDER_HOMES, **_OFFICE),
    "CD": ZoneRules(
        name="CD",
        allowed=ALL_TYPES,
        # Section 4-505(B) asks 1,452 sq ft of each house, two-unit house and
        # townhouse ("dwelling"), not of each home in it as the RM zone does.
        lot_area={kind: 1452 for kind in HOUSE_LIKE},
        lot_width={"single": 25, "semi": 25, "two_unit": 25, "townhouse": 18,
                   "multi": 50},
        # A twin needs 25 ft of frontage for each of its homes.
        frontage={"single": 25, "semi": 25, "two_unit": 50, "townhouse": 18,
                  "multi": 50},
        front_yard_by_block_average=True,
        side_yard={kind: Yard(5) for kind in HOUSE_LIKE} | {"multi": Yard(25, 1 / 3)},
        rear_yard={kind: Yard(16, 1 / 2) for kind in HOUSE_LIKE}
        | {"multi": Yard(25, 1.0)},
        no_side_yard_below_width=25,
        max_floor_area_ratio={kind: 1.50 for kind in HOUSE_LIKE} | {"multi": 1.25},
        max_height={kind: 35 for kind in HOUSE_LIKE} | {"multi": 50},
        pitched_roof_height={kind: 45 for kind in HOUSE_LIKE},
        min_open_space=0.35,
        open_space_applies_to=frozenset({"multi"}),
    ),
    # Waterfront mixed-use zone (sections 5-505, 5-506 and 5-512). Its height
    # is the height district map's (section 5-507).
    "W-1": ZoneRules(
        name="W-1",
        allowed=ALL_TYPES,
        # Section 5-506(A) asks no front yard of any building, but 5-512
        # gives houses and townhouses one set by the neighboring homes.
        no_front_yard_for=frozenset({"multi"}),
        contextual_front_yard=20,
        lot_area={"single": 5000, "semi": 2500, "two_unit": 5000, "townhouse": 1452},
        lot_width={"single": 50, "semi": 25, "two_unit": 50, "townhouse": 18,
                   "multi": 50},
        end_lot_width={"townhouse": 26},
        frontage={"single": 50, "semi": 25, "two_unit": 50, "townhouse": 18,
                  "multi": 50},
        side_yard={"single": Yard(8, 1 / 3), "semi": Yard(8, 1 / 3),
                   "two_unit": Yard(8, 1 / 3), "townhouse": Yard(8),
                   "multi": Yard(16, 1 / 2)},
        rear_yard={kind: Yard(8, 1.0) for kind in HOUSE_LIKE}
        | {"multi": Yard(16, 1 / 2)},
        no_side_yard_below_width=25,
        max_floor_area_ratio=1.0,
        historic_floor_area_ratio={kind: 1.50 for kind in HOUSE_LIKE},
        min_open_space=0.35,
        height_set_by="the height district map",
    ),
}

# Houses and two-unit houses in the mixed-use zones (sections 5-111, 5-211,
# 5-311 and 5-404(B)): lot size, frontage, and side and rear yards like a
# commercial zone's, with a rear yard that grows with height.
_MIXED_USE_HOUSES = {
    "lot_area": {"single": 5000, "semi": 2500, "two_unit": 5000},
    "lot_width": {"single": 50, "semi": 25, "two_unit": 50},
    "frontage": {"single": 50, "semi": 25, "two_unit": 50},
    "width_measured_at": 20,
    "contextual_front_yard": 20,
    # The front yard rule (sections 5-111, 5-211, 5-311 and 5-404) is for
    # houses and townhouses only.
    "no_front_yard_for": frozenset({"multi"}),
    "side_yard": {kind: Yard(8, 1 / 3) for kind in ("single", "semi", "two_unit")},
    "rear_yard": {kind: Yard(8, 1.0) for kind in ("single", "semi", "two_unit")},
    "no_side_yard_below_width": 25,
}

# The mixed-use zones. Bigger projects there need a special permit; these
# are the limits that apply without one. Townhouses get the house yard
# rules but no lot size or frontage rule. Apartments get only floor space
# and open space. Height comes from a small area plan (section 5-106 and its
# matches), which the map doesn't have; only the height district map's
# limit is checked.
for _name in ("CRMU/L", "CRMU/M", "CRMU/H"):
    ZONES[_name] = ZoneRules(
        name=_name.replace("/", "-"),
        allowed=ALL_TYPES,
        max_floor_area_ratio=1.0,
        historic_floor_area_ratio={kind: 1.50 for kind in HOUSE_LIKE},
        min_open_space=0.35,
        height_set_by="the neighborhood's small area plan",
        **(_MIXED_USE_HOUSES | {
            "side_yard": {kind: Yard(8, 1 / 3) for kind in HOUSE_LIKE},
            "rear_yard": {kind: Yard(8, 1.0) for kind in HOUSE_LIKE},
        }),
    )

ZONES |= {
    # Without a special permit CRMU-X allows only houses and townhouses.
    "CRMU/X": ZoneRules(
        name="CRMU-X",
        allowed=frozenset(HOUSE_LIKE),
        max_floor_area_ratio=1.50,
        height_set_by="the Old Town North Small Area Plan",
        **(_MIXED_USE_HOUSES | {
            "lot_area": _MIXED_USE_HOUSES["lot_area"] | {"townhouse": 1452},
            "lot_width": _MIXED_USE_HOUSES["lot_width"] | {"townhouse": 18},
            "frontage": _MIXED_USE_HOUSES["frontage"] | {"townhouse": 18},
            "side_yard": _MIXED_USE_HOUSES["side_yard"]
            | {"townhouse": Yard(8, 1 / 3)},
            "rear_yard": _MIXED_USE_HOUSES["rear_yard"]
            | {"townhouse": Yard(16, 1 / 2)},
        }),
    ),
    # King Street retail zone (section 6-700). Homes are allowed only as
    # apartments above or behind the shops, with no lot or yard rules. These
    # are the limits west of South Peyton and Harvard Streets; see
    # king_street_retail_rules() for the rest of the zone.
    "KR": ZoneRules(
        name="KR", allowed=frozenset({"multi"}), no_front_yard_for=ALL_TYPES,
        max_floor_area_ratio=2.0,
        floor_area_note=(
            "The KR zone sets one floor space limit for homes and another for "
            "shops and offices. The city's figure covers the whole building, "
            "shops below included, so the map holds the building to the looser "
            "of the two.")),
    # Industrial and utility zones do not allow homes at all.
    "I": ZoneRules(name="I (industrial)", allowed=frozenset()),
    "UT": ZoneRules(name="UT (utility)", allowed=frozenset()),
}

def king_street_retail_rules(east_of_peyton_and_harvard: bool, residential_only=False,
                            near_station=True) -> ZoneRules:
    """The KR zone's rules for a lot on one side or the other of its dividing line.

    The zone sets separate floor area limits for homes and for shops and
    offices (section 6-705(C)). The city's floor space figure covers the whole
    building, shops below included, so it can't be split between the two.
    Residential-only records use the residential limit. Mixed or ambiguous
    records use the looser of the two limits:

    - East of South Peyton Street (south side of King Street) and Harvard
      Street (north side): 1.25 for homes and 1.5 for shops, so 1.5. Height
      there is capped at 50 ft (section 6-705(D)(1)).
    - West of them: 1.25 for homes (2.0 near a Metro station) and 2.0 for
      shops, so 2.0. Height follows the King Street Metro Station height
      district (section 6-705(D)(2)), which the height district map gives.
    """
    rules = ZONES["KR"]
    if not east_of_peyton_and_harvard:
        rules = replace(rules, height_set_by="the King Street Metro Station height district")
        if residential_only:
            return replace(rules, max_floor_area_ratio=2.0 if near_station else 1.25,
                           floor_area_note="The residential limit increases within 1,000 ft of Metro.")
        return rules
    if residential_only:
        return replace(rules, max_floor_area_ratio=1.25, max_height={"multi": 50},
                       floor_area_note="City records identify residential use throughout this lot.")
    return replace(rules, max_floor_area_ratio=1.5, max_height={"multi": 50})


def office_high_rules(near_metro: bool) -> ZoneRules:
    """The OCH zone's rules, with the floor space limit for homes set by where the lot is.

    Section 4-1105(C)(2) gives homes a floor area ratio of 1.25, or 2.0 within
    1,000 ft of a Metro station, or 1.50 for houses, twin houses and
    townhouses in the Old and Historic Alexandria and Parker-Gray districts.
    The ordinance doesn't say which wins for a house-like home both near a
    station and in a historic district, so it gets the looser 2.0.
    """
    rules = ZONES["OCH"]
    if near_metro:
        return replace(rules, max_floor_area_ratio=2.0, historic_floor_area_ratio={})
    return rules


@dataclass(frozen=True)
class PlannedDistrict:
    """A planned district ("coordinated development district", or CDD).

    Each was built under a special permit with its own plan. The ordinance
    (section 5-602, Table 1) gives two sets of limits for every district:

    - With the special permit: district-wide caps on homes or floor space,
      a maximum height, and the kinds of use allowed. Lot sizes and yards
      are not set by rule; the approved site plan drawings fix them.
    - Without it: an ordinary zone's rules, sometimes with a changed floor
      area or height limit. These are the "fallback" fields.
    """

    name: str
    fallback_zone: str | None
    fallback_floor_area_ratio: float | None = None
    fallback_height: float | None = None
    # Home types the fallback allows, where narrower than the zone's own.
    fallback_allowed: frozenset | None = None
    plan_height: float | None = None
    plan_allowed: frozenset = ALL_TYPES
    # Cap on homes across the whole district, if the ordinance sets one.
    home_cap: int | None = None
    homes_per_acre_cap: float | None = None
    # True where the approval sets aside the rule tying a building's height
    # to its distance from the middle of the street (section 6-403(A)).
    plan_waives_height_near_street: bool = False
    # Plain-language summary of what the approval allows.
    plan_summary: str = ""


PLANNED_DISTRICTS = {
    # The fallback floor area ratio is 1.25 within 1,000 ft of the King
    # Street Metro kiosk and 1.0 elsewhere; see duke_street_floor_area().
    "CDD#1": PlannedDistrict(
        "Duke Street / Carlyle", "OC", 1.25, 77, plan_height=200,
        plan_summary="The approval allows a mix of uses including homes, "
        "with buildings up to 200 ft."),
    "CDD#2": PlannedDistrict(
        "Eisenhower Avenue Metro", "OC", 1.25, 100,
        plan_allowed=frozenset({"multi"}),
        plan_waives_height_near_street=True,
        plan_summary="The approval allows apartment buildings, with no lot "
        "size or yard rules; heights are set block by block in the "
        "neighborhood plan."),
    "CDD#3": PlannedDistrict(
        "Cameron Center", "OC", 1.50, 77, plan_height=225,
        plan_summary="The approval allows offices, shops and homes, with "
        "mostly residential buildings up to 225 ft."),
    "CDD#4": PlannedDistrict(
        "Winkler Tract", "RA", plan_height=150,
        plan_summary="The approval allows homes among other uses, with "
        "buildings up to 150 ft."),
    "CDD#5": PlannedDistrict(
        "Stone Tract", "RA", plan_height=150, homes_per_acre_cap=54.45,
        plan_summary="The approval allows up to 54.45 homes per acre "
        "across the district, with buildings up to 150 ft."),
    # RB along Reed Avenue, RC along Commonwealth Avenue, OC on the rest;
    # see route_1_properties_fallback().
    "CDD#7": PlannedDistrict(
        "Route 1 Properties", "OC", plan_height=45,
        plan_summary="The approval allows homes among other uses, with "
        "buildings up to 45 ft."),
    "CDD#8": PlannedDistrict(
        "Trade Center", "CG",
        plan_summary="The approval allows a mix of shops and homes with "
        "limited offices; the ordinance sets no district-wide height or home "
        "count."),
    "CDD#9": PlannedDistrict(
        "Cameron Station", "R-8", plan_height=120, home_cap=2510,
        plan_summary="The approval allows up to 2,510 homes on 97 acres. "
        "Heights run from 45 ft at the edges to 120 ft for a few buildings "
        "on the south side; this map only tests the 120 ft ceiling."),
    # Potomac Yard's fallback depends on where in the district the lot is;
    # see potomac_yard_zone(). The ordinance also lets the "Piggyback Yard"
    # and Slaters Lane parts of the yard use CRMU-L rules, but those areas
    # are drawn only on a 1995 rezoning plat (REZ #95-0004) that isn't in
    # the map's data, so they are judged like the rest of the yard.
    "CDD#10": PlannedDistrict(
        "Potomac Yard / Potomac Greens", None, home_cap=2800,
        plan_summary="The approval allows up to 2,800 homes, mostly "
        "residential with offices, shops and parks. Heights follow a map "
        "in the neighborhood plan, which is not checked here."),
    "CDD#11": PlannedDistrict(
        "South Carlyle", "OCM(100)", 1.0, 100,
        plan_summary="The approval allows offices, homes and shops, with "
        "floor space and height set block by block in the neighborhood "
        "plan."),
    "CDD#13": PlannedDistrict(
        "Triangle Sites", "CL", plan_height=45,
        fallback_allowed=frozenset({"multi"}),
        plan_allowed=frozenset({"multi"}),
        plan_summary="The approval allows apartments over shops, up to "
        "45 ft; houses and townhouses are not allowed."),
    # OCM(50) on most of the site, CRMU-H on one acre at First and Fayette
    # Streets; see braddock_gateway_fallback().
    "CDD#15": PlannedDistrict(
        "Braddock Gateway", "OCM(50)", 1.50, 50,
        plan_summary="Floor space, height and home counts are set building "
        "by building in the district's approved concept plan."),
    "CDD#16": PlannedDistrict(
        "James Bland", "RB",
        plan_summary="Floor space, height and home counts are set in the "
        "district's approved concept plan, which allows townhouses and "
        "apartments."),
    # CG or industrial depending on the block; CG is the looser of the two.
    # The parcel layer files Cameron Park (district 17a, which allows
    # townhouses) under this label too, so every home type is accepted.
    "CDD#17": PlannedDistrict(
        "Landmark Gateway / Cameron Park", "CG",
        plan_summary="Floor space, height and home counts are set in the "
        "district's approved concept plan, which allows apartments, shops "
        "and, in the Cameron Park part, townhouses."),
    "CDD#20": PlannedDistrict(
        "Harris Teeter of Old Town North", "CD",
        plan_summary="Floor space, height and home counts are set in the "
        "district's approved concept plan, which allows townhouses, "
        "apartments and shops."),
}

# Potomac Yard: rough stand-ins for the boundaries named in the ordinance.
ROUTE_1_STRIP_DEPTH = 250.0
ROUTE_1_HALF_WIDTH = 60.0
METRO_TRACKS_LONGITUDE = -77.0472
MONROE_BRIDGE_LATITUDE = 38.8222


def potomac_yard_zone(longitude, latitude, feet_east_of_route_1) -> str:
    """Pick the fallback zone for a lot in the Potomac Yard district.

    The ordinance gives three: RB south of the Monroe Avenue bridge and
    east of the Metro tracks, CSL for the first 250 feet east of Route 1,
    and industrial everywhere else. The bridge and tracks are approximated
    here by a line of latitude and a line of longitude.
    """
    if longitude > METRO_TRACKS_LONGITUDE and latitude < MONROE_BRIDGE_LATITUDE:
        return "RB"
    if (feet_east_of_route_1 is not None
            and 0 <= feet_east_of_route_1 <= ROUTE_1_STRIP_DEPTH + ROUTE_1_HALF_WIDTH):
        return "CSL"
    return "I"


def duke_street_floor_area(near_king_street_metro: bool) -> dict:
    """District 1's fallback floor area ratio, by distance to the King Street Metro."""
    return {"max_floor_area_ratio": 1.25 if near_king_street_metro else 1.0}


# How deep the RC strip along Commonwealth Avenue runs in district 7, measured
# here from the street's centerline, so half a typical street is added.
COMMONWEALTH_STRIP_DEPTH = 100.0 + 30.0


def route_1_properties_fallback(on_reed_avenue: bool,
                                feet_from_commonwealth: float | None) -> tuple:
    """District 7's fallback zone and changes to it, from where the lot sits.

    RB zone rules apply along Reed Avenue, RC rules capped at 45 ft along
    Commonwealth Avenue to a depth of 100 feet, and OC rules on the rest.
    """
    if on_reed_avenue:
        return "RB", {}
    if (feet_from_commonwealth is not None
            and feet_from_commonwealth <= COMMONWEALTH_STRIP_DEPTH):
        return "RC", {"max_height": {kind: 45 for kind in ALL_TYPES}}
    return "OC", {}


# Approximate the one-acre corner from the street intersection; the boundary plat is unavailable.
FIRST_AND_FAYETTE_RADIUS = 250.0


def braddock_gateway_fallback(feet_from_first_and_fayette: float | None) -> tuple:
    """District 15's fallback zone and changes, from distance to First and Fayette.

    CRMU-H rules apply to the one-acre part of the site at First and Fayette
    Streets, with a floor area ratio of 1.25 and a height of 77 ft. OCM(50)
    applies to the rest.
    """
    if (feet_from_first_and_fayette is not None
            and feet_from_first_and_fayette <= FIRST_AND_FAYETTE_RADIUS):
        return "CRMU/H", {"max_floor_area_ratio": 1.25,
                          "max_height": {kind: 77 for kind in ALL_TYPES}}
    return None, {}


def planned_district_rules(label, in_historic_district=False, zone=None, changes=None):
    """Look up both rule sets for a lot in a planned district.

    Returns (district, plan rules, fallback rules), or None for a district
    not in the table. Plan rules are what the district's special approval
    allows. Fallback rules are the ordinary zone that applies without it;
    zone overrides the table's fallback where that depends on location, and
    changes (field name to value) override the table's changes to it.
    """
    key = label.strip().upper() if isinstance(label, str) else None
    district = PLANNED_DISTRICTS.get(key)
    if district is None:
        return None
    plan = ZoneRules(
        name=f"{district.name} approved plan",
        described_as=f"approved plan for {district.name}",
        allowed=district.plan_allowed,
        max_height={kind: district.plan_height for kind in ALL_TYPES}
        if district.plan_height else {},
        height_near_street_waived=district.plan_waives_height_near_street,
    )
    from_table = {}
    if zone is None or zone == district.fallback_zone:
        if district.fallback_floor_area_ratio:
            from_table["max_floor_area_ratio"] = district.fallback_floor_area_ratio
        if district.fallback_height:
            from_table["max_height"] = {
                kind: district.fallback_height for kind in ALL_TYPES}
            from_table["pitched_roof_height"] = {}
    zone = zone or district.fallback_zone
    if district.fallback_allowed is not None:
        from_table["allowed"] = district.fallback_allowed
        from_table["described_as"] = f"{zone} zone rules for {district.name}"

    fallback = rules_for(zone, in_historic_district)
    changes = from_table | (changes or {})
    return district, plan, replace(fallback, **changes) if changes else fallback


# Inside the two historic districts the RB zone swaps in looser rules.
RB_HISTORIC = ZoneRules(
    name="RB",
    allowed=ZONES["RB"].allowed,
    allowed_if_built_before=ZONES["RB"].allowed_if_built_before,
    lot_area=ZONES["RB"].lot_area,
    lot_width=ZONES["RB"].lot_width,
    end_lot_width=ZONES["RB"].end_lot_width,
    corner_lot_width=ZONES["RB"].corner_lot_width,
    frontage=ZONES["RB"].frontage,
    width_measured_at=0,
    front_at_lot_line_unless_approved=True,
    side_yards_by_lot_width=True,
    rear_yard=Yard(8, 1.0),
    max_floor_area_ratio=1.50,
    max_height={kind: 45 for kind in ALL_TYPES},
    min_open_space=0.35,
)

@dataclass(frozen=True)
class OlderLotRule:
    """The rule that lets an older lot too small for today's minimums hold a house.

    Section 12-1000 says any lot recorded before December 16, 2023 in the
    listed zones that "exceeds the maximum density permitted or has less lot
    area, width, or frontage than the minimum required" may still be built on
    with a detached house, a two-unit house or a townhouse. The home must meet
    the zone's other bulk and open space rules (yards, open space), but
    "regardless of the maximum height and floor area ratio otherwise
    established", its height is capped at 35 ft and its floor area ratio at
    1.50. That cap can be looser or stricter than the zone's own.

    The section's title also names CRMU-M, but its text leaves CRMU-M out,
    and the text governs. So CRMU-M is not in `zones`.
    """

    zones: frozenset
    recorded_before: str
    floor_area_ratio: float
    height: float


OLDER_LOTS = OlderLotRule(
    zones=frozenset({"RA", "RB", "RM", "CL", "CSL", "CD", "CDX", "OC", "OCM(50)",
                     "OCM(100)", "OCH", "CRMU-L", "CRMU-H", "CRMU-X"}),
    recorded_before="December 16, 2023",
    floor_area_ratio=1.50,
    height=35.0,
)


@dataclass(frozen=True)
class HeightMapLimit:
    """What one area of the city's height district maps allows.

    Section 6-402 ("Operation of height districts") says every building must
    stay within both its zone's height limit and the limit on the height
    district map, and "the lowest applicable height limitation shall
    prevail."

    district:      the height district's name, after "the".
    height:        the map's limit in feet, or None where it adds none ("By Zone").
    retail_height: a higher limit for a building with shops on its ground floor.
    permit_height: the most a special permit from City Council could allow.
    along_street:  a street, as the street layer names it, where a lower
                   limit applies to lots facing it; `along_name` is what to
                   call it and `along_height` is that lower limit.
    note:          a part of the map's rule that can't be judged lot by lot.
    """

    district: str = ""
    height: float | None = None
    retail_height: float | None = None
    permit_height: float | None = None
    along_street: str | None = None
    along_name: str = ""
    along_height: float | None = None
    note: str = ""


# The six height districts named in section 6-401, by the code the city's
# height district layer gives them.
HEIGHT_DISTRICT_NAMES = {
    "HD1": "Old and Historic Alexandria height district",
    "HD2": "Parker-Gray height district",
    "HD3": "Potomac River Vicinity height district",
    "HD4": "Old Town North height district",
    "HD5": "King Street Metro Station height district",
    "HD6": "height district for the rest of the city",
}

# The limit each area of the height district maps sets, keyed by the text
# the city's height district layer gives it. Written out here once, with
# where each comes from, rather than read from that text as the map runs.
HEIGHT_MAP_LIMITS = {
    "By Zone": HeightMapLimit(),
    "65'": HeightMapLimit(height=65),
    "30'": HeightMapLimit(height=30),
    "45'": HeightMapLimit(height=45),
    "50'": HeightMapLimit(height=50),
    "66'": HeightMapLimit(height=66),
    "77'": HeightMapLimit(height=77),
    "100'": HeightMapLimit(height=100),
    # Section 6-404(A): 30 ft, or up to 50 ft "subject to the issuance of a
    # special use permit" and a certificate of appropriateness.
    "30'/50'": HeightMapLimit(height=30, permit_height=50),
    # Section 6-405: 77 ft, "increased by up to five feet in those buildings
    # in which at least 30 feet of depth facing public streets is designed to
    # accommodate predominantly retail uses." No permit is needed. The city's
    # building records mark buildings with ground floor shops, which the
    # map uses to decide.
    "77', 82' if 60% of first floor used for retail": HeightMapLimit(
        height=77, retail_height=82),
    # The Old Town North Small Area Plan's height map pairs a 77 ft maximum
    # with a 50 ft average. The average covers a whole block or development,
    # so only the maximum is checked.
    "77' Max. 50' Avg.": HeightMapLimit(
        height=77,
        note=("This part of the height district map also caps the average height "
              "at 50 ft. That average is taken over a whole block or development, "
              "so the map can't judge it lot by lot and checks only the 77 ft "
              "maximum.")),
    # The Old Town North Small Area Plan's height map gives 50 ft "along N
    # Royal" and 77 ft behind it. The plan's map couldn't be read to find how
    # deep the 50 ft strip runs, so a lot with any street edge on North Royal
    # Street gets 50 ft and every other lot in the area 77 ft.
    "77' (50' along N. Royal)": HeightMapLimit(
        height=77, along_street="ROYAL", along_name="North Royal Street",
        along_height=50),
}


def height_map_limit(district: str, text: str) -> HeightMapLimit:
    """The rule for one area of the height district maps, from its district code and text.

    Raises ValueError for text not in `HEIGHT_MAP_LIMITS`, so a change to the
    city's layer is noticed rather than skipped.
    """
    if text not in HEIGHT_MAP_LIMITS:
        raise ValueError(f"No rule written for height district map text {text!r}")
    return replace(HEIGHT_MAP_LIMITS[text],
                   district=HEIGHT_DISTRICT_NAMES.get(district, "height district map"))


HOME_TYPE_NAMES = {
    "single": "detached house",
    "semi": "twin house (one half)",
    "two_unit": "two-unit house (both homes on one lot)",
    "townhouse": "townhouse",
    "multi": "apartment or condo building",
}


def normalize_zone(label) -> str | None:
    """Turn the parcel layer's zone label into a key of ZONES.

    The parcel layer writes "R 8" and "R 2-5" where the ordinance writes
    "R-8" and "R-2-5". Lots split between two zones return None.
    """
    if not isinstance(label, str):
        return None
    zone = label.strip().upper().replace(" ", "-")
    return zone if zone in ZONES else None


def rules_for(zone: str, in_historic_district: bool) -> ZoneRules:
    """Pick the rule set for a zone, honoring the historic district swap."""
    if zone == "RB" and in_historic_district:
        return RB_HISTORIC
    return ZONES[zone]
