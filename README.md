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

## What gets checked

Every lot with a home is measured against the rules for its zone. That covers
the residential zones (R-20, R-12, R-8, R-5, R-2-5, RA, RB, RCX, RC, RD, RM,
RS, RT) and homes in the commercial, office and waterfront zones (CL, CC, CSL,
CG, CD, CDX, OC, OCM, OCH, W-1, CRMU, KR) and in planned districts:

- **Lot size**, **lot width** and **street frontage**
- **Side and rear yards**, both the fixed minimum and the deeper yard taller
  buildings need
- **Floor space** compared with lot size
- **Height**
- **Open space** or building coverage
- **Home type**, e.g. townhouses in a zone that allows only houses

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

In Potomac Yard the ordinary zone depends on where the lot sits (near Route
1, east of the Metro tracks, or elsewhere, where it is industrial and allows
no homes); those boundaries are approximated.

### Mixed-use zones

The mixed-use zones (CRMU-L, -M, -H, -X) and the King Street retail zone (KR)
are judged by their limits without a special permit. The ordinance sets few
of those: mainly floor space and open space. Many buildings there were
approved with individual special permits that this project does not know
about, so findings in these zones are the least reliable.

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
That site blocks automated readers, so the rule text was read from the copy at
[zoneomics.com](https://www.zoneomics.com/code/alexandria-VA/chapter_5)
(chapters 4 to 9 there).
