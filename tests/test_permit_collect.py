"""Tests for collecting permit cases into the catalog."""
import json

import pytest

from alx_zoning_illegal_homes.permits import catalog, collect as collect_module
from alx_zoning_illegal_homes.permits.archive import ArchiveDocument, SearchPage
from alx_zoning_illegal_homes.permits.collect import (
    EmptyPageError, cases_from_documents, collect, crawl)


class FakeClient:
    """Stands in for ArchiveClient: serves made-up result pages and counts searches.

    `pages` gives how many result pages each prefix has; prefixes not listed
    have no results. Asking for `fail_on_page` raises ConnectionError.
    """

    def __init__(self, pages, fail_on_page=None, empty_page=None):
        self.pages = pages
        self.fail_on_page = fail_on_page
        self.empty_page = empty_page
        self.calls = 0
        self.asked = []

    def search(self, prefix, page=1):
        self.calls += 1
        self.asked.append(page)
        if page == self.fail_on_page:
            raise ConnectionError("the network went away")
        count = self.pages.get(prefix, 0)
        if count == 0:
            return SearchPage([], 1, 0)
        if page == self.empty_page:
            return SearchPage([], page, count)
        kind = prefix.rstrip("*")
        documents = [ArchiveDocument(page * 100 + n, f"doc {page}-{n}", 1,
                                     {"Case/Permit #": f"{kind}2020-{page:05d}",
                                      "Document Type": "Staff Report"})
                     for n in range(2)]
        return SearchPage(documents, page, count)


def seed_catalog(tmp_path, *records):
    """Write a catalog holding records and point everything collect touches at tmp_path."""
    path = tmp_path / "catalog.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_documents_group_into_cases_and_ignore_parcel_zero():
    docs = [ArchiveDocument(1, "a", 3, {"Case/Permit #": "SUP2005-00035", "Address #": "3314",
                                        "Address Street": "JEFFERSON DAVIS HY", "Parcel ID": "0",
                                        "Document Type": "Other"}),
            ArchiveDocument(2, "b", 1, {"Case/Permit #": "SUP 2005-35", "Parcel ID": "",
                                        "Document Type": "Staff Report"}),
            ArchiveDocument(3, "c", 1, {"Case/Permit #": ""})]
    (case,) = cases_from_documents(docs)
    assert case["case"] == "SUP2005-00035"
    assert case["parcel_ids"] == [] and case["addresses"] == ["3314 JEFFERSON DAVIS HY"]
    assert [d["id"] for d in case["documents"]] == [1, 2]


def test_documents_fill_the_other_fields():
    docs = [ArchiveDocument(7, "Staff report", None, {
        "Case/Permit #": "BZA2014-00015", "Parcel ID": " 50618820 ",
        "Project Name": "Corner Store", "Master Case #": "CDD98-03",
        "Applicant Name": "Jane Doe", "Document Type": "Staff Report"})]
    (case,) = cases_from_documents(docs)
    assert case["kind"] == "BZA" and case["year"] == 2014
    assert case["parcel_ids"] == ["50618820"]
    assert case["project_names"] == ["Corner Store"]
    assert case["master_cases"] == ["CDD98-03"]
    assert case["applicants"] == ["Jane Doe"]
    assert case["sources"] == ["archive"]
    assert case["documents"] == [{"id": 7, "name": "Staff report", "type": "Staff Report",
                                  "pages": None}]


def test_crawl_resumes_without_refetching_saved_pages(tmp_path):
    client = FakeClient(pages={"SUP*": 5})
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    first = client.calls
    client.calls = 0
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert first == 5 and client.calls == 4      # page 1 plus the last 3


def test_crawl_full_fetches_every_page_again(tmp_path):
    client = FakeClient(pages={"SUP*": 5})
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    client.calls = 0
    documents = crawl(client, prefixes=("SUP*",), raw_dir=tmp_path, full=True)
    assert client.calls == 5
    assert len(documents) == 10


def test_crawl_returns_saved_pages_it_skipped(tmp_path):
    client = FakeClient(pages={"SUP*": 6})
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    documents = crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert sorted(d.doc_id for d in documents) == sorted(
        page * 100 + n for page in range(1, 7) for n in range(2))


def test_documents_drop_the_blank_placeholder():
    docs = [ArchiveDocument(1, "a", 1, {
        "Case/Permit #": "BZA2014-00015", "Parcel ID": "-- Blank --",
        "Project Name": "-- Blank --", "Master Case #": "-- Blank --",
        "Applicant Name": "-- Blank --", "Address #": "-- Blank --",
        "Address Street": "KING ST"})]
    (case,) = cases_from_documents(docs)
    assert case["parcel_ids"] == [] and case["project_names"] == []
    assert case["master_cases"] == [] and case["applicants"] == []
    assert case["addresses"] == ["KING ST"]


def test_crawl_refetches_the_old_last_page_when_the_page_count_grows(tmp_path):
    client = FakeClient(pages={"SUP*": 5})
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    client.pages["SUP*"] = 9
    client.asked = []
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert client.asked == [1, 5, 6, 7, 8, 9]


def test_crawl_refuses_to_save_an_empty_page(tmp_path):
    client = FakeClient(pages={"SUP*": 5}, empty_page=3)
    with pytest.raises(EmptyPageError):
        crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert not (tmp_path / "SUP" / "3.json").exists()


def test_crawl_fetches_unreadable_or_empty_saved_pages_again(tmp_path):
    client = FakeClient(pages={"SUP*": 8})
    crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    (tmp_path / "SUP" / "2.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "SUP" / "3.json").write_text("[]", encoding="utf-8")
    client.asked = []
    documents = crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert client.asked == [1, 2, 3, 6, 7, 8]
    assert len(documents) == 16


def test_crawl_after_a_crash_keeps_saved_pages(tmp_path):
    client = FakeClient(pages={"SUP*": 5}, fail_on_page=3)
    with pytest.raises(ConnectionError):
        crawl(client, prefixes=("SUP*",), raw_dir=tmp_path)
    assert sorted(p.name for p in (tmp_path / "SUP").iterdir()) == ["1.json", "2.json"]


def test_crawl_handles_a_prefix_with_no_results(tmp_path):
    assert crawl(FakeClient(pages={}), prefixes=("DSUP*",), raw_dir=tmp_path) == []


def test_collect_never_drops_a_case(tmp_path, monkeypatch):
    path = seed_catalog(tmp_path, {"case": "SUP1999-00001", "last_seen": "2026-01-01"})
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    monkeypatch.setattr(collect_module, "RAW_DIR", tmp_path / "raw")
    sup_layer = tmp_path / "sup.geojson"
    sup_layer.write_text(json.dumps({"features": [{
        "properties": {"PLANNUMBER": "SUP2020-00001", "DESCRIPTION": "Restaurant"},
        "geometry": {"type": "Point", "coordinates": [-77.05, 38.8]}}]}), encoding="utf-8")
    monkeypatch.setattr(collect_module, "SUP_LAYER_PATH", sup_layer)
    monkeypatch.setattr(collect_module, "PROJECTS_PATH", tmp_path / "missing.geojson")
    result = collect(FakeClient(pages={"SUP*": 1}), today="2026-11-24")
    assert "SUP1999-00001" in result and result["SUP1999-00001"]["last_seen"] == "2026-01-01"
    merged = result["SUP2020-00001"]
    assert merged["sources"] == ["archive", "sup_layer"]
    assert merged["points"] == [[-77.05, 38.8]] and len(merged["documents"]) == 2
    assert catalog.load_catalog(path) == result
