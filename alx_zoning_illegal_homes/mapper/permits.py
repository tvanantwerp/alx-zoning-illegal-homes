"""Letting a city permit on file settle a rule row that fails for want of it.

The checks in `checks.py` mark each row that fails, or can't be judged, only
because the map can't see a permit the ordinance allows on that lot: the row
gets the permit tags that could settle it (`RuleResult.permit_tags`), and
`RuleResult.permit_can_allow` when the building is within the most such a
permit can allow. `apply_permits` then looks at the lot's matched cases.

A case settles a row, turning it to `PERMIT_ON_FILE`, when one of its tags
covers the row's rule (`TAG_RULE_IDS`) and either:

- the tag is one of the row's permit tags and the row is within the permit's
  ceiling, or
- the tag is a variance (`variance:<rule>`), which the Board of Zoning
  Appeals grants for one lot and one rule, whatever the zone.

The match has to be close enough. A case found only by a map point inside
the lot never settles a row, since points sometimes land on the lot next
door. A site plan outline can cover hundreds of lots, so a case found that
way settles only the rules a whole development is approved for
(`DEVELOPMENT_WIDE`). Everything else needs a parcel or address match. A
hand-made override works through the parcel IDs it adds, which then match as
"parcel".

A permit for building a new home (`BUILT_UNDER_PERMIT`) settles a row only
when the home on the lot is the one it allowed: the year the oldest home
was built must be known and no earlier than the year before the case's
year, since a case is numbered by the year it was filed. With either year
unknown it settles nothing, though the case is still listed on the lot.

A row past the permit's ceiling still fails, and its explanation says the
case is on file. Either way, the sentences saying the map has no record of
such a permit are dropped, since now it has one. With no cases, nothing
changes.

`lot_permits` lists every case matched to a lot for the lot's file.
"""
import re

from alx_zoning_illegal_homes.permits.archive import document_url, search_url
from alx_zoning_illegal_homes.permits.match import HOW_ORDER, CaseMatch
from alx_zoning_illegal_homes.permits.tags import TAG_RULE_IDS

from .checks import Findings
from .rule_results import FAILS, NOT_CHECKED, PERMIT_ON_FILE, RuleResult, reason_kind

DEVELOPMENT_WIDE = frozenset({
    "tract", "townhouse_row", "homes_near_eisenhower", "extra_height", "extra_floor_area"})
CLOSE_MATCHES = frozenset({"parcel", "address"})
# Tags for permits that allow building a new home. An older home on the lot
# isn't the one the permit allowed.
BUILT_UNDER_PERMIT = frozenset({"undersized_lot", "no_frontage"})


def _close_enough(tag: str, how: str) -> bool:
    """Whether a case matched to the lot `how` is sure enough to settle a rule with `tag`."""
    return how in CLOSE_MATCHES or (how == "outline" and tag in DEVELOPMENT_WIDE)


def _home_built_under(case: dict, year_built: int | None) -> bool:
    """Whether a home built in `year_built` can be the one this case allowed."""
    year = case.get("year")
    return year_built is not None and year is not None and year_built >= year - 1


def _covering(row: RuleResult, cases: list[dict], how_by_case: dict[str, str],
              year_built: int | None):
    """The cases that speak to this row, each as (case, how, whether it can settle the row)."""
    found = []
    for case in cases:
        how = how_by_case.get(case["case"])
        if how is None:
            continue
        settles = None
        for tag in case.get("tags") or ():
            if row.rule not in TAG_RULE_IDS.get(tag, ()) or not _close_enough(tag, how):
                continue
            if tag in BUILT_UNDER_PERMIT and not _home_built_under(case, year_built):
                continue
            if tag.startswith("variance:"):
                settles = True
            elif tag in row.permit_tags:
                settles = bool(settles or row.permit_can_allow)
        if settles is not None:
            found.append((case, how, settles))
    return found


def _surest(found):
    """The case matched most surely, then the newest."""
    return min(found, key=lambda item: (HOW_ORDER.index(item[1]), -(item[0].get("year") or 0)))


# Sentences in the checks' explanations that say the map can't see a permit.
_NO_RECORD = ("has no record of", "can't verify eligibility or count that permit")
# A sentence ends at a period followed by a space and a capital letter, so a
# number like "30.5 ft" doesn't split one.
_SENTENCE_END = re.compile(r"(?<=\.)\s+(?=[A-Z])")


def _add(explanation: str | None, text: str) -> str:
    """Add `text` to an explanation, first dropping any sentence saying there's no record of it."""
    if not explanation:
        return text
    kept = [sentence for sentence in _SENTENCE_END.split(explanation)
            if not any(phrase in sentence for phrase in _NO_RECORD)]
    return " ".join([*kept, text])


def apply_permits(findings: Findings, cases: list[dict], matches: list[CaseMatch],
                  year_built: int | None = None) -> None:
    """Settle the rows of `findings` that a permit on file for the lot allows.

    `cases` are the lot's cases, each with its "case" number, "year" and
    "tags"; `matches` say how each was matched to the lot. `year_built` is
    the year the lot's oldest home was built, if known; without it, permits
    for building a new home settle nothing. Settled rows get
    `PERMIT_ON_FILE` and `permit`, and the failing reasons go once no row
    of their kind still fails.
    """
    how_by_case: dict[str, str] = {}
    for match in matches:
        known = how_by_case.get(match.case)
        if known is None or HOW_ORDER.index(match.how) < HOW_ORDER.index(known):
            how_by_case[match.case] = match.how
    settled_kinds = set()
    for row in findings.results:
        if row.status not in (FAILS, NOT_CHECKED):
            continue
        found = _covering(row, cases, how_by_case, year_built)
        settling = [item for item in found if item[2]]
        if settling:
            case, how, _ = _surest(settling)
            row.status = PERMIT_ON_FILE
            row.permit = {"case": case["case"], "how": how}
            row.explanation = _add(row.explanation, f"City case {case['case']} is on file for this.")
            settled_kinds.add(reason_kind(row.rule))
        elif found and row.status == FAILS:
            case, _, _ = _surest(found)
            row.explanation = _add(row.explanation, (
                f"City case {case['case']} is on file for this, but no permit can allow "
                "this much."))
    still_failing = {reason_kind(row.rule) for row in findings.results if row.status == FAILS}
    gone = settled_kinds - still_failing
    if gone:
        findings.reasons = [reason for reason in findings.reasons if reason.kind not in gone]


def _description(case: dict) -> str:
    """One line saying what a case is about: its description, project name, or first document."""
    for value in (*(case.get("descriptions") or ()), *(case.get("project_names") or ())):
        if value:
            return value
    documents = case.get("documents") or ()
    return (documents[0].get("name") or "") if documents else ""


def lot_permits(cases: list[dict], matches: list[CaseMatch], *results: list) -> list[dict]:
    """The lot file's list of the cases matched to a lot, newest year first, then by case.

    `cases` and `matches` are the lot's, as for `apply_permits`. `results`
    are the lot's lists of rule rows after `apply_permits`; each case's
    "grants" are the rules it settled in any of them.
    """
    how_by_case = {match.case: match.how for match in matches}
    grants: dict[str, set[str]] = {}
    for rows in results:
        for row in rows:
            if row.permit:
                grants.setdefault(row.permit["case"], set()).add(row.rule)
    listed = [{
        "case": case["case"],
        "kind": case.get("kind"),
        "year": case.get("year"),
        "description": _description(case),
        "how": how_by_case.get(case["case"]),
        "grants": sorted(grants.get(case["case"], ())),
        "links": [{"name": document.get("name") or "", "url": document_url(document["id"])}
                  for document in case.get("documents") or ()],
        "search_url": search_url(case["case"]),
    } for case in cases]
    return sorted(listed, key=lambda item: (-(item["year"] or 0), item["case"]))
