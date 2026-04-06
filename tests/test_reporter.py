"""Tests for src/reporter.py

generate_report and _call_llm are intentionally skipped — they require an
Anthropic API key.  Only _build_schedule_summary is tested here.
"""
from datetime import date, timedelta

import pytest

from src.models import (
    DepartmentRequirements,
    ParsedInputs,
    Role,
    Schedule,
    ShiftAssignment,
    ShiftType,
    Staff,
    StaffConstraints,
    WorkLawRules,
)
from src.reporter import _build_schedule_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_inputs():
    return ParsedInputs(
        staff=[
            Staff("Alice", Role.NURSE, 1.0, StaffConstraints()),
            Staff("Carol", Role.DOCTOR, 1.0, StaffConstraints()),
        ],
        dept_requirements=DepartmentRequirements(department_name="Test Ward"),
        law_rules=WorkLawRules(),
    )


@pytest.fixture
def sample_schedule():
    start = date(2024, 1, 1)
    assignments = [
        ShiftAssignment("Alice", start + timedelta(days=d), ShiftType.DAY)
        for d in range(5)
    ] + [
        ShiftAssignment("Carol", start + timedelta(days=d), ShiftType.DAY)
        for d in range(5)
    ]
    return Schedule(
        assignments=assignments,
        start_date=start,
        num_weeks=1,
        solver_status="OPTIMAL",
    )


# ---------------------------------------------------------------------------
# Header / metadata
# ---------------------------------------------------------------------------

def test_summary_contains_schedule_summary_header(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "SCHEDULE SUMMARY" in text


def test_summary_contains_department_name(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "Test Ward" in text


def test_summary_contains_solver_status(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "OPTIMAL" in text


def test_summary_contains_planning_period(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "2024-01-01" in text


def test_summary_contains_num_weeks(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "1" in text  # num_weeks


# ---------------------------------------------------------------------------
# Per-staff section
# ---------------------------------------------------------------------------

def test_summary_contains_alice(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "Alice" in text


def test_summary_contains_carol(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "Carol" in text


def test_summary_contains_shift_type_counts(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    # Alice has 5 day shifts, 0 evening, 0 night
    assert "Day=5" in text
    assert "Eve=0" in text
    assert "Night=0" in text


def test_summary_contains_week_breakdown(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "Week breakdown" in text


# ---------------------------------------------------------------------------
# Daily staffing section
# ---------------------------------------------------------------------------

def test_summary_contains_daily_staffing_header(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "DAILY STAFFING LEVELS" in text


def test_summary_contains_date_rows(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "2024-01-01" in text


# ---------------------------------------------------------------------------
# Broken preferences section
# ---------------------------------------------------------------------------

def test_summary_no_broken_prefs_message(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "None — all soft preferences were honoured." in text


def test_summary_lists_broken_prefs_when_present():
    start = date(2024, 1, 1)
    schedule = Schedule(
        assignments=[ShiftAssignment("Alice", start, ShiftType.NIGHT)],
        start_date=start,
        num_weeks=1,
        solver_status="FEASIBLE",
        infeasible_preferences=[
            "Alice: scheduled night on 2024-01-01 (preference: avoid this shift type)"
        ],
    )
    inputs = ParsedInputs(
        staff=[Staff("Alice", Role.NURSE, 1.0, StaffConstraints())],
        dept_requirements=DepartmentRequirements(),
        law_rules=WorkLawRules(),
    )
    text = _build_schedule_summary(schedule, inputs)
    assert "BROKEN PREFERENCES" in text
    assert "Alice" in text


def test_summary_broken_prefs_section_present(sample_schedule, sample_inputs):
    text = _build_schedule_summary(sample_schedule, sample_inputs)
    assert "BROKEN PREFERENCES" in text
