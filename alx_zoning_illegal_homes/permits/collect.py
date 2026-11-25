"""The ``collect-permits`` command: gather every permit source into the catalog.

It crawls the city's document archive one result page at a time, reads the
special use permit and development project map layers, and merges all of it
into the committed catalog, which only ever grows.

Each archive result page is saved under ``RAW_DIR/<prefix>/<page>.json`` as
soon as it arrives, so an interrupted crawl picks up where it stopped. On a
later run, saved pages are skipped, except page 1 (which tells us how many
pages there are now) and the last 3 pages (where newly added cases tend to
land), and every page from the earlier crawl's last page onward.
``--full`` fetches every page again.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from alx_zoning_illegal_homes.downloader.download import DATA_DIR
from alx_zoning_illegal_homes.permits import catalog
from alx_zoning_illegal_homes.permits.archive import ArchiveClient, ArchiveDocument
from alx_zoning_illegal_homes.permits.catalog import (
    case_kind, case_year, load_catalog, merge_case, normalize_case, save_catalog)
from alx_zoning_illegal_homes.permits.layers import cases_from_projects, cases_from_sup_layer

PREFIXES = ("SUP*", "BZA*", "DSUP*", "DSP*")
RAW_DIR = DATA_DIR / "permits" / "raw"
PDF_DIR = DATA_DIR / "permits" / "pdf"
SUP_LAYER_PATH = DATA_DIR / "Special_Use_Permits.geojson"
PROJECTS_PATH = DATA_DIR / "Development_Projects.geojson"
REFETCH_LAST_PAGES = 3


PLACEHOLDERS = {"-- Blank --"}


def _clean(value) -> str:
    """Collapse spaces, and turn the archive's "-- Blank --" placeholder into an empty string."""
    text = " ".join(str(value).split()) if value else ""
    return "" if text in PLACEHOLDERS else text


class EmptyPageError(RuntimeError):
    """A result page that should hold documents came back with none."""


def cases_from_documents(documents: list[ArchiveDocument]) -> list[dict]:
    """Group archive documents into case records, one per case number.

    Documents whose "Case/Permit #" is not a case we track are skipped. A
    parcel ID of "0" means the archive has none, so it is dropped, as is the
    archive's "-- Blank --" placeholder in any field. A master
    case number is given its standard spelling when it has one, and kept as
    written otherwise.
    """
    cases: dict[str, dict] = {}
    for document in documents:
        fields = document.fields
        case = normalize_case(fields.get("Case/Permit #"))
        if case is None:
            continue
        record = cases.setdefault(case, {
            "case": case, "kind": case_kind(case), "year": case_year(case),
            "addresses": [], "parcel_ids": [], "project_names": [], "master_cases": [],
            "applicants": [], "documents": [], "sources": ["archive"],
        })
        address = _clean(f"{_clean(fields.get('Address #'))} {_clean(fields.get('Address Street'))}")
        parcel = _clean(fields.get("Parcel ID"))
        master = _clean(fields.get("Master Case #"))
        values = {
            "addresses": address,
            "parcel_ids": "" if parcel == "0" else parcel,
            "project_names": _clean(fields.get("Project Name")),
            "master_cases": normalize_case(master) or master,
            "applicants": _clean(fields.get("Applicant Name")),
        }
        for key, value in values.items():
            if value and value not in record[key]:
                record[key].append(value)
        record["documents"].append({"id": document.doc_id, "name": document.name,
                                    "type": _clean(fields.get("Document Type")),
                                    "pages": document.pages})
    for record in cases.values():
        for key in ("addresses", "parcel_ids", "project_names", "master_cases", "applicants"):
            record[key].sort()
        record["documents"].sort(key=lambda d: d["id"])
    return [cases[key] for key in sorted(cases)]


def _save_page(path: Path, documents: list[ArchiveDocument]) -> None:
    """Write one result page through a ".part" file, so only finished pages count as saved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"doc_id": d.doc_id, "name": d.name, "pages": d.pages, "fields": d.fields}
            for d in documents]
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    part.replace(path)


def _load_page(path: Path) -> list[ArchiveDocument] | None:
    """Read a saved page, or None if it is missing, unreadable, or empty (so it is fetched again)."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        documents = [ArchiveDocument(r["doc_id"], r["name"], r["pages"], r["fields"])
                     for r in rows]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return documents or None


def _saved_last_page(folder: Path) -> int:
    """The highest page number saved by an earlier crawl, or 0 if there is none."""
    numbers = [int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()]
    return max(numbers, default=0)


def crawl(client: ArchiveClient, prefixes=PREFIXES, raw_dir: Path = RAW_DIR,
          full: bool = False) -> list[ArchiveDocument]:
    """Fetch every result page for each prefix and return all their documents.

    Each page is saved as ``raw_dir/<prefix without "*">/<page>.json``.
    Unless ``full``, a page already saved is read from disk instead, except
    page 1, the last 3 pages, and every page from the earlier crawl's last
    page onward (that page was likely only partly full, and may have gained
    documents). A saved file that can't be read is fetched again. Documents
    are returned once each, even if a page boundary moved and one shows up
    on two pages.

    Raises EmptyPageError if a page that should hold documents comes back
    empty, rather than saving it and trusting it on later runs.
    """
    documents: dict[int, ArchiveDocument] = {}
    for prefix in prefixes:
        folder = raw_dir / prefix.rstrip("*")
        refetch_from = _saved_last_page(folder)
        first = client.search(prefix, 1)
        if first.page_count and not first.documents:
            raise EmptyPageError(f"{prefix} page 1 came back with no documents")
        _save_page(folder / "1.json", first.documents)
        page_count = max(first.page_count, 1)
        refetch_from = min(refetch_from or 1, page_count - REFETCH_LAST_PAGES + 1)
        print(f"{prefix} page 1 of {page_count}: {len(first.documents)} documents", flush=True)
        pages = [first.documents]
        for page in range(2, page_count + 1):
            saved = None if full or page >= refetch_from else _load_page(folder / f"{page}.json")
            if saved is None:
                saved = client.search(prefix, page).documents
                if not saved:
                    raise EmptyPageError(
                        f"{prefix} page {page} of {page_count} came back with no documents")
                _save_page(folder / f"{page}.json", saved)
                print(f"{prefix} page {page} of {page_count}: {len(saved)} documents",
                      flush=True)
            pages.append(saved)
        for page_documents in pages:
            for document in page_documents:
                documents[document.doc_id] = document
    return [documents[key] for key in sorted(documents)]


def _read_layer(path: Path, reader) -> list[dict]:
    """Read cases from a map layer file, or none (with a note) if it hasn't been downloaded."""
    if not path.exists():
        print(f"Skipping {path.name}: the file is missing. Download it with "
              "`python -m alx_zoning_illegal_homes.downloader.download`.")
        return []
    return reader(json.loads(path.read_text(encoding="utf-8")))


def collect(client: ArchiveClient, today: str, full: bool = False) -> dict[str, dict]:
    """Crawl the archive, read both map layers, merge it all into the catalog, and save it.

    Cases already in the catalog are never dropped; the ones seen again get
    ``last_seen`` set to ``today``.
    """
    cases = [*_read_layer(SUP_LAYER_PATH, cases_from_sup_layer),
             *_read_layer(PROJECTS_PATH, cases_from_projects),
             *cases_from_documents(crawl(client, raw_dir=RAW_DIR, full=full))]
    result = load_catalog(catalog.CATALOG_PATH)
    for record in cases:
        result[record["case"]] = merge_case(result.get(record["case"]), record, today)
    save_catalog(result, catalog.CATALOG_PATH)
    return result


def main() -> None:
    """Run ``collect-permits`` from the command line."""
    parser = argparse.ArgumentParser(
        description="Gather every permit source into the catalog.")
    parser.add_argument("--full", action="store_true",
                        help="fetch every archive result page again, not just new ones. "
                             "Use it now and then: results are sorted by name, so documents "
                             "filed into the middle of the list are only found this way")
    parser.add_argument("--documents", action="store_true",
                        help="also download each case's documents as PDFs (not built yet)")
    args = parser.parse_args()
    if args.documents:
        print("Downloading documents is not built yet.")
        sys.exit(2)
    result = collect(ArchiveClient(), today=date.today().isoformat(), full=args.full)
    print(f"The catalog now holds {len(result)} cases.")


if __name__ == "__main__":
    main()
