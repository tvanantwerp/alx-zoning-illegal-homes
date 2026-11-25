# Permits and approvals: design

## Why

Many rows on the map end with "the map has no record of special permits, so it
can't tell…". Examples include homes near Eisenhower Avenue, townhouse rows
longer than eight homes, extra height or floor space by special permit,
undersized older lots (sections 12-401 and 12-402), lots without public street
frontage (section 7-1007, issue #87), and CRMU developments judged as one tract
(section 1-400(B)(3)(c), issue #117). The city does publish records of these
approvals. Collecting them lets the map:

1. show every permit, variance and site plan on file for a lot, with a link to
   the city's documents, and
2. settle a "may pass, if a permit was granted" row when a matching permit is
   found.

The user wants every permit we can find, the relevant documents downloaded so
the web page can link straight to them, and the processing code to merge permits
with the GIS data on every build, so nothing gets lost when the city's data
changes.

## Goals

- Collect every special use permit (SUP), Board of Zoning Appeals variance
  (BZA), and development site plan (DSP and DSUP) the city publishes.
- Keep a permanent, committed list of every case ever seen. A case that later
  drops out of the city's data stays on our list.
- Attach each case to the lots it covers.
- Download the documents for cases attached to a checked home lot, keep them
  out of git, and link the site to the city's originals.
- When a case clearly grants what a rule needs, show that rule as "permit on
  file" (counts as passing, keeps the case on show, links the document).
- Show every attached case in the lot pop-up, whether or not it settles a rule.

## Non-goals

- Reading the full text of every permit to work out its exact conditions.
  Matching uses the case description and the document's index fields, plus a
  hand-checked list of corrections.
- City Council and Planning Commission agenda PDFs (dockets). They're a possible
  later source for cases missing from the archive.
- Homeowners-association land (the city's "Common Ownership Areas" layer),
  subdivision plats and rezoning proffers. These are useful for #88, #117 and
  older-lot dates, but they're separate pieces of work.

## Anti-goals

- **Never treat "no permit found" as proof there's no permit.** The records
  have gaps: years with almost nothing, and older cases lumped together. A
  missing permit leaves a row exactly as it is today.
- **Never turn a failing row into a pass on a weak match.** A permit for a
  restaurant on the ground floor doesn't excuse the apartments' height. When
  unsure, list the case in the pop-up and leave the row alone.
- **Never overload the city's servers.** Crawl slowly, cache everything, and
  only fetch what's new on later builds.

## What the city publishes (found Nov. 24, 2026)

| Source | What it holds | Access |
|---|---|---|
| Special use permit layer (`geoportal.alexandriava.gov/.../Special_Use_Permits/FeatureServer/0`, same as `maps.alexandriava.gov/.../alxSUPWm/MapServer/1`) | 926 approved SUPs as points: case number, short description, address, link to documents | ArcGIS query, GeoJSON |
| Development projects layer (`alxPlanningDevelopmentWm/MapServer/0`) | 444 site plan outlines (DSP, DSUP) with names and case numbers | Already downloaded as `Development_Projects` |
| City document archive (Laserfiche WebLink, `imaging.alexandriava.gov/weblink7PZSUP/`) | Scanned documents tagged with the "Land Development" fields: case number, document type, address number and street, project number and name, master case, parcel ID, applicant | Searchable by case number with wildcards (`SUP*` gives about 812 result pages, `BZA*` about 262). Needs a cookie session. Each document has a page viewer and a PDF export (`GeneratePDF.aspx`). |

The archive is the fullest source. The SUP layer is a small, located subset of it.

## Approaches considered

1. **Use the SUP layer only.** It's simple and already has locations. But it
   holds only 926 cases, mostly businesses, with no variances and big gaps by
   year. Too thin to answer most of the open questions.
2. **Crawl the document archive as well, and merge it with the GIS layers
   (chosen).** It covers far more cases, including variances, and carries
   parcel IDs and addresses for matching. It costs a polite, resumable crawler
   and a matching step.
3. **Also read every City Council docket PDF.** That gives the best coverage
   of old cases, but parsing decades of agenda PDFs is a large job with a lot
   of guesswork. Left for later, if the archive turns out to miss cases we care
   about.

The user left the choice of approach to me, and I picked approach 2.

## Design

### 1. Collecting cases (new `downloader/permits.py`)

- **Layers:** add the SUP layer to `files.json` as GeoJSON (it uses the same
  paged download as other layers). `Development_Projects` is already there.
- **Archive crawl:** run wildcard searches by case number (`SUP*`, `BZA*`,
  `DSUP*`, `DSP*`, plus the older spellings the archive turns up) and walk every
  result page. For each document, record its id, page count, and template
  fields (case number, document type, address number and street, parcel ID,
  project name, master case, applicant).
- **Being polite:** use one session with cookies, wait about one second between
  requests, and use a plain project user agent with no personal details. Save
  each result page so an interrupted crawl picks up where it stopped. On
  later builds, re-walk only the newest pages and look up any case in the
  layers that the catalog doesn't have yet.
- **Raw cache:** `data/permits/raw/`, git-ignored like the rest of `data/`.

### 2. The permanent catalog (committed)

`alx_zoning_illegal_homes/permits/catalog.jsonl` has one line per case:

- case number (normalized, e.g. `SUP2005-00035`) and kind (`SUP`, `BZA`, `DSP`, `DSUP`)
- description(s), addresses, parcel IDs, project name, master case, applicant
- status (where known), year
- document ids, with page counts and document types
- where it came from (layer or archive), plus first seen and last seen dates
- the location used for matching (a point or outline, with how it was found)

Each build merges the new data into the catalog. Fields are filled in, never
blanked. A case missing from today's data keeps its line, and its "last seen"
date shows it dropped out. The file is sorted by case number so diffs stay
readable. This is how nothing gets lost.

`alx_zoning_illegal_homes/permits/overrides.json` is also committed: hand-made
corrections, such as "this case covers these parcels", "this case grants this
rule", "ignore this case", each with a short source note. It follows the same
pattern as `TOWNHOUSE_DEVELOPMENTS` in `analyze.py`.

### 3. Matching cases to lots

In order of trust:

1. **Parcel ID** from the archive, matched against the parcel layer's map,
   block and lot number (`PID_RE` and its parts).
2. **Outline:** a site plan outline covering the lot's point, as `_project_for`
   does today. Every overlapping case is kept, not just the smallest.
3. **Address:** the archive's or the SUP layer's address, normalized the way
   the parcel layer writes addresses (`ST_NUM`, `ST_NAME`, `ST_TYPE`, the old
   "JEFFERSON DAVIS HY" spelling of today's "RICHMOND HWY", and so on).
4. **SUP layer point** inside a parcel.

Each match records how it was made. A case can cover many lots. A lot can have
many cases.

### 4. Deciding which rule a case settles

Each case gets zero or more rule tags, matched from its description and
document type by plain keyword rules in one table that's easy to read:

| Tag | Settles | Example wording |
|---|---|---|
| `undersized_lot` | lot size, width and frontage on undersized older lots (sections 12-401, 12-402) | "substandard lot", "undersized lot" |
| `no_frontage` | frontage on a private-street lot (section 7-1007) | "without frontage", "private street" |
| `townhouse_row` | rows of more than eight townhouses | "more than eight townhouses" |
| `homes_near_eisenhower` | homes near Eisenhower Avenue | residential use in the OCM(100) or OCH zones near Eisenhower |
| `extra_height` | height above the plain limit, up to the permit limit | "increase in height", "height" |
| `extra_floor_area` | floor space above the plain limit, up to the permit limit | "increase in FAR", "floor area ratio" |
| `tract` | CRMU floor space and density judged across the development (#117) | "tract", "development special use permit" in a CRMU zone |
| `variance:<rule>` | the named yard, height or floor space rule on that lot (BZA) | "variance … side yard", "rear yard", "front yard" |

Then:

- A row whose rule matches a tag on one of the lot's cases, and which today is
  "fails" or "may pass" only because a permit might exist, becomes **"permit on
  file"**. That's a new status like `older_lot`: it counts as passing, keeps the
  measured shortfall on show, and names and links the case.
- A permit can't lift a building past the ordinance's upper limit for that
  permit (for example the longest townhouse row any permit allows, or the
  height ceiling a special permit can reach). Those rows still fail, and the
  note says a permit is on file.
- Cases with no matching tag are still listed in the pop-up under "Permits and
  approvals on file".
- Overrides win over keyword tags.

### 5. Documents on the site

- For every case attached to a checked home lot, export **every** document
  filed under that case number to PDF, once (the user's choice).
- **Storage (the user's choice): download the PDFs but keep them out of git.**
  They live in `data/permits/pdf/<case number>/<document id>.pdf`. That folder
  is already git-ignored, since all of `data/` is. Builds only add files, never
  delete them. A PDF stays even if its case later stops matching a home lot or
  drops out of the city's archive. This local copy is a backup and something
  later tools can read. The site doesn't serve it.
- **The site links to the city's originals.** Each case in a lot file carries
  the city's document viewer link for each of its documents, plus a search link
  for the whole case number. Nothing is copied into `site/`.
- The committed catalog keeps every document id. If the city ever moves its
  archive, links can be rebuilt from the catalog, and the local PDFs are the
  fallback.
- The lot file (`site/lots/<id>.json`) gets a `permits` list: case number,
  kind, description, year, how it was matched, and the city's document links.
  `lots.geojson` gets a short `permits` count so the map can filter on it later.

### 6. Pop-up

A "Permits and approvals" section under the rules table lists each case: its
number (linked to the city's document), kind, year and one-line description, and the rule
it settles if any. A "permit on file" row in the rules table links to the same
case.

## Constraints

- Follow the project's existing patterns: `files.json` for layers,
  `loader.py` for reading, `analyze.py` for joining to lots, the status
  constants in `rule_results.py`, `lot_files.py` for per-lot output, and plain
  wording in explanations.
- Python with uv and the `requests` library already in use. No new heavy
  dependencies.
- The crawl must work outside the sandbox. Network to `imaging.alexandriava.gov`,
  `geoportal.alexandriava.gov` and `maps.alexandriava.gov` is needed.
- Tests use small saved copies of archive pages and layer responses. No
  network in tests.

## Left to the builder

- The exact request the archive needs for a PDF export (`GeneratePDF.aspx`),
  worked out from the viewer's script. This is the first spike. Since the site
  links to the city's originals anyway, the map doesn't depend on it. If the
  export needs a browser, skip the local copies and say so.
- The full list of wildcard prefixes. Start from the case numbers the SUP and
  site plan layers use.
- Keyword wording for each tag, tuned against the real descriptions.
  Every tag gets a test with real examples that should and shouldn't match.
- How the pop-up section looks, following the existing pop-up styles.

## Decisions made by the user

- Collect every permit we can find, and download the relevant documents so the
  site can link straight to them.
- Merge the permits with the GIS data on every build, so nothing gets lost.
- Download the PDFs into the git-ignored `data/` folder, and link the site to
  the city's originals. This keeps the repo small. An earlier idea, committing
  them with Git LFS, was dropped for this reason.
- Download every document filed under a relevant case, not just the decision
  documents.

## Calls I made (check these)

- The archive crawl, merged with the two map layers, is the main source.
  Council dockets come later, if needed.
- Variances (BZA) count as permits.
- New status "permit on file" counts as passing and keeps the shortfall shown.
- A permit never lifts a building past the ordinance's ceiling for that permit.
- The catalog is JSON lines, sorted by case number, only ever added to.
- Homeowners-association land, plats and proffers are separate pieces of work.
