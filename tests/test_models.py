"""Tests for src/models.py"""
from datetime import date

import pytest

from src.models import (
    SHIFT_IDX,
    SHIFT_LIST,
    SHIFT_END_HOUR,
    SHIFT_START_HOUR,
    Role,
    Schedule,
    ShiftAssignment,
    ShiftType,
    Staff,
    StaffConstraints,
    StaffPreferences,
)


# ---------------------------------------------------------------------------
# ShiftType / constants
# ---------------------------------------------------------------------------

def test_shift_type_values():
    assert ShiftType.DAY.value == "day"
    assert ShiftType.EVENING.value == "evening"
    assert ShiftType.NIGHT.value == "night"


def test_shift_list_order():
    assert SHIFT_LIST == [ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT]


def test_shift_idx_mapping():
    assert SHIFT_IDX[ShiftType.DAY] == 0
    assert SHIFT_IDX[ShiftType.EVENING] == 1
    assert SHIFT_IDX[ShiftType.NIGHT] == 2


def test_shift_start_hours():
    assert SHIFT_START_HOUR[ShiftType.DAY] == 7
    assert SHIFT_START_HOUR[ShiftType.EVENING] == 15
    assert SHIFT_START_HOUR[ShiftType.NIGHT] == 23


def test_shift_end_hours():
    assert SHIFT_END_HOUR[ShiftType.DAY] == 15
    assert SHIFT_END_HOUR[ShiftType.EVENING] == 23
    assert SHIFT_END_HOUR[ShiftType.NIGHT] == 7  # next calendar day


# ---------------------------------------------------------------------------
# Staff properties
# ---------------------------------------------------------------------------

def _make_staff(role=Role.NURSE, contract_pct=1.0, max_weekly=5):
    return Staff(
        name="Test",
        role=role,
        contract_pct=contract_pct,
        constraints=StaffConstraints(max_weekly_shifts=max_weekly),
    )


def test_staff_target_shifts_full_time():
    assert _make_staff(contract_pct=1.0).target_shifts_per_week == pytest.approx(5.0)


def test_staff_target_shifts_part_time_80():
    assert _make_staff(contract_pct=0.8).target_shifts_per_week == pytest.approx(4.0)


def test_staff_target_shifts_part_time_60():
    assert _make_staff(contract_pct=0.6).target_shifts_per_week == pytest.approx(3.0)


def test_staff_max_shifts_per_week():
    assert _make_staff(max_weekly=4).max_shifts_per_week == 4


def test_staff_max_shifts_per_week_from_constraints():
    staff = _make_staff(max_weekly=3)
    assert staff.max_shifts_per_week == staff.constraints.max_weekly_shifts


# ---------------------------------------------------------------------------
# ShiftAssignment
# ---------------------------------------------------------------------------

def test_shift_assignment_repr_contains_name():
    a = ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY)
    assert "Alice" in repr(a)


def test_shift_assignment_repr_contains_date():
    a = ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY)
    assert "2024-01-01" in repr(a)


def test_shift_assignment_repr_contains_shift_type():
    a = ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.NIGHT)
    assert "night" in repr(a)


# ---------------------------------------------------------------------------
# Schedule methods
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_schedule():
    assignments = [
        ShiftAssignment("Alice", date(2024, 1, 3), ShiftType.DAY),
        ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.EVENING),
        ShiftAssignment("Bob",   date(2024, 1, 1), ShiftType.NIGHT),
        ShiftAssignment("Alice", date(2024, 1, 2), ShiftType.DAY),
    ]
    return Schedule(assignments=assignments, start_date=date(2024, 1, 1), num_weeks=1)


def test_get_staff_assignments_filters_by_name(sample_schedule):
    alice = sample_schedule.get_staff_assignments("Alice")
    assert all(a.staff_name == "Alice" for a in alice)
    assert len(alice) == 3


def test_get_staff_assignments_sorted_by_date(sample_schedule):
    alice = sample_schedule.get_staff_assignments("Alice")
    dates = [a.date for a in alice]
    assert dates == sorted(dates)


def test_get_staff_assignments_excludes_other_staff(sample_schedule):
    alice = sample_schedule.get_staff_assignments("Alice")
    assert all(a.staff_name != "Bob" for a in alice)


def test_get_staff_assignments_empty_for_unknown(sample_schedule):
    assert sample_schedule.get_staff_assignments("Unknown") == []


def test_get_day_assignments_returns_all_on_day(sample_schedule):
    day1 = sample_schedule.get_day_assignments(date(2024, 1, 1))
    assert len(day1) == 2
    assert {a.staff_name for a in day1} == {"Alice", "Bob"}


def test_get_day_assignments_empty_for_unscheduled_day(sample_schedule):
    assert sample_schedule.get_day_assignments(date(2024, 1, 10)) == []


def test_total_shifts_for_alice(sample_schedule):
    assert sample_schedule.total_shifts_for("Alice") == 3


def test_total_shifts_for_bob(sample_schedule):
    assert sample_schedule.total_shifts_for("Bob") == 1


def test_total_shifts_for_unknown(sample_schedule):
    assert sample_schedule.total_shifts_for("Unknown") == 0


# ---------------------------------------------------------------------------
# Shift-level off fields — defaults and assignment
# ---------------------------------------------------------------------------

def test_staff_constraints_default_mandatory_shifts_off_empty():
    assert StaffConstraints().mandatory_shifts_off == []


def test_staff_constraints_default_recurring_shifts_off_empty():
    assert StaffConstraints().recurring_shifts_off == []


def test_staff_preferences_default_preferred_shifts_off_empty():
    assert StaffPreferences().preferred_shifts_off == []


def test_staff_constraints_stores_mandatory_shifts_off():
    c = StaffConstraints(
        mandatory_shifts_off=[(date(2024, 3, 15), ShiftType.NIGHT)]
    )
    assert (date(2024, 3, 15), ShiftType.NIGHT) in c.mandatory_shifts_off


def test_staff_constraints_stores_recurring_shifts_off():
    c = StaffConstraints(
        recurring_shifts_off=[(4, ShiftType.EVENING)]  # Friday evening
    )
    assert (4, ShiftType.EVENING) in c.recurring_shifts_off


def test_staff_preferences_stores_preferred_shifts_off():
    p = StaffPreferences(preferred_shifts_off=[(5, ShiftType.DAY)])
    assert (5, ShiftType.DAY) in p.preferred_shifts_off
