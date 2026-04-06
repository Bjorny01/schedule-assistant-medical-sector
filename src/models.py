"""
Data models for the Medical Staff Rostering System.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class ShiftType(str, Enum):
    DAY = "day"        # 07:00–15:00
    EVENING = "evening"  # 15:00–23:00
    NIGHT = "night"    # 23:00–07:00


SHIFT_LIST = [ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT]
SHIFT_IDX: dict[ShiftType, int] = {s: i for i, s in enumerate(SHIFT_LIST)}

SHIFT_START_HOUR = {
    ShiftType.DAY: 7,
    ShiftType.EVENING: 15,
    ShiftType.NIGHT: 23,
}
SHIFT_END_HOUR = {
    ShiftType.DAY: 15,
    ShiftType.EVENING: 23,
    ShiftType.NIGHT: 7,  # next calendar day
}


class Role(str, Enum):
    NURSE = "nurse"
    DOCTOR = "doctor"


@dataclass
class StaffPreferences:
    """Soft preferences — the solver maximises compliance but cannot guarantee them."""
    preferred_shifts: list[ShiftType] = field(default_factory=list)
    avoid_shifts: list[ShiftType] = field(default_factory=list)
    preferred_days_off: list[int] = field(default_factory=list)  # 0=Monday … 6=Sunday
    max_night_shifts_per_week: int = 3
    max_consecutive_working_days: int = 5
    prefer_consecutive_days_off: bool = False  # cluster rest days together


@dataclass
class StaffConstraints:
    """
    Hard and soft constraints for one staff member.

    Tier 3 hard  → mandatory_days_off, recurring_days_off, allowed_shifts
    Tier 3 soft  → preferences
    """
    # Hard personal needs
    mandatory_days_off: list[date] = field(default_factory=list)
    recurring_days_off: list[int] = field(default_factory=list)   # 0=Mon … 6=Sun
    allowed_shifts: Optional[list[ShiftType]] = None               # None = all allowed
    max_weekly_shifts: int = 5                                     # from contract

    # Soft preferences
    preferences: StaffPreferences = field(default_factory=StaffPreferences)


@dataclass
class Staff:
    name: str
    role: Role
    contract_pct: float  # 1.0 = 100 %, 0.8 = 80 %, etc.
    constraints: StaffConstraints

    @property
    def target_shifts_per_week(self) -> float:
        return 5.0 * self.contract_pct

    @property
    def max_shifts_per_week(self) -> int:
        return self.constraints.max_weekly_shifts


@dataclass
class ShiftAssignment:
    staff_name: str
    date: date
    shift_type: ShiftType

    def __repr__(self) -> str:
        return f"<{self.staff_name} | {self.date} | {self.shift_type.value}>"


@dataclass
class Schedule:
    assignments: list[ShiftAssignment]
    start_date: date
    num_weeks: int
    infeasible_preferences: list[str] = field(default_factory=list)
    solver_status: str = "unknown"
    objective_value: Optional[float] = None

    def get_staff_assignments(self, staff_name: str) -> list[ShiftAssignment]:
        return sorted(
            [a for a in self.assignments if a.staff_name == staff_name],
            key=lambda a: a.date,
        )

    def get_day_assignments(self, day: date) -> list[ShiftAssignment]:
        return [a for a in self.assignments if a.date == day]

    def total_shifts_for(self, staff_name: str) -> int:
        return len(self.get_staff_assignments(staff_name))


@dataclass
class DepartmentRequirements:
    department_name: str = "Medical Department"

    # Weekday minimums (hard)
    min_nurses_day: int = 3
    min_nurses_evening: int = 2
    min_nurses_night: int = 2
    min_doctors_day: int = 1
    min_doctors_evening: int = 0
    min_doctors_night: int = 0

    # Weekend minimums (hard)
    min_nurses_weekend_day: int = 2
    min_nurses_weekend_evening: int = 2
    min_nurses_weekend_night: int = 1
    min_doctors_weekend_day: int = 1
    min_doctors_weekend_evening: int = 0
    min_doctors_weekend_night: int = 0

    # Public holidays: use weekend minimums (listed in department_requirements.txt)
    public_holidays: list[date] = field(default_factory=list)


@dataclass
class WorkLawRules:
    """
    Hard scheduling rules derived from Swedish Arbetstidslagen (1982:673)
    and Arbetsmiljöverket regulations.  See swedish_work_law.txt for references.
    """
    # Section 1 — daily hours
    shift_duration_hours: int = 8
    min_daily_rest_hours: int = 11     # HC-02, HC-03, HC-04

    # Section 2 — weekly hours
    max_shifts_per_week: int = 5       # HC-05  (5 × 8 h = 40 h)
    max_consecutive_work_days: int = 5  # HC-06

    # Section 3 — overtime (informational, not enforced by solver in v1)
    max_overtime_per_month_hours: int = 50
    max_overtime_per_year_hours: int = 200

    # Section 4 — night work
    max_night_shifts_per_4weeks: int = 8   # HC-07
    night_start_hour: int = 22
    night_end_hour: int = 6


@dataclass
class ParsedInputs:
    staff: list[Staff]
    dept_requirements: DepartmentRequirements
    law_rules: WorkLawRules
