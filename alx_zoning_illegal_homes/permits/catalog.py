"""The permanent list of permit cases.

The catalog is a committed file with one JSON record per line, sorted by case
number. It only grows: merging new data adds cases and fills in blank fields,
but never blanks a field or drops a case.
"""
import json
import re
from pathlib import Path

KINDS = ("SUP", "BZA", "DSUP", "DSP")
CATALOG_PATH = Path(__file__).with_name("catalog.jsonl")

# Longest first, so DSUP is not read as DSP or SUP.
_KINDS_LONGEST_FIRST = sorted(KINDS, key=len, reverse=True)
_YEAR_FORM = re.compile(r"^([A-Z]+)(\d{4}|\d{2})-(\d+)(.*)$")
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})
_KIND_PATTERN = "|".join(_KINDS_LONGEST_FIRST)
_NEW_FORM = re.compile(
    rf"^\s*({_KIND_PATTERN})\s*(\d{{4}}|\d{{2}})\s*-\s*(\d+)([A-Z]?)(?![0-9A-Z])"
)
_PLAIN_FORM = re.compile(rf"^\s*({_KIND_PATTERN})\s*(\d+)([A-Z]?)(?![0-9A-Z])")


def case_kind(case: str) -> str:
    """The kind of case, from the longest matching prefix in ``KINDS``."""
    for kind in _KINDS_LONGEST_FIRST:
        if case.startswith(kind):
            return kind
    raise ValueError(f"Unknown case kind: {case!r}")


def normalize_case(text: str | None) -> str | None:
    """Give a case number its one standard spelling, or None if it is not one we track.

    Spaces and "#" are dropped, letters are upper-cased, dash lookalikes count
    as "-", and the number after the year loses extra leading zeros and is
    padded to 5 digits ("SUP 2005-35" becomes "SUP2005-00035"). Old plain
    numbers keep their letters ("SUP1232D", "BZA57"). Anything after the case
    number, such as "(amended)", is ignored.
    """
    if not text:
        return None
    text = text.upper().translate(_DASHES).replace("#", " ")
    match = _NEW_FORM.match(text)
    if match:
        kind, year, number, letter = match.groups()
        return f"{kind}{year}-{(number.lstrip('0') or '0').zfill(5)}{letter}"
    match = _PLAIN_FORM.match(text)
    if match:
        kind, number, letter = match.groups()
        return f"{kind}{number}{letter}"
    return None


def case_year(case: str) -> int | None:
    """The year in a case number. Two-digit years over 50 are 19xx. None for old plain numbers."""
    match = _YEAR_FORM.match(case)
    if not match:
        return None
    year = match.group(2)
    if len(year) == 4:
        return int(year)
    return 1900 + int(year) if int(year) > 50 else 2000 + int(year)


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, dict]:
    """Read the catalog into a dict keyed by case number. A missing file is an empty catalog.

    If a case appears on more than one line (for example after a hand edit),
    the lines are merged: fields are filled in, the oldest ``first_seen`` and
    the newest ``last_seen`` win.
    """
    if not path.exists():
        return {}
    cases: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = normalize_case(record["case"]) or record["case"]
        record["case"] = key
        if key not in cases:
            cases[key] = record
            continue
        existing = cases[key]
        firsts = [d for d in (existing.get("first_seen"), record.get("first_seen")) if d]
        lasts = [d for d in (existing.get("last_seen"), record.get("last_seen")) if d]
        merged = merge_case(existing, record, today=max(lasts, default=""))
        if firsts:
            merged["first_seen"] = min(firsts)
        if not lasts:
            merged.pop("last_seen")
        cases[key] = merged
    return cases


def save_catalog(cases: dict[str, dict], path: Path = CATALOG_PATH) -> None:
    """Write the catalog sorted by case number, through a temporary file so a crash cannot leave half a file."""
    lines = [json.dumps(cases[key], sort_keys=True, ensure_ascii=False) for key in sorted(cases)]
    part = path.with_name(path.name + ".part")
    part.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    part.replace(path)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_documents(old: list[dict], new: list[dict]) -> list[dict]:
    """Documents are unique by id; inside one document a later non-empty field wins."""
    by_id: dict[int, dict] = {}
    for document in [*old, *new]:
        merged = by_id.setdefault(document["id"], {})
        for key, value in document.items():
            if not _is_empty(value):
                merged[key] = value
            else:
                merged.setdefault(key, value)
    return [by_id[key] for key in sorted(by_id)]


def _merge_list(old: list, new: list) -> list:
    """A sorted union with no duplicates."""
    unique = {json.dumps(item, sort_keys=True): item for item in [*old, *new]}
    return [unique[key] for key in sorted(unique)]


def merge_case(old: dict | None, new: dict, today: str) -> dict:
    """Combine an existing record with fresh data.

    Lists become a sorted union, other fields keep the old value when the new
    one is empty, ``first_seen`` keeps the oldest date, and ``last_seen``
    becomes ``today``.
    """
    old = old or {}
    merged = dict(old)
    for key, value in new.items():
        if key in ("first_seen", "last_seen"):
            continue
        if key == "documents":
            merged[key] = _merge_documents(old.get(key) or [], value or [])
        elif isinstance(value, list) or isinstance(old.get(key), list):
            merged[key] = _merge_list(old.get(key) or [], value or [])
        elif not _is_empty(value):
            merged[key] = value
        else:
            merged.setdefault(key, value)
    merged["first_seen"] = old.get("first_seen") or today
    merged["last_seen"] = today
    return merged
