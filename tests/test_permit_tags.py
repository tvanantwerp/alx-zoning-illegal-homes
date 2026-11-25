"""Which zoning rules a permit case can settle, read from its wording.

Most example descriptions below are copied from the real catalog, with the
case number they came from. Where the catalog has too few real examples (it
has no BZA descriptions at all yet), the wording is written to look like the
city's.
"""
import json

import pytest

from alx_zoning_illegal_homes.mapper import loader
from alx_zoning_illegal_homes.permits.tags import (
    KEYWORDS,
    TAG_RULE_IDS,
    apply_overrides,
    load_overrides,
    tags_for,
)


def sup(text, kind="SUP"):
    return tags_for({"kind": kind, "descriptions": [text], "documents": []})


def bza(text):
    return sup(text, kind="BZA")


# The fixed cases from the task.

def test_business_permits_grant_nothing():
    for text in ["continued use of a convenience store", "restaurant with outdoor dining",
                 "parking reduction for an office building", "TMP for multi-family residential community"]:
        assert tags_for({"kind": "SUP", "descriptions": [text], "documents": []}) == set()


def test_substandard_lot():
    assert "undersized_lot" in tags_for({"kind": "SUP", "descriptions": ["construct a single family dwelling on a substandard lot"], "documents": []})


def test_variance_names_its_yard():
    assert tags_for({"kind": "BZA", "descriptions": ["variance to construct an addition in the required side yard"], "documents": []}) == {"variance:yard:left", "variance:yard:right"}


def test_variance_wording_on_an_sup_is_not_a_variance():
    assert not any(t.startswith("variance:") for t in tags_for({"kind": "SUP", "descriptions": ["side yard"], "documents": []}))


def test_override_replaces_tags_and_needs_a_source():
    cases = {"SUP2001-00001": {"case": "SUP2001-00001", "descriptions": ["restaurant"]}}
    out = apply_overrides(cases, {"cases": {"SUP2001-00001": {"tags": ["extra_height"], "source": "docket 2001"}}})
    assert out["SUP2001-00001"]["tags"] == ["extra_height"]
    with pytest.raises(ValueError):
        apply_overrides(cases, {"cases": {"SUP2001-00001": {"tags": []}}})


# Each tag: real wording that should match, and wording that should not.

@pytest.mark.parametrize("tag, text", [
    ("undersized_lot", "Request to construct a single family dwelling on a substandard lot"),  # SUP2009-00046
    ("undersized_lot", "SUP application for SFD Substandard lot"),  # SUP2018-00008
    ("undersized_lot", "substandard lot construction"),  # SUP2467B
    ("undersized_lot", "Development of lots substandard in size and parking reduction."),  # SUP99-00023
    ("undersized_lot", "218-228 N Payne St; lot area of less than the required minimum (1,980 sf), "
                       "with reduction of off-street parking, and modification of open space."),  # SUP99-00143
    ("undersized_lot", "removal of existing house on a substandard lot and replacing with new house"),  # SUP2024-00057
    ("no_frontage", "residential development plan, with site plan. modifications: lots without street "
                    "frontage, increase in f.a.r., townhouses exceeding 8 units in a single structure, "
                    "tandem parking spaces."),  # SUP96-00056
    ("no_frontage", "construct a single family dwelling on a lot without frontage on a public street"),
    ("no_frontage", "townhouse development with lots fronting on a private street"),
    ("townhouse_row", "residential development plan, with site plan. modifications: lots without street "
                      "frontage, increase in f.a.r., townhouses exceeding 8 units in a single structure, "
                      "tandem parking spaces."),  # SUP96-00056
    ("townhouse_row", "request to allow more than eight townhouses in a row"),
    ("townhouse_row", "residential townhouse development with more than 8 units in a row"),
    ("homes_near_eisenhower", "residential development at 2400 Eisenhower Avenue with 300 dwelling units"),
    ("homes_near_eisenhower", "multi-family residential use in Eisenhower East Block 20"),
    ("homes_near_eisenhower", "apartments on Eisenhower Ave"),
    ("extra_height", "sup amendment to amend condition 104 of the Carlyle Development plan sup to permit "
                     "additional height on the southern portion of block O."),  # SUP2004-00003
    ("extra_height", "Request for additional height - proposed rooftop structures"),  # SUP2017-00072
    ("extra_height", "Request for increased height and front yard setback modifications"),  # SUP2017-00088
    ("extra_height", "home for elderly (131 unit 15 story highrise apartment building for 172-198 senior "
                     "residents), underground parking, setback modification, penthouse height "
                     "modification."),  # SUP95-00171
    ("extra_floor_area", "Consideration of a request to increase the floor area ratio (FAR)."),  # SUP2007-00057
    ("extra_floor_area", "request for for SUP w/ plot plan to increase the floor area ratio (FAR) and parking "
                         "reduction for an eight unit residential building"),  # SUP2005-00050
    ("extra_floor_area", "residential development plan, with site plan. modifications: lots without street "
                         "frontage, increase in f.a.r., townhouses exceeding 8 units in a single "
                         "structure."),  # SUP96-00056
    ("extra_floor_area", "zone transition setback - 25 ft or bldg ht increase f.a.r. to 2.5"),  # SUP94-00305
    ("tract", "SUP (DSUP) for cluster residential; zoning modifications; sales trailer."),  # SUP97-00055
    ("tract", "DSUP with site plan, for residential townhouses, with modifications."),  # SUP96-00160
    ("tract", "development special use permit for a multi-family residential building"),
    ("tract", "residential development on the tract with floor area calculated across the tract"),
])
def test_wording_that_grants_a_tag(tag, text):
    assert tag in sup(text)


@pytest.mark.parametrize("tag, text", [
    ("undersized_lot", "construct two attached dwelling units."),  # SUP2001-00079
    ("undersized_lot", "lot frontage."),  # SUP2814
    ("undersized_lot", "SUP Request to conctruct accessory structure for single-family dwelling on a "
                       "substandard lot"),  # SUP2017-00077: the permit is for a shed-like building
    ("no_frontage", "TD Bank - Allow for frontage over 30 feet"),  # SUP2024-00060
    ("no_frontage", "lot frontage."),  # SUP2814
    ("no_frontage", "Request to construct a single family dwelling on a substandard lot"),  # SUP2009-00046
    ("townhouse_row", "request for for SUP w/ plot plan to increase the floor area ratio (FAR) and parking "
                      "reduction for an eight unit residential building"),  # SUP2005-00050
    ("townhouse_row", "Cluster development for townhouses at N Fairfax & Princess St."),  # SUP1044
    ("townhouse_row", "request for a sales trailer for the West Glebe Road townhouse development"),  # SUP2005-00121
    ("homes_near_eisenhower", "SEE DSUP2012-00023 - Amendment to existing TMP for Block 19 in "
                              "Eisenhower East."),  # SUP2013-00027
    ("homes_near_eisenhower", "Transportation Mangement Plan for 2901 Eisenhower Avenue"),  # SUP2015-00100
    ("homes_near_eisenhower", "Request to operate a restaurant. *SAP is King St. Metro/Eisenhower "
                              "Avenue"),  # SUP2012-00023
    ("homes_near_eisenhower", "catering (4936-A Eisenhower Av, #34)"),  # SUP98-00141
    ("homes_near_eisenhower", "residential development. Townes at Slater's Village."),  # SUP95-00120
    ("extra_height", "Athletic field netting above 15' height up to 30' height at Witter fields."),  # SUP2022-00006
    ("extra_height", "Request for park improvements to baseball field - 15 ft+ backstop - Stevenson Park"),  # SUP2018-00053
    ("extra_height", "restaurant with additional height for a rooftop bar"),
    ("extra_height", "zone transition setback - 25 ft or bldg ht increase f.a.r. to 2.5"),  # SUP94-00305
    ("extra_floor_area", "DSUP for a hotel; retail space; increase f.a.r.; reduction of loading space "
                         "requirement."),  # SUP98-00039
    ("extra_floor_area", "request to remove lots 803 and 804 and their accompanying allocated floor area "
                         "from the Carlyle SUP"),  # SUP2009-00066
    ("extra_floor_area", "request to amend the Carlyle Development Plan to tranfer 5,000 square feet of GFA "
                         "from Block L to Block O"),  # SUP2005-00091
    ("extra_floor_area", "office building with an increase in floor area ratio"),
    ("extra_floor_area", "Request to increase the hours so far approved"),
    ("tract", "request for for SUP w/ plot plan to increase the floor area ratio (FAR) and parking "
              "reduction for an eight unit residential building; see DSUP #2005-0001 for additional "
              "information and activities."),  # SUP2005-00050: points to another case
    ("tract", "SUP (DSUP) for expansion and alterations to a nursing home."),  # SUP97-00053
    ("tract", "DSUP for a wastewater treatment facility."),  # SUP98-00037
    ("tract", "TMP for reapproval of a development SUP for multi-family development"),  # SUP99-00011
    ("tract", "mixed use: retail (existing), office (existing), and proposed residential apartments with "
              "parking reduction."),  # SUP2002-00082
])
def test_wording_that_does_not_grant_a_tag(tag, text):
    assert tag not in sup(text)


@pytest.mark.parametrize("text", [
    "Request to operate a light auto repair facility",  # SUP2011-00034
    "Amendment to SUP2012-0039 to add 12 additional outdoor seats",  # SUP2015-00130
    "Request for a minor amendment to allow additonal seating",  # SUP2009-00034
    "Request to expanded seating volume, renovate interior, and construct a rooftop deck",  # SUP2018-00093
    "TMP for Hoffman site (blks. 2,3,4,5,6).",  # SUP98-00043
    "Request for respite day center for homeless and disadvantaged; use: social service",  # SUP2018-00017
    "Request for setback modifications and for a parking reduction",  # SUP2016-00090
    "child care facility with additional height for the play structure",
    "convenience store; increase the floor area ratio",
    "sign exceeding the permitted height",
    "Transportation Management Plan for a residential building with additional height",
    "school expansion on a substandard lot",
])
def test_businesses_and_side_matters_grant_nothing(text):
    assert sup(text) == set()


@pytest.mark.parametrize("text, expected", [
    ("variance to construct an addition in the required front yard", {"variance:yard:front"}),
    ("variance to construct a rear addition in the required rear yard", {"variance:yard:rear"}),
    ("variance from the side yard and rear yard requirements",
     {"variance:yard:left", "variance:yard:right", "variance:yard:rear"}),
    ("variance to exceed the maximum height for a single family dwelling", {"variance:height"}),
    ("variance to exceed the maximum floor area ratio", {"variance:floor_area"}),
    ("variance to exceed the permitted FAR for an addition", {"variance:floor_area"}),
    ("variance to reduce the required open space", {"variance:open_space"}),
    ("variance for a lot with less than the required frontage", {"variance:frontage"}),
    ("variance for lot width and lot area to build a house",
     {"variance:width", "variance:lot_area"}),
    ("variance for lot size for a single family dwelling", {"variance:lot_area"}),
])
def test_variance_wording(text, expected):
    assert bza(text) == expected


@pytest.mark.parametrize("text", [
    "variance to construct a fence in the front yard exceeding the maximum height",
    "variance to construct a shed in the required side yard",
    "variance to construct a detached garage in the rear yard",
    "appeal of the zoning administrator's decision regarding the side yard",
    "variance for a sign exceeding the permitted height on a restaurant",
    "variance to construct an accessory structure in the rear yard",
    "variance to construct a swimming pool in the side yard",
])
def test_variances_for_things_other_than_the_home_grant_nothing(text):
    assert bza(text) == set()


def test_bza_cases_get_no_permit_tags():
    assert bza("construct a single family dwelling on a substandard lot") == set()


def test_document_types_are_read_too():
    case = {"kind": "SUP", "descriptions": [],
            "documents": [{"id": 1, "name": "x", "type": "Substandard lot", "pages": 1}]}
    assert tags_for(case) == {"undersized_lot"}


def test_cases_without_descriptions_get_no_tags():
    assert tags_for({"kind": "SUP", "documents": [{"id": 1, "name": "SUP1", "type": "Other", "pages": 3}]}) == set()


def test_every_tag_covers_known_rules():
    assert TAG_RULE_IDS["undersized_lot"] == ("lot_area", "width", "frontage")
    assert TAG_RULE_IDS["no_frontage"] == ("frontage",)
    assert TAG_RULE_IDS["townhouse_row"] == ("row_length",)
    assert TAG_RULE_IDS["homes_near_eisenhower"] == ("home_type",)
    assert TAG_RULE_IDS["extra_height"] == ("height",)
    assert TAG_RULE_IDS["extra_floor_area"] == ("floor_area",)
    assert TAG_RULE_IDS["tract"] == ("floor_area", "lot_area")
    for rule in ["yard:front", "yard:left", "yard:right", "yard:rear", "height", "floor_area",
                 "open_space", "frontage", "width", "lot_area"]:
        assert TAG_RULE_IDS[f"variance:{rule}"] == (rule,)
    assert {tag for tag, _ in KEYWORDS} == set(TAG_RULE_IDS)


# Overrides.

def test_override_adds_parcel_ids_and_keeps_the_rest():
    cases = {"SUP2001-00001": {"case": "SUP2001-00001", "parcel_ids": ["A"], "tags": ["undersized_lot"]}}
    out = apply_overrides(cases, {"cases": {"SUP2001-00001": {"parcel_ids": ["B", "A"], "source": "deed"}}})
    assert out["SUP2001-00001"]["parcel_ids"] == ["A", "B"]
    assert out["SUP2001-00001"]["tags"] == ["undersized_lot"]
    assert cases["SUP2001-00001"]["parcel_ids"] == ["A"]


def test_override_can_ignore_a_case():
    cases = {"SUP2001-00001": {"case": "SUP2001-00001"}, "SUP2001-00002": {"case": "SUP2001-00002"}}
    out = apply_overrides(cases, {"cases": {"SUP2001-00001": {"ignore": True, "source": "test record"}}})
    assert set(out) == {"SUP2001-00002"}


@pytest.mark.parametrize("override", [
    {"tags": ["not_a_tag"], "source": "x"},
    {"color": "red", "source": "x"},
    {"tags": ["extra_height"], "source": "  "},
])
def test_bad_overrides_are_refused(override):
    cases = {"SUP2001-00001": {"case": "SUP2001-00001"}}
    with pytest.raises(ValueError):
        apply_overrides(cases, {"cases": {"SUP2001-00001": override}})


def test_override_for_an_unknown_case_is_refused():
    with pytest.raises(ValueError):
        apply_overrides({}, {"cases": {"SUP2001-00001": {"ignore": True, "source": "x"}}})


def test_committed_overrides_file_loads(tmp_path):
    assert "cases" in load_overrides()
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"cases": {"SUP1": {"ignore": True, "source": "x"}}}))
    assert load_overrides(path)["cases"]["SUP1"]["ignore"] is True


def test_load_permits_tags_every_case_and_drops_ignored_ones(tmp_path, monkeypatch):
    catalog = {
        "SUP2009-00046": {"case": "SUP2009-00046", "kind": "SUP", "documents": [],
                          "descriptions": ["Request to construct a single family dwelling on a substandard lot"]},
        "SUP2009-00070": {"case": "SUP2009-00070", "kind": "SUP", "documents": [],
                          "descriptions": ["Request to amend hours of operation"]},
        "SUP2019-00099": {"case": "SUP2019-00099", "kind": "SUP", "documents": [], "descriptions": ["TEST"]},
    }
    monkeypatch.setattr(loader, "load_catalog", lambda: {k: dict(v) for k, v in catalog.items()})
    monkeypatch.setattr(loader, "load_overrides", lambda: {"cases": {
        "SUP2019-00099": {"ignore": True, "source": "a test record in the city's system"}}})
    permits = loader.load_permits()
    assert set(permits) == {"SUP2009-00046", "SUP2009-00070"}
    assert permits["SUP2009-00046"]["tags"] == ["undersized_lot"]
    assert permits["SUP2009-00070"]["tags"] == []
