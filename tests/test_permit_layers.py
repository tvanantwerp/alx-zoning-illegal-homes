"""Reading permit cases from the city's map layers."""
import json
from pathlib import Path

from alx_zoning_illegal_homes.permits.layers import cases_from_projects, cases_from_sup_layer

FIXTURES = Path(__file__).parent / "fixtures" / "permits"


def read_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sup_layer_cases():
    cases = {c["case"]: c for c in cases_from_sup_layer(read_json("sup_layer_sample.geojson"))}
    c = cases["SUP2005-00035"]
    assert c["kind"] == "SUP" and c["year"] == 2005
    assert c["descriptions"] == ["continued use of a convenience store"]
    assert c["addresses"] == ["3314 RICHMOND HWY"] and len(c["points"]) == 1
    assert c["sources"] == ["sup_layer"] and c["status"] == "Approved"
    assert "SUP1232D" in cases


def test_sup_layer_blank_description_gives_no_description():
    cases = {c["case"]: c for c in cases_from_sup_layer(read_json("sup_layer_sample.geojson"))}
    assert cases["SUP1228"]["descriptions"] == []


def test_sup_layer_skips_unreadable_case_numbers():
    data = {"features": [{"geometry": None, "properties": {"PLANNUMBER": "nonsense"}}]}
    assert cases_from_sup_layer(data) == []


def test_project_cases_skip_blank_case_numbers():
    data = {"features": [{"properties": {"PERMIT_PLAN_CASE": None, "PROJECTNAME": "X"}},
                         {"properties": {"PERMIT_PLAN_CASE": "DSP2002-00029", "PROJECTNAME": "Chatham Square",
                                         "PROJECTGENLOCATION": "500 Pitt St"}}]}
    cases = cases_from_projects(data)
    assert [c["case"] for c in cases] == ["DSP2002-00029"]
    assert cases[0]["sources"] == ["projects_layer"]
    assert cases[0]["project_names"] == ["Chatham Square"]
    assert cases[0]["addresses"] == ["500 Pitt St"] and cases[0]["points"] == []
