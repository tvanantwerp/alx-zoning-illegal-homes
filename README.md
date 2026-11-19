# Mapping which homes are illegal to build again under current zoning in Alexandria, VA

An interactive map of Alexandria homes that could not be built today because
they break the city's current zoning rules for new construction. Hover over a
lot to see why.

## Run it

```sh
uv sync
uv run create-map                       # downloads data, checks every lot, writes site/lots.geojson
python3 -m http.server -d site 8765     # then open http://127.0.0.1:8765
uv run pytest                           # tests
```

`uv run python -m alx_zoning_illegal_homes.downloader.download --refresh`
fetches fresh copies of the city's data.

## The lot drawing

Clicking a checked home lot on the map, or finding one with the address
search, opens a pop-up. It draws the lot and its buildings in 3D, marks
every rule the lot breaks, and lists every rule the map checks with the
measured value and what the rule asks for. Hovering over a row lights up its
part of the drawing. Lots the map didn't check, such as parks, don't open
one.

For planned-district lots the pop-up has its own copy of the "Judge them by
ordinary zoning instead" checkbox. Both boxes control the same setting, so
ticking either one updates the map, the side panel and the pop-up together.

Each drawing loads its own small file. `create-map` writes one per checked
lot into `site/lots/`, next to `site/lots.geojson`. Both are generated and
left out of git, so run `create-map` before serving the site.

## What gets checked

Every lot with a home is measured against the rules for its zone. That covers
the residential zones (R-20, R-12, R-8, R-5, R-2-5, RA, RB, RCX, RC, RD, RM,
RS, RT) and homes in the commercial, office and waterfront zones (CL, CC, CSL,
CG, CD, CDX, OC, OCM, OCH, W-1, CRMU, KR) and in planned districts:

- **Lot size**, **lot width** and **street frontage**. In RA, RB, RM, CL,
  CSL, CD, CDX, OC, OCM, OCH, CRMU-L, CRMU-H and CRMU-X, a lot recorded
  before December 16, 2023 may still hold a detached house, a two-unit house
  or a townhouse when it is too small, too narrow, has too little street
  frontage, or has too little land per home (section 12-1000, on older lots).
  Those rows show as "older lot OK", which counts as passing, and still show
  the shortfall. The home must still meet the zone's yard and open space
  rules, but its floor space is capped at 150% of the lot and its height at
  35 ft, whatever the zone's own limits. That height cap is stricter than
  the 45 ft many of these zones give townhouses. The section's title also
  names CRMU-M, but its text leaves CRMU-M out, so the map doesn't apply it
  there. Apartment buildings get no such excuse.
- **Side and rear yards**, both the fixed minimum and the deeper yard taller
  buildings need. The deeper yard is judged for each part of a home (a
  low wing, a taller main block) at that part's own height and distance
  from the lot line, with each part's height measured the same way as in
  the height check below: a flat roof at its top, a gable or hip roof
  halfway up.
- **Floor space** compared with lot size. In the KR and OCH zones the limit
  is looser within 1,000 ft of a Metro station.
- **Height**, measured as the ordinance does: to the top of a flat roof, but
  only halfway between the eaves and the peak of a gable or hip roof. The
  city's 3D data gives only the peak, so the map guesses the roof's shape and
  the height of its eaves from the number of stories in city records (about
  10 ft per full story, plus 2 ft for a raised ground floor). A roof that
  rises only a few feet above those eaves counts as flat, and apartment
  buildings are taken to have flat roofs. A roof is never taken to rise
  more than 15 ft, since a story count that leaves a taller roof is
  probably short. With no story count, a pitched roof is measured at 85% of
  its peak. The limit is the lower of the zone's own and the city's height
  district map's, and the pop-up says which one set it. W-1 takes its height
  from the map; CDX and the CRMU zones take theirs from a small area plan
  the map doesn't have, so only the height district map's limit is checked
  there. In the Potomac River area the map allows 30 ft, and up to 50 ft
  only with a special permit from City Council, so 30 ft is used. Near the
  King Street Metro it allows 77 ft, or 82 ft for a building that city
  records mark as having shops on the ground floor.
- **Open space** or building coverage. Open space is the land not under a
  building, road, alley, driveway or parking lot, leaving out every strip
  narrower than 8 ft, as the ordinance's definition of "open and usable
  space" says. The RM zone asks for 35% of the lot and never less than
  300 sq ft. It also lets a lot keep the open space it had on June 24, 1992
  if that was less, and lets a lot that already fell short then count strips
  narrower than 8 ft. The map can't know any of that, so an older RM home
  may be fine as it stands. The RD zone lets half the land used for parking count,
  up to 90% of the open space it requires. Building coverage (the RT zone's
  rule) counts buildings only.
- **Home type**, e.g. townhouses in a zone that allows only houses. A few
  zones carry their own exceptions for older homes, and those homes pass:
  apartment buildings in the RB zone built before 1978 (the exception also
  asks that the land was zoned RB by 1973, which the map can't confirm), and
  detached and twin houses in the RC and RCX zones built before June 24, 1992.
  Those RC and RCX houses may be rebuilt under the limits they were built
  under, which the map doesn't know.
- **Homes near Eisenhower Avenue.** The OCM(100) and OCH zones allow homes on
  lots within 1,000 ft of the avenue's centerline only with a special permit
  from City Council, so homes there count as breaking the rules. OCH homes
  built by 1999 get a note that they may be kept without one (homes there by
  November 9, 1999 are exempt), but are still judged as new construction.
  South Carlyle's ordinary-zoning view (OCM(100)) gets the same rule.

The rules live as plain data in `alx_zoning_illegal_homes/mapper/rules.py`.
They come from Articles III, IV and V of the Zoning Ordinance as amended
through Ordinance 5614 (January 2026), which includes the 2023 "Zoning for
Housing" changes.

The test is always: *if the buildings vanished, could you legally put them
back today?*

### Planned districts

Zones starting with CDD (Cameron Station, Potomac Yard, Carlyle and others)
are planned districts. Each was built under a special permit from City
Council, and that approval still governs the land. The ordinance (section
5-602, Table 1) gives two sets of limits for every district:

- **With the special approval:** which kinds of home are allowed, a maximum
  height, and a cap on homes or floor space across the whole district. Lot
  sizes and yards are not set by rule; the approved site plan drawings fix
  them.
- **Without it:** an ordinary zone's rules (R-8 for Cameron Station, for
  example), sometimes with a changed floor area or height limit.

Homes there are judged by the first set, since that is what a rebuild would
be held to. That means checking home type and height lot by lot, and
reporting each district's home count against its cap. Lot sizes and yards are
not judged, because the drawings that set them are not available as data.

Each lot also records how it would fare under the second set, and the map has
a checkbox to switch to that view. It shows how far these neighborhoods are
from what ordinary zoning allows.

Where the city's development-projects layer covers a lot, the lot is tagged
with its case name and number (for example "Cameron Station Phase VI
(DSP2003-00018)") so the actual approval can be looked up. That layer mostly
covers cases from about 2002 on.

In a few districts the ordinary zone depends on where the lot sits, and
those boundaries are approximated:

- Potomac Yard: near Route 1, east of the Metro tracks, or elsewhere, where
  it is industrial and allows no homes. The ordinance also lets the
  "Piggyback Yard" and Slaters Lane parts use CRMU-L rules, but those areas
  are drawn only on a 1995 rezoning plat the map doesn't have.
- Route 1 Properties: RB along Reed Avenue, RC within 100 ft of Commonwealth
  Avenue, OC on the rest.
- Duke Street / Carlyle: a looser floor space limit within 1,000 ft of the
  King Street Metro station.
- Braddock Gateway: CRMU-H on one acre at First and Fayette Streets, OCM(50)
  on the rest. The map approximates the corner parcel using a 250 ft radius
  from the street intersection.

Metro station locations aren't in the city's data, so `places.py` lists them.

### Mixed-use zones

The mixed-use zones (CRMU-L, -M, -H, -X), the waterfront zone (W-1) and the
King Street retail zone (KR) are judged by their limits without a special
permit. For apartment buildings those are mainly floor space and open space.
Houses, twins and townhouses get more: lot size, street frontage, and side
and rear yards, much as in the commercial zones. KR allows homes only as
apartments over or behind shops. Many buildings in these zones were approved
with individual special permits that this project does not know about, so
findings here are the least reliable.

## How lots are measured

The parcel map is only a set of polygons, so `lot_lines.py` works out each
lot's front, sides and rear from shape alone:

1. The lot outline is cut into short pieces.
2. A piece with another lot right across it is a shared line. Otherwise it is
   open.
3. An open piece faces a street if a street centerline is close by, roughly
   straight out from it, with no other lot in between. This is what keeps an
   edge along an alley from counting as street frontage.
4. Two fronts that meet make a corner lot. The front named in the lot's
   address is the main one.
5. Lot width is measured the way the ordinance says: straight across the
   lot, set back from the front line by the zone's front yard depth. This
   gives sensible answers for pie-shaped and flag-shaped lots.

Other details that matter:

- Condo units are stacked on one polygon in the parcel layer, or drawn as
  small outlines on top of the land they share; either way they are folded
  into one lot.
- The city often draws a whole townhouse row or condo building as a single
  outline across many lots. Such a building is cut along the lot lines so
  each lot is judged on its own part. A piece too small to count as a home
  (a strip left where a lot line runs a few feet inside a building) stays
  with the larger piece it touches, so the building keeps its full outline
  where it meets its neighbor.
- Lots that one owner has built a single house across are joined.
- Homes that share a wall (twins, townhouses) are not expected to have a yard
  on that side. The exception is half of a twin on a lot of its own in R-20,
  R-12, R-8 or R-5: those zones allow a twin only as one building on one lot,
  so a lot line along the shared wall counts as a missing side yard. Rows of three or more attached homes are treated as
  townhouses whatever the assessor's label says.
- A lot the assessor calls half of a twin is checked the same way. If both
  halves stand on that one lot, attached to no home on another lot, it is a
  whole two-unit house, and its lot needs room for both homes: in most zones
  twice the land and street frontage that one half needs on a lot of its
  own. If the lot holds just one outline drawn as a detached house, with no
  other home within 6 ft, it is judged as a detached house. A detached
  house with an apartment inside keeps its detached-house label and is
  never treated as a two-unit house.

## Limits

- "Illegal" means *could not be permitted as new construction*. The ordinance
  lets these older buildings stay, and be rebuilt as they were.
- Measurements come from public map data, not surveys. Every check leaves a
  margin, but any single finding can be wrong. Yard findings are the least
  certain: building outlines are traced from roofs, and lot lines and
  buildings come from different sources. Yards get 2.5 ft of slack, which
  covers measuring error and the 30 inches that eaves and roof overhangs may
  reach into a yard. It applies to every home, even ones with little or no
  overhang. A home drawn touching or crossing a
  lot line is assumed to be a mapping error and its yards are skipped.
- Front yards are mostly not checked. In most zones the rule depends on the
  neighbors' front yards, which an existing home meets almost by definition.
  RC, RCX, RD and KR require no front yard at all, nor does W-1 for
  apartment buildings, though the extra
  street setbacks along Duke Street, King Street and four other streets
  (section 7-1006) aren't checked yet.
- Roads, driveways and parking lots come from the city's planimetric map,
  traced from aerial photos. Patios, small parking pads and paving missing
  from that map still count as open space, so open space can look bigger
  than the ordinance would count it. Many zones also let a landscaped roof
  count, with the planning director's approval, which the map can't see, so
  an apartment building may have more open space than it shows.
- Parking rules are not checked.
- Height comes from the city's 3D building layer and floor space from the
  city's building records; neither matches the ordinance's definitions
  exactly. The 3D layer draws each part of a building as a flat-topped block
  as tall as its peak, so it can't show a roof's slope; where the eaves are
  is a guess from the number of stories. Every pitched roof is treated as a
  gable or hip roof. Gambrel roofs (measured halfway up the upper slope) and
  mansard roofs (measured at the roof line) come out lower on the map than
  the ordinance would measure them. Dormers can't be seen either: in R-20,
  R-12, R-8, R-5 and R-2-5, and for houses and two-unit houses in RA and RB
  outside the historic districts, dormers wider in total than 30% of the
  roof move the measurement up to halfway up the dormers, so a house with
  wide dormers may be taller than the map says. On a flat roof the 3D layer
  can't tell a parapet (a low wall around the roof's edge) from the roof
  itself. The ordinance leaves out a parapet of 3 ft or less but counts a
  taller one; the map counts the top of whatever the 3D layer shows, so a
  flat-roofed building with a low parapet may be up to 3 ft shorter than
  the map says. These guesses feed the yard check as well as the height
  check.
- When one owner holds both halves of a twin, each half on its own parcel,
  and the city's outline pokes a little over the line between them, the two
  parcels are joined and judged as one lot with a two-unit house on it. In
  most zones the land and frontage needed come out about the same as for
  two halves, but the map can't tell if one half's own parcel is too small.
- A few hundred home lots are left unchecked because the city's data gives
  them no zone, two zones, or no matching building.
- Variances and special approvals for individual properties are unknown.
- On the height district map, two Old Town North areas need a guess. One
  caps height at 77 ft and the average at 50 ft; the average covers a whole
  block or development, so only the 77 ft cap is checked. Another allows
  50 ft along North Royal Street and 77 ft behind it; how deep that strip
  runs couldn't be found, so every lot with a street edge on North Royal
  Street gets 50 ft. The height districts' rule tying a building's height to
  its distance from the middle of the street isn't checked yet. Lots in CDX
  and the CRMU zones outside the map's numbered areas have no height limit
  the map knows of.
- Every lot is taken to have been recorded before December 16, 2023, so the
  rule for older undersized lots applies to all of them. The parcel map shows
  lots as they are today and can't tell a lot split or redrawn since then.

## Data sources

From the [City of Alexandria open data site](https://cityofalexandria-alexgis.opendata.arcgis.com/)
(download links are in `alx_zoning_illegal_homes/downloader/files.json`):

- [Parcels](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::alexandria-parcels/explore)
- [Buildings](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/aec4d1c6ee894e1b821ff39d30bdfc30_0)
- [Buildings 3D](https://cityofalexandria-alexgis.opendata.arcgis.com/maps/buildings-3d) (heights)
- [Streets](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::transport-streets/explore)
- [Historic Districts](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::historic-districts/explore)
- [Development Projects](https://maps.alexandriava.gov/arcgis/rest/services/alxPlanningDevelopmentWm/MapServer)
  (links planned-district lots to their approval cases)
- [Roads, driveways and parking lots](https://maps.alexandriava.gov/arcgis/rest/services/alxBasemapWm/MapServer/17)
  from the city's basemap (left out of open space). The open data site has
  older copies from 2017, so the map uses the city's own map server.
- [Height Districts](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::height-districts/explore)
  (height limits that apply on top of each zone's own)
- [Zoning Map](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::zoning/explore)
  (downloaded but not yet used; zoning comes from the parcel layer)

The Zoning Ordinance is published at
[library.municode.com](https://library.municode.com/va/alexandria/codes/zoning).
That site blocks automated readers, so the rules were first read from the copy
at [zoneomics.com](https://www.zoneomics.com/code/alexandria-VA/chapter_5), then
checked against a saved copy of the ordinance kept as one file per section.
