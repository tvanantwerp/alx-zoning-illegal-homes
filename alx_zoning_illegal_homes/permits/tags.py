"""What a permit case grants: which zoning rules it can settle on its lot.

Each case gets zero or more tags, read from the wording of its descriptions
and the types of its documents. A tag names the rules it can settle, in
``TAG_RULE_IDS``. A wrong tag can turn an illegal-looking home into "permit on
file", so the wording has to be specific. When in doubt, no tag: the case is
still listed on the lot, it just doesn't settle a rule.

How it works:

- ``KEYWORDS`` is the table of tags and the wording that gives each one.
  Tags starting with ``variance:`` only come from Board of Zoning Appeals
  (BZA) cases. All other tags only come from the other kinds of case.
- ``NOT_THE_HOME`` lists wording that means the case is about something other
  than a home: a business, a parking plan, a sign, a shed or fence, an
  appeal. A description with any of it gives no tags at all, even if it also
  says "height" or "floor area", because a restaurant's permit doesn't excuse
  the apartments above it.

Tags that settle a building's size (``extra_height``, ``extra_floor_area``,
``tract`` and ``homes_near_eisenhower``) also need wording that names homes
("residential", "dwelling", "apartment" and so on). A request for "additional
height" that never says what the building is for gives no tag.

Two tags only make sense in certain zones, but tags only see a case's text:

- ``homes_near_eisenhower`` matches homes mentioned alongside Eisenhower
  Avenue. It is meant for homes in the OCM(100) and OCH zones near
  Eisenhower.
- ``tract`` matches a development special use permit (or the word "tract")
  for homes. It is meant for the CRMU zones, where floor area and lot area
  can be judged across a whole development. "See DSUP #2005-0001" is a
  pointer to another case, not this one, so a "DSUP" followed by a case
  number doesn't count.

The home type, floor area and lot area rules exist in every zone, so the zone
check can't happen here. It happens when a tag is applied to a lot's rule:
``tract`` only counts on lots in a CRMU zone, and ``homes_near_eisenhower``
only on lots in the OCM(100) or OCH zones.

Overrides, kept in ``overrides.json``, are hand-made corrections that win over
the keywords. Each one needs a ``source`` note saying where it came from.
"""
import json
import re
from pathlib import Path

OVERRIDES_PATH = Path(__file__).with_name("overrides.json")

TAG_RULE_IDS: dict[str, tuple[str, ...]] = {
    "undersized_lot": ("lot_area", "width", "frontage"),
    "no_frontage": ("frontage",),
    "townhouse_row": ("row_length",),
    "homes_near_eisenhower": ("home_type",),
    "extra_height": ("height",),
    "extra_floor_area": ("floor_area",),
    "tract": ("floor_area", "lot_area"),
    **{f"variance:{rule}": (rule,) for rule in (
        "yard:front", "yard:left", "yard:right", "yard:rear", "height",
        "floor_area", "open_space", "frontage", "width", "lot_area",
    )},
}


def _words(pattern: str) -> re.Pattern:
    """A pattern that ignores upper and lower case."""
    return re.compile(pattern, re.IGNORECASE)


def _all_of(*patterns: str) -> re.Pattern:
    """A pattern that matches only text containing every one of ``patterns``, in any order."""
    return re.compile("^" + "".join(f"(?=[\\s\\S]*?(?:{p}))" for p in patterns), re.IGNORECASE)


_HOMES = (r"\bresidential\b|\bdwellings?\b|\bapartments?\b|\bcondominiums?\b|\bhomes\b"
          r"|\bmulti-?family\b|\bsingle[-\s]family\b|\bsemi-?detached\b|\btown\s?(?:houses?|homes?)\b")
_MORE_THAN_EIGHT = r"\b(?:more\s+than|exceeding|over)\s+(?:eight|8)\s+(?:units|town\s?(?:houses|homes)|dwellings)\b"
_FLOOR_AREA = r"\bfloor\s+area\b|\bf\.a\.r\b|(?-i:\bFAR\b)"
_SIDE_YARD = r"\bside\s+yards?\b"
_MORE_HEIGHT = (r"\b(?:increased?|increasing|additional|extra|bonus)\s+"
                r"(?:(?:in|of|the)\s+)*(?:building\s+|maximum\s+)?height\b"
                r"|\bheight\s+(?:increase|modification|bonus|district)s?\b")
_MORE_FLOOR_AREA = (r"\b(?:increased?|increasing|additional|bonus)\s+"
                    r"(?:(?:in|of|the)\s+)*(?:f\.a\.r\b|(?-i:FAR\b)|floor\s+area\b)")

KEYWORDS: list[tuple[str, re.Pattern]] = [
    # Special use permits and site plans
    ("undersized_lot",        _words(r"\b(?:substandard|undersized)\s+lots?\b"
                                     r"|\blots?\s+substandard\s+in\s+size\b"
                                     r"|\blot\s+area\s+(?:of\s+)?less\s+than\s+the\s+required\b")),
    ("no_frontage",           _words(r"\bwithout\s+(?:street\s+|public\s+street\s+)?frontage\b"
                                     r"|\bprivate\s+streets?\b")),
    ("townhouse_row",         _all_of(r"\btown\s?(?:houses?|homes?)\b", _MORE_THAN_EIGHT)),
    ("homes_near_eisenhower", _all_of(r"\beisenhower\b", _HOMES)),
    ("extra_height",          _all_of(_MORE_HEIGHT, _HOMES)),
    ("extra_floor_area",      _all_of(_MORE_FLOOR_AREA, _HOMES)),
    ("tract",                 _all_of(r"\btract\b|\bDSUP\b(?!\s*#?\s*\d)|\bdevelopment\s+(?:special\s+use\s+permit|SUP)\b",
                                      _HOMES)),
    # Variances (BZA cases only)
    ("variance:yard:front",   _words(r"\bfront\s+yards?\b")),
    ("variance:yard:left",    _words(_SIDE_YARD)),
    ("variance:yard:right",   _words(_SIDE_YARD)),
    ("variance:yard:rear",    _words(r"\brear\s+yards?\b")),
    ("variance:height",       _words(r"\bheights?\b")),
    ("variance:floor_area",   _words(_FLOOR_AREA)),
    ("variance:open_space",   _words(r"\bopen\s+space\b")),
    ("variance:frontage",     _words(r"\bfrontage\b")),
    ("variance:width",        _words(r"\blot\s+width\b")),
    ("variance:lot_area",     _words(r"\blot\s+(?:area|size)\b")),
]

NOT_THE_HOME = _words("|".join([
    # Businesses and other uses that aren't homes
    r"\brest[aru]{3,5}nts?\b", r"(?-i:\b[Bb]ars?\b)", r"\bbrew(?:ery|eries|pub)\b",
    r"\btaverns?\b", r"\bcoffee\b", r"\bpharmac(?:y|ies)\b", r"\bcaf[eé]s?\b", r"\bcatering\b", r"\bcarry\s?-?out\b",
    r"\bseat(?:s|ing)\b", r"\bdining\b", r"\bbakery\b", r"\bdeli\b", r"\bfood\b",
    r"\bconv[a-z]*nce\s+stores?\b", r"\bstores?\b", r"\bretail\b", r"\bshopping\b",
    r"\bmarket\b", r"\bwholesale\b", r"\bbusiness(?:es)?\b", r"\bbanks?\b",
    r"\boffices?\b", r"\bhotels?\b", r"\bcommercial\s+(?:use|space|building)s?\b",
    r"\b(?:child|day|elder)\s?care\b", r"\bschools?\b", r"\bclassrooms?\b", r"\bchurch(?:es)?\b",
    r"\bnursing\s+homes?\b", r"\bsocial\s+service\b", r"\bmedical\b", r"\bhospitals?\b",
    r"\bauto(?:mobile|motive)?\b", r"\bservice\s+station\b", r"\bgas(?:oline)?\b", r"\bcar\s+wash\b",
    r"\bdry\s?clean", r"\bsalons?\b", r"\bbarber", r"\bmassage\b", r"\bfitness\b", r"\bgym\b",
    r"\banimals?\b", r"\bveterinar", r"\bkennels?\b", r"\bdogs?\b", r"\bgrooming\b",
    r"\bamusement\b", r"\btheat(?:er|re)s?\b", r"\bclubs?\b", r"\bmarina\b", r"\bboats?\b",
    r"\bstorage\b", r"\bwarehouses?\b", r"\brecycling\b", r"\bwastewater\b", r"\butility\b",
    r"\btelecommunications?\b", r"\bfire\s+station\b", r"\bpublic\s+building\b",
    r"\bparks?\b", r"\bplaygrounds?\b", r"\bathletic\b", r"\b(?:ball)?fields?\b", r"\bnetting\b",
    r"\bbackstop\b",
    # Parking and transportation plans
    r"\bTMP\b", r"\btransportation\s+man[a-z]*\s+plan\b", r"\bparking\s+(?:lot|garage|facility)s?\b",
    # Signs, and parts of a lot that aren't the home itself
    r"\bsigns?\b", r"\bsignage\b", r"\bfences?\b", r"\bretaining\s+walls?\b", r"\bsheds?\b",
    r"\bdetached\s+garages?\b", r"\b(?:swimming\s+)?pools?\b",
    r"\baccessory\s+(?:buildings?|structures?|dwellings?)\b",
    # Appeals of a zoning decision grant nothing by themselves. The Board of
    # Zoning Appeals' own name is not an appeal.
    r"(?<!zoning )\bappeal(?:s|ed)?\s+(?:of|from)\b", r"\bappellants?\b",
]))


def tags_for(case: dict) -> set[str]:
    """The tags a case's descriptions and document types give it.

    A description that mentions anything in ``NOT_THE_HOME`` gives the whole
    case no tags. Document types are only matched for tags, since they name
    kinds of files ("Staff Report to BZA/BAR"), not what the case is about.
    """
    descriptions = [text for text in case.get("descriptions") or [] if text]
    if any(NOT_THE_HOME.search(text) for text in descriptions):
        return set()
    texts = descriptions + [doc.get("type") or "" for doc in case.get("documents") or []]
    is_variance = case.get("kind") == "BZA"
    return {
        tag for tag, pattern in KEYWORDS
        if tag.startswith("variance:") == is_variance and any(pattern.search(text) for text in texts)
    }


def load_overrides(path: Path = OVERRIDES_PATH) -> dict:
    """Read the hand-made corrections file."""
    return json.loads(Path(path).read_text())


_OVERRIDE_FIELDS = {"tags", "parcel_ids", "ignore", "source"}


def _check_override(case: str, override: dict, cases: dict[str, dict]) -> None:
    if case not in cases:
        raise ValueError(f"Override for {case}, which is not in the catalog")
    unknown = set(override) - _OVERRIDE_FIELDS
    if unknown:
        raise ValueError(f"Override for {case} has unknown fields: {sorted(unknown)}")
    if not str(override.get("source") or "").strip():
        raise ValueError(f"Override for {case} needs a source note")
    for field in ("tags", "parcel_ids"):
        value = override.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Override for {case}: {field} must be a list of text values")
    bad_tags = set(override.get("tags") or []) - set(TAG_RULE_IDS)
    if bad_tags:
        raise ValueError(f"Override for {case} has unknown tags: {sorted(bad_tags)}")


def apply_overrides(cases: dict[str, dict], overrides: dict) -> dict[str, dict]:
    """Return the cases with the hand-made corrections applied.

    An override can replace a case's ``tags``, add ``parcel_ids``, or
    ``ignore`` the case, which leaves it out of the result. Every override
    needs a ``source`` note. The cases passed in are not changed.
    """
    result = dict(cases)
    for case, override in (overrides.get("cases") or {}).items():
        _check_override(case, override, cases)
        if override.get("ignore"):
            result.pop(case, None)
            continue
        record = dict(result[case])
        if "tags" in override:
            record["tags"] = list(override["tags"])
        if "parcel_ids" in override:
            existing = list(record.get("parcel_ids") or [])
            record["parcel_ids"] = existing + [p for p in override["parcel_ids"] if p not in existing]
        result[case] = record
    return result
