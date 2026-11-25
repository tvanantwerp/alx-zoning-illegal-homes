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
(`DEVELOPMENT_WIDE`). Everything else needs a parcel, address or hand-made
override match.

A row past the permit's ceiling still fails, and its explanation says the
case is on file. With no cases, nothing changes.
"""
from alx_zoning_illegal_homes.permits.match import HOW_ORDER, CaseMatch
from alx_zoning_illegal_homes.permits.tags import TAG_RULE_IDS

from .checks import Findings
from .rule_results import FAILS, NOT_CHECKED, PERMIT_ON_FILE, RuleResult, reason_kind

DEVELOPMENT_WIDE = frozenset({
    "tract", "townhouse_row", "homes_near_eisenhower", "extra_height", "extra_floor_area"})
CLOSE_MATCHES = frozenset({"override", "parcel", "address"})


def _close_enough(tag: str, how: str) -> bool:
    """Whether a case matched to the lot `how` is sure enough to settle a rule with `tag`."""
    return how in CLOSE_MATCHES or (how == "outline" and tag in DEVELOPMENT_WIDE)


def _covering(row: RuleResult, cases: list[dict], how_by_case: dict[str, str]):
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


def _add(explanation: str | None, text: str) -> str:
    return f"{explanation} {text}" if explanation else text


def apply_permits(findings: Findings, cases: list[dict], matches: list[CaseMatch]) -> None:
    """Settle the rows of `findings` that a permit on file for the lot allows.

    `cases` are the lot's cases, each with its "case" number, "year" and
    "tags"; `matches` say how each was matched to the lot. Settled rows get
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
        found = _covering(row, cases, how_by_case)
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
