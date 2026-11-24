"""King Street retail stepback above a rear boundary shared with homes."""
from shapely.geometry import box

from .helpers import between_neighbors, check


def _stepback(residential, front_peak=40, rear_sections=True, units=3):
    lot = box(0, 0, 50, 100)
    front = box(5, 10, 45, 40)
    rear = box(5, 40, 45, 90)
    sections = [(front, front_peak)] + ([(rear, 10)] if rear_sections else [])
    kinds, findings = check(
        lot, front.union(rear), "KR", home_type="multi", units=units,
        neighbors=between_neighbors(lot), sections=sections,
        residential_abutters=residential)
    return kinds, next(row for row in findings.results if row.rule == "height_at_rear")


def test_rear_stepback_checks_each_roof_part_at_its_own_distance():
    kinds, row = _stepback(box(0, 100, 50, 150))
    assert "height" not in kinds
    assert row.status == "passes" and row.measured == 10
    kinds, row = _stepback(box(0, 100, 50, 150), front_peak=55)
    assert "height" in kinds
    assert row.status == "fails" and row.measured == 55 and row.required == 45


def test_rear_stepback_requires_residential_use_on_the_rear_line():
    for residential in (None, box(-50, 0, 0, 100), box(50, 100, 75, 125)):
        _, row = _stepback(residential)
        assert row.status == "not_required"


def test_rear_stepback_pass_needs_roof_coverage_and_a_site_plan_trigger():
    _, row = _stepback(box(0, 100, 50, 150), rear_sections=False)
    assert row.status == "not_checked"
    _, row = _stepback(box(0, 100, 50, 150), units=2)
    assert row.status == "not_checked"
