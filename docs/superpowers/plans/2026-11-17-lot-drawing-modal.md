# Lot Drawing Pop-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a checked home lot on the map opens a pop-up. It shows the lot and its buildings in 3D, every broken rule drawn on it, and a table of every rule and how the lot did.

**Architecture:**

- The Python checker records one `RuleResult` per rule as it checks. Each holds the result, the numbers, a plain-words explanation, and the shapes to draw.
- `analyze()` keeps those results for each lot. For planned-district lots it keeps two sets: one under the special approval, one under the ordinary zone.
- A new exporter writes one JSON file per lot to `site/lots/`. The file is already turned so the street is at the bottom.
- The site loads that file on click. A small set of ES modules renders it with Three.js. The browser holds no zoning rules.

**Tech Stack:**

- Python 3.11+ with shapely and geopandas, run with uv. Tests use pytest.
- Plain HTML and ES modules, with no build step.
- MapLibre GL 5 (already used) and Three.js through an import map from unpkg, not pinned to an exact version.
- `node --test` for the pure JavaScript modules. It needs no packages.

**Spec:** `docs/superpowers/specs/2026-11-17-lot-drawing-modal-design.md`. The mockup it refers to is saved at `docs/superpowers/specs/2026-11-17-lot-drawing-mockup.html`. Open it over http and pick "F" to see the target. Its script holds the drawing code to port: `frontTrace`, `build3D`, `lotSquares`, `reportTable`, `showTip`.

## Global Constraints

- Static site only: no bundler and no `package.json` dependencies. Libraries come from a CDN without an exact version (`maplibre-gl@5` is the pattern; Three.js is `three` with no version).
- Python commands run through uv. In the sandbox, prefix them with `UV_CACHE_DIR="$TMPDIR/uv-cache"`.
- `site/lots/` and `site/lots.geojson` are generated and git-ignored.
- `lots.geojson` gains only one new property, `id`, and only on checked lots.
- Coordinates in lot files are in feet, centered on the lot, and turned so the street is at the bottom (−y) and the lot runs up (+y). "Right" is +x, as seen standing in the street facing the lot. They're rounded to 0.1 ft.
- Result labels: `fails`, `passes`, `not_checked`, `no_rule`, `not_required`. The table shows them as FAILS, PASSES, NOT CHECKED, NO RULE, NOT REQUIRED.
- A rule row is `fails` exactly when the checker wrote a matching reason. Reasons and their wording don't change.
- Height plane: drawn only when the height row is `fails`.
- All user-facing text is plain words, with no section numbers or jargon. Docstrings are preferred over inline comments.
- On phones (≤ 640 px wide) the pop-up fills the screen, and the extra planned-district column replaces the bar column.

## Review Focus

1. **The lot file is missing or fails to load**, for example when `lots.geojson` is newer than `site/lots/`. The pop-up should say so in plain words, and the side panel should still work. *Test: Task 8, step 6.*
2. **A lot with no street found** has no front line and no turning direction. The exporter should still write a file without turning it. The drawing should render, and frontage, width and yards should read NOT CHECKED. *Test: Task 5, `test_lot_without_street_is_written_unturned`.*
3. **A lot or building made of several pieces, or with a hole.** Every piece must be written and drawn. *Test: Task 5, `test_multipart_lot_keeps_every_piece`.*
4. **Clicking a second lot before the first lot's file has loaded.** The pop-up must end up showing the second lot only. *Test: Task 8, step 6.*
5. **A phone-width screen (375 px) with a planned-district lot open.** There must be no sideways page scroll, and the extra column must show in place of the bars. *Test: Task 9, step 3.*

---

### Task 1: Rule results for home type, lot size, frontage and width

**Files:**
- Create: `alx_zoning_illegal_homes/mapper/rule_results.py`
- Modify: `alx_zoning_illegal_homes/mapper/checks.py` (`Findings`, `check_lot`, `_check_home_type`, `_check_lot_area`, `_check_width_and_frontage`)
- Modify: `alx_zoning_illegal_homes/mapper/lot_lines.py` (add `lot_width_line`; `lot_width` uses it)
- Test: `tests/test_rule_results.py` (new), `tests/test_lot_lines.py`

**Interfaces:**
- Produces, in `rule_results.py`:

```python
FAILS, PASSES, NOT_CHECKED, NO_RULE, NOT_REQUIRED = (
    "fails", "passes", "not_checked", "no_rule", "not_required")

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

RULE_IDS = ("lot_area", "frontage", "width", "yard:front", "yard:left", "yard:right",
            "yard:rear", "yard:nearest", "floor_area", "height", "coverage",
            "open_space", "home_type")

def reason_kind(rule: str) -> str
    """The Reason.kind a failing row of this rule goes with."""
    # lot_area->lot_size, frontage/width->lot_width, yard:*->yards,
    # coverage/open_space->open_space, others map to themselves.
```

  This file also holds the explanation texts as constants and small functions, so the checks stay readable. See step 3.

- Produces, in `checks.py`: `Findings.results: list[RuleResult]`, filled by `check_lot` in `RULE_IDS` order (yards come in Task 2, the rest in Task 3).
- Produces, in `lot_lines.py`: `lot_width_line(lot, lines: LotLines, distance_back: float) -> LineString | None`. This is the straight line between the two ends of the trace `distance_back` feet in from the front line. It returns None when there's no front, when `distance_back <= 0`, or when the lot is too shallow. `lot_width` returns `lines.frontage` when `distance_back <= 0`, otherwise `lot_width_line(...).length`, unchanged in behavior.

- [ ] **Step 1: Write the failing tests**

In `tests/test_rule_results.py`, reuse the `check` and `between_neighbors` helpers. Move them from `tests/test_checks.py` into `tests/helpers.py` and import them in both test files, so they aren't copied twice.

```python
def rows(findings):
    return {r.rule: r for r in findings.results}

def test_lot_rows_on_a_small_narrow_lot():
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide, R-8
    _, findings = check(lot, box(10, 35, 30, 65), "R-8", neighbors=between_neighbors(lot))
    r = rows(findings)
    assert r["lot_area"].status == FAILS and r["lot_area"].measured == 4000
    assert r["lot_area"].required == 8000 and r["lot_area"].unit == "sq ft"
    assert r["width"].status == FAILS and r["width"].required == 65
    assert r["width"].detail == "measured 30 ft back"   # R-8 width_measured_at
    assert r["width"].shapes["line"].length == pytest.approx(40, abs=0.5)
    assert r["frontage"].status == PASSES and r["frontage"].required == 40
    assert "front lot line" in r["frontage"].about
    assert r["home_type"].status == PASSES
    assert r["home_type"].summary == "detached house allowed in the R-8 zone"

def test_townhouse_in_house_zone_fails_home_type():
    lot = box(0, 0, 80, 120)
    _, findings = check(lot, box(20, 35, 60, 75), "R-8", home_type="townhouse")
    assert rows(findings)["home_type"].status == FAILS

def test_zone_without_lot_size_rule_says_no_rule():
    lot = box(0, 0, 80, 120)
    zone = next(z for z, rules in ZONES.items() if "single" in rules.allowed and not rules.lot_area.get("single"))
    _, findings = check(lot, box(20, 35, 60, 75), zone)
    row = rows(findings)["lot_area"]
    assert row.status == NO_RULE and "minimum lot size" in row.explanation

def test_no_street_leaves_frontage_and_width_unchecked():
    lot = box(0, 0, 80, 120)
    facts = LotFacts(shape=lot, area=lot.area, rules=ZONES["R-8"], home_type="single",
                     homes=[Home(shape=box(20, 35, 60, 75), height=20, floor_area=1000)],
                     lines=classify(lot, None, [], None), all_buildings=[box(20, 35, 60, 75)])
    r = rows(check_lot(facts))
    assert r["frontage"].status == r["width"].status == NOT_CHECKED
    assert "public street" in r["frontage"].explanation

def test_failing_rows_match_reasons_for_lot_rules():
    lot = box(0, 0, 40, 100)
    _, findings = check(lot, box(10, 35, 30, 65), "R-8", neighbors=between_neighbors(lot))
    failing = {reason_kind(r.rule) for r in findings.results if r.status == FAILS}
    assert failing == {reason.kind for reason in findings.reasons}
```

In `tests/test_lot_lines.py`:

```python
def test_width_line_sits_the_measuring_depth_back():
    lot = box(0, 0, 60, 100)
    lines = classify(lot, None, [MAIN], "MAIN")   # MAIN runs along y = -25
    line = lot_width_line(lot, lines, 25)
    assert line.length == pytest.approx(60, abs=0.5)
    assert all(y == pytest.approx(25, abs=0.5) for _, y in line.coords)
    assert lot_width_line(lot, lines, 0) is None
```

Use whatever street helper `tests/test_lot_lines.py` already has, if it has one.

- [ ] **Step 2: Run the tests and check they fail**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest tests/test_rule_results.py tests/test_lot_lines.py -q`
Expected: they fail with an ImportError (`rule_results`, `lot_width_line`).

- [ ] **Step 3: Write `rule_results.py` and the rows for these four rules**

How each row works:

- **`home_type`:** `name="Home type"`. `summary` is `f"{type name} allowed in the {rules.label}"`, or `"… not allowed in …"` when it fails. When the unit cap fails, use `f"{units} homes in one building; the {rules.label} allows {max}"`.
- **`lot_area`:** `name` is `"Lot size"`, or `"Land per home"` when it's measured per home. `measured` is the area or the area per home. `required` is the table value. NO_RULE when that's empty, with `explanation=no_rule_explanation(rules.label, type name, "minimum lot size")`.
- **`frontage`:**
  - `name="Street frontage"`.
  - `measured=lines.frontage`.
  - `required` is `need_frontage`.
  - `shapes={"line": lines.front_line}`.
  - `about=frontage_about(street, label, required, width_measured_at)`.
  - NOT_CHECKED when there's no front, with `NO_STREET`.
  - NOT_CHECKED with `SHARED_LOT` when several townhouses share one lot.
  - NO_RULE when `required` is empty.
- **`width`:**
  - `name="Lot width"`.
  - `detail=f"measured {_feet(at)} back"` when `width_measured_at > 0`, otherwise `"measured at the street"`.
  - `shapes={"line": lot_width_line(...)}` when there is one.
  - NOT_CHECKED with `NO_STREET` or `SHARED_LOT`, as for frontage.
  - NOT_CHECKED with `TOO_SHALLOW` when the width is None.
  - NO_RULE when `need_width` is empty.

Every status comes from the same `if` that appends the reason. Don't test the numbers a second time.

Explanation texts, copied as they are written here:

```python
NO_STREET = ("The map couldn't find a public street next to this lot, so it "
             "can't tell which edge is the front.")
SHARED_LOT = ("Several homes share this one lot, so no single home has lot "
              "lines of its own to measure.")
TOO_SHALLOW = ("The lot is shallower than the depth where this zone measures "
               "width, so the map couldn't measure it.")

def no_rule_explanation(zone_label: str, home_type_name: str, what: str) -> str:
    return f"The map's rules for the {zone_label} include no {what} for a {home_type_name}."

def frontage_about(street: str, zone_label: str, required: float | None,
                   width_measured_at: float) -> str:
    """Explain street frontage for this lot (the tooltip on the rule's name)."""
```

`frontage_about` produces this text:

> How much of the lot touches the street: the length of the front lot line along {street}, following any curve.

When `required` is set, it adds:

> The {zone_label} requires at least {required} ft.

When `width_measured_at > 0`, it adds:

> This is a separate rule from lot width, which is measured in a straight line across the lot {width_measured_at} ft back from the street, where the front yard ends. A lot can pass one and fail the other, as on a cul-de-sac, where lots are narrow at the street and widen further back.

Otherwise it adds:

> In this zone, lot width is also measured right at the street, so here the two rules measure the same line.

- [ ] **Step 4: Run the full test suite and check it passes**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q`
Expected: every test passes, the old ones included.

- [ ] **Step 5: Commit**

```bash
git add alx_zoning_illegal_homes/mapper/rule_results.py alx_zoning_illegal_homes/mapper/checks.py alx_zoning_illegal_homes/mapper/lot_lines.py tests/
git commit -m "Record a result for home type, lot size, frontage and width"
```

---

### Task 2: Rule results for yards

**Files:**
- Modify: `alx_zoning_illegal_homes/mapper/checks.py` (`_yard_gaps`, `_check_yards`, `_judge_yard`, `_check_yards_without_front`)
- Modify: `alx_zoning_illegal_homes/mapper/rule_results.py` (yard explanation texts)
- Test: `tests/test_rule_results.py`

**Interfaces:**
- Consumes: `RuleResult` and the status constants from Task 1.
- Produces: four rows, `yard:front`, `yard:left`, `yard:right` and `yard:rear`, on every lot with a known front. Names are "Front yard", "Left side yard", "Right side yard" and "Rear yard". Lots with no front get these four as NOT_CHECKED (`NO_STREET`), plus `yard:nearest` ("Closest lot line") when the fallback check runs.
- Each judged yard row has:
  - `measured`: the gap in feet;
  - `required`: what the home needs;
  - `detail`: `"needs"` or `"a home this tall needs"`;
  - `shapes={"gap": LineString(nearest point on home, nearest point on lot line), "strip": required-depth strip along that side's lot lines, clipped to the lot}`.
- Internal: `_yard_gaps(facts, home) -> tuple[dict, set]`. The dict maps a key (-1, +1, "rear", "front") to a `YardGap(gap: float, on_open: bool, nearest: LineString, lines: list[LineString])`. The set holds the side keys that share a wall.
- Internal: `_judge_yard(record, name, label, gap, credited_gap, yard, height) -> tuple[bool, float, str]`. It returns (fails, required ft, detail) and still calls `record` exactly as now when the yard fails.
- Internal: `_side_name(facts, key) -> "left" | "right"`. Key k is "right" when `k * (front_direction @ (inward_y, -inward_x)) > 0`. That's right as seen standing in the street facing the lot, which is +x in the lot files.

- [ ] **Step 1: Write the failing tests**

```python
def test_side_yard_too_small_is_drawn_on_the_correct_side():
    lot = box(0, 0, 80, 120)               # street to the south, so +x is right
    _, f = check(lot, box(3, 35, 43, 75), "R-8", neighbors=between_neighbors(lot))
    r = rows(f)
    assert r["yard:left"].status == FAILS and r["yard:left"].measured == pytest.approx(3)
    assert r["yard:left"].required == 8 and r["yard:left"].detail == "needs"
    assert r["yard:right"].status == PASSES
    assert r["yard:left"].shapes["strip"].bounds[0] == pytest.approx(0)
    assert r["yard:left"].shapes["strip"].bounds[2] == pytest.approx(8)

def test_tall_home_row_says_height_drives_the_yard():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(11, 35, 51, 75), "R-8", neighbors=between_neighbors(lot), height=34)
    row = rows(f)["yard:left"]
    assert row.status == FAILS and row.detail == "a home this tall needs" and row.required > 11

def test_shared_wall_side_is_not_required():
    # reuse the setup from test_shared_walls_are_not_missing_side_yards
    ...
    assert rows(f)["yard:left"].status == NOT_REQUIRED      # whichever side is attached
    assert "shares a wall" in rows(f)["yard:left"].explanation

def test_corner_lot_has_no_rear_yard_row_checked():
    # lot with streets on the south and west (add a second street, e.g. ("SIDE", LineString([(-25,-300),(-25,500)])))
    ...
    assert rows(f)["yard:rear"].status == NOT_CHECKED
    assert "corner lot" in rows(f)["yard:rear"].explanation

def test_front_yard_not_checked_in_contextual_zone():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(20, 35, 60, 75), "R-8", neighbors=between_neighbors(lot))
    row = rows(f)["yard:front"]
    assert row.status == NOT_CHECKED and row.measured == pytest.approx(35)
    assert "neighboring homes" in row.explanation

def test_narrow_rm_lot_needs_no_side_yards():
    lot = box(0, 0, 20, 100)
    _, f = check(lot, box(0.6, 20, 19.4, 60), "RM", home_type="townhouse",
                 neighbors=between_neighbors(lot))
    assert rows(f)["yard:left"].status == NOT_REQUIRED
    assert "under 25 ft wide" in rows(f)["yard:left"].explanation

def test_rm_lot_missing_its_one_side_yard_fails_both_thin_sides():
    lot = box(0, 0, 30, 100)
    _, f = check(lot, box(1, 20, 29, 60), "RM", home_type="single", neighbors=between_neighbors(lot))
    r = rows(f)
    assert r["yard:left"].status == r["yard:right"].status == FAILS
    assert r["yard:left"].required == 5

def test_yard_failures_match_reasons():
    for args in [YARD_CASES]:  # the setups above plus test_house_near_rear_line_is_flagged's
        _, f = check(*args...)
        failing = {reason_kind(r.rule) for r in f.results if r.status == FAILS}
        assert failing == {reason.kind for reason in f.reasons}
```

Fill in the `...` with the same lot shapes the existing tests in `tests/test_checks.py` use for shared walls and end townhouses. The corner case needs a second street passed to `classify`. Set up `YARD_CASES` as a list of keyword-argument dicts for `check()`.

- [ ] **Step 2: Run the tests and check they fail**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest tests/test_rule_results.py -q`
Expected: the new yard tests fail with a KeyError on `yard:left`.

- [ ] **Step 3: Record yard rows in `_check_yards`**

Work out a candidate row for every home and every role. Keep the worst one per role. Worst means the highest rank in FAILS > PASSES > NOT_CHECKED > NOT_REQUIRED > NO_RULE, then the smallest `measured - required`.

| Role | Situation | Row |
|---|---|---|
| any | home outline crosses the lot line (the current note) | NOT_CHECKED, `CROSSES_LOT_LINE` |
| left/right/rear | gap under `TOUCHING_GAP` with no neighbor (mapping error) | NOT_CHECKED, `MAPPING_ERROR` |
| left/right/rear | side shares a wall | NOT_REQUIRED, `SHARED_WALL` |
| front | `rules.front_yard` set | judged against it (FAILS/PASSES), `required=rules.front_yard`, `detail="needs"` |
| front | `rules.front_yard` None | NOT_CHECKED, `front_yard_explanation(rules, in_historic_district)`, `measured` = gap |
| left/right | `side_yards_by_lot_width`, corner lot | NOT_CHECKED, `SIDE_COUNT_ON_CORNER` |
| left/right | `side_yards_by_lot_width`, needs 0 | NOT_REQUIRED, `side_count_explanation(label, width, 0)` |
| left/right | `side_yards_by_lot_width`, needs 1 or 2 | `required=5`. FAILS when the count falls short **and** this side's gap + margin < 5, otherwise PASSES. `explanation=side_count_explanation(...)` |
| left/right | width under `no_side_yard_below_width` | NOT_REQUIRED, `f"Lots narrower than {_feet(w)} need no side yards in the {label}."` |
| left/right | no side yard rule for this home type | NO_RULE, `no_rule_explanation(..., "side yard rule")` |
| left/right | otherwise | `_judge_yard` result |
| rear | corner lot | NOT_CHECKED, `CORNER_NO_REAR` |
| rear | no "rear" key (through lot or odd shape) | NOT_CHECKED, `NO_REAR_FOUND` |
| rear | no rear rule | NO_RULE |
| rear | otherwise | `_judge_yard` result. When on an alley, `detail` gains `", counting half the alley"` |
| left/right | no lot line found on that side | NOT_CHECKED, `"The map couldn't find a lot line on this side of the home."` |

Strip: buffer each of that side's `YardGap.lines` by `required` with `cap_style="flat"`, union them, and clip to the lot.

Add these texts to `rule_results.py`, copied as they are written here:

```python
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

def front_yard_explanation(rules: ZoneRules, in_historic_district: bool) -> str:
    """Why the front yard isn't checked in this lot's zone."""

def side_count_explanation(zone_label: str, width: float, needed: int) -> str:
```

`front_yard_explanation` gives one of three texts:

- **RM, or RB inside a historic district:**
  > In the {label}, a home's front wall is meant to sit right at the front lot line, unless most homes on the block are set back further. Then it must line up with their average. The map doesn't measure the neighbors' homes yet, so this rule isn't checked.
- **Other zones whose name starts with "R":**
  > In the {label}, the front yard must fall within the range of front yards of the neighboring homes that share this street frontage. The map doesn't measure the neighbors' homes yet, so this rule isn't checked.
- **Everything else:**
  > The map doesn't check front yards in the {label}.

`side_count_explanation` gives:

> In the {label}, side yards depend on lot width: none on lots under 25 ft wide, one 5 ft side yard from 25 to 35 ft, and two at 35 ft or more. This lot is about {width} wide, so it needs …

It ends with "none.", "a 5 ft yard on at least one side." or "a 5 ft yard on both sides."

`_check_yards_without_front`: give all four roles NOT_CHECKED (`NO_STREET`). When the fallback measures a gap, also add a `yard:nearest` row ("Closest lot line"). It's FAILS exactly when the fallback writes its reason, with the gap, the needed figure and a `"gap"` shape.

- [ ] **Step 4: Run the full test suite and check it passes**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add alx_zoning_illegal_homes/mapper/ tests/
git commit -m "Record a result for every yard, with the shapes to draw it"
```

---

### Task 3: Rule results for floor space, height and open space

**Files:**
- Modify: `alx_zoning_illegal_homes/mapper/checks.py` (`_check_floor_area`, `_check_height`, `_check_open_space`, plus a `_home_indexes(facts) -> list[int]` helper)
- Modify: `alx_zoning_illegal_homes/mapper/rule_results.py` (`RM_OPEN_SPACE`, `NO_FLOOR_AREA`, `NO_HEIGHT`, `NO_OUTLINES`)
- Test: `tests/test_rule_results.py`

**Interfaces:**
- Produces: these rows on every lot.
  - **`floor_area`** ("Floor space", sq ft, max). `required` = limit × lot area. `buildings` = the homes' indexes.
  - **`height`** ("Height", ft, max). `required` = the limit. `buildings` = the tallest home's index.
  - **Open space:** exactly one of these two.
    - `coverage` ("Land covered by buildings", share, max). `buildings` = every index.
    - `open_space` ("Open space", share, min). `measured` = 1 − covered share.
- `_home_indexes` finds each home in `facts.all_buildings` with `.equals`.

- [ ] **Step 1: Write the failing tests**

```python
def test_oversized_home_marks_floor_space_and_its_building():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(20, 35, 60, 75), "R-8", neighbors=between_neighbors(lot), floor_area=9000)
    row = rows(f)["floor_area"]
    assert row.status == FAILS and row.measured == 9000
    assert row.required == pytest.approx(0.35 * 9600)   # use R-8's actual limit from ZONES
    assert row.buildings == [0]

def test_height_row_carries_the_limit():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(25, 40, 55, 70), "R-8", neighbors=between_neighbors(lot), height=60)
    row = rows(f)["height"]
    assert row.status == FAILS and row.required == ZONES["R-8"].max_height["single"]

def test_unknown_floor_space_is_not_checked():
    lot = box(0, 0, 80, 120)
    _, f = check(lot, box(20, 35, 60, 75), "R-8", floor_area=None)
    assert rows(f)["floor_area"].status == NOT_CHECKED

def test_rm_open_space_not_checked_until_the_rule_exists():
    lot = box(0, 0, 30, 100)
    _, f = check(lot, box(5, 20, 25, 60), "RM", home_type="single", neighbors=between_neighbors(lot))
    r = rows(f)
    assert "coverage" not in r and r["open_space"].status == NOT_CHECKED
    assert "June 24, 1992" in r["open_space"].explanation

def test_every_case_has_one_row_per_rule_in_order_and_rows_match_reasons():
    for kwargs in ALL_CASES:   # every setup in test_checks.py and test_rule_results.py
        _, f = check(**kwargs)
        ids = [r.rule for r in f.results]
        assert ids == sorted(ids, key=RULE_IDS.index) and len(ids) == len(set(ids))
        failing = {reason_kind(r.rule) for r in f.results if r.status == FAILS}
        assert failing == {reason.kind for reason in f.reasons}
```

Replace the 0.35 in the first test with R-8's real ratio, read from `ZONES["R-8"].floor_area_ratio_for("single", False)`.

- [ ] **Step 2: Run the tests and check they fail**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest tests/test_rule_results.py -q`
Expected: the new tests fail with a KeyError on `floor_area`, `height` and `open_space`.

- [ ] **Step 3: Record the rows**

- **Floor space:**
  - NO_RULE when there's no limit.
  - NOT_CHECKED with `NO_FLOOR_AREA` when any home lacks floor space:
    > City records don't give this home's floor space, and it couldn't be estimated from the number of stories.
- **Height:**
  - NO_RULE when there's no limit.
  - NOT_CHECKED with `NO_HEIGHT` when no heights are known:
    > The city's 3D building data has no height for this home.
- **Open space:**
  - When there are no outlines, NOT_CHECKED with `NO_OUTLINES`:
    > The city's map has no building outlines on this lot.
  - When `open_space_applies_to` excludes the home type, NO_RULE.
  - When the zone has neither rule:
    - for RM (`rules.name == "RM"`), the `open_space` row is NOT_CHECKED with `RM_OPEN_SPACE`:
      > The RM zone requires each home lot to keep open, usable space: 35% of the lot, or the amount it had on June 24, 1992 if that is less, and never under 300 sq ft. Driveways don't count. The map doesn't check this rule yet.
    - for every other zone, the `coverage` row is NO_RULE.

- [ ] **Step 4: Run the full test suite and check it passes**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git commit -am "Record a result for floor space, height and open space"
```

---

### Task 4: Two result sets for planned-district lots

**Files:**
- Modify: `alx_zoning_illegal_homes/mapper/rule_results.py` (add `under_special_approval`)
- Modify: `alx_zoning_illegal_homes/mapper/analyze.py:452-488` (keep results in each record)
- Test: `tests/test_rule_results.py`

**Interfaces:**
- Produces: `under_special_approval(results: list[RuleResult], district: PlannedDistrict) -> list[RuleResult]`. It returns new rows; it doesn't change the ones passed in.
  - Rows for `lot_area`, `frontage`, `width` and every `yard:*` whose status is NO_RULE or NOT_CHECKED become NOT_REQUIRED, with this explanation:
    > The approved site plan for {district.name} sets lot sizes and yards here, so no general rule applies.
  - Other NO_RULE rows get this explanation:
    > The special approval sets no lot-by-lot limit for this. {district.plan_summary}
- Produces: each checked record in `analyze()` gets `record["rule_results"]` (list[RuleResult]). District lots also get `record["ordinary_rule_results"]` (from the second `check_lot`) and `record["ordinary_notes"]` (the second run's notes).

- [ ] **Step 1: Write the failing test**

```python
def test_special_approval_turns_lot_rules_into_not_required():
    district, plan, fallback = planned_district_rules("CDD#9")   # Cameron Station, R-8 fallback
    lot = box(0, 0, 20, 90)
    _, f = check(lot, box(0, 20, 20, 60), "R-8", home_type="townhouse", rules=plan)
    r = {x.rule: x for x in under_special_approval(f.results, district)}
    assert r["lot_area"].status == NOT_REQUIRED and "site plan" in r["lot_area"].explanation
    assert r["yard:left"].status == NOT_REQUIRED
    assert r["height"].status == PASSES and r["height"].required == 120
```

Change `check()` in `tests/helpers.py` so it also accepts a `rules=` override. Then the test can run it once with `plan` and once with `fallback`, without building `LotFacts` by hand.

- [ ] **Step 2: Run the test and check it fails**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest tests/test_rule_results.py -k special_approval -q`
Expected: it fails with an ImportError on `under_special_approval`.

- [ ] **Step 3: Implement `under_special_approval` and keep the results in `analyze()`**

In `analyze()`:

- Set `findings.results = under_special_approval(findings.results, district)` for district lots.
- Store `record["rule_results"] = findings.results` for every checked lot.
- Store `record["ordinary_rule_results"] = ordinary.results` and `record["ordinary_notes"] = ordinary.notes` for district lots.

`export()` ignores these columns because they aren't in `PROPERTY_NAMES`.

- [ ] **Step 4: Run the full test suite and check it passes**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git commit -am "Keep both sets of rule results for planned-district lots"
```

---

### Task 5: Write one file per lot

**Files:**
- Create: `alx_zoning_illegal_homes/mapper/lot_files.py`
- Modify: `alx_zoning_illegal_homes/mapper/main.py` (`export` adds `id`; `main` keeps facts and writes the files)
- Modify: `.gitignore` (add `site/lots/`)
- Test: `tests/test_lot_files.py` (new)

**Interfaces:**
- Consumes: `record["rule_results"]`, `record["ordinary_rule_results"]`, `record["ordinary_notes"]` (Task 4), `LotFacts` from `analyze(keep_facts=...)`.
- Produces:

```python
LOTS_DIR = SITE_DIR / "lots"

def lot_frame(facts: LotFacts) -> Callable[[BaseGeometry], BaseGeometry]:
    """Move and turn shapes so the lot's center is at zero and its street is at the bottom."""

def lot_drawing(lot_id: int, record: dict, facts: LotFacts) -> dict:
    """Everything the pop-up needs for one lot, as plain JSON-ready data."""

def write_lot_files(results: GeoDataFrame, facts: dict[int, LotFacts], folder: Path = LOTS_DIR) -> int:
    """Empty the folder, then write <id>.json for every checked lot. Returns the count."""
```

- The file contents (field names are fixed here; the browser tasks rely on them):

```json
{
  "id": 1234, "address": "1313 WILKES ST", "zone": "RM", "zone_label": "RM zone",
  "home_type": "townhouse", "street": "WILKES ST", "position": "interior",
  "historic": true, "district": null, "fallback_zone": null,
  "lot": [[[[x, y], ...], [hole...]]],
  "edges": [{"line": [[x, y], ...], "kind": "street", "street": "WILKES ST"}],
  "buildings": [{"outline": [[[[x, y], ...]]], "height": 28.0, "floor_area": 1800, "is_home": true}],
  "results": {"label": "RM zone rules", "rules": [ROW, ...]},
  "ordinary": {"label": "Ordinary R-8 zone", "rules": [ROW, ...]},
  "notes": ["..."], "ordinary_notes": ["..."]
}
```

  - `ROW` is `{"rule", "name", "status", "measured", "required", "unit", "limit", "explanation", "about", "detail", "summary", "shapes", "buildings"}`.
  - In `shapes`, each geometry is a polygon list like `lot` or a line list like `edges[].line`, depending on its type.
  - None values are left out.
  - The `results.label` for district lots is `"Special approval"`.
  - `ordinary` and `ordinary_notes` appear only for district lots.
  - Polygon lists are always a list of polygons, so a single polygon is wrapped too. Rings aren't closed.
- `lot_frame`:
  - It turns the lot by `90° − angle(lines.inward)` around the lot's centroid, then moves it to the origin.
  - With no `inward` (no street), it only moves it.
  - After turning, `inward` points to +y and the street sits at −y.
- `export()` adds `properties["id"] = int(index)` for checked lots. It switches to `results.itertuples(index=True)`.
- `main()` runs `facts = {}`, `results = analyze(keep_facts=facts)`, `export(results)`, then `write_lot_files(results, facts)`. It prints the count.

- [ ] **Step 1: Write the failing tests**

```python
def test_frame_puts_the_street_at_the_bottom():
    # lot whose street is on its EAST side (street LineString x = 105)
    facts = facts_for(box(0, 0, 100, 40), street=("EAST ST", LineString([(105, -300), (105, 300)])))
    drawing = lot_drawing(7, record_for(facts), facts)
    xs = [x for x, _ in drawing["lot"][0][0]]; ys = [y for _, y in drawing["lot"][0][0]]
    assert max(xs) - min(xs) == pytest.approx(40, abs=0.2)     # turned: width now across
    street_edge = next(e for e in drawing["edges"] if e["kind"] == "street")
    assert all(y == pytest.approx(min(ys), abs=0.2) for _, y in street_edge["line"])

def test_lot_without_street_is_written_unturned():
    facts = facts_for(box(0, 0, 100, 40), street=None)
    drawing = lot_drawing(7, record_for(facts), facts)
    assert drawing["street"] is None
    status = {r["rule"]: r["status"] for r in drawing["results"]["rules"]}
    assert status["frontage"] == status["yard:left"] == "not_checked"

def test_multipart_lot_keeps_every_piece():
    lot = MultiPolygon([box(0, 0, 50, 100), box(60, 0, 80, 20)])
    facts = facts_for(lot, building=box(10, 30, 40, 70).difference(box(20, 40, 30, 60)))
    drawing = lot_drawing(7, record_for(facts), facts)
    assert len(drawing["lot"]) == 2
    assert len(drawing["buildings"][0]["outline"][0]) == 2      # outer ring + hole

def test_rows_round_trip_with_shapes_and_no_nulls():
    facts = facts_for(box(0, 0, 40, 100))
    drawing = lot_drawing(7, record_for(facts), facts)
    width = next(r for r in drawing["results"]["rules"] if r["rule"] == "width")
    assert "line" in width["shapes"] and None not in width.values()
    json.dumps(drawing)   # must be plain JSON

def test_write_lot_files_replaces_old_files(tmp_path):
    (tmp_path / "999.json").write_text("{}")
    count = write_lot_files(small_results_frame, {7: facts}, tmp_path)
    assert count == 1 and not (tmp_path / "999.json").exists()
    assert json.loads((tmp_path / "7.json").read_text())["id"] == 7
```

`facts_for(lot, street=..., building=...)` and `record_for(facts)` are helpers in the test file:

- `facts_for` builds `LotFacts` through `classify`, like `tests/helpers.check`.
- `record_for` runs `check_lot` and returns `{"address": "1 TEST ST", "zone": "R-8", "home_type": "single", "historic": False, "notes": [...], "rule_results": findings.results, "position": ...}`.
- `small_results_frame` is a one-row GeoDataFrame with index 7, `status="ok"` and those fields.

- [ ] **Step 2: Run the tests and check they fail**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest tests/test_lot_files.py -q`
Expected: they fail with an ImportError on `lot_files`.

- [ ] **Step 3: Implement `lot_files.py` and wire it into `main.py`**

Write files with `json.dumps(..., separators=(",", ":"))`. Round coordinates to 1 decimal place and numbers to 2.

- [ ] **Step 4: Run the full test suite, then build the real data**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q`
Expected: every test passes.

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run create-map && ls site/lots | wc -l && du -sh site/lots`
Expected: it prints the usual summary plus "Wrote N lot files". It makes about 22,000 files, roughly 100–200 MB. The `id`s in `lots.geojson` match the file names.

- [ ] **Step 5: Commit**

```bash
git add alx_zoning_illegal_homes/mapper/lot_files.py alx_zoning_illegal_homes/mapper/main.py .gitignore tests/test_lot_files.py
git commit -m "Write a drawing file for every checked lot"
```

---

### Task 6: The rules table and lot-size squares, in the browser

**Files:**
- Create: `site/lot-drawing/format.js`, `site/lot-drawing/table.js`
- Test: `tests/site/table.test.js`

**Interfaces:**
- Consumes: the lot file format from Task 5.
- Produces, in `format.js`:
  - `ft(n)` gives `"1.5 ft"` under 20 and `"25 ft"` otherwise;
  - `sqft(n)` gives `"8,000 sq ft"`;
  - `pct(n)` gives `"35%"`;
  - `esc(text)`;
  - `showValue(value, unit)` picks among the three formatters by unit (`"ft"`, `"sq ft"`, `"share"`).
- Produces, in `table.js`:

```js
/** Which result set the main columns show, and which the extra column shows. */
export function chooseResults(lot, ordinary) // -> { main: {label, rules}, extra: {label, rules} | null }
//   not a district lot: { main: lot.results, extra: null }
//   district, ordinary false: { main: lot.results, extra: lot.ordinary }
//   district, ordinary true:  { main: lot.ordinary, extra: lot.results }
export function rulesTable(main, extra) // -> HTML string
export function lotSquares(row)         // -> HTML string with an inline SVG, or "" when row.required is missing
export function notesList(notes)        // -> HTML string
```

- `rulesTable` details:
  - Each row is `<tr data-rule="{rule}">`.
  - The columns are Rule, Result, Measured, Rule says and a bar; with `extra` there's one more column headed `extra.label`.
  - A result label with an `explanation` gets `class="pill … explain" tabindex="0" data-tip="…"`. A rule name with `about` gets the same treatment.
  - "Rule says" shows `≥ ` for `limit: "min"` and `≤ ` for `"max"`, then the formatted `required`.
  - Rows with a `summary` (home type) span the Measured, Rule says and bar columns with that text.
  - Extra-column cells show the matching row's result label and "Rule says" (for example `FAILS ≥ 5,000 sq ft`), or "–" when the other set has no row with that rule id.
  - The bar is the mockup's `.bar` (the actual value's width, plus a mark at the requirement). It's red when the row fails.
- `lotSquares`: two squares to scale, labeled "This lot" and "Smallest allowed". The second square is red when the row fails.

- [ ] **Step 1: Write the failing tests**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { chooseResults, rulesTable, lotSquares } from "../../site/lot-drawing/table.js";

const row = (o) => ({ rule: "lot_area", name: "Lot size", status: "fails", measured: 4000, required: 8000, unit: "sq ft", limit: "min", ...o });
const plain = { results: { label: "R-8 zone rules", rules: [row()] } };
const district = { district: "Cameron Station", results: { label: "Special approval", rules: [row({ status: "not_required", required: undefined, explanation: "site plan" })] },
                   ordinary: { label: "Ordinary R-8 zone", rules: [row()] } };

test("plain lots have no extra column", () => {
  assert.equal(chooseResults(plain, true).extra, null);
});
test("district lots swap sets with the switch", () => {
  assert.equal(chooseResults(district, false).main.label, "Special approval");
  assert.equal(chooseResults(district, false).extra.label, "Ordinary R-8 zone");
  assert.equal(chooseResults(district, true).main.label, "Ordinary R-8 zone");
  assert.equal(chooseResults(district, true).extra.label, "Special approval");
});
test("table shows labels, limits and tooltips", () => {
  const { main, extra } = chooseResults(district, false);
  const html = rulesTable(main, extra);
  assert.match(html, /data-rule="lot_area"/);
  assert.match(html, /NOT REQUIRED/);
  assert.match(html, /data-tip="site plan"/);
  assert.match(html, /Ordinary R-8 zone/);
  assert.match(html, /FAILS[^<]*<\/span>[^]*≥ 8,000 sq ft/);
});
test("text is escaped", () => {
  const html = rulesTable({ label: "x", rules: [row({ explanation: 'a "quote" <b>' })] }, null);
  assert.doesNotMatch(html, /<b>/);
});
test("squares are skipped without a minimum", () => {
  assert.equal(lotSquares(row({ required: undefined })), "");
  assert.match(lotSquares(row()), /<svg/);
});
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `node --test tests/site/`
Expected: they fail with "Cannot find module …/table.js".

- [ ] **Step 3: Implement `format.js` and `table.js`**

Port `reportTable` and `lotSquares` from the mockup. Drop every rule decision, because the rows now carry their own status and text.

- [ ] **Step 4: Run the tests and check they pass**

Run: `node --test tests/site/`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add site/lot-drawing/format.js site/lot-drawing/table.js tests/site/table.test.js
git commit -m "Render the rules table and lot-size squares from a lot file"
```

---

### Task 7: The 3D drawing

**Files:**
- Create: `site/lot-drawing/scene.js`

**Interfaces:**
- Consumes: the lot file (Task 5); a result set `{label, rules}` (Task 6's `chooseResults(...).main`).
- Produces:

```js
/** Draw a lot in 3D inside `container`. Returns controls for the pop-up. */
export function drawLot(container, lot, results)
// -> { highlight(ruleIds: string[]), dispose() }
```

- Imports: `import * as THREE from "three"` and `import { OrbitControls } from "three/addons/controls/OrbitControls.js"`. The import map comes in Task 8.
- Mapping: file (x, y) becomes Three.js (x, 0, −y). The camera starts on the street side, looking at the lot from above at an angle.

Port `build3D` from the mockup, with these rules (they match the spec):

- **Lot:** a flat outline. Each street edge is labeled with `street` (HTML labels projected from 3D, as the mockup does).
- **Buildings:** extruded to `height`. Homes in any failing row's `buildings` are red. Other homes use the ink tone, and buildings that aren't homes are pale. A missing height uses 12 ft for outbuildings.
- **Failing rows only:**
  - `frontage`: a dimension line that follows `shapes.line` offset toward the street, using `frontTrace`. The label is `"{measured} of street frontage · needs {required}"`.
  - `width`: a line on the ground along `shapes.line`. The label adds `detail`.
  - `yard:*`: shade `shapes.strip` on the ground and draw `shapes.gap`. The label is `"{name} {measured} · {detail} {required}"`.
  - `height`: a see-through plane at `required` over the lot. **Draw this only when the height row fails.**
  - `floor_area` and `coverage`/`open_space`: outline the listed `buildings`, with the label `"{measured} of {required} allowed"`.
- **`highlight(ids)`:** brighten the parts for those rule ids and dim the rest. `highlight([])` resets everything.
- **`dispose()`:** stop the animation loop, dispose of every geometry, material and the renderer, remove the labels, and disconnect the ResizeObserver.

- [ ] **Step 1: Write a check page**

Create `tests/site/scene-check.html`. It's not shipped. It loads the same import map, fetches `../../site/lots/{id}.json` for the id in `?id=`, calls `drawLot` on a 900×600 div, and writes `window.sceneReady = true` once it's done.

- [ ] **Step 2: Implement `scene.js`**

- [ ] **Step 3: Look at the five mockup lots**

Serve the repo root with `python3 -m http.server 8765` (sandbox off). Find each address's id with this command:

```bash
.venv/bin/python -c "import json;f=json.load(open('site/lots.geojson'));print({p['address']:p['id'] for p in (x['properties'] for x in f['features']) if p.get('address') in ['1704 OAKCREST DR','2804 DAVIS AVE','1607 WALLESTON CT','1313 WILKES ST','425 QUEEN ST']})"
```

Open `tests/site/scene-check.html?id=…` in playwright-cli (sandbox off) for each lot and take a screenshot. Compare each one with the mockup's "F" view of the same lot. Expect the same marks and no console errors. 2804 DAVIS AVE must show the height plane, because its height fails. A lot whose height passes must not show one.

- [ ] **Step 4: Commit**

```bash
git add site/lot-drawing/scene.js tests/site/scene-check.html
git commit -m "Draw a lot and its broken rules in 3D"
```

---

### Task 8: The pop-up on the map, with the shared switch

**Files:**
- Create: `site/lot-drawing/index.js`
- Modify: `site/index.html` (import map, `<dialog>`, styles, main script becomes `type="module"`, one `setOrdinaryRules`, click and search open the pop-up)
- Modify: `README.md` (describe the pop-up and `site/lots/`)

**Interfaces:**
- Consumes: `chooseResults`, `rulesTable`, `lotSquares` and `notesList` (Task 6); `drawLot` (Task 7).
- Produces:

```js
/** Wire up the pop-up. `isOrdinary()` reads the shared switch; `setOrdinary(bool)` changes it everywhere. */
export function setUpLotDrawing({ isOrdinary, setOrdinary })
// -> { open(properties), refresh(), close() }
```

- `open(properties)`:
  - Does nothing when `properties.id` is missing (an unchecked lot).
  - Otherwise shows the dialog right away with the address and "Loading…", then fetches `lots/{id}.json`.
  - A counter makes sure only the latest `open` call renders. Results from an older fetch are thrown away.
  - If the fetch fails, the body says: "The drawing for this lot couldn't be loaded. Try rebuilding the map data." The side panel is left alone.
- `refresh()`: if a lot is showing, re-renders the table, the header checkbox, the highlights and the height plane under the current switch, with no new fetch.
- Header content:
  - the address;
  - `"{zone_label} · {home_type} · Breaks N rules"`, or `"Passes every rule the map checks"`;
  - for district lots, a checkbox labeled "Judge by ordinary zoning instead", whose change calls `setOrdinary(checked)`.
- Layout:
  - Drawing on the left, with the squares beside it on wide screens.
  - The table below, then the notes. Show `ordinary_notes` when the switch is on ordinary rules and the lot has them.
  - A line under the drawing: "Measured from the city's map data, not a survey. Drag to turn it."
  - At ≤ 640 px the dialog fills the screen and the bar column hides when the extra column is present.
- Table rows highlight their parts of the drawing on `mouseenter` and `focusin`. A pointer leaving the table resets the highlights.
- Tooltips: port `showTip` and `hideTip` from the mockup for `.explain` elements, on hover and focus.
- `index.html`:
  - Add the import map: `{"imports": {"three": "https://unpkg.com/three/build/three.module.js", "three/addons/": "https://unpkg.com/three/examples/jsm/"}}`.
  - Keep MapLibre's classic `<script>` tag.
  - Turn the page script into `<script type="module">`, which imports `setUpLotDrawing`.
  - `setOrdinaryRules(value)` sets `ordinaryRules`, ticks `#ordinary-rules`, repaints the map, updates the headline, re-renders the side panel for the selected lot, and calls `drawing.refresh()`.
  - The `#ordinary-rules` change handler calls `setOrdinaryRules`.
  - `select(feature)` remembers the feature and calls `drawing.open(feature.properties)`. Both the click handler and the search use `select`.
- Closing uses the native `<dialog>`: Escape and the × button close it, and a click on the backdrop closes it (`event.target === dialog`). Closing calls `dispose()` on the drawing and returns focus to the map canvas.

- [ ] **Step 1: Implement `index.js` and the `index.html` changes**

- [ ] **Step 2: Run the JavaScript tests again**

Run: `node --test tests/site/`
Expected: every test passes.

- [ ] **Step 3: Check the page loads cleanly**

Serve `site/` with `python3 -m http.server 8765 -d site` (sandbox off). Open it with playwright-cli and wait for the map.
Expected: the console has no errors.

- [ ] **Step 4: Click lots and use the search**

- Search "425 QUEEN ST" and press Enter.
  - **Expect:** the side panel updates and the pop-up opens.
  - **Expect:** the table shows a Front yard row of NOT CHECKED with a tooltip, and Lot width FAILS.
- Press Escape.
  - **Expect:** the pop-up closes.
- Click an unchecked lot, such as a park.
  - **Expect:** no pop-up.

- [ ] **Step 5: Check the shared switch on a district lot**

Search for a Cameron Station address. Pick one from `lots.geojson` where `district == "Cameron Station"`.

- **Expect:** a table headed "Special approval", with an extra "Ordinary R-8 zone" column.

Tick the switch in the pop-up.

- **Expect:** the map's `#ordinary-rules` is ticked, and the map colors change.
- **Expect:** the main columns now read the ordinary R-8 results, and the extra column reads "Special approval".

Untick the map's checkbox.

- **Expect:** the pop-up's checkbox clears, and the table goes back.

- [ ] **Step 6: Check the two failure cases from Review Focus**

- **Missing file:** in the browser console, run `drawing.open({id: 99999999, address: "TEST"})`. Expose `window.drawing` from the page script for this.
  - **Expect:** the plain-words error and no console exception.
- **Two quick opens:** run `drawing.open(A); drawing.open(B)` back to back with two real ids.
  - **Expect:** once both have loaded, the header shows B's address.

- [ ] **Step 7: Commit**

```bash
git add site/lot-drawing/index.js site/index.html README.md
git commit -m "Open a lot's drawing from the map, with the planned-district switch inside it"
```

---

### Task 9: Final check on all screens

**Files:** fixes only, wherever the checks below find a problem.

- [ ] **Step 1: Run every test**

Run: `UV_CACHE_DIR="$TMPDIR/uv-cache" uv run pytest -q && node --test tests/site/`
Expected: every test passes.

- [ ] **Step 2: Take desktop screenshots of the five mockup lots and one district lot**

The window is 1400×900. Compare each with the mockup's "F" view. Check that:

- the frontage line follows the curve on 1607 WALLESTON CT;
- 425 QUEEN ST's tooltips appear on hover and on keyboard focus.

- [ ] **Step 3: Check phone width**

Set the window to 375×812 and open a Cameron Station lot.

- **Expect:** the pop-up fills the screen with no sideways page scroll (`document.documentElement.scrollWidth <= 375`).
- **Expect:** the extra column shows and the bar column is hidden.
- **Expect:** the drawing still turns when dragged.

- [ ] **Step 4: Commit any fixes**

```bash
git commit -am "Polish the lot drawing pop-up"
```
