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
