"""Tests for src/config_parser.py

LLM-dependent functions (_parse_with_llm, the LLM branch of parse_all_inputs)
are intentionally skipped — they require an Anthropic API key.
"""
from datetime import date

import pytest

from src.config_parser import (
    _build_parsed_inputs,
    _dept_from_dict,
    _extract_kv,
    _parse_allowed_shifts,
    _parse_contract_pct,
    _parse_dates,
    _parse_dates_with_shifts,
    _parse_department_file,
    _parse_int,
    _parse_shift_list,
    _parse_staff_file,
    _parse_weekdays,
    _parse_weekdays_with_shifts,
    _parse_with_fallback,
    _read_all_files,
    _staff_from_dict,
    parse_all_inputs,
)
from src.models import Role, ShiftType


# ---------------------------------------------------------------------------
# _extract_kv
# ---------------------------------------------------------------------------

def test_extract_kv_basic():
    kv = _extract_kv("Name: Alice\nRole: nurse")
    assert kv["name"] == "Alice"
    assert kv["role"] == "nurse"


def test_extract_kv_keys_lowercased():
    kv = _extract_kv("Max Shifts Per Week: 5")
    assert "max shifts per week" in kv


def test_extract_kv_first_occurrence_wins():
    kv = _extract_kv("Name: Alice\nName: Bob")
    assert kv["name"] == "Alice"


def test_extract_kv_ignores_comment_lines():
    kv = _extract_kv("# comment\nName: Alice")
    assert list(kv.keys()) == ["name"]


def test_extract_kv_ignores_plain_sentences():
    kv = _extract_kv("just a sentence\nName: Alice")
    assert list(kv.keys()) == ["name"]


def test_extract_kv_strips_value_whitespace():
    kv = _extract_kv("Name:   Alice   ")
    assert kv["name"] == "Alice"


# ---------------------------------------------------------------------------
# _parse_contract_pct
# ---------------------------------------------------------------------------

def test_parse_contract_pct_100():
    assert _parse_contract_pct("100%") == pytest.approx(1.0)


def test_parse_contract_pct_80():
    assert _parse_contract_pct("80%") == pytest.approx(0.8)


def test_parse_contract_pct_float_string():
    assert _parse_contract_pct("0.75") == pytest.approx(0.75)


def test_parse_contract_pct_invalid_defaults_to_1():
    assert _parse_contract_pct("full time") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _parse_int
# ---------------------------------------------------------------------------

def test_parse_int_plain_number():
    assert _parse_int("5") == 5


def test_parse_int_embedded_in_phrase():
    assert _parse_int("max 3 shifts") == 3


def test_parse_int_empty_returns_default():
    assert _parse_int("", default=7) == 7


def test_parse_int_no_digit_returns_default():
    assert _parse_int("none", default=2) == 2


# ---------------------------------------------------------------------------
# _parse_dates
# ---------------------------------------------------------------------------

def test_parse_dates_single():
    assert _parse_dates("2024-03-15") == [date(2024, 3, 15)]


def test_parse_dates_multiple():
    result = _parse_dates("2024-03-15, 2024-03-22")
    assert result == [date(2024, 3, 15), date(2024, 3, 22)]


def test_parse_dates_none_found():
    assert _parse_dates("no dates here") == []


def test_parse_dates_empty_string():
    assert _parse_dates("") == []


# ---------------------------------------------------------------------------
# _parse_weekdays
# ---------------------------------------------------------------------------

def test_parse_weekdays_full_names():
    result = _parse_weekdays("Monday, Friday")
    assert 0 in result  # Monday
    assert 4 in result  # Friday


def test_parse_weekdays_abbreviations():
    result = _parse_weekdays("sat, sun")
    assert 5 in result
    assert 6 in result


def test_parse_weekdays_empty():
    assert _parse_weekdays("") == []


def test_parse_weekdays_no_duplicates():
    result = _parse_weekdays("monday, Monday, mon")
    assert result.count(0) == 1


# ---------------------------------------------------------------------------
# _parse_allowed_shifts
# ---------------------------------------------------------------------------

def test_parse_allowed_shifts_all_returns_none():
    assert _parse_allowed_shifts("all") is None


def test_parse_allowed_shifts_empty_returns_none():
    assert _parse_allowed_shifts("") is None


def test_parse_allowed_shifts_day_and_evening():
    result = _parse_allowed_shifts("day, evening")
    assert ShiftType.DAY in result
    assert ShiftType.EVENING in result
    assert ShiftType.NIGHT not in result


def test_parse_allowed_shifts_night_only():
    result = _parse_allowed_shifts("night")
    assert result == [ShiftType.NIGHT]


# ---------------------------------------------------------------------------
# _parse_shift_list
# ---------------------------------------------------------------------------

def test_parse_shift_list_single():
    assert _parse_shift_list("day") == [ShiftType.DAY]


def test_parse_shift_list_multiple():
    result = _parse_shift_list("day, night")
    assert ShiftType.DAY in result
    assert ShiftType.NIGHT in result
    assert ShiftType.EVENING not in result


def test_parse_shift_list_empty():
    assert _parse_shift_list("") == []


# ---------------------------------------------------------------------------
# _parse_staff_file
# ---------------------------------------------------------------------------

_ALICE_TXT = """\
Name: Alice
Role: nurse
Contract: 100%
Max shifts per week: 5
Preferred shifts: day
Avoid shifts: night
"""

_CAROL_TXT = """\
Name: Carol
Role: doctor
Contract: 100%
Max shifts per week: 5
Allowed shifts: day, evening
"""

_BOB_TXT = """\
Name: Bob
Role: nurse
Contract: 80%
Max shifts per week: 4
Mandatory days off: 2024-03-15, 2024-03-22
Recurring unavailability: Saturday, Sunday
"""


def test_parse_staff_file_name():
    staff = _parse_staff_file(_ALICE_TXT, date(2024, 1, 1))
    assert staff.name == "Alice"


def test_parse_staff_file_nurse_role():
    staff = _parse_staff_file(_ALICE_TXT, date(2024, 1, 1))
    assert staff.role == Role.NURSE


def test_parse_staff_file_doctor_role():
    staff = _parse_staff_file(_CAROL_TXT, date(2024, 1, 1))
    assert staff.role == Role.DOCTOR


def test_parse_staff_file_contract_pct():
    staff = _parse_staff_file(_BOB_TXT, date(2024, 1, 1))
    assert staff.contract_pct == pytest.approx(0.8)


def test_parse_staff_file_preferred_shifts():
    staff = _parse_staff_file(_ALICE_TXT, date(2024, 1, 1))
    assert ShiftType.DAY in staff.constraints.preferences.preferred_shifts


def test_parse_staff_file_avoid_shifts():
    staff = _parse_staff_file(_ALICE_TXT, date(2024, 1, 1))
    assert ShiftType.NIGHT in staff.constraints.preferences.avoid_shifts


def test_parse_staff_file_allowed_shifts():
    staff = _parse_staff_file(_CAROL_TXT, date(2024, 1, 1))
    assert staff.constraints.allowed_shifts == [ShiftType.DAY, ShiftType.EVENING]


def test_parse_staff_file_mandatory_days_off():
    staff = _parse_staff_file(_BOB_TXT, date(2024, 1, 1))
    assert date(2024, 3, 15) in staff.constraints.mandatory_days_off
    assert date(2024, 3, 22) in staff.constraints.mandatory_days_off


def test_parse_staff_file_recurring_days_off():
    staff = _parse_staff_file(_BOB_TXT, date(2024, 1, 1))
    assert 5 in staff.constraints.recurring_days_off  # Saturday
    assert 6 in staff.constraints.recurring_days_off  # Sunday


def test_parse_staff_file_no_name_returns_none():
    assert _parse_staff_file("Role: nurse\nContract: 100%", date(2024, 1, 1)) is None


# ---------------------------------------------------------------------------
# _parse_department_file
# ---------------------------------------------------------------------------

_DEPT_TXT = """\
Department: Test Ward
Min nurses day: 2
Min nurses evening: 1
Min nurses night: 1
Min doctors day: 1
Min doctors evening: 0
Min doctors night: 0
Min nurses weekend day: 1
Min nurses weekend evening: 1
Min nurses weekend night: 0
Min doctors weekend day: 0
Min doctors weekend evening: 0
Min doctors weekend night: 0
Public holidays: 2024-01-01, 2024-12-25
"""


def test_parse_department_file_name():
    dept = _parse_department_file(_DEPT_TXT)
    assert dept.department_name == "Test Ward"


def test_parse_department_file_weekday_nurse_mins():
    dept = _parse_department_file(_DEPT_TXT)
    assert dept.min_nurses_day == 2
    assert dept.min_nurses_evening == 1
    assert dept.min_nurses_night == 1


def test_parse_department_file_weekday_doctor_mins():
    dept = _parse_department_file(_DEPT_TXT)
    assert dept.min_doctors_day == 1
    assert dept.min_doctors_evening == 0


def test_parse_department_file_weekend_mins():
    dept = _parse_department_file(_DEPT_TXT)
    assert dept.min_nurses_weekend_day == 1
    assert dept.min_doctors_weekend_day == 0


def test_parse_department_file_holidays():
    dept = _parse_department_file(_DEPT_TXT)
    assert date(2024, 1, 1) in dept.public_holidays
    assert date(2024, 12, 25) in dept.public_holidays


def test_parse_department_file_empty_uses_defaults():
    dept = _parse_department_file("")
    assert dept.department_name == "Medical Department"
    assert dept.min_nurses_day == 2


# ---------------------------------------------------------------------------
# _staff_from_dict
# ---------------------------------------------------------------------------

def test_staff_from_dict_nurse():
    staff = _staff_from_dict({"name": "Alice", "role": "nurse", "contract_pct": 1.0})
    assert staff.name == "Alice"
    assert staff.role == Role.NURSE


def test_staff_from_dict_doctor():
    staff = _staff_from_dict({"name": "Carol", "role": "doctor", "contract_pct": 1.0})
    assert staff.role == Role.DOCTOR


def test_staff_from_dict_contract_pct():
    staff = _staff_from_dict({"name": "Bob", "role": "nurse", "contract_pct": 0.8})
    assert staff.contract_pct == pytest.approx(0.8)


def test_staff_from_dict_mandatory_days_off():
    staff = _staff_from_dict({
        "name": "Bob", "role": "nurse", "contract_pct": 0.8,
        "mandatory_days_off": ["2024-03-15"],
    })
    assert date(2024, 3, 15) in staff.constraints.mandatory_days_off


def test_staff_from_dict_allowed_shifts_none():
    staff = _staff_from_dict({"name": "Alice", "role": "nurse", "contract_pct": 1.0, "allowed_shifts": None})
    assert staff.constraints.allowed_shifts is None


def test_staff_from_dict_allowed_shifts_subset():
    staff = _staff_from_dict({
        "name": "Carol", "role": "doctor", "contract_pct": 1.0,
        "allowed_shifts": ["day", "evening"],
    })
    assert staff.constraints.allowed_shifts == [ShiftType.DAY, ShiftType.EVENING]


def test_staff_from_dict_preferred_shifts():
    staff = _staff_from_dict({
        "name": "Alice", "role": "nurse", "contract_pct": 1.0,
        "preferred_shifts": ["day"],
    })
    assert ShiftType.DAY in staff.constraints.preferences.preferred_shifts


# ---------------------------------------------------------------------------
# _dept_from_dict
# ---------------------------------------------------------------------------

def test_dept_from_dict_name():
    dept = _dept_from_dict({"department_name": "Test Ward"})
    assert dept.department_name == "Test Ward"


def test_dept_from_dict_nurse_mins():
    dept = _dept_from_dict({"min_nurses_day": 2, "min_nurses_evening": 1})
    assert dept.min_nurses_day == 2
    assert dept.min_nurses_evening == 1


def test_dept_from_dict_holidays():
    dept = _dept_from_dict({"public_holidays": ["2024-01-01", "2024-12-25"]})
    assert date(2024, 1, 1) in dept.public_holidays
    assert date(2024, 12, 25) in dept.public_holidays


def test_dept_from_dict_empty_uses_defaults():
    dept = _dept_from_dict({})
    assert dept.department_name == "Medical Department"
    assert dept.min_nurses_day == 3


# ---------------------------------------------------------------------------
# _build_parsed_inputs
# ---------------------------------------------------------------------------

def test_build_parsed_inputs_staff_count():
    data = {
        "staff": [
            {"name": "Alice", "role": "nurse", "contract_pct": 1.0},
            {"name": "Carol", "role": "doctor", "contract_pct": 1.0},
        ],
        "department": {"department_name": "Test Ward"},
    }
    result = _build_parsed_inputs(data, date(2024, 1, 1))
    assert len(result.staff) == 2


def test_build_parsed_inputs_department_name():
    data = {
        "staff": [],
        "department": {"department_name": "Test Ward"},
    }
    result = _build_parsed_inputs(data, date(2024, 1, 1))
    assert result.dept_requirements.department_name == "Test Ward"


def test_build_parsed_inputs_law_rules_present():
    data = {"staff": [], "department": {}}
    result = _build_parsed_inputs(data, date(2024, 1, 1))
    assert result.law_rules is not None


# ---------------------------------------------------------------------------
# _read_all_files  (uses fixture files via conftest.py)
# ---------------------------------------------------------------------------

def test_read_all_files_has_department_key(staff_configs_dir, dept_req_file, law_file):
    texts = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    assert "department" in texts


def test_read_all_files_has_law_key(staff_configs_dir, dept_req_file, law_file):
    texts = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    assert "law" in texts


def test_read_all_files_has_staff_keys(staff_configs_dir, dept_req_file, law_file):
    texts = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    staff_keys = [k for k in texts if k.startswith("staff:")]
    assert len(staff_keys) == 3  # alice, bob, carol


def test_read_all_files_staff_content_nonempty(staff_configs_dir, dept_req_file, law_file):
    texts = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    for key, text in texts.items():
        if key.startswith("staff:"):
            assert len(text) > 0


# ---------------------------------------------------------------------------
# _parse_with_fallback / parse_all_inputs (end-to-end, no LLM)
# ---------------------------------------------------------------------------

def test_parse_with_fallback_staff_count(staff_configs_dir, dept_req_file, law_file):
    raw = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    result = _parse_with_fallback(raw, date(2024, 1, 1))
    assert len(result.staff) == 3


def test_parse_with_fallback_has_nurse_and_doctor(staff_configs_dir, dept_req_file, law_file):
    raw = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    result = _parse_with_fallback(raw, date(2024, 1, 1))
    roles = {s.role for s in result.staff}
    assert Role.NURSE in roles
    assert Role.DOCTOR in roles


def test_parse_with_fallback_department_name(staff_configs_dir, dept_req_file, law_file):
    raw = _read_all_files(staff_configs_dir, dept_req_file, law_file)
    result = _parse_with_fallback(raw, date(2024, 1, 1))
    assert result.dept_requirements.department_name == "Test Ward"


def test_parse_all_inputs_no_llm(staff_configs_dir, dept_req_file, law_file):
    result = parse_all_inputs(
        staff_configs_dir, dept_req_file, law_file,
        start_date=date(2024, 1, 1),
        use_llm=False,
    )
    assert len(result.staff) == 3
    assert result.dept_requirements is not None
    assert result.law_rules is not None


# ---------------------------------------------------------------------------
# _parse_dates_with_shifts  (shift-level off syntax)
# ---------------------------------------------------------------------------

def test_parse_dates_with_shifts_bare_date_is_whole_day():
    whole, shifts = _parse_dates_with_shifts("2024-03-15")
    assert whole == [date(2024, 3, 15)]
    assert shifts == []


def test_parse_dates_with_shifts_single_shift():
    whole, shifts = _parse_dates_with_shifts("2024-03-15 (night)")
    assert whole == []
    assert shifts == [(date(2024, 3, 15), ShiftType.NIGHT)]


def test_parse_dates_with_shifts_multiple_shifts_same_date():
    whole, shifts = _parse_dates_with_shifts("2024-05-01 (evening, night)")
    assert whole == []
    assert (date(2024, 5, 1), ShiftType.EVENING) in shifts
    assert (date(2024, 5, 1), ShiftType.NIGHT) in shifts
    assert len(shifts) == 2


def test_parse_dates_with_shifts_mixed_bare_and_annotated():
    whole, shifts = _parse_dates_with_shifts(
        "2024-04-24, 2024-05-01 (evening, night), 2024-05-02"
    )
    assert date(2024, 4, 24) in whole
    assert date(2024, 5, 2) in whole
    assert (date(2024, 5, 1), ShiftType.EVENING) in shifts
    assert (date(2024, 5, 1), ShiftType.NIGHT) in shifts


def test_parse_dates_with_shifts_empty_parens_treated_as_whole_day():
    whole, shifts = _parse_dates_with_shifts("2024-03-15 ()")
    assert whole == [date(2024, 3, 15)]
    assert shifts == []


def test_parse_dates_with_shifts_empty_input():
    whole, shifts = _parse_dates_with_shifts("")
    assert whole == []
    assert shifts == []


# ---------------------------------------------------------------------------
# _parse_weekdays_with_shifts
# ---------------------------------------------------------------------------

def test_parse_weekdays_with_shifts_bare_weekday_is_whole_day():
    whole, shifts = _parse_weekdays_with_shifts("Sunday")
    assert whole == [6]
    assert shifts == []


def test_parse_weekdays_with_shifts_single_shift():
    whole, shifts = _parse_weekdays_with_shifts("Friday (evening)")
    assert whole == []
    assert shifts == [(4, ShiftType.EVENING)]


def test_parse_weekdays_with_shifts_multiple_shifts_same_weekday():
    whole, shifts = _parse_weekdays_with_shifts("Saturday (day, evening)")
    assert whole == []
    assert (5, ShiftType.DAY) in shifts
    assert (5, ShiftType.EVENING) in shifts


def test_parse_weekdays_with_shifts_mixed_bare_and_annotated():
    whole, shifts = _parse_weekdays_with_shifts("Monday, Saturday (day)")
    assert whole == [0]
    assert shifts == [(5, ShiftType.DAY)]


def test_parse_weekdays_with_shifts_deduplicates():
    whole, shifts = _parse_weekdays_with_shifts("Monday, Monday")
    assert whole == [0]


def test_parse_weekdays_with_shifts_empty_input():
    whole, shifts = _parse_weekdays_with_shifts("")
    assert whole == []
    assert shifts == []


# ---------------------------------------------------------------------------
# _parse_staff_file — shift-level off fields (fallback path)
# ---------------------------------------------------------------------------

_SHIFT_OFF_TXT = """\
Name: Dana
Role: nurse
Contract: 100%
Max shifts per week: 5
Mandatory days off: 2024-04-08 (night), 2024-04-22
Recurring unavailability: Sunday, Friday (evening)
Preferred days off: Monday, Saturday (day)
"""


def test_parse_staff_file_mandatory_shift_off_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert (date(2024, 4, 8), ShiftType.NIGHT) in staff.constraints.mandatory_shifts_off


def test_parse_staff_file_mandatory_whole_day_still_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert date(2024, 4, 22) in staff.constraints.mandatory_days_off


def test_parse_staff_file_recurring_shift_off_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert (4, ShiftType.EVENING) in staff.constraints.recurring_shifts_off  # Friday evening


def test_parse_staff_file_recurring_whole_day_still_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert 6 in staff.constraints.recurring_days_off  # Sunday


def test_parse_staff_file_preferred_shift_off_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert (5, ShiftType.DAY) in staff.constraints.preferences.preferred_shifts_off


def test_parse_staff_file_preferred_whole_day_still_extracted():
    staff = _parse_staff_file(_SHIFT_OFF_TXT, date(2024, 1, 1))
    assert 0 in staff.constraints.preferences.preferred_days_off  # Monday


# ---------------------------------------------------------------------------
# _staff_from_dict — shift-level off fields (LLM JSON path)
# ---------------------------------------------------------------------------

def test_staff_from_dict_mandatory_shifts_off():
    staff = _staff_from_dict({
        "name": "Dana", "role": "nurse", "contract_pct": 1.0,
        "mandatory_shifts_off": [
            {"date": "2024-04-08", "shifts": ["night"]},
        ],
    })
    assert (date(2024, 4, 8), ShiftType.NIGHT) in staff.constraints.mandatory_shifts_off


def test_staff_from_dict_mandatory_shifts_off_multiple_shifts_per_date():
    staff = _staff_from_dict({
        "name": "Dana", "role": "nurse", "contract_pct": 1.0,
        "mandatory_shifts_off": [
            {"date": "2024-05-01", "shifts": ["evening", "night"]},
        ],
    })
    pairs = staff.constraints.mandatory_shifts_off
    assert (date(2024, 5, 1), ShiftType.EVENING) in pairs
    assert (date(2024, 5, 1), ShiftType.NIGHT) in pairs


def test_staff_from_dict_recurring_shifts_off():
    staff = _staff_from_dict({
        "name": "Dana", "role": "nurse", "contract_pct": 1.0,
        "recurring_shifts_off": [{"weekday": 4, "shifts": ["evening"]}],
    })
    assert (4, ShiftType.EVENING) in staff.constraints.recurring_shifts_off


def test_staff_from_dict_preferred_shifts_off():
    staff = _staff_from_dict({
        "name": "Dana", "role": "nurse", "contract_pct": 1.0,
        "preferred_shifts_off": [{"weekday": 5, "shifts": ["day"]}],
    })
    assert (5, ShiftType.DAY) in staff.constraints.preferences.preferred_shifts_off


def test_staff_from_dict_shift_off_fields_default_empty():
    staff = _staff_from_dict({"name": "Dana", "role": "nurse", "contract_pct": 1.0})
    assert staff.constraints.mandatory_shifts_off == []
    assert staff.constraints.recurring_shifts_off == []
    assert staff.constraints.preferences.preferred_shifts_off == []
