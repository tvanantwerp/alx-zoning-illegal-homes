"""The per-lot drawing files the pop-up reads."""
import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from alx_zoning_illegal_homes.mapper.checks import Home, LotFacts, check_lot
from alx_zoning_illegal_homes.mapper.lot_files import lot_drawing, replace_lot_files, write_lot_files
from alx_zoning_illegal_homes.mapper.lot_lines import classify
from alx_zoning_illegal_homes.mapper.rules import ZONES

SOUTH = ("MAIN", LineString([(-300, -25), (500, -25)]))


def facts_for(lot, street=SOUTH, building=None):
    """Facts for a lot with one home. street is a (name, centerline) pair or None."""
    if building is None:
        x0, y0, x1, y1 = lot.bounds
        building = box(x0 + 20, y0 + 20, x1 - 20, y1 - 20)
    streets = [street] if street else []
    return LotFacts(
        shape=lot, area=lot.area, rules=ZONES["R-8"], home_type="single",
        homes=[Home(shape=building, height=20, floor_area=1000)],
        lines=classify(lot, None, streets, street[0] if street else None),
        all_buildings=[building])


def record_for(facts):
    findings = check_lot(facts)
    return {"address": "1 TEST ST", "zone": "R-8", "home_type": "single",
            "historic": False, "notes": findings.notes,
            "rule_results": findings.results,
            "position": findings.measurements["position"]}


def test_frame_puts_the_street_at_the_bottom():
    facts = facts_for(box(0, 0, 100, 40), street=("EAST ST", LineString([(105, -300), (105, 300)])))
    drawing = lot_drawing(7, record_for(facts), facts)
    xs = [x for x, _ in drawing["lot"][0][0]]
    ys = [y for _, y in drawing["lot"][0][0]]
    assert max(xs) - min(xs) == pytest.approx(40, abs=0.2)
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
    assert len(drawing["buildings"][0]["outline"][0]) == 2


def test_sections_of_different_heights_become_parts():
    building = box(10, 20, 30, 80)
    facts = facts_for(box(0, 0, 40, 100), building=building)
    facts.building_sections = [[(box(10, 20, 30, 50), 24.0), (box(10, 50, 30, 65), 24.0),
                                (box(10, 65, 30, 80), 14.0)]]
    drawn = lot_drawing(7, record_for(facts), facts)["buildings"][0]
    parts = sorted(drawn["parts"], key=lambda part: part["height"])
    assert [part["height"] for part in parts] == [14, 24]
    # Same-height sections are merged into one part.
    assert [len(part["outline"]) for part in parts] == [1, 1]
    assert drawn["height"] == 20   # the home's measured height is kept for labels


def test_sections_of_one_height_add_no_parts():
    building = box(10, 20, 30, 80)
    facts = facts_for(box(0, 0, 40, 100), building=building)
    facts.building_sections = [[(box(10, 20, 30, 50), 24.0), (box(10, 50, 30, 80), 24.0)]]
    assert "parts" not in lot_drawing(7, record_for(facts), facts)["buildings"][0]


def test_sections_are_trimmed_and_gaps_keep_the_building_height():
    building = box(10, 20, 30, 80)
    facts = facts_for(box(0, 0, 40, 100), building=building)
    # The first section spills past the outline; nothing covers y 60-80.
    facts.building_sections = [[(box(0, 20, 30, 40), 30.0), (box(10, 40, 30, 60), 14.0)]]
    parts = lot_drawing(7, record_for(facts), facts)["buildings"][0]["parts"]
    area = {part["height"]: sum(Polygon(poly[0], poly[1:]).area for poly in part["outline"])
            for part in parts}
    assert area == {30: pytest.approx(400, abs=1), 14: pytest.approx(400, abs=1),
                    20: pytest.approx(400, abs=1)}


def test_rows_round_trip_with_shapes_and_no_nulls():
    facts = facts_for(box(0, 0, 40, 100))
    drawing = lot_drawing(7, record_for(facts), facts)
    width = next(r for r in drawing["results"]["rules"] if r["rule"] == "width")
    assert "line" in width["shapes"] and None not in width.values()
    line = width["shapes"]["line"]
    assert len(line) == 1 and len(line[0][0]) == 2   # a list of lines, each a list of points
    json.dumps(drawing)


def test_write_lot_files_replaces_old_files(tmp_path):
    facts = facts_for(box(0, 0, 40, 100))
    record = record_for(facts)
    frame = gpd.GeoDataFrame(
        [{**record, "status": "ok", "geometry": facts.shape}], index=[7])
    (tmp_path / "999.json").write_text("{}")
    count = write_lot_files(frame, {7: facts}, tmp_path)
    assert count == 1 and not (tmp_path / "999.json").exists()
    assert json.loads((tmp_path / "7.json").read_text())["id"] == 7


def test_home_type_is_the_display_name():
    facts = facts_for(box(0, 0, 40, 100))
    assert lot_drawing(7, record_for(facts), facts)["home_type"] == "detached house"


def test_ordinary_block_only_for_district_lots():
    facts = facts_for(box(0, 0, 40, 100))
    plain = lot_drawing(7, record_for(facts), facts)
    assert "ordinary" not in plain and "ordinary_notes" not in plain
    assert plain["district"] is None and plain["fallback_zone"] is None
    assert plain["zone_label"] == "R-8 zone" and plain["results"]["label"] == "R-8 zone rules"

    record = {**record_for(facts), "district": "Test Village", "fallback_zone": "R-8",
              "ordinary_rule_results": check_lot(facts).results,
              "ordinary_notes": ["an ordinary note"]}
    drawing = lot_drawing(7, record, facts)
    assert drawing["zone_label"] == "Test Village planned district"
    assert drawing["results"]["label"] == "Test Village approved plan"
    assert drawing["district"] == "Test Village" and drawing["fallback_zone"] == "R-8"
    assert drawing["ordinary"]["label"] == "Ordinary R-8 zone"
    assert drawing["ordinary"]["rules"] and drawing["ordinary_notes"] == ["an ordinary note"]
    json.dumps(drawing)


def test_missing_facts_is_an_error(tmp_path):
    facts = facts_for(box(0, 0, 40, 100))
    frame = gpd.GeoDataFrame(
        [{**record_for(facts), "status": "ok", "geometry": facts.shape}], index=[7])
    with pytest.raises(KeyError, match="Lot 7"):
        write_lot_files(frame, {}, tmp_path)


def test_replace_lot_files_swaps_the_folder_in(tmp_path):
    facts = facts_for(box(0, 0, 40, 100))
    frame = gpd.GeoDataFrame(
        [{**record_for(facts), "status": "ok", "geometry": facts.shape}], index=[7])
    folder = tmp_path / "lots"
    folder.mkdir()
    (folder / "999.json").write_text("{}")
    assert replace_lot_files(frame, {7: facts}, folder) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["lots"]
    assert sorted(p.name for p in folder.iterdir()) == ["7.json"]


def test_failed_replace_keeps_the_old_folder(tmp_path):
    facts = facts_for(box(0, 0, 40, 100))
    frame = gpd.GeoDataFrame(
        [{**record_for(facts), "status": "ok", "geometry": facts.shape}], index=[7])
    folder = tmp_path / "lots"
    folder.mkdir()
    (folder / "999.json").write_text("{}")
    with pytest.raises(KeyError):
        replace_lot_files(frame, {}, folder)
    assert sorted(p.name for p in folder.iterdir()) == ["999.json"]


def test_matched_cases_are_listed_with_links_and_settled_rows_carry_the_case():
    from alx_zoning_illegal_homes.mapper.permits import apply_permits, lot_permits
    from alx_zoning_illegal_homes.permits.match import CaseMatch

    facts = facts_for(box(0, 0, 80, 120), building=box(4.3, 35, 75.7, 75))
    findings = check_lot(facts)
    case = {"case": "BZA2015-00003", "kind": "BZA", "year": 2015,
            "descriptions": ["Variance to side yard"], "tags": ["variance:yard:left"],
            "documents": [{"id": 17803, "name": "BZA2015-00003", "type": "Other", "pages": 4}]}
    matches = [CaseMatch("BZA2015-00003", "parcel")]
    apply_permits(findings, [case], matches)
    record = {**record_for(facts), "rule_results": findings.results,
              "permits": lot_permits([case], matches, findings.results)}
    drawing = lot_drawing(7, record, facts)
    listed = drawing["permits"][0]
    assert listed["links"][0]["url"].startswith("https://imaging.alexandriava.gov/")
    assert listed["grants"] == ["yard:left"] and listed["how"] == "parcel"
    left = next(r for r in drawing["results"]["rules"] if r["rule"] == "yard:left")
    assert left["permit"] == {"case": "BZA2015-00003", "how": "parcel"}
    json.dumps(drawing)


def test_lot_without_cases_has_no_permits_list():
    facts = facts_for(box(0, 0, 40, 100))
    assert "permits" not in lot_drawing(7, {**record_for(facts), "permits": []}, facts)
