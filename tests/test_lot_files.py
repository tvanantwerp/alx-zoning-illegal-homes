"""The per-lot drawing files the pop-up reads."""
import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, box

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
    assert drawing["results"]["label"] == "Special approval"
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
