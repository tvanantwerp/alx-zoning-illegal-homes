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
RMF, RS, RT) and homes in the commercial, office and waterfront zones (CL, CC, CSL,
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
- **Land per home for CRMU-X townhouses.** The 1,452 sq ft minimum applies
  across the whole development, including shared land. The map uses verified
  site area and dwelling counts from the development approval where available.
  The city project layer currently identifies Chatham Square, whose count
  includes its stacked townhouses. The rule stays unchecked without confirmed
  development data. Separate lot width and frontage rules can still trigger
  the older-lot allowance.
- **Front yards.** In most zones (R-20 through R-2-5, RA, RB outside the
  historic districts, the commercial and office zones, and houses and
  townhouses in the CRMU zones and W-1) a home's front yard must fall within
  the range of its neighbors' front yards: the ordinance's "contextual block
  face", which its drawings show as the lots on either side that face the
  same street and the lots straight across the street from them. Once the
  shallowest of those is deeper than the zone's cap (40 ft in R-20, 35 ft in
  R-12, 30 ft in R-8, 20 ft elsewhere), the cap is enough. The map checks
  that a home stands back at least as far as its closest neighbor (or the
  cap), with the same 2.5 ft of slack as other yards; the home itself isn't
  counted. A corner or through lot is judged on each street against the
  neighbors along that street. A home with no neighbors on its street isn't
  judged. RS (20 ft) and RT (4 ft) have fixed front yards. RC, RCX, RD and
  KR require none, nor do apartment buildings in W-1 and the CRMU zones,
  or townhouses in CRMU-X.
  RB homes in the historic districts belong at the front lot line unless the
  board of architectural review approves another line: a home at the line
  passes, and one set back isn't judged.
- **Extra setbacks along named streets** (section 7-1006). In every zone,
  buildings along these stretches must stand back at least this far:
  - Mount Vernon Avenue, from Braddock Road north: 10 ft from the front lot line.
  - Duke Street, from Diagonal Road to Quaker Lane: 60 ft from the center of
    the street; west of Quaker Lane: 75 ft.
  - King Street, from Braddock Road northwest: 75 ft from the center.
  - Seminary Road, west of Quaker Lane: 60 ft from the center.
  - Beauregard Street: 80 ft from the center.
  - South Pickett Street: 50 ft from the center.

  The ordinance measures from the centerline as mapped in 1960; the map uses
  today's street map, with 5 ft of slack as for the height-near-the-street
  rule (2.5 ft on Mount Vernon Avenue, as for other yards). The ends of each
  stretch are approximated by lines of longitude or latitude through the
  cross streets. Planned districts' approved plans set the rule aside.
- **Side and rear yards**, both the fixed minimum and the deeper yard taller
  buildings need. The deeper yard is judged for each part of a home (a
  low wing, a taller main block) at that part's own height and distance
  from the lot line, with each part's height measured the same way as in
  the height check below: a flat roof at its top, a gable or hip roof
  halfway up. A corner lot has no rear yard: both street sides are fronts
  and the rest are sides. The exception is a townhouse on a corner in the
  RM zone, where the yard left over must meet the rear yard rule (at least
  16 ft, and 1 ft for every 2 ft of height, counting half of an alley
  behind toward the second part). The map measures it to every lot line
  away from both streets that isn't along a shared wall.
- **Floor space** compared with lot size. In the KR and OCH zones the limit
  is looser within 1,000 ft of a Metro station. Where a floor space limit
  applies, the map counts garages, sheds and other outbuildings. Outside
  the historic districts, homes in R-20 through R-2-5 and houses and
  two-unit houses in RA and RB get an allowance of 100 sq ft (lots under
  2,500 sq ft), 350 sq ft, or 600 sq ft (lots of 8,000 sq ft or more).
  Only qualifying sheds and garages get this allowance. The map estimates
  eligibility from their floor space. On lots with a house or two-unit
  house, sheds may total up to 100 sq ft. One garage of up to 250 sq ft
  qualifies on lots of 2,500 to under 8,000 sq ft, or up to 500 sq ft on
  larger lots. Their floor space comes from their outlines, as one story
  unless the city's 3D data shows a building tall enough for more.
  Elsewhere, section 2-145(B) counts garages in full. It leaves out small
  sheds: up to 100 sq ft for houses and two-unit houses outside the
  historic districts, and up to 65 sq ft for houses, two-unit houses and
  townhouses inside them. Other homes get no shed exclusion. City records
  group garages and sheds together, so the map uses floor space to
  estimate which structures qualify.
- **Height**, measured as the ordinance does: to the top of a flat roof, but
  only halfway between the eaves and the peak of a gable or hip roof. The
  city's 3D data gives only the peak, so the map guesses the roof's shape and
  the height of its eaves from the number of stories in city records (about
  10 ft per full story, plus 2 ft for a raised ground floor). A roof that
  rises only a few feet above those eaves counts as flat. Apartment
  buildings with at least five full stories or an unknown story count
  are assumed to have flat roofs. A roof is never taken to rise
  more than 15 ft, since a story count that leaves a taller roof is
  probably short. With no story count, a pitched roof is measured at 85% of
  its peak. The limit is the lower of the zone's own and the city's height
  district map's, and the pop-up says which one set it. RM, and houses and
  townhouses in CD, allow 35 ft, or 45 ft when the roof's ridge runs
  parallel to the street and its slope fits the neighbors'. A roof the map
  takes as flat has no ridge, so it is held to 35 ft; every other roof gets
  45 ft (see below). W-1 takes its height
  from the map; CDX and the CRMU zones take theirs from a small area plan
  the map doesn't have, so only the height district map's limit is checked
  there. In the Potomac River area the map allows 30 ft, and up to 50 ft
  only with a special permit from City Council, so 30 ft is used. Near the
  King Street Metro it allows 77 ft, or 82 ft for a building that city
  records mark as having shops on the ground floor.
- **Height near the street.** Every height district holds a building to at
  most twice the distance from its wall to the center of the street it
  faces, so taller parts must step back. Each part of each home is checked
  at its own height, measured as above, against the center of every street
  the lot faces (on a corner or through lot, both streets). The center comes
  from the city's street map. A divided road is drawn there as one
  centerline per side, so its center is taken as halfway between the two.
  The approved plan for the Eisenhower Avenue Metro planned district sets this
  rule aside, so it isn't checked there.
- **Open space** or building coverage. Open space is the land not under a
  building, road, alley, driveway or parking lot, leaving out every strip
  narrower than 8 ft, as the ordinance's definition of "open and usable
  space" says. The RM zone asks for 35% of the lot and never less than
  300 sq ft. It also lets a lot keep the open space it had on June 24, 1992
  if that was less, and lets a lot that already fell short then count strips
  narrower than 8 ft. The map can't know any of that, so an older RM home
  may be fine as it stands. CD asks for 35% of every home lot, with the same
  1992 allowance for houses, twin houses and townhouses, so an older one
  there may be fine too. Both zones let one parking space count as open
  space where a lot provides at least two; the map can't tell stalls apart,
  so it leaves the result unchecked when that space would make the
  difference. The RD zone lets half the land used for parking count,
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
- **Townhouses in one row.** The ordinance allows at most eight townhouses
  in one building (section 7-1600). In RA, RB, RM, RS, RT, CD and CL no
  special permit can allow more. In the other zones that allow townhouses,
  City Council can allow more with a special permit, so a longer row counts
  as breaking the rules, but no permit can allow a building longer than
  212 ft. A row is every home whose outline shares a wall with the next one
  along, whenever each was built, which is how the ordinance's "single
  structure" reads. Two outlines share a wall when they run together for at
  least 4 ft; rows whose corners meet across an alley stay apart, while
  townhouses built back to back count as one building. Each lot in the row
  counts as one home, except a condo lot, where each building outline counts
  as one. The row's length is the long side of the smallest rectangle around
  it, with 5 ft of slack for the eaves at its two ends. In planned districts
  the approved plan sets this, so only the ordinary-zoning view checks it.
  The pop-up outlines the row's other buildings (up to 40 of them, nearest
  first).

The rules live as plain data in `alx_zoning_illegal_homes/mapper/rules.py`.
They come from Articles III, IV and V of the Zoning Ordinance as amended
through Ordinance 5614 (January 2026), which includes the 2023 "Zoning for
Housing" changes.

The test is always: *if the buildings vanished, could you legally put them
back today?*

### Zones that restrict ordinary homes

The map flags ordinary home uses in I, UT, CR, NR, POS and WPR. NR allows
up to four auxiliary dwellings associated with a commercial use and may
allow townhouses with a special use permit.

### Planned districts

Zones starting with CDD (Cameron Station, Potomac Yard, Carlyle and others)
are planned districts. Each was built under a plan for the whole district,
approved by City Council through a special use permit, and that plan still
governs the land in place of the ordinary zone rules. The ordinance (section
5-602, Table 1) gives two sets of limits for every district:

- **With the approved plan:** which kinds of home are allowed, a maximum
  height, and a cap on homes or floor space across the whole district. Lot
  sizes and ordinary yards are set by the approved site plan drawings. The
  map checks named-street setbacks where the ordinance keeps them in force.
- **Without it:** an ordinary zone's rules (R-8 for Cameron Station, for
  example), sometimes with a changed floor area or height limit.

Homes there are judged by the first set, since that is what a rebuild would
be held to. That means checking home type and height lot by lot, and
reporting each district's home count against its cap. The drawings that
set lot sizes and ordinary yards are unavailable as data, so those checks
are omitted.

Each lot also records how it would fare under the second set, and the map has
a checkbox to switch to that view. It shows how far these neighborhoods are
from what ordinary zoning allows.

Where the city's development-projects layer covers a lot, the lot is tagged
with its case name and number (for example "Cameron Station Phase VI
(DSP2003-00018)") so the actual approval can be looked up. That layer mostly
covers cases from about 2002 on.

In a few districts the ordinary zone depends on where the lot sits, and
those boundaries are approximated:

- Potomac Yard: RB east of the Metro tracks and south of the Monroe Avenue
  bridge; CSL near Route 1; and industrial, which allows no homes, elsewhere.
  The map approximates the Slaters Lane and Piggyback Yard areas on the east
  side of the tracks using the bridge line and shows the CRMU-L option
  there. The Piggyback Yard option requires a special use permit and caps
  development at 275 homes and 50 ft. The map lacks the 1995 rezoning plats
  to narrow these conditions to the Piggyback Yard or to locate the utility
  strip just west of the tracks.
- Route 1 Properties: RB along Reed Avenue, RC within 100 ft of Commonwealth
  Avenue, OC on the rest.
- Duke Street / Carlyle: a looser floor space limit within 1,000 ft of the
  King Street Metro station.
- Eisenhower Avenue Metro: the ordinary height limit is 150 ft on the
  Hoffman Tract and 100 ft elsewhere. The map identifies the tract from
  Hoffman sites in the city's development-projects layer.
- Winkler Tract: the ordinary rules allow up to 100 ft in the area bounded
  by Beauregard Street, Seminary Road, I-395 and Roanoke Avenue, with height
  tied to the distance from the Beauregard curb and a 50 ft minimum
  setback. The map lacks a curb line for this check and uses the RA height
  limits there.
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

- The city’s zoning map supplies the zone covering the most area on each
  lot. The parcel record supplies a fallback where the maps have no area in
  common. A split lot can be subject to more than one zone in practice.
- In RMF, the map applies the by-right floor area limit and estimates the
  residential open space requirement lot by lot. It cannot measure yards or
  height from a governing small area plan, or confirm a permit that allows
  additional floor area for committed affordable housing.

- Condo units are stacked on one polygon in the parcel layer, or drawn as
  small outlines on top of the land they share; either way they are folded
  into one lot.
- The city often draws a whole townhouse row or condo building as a single
  outline across many lots. Such a building is cut along the lot lines so
  each lot is judged on its own part. A piece too small to count as a home
  (a strip left where a lot line runs a few feet inside a building) stays
  with the larger piece it touches, so the building keeps its full outline
  where it meets its neighbor.
- A lot is treated as historic when more than half its area is inside the
  historic districts. The pop-up gives the percentage for lots the boundary
  crosses. This is how the map handles split lots.
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
- Other measurements also get some slack:
  - **Building height:** 5 ft for uncertainty in the city's 3D data and in
    estimating where a sloped roof's eaves are.
  - **Floor space:** 10% because assessment records and the ordinance count
    different kinds of space.
  - **Lot width:** 5% for differences between mapped lot edges and a survey.
  - **Lot size and open space:** 3% for uncertainty in drawing lot boundaries,
    building outlines and paving.
  - **Building coverage:** 3% of the limit for uncertainty in the mapped lot
    and roof outlines.
- Front yards set by the neighbors are measured from building outlines
  traced from roofs, so a porch roof or overhang counts as part of the
  building, for a home and its neighbors alike. A home with a deep porch
  next to homes without one can look closer to the street than it is.
  Corner lots get judged on both streets, as the
  ordinance asks, and fail more often than other lots, mostly along the
  side street. Where the street map changes a street's name partway along a
  lot, the lot is treated as a corner lot.
- The RM and CD zones put a home's front wall at the front lot line, or in
  line with the average of the other buildings on the same side of the block
  when most of them stand back. The map shows that line in the pop-up but
  doesn't judge it: one exact line is more than the map's measurements can
  test, and the map's idea of a block's side ends at any alley.
- On an RM corner townhouse lot, the map counts a lot line as a shared wall
  only where the home and its neighbor both come within 3 ft of it. When a
  home is attached to its neighbor but no lot line runs along their wall
  (the lot lines and outlines are a few feet apart), the yard left over
  isn't judged, and neither is it when every lot line away from the
  streets is a shared wall. A home a few feet in from a lot line beside a
  neighbor still counts that strip as part of the yard left over, as the
  ordinance's words say, so it fails; some of those strips may really be
  a shared wall drawn off its line.
- Townhouse rows are found from building outlines. Outlines more than half a
  foot apart break a row even where the homes may really share a wall, and a
  row the city draws as one outline on one condo lot counts as one home. A
  lot holding several townhouses that isn't a condo counts as one home. Many
  Old Town rows were built a house or two at a time, but where their walls
  are shared the map counts them as one building, as the ordinance's words
  read, so a number of Old Town blocks fail.
- Roads, driveways and parking lots come from the city's planimetric map,
  traced from aerial photos. Patios, small parking pads and paving missing
  from that map still count as open space, so open space can look bigger
  than the ordinance would count it. Many zones also let a landscaped roof
  count, with the planning director's approval, which the map can't see, so
  an apartment building may have more open space than it shows.
- Parking rules are not checked.
- Some rules are left out on purpose; `rules.py` says why beside each one.
  Across zones: threshold height (how high the front door sits), homes per
  acre across a whole development, and anything a special permit or the
  planning commission could loosen. In single zones: the RB zone's lower
  land-per-home minimum on certain urban renewal land, the RT zone's rules
  for a townhouse row as a whole, the KR zone's 150 sq ft of
  open space per home (balconies and roofs count), the extra floor space
  for shops in W-1, CRMU-M and CRMU-H, and the deep setback from Washington
  Street for RC lots along the parkway.
- In Old Town North, section 6-503(D) gives sites in designated retail focus
  areas extra floor space equal to the space required for retail focus uses
  (one-twelfth of the site's allowable floor area ratio). The increase is
  capped at 0.25, and the total at 2.5. The map's zoning data doesn't include
  the designated areas, so it uses the base limit there.
- Floor space comes from the city's assessment records, which seem to count
  only finished living space. The ordinance counts all space under a roof,
  finished or not, attached garages included, so a home's real floor space
  may be somewhat higher than the map shows. Every garage or shed counts
  against the outbuilding allowance, though the ordinance's allowance covers
  only detached garages behind the house, sheds and backyard cottages.
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
- In RM, and for houses and townhouses in CD, the map can't tell which way a
  roof's ridge runs or how steep the roof is, so it can't check whether a
  sloped roof earns the 45 ft limit. The 3D layer's tallest block is
  usually the whole main house, not a thin strip along the ridge, and a
  main house's long side says little about its ridge: many Old Town
  rowhouses run deep from front to back while their ridges run along the
  street. So every home the map takes to have a sloped roof gets 45 ft, and
  its pop-up says it may be held to 35 ft. Flat roofs, as guessed from the
  number of stories, get 35 ft.
- When one owner holds both halves of a twin, each half on its own parcel,
  and the city's outline pokes a little over the line between them, the two
  parcels are joined and judged as one lot with a two-unit house on it. In
  most zones the land and frontage needed come out about the same as for
  two halves, but the map can't tell if one half's own parcel is too small.
- A few hundred home lots are left unchecked because the city's data gives
  them no zone, two zones, or no matching building.
- Variances and special use permits for individual properties are unknown.
- On the height district map, two Old Town North areas need a guess. One
  caps height at 77 ft and the average at 50 ft; the average covers a whole
  block or development, so only the 77 ft cap is checked. Another allows
  50 ft along North Royal Street and 77 ft behind it; how deep that strip
  runs couldn't be found, so every lot with a street edge on North Royal
  Street gets 50 ft. Lots in CDX and the CRMU zones outside the map's
  numbered areas have no height limit the map knows of.
- The rule tying height to distance from the center of the street is
  measured from the city's street centerlines, which trace the middle of
  the pavement. The rule means the middle of the public street, which can
  sit a few feet off it, so the map allows 5 ft of distance (10 ft of
  height) on top of the usual slack for roof overhangs. Where a divided
  road's far side can't be found near a lot, that street isn't measured
  from. Several planned districts the map doesn't check also set this rule
  aside.
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
  (the main source for each lot’s zone)

The Zoning Ordinance is published at
[library.municode.com](https://library.municode.com/va/alexandria/codes/zoning).
That site blocks automated readers, so the rules were first read from the copy
at [zoneomics.com](https://www.zoneomics.com/code/alexandria-VA/chapter_5), then
checked against a saved copy of the ordinance kept as one file per section.
