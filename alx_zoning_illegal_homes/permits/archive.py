"""Read the city's Planning and Zoning document archive.

The archive is a Laserfiche WebLink 7 site. What we learned by trying it
(November 2026):

Cookies
    The first request in a new session is redirected (302) to the same
    address with "&cr=1" added, which sets the cookies, then redirected back.
    ``requests`` follows those redirects and keeps the cookies, so one
    session just works. If a reply ever says "Cookies are not enabled", the
    client starts a new session and asks once more.

Searching
    ``Search.aspx?searchcommand={[Land Development]:[Case/Permit #]="SUP*"}``
    runs a search. Results come 20 to a page, sorted by document name, under
    "Results 1 - 20 of 16238" with "Page 1 of 812" at the foot. Each result
    row already holds every template field ("Case/Permit #", "Document
    Type", "Address #", "Parcel ID" and so on), so there is no need to open
    each document to read them. Rows link either to ``DocView.aspx?id=N``
    (scanned pages) or ``ElectronicFile.aspx?docid=N`` (an uploaded file
    such as a PDF or an Outlook message). For uploaded files the page count
    is 0.

    A search that finds exactly one document skips the result list and
    shows that document's viewer page instead.

Paging
    There is no page number in the address. The page links are ASP.NET
    postbacks: post the search page's own form back to its form address with
    ``__EVENTTARGET=TheSearchResultsBrowser`` and
    ``__EVENTARGUMENT=StartIndex:<first result number>`` (21 for page 2, 41
    for page 3, and so on) plus the form's hidden fields (``__VIEWSTATE``
    and friends). Any page can be reached in one jump. A ``startidx=``
    address parameter is ignored.

PDF export
    Works without a browser, in three steps after opening the document's
    viewer page in the same session (the viewer page is what makes the
    server remember the document):

    1. ``GeneratePDF.aspx?Key=WLOpenDocumentPages<id>&PageRange=1 - <pages>``
       answers with a small page holding ``<key>WLPDFCreatorThread<n></key>``.
       Without the viewer step the key is missing.
    2. ``PDFTransition.aspx?Key=<that key>`` answers with a page whose script
       calls ``location.replace("PDF/<session>/<n>/<name>.pdf")``. While the
       PDF is still being built the page has no such call, so we ask again.
    3. Fetching that path gives the PDF.

    The site caps exports at 300 pages and trims longer documents. Uploaded
    files (``ElectronicFile.aspx``) are not exported this way; their viewer
    page links straight to the file at ``0/edoc/<id>/<name>``, which we
    download when the name ends in ".pdf".

Case numbers seen
    "SUP2014-00123" (4-digit year), "SUP96-00084" and "SUP95-0120" (2-digit
    year), "SUP0991", "SUP1748A" (old plain numbers, sometimes with a letter).
    Variances are "BZA2014-00015" and old plain numbers "BZA57", "BZA1000".
    Site plans appear as "SP94-0021" and "DSP98-0020"; "CDD2014-0002" and
    "CDD98-03" (coordinated development districts) also show up, often as
    the "Master Case #". "Master Case #" is sometimes missing its prefix
    ("2014-00123"). Searches for "VAR*", "V*", "VA*", "SIT*", "DSUP*",
    "SPA*" and "SUP8*" found nothing.

Parcel ID
    Usually "0" or missing. When filled in it is an 8-digit number such as
    "50618820" or "18744000", which is not the city's map-block-lot form
    ("075.01-04-08"); it looks like the real estate account number.
"""
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

ARCHIVE = "https://imaging.alexandriava.gov/weblink7PZSUP/"
USER_AGENT = "alx-zoning-illegal-homes permit collector"
RESULTS_PER_PAGE = 20
COOKIE_WARNING = "Cookies are not enabled"
NO_RESULTS = re.compile(r"Results\s*<em>\s*0\s*-\s*0\s*</em>\s*of\s+0\b")


@dataclass(frozen=True)
class ArchiveDocument:
    """One document in the archive, with its template fields by label."""
    doc_id: int
    name: str
    pages: int | None
    fields: dict[str, str]


@dataclass(frozen=True)
class SearchPage:
    """One page of search results."""
    documents: list[ArchiveDocument]
    page: int
    page_count: int


def search_url(prefix: str) -> str:
    """Address of a search for documents whose case number matches prefix.

    The prefix may hold the archive's wildcard, as in "SUP*".
    """
    command = '{[Land Development]:[Case/Permit #]="%s"}' % prefix
    return ARCHIVE + "Search.aspx?searchcommand=" + quote(command, safe="")


def document_url(doc_id: int) -> str:
    """Address of a document's viewer page."""
    return ARCHIVE + f"DocView.aspx?id={doc_id}&dbid=0"


def _classes(attrs: dict) -> set[str]:
    return set((attrs.get("class") or "").split())


def _doc_id_from_link(href: str) -> int | None:
    query = parse_qs(urlparse(href).query)
    for key in ("id", "docid"):
        if query.get(key, [""])[0].isdigit():
            return int(query[key][0])
    return None


class _SearchResultsParser(HTMLParser):
    """Reads result rows and the "Page X of Y" line from a search page."""

    def __init__(self):
        super().__init__()
        self.found_results = False
        self.rows: list[dict] = []
        self.page = self.page_count = None
        self._row = None
        self._mode = None
        self._label = None
        self._text: list[str] = []

    def _finish_value(self):
        if self._label is not None:
            self._row["fields"][self._label] = " ".join("".join(self._text).split())
        self._label, self._text = None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = _classes(attrs)
        if tag == "div" and "SearchResultContainer" in classes:
            self.found_results = True
        elif tag == "div" and "SearchResultItem" in classes:
            self._row = {"doc_id": None, "name": "", "pages": None, "fields": {}}
            self.rows.append(self._row)
            self._mode = None
        elif tag == "div" and "PageXofY" in classes:
            self._mode, self._text = "pager", []
        elif self._row is None:
            return
        elif tag == "a" and "DocumentTitle" in classes:
            self._row["doc_id"] = _doc_id_from_link(attrs.get("href", ""))
            self._mode, self._text = "name", []
        elif tag == "div" and "UserProperties" in classes:
            self._mode, self._text = "properties", []
        elif tag == "div" and "FieldSection" in classes:
            self._mode = "fields"
        elif tag == "em" and self._mode == "fields":
            self._finish_value()
            self._mode = "label"

    def handle_endtag(self, tag):
        text = "".join(self._text)
        if self._mode == "pager" and tag == "div":
            match = re.search(r"Page (\d+) of (\d+)", text)
            if match:
                self.page, self.page_count = int(match[1]), int(match[2])
            self._mode = None
        elif self._mode == "name" and tag == "a":
            self._row["name"] = text.strip()
            self._mode = None
        elif self._mode == "properties" and tag == "div":
            match = re.search(r"Page count:\s*(\d+)", text)
            self._row["pages"] = int(match[1]) if match else None
            self._mode = None
        elif self._mode == "label" and tag == "em":
            self._label, self._text = text.strip().rstrip(":"), []
            self._mode = "fields"
        elif self._mode == "fields" and tag == "div" and (self._label or self._row["fields"]):
            self._finish_value()
            self._mode = None

    def handle_data(self, data):
        if self._mode in ("pager", "name", "properties", "label") or self._label is not None:
            self._text.append(data)


class _ViewerParser(HTMLParser):
    """Reads a document viewer page: its id, title, page count, fields and file link."""

    def __init__(self):
        super().__init__()
        self.doc_id = None
        self.title = ""
        self.pages = None
        self.file_link = None
        self.fields: dict[str, str] = {}
        self._mode = None
        self._label = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = _classes(attrs)
        if tag == "form" and attrs.get("id") == "Form1":
            self.doc_id = _doc_id_from_link(attrs.get("action", ""))
        elif tag == "a" and attrs.get("id") == "TheElectFileLink_EDocLink":
            self.file_link = attrs.get("href")
        mode = None
        if tag == "title":
            mode = "title"
        elif tag == "span" and "PageNumberToolbarCount" in classes:
            mode = "pages"
        elif tag == "div" and "FieldDisplayName" in classes:
            mode = "label"
        elif tag == "div" and "FieldDisplayValue" in classes and self._label is not None:
            mode = "value"
        elif tag == "div" and "FieldDisplayBody" in classes:
            self._label = None
        if mode:
            self._mode, self._text = mode, []

    def handle_endtag(self, tag):
        if self._mode is None or tag not in ("title", "span", "div"):
            return
        text = " ".join("".join(self._text).split())
        if self._mode == "title":
            self.title = text.removesuffix(" - Laserfiche WebLink")
        elif self._mode == "pages" and text.isdigit():
            self.pages = int(text)
        elif self._mode == "label":
            self._label = text
        elif self._mode == "value":
            self.fields[self._label] = text
            self._label = None
        self._mode = None

    def handle_data(self, data):
        if self._mode:
            self._text.append(data)


class _FormParser(HTMLParser):
    """Collects the main form's address and the fields a postback must send back."""

    def __init__(self):
        super().__init__()
        self.action = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "Form1":
            self.action = attrs.get("action")
        elif (tag == "input" and attrs.get("name")
              and (attrs.get("type") or "text").lower() in ("hidden", "text")):
            self.fields[attrs["name"]] = attrs.get("value") or ""


class _PdfStepParser(HTMLParser):
    """Reads the PDF export replies: the job key, and the finished file's path."""

    def __init__(self):
        super().__init__()
        self.key = None
        self.pdf_path = None
        self._tag = None

    def handle_starttag(self, tag, attrs):
        if tag in ("key", "script"):
            self._tag = tag

    def handle_endtag(self, tag):
        self._tag = None

    def handle_data(self, data):
        if self._tag == "key" and data.strip():
            self.key = data.strip()
        elif self._tag == "script":
            match = re.search(r'location\.replace\("([^"]+)"\)', data)
            if match:
                self.pdf_path = match[1]


def _parse_viewer(html: str) -> _ViewerParser:
    parser = _ViewerParser()
    parser.feed(html)
    return parser


def parse_search_page(html: str) -> SearchPage:
    """Read the documents and the page position from a search page.

    A search with a single hit returns that document's viewer page; it is
    read as one page holding one document. A search with no hits still says
    "Page 1 of 1", so its "Results 0 - 0 of 0" line is what gives it zero pages.
    """
    parser = _SearchResultsParser()
    parser.feed(html)
    if not parser.found_results:
        viewer = _parse_viewer(html)
        if viewer.doc_id is not None and viewer.fields:
            return SearchPage([ArchiveDocument(viewer.doc_id, viewer.title,
                                               viewer.pages, viewer.fields)], 1, 1)
    documents = [ArchiveDocument(row["doc_id"], row["name"], row["pages"], row["fields"])
                 for row in parser.rows if row["doc_id"] is not None]
    if NO_RESULTS.search(html):
        return SearchPage(documents, 1, 0)
    return SearchPage(documents, parser.page or 1, parser.page_count or 0)


def parse_document_fields(html: str) -> dict[str, str]:
    """Read a viewer page's template fields, keyed by the archive's labels."""
    return _parse_viewer(html).fields


class ArchiveClient:
    """Talks to the archive politely: one request at a time, delay seconds apart.

    Failed requests are tried again, up to 5 times with 5 seconds between.
    """

    def __init__(self, delay: float = 1.0, session: requests.Session | None = None):
        self.delay = delay
        self.session = session or self._new_session()
        self._form: tuple[str, str, dict[str, str]] | None = None

    @staticmethod
    def _new_session() -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        return session

    def _send(self, method: str, url: str, attempts: int = 5, **kwargs) -> requests.Response:
        for attempt in range(attempts):
            try:
                time.sleep(self.delay)
                send = self.session.post if method == "POST" else self.session.get
                response = send(url, timeout=120, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise
                time.sleep(5)
        raise AssertionError("unreachable")

    def _request(self, method: str, url: str, check_cookies: bool = True,
                 **kwargs) -> requests.Response:
        """Send a request, starting a new session once if cookies were lost.

        Pass check_cookies=False for file downloads: reading a large PDF's
        body as text just to look for the warning is slow and pointless.
        """
        response = self._send(method, url, **kwargs)
        if check_cookies and COOKIE_WARNING in response.text:
            self.session = self._new_session()
            response = self._send(method, url, **kwargs)
        return response

    def _remember_form(self, prefix: str, response: requests.Response) -> None:
        parser = _FormParser()
        parser.feed(response.text)
        if parser.action:
            self._form = (prefix, urljoin(response.url, parser.action), parser.fields)

    def search(self, prefix: str, page: int = 1) -> SearchPage:
        """Fetch one page of results for a case number prefix such as "SUP*".

        Pages after the first are reached by posting the last search page's
        form back. Asking for further pages of the same prefix reuses the
        most recent reply's form, so each page costs one request.
        """
        if self._form is None or self._form[0] != prefix:
            response = self._request("GET", search_url(prefix))
            self._remember_form(prefix, response)
            if page == 1:
                return parse_search_page(response.text)
        _, action, fields = self._form
        data = dict(fields,
                    __EVENTTARGET="TheSearchResultsBrowser",
                    __EVENTARGUMENT=f"StartIndex:{(page - 1) * RESULTS_PER_PAGE + 1}")
        response = self._request("POST", action, data=data)
        self._remember_form(prefix, response)
        return parse_search_page(response.text)

    def document_fields(self, doc_id: int) -> dict[str, str]:
        """Fetch a document's viewer page and read its template fields."""
        return parse_document_fields(self._request("GET", document_url(doc_id)).text)

    def export_pdf(self, doc_id: int, destination: Path, polls: int = 30) -> bool:
        """Save a document as a PDF, returning False if the archive won't give one.

        Scanned documents go through the archive's PDF export; uploaded PDF
        files are downloaded as they are. The file is written beside
        destination with ".part" added, then renamed, so a half-written file
        never takes its place. Network failures still raise.
        """
        viewer_page = self._request("GET", document_url(doc_id))
        viewer = _parse_viewer(viewer_page.text)
        if viewer.file_link and viewer.file_link.lower().endswith(".pdf"):
            pdf_url = urljoin(viewer_page.url, viewer.file_link)
        elif viewer.pages:
            pdf_url = self._build_pdf(doc_id, viewer.pages, polls)
            if pdf_url is None:
                return False
        else:
            return False
        content = self._request("GET", pdf_url, check_cookies=False).content
        if not content.startswith(b"%PDF"):
            return False
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(content)
        partial.replace(destination)
        return True

    def _build_pdf(self, doc_id: int, pages: int, polls: int) -> str | None:
        """Ask the archive to build a PDF of every page and return its address."""
        start = _PdfStepParser()
        start.feed(self._request("GET", ARCHIVE + "GeneratePDF.aspx", params={
            "Key": f"WLOpenDocumentPages{doc_id}", "PageRange": f"1 - {pages}"}).text)
        if start.key is None:
            return None
        for _ in range(polls):
            response = self._request("GET", ARCHIVE + "PDFTransition.aspx",
                                     params={"Key": start.key})
            step = _PdfStepParser()
            step.feed(response.text)
            if step.pdf_path:
                return urljoin(response.url, step.pdf_path)
        return None
