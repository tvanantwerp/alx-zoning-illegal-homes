"""Download the City of Alexandria map layers this project needs."""
import argparse
import json
import time
from pathlib import Path

import requests

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR.parent.parent / "data"
FILE_LIST = PACKAGE_DIR / "files.json"


def download_file(url: str, destination: Path, attempts: int = 20) -> None:
    """Download one file, waiting while the city's server prepares the export.

    The open data site answers with "202 Accepted" while it builds a fresh
    export, so we keep asking until the real file is ready.
    """
    for _ in range(attempts):
        response = requests.get(url, timeout=120)
        if response.status_code == 202:
            time.sleep(5)
            continue
        response.raise_for_status()
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(response.content)
        partial.replace(destination)
        return
    raise TimeoutError(f"The server never finished preparing {url}")


def _get_page(url: str, params: dict, attempts: int = 5) -> list:
    """Fetch one page of shapes, trying again if the connection drops."""
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()
            return response.json().get("features", [])
        except (requests.RequestException, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(5)
    return []


def download_in_pages(url: str, destination: Path, page_size: int) -> None:
    """Download a GeoJSON layer from a city map server, a page at a time.

    The city's map servers hand back at most about a thousand shapes per
    request, so we ask for one page after another and join them into a
    single file.
    """
    features = []
    while True:
        page = _get_page(url, {"resultOffset": len(features),
                               "resultRecordCount": page_size})
        if not page:
            break
        features.extend(page)
    partial = destination.with_name(destination.name + ".part")
    partial.write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                       encoding="utf-8")
    partial.replace(destination)


def get_data(refresh: bool = False) -> None:
    """Download every layer listed in files.json into the data folder.

    Files that already exist are skipped unless refresh is True. An entry
    with a "page_size" is fetched in pages of that many shapes.
    """
    DATA_DIR.mkdir(exist_ok=True)
    for entry in json.loads(FILE_LIST.read_text(encoding="utf-8")):
        destination = DATA_DIR / f"{entry['name']}.{entry['filetype']}"
        if destination.exists() and not refresh:
            continue
        print(f"Downloading {destination.name}...")
        if "page_size" in entry:
            download_in_pages(entry["url"], destination, entry["page_size"])
        else:
            download_file(entry["url"], destination)


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="download again even if a file is already present",
    )
    get_data(refresh=parser.parse_args().refresh)


if __name__ == "__main__":
    main()
