"""Tests for deciding which lot each building stands on."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.analyze import (
    _home_type, _mapped_zone_labels, _match_buildings_to_lots, _outbuilding,
    _place_buildings, _row_sizes)


def place(lot_shapes, building_shapes, is_home=True):
    """Place made-up home buildings on made-up lots, as the analysis does."""
    lots = gpd.GeoDataFrame({"owner": [None] * len(lot_shapes)},
                            geometry=list(lot_shapes))
    buildings = gpd.GeoDataFrame({
        "building_id": range(len(building_shapes)),
        "is_home": is_home,
        "BUSE": "Residential",
        "BTYPE": "Duplex",
        "BSIZE": 1000.0,
        "BUNITS": 1.0,
        "STORIES": 2.0,
        "YEARBLT": 1950,
        "height": 25.0,
        "sections": [[] for _ in building_shapes],
        "ground_floor_retail": None,
    }, geometry=list(building_shapes))
    buildings["footprint"] = buildings.geometry.area
    pairs = _match_buildings_to_lots(lots, buildings)
    return _place_buildings(lots, buildings, pairs)


def test_map_zone_uses_largest_combined_overlap_and_ignores_boundary_touches():
    lots = gpd.GeoSeries([box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10)])
    zones = gpd.GeoDataFrame({"zone": ["R8", "R 8", "R8", "RB", "CDD #1"]},
                             geometry=[box(0, 0, 3, 10), box(7, 0, 10, 10), box(1, 0, 3, 10),
                                       box(3, 0, 7, 10), box(10, 0, 20, 10)])
    chosen = _mapped_zone_labels(lots, zones)
    assert chosen.iloc[:2].tolist() == ["R-8", "CDD#1"]
    assert pd.isna(chosen.iloc[2])


def test_disconnected_scrap_does_not_follow_its_adjacent_component():
    from shapely.geometry import MultiPolygon
    from alx_zoning_illegal_homes.mapper.analyze import _join_small_pieces
    home = box(0, 0, 20, 40)
    scraps = MultiPolygon([box(20, 0, 21, 40), box(80, 0, 81, 40)])
    assert _join_small_pieces({0: home}, [scraps])[0].equals(box(0, 0, 21, 40))


def test_twin_half_keeps_the_strip_on_its_neighbors_lot():
    # The halves meet at x = 27.5, but the lot line runs 2.5 ft into half B.
    lot_a, lot_b = box(0, 0, 30, 100), box(30, 0, 60, 100)
    half_a, half_b = box(5, 20, 27.5, 60), box(27.5, 20, 45, 60)
    placed = place([lot_a, lot_b], [half_a, half_b])

    on_b = placed[placed["building_id"] == 1]
    assert list(on_b["lot_id"]) == [1]
    assert on_b.geometry.iloc[0].area == pytest.approx(half_b.area)
    assert on_b["share"].iloc[0] == pytest.approx(1.0)
    assert list(placed[placed["lot_id"] == 0]["building_id"]) == [0]

    sizes = _row_sizes(placed.geometry.values, placed["lot_id"].values)
    assert sizes == {0: 2, 1: 2}


def test_strip_between_two_counted_pieces_keeps_the_row_joined():
    # One outline over two lots, with a 2 ft strip lot between them.
    lots = [box(0, 0, 30, 100), box(30, 0, 32, 100), box(32, 0, 62, 100)]
    placed = place(lots, [box(10, 20, 52, 60)])

    assert sorted(placed["lot_id"]) == [0, 2]
    assert placed.geometry.area.sum() == pytest.approx(42 * 40)
    sizes = _row_sizes(placed.geometry.values, placed["lot_id"].values)
    assert sizes == {0: 2, 2: 2}


def test_piece_mostly_off_every_lot_is_still_dropped():
    # A house drawn mostly over unmapped land barely touches the only lot.
    placed = place([box(0, 0, 30, 100)], [box(28, 20, 68, 60)])
    assert placed.empty


def _lot(land_use, condo_units=0):
    return pd.Series({"land_use": land_use, "condo_units": condo_units})


def _homes(*shapes, btype="Duplex"):
    return gpd.GeoDataFrame({"BTYPE": [btype] * len(shapes)}, geometry=list(shapes))


TWIN = "SEMI-DETACHED HOUSE"
HALVES = (box(0, 0, 20, 40), box(20, 0, 40, 40))


def test_both_halves_of_a_twin_on_one_lot_make_a_two_unit_house():
    assert _home_type(_lot(TWIN), _homes(*HALVES), row_size=1) == "two_unit"


def test_three_outlines_do_not_make_a_whole_twin():
    homes = _homes(*HALVES, box(40, 0, 60, 40))
    assert _home_type(_lot(TWIN), homes, row_size=1) == "semi"


def test_twin_half_attached_to_its_neighbor_stays_a_half():
    assert _home_type(_lot(TWIN), _homes(HALVES[0]), row_size=2) == "semi"


def test_two_unit_house_needs_its_homes_to_touch():
    apart = _homes(box(0, 0, 20, 40), box(40, 0, 60, 40))
    assert _home_type(_lot(TWIN), apart, row_size=1) == "semi"


def test_detached_house_label_never_makes_a_two_unit_house():
    # A house with an apartment inside, drawn as two outlines.
    homes = _homes(*HALVES, btype="Detached house")
    assert _home_type(_lot("DETACHED HOUSE"), homes, row_size=1) == "single"


def test_lone_detached_house_labeled_a_twin_is_a_detached_house():
    house = _homes(box(0, 0, 30, 40), btype="Detached house")
    assert _home_type(_lot(TWIN), house, row_size=1, alone=True) == "single"
    assert _home_type(_lot(TWIN), house, row_size=1, alone=False) == "semi"
    duplex = _homes(box(0, 0, 30, 40))
    assert _home_type(_lot(TWIN), duplex, row_size=1, alone=True) == "semi"


def test_outbuilding_floor_space_takes_one_story_unless_tall_enough_for_more():
    part = pd.Series({"BSIZE": 0, "STORIES": 0, "footprint": 200.0, "share": 1.0,
                      "BTYPE": "Garage or shed", "height": 11.0, "sections": [(None, 11.0)]})
    garage = _outbuilding(3, part)
    assert garage.index == 3 and garage.label == "garage or shed"
    assert garage.floor_area == pytest.approx(160)  # 200 sq ft less a fifth for eaves
    # Recorded as two stories, but only 11 ft tall: one story.
    assert _outbuilding(0, pd.Series({**part, "STORIES": 2})).floor_area == pytest.approx(160)
    tall = pd.Series({**part, "STORIES": 2, "height": 22.0, "BTYPE": "Other"})
    assert _outbuilding(0, tall).floor_area == pytest.approx(320)
    assert _outbuilding(0, tall).label == "outbuilding"
    # No 3D data: the height is only a guess from the stories, so one story.
    assert _outbuilding(0, pd.Series({**tall, "sections": []})).floor_area == pytest.approx(160)


def test_low_section_alone_does_not_confirm_two_outbuilding_stories():
    part = pd.Series({"STORIES": 2, "footprint": 200, "share": 1, "BTYPE": "Garage or shed",
                      "height": float("nan"), "sections": [(box(0, 0, 2, 5), 11)]})
    assert _outbuilding(0, part).floor_area == pytest.approx(160)


def test_shared_garage_apportions_floor_area_to_both_lots():
    lots = [box(0, 0, 50, 50), box(50, 0, 100, 50)]
    placed = place(lots, [box(30, 10, 70, 30)], is_home=False)
    assert list(placed.lot_id) == [0, 1]
    assert [_outbuilding(0, part).floor_area for _, part in placed.iterrows()] == [320, 320]


def test_outbuilding_sliver_stays_with_the_rest_of_the_building():
    # Half on each of the first two lots, and a 2% sliver over the back line.
    lots = [box(0, 0, 50, 100), box(50, 0, 100, 100), box(0, 100, 100, 200)]
    placed = place(lots, [box(20, 50, 80, 101)], is_home=False)
    assert sorted(placed.lot_id) == [0, 1]
    assert placed.share.sum() == pytest.approx(1.0)
