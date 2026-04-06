"""Tests for src/exporters.py

Both icalendar and openpyxl are required.  If either is not installed,
the entire module is skipped via pytest.importorskip.
"""
from datetime import date, timedelta

import pytest

icalendar = pytest.importorskip("icalendar")
openpyxl = pytest.importorskip("openpyxl")

from src.exporters import _make_ical_event, export_excel, export_ics_files
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
        dept_requirements=DepartmentRequirements(),
        law_rules=WorkLawRules(),
    )


@pytest.fixture
def sample_schedule():
    start = date(2024, 1, 1)
    return Schedule(
        assignments=[
            ShiftAssignment("Alice", start,                       ShiftType.DAY),
            ShiftAssignment("Alice", start + timedelta(days=1),   ShiftType.EVENING),
            ShiftAssignment("Alice", start + timedelta(days=2),   ShiftType.NIGHT),
            ShiftAssignment("Carol", start,                       ShiftType.DAY),
        ],
        start_date=start,
        num_weeks=1,
        solver_status="OPTIMAL",
    )


# ---------------------------------------------------------------------------
# _make_ical_event — day shift
# ---------------------------------------------------------------------------

def test_ical_event_day_shift_start_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY))
    assert event["dtstart"].dt.hour == 7


def test_ical_event_day_shift_end_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY))
    assert event["dtend"].dt.hour == 15


def test_ical_event_day_shift_same_day():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY))
    assert event["dtstart"].dt.date() == event["dtend"].dt.date()


# ---------------------------------------------------------------------------
# _make_ical_event — evening shift
# ---------------------------------------------------------------------------

def test_ical_event_evening_shift_start_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.EVENING))
    assert event["dtstart"].dt.hour == 15


def test_ical_event_evening_shift_end_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.EVENING))
    assert event["dtend"].dt.hour == 23


# ---------------------------------------------------------------------------
# _make_ical_event — night shift (ends next calendar day)
# ---------------------------------------------------------------------------

def test_ical_event_night_shift_start_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.NIGHT))
    assert event["dtstart"].dt.hour == 23


def test_ical_event_night_shift_end_next_day():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.NIGHT))
    assert event["dtend"].dt.date() == date(2024, 1, 2)


def test_ical_event_night_shift_end_hour():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.NIGHT))
    assert event["dtend"].dt.hour == 7


# ---------------------------------------------------------------------------
# _make_ical_event — summary and description
# ---------------------------------------------------------------------------

def test_ical_event_summary_contains_shift_label():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY))
    assert "Day" in str(event["summary"])


def test_ical_event_description_contains_staff_name():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.EVENING))
    assert "Alice" in str(event["description"])


def test_ical_event_status_confirmed():
    event = _make_ical_event(ShiftAssignment("Alice", date(2024, 1, 1), ShiftType.DAY))
    assert str(event["status"]).upper() == "CONFIRMED"


# ---------------------------------------------------------------------------
# export_ics_files
# ---------------------------------------------------------------------------

def test_export_ics_files_creates_one_file_per_staff(tmp_path, sample_schedule, sample_inputs):
    export_ics_files(sample_schedule, sample_inputs, tmp_path)
    ics_files = list(tmp_path.glob("*.ics"))
    assert len(ics_files) == 2


def test_export_ics_files_alice_file_exists(tmp_path, sample_schedule, sample_inputs):
    export_ics_files(sample_schedule, sample_inputs, tmp_path)
    assert (tmp_path / "alice.ics").exists()


def test_export_ics_files_carol_file_exists(tmp_path, sample_schedule, sample_inputs):
    export_ics_files(sample_schedule, sample_inputs, tmp_path)
    assert (tmp_path / "carol.ics").exists()


def test_export_ics_files_alice_has_correct_event_count(tmp_path, sample_schedule, sample_inputs):
    export_ics_files(sample_schedule, sample_inputs, tmp_path)
    cal = icalendar.Calendar.from_ical((tmp_path / "alice.ics").read_bytes())
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 3  # Alice has 3 assignments


def test_export_ics_files_carol_has_correct_event_count(tmp_path, sample_schedule, sample_inputs):
    export_ics_files(sample_schedule, sample_inputs, tmp_path)
    cal = icalendar.Calendar.from_ical((tmp_path / "carol.ics").read_bytes())
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 1  # Carol has 1 assignment


def test_export_ics_files_creates_output_dir_if_missing(tmp_path, sample_schedule, sample_inputs):
    output_dir = tmp_path / "new_subdir"
    export_ics_files(sample_schedule, sample_inputs, output_dir)
    assert output_dir.exists()


# ---------------------------------------------------------------------------
# export_excel
# ---------------------------------------------------------------------------

def test_export_excel_creates_file(tmp_path, sample_schedule, sample_inputs):
    export_excel(sample_schedule, sample_inputs, tmp_path)
    assert (tmp_path / "schedule_overview.xlsx").exists()


def test_export_excel_has_schedule_overview_sheet(tmp_path, sample_schedule, sample_inputs):
    export_excel(sample_schedule, sample_inputs, tmp_path)
    wb = openpyxl.load_workbook(tmp_path / "schedule_overview.xlsx")
    assert "Schedule Overview" in wb.sheetnames


def test_export_excel_has_legend_sheet(tmp_path, sample_schedule, sample_inputs):
    export_excel(sample_schedule, sample_inputs, tmp_path)
    wb = openpyxl.load_workbook(tmp_path / "schedule_overview.xlsx")
    assert "Legend" in wb.sheetnames


def test_export_excel_creates_output_dir_if_missing(tmp_path, sample_schedule, sample_inputs):
    output_dir = tmp_path / "new_subdir"
    export_excel(sample_schedule, sample_inputs, output_dir)
    assert output_dir.exists()
