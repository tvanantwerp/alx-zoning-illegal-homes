"""Alexandria, VA's zoning rules for homes, written as data.

Numbers come from the Zoning Ordinance as amended through Ordinance 5614
(January 24, 2026): Article III for the residential zones, and Articles IV
and V for homes in commercial, office and waterfront zones. Distances are in feet
and areas in square feet.

Home types used throughout:
    single     a detached house with one home in it
    semi       one half of a twin house, sitting on its own lot
    townhouse  one of a row of three or more attached homes
    multi      a building with three or more homes (apartments, condos)
"""
from dataclasses import dataclass, field, replace


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
class ZoneRules:
    """Everything we check for one zone. Dicts are keyed by home type."""

    name: str
    allowed: frozenset
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
    # Lower frontage allowed on curving streets (R-20 and R-12 only).
    curved_frontage: dict = field(default_factory=dict)
    # Lot width is measured this far back from the street.
    width_measured_at: float = 0.0
    side_yard: dict = field(default_factory=dict)
    # One rear yard rule for the zone, or a dict keyed by home type.
    rear_yard: Yard | dict | None = None
    # Fixed front yard. None where the rule depends on neighboring homes.
    front_yard: float | None = None
    # False in zones that ask for no front yard at all, apart from the extra
    # setbacks along a few named streets (section 7-1006).
    front_yard_required: bool = True
    # Zones where side yards depend only on lot width (RM, historic RB).
    side_yards_by_lot_width: bool = False
    # Lots narrower than this need no side yards.
    no_side_yard_below_width: float = 0.0
    # One limit for the zone, or a dict keyed by home type.
    max_floor_area_ratio: float | dict | None = None
    # Looser floor area limit inside the historic districts, by home type.
    historic_floor_area_ratio: dict = field(default_factory=dict)
    max_height: dict = field(default_factory=dict)
    # Share of the lot that must stay open (0.35 = 35%).
    min_open_space: float | None = None
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
                 measured_at, yard, side_share, far, curved=None, semi=None):
    """Build rules for the five house zones (R-20 through R-2-5).

    These zones allow a detached house, a two-home building, or a building
    with up to four homes. Each building needs its own full-size lot, except
    in R-2-5 where each half of a twin house may have its own smaller lot.
    """
    types = ("single", "semi", "multi")
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
        side_yard={t: Yard(yard, side_share) for t in types},
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
                         0.25, curved=55),
    "R-12": _low_density("R-12", 12000, 12000, 80, 95, 60, 35, 10, 1 / 2,
                         0.30, curved=45),
    "R-8": _low_density("R-8", 8000, 9000, 65, 80, 40, 30, 8, 1 / 2, 0.35),
    "R-5": _low_density("R-5", 5000, 6500, 50, 65, 40, 20, 7, 1 / 3, 0.45),
    "R-2-5": _low_density(
        "R-2-5", 5000, 6500, 50, 65, 40, 20, 7, 1 / 3, 0.45,
        semi={
            "area": {"semi": 2500},
            "corner_area": {"semi": 3250},
            "width": {"semi": 25},
            "frontage": {"semi": 25},
        },
    ),
    "RA": ZoneRules(
        name="RA",
        allowed=frozenset({"single", "semi", "townhouse", "multi"}),
        lot_area={"single": 1980, "semi": 1980, "townhouse": 1980},
        lot_width={"single": 50, "semi": 25, "multi": 50, "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"single": 50, "semi": 25, "multi": 50, "townhouse": 18},
        width_measured_at=20,
        side_yard={
            "single": Yard(7, 1 / 3),
            "semi": Yard(7, 1 / 3),
            "townhouse": Yard(8, 1 / 3),
            "multi": Yard(16, 1 / 2),
        },
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=0.75,
        max_height={"single": 30, "semi": 30, "townhouse": 45, "multi": 45},
        min_open_space=0.35,
    ),
    "RB": ZoneRules(
        name="RB",
        allowed=frozenset({"single", "semi", "townhouse"}),
        lot_area={"single": 1980, "semi": 1980, "townhouse": 1980},
        lot_width={"single": 50, "semi": 25, "townhouse": 18},
        end_lot_width={"townhouse": 26},
        corner_lot_width={"townhouse": 38},
        frontage={"single": 50, "semi": 25, "townhouse": 18},
        width_measured_at=20,
        side_yard={
            "single": Yard(8, 1 / 3),
            "semi": Yard(8, 1 / 3),
            "townhouse": Yard(8, 1 / 3),
            "multi": Yard(16, 1 / 2),
        },
        rear_yard=Yard(8, 1.0),
        no_side_yard_below_width=25,
        max_floor_area_ratio=0.75,
        max_height={"single": 30, "semi": 30, "townhouse": 45, "multi": 45},
        min_open_space=0.35,
    ),
    "RCX": ZoneRules(
        name="RCX",
        allowed=frozenset({"townhouse", "multi"}),
        front_yard_required=False,
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
        front_yard_required=False,
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
        front_yard_required=False,
        lot_area={"multi": 43560},
        frontage={"multi": 100},
        side_yard={"multi": Yard(16, 1 / 2)},
        rear_yard=Yard(16, 1 / 2),
        max_height={"multi": 150},
        min_open_space=0.40,
    ),
    "RM": ZoneRules(
        name="RM",
        allowed=frozenset({"single", "semi", "townhouse"}),
        lot_area={"single": 1452, "semi": 1452, "townhouse": 1452},
        lot_width={"single": 25, "semi": 25, "townhouse": 18},
        frontage={"single": 25, "semi": 25, "townhouse": 18},
        side_yards_by_lot_width=True,
        rear_yard=Yard(16, 1 / 2),
        max_floor_area_ratio=1.50,
        # 35 feet by default; 45 is allowed for some roof shapes, so we
        # only count a building as too tall above 45.
        max_height={"single": 45, "semi": 45, "townhouse": 45},
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
        frontage={},
        width_measured_at=6,
        side_yard={"townhouse": Yard(12, 1 / 2)},
        rear_yard=Yard(12, 1.0),
        front_yard=4,
        max_floor_area_ratio=0.50,
        max_height={"townhouse": 35},
        max_coverage=0.30,
    ),
}

ALL_TYPES = frozenset({"single", "semi", "townhouse", "multi"})
HOUSE_LIKE = ("single", "semi", "townhouse")


def _commercial(name, townhouse_area, far, height, historic_far=False,
                **overrides):
    """Build the rules for homes in a commercial or office zone.

    These zones (Article IV of the ordinance) share one pattern for homes:
    house-sized lots, townhouse lots, and yards much like the RB zone.
    """
    settings = {
        "name": name,
        "allowed": ALL_TYPES,
        "lot_area": {"single": 5000, "semi": 2500, "townhouse": townhouse_area},
        "lot_width": {"single": 50, "semi": 25, "multi": 50, "townhouse": 18},
        "end_lot_width": {"townhouse": 26},
        "corner_lot_width": {"townhouse": 38},
        "frontage": {"single": 50, "semi": 25, "multi": 50, "townhouse": 18},
        "width_measured_at": 20,
        "side_yard": {
            "single": Yard(8, 1 / 3),
            "semi": Yard(8, 1 / 3),
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
    "lot_width": {"single": 50, "semi": 25},
    "end_lot_width": {},
    "corner_lot_width": {},
    "frontage": {"single": 50, "semi": 25},
}

ZONES |= {
    "CL": _commercial("CL", 1980, 0.75, 35, historic_far=True),
    "CC": _commercial("CC", 1980, 0.75, 35),
    "CSL": _commercial("CSL", 1980, 0.75, 50, historic_far=True),
    "CG": _commercial("CG", 1980, 0.75, 50),
    "OC": _commercial("OC", 1600, 1.25, 50, historic_far=True),
    # Height in CDX comes from a neighborhood plan, so it is not checked.
    "CDX": _commercial("CDX", 1245, 1.25, None, historic_far=True,
                       end_lot_width={}, corner_lot_width={}),
    "OCM(50)": _commercial("OCM(50)", 800, 1.50, 50, **_OFFICE),
    "OCM(100)": _commercial("OCM(100)", 800, 1.50, 100, **_OFFICE),
    # OCH floor area rules for homes have several special cases; skipped.
    "OCH": _commercial("OCH", 800, None, 100, **_OFFICE),
    "CD": ZoneRules(
        name="CD",
        allowed=ALL_TYPES,
        lot_area={kind: 1452 for kind in HOUSE_LIKE},
        lot_width={"single": 25, "semi": 25, "townhouse": 18, "multi": 50},
        frontage={"single": 25, "semi": 25, "townhouse": 18, "multi": 50},
        side_yard={
            "single": Yard(5),
            "semi": Yard(5),
            "townhouse": Yard(5),
            "multi": Yard(25, 1 / 3),
        },
        rear_yard={
            "single": Yard(16, 1 / 2),
            "semi": Yard(16, 1 / 2),
            "townhouse": Yard(16, 1 / 2),
            "multi": Yard(25, 1.0),
        },
        no_side_yard_below_width=25,
        max_floor_area_ratio={"single": 1.50, "semi": 1.50, "townhouse": 1.50,
                              "multi": 1.25},
        # Houses: 35 feet, or 45 for some roof shapes, so we use 45.
        max_height={"single": 45, "semi": 45, "townhouse": 45, "multi": 50},
        min_open_space=0.35,
        open_space_applies_to=frozenset({"multi"}),
    ),
    # Waterfront mixed-use zone. Its height limit was not captured.
    "W-1": ZoneRules(
        name="W-1",
        allowed=ALL_TYPES,
        front_yard_required=False,
        lot_area={"townhouse": 1452},
        lot_width={"townhouse": 18, "multi": 50},
        end_lot_width={"townhouse": 26},
        frontage={"townhouse": 18, "multi": 50},
        side_yard={"townhouse": Yard(8), "multi": Yard(16, 1 / 2)},
        rear_yard={"single": Yard(8), "semi": Yard(8), "townhouse": Yard(8),
                   "multi": Yard(16, 1 / 2)},
        no_side_yard_below_width=25,
        max_floor_area_ratio=1.0,
        historic_floor_area_ratio={kind: 1.50 for kind in HOUSE_LIKE},
        min_open_space=0.35,
    ),
}

# The mixed-use zones. Bigger projects there need a special permit; these
# are the limits that apply without one.
for _name in ("CRMU/L", "CRMU/M", "CRMU/H"):
    ZONES[_name] = ZoneRules(
        name=_name.replace("/", "-"),
        allowed=ALL_TYPES,
        max_floor_area_ratio=1.0,
        historic_floor_area_ratio={kind: 1.50 for kind in HOUSE_LIKE},
        min_open_space=0.35,
    )

ZONES |= {
    # Without a special permit CRMU-X allows only houses and townhouses.
    "CRMU/X": ZoneRules(
        name="CRMU-X",
        allowed=frozenset(HOUSE_LIKE),
        lot_area={"townhouse": 1452},
        lot_width={"townhouse": 18},
        frontage={"townhouse": 18},
        side_yard={"townhouse": Yard(8, 1 / 3)},
        rear_yard={"townhouse": Yard(16, 1 / 2)},
        no_side_yard_below_width=25,
        max_floor_area_ratio=1.50,
    ),
    # King Street retail zone: no lot or yard rules for homes. Its floor
    # area limit depends on the block, so it is not checked.
    "KR": ZoneRules(name="KR", allowed=ALL_TYPES, front_yard_required=False),
    # Industrial and utility zones do not allow homes at all.
    "I": ZoneRules(name="I (industrial)", allowed=frozenset()),
    "UT": ZoneRules(name="UT (utility)", allowed=frozenset()),
}

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
    plan_height: float | None = None
    plan_allowed: frozenset = ALL_TYPES
    # Cap on homes across the whole district, if the ordinance sets one.
    home_cap: int | None = None
    homes_per_acre_cap: float | None = None
    # Plain-language summary of what the approval allows.
    plan_summary: str = ""


PLANNED_DISTRICTS = {
    "CDD#1": PlannedDistrict(
        "Duke Street / Carlyle", "OC", 1.25, 77, plan_height=200,
        plan_summary="The approval allows a mix of uses including homes, "
        "with buildings up to 200 ft."),
    "CDD#2": PlannedDistrict(
        "Eisenhower Avenue Metro", "OC", 1.25, 100,
        plan_allowed=frozenset({"multi"}),
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
    # RB and RC apply on two edges of this district; OC on the rest.
    "CDD#7": PlannedDistrict(
        "Route 1 Properties", "OC", plan_height=45,
        plan_summary="The approval allows homes among other uses, with "
        "buildings up to 45 ft."),
    "CDD#9": PlannedDistrict(
        "Cameron Station", "R-8", plan_height=120, home_cap=2510,
        plan_summary="The approval allows up to 2,510 homes on 97 acres. "
        "Heights run from 45 ft at the edges to 120 ft for a few buildings "
        "on the south side; this map only tests the 120 ft ceiling."),
    # Potomac Yard's fallback depends on where in the district the lot is;
    # see potomac_yard_zone().
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
        plan_allowed=frozenset({"multi"}),
        plan_summary="The approval allows apartments over shops, up to "
        "45 ft; houses and townhouses are not allowed."),
    "CDD#15": PlannedDistrict(
        "Braddock Gateway", "OCM(50)", 1.50,
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


def planned_district_rules(label, in_historic_district=False, zone=None):
    """Look up both rule sets for a lot in a planned district.

    Returns (district, plan rules, fallback rules), or None for a district
    not in the table. Plan rules are what the district's special approval
    allows. Fallback rules are the ordinary zone that applies without it;
    zone overrides the table's fallback where that depends on location.
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
    )
    zone = zone or district.fallback_zone
    fallback = rules_for(zone, in_historic_district)
    changes = {}
    if district.fallback_floor_area_ratio:
        changes["max_floor_area_ratio"] = district.fallback_floor_area_ratio
    if district.fallback_height:
        changes["max_height"] = {
            kind: district.fallback_height for kind in ALL_TYPES}
    return district, plan, replace(fallback, **changes) if changes else fallback


# Inside the two historic districts the RB zone swaps in looser rules.
RB_HISTORIC = ZoneRules(
    name="RB",
    allowed=ZONES["RB"].allowed,
    lot_area=ZONES["RB"].lot_area,
    lot_width=ZONES["RB"].lot_width,
    end_lot_width=ZONES["RB"].end_lot_width,
    corner_lot_width=ZONES["RB"].corner_lot_width,
    frontage=ZONES["RB"].frontage,
    width_measured_at=0,
    side_yards_by_lot_width=True,
    rear_yard=Yard(8, 1.0),
    max_floor_area_ratio=1.50,
    max_height={"single": 45, "semi": 45, "townhouse": 45, "multi": 45},
    min_open_space=0.35,
)

HOME_TYPE_NAMES = {
    "single": "detached house",
    "semi": "twin house (one half)",
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
