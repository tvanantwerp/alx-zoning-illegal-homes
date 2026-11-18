# Lot drawing pop-up

## Why

The map colors each lot by whether its home could be rebuilt under today's zoning. The side panel lists the reasons in words, such as "Lot is 3,900 sq ft; the R-5 zone requires 5,000." That's accurate but hard to picture. People want to *see* what's wrong: which edge is too short, which yard is too thin, how far the roof goes past the height limit.

This feature adds a pop-up that draws one lot and its buildings in 3D and marks every rule the lot breaks. Next to the drawing is a table of every rule the map checks and how the lot did.

The look was settled through a round of mockups. The chosen one, "Idea F", is published at https://claude.ai/artifact/S5Jtu9NgP6rSkYD9Xi3vH2. Its source is `template.html` in this session's scratchpad. The builder should treat that page as the reference for look and behavior, and reuse its drawing code where it fits.

## Goals

- Show at a glance why a lot fails, drawn on the lot itself.
- Explain every rule in plain words, including why some aren't checked.
- Always agree with the map colors and the side panel.

## Non-goals

- **Front yards that depend on the neighbors.** These are GitHub issue #3. The pop-up shows these rows as "Not checked", with a tooltip saying why.
- **The RM zone's open space rule.** This is GitHub issue #4. Same treatment.
- Satellite imagery or a street map under the drawing. The pop-up shows geometry only.
- Printing, sharing links to a lot, or editing anything.

## Anti-goals

These would make the feature a failure even if it technically worked:

- **The pop-up disagrees with the map or side panel.** For example, a lot colored as passing while its table shows a failure. This is the main risk, and it drives the choice of approach below.
- **The map gets slower to open.** `lots.geojson` is already 16.5 MB. The pop-up's data must load only when someone opens a lot.
- **The drawing looks more exact than the data is.** Building outlines are traced from roofs, and heights are estimated. The pop-up keeps the side panel's caveats and shows the same safety margins the checker uses.

## Constraints

- The site stays static: plain HTML and JavaScript, with no build step. Libraries load from a CDN, as MapLibre does today.
- The data pipeline stays in Python, run with uv.
- Generated data stays out of git, like `site/lots.geojson`.
- Following the project's habit, libraries aren't pinned to exact versions.

## Approaches

**A. The checker records a result for every rule (chosen).** Each check already decides pass or fail and writes a reason. It will also record a structured row for the table. Each row holds the rule, the measured value, what the rule requires, the result, a plain-words explanation, and the shapes needed to draw it. The exporter writes these rows to one small file per lot. The pop-up only draws what it's given.

- *Good:* the result in the table comes from the same line of code that writes the side panel's reason, so they can't disagree. The rules exist only in Python.
- *Cost:* the most Python work. Every check function changes.

**B. The exporter works out the table from the raw measurements (rejected).** This is what the mockup did. It re-derived yard requirements, side-yard counts and width failures outside the checker. That copy drifted from the checker three times while building the mockups:

- a yard judged against the wrong requirement;
- side yards marked "not checked" when they were checked;
- a lot width marked as passing when it failed.

**C. The browser works it out from `lots.geojson` (ruled out).** The map file has no building outlines, heights, or lot-line types. Adding them would make the map's first load much slower.

## What people see

### Opening and closing

- Clicking a checked home lot does two things. It updates the side panel's "Selected lot" as today, and it opens the pop-up. Picking a lot through the address search does the same.
- Lots the map didn't check, such as parks and vacant land, only update the side panel. There's nothing to draw.
- The pop-up closes with its × button, the Escape key, or a click outside it. Focus moves into the pop-up when it opens and back to the map when it closes.
- While the lot's file loads, the pop-up shows the address and a short "Loading…" line. If the file can't be loaded, it says so in plain words and the side panel still works.

### Layout

```
┌───────────────────────────────────────────────────────────────┐
│ 1313 WILKES ST                                             ×  │
│ RM zone · townhouse · Breaks 3 rules                          │
│ [✓] Judge by ordinary zoning instead   (planned districts only)│
├──────────────────────────────┬────────────────────────────────┤
│                              │  Lot size                      │
│    3D drawing of the lot     │  ┌────┐ ┌──────┐               │
│    (drag to spin)            │  │this│ │least │               │
│                              │  │lot │ │allowed               │
│                              │  └────┘ └──────┘               │
├──────────────────────────────┴────────────────────────────────┤
│ Rule          Result   Measured  Rule says  │ Ordinary R-5    │
│ Lot size      FAILS    1,694     ≥ 1,980    │ FAILS ≥ 5,000   │
│ Street front… PASSES   20 ft     ≥ 18 ft    │ FAILS ≥ 50 ft   │
│ …                                                             │
├───────────────────────────────────────────────────────────────┤
│ Notes (same as the side panel)                                │
└───────────────────────────────────────────────────────────────┘
```

On phones the pop-up fills the screen. The drawing sits on top, and the squares and table scroll below it.

### The 3D drawing

As in the mockup:

- The lot is drawn flat, turned so its front faces the viewer. The street name labels the front edge, and other street edges are labeled too.
- Buildings rise to their recorded heights. Homes that break a rule are red, other homes are neutral, and sheds and garages are pale.
- Click and drag to spin. Scroll or pinch to zoom.
- Only broken rules are drawn on the lot:
  - A too-short frontage gets a measurement line that follows the front lot line, curves included.
  - A too-narrow lot gets a width line on the ground, at the depth where width is measured.
  - A too-thin yard gets a shaded strip of the required depth along that edge, plus a line showing the actual gap.
  - A home that's too tall gets a see-through plane at the height limit. The plane appears **only** when height fails.
  - A home with too much floor space, or buildings covering too much of the lot, gets the offending buildings marked, with labels like "2,900 sq ft of 2,400 allowed".
- Hovering or focusing a table row highlights its parts of the drawing.

### Lot size squares

There are two squares drawn to scale: this lot's area and the smallest lot the rules allow. The second square is red when the lot is too small. The block is hidden when the zone has no minimum lot size.

### The rules table

There is one row per rule the map checks, in this order:

1. lot size
2. street frontage
3. lot width
4. each yard (front, left side, right side, rear)
5. floor space
6. height
7. land covered by buildings, or open space
8. home type

The columns are Rule, Result, Measured, Rule says, and a small bar comparing the two.

The result is one of five labels:

- **Fails**
- **Passes**
- **Not checked:** the rule applies, but the map can't judge it yet.
- **No rule:** this zone has no such limit for this kind of home.
- **Not required:** for example, a side that shares a wall with the house next door.

Every label except Fails and Passes has a tooltip giving the reason for *this* lot, in plain words. The mockup's tooltips are the starting text:

- front yards that depend on the neighbors;
- the RM open space rule;
- corner lots having no rear yard;
- odd-shaped lots with no clear back edge;
- shared walls;
- the RM and historic RB side-yard rule, which depends on lot width;
- no street found next to the lot.

"Street frontage" itself has a tooltip explaining that it's the length of the front lot line, and how it differs from lot width.

Under the table come the lot's notes, the same ones the side panel shows.

### Planned districts

About 1 in 6 checked lots are in planned districts, like Cameron Station and Potomac Yard. They're judged by their special approval unless the map's "Judge them by ordinary zoning instead" box is ticked.

- **One switch, shared everywhere.** The pop-up header repeats that checkbox for planned-district lots. Both boxes are views of one setting. Ticking either one:
  - ticks the other;
  - recolors the map;
  - refreshes the side panel;
  - redraws the open pop-up's table, highlights and height plane.

  People can switch without leaving the pop-up.
- **The main table follows the switch.** Under the special approval, lot size and yards read "Not required here", with a tooltip saying the approved site plan sets them. Under ordinary rules, the table looks like any other lot's.
- **An extra column always shows the ordinary zone.** For planned-district lots, the table gets one more column headed "Ordinary R-5 zone" (named for that lot's fallback zone). Each row shows the ordinary zone's result label and what that rule says. Readers can always compare the two without flipping the switch. Other lots don't get this column.
  - *My call, for you to check:* when the switch is set to ordinary rules, the main columns already show the ordinary zone. The extra column would then repeat them, so it switches to "Special approval" and shows that instead. That way the table always shows both sides. If you'd rather it stay fixed on the ordinary zone, that's a one-line change.
- On phones, the extra column replaces the bar column to save room.

## How it's built

### 1. The checker records a row per rule

In `alx_zoning_illegal_homes/mapper/checks.py`, `Findings` gains a list of rule results alongside `reasons`, `notes` and `measurements`. Each result says:

- which rule it is, as a short fixed id like `lot_area`, `frontage`, `width`, `yard:left` or `height`;
- its name, as the table shows it;
- its result: fails, passes, not checked, no rule, or not required;
- the measured value and the required value, with units, and whether the requirement is a minimum or a maximum;
- an explanation for the tooltip, written in Python in plain words, or none;
- the shapes needed to draw it, in the lot's own coordinates (feet):
  - for frontage, the front lot line pieces;
  - for width, the two ends of the width line and how far back it's measured;
  - for a yard, the two nearest points on the home and the lot line, plus the strip of required yard;
  - for height, the limit;
  - for floor space and coverage, which buildings count.

Each check function records its rows where it already decides pass or fail. A row is "fails" exactly when that check writes a reason. A test makes sure this holds.

The yard check is where the mockup went wrong most. The row must use the same requirement `_judge_yard` uses: the zone's minimum unless the home is tall enough for the height-based figure to apply. It must use the same 2 ft margin too.

One more trap: on lots where width is measured right at the street, the checker folds a too-narrow width into the frontage reason. In that case both the frontage row and the width row must read "fails".

Row ids are fixed strings, so a row can be matched to its counterpart in the other result set for planned-district lots.

### 2. Two result sets for planned-district lots

`analyze()` already runs the checker twice for planned-district lots, once under the approval and once under the ordinary zone. Both runs' rule rows are kept. Rows under the approval that don't apply, like lot size and yards, are recorded as "Not required here" with the site-plan explanation, not left out.

### 3. The exporter writes one file per lot

`export()` in `main.py` also writes `site/lots/<id>.json` for every checked home lot, about 22,000 files. The folder is emptied first, so no stale files are left behind, and it's added to `.gitignore`.

- **The id** is the lot's row number from `analyze()`. It's added to each feature in `lots.geojson` as a short `id` property, so the map knows which file to fetch. That's the only change to the map file.
- **Contents:**
  - the lot outline;
  - its edges, each with its type (street, shared, open), street name and whether a home wall sits on it;
  - the buildings, with outline, height, floor space, whether each is a home, and whether it's the main home;
  - the rule rows;
  - for planned-district lots, the second set of rule rows and the fallback zone's name;
  - the notes.
- **Coordinates** are moved and turned so the lot's center is at zero and its front faces down the page. They're rounded to 0.1 ft. The browser doesn't need to know about turning.
- **Size** is about 3–9 KB per lot, or roughly 100–200 MB on disk in total. Only one file loads per click.

`analyze(keep_facts=…)` already hands back the lot facts the exporter needs for outlines and edges.

### 4. The pop-up in the site

The pop-up lives in a new `site/lot-drawing.js`, loaded by `index.html` as a module. Its styles match the existing page: paper background, ink text, the accent red, and the Iowan Old Style serif.

- **Three.js** loads from a CDN through an import map, since its current releases come only as modules. Following the project's habit, it isn't pinned to an exact version. Three.js releases are all numbered 0.x, though, so this means always the latest. The drawing should stick to long-standing parts: basic shapes, extruded outlines, simple materials, and the orbit controls add-on.
- **One drawing at a time.** Opening a new lot replaces the old drawing, and closing the pop-up frees its graphics memory.
- **No rules in JavaScript.** The table, labels and tooltips come straight from the file. The browser only formats numbers and draws.
- **The shared switch.** `index.html` gets one function that sets the "ordinary rules" setting. It updates both checkboxes, the map colors, the side panel and the open pop-up. Both checkboxes call that function.

### 5. Tests

- **Python**, in `tests/test_checks.py`, using the existing small hand-made lots:
  - each result label shows up where expected (a failing yard, a shared wall marked not required, a corner lot with no rear yard, an RM lot under 25 ft wide needing no side yards);
  - for every test lot, the failing rows match the reasons;
  - for a planned-district lot, both result sets are present.
- **Exporter:** a test writes the files for a couple of lots into a temporary folder. It checks they're valid JSON with the expected parts and that the coordinates are centered and turned.
- **In the browser:** open the five mockup lots and one planned-district lot in a headless browser, take screenshots and check there are no console errors. The five lots are 1704 OAKCREST DR, 2804 DAVIS AVE, 1607 WALLESTON CT, 1313 WILKES ST and 425 QUEEN ST. Then flip the switch from inside the pop-up and check that the map's checkbox, the map colors and the table all change.

## Left to the builder

- Exact field names in the per-lot files.
- How labels avoid overlapping in the drawing, and the camera's starting angle.
- Exact phone breakpoints.
- Whether the lot-size squares sit beside or above the drawing on mid-size screens.
- Small wording changes to tooltips, as long as they stay plain and specific to the lot.
