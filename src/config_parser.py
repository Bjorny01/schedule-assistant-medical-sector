"""
Input parsing layer for the Medical Staff Rostering System.

Two modes:
  LLM mode   — sends all config files to Claude, receives structured JSON.
  Fallback   — simple key-value text parser (no API key required).

The LLM mode is more robust for natural-language fields (e.g. "every other
Tuesday", "weeks 3-4").  The fallback handles well-structured config files
that follow the template exactly.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import (
    DepartmentRequirements,
    ParsedInputs,
    Role,
    ShiftType,
    Staff,
    StaffConstraints,
    StaffPreferences,
    WorkLawRules,
)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_all_inputs(
    staff_config_dir: Path,
    dept_req_file: Path,
    law_file: Path,
    start_date: date,
    use_llm: bool = True,
    manual_llm: bool = False,
    output_dir: Path | None = None,
) -> ParsedInputs:
    """
    Read all input files and return a ParsedInputs object.

    Falls back to the built-in text parser if the LLM call fails or
    use_llm is False.
    """
    raw_texts = _read_all_files(staff_config_dir, dept_req_file, law_file)

    if manual_llm:
        return _parse_with_manual_llm(raw_texts, start_date, output_dir or Path("output"))

    if use_llm:
        try:
            return _parse_with_llm(raw_texts, start_date)
        except Exception as exc:
            print(f"[config_parser] LLM parse failed ({exc}), falling back to text parser.")

    return _parse_with_fallback(raw_texts, start_date)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_all_files(
    staff_config_dir: Path,
    dept_req_file: Path,
    law_file: Path,
) -> dict[str, str]:
    texts: dict[str, str] = {}

    for path in sorted(staff_config_dir.glob("*.txt")):
        texts[f"staff:{path.stem}"] = path.read_text(encoding="utf-8")

    texts["department"] = dept_req_file.read_text(encoding="utf-8")
    texts["law"] = law_file.read_text(encoding="utf-8")

    return texts


# ---------------------------------------------------------------------------
# LLM parsing
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a scheduling data extractor for a medical rostering system.
You will receive plain-text configuration files for a hospital department
and must return a single JSON object that captures all scheduling constraints.

Follow this exact JSON schema:

{
  "staff": [
    {
      "name": "<full name>",
      "role": "nurse" | "doctor",
      "contract_pct": <float 0.0-1.0>,
      "max_weekly_shifts": <int>,
      "mandatory_days_off": ["YYYY-MM-DD", ...],
      "recurring_days_off": [<int 0=Mon .. 6=Sun>, ...],
      "allowed_shifts": null | ["day","evening","night"],
      "preferred_shifts": ["day","evening","night"],
      "avoid_shifts": ["day","evening","night"],
      "preferred_days_off": [<int 0=Mon .. 6=Sun>, ...],
      "max_night_shifts_per_week": <int>,
      "max_consecutive_working_days": <int>,
      "prefer_consecutive_days_off": <bool>
    }
  ],
  "department": {
    "department_name": "<string>",
    "min_nurses_day": <int>,
    "min_nurses_evening": <int>,
    "min_nurses_night": <int>,
    "min_doctors_day": <int>,
    "min_doctors_evening": <int>,
    "min_doctors_night": <int>,
    "min_nurses_weekend_day": <int>,
    "min_nurses_weekend_evening": <int>,
    "min_nurses_weekend_night": <int>,
    "min_doctors_weekend_day": <int>,
    "min_doctors_weekend_evening": <int>,
    "min_doctors_weekend_night": <int>,
    "public_holidays": ["YYYY-MM-DD", ...]
  }
}

Rules:
- Output ONLY valid JSON — no markdown fences, no commentary.
- contract_pct: 100% → 1.0,  80% → 0.8,  75% → 0.75,  60% → 0.6, etc.
- allowed_shifts null means all three shift types are allowed.
- recurring_days_off uses integers: 0=Monday, 1=Tuesday, ..., 6=Sunday.
- For any date references like "every Friday", convert to recurring_days_off.
- For specific date references, output absolute ISO dates (YYYY-MM-DD).
  The schedule start date is provided in the user message.
- If a field cannot be determined, use a sensible default.
"""


def _build_user_message(raw_texts: dict[str, str], start_date: date) -> str:
    sections = [f"Schedule start date: {start_date.isoformat()}\n"]
    for key, text in raw_texts.items():
        sections.append(f"=== FILE: {key} ===\n{text}\n")
    return "\n".join(sections)


def _parse_with_manual_llm(
    raw_texts: dict[str, str], start_date: date, output_dir: Path
) -> ParsedInputs:
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = output_dir / "parser_prompt.txt"
    response_file = output_dir / "parser_response.txt"

    user_message = _build_user_message(raw_texts, start_date)

    prompt_file.write_text(
        "=== SYSTEM PROMPT ===\n\n"
        + _SYSTEM_PROMPT
        + "\n\n=== USER MESSAGE ===\n\n"
        + user_message,
        encoding="utf-8",
    )
    print(f"      Prompt written to: {prompt_file.resolve()}")
    print(f"      Paste the LLM response into: {response_file.resolve()}")
    input("      Press Enter when the response file is ready...")

    raw_json = response_file.read_text(encoding="utf-8").strip()
    raw_json = re.sub(r"^```json\s*", "", raw_json)
    raw_json = re.sub(r"```\s*$", "", raw_json)

    data = json.loads(raw_json)
    return _build_parsed_inputs(data, start_date)


def _parse_with_llm(raw_texts: dict[str, str], start_date: date) -> ParsedInputs:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    user_message = _build_user_message(raw_texts, start_date)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_json = response.content[0].text.strip()
    # Strip markdown fences if the model added them despite instructions
    raw_json = re.sub(r"^```json\s*", "", raw_json)
    raw_json = re.sub(r"```\s*$", "", raw_json)

    data = json.loads(raw_json)
    return _build_parsed_inputs(data, start_date)


# ---------------------------------------------------------------------------
# Fallback text parser
# ---------------------------------------------------------------------------

def _parse_with_fallback(raw_texts: dict[str, str], start_date: date) -> ParsedInputs:
    staff_list: list[Staff] = []

    for key, text in raw_texts.items():
        if not key.startswith("staff:"):
            continue
        staff = _parse_staff_file(text, start_date)
        if staff is not None:
            staff_list.append(staff)

    dept_req = _parse_department_file(raw_texts.get("department", ""))
    law_rules = WorkLawRules()  # use statutory defaults from models.py

    return ParsedInputs(staff=staff_list, dept_requirements=dept_req, law_rules=law_rules)


def _parse_staff_file(text: str, start_date: date) -> Staff | None:
    kv = _extract_kv(text)
    if "name" not in kv:
        return None

    name = kv["name"]
    role_raw = kv.get("role", "").lower()
    role = Role.DOCTOR if "doctor" in role_raw or "läkare" in role_raw else Role.NURSE

    contract_pct = _parse_contract_pct(kv.get("contract", kv.get("contract pct", "100%")))
    max_weekly = _parse_int(kv.get("max shifts per week", ""), default=round(5 * contract_pct))

    mandatory_off = _parse_dates(kv.get("mandatory days off", ""))
    recurring_off = _parse_weekdays(kv.get("recurring unavailability", ""))

    allowed_raw = kv.get("allowed shifts", "").lower()
    allowed_shifts = _parse_allowed_shifts(allowed_raw)

    pref_raw = kv.get("preferred shifts", "").lower()
    avoid_raw = kv.get("avoid shifts", "").lower()
    pref_days_raw = kv.get("preferred days off", "").lower()
    max_nights = _parse_int(kv.get("max night shifts per week", ""), default=3)
    max_consec = _parse_int(kv.get("max consecutive working days", ""), default=5)
    consec_off = "consecutive" in kv.get("consecutive days off", "").lower()
    #consec_off = True      # If always true consecutive days off are desired

    preferences = StaffPreferences(
        preferred_shifts=_parse_shift_list(pref_raw),
        avoid_shifts=_parse_shift_list(avoid_raw),
        preferred_days_off=_parse_weekday_list(pref_days_raw),
        max_night_shifts_per_week=max_nights,
        max_consecutive_working_days=max_consec,
        prefer_consecutive_days_off=consec_off,
    )

    constraints = StaffConstraints(
        mandatory_days_off=mandatory_off,
        recurring_days_off=recurring_off,
        allowed_shifts=allowed_shifts,
        max_weekly_shifts=max_weekly,
        preferences=preferences,
    )

    return Staff(name=name, role=role, contract_pct=contract_pct, constraints=constraints)


def _parse_department_file(text: str) -> DepartmentRequirements:
    kv = _extract_kv(text)

    def gi(key: str, default: int) -> int:
        return _parse_int(kv.get(key, ""), default=default)

    holidays = _parse_dates(kv.get("public holidays", ""))

    return DepartmentRequirements(
        department_name=kv.get("department", "Medical Department"),
        min_nurses_day=gi("min nurses day", 2),
        min_nurses_evening=gi("min nurses evening", 1),
        min_nurses_night=gi("min nurses night", 1),
        min_doctors_day=gi("min doctors day", 1),
        min_doctors_evening=gi("min doctors evening", 0),
        min_doctors_night=gi("min doctors night", 0),
        min_nurses_weekend_day=gi("min nurses weekend day", 2),
        min_nurses_weekend_evening=gi("min nurses weekend evening", 1),
        min_nurses_weekend_night=gi("min nurses weekend night", 1),
        min_doctors_weekend_day=gi("min doctors weekend day", 1),
        min_doctors_weekend_evening=gi("min doctors weekend evening", 0),
        min_doctors_weekend_night=gi("min doctors weekend night", 0),
        public_holidays=holidays,
    )


# ---------------------------------------------------------------------------
# JSON → models (shared by LLM path)
# ---------------------------------------------------------------------------

def _build_parsed_inputs(data: dict[str, Any], start_date: date) -> ParsedInputs:
    staff_list = [_staff_from_dict(s) for s in data.get("staff", [])]
    dept = _dept_from_dict(data.get("department", {}))
    law_rules = WorkLawRules()
    return ParsedInputs(staff=staff_list, dept_requirements=dept, law_rules=law_rules)


def _staff_from_dict(d: dict[str, Any]) -> Staff:
    role = Role.DOCTOR if d.get("role", "").lower() == "doctor" else Role.NURSE
    contract_pct = float(d.get("contract_pct", 1.0))
    max_weekly = int(d.get("max_weekly_shifts", round(5 * contract_pct)))

    mandatory_off = [date.fromisoformat(s) for s in d.get("mandatory_days_off", [])]
    recurring_off = [int(x) for x in d.get("recurring_days_off", [])]

    raw_allowed = d.get("allowed_shifts")
    allowed_shifts: list[ShiftType] | None = (
        [ShiftType(s) for s in raw_allowed] if raw_allowed is not None else None
    )

    preferences = StaffPreferences(
        preferred_shifts=[ShiftType(s) for s in d.get("preferred_shifts", [])],
        avoid_shifts=[ShiftType(s) for s in d.get("avoid_shifts", [])],
        preferred_days_off=[int(x) for x in d.get("preferred_days_off", [])],
        max_night_shifts_per_week=int(d.get("max_night_shifts_per_week", 3)),
        max_consecutive_working_days=int(d.get("max_consecutive_working_days", 5)),
        prefer_consecutive_days_off=bool(d.get("prefer_consecutive_days_off", False)),
    )

    constraints = StaffConstraints(
        mandatory_days_off=mandatory_off,
        recurring_days_off=recurring_off,
        allowed_shifts=allowed_shifts,
        max_weekly_shifts=max_weekly,
        preferences=preferences,
    )

    return Staff(
        name=d["name"],
        role=role,
        contract_pct=contract_pct,
        constraints=constraints,
    )


def _dept_from_dict(d: dict[str, Any]) -> DepartmentRequirements:
    holidays = [date.fromisoformat(s) for s in d.get("public_holidays", [])]
    return DepartmentRequirements(
        department_name=d.get("department_name", "Medical Department"),
        min_nurses_day=int(d.get("min_nurses_day", 3)),
        min_nurses_evening=int(d.get("min_nurses_evening", 2)),
        min_nurses_night=int(d.get("min_nurses_night", 2)),
        min_doctors_day=int(d.get("min_doctors_day", 1)),
        min_doctors_evening=int(d.get("min_doctors_evening", 0)),
        min_doctors_night=int(d.get("min_doctors_night", 0)),
        min_nurses_weekend_day=int(d.get("min_nurses_weekend_day", 2)),
        min_nurses_weekend_evening=int(d.get("min_nurses_weekend_evening", 2)),
        min_nurses_weekend_night=int(d.get("min_nurses_weekend_night", 1)),
        min_doctors_weekend_day=int(d.get("min_doctors_weekend_day", 1)),
        min_doctors_weekend_evening=int(d.get("min_doctors_weekend_evening", 0)),
        min_doctors_weekend_night=int(d.get("min_doctors_weekend_night", 0)),
        public_holidays=holidays,
    )


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

def _extract_kv(text: str) -> dict[str, str]:
    """
    Extract key-value pairs from lines of the form  'Key: value'.
    Keys are lowercased and stripped.  Values are stripped.
    Only the first occurrence of each key is kept.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z\s/()]+):\s*(.+)$", line)
        if match:
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            if key not in result:
                result[key] = value
    return result


def _parse_contract_pct(raw: str) -> float:
    match = re.search(r"(\d+)\s*%", raw)
    if match:
        return int(match.group(1)) / 100.0
    try:
        return float(raw)
    except ValueError:
        return 1.0


def _parse_int(raw: str, default: int = 0) -> int:
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else default


def _parse_dates(raw: str) -> list[date]:
    return [
        date.fromisoformat(m)
        for m in re.findall(r"\d{4}-\d{2}-\d{2}", raw)
    ]


_WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _parse_weekdays(raw: str) -> list[int]:
    found = []
    lower = raw.lower()
    for name, idx in _WEEKDAY_NAMES.items():
        if name in lower and idx not in found:
            found.append(idx)
    return found


def _parse_weekday_list(raw: str) -> list[int]:
    return _parse_weekdays(raw)


def _parse_allowed_shifts(raw: str) -> list[ShiftType] | None:
    if not raw or "all" in raw:
        return None
    shifts = []
    if "day" in raw:
        shifts.append(ShiftType.DAY)
    if "evening" in raw:
        shifts.append(ShiftType.EVENING)
    if "night" in raw:
        shifts.append(ShiftType.NIGHT)
    return shifts if shifts else None


def _parse_shift_list(raw: str) -> list[ShiftType]:
    shifts = []
    if "day" in raw:
        shifts.append(ShiftType.DAY)
    if "evening" in raw:
        shifts.append(ShiftType.EVENING)
    if "night" in raw:
        shifts.append(ShiftType.NIGHT)
    return shifts
