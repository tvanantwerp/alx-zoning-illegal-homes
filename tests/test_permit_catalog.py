import json

import pytest

from alx_zoning_illegal_homes.permits.catalog import (
    case_kind,
    case_year,
    load_catalog,
    merge_case,
    normalize_case,
    save_catalog,
)


@pytest.mark.parametrize("text", ["SUP2005-00035", "SUP 2005-0035", "SUP#2005-35", "sup2005-00035 "])
def test_one_case_many_spellings(text):
    assert normalize_case(text) == "SUP2005-00035"


def test_old_case_numbers_keep_their_letters():
    assert normalize_case("SUP1232D") == "SUP1232D"
    assert normalize_case("SUP98-00167") == "SUP98-00167"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("SUP95-0120", "SUP95-00120"),
        ("SUP0991", "SUP0991"),
        ("SUP1748A", "SUP1748A"),
        ("BZA57", "BZA57"),
        ("BZA1000", "BZA1000"),
        ("DSP98-0020", "DSP98-00020"),
        ("DSUP2003-18", "DSUP2003-00018"),
    ],
)
def test_other_forms_in_the_archive(text, expected):
    assert normalize_case(text) == expected


@pytest.mark.parametrize("text", ["SP94-0021", "CDD2014-0002", "2014-00123", "", None])
def test_unknown_kinds_give_none(text):
    assert normalize_case(text) is None


def test_kind_prefers_the_longest_prefix():
    assert case_kind("DSUP2003-00018") == "DSUP"
    assert case_kind("DSP2002-00029") == "DSP"
    assert case_kind("BZA2019-00012") == "BZA"


def test_years():
    assert case_year("SUP2005-00035") == 2005 and case_year("SUP98-00167") == 1998
    assert case_year("SUP10-00001") == 2010
    assert case_year("SUP1232D") is None


def test_merge_fills_in_but_never_blanks():
    old = {"case": "SUP2005-00035", "descriptions": ["convenience store"], "status": "Approved",
           "documents": [{"id": 1, "name": "a", "type": "Other", "pages": 3}],
           "sources": ["sup_layer"], "first_seen": "2026-11-01", "last_seen": "2026-11-01"}
    new = {"case": "SUP2005-00035", "descriptions": [], "status": None,
           "documents": [{"id": 2, "name": "b", "type": "Staff Report", "pages": None}],
           "sources": ["archive"]}
    merged = merge_case(old, new, today="2026-11-24")
    assert merged["descriptions"] == ["convenience store"]
    assert merged["status"] == "Approved"
    assert [d["id"] for d in merged["documents"]] == [1, 2]
    assert merged["sources"] == ["archive", "sup_layer"]
    assert merged["first_seen"] == "2026-11-01" and merged["last_seen"] == "2026-11-24"


def test_merge_into_nothing_starts_a_record():
    merged = merge_case(None, {"case": "SUP2005-00035", "status": "Approved"}, today="2026-11-24")
    assert merged["first_seen"] == merged["last_seen"] == "2026-11-24"
    assert merged["status"] == "Approved"


def test_merge_fills_document_gaps_and_points():
    old = {"case": "X", "documents": [{"id": 1, "name": "a", "type": "Other", "pages": None}],
           "points": [[-77.0, 38.8]]}
    new = {"case": "X", "documents": [{"id": 1, "name": "", "type": "Other", "pages": 4}],
           "points": [[-77.0, 38.8], [-77.1, 38.9]]}
    merged = merge_case(old, new, today="2026-11-24")
    assert merged["documents"] == [{"id": 1, "name": "a", "type": "Other", "pages": 4}]
    assert merged["points"] == [[-77.0, 38.8], [-77.1, 38.9]]


def test_save_and_load_round_trip_sorted(tmp_path):
    path = tmp_path / "catalog.jsonl"
    save_catalog({"SUP2010-00001": {"case": "SUP2010-00001"}, "BZA2001-00001": {"case": "BZA2001-00001"}}, path)
    assert [json.loads(l)["case"] for l in path.read_text().splitlines()] == ["BZA2001-00001", "SUP2010-00001"]
    assert set(load_catalog(path)) == {"BZA2001-00001", "SUP2010-00001"}


def test_saving_twice_changes_nothing(tmp_path):
    path = tmp_path / "catalog.jsonl"
    cases = {"SUP2010-00001": {"case": "SUP2010-00001", "addresses": ["1 KING ST"]}}
    save_catalog(cases, path); first = path.read_bytes()
    save_catalog(load_catalog(path), path)
    assert path.read_bytes() == first


def test_missing_catalog_loads_empty(tmp_path):
    assert load_catalog(tmp_path / "nope.jsonl") == {}
