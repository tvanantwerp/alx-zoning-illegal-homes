"""The ``collect-permits`` command: gather every permit source into the catalog.

It crawls the city's document archive one result page at a time, reads the
special use permit and development project map layers, and merges all of it
into the committed catalog, which only ever grows.

Each archive result page is saved under ``RAW_DIR/<prefix>/<page>.json`` as
soon as it arrives, so an interrupted crawl picks up where it stopped. On a
later run, saved pages are skipped, except page 1 (which tells us how many
pages there are now) and the last 3 pages (where newly added cases tend to
land). ``--full`` fetches every page again.
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


def _clean(value) -> str:
    return " ".join(str(value).split()) if value else ""


def cases_from_documents(documents: list[ArchiveDocument]) -> list[dict]:
    """Group archive documents into case records, one per case number.

    Documents whose "Case/Permit #" is not a case we track are skipped. A
    parcel ID of "0" means the archive has none, so it is dropped. A master
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
        address = _clean(f"{fields.get('Address #', '')} {fields.get('Address Street', '')}")
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


def _load_page(path: Path) -> list[ArchiveDocument]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [ArchiveDocument(r["doc_id"], r["name"], r["pages"], r["fields"]) for r in rows]


def crawl(client: ArchiveClient, prefixes=PREFIXES, raw_dir: Path = RAW_DIR,
          full: bool = False) -> list[ArchiveDocument]:
    """Fetch every result page for each prefix and return all their documents.

    Each page is saved as ``raw_dir/<prefix without "*">/<page>.json``.
    Unless ``full``, a page already saved is read from disk instead, except
    page 1 and the last 3 pages, which are always fetched again. Documents
    are returned once each, even if a page boundary moved and one shows up
    on two saved pages.
    """
    documents: dict[int, ArchiveDocument] = {}
    for prefix in prefixes:
        folder = raw_dir / prefix.rstrip("*")
        first = client.search(prefix, 1)
        _save_page(folder / "1.json", first.documents)
        page_count = max(first.page_count, 1)
        print(f"{prefix} page 1 of {page_count}: {len(first.documents)} documents", flush=True)
        for page in range(2, page_count + 1):
            path = folder / f"{page}.json"
            if path.exists() and not full and page <= page_count - REFETCH_LAST_PAGES:
                continue
            result = client.search(prefix, page)
            _save_page(path, result.documents)
            print(f"{prefix} page {page} of {page_count}: {len(result.documents)} documents",
                  flush=True)
        for path in sorted(folder.glob("*.json")):
            for document in _load_page(path):
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true",
                        help="fetch every archive result page again, not just new ones")
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
