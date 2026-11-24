"""Estimate a building's height the way the zoning ordinance measures it.

The ordinance's definition of building height (section 2-154) measures a
flat roof at its top, but a gable or hip roof only halfway between the eaves
and the ridge. The city's 3D building layer gives only the top of each roof,
the peak, so the map has to guess the roof's shape and where its eaves are.

The 3D layer splits a building into blocks (the main house, a wing, a
porch), each drawn as a flat-topped box as tall as its highest point. The
boxes don't show a roof's slope, so they can't tell a flat roof from a
pitched one on their own. They do give each block its own peak, so each
block is estimated on its own: a low wing gets its own eaves, not the main
house's. The guess for each block goes like this:

- Apartment buildings are taken to have flat roofs, as most do.
- Otherwise the eaves are put at about 10 ft per full story, plus 2 ft for
  a ground floor raised above the ground, using the city's count of
  stories. Half and quarter stories are rooms tucked under the roof, so
  they don't raise the eaves. A block too low to hold every story gets as
  many as fit under its peak.
- A roof that rises only a few feet above those eaves is taken as flat.
  Anything taller is taken as a gable or hip roof and measured halfway up.
- Home roofs rarely rise more than about 15 ft. When the stories leave a
  taller roof than that (a one-story house with a 35 ft peak), the story
  count is probably short, so the eaves are put 15 ft below the peak.
- When the city has no story count, the roof is taken as pitched and
  measured at a fixed share of its peak, but never more than half of that
  15 ft below it.

Gambrel and mansard roofs, which the ordinance measures higher, and wide
dormers, which in some zones move the measurement up, can't be seen in the
data. Every pitched roof is treated as a gable or hip roof.
"""
import math
from dataclasses import dataclass, field, replace

import shapely
from shapely.ops import unary_union

# Roof pieces smaller than this, in square feet, are dropped as slivers.
MIN_PART_AREA = 5.0
# A story's height, floor to floor, in feet.
STORY_HEIGHT = 10.0
# How far a ground floor usually sits above the ground, in feet.
FIRST_FLOOR_RISE = 2.0
# A roof rising no more than this above the estimated eaves is taken as
# flat. It covers the parapet up to 3 ft that the ordinance leaves out of a
# flat roof's height, and stories that run a little taller than estimated.
FLAT_ROOF_RISE = 4.0
# A home's roof rarely rises more than this above its eaves, in feet. When
# the story count puts the eaves lower, the eaves are raised to this far
# below the peak.
MAX_ROOF_RISE = 15.0
# With nothing better known, a pitched roof's height is taken as this share
# of its peak.
PITCHED_SHARE = 0.85
# Section 6-403(B)(3) permits up to three 15-foot rooftop penthouses by right.
MAX_ROOFTOP_RISE = 15.0
MAX_ROOFTOP_PARTS = 3
# Geometry used to identify likely rooftop equipment in the 3D layer.
MAX_ROOFTOP_SHARE = 0.25
ROOF_EDGE_TOLERANCE = 1.0

FLAT, PITCHED, UNKNOWN = "flat", "pitched", "unknown"


@dataclass
class RoofHeight:
    """One roof's peak and its height as the ordinance measures it, in feet.

    `shape` is "flat", "pitched", or "unknown" for a stories-only estimate. `why` is a plain-language sentence
    saying how the shape and eaves were guessed. `eaves` is the estimated
    height of the eaves, or None when it wasn't estimated (a flat roof
    with no story count). `outline` is the part of the building under
    this roof.
    """

    peak: float
    height: float
    shape: str
    why: str
    eaves: float | None = None
    outline: object = None

    @property
    def rise(self) -> float | None:
        """How far the roof rises above its eaves, or None when the eaves aren't known."""
        return None if self.eaves is None else self.peak - self.eaves


@dataclass
class BuildingHeight:
    """A building's height as the ordinance measures it, with each roof part's own.

    The building's height is that of its tallest part as the ordinance
    measures it; its peak is the highest point of any part. The shape, the
    reason and the eaves are those of the tallest part.
    """

    parts: list[RoofHeight] = field(default_factory=list)

    @property
    def tallest(self) -> RoofHeight:
        """The part with the greatest height as the ordinance measures it."""
        return max(self.parts, key=lambda part: (part.height, part.peak))

    @property
    def peak(self) -> float:
        return max(part.peak for part in self.parts)

    @property
    def height(self) -> float:
        return self.tallest.height

    @property
    def shape(self) -> str:
        return self.tallest.shape

    @property
    def why(self) -> str:
        return self.tallest.why

    @property
    def eaves(self) -> float | None:
        return self.tallest.eaves


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


def _stories_word(stories: float) -> str:
    return f"{stories:g} {'story' if stories == 1 else 'stories'}"


def roof_height(peak: float, stories: float | None = None, apartment: bool = False,
                outline=None, building_peak: float | None = None) -> RoofHeight:
    """Estimate one roof's height as the ordinance measures it, from its peak.

    `stories` is the city's count of stories for the whole building, or None
    when unknown. `apartment` marks an apartment building, whose roof is
    taken as flat. `building_peak` is the peak of the whole building when
    this roof covers only part of it: a lower part holds only as many full
    stories as fit under its own peak. See the module's description for how
    the guess is made.
    """
    peak = float(peak)
    if apartment:
        return RoofHeight(peak, peak, FLAT, (
            "Apartment buildings mostly have flat roofs, so it is measured at the top."),
            outline=outline)
    if stories:
        full_stories = math.floor(stories)
        counted = f"City records give it {_stories_word(stories)}"
        if building_peak is not None and peak < building_peak:
            fit = math.floor((peak - FIRST_FLOOR_RISE) / STORY_HEIGHT)
            if fit < full_stories:
                full_stories = fit
                counted = (f"This lower part of the home has room for "
                           f"{_stories_word(max(fit, 0))} under its roof")
        if full_stories < 1:
            return RoofHeight(peak, peak, FLAT, (
                "This part is too low to hold a full story under a sloped roof, so it "
                "is measured at the top."), outline=outline)
        eaves = FIRST_FLOOR_RISE + STORY_HEIGHT * full_stories
        rise = peak - eaves
        if rise <= FLAT_ROOF_RISE:
            return RoofHeight(peak, peak, FLAT, (
                f"{counted}, which reach nearly to the top, so the roof looks flat and "
                "is measured at the top."), eaves=eaves, outline=outline)
        if rise <= MAX_ROOF_RISE:
            placed = (f"{counted}, so its eaves are probably about {eaves:.0f} ft up, at "
                      f"about {STORY_HEIGHT:.0f} ft per full story.")
        else:
            eaves = peak - MAX_ROOF_RISE
            placed = (f"{counted}, which would leave a roof taller than homes usually "
                      "have, so the count is probably short. The map puts the eaves "
                      f"{MAX_ROOF_RISE:.0f} ft below the peak, about {eaves:.0f} ft up.")
        return RoofHeight(peak, (eaves + peak) / 2, PITCHED, placed + (
            " The roof above them is taken as a gable or hip roof, which the zoning "
            "rules measure halfway between the eaves and the peak."),
            eaves=eaves, outline=outline)
    height = max(PITCHED_SHARE * peak, peak - MAX_ROOF_RISE / 2)
    return RoofHeight(peak, height, PITCHED, (
        "City records don't say how many stories it has. "
        "Like most homes, it is taken to have a gable or hip roof, which the zoning "
        "rules measure halfway between the eaves and the peak; the map counts "
        f"{PITCHED_SHARE:.0%} of the peak, and never more than "
        f"{MAX_ROOF_RISE / 2:.1f} ft below it."), outline=outline)


def building_height(home, apartment: bool = False) -> BuildingHeight | None:
    """Estimate a home's height as the ordinance measures it, part by part.

    `home` is a `checks.Home`: its outline, its peak height, its 3D roof
    sections and its story count. The home is split into parts by roof
    height (see `roof_parts`) and each part is estimated with `roof_height`.
    A part taller than the home's own height is a chimney, stair tower or
    similar small piece the home's height already leaves out, so it is
    lowered to that height. On an apartment building, small raised parts
    enclosed by the main flat roof are taken as rooftop appurtenances (see
    `_exclude_rooftop_parts`). Returns None when the home's height is unknown.
    """
    estimated = []
    for shape, peak in roof_parts(home.shape, home.sections, home.height or 0):
        if peak > 0:
            peak = min(peak, home.height) if home.height else peak
            estimated.append(roof_height(peak, home.stories, apartment, shape,
                                         building_peak=home.height))
        elif home.stories:
            height = home.stories * STORY_HEIGHT
            estimated.append(RoofHeight(height, height, UNKNOWN,
                                        "Height is estimated from the recorded stories. "
                                        "The roof height and shape are unknown.", outline=shape))
    if not estimated:
        return None
    # On a flat-roofed house or townhouse, a raised part this size is as likely
    # a rooftop room as a stair or elevator penthouse, and a room counts toward height.
    return BuildingHeight(_exclude_rooftop_parts(estimated, home.shape) if apartment
                          else estimated)


def _exclude_rooftop_parts(parts: list[RoofHeight], footprint) -> list[RoofHeight]:
    """Estimate the rooftop appurtenance exclusion under section 6-403(B).

    The city maps heights and outlines without identifying use or construction.
    A likely appurtenance is a small raised section surrounded by the largest
    flat roof. Higher roof sections that extend to a wall count at full height.
    """
    if len(parts) < 2:
        return parts
    base = max(parts, key=lambda part: part.outline.area)
    if base.shape != FLAT:
        return parts
    candidates = {}
    max_area = MAX_ROOFTOP_SHARE * footprint.area
    boundary = footprint.boundary
    base_with_slack = base.outline.buffer(ROOF_EDGE_TOLERANCE)
    for index, part in enumerate(parts):
        rise = part.peak - base.peak
        if not 0 < rise <= MAX_ROOFTOP_RISE or part.outline.area > max_area:
            continue
        islands = shapely.get_parts(part.outline)
        if all(
            island.distance(boundary) > ROOF_EDGE_TOLERANCE
            and base_with_slack.covers(island.buffer(2 * ROOF_EDGE_TOLERANCE).difference(island))
            for island in islands
        ):
            candidates[index] = part
    count = sum(shapely.get_num_geometries(part.outline) for part in candidates.values())
    area = sum(part.outline.area for part in candidates.values())
    if not candidates or count > MAX_ROOFTOP_PARTS or area > max_area:
        return parts
    combined = replace(
        base, outline=unary_union([base.outline, *(part.outline for part in candidates.values())]),
        why=base.why + " The map treats small raised parts surrounded by this roof as "
        "rooftop structures, which section 6-403(B) allows above the roofline.")
    return [combined if part is base else part for i, part in enumerate(parts) if i not in candidates]
