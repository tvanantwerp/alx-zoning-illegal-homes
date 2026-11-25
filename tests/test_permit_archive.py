"""Reading search results and document pages from the city's permit archive."""
from pathlib import Path

import pytest

from alx_zoning_illegal_homes.permits import archive
from alx_zoning_illegal_homes.permits.archive import (
    ARCHIVE,
    ArchiveClient,
    document_url,
    parse_document_fields,
    parse_search_page,
    search_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "permits"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_search_page_lists_documents_and_page_count():
    page = parse_search_page(read_fixture("search_sup_page1.html"))
    assert page.page == 1 and page.page_count >= 800
    assert len(page.documents) > 0
    assert all(isinstance(d.doc_id, int) for d in page.documents)


def test_search_rows_carry_their_template_fields():
    page = parse_search_page(read_fixture("search_sup_page1.html"))
    assert len(page.documents) == 20
    first = page.documents[0]
    assert first.doc_id == 441042
    assert first.name.startswith("Administrative Special Use Permit Request")
    assert first.pages == 0
    assert first.fields["Case/Permit #"] == "SUP2014-00123"
    assert first.fields["Department"] == "Planning & Zoning"
    assert first.fields["Parcel ID"] == "50618820"
    assert first.fields["Applicant Name"] == "Jodey McGhee"


def test_last_search_page_knows_where_it_is():
    page = parse_search_page(read_fixture("search_sup_last.html"))
    assert page.page == page.page_count >= 800
    assert 0 < len(page.documents) <= 20


def test_empty_search_has_no_documents():
    page = parse_search_page(read_fixture("search_none.html"))
    assert page.documents == [] and page.page_count in (0, 1)


def test_search_with_one_hit_opens_the_document_itself():
    page = parse_search_page(read_fixture("search_single_hit.html"))
    assert (page.page, page.page_count) == (1, 1)
    [document] = page.documents
    assert document.doc_id == 325073
    assert document.name == "SP94-021.PDF"
    assert document.fields["Case/Permit #"] == "SP94-0021"


def test_document_fields_are_read_by_label():
    fields = parse_document_fields(read_fixture("docview_194633.html"))
    assert fields["Case/Permit #"] == "SUP2005-00035"
    assert fields["Address #"] == "3314"
    assert fields["Address Street"] == "JEFFERSON DAVIS HY"
    assert fields["Master Case #"] == "SUP1748A"
    assert "Last modified" not in fields


def test_search_url_quotes_the_wildcard():
    assert "%22SUP%2A%22" in search_url("SUP*") or "%22SUP*%22" in search_url("SUP*")
    assert search_url("SUP*").startswith(ARCHIVE + "Search.aspx?searchcommand=")


def test_document_url():
    assert document_url(194633) == ARCHIVE + "DocView.aspx?id=194633&dbid=0"


class FakeResponse:
    def __init__(self, url, text="", content=None):
        self.url = url
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = 200

    def raise_for_status(self):
        pass


class FakeSession:
    """Answers requests from a list of canned replies and records each call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.headers = {}

    def _reply(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(url, **reply) if isinstance(reply, dict) else FakeResponse(url, reply)

    def get(self, url, **kwargs):
        return self._reply("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._reply("POST", url, **kwargs)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(archive.time, "sleep", lambda seconds: None)


def test_later_pages_are_reached_by_posting_the_form_back():
    session = FakeSession([read_fixture("search_sup_page1.html"),
                           read_fixture("search_sup_last.html")])
    page = ArchiveClient(session=session).search("SUP*", page=812)
    assert page.page == 812
    (first_method, _, _), (method, url, kwargs) = session.calls
    assert (first_method, method) == ("GET", "POST")
    assert url.startswith(ARCHIVE + "Search.aspx?searchcommand=")
    assert kwargs["data"]["__EVENTTARGET"] == "TheSearchResultsBrowser"
    assert kwargs["data"]["__EVENTARGUMENT"] == "StartIndex:16221"
    assert "__VIEWSTATE" in kwargs["data"]


def test_next_page_reuses_the_form_from_the_last_reply():
    session = FakeSession([read_fixture("search_sup_page1.html"),
                           read_fixture("search_sup_last.html"),
                           read_fixture("search_sup_page1.html")])
    client = ArchiveClient(session=session)
    client.search("SUP*", page=1)
    client.search("SUP*", page=812)
    client.search("SUP*", page=1)
    assert [call[0] for call in session.calls] == ["GET", "POST", "POST"]
    assert session.calls[2][2]["data"]["__EVENTARGUMENT"] == "StartIndex:1"


def test_failed_requests_are_retried():
    import requests
    session = FakeSession([requests.ConnectionError("dropped"),
                           read_fixture("search_none.html")])
    page = ArchiveClient(session=session).search("NOTHING*")
    assert page.documents == [] and len(session.calls) == 2


def test_cookie_warning_opens_a_new_session(monkeypatch):
    stale = FakeSession(["<html><body>Cookies are not enabled</body></html>"])
    fresh = FakeSession([read_fixture("docview_194633.html")])
    monkeypatch.setattr(archive.requests, "Session", lambda: fresh)
    fields = ArchiveClient(session=stale).document_fields(194633)
    assert fields["Case/Permit #"] == "SUP2005-00035"
    assert len(fresh.calls) == 1


def test_export_pdf_follows_the_viewer_steps(tmp_path):
    session = FakeSession([
        read_fixture("docview_194633.html"),
        read_fixture("pdf_export_response.xml"),
        read_fixture("pdf_export_response.html"),
        {"content": b"%PDF-1.6 fake"},
    ])
    destination = tmp_path / "194633.pdf"
    assert ArchiveClient(session=session).export_pdf(194633, destination)
    assert destination.read_bytes() == b"%PDF-1.6 fake"
    assert not destination.with_name("194633.pdf.part").exists()
    generate, transition, pdf = session.calls[1:]
    assert generate[2]["params"] == {"Key": "WLOpenDocumentPages194633", "PageRange": "1 - 3"}
    assert transition[2]["params"] == {"Key": "WLPDFCreatorThread3"}
    assert pdf[1].endswith("/PDF/n3paejueaogc41fh3h2zhl43/3/SUP2005-00035 (6).pdf")


def test_export_pdf_downloads_an_electronic_pdf_directly(tmp_path):
    session = FakeSession([read_fixture("search_single_hit.html"),
                           {"content": b"%PDF-1.4 scanned"}])
    destination = tmp_path / "325073.pdf"
    assert ArchiveClient(session=session).export_pdf(325073, destination)
    assert session.calls[1][1].endswith("/0/edoc/325073/SP94-021.pdf")
    assert destination.read_bytes() == b"%PDF-1.4 scanned"


def test_export_pdf_returns_false_when_no_pdf_comes_back(tmp_path):
    session = FakeSession([
        read_fixture("docview_194633.html"),
        read_fixture("pdf_export_response.xml"),
        read_fixture("pdf_export_response.html"),
        {"content": b"<html>error</html>"},
    ])
    destination = tmp_path / "194633.pdf"
    assert ArchiveClient(session=session).export_pdf(194633, destination) is False
    assert not destination.exists()
    assert not destination.with_name("194633.pdf.part").exists()
