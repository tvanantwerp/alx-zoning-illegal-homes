import pytest
from shapely.geometry import box

from alx_zoning_illegal_homes.mapper.checks import Home
from alx_zoning_illegal_homes.mapper.heights import (
    FLAT, PITCHED, PITCHED_SHARE, building_height, roof_height)


def test_pitched_roof_is_measured_halfway_between_eaves_and_peak():
    roof = roof_height(37, stories=2.5)
    # Two full stories put the eaves about 22 ft up; the half story is under the roof.
    assert roof.shape == PITCHED and roof.eaves == 22
    assert roof.height == pytest.approx(29.5)
    assert roof.rise == 15
    assert "2.5 stories" in roof.why


def test_roof_close_to_the_top_story_is_flat():
    roof = roof_height(34, stories=3)
    assert roof.shape == FLAT and roof.height == 34


def test_stories_taller_than_the_peak_mean_a_flat_roof():
    roof = roof_height(30, stories=3)
    assert roof.shape == FLAT and roof.height == 30


def test_apartment_building_is_flat_whatever_its_stories():
    roof = roof_height(40, stories=2, apartment=True)
    assert roof.shape == FLAT and roof.height == 40 and roof.eaves is None


def test_unknown_stories_fall_back_to_a_share_of_the_peak():
    roof = roof_height(40)
    assert roof.shape == PITCHED and roof.height == pytest.approx(PITCHED_SHARE * 40)
    assert roof.eaves is None and "don't say how many stories" in roof.why


def test_story_count_far_too_low_for_the_peak_caps_the_roof():
    roof = roof_height(40, stories=1)
    # One story would leave a 26 ft roof; the eaves go 15 ft below the peak instead.
    assert roof.shape == PITCHED and roof.eaves == 25 and roof.height == 32.5
    assert "probably short" in roof.why


def test_unknown_stories_never_shrink_more_than_half_the_tallest_roof():
    assert roof_height(80).height == 72.5


def test_lower_wing_gets_only_the_stories_that_fit_under_it():
    wing = roof_height(20, stories=2, building_peak=30)
    assert wing.shape == PITCHED and wing.eaves == 12 and wing.height == 16
    assert "lower part" in wing.why
    porch = roof_height(11, stories=2, building_peak=30)
    assert porch.shape == FLAT and porch.height == 11


def test_building_height_comes_from_its_tallest_part():
    main, wing = box(0, 0, 30, 30), box(30, 0, 50, 20)
    home = Home(shape=main.union(wing), height=33, stories=2,
                sections=[(main, 33), (wing, 20)])
    estimate = building_height(home)
    assert len(estimate.parts) == 2
    assert estimate.peak == 33 and estimate.height == pytest.approx(27.5)
    assert estimate.shape == PITCHED and estimate.eaves == 22
    assert sorted(part.height for part in estimate.parts) == [16, 27.5]


def test_small_tower_above_the_home_height_is_lowered_to_it():
    main, tower = box(0, 0, 40, 40), box(0, 0, 5, 5)
    home = Home(shape=main, height=26, stories=2, sections=[(main, 26), (tower, 45)])
    estimate = building_height(home)
    assert estimate.peak == 26


def test_home_without_a_height_has_no_estimate():
    assert building_height(Home(shape=box(0, 0, 10, 10))) is None
