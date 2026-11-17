"""Rule checks on made-up lots where the right answer is obvious."""
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rules import ZONES, normalize_zone, rules_for

MAIN = ("MAIN", LineString([(-300, -25), (500, -25)]))


def check(lot, home, zone, home_type="single", neighbors=None, attached=None,
          height=20, floor_area=1000, units=1):
    """Check one lot holding one home, fronting Main St to its south."""
    facts = LotFacts(
        shape=lot,
        area=lot.area,
        rules=ZONES[zone],
        home_type=home_type,
        homes=[Home(shape=home, height=height, floor_area=floor_area)],
        lines=classify(lot, neighbors, [MAIN], "MAIN"),
        units=units,
        all_buildings=[home],
        attached_neighbors=attached,
    )
    findings = check_lot(facts)
    return {reason.kind for reason in findings.reasons}, findings


def between_neighbors(lot):
    """Lots on both sides and behind, so every edge but the front is shared."""
    x0, y0, x1, y1 = lot.bounds
    return unary_union([box(x0 - 80, y0, x0, y1), box(x1, y0, x1 + 80, y1),
                        box(x0 - 80, y1, x1 + 80, y1 + 100)])


def test_roomy_house_passes_everything():
    lot = box(0, 0, 80, 120)  # 9,600 sq ft in R-8
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8",
                     neighbors=between_neighbors(lot), floor_area=3000)
    assert kinds == set()


def test_small_narrow_lot_is_flagged():
    lot = box(0, 0, 40, 100)  # 4,000 sq ft, 40 ft wide in R-8
    kinds, _ = check(lot, box(10, 35, 30, 65), "R-8",
                     neighbors=between_neighbors(lot))
    assert {"lot_size", "lot_width"} <= kinds
    assert "yards" not in kinds


def test_house_near_side_line_is_flagged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(3, 35, 43, 75), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == {"yards"}
    assert "Side yard" in findings.reasons[0].text


def test_tall_house_needs_a_deeper_side_yard():
    lot = box(0, 0, 80, 120)
    home = box(11, 35, 51, 75)  # 11 ft side yard: fine at 20 ft tall
    assert check(lot, home, "R-8", neighbors=between_neighbors(lot))[0] == set()
    kinds, findings = check(lot, home, "R-8", neighbors=between_neighbors(lot),
                            height=34)
    assert "yards" in kinds
    assert "height" in findings.reasons[0].text


def test_house_near_rear_line_is_flagged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(20, 80, 60, 116), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == {"yards"}
    assert "Rear yard" in findings.reasons[0].text


def test_oversized_house_breaks_floor_area_limit():
    lot = box(0, 0, 80, 120)
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8",
                     neighbors=between_neighbors(lot), floor_area=5000)
    assert kinds == {"floor_area"}


def test_townhouse_is_not_allowed_in_a_house_zone():
    lot = box(0, 0, 80, 120)
    kinds, _ = check(lot, box(20, 35, 60, 75), "R-8", home_type="townhouse",
                     neighbors=between_neighbors(lot))
    assert "home_type" in kinds


def test_shared_walls_are_not_missing_side_yards():
    # A 20 ft wide townhouse filling its lot width, neighbors attached.
    lot = box(0, 0, 20, 110)
    home = box(0, 15, 20, 55)
    attached = unary_union([box(-20, 15, 0, 55), box(20, 15, 40, 55)])
    kinds, findings = check(lot, home, "RB", home_type="townhouse",
                            neighbors=between_neighbors(lot), attached=attached)
    assert kinds == set()
    assert findings.measurements["position"] == "interior"


def test_end_townhouse_needs_a_wider_lot():
    lot = box(0, 0, 20, 110)
    home = box(0, 15, 12, 55)
    attached = box(-20, 15, 0, 55)
    kinds, findings = check(lot, home, "RB", home_type="townhouse",
                            neighbors=between_neighbors(lot), attached=attached)
    assert findings.measurements["position"] == "end"
    assert "lot_width" in kinds


def test_home_drawn_on_the_lot_line_is_not_judged():
    lot = box(0, 0, 80, 120)
    kinds, findings = check(lot, box(0.1, 35, 40, 75), "R-8",
                            neighbors=between_neighbors(lot))
    assert kinds == set()
    assert any("mapping error" in note for note in findings.notes)


def test_zone_labels_from_the_parcel_layer():
    assert normalize_zone("R 8") == "R-8"
    assert normalize_zone("R 2-5") == "R-2-5"
    assert normalize_zone("RB") == "RB"
    assert normalize_zone("RB/R-8") is None
    assert normalize_zone("CDD#9") is None
    assert normalize_zone(None) is None


def test_historic_district_loosens_rb_floor_area():
    assert rules_for("RB", False).max_floor_area_ratio == 0.75
    assert rules_for("RB", True).max_floor_area_ratio == 1.50
