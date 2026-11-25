"""Matching permit cases to lots."""
import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.loader import FEET_CRS, parcel_ids_of
from alx_zoning_illegal_homes.permits.match import CaseMatch, match_cases, normalize_address

TO_LON_LAT = Transformer.from_crs(FEET_CRS, "EPSG:4326", always_xy=True)

# Two side-by-side lots near Old Town, in feet.
X, Y = 11_900_000, 6_990_000


def make_lots(first_address="105 N UNION ST", second_address="200 KING ST"):
    return gpd.GeoDataFrame(
        {"address": [first_address, second_address],
         "parcel_ids": [["075.01-04-08", "50618820"], ["075.01-04-09", "50618830"]]},
        geometry=[box(X, Y, X + 50, Y + 100), box(X + 50, Y, X + 100, Y + 100)],
        crs=FEET_CRS,
    )


lots = make_lots()
no_projects = gpd.GeoDataFrame({"PERMIT_PLAN_CASE": []}, geometry=[], crs=FEET_CRS)


def lots_with_address(address):
    return make_lots(address)


def projects_with(*cases):
    """Project outlines that each cover lot 0 and stop short of lot 1."""
    return gpd.GeoDataFrame({"PERMIT_PLAN_CASE": list(cases)},
                            geometry=[box(X - 10, Y - 10, X + 40, Y + 110)] * len(cases),
                            crs=FEET_CRS)


def case(addresses=(), parcel_ids=(), points=()):
    return {"addresses": list(addresses), "parcel_ids": list(parcel_ids), "points": list(points)}


def to_lon_lat(point):
    return TO_LON_LAT.transform(point.x, point.y)


def test_address_forms_agree():
    assert normalize_address("2121 JAMIESON AVE UNIT 809") == normalize_address("2121 Jamieson Av")
    assert normalize_address("3314 JEFFERSON DAVIS HY") == "3314 RICHMOND HWY"
    assert normalize_address("105 NORTH UNION STREET") == normalize_address("105 N UNION ST")


def test_address_odd_spellings():
    assert normalize_address("1601 MT VERNON AV") == "1601 MOUNT VERNON AVE"
    assert normalize_address("1000 ST STEPHENS RD") == "1000 SAINT STEPHENS RD"
    assert normalize_address("701 SLATERS LA") == "701 SLATERS LN"
    assert normalize_address("44Canal Center Plaza") == "44 CANAL CENTER PLZ"
    assert normalize_address("4600 DUKE ST # 621") == "4600 DUKE ST"
    assert normalize_address("King Street") is None
    assert normalize_address("") is None and normalize_address(None) is None


def test_parcel_match_beats_address():
    m = match_cases(lots, {"SUP2001-00001": case(parcel_ids=["075.01-04-08"], addresses=["9 ELSEWHERE ST"])}, no_projects)
    assert m[0] == [CaseMatch("SUP2001-00001", "parcel")]


def test_parcel_match_by_account_number():
    m = match_cases(lots, {"BZA2001-00003": case(parcel_ids=[" 50618830 "], addresses=["105 N UNION ST"])},
                    no_projects)
    assert m[1] == [CaseMatch("BZA2001-00003", "parcel")]
    assert m[0] == [CaseMatch("BZA2001-00003", "address")]


def test_parcel_zero_never_matches():
    m = match_cases(lots, {"SUP2001-00002": case(parcel_ids=["0"], addresses=[])}, no_projects)
    assert m.get(0, []) == [] and m.get(1, []) == []


def test_outline_match_lists_every_overlapping_case():
    m = match_cases(lots, {}, projects_with("DSP2002-00029", "DSUP2003-00018"))
    assert {c.case for c in m[0]} == {"DSP2002-00029", "DSUP2003-00018"}
    assert 1 not in m


def test_outline_beats_address_for_the_same_case():
    m = match_cases(lots, {"DSP2002-00029": case(addresses=["105 N UNION ST"])}, projects_with("DSP2002-00029"))
    assert m[0] == [CaseMatch("DSP2002-00029", "outline")]


def test_address_match_with_old_street_name():
    m = match_cases(lots_with_address("3314 RICHMOND HWY"),
                    {"SUP2005-00035": case(addresses=["3314 JEFFERSON DAVIS HY"])}, no_projects)
    assert m[0] == [CaseMatch("SUP2005-00035", "address")]


def test_address_without_direction_matches_the_only_directional_form():
    m = match_cases(lots, {"BZA2002-00089": case(addresses=["105 UNION ST"])}, no_projects)
    assert m[0] == [CaseMatch("BZA2002-00089", "address")]


def test_address_without_direction_skips_when_both_directions_exist():
    both = make_lots("100 N WASHINGTON ST", "100 S WASHINGTON ST")
    m = match_cases(both, {"BZA2002-00090": case(addresses=["100 WASHINGTON ST"])}, no_projects)
    assert m == {}


def test_point_inside_lot_matches_when_nothing_else_does():
    lon, lat = to_lon_lat(lots.geometry.iloc[1].centroid)
    m = match_cases(lots, {"SUP2003-00007": case(points=[[lon, lat]])}, no_projects)
    assert m[1] == [CaseMatch("SUP2003-00007", "point")] and 0 not in m


def test_lot_parcel_ids_take_both_forms():
    group = pd.DataFrame({"PID_RE": ["075.01-04-08", " 075.01-04-08", None, ""],
                          "ACCOUNTNO": [50618820.0, "0", None, "50618821"]})
    assert parcel_ids_of(group) == ["075.01-04-08", "50618820", "50618821"]
