import json

import geopandas as gpd
import shapely

from alx_zoning_illegal_homes.mapper.main import export


def _export(tmp_path, rows):
    lots = gpd.GeoDataFrame(rows, geometry=[shapely.box(0, 0, 30, 30)] * len(rows),
                            crs="EPSG:2283")
    path = tmp_path / "lots.geojson"
    export(lots, path)
    return [f["properties"] for f in json.loads(path.read_text())["features"]]


def test_unchecked_lots_say_why_and_name_their_land_use_plainly(tmp_path):
    no_home, = _export(tmp_path, [dict(
        address="A", status="not_checked", land_use="OP.RAILROAD VDT",
        home_type=None, skipped="no_building", zone="I")])
    assert no_home["skipped"] == "no_building"
    assert no_home["use"] == "Railroad tracks in use"


def test_home_skipped_for_its_zone_shows_its_home_type_not_the_city_label(tmp_path):
    # The empty home type on the other row arrives as NaN, which must still count as empty.
    home, no_home = _export(tmp_path, [
        dict(address="A", status="not_checked", land_use="SEMI-DETACHED HOUSE",
             home_type="townhouse", skipped="no_rules", zone="RM/CL"),
        dict(address="B", status="not_checked", land_use="ROW (TOWNHOUSE)",
             home_type=None, skipped="no_building", zone="RM"),
    ])
    assert home["type"] == "townhouse" and "use" not in home
    assert no_home["use"] == "City records list this as a townhouse"


def test_checked_lots_carry_no_skip_reason(tmp_path):
    checked, = _export(tmp_path, [dict(
        address="A", status="ok", land_use="DETACHED HOUSE",
        home_type="detached house", skipped=None, zone="R-8")])
    assert "skipped" not in checked and "use" not in checked


def test_permit_count_shows_only_when_a_lot_has_cases(tmp_path):
    with_cases, without = _export(tmp_path, [
        dict(address="A", status="ok", zone="R-8", permit_count=2),
        dict(address="B", status="ok", zone="R-8", permit_count=0),
    ])
    assert with_cases["permits"] == 2 and "permits" not in without


def test_needed_permits_lists_cases_on_checked_lots_once(tmp_path):
    import pandas as pd

    from alx_zoning_illegal_homes.mapper.main import write_needed_permits

    results = pd.DataFrame({
        "status": ["ok", "illegal", "not_checked"],
        "permits": [[{"case": "SUP2001-00001"}, {"case": "BZA2015-00003"}],
                    [{"case": "SUP2001-00001"}], [{"case": "DSP2010-00001"}]],
    })
    path = tmp_path / "permits" / "needed.json"
    assert write_needed_permits(results, path) == 2
    assert json.loads(path.read_text()) == ["BZA2015-00003", "SUP2001-00001"]
