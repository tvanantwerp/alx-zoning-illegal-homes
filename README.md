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

- **Lot size**, **lot width** and **street frontage**
- **Side and rear yards**, both the fixed minimum and the deeper yard taller
  buildings need
- **Floor space** compared with lot size. In the KR and OCH zones the limit
  is looser within 1,000 ft of a Metro station.
- **Height**
- **Open space** or building coverage. The RM zone asks for 35% of the lot
  and never less than 300 sq ft. It also lets a lot keep the open space it
  had on June 24, 1992 if that was less, which the map can't know, so an
  older RM home may be fine as it stands.
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
  each lot is judged on its own part.
- Lots that one owner has built a single house across are joined.
- Homes that share a wall (twins, townhouses) are not expected to have a yard
  on that side. Rows of three or more attached homes are treated as
  townhouses whatever the assessor's label says.

## Limits

- "Illegal" means *could not be permitted as new construction*. The ordinance
  lets these older buildings stay, and be rebuilt as they were.
- Measurements come from public map data, not surveys. Every check leaves a
  margin, but any single finding can be wrong. Yard findings are the least
  certain: building outlines are traced from roofs, and lot lines and
  buildings come from different sources. A home drawn touching or crossing a
  lot line is assumed to be a mapping error and its yards are skipped.
- Front yards are mostly not checked. In most zones the rule depends on the
  neighbors' front yards, which an existing home meets almost by definition.
  RC, RCX, RD and KR require no front yard at all, nor does W-1 for
  apartment buildings, though the extra
  street setbacks along Duke Street, King Street and four other streets
  (section 7-1006) aren't checked yet.
- Open space is all the land not under a building outline. Driveways,
  patios and parking pads aren't in the data, so open space looks bigger
  than the ordinance would count it.
- Parking rules are not checked.
- Height comes from the city's 3D building layer and floor space from the
  city's building records; neither matches the ordinance's definitions
  exactly.
- A few hundred home lots are left unchecked because the city's data gives
  them no zone, two zones, or no matching building.
- Variances and special approvals for individual properties are unknown.

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
- [Zoning Map](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::zoning/explore) and
  [Height Districts](https://cityofalexandria-alexgis.opendata.arcgis.com/datasets/AlexGIS::height-districts/explore)
  (downloaded but not yet used; zoning comes from the parcel layer)

The Zoning Ordinance is published at
[library.municode.com](https://library.municode.com/va/alexandria/codes/zoning).
That site blocks automated readers, so the rules were first read from the copy
at [zoneomics.com](https://www.zoneomics.com/code/alexandria-VA/chapter_5), then
checked against a saved copy of the ordinance kept as one file per section.
