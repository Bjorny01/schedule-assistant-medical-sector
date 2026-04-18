"""Tests for src/solver.py

Uses a minimal setup: 2 nurses + 1 doctor, 1 week, low department requirements
so the solver runs quickly while still exercising all constraint tiers.

Schedule start: 2024-01-01 (Monday).
"""
from datetime import date, timedelta

import pytest

from src.models import (
    DepartmentRequirements,
    ParsedInputs,
    Role,
    ShiftType,
    Staff,
    StaffConstraints,
    StaffPreferences,
    WorkLawRules,
)
from src.solver import build_schedule

START = date(2024, 1, 1)  # Monday


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_nurse(name, contract_pct=1.0, max_weekly=5, **constraint_kwargs):
    return Staff(
        name=name,
        role=Role.NURSE,
        contract_pct=contract_pct,
        constraints=StaffConstraints(max_weekly_shifts=max_weekly, **constraint_kwargs),
    )


def _make_doctor(name, contract_pct=1.0, max_weekly=5, **constraint_kwargs):
    return Staff(
        name=name,
        role=Role.DOCTOR,
        contract_pct=contract_pct,
        constraints=StaffConstraints(max_weekly_shifts=max_weekly, **constraint_kwargs),
    )


def _minimal_dept():
    """Requirements achievable by 2 nurses + 1 doctor over 1 week.

    Weekday: 1 nurse + 1 doctor on day shift only.
    Weekend: 1 nurse on day shift, no doctor required.
    This keeps total required shifts well within the 5-shift weekly cap.
    """
    return DepartmentRequirements(
        department_name="Test Ward",
        min_nurses_day=1,
        min_nurses_evening=0,
        min_nurses_night=0,
        min_doctors_day=1,
        min_doctors_evening=0,
        min_doctors_night=0,
        min_nurses_weekend_day=1,
        min_nurses_weekend_evening=0,
        min_nurses_weekend_night=0,
        min_doctors_weekend_day=0,
        min_doctors_weekend_evening=0,
        min_doctors_weekend_night=0,
    )


@pytest.fixture
def minimal_inputs():
    return ParsedInputs(
        staff=[
            _make_nurse("Alice", contract_pct=1.0, max_weekly=5),
            _make_nurse("Bob",   contract_pct=0.8, max_weekly=4),
            _make_doctor("Carol", contract_pct=1.0, max_weekly=5),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )


# ---------------------------------------------------------------------------
# Basic feasibility
# ---------------------------------------------------------------------------

def test_build_schedule_returns_schedule(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    assert schedule is not None


def test_build_schedule_has_assignments(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    assert len(schedule.assignments) > 0


def test_build_schedule_status_is_feasible_or_optimal(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    assert schedule.solver_status in ("OPTIMAL", "FEASIBLE")


def test_build_schedule_start_date_recorded(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    assert schedule.start_date == START


def test_build_schedule_num_weeks_recorded(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    assert schedule.num_weeks == 1


# ---------------------------------------------------------------------------
# HC-01: at most 1 shift per person per calendar day
# ---------------------------------------------------------------------------

def test_no_double_shift_per_day(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    for staff in minimal_inputs.staff:
        dates = [a.date for a in schedule.get_staff_assignments(staff.name)]
        assert len(dates) == len(set(dates)), (
            f"{staff.name} was assigned two shifts on the same day"
        )


# ---------------------------------------------------------------------------
# HC-05: at most max_shifts_per_week shifts in any calendar week
# ---------------------------------------------------------------------------

def test_weekly_shift_cap_not_exceeded(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    for staff in minimal_inputs.staff:
        total = schedule.total_shifts_for(staff.name)
        assert total <= staff.max_shifts_per_week, (
            f"{staff.name} has {total} shifts but cap is {staff.max_shifts_per_week}"
        )


# ---------------------------------------------------------------------------
# TIER 2: department minimum staffing
# ---------------------------------------------------------------------------

def test_min_nurse_day_shift_met_every_day(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    nurse_names = {s.name for s in minimal_inputs.staff if s.role == Role.NURSE}
    for d in range(7):
        day = START + timedelta(days=d)
        nurses_on_day = [
            a for a in schedule.get_day_assignments(day)
            if a.staff_name in nurse_names and a.shift_type == ShiftType.DAY
        ]
        assert len(nurses_on_day) >= 1, f"No nurse on day shift for {day}"


def test_min_doctor_day_shift_met_on_weekdays(minimal_inputs):
    schedule = build_schedule(minimal_inputs, START, num_weeks=1)
    doctor_names = {s.name for s in minimal_inputs.staff if s.role == Role.DOCTOR}
    for d in range(5):  # Mon–Fri only (weekend min_doctors_weekend_day=0)
        day = START + timedelta(days=d)
        doctors_on_day = [
            a for a in schedule.get_day_assignments(day)
            if a.staff_name in doctor_names and a.shift_type == ShiftType.DAY
        ]
        assert len(doctors_on_day) >= 1, f"No doctor on day shift for {day}"


# ---------------------------------------------------------------------------
# TIER 3: mandatory days off
# ---------------------------------------------------------------------------

def test_mandatory_day_off_respected():
    off_date = START + timedelta(days=2)  # Wednesday
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice", mandatory_days_off=[off_date]),
            _make_nurse("Bob"),
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    alice_dates = [a.date for a in schedule.get_staff_assignments("Alice")]
    assert off_date not in alice_dates


# ---------------------------------------------------------------------------
# TIER 3: recurring weekday off
# ---------------------------------------------------------------------------

def test_recurring_day_off_respected():
    # Bob never works on Fridays (weekday index 4)
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice"),
            _make_nurse("Bob", recurring_days_off=[4]),
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    for a in schedule.get_staff_assignments("Bob"):
        assert a.date.weekday() != 4, f"Bob worked on a Friday: {a.date}"


# ---------------------------------------------------------------------------
# TIER 3: allowed shift types
# ---------------------------------------------------------------------------

def test_allowed_shifts_restricts_to_day_only():
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice"),
            _make_nurse("Bob"),
            _make_doctor("Carol", allowed_shifts=[ShiftType.DAY]),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    for a in schedule.get_staff_assignments("Carol"):
        assert a.shift_type == ShiftType.DAY, (
            f"Carol was assigned a {a.shift_type.value} shift despite day-only restriction"
        )


# ---------------------------------------------------------------------------
# Infeasible problem → None
# ---------------------------------------------------------------------------

def test_infeasible_requirements_returns_none():
    """Require 5 nurses per shift with only 2 available — must be infeasible."""
    impossible_dept = DepartmentRequirements(
        min_nurses_day=5,
        min_nurses_evening=5,
        min_nurses_night=5,
    )
    inputs = ParsedInputs(
        staff=[_make_nurse("Alice"), _make_nurse("Bob"), _make_doctor("Carol")],
        dept_requirements=impossible_dept,
        law_rules=WorkLawRules(),
    )
    result = build_schedule(inputs, START, num_weeks=1)
    assert result is None


# ---------------------------------------------------------------------------
# TIER 3 HARD: mandatory_shifts_off (shift-level specific date)
# ---------------------------------------------------------------------------

def test_mandatory_shift_off_blocks_only_specified_shift():
    """The blocked shift on that date must not be scheduled for that person."""
    off_date = START + timedelta(days=2)  # Wednesday
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice", mandatory_shifts_off=[(off_date, ShiftType.NIGHT)]),
            _make_nurse("Bob"),
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    alice_on_off_date = [
        a for a in schedule.get_staff_assignments("Alice") if a.date == off_date
    ]
    assert all(a.shift_type != ShiftType.NIGHT for a in alice_on_off_date), (
        f"Alice assigned night despite mandatory_shifts_off: {alice_on_off_date}"
    )


def test_mandatory_shift_off_permits_other_shifts_same_date():
    """Alice can still work day or evening on a date with only night blocked.

    Setup: 2 nurses — Bob has Mondays off entirely, so Alice is the only nurse
    available for Monday day. Alice also has a Monday-night mandatory_shifts_off
    block; that must not prevent her Monday day assignment.
    """
    off_date = START  # Monday
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice", mandatory_shifts_off=[(off_date, ShiftType.NIGHT)]),
            _make_nurse("Bob", recurring_days_off=[0]),  # Bob off all Mondays
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    alice_mon_day = [
        a for a in schedule.get_staff_assignments("Alice")
        if a.date == off_date and a.shift_type == ShiftType.DAY
    ]
    assert len(alice_mon_day) == 1


# ---------------------------------------------------------------------------
# TIER 3 HARD: recurring_shifts_off (shift-level recurring weekday)
# ---------------------------------------------------------------------------

def test_recurring_shift_off_never_schedules_blocked_shift():
    """Bob never works Friday nights, but other Friday shifts are bookable."""
    inputs = ParsedInputs(
        staff=[
            _make_nurse("Alice"),
            _make_nurse("Bob", recurring_shifts_off=[(4, ShiftType.NIGHT)]),  # Fri
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    for a in schedule.get_staff_assignments("Bob"):
        if a.date.weekday() == 4:
            assert a.shift_type != ShiftType.NIGHT, (
                f"Bob scheduled night on Friday {a.date} despite recurring_shifts_off"
            )


# ---------------------------------------------------------------------------
# SOFT: preferred_shifts_off  (penalty + broken-pref reporting)
# ---------------------------------------------------------------------------

def test_preferred_shift_off_reported_when_violated():
    """Alice must work Mon day (Bob blocked) — the pref-off must be flagged."""
    inputs = ParsedInputs(
        staff=[
            _make_nurse(
                "Alice",
                preferences=StaffPreferences(
                    preferred_shifts_off=[(0, ShiftType.DAY)]  # Mondays (day)
                ),
            ),
            _make_nurse("Bob", recurring_days_off=[0]),  # Bob off all Mondays
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    alice_mon_day = [
        a for a in schedule.get_staff_assignments("Alice")
        if a.date == START and a.shift_type == ShiftType.DAY
    ]
    assert len(alice_mon_day) == 1
    alice_broken = [m for m in schedule.infeasible_preferences if "Alice" in m]
    assert any("Monday" in m and "day" in m.lower() for m in alice_broken), (
        f"Expected Alice broken-pref about Monday day; got: {alice_broken}"
    )


def test_preferred_shift_off_does_not_penalise_other_shifts_same_weekday():
    """Pref-off on Monday evening must NOT produce a broken-pref when Alice works Monday day."""
    inputs = ParsedInputs(
        staff=[
            _make_nurse(
                "Alice",
                preferences=StaffPreferences(
                    preferred_shifts_off=[(0, ShiftType.EVENING)]  # Monday evening only
                ),
            ),
            _make_nurse("Bob", recurring_days_off=[0]),
            _make_doctor("Carol"),
        ],
        dept_requirements=_minimal_dept(),
        law_rules=WorkLawRules(),
    )
    schedule = build_schedule(inputs, START, num_weeks=1)
    assert schedule is not None
    alice_broken = [m for m in schedule.infeasible_preferences if "Alice" in m]
    assert not any(
        "evening" in m.lower() and "preference: evening off" in m.lower()
        for m in alice_broken
    ), (
        f"Unexpected Monday-evening pref-off broken-pref for Alice: {alice_broken}"
    )
